"""v0.3.9: legacy hashed command names must be safe to recognize, not blindly deleted."""
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


LEGACY_COVERS = [
    ('Kinderzimmer seite', 71, 'CL Rollladen Kinderzimme-3AC3 M71'),
    ('Kinderzimmer front', 73, 'CL Rollladen Kinderzimme-811D M73'),
    ('Wohnzimmer EC15', 87, 'CL Rollladen Wohnzimmer-EC15 M87'),
    ('Wohnzimmer F544', 91, 'CL Rollladen Wohnzimmer-F544 M91'),
    ('Esszimmer Terrasse', 93, 'CL Rollladen Esszimmer T-EDB0 M93'),
]


def _historical_config():
    signals = [Channel(kind='cover', name='Rollladen ' + room,
                       key=f'cover:M{marker}', marker_id=marker, analog=True)
               for room, marker, _ in LEGACY_COVERS]
    config = {'FubModules': {'10': {'8': {}}}}
    plan = {'elements': {}, 'connections': {}}
    for idx, (_, marker, old_label) in enumerate(LEGACY_COVERS, 1):
        command_id = 108 + idx
        config['FubModules']['10']['8'][str(command_id)] = {
            'Name': old_label, 'TypeId': 2, 'WebDeviceId': 8}
        source_eid, command_eid = idx * 2, idx * 2 + 1
        plan['elements'][str(source_eid)] = {'reference': {'type': 2, 'ref_id': marker}}
        plan['elements'][str(command_eid)] = {'reference': {'type': 10, 'ref_id': command_id}}
        # Real COMEXIO loadelements response shape, not a guessed mock format.
        plan['connections'][str(idx)] = {
            'input': {'FubElementId': source_eid, 'IOPos': 0, 'Inverted': False},
            'output': [{'FubElementId': command_eid, 'IOPos': 0, 'Inverted': False}]}
    return config, {'33': plan}, signals


def _fixture_with_legacy_name():
    config, plans, channels = _installed()
    original_channel = channels['cover:M79']
    channels['cover:M79'] = replace(original_channel,
                                   name='Rollladen Wohnzimmer Front EC15')
    canonical = friendly_command_name(original_channel)
    for record in config['FubModules']['10']['19'].values():
        if record['Name'] == canonical:
            record['Name'] = 'CL Rollladen Wohnzimmer-EC15 M79'
            break
    else:
        raise AssertionError('fixture cover command was not found')
    return AdminFake(config, plans), channels


def test_five_reported_hash_suffixes_match_unique_physical_markers():
    config, plans, signals = _historical_config()
    resolved = validate_owned_push_commands(config, '8', signals, plans)
    assert {cid: signal.marker_id for cid, signal in resolved.items()} == {
        109: 71, 110: 73, 111: 87, 112: 91, 113: 93}


def test_canonical_light_shortened_with_old_module_code():
    signal = Channel(kind='light', name='Flur und Kaminzimmer Licht',
                     plan='Flur und Kaminzimmer', extension='IO-Server-1',
                     identifier='Q2', io_id=42, key='io:IO-Server-1/Q2')
    config = {'FubModules': {'10': {'8': {'126': {
        'Name': 'CL Licht Flur und Ka-789C S1/Q2', 'TypeId': 1,
        'WebDeviceId': '8'}}}}}
    assert list(validate_owned_push_commands(config, '8', [signal], {}).values()) == [signal]


def test_preview_and_full_cleanup_accept_previous_short_label_without_foreign_writes():
    admin, channels = _fixture_with_legacy_name()
    original = deepcopy(admin.config['Fubs']['13'])
    async def go():
        manager = PushRebuild(FakeRuntime(admin, channels), MemoryStore())
        preview = await manager.preview()
        assert preview['requires_cleanup'] is True
        assert preview['commands'] == len(admin.config['FubModules']['10']['19'])
        assert not admin.writes
        config, owned, device_id = await _preflight(admin, ENTRY, channels, BASE)
        assert len(owned) >= 1 and device_id == '19'
        await cleanup_owned_push(admin, ENTRY, channels, BASE)
        assert admin.config['Fubs'] == {'13': original}
        assert admin.writes[-1] == ('delete_device', '19')
        assert len([w for w in admin.writes if w[0] == 'delete_plan']) == len(owned)
    asyncio.run(go())


