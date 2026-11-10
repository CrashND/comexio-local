"""v0.4.3 regressions: 31 sources, 17 links, inactive plans, crash recovery.

These are deterministic simulated COMEXIO data, NOT a firmware 11.1.5 test.
"""
from __future__ import annotations

import asyncio
from copy import deepcopy

from comexio_local.admin_api import AdminError
from comexio_local.discovery import Channel
from comexio_local.push_audit import audit_config
from comexio_local.push_rebuild import PushRebuild, _make_steps
from comexio_local.push_repair import inspect_push_repair
from comexio_local.push_setup import push_sources, _stable_groups
from comexio_local.push_labels import friendly_plan_name, friendly_command_name
from test_discovery import _config
from test_push_rebuild import AdminFake, FakeRuntime, MemoryStore, fake_dispatcher
from test_push_audit import ENTRY, PATH, BASE


def real_size_channels():
    channels = {}
    for index, marker in enumerate(range(69, 98, 2)):
        signal = Channel(kind='cover', name=f'Rollladen {index + 1}',
                         key=f'cover:M{marker}', marker_id=marker,
                         target_marker_id=marker - 1, analog=True)
        channels[signal.key] = signal
    groups = {
        'IO-Ext-1': (1, 4, 7), 'IO-Ext-2': tuple(range(1, 10)),
        'IO-Ext-3': (7,), 'IO-Server-1': (1, 2, 3),
    }
    io_id = 3000
    for device, indices in groups.items():
        for port in indices:
            io_id += 1
            signal = Channel(kind='light', name=f'Licht {device} Q{port}',
                             key=f'io:{device}/Q{port}', extension=device,
                             identifier=f'Q{port}', io_id=io_id)
            channels[signal.key] = signal
    assert len(channels) == 31
    assert len(_stable_groups(push_sources(channels))) == 7
    assert len(_make_steps(channels)) == 70
    return channels


def remove_plan_signal(admin, plan_id, signal):
    """Simulate missing pair; no need to invent COMEXIO element/command IDs."""
    plan = admin.plans[str(plan_id)]
    src_kind = 2 if signal.kind == 'cover' else 1
    src_ref = signal.marker_id if signal.kind == 'cover' else signal.io_id
    sources = [key for key, record in plan['elements'].items()
               if record.get('reference') == {'type': src_kind, 'ref_id': src_ref}]
    assert len(sources) == 1
    src_id = sources[0]
    connections = [key for key, conn in plan['connections'].items()
                   if conn.get('input', {}).get('element') == src_id]
    assert len(connections) == 1
    out_id = plan['connections'][connections[0]]['output']['0']['element']
    del plan['connections'][connections[0]]
    del plan['elements'][src_id]
    del plan['elements'][out_id]


class FailOnceWireAdmin(AdminFake):
    def __init__(self, config, plans):
        super().__init__(config, plans)
        # A firmware restart must not reset its ID generator. Rebuild the
        # fake's allocators from the saved COMEXIO inventory.
        self.next_eid = max([1000] + [int(eid) for p in self.plans.values()
                                      for eid in p['elements']])
        self.next_cmd = max([200] + [int(cid) for cmd in
                             (self.config.get('FubModules') or {}).get('10', {}).values()
                             for cid in cmd])
        self.wire_attempts = 0

    async def wire(self, fid, src, dest, analog):
        self.wire_attempts += 1
        if self.wire_attempts == 2:
            self.writes.append(('wire_failed', fid, src, dest))
            raise AdminError('Simulierter Kommunikationsabbruch nach Bausteinanlage')
        return await super().wire(fid, src, dest, analog)


