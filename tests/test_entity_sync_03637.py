"""Safety regressions for explicit, registry-scoped COMEXIO Local sync."""
from __future__ import annotations

import asyncio
import sys
import types
from dataclasses import replace
from types import SimpleNamespace

import pytest

from comexio_local.discovery import Channel
from comexio_local.discovery_sync import compare_catalog
from comexio_local.entity_sync import (
    build_entity_plan, entity_domain, physical_key, saved_user_choices,
    unique_id_for, verify_registry_candidates,
)

ENTRY = SimpleNamespace(entry_id='entry-01', unique_id='comexio_local:device', options={})


def source(key='io:IO-Server-1/Q4', kind='relay', name='Roll Kind 2 H X1/5'):
    return Channel(key=key, kind=kind, name=name, extension='IO-Server-1',
                   identifier='Q4', io_id=4)


def row(key='io:IO-Server-1/Q4', domain='binary_sensor', *, name=None,
        area='buero', entry_id=ENTRY.entry_id, platform='comexio_local', eid=None):
    return SimpleNamespace(entity_id=eid or f'{domain}.kind_2_rool_h_x1_5',
                           unique_id=unique_id_for(ENTRY, key), domain=domain,
                           config_entry_id=entry_id, platform=platform,
                           area_id=area, name=name, disabled_by=None, hidden_by=None)


def plan(old, new, rows, options=None, *, foreign=None):
    return build_entity_plan(ENTRY, old, new, options or {}, rows, foreign_ids=foreign)


def test_motor_correction_removes_old_own_binary_sensor_but_not_foreign():
    old = {'io:IO-Server-1/Q4': source(kind='relay', name='Kind 2 Rool H X1/5')}
    new = {'io:IO-Server-1/Q4': source(kind='motor')}
    own = row(name='Von Nutzer angepasst')
    foreign = row(entry_id='other-instance', eid='binary_sensor.foreign')
    p = plan(old, new, [own, foreign])
    assert p['requires_confirmation']
    assert p['counts']['type_changed'] == 1
    assert len(p['registry_removals']) == 1
    assert p['registry_removals'][0]['entity_id'] == own.entity_id
    assert p['registry_removals'][0]['replacement_domain'] is None
    assert not saved_user_choices(p['registry_removals'], new)


def test_domain_change_preserves_user_area_and_custom_name():
    key='io:IO-Ext-1/Q2'
    old={key:source(key=key,kind='relay')}
    new={key:replace(old[key],kind='light')}
    p=plan(old,new,[row(key=key,name='Mein Licht',area='wohnzimmer')])
    assert p['registry_removals'][0]['replacement_domain']=='light'
    assert saved_user_choices(p['registry_removals'],new)=={
        key:{'name':'Mein Licht','area_id':'wohnzimmer','icon':None,'labels':[]}}


def test_same_domain_class_change_does_not_delete_registry():
    key='io:IO-Ext-1/I1'
    old={key:source(key=key,kind='relay')}
    new={key:replace(old[key],kind='binary_input',input_mode='taster')}
    p=plan(old,new,[row(key=key)])
    assert p['counts']['type_changed']==1
    assert p['registry_removals']==[]
    assert p['reload_required']


def test_stale_owned_entity_removed_even_when_live_catalog_is_unchanged():
    key='io:IO-Ext-3/Q12'
    channels={'io:IO-Server-1/Q4':source(kind='motor')}
    p=plan(channels,channels,[row(key=key),row(key='cover:M85', domain='cover')])
    assert len(p['registry_removals'])==2
    assert not p['changes']
    assert p['requires_confirmation']


def test_diagnostics_and_unrelated_entity_registry_entries_not_deleted():
    channels={'io:IO-Server-1/Q4': source(kind='motor')}
    rows=[row(key='another:diagnostic',eid='sensor.comexio_diagnostics'),
          row(key='io:IO-Server-1/Q4', platform='another_integration',eid='binary_sensor.other'),
          row(key='io:IO-Server-1/Q4',entry_id='another-entry',eid='binary_sensor.other_2')]
    assert plan(channels,channels,rows)['registry_removals']==[]
    assert physical_key(ENTRY,'other-platform:io:IO-Server-1/Q4') is None
    assert entity_domain('motor') is None


