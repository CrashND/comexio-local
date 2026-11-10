"""v0.4.4 EnOcean: observed COMEXIO metadata, isolated additive push and HA identities.

These are offline/mock tests. They do not assert actual firmware support for EI
TCP GET, Web-IO analog ranges or sender radio IDs.
"""
from __future__ import annotations

import asyncio
from copy import deepcopy
from types import SimpleNamespace

import pytest

from comexio_local.admin_api import AdminError, make_push_command
from comexio_local.discovery import Channel, discover
from comexio_local.entity_sync import entity_domain
from comexio_local.hardware_devices import discover_hardware, device_identifier, sync_hardware_registry
from comexio_local.input_push import _groups, _select, apply_input_push, input_catalog, inspect_input_push
from comexio_local.preferences import apply_classifications
from comexio_local.push_setup import push_sources
from comexio_local.webio_command import WebIOCommand
from test_discovery import _config
from test_input_push_0363 import InputAdminFake
from test_push_audit import BASE, ENTRY, PATH, _installed
from test_hardware_devices_040 import ENTRY as HA_ENTRY, FakeHardwareRegistry, FakeEntityRegistry, FakeEntityRow, _stub_registry

# The exact 19 rows supplied by the user on 2026-11-10 (18 EI plus TL1).
EI_ROWS = [
    (190, 'TL1', 12, 2),
    (191, 'EI1_A0', 23, 1), (192, 'EI1_AI', 23, 1),
    (193, 'EI2_SVC', 22, 2), (194, 'EI2_PIRS', 22, 2),
    (195, 'EI3_SVC', 22, 2), (196, 'EI3_ILL', 22, 2), (197, 'EI3_PIRS', 23, 1),
    (198, 'EI4_SVC', 22, 2), (199, 'EI4_ILL', 22, 2), (200, 'EI4_PIRS', 23, 1),
    (201, 'EI5_CO', 23, 1),
    (202, 'EI6_SVC', 22, 2), (203, 'EI6_ILL', 22, 2), (204, 'EI6_PIRS', 23, 1),
    (206, 'EI7_A0', 23, 1), (207, 'EI7_AI', 23, 1),
    (208, 'EI7_B0', 23, 1), (209, 'EI7_BI', 23, 1),
]


def enocean_config():
    config = _config()
    channels = {}
    for id_value, identifier, typ, conn in EI_ROWS:
        channels[str(id_value)] = {
            'Id': id_value, 'Identifier': identifier,
            'Description': identifier, 'Active': 1,
            'InOutputTypeId': typ, 'ConnectionType': conn,
            'CategoryId': 3, 'InOutputIdentifierTypeId': 14 if identifier == 'TL1' else (15 if typ == 22 else 16),
            'IntIsOutput': 0,
        }
    config['FubModules']['1']['9'] = {'extension': {'Name': 'EnOcean'}, 'inoutput': channels}
    return config


def test_all_real_enocean_channels_and_analog_pirs_semantics():
    raw = discover(enocean_config())
    enocean = {key: c for key, c in raw.items() if c.is_enocean}
    assert len(enocean) == 18
    assert len([c for c in enocean.values() if c.analog]) == 8
    assert len([c for c in enocean.values() if not c.analog]) == 10
    assert 'io:EnOcean/TL1' not in raw
    analog_presence = raw['io:EnOcean/EI2_PIRS']
    assert analog_presence.kind == 'binary_input'
    assert analog_presence.analog is True
    assert analog_presence.push_maximum == 1023
    digital_motion = raw['io:EnOcean/EI3_PIRS']
    assert digital_motion.kind == 'binary_input' and digital_motion.analog is False
    assert raw['io:EnOcean/EI3_ILL'].kind == 'enocean_sensor'
    assert raw['io:EnOcean/EI3_SVC'].kind == 'enocean_sensor'
    assert raw['io:EnOcean/EI7_A0'].input_mode == 'taster'
    assert raw['io:EnOcean/EI5_CO'].input_mode == 'schalter'
    assert all(c.is_push_source for c in enocean.values())
    # A normal hardware AI does not silently become a sensor or a push source.
    assert raw['io:IO-Ext-2/Q1'].kind == 'light'
    assert 'io:IO-Ext-2/AI1' not in raw
    assert not any(c.is_enocean for c in push_sources(raw))
    assert entity_domain('analog_input') is None
    assert entity_domain('enocean_sensor') == 'sensor'
    assert entity_domain('binary_input') == 'binary_sensor'


