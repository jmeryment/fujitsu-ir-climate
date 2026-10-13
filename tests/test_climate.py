"""Climate and button entity tests: what is sent through the emitter."""

from unittest.mock import patch

from homeassistant.components.climate import (
    ATTR_FAN_MODE,
    ATTR_HVAC_MODE,
    ATTR_SWING_MODE,
    DOMAIN as CLIMATE,
    HVACMode,
)
from homeassistant.const import ATTR_ENTITY_ID, ATTR_TEMPERATURE, STATE_UNAVAILABLE, Platform
from homeassistant.core import HomeAssistant, State
from homeassistant.exceptions import HomeAssistantError
from homeassistant.util.unit_system import US_CUSTOMARY_SYSTEM
import pytest
from pytest_homeassistant_custom_component.common import (
    mock_restore_cache,
    mock_restore_cache_with_extra_data,
)

from custom_components.fujitsu_ir_climate import ir_protocol as p

from .conftest import EMITTER, TEMP_SENSOR

ENTITY = "climate.bedroom_ac"
OFF = "146300101002fd"


async def _call(hass, service, **data):
    await hass.services.async_call(
        CLIMATE, service, {ATTR_ENTITY_ID: ENTITY, **data}, blocking=True
    )


def _frames(emitter):
    return [c.frame.hex() for c in emitter.commands]


def _state(mode, temp, fan="auto", swing="off"):
    return p.long_frame(mode, temp, fan, swing).hex()


async def test_initial_state(hass: HomeAssistant, init_integration, emitter) -> None:
    state = hass.states.get(ENTITY)
    assert state.state == HVACMode.OFF
    assert state.attributes["friendly_name"] == "Bedroom AC"
    assert state.attributes["current_temperature"] == 25.5
    assert state.attributes["current_humidity"] == 61.2
    assert state.attributes["assumed_state"] is True
    assert state.attributes["fan_modes"] == ["auto", "high", "medium", "low", "quiet"]
    assert "preset_modes" not in state.attributes
    assert emitter.commands == []


async def test_turn_on_sends_state_frame(hass: HomeAssistant, init_integration, emitter) -> None:
    await _call(hass, "set_temperature", **{ATTR_TEMPERATURE: 22, ATTR_HVAC_MODE: "cool"})
    assert _frames(emitter) == [_state("cool", 22)]
    assert hass.states.get(ENTITY).state == "cool"
    assert emitter.commands[0].modulation == 38_000


async def test_every_change_while_on_is_sent(
    hass: HomeAssistant, init_integration, emitter
) -> None:
    await _call(hass, "set_hvac_mode", **{ATTR_HVAC_MODE: "cool"})
    await _call(hass, "set_fan_mode", **{ATTR_FAN_MODE: "quiet"})
    await _call(hass, "set_swing_mode", **{ATTR_SWING_MODE: "vertical"})
    await _call(hass, "set_temperature", **{ATTR_TEMPERATURE: 21})
    await _call(hass, "set_hvac_mode", **{ATTR_HVAC_MODE: "cool"})  # same mode: still sent
    assert _frames(emitter) == [
        _state("cool", 24),
        _state("cool", 24, "quiet"),
        _state("cool", 24, "quiet", "vertical"),
        _state("cool", 21, "quiet", "vertical"),
        _state("cool", 21, "quiet", "vertical"),
    ]


async def test_turn_off_and_resume(hass: HomeAssistant, init_integration, emitter) -> None:
    await _call(hass, "set_hvac_mode", **{ATTR_HVAC_MODE: "heat"})
    await _call(hass, "turn_off")
    assert _frames(emitter)[-1] == OFF
    assert hass.states.get(ENTITY).state == HVACMode.OFF
    await _call(hass, "turn_on")  # resumes the last mode
    assert hass.states.get(ENTITY).state == "heat"
    assert _frames(emitter)[-1] == _state("heat", 24)


async def test_explicit_off_is_sent_even_when_already_off(
    hass: HomeAssistant, init_integration, emitter
) -> None:
    # IR is one-way: someone may have switched the unit on with its own remote.
    await _call(hass, "turn_off")
    assert _frames(emitter) == [OFF]


async def test_changes_while_off_are_stored(hass: HomeAssistant, init_integration, emitter) -> None:
    await _call(hass, "set_temperature", **{ATTR_TEMPERATURE: 20.4})
    await _call(hass, "set_fan_mode", **{ATTR_FAN_MODE: "quiet"})
    await _call(hass, "set_swing_mode", **{ATTR_SWING_MODE: "both"})
    assert emitter.commands == []
    assert hass.states.get(ENTITY).attributes[ATTR_TEMPERATURE] == 20  # normalised at once
    await _call(hass, "set_hvac_mode", **{ATTR_HVAC_MODE: "cool"})
    assert _frames(emitter) == [_state("cool", 20, "quiet", "both")]


async def test_cool_clamps_to_18(hass: HomeAssistant, init_integration, emitter) -> None:
    await _call(hass, "set_temperature", **{ATTR_TEMPERATURE: 16, ATTR_HVAC_MODE: "cool"})
    assert hass.states.get(ENTITY).attributes[ATTR_TEMPERATURE] == 18
    assert _frames(emitter) == [_state("cool", 18)]


