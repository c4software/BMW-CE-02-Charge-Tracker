"""Sensor platform for BMW CE-02 Charge Tracker (controller, duration and energy sensors)."""
import logging
from datetime import datetime, timedelta, timezone

from homeassistant.components.sensor import (
    RestoreSensor,
    SensorDeviceClass,
    SensorStateClass,
    SensorEntity,
)
from homeassistant.core import HomeAssistant, callback, State
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.config_entries import ConfigEntry
from homeassistant.helpers.event import async_track_time_interval
from homeassistant.const import (
    UnitOfTime,
    UnitOfEnergy,
    STATE_UNKNOWN,
    STATE_UNAVAILABLE,
    UnitOfPower,
)

from .const import (
    DOMAIN,
    BATTERY_CAPACITY_KWH,
    SOC_THRESHOLD_PHASE2,
    UPDATE_INTERVAL_CHARGING_SECONDS,
    CONF_POWER_SENSOR_ENTITY_ID,
    CONF_MIN_CHARGING_POWER,
    DEFAULT_MIN_CHARGING_POWER_W,
    TIME_REMAINING_STATUS_REACHED,
    TIME_REMAINING_STATUS_FULL,
    TIME_REMAINING_STATUS_UNAVAILABLE,
    CHARGER_LOST_FACTOR,
)

_LOGGER = logging.getLogger(__name__)