def test_enocean_names_slots_and_unknown_suffixes_are_generic_and_stable():
    config = enocean_config()
    original = discover(config)
    config['FubModules']['1']['9']['inoutput']['196']['Description'] = 'Ganz andere Helligkeit'
    changed = discover(config)
    key = 'io:EnOcean/EI3_ILL'
    assert changed[key].key == original[key].key
    assert changed[key].name != original[key].name
    config['FubModules']['1']['9']['inoutput']['250'] = {
        'Id': 250, 'Identifier': 'EI20_HUM', 'Active': 1,
        'InOutputTypeId': 22, 'ConnectionType': 2,
    }
    config['FubModules']['1']['9']['inoutput']['251'] = {
        'Id': 251, 'Identifier': 'EI21_ALARM', 'Active': 1,
        'InOutputTypeId': 23, 'ConnectionType': 1,
    }
    config['FubModules']['1']['9']['inoutput']['252'] = {
        'Id': 252, 'Identifier': 'EI22_BAD', 'Active': 1,
        'InOutputTypeId': 23, 'ConnectionType': 2,
    }
    config['FubModules']['1']['9']['inoutput']['253'] = {
        'Id': 253, 'Identifier': 'EI23_BAD', 'Active': 1,
        'InOutputTypeId': 23, 'ConnectionType': 1, 'IntIsOutput': 1,
    }
    expanded = discover(config)
    assert 'io:EnOcean/EI23_BAD' not in expanded
    assert expanded['io:EnOcean/EI20_HUM'].kind == 'enocean_sensor'
    assert expanded['io:EnOcean/EI21_ALARM'].kind == 'binary_input'
    assert 'io:EnOcean/EI22_BAD' not in expanded  # metadata contradiction, fail closed
    c = expanded['io:EnOcean/EI20_HUM']
    assert c.enocean_slot == 20 and c.enocean_signal == 'HUM'
    assert c.push_maximum == 1023


def test_selectable_input_catalog_preserves_original_physical_i_and_ai_plan():
    config = enocean_config()
    config['FubModules']['1']['5']['inoutput']['99'] = {
        'Id': 99, 'Identifier': 'I1', 'Active': 1, 'Description': 'Taster'}
    config['FubModules']['1']['5']['inoutput']['98'] = {
        'Id': 98, 'Identifier': 'AI2', 'Active': 1, 'Description': 'Thermometer'}
    raw = discover(config)
    catalog = input_catalog(raw)
    assert len(catalog) == 20
    groups = _groups(raw, ENTRY)
    assert len({groups[key][0] for key in catalog if raw[key].is_enocean}) == 7
    assert groups['io:EnOcean/EI3_ILL'][0] == 'CL Eingänge EnOcean EI3'
    assert len({groups[f'io:EnOcean/EI3_{suffix}'][2] for suffix in ('PIRS', 'SVC', 'ILL')}) == 3
    assert groups['io:IO-Ext-2/I1'][0] == 'CL Eingänge IO-Ext-2 I1-I18'
    assert groups['io:IO-Ext-2/AI2'][0] == 'CL Eingänge IO-Ext-2 AI1-AI18'
    selected = _select(raw, {'io:EnOcean/EI3_ILL': 'auto', 'io:EnOcean/EI2_PIRS': 'auto',
                             'io:IO-Ext-2/I1': 'taster', 'io:IO-Ext-2/AI2': 'schalter'})
    assert selected['io:EnOcean/EI3_ILL'].analog
    assert selected['io:EnOcean/EI2_PIRS'].analog
    assert selected['io:IO-Ext-2/AI2'].analog is False
    assert apply_classifications(raw, {'input_modes': {'io:EnOcean/EI3_ILL': 'taster'}})[
        'io:EnOcean/EI3_ILL'].kind == 'enocean_sensor'
    with pytest.raises(AdminError):
        _select(raw, {'io:EnOcean/EI3_ILL': 'taster'})


