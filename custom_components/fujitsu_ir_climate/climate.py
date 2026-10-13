"""Climate platform for Fujitsu IR Climate."""

from __future__ import annotations

from dataclasses import dataclass, replace
import math
from typing import Any, Self

from homeassistant.components.climate import (
    ATTR_FAN_MODE,
    ATTR_HVAC_MODE,
    ATTR_SWING_MODE,
    ClimateEntity,
    ClimateEntityFeature,
    HVACMode,
)
from homeassistant.components.infrared import InfraredEmitterConsumerEntity
from homeassistant.const import (
    ATTR_TEMPERATURE,
    ATTR_UNIT_OF_MEASUREMENT,
    CONF_NAME,
    STATE_UNAVAILABLE,
    STATE_UNKNOWN,
    UnitOfTemperature,
)
from homeassistant.core import HomeAssistant, State, callback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.event import async_track_state_change_event
from homeassistant.helpers.restore_state import ExtraStoredData, RestoreEntity
from homeassistant.util.unit_conversion import TemperatureConverter

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
ALL_MODES = (HVACMode.OFF, *ON_MODES)
DEFAULT_TARGET = 24
FAN_AUTO = "auto"
SWING_OFF = "off"


@dataclass(frozen=True)
class _Settings:
    """What the unit was last told (the entity is optimistic)."""

    hvac_mode: HVACMode = HVACMode.OFF
    target: int = DEFAULT_TARGET  # Celsius, always
    fan_mode: str = FAN_AUTO
    swing_mode: str = SWING_OFF
    last_on_mode: HVACMode = HVACMode.COOL


