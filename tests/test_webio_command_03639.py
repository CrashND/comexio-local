"""Regression: JSON import and later form POST share one push-command profile.

Offline tests verify payload equality and safe refusal of inconsistent data.
They cannot prove the visual result in COMEXIO Studio 11.1.5.
"""
from __future__ import annotations

import asyncio
from copy import deepcopy
from types import SimpleNamespace

import pytest

from comexio_local.admin_api import AdminError, make_push_command
from comexio_local.discovery import Channel
from comexio_local.push_setup import _append_command
from comexio_local.push_rebuild import PushRebuild, RebuildError
from comexio_local.webio_command import WebIOCommand
from comexio_local.push_labels import friendly_command_name


@pytest.fixture
def output():
    return Channel(kind='light', name='Flur Licht', key='io:IO-Server-1/Q1',
                   extension='IO-Server-1', identifier='Q1', io_id=45, plan='Flur')


@pytest.fixture
def position():
    return Channel(kind='cover', name='Schlafzimmer', key='cover:M69',
                   marker_id=69, target_marker_id=68, analog=True)


@pytest.fixture
def button():
    return Channel(kind='binary_input', name='Flur Licht Rot',
                   key='io:IO-Ext-3/I1', extension='IO-Ext-3',
                   identifier='I1', io_id=27, input_mode='taster')


def test_unchanged_json_import_schema_for_existing_light(output):
    """The first import must remain byte-for-byte compatible with v0.3.6.3.8."""
    actual = make_push_command(output, '/api/webhook/abc', name='CL Licht Flur IO-Server-1/Q1')
    assert actual == {
        'Name': 'CL Licht Flur IO-Server-1/Q1', 'TypeId': 1,
        'Min': 0, 'Max': 1, 'Parameter': '/api/webhook/abc',
        'HeaderModifier': 'Content-Type: application/json',
        'Data': ('function data(a)\r\n  return json_stringify('
                 '{type="io",ext="IO-Server-1",io="Q1",value=a})\r\nend'),
        'Protocol': 0, 'PostGet': 1, 'WebDeviceId': 0,
        'Authentication': 0, 'Input': 1, 'ReqFreq': '',
        'ReplyInterpreter': '', 'Port': '', 'SendOnOne': 0,
        'Changed': 1, 'BaseId': 0, 'DefaultValue': '',
        'DefaultActive': 1, 'io': [],
    }


@pytest.mark.parametrize('fixture_name', ['output', 'position', 'button'])
def test_same_canonical_settings_in_json_and_form(request, fixture_name):
    channel = request.getfixturevalue(fixture_name)
    label = ('CL Eingang IO-Ext-3/I1' if fixture_name == 'button'
             else friendly_command_name(channel))
    command = make_push_command(channel, '/api/webhook/abc', name=label)
    spec = WebIOCommand.from_import(command)
    assert spec.as_import() == command
    form = spec.as_append_form('19', '9')
    mapped = {
        'Name': form['name_cmd_io_0'], 'TypeId': form['type_cmd_io_0'],
        'Min': form['min_cmd_io_0'], 'Max': form['max_cmd_io_0'],
        'Parameter': form['parameter'], 'Data': form['data'],
        'HeaderModifier': form['header_modifier'],
        'Protocol': form['protocol'], 'PostGet': form['post_get'],
        'Authentication': form['authentication'], 'Input': form['input_cmd_io_0'],
        'SendOnOne': form['send_on_one_cmd_io_0'],
        'DefaultValue': form['default_value_cmd_io_0'],
        'DefaultActive': form['DefaultActive'],
    }
    assert all(mapped[key] == command[key] for key in mapped)
    assert form['function_cmd_io_0'] == '1_1_0'
    assert form['deviceBaseId'] == '9'
    assert form['dlg_web_device_id'] == '19'
    assert form['id_cmd_io_0'] == 'eyJzcmMiOiJjb21tYW5kIiwiaWQiOm51bGx9'


