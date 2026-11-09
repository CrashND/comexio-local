"""v0.3.11: German legacy spellings and complete safe cleanup diagnostics."""
import asyncio
from copy import deepcopy
from dataclasses import replace
import unicodedata

import pytest

from comexio_local.admin_api import AdminError
from comexio_local.discovery import Channel
from comexio_local.managed_resources import validate_owned_push_commands
from comexio_local.push_cleanup import _preflight, cleanup_owned_push
from comexio_local.push_rebuild import PushRebuild, RebuildError
from comexio_local.push_labels import friendly_command_name
from test_push_audit import _installed, ENTRY, BASE
from test_push_rebuild import AdminFake, FakeRuntime, MemoryStore, fake_dispatcher


def _light(room='K\u00fcche', extension='IO-Ext-2', q='Q6'):
    return Channel(kind='light', name=room + ' Licht', plan=room,
                   key=f'io:{extension}/{q}', extension=extension,
                   identifier=q, io_id=60 + int(q[1:]))


def _single_command(label, signal=None):
    config = {'FubModules': {'10': {'8': {'126': {
        'Name': label, 'TypeId': 1, 'WebDeviceId': '8'}}}}}
    return config, signal or _light()


@pytest.mark.parametrize('room,old_label', [
    ('K\u00fcche', 'CL Licht Kuche E2/Q6'),
    ('K\u00fcche', 'CL Licht Kueche E2/Q6'),
    ('K\u00fcche', 'CL Licht K\u00fcche E2/Q6'),
    ('G\u00e4ste WC', 'CL Licht GasteWC E2/Q6'),
    ('G\u00e4ste WC', 'CL Licht GaesteWC E2/Q6'),
    ('B\u00fcro', 'CL Licht Buro E2/Q6'),
    ('B\u00fcro', 'CL Licht Buero E2/Q6'),
    ('H\u00f6hle', 'CL Licht Hohle E2/Q6'),
    ('H\u00f6hle', 'CL Licht Hoehle E2/Q6'),
    ('Au\u00dfen', 'CL Licht Aussen E2/Q6'),
    ('M\u00fcller B\u00fcro', 'CL Licht MullerBuro E2/Q6'),
    ('M\u00fcller B\u00fcro', 'CL Licht MuellerBuero E2/Q6'),
    ('K\u00fcchenb\u00fcro', 'CL Licht Kuchenburo IO-Ext-2/Q6'),
    ('K\u00fcche', 'CL Licht Kuche IO-Ext-2/Q6'),
])
def test_german_room_variants_resolve_the_same_exact_address(room, old_label):
    signal = _light(room)
    config, _ = _single_command(old_label, signal)
    assert validate_owned_push_commands(config, '8', [signal], {}) == {126: signal}


def test_composed_and_decomposed_unicode_are_equivalent():
    signal = _light()
    old = unicodedata.normalize('NFD', 'CL Licht K\u00fcche E2/Q6')
    config, _ = _single_command(old, signal)
    assert validate_owned_push_commands(config, '8', [signal], {}) == {126: signal}


def test_hashed_truncated_german_room_prefix_still_requires_the_real_address():
    signal = _light('K\u00fcchenzimmer S\u00fcdseite')
    config, _ = _single_command('CL Licht Kuchenzimmer S-AB12 E2/Q6', signal)
    assert validate_owned_push_commands(config, '8', [signal], {}) == {126: signal}
    config['FubModules']['10']['8']['126']['Name'] = 'CL Licht Kuchenzimmer S-AB12 E2/Q5'
    with pytest.raises(AdminError, match='Fremde/unbekannte'):
        validate_owned_push_commands(config, '8', [signal], {})


@pytest.mark.parametrize('bad_label', [
    'CL Licht Bauer E2/Q6',  # no blind folding of ASCII ue: Bauer != Baur
    'CL Licht Kuche E2/Q5',
    'CL Licht Kuche E3/Q6',
    'CL Licht Kuche S2/Q6',
    'CL Licht Kuche E2/Q60',
    'CL Licht KucheGaeste E2/Q6',
    'CL Status Kuche E2/Q6',
    'Other Licht Kuche E2/Q6',
    'CL Licht Kuche E2/Q6 ',
])
def test_similarity_cannot_replace_full_room_role_and_physical_identity(bad_label):
    signal = _light()
    config, _ = _single_command(bad_label, signal)
    with pytest.raises(AdminError, match='Fremde/unbekannte'):
        validate_owned_push_commands(config, '8', [signal], {})


def test_ascii_ue_without_actual_expected_umlaut_is_not_blindly_folded():
    # A generic ue->u rewrite would conflate two genuine distinct German names.
    signal = _light('Bauer')
    config, _ = _single_command('CL Licht Baur E2/Q6', signal)
    with pytest.raises(AdminError, match='Fremde/unbekannte'):
        validate_owned_push_commands(config, '8', [signal], {})


