"""v0.4.0: physical device registry, stable channel ownership and no fabricated IO."""
from __future__ import annotations

from dataclasses import dataclass
from types import SimpleNamespace
import sys
import types

import pytest

from comexio_local.discovery import Channel
from comexio_local.hardware_devices import (
    discover_hardware, device_identifier, sync_hardware_registry,
)
from comexio_local.device_metadata import device_info


ENTRY = SimpleNamespace(entry_id='entry-01', unique_id='server-unique',
                        data={'host': 'example.invalid'})


def sample_config():
    return {'FubModules': {
        '1': {
            '1': {'extension': {'Name': 'IO-Server-1', 'Model': 'IO-Server 2G'},
                  'inoutput': {'9': {'Identifier': 'Q1', 'Active': 1}}},
            '5': {'extension': {'Name': 'IO-Ext-2', 'Model': 'IO-Extension'},
                  'inoutput': {'4': {'Identifier': 'Q1', 'Active': 1}}},
            '8': {'extension': {'Name': 'Universal-Aktor 1', 'TypeName': 'Universal Aktor'},
                  'inoutput': {'14': {'Identifier': 'Q1', 'Active': 1}}},
        },
        '3': {
            # No active IOs: the physical radio gateway is still a real device.
            '11': {'extension': {'Name': 'EnOcean-Bridge 1', 'HardwareType': 'EnOcean Bridge'},
                   'inoutput': {}}
        },
        '2': {'91': {'Name': 'R_Test_ist', 'Id': 91}},
        '10': {'8': {'Name': 'CL Push Home Assistant'}},
    }}


def _channel(extension, identifier='Q1', kind='light', io_id=14):
    return Channel(kind=kind, name=f'COMEXIO {extension}',
                   key=f'io:{extension}/{identifier}', extension=extension,
                   identifier=identifier, io_id=io_id)


def test_discovery_registers_real_cards_even_without_active_channels():
    hardware, origin = discover_hardware(sample_config())
    assert set(hardware) == {'module:1:5', 'module:1:8', 'module:3:11'}
    assert origin['Universal-Aktor 1'].model == 'Universal Aktor'
    assert origin['EnOcean-Bridge 1'].model == 'EnOcean Bridge'
    assert origin['IO-Ext-2'].name == 'IO-Ext-2'
    assert 'IO-Server-1' not in origin
    assert device_identifier(ENTRY, origin['IO-Ext-2']) == (
        'comexio_local', 'server-unique:module:1:5')


def test_only_explicit_physical_metadata_is_registered():
    config = sample_config()
    config['FubModules']['4'] = {'17': {'Name': 'EnOcean Taster', 'Id': 17},
                                 '18': {'extension': {'Name': ''}},
                                 '19': {'extension': {'Name': 'Other Extension'}}}
    hardware, origin = discover_hardware(config)
    assert 'module:4:17' not in hardware
    assert 'module:4:18' not in hardware
    assert 'module:4:19' in hardware
    assert origin['Other Extension'].model == 'COMEXIO Erweiterung'


def test_module_key_does_not_depend_on_name_or_model():
    config = sample_config()
    before, _ = discover_hardware(config)
    config['FubModules']['1']['8']['extension']['Name'] = 'Umbenannt'
    config['FubModules']['1']['8']['extension']['TypeName'] = 'Other model'
    after, origin = discover_hardware(config)
    assert before['module:1:8'].key == after['module:1:8'].key
    assert 'Umbenannt' in origin


def test_duplicate_source_names_are_not_implicitly_assigned_to_a_module():
    config = sample_config()
    config['FubModules']['3']['11']['extension']['Name'] = 'IO-Ext-2'
    devices, origin = discover_hardware(config)
    assert len(devices) == 3
    assert 'IO-Ext-2' not in origin


@dataclass
class FakeEntityRow:
    entity_id: str
    unique_id: str
    config_entry_id: str = ENTRY.entry_id
    platform: str = 'comexio_local'
    device_id: str = 'root-device'
    name: str | None = 'Eigener Anzeigename'
    area_id: str | None = 'kueche'
    labels: tuple[str, ...] = ('wichtig',)


class FakeHardwareRegistry:
    def __init__(self):
        self.devices = {}
        self.created = []

    def async_get_or_create(self, **kwargs):
        identifier = next(iter(kwargs['identifiers']))
        self.created.append(kwargs)
        if identifier not in self.devices:
            self.devices[identifier] = SimpleNamespace(id='root-device' if identifier == (
                'comexio_local', 'server-unique') else f'device-{len(self.devices)}')
        return self.devices[identifier]


