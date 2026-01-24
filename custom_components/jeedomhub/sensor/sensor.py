"""Sensor platform for the Jeedom integration."""
from __future__ import annotations

from homeassistant.components.sensor import SensorEntity
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
    """Set up the Jeedom sensor platform."""
    hub: JeedomHub = hass.data[DOMAIN][entry.entry_id]

    async_add_entities([JeedomSensor(hub, spec) for spec in hub.get_specs(Platform.SENSOR)])

    @callback
    def _async_add_new_entities(new_specs: list[JeedomEntitySpec]) -> None:
        async_add_entities([JeedomSensor(hub, spec) for spec in new_specs])

    async_dispatcher_connect(hass, hub.signal_new_entities(Platform.SENSOR), _async_add_new_entities)


class JeedomSensor(JeedomEntity, SensorEntity):
    """Representation of a Jeedom sensor."""

    def __init__(self, hub: JeedomHub, spec: JeedomEntitySpec) -> None:
        super().__init__(hub, spec)
        cfg = spec.entity_config
        self._attr_device_class = cfg.get("device_class")
        self._attr_state_class = cfg.get("state_class")
        self._attr_native_unit_of_measurement = cfg.get("unit_of_measurement")
        self._attr_icon = cfg.get("icon")
        self._is_numeric = cfg.get("value_template") is not None or self._attr_state_class is not None
        self._attr_native_value = None

    def _handle_cmd_update(self, cmd_id: int, value) -> None:
        if cmd_id != self._spec.state_cmd_ids.get("state"):
            return
        self._attr_native_value = self._coerce_value(value)
        self._safe_write_ha_state()

    def _coerce_value(self, value):
        if value is None:
            return None
        if self._is_numeric:
            try:
                return float(value)
            except Exception:
                return None
        return value

    def _restore_from_state(self, state) -> None:
        self._attr_native_value = self._coerce_value(state.state)
