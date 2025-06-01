import logging
from datetime import datetime, timedelta, timezone
import voluptuous as vol

from homeassistant.components.sensor import (
    RestoreSensor,
    SensorDeviceClass,
    SensorStateClass,
)
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback, async_get_current_platform
from homeassistant.config_entries import ConfigEntry
from homeassistant.helpers.event import async_track_time_interval
from homeassistant.const import (
    PERCENTAGE,
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

        self.current_soc = 50.0
        self.is_charging = False

        self._soc_at_charge_start = 0.0
        self._charge_start_time = None
        self._last_soc_update_time = None

        self.persisted_is_charging = False
        self.persisted_soc_at_charge_start = 0.0
        self.persisted_charge_start_time_str = None
        self.persisted_last_soc_update_time_str = None

        self._update_callbacks = []
        self._listeners = []

    async def async_initialize_listeners(self):
        """Initialize listeners. Called after sensor state restoration."""
        self.async_unsubscribe_listeners() # Nettoie les anciens listeners au cas où

        if self.persisted_is_charging:
            self.is_charging = True
            self._soc_at_charge_start = self.persisted_soc_at_charge_start
            try:
                self._charge_start_time = datetime.fromisoformat(self.persisted_charge_start_time_str) if self.persisted_charge_start_time_str else datetime.now(timezone.utc)
                self._last_soc_update_time = datetime.fromisoformat(self.persisted_last_soc_update_time_str) if self.persisted_last_soc_update_time_str else self._charge_start_time
                _LOGGER.info(f"{self.device_name} charging state RESTORED to ON from persisted data. SoC at recorded start: {self._soc_at_charge_start:.1f}%. Current SoC: {self.current_soc:.1f}%")
            except (ValueError, TypeError) as e:
                _LOGGER.warning(f"Failed to parse persisted date string for {self.device_name}: {e}. Resetting session times.")
                self._charge_start_time = datetime.now(timezone.utc)
                self._last_soc_update_time = self._charge_start_time
        else:
            self.is_charging = False

        self._listeners.append(
            async_track_time_interval(self.hass, self._async_update_soc_calculation, timedelta(seconds=UPDATE_INTERVAL_CHARGING_SECONDS))
        )
        self._notify_updates() # Notifie les entités de l'état (potentiellement restauré)

    def async_unsubscribe_listeners(self):
        for unsub_listener in self._listeners:
            unsub_listener()
        self._listeners.clear()

    def start_charging_manual(self):
        """Manually start the charging process via switch/service."""
        if not self.is_charging:
            self.is_charging = True
            self._soc_at_charge_start = self.current_soc
            self._charge_start_time = datetime.now(timezone.utc)
            self._last_soc_update_time = self._charge_start_time
            
            self.persisted_is_charging = True
            self.persisted_soc_at_charge_start = self._soc_at_charge_start
            self.persisted_charge_start_time_str = self._charge_start_time.isoformat()
            self.persisted_last_soc_update_time_str = self._last_soc_update_time.isoformat()

            _LOGGER.info(f"{self.device_name} charging MANUALLY STARTED. SoC at start: {self._soc_at_charge_start:.1f}%")
            self._notify_updates()

    def stop_charging_manual(self):
        """Manually stop the charging process via switch/service."""
        if self.is_charging:
            self.is_charging = False
            self.persisted_is_charging = False
            self._update_soc_calculation_logic(final_update=True)
            _LOGGER.info(f"{self.device_name} charging MANUALLY STOPPED. Final SoC: {self.current_soc:.1f}%")
            self._notify_updates()

    async def _async_update_soc_calculation(self, now=None):
        if not self.is_charging or self._charge_start_time is None:
            return
        self._update_soc_calculation_logic()
        self._notify_updates()

    def _update_soc_calculation_logic(self, final_update=False):
        if (not self.is_charging and not final_update) or self.current_soc >= 100:
            if self.current_soc >= 100 and self.is_charging:
                 _LOGGER.debug(f"{self.device_name} at 100% SoC. No further SoC increase calculated.")
            return

        if self._last_soc_update_time is None:
            self._last_soc_update_time = datetime.now(timezone.utc)
            if self._charge_start_time is not None:
                 self._last_soc_update_time = self._charge_start_time
            else:
                 _LOGGER.warning(f"Charge start time is None for {self.device_name} during SoC calculation. Resetting last_soc_update_time.")
                 return # Ne pas continuer si _charge_start_time est None ici

        current_time = datetime.now(timezone.utc)
        time_delta_seconds = (current_time - self._last_soc_update_time).total_seconds()

        if time_delta_seconds <= 1:
            return

        charge_power_kw = CHARGER_POWER_PHASE1_KW if self.current_soc < SOC_THRESHOLD_PHASE2 else CHARGER_POWER_PHASE2_KW
        energy_added_kwh = charge_power_kw * (time_delta_seconds / 3600.0)
        soc_added = (energy_added_kwh / BATTERY_CAPACITY_KWH) * 100.0

        if soc_added > 0:
            new_soc = self.current_soc + soc_added
            self.current_soc = min(100.0, new_soc)
            _LOGGER.debug(f"{self.device_name} SoC update: Added {soc_added:.3f}%. New SoC: {self.current_soc:.1f}%. Power: {charge_power_kw} kW. Delta t: {time_delta_seconds:.1f}s")
        
        self._last_soc_update_time = current_time
        self.persisted_last_soc_update_time_str = current_time.isoformat()

    def register_update_callback(self, callback_func):
        if callback_func not in self._update_callbacks:
            self._update_callbacks.append(callback_func)
        callback_func() 

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
            self._notify_updates()
        else:
            _LOGGER.warning(f"Invalid SoC value for manual set: {soc_value}")


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the BMW CE-02 SoC sensor."""
    controller = hass.data[DOMAIN][config_entry.entry_id]["controller"]
    soc_sensor = BMWCE02SoCSensor(config_entry, controller)
    async_add_entities([soc_sensor], True) # True pour update_before_add


class BMWCE02SoCSensor(RestoreSensor, SensorEntity):
    """Representation of the BMW CE-02 Estimated SoC Sensor."""
    _attr_device_class = SensorDeviceClass.BATTERY
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = PERCENTAGE
    _attr_should_poll = False

    def __init__(self, config_entry: ConfigEntry, controller: BMWCE02ChargeController):
        self._config_entry = config_entry
        self._controller = controller
        self._attr_name = f"{self._controller.device_name} Estimated SoC"
        self._attr_unique_id = f"{config_entry.entry_id}_estimated_soc"
        self._attr_native_value = self._controller.current_soc

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
                if self._controller.persisted_is_charging:
                     _LOGGER.info(f"Restored persisted charging session flags for {self._controller.device_name}.")
        else:
            self._controller.current_soc = 50.0 
            _LOGGER.info(f"No SoC state found for {self._controller.device_name}, defaulting to {self._controller.current_soc:.1f}%")
        
        self._attr_native_value = round(self._controller.current_soc, 1)

        self._controller.register_update_callback(self._handle_controller_update)

        platform = async_get_current_platform()
        platform.async_register_entity_service(
            "set_current_soc",
            {vol.Required("soc"): vol.All(vol.Coerce(float), vol.Range(min=0, max=100))},
            self._controller.async_set_current_soc,
        )

    @callback
    def _handle_controller_update(self):
        self._attr_native_value = round(self._controller.current_soc, 1)
        self.async_write_ha_state()

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

        attrs["duration_to_80_pct_hours"] = None
        attrs["time_at_80_pct"] = None
        attrs["duration_to_100_pct_hours"] = None
        attrs["time_at_100_pct"] = None

        if self._controller.is_charging:
            now_utc = datetime.now(timezone.utc)
            if current_soc_val < SOC_THRESHOLD_PHASE2:
                soc_needed_to_80 = SOC_THRESHOLD_PHASE2 - current_soc_val
                if CHARGER_POWER_PHASE1_KW > 0:
                    duration_to_80_hours = (soc_needed_to_80 / 100.0 * BATTERY_CAPACITY_KWH) / CHARGER_POWER_PHASE1_KW
                    if duration_to_80_hours >= 0:
                       attrs["duration_to_80_pct_hours"] = round(duration_to_80_hours, 2)
                       attrs["time_at_80_pct"] = (now_utc + timedelta(hours=duration_to_80_hours)).isoformat()
            elif current_soc_val < 100: # Déjà >= 80 mais pas 100
                attrs["duration_to_80_pct_hours"] = "Atteint"
                attrs["time_at_80_pct"] = "Atteint"


            if current_soc_val < 100.0:
                total_duration_to_100_hours = 0.0
                can_charge_to_100 = True
                if current_soc_val < SOC_THRESHOLD_PHASE2:
                    soc_to_reach_phase2_from_current = SOC_THRESHOLD_PHASE2 - current_soc_val
                    if CHARGER_POWER_PHASE1_KW > 0:
                        duration_in_phase1 = (soc_to_reach_phase2_from_current / 100.0 * BATTERY_CAPACITY_KWH) / CHARGER_POWER_PHASE1_KW
                        total_duration_to_100_hours += duration_in_phase1
                    else: can_charge_to_100 = False
                    
                    if can_charge_to_100:
                        soc_in_phase2_to_charge = 100.0 - SOC_THRESHOLD_PHASE2
                        if CHARGER_POWER_PHASE2_KW > 0:
                            duration_in_phase2 = (soc_in_phase2_to_charge / 100.0 * BATTERY_CAPACITY_KWH) / CHARGER_POWER_PHASE2_KW
                            total_duration_to_100_hours += duration_in_phase2
                        elif soc_in_phase2_to_charge > 0 : can_charge_to_100 = False
                else: # current_soc_val >= SOC_THRESHOLD_PHASE2
                    soc_to_reach_100_in_phase2 = 100.0 - current_soc_val
                    if CHARGER_POWER_PHASE2_KW > 0:
                        duration_in_phase2 = (soc_to_reach_100_in_phase2 / 100.0 * BATTERY_CAPACITY_KWH) / CHARGER_POWER_PHASE2_KW
                        total_duration_to_100_hours += duration_in_phase2
                    elif soc_to_reach_100_in_phase2 > 0: can_charge_to_100 = False
                
                if not can_charge_to_100:
                    attrs["duration_to_100_pct_hours"] = None
                    attrs["time_at_100_pct"] = None
                elif total_duration_to_100_hours >= 0:
                    attrs["duration_to_100_pct_hours"] = round(total_duration_to_100_hours, 2)
                    attrs["time_at_100_pct"] = (now_utc + timedelta(hours=total_duration_to_100_hours)).isoformat()
        
        if current_soc_val >= 100.0: # Vérification finale, même si pas en charge
            attrs["duration_to_100_pct_hours"] = "Pleine"
            attrs["time_at_100_pct"] = "Pleine"
        if current_soc_val >= SOC_THRESHOLD_PHASE2:
            attrs["duration_to_80_pct_hours"] = "Atteint" # Remplacera si déjà à 80+ et pas en charge
            attrs["time_at_80_pct"] = "Atteint"
            
        return attrs

    @property
    def device_info(self):
        return {
            "identifiers": {(DOMAIN, self._config_entry.entry_id)},
            "name": self._controller.device_name,
            "manufacturer": "BMW CE-02 Tracker (Custom)",
            "model": "CE-02 Simulated",
        }