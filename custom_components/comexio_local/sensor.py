"""Diagnostics only; no periodic status polling."""
from homeassistant.components.sensor import SensorEntity
from homeassistant.const import EntityCategory
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from .entities import BaseChannel
from .device_metadata import device_info

async def async_setup_entry(hass,entry,async_add_entities):
    runtime=hass.data['comexio_local'][entry.entry_id]
    async_add_entities([EventCount(runtime),SignalCount(runtime),RejectedCount(runtime),PushState(runtime),RecentPushEvents(runtime),IntegrationVersion(runtime),PushRebuildStatus(runtime),InputPushStatus(runtime)])
    # EnOcean analog channels are read-only native measurements. Physical AI
    # inputs keep their existing opt-in digital semantics and are not added.
    known = set()
    def update():
        new = [c for c in runtime.channels.values()
               if c.is_enocean and c.kind == 'enocean_sensor' and c.key not in known]
        if new:
            known.update(c.key for c in new)
            async_add_entities([ComexioEnOceanSensor(runtime, c) for c in new])
    update()
    entry.async_on_unload(async_dispatcher_connect(hass, runtime.discovery_signal, update))


class ComexioEnOceanSensor(BaseChannel, SensorEntity):
    """Unscaled numeric COMEXIO data; do not label raw 10-bit values as lux."""
    @property
    def native_value(self):
        return self.runtime.value(self.channel.key)

    @property
    def extra_state_attributes(self):
        return {**super().extra_state_attributes,
                'enocean_teilnehmerplatz': f'EI{self.channel.enocean_slot}',
                'enocean_signal': self.channel.enocean_signal,
                'wertdarstellung': 'COMEXIO-Rohwert (Einheit nicht verifiziert)'}

class _StatSensor(SensorEntity):
    _attr_entity_category=EntityCategory.DIAGNOSTIC
    _attr_should_poll=False
    def __init__(self,runtime,suffix,name):
        self.runtime=runtime
        self._attr_unique_id=f"{runtime.entry.entry_id}-{suffix}"
        self._attr_name=name
    @property
    def device_info(self):
        return device_info(self.runtime)
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


class RejectedCount(_StatSensor):
    def __init__(self, runtime):
        super().__init__(runtime, 'rejected', 'COMEXIO Push abgelehnte Ereignisse')
    @property
    def native_value(self):
        return self.runtime.rejected_events
    @property
    def extra_state_attributes(self):
        return {'last_reason': self.runtime.last_rejection}

class PushState(_StatSensor):
    def __init__(self, runtime):
        super().__init__(runtime, 'push_state', 'COMEXIO Push Konfiguration')
    @property
    def native_value(self):
        return (self.runtime.push_diagnostics or {}).get('status', 'not_checked')
    @property
    def extra_state_attributes(self):
        return self.runtime.push_diagnostics or {}

class RecentPushEvents(_StatSensor):
    """Small, bounded in-memory preview of accepted webhook events."""

    def __init__(self, runtime):
        super().__init__(runtime, 'recent_push', 'COMEXIO Push Ereignisprotokoll')

    @property
    def native_value(self):
        recent = self.runtime.push_journal.recent(1)
        return recent[0]['source'] if recent else 'noch_keine_ereignisse'

    @property
    def extra_state_attributes(self):
        journal = self.runtime.push_journal
        return {
            'last_event': journal.recent(1)[0] if journal.total else None,
            'recent_events': journal.recent(12),
            'source_counts': {source: item['count'] for source, item in journal.sources().items()},
            'total_since_start': journal.total,
            'same_as_cached': journal.same_as_cached,
            'unique_sources': len(journal.sources()),
        }


class IntegrationVersion(_StatSensor):
    """Explicit integration version, separate from the IO-Server firmware."""
    def __init__(self, runtime):
        super().__init__(runtime, 'integration_version', 'COMEXIO Local Version')

    @property
    def native_value(self):
        from .constants import INTEGRATION_VERSION
        return INTEGRATION_VERSION


class InputPushStatus(_StatSensor):
    """EnOcean/physical input background job status without COMEXIO polling."""
    def __init__(self, runtime):
        super().__init__(runtime, 'input_push_status', 'COMEXIO Eingangs-Push Auftrag')

    @property
    def native_value(self):
        return self.runtime.input_push_status()['status']

    @property
    def extra_state_attributes(self):
        return self.runtime.input_push_status()


class PushRebuildStatus(_StatSensor):
    """Live dashboard percentage and status; no polling."""
    def __init__(self, runtime):
        super().__init__(runtime, 'push_rebuild_progress', 'COMEXIO Push Neuaufbau Fortschritt')

    _attr_native_unit_of_measurement = '%'

    @property
    def native_value(self):
        return self.runtime.push_rebuild.status()['percent']

    @property
    def extra_state_attributes(self):
        return self.runtime.push_rebuild.status()
