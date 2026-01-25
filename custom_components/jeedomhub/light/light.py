"""Light platform for the Jeedom integration."""
from __future__ import annotations

from homeassistant.components.light import LightEntity, ColorMode
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.const import Platform
from homeassistant.const import STATE_ON
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.util.color import color_hs_to_RGB, color_xy_to_RGB

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
        self._attr_rgb_color = None
        self._attr_rgbw_color = None
        self._last_rgbw = None

        self._brightness_min = _coerce_int(self._spec.action_config.get("brightness_min"), 0)
        self._brightness_max = _coerce_int(self._spec.action_config.get("brightness_max"), JEEDOM_BRIGHTNESS_MAX)
        if self._brightness_max <= self._brightness_min:
            self._brightness_max = JEEDOM_BRIGHTNESS_MAX

        self._has_brightness = bool(self._spec.action_config.get("brightness_cmd_id"))
        self._channel_cmd_ids = {
            ch: int(self._spec.action_config[f"{ch}_cmd_id"])
            for ch in ("red", "green", "blue", "white")
            if self._spec.action_config.get(f"{ch}_cmd_id") is not None
        }
        self._channel_ranges = {}
        for ch in self._channel_cmd_ids:
            cmin = _coerce_int(self._spec.action_config.get(f"{ch}_min"), 0)
            cmax = _coerce_int(self._spec.action_config.get(f"{ch}_max"), JEEDOM_BRIGHTNESS_MAX)
            if cmax <= cmin:
                cmax = JEEDOM_BRIGHTNESS_MAX
            self._channel_ranges[ch] = (cmin, cmax)
        self._channel_values = {ch: None for ch in self._channel_cmd_ids}
        self._channel_state_cmd_id_to_channel = {
            cmd_id: ch
            for ch, cmd_id in self._spec.state_cmd_ids.items()
            if ch in ("red", "green", "blue", "white") and cmd_id is not None
        }

        self._has_rgb = all(ch in self._channel_cmd_ids for ch in ("red", "green", "blue"))
        self._has_white = "white" in self._channel_cmd_ids

        if self._has_rgb and self._has_white:
            self._attr_supported_color_modes = {ColorMode.RGBW}
            self._attr_color_mode = ColorMode.RGBW
        elif self._has_rgb:
            self._attr_supported_color_modes = {ColorMode.RGB}
            self._attr_color_mode = ColorMode.RGB
        elif self._has_brightness:
            self._attr_supported_color_modes = {ColorMode.BRIGHTNESS}
            self._attr_color_mode = ColorMode.BRIGHTNESS
        else:
            self._attr_supported_color_modes = {ColorMode.ONOFF}
            self._attr_color_mode = ColorMode.ONOFF

    def _handle_cmd_update(self, cmd_id: int, value) -> None:
        if cmd_id == self._spec.state_cmd_ids.get("state"):
            self._attr_is_on = _coerce_bool(value)
        if cmd_id == self._spec.state_cmd_ids.get("brightness"):
            brightness = _jeedom_to_ha_brightness(value, self._brightness_min, self._brightness_max)
            if brightness is not None:
                self._attr_brightness = brightness
                self._last_brightness = brightness
                self._attr_is_on = brightness > 0
        channel = self._channel_state_cmd_id_to_channel.get(cmd_id)
        if channel:
            chan_min, chan_max = self._channel_ranges.get(channel, (0, JEEDOM_BRIGHTNESS_MAX))
            channel_value = _jeedom_to_ha_brightness(value, chan_min, chan_max)
            if channel_value is not None:
                self._channel_values[channel] = channel_value
                self._update_color_attrs()
        self._safe_write_ha_state()

    async def async_turn_on(self, **kwargs) -> None:
        brightness = kwargs.get("brightness")
        rgbw = kwargs.get("rgbw_color")
        rgb = kwargs.get("rgb_color")
        hs = kwargs.get("hs_color")
        xy = kwargs.get("xy_color")

        if rgbw is None and rgb is None and hs is not None:
            rgb = color_hs_to_RGB(*hs)
        if rgbw is None and rgb is None and xy is not None:
            rgb = color_xy_to_RGB(*xy)

        if rgbw is None and rgb is not None and self._has_rgb:
            rgbw = _rgb_to_rgbw(rgb) if self._has_white else None

        if rgbw is not None and self._has_rgb:
            if brightness is not None and not self._has_brightness:
                rgbw = _scale_rgbw(rgbw, brightness)
            await self._async_set_rgbw(rgbw)
            if brightness is not None and self._has_brightness:
                await self._async_set_brightness(brightness)
            return

        if brightness is not None and self._has_brightness:
            await self._async_set_brightness(brightness)
            return

        cmd_id = self._spec.action_config.get("on_cmd_id")
        if cmd_id is not None:
            await self._hub.api.async_exec_cmd(int(cmd_id))
            return

        if self._has_rgb:
            fallback_rgbw = self._last_rgbw
            if fallback_rgbw is None:
                if self._has_white:
                    fallback_rgbw = (0, 0, 0, 255)
                else:
                    fallback_rgbw = (255, 255, 255)
            await self._async_set_rgbw(fallback_rgbw)
            return

        if self._has_brightness:
            fallback = self._last_brightness
            if fallback is None:
                fallback = _jeedom_to_ha_brightness(
                    self._spec.action_config.get("default_on_brightness", self._brightness_max),
                    self._brightness_min,
                    self._brightness_max,
                )
            await self._async_set_brightness(fallback or 0)

    async def async_turn_off(self, **kwargs) -> None:
        cmd_id = self._spec.action_config.get("off_cmd_id")
        if cmd_id is not None:
            await self._hub.api.async_exec_cmd(int(cmd_id))
            return
        if self._has_rgb:
            await self._async_set_rgbw((0, 0, 0, 0) if self._has_white else (0, 0, 0))
            return
        if self._has_brightness:
            await self._async_set_brightness(0)

    async def _async_set_brightness(self, brightness: int) -> None:
        cmd_id = self._spec.action_config.get("brightness_cmd_id")
        if cmd_id is None:
            return
        value = _ha_to_jeedom_brightness(brightness, self._brightness_min, self._brightness_max)
        self._last_brightness = brightness
        await self._hub.api.async_exec_cmd(int(cmd_id), value=str(value), options={"slider": str(value)})

    async def _async_set_rgbw(self, rgbw) -> None:
        if not self._has_rgb:
            return
        if len(rgbw) == 3:
            rgbw = (*rgbw, 0)
        r, g, b, w = (int(c) for c in rgbw)
        self._last_rgbw = (r, g, b, w)

        for channel, value in (("red", r), ("green", g), ("blue", b), ("white", w)):
            cmd_id = self._channel_cmd_ids.get(channel)
            if cmd_id is None:
                continue
            chan_min, chan_max = self._channel_ranges.get(channel, (0, JEEDOM_BRIGHTNESS_MAX))
            jvalue = _ha_to_jeedom_brightness(value, chan_min, chan_max)
            await self._hub.api.async_exec_cmd(int(cmd_id), value=str(jvalue), options={"slider": str(jvalue)})

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
        rgbw = state.attributes.get("rgbw_color")
        rgb = state.attributes.get("rgb_color")
        if rgbw is not None:
            try:
                self._attr_rgbw_color = tuple(int(v) for v in rgbw)
                self._last_rgbw = self._attr_rgbw_color
            except Exception:
                pass
        elif rgb is not None:
            try:
                self._attr_rgb_color = tuple(int(v) for v in rgb)
                self._last_rgbw = _rgb_to_rgbw(self._attr_rgb_color)
            except Exception:
                pass

    def _update_color_attrs(self) -> None:
        if not self._has_rgb:
            return
        r = self._channel_values.get("red") or 0
        g = self._channel_values.get("green") or 0
        b = self._channel_values.get("blue") or 0
        if self._has_white:
            w = self._channel_values.get("white") or 0
            self._attr_rgbw_color = (r, g, b, w)
            self._attr_rgb_color = None
            self._last_rgbw = self._attr_rgbw_color
        else:
            self._attr_rgb_color = (r, g, b)
            self._attr_rgbw_color = None
            self._last_rgbw = (r, g, b, 0)
        if self._attr_brightness is None:
            self._attr_brightness = max(r, g, b, self._attr_rgbw_color[3] if self._attr_rgbw_color else 0)
        if self._attr_brightness is not None:
            self._attr_is_on = (self._attr_brightness > 0) or any(v > 0 for v in (r, g, b))
        else:
            self._attr_is_on = any(v > 0 for v in (r, g, b, self._attr_rgbw_color[3] if self._attr_rgbw_color else 0))


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


