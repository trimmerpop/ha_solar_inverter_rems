"""Config flow for the Solar Inverter REMS integration."""

from __future__ import annotations

from typing import Any

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.const import (
    CONF_IP_ADDRESS,
    CONF_NAME,
    CONF_PORT,
    CONF_SCAN_INTERVAL,
)
from homeassistant.core import callback
from homeassistant.helpers.selector import (
    NumberSelector,
    NumberSelectorConfig,
    NumberSelectorMode,
)

from .const import (
    CONF_SLAVE_ID,
    DEFAULT_NAME,
    DEFAULT_PORT,
    DEFAULT_SCAN_INTERVAL,
    DOMAIN,
)

# Explicit selectors are used so the frontend renders plain numeric input
# boxes instead of sliders (which voluptuous Range would produce).
PORT_SELECTOR = NumberSelector(
    NumberSelectorConfig(min=1, max=65535, step=1, mode=NumberSelectorMode.BOX)
)
SLAVE_ID_SELECTOR = NumberSelector(
    NumberSelectorConfig(min=1, max=247, step=1, mode=NumberSelectorMode.BOX)
)
SCAN_INTERVAL_SELECTOR = NumberSelector(
    NumberSelectorConfig(
        min=5,
        step=1,
        mode=NumberSelectorMode.BOX,
        unit_of_measurement="s",
    )
)


class SolarInverterConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Solar Inverter REMS."""

    VERSION = 2

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.ConfigFlowResult:
        """Handle the initial step."""
        if user_input is not None:
            await self.async_set_unique_id(
                f"{user_input[CONF_IP_ADDRESS]}_{user_input[CONF_SLAVE_ID]}"
            )
            self._abort_if_unique_id_configured()
            return self.async_create_entry(title=user_input[CONF_NAME], data=user_input)

        data_schema = vol.Schema(
            {
                vol.Required(CONF_NAME, default=DEFAULT_NAME): str,
                vol.Required(CONF_IP_ADDRESS): str,
                vol.Required(CONF_PORT, default=DEFAULT_PORT): PORT_SELECTOR,
                vol.Required(CONF_SLAVE_ID, default=1): SLAVE_ID_SELECTOR,
                vol.Optional(
                    CONF_SCAN_INTERVAL, default=DEFAULT_SCAN_INTERVAL
                ): SCAN_INTERVAL_SELECTOR,
            }
        )

        return self.async_show_form(step_id="user", data_schema=data_schema)

    @staticmethod
    @callback
    def async_get_options_flow(
        config_entry: config_entries.ConfigEntry,
    ) -> config_entries.OptionsFlow:
        """Create the options flow."""
        return SolarInverterOptionsFlowHandler()


class SolarInverterOptionsFlowHandler(config_entries.OptionsFlowWithReload):
    """Handle options flow for Solar Inverter REMS."""

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.ConfigFlowResult:
        """Manage the options."""
        if user_input is not None:
            if (
                user_input.get(CONF_NAME)
                and user_input[CONF_NAME] != self.config_entry.title
            ):
                self.hass.config_entries.async_update_entry(
                    self.config_entry, title=user_input[CONF_NAME]
                )
            return self.async_create_entry(data=user_input)

        config = {**self.config_entry.data, **self.config_entry.options}

        data_schema = vol.Schema(
            {
                vol.Required(
                    CONF_IP_ADDRESS, default=config.get(CONF_IP_ADDRESS, "")
                ): str,
                vol.Required(
                    CONF_PORT, default=config.get(CONF_PORT, DEFAULT_PORT)
                ): PORT_SELECTOR,
                vol.Required(
                    CONF_SLAVE_ID, default=config.get(CONF_SLAVE_ID, 1)
                ): SLAVE_ID_SELECTOR,
                vol.Required(
                    CONF_NAME, default=config.get(CONF_NAME, DEFAULT_NAME)
                ): str,
                vol.Optional(
                    CONF_SCAN_INTERVAL,
                    default=config.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL),
                ): SCAN_INTERVAL_SELECTOR,
            }
        )

        return self.async_show_form(step_id="init", data_schema=data_schema)