def test_analog_and_digital_command_semantics(position, output):
    analog = WebIOCommand.from_import(make_push_command(
        position, '/api/webhook/a', name='CL Rollladen Schlafzimmer M69'))
    digital = WebIOCommand.from_import(make_push_command(
        output, '/api/webhook/a', name='CL Licht Flur IO-Server-1/Q1'))
    assert analog.type_id == 2 and analog.maximum == 100
    assert digital.type_id == 1 and digital.maximum == 1
    assert 'type="marker",id="69"' in analog.data
    assert 'type="io",ext=' in digital.data


@pytest.mark.parametrize('field,wrong', [
    ('TypeId', 2), ('Max', 100), ('Name', 'CL Wrong Name'),
    ('Protocol', 1), ('Input', 0),
])
def test_readback_catches_contradictions(output, field, wrong):
    spec = WebIOCommand.from_import(make_push_command(
        output, '/api/webhook/abc', name='CL Licht Flur IO-Server-1/Q1'))
    observed = {field: wrong}
    assert spec.readback_mismatch(observed) == [field]


def test_missing_readback_fields_are_unverified_not_false_mismatches(output):
    spec = WebIOCommand.from_import(make_push_command(
        output, '/api/webhook/abc', name='CL Licht Flur IO-Server-1/Q1'))
    assert spec.readback_mismatch({'Name': spec.name}) == []
    assert spec.readback_mismatch({'TypeId': '1', 'Max': 1.0}) == []


@pytest.mark.parametrize('bad', [
    {'TypeId': 99}, {'Min': -1}, {'Changed': 0},
    {'Parameter': 'http://outside.invalid'}, {'io': [123]},
    {'HeaderModifier': 'X-Wrong: 1'}, {'BaseId': 123},
])
def test_invalid_payload_is_rejected_before_form_POST(output, bad):
    good = make_push_command(output, '/api/webhook/abc', name='CL Licht Flur IO-Server-1/Q1')
    good.update(bad)

    class FakeAdmin:
        def __init__(self):
            self._lock = asyncio.Lock()
            self.calls = 0

        async def _wait_write_slot(self):
            self.calls += 1

    admin = FakeAdmin()
    with pytest.raises(AdminError, match='Befehlsdefinition'):
        asyncio.run(_append_command(admin, '19', '9', good))
    assert admin.calls == 0


def test_form_rejects_unknown_ids_before_write(output):
    spec = WebIOCommand.from_import(make_push_command(
        output, '/api/webhook/abc', name='CL Licht Flur IO-Server-1/Q1'))
    for device, base in [('not-an-id', '9'), ('19', ''), ('0', '9'), ('19', '-4')]:
        with pytest.raises(ValueError, match='ID'):
            spec.as_append_form(device, base)


def test_real_rebuild_id_read_blocks_mismatched_command_before_link(output):
    label = 'CL Licht Flur IO-Server-1/Q1'
    original = make_push_command(output, '/api/webhook/abc', name=label)
    class FakeAdmin:
        async def read_config(self):
            wrong = deepcopy(original)
            wrong['TypeId'] = 2
            return {'WebDevices': {'19': {'Name': 'CL Push Home Assistant', 'BaseId': 9}},
                    'FubModules': {'10': {'19': {'200': wrong}}}}
    runtime = SimpleNamespace(hass=object(), admin=FakeAdmin(), channels={output.key: output},
                              entry=SimpleNamespace(data={'webhook_id': 'abc'}))
    rebuild = PushRebuild(runtime, object())
    cached = {'old': True}
    with pytest.raises(RebuildError, match='TypeId'):
        asyncio.run(rebuild._refresh_command_ids(cached))
    assert cached == {'old': True} and not rebuild._command_ids_refreshed


