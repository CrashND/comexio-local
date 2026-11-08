"""Regression checks for v0.3.6.3.5 ownership, safe lookups, labels and input isolation."""
from __future__ import annotations

import asyncio
import sys
import types
from copy import deepcopy

import pytest

from comexio_local.admin_api import AdminError, make_push_command
from comexio_local.discovery import discover
from comexio_local.input_push import (
    _command_for, _groups, _validate_existing_plan,
    input_command_name, inspect_input_push,
)
from comexio_local.managed_resources import is_owned_plan, plan_comment, plan_family
from comexio_local.name_inspection import inspect_names
from comexio_local.push_labels import friendly_command_name, friendly_plan_name
from comexio_local.push_rebuild import PushRebuild
from comexio_local.push_setup import _existing_commands, _find_plan, _stable_groups, push_sources
from test_discovery import _config
from test_input_push_0363 import InputAdminFake, with_inputs
from test_push_audit import BASE, ENTRY, PATH, _installed
from test_push_rebuild import AdminFake, FakeRuntime, MemoryStore


def test_owner_marker_is_exact_and_shared_between_push_and_input():
    for family in ('input', 'push'):
        meta = {'Comment': plan_comment(ENTRY, family)}
        assert is_owned_plan(meta, ENTRY, family)
        assert plan_family(meta, ENTRY) == family
        assert plan_family(meta, ENTRY + '-second') is None
        assert not is_owned_plan(meta, ENTRY, 'push' if family == 'input' else 'input')
    # A substring of a different entry ID is never proof of plan ownership.
    assert plan_family({'Comment': plan_comment('some-' + ENTRY, 'push')}, ENTRY) is None
    assert plan_family({'Comment': f'free text mentioning {ENTRY}'}, ENTRY) is None
    assert plan_family({'Comment': f'Managed exclusively by COMEXIO Local UNKNOWN ({ENTRY})'}, ENTRY) is None


def test_duplicate_named_webio_commands_fail_closed():
    config, _, _ = _installed()
    source = config['FubModules']['10']['19']['201']
    config['FubModules']['10']['19']['999'] = deepcopy(source)
    with pytest.raises(AdminError, match='Doppelter COMEXIO-Web-IO-Befehlsname'):
        _existing_commands(config, '19')
    del config['FubModules']['10']['19']['999']
    config['FubModules']['10']['19']['xyz'] = config['FubModules']['10']['19'].pop('201')
    with pytest.raises(AdminError, match='ungültige|Ungültige'):
        _existing_commands(config, '19')


def test_duplicate_named_plans_fail_closed_and_malformed_ids_refused():
    config, _, _ = _installed()
    name = next(meta['Name'] for meta in config['Fubs'].values() if meta['Name'].startswith('CL'))
    config['Fubs']['4242'] = {'Name': name}
    with pytest.raises(AdminError, match='Mehrere COMEXIO-Logikpläne'):
        _find_plan(config, name)
    del config['Fubs']['4242']
    fid = next(fid for fid, meta in config['Fubs'].items() if meta['Name'] == name)
    config['Fubs']['bad'] = config['Fubs'].pop(fid)
    with pytest.raises(AdminError, match='Ungültige COMEXIO-Logikplan-ID'):
        _find_plan(config, name)


def test_new_labels_are_readable_and_single_schema_only():
    config, _, channels = _installed()
    for c in push_sources(channels):
        assert ENTRY[:8].upper() not in friendly_command_name(c)
        if c.kind != 'cover':
            assert c.extension in friendly_command_name(c)
    for bucket, group in _stable_groups(push_sources(channels)):
        label = friendly_plan_name(group, bucket)
        assert label.startswith('CL Push ')
        assert ENTRY[:8].upper() not in label
        assert 'Rollläden' in label if group[0].kind == 'cover' else group[0].extension in label


def test_only_canonical_input_command_is_recognized():
    config = with_inputs(_config())
    raw = discover(config)
    c = raw['io:IO-Ext-2/I1']
    name = input_command_name(c)
    assert name == 'CL Eingang IO-Ext-2/I1'
    command = make_push_command(c, PATH, name=name)
    assert _command_for({name: (123, command)}, c)[0] == 123
    assert _command_for({'Anderer Eingangsbefehl': (123, command)}, c) is None


