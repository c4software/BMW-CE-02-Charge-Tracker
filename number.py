"""Number platform for BMW CE-02 Charge Tracker, now handling SoC display and input."""
import logging
from typing import Optional
from datetime import datetime, timedelta, timezone 

from homeassistant.components.number import (
    NumberEntity,
    NumberDeviceClass,
    NumberMode,
    RestoreNumber,
)
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import PERCENTAGE

from .const import (
    DOMAIN,
    BATTERY_CAPACITY_KWH, 
    SOC_THRESHOLD_PHASE2,
    CHARGER_POWER_PHASE1_KW,
    CHARGER_POWER_PHASE2_KW,
)
from .sensor import BMWCE02ChargeController 

_LOGGER = logging.getLogger(__name__)

async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the BMW CE-02 SoC number entity."""
    controller = hass.data[DOMAIN][config_entry.entry_id]["controller"]
    async_add_entities([BMWCE02SoCNumberEntity(config_entry, controller)])


class BMWCE02SoCNumberEntity(RestoreNumber, NumberEntity): # Hérite de RestoreNumber
    """Representation of the BMW CE-02 SoC entity (display and input)."""
    _attr_should_poll = False
    _attr_device_class = NumberDeviceClass.BATTERY
    _attr_mode = NumberMode.SLIDER 
    _attr_native_unit_of_measurement = PERCENTAGE
    _attr_native_min_value = 0.0
    _attr_native_max_value = 100.0
    _attr_native_step = 1.0

    def __init__(self, config_entry: ConfigEntry, controller: BMWCE02ChargeController):
        self._config_entry = config_entry
        self._controller = controller
        self._attr_name = f"{self._controller.device_name} SoC" # Nom plus direct
        self._attr_unique_id = f"{config_entry.entry_id}_soc_number_input" # ID unique mis à jour

    async def async_added_to_hass(self) -> None:
        """Restore last state and controller session state."""
        await super().async_added_to_hass() # Important pour RestoreNumber

        last_number_data = await self.async_get_last_number_data()
        if last_number_data and last_number_data.native_value is not None:
            restored_soc = float(last_number_data.native_value)
            self._controller.current_soc = restored_soc # Met à jour le SoC du contrôleur
            _LOGGER.info(f"Restored SoC for {self._controller.device_name} to {self._controller.current_soc:.1f}% from NumberEntity state.")

            # Restaure l'état de la session du contrôleur depuis les attributs de CETTE entité
            if hasattr(last_number_data, 'extra_attributes') and last_number_data.extra_attributes:
                attrs = last_number_data.extra_attributes
                self._controller.persisted_is_charging = attrs.get("persisted_is_charging_flag", False)
                self._controller.persisted_soc_at_charge_start = attrs.get("persisted_soc_at_charge_start_val", self._controller.current_soc)
                self._controller.persisted_charge_start_time_str = attrs.get("persisted_charge_start_time_val")
                self._controller.persisted_last_soc_update_time_str = attrs.get("persisted_last_soc_update_time_val")
                if self._controller.persisted_is_charging:
                     _LOGGER.info(f"Restored persisted charging session flags for {self._controller.device_name} from SoC NumberEntity attributes.")
        else:
            # Si pas d'état pour NumberEntity, le current_soc du contrôleur (avec sa valeur par défaut de 50.0) est utilisé.
            if self._controller.current_soc is None: self._controller.current_soc = 50.0 # Sécurité
            _LOGGER.info(f"No NumberEntity state found for {self._controller.device_name}, SoC uses controller's current value: {self._controller.current_soc:.1f}%")
        
        self._attr_native_value = round(self._controller.current_soc, 1) # Assure que la valeur native est à jour

        # S'enregistre pour les mises à jour du contrôleur
        @callback
        def _update_callback():
            new_value = round(self._controller.current_soc, 1)
            if self._attr_native_value != new_value:
                self._attr_native_value = new_value
                if self.hass: self.async_write_ha_state()
        
        self._controller.register_update_callback(_update_callback)

    @property
    def native_value(self) -> float | None:
        """Return the current SoC from the controller."""
        return round(self._controller.current_soc, 1)

    async def async_set_native_value(self, value: float) -> None:
        """Update the current SoC value in the controller."""
        await self._controller.async_set_current_soc(value)
        self._attr_native_value = round(value, 1) # Assure la mise à jour pour RestoreNumber
        self.async_write_ha_state() # Force l'écriture de l'état

    @property
    def extra_state_attributes(self):
        """Return the state attributes, now including all previous SoC sensor attributes."""
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

        current_soc_val = float(self.native_value if self.native_value is not None else 0.0)
        attrs["current_charge_power_kw"] = (CHARGER_POWER_PHASE1_KW if current_soc_val < SOC_THRESHOLD_PHASE2 else CHARGER_POWER_PHASE2_KW) if self._controller.is_charging and current_soc_val < 100 else 0
        
        attrs["time_at_80_pct"] = None
        attrs["time_at_100_pct"] = None

        if self._controller.is_charging:
            now_utc = datetime.now(timezone.utc)
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
        else: 
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

    @property
    def icon(self):
        """Return the icon to use in the frontend, if any."""
        soc = self.native_value
        if soc is None: return "mdi:battery-unknown"
        
        base_icon = "mdi:battery"
        if self._controller.is_charging:
            base_icon = "mdi:battery-charging"
        
        if soc >= 95: return f"{base_icon}" if self._controller.is_charging else "mdi:battery" # mdi:battery-100 n'existe pas pour charging
        if soc >= 85: return f"{base_icon}-90"
        if soc >= 75: return f"{base_icon}-80"
        if soc >= 65: return f"{base_icon}-70"
        if soc >= 55: return f"{base_icon}-60"
        if soc >= 45: return f"{base_icon}-50"
        if soc >= 35: return f"{base_icon}-40"
        if soc >= 25: return f"{base_icon}-30"
        if soc >= 15: return f"{base_icon}-20"
        if soc >= 5: return f"{base_icon}-10"
        return f"{base_icon}-outline"