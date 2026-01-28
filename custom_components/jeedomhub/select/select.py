"""Select platform for the Jeedom integration."""
from __future__ import annotations

from homeassistant.components.select import SelectEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.const import Platform
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

PILOT_WIRE_VALUES = {0, 20, 30, 40, 50, 99, 255}


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the Jeedom select platform."""
    hub: JeedomHub = hass.data[DOMAIN][entry.entry_id]

    async_add_entities([JeedomSelect(hub, spec) for spec in hub.get_specs(Platform.SELECT)])

    @callback
    def _async_add_new_entities(new_specs: list[JeedomEntitySpec]) -> None:
        async_add_entities([JeedomSelect(hub, spec) for spec in new_specs])

    async_dispatcher_connect(hass, hub.signal_new_entities(Platform.SELECT), _async_add_new_entities)


class JeedomSelect(JeedomEntity, SelectEntity):
    """Representation of a Jeedom select."""

    def __init__(self, hub: JeedomHub, spec: JeedomEntitySpec) -> None:
        super().__init__(hub, spec)
        self._options = list(spec.entity_config.get("options") or [])
        self._attr_options = self._options
        self._attr_current_option = None

        self._option_by_value = {}
        values = []
        for label, payload in (spec.action_config.get("options") or {}).items():
            val = payload.get("value")
            if val is None:
                continue
            try:
                v = int(float(val))
            except Exception:
                continue
            self._option_by_value[v] = label
            values.append(v)
        self._is_pilot_wire = any(v in PILOT_WIRE_VALUES for v in values)

    def _handle_cmd_update(self, cmd_id: int, value) -> None:
        if cmd_id != self._spec.state_cmd_ids.get("state"):
            return
        option = self._value_to_option(value)
        if option is not None:
            self._attr_current_option = option
            self._safe_write_ha_state()

    async def async_select_option(self, option: str) -> None:
        payload = (self._spec.action_config.get("options") or {}).get(option)
        if not payload:
            return
        cmd_id = payload.get("cmd_id")
        if cmd_id is None:
            return
        value = payload.get("value")
        await self._hub.api.async_exec_cmd(int(cmd_id), value=value)

    def _value_to_option(self, value) -> str | None:
        try:
            v = int(float(value))
        except Exception:
            return None
        if v in self._option_by_value:
            return self._option_by_value[v]
        if self._is_pilot_wire:
            return _pilot_wire_label(v, self._option_by_value)
        return None

    def _restore_from_state(self, state) -> None:
        if state.state in self._attr_options:
            self._attr_current_option = state.state


def _pilot_wire_label(value: int, label_by_value: dict[int, str]) -> str | None:
    def pick(values: tuple[int, ...], fallback: str) -> str:
        for v in values:
            if v in label_by_value:
                return label_by_value[v]
        return fallback

    if value <= PILOT_WIRE_THRESHOLD_OFF:
        return pick((0, 10), "Off")
    if value <= PILOT_WIRE_THRESHOLD_FROST:
        return pick((20,), "Away")
    if value <= PILOT_WIRE_THRESHOLD_ECO:
        return pick((30,), "Eco")
    if value <= PILOT_WIRE_THRESHOLD_COMFORT_2:
        return pick((40,), "Comfort -2")
    if value <= PILOT_WIRE_THRESHOLD_COMFORT_1:
        return pick((50,), "Comfort -1")
    return pick((255, 99, 100), "Comfort")
