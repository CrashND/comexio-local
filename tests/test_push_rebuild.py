"""Crash safety, checkpoint integrity and cleanup guards for v0.3.6."""
import asyncio
from copy import deepcopy
import sys
import types
from types import SimpleNamespace

import pytest
from comexio_local.discovery import discover
from comexio_local.push_rebuild import PushRebuild, RebuildError, WRITE_GAP
from test_push_audit import _installed, ENTRY, PATH, BASE
from test_discovery import _config


class MemoryStore:
    def __init__(self, data=None):
        self.data = deepcopy(data)
        self.saves = 0

    async def async_load(self):
        return deepcopy(self.data)

    async def async_save(self, value):
        self.saves += 1
        self.data = deepcopy(value)


class AdminFake:
    def __init__(self, config, plans=None):
        self.config = deepcopy(config)
        self.plans = deepcopy(plans or {})
        self.writes = []
        self.write_gap = 1.25
        self.next_eid = 1000
        self.element_names = []
        self.next_cmd = 200

    async def read_config(self):
        return deepcopy(self.config)

    async def read_plan(self, fid):
        return deepcopy(self.plans[str(fid)])

    async def ensure_webio_commands_active(self, config, device_id, names, *, force=False, force_names=None):
        # Test double for the separately verified COMEXIO POST operation.
        records = self.config['FubModules']['10'][str(device_id)]
        for name in names:
            matches = [record for record in records.values() if record['Name'] == name]
            assert len(matches) == 1
            if force or name in (force_names or set()) or str(matches[0].get('Active', '')).lower() not in ('1', 'true'):
                self.writes.append(('webio_active', device_id, name))
                matches[0]['Active'] = '1'
        return await self.read_config()

    async def read_plans(self, config, limit=None, *, strict=False):
        return {str(fid): deepcopy(self.plans.get(str(fid),
                {'elements': {}, 'connections': {}})) for fid in config['Fubs']}

    async def delete_owned_push_plan(self, fid, *, name, entry_id):
        from comexio_local.managed_resources import is_owned_plan
        assert is_owned_plan(self.config['Fubs'][str(fid)], entry_id, 'push')
        assert self.config['Fubs'][str(fid)]['Name'] == name
        self.writes.append(('delete_plan', fid, name))
        del self.config['Fubs'][str(fid)]
        self.plans.pop(str(fid), None)

    async def delete_owned_push_device(self, device_id, *, expected_name):
        assert self.config['WebDevices'][str(device_id)]['Name'] == expected_name
        self.writes.append(('delete_device', str(device_id)))
        del self.config['WebDevices'][str(device_id)]
        self.config['FubModules']['10'].pop(str(device_id), None)

    async def create_push_class(self, name, commands, target):
        self.writes.append(('class', name))
        self.config['WebDevices'] = {'19': {'Name': name, 'Ip': target, 'BaseId': 9}}
        self.config['FubModules']['10'] = {'19': {}}
        for cmd in commands:
            self.next_cmd += 1
            self.config['FubModules']['10']['19'][str(self.next_cmd)] = deepcopy(cmd)

    async def create_plan(self, name, comment):
        self.writes.append(('plan', name))
        fid = 100 + len(self.plans)
        self.config['Fubs'][str(fid)] = {'Name': name, 'Comment': comment, 'Active': False}
        self.plans[str(fid)] = {'elements': {}, 'connections': {}}
        return fid

    async def add_element(self, fid, ref, typ, x, y, connection=None, *, name=""):
        self.writes.append(('element', fid, ref, typ))
        self.element_names.append((fid, ref, typ, name))
        self.next_eid += 1
        eid = self.next_eid
        plan = self.plans[str(fid)]
        plan['elements'][str(eid)] = {'reference': {'type': typ, 'ref_id': ref}}
        if connection:
            for raw in connection.values():
                src = raw['input']['element']
                key = str(len(plan['connections']) + 1)
                plan['connections'][key] = {'input': {'element': src},
                                           'output': {'0': {'element': str(eid)}}}
        return eid

    async def wire(self, fid, src, dest, analog):
        self.writes.append(('wire', fid, src, dest, analog))
        plan = self.plans[str(fid)]
        key = str(len(plan['connections']) + 1)
        plan['connections'][key] = {
            'input': {'element': str(src)},
            'output': {'0': {'element': str(dest)}},
        }

    async def run_plan(self, fid):
        self.writes.append(('activate', fid))
        self.config['Fubs'][str(fid)]['Active'] = True


class FakeRuntime:
    def __init__(self, admin, channels):
        self.admin = admin
        self.channels = channels
        self.entry = SimpleNamespace(
            entry_id=ENTRY,
            data={'webhook_id': 'REDACTED-TEST-SECRET', 'push_base': BASE},
        )
        self.maintenance_lock = asyncio.Lock()
        self.state_signal = 'comexio_rebuild_updates'
        self.hass = SimpleNamespace(async_create_task=lambda coro: asyncio.create_task(coro))


