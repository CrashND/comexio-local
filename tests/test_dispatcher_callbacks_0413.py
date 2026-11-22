"""v0.4.13: synchronous HA dispatcher handlers are marked for the event loop.

Emulates HA callback classification in offline mocks. It is not a real HA run.
"""
from __future__ import annotations

import asyncio
from enum import IntFlag
import importlib.util
from pathlib import Path
import sys
import types
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[1] / 'custom_components' / 'comexio_local'


def _stub_home_assistant(monkeypatch):
    """Use a marker to emulate HA's callback recognition (not a real dispatcher)."""
    core = types.ModuleType('homeassistant.core')
    def callback(func):
        func.__homeassistant_callback__ = True
        return func
    core.callback = callback
    listeners = {}
    dispatcher = types.ModuleType('homeassistant.helpers.dispatcher')
    def connect(_hass, signal, func):
        listeners.setdefault(signal, []).append(func)
        return lambda: listeners[signal].remove(func)
    dispatcher.async_dispatcher_connect = connect
    base = types.ModuleType('comexio_local.entities')
    class BaseChannel:
        def __init__(self, runtime, channel):
            self.runtime, self.channel = runtime, channel
    base.BaseChannel = BaseChannel
    class Feature(IntFlag):
        OPEN = 1
        CLOSE = 2
        SET_POSITION = 4
    modules = {
        'homeassistant': types.ModuleType('homeassistant'),
        'homeassistant.core': core,
        'homeassistant.helpers': types.ModuleType('homeassistant.helpers'),
        'homeassistant.helpers.dispatcher': dispatcher,
        'homeassistant.components': types.ModuleType('homeassistant.components'),
        'homeassistant.components.light': types.ModuleType('homeassistant.components.light'),
        'homeassistant.components.cover': types.ModuleType('homeassistant.components.cover'),
        'homeassistant.components.binary_sensor': types.ModuleType('homeassistant.components.binary_sensor'),
        'homeassistant.components.switch': types.ModuleType('homeassistant.components.switch'),
        'homeassistant.components.sensor': types.ModuleType('homeassistant.components.sensor'),
        'homeassistant.exceptions': types.ModuleType('homeassistant.exceptions'),
        'homeassistant.const': types.ModuleType('homeassistant.const'),
        'comexio_local.entities': base,
    }
    for key, module in modules.items():
        monkeypatch.setitem(sys.modules, key, module)
    light = modules['homeassistant.components.light']
    light.LightEntity = type('LightEntity', (), {})
    light.ColorMode = SimpleNamespace(ONOFF='onoff')
    cover = modules['homeassistant.components.cover']
    cover.CoverEntity = type('CoverEntity', (), {})
    cover.CoverDeviceClass = SimpleNamespace(AWNING='awning', SHUTTER='shutter')
    cover.CoverEntityFeature = Feature
    binary = modules['homeassistant.components.binary_sensor']
    binary.BinarySensorEntity = type('BinarySensorEntity', (), {})
    binary.BinarySensorDeviceClass = SimpleNamespace(OCCUPANCY='occupancy', MOTION='motion')
    modules['homeassistant.components.switch'].SwitchEntity = type('SwitchEntity', (), {})
    modules['homeassistant.components.sensor'].SensorEntity = type('SensorEntity', (), {})
    modules['homeassistant.const'].EntityCategory = SimpleNamespace(DIAGNOSTIC='diagnostic')
    modules['homeassistant.exceptions'].HomeAssistantError = type('HomeAssistantError', (Exception,), {})
    return listeners


def _load(name, monkeypatch):
    path = ROOT / f'{name}.py'
    module_name = f'comexio_local._callback_0413_{name}'
    spec = importlib.util.spec_from_file_location(module_name, path)
    module = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, module_name, module)
    spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize('platform,kind', [
    ('binary_sensor', 'binary_input'),
    ('light', 'light'),
    ('switch', 'switch'),
    ('cover', 'cover'),
    ('sensor', 'enocean_sensor'),
])
def test_discovery_listener_runs_in_ha_event_loop_and_adds_new_channels(monkeypatch, platform, kind):
    listeners = _stub_home_assistant(monkeypatch)
    module = _load(platform, monkeypatch)
    initial = SimpleNamespace(key='io:EnOcean/EI1_' + kind, kind=kind, is_enocean=True)
    added = SimpleNamespace(key='io:EnOcean/EI2_' + kind, kind=kind, is_enocean=True)
    runtime = SimpleNamespace(channels={initial.key: initial}, discovery_signal='discovery',
                              entry=SimpleNamespace(entry_id='entry'))
    recorded = []
    unloaded = []
    entry = SimpleNamespace(entry_id='entry', async_on_unload=unloaded.append)
    hass = SimpleNamespace(data={'comexio_local': {'entry': runtime}})

    async def run():
        loop = asyncio.get_running_loop()
        def add_entities(items):
            assert asyncio.get_running_loop() is loop, 'HA async_add_entities outside event loop'
            recorded.extend(items)
        await module.async_setup_entry(hass, entry, add_entities)
        if platform == 'sensor':
            assert len(recorded) == 9  # eight diagnostic sensors plus one EnOcean sensor
            assert any(getattr(ent, 'channel', None) is initial for ent in recorded)
        else:
            assert len(recorded) == 1
            assert recorded[0].channel is initial
        assert len(listeners['discovery']) == 1
        listener = listeners['discovery'][0]
        assert getattr(listener, '__homeassistant_callback__', False), f'{platform} listener not @callback'
        runtime.channels[added.key] = added
        listener()
        assert sum(getattr(e, 'channel', None) is added for e in recorded) == 1
        listener()
        assert sum(getattr(e, 'channel', None) is added for e in recorded) == 1
        assert len(unloaded) == 1
        unloaded[0]()
        assert not listeners['discovery']

    asyncio.run(run())


def test_entity_catalog_listener_updates_existing_entity_on_event_loop(monkeypatch):
    listeners = _stub_home_assistant(monkeypatch)
    # Use real BaseChannel rather than the platform-test substitute.
    entity_module = types.ModuleType('homeassistant.helpers.entity')
    class Entity:
        def async_on_remove(self, cb):
            self._unload.append(cb)
        def async_write_ha_state(self):
            assert asyncio.get_running_loop() is self._loop
            self.state_writes += 1
    entity_module.Entity = Entity
    monkeypatch.setitem(sys.modules, 'homeassistant.helpers.entity', entity_module)
    monkeypatch.delitem(sys.modules, 'comexio_local.entities', raising=False)
    module = _load('entities', monkeypatch)
    initial = SimpleNamespace(key='io:EnOcean/EI5_CO', name='Wohnung OG', kind='binary_input')
    updated = SimpleNamespace(key=initial.key, name='Eingang OG', kind='binary_input')
    entry = SimpleNamespace(entry_id='e', unique_id='uid', options={})
    runtime = SimpleNamespace(channels={initial.key: initial}, entry=entry,
                              state_signal='state', discovery_signal='discovery')
    entity = module.BaseChannel(runtime, initial)
    entity._unload = []
    entity.state_writes = 0
    entity.entity_id = None
    entity.hass = SimpleNamespace()

    async def run():
        entity._loop = asyncio.get_running_loop()
        await entity.async_added_to_hass()
        handler = listeners['discovery'][0]
        assert getattr(handler, '__homeassistant_callback__', False)
        runtime.channels[updated.key] = updated
        handler()
        assert entity.channel is updated
        assert entity._attr_name == 'Eingang OG'
        assert entity.state_writes == 1
        for cb in entity._unload:
            cb()
        assert not listeners['discovery']
    asyncio.run(run())