def make_partial_17(admin, channels):
    """Exactly the reported 31/17/4 scenario, all original room plans intact."""
    for bucket, group in _stable_groups(push_sources(channels)):
        name = friendly_plan_name(group, bucket)
        fid = next(fid for fid, meta in admin.config['Fubs'].items()
                   if meta['Name'] == name)
        if name.startswith('CL Push Rollläden'):
            admin.config['Fubs'][fid]['Active'] = False
        elif name.startswith('CL Push IO-Ext-1'):
            unlinked = [c for c in group if c.identifier == 'Q7']
            assert len(unlinked) == 1
            remove_plan_signal(admin, fid, unlinked[0])
            admin.config['Fubs'][fid]['Active'] = False
        else:
            del admin.config['Fubs'][fid]
            del admin.plans[fid]
    report = audit_config(admin.config, admin.plans, channels, ENTRY, PATH, BASE)
    assert (report.sources, report.linked, report.plans_inspected) == (31, 17, 4)
    assert len(report.missing_links) == 14
    assert len([err for err in report.errors if 'nicht aktiv' in err]) == 4
    assert not report.missing_commands
    return report


async def prepare_partial(monkeypatch):
    from comexio_local import push_rebuild
    channels = real_size_channels()
    config = _config()
    admin = AdminFake(config)
    manager = PushRebuild(FakeRuntime(admin, channels), MemoryStore())
    async def fake_append(adm, device_id, base_id, cmd):
        adm.writes.append(('append', cmd['Name']))
        adm.next_cmd += 1
        adm.config['FubModules']['10'][str(device_id)][str(adm.next_cmd)] = deepcopy(cmd)
    monkeypatch.setattr(push_rebuild, '_append_command', fake_append)
    monkeypatch.setattr(push_rebuild, 'SETTLE_GAP', 0)
    preview = await manager.preview()
    assert not preview['requires_cleanup']
    await manager.start(preview['fingerprint'], True)
    await manager._task
    assert manager.status()['status'] == 'completed', manager.status()
    make_partial_17(admin, channels)
    return admin, channels


def test_all_31_repaired_by_unified_background_worker_without_recreating_links(monkeypatch):
    async def go():
        admin, channels = await prepare_partial(monkeypatch)
        preexisting = deepcopy(admin.plans)
        admin.writes.clear()
        keys = [c.key for c in push_sources(channels)]
        preview = await inspect_push_repair(admin, channels, ENTRY, PATH, BASE, keys)
        assert preview.needs_write and not preview.has_blocks
        manager = PushRebuild(FakeRuntime(admin, channels), MemoryStore())
        await manager.start_repair(keys, mode='repair', fingerprint=preview.fingerprint,
                                   confirmed=True)
        assert manager.status()['status'] == 'running'
        await manager._task
        assert manager.status()['status'] == 'completed', manager.status()
        report = audit_config(admin.config, admin.plans, channels, ENTRY, PATH, BASE)
        assert (report.sources, report.linked, report.plans_inspected) == (31, 31, 7)
        assert not (report.missing_commands or report.missing_links or report.errors)
        assert len([x for x in admin.writes if x[0] == 'wire']) == 14
        assert len([x for x in admin.writes if x[0] == 'activate']) == 7
        assert not any(x[0] in ('delete_plan', 'delete_device', 'class', 'append')
                       for x in admin.writes)
        # The completed original cover connections stayed byte-for-byte intact.
        for fid, old in preexisting.items():
            if admin.config['Fubs'].get(fid, {}).get('Name', '').startswith('CL Push Rollläden'):
                assert admin.plans[fid] == old
    asyncio.run(go())