@pytest.fixture(autouse=True)
def fake_dispatcher(monkeypatch):
    dispatch = types.ModuleType('homeassistant.helpers.dispatcher')
    dispatch.async_dispatcher_send = lambda *args: None
    monkeypatch.setitem(sys.modules, 'homeassistant', types.ModuleType('homeassistant'))
    monkeypatch.setitem(sys.modules, 'homeassistant.helpers', types.ModuleType('homeassistant.helpers'))
    monkeypatch.setitem(sys.modules, 'homeassistant.helpers.dispatcher', dispatch)


def test_confirmed_rebuild_deletes_only_own_plans_then_device_and_recreates(monkeypatch):
    """Offline mock of the real COMEXIO plan-first/device-second sequence."""
    from comexio_local import push_rebuild as mod
    config, plans, channels = _installed()
    admin = AdminFake(config, plans)
    manager = PushRebuild(FakeRuntime(admin, channels), MemoryStore())
    original_fubs = {k: deepcopy(v) for k, v in config['Fubs'].items()
                     if not str(v.get('Name', '')).startswith('CL Push')}

    async def fake_append(adm, device_id, base_id, cmd):
        adm.writes.append(('append', cmd['Name']))
        adm.next_cmd += 1
        adm.config['FubModules']['10'][str(device_id)][str(adm.next_cmd)] = deepcopy(cmd)

    monkeypatch.setattr(mod, '_append_command', fake_append)
    monkeypatch.setattr(mod, 'SETTLE_GAP', 0)

    async def go():
        await manager.initialize()
        preview = await manager.preview()
        assert preview['requires_cleanup'] is True
        assert 'Bestätigung' in preview['note']
        status = await manager.start(preview['fingerprint'], True, cleanup_confirmed=True)
        assert status['status'] == 'running'
        await manager._task
        final = manager.status()
        assert final['status'] == 'completed', final
        kinds = [action[0] for action in admin.writes]
        assert kinds.count('delete_plan') == len(plans)
        assert kinds.count('delete_device') == 1
        assert max(i for i, kind in enumerate(kinds) if kind == 'delete_plan') < kinds.index('delete_device')
        assert kinds.index('delete_device') < kinds.index('class')
        assert all(admin.config['Fubs'].get(fid) == old for fid, old in original_fubs.items())

    asyncio.run(go())


def test_requires_confirmation_and_fingerprint_before_any_write():
    admin = AdminFake(_config())
    manager = PushRebuild(FakeRuntime(admin, discover(admin.config)), MemoryStore())

    async def go():
        preview = await manager.preview()
        with pytest.raises(RebuildError, match='Sicherung'):
            await manager.start(preview['fingerprint'], False)
        with pytest.raises(RebuildError, match='Vorschau'):
            await manager.start('0' * 64, True)
        assert admin.writes == []

    asyncio.run(go())


def test_restart_does_not_resume_running_job():
    admin = AdminFake(_config())
    channels = discover(admin.config)
    store = MemoryStore()
    manager = PushRebuild(FakeRuntime(admin, channels), store)

    async def go():
        preview = await manager.preview()
        await manager.start(preview['fingerprint'], True)
        await manager.stop_for_unload()
        # May have created some resources but never automatically resumes on boot.
        restored = PushRebuild(FakeRuntime(admin, channels), store)
        await restored.initialize()
        assert restored.status()['status'] == 'interrupted'
        assert restored._task is None

    asyncio.run(go())


def test_stale_checkpoint_blocks_resume_after_out_of_band_change():
    admin = AdminFake(_config())
    channels = discover(admin.config)
    manager = PushRebuild(FakeRuntime(admin, channels), MemoryStore())

    async def go():
        preview = await manager.preview()
        await manager.start(preview['fingerprint'], True)
        await manager.pause()
        await manager._task
        assert manager.status()['status'] == 'paused'
        admin.config['WebDevices'] = {'19': {'Name': 'CL Push Home Assistant', 'Ip': '192.168.10.88', 'BaseId': 9}}
        with pytest.raises(RebuildError, match='Topologie'):
            await manager.resume()

    asyncio.run(go())


def test_single_job_completes_with_paced_writes_and_no_unowned_changes(monkeypatch):
    from comexio_local import push_rebuild as mod
    admin = AdminFake(_config())
    original_fubs = deepcopy(admin.config['Fubs'])
    channels = discover(admin.config)
    manager = PushRebuild(FakeRuntime(admin, channels), MemoryStore())

    async def append_command(admin, device_id, base_id, cmd):
        admin.writes.append(('append', cmd['Name'], admin.write_gap))
        admin.next_cmd += 1
        admin.config['FubModules']['10']['19'][str(admin.next_cmd)] = deepcopy(cmd)

    monkeypatch.setattr(mod, '_append_command', append_command)
    monkeypatch.setattr(mod, 'SETTLE_GAP', 0)
    async def go():
        preview = await manager.preview()
        status = await manager.start(preview['fingerprint'], True)
        assert status['status'] == 'running'
        await manager._task
        final = manager.status()
        assert final['status'] == 'completed', final
        assert final['done'] == final['total']
        assert admin.write_gap == 1.25  # restored
        assert original_fubs.items() <= admin.config['Fubs'].items()
        assert [x for x in admin.writes if x[0] == 'append'][0][2] >= WRITE_GAP
        assert ('class', 'CL Push Home Assistant') in admin.writes
        assert any(x[0] == 'plan' and x[1].startswith('CL Push ') for x in admin.writes)

    asyncio.run(go())


