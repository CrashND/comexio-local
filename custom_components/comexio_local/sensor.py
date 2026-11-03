"""Diagnostics only; no periodic status polling."""
from homeassistant.components.sensor import SensorEntity
from homeassistant.const import EntityCategory
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from .entities import BaseChannel

async def async_setup_entry(hass,entry,async_add_entities):
    runtime=hass.data['comexio_local'][entry.entry_id]
    async_add_entities([EventCount(runtime),SignalCount(runtime)])

class _StatSensor(SensorEntity):
    _attr_entity_category=EntityCategory.DIAGNOSTIC
    _attr_should_poll=False
    def __init__(self,runtime,suffix,name):
        self.runtime=runtime
        self._attr_unique_id=f"{runtime.entry.entry_id}-{suffix}"
        self._attr_name=name
    async def async_added_to_hass(self):
        self.async_on_remove(async_dispatcher_connect(self.hass,self.runtime.state_signal,self.async_write_ha_state))
        self.async_on_remove(async_dispatcher_connect(self.hass,self.runtime.discovery_signal,self.async_write_ha_state))

class EventCount(_StatSensor):
    def __init__(self,runtime): super().__init__(runtime,'events','COMEXIO Push Ereignisse')
    @property
    def native_value(self): return self.runtime.events

class SignalCount(_StatSensor):
    def __init__(self,runtime): super().__init__(runtime,'discovered','COMEXIO Entdeckte Anschluesse')
    @property
    def native_value(self): return len(self.runtime.channels)
