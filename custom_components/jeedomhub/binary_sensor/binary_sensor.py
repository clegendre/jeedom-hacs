"""Binary sensor platform for the Jeedom integration."""
from __future__ import annotations

from homeassistant.components.binary_sensor import BinarySensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.const import Platform
from homeassistant.const import STATE_ON
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
    """Set up the Jeedom binary sensor platform."""
    hub: JeedomHub = hass.data[DOMAIN][entry.entry_id]

    async_add_entities([JeedomBinarySensor(hub, spec) for spec in hub.get_specs(Platform.BINARY_SENSOR)])

    @callback
    def _async_add_new_entities(new_specs: list[JeedomEntitySpec]) -> None:
        async_add_entities([JeedomBinarySensor(hub, spec) for spec in new_specs])

    async_dispatcher_connect(hass, hub.signal_new_entities(Platform.BINARY_SENSOR), _async_add_new_entities)


class JeedomBinarySensor(JeedomEntity, BinarySensorEntity):
    """Representation of a Jeedom binary sensor."""

    def __init__(self, hub: JeedomHub, spec: JeedomEntitySpec) -> None:
        super().__init__(hub, spec)
        cfg = spec.entity_config
        self._attr_device_class = cfg.get("device_class")
        self._attr_icon = cfg.get("icon")
        self._payload_on = str(cfg.get("payload_on", "1")).strip().lower()
        self._payload_off = str(cfg.get("payload_off", "0")).strip().lower()
        self._attr_is_on = None

    def _handle_cmd_update(self, cmd_id: int, value) -> None:
        if cmd_id != self._spec.state_cmd_ids.get("state"):
            return
        self._attr_is_on = self._coerce_state(value)
        self._safe_write_ha_state()

    def _coerce_state(self, value):
        if value is None:
            return None
        if isinstance(value, bool):
            return value
        if isinstance(value, (int, float)):
            return value > 0
        text = str(value).strip().lower()
        if text == self._payload_on:
            return True
        if text == self._payload_off:
            return False
        if text.isdigit():
            return int(text) > 0
        return False

    def _restore_from_state(self, state) -> None:
        self._attr_is_on = state.state == STATE_ON