def test_input_preview_reuses_exact_canonical_name_without_duplicates():
    config = with_inputs(_config())
    raw = discover(config)
    c = raw['io:IO-Ext-2/I1']
    admin = InputAdminFake(config)
    admin.config['WebDevices'] = {
        '77': {'Name': 'CL Eingänge Home Assistant', 'Ip': '192.168.10.6:8123', 'BaseId': 9}}
    admin.config['FubModules']['10'] = {
        '77': {'301': make_push_command(c, PATH, name=input_command_name(c))}}

    async def check():
        preview = await inspect_input_push(admin, raw, ENTRY, PATH, BASE,
                                           {c.key: 'taster'})
        assert preview['sources'][0]['action'] == 'verknuepfen'
        assert admin.writes == []
    asyncio.run(check())


def test_input_plan_rejects_command_from_another_input_group():
    config = with_inputs(_config())
    raw = discover(config)
    channels = _groups(raw, ENTRY)
    c = raw['io:IO-Ext-2/I1']
    foreign = raw['io:IO-Ext-2/AI2']
    name, group, _ = channels[c.key]
    known = {
        input_command_name(c): (101, {}),
        input_command_name(foreign): (102, {}),
    }
    plan = {'elements': {
        '1': {'reference': {'type': 1, 'ref_id': c.io_id}},
        '2': {'reference': {'type': 10, 'ref_id': 102}},
    }, 'connections': {'1': {'input': {'element': '1'},
                             'output': {'0': {'element': '2'}}}}}
    with pytest.raises(AdminError, match='Fremder Baustein'):
        _validate_existing_plan(plan, name, group, known)


def test_name_inspection_ignores_other_namespace_collisions():
    config, _, channels = _installed()
    groups = _stable_groups(push_sources(channels))
    planned_label = friendly_plan_name(groups[0][1], groups[0][0])
    config['FubModules']['10']['19']['985'] = {'Name': planned_label}
    report = inspect_names(config, channels, ENTRY)
    assert any('Unbekannter Befehl' in issue for issue in report['blockers'])


def test_checkpoint_resume_ignores_owned_input_plans_without_touching_them(monkeypatch):
    """Regression: _snapshot excluded INPUT but _validate_checkpoint once rejected it."""
    import comexio_local.push_rebuild as rebuild_mod
    config = _config()
    admin = AdminFake(config)
    runtime = FakeRuntime(admin, discover(config))
    store = MemoryStore()
    manager = PushRebuild(runtime, store)

    async def append(adm, did, base_id, command):
        adm.next_cmd += 1
        adm.config['FubModules']['10']['19'][str(adm.next_cmd)] = deepcopy(command)

    monkeypatch.setattr(rebuild_mod, '_append_command', append)
    dispatcher = types.ModuleType('homeassistant.helpers.dispatcher')
    dispatcher.async_dispatcher_send = lambda *_args: None
    monkeypatch.setitem(sys.modules, 'homeassistant', types.ModuleType('homeassistant'))
    monkeypatch.setitem(sys.modules, 'homeassistant.helpers', types.ModuleType('homeassistant.helpers'))
    monkeypatch.setitem(sys.modules, 'homeassistant.helpers.dispatcher', dispatcher)

    async def run():
        before = await manager.preview()
        await manager.start(before['fingerprint'], True)
        await manager._task
        assert manager.status()['status'] == 'completed', manager.status()

        # Pretend the final verification was interrupted; everything previously
        # completed must still be present and eligible for a safe resume.
        manager._state['status'] = 'failed'
        manager._state['cursor'] = len(manager._state['steps']) - 1
        await manager._save()

        input_fid = '9876'
        input_meta = {'Name': 'CL Eingänge IO-Ext-3 I1-I18',
                      'Comment': plan_comment(ENTRY, 'input'), 'Active': True}
        admin.config['Fubs'][input_fid] = deepcopy(input_meta)
        admin.plans[input_fid] = {'elements': {}, 'connections': {}}
        input_before = deepcopy(admin.config['Fubs'][input_fid])

        await manager.resume()
        await manager._task
        assert manager.status()['status'] == 'completed', manager.status()
        assert admin.config['Fubs'][input_fid] == input_before
        assert admin.plans[input_fid] == {'elements': {}, 'connections': {}}

    asyncio.run(run())