def test_registry_changes_and_catalog_changes_invalidate_confirmed_fingerprint():
    key='io:IO-Server-1/Q4'; old={key:source(kind='relay')}; new={key:source(kind='motor')}
    p=plan(old,new,[row(name='Alt')])
    assert p['fingerprint']!=plan(old,new,[row(name='Neu')])['fingerprint']
    assert p['fingerprint']!=plan(old,new,[],{'input_modes':{key:'taster'}})['fingerprint']
    assert p['fingerprint']!=plan(old,{key:replace(new[key],io_id=99)},[row(name='Alt')])['fingerprint']
    assert p['fingerprint']==plan(old,new,[row(name='Alt')])['fingerprint']


def test_foreign_registry_collision_blocks_mutations():
    key='io:IO-Server-1/Q4'; new={key:source(kind='light')}
    p=plan({},new,[],foreign={('light',unique_id_for(ENTRY,key)):'another-entry'})
    assert any('Fremder Registry-Eintrag' in x for x in p['blockers'])


def test_preflight_fails_closed_when_name_or_owner_changed():
    key='io:IO-Ext-1/Q1'; rec=row(key=key,name='Original')
    p=plan({key:source(key=key)},{},[rec])
    class Registry:
        def __init__(self,v):self.v=v
        def async_get(self,k):return self.v
    verify_registry_candidates(Registry(rec), ENTRY, p['registry_removals'])
    for changed in (row(key=key,name='Changed'), row(key=key,entry_id='other'), None):
        with pytest.raises(ValueError,match='Registry-Eintrag'):
            verify_registry_candidates(Registry(changed),ENTRY,p['registry_removals'])


def test_catalog_metadata_updates_are_visible_and_fingerprinted():
    key='io:IO-Ext-3/Q1'; ch=source(key=key,kind='light')
    new={key:replace(ch,io_id=111)}
    report=compare_catalog({key:ch},new,{})
    assert report['counts']['updated']==1


def test_strict_plan_reader_fail_closed_on_partial_or_unexpected_plan():
    from comexio_local.admin_api import ComexioAdmin, AdminError
    class Fake(ComexioAdmin):
        def __init__(self, answer):
            super().__init__(None,'comexio.test','u','p')
            self.answer=answer
            self.seen=[]
        async def request_json(self, method, route, *, params=None, **kwargs):
            self.seen.append(params['fubid'])
            if params['fubid']== '51' and isinstance(self.answer, Exception):
                raise self.answer
            return self.answer
    config={'Fubs':{'50':{},'51':{},'52':{}}}
    for invalid in (AdminError('GET 500'),{'unexpected':True}):
        with pytest.raises(AdminError,match='nicht lesbar'):
            asyncio.run(Fake(invalid).read_plans(config,limit=None,strict=True))
    fake=Fake({'elements':{}})
    assert len(asyncio.run(fake.read_plans(config,limit=None,strict=True)))==3
    assert fake.seen==['50','51','52']
    with pytest.raises(AdminError,match='abgeschnitten'):
        asyncio.run(fake.read_plans(config,limit=2,strict=True))


def test_registry_removal_has_no_automatic_action_on_discovery():
    # Pure planning must never expose a callable write or mutate its input.
    key='io:IO-Ext-1/Q2'; known={key:source(key=key,kind='relay')}
    entries=[row(key=key)]
    before=dict(known)
    p=plan(known,{},entries)
    assert known==before and entries[0].entity_id=='binary_sensor.kind_2_rool_h_x1_5'
    assert 'registry_removals' in p and 'fingerprint' in p


