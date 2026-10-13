"""Config flow for Fujitsu IR Climate."""

from __future__ import annotations

from typing import Any

from homeassistant.components.infrared import async_get_emitters
from homeassistant.components.sensor import SensorDeviceClass
from homeassistant.config_entries import (
    ConfigEntry,
    ConfigFlow,
    ConfigFlowResult,
    OptionsFlow,
)
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


def _emitter_selector(emitters: list[str]) -> selector.EntitySelector:
    return selector.EntitySelector(
        selector.EntitySelectorConfig(domain="infrared", include_entities=emitters)
    )


def _sensor_schema(defaults: dict[str, Any]) -> dict[vol.Marker, Any]:
    schema: dict[vol.Marker, Any] = {}
    for key, device_class in (
        (CONF_TEMPERATURE_SENSOR, SensorDeviceClass.TEMPERATURE),
        (CONF_HUMIDITY_SENSOR, SensorDeviceClass.HUMIDITY),
    ):
        schema[vol.Optional(key, description={"suggested_value": defaults.get(key)})] = (
            selector.EntitySelector(
                selector.EntitySelectorConfig(domain="sensor", device_class=device_class)
            )
        )
    return schema


class FujitsuIRClimateConfigFlow(ConfigFlow, domain=DOMAIN):
    """Create a Fujitsu IR climate device."""

    VERSION = 1

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> OptionsFlow:
        return FujitsuIRClimateOptionsFlow()

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        emitters = async_get_emitters(self.hass)
        if not emitters:
            return self.async_abort(reason="no_emitters")

        errors: dict[str, str] = {}
        if user_input is not None:
            emitter = user_input[CONF_EMITTER_ENTITY_ID]
            if emitter not in emitters:
                errors[CONF_EMITTER_ENTITY_ID] = "invalid_emitter"
            else:
                # One air conditioner per emitter: two units would both obey its frames.
                self._async_abort_entries_match({CONF_EMITTER_ENTITY_ID: emitter})
                await self.async_set_unique_id(f"{slugify(user_input[CONF_NAME])}_{emitter}")
                self._abort_if_unique_id_configured()
                return self.async_create_entry(title=user_input[CONF_NAME], data=user_input)

        defaults = user_input or {}
        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_NAME, default=defaults.get(CONF_NAME, DEFAULT_NAME)): str,
                    vol.Required(
                        CONF_EMITTER_ENTITY_ID,
                        description={"suggested_value": defaults.get(CONF_EMITTER_ENTITY_ID)},
                    ): _emitter_selector(emitters),
                    **_sensor_schema(defaults),
                }
            ),
            errors=errors,
        )

    async def async_step_reconfigure(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Point the air conditioner at a different (or renamed) emitter."""

        entry = self._get_reconfigure_entry()
        emitters = async_get_emitters(self.hass)
        errors: dict[str, str] = {}
        if user_input is not None:
            emitter = user_input[CONF_EMITTER_ENTITY_ID]
            if emitter not in emitters:
                errors[CONF_EMITTER_ENTITY_ID] = "invalid_emitter"
            elif emitter != entry.data[CONF_EMITTER_ENTITY_ID]:
                self._async_abort_entries_match({CONF_EMITTER_ENTITY_ID: emitter})
            if not errors:
                return self.async_update_reload_and_abort(entry, data_updates=user_input)

        return self.async_show_form(
            step_id="reconfigure",
            data_schema=vol.Schema(
                {
                    vol.Required(
                        CONF_EMITTER_ENTITY_ID,
                        default=entry.data[CONF_EMITTER_ENTITY_ID],
                    ): _emitter_selector(emitters),
                }
            ),
            errors=errors,
        )


class FujitsuIRClimateOptionsFlow(OptionsFlow):
    """Change the room sensors."""

    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        if user_input is not None:
            for key in (CONF_TEMPERATURE_SENSOR, CONF_HUMIDITY_SENSOR):
                user_input.setdefault(key, None)
            return self.async_create_entry(data=user_input)

        current = {**self.config_entry.data, **self.config_entry.options}
        return self.async_show_form(step_id="init", data_schema=vol.Schema(_sensor_schema(current)))
