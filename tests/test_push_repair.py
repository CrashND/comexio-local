"""Safety tests for the read-only preview and additive repair path."""
from __future__ import annotations

import asyncio
from copy import deepcopy
import pytest

from test_push_audit import _installed, ENTRY, PATH, BASE
from test_push_rebuild import AdminFake, FakeRuntime, MemoryStore, fake_dispatcher
from comexio_local.push_rebuild import PushRebuild, RebuildError
from comexio_local.push_repair import (
    RepairError, inspect_push_repair,
)
from comexio_local.push_labels import friendly_command_name, friendly_plan_name
from comexio_local.push_setup import _stable_groups


class FakeAdmin:
    def __init__(self, config, plans):
        self.config, self.plans = deepcopy(config), deepcopy(plans)
        self.writes = []

    async def read_config(self):
        return deepcopy(self.config)

    async def read_plan(self, fid):
        return deepcopy(self.plans[str(fid)])

    async def ensure_webio_commands_active(self, config, device_id, names, *, force_names=None, force=False):
        # Installed fixture carries active commands; repairing a link adds no
        # extra activation writes to existing Web-IO entries.
        commands = self.config['FubModules']['10'][str(device_id)]
        for name in names:
            matching = [v for v in commands.values() if v.get('Name') == name]
            assert len(matching) == 1
            if str(matching[0].get('Active')).lower() not in ('1', 'true'):
                self.writes.append(('webio_active', name))
                matching[0]['Active'] = '1'
        return await self.read_config()

    async def wire(self, fid, src, dst, analog):
        self.writes.append(('wire', fid, src, dst))
        plan = self.plans[str(fid)]
        idx = str(max(map(int, plan['connections']), default=0) + 1)
        plan['connections'][idx] = {'input': {'element': str(src)},
                                    'output': {'0': {'element': str(dst)}}}

    async def run_plan(self, fid):
        self.writes.append(('run', fid))


def test_friendly_names_are_source_distinct_and_canonical():
    cfg, plans, channels = _installed()
    names = [friendly_command_name(c) for c in channels.values() if c.kind in ('light', 'cover')]
    assert len(set(names)) == len(names)
    assert all(name.startswith('CL ') and ENTRY[:8].upper() not in name for name in names)
    groups = _stable_groups([c for c in channels.values() if c.kind in ('light', 'cover')])
    assert all(friendly_plan_name(signals, name).startswith('CL Push ') for name, signals in groups)


def test_read_only_preview_recognizes_existing_and_guided_rebuild():
    config, plans, channels = _installed()
    admin = FakeAdmin(config, plans)
    key = 'io:IO-Ext-2/Q1'
    async def go():
        report = await inspect_push_repair(admin, channels, ENTRY, PATH, BASE, [key])
        assert report.inspections[0].action == 'none'
        assert not report.needs_write
        renewal = await inspect_push_repair(admin, channels, ENTRY, PATH, BASE, [key], mode='rebuild')
        assert renewal.inspections[0].action == 'manual_rebuild'
        assert renewal.has_blocks
        assert admin.writes == []
    asyncio.run(go())


def test_missing_link_can_be_repaired_without_touching_other_sources(monkeypatch):
    from comexio_local import push_rebuild
    monkeypatch.setattr(push_rebuild, 'SETTLE_GAP', 0)
    config, plans, channels = _installed()
    key = 'io:IO-Ext-2/Q1'
    fid = next(fid for fid,p in plans.items()
               if any(e.get('reference',{}).get('type') == 1 for e in p['elements'].values()))
    plans[fid]['connections'].clear()
    admin = AdminFake(config, plans)
    manager = PushRebuild(FakeRuntime(admin, channels), MemoryStore())
    async def go():
        preview = await inspect_push_repair(admin, channels, ENTRY, PATH, BASE, [key])
        assert preview.inspections[0].action == 'restore_link'
        await manager.start_repair([key], mode='repair', fingerprint=preview.fingerprint, confirmed=True)
        await manager._task
        assert manager.status()['status'] == 'completed', manager.status()
        assert len([x for x in admin.writes if x[0] == 'wire']) == 1
        assert len([x for x in admin.writes if x[0] == 'activate']) == 1
        check = await inspect_push_repair(admin, channels, ENTRY, PATH, BASE, [key])
        assert check.inspections[0].action == 'none'
    asyncio.run(go())


def test_stale_fingerprint_aborts_before_any_write():
    config, plans, channels = _installed()
    key = 'io:IO-Ext-2/Q1'
    fid = next(fid for fid,p in plans.items()
               if any(e.get('reference',{}).get('type') == 1 for e in p['elements'].values()))
    plans[fid]['connections'].clear()
    admin = AdminFake(config, plans)
    manager = PushRebuild(FakeRuntime(admin, channels), MemoryStore())
    async def go():
        preview = await inspect_push_repair(admin, channels, ENTRY, PATH, BASE, [key])
        admin.config['WebDevices']['19']['Ip'] = '192.168.10.199:8123'
        with pytest.raises(RebuildError):
            await manager.start_repair([key], mode='repair', fingerprint=preview.fingerprint, confirmed=True)
        assert admin.writes == []
    asyncio.run(go())


