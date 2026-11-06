"""v0.3.6.3: physical I/AI push, latching inputs and non-interference."""
import asyncio
from copy import deepcopy

import pytest

from comexio_local.admin_api import AdminError
from comexio_local.discovery import discover, extract_plan_assignments
from comexio_local.input_push import (
    apply_input_push, input_catalog, input_command_name, input_device_name,
    inspect_input_push,
)
from comexio_local.preferences import INPUT_MODES, apply_classifications
from comexio_local.push_setup import push_sources
from comexio_local.push_rebuild import PushRebuild
from test_discovery import _config
from test_push_rebuild import AdminFake, FakeRuntime, MemoryStore
from test_push_audit import _installed, ENTRY, PATH, BASE


def with_inputs(config):
    conf = deepcopy(config)
    channel = conf['FubModules']['1']['5']['inoutput']
    channel['20'] = {'Id':20, 'Identifier':'I1', 'Active':1, 'Description':'Flur Taster'}
    channel['21'] = {'Id':21, 'Identifier':'AI2', 'Active':1, 'Description':'Licht SZ Gruen'}
    channel['22'] = {'Id':22, 'Identifier':'AI3', 'Active':1, 'Description':'Temperatur analog'}
    return conf


class InputAdminFake(AdminFake):
    async def create_push_class(self, name, commands, target):
        # Model an additive COMEXIO device creation, preserving existing Q.
        self.writes.append(('class', name, self.write_gap))
        self.config.setdefault('WebDevices', {})['77'] = {'Name':name,'Ip':target,'BaseId':9}
        self.config.setdefault('FubModules', {}).setdefault('10', {})['77'] = {}
        for command in commands:
            self.next_cmd += 1
            self.config['FubModules']['10']['77'][str(self.next_cmd)] = deepcopy(command)

    async def create_plan(self, name, comment):
        fid = max([100, *[int(x) for x in self.config.get('Fubs', {})]]) + 1
        self.writes.append(('plan', name))
        self.config['Fubs'][str(fid)] = {'Name':name,'Comment':comment,'Active':False}
        self.plans[str(fid)] = {'elements':{},'connections':{}}
        return fid

    async def wire(self, fid, src, dst, analog):
        self.writes.append(('wire', fid, src, dst, analog))
        plan = self.plans[str(fid)]
        key = str(len(plan['connections'])+1)
        plan['connections'][key] = {'input':{'element':str(src)},
                                    'output':{'0':{'element':str(dst)}}}


def test_discovery_and_opt_in_selection_preserve_core_push():
    raw = discover(with_inputs(_config()))
    assert raw['io:IO-Ext-2/I1'].kind == 'input'
    assert raw['io:IO-Ext-2/AI2'].kind == 'analog_input'
    assert raw['io:IO-Ext-2/AI3'].kind == 'analog_input'
    assert len(input_catalog(raw)) == 3
    converted = apply_classifications(raw, {INPUT_MODES:{
        'io:IO-Ext-2/I1':'schalter', 'io:IO-Ext-2/AI2':'taster'}})
    assert converted['io:IO-Ext-2/I1'].kind == 'binary_input'
    assert converted['io:IO-Ext-2/I1'].input_mode == 'schalter'
    assert converted['io:IO-Ext-2/AI2'].analog is False
    assert converted['io:IO-Ext-2/AI3'].kind == 'analog_input'  # no blind AI conversion
    assert converted['io:IO-Ext-2/AI3'].is_push_source is False
    assert {x.key for x in push_sources(converted)} == {x.key for x in push_sources(raw)}
    assert converted['io:IO-Ext-2/AI2'].is_push_source is True
    assert input_command_name(converted['io:IO-Ext-2/I1']) == 'CL Eingang E2/I1'


