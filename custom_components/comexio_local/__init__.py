"""COMEXIO Local: local read-first TCP bridge for configured relay outputs."""

from __future__ import annotations

import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryNotReady

from .catalog import CHANNEL_BY_ID, DEFAULT_CHANNEL_IDS
from .const import (
    CONF_ALLOW_WRITES,
    CONF_CHANNELS,
    CONF_HOST,
    CONF_PORT,
    CONF_SCAN_INTERVAL,
    DEFAULT_ALLOW_WRITES,
    DEFAULT_SCAN_INTERVAL,
    DOMAIN,
)
from .coordinator import ComexioCoordinator
from .tcp_client import ComexioTCPClient

_LOGGER = logging.getLogger(__name__)
PLATFORMS = ("light", "binary_sensor", "sensor")


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Setup a COMEXIO server without modifying its configuration."""
    settings = {**entry.data, **entry.options}
    selection = settings.get(CONF_CHANNELS, DEFAULT_CHANNEL_IDS)
    channels = tuple(CHANNEL_BY_ID[item] for item in selection if item in CHANNEL_BY_ID)
    if not channels:
        raise ConfigEntryNotReady("No COMEXIO output channels were selected")

    client = ComexioTCPClient(entry.data[CONF_HOST], entry.data[CONF_PORT])
    coordinator = ComexioCoordinator(
        hass,
        client,
        channels,
        int(settings.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL)),
    )
    await coordinator.async_config_entry_first_refresh()
    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = {
        "coordinator": coordinator,
        "allow_writes": bool(settings.get(CONF_ALLOW_WRITES, DEFAULT_ALLOW_WRITES)),
    }
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    entry.async_on_unload(entry.add_update_listener(_async_update_listener))
    return True


async def _async_update_listener(hass: HomeAssistant, entry: ConfigEntry) -> None:
    await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Remove only HA resources; leave COMEXIO untouched."""
    unloaded = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unloaded:
        hass.data[DOMAIN].pop(entry.entry_id, None)
    return unloaded