def test_enocean_webio_commands_preserve_numeric_range_and_old_analog_cover():
    raw = discover(enocean_config())
    for key in ('io:EnOcean/EI2_PIRS', 'io:EnOcean/EI3_ILL', 'io:EnOcean/EI3_SVC'):
        channel = raw[key]
        cmd = make_push_command(channel, PATH, name=f'CL Eingang EnOcean/{channel.identifier}')
        assert (cmd['TypeId'], cmd['Min'], cmd['Max']) == (2, 0, 1023)
        assert f'io="{channel.identifier}"' in cmd['Data']
        spec = WebIOCommand.from_import(cmd)
        assert spec.as_append_form('77', '9')['max_cmd_io_0'] == 1023
    digital = raw['io:EnOcean/EI3_PIRS']
    cmd = make_push_command(digital, PATH, name='CL Eingang EnOcean/EI3_PIRS')
    assert (cmd['TypeId'], cmd['Max']) == (1, 1)
    cover = Channel(kind='cover', name='Rollo', key='cover:M79', marker_id=79, analog=True)
    cmd_cover = make_push_command(cover, PATH, name='CL Rollladen Test M79')
    assert (cmd_cover['TypeId'], cmd_cover['Max']) == (2, 100)


def test_enocean_entirely_belongs_to_one_existing_bridge(monkeypatch):
    raw = discover(enocean_config())
    devices, by_source = discover_hardware(enocean_config())
    bridge = by_source['EnOcean']
    assert bridge.name == 'EnOcean'
    assert all(':EI' not in key for key in devices)
    assert bridge.key in devices
    assert '5148ce2' not in bridge.key  # radio sender ID unavailable in config

    # All 18 EnOcean channels, not just a sample, belong to one physical
    # HA device. The individual EI addresses remain stable entity identities.
    own_rows = [
        FakeEntityRow(
            ('sensor' if c.kind == 'enocean_sensor' else 'binary_sensor')
            + f'.test_{c.identifier.lower()}',
            f'server-unique:{c.key}',
        )
        for c in raw.values() if c.is_enocean
    ]
    assert len(own_rows) == 18
    dr, er = FakeHardwareRegistry(), FakeEntityRegistry(own_rows)
    _stub_registry(monkeypatch, dr, er)
    sync_hardware_registry(SimpleNamespace(), HA_ENTRY, raw, devices, by_source)
    bridge_id = dr.devices[device_identifier(HA_ENTRY, bridge)].id
    assert {er.rows[r].device_id for r in er.rows} == {bridge_id}
    assert len([d for d in dr.created if ':EI' in next(iter(d['identifiers']))[1]]) == 0
    assert all(row.name == 'Eigener Anzeigename' for row in er.rows.values())
    assert len(er.updated) == 18

    # The device_info on newly instantiated sensor entities agrees with the
    # existing registry bridge identity (not just after a registry sync).
    from comexio_local.device_metadata import device_info
    from test_ha_202611_device_info import _device_registry_stub
    _device_registry_stub(monkeypatch)
    runtime = SimpleNamespace(entry=HA_ENTRY, hardware_devices=devices,
                              hardware_by_source=by_source, firmware_version='11.1.5')
    for c in raw.values():
        if c.is_enocean:
            assert device_info(runtime, c).identifiers == {device_identifier(HA_ENTRY, bridge)}