def test_all_independent_command_conflicts_reported_in_one_pass():
    signals = [_light(), _light('B\u00fcro', q='Q2'), _light('G\u00e4ste WC', q='Q3')]
    config = {'FubModules': {'10': {'8': {
        '126': {'Name': 'CL Licht AndereKueche E2/Q6', 'TypeId': 1, 'WebDeviceId': '8'},
        '127': {'Name': 'CL Licht AnderesBuero E2/Q2', 'TypeId': 1, 'WebDeviceId': '8'},
        '128': {'Name': 'CL Licht GasteWC E2/Q3', 'TypeId': 2, 'WebDeviceId': '9'},
    }}}}
    with pytest.raises(AdminError) as error:
        validate_owned_push_commands(config, '8', signals, {})
    msg = str(error.value)
    assert '3 Konflikt' in msg
    assert msg.count('CL Licht ') == 3
    assert 'AndereKueche' in msg and 'AnderesBuero' in msg and 'GasteWC' in msg
    assert 'Ger\u00e4te-ID' in msg and 'Typ' in msg
    assert 'keine Bereinigung' in msg
    assert '127' not in msg  # no accidental secret/diagnostic command-ID dependence


def _installed_with_old_kitchen():
    config, plans, channels = _installed()
    key = 'io:IO-Ext-2/Q1'
    original = channels[key]
    channels[key] = replace(original, plan='K\u00fcche', name='K\u00fcche Licht')
    old_name = friendly_command_name(original)
    matching = [record for record in config['FubModules']['10']['19'].values()
                if record['Name'] == old_name]
    assert len(matching) == 1
    matching[0]['Name'] = 'CL Licht Kuche E2/Q1'
    return AdminFake(config, plans), channels


def test_preview_and_preflight_are_read_only_with_old_kitchen_name():
    admin, channels = _installed_with_old_kitchen()

    async def go():
        manager = PushRebuild(FakeRuntime(admin, channels), MemoryStore())
        preview = await manager.preview()
        assert preview['requires_cleanup']
        assert preview['commands'] == 2
        _, owned, device = await _preflight(admin, ENTRY, channels, BASE)
        assert owned and device == '19'
        assert admin.writes == []

    asyncio.run(go())


def test_confirmed_cleanup_can_validate_old_kitchen_even_after_plan_deletion():
    admin, channels = _installed_with_old_kitchen()
    original_plan = deepcopy(admin.config['Fubs']['13'])

    async def go():
        await cleanup_owned_push(admin, ENTRY, channels, BASE)
        assert admin.config['Fubs'] == {'13': original_plan}
        assert admin.writes[-1] == ('delete_device', '19')
        assert admin.config['WebDevices'] == {}

    asyncio.run(go())


def test_unknown_names_in_preview_and_preflight_remain_read_only_and_aggregated():
    admin, channels = _installed_with_old_kitchen()
    commands = admin.config['FubModules']['10']['19']
    commands['201']['Name'] = 'CL Licht AndereKueche E2/Q1'
    commands['202']['Name'] = 'CL Rollladen Fremd M79'

    async def go():
        manager = PushRebuild(FakeRuntime(admin, channels), MemoryStore())
        with pytest.raises(RebuildError) as error:
            await manager.preview()
        text = str(error.value)
        assert '2 Konflikt' in text
        assert 'AndereKueche' in text and 'Fremd' in text
        assert text.count('Fremde/unbekannte Befehle in eigener Web-IO-Klasse') == 1
        with pytest.raises(AdminError, match='2 Konflikt'):
            await _preflight(admin, ENTRY, channels, BASE)
        assert admin.writes == []

    asyncio.run(go())


def test_full_rebuild_with_kitchen_variant_respects_plan_device_order(monkeypatch, fake_dispatcher):
    from comexio_local import push_rebuild as module
    admin, channels = _installed_with_old_kitchen()
    before = deepcopy(admin.config['Fubs']['13'])
    manager = PushRebuild(FakeRuntime(admin, channels), MemoryStore())

    async def append(adm, device_id, base_id, command):
        adm.next_cmd += 1
        adm.writes.append(('append', command['Name']))
        adm.config['FubModules']['10'][str(device_id)][str(adm.next_cmd)] = deepcopy(command)

    monkeypatch.setattr(module, '_append_command', append)
    monkeypatch.setattr(module, 'SETTLE_GAP', 0)

    async def go():
        preview = await manager.preview()
        assert not admin.writes
        await manager.start(preview['fingerprint'], True, cleanup_confirmed=True)
        await manager._task
        assert manager.status()['status'] == 'completed', manager.status()
        actions = [write[0] for write in admin.writes]
        assert actions.index('delete_plan') < actions.index('delete_device') < actions.index('class')
        assert admin.config['Fubs']['13'] == before
        assert all(record['Name'] != 'CL Licht Kuche E2/Q1'
                   for record in admin.config['FubModules']['10']['19'].values())

    asyncio.run(go())
