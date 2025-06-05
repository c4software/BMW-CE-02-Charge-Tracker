"""Number platform for BMW CE-02 Charge Tracker, handling SoC display and input."""
import logging
from typing import Optional
from datetime import datetime, timedelta, timezone 

from homeassistant.components.number import (
    NumberEntity,
    NumberDeviceClass,
    NumberMode,
    RestoreNumber, # Keep for SoC persistence
)
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import PERCENTAGE

from .const import (
    DOMAIN,
    BATTERY_CAPACITY_KWH, 
    SOC_THRESHOLD_PHASE2, # Used for time_at_80_pct attribute
    TIME_REMAINING_STATUS_REACHED,
    TIME_REMAINING_STATUS_FULL,
)
from .sensor import BMWCE02ChargeController # Controller class

_LOGGER = logging.getLogger(__name__)

async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the BMW CE-02 SoC number entity."""
    controller: BMWCE02ChargeController = hass.data[DOMAIN][config_entry.entry_id]["controller"]
    async_add_entities([BMWCE02SoCNumberEntity(config_entry, controller)])


class BMWCE02SoCNumberEntity(RestoreNumber, NumberEntity):
    _attr_should_poll = False # Updates are pushed by controller
    _attr_device_class = NumberDeviceClass.BATTERY
    _attr_mode = NumberMode.SLIDER 
    _attr_native_unit_of_measurement = PERCENTAGE
    _attr_native_min_value = 0.0
    _attr_native_max_value = 100.0
    _attr_native_step = 1.0 # Or 0.1 if you want finer control via UI

    def __init__(self, config_entry: ConfigEntry, controller: BMWCE02ChargeController):
        self._config_entry = config_entry
        self._controller = controller
        self._attr_name = f"{self._controller.device_name} SoC"
        self._attr_unique_id = f"{config_entry.entry_id}_soc_number_input"
        # _attr_native_value will be set in async_added_to_hass

    async def async_added_to_hass(self) -> None:
        """Restore last state and subscribe to controller updates."""
        await super().async_added_to_hass() # Handles restoring _attr_native_value

        restored_soc = self.native_value # From RestoreNumber
        
        if restored_soc is not None:
            self._controller.current_soc = float(restored_soc)
            _LOGGER.info(
                f"Restored SoC for {self._controller.device_name} to {self._controller.current_soc:.1f}% from NumberEntity state."
            )
        else:
            # If no restored state, use controller's default (e.g., 50.0)
            self._controller.current_soc = self._controller.current_soc # Ensure it's set
            self._attr_native_value = round(self._controller.current_soc,1) # Update restored value if it was None
            _LOGGER.info(
                f"No NumberEntity state found for {self._controller.device_name}, SoC uses controller's current value: {self._controller.current_soc:.1f}%"
            )
        
        # Ensure _attr_native_value reflects the controller's SoC after potential restoration
        if self._attr_native_value is None or round(self._controller.current_soc,1) != self._attr_native_value :
             self._attr_native_value = round(self._controller.current_soc, 1)


        @callback
        def _update_callback():
            new_value = round(self._controller.current_soc, 1)
            if self._attr_native_value != new_value:
                self._attr_native_value = new_value
                if self.hass: self.async_write_ha_state()
        
        self._controller.register_update_callback(_update_callback)
        # Ensure initial state is pushed
        if self.hass: self.async_schedule_update_ha_state(True)


    @property
    def native_value(self) -> float | None:
        """Return the current SoC from the controller."""
        return round(self._controller.current_soc, 1)

    async def async_set_native_value(self, value: float) -> None:
        """Update the current SoC value in the controller when user changes it."""
        rounded_value = round(value, 1)
        await self._controller.async_set_current_soc(rounded_value) # Notify controller
        if self._attr_native_value != rounded_value:
            self._attr_native_value = rounded_value 
            self.async_write_ha_state()

    @property
    def extra_state_attributes(self):
        """Return the state attributes."""
        attrs = {
            "is_charging": self._controller.is_charging, # Now based on actual power
            "current_charge_power_kw": round(self._controller.current_power_kw, 3) if self._controller.is_charging else 0.0,
            "soc_at_charge_start": None,
            "charge_start_time": None,
            "battery_capacity_kwh": BATTERY_CAPACITY_KWH,
            "target_soc_phase_change_pct": SOC_THRESHOLD_PHASE2,
            "time_at_80_pct": None,
            "time_at_100_pct": None,
        }

        if self._controller.is_charging and self._controller._charge_start_time:
            attrs["soc_at_charge_start"] = round(self._controller._soc_at_charge_start, 1)
            attrs["charge_start_time"] = self._controller._charge_start_time.isoformat()

        current_soc_val = self._controller.current_soc # Use controller's live SoC

        # Estimated time attributes
        now_utc = datetime.now(timezone.utc)
        if self._controller.is_charging or current_soc_val < SOC_THRESHOLD_PHASE2 : # Show if charging or not yet reached
            if self._controller.duration_to_80_pct_seconds is not None:
                if self._controller.duration_to_80_pct_seconds == 0 and current_soc_val >= SOC_THRESHOLD_PHASE2:
                    attrs["time_at_80_pct"] = TIME_REMAINING_STATUS_REACHED
                elif self._controller.duration_to_80_pct_seconds > 0:
                    attrs["time_at_80_pct"] = (now_utc + timedelta(seconds=self._controller.duration_to_80_pct_seconds)).isoformat()
        elif current_soc_val >= SOC_THRESHOLD_PHASE2:
             attrs["time_at_80_pct"] = TIME_REMAINING_STATUS_REACHED


        if self._controller.is_charging or current_soc_val < 100.0: # Show if charging or not yet full
            if self._controller.duration_to_100_pct_seconds is not None:
                if self._controller.duration_to_100_pct_seconds == 0 and current_soc_val >= 100.0:
                    attrs["time_at_100_pct"] = TIME_REMAINING_STATUS_FULL
                elif self._controller.duration_to_100_pct_seconds > 0:
                     attrs["time_at_100_pct"] = (now_utc + timedelta(seconds=self._controller.duration_to_100_pct_seconds)).isoformat()
        elif current_soc_val >= 100.0:
            attrs["time_at_100_pct"] = TIME_REMAINING_STATUS_FULL
            
        return attrs

    @property
    def device_info(self):
        return {
            "identifiers": {(DOMAIN, self._config_entry.entry_id)},
            "name": self._controller.device_name,
            "manufacturer": "BMW CE-02 Tracker (Custom)", # Keep or update as you see fit
            "model": "CE-02 RealPower Sim", # Updated model
        }

    @property
    def icon(self):
        """Return the icon to use in the frontend, if any."""
        soc = self.native_value # Use the entity's current native_value
        if soc is None: return "mdi:battery-unknown"
        
        is_charging_state = self._controller.is_charging # Use controller's live charging state
        
        base_icon = "mdi:battery"
        if is_charging_state:
            # Check if power is very low, could be "plugged in, not charging"
            # This threshold is for icon display only, not for SoC calculation logic.
            if self._controller.current_power_kw * 1000 < (self._controller.min_charging_power_w / 2) and soc < 99:
                 base_icon = "mdi:battery-plus" # Or mdi:power-plug if preferred for "plugged in"
            else:
                 base_icon = "mdi:battery-charging" # Actively charging

        # Specific SoC level icons
        if soc >= 95: return f"{base_icon}" if is_charging_state and base_icon == "mdi:battery-charging" else ("mdi:battery" if not is_charging_state else base_icon)
        # For charging icons, append level: mdi:battery-charging-90, mdi:battery-charging-80 etc.
        # For non-charging: mdi:battery-90, mdi:battery-80 etc.
        level_suffix = ""
        if soc >= 85: level_suffix = "-90"
        elif soc >= 75: level_suffix = "-80"
        elif soc >= 65: level_suffix = "-70"
        elif soc >= 55: level_suffix = "-60"
        elif soc >= 45: level_suffix = "-50"
        elif soc >= 35: level_suffix = "-40"
        elif soc >= 25: level_suffix = "-30"
        elif soc >= 15: level_suffix = "-20"
        elif soc > 5 : level_suffix = "-10" # Only add -10 if soc is actually > 5, not just >=5
        elif soc <=5 : return f"{base_icon}-outline" if not is_charging_state else f"{base_icon}-alert-variant-outline" # Example for very low
        
        return f"{base_icon}{level_suffix}"