def test_cleanup_can_resume_after_owned_plans_were_deleted():
    admin, channels = _fixture_with_legacy_name()
    for fid, record in list(admin.config['Fubs'].items()):
        if fid != '13':
            admin.config['Fubs'].pop(fid)
            admin.plans.pop(fid, None)
    async def go():
        await cleanup_owned_push(admin, ENTRY, channels, BASE)
        assert admin.writes == [('delete_device', '19')]
    asyncio.run(go())


def test_confirmed_rebuild_with_legacy_name_runs_cleanup_then_recreates(monkeypatch, fake_dispatcher):
    """Exercise the user's full preview -> consent -> cleanup -> rebuild path."""
    from comexio_local import push_rebuild as module
    admin, channels = _fixture_with_legacy_name()
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
        actions = [entry[0] for entry in admin.writes]
        assert 'delete_plan' in actions and 'delete_device' in actions
        assert max(i for i, value in enumerate(actions) if value == 'delete_plan') < actions.index('delete_device')
        assert actions.index('delete_device') < actions.index('class')
        assert admin.config['Fubs']['13'] == original
        assert all(record['Name'] != 'CL Rollladen Wohnzimmer-EC15 M79'
                   for record in admin.config['FubModules']['10']['19'].values())

    asyncio.run(go())


@pytest.mark.parametrize('bad_name', [
    'CL Rollladen Anderer Raum-EC15 M79', # no matching current prefix
    'CL Rollladen Wohnzimmer-EC15 M71',  # wrong physical marker
    'CL Rollladen Wohnzimmer-INVALID M79',
    'CL Rollladen Wohnz-EC15 M79',       # unreasonably short prefix
    'NOT OURS Wohnzimmer-EC15 M79',
])
def test_unknown_or_spoofed_names_still_block_without_deleting(bad_name):
    admin, channels = _fixture_with_legacy_name()
    for record in admin.config['FubModules']['10']['19'].values():
        if record['Name'] == 'CL Rollladen Wohnzimmer-EC15 M79':
            record['Name'] = bad_name
    async def go():
        with pytest.raises((AdminError, RebuildError), match='Fremde/unbekannte'):
            await cleanup_owned_push(admin, ENTRY, channels, BASE)
        assert not admin.writes
    asyncio.run(go())


def test_graph_link_to_wrong_source_blocks_legacy_cleanup():
    admin, channels = _fixture_with_legacy_name()
    for plan in admin.plans.values():
        refs = plan['elements']
        if any(element['reference'] == {'type': 2, 'ref_id': 79}
               for element in refs.values()):
            for element in refs.values():
                if element['reference'] == {'type': 2, 'ref_id': 79}:
                    element['reference'] = {'type': 1, 'ref_id': 4}
    async def go():
        with pytest.raises(AdminError, match='widerspricht'):
            await cleanup_owned_push(admin, ENTRY, channels, BASE)
        assert not admin.writes
    asyncio.run(go())


def test_duplicate_command_for_same_marker_blocks_cleanup():
    admin, channels = _fixture_with_legacy_name()
    admin.config['FubModules']['10']['19']['999'] = {
        'Name': friendly_command_name(channels['cover:M79']), 'TypeId': 2}
    async def go():
        with pytest.raises(AdminError, match='Mehrere Web-IO-Befehle'):
            await cleanup_owned_push(admin, ENTRY, channels, BASE)
        assert not admin.writes
    asyncio.run(go())


def test_mismatched_type_or_device_id_blocks_cleanup():
    for key, value, match in [('TypeId', 1, 'Typ'), ('WebDeviceId', '23', 'Geräte-ID')]:
        admin, channels = _fixture_with_legacy_name()
        for record in admin.config['FubModules']['10']['19'].values():
            if record['Name'] == 'CL Rollladen Wohnzimmer-EC15 M79':
                record[key] = value
        async def go():
            with pytest.raises(AdminError, match=match):
                await cleanup_owned_push(admin, ENTRY, channels, BASE)
            assert not admin.writes
        asyncio.run(go())
