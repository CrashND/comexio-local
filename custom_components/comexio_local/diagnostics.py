"""Read-only HA diagnostics, with no secrets or raw responses."""

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from .const import DOMAIN, CONF_PORT


async def async_get_config_entry_diagnostics(hass: HomeAssistant, entry: ConfigEntry):
    runtime = hass.data[DOMAIN][entry.entry_id]
    coord = runtime["coordinator"]
    return {
        "server": {"host": "[redacted]", "port": entry.data[CONF_PORT]},
        "active_channels": [channel.id for channel in coord.channels],
        "allow_direct_writes": runtime["allow_writes"],
        "last_update_success": coord.last_update_success,
        "valid_channels": sum(value is not None for value in (coord.data or {}).values()),
        "request_count": coord.client.request_count,
        "error_count": coord.client.error_count,
        "last_latency_ms": coord.client.last_latency_ms,
    }