def test_crash_with_dangling_elements_resumes_after_verified_checkpoint(monkeypatch):
    async def go():
        admin, channels = await prepare_partial(monkeypatch)
        admin = FailOnceWireAdmin(admin.config, admin.plans)
        admin.writes.clear()
        store = MemoryStore()
        keys = [c.key for c in push_sources(channels)]
        preview = await inspect_push_repair(admin, channels, ENTRY, PATH, BASE, keys)
        manager = PushRebuild(FakeRuntime(admin, channels), store)
        await manager.start_repair(keys, mode='repair', fingerprint=preview.fingerprint,
                                   confirmed=True)
        await manager._task
        assert manager.status()['status'] == 'failed', manager.status()
        assert any(w[0] == 'wire_failed' for w in admin.writes)
        # The fully finished IO-Ext-1 group is activated before the later
        # IO-Ext-2 failure. Other original groups may still be inactive.
        activated = [meta for meta in admin.config['Fubs'].values()
                     if meta.get('Name') == 'CL Push IO-Ext-1 Q1-Q18']
        assert len(activated) == 1 and activated[0]['Active'] is True
        resumed = PushRebuild(FakeRuntime(admin, channels), store)
        await resumed.initialize()
        assert resumed.status()['status'] == 'failed'
        await resumed.resume()
        await resumed._task
        assert resumed.status()['status'] == 'completed', resumed.status()
        report = audit_config(admin.config, admin.plans, channels, ENTRY, PATH, BASE)
        assert report.linked == report.sources == 31
        assert not report.errors
        for plan in admin.plans.values():
            refs = [(int(x['reference']['type']), int(x['reference']['ref_id']))
                    for x in plan['elements'].values()]
            assert len(refs) == len(set(refs)), 'No repeated element/POST after resume'
        assert len([x for x in admin.writes if x[0] == 'wire']) == 14
    asyncio.run(go())


def test_status_never_succeeds_if_plan_activation_readback_is_false(monkeypatch):
    async def go():
        admin, channels = await prepare_partial(monkeypatch)
        class UnconfirmedActivation(AdminFake):
            async def run_plan(self, fid):
                self.writes.append(('activate_ignored', fid))
        broken = UnconfirmedActivation(admin.config, admin.plans)
        keys = [c.key for c in push_sources(channels)]
        preview = await inspect_push_repair(broken, channels, ENTRY, PATH, BASE, keys)
        manager = PushRebuild(FakeRuntime(broken, channels), MemoryStore())
        await manager.start_repair(keys, mode='repair', fingerprint=preview.fingerprint,
                                   confirmed=True)
        await manager._task
        assert manager.status()['status'] == 'failed'
        assert 'inaktiv' in manager.status()['message']
        assert not any(w[0] == 'delete_plan' for w in broken.writes)
    asyncio.run(go())


def test_selected_repair_cannot_activate_incomplete_unselected_group():
    """A one-source selection must never silently rewrite other missing channels."""
    from test_push_audit import _installed
    config, plans, channels = _installed()
    # Both cover channels share a plan? Use a two-light group constructed below.
    signals = [Channel(kind='light', name=f'Test {i}',
                       key=f'io:IO-Ext-1/Q{i}', extension='IO-Ext-1',
                       identifier=f'Q{i}', io_id=900+i)
               for i in (1, 2)]
    config = _config()
    channels = {s.key: s for s in signals}
    admin = AdminFake(config)
    async def go():
        # No device, no plan, but user selects only Q1. The other source in
        # that same target group is missing and has not been authorized.
        preview = await inspect_push_repair(admin, channels, ENTRY, PATH, BASE,
                                            [signals[0].key])
        assert preview.has_blocks
        assert preview.inspections[0].action == 'blocked'
        assert admin.writes == []
    asyncio.run(go())


def test_inactive_webio_command_is_not_considered_nothing_to_do(monkeypatch):
    from test_push_audit import _installed
    from comexio_local import push_rebuild
    monkeypatch.setattr(push_rebuild, 'SETTLE_GAP', 0)
    config, plans, channels = _installed()
    target = next(c for c in push_sources(channels) if c.kind == 'light')
    cmd = next(c for c in config['FubModules']['10']['19'].values()
               if c['Name'] == friendly_command_name(target))
    cmd['Active'] = '0'
    admin = AdminFake(config, plans)
    manager = PushRebuild(FakeRuntime(admin, channels), MemoryStore())
    async def go():
        preview = await inspect_push_repair(admin, channels, ENTRY, PATH, BASE, [target.key])
        assert preview.inspections[0].action == 'activate_command'
        await manager.start_repair([target.key], mode='repair',
                                   fingerprint=preview.fingerprint, confirmed=True)
        await manager._task
        assert manager.status()['status'] == 'completed', manager.status()
        assert ('webio_active', '19', friendly_command_name(target)) in admin.writes
    asyncio.run(go())


