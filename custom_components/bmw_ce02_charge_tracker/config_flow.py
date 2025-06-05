"""Config flow for BMW CE-02 Charge Tracker."""
import voluptuous as vol
from homeassistant import config_entries
from homeassistant.components.sensor import SensorDeviceClass
from homeassistant.helpers.selector import (
    TextSelector,
    TextSelectorConfig,
    TextSelectorType,
    EntitySelector,
    EntitySelectorConfig,
    NumberSelector,
    NumberSelectorConfig,
    NumberSelectorMode,
)
from homeassistant.const import UnitOfPower

from .const import (
    DOMAIN,
    CONF_DEVICE_NAME,
    DEFAULT_NAME,
    CONF_POWER_SENSOR_ENTITY_ID,
    CONF_MIN_CHARGING_POWER,
    DEFAULT_MIN_CHARGING_POWER_W,
)

class BMWCE02ConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for BMW CE-02 Charge Tracker."""
    VERSION = 1

    async def async_step_user(self, user_input=None):
        """Handle the initial step."""
        errors = {}
        if user_input is not None:
            return self.async_create_entry(title=user_input[CONF_DEVICE_NAME], data=user_input)

        data_schema=vol.Schema({
            vol.Required(CONF_DEVICE_NAME, default=DEFAULT_NAME): TextSelector(
                TextSelectorConfig(type=TextSelectorType.TEXT)
            ),
            vol.Required(CONF_POWER_SENSOR_ENTITY_ID): EntitySelector(
                EntitySelectorConfig(
                    domain="sensor",
                    device_class=SensorDeviceClass.POWER
                )
            ),
            vol.Required(
                CONF_MIN_CHARGING_POWER,
                default=DEFAULT_MIN_CHARGING_POWER_W,
            ): NumberSelector(
                NumberSelectorConfig(
                    min=0,
                    max=2500,
                    step=0.1,
                    mode=NumberSelectorMode.BOX,
                    unit_of_measurement=UnitOfPower.WATT,
                )
            ),
        })

        return self.async_show_form(
            step_id="user",
            data_schema=data_schema,
            errors=errors
        )