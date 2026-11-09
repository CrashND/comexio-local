"""v0.3.8: destructive COMEXIO GETs require ownership, consent, readback.

Only mocks of captured COMEXIO 11.1.5 responses; no hardware writes.
"""
import asyncio
from copy import deepcopy

import pytest

from comexio_local.admin_api import AdminError, ComexioAdmin
from comexio_local.push_cleanup import _preflight, cleanup_owned_push
from comexio_local.push_rebuild import PushRebuild, RebuildError
from comexio_local.push_labels import PREFERRED_PUSH_CLASS
from test_push_audit import _installed, ENTRY, BASE
from test_push_rebuild import AdminFake, FakeRuntime, MemoryStore, fake_dispatcher


def setup_admin():
    config, plans, channels = _installed()
    return AdminFake(config, plans), channels


def test_cleanup_success_without_touching_original_plans():
    admin, channels = setup_admin()
    before = deepcopy(admin.config['Fubs']['13'])
    original_ids = set(admin.config['Fubs'])
    async def go():
        result = await cleanup_owned_push(admin, ENTRY, channels, BASE)
        assert len([w for w in admin.writes if w[0] == 'delete_plan']) == len(original_ids) - 1
        assert admin.writes[-1] == ('delete_device', '19')
        assert admin.config['Fubs'] == {'13': before}
        assert result['Fubs'] == {'13': before}
        assert admin.config['WebDevices'] == {}
    asyncio.run(go())


def test_cleanup_requires_distinct_confirmation_before_any_write():
    admin, channels = setup_admin()
    manager = PushRebuild(FakeRuntime(admin, channels), MemoryStore())
    async def go():
        preview = await manager.preview()
        with pytest.raises(RebuildError, match='separat bestätigen'):
            await manager.start(preview['fingerprint'], True)
        assert not admin.writes
        assert manager.status()['status'] == 'not_started'
    asyncio.run(go())


def test_foreign_reference_to_own_webio_stops_entire_cleanup():
    admin, channels = setup_admin()
    admin.plans['13'] = {'elements': {'42': {'reference': {'type': 10, 'ref_id': 201}}},
                         'connections': {}}
    async def go():
        with pytest.raises(AdminError, match='Fremder Logikplan'):
            await cleanup_owned_push(admin, ENTRY, channels, BASE)
        assert not admin.writes
    asyncio.run(go())


def test_edited_owned_plan_with_foreign_element_never_deleted():
    admin, channels = setup_admin()
    first = next(k for k, meta in admin.config['Fubs'].items() if k != '13')
    admin.plans[first]['elements']['9999'] = {'reference': {'type': 5, 'ref_id': 123}}
    async def go():
        with pytest.raises(AdminError, match='fremde Elemente'):
            await cleanup_owned_push(admin, ENTRY, channels, BASE)
        assert not admin.writes
    asyncio.run(go())


@pytest.mark.parametrize('mutation,expected_error', [
    (lambda a: a.config['WebDevices']['19'].update(Ip='192.168.10.99:8123'), 'abweichendes Ziel'),
    (lambda a: a.config['Fubs']['101'].update(Comment='Manually added'), 'Eigentumsnachweis'),
    (lambda a: a.config['FubModules']['10']['19'].update({'999': {'Name':'NOT OURS'}}), 'Fremde'),
    (lambda a: a.config['FubModules']['10'].update({'20': {'201': {'Name': 'Other'}}}), 'Mehrdeutige'),
])
def test_guards_before_any_delete(mutation, expected_error):
    admin, channels = setup_admin()
    mutation(admin)
    async def go():
        with pytest.raises(AdminError, match=expected_error):
            await cleanup_owned_push(admin, ENTRY, channels, BASE)
        assert not admin.writes
    asyncio.run(go())


def test_unknown_plan_readback_stops_before_delete():
    admin, channels = setup_admin()
    async def broken_read_plans(*args, **kwargs):
        return {}
    admin.read_plans = broken_read_plans
    async def go():
        with pytest.raises(AdminError, match='unvollständig'):
            await cleanup_owned_push(admin, ENTRY, channels, BASE)
        assert not admin.writes
    asyncio.run(go())


class FakeResponse:
    def __init__(self, status, location='', on_enter=None):
        self.status = status
        self.headers = {'Location': location}
        self.on_enter = on_enter
    async def __aenter__(self):
        if self.on_enter: self.on_enter()
        return self
    async def __aexit__(self, *args):
        return False
    async def read(self):
        return b'<html>COMEXIO Web IO</html>'