def test_real_rebuild_id_read_accepts_matching_command(output):
    label = 'CL Licht Flur IO-Server-1/Q1'
    original = make_push_command(output, '/api/webhook/abc', name=label)
    class FakeAdmin:
        async def read_config(self):
            return {'WebDevices': {'19': {'Name': 'CL Push Home Assistant', 'BaseId': 9}},
                    'FubModules': {'10': {'19': {'200': original}}}}

        async def ensure_webio_commands_active(self, config, device_id, names, *, force=False, force_names=None):
            assert device_id == '19' and names == [label]
            config['FubModules']['10']['19']['200']['Active'] = '1'
            return config
    runtime = SimpleNamespace(hass=object(), admin=FakeAdmin(), channels={output.key: output},
                              entry=SimpleNamespace(data={'webhook_id': 'abc'}))
    rebuild = PushRebuild(runtime, object())
    cached = {}
    asyncio.run(rebuild._refresh_command_ids(cached))
    assert rebuild._command_ids_refreshed
    assert cached['FubModules']['10']['19']['200']['Name'] == label


def _comparison_fixture(*, first_mutations=None, second_mutations=None):
    """Two firmware records: one JSON-imported, one form-created."""
    first = Channel(kind='cover', name='Schlafzimmer', key='cover:M69',
                    marker_id=69, target_marker_id=68, analog=True)
    second = Channel(kind='cover', name='Kinderzimmer Seite', key='cover:M71',
                     marker_id=71, target_marker_id=70, analog=True)
    cmd_first = make_push_command(first, '/api/webhook/abc', name=friendly_command_name(first))
    cmd_second = make_push_command(second, '/api/webhook/abc', name=friendly_command_name(second))
    for target, changes in ((cmd_first, first_mutations), (cmd_second, second_mutations)):
        for key, value in (changes or {}).items():
            if value == '_DELETE_':
                target.pop(key, None)
            else:
                target[key] = value

    class ReadOnlyAdmin:
        def __init__(self):
            self.reads = 0

        async def read_config(self):
            self.reads += 1
            return {'WebDevices': {'19': {'Name': 'CL Push Home Assistant', 'BaseId': 9}},
                    'FubModules': {'10': {'19': {'200': cmd_first, '201': cmd_second}}}}

    admin = ReadOnlyAdmin()
    runtime = SimpleNamespace(hass=object(), admin=admin,
                              channels={first.key: first, second.key: second},
                              entry=SimpleNamespace(data={'webhook_id': 'abc'}))
    return PushRebuild(runtime, object()), admin, second


def test_live_parity_read_runs_only_once_and_updates_cache():
    rebuild, admin, second = _comparison_fixture()
    cache = {'staged': True}
    asyncio.run(rebuild._verify_initial_append(cache, second))
    assert admin.reads == 1
    assert 'staged' not in cache
    assert cache['FubModules']['10']['19']['200']['Name'] == 'CL Rollladen Schlafzimmer M69'


@pytest.mark.parametrize('first,second,expected', [
    ({'Protocol': '_DELETE_'}, {}, 'Protocol'),
    ({}, {'DefaultActive': '_DELETE_'}, 'DefaultActive'),
    ({}, {'WebDeviceId': 999}, 'WebDeviceId'),
    ({}, {'TypeId': 1}, 'TypeId'),
    ({}, {'Max': 42}, 'Max'),
])
def test_live_parity_blocks_bad_form_records_before_any_links(first, second, expected):
    rebuild, admin, appended = _comparison_fixture(first_mutations=first, second_mutations=second)
    cache = {'original': True}
    with pytest.raises(RebuildError, match=expected):
        asyncio.run(rebuild._verify_initial_append(cache, appended))
    assert admin.reads == 1
    assert cache == {'original': True}


def test_live_parity_does_not_leak_webhook_token_in_message():
    rebuild, _, appended = _comparison_fixture(
        second_mutations={'Parameter': '/api/webhook/wrong-secret-token'})
    with pytest.raises(RebuildError) as caught:
        asyncio.run(rebuild._verify_initial_append({}, appended))
    assert 'wrong-secret-token' not in str(caught.value)
