"""Alarm control panel platform for the Jeedom integration."""
from __future__ import annotations

from homeassistant.components.alarm_control_panel import (
    AlarmControlPanelEntity,
    AlarmControlPanelEntityFeature,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.const import Platform
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.dispatcher import async_dispatcher_connect

from ..const import DOMAIN
from ..entity import JeedomEntity
from ..hub import JeedomHub
from ..models import JeedomEntitySpec


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the Jeedom alarm control panel platform."""
    hub: JeedomHub = hass.data[DOMAIN][entry.entry_id]

    async_add_entities(
        [JeedomAlarmControlPanel(hub, spec) for spec in hub.get_specs(Platform.ALARM_CONTROL_PANEL)]
    )

    @callback
    def _async_add_new_entities(new_specs: list[JeedomEntitySpec]) -> None:
        async_add_entities([JeedomAlarmControlPanel(hub, spec) for spec in new_specs])

    async_dispatcher_connect(
        hass, hub.signal_new_entities(Platform.ALARM_CONTROL_PANEL), _async_add_new_entities
    )


class JeedomAlarmControlPanel(JeedomEntity, AlarmControlPanelEntity):
    """Representation of a Jeedom alarm control panel."""

    def __init__(self, hub: JeedomHub, spec: JeedomEntitySpec) -> None:
        super().__init__(hub, spec)
        cfg = spec.entity_config
        state_map = cfg.get("state_map") or {}
        self._state_map = {
            str(key).strip().lower(): str(value).strip().lower()
            for key, value in state_map.items()
            if key is not None and value is not None
        }
        self._attr_alarm_state = None
        self._attr_supported_features = _compute_features(spec.action_config)

    def _handle_cmd_update(self, cmd_id: int, value) -> None:
        if cmd_id != self._spec.state_cmd_ids.get("state"):
            return
        self._attr_alarm_state = _map_alarm_state(value, self._state_map)
        self._safe_write_ha_state()

    async def async_alarm_arm_home(self, **kwargs) -> None:
        cmd_id = self._spec.action_config.get("arm_home_cmd_id")
        if cmd_id is None:
            return
        await self._hub.api.async_exec_cmd(int(cmd_id))

    async def async_alarm_arm_away(self, **kwargs) -> None:
        cmd_id = self._spec.action_config.get("arm_away_cmd_id")
        if cmd_id is None:
            return
        await self._hub.api.async_exec_cmd(int(cmd_id))

    async def async_alarm_arm_night(self, **kwargs) -> None:
        cmd_id = self._spec.action_config.get("arm_night_cmd_id")
        if cmd_id is None:
            return
        await self._hub.api.async_exec_cmd(int(cmd_id))

    async def async_alarm_disarm(self, **kwargs) -> None:
        cmd_id = self._spec.action_config.get("disarm_cmd_id")
        if cmd_id is None:
            return
        await self._hub.api.async_exec_cmd(int(cmd_id))

    def _restore_from_state(self, state) -> None:
        self._attr_alarm_state = state.state


def _compute_features(action_config: dict) -> AlarmControlPanelEntityFeature:
    features = AlarmControlPanelEntityFeature(0)
    if action_config.get("arm_home_cmd_id") is not None:
        features |= AlarmControlPanelEntityFeature.ARM_HOME
    if action_config.get("arm_away_cmd_id") is not None:
        features |= AlarmControlPanelEntityFeature.ARM_AWAY
    if action_config.get("arm_night_cmd_id") is not None:
        features |= AlarmControlPanelEntityFeature.ARM_NIGHT
    if action_config.get("disarm_cmd_id") is not None:
        features |= AlarmControlPanelEntityFeature.DISARM
    return features


def _normalize_state_value(value) -> str | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return "1" if value else "0"
    if isinstance(value, (int, float)):
        if float(value).is_integer():
            return str(int(value))
        return str(value)
    return str(value).strip().lower()


def _map_alarm_state(value, state_map: dict[str, str]) -> str | None:
    key = _normalize_state_value(value)
    if key is None:
        return None
    if key in state_map:
        return state_map[key]

    if key in (
        "disarmed",
        "armed_home",
        "armed_away",
        "armed_night",
        "armed_vacation",
        "armed_custom_bypass",
        "arming",
        "pending",
        "triggered",
    ):
        return key

    if key in ("home", "arm_home", "armed_home"):
        return "armed_home"
    if key in ("away", "arm_away", "armed_away"):
        return "armed_away"
    if key in ("disarm", "off", "false"):
        return "disarmed"

    if key.isdigit():
        return "armed_away" if int(key) > 0 else "disarmed"

    return None
