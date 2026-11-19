"""v0.4.9: unified real COMEXIO physical-module metadata, no placeholders.

Synthetic values mirror the seven structural module records observed on the
COMEXIO OS 11.1.5 installation; no actual owner serial number is stored.
"""
from __future__ import annotations

from copy import deepcopy
from types import SimpleNamespace
import re

import pytest

from comexio_local.hardware_devices import discover_hardware, device_identifier, sync_hardware_registry
from comexio_local.device_metadata import device_info
from test_hardware_devices_040 import (
    ENTRY, FakeEntityRegistry, FakeEntityRow, FakeHardwareRegistry,
    _channel, _stub_registry,
)
from test_ha_202611_device_info import NOT_SET, _device_registry_stub


# One controller and the six modules observed in the actual configuration.
# Only structure and TypeIds, never actual controller/extension serials.
HARDWARE = (
    ('1', 'IO-Server-1', 9, '1111-2222-3333', None),
    ('2', 'IO-Ext-1', 10, '1112-2222-3333', 'IO-Extension'),
    ('3', 'IO-Ext-2', 10, '1113-2222-3333', 'IO-Extension'),
    ('4', 'IO-Ext-3', 10, '1114-2222-3333', 'IO-Extension'),
    ('5', 'Uni-Aktor-1', 14, '1115-2222-3333', 'Universal-Aktor'),
    ('6', 'Doorstation', 16, '1116-2222-3333', 'Doorstation'),
    ('7', 'EnOcean', 4, '1117-2222-3333', 'EnOcean-Bridge'),
)


def live_shape():
    return {'FubModules': {'1': {
        idx: {'extension': {
            'ConnectionMethod': 0, 'Id': int(idx),
            'Identifier': serial, 'Location': '',
            'Mode': 0, 'Name': name, 'Pos': int(idx),
            'TypeId': typ, 'Wireless': False,
        }} for idx, name, typ, serial, _ in HARDWARE
    }, '2': {'8': {'Name': 'Virtual marker'}},
        '10': {'9': {'Name': 'A Web-IO command'}}}}


def test_all_six_real_extensions_and_controller_have_correct_metadata():
    devices, sources = discover_hardware(live_shape())
    assert len(devices) == len(sources) == 6
    assert 'IO-Server-1' not in sources
    for idx, name, typ, serial, model in HARDWARE[1:]:
        dev = devices[f'module:1:{idx}']
        assert dev.name == dev.source_name == name
        assert dev.model == model
        assert dev.serial_number == serial
        assert dev.firmware_version is None
        assert device_identifier(ENTRY, dev) == ('comexio_local', f'server-unique:module:1:{idx}')
    assert all('EI' not in item for item in devices)


@pytest.mark.parametrize('typ,expected', [
    (4, 'EnOcean-Bridge'), (10, 'IO-Extension'),
    (14, 'Universal-Aktor'), (16, 'Doorstation'),
    ('10', 'IO-Extension'), (999, None), ('bad', None),
    (None, None), (True, None),
])
def test_known_types_are_translated_but_unrecognized_types_are_never_guessed(typ, expected):
    config = live_shape()
    config['FubModules']['1']['2']['extension']['Name'] = 'Frei umbenannt'
    config['FubModules']['1']['2']['extension']['TypeId'] = typ
    devices, sources = discover_hardware(config)
    assert sources['Frei umbenannt'].model == expected
    assert devices['module:1:2'].key == 'module:1:2'


def test_explicit_comexio_model_wins_and_unspecified_model_does_not_hide_type_id():
    config = live_shape()
    ext = config['FubModules']['1']['2']['extension']
    ext['Model'] = 'IO-Extension Revision C'
    assert discover_hardware(config)[0]['module:1:2'].model == 'IO-Extension Revision C'
    ext['Model'] = 'COMEXIO Erweiterung'
    assert discover_hardware(config)[0]['module:1:2'].model == 'IO-Extension'
    ext['Model'] = 'Unknown'
    assert discover_hardware(config)[0]['module:1:2'].model == 'IO-Extension'
    # Even when the TypeId is unknown, a valid, explicit model is authoritative.
    ext['TypeId'] = 999
    ext['Model'] = 'Reale neue COMEXIO Hardware'
    assert discover_hardware(config)[0]['module:1:2'].model == 'Reale neue COMEXIO Hardware'


@pytest.mark.parametrize('value', [
    '', 'EI5_CO', 'abc', 'unknown', '0000-0000-0000',
    'aa11-bb22-cc33', 'not-a-serial', '1234-5678-9012 and more',
])
def test_invalid_identifiers_are_never_transferred_as_serial_numbers(value):
    config = live_shape()
    config['FubModules']['1']['2']['extension']['Identifier'] = value
    assert discover_hardware(config)[0]['module:1:2'].serial_number is None


