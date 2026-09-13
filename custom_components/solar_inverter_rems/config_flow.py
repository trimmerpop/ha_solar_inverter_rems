import voluptuous as vol
from homeassistant import config_entries
from homeassistant.core import callback
from homeassistant.const import CONF_IP_ADDRESS, CONF_PORT, CONF_NAME, CONF_SCAN_INTERVAL
from .const import DOMAIN, CONF_SLAVE_ID, DEFAULT_NAME, DEFAULT_SCAN_INTERVAL, DEFAULT_PORT

class SolarInverterConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Solar Inverter REMS."""
    VERSION = 1

    async def async_step_user(self, user_input=None):
        """Handle the initial step."""
        errors = {}
        if user_input is not None:
            await self.async_set_unique_id(f"{user_input[CONF_IP_ADDRESS]}_{user_input[CONF_SLAVE_ID]}")
            self._abort_if_unique_id_configured()
            return self.async_create_entry(title=user_input[CONF_NAME], data=user_input)

        data_schema = vol.Schema({
            vol.Required(CONF_NAME, default=DEFAULT_NAME): str,
            vol.Required(CONF_IP_ADDRESS): str,
            vol.Required(CONF_PORT, default=DEFAULT_PORT): int,
            vol.Required(CONF_SLAVE_ID, default=1): int,
            vol.Optional(CONF_SCAN_INTERVAL, default=DEFAULT_SCAN_INTERVAL): int,
        })

        return self.async_show_form(step_id="user", data_schema=data_schema, errors=errors)

    @staticmethod
    @callback
    def async_get_options_flow(config_entry):
        return SolarInverterOptionsFlowHandler(config_entry)

class SolarInverterOptionsFlowHandler(config_entries.OptionsFlow):
    """Handle options flow for Solar Inverter REMS."""

    def __init__(self, config_entry):
        """Initialize options flow."""
        self._config_entry = config_entry

    async def async_step_init(self, user_input=None):
        """Manage the options."""
        if user_input is not None:
            return self.async_create_entry(title="", data=user_input)

        config = {**self._config_entry.data, **self._config_entry.options}

        data_schema = vol.Schema({
            vol.Required(CONF_IP_ADDRESS, default=config.get(CONF_IP_ADDRESS, "")): str,
            vol.Required(CONF_PORT, default=config.get(CONF_PORT, DEFAULT_PORT)): int,
            vol.Required(CONF_SLAVE_ID, default=config.get(CONF_SLAVE_ID, 1)): int,
            vol.Required(CONF_NAME, default=config.get(CONF_NAME, DEFAULT_NAME)): str,
            vol.Optional(CONF_SCAN_INTERVAL, default=config.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL)): int,
        })

        return self.async_show_form(step_id="init", data_schema=data_schema)