class FakeSession:
    def __init__(self, factory):
        self.factory = factory
        self.calls = []
    def get(self, url, *, params=None, headers=None, allow_redirects=True):
        self.calls.append((url, deepcopy(params), deepcopy(headers), allow_redirects))
        return self.factory(url, params)


class DeleteAdmin(ComexioAdmin):
    def __init__(self, config, response_factory):
        super().__init__(FakeSession(response_factory), 'example.invalid', 'test', 'none')
        self.config = deepcopy(config)
        self.write_gap = 0
    async def read_config(self):
        return deepcopy(self.config)


def test_real_302_plan_delete_requires_redirect_and_missing_plan_readback():
    config, _, _ = _installed()
    fid = '101'
    name = config['Fubs'][fid]['Name']
    admin = None
    def factory(url, params):
        assert params == {'id': fid}
        assert url.endswith('/admin/function_function_module/delete/')
        return FakeResponse(302, '/admin/function_function_module/home/?delete=ok&name=' + name,
                            on_enter=lambda: admin.config['Fubs'].pop(fid))
    admin = DeleteAdmin(config, factory)
    asyncio.run(admin.delete_owned_push_plan(int(fid), name=name, entry_id=ENTRY))
    assert fid not in admin.config['Fubs']
    assert not admin.session.calls[0][3]
    assert 'X-Requested-With' not in admin.session.calls[0][2]


def test_302_redirect_without_actual_deletion_is_rejected():
    config, _, _ = _installed()
    name = config['Fubs']['101']['Name']
    admin = DeleteAdmin(config, lambda *args: FakeResponse(
        302, '/admin/function_function_module/home/?delete=ok&name=' + name))
    with pytest.raises(AdminError, match='weiterhin vorhanden'):
        asyncio.run(admin.delete_owned_push_plan(101, name=name, entry_id=ENTRY))


def test_webio_device_200_may_mean_rejected_or_success():
    config, _, _ = _installed()
    failure = DeleteAdmin(config, lambda *args: FakeResponse(200))
    with pytest.raises(AdminError, match='weiterhin vorhanden'):
        asyncio.run(failure.delete_owned_push_device('19', expected_name=PREFERRED_PUSH_CLASS))
    admin = None
    def success(url, params):
        assert url.endswith('/admin/web_io/delete_device/')
        assert params == {'id': '19'}
        return FakeResponse(200, on_enter=lambda: (admin.config['WebDevices'].pop('19'),
                                                admin.config['FubModules']['10'].pop('19')))
    admin = DeleteAdmin(config, success)
    asyncio.run(admin.delete_owned_push_device('19', expected_name=PREFERRED_PUSH_CLASS))
    assert not admin.session.calls[0][3]
    assert '19' not in admin.config['WebDevices']


def test_interrupted_cleanup_stops_between_deletes_with_no_retries():
    admin, channels = setup_admin()
    async def go():
        with pytest.raises(AdminError, match='angehalten'):
            await cleanup_owned_push(admin, ENTRY, channels, BASE,
                                     should_stop=lambda: bool(admin.writes))
        assert len(admin.writes) == 1
        assert admin.writes[0][0] == 'delete_plan'
    asyncio.run(go())


def test_incomplete_old_cleanup_checkpoint_never_grants_new_delete_consent(fake_dispatcher):
    admin, channels = setup_admin()
    store = MemoryStore({
        'version': 3, 'entry_id': ENTRY, 'status': 'awaiting_cleanup',
        'steps': [], 'cursor': 0, 'started_at_utc': '2026-11-09T00:00:00Z',
        'elapsed_seconds': 0,
    })
    manager = PushRebuild(FakeRuntime(admin, channels), store)
    async def go():
        await manager.initialize()
        assert manager.status()['status'] == 'cancelled'
        assert 'neue Push-Vorschau' in manager.status()['message']
        assert not admin.writes
    asyncio.run(go())


def test_final_audit_rejects_unreadable_active_but_not_unreadable_optional_http_fields():
    from comexio_local.push_rebuild import RebuildError
    config, plans, channels = _installed()
    admin = AdminFake(config, plans)
    manager = PushRebuild(FakeRuntime(admin, channels), MemoryStore())
    step = {'kind': 'verify', 'key': 'all', 'label': 'Abschlusskontrolle'}
    async def go():
        admin.config['FubModules']['10']['19']['201'].pop('Active')
        with pytest.raises(RebuildError, match='Abschlussprüfung'):
            await manager._execute_step(step, admin.config, admin.plans)
        admin.config['FubModules']['10']['19']['201']['Active'] = '1'
        admin.config['FubModules']['10']['19']['201'].pop('Data')
        await manager._execute_step(step, admin.config, admin.plans)
    asyncio.run(go())
