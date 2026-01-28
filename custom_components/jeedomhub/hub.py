"""Jeedom hub coordinating discovery, events, and entity registry."""
from __future__ import annotations

import asyncio
import json
import logging
import re
from pathlib import Path
from typing import Any, Dict, List, Optional

from homeassistant.components import mqtt
from homeassistant.const import Platform
from homeassistant.helpers.dispatcher import async_dispatcher_send
from homeassistant.helpers.storage import Store

from .api import JeedomApi
from .const import (
    CONF_API_KEY,
    CONF_CONFIG_PATH,
    CONF_HOST,
    CONF_JSONRPC_FALLBACK,
    CONF_JSONRPC_URL,
    CONF_PORT,
    CONF_USE_JSONRPC,
    CONF_IMPORT_MODE,
    CONF_DOMAINS,
    DOMAIN,
    IMPORT_MODE_NATIVE,
    IMPORT_MODE_MQTT,
    SUPPORTED_DOMAINS,
    MQTT_DISCOVERY_TOPIC,
    MQTT_EVENT_TOPIC,
)
from .discovery import JeedomDiscoveryEngine, load_config
from .models import JeedomEntitySpec

_LOGGER = logging.getLogger(__name__)

UID_CMD_RE = re.compile(r"^jeedom_(\d+)_(\d+)$")
UID_EQ_RE = re.compile(r"^jeedom_(\d+)")

DISCOVERY_STORE_VERSION = 1

PLATFORM_BY_KEY = {
    "sensor": Platform.SENSOR,
    "binary_sensor": Platform.BINARY_SENSOR,
    "alarm_control_panel": Platform.ALARM_CONTROL_PANEL,
    "climate": Platform.CLIMATE,
    "light": Platform.LIGHT,
    "switch": Platform.SWITCH,
    "cover": Platform.COVER,
    "number": Platform.NUMBER,
    "select": Platform.SELECT,
    "water_heater": Platform.WATER_HEATER,
}

ACTION_KEY_BY_PLATFORM = {
    Platform.ALARM_CONTROL_PANEL: "alarm_control_panel",
    Platform.SWITCH: "switch",
    Platform.LIGHT: "light",
    Platform.COVER: "cover",
    Platform.NUMBER: "number",
    Platform.SELECT: "select",
    Platform.CLIMATE: "climate",
    Platform.WATER_HEATER: "water_heater",
}



