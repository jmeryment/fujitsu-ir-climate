"""Fujitsu IR Climate: Fujitsu General A/C over Home Assistant's infrared platform."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_NAME
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo

from .const import DOMAIN, MANUFACTURER, MODEL, PLATFORMS

if TYPE_CHECKING:
    from .climate import FujitsuIRClimate


@dataclass
class FujitsuIRData:
    """Runtime data shared by the entry's platforms."""

    config: dict[str, Any]
    climate: FujitsuIRClimate | None = None


type FujitsuIRConfigEntry = ConfigEntry[FujitsuIRData]


def device_info(entry: FujitsuIRConfigEntry) -> DeviceInfo:
    """Full device info, so every platform names the device whichever sets up first."""

    return DeviceInfo(
        identifiers={(DOMAIN, entry.entry_id)},
        manufacturer=MANUFACTURER,
        model=MODEL,
        name=entry.runtime_data.config[CONF_NAME],
    )


async def async_setup_entry(hass: HomeAssistant, entry: FujitsuIRConfigEntry) -> bool:
    """Set up a Fujitsu IR climate device from a config entry."""

    entry.runtime_data = FujitsuIRData(config={**entry.data, **entry.options})
    entry.async_on_unload(entry.add_update_listener(_async_reload_entry))
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: FujitsuIRConfigEntry) -> bool:
    """Unload a config entry."""

    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)


async def _async_reload_entry(hass: HomeAssistant, entry: FujitsuIRConfigEntry) -> None:
    await hass.config_entries.async_reload(entry.entry_id)