def test_runtime_sync_is_a_single_validated_read_and_scoped_registry_commit(monkeypatch):
    import importlib
    from comexio_local.discovery import discover

    reg_module=types.ModuleType('homeassistant.helpers.entity_registry')
    class FakeRegistry:
        def __init__(self):
            self.items={}
            self.removed=[]
        def async_get(self,eid):return self.items.get(eid)
        def async_get_entity_id(self,domain,platform,uid):
            return next((r.entity_id for r in self.items.values()
                         if (r.domain,r.platform,r.unique_id)==(domain,platform,uid)),None)
        def async_remove(self,eid):
            self.removed.append(eid)
            del self.items[eid]
    registry=FakeRegistry()
    previous=source(kind='relay',name='Kind 2 Rool H X1/5')
    old=row(name='Mein alter Sensor')
    registry.items[old.entity_id]=old
    registry.items['binary_sensor.fremd']=row(
        key='io:IO-Server-1/Q4',entry_id='another-entry',eid='binary_sensor.fremd')
    reg_module.async_get=lambda _hass:registry
    reg_module.async_entries_for_config_entry=lambda r,eid:[v for v in r.items.values()
                                                            if v.config_entry_id==eid]
    dispatcher=types.ModuleType('homeassistant.helpers.dispatcher')
    dispatcher.async_dispatcher_send=lambda *args:None
    monkeypatch.setitem(sys.modules,'homeassistant',types.ModuleType('homeassistant'))
    monkeypatch.setitem(sys.modules,'homeassistant.helpers',types.ModuleType('homeassistant.helpers'))
    monkeypatch.setitem(sys.modules,'homeassistant.helpers.entity_registry',reg_module)
    monkeypatch.setitem(sys.modules,'homeassistant.helpers.dispatcher',dispatcher)
    module=importlib.import_module('comexio_local.runtime')

    class FakeAdmin:
        def __init__(self):self.calls=0
        async def read_config(self):
            self.calls+=1
            return {'FubModules':{'1':{'1':{'extension':{'Name':'IO-Server-1'},
                'inoutput':{'4':{'Identifier':'Q4','Id':4,'Description':
                                'Roll Kind 2 H X1/5','Active':True}}}},'2':{}},
                'Fubs':{}}
        async def read_plans(self,config,limit=None,strict=False):
            assert strict and limit is None
            return {}

    reload_calls=[]
    config=SimpleNamespace(async_update_entry=lambda _entry,options:None,
                           async_schedule_reload=lambda eid:reload_calls.append(eid))
    hass=SimpleNamespace(config_entries=config)
    entry=SimpleNamespace(entry_id=ENTRY.entry_id,unique_id=ENTRY.unique_id,options={})
    admin=FakeAdmin()
    rt=module.Runtime(hass,entry,admin,None)
    rt.channels={previous.key:previous}

    async def run():
        preview=await rt.preview_sync()
        assert preview['counts']['type_changed']==1
        assert [r['entity_id'] for r in preview['registry_removals']]==[old.entity_id]
        assert not registry.removed and not reload_calls
        assert admin.calls==1
        applied=await rt.apply_sync(preview['fingerprint'])
        assert applied['fingerprint']==preview['fingerprint']
        assert admin.calls==2  # exactly one COMEXIO configuration read per step
        assert registry.removed==[old.entity_id]
        assert reload_calls==[entry.entry_id]
        assert 'binary_sensor.fremd' in registry.items
    asyncio.run(run())