class JeedomHub:
    """Hub handling Jeedom discovery, event routing, and API calls."""

    def __init__(self, hass, entry) -> None:
        self.hass = hass
        self.entry = entry
        self.api = self._build_api()
        self._unsub_mqtt: List[callable] = []
        self._entity_specs: Dict[Platform, Dict[str, JeedomEntitySpec]] = {
            platform: {} for platform in PLATFORM_BY_KEY.values()
        }
        self._actions: Dict[str, Any] = {}
        self._lock = asyncio.Lock()
        self._store = Store(hass, DISCOVERY_STORE_VERSION, f"{DOMAIN}.{entry.entry_id}.discovery")
        self._save_task: Optional[asyncio.Task] = None

        config_path = entry.options.get(CONF_CONFIG_PATH) or entry.data.get(CONF_CONFIG_PATH)
        path_obj = Path(config_path) if config_path else None
        config = load_config(path_obj)
        self._discovery = JeedomDiscoveryEngine(config)
        if config_path:
            _LOGGER.debug(
                "Loaded Jeedom config from %s (devices=%s, include_all_if_no_filter=%s)",
                config_path,
                len(config.devices),
                config.include_all_if_no_filter,
            )
        self._import_mode = entry.options.get(CONF_IMPORT_MODE) or entry.data.get(
            CONF_IMPORT_MODE, IMPORT_MODE_NATIVE
        )
        self._allowed_domains = set(
            entry.options.get(CONF_DOMAINS)
            or entry.data.get(CONF_DOMAINS)
            or SUPPORTED_DOMAINS
        )

        if self._import_mode not in (IMPORT_MODE_NATIVE, IMPORT_MODE_MQTT):
            self._import_mode = IMPORT_MODE_NATIVE

    def _build_api(self) -> JeedomApi:
        host = self.entry.data.get(CONF_HOST)
        port = self.entry.data.get(CONF_PORT)
        api_key = self.entry.data.get(CONF_API_KEY)
        jsonrpc_url = self.entry.options.get(CONF_JSONRPC_URL) or self.entry.data.get(CONF_JSONRPC_URL)
        use_jsonrpc = self.entry.options.get(CONF_USE_JSONRPC)
        jsonrpc_fallback = self.entry.options.get(CONF_JSONRPC_FALLBACK)

        if use_jsonrpc is None:
            use_jsonrpc = True
        if jsonrpc_fallback is None:
            jsonrpc_fallback = True

        if host and "://" in host:
            base_url = host
        else:
            base_url = f"http://{host}:{port}" if port else f"http://{host}"

        return JeedomApi(
            self.hass,
            base_url=base_url,
            api_key=api_key,
            jsonrpc_url=jsonrpc_url,
            use_jsonrpc=bool(use_jsonrpc),
            jsonrpc_fallback=bool(jsonrpc_fallback),
        )

    async def async_setup(self) -> None:
        _LOGGER.debug("Setting up Jeedom hub")
        if self.is_native_mode:
            await self._restore_discovery()
            self._unsub_mqtt.append(
                await mqtt.async_subscribe(
                    self.hass, MQTT_DISCOVERY_TOPIC, self._handle_discovery_message
                )
            )
            self._unsub_mqtt.append(
                await mqtt.async_subscribe(
                    self.hass, MQTT_EVENT_TOPIC, self._handle_event_message
                )
            )
        else:
            _LOGGER.info(
                "Jeedom integration running in MQTT entities mode; no entities will be created."
            )

    async def async_unload(self) -> None:
        for unsub in self._unsub_mqtt:
            unsub()
        self._unsub_mqtt.clear()
        if self._save_task and not self._save_task.done():
            self._save_task.cancel()
            self._save_task = None
        await self._flush_store()

    def signal_new_entities(self, platform: Platform) -> str:
        return f"{DOMAIN}_{self.entry.entry_id}_{platform.value}_new"

    def signal_cmd(self, cmd_id: int) -> str:
        return f"{DOMAIN}_{self.entry.entry_id}_cmd_{cmd_id}"

    def get_specs(self, platform: Platform) -> List[JeedomEntitySpec]:
        if not self.is_native_mode:
            return []
        return list(self._entity_specs.get(platform, {}).values())

    @property
    def is_native_mode(self) -> bool:
        return self._import_mode == IMPORT_MODE_NATIVE

    async def _handle_discovery_message(self, msg) -> None:
        raw = msg.payload if isinstance(msg.payload, str) else msg.payload.decode("utf-8", errors="ignore")
        raw = raw.strip() if raw else ""
        if not raw:
            return
        try:
            data = json.loads(raw)
        except Exception:
            _LOGGER.debug("Jeedom discovery JSON parse failed for topic %s", msg.topic)
            return

        async with self._lock:
            self._discovery.update_eqlogic(data)
            entity_doc, actions = await self.hass.async_add_executor_job(self._discovery.generate)
            self._apply_updates(entity_doc, actions)
            self._schedule_store_save()

    async def _handle_event_message(self, msg) -> None:
        topic = msg.topic or ""
        if not topic.startswith("jeedom/cmd/event/"):
            return
        try:
            cmd_id = int(topic.split("/")[-1])
        except Exception:
            return
        raw = msg.payload if isinstance(msg.payload, str) else msg.payload.decode("utf-8", errors="ignore")
        raw = raw.strip() if raw else ""
        if not raw:
            return
        try:
            data = json.loads(raw)
        except Exception:
            return
        value = data.get("value")
        if value is None:
            return

        async_dispatcher_send(self.hass, self.signal_cmd(cmd_id), cmd_id, value)

    def _apply_updates(self, entity_doc: Dict[str, List[Dict[str, Any]]], actions: Dict[str, Any]) -> None:
        self._actions = actions
        _LOGGER.debug(
            "Generated entities: %s",
            {key: len(items) for key, items in entity_doc.items()},
        )
        for key, items in entity_doc.items():
            if self._allowed_domains and key not in self._allowed_domains:
                continue
            platform = PLATFORM_BY_KEY.get(key)
            if platform is None:
                continue
            known = self._entity_specs.setdefault(platform, {})
            new_specs: List[JeedomEntitySpec] = []
            for item in items:
                spec = self._build_spec(platform, item, actions)
                if spec is None:
                    continue
                existing = known.get(spec.unique_id)
                if existing:
                    existing.entity_config = spec.entity_config
                    existing.action_config = spec.action_config
                    existing.state_cmd_ids = spec.state_cmd_ids
                    existing.device_info = spec.device_info
                    existing.name = spec.name
                else:
                    known[spec.unique_id] = spec
                    new_specs.append(spec)
            if new_specs:
                async_dispatcher_send(self.hass, self.signal_new_entities(platform), new_specs)

    def _build_spec(
        self, platform: Platform, item: Dict[str, Any], actions: Dict[str, Any]
    ) -> Optional[JeedomEntitySpec]:
        unique_id = item.get("unique_id")
        if not unique_id:
            return None

        device_info = self._device_info_from_item(item)
        name = item.get("name") or unique_id

        cmd_match = UID_CMD_RE.match(unique_id)
        eq_match = UID_EQ_RE.match(unique_id)
        eq_id = int(eq_match.group(1)) if eq_match else None

        device_key = f"jeedom_{eq_id}" if eq_id is not None else None

        is_pilot = platform == Platform.CLIMATE and unique_id.endswith("_pilot_climate")
        action_key = ACTION_KEY_BY_PLATFORM.get(platform)
        if is_pilot:
            action_key = "pilot_climate"
        action_config = actions.get(action_key, {}).get(device_key, {}) if action_key else {}

        state_cmd_ids: Dict[str, int] = {}

        if platform in (Platform.SENSOR, Platform.BINARY_SENSOR):
            cmd_id = item.get("_cmd_id")
            if cmd_id is not None:
                state_cmd_ids["state"] = int(cmd_id)
            elif cmd_match:
                state_cmd_ids["state"] = int(cmd_match.group(2))
            else:
                return None
        else:
            if not action_config:
                return None

        if platform == Platform.SWITCH:
            if action_config.get("state_cmd_id") is not None:
                state_cmd_ids["state"] = int(action_config["state_cmd_id"])
        elif platform == Platform.LIGHT:
            if action_config.get("state_cmd_id") is not None:
                state_cmd_ids["state"] = int(action_config["state_cmd_id"])
            if action_config.get("brightness_state_cmd_id") is not None:
                state_cmd_ids["brightness"] = int(action_config["brightness_state_cmd_id"])
            for channel in ("red", "green", "blue", "white"):
                key = f"{channel}_state_cmd_id"
                if action_config.get(key) is not None:
                    state_cmd_ids[channel] = int(action_config[key])
        elif platform == Platform.COVER:
            if action_config.get("position_state_cmd_id") is not None:
                state_cmd_ids["position"] = int(action_config["position_state_cmd_id"])
        elif platform == Platform.NUMBER:
            if action_config.get("state_cmd_id") is not None:
                state_cmd_ids["state"] = int(action_config["state_cmd_id"])
        elif platform == Platform.SELECT:
            if action_config.get("state_cmd_id") is not None:
                state_cmd_ids["state"] = int(action_config["state_cmd_id"])
        elif platform == Platform.ALARM_CONTROL_PANEL:
            if action_config.get("state_cmd_id") is not None:
                state_cmd_ids["state"] = int(action_config["state_cmd_id"])
        elif platform == Platform.CLIMATE:
            if is_pilot:
                if action_config.get("state_cmd_id") is not None:
                    state_cmd_ids["state"] = int(action_config["state_cmd_id"])
                if item.get("_current_temperature_cmd_id") is not None:
                    state_cmd_ids["current_temperature"] = int(item["_current_temperature_cmd_id"])
            else:
                if action_config.get("current_temperature_cmd_id") is not None:
                    state_cmd_ids["current_temperature"] = int(action_config["current_temperature_cmd_id"])
                if action_config.get("temperature_state_cmd_id") is not None:
                    state_cmd_ids["target_temperature"] = int(action_config["temperature_state_cmd_id"])
                for kind in ("hot", "auto", "cold"):
                    key = f"temperature_state_cmd_id_{kind}"
                    if action_config.get(key) is not None:
                        state_cmd_ids[f"target_temperature_{kind}"] = int(action_config[key])
        elif platform == Platform.WATER_HEATER:
            if action_config.get("state_cmd_id") is not None:
                state_cmd_ids["state"] = int(action_config["state_cmd_id"])

        return JeedomEntitySpec(
            platform=platform,
            unique_id=unique_id,
            name=name,
            device_info=device_info,
            entity_config=item,
            action_config=action_config,
            state_cmd_ids=state_cmd_ids,
            device_key=device_key,
            is_pilot_climate=is_pilot,
        )

    def _device_info_from_item(self, item: Dict[str, Any]) -> Dict[str, Any]:
        device = item.get("device") or {}
        identifiers = device.get("identifiers") or []
        info: Dict[str, Any] = {}
        if identifiers:
            info["identifiers"] = {(DOMAIN, str(ident)) for ident in identifiers}
        if device.get("name"):
            info["name"] = device["name"]
        if device.get("manufacturer"):
            info["manufacturer"] = device["manufacturer"]
        if device.get("model"):
            info["model"] = device["model"]
        return info

    async def _restore_discovery(self) -> None:
        stored = await self._store.async_load()
        if not stored:
            return
        eqlogic_store = stored.get("eqlogic_store")
        if not isinstance(eqlogic_store, dict):
            return
        restored = 0
        for eqlogic in eqlogic_store.values():
            if isinstance(eqlogic, dict):
                self._discovery.update_eqlogic(eqlogic)
                restored += 1
        if not restored:
            return
        entity_doc, actions = await self.hass.async_add_executor_job(self._discovery.generate)
        self._apply_updates(entity_doc, actions)
        _LOGGER.debug("Restored Jeedom discovery cache (%s devices)", restored)

    def _schedule_store_save(self) -> None:
        if self._save_task and not self._save_task.done():
            return
        self._save_task = self.hass.async_create_task(self._async_save_store_delayed())

    async def _async_save_store_delayed(self) -> None:
        try:
            await asyncio.sleep(2)
            await self._flush_store()
        finally:
            self._save_task = None

    async def _flush_store(self) -> None:
        if not self.is_native_mode:
            return
        payload = {"eqlogic_store": {str(k): v for k, v in self._discovery.eqlogic_store.items()}}
        await self._store.async_save(payload)


__all__ = ["JeedomHub"]
