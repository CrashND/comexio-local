"""v0.4.10: connection options and passive input diagnostic menus."""
import asyncio
import json
from pathlib import Path
from types import SimpleNamespace

from comexio_local.constants import (
    CONF_HOST, CONF_ADMIN_USER, CONF_ADMIN_PASSWORD, CONF_TCP_PORT,
    CONF_PUSH_BASE, DOMAIN,
)
from comexio_local.admin_api import AdminError
from test_input_flow_03633 import _load_options_flow


ADDRESS = '192.168.10.254'
TARGET = 'http://192.168.10.6:8123'


def setup_connection(monkeypatch, *, owns_input=True):
    mod = _load_options_flow(monkeypatch)
    flow = mod.ComexioLocalOptionsFlow()
    entry = SimpleNamespace(entry_id='entry', unique_id=f'comexio_local:{ADDRESS}',
                            data={CONF_HOST: ADDRESS, CONF_TCP_PORT: 1505,
                                  CONF_ADMIN_USER: 'admin',
                                  CONF_ADMIN_PASSWORD: 'not_a_real_password',
                                  CONF_PUSH_BASE: TARGET})
    records = []
    class ConfigEntries:
        def async_entries(self, domain):
            assert domain == DOMAIN
            return [entry]
        def async_update_entry(self, entry_arg, **kwargs):
            assert entry_arg is entry
            records.append(kwargs)
            for key, val in kwargs.items():
                setattr(entry, key, val)
        async def async_reload(self, entry_id):
            assert entry_id == 'entry'
            return True
    class DummyRuntime:
        push_rebuild = None
        def input_push_status(self):
            return {'status': 'completed'}
    rt = DummyRuntime()
    flow.config_entry = entry
    flow.hass = SimpleNamespace(config_entries=ConfigEntries(),
                                async_create_task=lambda coro: asyncio.create_task(coro))
    flow._runtime = lambda: rt
    config = {'FubModules': {'1': {}}, 'WebDevices': (
        {'1': {'Name': 'CL Eing\u00e4nge Home Assistant'}} if owns_input else {})}
    class Admin:
        def __init__(self, session, host, user, password):
            assert password != ''
        async def read_config(self):
            return config
    monkeypatch.setattr(mod, 'ComexioAdmin', Admin)
    monkeypatch.setattr(mod, 'async_create_clientsession', lambda *args, **kwargs: None)
    return flow, entry, records, rt, config


def values(entry, **changes):
    return {CONF_HOST: entry.data[CONF_HOST],
            CONF_TCP_PORT: entry.data[CONF_TCP_PORT],
            CONF_ADMIN_USER: entry.data[CONF_ADMIN_USER],
            CONF_PUSH_BASE: entry.data[CONF_PUSH_BASE], **changes}


def test_menu_hierarchy_has_all_five_approved_groups(monkeypatch):
    mod = _load_options_flow(monkeypatch)
    flow = mod.ComexioLocalOptionsFlow()
    flow._runtime = lambda: object()
    result = asyncio.run(flow.async_step_init())
    assert result['menu_options'] == [
        'connection_menu','devices_menu','inputs_menu','push_management','maintenance_menu']
    for step in result['menu_options']:
        nested = asyncio.run(getattr(flow, f'async_step_{step}')())
        assert nested['type'] == 'menu'
        for child in nested['menu_options']:
            assert callable(getattr(flow, f'async_step_{child}'))


def test_connection_saves_without_replacing_hardware_or_entity_identity(monkeypatch):
    flow, entry, writes, _, config = setup_connection(monkeypatch)
    new_host = '192.168.10.253'
    async def run():
        first = await flow.async_step_connection_settings(values(entry, host=new_host))
        assert first['errors']['base'] == 'identity_confirmation_required'
        assert writes == []
        result = await flow.async_step_connection_settings(values(
            entry, host=new_host, same_server_confirmed=True))
        assert result['reason'] == 'connection_saved'
        await asyncio.sleep(0)
    asyncio.run(run())
    assert entry.data[CONF_HOST] == new_host
    assert entry.unique_id == f'comexio_local:{ADDRESS}'
    assert len(writes) == 1 and list(writes[0]) == ['data']
    assert entry.data[CONF_ADMIN_PASSWORD] == 'not_a_real_password'


def test_callback_address_edit_blocked_when_own_webio_devices_exist(monkeypatch):
    flow, entry, writes, _, config = setup_connection(monkeypatch)
    result = asyncio.run(flow.async_step_connection_settings(values(
        entry, push_base='http://192.168.10.7:8123')))
    assert result['errors']['base'] == 'push_target_in_use'
    assert writes == []


def test_connection_cannot_override_active_rebuild(monkeypatch):
    flow, entry, writes, rt, config = setup_connection(monkeypatch)
    rt.input_push_status = lambda: {'status': 'running'}
    result = asyncio.run(flow.async_step_connection_settings(values(entry)))
    assert result['errors']['base'] == 'job_running'
    assert writes == []


def test_passive_event_menu_reads_only_accepted_enocean_history(monkeypatch):
    mod = _load_options_flow(monkeypatch)
    flow = mod.ComexioLocalOptionsFlow()
    class Runtime:
        rejected_events = 4
        def push_events_report(self, limit):
            assert limit == 30
            return {'sources': {'io:EnOcean/EI5_CO': {'count': 1},
                                'io:IO-Ext-3/I1': {'count': 5}},
                    'last_events': [{'source':'io:EnOcean/EI5_CO',
                                     'received_at_utc':'2026-11-21T08:00:00Z',
                                     'value': 1},
                                    {'source':'io:IO-Ext-3/I1',
                                     'received_at_utc':'2026-11-21T08:01:00Z',
                                     'value': 1}]}
    flow._runtime = lambda: Runtime()
    form = asyncio.run(flow.async_step_input_events())
    summary = form['description_placeholders']['summary']
    assert 'EI5_CO' in summary and 'I1' not in summary
    assert '4' in summary and '1' in summary
    assert form['data_schema'].schema == {}
    closed = asyncio.run(flow.async_step_input_events({}))
    assert closed['reason'] == 'diagnostic_closed'


def test_localizations_have_menu_and_form_entries():
    base = (Path(__file__).resolve().parents[1] / 'custom_components' / 'comexio_local')
    approved = ['connection_menu','devices_menu','inputs_menu',
                'push_management','maintenance_menu']
    for rel in ('strings.json','translations/de.json','translations/en.json'):
        data = json.loads((base / rel).read_text())['options']
        assert all(key in data['step']['init']['menu_options'] for key in approved)
        assert data['step']['init']['menu_options']['inputs_menu'] in (
            'Eing\u00e4nge & Sensoren', 'Inputs & Sensors')
        assert 'same_server_confirmed' in data['step']['connection_settings']['data']
        assert 'identity_confirmation_required' in data['error']
