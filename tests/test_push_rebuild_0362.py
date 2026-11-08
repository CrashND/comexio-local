"""v0.3.6.2 regression: bounded reads and recovery of old/partial checkpoints."""
import asyncio
from copy import deepcopy
import sys
import types

import pytest
from comexio_local.admin_api import AdminError, ComexioAdmin
from comexio_local.discovery import discover
from comexio_local.push_rebuild import PushRebuild, RebuildError
from comexio_local.push_setup import push_sources
from test_discovery import _config
from test_push_rebuild import AdminFake, FakeRuntime, MemoryStore


@pytest.fixture(autouse=True)
def fake_dispatcher(monkeypatch):
    dispatch = types.ModuleType('homeassistant.helpers.dispatcher')
    dispatch.async_dispatcher_send = lambda *args: None
    monkeypatch.setitem(sys.modules, 'homeassistant', types.ModuleType('homeassistant'))
    monkeypatch.setitem(sys.modules, 'homeassistant.helpers', types.ModuleType('homeassistant.helpers'))
    monkeypatch.setitem(sys.modules, 'homeassistant.helpers.dispatcher', dispatch)


class InstrumentedAdmin(AdminFake):
    def __init__(self, config):
        super().__init__(config)
        self.config_reads = 0
        self.plan_reads = 0

    async def read_config(self):
        self.config_reads += 1
        return await super().read_config()

    async def read_plan(self, fid):
        self.plan_reads += 1
        return await super().read_plan(fid)


def test_no_full_topology_read_before_and_after_each_step(monkeypatch):
    from comexio_local import push_rebuild as mod
    admin = InstrumentedAdmin(_config())
    runtime = FakeRuntime(admin, discover(admin.config))
    manager = PushRebuild(runtime, MemoryStore())

    async def append_command(adm, dev_id, base_id, cmd):
        adm.next_cmd += 1
        adm.config['FubModules']['10']['19'][str(adm.next_cmd)] = deepcopy(cmd)

    monkeypatch.setattr(mod, '_append_command', append_command)

    async def go():
        preview = await manager.preview()
        await manager.start(preview['fingerprint'], True)
        await manager._task
        assert manager.status()['status'] == 'completed', manager.status()
        assert manager.status()['done'] == manager.status()['total']
        # Two-channel job has 7 steps. Old implementation performed several
        # full snapshots/plan GETs for every one. New path reads at phase edges.
        assert admin.config_reads <= 7, admin.config_reads
        assert admin.plan_reads <= 4, admin.plan_reads
        # 2s pacing remains enforced even while the GET overhead is reduced.
        assert admin.write_gap == 1.25

    asyncio.run(go())


def test_resume_current_checkpoint_with_partial_current_link(monkeypatch):
    """The digest may differ because the current link was half-written."""
    from comexio_local import push_rebuild as mod
    admin = InstrumentedAdmin(_config())
    runtime = FakeRuntime(admin, discover(admin.config))
    store = MemoryStore()
    first = PushRebuild(runtime, store)
    writes = []
    original_add = admin.add_element
    fail = {'yes': True}

    async def flaky_add(fid, ref, typ, x, y, connection=None, **kwargs):
        if typ == 10 and fail['yes'] and len(writes) >= 3:
            fail['yes'] = False
            raise RebuildError('Simulated COMEXIO HTTP 500 after first element of current link')
        result = await original_add(fid, ref, typ, x, y, connection=connection, **kwargs)
        writes.append((fid, ref, typ, result))
        return result

    async def append_command(adm, dev_id, base_id, cmd):
        adm.next_cmd += 1
        adm.config['FubModules']['10']['19'][str(adm.next_cmd)] = deepcopy(cmd)

    monkeypatch.setattr(mod, '_append_command', append_command)
    admin.add_element = flaky_add

    async def go():
        preview = await first.preview()
        await first.start(preview['fingerprint'], True)
        await first._task
        assert first.status()['status'] == 'failed', first.status()
        cursor = first.status()['done']
        assert cursor >= 3, first.status()
        # The full topology fingerprint is older than the partially written
        # current step, which must be reconciled without repeating past links.
        store.data['topology_digest'] = 'f' * 64
        restored = PushRebuild(runtime, store)
        await restored.initialize()
        await restored.resume()
        await restored._task
        assert restored.status()['status'] == 'completed', restored.status()
        # No duplicate COMEXIO physical elements or command references.
        for plan in admin.plans.values():
            refs = [(int(x['reference']['type']), int(x['reference']['ref_id']))
                    for x in plan['elements'].values()]
            assert len(refs) == len(set(refs)), refs
        assert restored.status()['done'] == restored.status()['total']

    asyncio.run(go())


def test_abort_when_completed_link_removed_before_resume(monkeypatch):
    from comexio_local import push_rebuild as mod
    admin = AdminFake(_config())
    runtime = FakeRuntime(admin, discover(admin.config))
    manager = PushRebuild(runtime, MemoryStore())
    original_add = admin.add_element
    fail = {'yes': True}

    async def flaky_add(fid, ref, typ, x, y, connection=None, **kwargs):
        if typ == 10 and fail['yes'] and any(admin.plans.values()):
            # Fail on second link after one has been completed.
            count = sum(len(p['connections']) for p in admin.plans.values())
            if count:
                fail['yes'] = False
                raise RebuildError('Simulated write error')
        return await original_add(fid, ref, typ, x, y, connection=connection, **kwargs)

    async def append_command(adm, dev_id, base_id, cmd):
        adm.next_cmd += 1
        adm.config['FubModules']['10']['19'][str(adm.next_cmd)] = deepcopy(cmd)

    monkeypatch.setattr(mod, '_append_command', append_command)
    admin.add_element = flaky_add

    async def go():
        preview = await manager.preview()
        await manager.start(preview['fingerprint'], True)
        await manager._task
        assert manager.status()['status'] == 'failed'
        assert manager.status()['completed_sources'] == 1
        for plan in admin.plans.values():
            plan['connections'].clear()  # unexpected alteration of a completed link
        with pytest.raises(RebuildError, match='Abgeschlossene Verknüpfung'):
            await manager.resume()
        assert manager.status()['status'] == 'failed'

    asyncio.run(go())


