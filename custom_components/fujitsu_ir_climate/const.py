"""Constants for the Fujitsu IR Climate integration."""

from __future__ import annotations

from homeassistant.const import Platform

DOMAIN = "fujitsu_ir_climate"
PLATFORMS = [Platform.CLIMATE, Platform.BUTTON]

CONF_EMITTER_ENTITY_ID = "emitter_entity_id"
CONF_HUMIDITY_SENSOR = "humidity_sensor"
CONF_TEMPERATURE_SENSOR = "temperature_sensor"

DEFAULT_NAME = "Fujitsu Air Conditioner"
MANUFACTURER = "Fujitsu General"
MODEL = "Wall split (ARRAH2E IR protocol)"
