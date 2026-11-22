"""v0.4.12 regression: real COMEXIO 2G TypeId=24 inverted binary EI and HA menu refresh.

All results here are offline mocks, not an IO-Server/HA hardware test.
"""
from __future__ import annotations

import asyncio
from copy import deepcopy
from types import SimpleNamespace

import pytest

from comexio_local.admin_api import AdminError
from comexio_local.discovery import discover
from comexio_local.discovery_sync import compare_catalog
from comexio_local.input_push import _groups, input_catalog, inspect_input_push, apply_input_push
from comexio_local.preferences import INPUT_INVERT_OVERRIDES, ha_binary_input_state, binary_input_is_inverted
from comexio_local.webio_command import WebIOCommand
from test_enocean_type_plans_0410 import CoordinateInputAdmin
from test_input_flow_03633 import _load_options_flow
from test_push_audit import ENTRY, PATH, BASE, _installed

CONTACTS = {
    193: 'EI2_CO', 201: 'EI5_CO', 194: 'EI8_CO',
    210: 'EI9_CO', 211: 'EI10_CO', 212: 'EI11_CO',
}


def observed_contacts_config():
    config, plans, _ = _installed()
    records = {}
    for ident, name in CONTACTS.items():
        records[str(ident)] = {
            'Id': ident, 'Identifier': name, 'Description': name,
            'Active': 1, 'IntIsOutput': 0, 'ConnectionType': 1,
            'InOutputTypeId': 23 if ident == 212 else 24,
        }
    # Preserve the existing lighting/cover configuration as a regression guard.
    config['FubModules']['1']['9'] = {
        'extension': {'Name': 'EnOcean'}, 'inoutput': records,
    }
    return config, plans


def test_six_observed_co_inputs_include_five_inverted_and_new_normal_contact():
    config, _ = observed_contacts_config()
    raw = discover(config)
    co = {c.identifier: c for c in raw.values() if c.is_enocean}
    assert set(co) == set(CONTACTS.values())
    for ident, channel in co.items():
        assert channel.kind == 'binary_input'
        assert channel.input_mode == 'schalter'
        assert channel.analog is False
        assert channel.push_maximum == 1
        assert channel.comexio_binary_inverted is (ident != 'EI11_CO')
        assert input_catalog(raw)[channel.key] == channel
        assert _groups(raw, ENTRY)[channel.key][0] == 'CL Eingänge EnOcean Kontakte'
        command = WebIOCommand.for_signal(channel, PATH, 'CL Eingang EnOcean/' + ident)
        assert (command.type_id, command.minimum, command.maximum) == (1, 0, 1)
        assert (command.input_index, command.changed, command.send_on_one) == (1, 1, 0)
    assert len({c.key for c in co.values()}) == 6


def test_comexio_inversion_toggle_retains_identity_and_only_changes_metadata():
    config, _ = observed_contacts_config()
    key = 'io:EnOcean/EI5_CO'
    inverted = discover(config)
    contact = inverted[key]
    assert contact.comexio_binary_inverted
    # Firmware is responsible for inversion; HA receives the interpreted value.
    assert ha_binary_input_state(1, False) is True
    assert ha_binary_input_state(0, False) is False
    options = {INPUT_INVERT_OVERRIDES: {key: True}}
    assert binary_input_is_inverted(options, key)
    assert ha_binary_input_state(1, binary_input_is_inverted(options, key)) is False
    config['FubModules']['1']['9']['inoutput']['201']['InOutputTypeId'] = 23
    normal = discover(config)
    assert normal[key].key == contact.key
    assert normal[key].io_id == contact.io_id
    assert normal[key].kind == contact.kind == 'binary_input'
    assert not normal[key].comexio_binary_inverted
    assert binary_input_is_inverted(options, key)  # HA opt-in persists independently
    comparison = compare_catalog(inverted, normal, options)
    assert any(row['key'] == key and row['action'] == 'updated' for row in comparison['changes'])
    assert comparison['counts']['removed'] == 0
    assert comparison['counts']['added'] == 0
    assert comparison['requires_manual_classification'] is False


