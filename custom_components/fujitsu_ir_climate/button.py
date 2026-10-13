"""Buttons for Fujitsu IR Climate."""

from __future__ import annotations

from collections.abc import Callable, Coroutine
from dataclasses import dataclass
from typing import Any

from homeassistant.components.button import ButtonEntity, ButtonEntityDescription
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import FujitsuIRConfigEntry, FujitsuIRData
from .const import DOMAIN

PARALLEL_UPDATES = 1


@dataclass(frozen=True, kw_only=True)
class FujitsuIRButtonDescription(ButtonEntityDescription):
    """A button that sends a one-off command through the climate entity."""

    press: Callable[[Any], Coroutine[Any, Any, None]]


BUTTONS = (
    FujitsuIRButtonDescription(
        key="force_send",
        translation_key="force_send",
        entity_category=EntityCategory.CONFIG,
        press=lambda climate: climate.async_force_send(),
    ),
    FujitsuIRButtonDescription(
        key="vane_step",
        translation_key="vane_step",
        press=lambda climate: climate.async_vane_step(),
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: FujitsuIRConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    async_add_entities(FujitsuIRButton(entry, description) for description in BUTTONS)


class FujitsuIRButton(ButtonEntity):
    """One-off IR command button."""

    _attr_has_entity_name = True
    entity_description: FujitsuIRButtonDescription

    def __init__(
        self, entry: FujitsuIRConfigEntry, description: FujitsuIRButtonDescription
    ) -> None:
        self.entity_description = description
        self._data: FujitsuIRData = entry.runtime_data
        self._attr_unique_id = f"{entry.unique_id or entry.entry_id}_{description.key}"
        self._attr_device_info = DeviceInfo(identifiers={(DOMAIN, entry.entry_id)})

    async def async_press(self) -> None:
        if self._data.climate is None:
            raise HomeAssistantError("The climate entity is not ready")
        await self.entity_description.press(self._data.climate)