async def test_dry_reports_fan_auto(hass: HomeAssistant, init_integration, emitter) -> None:
    await _call(hass, "set_fan_mode", **{ATTR_FAN_MODE: "high"})
    await _call(hass, "set_hvac_mode", **{ATTR_HVAC_MODE: "dry"})
    assert hass.states.get(ENTITY).attributes[ATTR_FAN_MODE] == "auto"
    assert _frames(emitter) == [_state("dry", 24, "auto")]
    await _call(hass, "set_hvac_mode", **{ATTR_HVAC_MODE: "cool"})  # preference kept
    assert hass.states.get(ENTITY).attributes[ATTR_FAN_MODE] == "high"


async def test_failed_send_keeps_previous_state(
    hass: HomeAssistant, init_integration, emitter
) -> None:
    emitter.fail = True
    with pytest.raises(HomeAssistantError):
        await _call(hass, "set_temperature", **{ATTR_TEMPERATURE: 19, ATTR_HVAC_MODE: "heat"})
    state = hass.states.get(ENTITY)
    assert state.state == HVACMode.OFF
    assert state.attributes[ATTR_TEMPERATURE] == 24
    assert state.attributes["last_on_mode"] == "cool"


async def test_unavailable_with_emitter(hass: HomeAssistant, init_integration) -> None:
    hass.states.async_set(EMITTER, STATE_UNAVAILABLE)
    await hass.async_block_till_done()
    assert hass.states.get(ENTITY).state == STATE_UNAVAILABLE


async def test_fahrenheit_sensor_is_converted(hass: HomeAssistant, init_integration) -> None:
    hass.states.async_set(TEMP_SENSOR, "77", {"unit_of_measurement": "°F"})
    await hass.async_block_till_done()
    assert hass.states.get(ENTITY).attributes["current_temperature"] == 25


async def test_non_finite_sensor_ignored(hass: HomeAssistant, init_integration) -> None:
    hass.states.async_set(TEMP_SENSOR, "nan", {"unit_of_measurement": "°C"})
    await hass.async_block_till_done()
    assert hass.states.get(ENTITY).attributes.get("current_temperature") is None


async def test_buttons(hass: HomeAssistant, init_integration, emitter) -> None:
    await hass.services.async_call(
        "button",
        "press",
        {ATTR_ENTITY_ID: "button.bedroom_ac_force_send_ir_command"},
        blocking=True,
    )
    assert _frames(emitter) == [OFF]  # off -> re-sends off
    await _call(hass, "set_hvac_mode", **{ATTR_HVAC_MODE: "heat"})
    await hass.services.async_call(
        "button",
        "press",
        {ATTR_ENTITY_ID: "button.bedroom_ac_force_send_ir_command"},
        blocking=True,
    )
    assert _frames(emitter)[-1] == _state("heat", 24)
    await hass.services.async_call(
        "button",
        "press",
        {ATTR_ENTITY_ID: "button.bedroom_ac_step_vertical_vane"},
        blocking=True,
    )
    assert _frames(emitter)[-1] == p.short_frame(p.CMD_STEP_VERT).hex()


async def _setup(hass, config_entry):
    config_entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done()


async def test_restore_from_extra_data(hass: HomeAssistant, emitter, config_entry) -> None:
    hass.config.units = US_CUSTOMARY_SYSTEM
    mock_restore_cache_with_extra_data(
        hass,
        [
            (
                State(ENTITY, "heat", {ATTR_TEMPERATURE: 70}),
                {
                    "hvac_mode": "heat",
                    "target_c": 21,
                    "fan_mode": "low",
                    "swing_mode": "vertical",
                    "last_on_mode": "heat",
                },
            )
        ],
    )
    await _setup(hass, config_entry)
    entity = config_entry.runtime_data.climate
    assert entity.hvac_mode == "heat"
    assert entity.target_temperature == 21  # native Celsius, not the displayed 70 F
    assert entity.fan_mode == "low"
    assert entity.swing_mode == "vertical"
    assert emitter.commands == []  # restoring never sends IR


async def test_restore_from_plain_state_converts_units(
    hass: HomeAssistant, emitter, config_entry
) -> None:
    hass.config.units = US_CUSTOMARY_SYSTEM
    mock_restore_cache(
        hass,
        [State(ENTITY, "cool", {ATTR_TEMPERATURE: 71.6, ATTR_FAN_MODE: "high"})],
    )
    await _setup(hass, config_entry)
    entity = config_entry.runtime_data.climate
    assert entity.hvac_mode == "cool"
    assert entity.target_temperature == 22
    assert entity.fan_mode == "high"
    assert emitter.commands == []


async def test_unload(hass: HomeAssistant, init_integration) -> None:
    assert await hass.config_entries.async_unload(init_integration.entry_id)
    await hass.async_block_till_done()
    assert hass.states.get(ENTITY).state == STATE_UNAVAILABLE


async def test_buttons_name_device_on_their_own(hass: HomeAssistant, emitter, config_entry) -> None:
    """Platforms set up concurrently; if buttons win the race they still name the device."""
    with patch("custom_components.fujitsu_ir_climate.PLATFORMS", [Platform.BUTTON]):
        await _setup(hass, config_entry)
    assert hass.states.get("button.bedroom_ac_force_send_ir_command") is not None
    assert hass.states.get("button.bedroom_ac_step_vertical_vane") is not None