class FakeEntityRegistry:
    def __init__(self, rows):
        self.rows = {row.entity_id: row for row in rows}
        self.updated = []

    def async_update_entity(self, entity_id, **kwargs):
        assert set(kwargs) == {'device_id'}
        self.updated.append((entity_id, kwargs['device_id']))
        self.rows[entity_id].device_id = kwargs['device_id']


def _stub_registry(monkeypatch, hardware_reg, entity_reg):
    dr = types.ModuleType('homeassistant.helpers.device_registry')
    dr.async_get = lambda _: hardware_reg
    er = types.ModuleType('homeassistant.helpers.entity_registry')
    er.async_get = lambda _: entity_reg
    er.async_entries_for_config_entry = lambda _, eid: [v for v in entity_reg.rows.values()
                                                         if v.config_entry_id == eid]
    monkeypatch.setitem(sys.modules, 'homeassistant', types.ModuleType('homeassistant'))
    monkeypatch.setitem(sys.modules, 'homeassistant.helpers', types.ModuleType('homeassistant.helpers'))
    monkeypatch.setitem(sys.modules, 'homeassistant.helpers.device_registry', dr)
    monkeypatch.setitem(sys.modules, 'homeassistant.helpers.entity_registry', er)


def test_device_assignment_moves_only_own_registered_io_entities(monkeypatch):
    hardware, origin = discover_hardware(sample_config())
    ext = _channel('IO-Ext-2')
    universal = _channel('Universal-Aktor 1')
    unknown = _channel('Not-Reported')
    own_rows = [
        FakeEntityRow('light.kueche', f'server-unique:{ext.key}'),
        FakeEntityRow('light.universal', f'server-unique:{universal.key}'),
        FakeEntityRow('light.unknown', f'server-unique:{unknown.key}'),
        FakeEntityRow('cover.rollo', 'server-unique:cover:M85'),
        FakeEntityRow('sensor.diagnose', 'entry-01-events'),
        FakeEntityRow('light.foreign', f'server-unique:{ext.key}', 'another-entry'),
    ]
    dr, er = FakeHardwareRegistry(), FakeEntityRegistry(own_rows)
    _stub_registry(monkeypatch, dr, er)
    cover = Channel(kind='cover', name='Roll', key='cover:M85', marker_id=85)
    channels = {c.key: c for c in (ext, universal, unknown, cover)}
    sync_hardware_registry(SimpleNamespace(), ENTRY, channels, hardware, origin)
    assert {r.entity_id for r in own_rows if r.device_id != 'root-device'} == {
        'light.kueche', 'light.universal'}
    assert er.rows['light.kueche'].name == 'Eigener Anzeigename'
    assert er.rows['light.kueche'].area_id == 'kueche'
    assert er.rows['light.kueche'].labels == ('wichtig',)
    assert er.rows['light.foreign'].device_id == 'root-device'
    assert len(dr.created) == 4  # controller plus 3 physical modules, even if empty
    assert len(er.updated) == 2
    # Repeated read cannot churn any existing registry entries.
    sync_hardware_registry(SimpleNamespace(), ENTRY, channels, hardware, origin)
    assert len(er.updated) == 2


def test_ambiguous_origin_does_not_move_entity_out_of_existing_device(monkeypatch):
    config = sample_config()
    config['FubModules']['3']['11']['extension']['Name'] = 'IO-Ext-2'
    devices, origin = discover_hardware(config)
    channel = _channel('IO-Ext-2')
    row = FakeEntityRow('light.kueche', f'server-unique:{channel.key}', device_id='previous-card')
    dr, er = FakeHardwareRegistry(), FakeEntityRegistry([row])
    _stub_registry(monkeypatch, dr, er)
    sync_hardware_registry(SimpleNamespace(), ENTRY, {channel.key: channel}, devices, origin)
    assert row.device_id == 'previous-card'
    assert er.updated == []


def test_device_info_ha202611_dataclass_selects_real_module_only(monkeypatch):
    from test_ha_202611_device_info import _device_registry_stub
    _device_registry_stub(monkeypatch)
    devices, source = discover_hardware(sample_config())
    runtime = SimpleNamespace(entry=ENTRY, firmware_version='11.1.5',
                              hardware_by_source=source)
    physical = device_info(runtime, _channel('Universal-Aktor 1'))
    assert physical.name == 'Universal-Aktor 1'
    assert physical.model == 'Universal Aktor'
    assert physical.identifiers == {('comexio_local', 'server-unique:module:1:8')}
    from test_ha_202611_device_info import NOT_SET
    assert physical.sw_version is NOT_SET
    root = device_info(runtime, Channel(kind='cover', name='Rollo', key='cover:M79', marker_id=79))
    assert root.identifiers == {('comexio_local', 'server-unique')}
    assert root.sw_version == '11.1.5'
    unrecognized = device_info(runtime, _channel('Other-Card'))
    assert unrecognized.identifiers == {('comexio_local', 'server-unique')}



