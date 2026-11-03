"""Diagnostics to keep controller traffic observable."""

from homeassistant.components.sensor import SensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback):
    coord = hass.data[DOMAIN][entry.entry_id]["coordinator"]
    async_add_entities([
        ComexioDiag(coord, "requests", "TCP requests", "request_count"),
        ComexioDiag(coord, "errors", "TCP errors", "error_count"),
        ComexioDiag(coord, "latency", "TCP latency", "last_latency_ms", "ms"),
    ])


class ComexioDiag(CoordinatorEntity, SensorEntity):
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_has_entity_name = True

    def __init__(self, coordinator, slug: str, title: str, field: str, unit: str | None = None):
        super().__init__(coordinator)
        self._attr_unique_id = f"{DOMAIN}_{coordinator.client.host}_{coordinator.client.port}_{slug}"
        self._attr_name = title
        self._field = field
        self._attr_native_unit_of_measurement = unit

    @property
    def native_value(self):
        return getattr(self.coordinator.client, self._field)

    @property
    def device_info(self):
        return {
            "identifiers": {(DOMAIN, f"{self.coordinator.client.host}:{self.coordinator.client.port}")},
            "name": "COMEXIO IO-Server",
            "manufacturer": "COMEXIO",
            "model": "IO-Server 2G",
        }

    @property
    def available(self):
        # Diagnostics stay visible even when the controller is not responding.
        return True
