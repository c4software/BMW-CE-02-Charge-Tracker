"""The BMW CE-02 Charge Tracker integration."""
import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.const import Platform

from .const import DOMAIN, CONF_DEVICE_NAME
from .sensor import BMWCE02ChargeController


_LOGGER = logging.getLogger(__name__)

PLATFORMS = [Platform.SENSOR, Platform.BINARY_SENSOR, Platform.NUMBER]

async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up BMW CE-02 Charge Tracker from a config entry."""
    hass.data.setdefault(DOMAIN, {})

    device_name = entry.data[CONF_DEVICE_NAME]

    controller = BMWCE02ChargeController(hass, entry, device_name)
    
    hass.data[DOMAIN][entry.entry_id] = {
        "controller": controller,
        "config": entry.data,
    }

    await controller.async_initialize_listeners()
    
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    
    entry.async_on_unload(controller.async_unsubscribe_listeners)
    entry.async_on_unload(entry.add_update_listener(_async_update_listener))


    return True

async def _async_update_listener(hass: HomeAssistant, entry: ConfigEntry):
    """Handle options update."""
    _LOGGER.debug("Configuration update listener called, reloading entry.")
    await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    controller: BMWCE02ChargeController | None = hass.data[DOMAIN].get(entry.entry_id, {}).get("controller")
    if controller:
        controller.async_unsubscribe_listeners()

    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)

    if unload_ok:
        hass.data[DOMAIN].pop(entry.entry_id, None)
        _LOGGER.info(f"BMW CE-02 Tracker for '{entry.title}' unloaded successfully.")
        return True
    
    _LOGGER.warning(f"Failed to unload BMW CE-02 Tracker for '{entry.title}'.")
    return False