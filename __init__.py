import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.const import Platform

from .const import DOMAIN, CONF_DEVICE_NAME
from .sensor import BMWCE02ChargeController

_LOGGER = logging.getLogger(__name__)

PLATFORMS = [Platform.SENSOR, Platform.BINARY_SENSOR, Platform.SWITCH]

async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up BMW CE-02 Charge Tracker from a config entry."""
    hass.data.setdefault(DOMAIN, {})

    device_name = entry.data[CONF_DEVICE_NAME]

    controller = BMWCE02ChargeController(hass, entry, device_name)

    hass.data[DOMAIN][entry.entry_id] = {
        "controller": controller,
        "config": entry.data,
    }

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    
    await controller.async_initialize_listeners()
    
    entry.async_on_unload(controller.async_unsubscribe_listeners)

    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)

    if unload_ok:
        hass.data[DOMAIN].pop(entry.entry_id)
        return True
    return False