def test_read_plan_retries_transient_500_without_post_retry(monkeypatch):
    from comexio_local import admin_api
    events = []
    class DummyAdmin(ComexioAdmin):
        def __init__(self):
            super().__init__(None, 'comexio.invalid', 'user', 'pw')

        async def request_json(self, method, route, *, params=None, **kwargs):
            events.append((method, route))
            if len(events) < 3:
                raise AdminError('COMEXIO GET /admin/function_function_module/loadelements/: HTTP 500')
            return {'elements': {}, 'connections': {}}

    async def no_wait(seconds):
        events.append(('sleep', seconds))
    # Counting requests separate from backoff sleeps
    class Counting(DummyAdmin):
        attempts = 0
        async def request_json(self, method, route, *, params=None, **kwargs):
            self.attempts += 1
            if self.attempts < 3:
                raise AdminError('COMEXIO GET /admin/function_function_module/loadelements/: HTTP 500')
            return {'elements': {}, 'connections': {}}

    monkeypatch.setattr(admin_api.asyncio, 'sleep', no_wait)
    admin = Counting()
    assert asyncio.run(admin.read_plan(123)) == {'elements': {}, 'connections': {}}
    assert admin.attempts == 3
    assert events == [('sleep', 2.0), ('sleep', 4.0)]


def test_read_plan_does_not_retry_non_transient_errors(monkeypatch):
    from comexio_local import admin_api
    class BadAdmin(ComexioAdmin):
        def __init__(self):
            super().__init__(None, 'comexio.invalid', 'user', 'pw')
            self.calls = 0
        async def request_json(self, method, route, **kwargs):
            self.calls += 1
            raise AdminError('COMEXIO GET /admin/function_function_module/loadelements/: HTTP 401')
    admin = BadAdmin()
    with pytest.raises(AdminError, match='HTTP 401'):
        asyncio.run(admin.read_plan(123))
    assert admin.calls == 1


def test_real_size_30_sources_66_steps_resume_at_46_after_partial_47(monkeypatch):
    """Model the customer's 30 sources / 66 steps / GET500 at link 17 situation."""
    from comexio_local import push_rebuild as mod
    from comexio_local.discovery import Channel
    from comexio_local.push_rebuild import _make_steps
    channels = {}
    for index in range(15):
        ext = f'IO-Ext-{index // 4 + 1}'
        c = Channel(kind='light', key=f'io:{ext}/Q{index + 1}',
                    name=f'Licht {index + 1}', extension=ext,
                    identifier=f'Q{index + 1}', io_id=500 + index)
        channels[c.key] = c
    for index in range(15):
        c = Channel(kind='cover', key=f'cover:M{901 + index}',
                    name=f'Rollladen {index + 1}', marker_id=901 + index,
                    target_marker_id=800 + index, analog=True)
        channels[c.key] = c
    steps = _make_steps(channels)
    assert len(steps) == 66
    assert steps[46]['kind'] == 'link'
    admin = InstrumentedAdmin(_config())
    runtime = FakeRuntime(admin, channels)
    store = MemoryStore()
    first = PushRebuild(runtime, store)
    fail = {'yes': True}
    original_add = admin.add_element

    async def fail_during_17th_link(fid, ref, typ, x, y, connection=None, **kwargs):
        if typ == 10 and fail['yes']:
            count = sum(len(p['connections']) for p in admin.plans.values())
            if count == 16:
                fail['yes'] = False
                raise RebuildError('Simulated GET/POST failure midway through link 17')
        return await original_add(fid, ref, typ, x, y, connection=connection, **kwargs)

    async def append_command(adm, dev_id, base_id, cmd):
        adm.next_cmd += 1
        adm.config['FubModules']['10']['19'][str(adm.next_cmd)] = deepcopy(cmd)

    monkeypatch.setattr(mod, '_append_command', append_command)
    admin.add_element = fail_during_17th_link

    async def go():
        preview = await first.preview()
        assert preview['steps'] == 66
        await first.start(preview['fingerprint'], True)
        await first._task
        assert first.status()['status'] == 'failed', first.status()
        assert first.status()['done'] == 46, first.status()
        assert first.status()['completed_sources'] == 16
        state = store.data
        state['topology_digest'] = 'f' * 64  # stale (partial 47th write)
        restored = PushRebuild(runtime, store)
        await restored.initialize()
        await restored.resume()
        await restored._task
        assert restored.status()['status'] == 'completed', restored.status()
        assert restored.status()['done'] == 66
        assert restored.status()['completed_sources'] == 30
        assert len([entry for entry in admin.writes if entry[0] == 'class']) == 1
        assert len([entry for entry in admin.writes if entry[0] == 'plan']) == 5  # 4 IO groups + cover group
        # Even across 66 operations and a resume, no 2x66 full reads.
        assert admin.config_reads <= 10, admin.config_reads
        assert admin.plan_reads <= 14, admin.plan_reads
        for plan in admin.plans.values():
            refs = [(int(item['reference']['type']), int(item['reference']['ref_id']))
                    for item in plan['elements'].values()]
            assert len(refs) == len(set(refs))

    asyncio.run(go())
