"""Sensor platform for BMW CE-02 Charge Tracker (duration, energy, and power sensors)."""
import logging
from datetime import datetime, timedelta, timezone

from homeassistant.components.sensor import (
    RestoreSensor,
    SensorDeviceClass,
    SensorStateClass,
    SensorEntity,
)
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.config_entries import ConfigEntry
from homeassistant.helpers.event import async_track_time_interval
from homeassistant.const import (
    UnitOfTime,
    UnitOfEnergy,
    UnitOfPower, 
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

        self.persisted_is_charging: bool = False
        self.persisted_soc_at_charge_start: float = 0.0
        self.persisted_charge_start_time_str: str | None = None
        self.persisted_last_soc_update_time_str: str | None = None

        self.elapsed_charging_seconds: int | None = 0
        self.duration_to_80_pct_seconds: int | None = None
        self.duration_to_100_pct_seconds: int | None = None
        
        self.total_energy_consumed_kwh: float = 0.0

        self._update_callbacks = []
        self._listeners = []

    @property
    def current_simulated_power_kw(self) -> float:
        """Return the current simulated charging power in kW."""
        if not self.is_charging:
            return 0.0
        if self.current_soc is None: 
             _LOGGER.warning("current_soc is None while trying to calculate simulated power.")
             return 0.0
        if self.current_soc >= 100.0:
            return 0.0 
        
        if self.current_soc < SOC_THRESHOLD_PHASE2:
            return CHARGER_POWER_PHASE1_KW
        else: 
            return CHARGER_POWER_PHASE2_KW

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
        
        self._update_duration_metrics() 

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
            self._update_duration_metrics() 
            self._notify_updates()

    async def _async_periodic_update(self, now=None):
        if not self.is_charging or self._charge_start_time is None:
            return
        self._update_soc_calculation_logic()
        self._update_duration_metrics() 
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

        charge_power_kw_for_energy_calc = 0.0
        if self.current_soc < SOC_THRESHOLD_PHASE2:
            charge_power_kw_for_energy_calc = CHARGER_POWER_PHASE1_KW
        elif self.current_soc < 100.0 : 
            charge_power_kw_for_energy_calc = CHARGER_POWER_PHASE2_KW
        
        energy_added_kwh = charge_power_kw_for_energy_calc * (time_delta_seconds / 3600.0)
        
        if energy_added_kwh > 0: 
            self.total_energy_consumed_kwh += energy_added_kwh

        soc_added = (energy_added_kwh / BATTERY_CAPACITY_KWH) * 100.0

        if soc_added > 0:
            new_soc = self.current_soc + soc_added
            self.current_soc = min(100.0, new_soc)
            _LOGGER.debug(f"{self.device_name} SoC update: +{soc_added:.3f}%. New: {self.current_soc:.1f}%. Energy tick: {energy_added_kwh:.4f} kWh")
        
        self._last_soc_update_time = current_time
        self.persisted_last_soc_update_time_str = current_time.isoformat()

    def _update_duration_metrics(self):
        if not self.is_charging or self.current_soc is None:
            self.elapsed_charging_seconds = 0
            self.duration_to_80_pct_seconds = 0 if (self.current_soc is not None and self.current_soc >= SOC_THRESHOLD_PHASE2) else None
            self.duration_to_100_pct_seconds = 0 if (self.current_soc is not None and self.current_soc >= 100.0) else None
            return

        if self._charge_start_time:
            self.elapsed_charging_seconds = round((datetime.now(timezone.utc) - self._charge_start_time).total_seconds())
        else:
            self.elapsed_charging_seconds = 0

        current_soc_val = self.current_soc
        if current_soc_val >= SOC_THRESHOLD_PHASE2:
            self.duration_to_80_pct_seconds = 0 
        else:
            soc_needed_to_80 = SOC_THRESHOLD_PHASE2 - current_soc_val
            if CHARGER_POWER_PHASE1_KW > 0:
                duration_hours = (soc_needed_to_80 / 100.0 * BATTERY_CAPACITY_KWH) / CHARGER_POWER_PHASE1_KW
                self.duration_to_80_pct_seconds = round(duration_hours * 3600) if duration_hours >=0 else 0
            else:
                self.duration_to_80_pct_seconds = None 

        if current_soc_val >= 100.0:
            self.duration_to_100_pct_seconds = 0 
        else:
            total_duration_hours = 0.0
            can_charge = True
            temp_current_soc = current_soc_val 
            if temp_current_soc < SOC_THRESHOLD_PHASE2:
                soc_needed_phase1 = SOC_THRESHOLD_PHASE2 - temp_current_soc
                if CHARGER_POWER_PHASE1_KW > 0:
                    total_duration_hours += (soc_needed_phase1 / 100.0 * BATTERY_CAPACITY_KWH) / CHARGER_POWER_PHASE1_KW
                    temp_current_soc = SOC_THRESHOLD_PHASE2 
                else:
                    can_charge = False
            
            if can_charge and temp_current_soc < 100.0: 
                soc_needed_phase2 = 100.0 - temp_current_soc
                if CHARGER_POWER_PHASE2_KW > 0:
                    total_duration_hours += (soc_needed_phase2 / 100.0 * BATTERY_CAPACITY_KWH) / CHARGER_POWER_PHASE2_KW
                elif soc_needed_phase2 > 0: 
                    can_charge = False
            
            if can_charge and total_duration_hours >= 0:
                self.duration_to_100_pct_seconds = round(total_duration_hours * 3600)
            else:
                self.duration_to_100_pct_seconds = None
    
    def register_update_callback(self, callback_func):
        if callback_func not in self._update_callbacks:
            self._update_callbacks.append(callback_func)

    def remove_update_callback(self, callback_func):
        if callback_func in self._update_callbacks:
            self._update_callbacks.remove(callback_func)

    def _notify_updates(self):
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
            self._update_duration_metrics() 
            self._notify_updates()
        else:
            _LOGGER.warning(f"Invalid SoC value for manual set: {soc_value}")

# Fin de BMWCE02ChargeController

async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the BMW CE-02 sensors."""
    controller = hass.data[DOMAIN][config_entry.entry_id]["controller"]
    
    entities_to_add = [
        BMWCE02ElapsedChargingTimeSensor(config_entry, controller),
        BMWCE02TimeTo80PctSensor(config_entry, controller),
        BMWCE02TimeToFullSensor(config_entry, controller),
        BMWCE02EnergySensor(config_entry, controller),
        BMWCE02PowerSensor(config_entry, controller),
    ]
    
    async_add_entities(entities_to_add, True)


class BMWCE02EnergySensor(RestoreSensor, SensorEntity):
    _attr_device_class = SensorDeviceClass.ENERGY
    _attr_state_class = SensorStateClass.TOTAL_INCREASING
    _attr_native_unit_of_measurement = UnitOfEnergy.KILO_WATT_HOUR
    _attr_icon = "mdi:flash"
    _attr_should_poll = False
    _attr_name: str
    _attr_unique_id: str
    _attr_native_value: float | None = 0.0

    def __init__(self, config_entry: ConfigEntry, controller: BMWCE02ChargeController):
        self._config_entry = config_entry
        self._controller = controller
        self._attr_name = f"{self._controller.device_name} Énergie Consommée"
        self._attr_unique_id = f"{config_entry.entry_id}_energy_consumed"

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        last_sensor_data = await self.async_get_last_sensor_data()
        restored_energy_kwh = 0.0
        if last_sensor_data and last_sensor_data.native_value is not None:
            try:
                restored_energy_kwh = float(last_sensor_data.native_value)
                _LOGGER.info(f"Restored energy for {self._controller.device_name} to {restored_energy_kwh:.3f} kWh")
            except ValueError:
                _LOGGER.warning(f"Could not parse restored energy value: {last_sensor_data.native_value}")
        self._controller.total_energy_consumed_kwh = restored_energy_kwh
        self._attr_native_value = restored_energy_kwh
        @callback
        def _update_callback():
            self._attr_native_value = round(self._controller.total_energy_consumed_kwh, 3)
            if self.hass: self.async_write_ha_state()
        self._controller.register_update_callback(_update_callback)

    @property
    def native_value(self) -> float | None:
        return self._attr_native_value

    @property
    def device_info(self):
        return {"identifiers": {(DOMAIN, self._config_entry.entry_id)}}


class BMWCE02ElapsedChargingTimeSensor(SensorEntity):
    _attr_device_class = SensorDeviceClass.DURATION
    _attr_native_unit_of_measurement = UnitOfTime.SECONDS
    _attr_icon = "mdi:timer-sand"
    _attr_should_poll = False
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_name: str
    _attr_unique_id: str
    _attr_native_value: int | None # Défini par le callback

    def __init__(self, config_entry: ConfigEntry, controller: BMWCE02ChargeController):
        self._config_entry = config_entry
        self._controller = controller
        self._attr_name = f"{self._controller.device_name} Temps de Charge Écoulé"
        self._attr_unique_id = f"{config_entry.entry_id}_elapsed_charging_time"

    async def async_added_to_hass(self) -> None:
        @callback
        def _update_callback():
            self._attr_native_value = self._controller.elapsed_charging_seconds
            if self.hass: self.async_write_ha_state()
        self._controller.register_update_callback(_update_callback)
        # L'appel initial à _update_callback via register_update_callback définira la valeur initiale.

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
        self._attr_name = f"{self._controller.device_name} Temps Restant jusqu'à 80%"
        self._attr_unique_id = f"{config_entry.entry_id}_time_to_80_pct"

    @property
    def native_value(self) -> str | None:
        if self._controller.current_soc is not None and self._controller.current_soc >= SOC_THRESHOLD_PHASE2:
            return "Atteint" 
        duration_seconds = self._controller.duration_to_80_pct_seconds
        if duration_seconds is None: return None 
        if duration_seconds == 0: return "00:00" 
        hours = duration_seconds // 3600
        minutes = (duration_seconds % 3600) // 60
        return f"{hours:02d}:{minutes:02d}"

    async def async_added_to_hass(self) -> None:
        @callback
        def _update_callback():
            if self.hass: self.async_write_ha_state()
        self._controller.register_update_callback(_update_callback)
        # La valeur sera mise à jour lors du premier _notify_updates du contrôleur.
        
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
            return "Pleine"
        duration_seconds = self._controller.duration_to_100_pct_seconds
        if duration_seconds is None: return None
        if duration_seconds == 0: return "00:00"
        hours = duration_seconds // 3600
        minutes = (duration_seconds % 3600) // 60
        return f"{hours:02d}:{minutes:02d}"

    async def async_added_to_hass(self) -> None:
        @callback
        def _update_callback():
            if self.hass: self.async_write_ha_state()
        self._controller.register_update_callback(_update_callback)

    @property
    def device_info(self):
        return { "identifiers": {(DOMAIN, self._config_entry.entry_id)} }


class BMWCE02PowerSensor(SensorEntity):
    _attr_device_class = SensorDeviceClass.POWER
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = UnitOfPower.KILO_WATT
    _attr_icon = "mdi:lightning-bolt"
    _attr_should_poll = False
    _attr_name: str
    _attr_unique_id: str

    def __init__(self, config_entry: ConfigEntry, controller: BMWCE02ChargeController):
        self._config_entry = config_entry
        self._controller = controller
        self._attr_name = f"{self._controller.device_name} Puissance de Charge"
        self._attr_unique_id = f"{config_entry.entry_id}_charging_power"

    @property
    def native_value(self) -> float | None:
        power_kw = self._controller.current_simulated_power_kw
        return round(power_kw, 3)

    async def async_added_to_hass(self) -> None:
        @callback
        def _update_callback():
            if self.hass: self.async_write_ha_state()
        self._controller.register_update_callback(_update_callback)

    @property
    def device_info(self):
        return {"identifiers": {(DOMAIN, self._config_entry.entry_id)}}