def test_runtime_sync_refuses_stale_registry_before_any_remove(monkeypatch):
    import importlib
    reg_module=types.ModuleType('homeassistant.helpers.entity_registry')
    class Registry:
        def __init__(self):self.rows=[row(name='Original')];self.removed=[]
        def async_get(self,eid):return next((r for r in self.rows if r.entity_id==eid),None)
        def async_get_entity_id(self,*args):return None
        def async_remove(self,eid):self.removed.append(eid)
    reg=Registry()
    reg_module.async_get=lambda _hass:reg
    reg_module.async_entries_for_config_entry=lambda *_args:list(reg.rows)
    dispatcher=types.ModuleType('homeassistant.helpers.dispatcher')
    dispatcher.async_dispatcher_send=lambda *args:None
    monkeypatch.setitem(sys.modules,'homeassistant',types.ModuleType('homeassistant'))
    monkeypatch.setitem(sys.modules,'homeassistant.helpers',types.ModuleType('homeassistant.helpers'))
    monkeypatch.setitem(sys.modules,'homeassistant.helpers.entity_registry',reg_module)
    monkeypatch.setitem(sys.modules,'homeassistant.helpers.dispatcher',dispatcher)
    runtime_module=importlib.import_module('comexio_local.runtime')
    class Admin:
        async def read_config(self):
            return {'FubModules':{'1':{'1':{'extension':{'Name':'IO-Server-1'},
                'inoutput':{'4':{'Identifier':'Q4','Id':4,
                    'Description':'Roll Kind 2 H X1/5','Active':True}}}}, '2':{}}, 'Fubs':{}}
        async def read_plans(self,config,limit=None,strict=False):return {}
    scheduled=[]
    hass=SimpleNamespace(config_entries=SimpleNamespace(
        async_update_entry=lambda *_args,**_kwargs:None,
        async_schedule_reload=lambda id:scheduled.append(id)))
    entry=SimpleNamespace(entry_id=ENTRY.entry_id,unique_id=ENTRY.unique_id,options={})
    rt=runtime_module.Runtime(hass,entry,Admin(),None)
    ch=source(kind='relay')
    rt.channels={ch.key:ch}
    async def run():
        preview=await rt.preview_sync()
        reg.rows[0]=row(name='Benutzername während Vorschau geändert')
        with pytest.raises(ValueError,match='geändert'):
            await rt.apply_sync(preview['fingerprint'])
    asyncio.run(run())
    assert not reg.removed and not scheduled


def test_motor_pin_is_safeguarded_while_corrected_motor_can_retire_old_sensor():
    from comexio_local.preferences import apply_classifications
    key='io:IO-Server-1/Q4'
    old={key:source(kind='relay', name='Kind 2 Rool H X1/5')}
    raw={key:source(kind='motor', name='Roll Kind 2 H X1/5')}
    options={'known_channel_kinds':{key:'relay'},
             'channel_kind_overrides':{key:'light'}}
    new=apply_classifications(raw,options)
    assert new[key].kind=='motor'  # source remains protected, never user-switchable
    p=plan(old,new,[row()])
    assert len(p['registry_removals'])==1


def test_manual_name_override_alone_does_not_trigger_registry_removal():
    key='io:IO-Ext-1/Q1'
    old={key:source(key=key,kind='light',name='Vorher')}
    new={key:replace(old[key],name='Nachher')}
    p=plan(old,new,[row(key=key,domain='light',name='Mein manueller Name')])
    assert p['counts']['renamed']==1
    assert p['registry_removals']==[]


def test_deleted_or_unavailable_entire_comexio_catalog_fails_closed(monkeypatch):
    import importlib
    dispatcher=types.ModuleType('homeassistant.helpers.dispatcher')
    dispatcher.async_dispatcher_send=lambda *args:None
    monkeypatch.setitem(sys.modules,'homeassistant',types.ModuleType('homeassistant'))
    monkeypatch.setitem(sys.modules,'homeassistant.helpers',types.ModuleType('homeassistant.helpers'))
    monkeypatch.setitem(sys.modules,'homeassistant.helpers.dispatcher',dispatcher)
    runtime_module=importlib.import_module('comexio_local.runtime')
    class EmptyAdmin:
        async def read_config(self):return {'FubModules':{'1':{},'2':{}},'Fubs':{}}
        async def read_plans(self,config,limit=None,strict=False):return {}
    rt=runtime_module.Runtime(SimpleNamespace(),ENTRY,EmptyAdmin(),None)
    ch=source(kind='light')
    rt.channels={ch.key:ch}
    with pytest.raises(ValueError,match='keinen einzigen Kanal'):
        asyncio.run(rt._complete_sync_catalog({}))
