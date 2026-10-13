"""Climate platform for Fujitsu IR Climate."""

from __future__ import annotations

from typing import Any

from homeassistant.components.climate import (
    ATTR_HVAC_MODE,
    PRESET_BOOST,
    PRESET_NONE,
    ClimateEntity,
    ClimateEntityFeature,
    HVACMode,
)
from homeassistant.components.infrared import InfraredEmitterConsumerEntity
from homeassistant.const import (
    ATTR_TEMPERATURE,
    CONF_NAME,
    STATE_UNAVAILABLE,
    STATE_UNKNOWN,
    UnitOfTemperature,
)
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.event import async_call_later, async_track_state_change_event
from homeassistant.helpers.restore_state import RestoreEntity

from . import FujitsuIRConfigEntry
from .const import (
    CONF_EMITTER_ENTITY_ID,
    CONF_HUMIDITY_SENSOR,
    CONF_TEMPERATURE_SENSOR,
    DOMAIN,
    MANUFACTURER,
    MODEL,
)
from .ir_protocol import (
    CMD_POWERFUL,
    CMD_STEP_VERT,
    CMD_TURN_OFF,
    FAN_CODES,
    MAX_TEMP,
    MIN_TEMP,
    SWING_CODES,
    FujitsuIRCommand,
    clamp_temperature,
    long_frame,
    short_frame,
)

PARALLEL_UPDATES = 1

ON_MODES = (HVACMode.HEAT_COOL, HVACMode.COOL, HVACMode.DRY, HVACMode.FAN_ONLY, HVACMode.HEAT)
# Fujitsu ends POWERFUL by itself after 20 minutes; drop the preset then.
BOOST_SECONDS = 20 * 60


