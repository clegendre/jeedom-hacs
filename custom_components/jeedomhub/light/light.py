"""Light platform for the Jeedom integration."""
from __future__ import annotations

from homeassistant.components.light import LightEntity, ColorMode
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

JEEDOM_BRIGHTNESS_MAX = 99


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the Jeedom light platform."""
    hub: JeedomHub = hass.data[DOMAIN][entry.entry_id]

    async_add_entities([JeedomLight(hub, spec) for spec in hub.get_specs(Platform.LIGHT)])

    @callback
    def _async_add_new_entities(new_specs: list[JeedomEntitySpec]) -> None:
        async_add_entities([JeedomLight(hub, spec) for spec in new_specs])

    async_dispatcher_connect(hass, hub.signal_new_entities(Platform.LIGHT), _async_add_new_entities)


class JeedomLight(JeedomEntity, LightEntity):
    """Representation of a Jeedom light."""

    def __init__(self, hub: JeedomHub, spec: JeedomEntitySpec) -> None:
        super().__init__(hub, spec)
        self._attr_is_on = None
        self._attr_brightness = None
        self._last_brightness = None

        self._has_brightness = bool(self._spec.action_config.get("brightness_cmd_id"))
        if self._has_brightness:
            self._attr_supported_color_modes = {ColorMode.BRIGHTNESS}
            self._attr_color_mode = ColorMode.BRIGHTNESS
        else:
            self._attr_supported_color_modes = {ColorMode.ONOFF}
            self._attr_color_mode = ColorMode.ONOFF

    def _handle_cmd_update(self, cmd_id: int, value) -> None:
        if cmd_id == self._spec.state_cmd_ids.get("state"):
            self._attr_is_on = _coerce_bool(value)
        if cmd_id == self._spec.state_cmd_ids.get("brightness"):
            brightness = _jeedom_to_ha_brightness(value)
            if brightness is not None:
                self._attr_brightness = brightness
                self._last_brightness = brightness
                self._attr_is_on = brightness > 0
        self._safe_write_ha_state()

    async def async_turn_on(self, **kwargs) -> None:
        brightness = kwargs.get("brightness")
        if brightness is not None and self._has_brightness:
            await self._async_set_brightness(brightness)
            return

        cmd_id = self._spec.action_config.get("on_cmd_id")
        if cmd_id is not None:
            await self._hub.api.async_exec_cmd(int(cmd_id))
            return

        if self._has_brightness:
            fallback = self._last_brightness
            if fallback is None:
                fallback = _jeedom_to_ha_brightness(self._spec.action_config.get("default_on_brightness", JEEDOM_BRIGHTNESS_MAX))
            await self._async_set_brightness(fallback or 0)

    async def async_turn_off(self, **kwargs) -> None:
        cmd_id = self._spec.action_config.get("off_cmd_id")
        if cmd_id is not None:
            await self._hub.api.async_exec_cmd(int(cmd_id))
            return
        if self._has_brightness:
            await self._async_set_brightness(0)

    async def _async_set_brightness(self, brightness: int) -> None:
        cmd_id = self._spec.action_config.get("brightness_cmd_id")
        if cmd_id is None:
            return
        value = _ha_to_jeedom_brightness(brightness)
        self._last_brightness = brightness
        await self._hub.api.async_exec_cmd(int(cmd_id), value=str(value), options={"slider": str(value)})

    @property
    def brightness(self) -> int | None:
        return self._attr_brightness

    def _restore_from_state(self, state) -> None:
        self._attr_is_on = state.state == STATE_ON
        brightness = state.attributes.get("brightness")
        if brightness is not None:
            try:
                self._attr_brightness = int(brightness)
                self._last_brightness = self._attr_brightness
            except Exception:
                pass


def _coerce_bool(value) -> bool:
    if value is None:
        return False
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value > 0
    text = str(value).strip().lower()
    if text in ("1", "true", "on", "yes"):
        return True
    if text in ("0", "false", "off", "no"):
        return False
    if text.isdigit():
        return int(text) > 0
    return False


def _ha_to_jeedom_brightness(value) -> int:
    try:
        v = int(value)
    except Exception:
        v = 0
    v = max(0, min(255, v))
    return int(round(v * JEEDOM_BRIGHTNESS_MAX / 255))


def _jeedom_to_ha_brightness(value) -> int | None:
    try:
        v = float(value)
    except Exception:
        return None
    v = max(0, min(JEEDOM_BRIGHTNESS_MAX, v))
    return int(round(v * 255 / JEEDOM_BRIGHTNESS_MAX))
