"""Validate that a *real* valid webhook is added to the in-memory journal."""
import importlib
import sys
import types
from types import SimpleNamespace

from comexio_local.discovery import Channel


def test_runtime_records_accepted_events_without_polling(monkeypatch):
    # Stub the HA dispatcher and entity registry, not the runtime or journal code.
    dispatches = []
    dispatcher = types.ModuleType('homeassistant.helpers.dispatcher')
    dispatcher.async_dispatcher_send = lambda _hass, signal: dispatches.append(signal)
    registry = types.ModuleType('homeassistant.helpers.entity_registry')
    class Registry:
        def async_get_entity_id(self, domain, platform, unique_id):
            assert (domain, platform, unique_id) == ('light', 'comexio_local', 'entry-1:io:IO-Ext-2/Q2')
            return 'light.buero'
    registry.async_get = lambda _hass: Registry()
    monkeypatch.setitem(sys.modules, 'homeassistant', types.ModuleType('homeassistant'))
    monkeypatch.setitem(sys.modules, 'homeassistant.helpers', types.ModuleType('homeassistant.helpers'))
    monkeypatch.setitem(sys.modules, 'homeassistant.helpers.dispatcher', dispatcher)
    monkeypatch.setitem(sys.modules, 'homeassistant.helpers.entity_registry', registry)

    module = importlib.import_module('comexio_local.runtime')
    recorded = []
    bus = SimpleNamespace(async_fire=lambda name, data: recorded.append((name, data)))
    hass = SimpleNamespace(bus=bus)
    entry = SimpleNamespace(entry_id='entry-1', unique_id=None)
    rt = module.Runtime(hass, entry, admin=None, tcp=None)
    ch = Channel(kind='light', name='Buero Licht', key='io:IO-Ext-2/Q2',
                 extension='IO-Ext-2', identifier='Q2')
    rt.channels = {ch.key: ch}
    rt.values[ch.key] = False

    assert rt.apply_event({'type': 'io', 'ext': 'IO-Ext-2', 'io': 'Q2', 'value': 1})
    assert rt.events == 1
    assert rt.values[ch.key] is True
    assert rt.push_events_report()['last_events'][0]['entity_id'] == 'light.buero'
    assert recorded[0][0] == 'comexio_local_push'
    assert recorded[0][1]['value'] == 1
    assert rt.state_signal in dispatches
    assert rt.apply_event({'type': 'io', 'ext': 'IO-Ext-2', 'io': 'Q2', 'value': 1})
    assert rt.push_journal.same_as_cached == 1
    assert rt.events == 2

    assert not rt.apply_event({'type': 'io', 'ext': 'IO-Ext-2', 'io': 'Q99', 'value': 0})
    assert rt.rejected_events == 1
    assert rt.push_journal.total == 2