def test_unexpected_legacy_object_blocks_automatic_rebuild():
    config, plans, channels = _installed()
    config['FubModules']['10']['19']['999'] = {'Name': 'UNRELATED COMMAND'}
    manager = PushRebuild(FakeRuntime(AdminFake(config, plans), channels), MemoryStore())

    async def go():
        with pytest.raises(RebuildError, match='Fremde'):
            await manager.preview()

    asyncio.run(go())


def test_pause_resume_finishes_current_step_and_keeps_checkpoint(monkeypatch):
    from comexio_local import push_rebuild as mod
    admin = AdminFake(_config())
    manager = PushRebuild(FakeRuntime(admin, discover(admin.config)), MemoryStore())
    entered, continue_step = asyncio.Event(), asyncio.Event()
    original_create = admin.create_push_class

    async def wait_during_write(*args):
        entered.set()
        await continue_step.wait()
        await original_create(*args)

    async def append_command(admin, device_id, base_id, cmd):
        admin.next_cmd += 1
        admin.config['FubModules']['10']['19'][str(admin.next_cmd)] = deepcopy(cmd)

    admin.create_push_class = wait_during_write
    monkeypatch.setattr(mod, '_append_command', append_command)
    monkeypatch.setattr(mod, 'SETTLE_GAP', 0)

    async def go():
        preview = await manager.preview()
        await manager.start(preview['fingerprint'], True)
        await entered.wait()
        await manager.pause()
        continue_step.set()
        await manager._task
        paused = manager.status()
        assert paused['status'] == 'paused'
        assert paused['done'] == 1  # finish the step first
        assert manager._store.saves >= 3
        await manager.resume()
        await manager._task
        assert manager.status()['status'] == 'completed'

    asyncio.run(go())


def test_admin_write_slot_enforces_two_second_spacing():
    from comexio_local.admin_api import ComexioAdmin
    import time
    admin = ComexioAdmin(None, '192.168.10.254', 'demo', 'dummy')
    admin.write_gap = WRITE_GAP

    async def go():
        admin._last_write = time.monotonic() - WRITE_GAP
        async with admin._lock:
            await admin._wait_write_slot()
            first = time.monotonic()
            await admin._wait_write_slot()
            second = time.monotonic()
        assert second - first >= WRITE_GAP - 0.02

    asyncio.run(go())


def test_v036_failed_empty_rebuild_resumes_after_fix_without_cleanup(monkeypatch):
    """A real 0/66-style failed checkpoint can resume after the upgrade."""
    from comexio_local import push_rebuild as mod
    admin = AdminFake(_config())
    channels = discover(admin.config)
    store = MemoryStore()
    runtime = FakeRuntime(admin, channels)
    manager = PushRebuild(runtime, store)
    original_create = admin.create_push_class

    async def fail_first_create(*args):
        raise RebuildError('COMEXIO refused to create the Web-IO class')

    async def append_command(adm, dev_id, base_id, cmd):
        adm.next_cmd += 1
        adm.config['FubModules']['10']['19'][str(adm.next_cmd)] = deepcopy(cmd)

    monkeypatch.setattr(mod, '_append_command', append_command)
    monkeypatch.setattr(mod, 'SETTLE_GAP', 0)

    async def go():
        admin.create_push_class = fail_first_create
        preview = await manager.preview()
        await manager.start(preview['fingerprint'], True)
        await manager._task
        assert manager.status()['status'] == 'failed'
        assert manager.status()['done'] == 0
        assert admin.writes == []
        restored = PushRebuild(runtime, store)
        await restored.initialize()
        admin.create_push_class = original_create
        await restored.resume()
        await restored._task
        assert restored.status()['status'] == 'completed'
        assert ('class', 'CL Push Home Assistant') in admin.writes
    asyncio.run(go())


def test_preview_note_matches_already_clean_configuration():
    """Don't tell users to delete CL resources that have already been removed."""
    admin = AdminFake(_config())
    manager = PushRebuild(FakeRuntime(admin, discover(admin.config)), MemoryStore())

    async def go():
        preview = await manager.preview()
        assert preview['requires_cleanup'] is False
        assert preview['commands'] == 0 and preview['plans'] == 0
        assert 'Keine verwalteten CL-Push-Pläne' in preview['note']
        assert 'müssen' not in preview['note']

    asyncio.run(go())