def test_readonly_preview_rejects_bad_selection_and_does_not_write():
    admin = InputAdminFake(with_inputs(_config()))
    raw = discover(admin.config)

    async def go():
        with pytest.raises(AdminError, match='Unbekannter'):
            await inspect_input_push(admin, raw, ENTRY, PATH, BASE, {'io:IO-Ext-2/Q1':'taster'})
        with pytest.raises(AdminError, match='ungültige'):
            await inspect_input_push(admin, raw, ENTRY, PATH, BASE, {'io:IO-Ext-2/AI2':'analog'})
        preview = await inspect_input_push(admin, raw, ENTRY, PATH, BASE, {'io:IO-Ext-2/AI2':'taster'})
        assert preview['needs_write'] is True
        assert preview['sources'][0]['action'] == 'anlegen'
        assert preview['sources'][0]['address'] == 'IO-Ext-2/AI2'
        assert admin.writes == []
        with pytest.raises(AdminError, match='sicherung'):
            await apply_input_push(admin,raw,ENTRY,PATH,BASE,{'io:IO-Ext-2/AI2':'taster'},
                                   preview['fingerprint'], False)
        with pytest.raises(AdminError, match='Vorschau'):
            await apply_input_push(admin,raw,ENTRY,PATH,BASE,{'io:IO-Ext-2/AI2':'taster'},
                                   '0'*64, True)
        assert admin.writes == []

    asyncio.run(go())


def test_additive_input_push_does_not_modify_existing_light_cover_plans(monkeypatch):
    from comexio_local import input_push
    config, plans, _ = _installed()
    config = with_inputs(config)
    admin = InputAdminFake(config, plans)
    originals = deepcopy(admin.plans)
    old_devices = deepcopy(admin.config.get('WebDevices'))
    old_commands = deepcopy(admin.config['FubModules'].get('10'))
    raw = discover(config)
    choices = {'io:IO-Ext-2/I1':'schalter','io:IO-Ext-2/AI2':'taster'}

    async def append(admin, device_id, base_id, command):
        admin.writes.append(('append',command['Name'],admin.write_gap))
        admin.next_cmd += 1
        admin.config['FubModules']['10'][str(device_id)][str(admin.next_cmd)] = deepcopy(command)

    monkeypatch.setattr(input_push, '_append_command', append)

    async def go():
        preview = await inspect_input_push(admin,raw,ENTRY,PATH,BASE,choices)
        stats = await apply_input_push(admin,raw,ENTRY,PATH,BASE,choices,preview['fingerprint'],True)
        assert stats == {'created_commands':2,'added_links':2,'activated_plans':2,'verified':2}, stats
        assert admin.config['WebDevices']['77']['Name'] == input_device_name(ENTRY)
        assert admin.config['WebDevices']['77']['Ip'] == BASE.removeprefix('http://')
        assert [w for w in admin.writes if w[0] == 'class'][0][2] >= 2.0
        assert [w for w in admin.writes if w[0] == 'append'][0][2] >= 2.0
        assert admin.write_gap == 1.25
        assert {i:admin.plans[i] for i in originals} == originals
        assert {i:admin.config['WebDevices'][i] for i in old_devices} == old_devices
        assert {i:admin.config['FubModules']['10'][i] for i in old_commands} == old_commands
        # Read-only preview is idempotent. No duplicate elements or writes.
        again = await inspect_input_push(admin,raw,ENTRY,PATH,BASE,choices)
        assert all(x['action']=='vorhanden' for x in again['sources'])
        written = len(admin.writes)
        await apply_input_push(admin,raw,ENTRY,PATH,BASE,choices,again['fingerprint'],True)
        assert len(admin.writes) == written
        # Input plans must be excluded from COMEXIO room affiliation.
        assignments = extract_plan_assignments(admin.plans,admin.config['Fubs'])
        assert (1,20) not in assignments and (1,21) not in assignments
        # Crucially, the OLD core rebuild must ignore the new owned input plan.
        manager = PushRebuild(FakeRuntime(admin, discover(admin.config)), MemoryStore())
        result = await manager.preview()
        assert result['sources'] > 0
        assert result['plans'] == len(originals)

    asyncio.run(go())


