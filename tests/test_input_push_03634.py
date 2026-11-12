"""v0.3.6.3.4: safe partial-input rebuild, readable names, strict present Data."""
import asyncio
import json
from copy import deepcopy

import pytest

from comexio_local.managed_resources import plan_comment
from comexio_local.admin_api import AdminError, make_push_command
from comexio_local.discovery import Channel, discover
from comexio_local.input_push import (
    PREFERRED_INPUT_CLASS, _groups, input_command_name, _same_lua_script, _verified_command,
    apply_input_push, input_device_name, inspect_input_push,
)
from test_discovery import _config
from test_input_push_0363 import InputAdminFake, with_inputs
from test_push_audit import BASE, ENTRY, PATH

KEY = 'io:IO-Ext-2/I1'


def _environment():
    config = with_inputs(_config())
    return config, discover(config)


def test_readable_class_and_plan_names_are_stable_and_not_entry_id_derived():
    assert input_device_name(ENTRY) == PREFERRED_INPUT_CLASS == 'CL Eingänge Home Assistant'
    assert input_device_name('ANOTHER-entry-id') == PREFERRED_INPUT_CLASS
    raw = {
        'io:IO-Ext-3/I1': Channel(kind='input', name='Flur Licht Rot',
            key='io:IO-Ext-3/I1', extension='IO-Ext-3', identifier='I1', io_id=51),
        'io:IO-Ext-3/I19': Channel(kind='input', name='Test Kanal 19',
            key='io:IO-Ext-3/I19', extension='IO-Ext-3', identifier='I19', io_id=52),
        'io:IO-Ext-3/AI2': Channel(kind='analog_input', name='Digital genutzter AI',
            key='io:IO-Ext-3/AI2', extension='IO-Ext-3', identifier='AI2', io_id=53),
    }
    grouped = _groups(raw, ENTRY)
    assert grouped['io:IO-Ext-3/I1'][0] == 'CL Eingänge IO-Ext-3 I1-I18'
    assert grouped['io:IO-Ext-3/I19'][0] == 'CL Eingänge IO-Ext-3 I19-I36'
    assert grouped['io:IO-Ext-3/AI2'][0] == 'CL Eingänge IO-Ext-3 AI1-AI18'
    assert {v[0] for v in grouped.values()} == {v[0] for v in _groups(raw, 'other-id').values()}
    with_one_more = dict(raw)
    with_one_more['io:IO-Ext-3/I2'] = Channel(kind='input', name='Zweiter Eingang',
        key='io:IO-Ext-3/I2', extension='IO-Ext-3', identifier='I2', io_id=54)
    assert _groups(with_one_more, ENTRY)['io:IO-Ext-3/I1'][0] == grouped['io:IO-Ext-3/I1'][0]
    assert not any(ENTRY[:4].upper() in item[0] for item in grouped.values())


def test_duplicate_canonical_input_class_blocks_before_any_write():
    config, raw = _environment()
    admin = InputAdminFake(config)
    admin.config['WebDevices'] = {
        '77': {'Name': PREFERRED_INPUT_CLASS, 'Ip': '192.168.10.6:8123'},
        '78': {'Name': PREFERRED_INPUT_CLASS, 'Ip': '192.168.10.6:8123'}}

    async def check():
        with pytest.raises(AdminError, match='Mehrere Eingangs-Web-IO-Klassen'):
            await inspect_input_push(admin, raw, ENTRY, PATH, BASE, {KEY:'taster'})
        assert admin.writes == []

    asyncio.run(check())


def test_unexpected_owned_input_plan_blocks_clean_setup():
    config, raw = _environment()
    admin = InputAdminFake(config)
    admin.config['Fubs']['123'] = {
        'Name': 'Falsch benannter Eingangsplan',
        'Comment': plan_comment(ENTRY, 'input'),
        'Active': True,
    }

    async def check():
        with pytest.raises(AdminError, match='außerhalb des aktuellen Namensschemas'):
            await inspect_input_push(admin, raw, ENTRY, PATH, BASE, {KEY: 'taster'})
        assert admin.writes == []
        del admin.config['Fubs']['123']
        preview = await inspect_input_push(admin, raw, ENTRY, PATH, BASE, {KEY: 'taster'})
        assert preview['sources'][0]['action'] == 'anlegen'
        assert preview['sources'][0]['plan'].startswith('CL Eingänge')

    asyncio.run(check())


def test_missing_or_empty_data_marks_readback_unverified_not_wrong():
    _, raw = _environment()
    c = raw[KEY]
    expected = make_push_command(c, PATH, name=input_command_name(c))
    for value in ('missing', None, '', '   '):
        stored = deepcopy(expected)
        if value == 'missing':
            del stored['Data']
        else:
            stored['Data'] = value
        assert _verified_command(stored, expected, KEY, '192.168.10.6:8123') is False
    stored = deepcopy(expected)
    stored['Data'] = None
    stored['data'] = expected['Data']
    assert _verified_command(stored, expected, KEY, '192.168.10.6:8123') is True