def test_selected_group_is_partial_not_a_global_success(monkeypatch):
    async def go():
        admin, channels = await prepare_partial(monkeypatch)
        # Complete only IO-Ext-1; other IO groups still have no plans.
        selected = [c.key for c in push_sources(channels)
                    if c.extension == 'IO-Ext-1']
        preview = await inspect_push_repair(admin, channels, ENTRY, PATH, BASE, selected)
        assert not preview.has_blocks
        manager = PushRebuild(FakeRuntime(admin, channels), MemoryStore())
        await manager.start_repair(selected, mode='repair', fingerprint=preview.fingerprint,
                                   confirmed=True)
        await manager._task
        status = manager.status()
        assert status['status'] == 'completed_partial', status
        assert status['verification']['linked'] == 18
        assert len(status['verification']['missing_links']) == 13
    asyncio.run(go())


def test_no_auto_resume_after_restart_of_running_repair(monkeypatch):
    async def go():
        admin, channels = await prepare_partial(monkeypatch)
        store = MemoryStore()
        selected = [c.key for c in push_sources(channels)]
        preview = await inspect_push_repair(admin, channels, ENTRY, PATH, BASE, selected)
        manager = PushRebuild(FakeRuntime(admin, channels), store)
        await manager.start_repair(selected, mode='repair', fingerprint=preview.fingerprint,
                                   confirmed=True)
        await manager.stop_for_unload()
        restarted = PushRebuild(FakeRuntime(admin, channels), store)
        await restarted.initialize()
        assert restarted.status()['status'] == 'interrupted'
        assert restarted._task is None
    asyncio.run(go())


def test_changed_completed_link_blocks_repair_resume(monkeypatch):
    async def go():
        admin, channels = await prepare_partial(monkeypatch)
        admin = FailOnceWireAdmin(admin.config, admin.plans)
        keys = [c.key for c in push_sources(channels)]
        preview = await inspect_push_repair(admin, channels, ENTRY, PATH, BASE, keys)
        store = MemoryStore()
        manager = PushRebuild(FakeRuntime(admin, channels), store)
        await manager.start_repair(keys, mode='repair', fingerprint=preview.fingerprint,
                                   confirmed=True)
        await manager._task
        assert manager.status()['status'] == 'failed'
        # Remove the previously completed connection from Q1 in IO-Ext-1.
        signal = next(c for c in channels.values()
                      if c.key == 'io:IO-Ext-1/Q1')
        fid = next(fid for fid, meta in admin.config['Fubs'].items()
                   if meta.get('Name') == 'CL Push IO-Ext-1 Q1-Q18')
        plan = admin.plans[fid]
        src = next(eid for eid, el in plan['elements'].items()
                   if el.get('reference') == {'type': 1, 'ref_id': signal.io_id})
        conn_id = next(cid for cid, c in plan['connections'].items()
                       if c.get('input', {}).get('element') == src)
        del plan['connections'][conn_id]
        resumed = PushRebuild(FakeRuntime(admin, channels), store)
        await resumed.initialize()
        writes_before = list(admin.writes)
        try:
            await resumed.resume()
        except AdminError as err:
            assert ('Verbindung fehlt' in str(err) or
                    'Logikplan enthält' in str(err) or
                    'Push-Verbindung' in str(err))
        else:
            raise AssertionError('Modified completed graph must block resume')
        assert admin.writes == writes_before
    asyncio.run(go())