def test_enocean_sync_never_deletes_ha_devices(monkeypatch):
    """Discovery/association must not include registry cleanup side effects."""
    raw = discover(enocean_config())
    devices, by_source = discover_hardware(enocean_config())

    class RegistryWithForbiddenDeletion(FakeHardwareRegistry):
        def async_remove_device(self, _device_id):
            pytest.fail('Device registry deletion is not part of hardware discovery')

    dr = RegistryWithForbiddenDeletion()
    er = FakeEntityRegistry([])
    _stub_registry(monkeypatch, dr, er)
    sync_hardware_registry(SimpleNamespace(), HA_ENTRY, raw, devices, by_source)
    assert len(dr.created) == len(devices) + 1  # root plus real modules only


def test_enocean_preview_and_additive_provision_are_idempotent(monkeypatch):
    from comexio_local import input_push
    config, plans, _ = _installed()  # installed v0.4.3 light/cover resources
    config['FubModules']['1']['9'] = enocean_config()['FubModules']['1']['9']
    admin = InputAdminFake(config, plans)
    original_plans = deepcopy(admin.plans)
    original_light_webio = deepcopy(admin.config['FubModules']['10']['19'])
    chosen = {f'io:EnOcean/{identifier}': 'auto' for identifier in
              ('EI2_PIRS', 'EI3_PIRS', 'EI3_ILL', 'EI3_SVC', 'EI1_A0', 'EI5_CO')}
    raw = discover(config)

    async def append(admin, device_id, base_id, command):
        admin.writes.append(('append', command['Name'], admin.write_gap))
        admin.next_cmd += 1
        admin.config['FubModules']['10'][str(device_id)][str(admin.next_cmd)] = deepcopy(command)

    monkeypatch.setattr(input_push, '_append_command', append)

    async def check():
        first = await inspect_input_push(admin, raw, ENTRY, PATH, BASE, chosen)
        assert first['needs_write'] and not admin.writes
        assert first['plan_count'] == 4
        assert all(row['action'] == 'anlegen' for row in first['sources'])
        with pytest.raises(AdminError, match='sicherung'):
            await apply_input_push(admin, raw, ENTRY, PATH, BASE,
                                   chosen, first['fingerprint'], False)
        assert not admin.writes
        stats = await apply_input_push(admin, raw, ENTRY, PATH, BASE,
                                       chosen, first['fingerprint'], True)
        assert stats['verified'] == len(chosen)
        assert stats['added_links'] == len(chosen)
        assert stats['activated_plans'] == 4
        assert admin.plans | original_plans == admin.plans
        assert all(admin.plans[fid] == original_plans[fid] for fid in original_plans)
        assert admin.config['FubModules']['10']['19'] == original_light_webio
        assert any(w[0] == 'wire' and w[-1] is True for w in admin.writes)
        assert any(w[0] == 'wire' and w[-1] is False for w in admin.writes)
        assert admin.write_gap == 1.25
        after = await inspect_input_push(admin, raw, ENTRY, PATH, BASE, chosen)
        assert all(row['action'] == 'vorhanden' for row in after['sources'])
        written = len(admin.writes)
        await apply_input_push(admin, raw, ENTRY, PATH, BASE, chosen, after['fingerprint'], True)
        assert len(admin.writes) == written
        # An existing analog command must not silently be accepted with Max=100.
        for command in admin.config['FubModules']['10']['77'].values():
            if command['Name'] == 'CL Eingang EnOcean/EI3_ILL':
                command['Max'] = 100
        with pytest.raises(AdminError, match='Max'):
            await inspect_input_push(admin, raw, ENTRY, PATH, BASE, chosen)

    asyncio.run(check())