def test_present_wrong_data_or_unknown_format_remains_blocked():
    _, raw = _environment()
    expected = make_push_command(raw[KEY], PATH, name=input_command_name(raw[KEY]))
    for value in ('function data(a) return "fremd" end', '{ type="io" }', [], 7):
        stored = deepcopy(expected)
        stored['Data'] = value
        with pytest.raises(AdminError, match='Data'):
            _verified_command(stored, expected, KEY, '192.168.10.6:8123')
    stored = deepcopy(expected)
    stored['data'] = 'not the same script'  # conflicting alias also blocks
    with pytest.raises(AdminError, match='Data'):
        _verified_command(stored, expected, KEY, '192.168.10.6:8123')


def test_lua_script_accepts_line_endings_and_json_string_transport_not_other_code():
    _, raw = _environment()
    expected = make_push_command(raw[KEY], PATH, name=input_command_name(raw[KEY]))
    script = expected['Data']
    assert _same_lua_script(script.replace('\r\n', '\n'), script)
    assert _same_lua_script(json.dumps(script), script)
    assert not _same_lua_script(script.replace('value=a', 'value=0'), script)


def test_firmware_omitting_data_during_class_creation_can_finish_unverified(caplog):
    """End-to-end offline simulation of a POST that works but a GET omits Data."""
    config, raw = _environment()

    class OmittedDataAdmin(InputAdminFake):
        async def read_config(self):
            snapshot = await super().read_config()
            for device in (snapshot['FubModules'].get('10') or {}).values():
                for command in device.values():
                    command.pop('Data', None)
            return snapshot

    admin = OmittedDataAdmin(config)
    selected = {KEY:'taster'}

    async def execute():
        before = await inspect_input_push(admin, raw, ENTRY, PATH, BASE, selected)
        assert before['needs_write']
        stats = await apply_input_push(admin, raw, ENTRY, PATH, BASE,
                                       selected, before['fingerprint'], True)
        assert stats['created_commands'] == 1
        assert stats['added_links'] == 1
        assert stats['verified'] == 1
        assert stats['callback_unverified'] == 1
        assert admin.config['FubModules']['10']['77']['201']['Data']  # stored script unaffected
        after = await inspect_input_push(admin, raw, ENTRY, PATH, BASE, selected)
        assert after['sources'][0]['action'] == 'vorhanden'
        assert after['sources'][0]['callback_verified'] is False
        old_writes = len(admin.writes)
        await apply_input_push(admin, raw, ENTRY, PATH, BASE, selected,
                               after['fingerprint'], True)
        assert len(admin.writes) == old_writes  # no duplicates

    asyncio.run(execute())
    assert 'erst durch echten Push-Test' in caplog.text


def test_mismatched_data_during_preview_does_not_modify_existing_components():
    config, raw = _environment()
    admin = InputAdminFake(config)
    cmd = make_push_command(raw[KEY], PATH, name=input_command_name(raw[KEY]))
    cmd['Data'] = 'function data(a) return "foreign" end'
    admin.config['WebDevices'] = {
        '77': {'Name': PREFERRED_INPUT_CLASS, 'Ip':'192.168.10.6:8123', 'WebDeviceBaseId':9}}
    admin.config.setdefault('FubModules', {}).setdefault('10', {})['77'] = {'501':cmd}
    async def check():
        with pytest.raises(AdminError, match='Data'):
            await inspect_input_push(admin, raw, ENTRY, PATH, BASE, {KEY:'taster'})
        assert admin.writes == []
    asyncio.run(check())


def test_header_modifier_missing_or_hidden_is_unverified_but_never_a_mismatch():
    """Generic firmware readback; a visible wrong header remains a hard stop."""
    _, raw = _environment()
    expected = make_push_command(raw[KEY], PATH, name=input_command_name(raw[KEY]))
    for hidden in ('absent', None, '', '   '):
        stored = deepcopy(expected)
        if hidden == 'absent':
            stored.pop('HeaderModifier')
        else:
            stored['HeaderModifier'] = hidden
        assert _verified_command(stored, expected, KEY, '192.168.10.6:8123') is False
    stored = deepcopy(expected)
    stored.pop('HeaderModifier')
    stored['header_modifier'] = expected['HeaderModifier']
    assert _verified_command(stored, expected, KEY, '192.168.10.6:8123') is True
    stored['HeaderModifier'] = 'Content-Type: text/plain'
    with pytest.raises(AdminError, match='HeaderModifier'):
        _verified_command(stored, expected, KEY, '192.168.10.6:8123')
    stored.pop('HeaderModifier')
    stored['header_modifier'] = 'X-Foreign: 1'
    with pytest.raises(AdminError, match='HeaderModifier'):
        _verified_command(stored, expected, KEY, '192.168.10.6:8123')
    stored['header_modifier'] = expected['HeaderModifier']
    stored.pop('TypeId')
    with pytest.raises(AdminError, match='TypeId'):
        _verified_command(stored, expected, KEY, '192.168.10.6:8123')
