"""Fixtures for Fujitsu IR Climate tests."""

from __future__ import annotations

from homeassistant.components.infrared import (
    DATA_COMPONENT,
    InfraredCommand,
    InfraredEmitterEntity,
)
from homeassistant.const import CONF_NAME
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.setup import async_setup_component
import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.fujitsu_ir_climate.const import (
    CONF_EMITTER_ENTITY_ID,
    CONF_HUMIDITY_SENSOR,
    CONF_TEMPERATURE_SENSOR,
    DOMAIN,
)

EMITTER = "infrared.test_emitter"
TEMP_SENSOR = "sensor.room_temperature"
HUMIDITY_SENSOR = "sensor.room_humidity"


class MockEmitter(InfraredEmitterEntity):
    """Records the commands it is asked to send; set `fail` to make sends raise."""

    def __init__(self, entity_id: str = EMITTER) -> None:
        self.entity_id = entity_id
        self._attr_unique_id = entity_id
        self.commands: list[InfraredCommand] = []
        self.fail = False

    async def async_send_command(self, command: InfraredCommand) -> None:
        if self.fail:
            raise HomeAssistantError("transmit failed")
        self.commands.append(command)


async def add_emitter(hass: HomeAssistant, entity_id: str = EMITTER) -> MockEmitter:
    """Set up the infrared component (if needed) and add a mock emitter."""
    assert await async_setup_component(hass, "infrared", {})
    entity = MockEmitter(entity_id)
    await hass.data[DATA_COMPONENT].async_add_entities([entity])
    await hass.async_block_till_done()
    return entity


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations):
    """Load custom_components/ in every test."""
    return


@pytest.fixture
async def emitter(hass: HomeAssistant) -> MockEmitter:
    """A working infrared emitter entity."""
    entity = await add_emitter(hass)
    hass.states.async_set(TEMP_SENSOR, "25.5", {"unit_of_measurement": "°C"})
    hass.states.async_set(HUMIDITY_SENSOR, "61.2", {"unit_of_measurement": "%"})
    await hass.async_block_till_done()
    return entity


@pytest.fixture
def config_entry() -> MockConfigEntry:
    return MockConfigEntry(
        domain=DOMAIN,
        title="Bedroom AC",
        unique_id=f"bedroom_ac_{EMITTER}",
        data={
            CONF_NAME: "Bedroom AC",
            CONF_EMITTER_ENTITY_ID: EMITTER,
            CONF_TEMPERATURE_SENSOR: TEMP_SENSOR,
            CONF_HUMIDITY_SENSOR: HUMIDITY_SENSOR,
        },
    )


@pytest.fixture
async def init_integration(
    hass: HomeAssistant, emitter: MockEmitter, config_entry: MockConfigEntry
) -> MockConfigEntry:
    config_entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done()
    return config_entry
