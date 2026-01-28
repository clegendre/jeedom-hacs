"""Switch platform for the Jeedom integration."""
from __future__ import annotations

from homeassistant.components.switch import SwitchEntity
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
    """Set up the Jeedom switch platform."""
    hub: JeedomHub = hass.data[DOMAIN][entry.entry_id]

    async_add_entities([JeedomSwitch(hub, spec) for spec in hub.get_specs(Platform.SWITCH)])

    @callback
    def _async_add_new_entities(new_specs: list[JeedomEntitySpec]) -> None:
        async_add_entities([JeedomSwitch(hub, spec) for spec in new_specs])

    async_dispatcher_connect(hass, hub.signal_new_entities(Platform.SWITCH), _async_add_new_entities)


class JeedomSwitch(JeedomEntity, SwitchEntity):
    """Representation of a Jeedom switch."""

    def __init__(self, hub: JeedomHub, spec: JeedomEntitySpec) -> None:
        super().__init__(hub, spec)
        self._attr_is_on = None
        self._attr_assumed_state = "state" not in spec.state_cmd_ids

    def _handle_cmd_update(self, cmd_id: int, value) -> None:
        if cmd_id != self._spec.state_cmd_ids.get("state"):
            return
        self._attr_is_on = _coerce_bool(value)
        self._safe_write_ha_state()

    async def async_turn_on(self, **kwargs) -> None:
        cmd_id = self._spec.action_config.get("on_cmd_id")
        if cmd_id is None:
            return
        await self._hub.api.async_exec_cmd(int(cmd_id))

    async def async_turn_off(self, **kwargs) -> None:
        cmd_id = self._spec.action_config.get("off_cmd_id")
        if cmd_id is None:
            return
        await self._hub.api.async_exec_cmd(int(cmd_id))

    def _restore_from_state(self, state) -> None:
        self._attr_is_on = state.state == STATE_ON


def _coerce_bool(value) -> bool:
    if value is None:
        return False
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value > 0
    text = str(value).strip().lower()
    if text in ("1", "true", "on", "yes", "open"):
        return True
    if text in ("0", "false", "off", "no", "closed"):
        return False
    if text.isdigit():
        return int(text) > 0
    return False
