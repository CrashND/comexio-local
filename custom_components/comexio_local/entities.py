"""Home Assistant entities created dynamically from live COMEXIO metadata."""
from __future__ import annotations
from homeassistant.helpers.entity import Entity
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from .constants import DOMAIN
from .device_metadata import device_info

class BaseChannel(Entity):
    _attr_should_poll=False
    _attr_has_entity_name=True

    def __init__(self, runtime, channel):
        self.runtime=runtime
        self.channel=channel
        self._attr_unique_id=f"{runtime.entry.unique_id or runtime.entry.entry_id}:{channel.key}"
        self._attr_name=channel.name

    @property
    def device_info(self):
        return device_info(self.runtime)

    @property
    def available(self):
        return self.channel.key in self.runtime.channels and self.runtime.value(self.channel.key) is not None

    async def async_added_to_hass(self):
        self.async_on_remove(async_dispatcher_connect(
            self.hass,self.runtime.state_signal,self.async_write_ha_state))
        self.async_on_remove(async_dispatcher_connect(
            self.hass,self.runtime.discovery_signal,self._refresh_catalog))
        # If the user explicitly changed an entity platform, keep its HA area
        # and display name on the newly created entity (never change COMEXIO).
        restored = self.runtime.entry.options.get('classification_areas', {}).get(self.channel.key)
        if isinstance(restored, dict) and self.entity_id:
            from homeassistant.helpers import entity_registry as er
            registry = er.async_get(self.hass)
            current = registry.async_get(self.entity_id)
            if current is not None and current.config_entry_id == self.runtime.entry.entry_id:
                updates = {}
                if current.area_id is None and restored.get('area_id'):
                    updates['area_id'] = restored['area_id']
                if current.name is None and restored.get('name'):
                    updates['name'] = restored['name']
                if updates:
                    registry.async_update_entity(self.entity_id, **updates)

    def _refresh_catalog(self):
        new=self.runtime.channels.get(self.channel.key)
        if new is not None:
            self.channel=new
            self._attr_name=new.name
        self.async_write_ha_state()
