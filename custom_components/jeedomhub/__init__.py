"""Support for Jeedom integration via MQTT."""
import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant

from .const import DOMAIN, CONF_IMPORT_MODE, IMPORT_MODE_NATIVE
from .hub import JeedomHub

_LOGGER = logging.getLogger(__name__)

PLATFORMS: list[Platform] = [
    Platform.BINARY_SENSOR,
    Platform.CLIMATE,
    Platform.COVER,
    Platform.LIGHT,
    Platform.NUMBER,
    Platform.SELECT,
    Platform.SENSOR,
    Platform.SWITCH,
    Platform.WATER_HEATER,
]


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Jeedom from a config entry."""
    _LOGGER.debug("Setting up Jeedom integration")

    hass.data.setdefault(DOMAIN, {})
    hub = JeedomHub(hass, entry)
    await hub.async_setup()
    hass.data[DOMAIN][entry.entry_id] = hub

    import_mode = entry.options.get(CONF_IMPORT_MODE) or entry.data.get(
        CONF_IMPORT_MODE, IMPORT_MODE_NATIVE
    )
    if import_mode == IMPORT_MODE_NATIVE:
        await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    _LOGGER.debug("Unloading Jeedom integration")

    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        hub = hass.data[DOMAIN].pop(entry.entry_id, None)
        if hub:
            await hub.async_unload()
    return unload_ok


async def async_reload_entry(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Reload config entry."""
    await async_unload_entry(hass, entry)
    await async_setup_entry(hass, entry)
