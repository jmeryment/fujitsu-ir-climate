"""Config, reconfigure and options flow tests."""

from homeassistant import config_entries
from homeassistant.const import CONF_NAME
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType, InvalidData
from homeassistant.setup import async_setup_component
import pytest

from custom_components.fujitsu_ir_climate.const import (
    CONF_EMITTER_ENTITY_ID,
    CONF_HUMIDITY_SENSOR,
    CONF_TEMPERATURE_SENSOR,
    DOMAIN,
)

from .conftest import EMITTER, HUMIDITY_SENSOR, TEMP_SENSOR, add_emitter


async def _start(hass):
    return await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )


async def test_user_flow_creates_entry(hass: HomeAssistant, emitter) -> None:
    result = await _start(hass)
    assert result["type"] is FlowResultType.FORM

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {
            CONF_NAME: "Bedroom AC",
            CONF_EMITTER_ENTITY_ID: EMITTER,
            CONF_TEMPERATURE_SENSOR: TEMP_SENSOR,
        },
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == "Bedroom AC"
    assert result["data"][CONF_EMITTER_ENTITY_ID] == EMITTER
    assert result["result"].unique_id == f"bedroom_ac_{EMITTER}"


async def test_second_ac_on_same_emitter_aborts(hass: HomeAssistant, init_integration) -> None:
    result = await _start(hass)
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_NAME: "Another name", CONF_EMITTER_ENTITY_ID: EMITTER}
    )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "already_configured"


async def test_user_flow_without_emitters_aborts(hass: HomeAssistant) -> None:
    assert await async_setup_component(hass, "infrared", {})
    result = await _start(hass)
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "no_emitters"


async def test_user_flow_rejects_non_emitter(hass: HomeAssistant, emitter) -> None:
    result = await _start(hass)
    with pytest.raises(InvalidData):  # the selector only offers emitter entities
        await hass.config_entries.flow.async_configure(
            result["flow_id"], {CONF_NAME: "AC", CONF_EMITTER_ENTITY_ID: "infrared.missing"}
        )


async def test_reconfigure_changes_emitter(hass: HomeAssistant, init_integration) -> None:
    other = await add_emitter(hass, "infrared.other_emitter")
    result = await init_integration.start_reconfigure_flow(hass)
    assert result["type"] is FlowResultType.FORM
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_EMITTER_ENTITY_ID: other.entity_id}
    )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "reconfigure_successful"
    assert init_integration.data[CONF_EMITTER_ENTITY_ID] == other.entity_id
    await hass.async_block_till_done()

    await hass.services.async_call(
        "climate", "turn_on", {"entity_id": "climate.bedroom_ac"}, blocking=True
    )
    assert len(other.commands) == 1


async def test_options_flow_changes_sensors(hass: HomeAssistant, init_integration) -> None:
    result = await hass.config_entries.options.async_init(init_integration.entry_id)
    assert result["type"] is FlowResultType.FORM
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {CONF_HUMIDITY_SENSOR: HUMIDITY_SENSOR}
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    await hass.async_block_till_done()
    assert init_integration.options[CONF_TEMPERATURE_SENSOR] is None
    state = hass.states.get("climate.bedroom_ac")
    assert state.attributes.get("current_temperature") is None
    assert state.attributes["current_humidity"] == 61.2
