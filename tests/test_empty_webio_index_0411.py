"""v0.4.11: strictly empty COMEXIO Web-IO arrays after manual EI cleanup.

The actual v0.4.10 firmware response is not available: [] is the testable
hypothesis. Populated arrays and malformed objects must still fail closed.
"""
from __future__ import annotations

import asyncio
from copy import deepcopy

import pytest

from comexio_local.admin_api import AdminError
from comexio_local.discovery import discover
from comexio_local.input_push import apply_input_push, inspect_input_push
from comexio_local.managed_resources import unique_webio_commands
from test_enocean_044 import enocean_config
from test_input_push_0363 import InputAdminFake
from test_push_audit import BASE, ENTRY, PATH, _installed


def test_only_an_empty_array_is_accepted_as_empty_command_index():
    config = {'FubModules': {'10': {'77': []}}}
    assert unique_webio_commands(config, '77') == {}
    config['FubModules']['10']['77'] = {}
    assert unique_webio_commands(config, '77') == {}
    assert unique_webio_commands(config, None) == {}


@pytest.mark.parametrize('unexpected, typename, count', [
    ([{'Name':'CL Eingang test', 'Data':'private-webhook-value'}], 'list', 1),
    ([1, 2], 'list', 2),
    ('private-webhook-value', 'str', None),
    (None, 'NoneType', None),
    (0, 'int', None),
    ((), 'tuple', 0),
])
def test_unexpected_nonempty_or_nonarray_command_structures_still_block(unexpected, typename, count):
    config = {'FubModules': {'10': {'77': unexpected}}}
    with pytest.raises(AdminError, match='Unbekannte COMEXIO-Web-IO-Befehlsstruktur') as error:
        unique_webio_commands(config, '77')
    message = str(error.value)
    assert f'Typ: {typename}' in message
    if count is not None:
        assert f'Einträge: {count}' in message
    assert 'private-webhook-value' not in message
    assert 'keine Änderung' in message


def _cleaned_enocean_admin():
    # Preserve an independent, fully functional Q output class and plans.
    config, protected_plans, _ = _installed()
    config['FubModules']['1']['9'] = deepcopy(enocean_config()['FubModules']['1']['9'])
    config['WebDevices']['77'] = {
        'Name': 'CL Eingänge Home Assistant',
        'Ip': '192.168.10.6:8123', 'WebDeviceBaseId': 9,
    }
    config['FubModules']['10']['77'] = []
    return InputAdminFake(config, protected_plans)


def test_enocean_preview_after_cleanup_accepts_empty_array_without_writes():
    admin = _cleaned_enocean_admin()
    raw = discover(admin.config)
    original_config = deepcopy(admin.config)
    selected = {'io:EnOcean/EI5_CO': 'auto'}

    async def run():
        preview = await inspect_input_push(admin, raw, ENTRY, PATH, BASE, selected)
        assert preview['needs_write'] is True
        assert preview['plan_count'] == 1
        assert preview['sources'][0]['action'] == 'anlegen'
        assert preview['sources'][0]['plan'] == 'CL Eingänge EnOcean Kontakte'
        assert admin.config == original_config
        assert admin.writes == []

    asyncio.run(run())


def test_enocean_sync_with_cleaned_array_keeps_other_push_resources(monkeypatch):
    from comexio_local import input_push
    admin = _cleaned_enocean_admin()
    raw = discover(admin.config)
    protected_plans = deepcopy(admin.plans)
    protected_commands = deepcopy(admin.config['FubModules']['10']['19'])
    selected = {'io:EnOcean/EI5_CO': 'auto'}

    async def append(fake, device_id, base_id, command):
        assert device_id == '77' and base_id == '9'
        assert fake.config['FubModules']['10']['77'] == []
        fake.writes.append(('append', command['Name'], fake.write_gap))
        # Simulates a fresh COMEXIO command readback after save_command:
        # records now have their real numeric firmware IDs as dictionary keys.
        fake.next_cmd += 1
        fake.config['FubModules']['10']['77'] = {
            str(fake.next_cmd): {**deepcopy(command), 'Active': 1}
        }

    monkeypatch.setattr(input_push, '_append_command', append)

    async def run():
        before = await inspect_input_push(admin, raw, ENTRY, PATH, BASE, selected)
        stats = await apply_input_push(admin, raw, ENTRY, PATH, BASE, selected,
                                       before['fingerprint'], True)
        assert stats['created_commands'] == 1
        assert stats['added_links'] == 1
        assert stats['verified'] == 1
        assert stats['activated_plans'] == 1
        assert admin.config['FubModules']['10']['19'] == protected_commands
        assert all(admin.plans[fid] == plan for fid, plan in protected_plans.items())
        assert not any(row[0] == 'class' for row in admin.writes)
        assert len([row for row in admin.writes if row[0] == 'append']) == 1
        assert len([meta for meta in admin.config['Fubs'].values()
                    if meta.get('Name') == 'CL Eingänge EnOcean Kontakte']) == 1
        after = await inspect_input_push(admin, raw, ENTRY, PATH, BASE, selected)
        assert after['sources'][0]['action'] == 'vorhanden'
        written = len(admin.writes)
        await apply_input_push(admin, raw, ENTRY, PATH, BASE, selected,
                               after['fingerprint'], True)
        assert len(admin.writes) == written

    asyncio.run(run())


def test_enocean_preview_rejects_nonempty_array_before_any_writes():
    admin = _cleaned_enocean_admin()
    admin.config['FubModules']['10']['77'] = [{'Id': 301, 'Name': 'CL Eingang fremd'}]
    raw = discover(admin.config)

    async def run():
        with pytest.raises(AdminError, match='Typ: list, Einträge: 1'):
            await inspect_input_push(admin, raw, ENTRY, PATH, BASE,
                                     {'io:EnOcean/EI5_CO': 'auto'})
        assert admin.writes == []

    asyncio.run(run())
