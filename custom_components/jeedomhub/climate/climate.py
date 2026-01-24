"""Climate platform for the Jeedom integration."""
from __future__ import annotations

from homeassistant.components.climate import ClimateEntity, ClimateEntityFeature
from homeassistant.components.climate.const import HVACMode
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.const import Platform
from homeassistant.const import UnitOfTemperature
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.dispatcher import async_dispatcher_connect

from ..const import DOMAIN
from ..discovery import (
    PILOT_WIRE_THRESHOLD_OFF,
    PILOT_WIRE_THRESHOLD_FROST,
    PILOT_WIRE_THRESHOLD_ECO,
    PILOT_WIRE_THRESHOLD_COMFORT_2,
    PILOT_WIRE_THRESHOLD_COMFORT_1,
)
from ..entity import JeedomEntity
from ..hub import JeedomHub
from ..models import JeedomEntitySpec


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the Jeedom climate platform."""
    hub: JeedomHub = hass.data[DOMAIN][entry.entry_id]

    entities = []
    for spec in hub.get_specs(Platform.CLIMATE):
        if spec.is_pilot_climate:
            entities.append(JeedomPilotClimate(hub, spec))
        else:
            entities.append(JeedomThermostat(hub, spec))

    async_add_entities(entities)

    @callback
    def _async_add_new_entities(new_specs: list[JeedomEntitySpec]) -> None:
        new_entities = []
        for spec in new_specs:
            if spec.is_pilot_climate:
                new_entities.append(JeedomPilotClimate(hub, spec))
            else:
                new_entities.append(JeedomThermostat(hub, spec))
        async_add_entities(new_entities)

    async_dispatcher_connect(hass, hub.signal_new_entities(Platform.CLIMATE), _async_add_new_entities)


class JeedomThermostat(JeedomEntity, ClimateEntity):
    """Representation of a Jeedom thermostat (setpoint-based)."""

    def __init__(self, hub: JeedomHub, spec: JeedomEntitySpec) -> None:
        super().__init__(hub, spec)
        cfg = spec.entity_config
        self._attr_temperature_unit = UnitOfTemperature.CELSIUS
        self._attr_hvac_modes = [HVACMode.HEAT]
        if "off" in (cfg.get("modes") or []):
            self._attr_hvac_modes.append(HVACMode.OFF)
        self._attr_hvac_mode = HVACMode.HEAT
        self._attr_supported_features = ClimateEntityFeature.TARGET_TEMPERATURE
        self._attr_min_temp = cfg.get("min_temp", 5)
        self._attr_max_temp = cfg.get("max_temp", 30)
        self._attr_target_temperature_step = cfg.get("temp_step", 0.5)
        self._attr_current_temperature = None
        self._attr_target_temperature = None

    def _handle_cmd_update(self, cmd_id: int, value) -> None:
        if cmd_id == self._spec.state_cmd_ids.get("current_temperature"):
            self._attr_current_temperature = _coerce_float(value)
        if cmd_id == self._spec.state_cmd_ids.get("target_temperature"):
            self._attr_target_temperature = _coerce_float(value)
        for key, state_cmd_id in self._spec.state_cmd_ids.items():
            if not key.startswith("target_temperature_"):
                continue
            if cmd_id == state_cmd_id:
                self._attr_target_temperature = _coerce_float(value)
        self._safe_write_ha_state()

    async def async_set_temperature(self, **kwargs) -> None:
        temperature = kwargs.get("temperature")
        if temperature is None:
            return
        cmd_id = self._select_setpoint_cmd_id()
        if cmd_id is None:
            return
        await self._hub.api.async_exec_cmd(int(cmd_id), value=str(temperature), options={"slider": str(temperature)})

    def _select_setpoint_cmd_id(self) -> int | None:
        cfg = self._spec.action_config
        pref = cfg.get("setpoint_kind")
        if pref and cfg.get(f"set_temperature_cmd_id_{pref}") is not None:
            return int(cfg.get(f"set_temperature_cmd_id_{pref}"))
        if cfg.get("set_temperature_cmd_id") is not None:
            return int(cfg.get("set_temperature_cmd_id"))
        return None

    def _restore_from_state(self, state) -> None:
        try:
            self._attr_hvac_mode = HVACMode(state.state)
        except Exception:
            pass
        temp = state.attributes.get("temperature")
        if temp is not None:
            self._attr_target_temperature = _coerce_float(temp)
        cur = state.attributes.get("current_temperature")
        if cur is not None:
            self._attr_current_temperature = _coerce_float(cur)


class JeedomPilotClimate(JeedomEntity, ClimateEntity):
    """Representation of a Jeedom pilot-wire climate entity."""

    def __init__(self, hub: JeedomHub, spec: JeedomEntitySpec) -> None:
        super().__init__(hub, spec)
        cfg = spec.entity_config
        self._attr_temperature_unit = UnitOfTemperature.CELSIUS
        self._attr_hvac_modes = [_map_hvac_mode(m) for m in (cfg.get("modes") or [])]
        if not self._attr_hvac_modes:
            self._attr_hvac_modes = [HVACMode.HEAT, HVACMode.OFF]
        self._attr_supported_features = ClimateEntityFeature.PRESET_MODE
        self._attr_preset_modes = list(cfg.get("preset_modes") or [])
        self._attr_hvac_mode = HVACMode.HEAT
        self._attr_preset_mode = None
        self._attr_current_temperature = None
        self._has_additional_modes = (
            "comfort-1" in (self._attr_preset_modes or []) and "comfort-2" in (self._attr_preset_modes or [])
        )

    def _handle_cmd_update(self, cmd_id: int, value) -> None:
        if cmd_id == self._spec.state_cmd_ids.get("current_temperature"):
            self._attr_current_temperature = _coerce_float(value)
        if cmd_id == self._spec.state_cmd_ids.get("state"):
            self._attr_hvac_mode = _pilot_mode_from_value(value)
            self._attr_preset_mode = _pilot_preset_from_value(value, self._has_additional_modes)
        self._safe_write_ha_state()

    async def async_set_hvac_mode(self, hvac_mode: HVACMode) -> None:
        mapping = (self._spec.action_config.get("mode") or {})
        key = "heat" if hvac_mode == HVACMode.HEAT else "off"
        payload = mapping.get(key)
        if not payload:
            return
        cmd_id = payload.get("cmd_id")
        if cmd_id is None:
            return
        value = payload.get("value")
        await self._hub.api.async_exec_cmd(int(cmd_id), value=value)

    async def async_set_preset_mode(self, preset_mode: str) -> None:
        mapping = (self._spec.action_config.get("preset") or {})
        payload = mapping.get(preset_mode)
        if not payload:
            return
        cmd_id = payload.get("cmd_id")
        if cmd_id is None:
            return
        value = payload.get("value")
        await self._hub.api.async_exec_cmd(int(cmd_id), value=value)

    def _restore_from_state(self, state) -> None:
        try:
            self._attr_hvac_mode = HVACMode(state.state)
        except Exception:
            pass
        preset = state.attributes.get("preset_mode")
        if preset is not None:
            self._attr_preset_mode = preset
        cur = state.attributes.get("current_temperature")
        if cur is not None:
            self._attr_current_temperature = _coerce_float(cur)


def _coerce_float(value) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except Exception:
        return None


def _map_hvac_mode(mode: str) -> HVACMode:
    return HVACMode.HEAT if mode == "heat" else HVACMode.OFF


def _pilot_mode_from_value(value) -> HVACMode:
    try:
        v = int(float(value))
    except Exception:
        v = 0
    return HVACMode.OFF if v <= PILOT_WIRE_THRESHOLD_OFF else HVACMode.HEAT


def _pilot_preset_from_value(value, additional_modes: bool) -> str:
    try:
        v = int(float(value))
    except Exception:
        v = 0
    if v <= PILOT_WIRE_THRESHOLD_OFF:
        return "none"
    if v <= PILOT_WIRE_THRESHOLD_FROST:
        return "away"
    if v <= PILOT_WIRE_THRESHOLD_ECO:
        return "eco"
    if additional_modes:
        if v <= PILOT_WIRE_THRESHOLD_COMFORT_2:
            return "comfort-2"
        if v <= PILOT_WIRE_THRESHOLD_COMFORT_1:
            return "comfort-1"
    return "comfort"