def test_admin_plan_creation_refuses_duplicate_or_foreign_readback():
    from comexio_local.admin_api import ComexioAdmin

    class PlanAdmin(ComexioAdmin):
        def __init__(self, entries):
            super().__init__(None, 'comexio.test', 'tester', 'unused')
            self.entries = entries
            self.calls = 0

        async def request_json(self, method, route, **kwargs):
            self.calls += 1
            assert method == 'POST' and route.endswith('/save_fub')
            return {'redirect': '/admin/function_function_module/home?added=1'}

        async def read_config(self):
            return {'Fubs': self.entries}

    owner = plan_comment(ENTRY, 'input')
    good = {'101': {'Name': 'CL Eingänge IO-Ext-3 I1-I18', 'Comment': owner}}
    admin = PlanAdmin(good)
    assert asyncio.run(admin.create_plan('CL Eingänge IO-Ext-3 I1-I18', owner)) == 101
    ambiguous = {**good, '102': deepcopy(good['101'])}
    with pytest.raises(AdminError, match='nicht eindeutig'):
        asyncio.run(PlanAdmin(ambiguous).create_plan('CL Eingänge IO-Ext-3 I1-I18', owner))
    wrong = {'101': {**good['101'], 'Comment': plan_comment('other-entry', 'input')}}
    with pytest.raises(AdminError, match='fremde Eigentumskennung'):
        asyncio.run(PlanAdmin(wrong).create_plan('CL Eingänge IO-Ext-3 I1-I18', owner))


def test_admin_plan_reader_never_discards_nonempty_element_or_connection_lists():
    from comexio_local.admin_api import ComexioAdmin

    class PlanAdmin(ComexioAdmin):
        def __init__(self, data):
            super().__init__(None, 'comexio.test', 'tester', 'unused')
            self.data = data

        async def request_json(self, method, route, **kwargs):
            assert method == 'GET'
            return deepcopy(self.data)

    empty = asyncio.run(PlanAdmin({'elements': [], 'connections': []}).read_plan(101))
    assert empty == {'elements': {}, 'connections': {}}
    for data in (
        {'elements': [{'id': 9, 'reference': {'type': 1, 'ref_id': 77}}], 'connections': []},
        {'elements': {}, 'connections': [{'input': 1, 'output': 2}]},
    ):
        with pytest.raises(AdminError, match='Listenformat'):
            asyncio.run(PlanAdmin(data).read_plan(101))


def test_shared_command_index_rejects_malformed_or_duplicate_ids():
    from comexio_local.managed_resources import unique_webio_commands
    good = {'FubModules': {'10': {'55': {'101': {'Name': 'CL Eingang IO-Ext-3/I1'}}}}}
    assert unique_webio_commands(good, '55')['CL Eingang IO-Ext-3/I1'][0] == 101
    both = deepcopy(good)
    both['FubModules']['10']['55']['102'] = {'Name': 'CL Eingang IO-Ext-3/I1'}
    with pytest.raises(AdminError, match='Doppelter COMEXIO-Web-IO'):
        unique_webio_commands(both, '55')
    invalid = deepcopy(good)
    invalid['FubModules']['10']['55'] = {'-101': {'Name': 'CL Eingang IO-Ext-3/I1'}}
    with pytest.raises(AdminError, match='Ungültige COMEXIO-Web-IO'):
        unique_webio_commands(invalid, '55')
    # A negative in-memory command ID is acceptable *only* with our explicit
    # staging sentinel. It must never be accepted as a real COMEXIO command.
    with pytest.raises(AdminError, match='Ungültige COMEXIO-Web-IO'):
        unique_webio_commands(invalid, '55', allow_staged=True)
    invalid['FubModules']['10']['55']['-101']['_local_staged'] = True
    assert unique_webio_commands(invalid, '55', allow_staged=True)['CL Eingang IO-Ext-3/I1'][0] == -101
    with pytest.raises(AdminError, match='Ungültige COMEXIO-Web-IO'):
        unique_webio_commands(invalid, '55')


