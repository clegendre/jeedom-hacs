"""Water heater platform for the Jeedom integration."""
from __future__ import annotations

from homeassistant.components.water_heater import (
    WaterHeaterEntity,
    WaterHeaterEntityFeature,
)
from homeassistant.const import UnitOfTemperature
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
    """Set up the Jeedom water heater platform."""
    hub: JeedomHub = hass.data[DOMAIN][entry.entry_id]

    async_add_entities([JeedomWaterHeater(hub, spec) for spec in hub.get_specs(Platform.WATER_HEATER)])

    @callback
    def _async_add_new_entities(new_specs: list[JeedomEntitySpec]) -> None:
        async_add_entities([JeedomWaterHeater(hub, spec) for spec in new_specs])

    async_dispatcher_connect(
        hass, hub.signal_new_entities(Platform.WATER_HEATER), _async_add_new_entities
    )


class JeedomWaterHeater(JeedomEntity, WaterHeaterEntity):
    """Representation of a Jeedom water heater."""

    def __init__(self, hub: JeedomHub, spec: JeedomEntitySpec) -> None:
        super().__init__(hub, spec)
        self._attr_temperature_unit = UnitOfTemperature.CELSIUS
        modes = [str(m).strip() for m in (spec.entity_config.get("modes") or []) if str(m).strip()]
        if not modes:
            modes = ["off", "heat"]
        if "off" not in modes:
            modes = ["off"] + [m for m in modes if m != "off"]

        self._attr_operation_list = modes
        self._attr_current_operation = None
        self._attr_supported_features = WaterHeaterEntityFeature.OPERATION_MODE
        self._on_mode = _water_heater_on_mode(modes)

    def _handle_cmd_update(self, cmd_id: int, value) -> None:
        if cmd_id != self._spec.state_cmd_ids.get("state"):
            return
        self._attr_current_operation = _coerce_operation(value, self._on_mode)
        self._safe_write_ha_state()

    async def async_set_operation_mode(self, operation_mode: str) -> None:
        if operation_mode == "off":
            cmd_id = self._spec.action_config.get("off_cmd_id")
        else:
            cmd_id = self._spec.action_config.get("on_cmd_id")
        if cmd_id is None:
            return
        await self._hub.api.async_exec_cmd(int(cmd_id))

    def _restore_from_state(self, state) -> None:
        operation = state.attributes.get("operation_mode") or state.state
        if operation in (self._attr_operation_list or []):
            self._attr_current_operation = operation


def _water_heater_on_mode(modes: list[str]) -> str:
    if "heat" in modes:
        return "heat"
    for mode in modes:
        if mode != "off":
            return mode
    return "on"


def _coerce_operation(value, on_mode: str) -> str:
    if value is None:
        return "off"
    if isinstance(value, (int, float)):
        return on_mode if float(value) > 0 else "off"
    text = str(value).strip().lower()
    if text in ("on", "heat", "eco", "boost", "1", "true"):
        return on_mode
    if text.isdigit() and int(text) > 0:
        return on_mode
    return "off"
