"""Config flow for Jeedom integration."""
import voluptuous as vol
from homeassistant import config_entries
from homeassistant.const import (
    CONF_HOST,
    CONF_PORT,
    CONF_API_KEY,
    CONF_NAME,
    CONF_PROTOCOL,
)
from homeassistant.data_entry_flow import FlowResult
from homeassistant.helpers import selector

from .const import (
    DOMAIN,
    DEFAULT_PORT,
    CONF_CONFIG_PATH,
    CONF_USE_JSONRPC,
    CONF_JSONRPC_FALLBACK,
    CONF_JSONRPC_URL,
    CONF_IMPORT_MODE,
    CONF_DOMAINS,
    IMPORT_MODE_NATIVE,
    IMPORT_MODE_MQTT,
    SUPPORTED_DOMAINS,
)

IMPORT_MODE_SELECTOR = selector.SelectSelector(
    selector.SelectSelectorConfig(
        options=[
            selector.SelectOptionDict(
                value=IMPORT_MODE_NATIVE, label="Native (Jeedom integration entities)"
            ),
            selector.SelectOptionDict(
                value=IMPORT_MODE_MQTT, label="MQTT entities (Home Assistant MQTT integration)"
            ),
        ],
        mode=selector.SelectSelectorMode.DROPDOWN,
    )
)

DOMAINS_SELECTOR = selector.SelectSelector(
    selector.SelectSelectorConfig(
        options=[selector.SelectOptionDict(value=d, label=d) for d in SUPPORTED_DOMAINS],
        multiple=True,
        mode=selector.SelectSelectorMode.DROPDOWN,
    )
)

DATA_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_HOST): str,
        vol.Optional(CONF_PORT, default=DEFAULT_PORT): int,
        vol.Required(CONF_API_KEY): str,
        vol.Optional(CONF_NAME, default="Jeedom"): str,
        vol.Optional(CONF_PROTOCOL, default="mqtt"): vol.In(["mqtt", "api"]),
        vol.Optional(CONF_IMPORT_MODE, default=IMPORT_MODE_NATIVE): IMPORT_MODE_SELECTOR,
        vol.Optional(CONF_DOMAINS, default=SUPPORTED_DOMAINS): DOMAINS_SELECTOR,
        vol.Optional(CONF_CONFIG_PATH): str,
        vol.Optional(CONF_USE_JSONRPC, default=True): bool,
        vol.Optional(CONF_JSONRPC_FALLBACK, default=True): bool,
        vol.Optional(CONF_JSONRPC_URL): str,
    }
)


class JeedomConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a Jeedom config flow."""

    VERSION = 1

    async def async_step_user(self, user_input=None) -> FlowResult:
        """Handle the initial step."""
        if user_input is None:
            return self.async_show_form(step_id="user", data_schema=DATA_SCHEMA)

        return self.async_create_entry(
            title=user_input[CONF_NAME],
            data=user_input,
        )

    @staticmethod
    def async_get_options_flow(config_entry):
        return JeedomOptionsFlowHandler(config_entry)


class JeedomOptionsFlowHandler(config_entries.OptionsFlow):
    """Handle Jeedom options flow."""

    def __init__(self, config_entry: config_entries.ConfigEntry) -> None:
        self._entry = config_entry

    async def async_step_init(self, user_input=None) -> FlowResult:
        """Manage the Jeedom options."""
        if user_input is not None:
            return self.async_create_entry(title="", data=user_input)

        data = self._entry.data
        options = self._entry.options

        schema = vol.Schema(
            {
                vol.Optional(
                    CONF_IMPORT_MODE,
                    default=options.get(
                        CONF_IMPORT_MODE, data.get(CONF_IMPORT_MODE, IMPORT_MODE_NATIVE)
                    ),
                ): IMPORT_MODE_SELECTOR,
                vol.Optional(
                    CONF_DOMAINS,
                    default=options.get(
                        CONF_DOMAINS, data.get(CONF_DOMAINS, SUPPORTED_DOMAINS)
                    ),
                ): DOMAINS_SELECTOR,
                vol.Optional(
                    CONF_CONFIG_PATH,
                    default=options.get(CONF_CONFIG_PATH, data.get(CONF_CONFIG_PATH, "")),
                ): str,
                vol.Optional(
                    CONF_USE_JSONRPC,
                    default=options.get(CONF_USE_JSONRPC, data.get(CONF_USE_JSONRPC, True)),
                ): bool,
                vol.Optional(
                    CONF_JSONRPC_FALLBACK,
                    default=options.get(
                        CONF_JSONRPC_FALLBACK, data.get(CONF_JSONRPC_FALLBACK, True)
                    ),
                ): bool,
                vol.Optional(
                    CONF_JSONRPC_URL,
                    default=options.get(CONF_JSONRPC_URL, data.get(CONF_JSONRPC_URL, "")),
                ): str,
            }
        )

        return self.async_show_form(step_id="init", data_schema=schema)
