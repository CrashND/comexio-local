"""Shared COMEXIO entity implementation."""

from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import ComexioCoordinator
from .catalog import Channel


class ComexioChannelEntity(CoordinatorEntity[ComexioCoordinator]):
    _attr_has_entity_name = True

    def __init__(self, coordinator: ComexioCoordinator, channel: Channel):
        super().__init__(coordinator)
        self.channel = channel
        self._attr_unique_id = f"{coordinator.client.host}_{coordinator.client.port}_{channel.id}"
        self._attr_name = channel.name

    @property
    def device_info(self):
        return {
            "identifiers": {(DOMAIN, f"{self.coordinator.client.host}:{self.coordinator.client.port}")},
            "name": "COMEXIO IO-Server",
            "manufacturer": "COMEXIO",
            "model": "IO-Server 2G",
        }

    @property
    def available(self) -> bool:
        return super().available and (self.coordinator.data or {}).get(self.channel.id) is not None