@pytest.mark.parametrize('url', [
    'http://192.168.10.6:8123',
    'http://10.0.0.3:80',
    'http://172.16.0.1:8123/',
])
def test_local_push_destination_is_private_lan_http(url):
    from comexio_local.push_target import private_lan_host_port
    assert private_lan_host_port(url)


@pytest.mark.parametrize('url', [
    '', 'http://127.0.0.1:8123', 'http://0.0.0.0:8123',
    'http://169.254.10.2:8123', 'https://192.168.10.6:8123',
    'http://192.168.10.6', 'http://192.168.10.6:8123/api/webhook/private',
    'http://name:secret@192.168.10.6:8123', 'http://192.168.10.6:8123/?token=secret',
    'http://8.8.8.8:8123', 'http://[::1]:8123',
    'http://homeassistant.local:8123',
])
def test_push_destination_refuses_nonavailable_or_unsafe_address(url):
    from comexio_local.push_target import private_lan_host_port
    assert private_lan_host_port(url) is None


def test_push_rebuild_snapshot_handles_invalid_config_command_without_exception():
    config = _config()
    prefix = 'CL' + ENTRY[:8].upper()
    config.setdefault('WebDevices', {})['19'] = {'Name': 'CL Push Home Assistant'}
    config.setdefault('FubModules', {}).setdefault('10', {})['19'] = {'999': 'invalid'}
    admin = AdminFake(config)
    manager = PushRebuild(FakeRuntime(admin, discover(config)), MemoryStore())
    with pytest.raises(Exception, match='Fremde/unbekannte Befehle'):
        asyncio.run(manager.preview())


def test_config_not_replaced_by_undocumented_read_plan_connection_shape():
    from comexio_local.admin_api import ComexioAdmin

    class PlanAdmin(ComexioAdmin):
        def __init__(self, data):
            super().__init__(None, 'comexio.invalid', 'tester', 'unused')
            self.data = data

        async def request_json(self, method, route, **kwargs):
            return deepcopy(self.data)

    for data in ({'elements': {}}, {'elements': {}, 'connections': None},
                 {'elements': {}, 'connections': 'unexpected'}):
        with pytest.raises(AdminError, match='Verbindungen'):
            asyncio.run(PlanAdmin(data).read_plan(1))


def test_input_plan_name_for_unknown_extension_does_not_generate_hash_fragment():
    from comexio_local.discovery import Channel
    extension = 'IO Erweiterung Zentral'
    c = Channel(kind='input', key=f'io:{extension}/I1', name='Taster',
                extension=extension, identifier='I1', io_id=8)
    name = _groups({c.key: c}, ENTRY)[c.key][0]
    assert name == 'CL Eingänge IO Erweiterung Zentral I1-I18'


def test_callback_url_requires_positive_port():
    from comexio_local.push_target import private_lan_host_port
    assert private_lan_host_port('http://192.168.10.6:0') is None


@pytest.mark.parametrize('malformed', [
    {'elements': {'1': {'unexpected': True}}, 'connections': {}},
    {'elements': {}, 'connections': {'1': {'input': {'element': '987'}}}},
    {'elements': [], 'connections': {}},
    {'elements': {}, 'connections': None},
])
def test_shared_graph_never_writes_to_unreadable_plan(malformed):
    from comexio_local.managed_graph import ensure_webio_link
    from comexio_local.discovery import Channel
    signal = Channel(kind='light', key='io:IO-Ext-2/Q3', name='Licht',
                     extension='IO-Ext-2', identifier='Q3', io_id=99)

    class NoWrites:
        async def add_element(self, *_args, **_kwargs):
            raise AssertionError('must never write')

        async def wire(self, *_args, **_kwargs):
            raise AssertionError('must never write')

    with pytest.raises(AdminError, match='Logikplan'):
        asyncio.run(ensure_webio_link(NoWrites(), 123, signal, 333, 0,
                                      deepcopy(malformed), update_cache=True, command_name="CL Test"))