def test_explicit_serial_and_firmware_are_module_scoped_and_validated():
    config = live_shape()
    ext = config['FubModules']['1']['2']['extension']
    ext.update(SerialNumber='SN12345678', FirmwareVersion='3.4.5', Version='99.99.99')
    dev = discover_hardware(config)[0]['module:1:2']
    assert dev.serial_number == 'SN12345678'
    assert dev.firmware_version == '3.4.5'
    del ext['FirmwareVersion']
    assert discover_hardware(config)[0]['module:1:2'].firmware_version is None
    ext['Firmware'] = 'Comexio OS 11.1.5'
    assert discover_hardware(config)[0]['module:1:2'].firmware_version is None


def test_unknown_module_can_be_registered_without_invented_model_or_firmware(monkeypatch):
    config = live_shape()
    config['FubModules']['1']['8'] = {'extension': {'Name': 'Neue Erweiterung',
                                                     'Identifier': '1118-2222-3333', 'TypeId': 999}}
    devices, sources = discover_hardware(config)
    unknown = sources['Neue Erweiterung']
    assert unknown.model is None
    assert unknown.serial_number == '1118-2222-3333'
    dr, er = FakeHardwareRegistry(), FakeEntityRegistry([])
    _stub_registry(monkeypatch, dr, er)
    sync_hardware_registry(SimpleNamespace(), ENTRY, {}, devices, sources,
                           controller_firmware='11.1.5')
    row = next(item for item in dr.created if item['name'] == 'Neue Erweiterung')
    assert row['model'] is None
    assert row['serial_number'] == '1118-2222-3333'
    assert 'sw_version' not in row


def test_registry_covers_every_extension_and_updates_without_new_identity(monkeypatch):
    devices, sources = discover_hardware(live_shape())
    dr, er = FakeHardwareRegistry(), FakeEntityRegistry([
        FakeEntityRow('light.kueche', 'server-unique:io:IO-Ext-2/Q1', device_id='root-device'),
        FakeEntityRow('light.fremd', 'server-unique:io:IO-Ext-2/Q1', 'other-entry'),
    ])
    _stub_registry(monkeypatch, dr, er)
    channels = {'a': _channel('IO-Ext-2'), 'b': _channel('EnOcean', 'EI5_CO', kind='binary_input')}
    sync_hardware_registry(SimpleNamespace(), ENTRY, channels, devices, sources,
                           controller_model='IO-Server 2G',
                           controller_firmware='11.1.5', controller_serial='1111-2222-3333')
    assert len(dr.created) == 7
    assert dr.created[0]['serial_number'] == '1111-2222-3333'
    assert dr.created[0]['sw_version'] == '11.1.5'
    for idx, name, typ, serial, model in HARDWARE[1:]:
        row = next(x for x in dr.created if x['name'] == name)
        assert row['model'] == model
        assert row['serial_number'] == serial
        assert 'sw_version' not in row
        assert row['identifiers'] == {('comexio_local', f'server-unique:module:1:{idx}')}
    assert er.rows['light.kueche'].device_id != 'root-device'
    assert er.rows['light.fremd'].device_id == 'root-device'
    assert er.rows['light.kueche'].name == 'Eigener Anzeigename'
    assert er.rows['light.kueche'].area_id == 'kueche'
    assert er.rows['light.kueche'].labels == ('wichtig',)
    number_updated = len(er.updated)
    # Same devices, different COMEXIO display name and serial number.
    config = live_shape()
    config['FubModules']['1']['3']['extension']['Name'] = 'Neue Bezeichnung'
    config['FubModules']['1']['3']['extension']['Identifier'] = '9999-8888-7777'
    renamed, renamed_sources = discover_hardware(config)
    sync_hardware_registry(SimpleNamespace(), ENTRY, channels, renamed, renamed_sources,
                           controller_model='IO-Server 2G',
                           controller_firmware='11.1.5', controller_serial='1111-2222-3333')
    assert len(dr.devices) == 7
    new = next(x for x in dr.created if x['name'] == 'Neue Bezeichnung')
    assert new['identifiers'] == {('comexio_local', 'server-unique:module:1:3')}
    assert new['serial_number'] == '9999-8888-7777'
    assert len(er.updated) == number_updated  # no guessing for renamed sources
    assert er.rows['light.kueche'].area_id == 'kueche'