def test_foreign_input_plan_blocks_all_writes():
    config = with_inputs(_config())
    admin = InputAdminFake(config)
    raw = discover(config)
    chosen={'io:IO-Ext-2/I1':'taster'}

    async def go():
        first = await inspect_input_push(admin, raw, ENTRY, PATH, BASE, chosen)
        plan_name=first['sources'][0]['plan']
        admin.config['Fubs']['123']={'Name':plan_name,'Comment':'Fremd','Active':True}
        admin.plans['123']={'elements':{}, 'connections':{}}
        with pytest.raises(AdminError,match='Fremder'):
            await inspect_input_push(admin, raw, ENTRY, PATH, BASE, chosen)
        assert admin.writes == []

    asyncio.run(go())


def test_preview_blocks_changed_callback_in_existing_input_command():
    config=with_inputs(_config()); raw=discover(config)
    admin=InputAdminFake(config)
    key='io:IO-Ext-2/I1'

    async def go():
        preview=await inspect_input_push(admin,raw,ENTRY,PATH,BASE,{key:'taster'})
        await apply_input_push(admin,raw,ENTRY,PATH,BASE,{key:'taster'},preview['fingerprint'],True)
        saved=admin.config['FubModules']['10']['77']
        next(iter(saved.values()))['Parameter']='/api/webhook/wrong'
        with pytest.raises(AdminError,match='Parameter'):
            await inspect_input_push(admin,raw,ENTRY,PATH,BASE,{key:'taster'})

    asyncio.run(go())


def test_partial_input_link_is_recovered_without_duplicate_elements():
    config=with_inputs(_config())
    raw=discover(config)
    admin=InputAdminFake(config)
    key='io:IO-Ext-2/AI2'
    original_add=admin.add_element
    fail_once={'yes':True}

    async def partly_failed(fid,ref,typ,x,y,connection=None):
        if typ == 10 and fail_once['yes']:
            fail_once['yes'] = False
            raise AdminError('COMEXIO HTTP 500 nach Anlegen des Eingangselements')
        return await original_add(fid,ref,typ,x,y,connection=connection)

    admin.add_element=partly_failed

    async def go():
        preview=await inspect_input_push(admin,raw,ENTRY,PATH,BASE,{key:'taster'})
        with pytest.raises(AdminError,match='500'):
            await apply_input_push(admin,raw,ENTRY,PATH,BASE,{key:'taster'},preview['fingerprint'],True)
        assert admin.write_gap == 1.25
        assert sum(len(plan['elements']) for plan in admin.plans.values()) == 1
        # A stale fingerprint must not be accepted after partial writes.
        with pytest.raises(AdminError,match='Vorschau'):
            await apply_input_push(admin,raw,ENTRY,PATH,BASE,{key:'taster'},preview['fingerprint'],True)
        fresh=await inspect_input_push(admin,raw,ENTRY,PATH,BASE,{key:'taster'})
        assert fresh['sources'][0]['action'] == 'verknuepfen'
        result=await apply_input_push(admin,raw,ENTRY,PATH,BASE,{key:'taster'},fresh['fingerprint'],True)
        assert result['created_commands']==0
        assert result['added_links']==1
        plan=next(iter(admin.plans.values()))
        refs=[(e['reference']['type'],e['reference']['ref_id']) for e in plan['elements'].values()]
        assert refs.count((1,21))==1
        assert len(refs)==2

    asyncio.run(go())


def test_input_callback_must_be_private_lan_http():
    conf=with_inputs(_config()); raw=discover(conf); admin=InputAdminFake(conf)
    for invalid in ('https://192.168.10.6:8123', 'http://example.org:8123',
                    'http://8.8.8.8:8123','http://user:pass@192.168.10.6:8123',
                    'http://192.168.10.6:8123/path','http://192.168.10.6:8123/?x=1'):
        with pytest.raises(AdminError,match='LAN'):
            asyncio.run(inspect_input_push(admin,raw,ENTRY,PATH,invalid,
                {'io:IO-Ext-2/AI2':'taster'}))
    assert admin.writes == []


