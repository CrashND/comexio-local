"""v0.3.7: COMEXIO 11.1.5 editor's active POST, strict ID/readback and guards.

Offline simulation of the captured form data and JSON response; not a claim
that an actual COMEXIO system was contacted.
"""
from __future__ import annotations

import asyncio
from copy import deepcopy

import pytest

from comexio_local.admin_api import ComexioAdmin, AdminError
from comexio_local.push_audit import audit_config
from test_push_audit import _installed, ENTRY, PATH, BASE
from test_push_rebuild import fake_dispatcher


NAME = 'CL Licht Buero IO-Ext-2/Q2'
OTHER = 'CL Licht Kinderzimmer IO-Ext-2/Q3'


def sample(*, active='0', klass='CL Push Home Assistant', second=False):
    commands = {'126': {'Name': NAME, 'Id': 126, 'WebCommandId': 1422,
                        'WebDeviceId': 8, 'Active': active}}
    if second:
        commands['127'] = {'Name': OTHER, 'Id': 127, 'WebCommandId': 1423,
                           'WebDeviceId': 8, 'Active': '0'}
    return {'WebDevices': {'8': {'Name': klass}},
            'FubModules': {'10': {'8': commands}}}


class CapturedAdmin(ComexioAdmin):
    def __init__(self, config, *, reply='ok', persist=True):
        super().__init__(None, 'example.invalid', 'user', 'unused')
        self.config = deepcopy(config)
        self.reply = reply
        self.persist = persist
        self.posts = []
        self.reads = 0

    async def read_config(self):
        self.reads += 1
        return deepcopy(self.config)

    async def request_json(self, method, route, *, data=None, **kwargs):
        assert method == 'POST' and route == '/admin/web_io/set_web_io_active'
        self.posts.append(deepcopy(data))
        if self.reply == 'negative':
            return {'ok': False, 'active': False, 'io': {}}
        if self.reply == 'wrong_command':
            returned_command = int(data['command']) + 1
        else:
            returned_command = int(data['command'])
        if self.persist:
            self.config['FubModules']['10'][data['device']][data['webIo']]['Active'] = '1'
        return {'ok': True, 'active': True,
                'io': {data['webIo']: {'Id': int(data['webIo']),
                                     'WebDeviceId': int(data['device']),
                                     'WebCommandId': returned_command,
                                     'Active': '1'}}}


def test_captured_editor_form_and_response_activate_then_read_back():
    admin = CapturedAdmin(sample())
    updated = asyncio.run(admin.ensure_webio_commands_active(sample(), '8', [NAME]))
    assert admin.posts == [{'webIo': '126', 'device': '8',
                            'command': '1422', 'active': '1'}]
    assert updated['FubModules']['10']['8']['126']['Active'] == '1'
    assert admin.reads == 1
    assert sample()['FubModules']['10']['8']['126']['Active'] == '0'


def test_second_command_and_already_active_command_are_not_confused():
    original = sample(active='1', second=True)
    admin = CapturedAdmin(original)
    result = asyncio.run(admin.ensure_webio_commands_active(original, '8', [NAME, OTHER]))
    assert admin.posts == [{'webIo': '127', 'device': '8',
                            'command': '1423', 'active': '1'}]
    assert all(cmd['Active'] == '1' for cmd in result['FubModules']['10']['8'].values())


def test_already_active_never_posts_or_reads_again():
    config = sample(active='1')
    admin = CapturedAdmin(config)
    result = asyncio.run(admin.ensure_webio_commands_active(config, '8', [NAME]))
    assert result is config
    assert admin.posts == [] and admin.reads == 0


@pytest.mark.parametrize('wrong,error', [
    (lambda c: c['WebDevices']['8'].update(Name='Other Web-IO'), 'CL-Push-Klasse'),
    (lambda c: c['FubModules']['10']['8']['126'].update(Id=500), 'widersprüchliche'),
    (lambda c: c['FubModules']['10']['8']['126'].update(WebDeviceId=9), 'Geräte-ID'),
    (lambda c: c['FubModules']['10']['8']['126'].pop('WebCommandId'), 'WebCommandId'),
    (lambda c: c['FubModules']['10']['8']['126'].update(WebCommandId=0), 'WebCommandId'),
])
def test_preflight_rejects_unsafe_ids_before_any_write(wrong, error):
    config = sample()
    wrong(config)
    admin = CapturedAdmin(config)
    with pytest.raises(AdminError, match=error):
        asyncio.run(admin.ensure_webio_commands_active(config, '8', [NAME]))
    assert admin.posts == []


def test_preflight_validates_entire_batch_before_any_write():
    config = sample(second=True)
    config['FubModules']['10']['8']['127'].pop('WebCommandId')
    admin = CapturedAdmin(config)
    with pytest.raises(AdminError, match='WebCommandId'):
        asyncio.run(admin.ensure_webio_commands_active(config, '8', [NAME, OTHER]))
    assert admin.posts == []


@pytest.mark.parametrize('names', [[], [NAME, NAME], ['Other Befehl'], ['CL Falsch']])
def test_only_exact_and_unique_owned_command_names(names):
    config = sample()
    admin = CapturedAdmin(config)
    with pytest.raises(AdminError):
        asyncio.run(admin.ensure_webio_commands_active(config, '8', names))
    assert admin.posts == []