def _runtime_for_enocean(monkeypatch):
    """Load the real runtime with only HA dispatcher/registry mechanics mocked."""
    import importlib
    import sys
    import types

    fired = []
    sent = []
    dispatcher = types.ModuleType('homeassistant.helpers.dispatcher')
    dispatcher.async_dispatcher_send = lambda _hass, signal: sent.append(signal)
    registry = types.ModuleType('homeassistant.helpers.entity_registry')
    class Registry:
        def async_get_entity_id(self, domain, platform, unique_id):
            return f'{domain}.test_enocean'
    registry.async_get = lambda _hass: Registry()
    monkeypatch.setitem(sys.modules, 'homeassistant', types.ModuleType('homeassistant'))
    monkeypatch.setitem(sys.modules, 'homeassistant.helpers', types.ModuleType('homeassistant.helpers'))
    monkeypatch.setitem(sys.modules, 'homeassistant.helpers.dispatcher', dispatcher)
    monkeypatch.setitem(sys.modules, 'homeassistant.helpers.entity_registry', registry)
    module = importlib.import_module('comexio_local.runtime')
    hass = SimpleNamespace(bus=SimpleNamespace(async_fire=lambda typ, data: fired.append((typ, data))))
    entry = SimpleNamespace(entry_id='entry-1', unique_id=None)
    runtime = module.Runtime(hass, entry, None, None)
    runtime.channels = apply_classifications(discover(enocean_config()), {})
    return runtime, fired, sent


def test_runtime_accepts_10bit_and_fractional_analog_enocean_and_validates_inputs(monkeypatch):
    import sys
    runtime, fired, _ = _runtime_for_enocean(monkeypatch)
    payload = lambda value: {'type': 'io', 'ext': 'EnOcean', 'io': 'EI3_ILL', 'value': value}
    assert runtime.apply_event(payload('562.75'))
    assert runtime.value('io:EnOcean/EI3_ILL') == 562.75
    assert fired[-1][1]['entity_id'] == 'sensor.test_enocean'
    assert runtime.apply_event(payload('1023'))
    assert runtime.value('io:EnOcean/EI3_ILL') == 1023.0
    for value in (1024, -1, 'nan', 'inf', '-inf', None, True):
        assert not runtime.apply_event(payload(value))
    assert runtime.value('io:EnOcean/EI3_ILL') == 1023.0
    assert runtime.rejected_events == 7
    # Existing roller position range remains exactly 0..100.
    cover = Channel(kind='cover', name='Cover', key='cover:M70', marker_id=70, analog=True)
    runtime.channels[cover.key] = cover
    assert not runtime.apply_event({'type': 'marker', 'id': 70, 'value': 101})
    sys.modules.pop('comexio_local.runtime', None)


def test_analog_presence_is_semantically_binary_but_command_transport_is_analog(monkeypatch):
    import sys
    runtime, fired, _ = _runtime_for_enocean(monkeypatch)
    p = lambda value: {'type': 'io', 'ext': 'EnOcean', 'io': 'EI2_PIRS', 'value': value}
    assert runtime.apply_event(p(0))
    assert runtime.value('io:EnOcean/EI2_PIRS') is False
    assert runtime.apply_event(p(0.5))
    assert runtime.value('io:EnOcean/EI2_PIRS') is True
    assert runtime.apply_event(p(0))
    assert runtime.value('io:EnOcean/EI2_PIRS') is False
    assert [row[1]['action'] for row in fired if row[0] == 'comexio_local_input'] == ['ein','aus']
    sys.modules.pop('comexio_local.runtime', None)


def test_repeated_enocean_rocker_presses_are_not_suppressed_by_state_cache(monkeypatch):
    import sys
    runtime, fired, _ = _runtime_for_enocean(monkeypatch)
    p = lambda value: {'type': 'io', 'ext': 'EnOcean', 'io': 'EI7_A0', 'value': value}
    assert runtime.apply_event(p(1))
    assert runtime.apply_event(p(1))
    assert runtime.apply_event(p(0))
    events = [data for typ, data in fired if typ == 'comexio_local_input']
    assert [e['action'] for e in events] == ['gedrueckt','gedrueckt','losgelassen']
    assert events[0]['entity_id'] == 'binary_sensor.test_enocean'
    assert runtime.push_journal.same_as_cached == 1
    assert runtime.events == 3
    sys.modules.pop('comexio_local.runtime', None)


