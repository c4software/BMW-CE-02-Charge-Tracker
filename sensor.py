"""Sensor platform for BMW CE-02 Charge Tracker."""
import logging
from datetime import datetime, timedelta, timezone
import voluptuous as vol

from homeassistant.components.sensor import (
    RestoreSensor,
    SensorDeviceClass,
    SensorStateClass,
    SensorEntity,
)
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback, async_get_current_platform
from homeassistant.config_entries import ConfigEntry
from homeassistant.helpers.event import async_track_time_interval
from homeassistant.const import (
    PERCENTAGE,
    UnitOfTime, # Nécessaire pour les capteurs de durée
)

from .const import (
    DOMAIN,
    CHARGER_POWER_PHASE1_KW,
    CHARGER_POWER_PHASE2_KW,
    BATTERY_CAPACITY_KWH,
    SOC_THRESHOLD_PHASE2,
    UPDATE_INTERVAL_CHARGING_SECONDS,
)

_LOGGER = logging.getLogger(__name__)

class BMWCE02ChargeController:
    """Manages the state and logic for BMW CE-02 charging."""
    def __init__(self, hass: HomeAssistant, config_entry: ConfigEntry, device_name: str):
        self.hass = hass
        self.config_entry = config_entry
        self.device_name = device_name

        self.current_soc: float = 50.0
        self.is_charging: bool = False

        self._soc_at_charge_start: float = 0.0
        self._charge_start_time: datetime | None = None
        self._last_soc_update_time: datetime | None = None

        # Persisted state fields
        self.persisted_is_charging: bool = False
        self.persisted_soc_at_charge_start: float = 0.0
        self.persisted_charge_start_time_str: str | None = None
        self.persisted_last_soc_update_time_str: str | None = None

        # Duration fields
        self.elapsed_charging_seconds: int | None = 0
        self.duration_to_80_pct_seconds: int | None = None
        self.duration_to_100_pct_seconds: int | None = None

        self._update_callbacks = []
        self._listeners = []

    async def async_initialize_listeners(self):
        self.async_unsubscribe_listeners()
        if self.persisted_is_charging:
            self.is_charging = True
            self._soc_at_charge_start = self.persisted_soc_at_charge_start
            try:
                self._charge_start_time = datetime.fromisoformat(self.persisted_charge_start_time_str) if self.persisted_charge_start_time_str else datetime.now(timezone.utc)
                self._last_soc_update_time = datetime.fromisoformat(self.persisted_last_soc_update_time_str) if self.persisted_last_soc_update_time_str else self._charge_start_time
                _LOGGER.info(f"{self.device_name} charging state RESTORED to ON. SoC at start: {self._soc_at_charge_start:.1f}%. Current SoC: {self.current_soc:.1f}%")
            except (ValueError, TypeError) as e:
                _LOGGER.warning(f"Failed to parse date for {self.device_name}: {e}. Resetting times.")
                self._charge_start_time = datetime.now(timezone.utc)
                self._last_soc_update_time = self._charge_start_time
        else:
            self.is_charging = False
        
        self._update_duration_metrics() # Calculate initial durations based on restored state

        self._listeners.append(
            async_track_time_interval(self.hass, self._async_periodic_update, timedelta(seconds=UPDATE_INTERVAL_CHARGING_SECONDS))
        )
        self._notify_updates()

    def async_unsubscribe_listeners(self):
        for unsub_listener in self._listeners:
            unsub_listener()
        self._listeners.clear()

    def start_charging_manual(self):
        if not self.is_charging:
            self.is_charging = True
            self._soc_at_charge_start = self.current_soc
            self._charge_start_time = datetime.now(timezone.utc)
            self._last_soc_update_time = self._charge_start_time
            self.persisted_is_charging = True
            self.persisted_soc_at_charge_start = self._soc_at_charge_start
            self.persisted_charge_start_time_str = self._charge_start_time.isoformat()
            self.persisted_last_soc_update_time_str = self._last_soc_update_time.isoformat()
            _LOGGER.info(f"{self.device_name} charging MANUALLY STARTED. SoC: {self.current_soc:.1f}%")
            self._update_duration_metrics()
            self._notify_updates()

    def stop_charging_manual(self):
        if self.is_charging:
            self.is_charging = False
            self.persisted_is_charging = False
            self._update_soc_calculation_logic(final_update=True)
            _LOGGER.info(f"{self.device_name} charging MANUALLY STOPPED. SoC: {self.current_soc:.1f}%")
            self._update_duration_metrics() # Update durations to 0/None
            self._notify_updates()

    async def _async_periodic_update(self, now=None):
        """Combined periodic update for SoC and duration metrics if charging."""
        if not self.is_charging or self._charge_start_time is None:
            # Ensure durations are None/0 if not charging (handled by _update_duration_metrics called from _notify_updates)
            return
        self._update_soc_calculation_logic()
        self._update_duration_metrics() # Recalculate durations
        self._notify_updates()

    def _update_soc_calculation_logic(self, final_update=False):
        if (not self.is_charging and not final_update) or self.current_soc >= 100:
            if self.current_soc >= 100 and self.is_charging:
                 _LOGGER.debug(f"{self.device_name} at 100%. No SoC increase.")
            return

        if self._last_soc_update_time is None:
            self._last_soc_update_time = datetime.now(timezone.utc)
            if self._charge_start_time is not None:
                 self._last_soc_update_time = self._charge_start_time
            else:
                 _LOGGER.warning(f"Charge start time is None for {self.device_name} during SoC calc.")
                 return

        current_time = datetime.now(timezone.utc)
        time_delta_seconds = (current_time - self._last_soc_update_time).total_seconds()

        if time_delta_seconds <= 1: return

        charge_power_kw = CHARGER_POWER_PHASE1_KW if self.current_soc < SOC_THRESHOLD_PHASE2 else CHARGER_POWER_PHASE2_KW
        energy_added_kwh = charge_power_kw * (time_delta_seconds / 3600.0)
        soc_added = (energy_added_kwh / BATTERY_CAPACITY_KWH) * 100.0

        if soc_added > 0:
            new_soc = self.current_soc + soc_added
            self.current_soc = min(100.0, new_soc)
            _LOGGER.debug(f"{self.device_name} SoC update: +{soc_added:.3f}%. New: {self.current_soc:.1f}%.")
        
        self._last_soc_update_time = current_time
        self.persisted_last_soc_update_time_str = current_time.isoformat()

    def _update_duration_metrics(self):
        """Calculates and updates all duration metrics."""
        if not self.is_charging or self.current_soc is None:
            self.elapsed_charging_seconds = 0
            self.duration_to_80_pct_seconds = 0 if self.current_soc >= SOC_THRESHOLD_PHASE2 else None
            self.duration_to_100_pct_seconds = 0 if self.current_soc >= 100.0 else None
            return

        # Elapsed time
        if self._charge_start_time:
            self.elapsed_charging_seconds = round((datetime.now(timezone.utc) - self._charge_start_time).total_seconds())
        else:
            self.elapsed_charging_seconds = 0

        current_soc_val = self.current_soc

        # --- Duration to 80% ---
        if current_soc_val >= SOC_THRESHOLD_PHASE2:
            self.duration_to_80_pct_seconds = 0 # "Atteint"
        else:
            soc_needed_to_80 = SOC_THRESHOLD_PHASE2 - current_soc_val
            if CHARGER_POWER_PHASE1_KW > 0:
                duration_hours = (soc_needed_to_80 / 100.0 * BATTERY_CAPACITY_KWH) / CHARGER_POWER_PHASE1_KW
                self.duration_to_80_pct_seconds = round(duration_hours * 3600) if duration_hours >=0 else 0
            else:
                self.duration_to_80_pct_seconds = None # Cannot calculate

        # --- Duration to 100% ---
        if current_soc_val >= 100.0:
            self.duration_to_100_pct_seconds = 0 # "Pleine"
        else:
            total_duration_hours = 0.0
            can_charge = True
            temp_current_soc = current_soc_val # Use a temporary var for multi-step calculation

            if temp_current_soc < SOC_THRESHOLD_PHASE2:
                soc_needed_phase1 = SOC_THRESHOLD_PHASE2 - temp_current_soc
                if CHARGER_POWER_PHASE1_KW > 0:
                    total_duration_hours += (soc_needed_phase1 / 100.0 * BATTERY_CAPACITY_KWH) / CHARGER_POWER_PHASE1_KW
                    temp_current_soc = SOC_THRESHOLD_PHASE2 # Advance SoC for next step calculation
                else:
                    can_charge = False
            
            if can_charge and temp_current_soc < 100.0: # If still needs charging (i.e. entered phase 2 or started in it)
                soc_needed_phase2 = 100.0 - temp_current_soc
                if CHARGER_POWER_PHASE2_KW > 0:
                    total_duration_hours += (soc_needed_phase2 / 100.0 * BATTERY_CAPACITY_KWH) / CHARGER_POWER_PHASE2_KW
                elif soc_needed_phase2 > 0: # Needs charging but power is zero
                    can_charge = False
            
            if can_charge and total_duration_hours >= 0:
                self.duration_to_100_pct_seconds = round(total_duration_hours * 3600)
            else:
                self.duration_to_100_pct_seconds = None
    
    def register_update_callback(self, callback_func):
        if callback_func not in self._update_callbacks:
            self._update_callbacks.append(callback_func)
        callback_func() 

    def remove_update_callback(self, callback_func):
        if callback_func in self._update_callbacks:
            self._update_callbacks.remove(callback_func)

    def _notify_updates(self):
        # Ensure duration metrics are up-to-date before notifying
        # self._update_duration_metrics() # Moved to be called by specific actions or periodic update
        for cb_func in self._update_callbacks:
            cb_func()

    async def async_set_current_soc(self, soc_value: float):
        if 0 <= soc_value <= 100:
            self.current_soc = float(soc_value)
            _LOGGER.info(f"{self.device_name} SoC manually set to: {self.current_soc:.1f}%")
            if self.is_charging:
                self._soc_at_charge_start = self.current_soc
                self._charge_start_time = datetime.now(timezone.utc)
                self._last_soc_update_time = self._charge_start_time
                self.persisted_soc_at_charge_start = self._soc_at_charge_start
                self.persisted_charge_start_time_str = self._charge_start_time.isoformat()
                self.persisted_last_soc_update_time_str = self._last_soc_update_time.isoformat()
            self._update_duration_metrics() # Recalculate durations after SoC change
            self._notify_updates()
        else:
            _LOGGER.warning(f"Invalid SoC value for manual set: {soc_value}")


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the BMW CE-02 sensors."""
    controller = hass.data[DOMAIN][config_entry.entry_id]["controller"]
    
    entities_to_add = [
        BMWCE02SoCSensor(config_entry, controller),
        BMWCE02ElapsedChargingTimeSensor(config_entry, controller),
        BMWCE02TimeTo80PctSensor(config_entry, controller),
        BMWCE02TimeToFullSensor(config_entry, controller),
    ]
    
    async_add_entities(entities_to_add, True)


class BMWCE02SoCSensor(RestoreSensor, SensorEntity):
    _attr_device_class = SensorDeviceClass.BATTERY
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = PERCENTAGE
    _attr_should_poll = False

    def __init__(self, config_entry: ConfigEntry, controller: BMWCE02ChargeController):
        self._config_entry = config_entry
        self._controller = controller
        self._attr_name = f"{self._controller.device_name} Estimated SoC"
        self._attr_unique_id = f"{config_entry.entry_id}_estimated_soc"
        self._attr_native_value = round(self._controller.current_soc, 1)

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        last_sensor_data = await self.async_get_last_sensor_data()
        if last_sensor_data and hasattr(last_sensor_data, 'native_value') and last_sensor_data.native_value is not None :
            self._controller.current_soc = float(last_sensor_data.native_value)
            _LOGGER.info(f"Restored SoC for {self._controller.device_name} to {self._controller.current_soc:.1f}%")
            if hasattr(last_sensor_data, 'extra_attributes') and last_sensor_data.extra_attributes:
                attrs = last_sensor_data.extra_attributes
                self._controller.persisted_is_charging = attrs.get("persisted_is_charging_flag", False)
                self._controller.persisted_soc_at_charge_start = attrs.get("persisted_soc_at_charge_start_val", self._controller.current_soc)
                self._controller.persisted_charge_start_time_str = attrs.get("persisted_charge_start_time_val")
                self._controller.persisted_last_soc_update_time_str = attrs.get("persisted_last_soc_update_time_val")
        else:
            if self._controller.current_soc is None: self._controller.current_soc = 50.0
            _LOGGER.info(f"SoC for {self._controller.device_name} (default/current): {self._controller.current_soc:.1f}%")
        self._attr_native_value = round(self._controller.current_soc, 1)
        self._controller.register_update_callback(self._handle_controller_update)

    @callback
    def _handle_controller_update(self):
        self._attr_native_value = round(self._controller.current_soc, 1)
        if self.hass: self.async_write_ha_state()

    @property
    def extra_state_attributes(self):
        attrs = {
            "is_charging": self._controller.is_charging,
            "soc_at_charge_start": round(self._controller._soc_at_charge_start, 1) if self._controller._charge_start_time and self._controller.is_charging else None,
            "charge_start_time": self._controller._charge_start_time.isoformat() if self._controller._charge_start_time and self._controller.is_charging else None,
            "last_soc_update_time": self._controller._last_soc_update_time.isoformat() if self._controller._last_soc_update_time and self._controller.is_charging else None,
            "battery_capacity_kwh": BATTERY_CAPACITY_KWH,
            "target_soc_phase_change_pct": SOC_THRESHOLD_PHASE2,
            "persisted_is_charging_flag": self._controller.persisted_is_charging,
            "persisted_soc_at_charge_start_val": self._controller.persisted_soc_at_charge_start,
            "persisted_charge_start_time_val": self._controller.persisted_charge_start_time_str,
            "persisted_last_soc_update_time_val": self._controller.persisted_last_soc_update_time_str,
        }
        current_soc_val = float(self._attr_native_value if self._attr_native_value is not None else 0.0)
        attrs["current_charge_power_kw"] = (CHARGER_POWER_PHASE1_KW if current_soc_val < SOC_THRESHOLD_PHASE2 else CHARGER_POWER_PHASE2_KW) if self._controller.is_charging and current_soc_val < 100 else 0
        
        now_utc = datetime.now(timezone.utc)
        attrs["time_at_80_pct"] = None
        attrs["time_at_100_pct"] = None

        if self._controller.is_charging:
            if self._controller.duration_to_80_pct_seconds is not None:
                if self._controller.duration_to_80_pct_seconds == 0 and current_soc_val >= SOC_THRESHOLD_PHASE2:
                    attrs["time_at_80_pct"] = "Atteint"
                elif self._controller.duration_to_80_pct_seconds > 0 :
                    attrs["time_at_80_pct"] = (now_utc + timedelta(seconds=self._controller.duration_to_80_pct_seconds)).isoformat()
            
            if self._controller.duration_to_100_pct_seconds is not None:
                if self._controller.duration_to_100_pct_seconds == 0 and current_soc_val >= 100.0:
                    attrs["time_at_100_pct"] = "Pleine"
                elif self._controller.duration_to_100_pct_seconds > 0:
                     attrs["time_at_100_pct"] = (now_utc + timedelta(seconds=self._controller.duration_to_100_pct_seconds)).isoformat()
        else: # Non en charge
            if current_soc_val >= SOC_THRESHOLD_PHASE2: attrs["time_at_80_pct"] = "Atteint"
            if current_soc_val >= 100.0: attrs["time_at_100_pct"] = "Pleine"
            
        return attrs

    @property
    def device_info(self):
        return {
            "identifiers": {(DOMAIN, self._config_entry.entry_id)},
            "name": self._controller.device_name,
            "manufacturer": "BMW CE-02 Tracker (Custom)",
            "model": "CE-02 Simulated",
        }

class BMWCE02ElapsedChargingTimeSensor(SensorEntity):
    _attr_device_class = SensorDeviceClass.DURATION
    _attr_native_unit_of_measurement = UnitOfTime.SECONDS
    _attr_icon = "mdi:timer-sand"
    _attr_should_poll = False
    _attr_state_class = SensorStateClass.MEASUREMENT

    def __init__(self, config_entry: ConfigEntry, controller: BMWCE02ChargeController):
        self._config_entry = config_entry
        self._controller = controller
        self._attr_name = f"{self._controller.device_name} Temps de Charge Écoulé"
        self._attr_unique_id = f"{config_entry.entry_id}_elapsed_charging_time"
        self._attr_native_value = self._controller.elapsed_charging_seconds

    async def async_added_to_hass(self) -> None:
        @callback
        def _update_callback():
            self._attr_native_value = self._controller.elapsed_charging_seconds
            if self.hass: self.async_write_ha_state()
        self._controller.register_update_callback(_update_callback)

    @property
    def device_info(self):
        return {
            "identifiers": {(DOMAIN, self._config_entry.entry_id)},
            "name": self._controller.device_name, # Lie au même appareil
        }

class BMWCE02TimeTo80PctSensor(SensorEntity):
    _attr_device_class = SensorDeviceClass.DURATION
    _attr_native_unit_of_measurement = UnitOfTime.SECONDS
    _attr_icon = "mdi:timer-arrow-right-outline"
    _attr_should_poll = False
    _attr_state_class = SensorStateClass.MEASUREMENT 

    def __init__(self, config_entry: ConfigEntry, controller: BMWCE02ChargeController):
        self._config_entry = config_entry
        self._controller = controller
        self._attr_name = f"{self._controller.device_name} Temps Restant jusqu'à 80%"
        self._attr_unique_id = f"{config_entry.entry_id}_time_to_80_pct"
        self._attr_native_value = self._controller.duration_to_80_pct_seconds

    async def async_added_to_hass(self) -> None:
        @callback
        def _update_callback():
            self._attr_native_value = self._controller.duration_to_80_pct_seconds
            if self.hass: self.async_write_ha_state()
        self._controller.register_update_callback(_update_callback)
        
    @property
    def device_info(self): # Lie au même appareil
        return { "identifiers": {(DOMAIN, self._config_entry.entry_id)} }


class BMWCE02TimeToFullSensor(SensorEntity):
    _attr_device_class = SensorDeviceClass.DURATION
    _attr_native_unit_of_measurement = UnitOfTime.SECONDS
    _attr_icon = "mdi:timer-check-outline"
    _attr_should_poll = False
    _attr_state_class = SensorStateClass.MEASUREMENT

    def __init__(self, config_entry: ConfigEntry, controller: BMWCE02ChargeController):
        self._config_entry = config_entry
        self._controller = controller
        self._attr_name = f"{self._controller.device_name} Temps Restant jusqu'à 100%"
        self._attr_unique_id = f"{config_entry.entry_id}_time_to_100_pct"
        self._attr_native_value = self._controller.duration_to_100_pct_seconds

    async def async_added_to_hass(self) -> None:
        @callback
        def _update_callback():
            self._attr_native_value = self._controller.duration_to_100_pct_seconds
            if self.hass: self.async_write_ha_state()
        self._controller.register_update_callback(_update_callback)

    @property
    def device_info(self): # Lie au même appareil
        return { "identifiers": {(DOMAIN, self._config_entry.entry_id)} }