def test_entity_device_info_contains_same_model_serial_and_module_firmware(monkeypatch):
    _device_registry_stub(monkeypatch)
    config = live_shape()
    config['FubModules']['1']['5']['extension']['FirmwareVersion'] = '2.3.4'
    devices, sources = discover_hardware(config)
    runtime = SimpleNamespace(
        entry=ENTRY, hardware_by_source=sources, firmware_version='11.1.5',
        controller_model='IO-Server 2G', controller_serial_number='1111-2222-3333'
    )
    for idx, name, typ, serial, model in HARDWARE[1:]:
        row = device_info(runtime, _channel(name))
        assert row.identifiers == {('comexio_local', f'server-unique:module:1:{idx}')}
        assert row.model == model and row.serial_number == serial
        assert row.sw_version == ('2.3.4' if idx == '5' else NOT_SET)
    root = device_info(runtime, _channel('IO-Server-1'))
    assert root.identifiers == {('comexio_local', 'server-unique')}
    assert root.model == 'IO-Server 2G'
    assert root.sw_version == '11.1.5'
    assert root.serial_number == '1111-2222-3333'


def test_duplicate_device_names_do_not_move_enocean_or_other_entities(monkeypatch):
    config = live_shape()
    config['FubModules']['1']['7']['extension']['Name'] = 'IO-Ext-2'
    devices, sources = discover_hardware(config)
    assert 'IO-Ext-2' not in sources
    dr, er = FakeHardwareRegistry(), FakeEntityRegistry([
        FakeEntityRow('binary_sensor.contact', 'server-unique:io:IO-Ext-2/EI5_CO',
                      device_id='previous-device')
    ])
    _stub_registry(monkeypatch, dr, er)
    ch = _channel('IO-Ext-2', 'EI5_CO', kind='binary_input')
    sync_hardware_registry(SimpleNamespace(), ENTRY, {ch.key: ch}, devices, sources)
    assert er.rows['binary_sensor.contact'].device_id == 'previous-device'
    assert not er.updated


def test_runtime_refresh_preserves_real_controller_info_after_optional_fetch_failure(monkeypatch):
    """A follow-up System Info failure cannot erase a successful first read."""
    import asyncio
    import importlib
    import sys
    import types
    from comexio_local.device_metadata import ControllerSystemInfo

    dr, er = FakeHardwareRegistry(), FakeEntityRegistry([])
    _stub_registry(monkeypatch, dr, er)
    dispatcher = types.ModuleType('homeassistant.helpers.dispatcher')
    dispatcher.async_dispatcher_send = lambda *_args: None
    monkeypatch.setitem(sys.modules, 'homeassistant.helpers.dispatcher', dispatcher)
    runtime_mod = importlib.import_module('comexio_local.runtime')

    class FakeAdmin:
        calls = 0
        async def read_config(self):
            return live_shape()
        async def read_system_info(self):
            self.calls += 1
            if self.calls == 1:
                return ControllerSystemInfo(firmware_version='11.1.5',
                                            model='IO-Server 2G',
                                            serial_number='1111-2222-3333')
            return ControllerSystemInfo()  # e.g. timeout, missing System Info
        async def read_plans(self, _cfg):
            return {}

    class FakeTCP:
        async def read_sources(self, _channels):
            return {}

    entry = SimpleNamespace(entry_id=ENTRY.entry_id, unique_id=ENTRY.unique_id,
                            data=ENTRY.data, options={})
    hass = SimpleNamespace(config_entries=SimpleNamespace(
        async_update_entry=lambda *_args, **_kwargs: None))
    runtime = runtime_mod.Runtime(hass, entry, FakeAdmin(), FakeTCP())

    async def run():
        await runtime.refresh_discovery()
        await runtime.refresh_discovery()
        assert runtime.controller_model == 'IO-Server 2G'
        assert runtime.firmware_version == '11.1.5'
        assert runtime.controller_serial_number == '1111-2222-3333'
        roots = [item for item in dr.created if item['name'] == 'COMEXIO IO-Server']
        assert len(roots) == 2
        assert roots[0]['model'] == roots[1]['model'] == 'IO-Server 2G'
        assert roots[0]['serial_number'] == roots[1]['serial_number'] == '1111-2222-3333'
        assert len(dr.devices) == 7
    asyncio.run(run())


def test_entity_device_info_does_not_clear_root_fields_when_no_source(monkeypatch):
    _device_registry_stub(monkeypatch)
    runtime = SimpleNamespace(entry=ENTRY, hardware_by_source={},
                              firmware_version=None, controller_model=None,
                              controller_serial_number=None)
    root = device_info(runtime)
    assert root.model is NOT_SET
    assert root.sw_version is NOT_SET
    assert root.serial_number is NOT_SET