def test_wrong_type_connection_pair_or_output_is_still_rejected():
    config, _ = observed_contacts_config()
    key = 'io:EnOcean/EI5_CO'
    row = config['FubModules']['1']['9']['inoutput']['201']
    row['ConnectionType'] = 2  # type 24 cannot be analog
    assert key not in discover(config)
    row['ConnectionType'] = 1
    row['IntIsOutput'] = 1
    assert key not in discover(config)
    row['IntIsOutput'] = 0
    row['InOutputTypeId'] = 25
    assert key not in discover(config)


def test_existing_five_webio_commands_survive_type_23_to_24_and_new_ei11_can_append(monkeypatch):
    from comexio_local import input_push
    config, protected_plans = observed_contacts_config()
    for row in config['FubModules']['1']['9']['inoutput'].values():
        row['InOutputTypeId'] = 23
    admin = CoordinateInputAdmin(config, protected_plans)
    original_protected_plans = deepcopy(protected_plans)
    original_light_cmd = deepcopy(config['FubModules']['10']['19'])
    raw = discover(admin.config)
    old = {key: 'auto' for key in raw if key.startswith('io:EnOcean/')
           and not key.endswith('EI11_CO')}

    async def append(fake, device_id, base_id, command):
        fake.writes.append(('append', command['Name'], fake.write_gap))
        fake.next_cmd += 1
        fake.config['FubModules']['10'][str(device_id)][str(fake.next_cmd)] = deepcopy(command)

    monkeypatch.setattr(input_push, '_append_command', append)

    async def go():
        before = await inspect_input_push(admin, raw, ENTRY, PATH, BASE, old)
        assert before['needs_write']
        result = await apply_input_push(admin, raw, ENTRY, PATH, BASE,
                                        old, before['fingerprint'], True)
        assert result['verified'] == 5
        writes_after_setup = len(admin.writes)
        # Change the COMEXIO setting on all five *without rebuilding anything*.
        for row in admin.config['FubModules']['1']['9']['inoutput'].values():
            if row['Identifier'] != 'EI11_CO':
                row['InOutputTypeId'] = 24
        changed = discover(admin.config)
        assert all(changed[key].comexio_binary_inverted for key in old)
        already = await inspect_input_push(admin, changed, ENTRY, PATH, BASE, old)
        assert all(row['action'] == 'vorhanden' for row in already['sources'])
        assert len(admin.writes) == writes_after_setup
        all_channels = {**old, 'io:EnOcean/EI11_CO': 'auto'}
        expansion = await inspect_input_push(admin, changed, ENTRY, PATH, BASE, all_channels)
        assert expansion['plan_count'] == 1
        assert sum(row['action'] == 'vorhanden' for row in expansion['sources']) == 5
        assert sum(row['action'] == 'anlegen' for row in expansion['sources']) == 1
        assert admin.plans | original_protected_plans == admin.plans
        assert {pid: admin.plans[pid] for pid in protected_plans} == original_protected_plans
        assert admin.config['FubModules']['10']['19'] == original_light_cmd
        # No unexpected foreign/renamed input command blocks this preview.
    asyncio.run(go())


def test_manual_menu_discovery_calls_existing_read_once_and_displays_summary(monkeypatch):
    mod = _load_options_flow(monkeypatch)
    flow = mod.ComexioLocalOptionsFlow()
    key = 'io:EnOcean/EI5_CO'
    cfg, _ = observed_contacts_config()
    after = discover(cfg)
    before_cfg = deepcopy(cfg)
    before_cfg['FubModules']['1']['9']['inoutput']['201']['InOutputTypeId'] = 23
    before_cfg['FubModules']['1']['9']['inoutput'].pop('212')
    before = discover(before_cfg)

    class Runtime:
        def __init__(self):
            self.channels = before
            self.calls = 0
        async def refresh_discovery(self):
            self.calls += 1
            self.channels = after
            return len(after.keys() - before.keys()), len(before.keys() - after.keys())

    runtime = Runtime()
    flow._runtime = lambda: runtime
    menu = asyncio.run(flow.async_step_devices_menu())
    assert menu['menu_options'][0] == 'discovery_refresh'
    shown = asyncio.run(flow.async_step_discovery_refresh())
    assert shown['type'] == 'form' and shown['step_id'] == 'discovery_refresh'
    summary = shown['description_placeholders']['summary']
    assert '**1 EnOcean**' not in summary  # all six are counted
    assert '**6 EnOcean**' in summary
    assert '**Neu:** 1' in summary
    assert '**Geänderte Metadaten:** 1' in summary
    assert runtime.calls == 1
    result = asyncio.run(flow.async_step_discovery_refresh({}))
    assert result['type'] == 'abort' and result['reason'] == 'diagnostic_closed'
    assert runtime.calls == 1


