"""Config flow for Fujitsu IR Climate."""

from __future__ import annotations

from typing import Any

from homeassistant import config_entries
from homeassistant.components import infrared
from homeassistant.const import CONF_NAME
from homeassistant.core import callback
from homeassistant.helpers import selector
from homeassistant.util import slugify
import voluptuous as vol

from .const import (
    CONF_EMITTER_ENTITY_ID,
    CONF_HUMIDITY_SENSOR,
    CONF_TEMPERATURE_SENSOR,
    DEFAULT_NAME,
    DOMAIN,
)


class FujitsuIRClimateConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Create a Fujitsu IR climate device."""

    VERSION = 1

    @staticmethod
    @callback
    def async_get_options_flow(
        config_entry: config_entries.ConfigEntry,
    ) -> config_entries.OptionsFlow:
        return FujitsuIRClimateOptionsFlow()

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.ConfigFlowResult:
        emitters = set(infrared.async_get_emitters(self.hass))
        if not emitters:
            return self.async_abort(reason="no_emitters")

        errors: dict[str, str] = {}
        if user_input is not None:
            if user_input[CONF_EMITTER_ENTITY_ID] not in emitters:
                errors[CONF_EMITTER_ENTITY_ID] = "invalid_emitter"
            else:
                name = user_input[CONF_NAME]
                await self.async_set_unique_id(
                    f"{slugify(name)}_{user_input[CONF_EMITTER_ENTITY_ID]}"
                )
                self._abort_if_unique_id_configured()
                return self.async_create_entry(title=name, data=user_input)

        return self.async_show_form(
            step_id="user", data_schema=_schema(user_input or {}), errors=errors
        )


class FujitsuIRClimateOptionsFlow(config_entries.OptionsFlow):
    """Change the emitter or room sensors."""

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            if user_input[CONF_EMITTER_ENTITY_ID] not in set(
                infrared.async_get_emitters(self.hass)
            ):
                errors[CONF_EMITTER_ENTITY_ID] = "invalid_emitter"
            else:
                for key in (CONF_TEMPERATURE_SENSOR, CONF_HUMIDITY_SENSOR):
                    user_input.setdefault(key, None)
                return self.async_create_entry(title="", data=user_input)

        defaults = user_input or {**self.config_entry.data, **self.config_entry.options}
        return self.async_show_form(step_id="init", data_schema=_schema(defaults), errors=errors)


def _schema(defaults: dict[str, Any]) -> vol.Schema:
    sensor = selector.EntitySelector(selector.EntitySelectorConfig(domain="sensor"))
    return vol.Schema(
        {
            vol.Required(CONF_NAME, default=defaults.get(CONF_NAME, DEFAULT_NAME)): str,
            vol.Required(
                CONF_EMITTER_ENTITY_ID,
                description={"suggested_value": defaults.get(CONF_EMITTER_ENTITY_ID)},
            ): selector.EntitySelector(selector.EntitySelectorConfig(domain="infrared")),
            vol.Optional(
                CONF_TEMPERATURE_SENSOR,
                description={"suggested_value": defaults.get(CONF_TEMPERATURE_SENSOR)},
            ): sensor,
            vol.Optional(
                CONF_HUMIDITY_SENSOR,
                description={"suggested_value": defaults.get(CONF_HUMIDITY_SENSOR)},
            ): sensor,
        }
    )
