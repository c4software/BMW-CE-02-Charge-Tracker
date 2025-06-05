"""Binary sensor platform for BMW CE-02 Charge Tracker."""
import logging

from homeassistant.components.binary_sensor import (
    BinarySensorEntity,
    BinarySensorDeviceClass,
)
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.config_entries import ConfigEntry

from .const import DOMAIN
from .sensor import BMWCE02ChargeController # Controller class

_LOGGER = logging.getLogger(__name__)

async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the BMW CE-02 charging status binary sensor."""
    controller: BMWCE02ChargeController = hass.data[DOMAIN][config_entry.entry_id]["controller"]
    async_add_entities([BMWCE02ChargingStatusBinarySensor(config_entry, controller)])


class BMWCE02ChargingStatusBinarySensor(BinarySensorEntity):
    _attr_device_class = BinarySensorDeviceClass.BATTERY_CHARGING
    _attr_should_poll = False # Updates are pushed

    def __init__(self, config_entry: ConfigEntry, controller: BMWCE02ChargeController):
        self._config_entry = config_entry
        self._controller = controller
        self._attr_name = f"{self._controller.device_name} Charging Status"
        self._attr_unique_id = f"{config_entry.entry_id}_charging_status"
        self._attr_is_on = self._controller.is_charging # Initial state

    @property
    def is_on(self) -> bool:
        """Return true if the battery is currently charging."""
        return self._controller.is_charging # Directly use controller's property

    # extra_state_attributes can be removed if not needed, or add power sensor ID for info
    @property
    def extra_state_attributes(self) -> dict:
        attrs = {}
        if self._controller.power_sensor_entity_id:
            attrs["power_sensor_entity_id"] = self._controller.power_sensor_entity_id
        attrs["actual_power_draw_kw"] = round(self._controller.current_power_kw, 3)
        return attrs

    async def async_added_to_hass(self) -> None:
        """Subscribe to controller updates."""
        @callback
        def _update_callback():
            new_state = self._controller.is_charging
            if self._attr_is_on != new_state:
                self._attr_is_on = new_state
                if self.hass: 
                    self.async_write_ha_state()
        
        self._controller.register_update_callback(_update_callback)
        # Ensure initial state is pushed
        if self.hass:
            self.async_schedule_update_ha_state(True)


    @property
    def device_info(self):
        # Same device info as NumberEntity for grouping
        return {
            "identifiers": {(DOMAIN, self._config_entry.entry_id)},
            "name": self._controller.device_name,
            "manufacturer": "BMW CE-02 Tracker (Custom)",
            "model": "CE-02 RealPower Sim", # Consistent model name
        }