def test_runtime_live_discovery_updates_hardware_catalog_without_comexio_writes(monkeypatch):
    import asyncio
    import importlib
    config = sample_config()
    for module, description in [('1', 'Licht Flur'), ('5', 'Licht Küche'), ('8', 'Licht Garage')]:
        config['FubModules']['1'][module]['inoutput'] = {
            '4': {'Id': int(module) * 10, 'Identifier': 'Q1', 'Active': True,
                  'Description': description}}

    dr, er = FakeHardwareRegistry(), FakeEntityRegistry([])
    _stub_registry(monkeypatch, dr, er)
    dispatcher = types.ModuleType('homeassistant.helpers.dispatcher')
    dispatcher.async_dispatcher_send = lambda *_: None
    monkeypatch.setitem(sys.modules, 'homeassistant.helpers.dispatcher', dispatcher)
    runtime_mod = importlib.import_module('comexio_local.runtime')
    counts = {'read_config': 0, 'read_plans': 0, 'writes': 0}

    class FakeAdmin:
        async def read_config(self):
            counts['read_config'] += 1
            return config
        async def read_plans(self, c):
            counts['read_plans'] += 1
            assert c is config
            return {}

    class FakeTCP:
        async def read_sources(self, channels):
            return {c.key: True for c in channels}

    entry = SimpleNamespace(entry_id=ENTRY.entry_id, unique_id=ENTRY.unique_id,
                            data=ENTRY.data, options={})
    updates = []
    hass = SimpleNamespace(config_entries=SimpleNamespace(
        async_update_entry=lambda _entry, **kwargs: updates.append(kwargs)))
    runtime = runtime_mod.Runtime(hass, entry, FakeAdmin(), FakeTCP())

    async def run():
        added, removed = await runtime.refresh_discovery()
        assert added == 3 and removed == 0
        assert len(runtime.hardware_devices) == 3
        assert 'IO-Ext-2' in runtime.hardware_by_source
        assert runtime.channels['io:IO-Server-1/Q1'].kind == 'light'
        assert counts == {'read_config': 1, 'read_plans': 1, 'writes': 0}
        assert len(dr.created) == 4
    asyncio.run(run())


def test_hardware_registry_failure_does_not_block_channel_discovery(monkeypatch, caplog):
    """HA registry errors must not disable existing TCP/Webhook functionality."""
    import asyncio
    import importlib
    config = sample_config()
    config['FubModules']['1']['5']['inoutput'] = {
        '4': {'Id': 50, 'Identifier': 'Q1', 'Active': True,
              'Description': 'Licht Kueche'}}
    dispatcher = types.ModuleType('homeassistant.helpers.dispatcher')
    dispatcher.async_dispatcher_send = lambda *_: None
    monkeypatch.setitem(sys.modules, 'homeassistant.helpers.dispatcher', dispatcher)
    runtime_mod = importlib.import_module('comexio_local.runtime')
    hardware_mod = importlib.import_module('comexio_local.hardware_devices')

    def fail_sync(*_args, **_kwargs):
        raise RuntimeError('HA device registry unavailable')

    monkeypatch.setattr(hardware_mod, 'sync_hardware_registry', fail_sync)

    class FakeAdmin:
        async def read_config(self):
            return config
        async def read_plans(self, _config):
            return {}

    class FakeTCP:
        async def read_sources(self, channels):
            return {c.key: True for c in channels}

    entry = SimpleNamespace(entry_id=ENTRY.entry_id, unique_id=ENTRY.unique_id,
                            data=ENTRY.data, options={})
    hass = SimpleNamespace(config_entries=SimpleNamespace(
        async_update_entry=lambda *_args, **_kwargs: None))
    runtime = runtime_mod.Runtime(hass, entry, FakeAdmin(), FakeTCP())

    async def run():
        added, removed = await runtime.refresh_discovery()
        assert added > 0 and removed == 0
        assert runtime.channels
        assert runtime._initialised is True
        assert runtime.hardware_by_source == {}
        assert runtime.hardware_devices
        assert runtime.value(next(iter(runtime.channels))) is not None

    with caplog.at_level('ERROR'):
        asyncio.run(run())
    assert 'keeping existing controller assignment' in caplog.text
