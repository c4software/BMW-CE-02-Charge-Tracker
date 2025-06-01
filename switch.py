"""Switch platfom for BMW CE-02 Charge Tracker."""
import logging

from homeassistant.components.switch import SwitchEntity, SwitchDeviceClass
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.config_entries import ConfigEntry

from .const import DOMAIN
from .sensor import BMWCE02ChargeController

_LOGGER = logging.getLogger(__name__)

async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    controller = hass.data[DOMAIN][config_entry.entry_id]["controller"]
    async_add_entities([BMWCE02ChargingToggleSwitch(config_entry, controller)])


class BMWCE02ChargingToggleSwitch(SwitchEntity):
    """Representation of the BMW CE-02 Charging Toggle switch."""
    _attr_should_poll = False
    _attr_device_class = SwitchDeviceClass.SWITCH

    def __init__(self, config_entry: ConfigEntry, controller: BMWCE02ChargeController):
        self._config_entry = config_entry
        self._controller = controller
        self._attr_name = f"{self._controller.device_name} Charging Toggle"
        self._attr_unique_id = f"{config_entry.entry_id}_charging_toggle"
        self._attr_is_on = self._controller.is_charging 

    @property
    def is_on(self) -> bool:
        return self._controller.is_charging

    async def async_turn_on(self, **kwargs) -> None:
        self._controller.start_charging_manual()

    async def async_turn_off(self, **kwargs) -> None:
        self._controller.stop_charging_manual()

    async def async_added_to_hass(self) -> None:
        @callback
        def _update_callback():
            new_state = self._controller.is_charging
            if self._attr_is_on != new_state:
                 self._attr_is_on = new_state
                 if self.hass:
                    self.async_write_ha_state()

        self._controller.register_update_callback(_update_callback)

    @property
    def device_info(self):
        return {
            "identifiers": {(DOMAIN, self._config_entry.entry_id)},
            "name": self._controller.device_name,
            "manufacturer": "BMW CE-02 Tracker (Custom)",
            "model": "CE-02 Simulated",
        }

    @property
    def icon(self):
        return "mdi:power-plug" if self.is_on else "mdi:power-plug-off"