def test_initial_enocean_tcp_error_does_not_mask_light_states(monkeypatch):
    import sys
    from comexio_local.tcp_client import ComexioError
    runtime, _, _ = _runtime_for_enocean(monkeypatch)
    light = discover(_config())['io:IO-Ext-2/Q1']
    runtime.channels[light.key] = light
    calls = []
    class TCP:
        async def read_sources(self, channels):
            calls.append([c.identifier for c in channels])
            if any(c.is_enocean for c in channels):
                raise ComexioError('EI GET not supported on this fake firmware')
            return {c.key: True for c in channels}
    runtime.tcp = TCP()
    asyncio.run(runtime.snapshot())
    assert runtime.value(light.key) is True
    assert runtime.value('io:EnOcean/EI3_ILL') is None
    assert runtime.errors == 1
    assert len(calls) == 2 and 'Q1' in calls[0] and not any(x.startswith('EI') for x in calls[0])
    sys.modules.pop('comexio_local.runtime', None)


def test_tcp_preserves_enoc_numeric_values_and_rejects_nan():
    from comexio_local.tcp_client import ComexioTCPClient
    client = ComexioTCPClient('invalid', 1234)
    channels = discover(enocean_config())
    keys = ['io:EnOcean/EI3_ILL', 'io:EnOcean/EI3_SVC', 'io:EnOcean/EI2_PIRS']
    selected = [channels[key] for key in keys]
    async def request(_request):
        return {'s0': '1000', 's1': '2.945', 's2': 'nan'}
    client._request = request
    results = asyncio.run(client.read_sources(selected))
    assert results == {keys[0]: 1000.0, keys[1]: 2.945, keys[2]: None}


def test_enocean_input_job_is_nonblocking_and_prevents_duplicate_writers(monkeypatch):
    import sys
    runtime, _, _ = _runtime_for_enocean(monkeypatch)
    gate = asyncio.Event()
    calls = []
    async def configure(selected, fingerprint):
        calls.append((selected, fingerprint))
        await gate.wait()
        return {'verified': 2, 'created_commands': 2}
    runtime.configure_input_push = configure
    runtime.hass.async_create_task = asyncio.create_task
    selected = {'io:EnOcean/EI3_ILL': 'auto', 'io:EnOcean/EI3_PIRS': 'auto'}

    async def execute():
        started = await runtime.start_input_push(selected, 'f' * 64)
        assert started['status'] == 'running'
        with pytest.raises(AdminError, match='läuft bereits'):
            await runtime.start_input_push(selected, 'f' * 64)
        assert len(calls) == 0  # returns immediately, not tied to flow request
        await asyncio.sleep(0)
        assert calls == [(selected, 'f' * 64)]
        assert runtime.input_push_status()['status'] == 'running'
        gate.set()
        await runtime._input_push_task
        assert runtime.input_push_status()['status'] == 'completed'
        assert runtime.input_push_status()['stats']['verified'] == 2
    asyncio.run(execute())
    sys.modules.pop('comexio_local.runtime', None)


def test_enocean_job_reports_partial_failure_without_unsafe_automatic_retry(monkeypatch):
    import sys
    runtime, _, _ = _runtime_for_enocean(monkeypatch)
    runtime.hass.async_create_task = asyncio.create_task
    calls = []
    async def configure(selected, fingerprint):
        calls.append(fingerprint)
        raise AdminError('COMEXIO HTTP 500 nach einem nur teilweise geschriebenen Plan')
    runtime.configure_input_push = configure

    async def execute():
        await runtime.start_input_push({'io:EnOcean/EI3_ILL': 'auto'}, 'a' * 64)
        await runtime._input_push_task
        status = runtime.input_push_status()
        assert status['status'] == 'failed'
        assert '500' in status['message']
        assert calls == ['a' * 64]
    asyncio.run(execute())
    sys.modules.pop('comexio_local.runtime', None)