async def async_setup_entry(
    hass: HomeAssistant,
    entry: FujitsuIRConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    entity = FujitsuIRClimate(entry)
    entry.runtime_data.climate = entity
    async_add_entities([entity])


class FujitsuIRClimate(InfraredEmitterConsumerEntity, ClimateEntity, RestoreEntity):
    """Optimistic (assumed-state) Fujitsu climate entity."""

    _attr_assumed_state = True
    _attr_has_entity_name = True
    _attr_name = None
    _attr_translation_key = "fujitsu_ac"
    _attr_temperature_unit = UnitOfTemperature.CELSIUS
    _attr_target_temperature_step = 1
    _attr_min_temp = MIN_TEMP
    _attr_max_temp = MAX_TEMP
    _attr_hvac_modes = [HVACMode.OFF, *ON_MODES]
    _attr_fan_modes = list(FAN_CODES)
    _attr_swing_modes = list(SWING_CODES)
    _attr_preset_modes = [PRESET_NONE, PRESET_BOOST]
    _attr_supported_features = (
        ClimateEntityFeature.TARGET_TEMPERATURE
        | ClimateEntityFeature.FAN_MODE
        | ClimateEntityFeature.SWING_MODE
        | ClimateEntityFeature.PRESET_MODE
        | ClimateEntityFeature.TURN_ON
        | ClimateEntityFeature.TURN_OFF
    )

    def __init__(self, entry: FujitsuIRConfigEntry) -> None:
        config = entry.runtime_data.config
        self._infrared_emitter_entity_id = config[CONF_EMITTER_ENTITY_ID]
        self._temp_sensor = config.get(CONF_TEMPERATURE_SENSOR) or None
        self._humidity_sensor = config.get(CONF_HUMIDITY_SENSOR) or None
        self._attr_unique_id = entry.unique_id or entry.entry_id
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            manufacturer=MANUFACTURER,
            model=MODEL,
            name=config[CONF_NAME],
        )
        self._attr_hvac_mode = HVACMode.OFF
        self._attr_target_temperature = 24
        self._attr_fan_mode = "auto"
        self._attr_swing_mode = "off"
        self._attr_preset_mode = PRESET_NONE
        self._last_on_mode = HVACMode.COOL
        self._cancel_boost = None

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        if (last := await self.async_get_last_state()) is not None:
            if last.state in ON_MODES or last.state == HVACMode.OFF:
                self._attr_hvac_mode = HVACMode(last.state)
            attrs = last.attributes
            if isinstance(attrs.get(ATTR_TEMPERATURE), (int, float)):
                self._attr_target_temperature = attrs[ATTR_TEMPERATURE]
            if attrs.get("fan_mode") in FAN_CODES:
                self._attr_fan_mode = attrs["fan_mode"]
            if attrs.get("swing_mode") in SWING_CODES:
                self._attr_swing_mode = attrs["swing_mode"]
            if attrs.get("last_on_mode") in ON_MODES:
                self._last_on_mode = HVACMode(attrs["last_on_mode"])
        if self._attr_hvac_mode != HVACMode.OFF:
            self._last_on_mode = self._attr_hvac_mode

        if sensors := [e for e in (self._temp_sensor, self._humidity_sensor) if e]:
            self.async_on_remove(
                async_track_state_change_event(self.hass, sensors, self._async_sensor_changed)
            )
        self.async_on_remove(self._cancel_boost_timer)

    @callback
    def _async_sensor_changed(self, _event) -> None:
        self.async_write_ha_state()

    @property
    def current_temperature(self) -> float | None:
        return self._sensor_value(self._temp_sensor)

    @property
    def current_humidity(self) -> float | None:
        return self._sensor_value(self._humidity_sensor)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        return {
            "last_on_mode": self._last_on_mode,
            "infrared_emitter": self._infrared_emitter_entity_id,
        }

    def _sensor_value(self, entity_id: str | None) -> float | None:
        if not entity_id or (state := self.hass.states.get(entity_id)) is None:
            return None
        if state.state in (STATE_UNKNOWN, STATE_UNAVAILABLE):
            return None
        try:
            return float(state.state)
        except ValueError:
            return None

    # --- commands -------------------------------------------------------

    async def async_set_hvac_mode(self, hvac_mode: HVACMode) -> None:
        hvac_mode = HVACMode(hvac_mode)
        if hvac_mode == HVACMode.OFF:
            await self.async_turn_off()
            return
        self._attr_hvac_mode = hvac_mode
        self._last_on_mode = hvac_mode
        await self._async_send_state()

    async def async_turn_on(self) -> None:
        await self.async_set_hvac_mode(self._last_on_mode)

    async def async_turn_off(self) -> None:
        await self._async_send(short_frame(CMD_TURN_OFF))
        self._attr_hvac_mode = HVACMode.OFF
        self._end_boost()
        self.async_write_ha_state()

    async def async_set_temperature(self, **kwargs: Any) -> None:
        if (temperature := kwargs.get(ATTR_TEMPERATURE)) is not None:
            self._attr_target_temperature = float(temperature)
        if (hvac_mode := kwargs.get(ATTR_HVAC_MODE)) is not None:
            await self.async_set_hvac_mode(hvac_mode)
            return
        await self._async_send_state_if_on()

    async def async_set_fan_mode(self, fan_mode: str) -> None:
        if fan_mode not in FAN_CODES:
            raise HomeAssistantError(f"Unsupported fan mode {fan_mode}")
        self._attr_fan_mode = fan_mode
        await self._async_send_state_if_on()

    async def async_set_swing_mode(self, swing_mode: str) -> None:
        if swing_mode not in SWING_CODES:
            raise HomeAssistantError(f"Unsupported swing mode {swing_mode}")
        self._attr_swing_mode = swing_mode
        await self._async_send_state_if_on()

    async def async_set_preset_mode(self, preset_mode: str) -> None:
        if preset_mode == PRESET_BOOST:
            if self._attr_hvac_mode == HVACMode.OFF:
                raise HomeAssistantError("Turn the air conditioner on before boost")
            await self._async_send(short_frame(CMD_POWERFUL))
            self._attr_preset_mode = PRESET_BOOST
            self._cancel_boost_timer()
            self._cancel_boost = async_call_later(self.hass, BOOST_SECONDS, self._boost_elapsed)
            self.async_write_ha_state()
        elif preset_mode == PRESET_NONE:
            # A full state frame (a mode/temperature command) ends POWERFUL.
            await self._async_send_state_if_on()
            self._end_boost()
            self.async_write_ha_state()
        else:
            raise HomeAssistantError(f"Unsupported preset {preset_mode}")

    async def async_force_send(self) -> None:
        """Re-send the current state (fixes a unit that missed a command)."""

        if self._attr_hvac_mode == HVACMode.OFF:
            await self._async_send(short_frame(CMD_TURN_OFF))
        else:
            await self._async_send_state()

    async def async_vane_step(self) -> None:
        """Move the vertical vane one position (the remote's SET button)."""

        await self._async_send(short_frame(CMD_STEP_VERT))

    async def _async_send_state_if_on(self) -> None:
        if self._attr_hvac_mode == HVACMode.OFF:
            self.async_write_ha_state()
        else:
            await self._async_send_state()

    async def _async_send_state(self) -> None:
        mode = self._attr_hvac_mode
        self._attr_target_temperature = clamp_temperature(mode, self._attr_target_temperature)
        await self._async_send(
            long_frame(
                mode, self._attr_target_temperature, self._attr_fan_mode, self._attr_swing_mode
            )
        )
        self._end_boost()
        self.async_write_ha_state()

    async def _async_send(self, frame: bytes) -> None:
        await self._send_command(FujitsuIRCommand(frame))

    # --- boost bookkeeping --------------------------------------------

    @callback
    def _boost_elapsed(self, _now) -> None:
        self._cancel_boost = None
        self._attr_preset_mode = PRESET_NONE
        self.async_write_ha_state()

    @callback
    def _end_boost(self) -> None:
        self._cancel_boost_timer()
        self._attr_preset_mode = PRESET_NONE

    @callback
    def _cancel_boost_timer(self) -> None:
        if self._cancel_boost is not None:
            self._cancel_boost()
            self._cancel_boost = None