def test_no_backup_never_modifies_comexio():
    config, plans, channels = _installed()
    admin = AdminFake(config, plans)
    manager = PushRebuild(FakeRuntime(admin, channels), MemoryStore())
    async def go():
        with pytest.raises(RebuildError, match='Sicherung'):
            await manager.start_repair(['io:IO-Ext-2/Q1'], mode='repair',
                                       fingerprint='0' * 64, confirmed=False)
        assert admin.writes == []
    asyncio.run(go())


def test_foreign_plan_is_blocked_not_overwritten():
    config, plans, channels = _installed()
    key = 'io:IO-Ext-2/Q1'
    fid = next(fid for fid,p in plans.items()
               if any(e.get('reference',{}).get('type') == 1 for e in p['elements'].values()))
    config['Fubs'][fid]['Comment'] = 'Not COMEXIO Local'
    admin = AdminFake(config, plans)
    manager = PushRebuild(FakeRuntime(admin, channels), MemoryStore())
    async def go():
        preview = await inspect_push_repair(admin, channels, ENTRY, PATH, BASE, [key])
        assert preview.has_blocks
        with pytest.raises(RebuildError):
            await manager.start_repair([key], mode='repair',
                                       fingerprint=preview.fingerprint, confirmed=True)
        assert not admin.writes
    asyncio.run(go())


def test_inactive_plan_is_real_repair_not_nothing_to_do(monkeypatch):
    from comexio_local import push_rebuild
    monkeypatch.setattr(push_rebuild, 'SETTLE_GAP', 0)
    config, plans, channels = _installed()
    next(meta for meta in config['Fubs'].values()
         if meta.get('Name', '').startswith('CL Push Rollläden'))['Active'] = False
    admin = AdminFake(config, plans)
    manager = PushRebuild(FakeRuntime(admin, channels), MemoryStore())
    key = next(c.key for c in channels.values() if c.kind == 'cover')
    async def go():
        preview = await inspect_push_repair(admin, channels, ENTRY, PATH, BASE, [key])
        assert preview.needs_write
        assert preview.inspections[0].action == 'activate_plan'
        await manager.start_repair([key], mode='repair', fingerprint=preview.fingerprint,
                                   confirmed=True)
        await manager._task
        assert manager.status()['status'] == 'completed', manager.status()
        assert len([w for w in admin.writes if w[0] == 'activate']) == 1
    asyncio.run(go())


def test_modified_lua_command_is_blocked_without_writing():
    config, plans, channels = _installed()
    key = 'io:IO-Ext-2/Q1'
    light_cmd = next(cmd for cmd in config['FubModules']['10']['19'].values() if 'IO-Ext-2/Q1' in cmd['Name'])
    light_cmd['Data'] = 'function data(a) return "wrong" end'
    admin = FakeAdmin(config, plans)
    async def go():
        preview = await inspect_push_repair(admin, channels, ENTRY, PATH, BASE, [key])
        assert preview.inspections[0].action == 'blocked'
        assert 'Data' in preview.inspections[0].detail
        assert not admin.writes
    asyncio.run(go())


def test_orphaned_webio_element_blocks_repair_in_preview():
    config, plans, channels = _installed()
    key = 'io:IO-Ext-2/Q1'
    fid = next(fid for fid, p in plans.items()
               if any(e.get('reference',{}).get('type') == 1 for e in p['elements'].values()))
    plans[fid]['elements']['999'] = {'reference': {'type': 10, 'ref_id': 99999}}
    admin = FakeAdmin(config, plans)
    async def go():
        preview = await inspect_push_repair(admin, channels, ENTRY, PATH, BASE, [key])
        assert preview.has_blocks
        assert 'verwaiste' in preview.inspections[0].detail
        assert not admin.writes
    asyncio.run(go())


def test_unknown_command_fields_are_not_assumed_verified():
    config, plans, channels = _installed()
    key = 'io:IO-Ext-2/Q1'
    light_cmd = next(cmd for cmd in config['FubModules']['10']['19'].values() if 'IO-Ext-2/Q1' in cmd['Name'])
    light_cmd.pop('Data')
    admin = FakeAdmin(config, plans)
    async def go():
        preview = await inspect_push_repair(admin, channels, ENTRY, PATH, BASE, [key])
        assert preview.inspections[0].action == 'none'  # topology exists, do not rewrite
        assert not admin.writes
    asyncio.run(go())