@dataclass
class _StoredSettings(ExtraStoredData):
    """Restore data kept in native units, independent of the UI's unit system."""

    settings: _Settings

    def as_dict(self) -> dict[str, Any]:
        s = self.settings
        return {
            "hvac_mode": s.hvac_mode,
            "target_c": s.target,
            "fan_mode": s.fan_mode,
            "swing_mode": s.swing_mode,
            "last_on_mode": s.last_on_mode,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Self | None:
        try:
            hvac_mode = HVACMode(data["hvac_mode"])
            last_on_mode = HVACMode(data["last_on_mode"])
        except (KeyError, TypeError, ValueError):
            return None
        target = _normalise_target(data.get("target_c"))
        if hvac_mode not in ALL_MODES or last_on_mode not in ON_MODES or target is None:
            return None
        return cls(
            _Settings(
                hvac_mode=hvac_mode,
                target=target,
                fan_mode=_valid(data.get("fan_mode"), FAN_CODES, FAN_AUTO),
                swing_mode=_valid(data.get("swing_mode"), SWING_CODES, SWING_OFF),
                last_on_mode=last_on_mode,
            )
        )


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
    _attr_hvac_modes = list(ALL_MODES)
    _attr_fan_modes = list(FAN_CODES)
    _attr_swing_modes = list(SWING_CODES)
    _attr_supported_features = (
        ClimateEntityFeature.TARGET_TEMPERATURE
        | ClimateEntityFeature.FAN_MODE
        | ClimateEntityFeature.SWING_MODE
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
        self._settings = _Settings()

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        stored = await self.async_get_last_extra_data()
        restored = _StoredSettings.from_dict(stored.as_dict()) if stored else None
        if restored is not None:
            self._settings = restored.settings
        elif (last := await self.async_get_last_state()) is not None:
            self._settings = self._settings_from_state(last)
        if sensors := [e for e in (self._temp_sensor, self._humidity_sensor) if e]:
            self.async_on_remove(
                async_track_state_change_event(self.hass, sensors, self._async_sensor_changed)
            )

    def _settings_from_state(self, state: State) -> _Settings:
        """Fallback restore from a plain state (no extra data stored yet)."""

        attrs = state.attributes
        settings = _Settings(
            fan_mode=_valid(attrs.get(ATTR_FAN_MODE), FAN_CODES, FAN_AUTO),
            swing_mode=_valid(attrs.get(ATTR_SWING_MODE), SWING_CODES, SWING_OFF),
        )
        if state.state in ALL_MODES:
            settings = self._with_mode(settings, HVACMode(state.state))
        if (last_on := attrs.get("last_on_mode")) in ON_MODES:
            settings = replace(settings, last_on_mode=HVACMode(last_on))
        # The state attribute is in the UI's unit system; convert it back to Celsius.
        temperature = attrs.get(ATTR_TEMPERATURE)
        if isinstance(temperature, (int, float)):
            unit = self.hass.config.units.temperature_unit
            celsius = TemperatureConverter.convert(temperature, unit, UnitOfTemperature.CELSIUS)
            if (target := _normalise_target(celsius)) is not None:
                settings = replace(settings, target=target)
        return settings

    @property
    def extra_restore_state_data(self) -> _StoredSettings:
        return _StoredSettings(self._settings)

    @callback
    def _async_sensor_changed(self, _event) -> None:
        self.async_write_ha_state()

    # --- state ----------------------------------------------------------

    @property
    def hvac_mode(self) -> HVACMode:
        return self._settings.hvac_mode

    @property
    def target_temperature(self) -> float:
        return self._settings.target

    @property
    def fan_mode(self) -> str:
        # Dry mode always runs (and is sent with) fan auto.
        if self._settings.hvac_mode == HVACMode.DRY:
            return FAN_AUTO
        return self._settings.fan_mode

    @property
    def swing_mode(self) -> str:
        return self._settings.swing_mode

    @property
    def current_temperature(self) -> float | None:
        value = self._sensor_value(self._temp_sensor)
        if value is None:
            return None
        state = self.hass.states.get(self._temp_sensor)
        unit = state.attributes.get(ATTR_UNIT_OF_MEASUREMENT)
        if unit in TemperatureConverter.VALID_UNITS and unit != UnitOfTemperature.CELSIUS:
            value = TemperatureConverter.convert(value, unit, UnitOfTemperature.CELSIUS)
        return value

    @property
    def current_humidity(self) -> float | None:
        return self._sensor_value(self._humidity_sensor)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        return {
            "last_on_mode": self._settings.last_on_mode,
            "infrared_emitter": self._infrared_emitter_entity_id,
        }

    def _sensor_value(self, entity_id: str | None) -> float | None:
        if not entity_id or (state := self.hass.states.get(entity_id)) is None:
            return None
        if state.state in (STATE_UNKNOWN, STATE_UNAVAILABLE):
            return None
        try:
            value = float(state.state)
        except ValueError:
            return None
        return value if math.isfinite(value) else None

    # --- commands -------------------------------------------------------

    async def async_set_hvac_mode(self, hvac_mode: HVACMode) -> None:
        settings = self._with_mode(self._settings, HVACMode(hvac_mode))
        await self._async_apply(settings, send_off=True)

    async def async_turn_on(self) -> None:
        await self.async_set_hvac_mode(self._settings.last_on_mode)

    async def async_turn_off(self) -> None:
        await self.async_set_hvac_mode(HVACMode.OFF)

    async def async_set_temperature(self, **kwargs: Any) -> None:
        settings = self._settings
        if (temperature := kwargs.get(ATTR_TEMPERATURE)) is not None:
            if (target := _normalise_target(temperature)) is None:
                raise HomeAssistantError(f"Invalid temperature {temperature}")
            settings = replace(settings, target=target)
        if (hvac_mode := kwargs.get(ATTR_HVAC_MODE)) is not None:
            settings = self._with_mode(settings, HVACMode(hvac_mode))
        await self._async_apply(settings, send_off=hvac_mode is not None)

    async def async_set_fan_mode(self, fan_mode: str) -> None:
        if fan_mode not in FAN_CODES:
            raise HomeAssistantError(f"Unsupported fan mode {fan_mode}")
        await self._async_apply(replace(self._settings, fan_mode=fan_mode))

    async def async_set_swing_mode(self, swing_mode: str) -> None:
        if swing_mode not in SWING_CODES:
            raise HomeAssistantError(f"Unsupported swing mode {swing_mode}")
        await self._async_apply(replace(self._settings, swing_mode=swing_mode))

    async def async_force_send(self) -> None:
        """Re-send the current state (brings a unit that missed a command back in line)."""

        await self._async_apply(self._settings, send_off=True)

    async def async_vane_step(self) -> None:
        """Move the vertical vane one position (the remote's SET button)."""

        await self._send_command(FujitsuIRCommand(short_frame(CMD_STEP_VERT)))

    @staticmethod
    def _with_mode(settings: _Settings, hvac_mode: HVACMode) -> _Settings:
        if hvac_mode not in ALL_MODES:
            raise HomeAssistantError(f"Unsupported HVAC mode {hvac_mode}")
        if hvac_mode == HVACMode.OFF:
            return replace(settings, hvac_mode=hvac_mode)
        return replace(settings, hvac_mode=hvac_mode, last_on_mode=hvac_mode)

    async def _async_apply(self, settings: _Settings, *, send_off: bool = False) -> None:
        """Send what `settings` needs, and only then adopt it as the entity state.

        While on, every change sends the full state frame. While off, only an explicit
        off (turn_off, set_hvac_mode, force send) is sent; other changes are stored and
        go out with the next turn-on. IR is one-way, so explicit commands are always
        sent even when the entity already shows that state. If the send fails the
        entity keeps its previous state.
        """

        mode = settings.hvac_mode
        frame: bytes | None = None
        if mode != HVACMode.OFF:
            settings = replace(settings, target=clamp_temperature(mode, settings.target))
            frame = long_frame(mode, settings.target, settings.fan_mode, settings.swing_mode)
        elif send_off:
            frame = short_frame(CMD_TURN_OFF)
        if frame is not None:
            await self._send_command(FujitsuIRCommand(frame))
        self._settings = settings
        self.async_write_ha_state()


def _valid(value: Any, allowed: Any, default: str) -> str:
    return value if value in allowed else default


def _normalise_target(value: Any) -> int | None:
    """Round to the unit's 1 C step and keep within 16-30 C; None if not a number."""

    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(number):
        return None
    return max(MIN_TEMP, min(MAX_TEMP, round(number)))
