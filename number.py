import logging
from typing import Optional

from homeassistant.components.number import (
    NumberEntity,
    NumberDeviceClass,
    NumberMode,
)
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import PERCENTAGE

from .const import DOMAIN
from .sensor import BMWCE02ChargeController # Accès au contrôleur

_LOGGER = logging.getLogger(__name__)

async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the BMW CE-02 manual SoC number entity."""
    controller = hass.data[DOMAIN][config_entry.entry_id]["controller"]
    async_add_entities([BMWCE02ManualSoCNumber(config_entry, controller)])


class BMWCE02ManualSoCNumber(NumberEntity):
    """Representation of a Number entity to set the BMW CE-02 SoC manually."""
    _attr_should_poll = False # Les mises à jour sont poussées par le contrôleur
    _attr_device_class = NumberDeviceClass.BATTERY # Classe d'appareil sémantique
    _attr_mode = NumberMode.SLIDER # Ou NumberMode.BOX si vous préférez un champ de saisie
    _attr_native_unit_of_measurement = PERCENTAGE
    _attr_native_min_value = 0.0
    _attr_native_max_value = 100.0
    _attr_native_step = 1.0 # Pas d'incrémentation/décrémentation

    def __init__(self, config_entry: ConfigEntry, controller: BMWCE02ChargeController):
        self._config_entry = config_entry
        self._controller = controller
        self._attr_name = f"{self._controller.device_name} Manual SoC Input"
        self._attr_unique_id = f"{config_entry.entry_id}_manual_soc_input"
        # La valeur initiale sera récupérée via le callback après la restauration du contrôleur
        self._attr_native_value = self._controller.current_soc

    @property
    def native_value(self) -> float | None:
        """Return the current value."""
        return round(self._controller.current_soc, 1)

    async def async_set_native_value(self, value: float) -> None:
        """Update the current value."""
        await self._controller.async_set_current_soc(value)
        # Le contrôleur notifiera ensuite tous les auditeurs (y compris cette entité via _handle_controller_update)

    async def async_added_to_hass(self) -> None:
        """Register for updates from the controller."""
        @callback
        def _update_callback():
            """Handle updates from the controller."""
            new_value = round(self._controller.current_soc, 1)
            if self._attr_native_value != new_value:
                self._attr_native_value = new_value
                if self.hass: # Vérifie si l'entité est toujours attachée à hass
                    self.async_write_ha_state()
        
        self._controller.register_update_callback(_update_callback)
        # La valeur initiale est déjà définie dans __init__ et sera mise à jour par le premier appel de _update_callback

    @property
    def device_info(self):
        """Return device information to link this entity with the device."""
        return {
            "identifiers": {(DOMAIN, self._config_entry.entry_id)},
            "name": self._controller.device_name,
            "manufacturer": "BMW CE-02 Tracker (Custom)",
            "model": "CE-02 Simulated",
        }

    @property
    def icon(self):
        """Return the icon to use in the frontend."""
        return "mdi:percent-box-outline" # ou "mdi:numeric" ou autre icône pertinente