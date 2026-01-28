"""Number platform for the Jeedom integration."""
from __future__ import annotations

from homeassistant.components.number import NumberEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.const import Platform
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.dispatcher import async_dispatcher_connect

from ..const import DOMAIN
from ..entity import JeedomEntity
from ..hub import JeedomHub
from ..models import JeedomEntitySpec

DEFAULT_MIN = 0.0
DEFAULT_MAX = 100.0
DEFAULT_STEP = 1.0


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the Jeedom number platform."""
    hub: JeedomHub = hass.data[DOMAIN][entry.entry_id]

    async_add_entities([JeedomNumber(hub, spec) for spec in hub.get_specs(Platform.NUMBER)])

    @callback
    def _async_add_new_entities(new_specs: list[JeedomEntitySpec]) -> None:
        async_add_entities([JeedomNumber(hub, spec) for spec in new_specs])

    async_dispatcher_connect(hass, hub.signal_new_entities(Platform.NUMBER), _async_add_new_entities)


class JeedomNumber(JeedomEntity, NumberEntity):
    """Representation of a Jeedom number."""

    def __init__(self, hub: JeedomHub, spec: JeedomEntitySpec) -> None:
        super().__init__(hub, spec)
        self._attr_native_min_value = DEFAULT_MIN
        self._attr_native_max_value = DEFAULT_MAX
        self._attr_native_step = DEFAULT_STEP
        self._attr_native_value = None

    def _handle_cmd_update(self, cmd_id: int, value) -> None:
        if cmd_id != self._spec.state_cmd_ids.get("state"):
            return
        try:
            self._attr_native_value = float(value)
        except Exception:
            self._attr_native_value = None
        self._safe_write_ha_state()

    async def async_set_native_value(self, value: float) -> None:
        cmd_id = self._spec.action_config.get("set_cmd_id")
        if cmd_id is None:
            return
        await self._hub.api.async_exec_cmd(int(cmd_id), value=str(value), options={"slider": str(value)})

    def _restore_from_state(self, state) -> None:
        try:
            self._attr_native_value = float(state.state)
        except Exception:
            self._attr_native_value = None
