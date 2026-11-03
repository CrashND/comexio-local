"""Home Assistant entities created dynamically from live COMEXIO metadata."""
from __future__ import annotations
from homeassistant.helpers.entity import Entity
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from .constants import DOMAIN

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
        return {"identifiers":{(DOMAIN,self.runtime.entry.unique_id or self.runtime.entry.entry_id)},
            "name":"COMEXIO IO-Server", "manufacturer":"COMEXIO", "model":"IO-Server"}

    @property
    def available(self):
        return self.channel.key in self.runtime.channels and self.runtime.value(self.channel.key) is not None

    async def async_added_to_hass(self):
        self.async_on_remove(async_dispatcher_connect(
            self.hass,self.runtime.state_signal,self.async_write_ha_state))
        self.async_on_remove(async_dispatcher_connect(
            self.hass,self.runtime.discovery_signal,self._refresh_catalog))

    def _refresh_catalog(self):
        new=self.runtime.channels.get(self.channel.key)
        if new is not None:
            self.channel=new
            self._attr_name=new.name
        self.async_write_ha_state()
