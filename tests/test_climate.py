"""Climate and button entity tests: what is sent through the emitter."""

from datetime import timedelta

from homeassistant.components.climate import (
    ATTR_FAN_MODE,
    ATTR_HVAC_MODE,
    ATTR_PRESET_MODE,
    ATTR_SWING_MODE,
    DOMAIN as CLIMATE,
    HVACMode,
)
from homeassistant.const import ATTR_ENTITY_ID, ATTR_TEMPERATURE, STATE_UNAVAILABLE
from homeassistant.core import HomeAssistant, State
from homeassistant.exceptions import HomeAssistantError
from homeassistant.util import dt as dt_util
import pytest
from pytest_homeassistant_custom_component.common import (
    async_fire_time_changed,
    mock_restore_cache,
)

from custom_components.fujitsu_ir_climate import ir_protocol as p

from .conftest import EMITTER

ENTITY = "climate.bedroom_ac"


async def _call(hass, service, **data):
    await hass.services.async_call(
        CLIMATE, service, {ATTR_ENTITY_ID: ENTITY, **data}, blocking=True
    )


def _frames(emitter):
    return [c.frame.hex() for c in emitter.commands]


async def test_initial_state(hass: HomeAssistant, init_integration, emitter) -> None:
    state = hass.states.get(ENTITY)
    assert state.state == HVACMode.OFF
    assert state.attributes["friendly_name"] == "Bedroom AC"
    assert state.attributes["current_temperature"] == 25.5
    assert state.attributes["current_humidity"] == 61.2
    assert state.attributes["assumed_state"] is True
    assert state.attributes["fan_modes"] == ["auto", "high", "medium", "low", "quiet"]
    assert emitter.commands == []


async def test_turn_on_sends_state_frame(hass: HomeAssistant, init_integration, emitter) -> None:
    await _call(hass, "set_temperature", **{ATTR_TEMPERATURE: 22, ATTR_HVAC_MODE: "cool"})
    assert _frames(emitter) == [p.long_frame("cool", 22, "auto", "off").hex()]
    assert hass.states.get(ENTITY).state == "cool"
    command = emitter.commands[0]
    assert command.modulation == 38_000


async def test_turn_off_sends_short_frame(hass: HomeAssistant, init_integration, emitter) -> None:
    await _call(hass, "set_hvac_mode", **{ATTR_HVAC_MODE: "heat"})
    await _call(hass, "turn_off")
    assert _frames(emitter)[-1] == "146300101002fd"
    assert hass.states.get(ENTITY).state == HVACMode.OFF
    # turn_on resumes the last mode
    await _call(hass, "turn_on")
    assert hass.states.get(ENTITY).state == "heat"
    assert _frames(emitter)[-1] == p.long_frame("heat", 24, "auto", "off").hex()


async def test_changes_while_off_send_nothing(
    hass: HomeAssistant, init_integration, emitter
) -> None:
    await _call(hass, "set_temperature", **{ATTR_TEMPERATURE: 20})
    await _call(hass, "set_fan_mode", **{ATTR_FAN_MODE: "quiet"})
    await _call(hass, "set_swing_mode", **{ATTR_SWING_MODE: "both"})
    assert emitter.commands == []
    await _call(hass, "set_hvac_mode", **{ATTR_HVAC_MODE: "cool"})
    assert _frames(emitter) == [p.long_frame("cool", 20, "quiet", "both").hex()]


async def test_cool_clamps_to_18(hass: HomeAssistant, init_integration, emitter) -> None:
    await _call(hass, "set_temperature", **{ATTR_TEMPERATURE: 16, ATTR_HVAC_MODE: "cool"})
    assert hass.states.get(ENTITY).attributes[ATTR_TEMPERATURE] == 18
    assert _frames(emitter) == [p.long_frame("cool", 18, "auto", "off").hex()]


async def test_boost(hass: HomeAssistant, init_integration, emitter) -> None:
    with pytest.raises(HomeAssistantError):
        await _call(hass, "set_preset_mode", **{ATTR_PRESET_MODE: "boost"})
    assert emitter.commands == []

    await _call(hass, "set_hvac_mode", **{ATTR_HVAC_MODE: "cool"})
    await _call(hass, "set_preset_mode", **{ATTR_PRESET_MODE: "boost"})
    assert _frames(emitter)[-1] == p.short_frame(p.CMD_POWERFUL).hex()
    assert hass.states.get(ENTITY).attributes[ATTR_PRESET_MODE] == "boost"

    # the unit ends POWERFUL after 20 minutes; so does the preset
    async_fire_time_changed(hass, dt_util.utcnow() + timedelta(minutes=21))
    await hass.async_block_till_done()
    assert hass.states.get(ENTITY).attributes[ATTR_PRESET_MODE] == "none"

    # any state frame also ends it
    await _call(hass, "set_preset_mode", **{ATTR_PRESET_MODE: "boost"})
    await _call(hass, "set_temperature", **{ATTR_TEMPERATURE: 23})
    assert hass.states.get(ENTITY).attributes[ATTR_PRESET_MODE] == "none"


async def test_unavailable_with_emitter(hass: HomeAssistant, init_integration) -> None:
    hass.states.async_set(EMITTER, STATE_UNAVAILABLE)
    await hass.async_block_till_done()
    assert hass.states.get(ENTITY).state == STATE_UNAVAILABLE


async def test_buttons(hass: HomeAssistant, init_integration, emitter) -> None:
    await hass.services.async_call(
        "button",
        "press",
        {ATTR_ENTITY_ID: "button.bedroom_ac_force_send_ir_command"},
        blocking=True,
    )
    assert _frames(emitter) == ["146300101002fd"]  # off -> re-sends off
    await hass.services.async_call(
        "button", "press", {ATTR_ENTITY_ID: "button.bedroom_ac_step_vertical_vane"}, blocking=True
    )
    assert _frames(emitter)[-1] == p.short_frame(p.CMD_STEP_VERT).hex()


async def test_restore_state(hass: HomeAssistant, emitter, config_entry) -> None:
    mock_restore_cache(
        hass,
        [
            State(
                ENTITY,
                "heat",
                {ATTR_TEMPERATURE: 21, ATTR_FAN_MODE: "low", ATTR_SWING_MODE: "vertical"},
            )
        ],
    )
    config_entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done()
    state = hass.states.get(ENTITY)
    assert state.state == "heat"
    assert state.attributes[ATTR_TEMPERATURE] == 21
    assert state.attributes[ATTR_FAN_MODE] == "low"
    assert emitter.commands == []  # restoring never sends IR


async def test_unload(hass: HomeAssistant, init_integration) -> None:
    assert await hass.config_entries.async_unload(init_integration.entry_id)
    await hass.async_block_till_done()
    assert hass.states.get(ENTITY).state == STATE_UNAVAILABLE
