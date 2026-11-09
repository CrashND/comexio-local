"""v0.3.10: historical un-hashed E1/Q labels and German room names."""
import asyncio
from copy import deepcopy
from dataclasses import replace

import pytest

from comexio_local.admin_api import AdminError
from comexio_local.discovery import Channel
from comexio_local.managed_resources import validate_owned_push_commands
from comexio_local.push_cleanup import _preflight, cleanup_owned_push
from comexio_local.push_rebuild import PushRebuild, RebuildError
from comexio_local.push_labels import friendly_command_name
from test_push_audit import _installed, ENTRY, BASE
from test_push_rebuild import AdminFake, FakeRuntime, MemoryStore, fake_dispatcher


def _guest_wc_signal(extension='IO-Ext-1'):
    return Channel(kind='light', name='Gäste WC Licht', plan='Gäste WC',
                   key=f'io:{extension}/Q1', extension=extension,
                   identifier='Q1', io_id=4)


def _one_command(label, signal=None):
    signal = signal or _guest_wc_signal()
    config = {'FubModules': {'10': {'8': {'126': {
        'Name': label, 'TypeId': 1, 'WebDeviceId': 8}}}}}
    return config, signal


def test_real_reported_guest_wc_label_maps_to_exact_physical_source():
    config, signal = _one_command('CL Licht GaesteWC E1/Q1')
    assert friendly_command_name(signal) == 'CL Licht Gäste WC IO-Ext-1/Q1'
    # Must remain identifiable after exclusively owned plans have been removed,
    # when the cleanup implementation rechecks before deleting the device.
    assert validate_owned_push_commands(config, '8', [signal], {}) == {126: signal}


def test_unhashed_old_labels_accept_only_exact_room_role_and_address():
    config, signal = _one_command('CL Licht GaesteWC E1/Q1')
    for valid in ['CL Licht GaesteWC E1/Q1',
                  'CL Licht Gäste-WC E1/Q1',
                  'CL Licht Gäste WC IO-Ext-1/Q1']:
        config['FubModules']['10']['8']['126']['Name'] = valid
        assert validate_owned_push_commands(config, '8', [signal], {}) == {126: signal}

    for invalid in ['CL Licht AndererRaum E1/Q1',
                    'CL Licht GaesteWC E2/Q1',
                    'CL Licht GaesteWC E1/Q2',
                    'CL Status GaesteWC E1/Q1',
                    'CL Licht E1/Q1',
                    'Fremd Licht GaesteWC E1/Q1']:
        config['FubModules']['10']['8']['126']['Name'] = invalid
        with pytest.raises(AdminError, match='Fremde/unbekannte'):
            validate_owned_push_commands(config, '8', [signal], {})


def test_short_module_for_server_uses_s_not_e():
    signal = _guest_wc_signal('IO-Server-1')
    config, _ = _one_command('CL Licht GaesteWC S1/Q1', signal)
    assert validate_owned_push_commands(config, '8', [signal], {}) == {126: signal}
    config['FubModules']['10']['8']['126']['Name'] = 'CL Licht GaesteWC E1/Q1'
    with pytest.raises(AdminError, match='Fremde/unbekannte'):
        validate_owned_push_commands(config, '8', [signal], {})


def test_old_label_rejects_wrong_device_and_type():
    config, signal = _one_command('CL Licht GaesteWC E1/Q1')
    config['FubModules']['10']['8']['126']['WebDeviceId'] = 9
    with pytest.raises(AdminError, match='Geräte-ID'):
        validate_owned_push_commands(config, '8', [signal], {})
    config['FubModules']['10']['8']['126']['WebDeviceId'] = 8
    config['FubModules']['10']['8']['126']['TypeId'] = 2
    with pytest.raises(AdminError, match='Typ'):
        validate_owned_push_commands(config, '8', [signal], {})


def _installed_with_legacy_light():
    config, plans, channels = _installed()
    key = 'io:IO-Ext-2/Q1'
    signal = channels[key]
    channels[key] = replace(signal, plan='Gäste WC', name='Gäste WC Licht')
    original_name = friendly_command_name(signal)
    matching = [record for record in config['FubModules']['10']['19'].values()
                if record['Name'] == original_name]
    assert len(matching) == 1
    matching[0]['Name'] = 'CL Licht GaesteWC E2/Q1'
    return AdminFake(config, plans), channels


def test_preview_preflight_and_cleanup_accept_old_guest_wc_without_graph_after_delete():
    admin, channels = _installed_with_legacy_light()
    original = deepcopy(admin.config['Fubs']['13'])

    async def go():
        manager = PushRebuild(FakeRuntime(admin, channels), MemoryStore())
        preview = await manager.preview()
        assert preview['requires_cleanup'] is True
        assert not admin.writes
        await _preflight(admin, ENTRY, channels, BASE)
        await cleanup_owned_push(admin, ENTRY, channels, BASE)
        assert admin.config['Fubs'] == {'13': original}
        assert admin.writes[-1] == ('delete_device', '19')
        assert not admin.config['FubModules']['10'].get('19')

    asyncio.run(go())


def test_foreign_graph_link_still_stops_unhashed_cleanup():
    admin, channels = _installed_with_legacy_light()
    for plan in admin.plans.values():
        for element in plan['elements'].values():
            if element['reference'] == {'type': 1, 'ref_id': 4}:
                element['reference'] = {'type': 1, 'ref_id': 9999}

    async def go():
        with pytest.raises(AdminError, match='fremder Quelle'):
            await cleanup_owned_push(admin, ENTRY, channels, BASE)
        assert not admin.writes

    asyncio.run(go())


def test_confirmed_rebuild_replaces_unhashed_legacy_names(monkeypatch, fake_dispatcher):
    """Ensure the second preflight after plan deletion does not reject old E2/Q."""
    from comexio_local import push_rebuild as module

    admin, channels = _installed_with_legacy_light()
    original = deepcopy(admin.config['Fubs']['13'])
    manager = PushRebuild(FakeRuntime(admin, channels), MemoryStore())

    async def append(adm, device_id, base_id, command):
        adm.next_cmd += 1
        adm.writes.append(('append', command['Name']))
        adm.config['FubModules']['10'][str(device_id)][str(adm.next_cmd)] = deepcopy(command)

    monkeypatch.setattr(module, '_append_command', append)
    monkeypatch.setattr(module, 'SETTLE_GAP', 0)

    async def go():
        preview = await manager.preview()
        await manager.start(preview['fingerprint'], True, cleanup_confirmed=True)
        await manager._task
        assert manager.status()['status'] == 'completed', manager.status()
        events = [write[0] for write in admin.writes]
        assert 'delete_device' in events
        assert max(i for i, event in enumerate(events) if event == 'delete_plan') < events.index('delete_device')
        assert events.index('delete_device') < events.index('class')
        assert admin.config['Fubs']['13'] == original
        assert all(record['Name'] != 'CL Licht GaesteWC E2/Q1'
                   for record in admin.config['FubModules']['10']['19'].values())

    asyncio.run(go())


def test_preview_reports_unowned_name_once_without_double_prefix():
    admin, channels = _installed_with_legacy_light()
    for record in admin.config['FubModules']['10']['19'].values():
        if record['Name'] == 'CL Licht GaesteWC E2/Q1':
            record['Name'] = 'CL Licht AndererRaum E2/Q1'

    async def go():
        manager = PushRebuild(FakeRuntime(admin, channels), MemoryStore())
        with pytest.raises(RebuildError) as error:
            await manager.preview()
        assert str(error.value).count('Fremde/unbekannte Befehle') == 1
        assert not admin.writes

    asyncio.run(go())