def test_foreign_element_in_owned_input_plan_fails_closed():
    conf=with_inputs(_config()); raw=discover(conf); admin=InputAdminFake(conf)
    key='io:IO-Ext-2/I1'

    async def go():
        prev=await inspect_input_push(admin,raw,ENTRY,PATH,BASE,{key:'taster'})
        await apply_input_push(admin,raw,ENTRY,PATH,BASE,{key:'taster'},prev['fingerprint'],True)
        name=prev['sources'][0]['plan']
        fid=next(str(fid) for fid,meta in admin.config['Fubs'].items() if meta['Name']==name)
        admin.plans[fid]['elements']['999']={'reference':{'type':10,'ref_id':777777}}
        with pytest.raises(AdminError,match='Fremder Baustein'):
            await inspect_input_push(admin,raw,ENTRY,PATH,BASE,{key:'taster'})

    asyncio.run(go())


def test_input_event_bus_only_emits_real_edges(monkeypatch):
    import importlib
    import sys
    import types
    from types import SimpleNamespace
    from comexio_local.discovery import Channel

    dispatch=types.ModuleType('homeassistant.helpers.dispatcher')
    dispatch.async_dispatcher_send=lambda *_args: None
    registry_module=types.ModuleType('homeassistant.helpers.entity_registry')
    class Registry:
        def async_get_entity_id(self, domain, integration, unique_id):
            assert domain=='binary_sensor'
            assert integration=='comexio_local'
            return 'binary_sensor.test_taster'
    registry_module.async_get=lambda _hass:Registry()
    monkeypatch.setitem(sys.modules,'homeassistant',types.ModuleType('homeassistant'))
    monkeypatch.setitem(sys.modules,'homeassistant.helpers',types.ModuleType('homeassistant.helpers'))
    monkeypatch.setitem(sys.modules,'homeassistant.helpers.dispatcher',dispatch)
    monkeypatch.setitem(sys.modules,'homeassistant.helpers.entity_registry',registry_module)
    module=importlib.import_module('comexio_local.runtime')
    seen=[]
    rt=module.Runtime(SimpleNamespace(bus=SimpleNamespace(
        async_fire=lambda name,data:seen.append((name,data)))),
        SimpleNamespace(entry_id='entry-1',unique_id=None),None,None)
    key='io:IO-Ext-2/AI2'
    c=Channel(kind='binary_input', name='Schlafzimmer Taster', key=key,
              extension='IO-Ext-2',identifier='AI2',input_mode='taster')
    rt.channels[key]=c
    # A press without a successful start-state GET still needs an event.
    assert rt.apply_event({'type':'io','ext':'IO-Ext-2','io':'AI2','value':1})
    assert rt.apply_event({'type':'io','ext':'IO-Ext-2','io':'AI2','value':1})
    assert rt.apply_event({'type':'io','ext':'IO-Ext-2','io':'AI2','value':0})
    events=[data for name,data in seen if name=='comexio_local_input']
    assert [e['action'] for e in events]==['gedrueckt','losgelassen']
    assert events[0]['entity_id']=='binary_sensor.test_taster'
    assert rt.events == 3  # journal includes duplicate raw push, but not input event
    assert rt.push_journal.same_as_cached == 1
    rt.channels[key]=Channel(kind='binary_input',name='Schalter',key=key,
                             extension='IO-Ext-2',identifier='AI2',input_mode='schalter')
    assert rt.apply_event({'type':'io','ext':'IO-Ext-2','io':'AI2','value':1})
    assert [data['action'] for name,data in seen if name=='comexio_local_input'][-1]=='ein'
    assert rt.apply_event({'type':'io','ext':'IO-Ext-2','io':'AI2','value':0})
    assert [data['action'] for name,data in seen if name=='comexio_local_input'][-1]=='aus'
    # Leave runtime import clean: other tests install their own HA dispatcher stub.
    sys.modules.pop('comexio_local.runtime', None)
