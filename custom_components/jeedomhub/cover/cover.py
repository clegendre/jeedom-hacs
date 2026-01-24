"""Cover platform for the Jeedom integration."""
from __future__ import annotations

from homeassistant.components.cover import CoverEntity, CoverEntityFeature
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.const import Platform
from homeassistant.const import STATE_CLOSED, STATE_OPEN
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
    """Set up the Jeedom cover platform."""
    hub: JeedomHub = hass.data[DOMAIN][entry.entry_id]

    async_add_entities([JeedomCover(hub, spec) for spec in hub.get_specs(Platform.COVER)])

    @callback
    def _async_add_new_entities(new_specs: list[JeedomEntitySpec]) -> None:
        async_add_entities([JeedomCover(hub, spec) for spec in new_specs])

    async_dispatcher_connect(hass, hub.signal_new_entities(Platform.COVER), _async_add_new_entities)


class JeedomCover(JeedomEntity, CoverEntity):
    """Representation of a Jeedom cover."""

    def __init__(self, hub: JeedomHub, spec: JeedomEntitySpec) -> None:
        super().__init__(hub, spec)
        self._attr_current_cover_position = None
        self._attr_is_closed = None

        features = CoverEntityFeature.OPEN | CoverEntityFeature.CLOSE
        if self._spec.action_config.get("stop_cmd_id") is not None:
            features |= CoverEntityFeature.STOP
        if self._spec.action_config.get("set_position_cmd_id") is not None:
            features |= CoverEntityFeature.SET_POSITION
        self._attr_supported_features = features

    def _handle_cmd_update(self, cmd_id: int, value) -> None:
        if cmd_id != self._spec.state_cmd_ids.get("position"):
            return
        position = _device_to_percent(value, self._spec.action_config)
        self._attr_current_cover_position = position
        if position is None:
            self._attr_is_closed = None
        else:
            self._attr_is_closed = position <= 0
        self._safe_write_ha_state()

    async def async_open_cover(self, **kwargs) -> None:
        cmd_id = self._spec.action_config.get("open_cmd_id")
        if cmd_id is None:
            return
        value = self._spec.action_config.get("open_cmd_value")
        await self._hub.api.async_exec_cmd(int(cmd_id), value=value)

    async def async_close_cover(self, **kwargs) -> None:
        cmd_id = self._spec.action_config.get("close_cmd_id")
        if cmd_id is None:
            return
        value = self._spec.action_config.get("close_cmd_value")
        await self._hub.api.async_exec_cmd(int(cmd_id), value=value)

    async def async_stop_cover(self, **kwargs) -> None:
        cmd_id = self._spec.action_config.get("stop_cmd_id")
        if cmd_id is None:
            return
        value = self._spec.action_config.get("stop_cmd_value")
        await self._hub.api.async_exec_cmd(int(cmd_id), value=value)

    async def async_set_cover_position(self, **kwargs) -> None:
        position = kwargs.get("position")
        if position is None:
            return
        cmd_id = self._spec.action_config.get("set_position_cmd_id")
        if cmd_id is None:
            return
        value = _percent_to_device(position, self._spec.action_config)
        await self._hub.api.async_exec_cmd(int(cmd_id), value=str(value), options={"slider": str(value)})

    def _restore_from_state(self, state) -> None:
        position = state.attributes.get("current_position")
        if position is not None:
            try:
                position = int(position)
            except Exception:
                position = None
        self._attr_current_cover_position = position
        if position is None:
            if state.state == STATE_CLOSED:
                self._attr_is_closed = True
            elif state.state == STATE_OPEN:
                self._attr_is_closed = False
            else:
                self._attr_is_closed = None
        else:
            self._attr_is_closed = position <= 0


def _percent_to_device(percent, config: dict) -> str:
    try:
        v = float(percent)
    except Exception:
        v = 0.0
    min_v = config.get("set_position_min")
    max_v = config.get("set_position_max")
    prop = str(config.get("set_position_property") or "").strip().lower()

    if min_v is not None and max_v is not None:
        try:
            min_f = float(min_v)
            max_f = float(max_v)
            v = min_f + (v / 100.0) * (max_f - min_f)
            v = max(min_f, min(max_f, v))
        except Exception:
            pass
    elif prop == "targetvalue":
        v = max(0.0, min(99.0, (v / 100.0) * 99.0)) if v <= 100 else max(0.0, min(99.0, v))
    else:
        v = max(0.0, min(100.0, v))

    return str(int(round(v)))


def _device_to_percent(value, config: dict) -> int | None:
    try:
        v = float(value)
    except Exception:
        return None
    min_v = config.get("set_position_min")
    max_v = config.get("set_position_max")
    prop = str(config.get("set_position_property") or "").strip().lower()

    if min_v is not None and max_v is not None:
        try:
            min_f = float(min_v)
            max_f = float(max_v)
            if max_f == min_f:
                return int(round(v))
            pct = (v - min_f) * 100.0 / (max_f - min_f)
            return int(round(max(0.0, min(100.0, pct))))
        except Exception:
            return None
    if prop == "targetvalue":
        pct = (v * 100.0 / 99.0) if v <= 99 else 100.0
        return int(round(max(0.0, min(100.0, pct))))
    return int(round(max(0.0, min(100.0, v))))