@pytest.mark.parametrize('reply,error', [('negative', 'nicht eindeutig bestätigt'),
                                        ('wrong_command', 'nicht eindeutig bestätigt')])
def test_bad_editor_response_stops_without_retries(reply, error):
    config = sample()
    admin = CapturedAdmin(config, reply=reply)
    with pytest.raises(AdminError, match=error):
        asyncio.run(admin.ensure_webio_commands_active(config, '8', [NAME]))
    assert len(admin.posts) == 1 and admin.reads == 0


def test_positive_post_but_inactive_readback_stops_without_retry():
    config = sample()
    admin = CapturedAdmin(config, persist=False)
    with pytest.raises(AdminError, match='nicht aktiv zurücklesbar'):
        asyncio.run(admin.ensure_webio_commands_active(config, '8', [NAME]))
    assert len(admin.posts) == 1 and admin.reads == 1


def test_input_own_class_uses_same_single_activation_method():
    input_name = 'CL Eingang IO-Ext-2/I1'
    config = sample(klass='CL Eingänge Home Assistant')
    config['FubModules']['10']['8']['126']['Name'] = input_name
    admin = CapturedAdmin(config)
    updated = asyncio.run(admin.ensure_webio_commands_active(config, '8', [input_name]))
    assert updated['FubModules']['10']['8']['126']['Active'] == '1'
    assert len(admin.posts) == 1


def test_audit_reports_inactive_instead_of_ready():
    config, plans, channels = _installed()
    config['FubModules']['10']['19']['201']['Active'] = '0'
    result = audit_config(config, plans, channels, ENTRY, PATH, BASE)
    assert not result.ready
    assert any('deaktiviert' in e for e in result.errors)


def test_audit_does_not_conflate_default_active_with_actual_active():
    config, plans, channels = _installed()
    config['FubModules']['10']['19']['201'].pop('Active')
    assert config['FubModules']['10']['19']['201']['DefaultActive'] == 1
    result = audit_config(config, plans, channels, ENTRY, PATH, BASE)
    assert not result.ready
    assert any('Active nicht auslesbar' in e for e in result.unknown_settings)


def test_initial_push_setup_enables_commands_before_any_graph_write(monkeypatch):
    """The configure_push service and full rebuild now use one job writer."""
    from comexio_local import push_rebuild
    from comexio_local.discovery import discover
    from comexio_local.push_repair import inspect_push_repair
    from test_discovery import _config
    from test_push_rebuild import AdminFake, FakeRuntime, MemoryStore
    from comexio_local.push_rebuild import PushRebuild

    config = _config()
    admin = AdminFake(config)
    channels = discover(config)
    manager = PushRebuild(FakeRuntime(admin, channels), MemoryStore())

    async def fake_append(adm, device_id, base_id, cmd):
        adm.writes.append(('append', cmd['Name']))
        adm.next_cmd += 1
        adm.config['FubModules']['10'][str(device_id)][str(adm.next_cmd)] = deepcopy(cmd)

    monkeypatch.setattr(push_rebuild, '_append_command', fake_append)
    monkeypatch.setattr(push_rebuild, 'SETTLE_GAP', 0)

    async def go():
        keys = [signal.key for signal in push_rebuild.push_sources(channels)]
        preview = await inspect_push_repair(admin, channels, ENTRY, PATH, BASE, keys)
        await manager.start_repair(keys, mode='repair', fingerprint=preview.fingerprint,
                                   confirmed=True)
        await manager._task
        assert manager.status()['status'] == 'completed', manager.status()
    asyncio.run(go())
    activations = [i for i, (kind, *_) in enumerate(admin.writes) if kind == 'webio_active']
    links = [i for i, (kind, *_) in enumerate(admin.writes) if kind in ('element', 'wire')]
    assert len(activations) == 2 and links and max(activations) < min(links)
    assert any(kind == 'activate' for kind, *_ in admin.writes)


def test_force_newly_created_posts_even_when_config_says_active():
    """The Studio switch can still be off although imported Active equals 1."""
    config = sample(active='1')
    admin = CapturedAdmin(config)
    updated = asyncio.run(admin.ensure_webio_commands_active(config, '8', [NAME], force=True))
    assert admin.posts == [{'webIo': '126', 'device': '8',
                            'command': '1422', 'active': '1'}]
    assert updated['FubModules']['10']['8']['126']['Active'] == '1'
    assert admin.reads == 1


def test_only_new_commands_forced_from_mixed_existing_batch():
    config = sample(active='1', second=True)
    config['FubModules']['10']['8']['127']['Active'] = '1'
    admin = CapturedAdmin(config)
    asyncio.run(admin.ensure_webio_commands_active(
        config, '8', [NAME, OTHER], force_names={OTHER}))
    assert admin.posts == [{'webIo': '127', 'device': '8',
                            'command': '1423', 'active': '1'}]


def test_force_names_outside_selected_batch_rejected_before_writes():
    config = sample()
    admin = CapturedAdmin(config)
    with pytest.raises(AdminError, match='Ungültige neu angelegte'):
        asyncio.run(admin.ensure_webio_commands_active(config, '8', [NAME],
                                                       force_names={OTHER}))
    assert not admin.posts