def test_manual_menu_discovery_handles_admin_failure_without_mutation(monkeypatch):
    mod = _load_options_flow(monkeypatch)
    flow = mod.ComexioLocalOptionsFlow()
    class FailingRuntime:
        channels = {}
        calls = 0
        async def refresh_discovery(self):
            self.calls += 1
            raise AdminError('Verbindung fehlgeschlagen')
    runtime = FailingRuntime()
    flow._runtime = lambda: runtime
    form = asyncio.run(flow.async_step_discovery_refresh())
    assert form['type'] == 'form'
    assert form['errors']['base'] == 'cannot_connect'
    assert runtime.calls == 1
    assert flow._runtime().channels == {}


def test_live_runtime_refresh_reuses_contact_key_after_comexio_polarity_change(monkeypatch):
    import importlib
    import sys
    import types
    from comexio_local.device_metadata import ControllerSystemInfo
    from comexio_local import hardware_devices
    signals = []
    dispatcher = types.ModuleType('homeassistant.helpers.dispatcher')
    dispatcher.async_dispatcher_send = lambda _hass, signal: signals.append(signal)
    for key, mod in (('homeassistant', types.ModuleType('homeassistant')),
                     ('homeassistant.helpers', types.ModuleType('homeassistant.helpers')),
                     ('homeassistant.helpers.dispatcher', dispatcher)):
        monkeypatch.setitem(sys.modules, key, mod)
    runtime_module = importlib.import_module('comexio_local.runtime')
    monkeypatch.setattr(runtime_module, 'async_dispatcher_send', dispatcher.async_dispatcher_send)
    monkeypatch.setattr(hardware_devices, 'discover_hardware', lambda config: ({}, {}))
    monkeypatch.setattr(hardware_devices, 'sync_hardware_registry', lambda *args, **kwargs: None)
    config, _ = observed_contacts_config()
    row = config['FubModules']['1']['9']['inoutput']['201']
    row['InOutputTypeId'] = 23
    counts = {'read': 0, 'writes': 0}

    class Admin:
        async def read_config(self):
            counts['read'] += 1
            return config
        async def read_system_info(self):
            return ControllerSystemInfo()
        async def read_plans(self, *_args):
            return {}

    class TCP:
        async def read_sources(self, sources):
            return {c.key: (False if c.identifier == 'EI5_CO' and row['InOutputTypeId'] == 24 else True)
                    for c in sources}

    fired = []
    hass = SimpleNamespace(bus=SimpleNamespace(async_fire=lambda *args: fired.append(args)),
                           config_entries=SimpleNamespace(async_update_entry=lambda *args, **kwargs: None))
    entry = SimpleNamespace(entry_id='test', unique_id='id', options={})
    runtime = runtime_module.Runtime(hass, entry, Admin(), TCP())
    monkeypatch.setattr(runtime, '_entity_id_for', lambda c: 'binary_sensor.ei5_co')
    key = 'io:EnOcean/EI5_CO'

    async def run():
        a, r = await runtime.refresh_discovery()
        assert (a, r) == (len(discover(config)), 0)
        first = runtime.channels[key]
        assert first.comexio_binary_inverted is False
        assert runtime.value(key) is True
        row['InOutputTypeId'] = 24
        a, r = await runtime.refresh_discovery()
        assert (a, r) == (0, 0)
        assert runtime.channels[key].key == first.key
        assert runtime.channels[key].kind == first.kind == 'binary_input'
        assert runtime.channels[key].comexio_binary_inverted is True
        assert runtime.value(key) is False  # controller-provided inverted state, not re-inverted
        assert runtime.apply_event({'type': 'io', 'ext': 'EnOcean', 'io': 'EI5_CO', 'value': 1})
        assert runtime.value(key) is True
        assert runtime.rejected_events == 0
        row['InOutputTypeId'] = 23
        a, r = await runtime.refresh_discovery()
        assert (a, r) == (0, 0)
        assert runtime.channels[key].comexio_binary_inverted is False
        assert counts == {'read': 3, 'writes': 0}
        assert len([x for x in signals if x == runtime.discovery_signal]) == 3

    asyncio.run(run())