def _coerce_int(value, default: int) -> int:
    try:
        return int(value)
    except Exception:
        return default


def _ha_to_jeedom_brightness(value, min_value: int = 0, max_value: int = JEEDOM_BRIGHTNESS_MAX) -> int:
    try:
        v = int(value)
    except Exception:
        v = 0
    v = max(0, min(255, v))
    if max_value <= min_value:
        return min_value
    scaled = min_value + (v / 255) * (max_value - min_value)
    return int(round(scaled))


def _jeedom_to_ha_brightness(value, min_value: int = 0, max_value: int = JEEDOM_BRIGHTNESS_MAX) -> int | None:
    try:
        v = float(value)
    except Exception:
        return None
    if max_value <= min_value:
        return None
    v = max(min_value, min(max_value, v))
    return int(round((v - min_value) * 255 / (max_value - min_value)))


def _rgb_to_rgbw(rgb):
    r, g, b = (int(c) for c in rgb)
    w = min(r, g, b)
    return (r - w, g - w, b - w, w)


def _scale_rgbw(rgbw, brightness: int):
    try:
        b = int(brightness)
    except Exception:
        b = 0
    b = max(0, min(255, b))
    if not rgbw:
        return rgbw
    if len(rgbw) == 3:
        rgbw = (*rgbw, 0)
    scale = b / 255 if b > 0 else 0
    return tuple(int(round(c * scale)) for c in rgbw)