class BMWCE02ChargeController:
    """Manages the state and logic for BMW CE-02 charging based on actual power."""
    def __init__(self, hass: HomeAssistant, config_entry: ConfigEntry, device_name: str):
        self.hass = hass
        self.config_entry = config_entry
        self.device_name = device_name

        self.power_sensor_entity_id: str | None = config_entry.data.get(CONF_POWER_SENSOR_ENTITY_ID)
        self.min_charging_power_w: float = config_entry.data.get(CONF_MIN_CHARGING_POWER, DEFAULT_MIN_CHARGING_POWER_W)

        self.current_soc: float = 50.0 # Default, will be restored by NumberEntity
        self._is_charging_session_active: bool = False # Internal flag based on power

        self._soc_at_charge_start: float = 0.0
        self._charge_start_time: datetime | None = None
        self._last_soc_update_time: datetime | None = None
        self._last_known_power_kw: float = 0.0 # Store the last valid power reading in kW

        self.elapsed_charging_seconds: int | None = 0
        self.duration_to_80_pct_seconds: int | None = None
        self.duration_to_100_pct_seconds: int | None = None
        
        self.total_energy_consumed_kwh: float = 0.0 # Will be initialized by BMWCE02EnergySensor

        self._update_callbacks = []
        self._listeners = []

    @property
    def current_power_kw(self) -> float:
        """Return the current power draw in kW from the configured sensor."""
        if not self.power_sensor_entity_id:
            _LOGGER.debug(f"{self.device_name}: Power sensor entity ID not configured.")
            return 0.0
        
        power_state: State | None = self.hass.states.get(self.power_sensor_entity_id)
        
        if power_state and power_state.state not in [STATE_UNKNOWN, STATE_UNAVAILABLE]:
            try:
                power_watts = float(power_state.state)
                # Apply 8% reduction for conversion losses
                power_watts_adjusted = power_watts * CHARGER_LOST_FACTOR
                # Store the last known power for use in final calculations if power drops to 0 suddenly
                self._last_known_power_kw = power_watts_adjusted / 1000.0
                return self._last_known_power_kw
            except ValueError:
                _LOGGER.warning(
                    f"{self.device_name}: Could not parse power sensor value: '{power_state.state}' "
                    f"from entity '{self.power_sensor_entity_id}'"
                )
                return 0.0 # Treat unparseable state as 0 power
        else:
            _LOGGER.debug(
                f"{self.device_name}: Power sensor '{self.power_sensor_entity_id}' is unavailable or unknown. State: {power_state.state if power_state else 'None'}"
            )
            return 0.0 # Treat unavailable sensor as 0 power

    @property
    def is_charging(self) -> bool:
        """Returns true if a charging session is currently considered active."""
        return self._is_charging_session_active

    async def async_initialize_listeners(self):
        """Initialize listeners for periodic updates. SoC is restored by NumberEntity."""
        self.async_unsubscribe_listeners()
        await self._async_periodic_update()

        self._listeners.append(
            async_track_time_interval(
                self.hass, 
                self._async_periodic_update, 
                timedelta(seconds=UPDATE_INTERVAL_CHARGING_SECONDS)
            )
        )
        self._notify_updates()

    def async_unsubscribe_listeners(self):
        for unsub_listener in self._listeners:
            unsub_listener()
        self._listeners.clear()

    async def _async_periodic_update(self, now: datetime | None = None):
        """Periodically update charging status and SoC based on power sensor."""
        actual_power_kw = self.current_power_kw # This will also update self._last_known_power_kw
        actual_power_watts = actual_power_kw * 1000.0

        is_drawing_significant_power = actual_power_watts > self.min_charging_power_w

        # --- State Transition Detection ---
        if is_drawing_significant_power and not self._is_charging_session_active:
            # ---- Charging STARTS ----
            self._is_charging_session_active = True
            self._soc_at_charge_start = self.current_soc
            self._charge_start_time = datetime.now(timezone.utc)
            self._last_soc_update_time = self._charge_start_time # Reset for new session
            _LOGGER.info(
                f"{self.device_name} charging DETECTED (power: {actual_power_watts:.1f}W > {self.min_charging_power_w:.1f}W). "
                f"SoC at start: {self.current_soc:.1f}%"
            )

        elif not is_drawing_significant_power and self._is_charging_session_active:
            # ---- Charging STOPS ----
            self._is_charging_session_active = False
            _LOGGER.info(
                f"{self.device_name} charging STOPPED (power: {actual_power_watts:.1f}W <= {self.min_charging_power_w:.1f}W)."
            )
            self._update_soc_calculation_logic(final_update=True, charge_power_override_kw=self._last_known_power_kw)


        if self._is_charging_session_active:
            self._update_soc_calculation_logic()
        
        self._update_duration_metrics()
        self._notify_updates()

    def _update_soc_calculation_logic(self, final_update: bool = False, charge_power_override_kw: float | None = None):
        """Calculate SoC increase based on power and time."""
        if (not self._is_charging_session_active and not final_update):
            return

        if self.current_soc >= 100.0 and self._is_charging_session_active:
            _LOGGER.debug(f"{self.device_name} is at 100% SoC. No further SoC increase calculated.")
            return

        if self._last_soc_update_time is None:
            if final_update and self._charge_start_time:
                self._last_soc_update_time = self._charge_start_time
            else:
                _LOGGER.warning(
                    f"{self.device_name}: _last_soc_update_time is None during SoC calculation. "
                    "This might occur if charging stops very quickly. Skipping SoC update."
                )
                return

        current_time = datetime.now(timezone.utc)
        time_delta_seconds = (current_time - self._last_soc_update_time).total_seconds()

        if time_delta_seconds <= 0.1 and not final_update: # Allow final update to process small intervals
            return

        active_charge_power_kw = charge_power_override_kw if final_update and charge_power_override_kw is not None else self._last_known_power_kw
        
        if active_charge_power_kw * 1000.0 < (self.min_charging_power_w / 2) and not final_update: # a bit of margin
             _LOGGER.debug(f"{self.device_name}: Charge power {active_charge_power_kw:.3f}kW too low for SoC increase during active session.")
             self._last_soc_update_time = current_time # Still update time to prevent large future delta
             return

        energy_added_kwh = active_charge_power_kw * (time_delta_seconds / 3600.0)
        
        if energy_added_kwh > 0:
            self.total_energy_consumed_kwh += energy_added_kwh

        soc_added = (energy_added_kwh / BATTERY_CAPACITY_KWH) * 100.0

        if soc_added != 0: # Allow for negative if power sensor glitches or for very small changes
            new_soc = self.current_soc + soc_added
            previous_soc = self.current_soc
            self.current_soc = min(100.0, max(0.0, new_soc)) # Clamp between 0 and 100
            
            _LOGGER.debug(
                f"{self.device_name} SoC updated by {self.current_soc - previous_soc:+.2f}% to {self.current_soc:.1f}%. "
                f"Power: {active_charge_power_kw:.3f}kW, Interval: {time_delta_seconds:.1f}s, "
                f"Energy this tick: {energy_added_kwh:.4f}kWh"
            )
        
        self._last_soc_update_time = current_time

    def _update_duration_metrics(self):
        """Update elapsed time and estimated time remaining."""
        if not self.is_charging or self.current_soc is None or self._charge_start_time is None:
            self.elapsed_charging_seconds = 0
            self.duration_to_80_pct_seconds = 0 if (self.current_soc is not None and self.current_soc >= SOC_THRESHOLD_PHASE2) else None
            self.duration_to_100_pct_seconds = 0 if (self.current_soc is not None and self.current_soc >= 100.0) else None
            return

        self.elapsed_charging_seconds = round((datetime.now(timezone.utc) - self._charge_start_time).total_seconds())

        current_soc_val = self.current_soc
        
        # Time to 80%
        if current_soc_val >= SOC_THRESHOLD_PHASE2:
            self.duration_to_80_pct_seconds = 0  # Reached
        else:
            estimation_power_phase1_kw = 0.9 # Default from original for estimation
            if self._last_known_power_kw > 0.2: # If we have a somewhat reliable recent power
                estimation_power_phase1_kw = max(self._last_known_power_kw, 0.2) # Ensure it's not too low for calc

            soc_needed_to_80 = SOC_THRESHOLD_PHASE2 - current_soc_val
            if estimation_power_phase1_kw > 0:
                duration_hours = (soc_needed_to_80 / 100.0 * BATTERY_CAPACITY_KWH) / estimation_power_phase1_kw
                self.duration_to_80_pct_seconds = round(duration_hours * 3600) if duration_hours >= 0 else 0
            else:
                self.duration_to_80_pct_seconds = None 

        # Time to 100%
        if current_soc_val >= 100.0:
            self.duration_to_100_pct_seconds = 0  # Full
        else:
            total_duration_hours = 0.0
            temp_current_soc = current_soc_val            

            soc_needed_phase1 = SOC_THRESHOLD_PHASE2 - temp_current_soc
            if estimation_power_phase1_kw > 0:
                total_duration_hours += (soc_needed_phase1 / 100.0 * BATTERY_CAPACITY_KWH) / estimation_power_phase1_kw
                temp_current_soc = SOC_THRESHOLD_PHASE2
            else: # Cannot estimate if power is zero
                self.duration_to_100_pct_seconds = None
                return 
            
            if total_duration_hours >= 0:
                self.duration_to_100_pct_seconds = round(total_duration_hours * 3600)
            else:
                self.duration_to_100_pct_seconds = None

    def register_update_callback(self, callback_func):
        if callback_func not in self._update_callbacks:
            self._update_callbacks.append(callback_func)
        # Initial call to ensure entities are up-to-date after registration
        callback_func() 

    def remove_update_callback(self, callback_func):
        if callback_func in self._update_callbacks:
            self._update_callbacks.remove(callback_func)

    def _notify_updates(self):
        for cb_func in self._update_callbacks:
            try:
                cb_func()
            except Exception as e:
                _LOGGER.error(f"Error calling update callback {cb_func}: {e}")


    async def async_set_current_soc(self, soc_value: float):
        """Allow SoC to be set manually (e.g., by the NumberEntity)."""
        if 0.0 <= soc_value <= 100.0:
            _LOGGER.info(f"{self.device_name} SoC manually set to: {self.current_soc:.1f}% by user, new value: {soc_value:.1f}%")
            self.current_soc = float(soc_value)
            
            # If charging, this manual SoC change effectively resets the reference point.
            if self.is_charging: # self._is_charging_session_active
                _LOGGER.debug(f"{self.device_name}: SoC changed during active charge. Updating _soc_at_charge_start and _last_soc_update_time.")
                self._last_soc_update_time = datetime.now(timezone.utc)
            
            self._update_duration_metrics() 
            self._notify_updates()
        else:
            _LOGGER.warning(f"Invalid SoC value for manual set: {soc_value}")


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the BMW CE-02 sensors from a config entry."""
    controller: BMWCE02ChargeController = hass.data[DOMAIN][config_entry.entry_id]["controller"]
    
    entities_to_add = [
        BMWCE02ElapsedChargingTimeSensor(config_entry, controller),
        BMWCE02TimeTo80PctSensor(config_entry, controller),
        BMWCE02TimeToFullSensor(config_entry, controller),
        BMWCE02EnergySensor(config_entry, controller),
    ]
    
    async_add_entities(entities_to_add)


class BMWCE02EnergySensor(RestoreSensor, SensorEntity):
    _attr_device_class = SensorDeviceClass.ENERGY
    _attr_state_class = SensorStateClass.TOTAL_INCREASING
    _attr_native_unit_of_measurement = UnitOfEnergy.KILO_WATT_HOUR
    _attr_icon = "mdi:flash"
    _attr_should_poll = False
    _attr_name: str
    _attr_unique_id: str
    # _attr_native_value is managed by RestoreSensor logic

    def __init__(self, config_entry: ConfigEntry, controller: BMWCE02ChargeController):
        self._config_entry = config_entry
        self._controller = controller
        self._attr_name = f"{self._controller.device_name} Énergie Consommée"
        self._attr_unique_id = f"{config_entry.entry_id}_energy_consumed"

    async def async_added_to_hass(self) -> None:
        """Restore last state and subscribe to controller updates."""
        await super().async_added_to_hass()

        restored_energy_kwh = 0.0
        if (last_sensor_data := await self.async_get_last_sensor_data()) and \
           last_sensor_data.native_value is not None:
            try:
                restored_energy_kwh = float(last_sensor_data.native_value)
                _LOGGER.info(
                    f"Restored energy for {self._controller.device_name} to {restored_energy_kwh:.3f} kWh"
                )
            except ValueError:
                _LOGGER.warning(
                    f"Could not parse restored energy value: {last_sensor_data.native_value}"
                )
        
        self._controller.total_energy_consumed_kwh = restored_energy_kwh
        self._attr_native_value = restored_energy_kwh # Set initial state

        @callback
        def _update_callback():
            new_value = round(self._controller.total_energy_consumed_kwh, 3)
            if self._attr_native_value != new_value:
                self._attr_native_value = new_value
                if self.hass:
                    self.async_write_ha_state()
        
        self._controller.register_update_callback(_update_callback)
        # Ensure initial state is pushed if not done by register_update_callback's immediate call
        if self.hass:
            self.async_schedule_update_ha_state(True)


    @property
    def device_info(self):
        return {"identifiers": {(DOMAIN, self._config_entry.entry_id)}}


class BMWCE02ElapsedChargingTimeSensor(SensorEntity):
    _attr_device_class = SensorDeviceClass.DURATION
    _attr_native_unit_of_measurement = UnitOfTime.SECONDS
    _attr_icon = "mdi:timer-sand"
    _attr_should_poll = False
    _attr_state_class = SensorStateClass.MEASUREMENT # Duration is often a measurement
    _attr_name: str
    _attr_unique_id: str

    def __init__(self, config_entry: ConfigEntry, controller: BMWCE02ChargeController):
        self._config_entry = config_entry
        self._controller = controller
        self._attr_name = f"{self._controller.device_name} Temps de Charge Écoulé"
        self._attr_unique_id = f"{config_entry.entry_id}_elapsed_charging_time"
        self._attr_native_value = self._controller.elapsed_charging_seconds # Initial value

    async def async_added_to_hass(self) -> None:
        @callback
        def _update_callback():
            new_value = self._controller.elapsed_charging_seconds
            if self._attr_native_value != new_value:
                self._attr_native_value = new_value
                if self.hass: self.async_write_ha_state()
        self._controller.register_update_callback(_update_callback)
        if self.hass: self.async_schedule_update_ha_state(True)


    @property
    def device_info(self):
        return { "identifiers": {(DOMAIN, self._config_entry.entry_id)} }

class BMWCE02TimeTo80PctSensor(SensorEntity):
    _attr_icon = "mdi:timer-arrow-right-outline"
    _attr_should_poll = False
    _attr_name: str
    _attr_unique_id: str

    def __init__(self, config_entry: ConfigEntry, controller: BMWCE02ChargeController):
        self._config_entry = config_entry
        self._controller = controller
        self._attr_name = f"{self._controller.device_name} Temps Restant jusqu'à {SOC_THRESHOLD_PHASE2}%"
        self._attr_unique_id = f"{config_entry.entry_id}_time_to_{SOC_THRESHOLD_PHASE2}_pct"

    @property
    def native_value(self) -> str | None:
        if self._controller.current_soc is not None and self._controller.current_soc >= SOC_THRESHOLD_PHASE2:
            return TIME_REMAINING_STATUS_REACHED
        
        duration_seconds = self._controller.duration_to_80_pct_seconds
        if duration_seconds is None: return TIME_REMAINING_STATUS_UNAVAILABLE
        if duration_seconds == 0 and not (self._controller.current_soc >= SOC_THRESHOLD_PHASE2): # Charging hasn't started or no power
             return "00:00" # Or unavailable if more appropriate
        
        hours = duration_seconds // 3600
        minutes = (duration_seconds % 3600) // 60
        return f"{hours:02d}:{minutes:02d}"

    async def async_added_to_hass(self) -> None:
        @callback
        def _update_callback():
            if self.hass: self.async_write_ha_state() # Value is read from property
        self._controller.register_update_callback(_update_callback)
        if self.hass: self.async_schedule_update_ha_state(True)
        
    @property
    def device_info(self):
        return { "identifiers": {(DOMAIN, self._config_entry.entry_id)} }

class BMWCE02TimeToFullSensor(SensorEntity):
    _attr_icon = "mdi:timer-check-outline"
    _attr_should_poll = False
    _attr_name: str
    _attr_unique_id: str

    def __init__(self, config_entry: ConfigEntry, controller: BMWCE02ChargeController):
        self._config_entry = config_entry
        self._controller = controller
        self._attr_name = f"{self._controller.device_name} Temps Restant jusqu'à 100%"
        self._attr_unique_id = f"{config_entry.entry_id}_time_to_100_pct"

    @property
    def native_value(self) -> str | None:
        if self._controller.current_soc is not None and self._controller.current_soc >= 100.0:
            return TIME_REMAINING_STATUS_FULL
            
        duration_seconds = self._controller.duration_to_100_pct_seconds
        if duration_seconds is None: return TIME_REMAINING_STATUS_UNAVAILABLE
        if duration_seconds == 0 and not (self._controller.current_soc >= 100.0): # Charging hasn't started or no power
            return "00:00" # Or unavailable

        hours = duration_seconds // 3600
        minutes = (duration_seconds % 3600) // 60
        return f"{hours:02d}:{minutes:02d}"

    async def async_added_to_hass(self) -> None:
        @callback
        def _update_callback():
            if self.hass: self.async_write_ha_state()
        self._controller.register_update_callback(_update_callback)
        if self.hass: self.async_schedule_update_ha_state(True)

    @property
    def device_info(self):
        return { "identifiers": {(DOMAIN, self._config_entry.entry_id)} }