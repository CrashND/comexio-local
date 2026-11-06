"""Regression tests for the failed physical-input preview in 0.3.6.3.2."""
import asyncio
import importlib.util
from pathlib import Path
import sys
import types
from types import SimpleNamespace

import pytest

from comexio_local.admin_api import AdminError
from comexio_local.discovery import Channel, discover
from comexio_local.input_push import inspect_input_push
from test_discovery import _config
from test_input_push_0363 import InputAdminFake, with_inputs
from test_push_audit import BASE, ENTRY, PATH


KEY = 'io:IO-Ext-3/I1'


def _load_options_flow(monkeypatch):
    """Exercise the real options-flow method without an installed HA runtime."""
    ha = types.ModuleType('homeassistant')
    ha.__path__ = []
    entries = types.ModuleType('homeassistant.config_entries')

    class ConfigFlow:
        def __init_subclass__(cls, **kwargs):
            super().__init_subclass__()

    class OptionsFlow:
        def async_show_form(self, **kwargs):
            return {'type': 'form', **kwargs}

        def async_abort(self, **kwargs):
            return {'type': 'abort', **kwargs}

    entries.ConfigFlow = ConfigFlow
    entries.OptionsFlow = OptionsFlow
    ha.config_entries = entries
    helpers = types.ModuleType('homeassistant.helpers')
    helpers.__path__ = []
    aiohttp_client = types.ModuleType('homeassistant.helpers.aiohttp_client')
    aiohttp_client.async_create_clientsession = lambda *args, **kwargs: None

    selector = types.ModuleType('homeassistant.helpers.selector')

    class SelectSelectorConfig:
        def __init__(self, **kwargs):
            vars(self).update(kwargs)

    class SelectSelector:
        def __init__(self, config):
            self.config = config

    selector.SelectSelector = SelectSelector
    selector.SelectSelectorConfig = SelectSelectorConfig
    selector.SelectSelectorMode = SimpleNamespace(DROPDOWN='dropdown')
    vol = types.ModuleType('voluptuous')

    class Required:
        def __init__(self, name, default=None):
            self.name = name
            self.default = default

    class Schema:
        def __init__(self, fields):
            self.schema = fields

    vol.Required = Required
    vol.Schema = Schema
    vol.In = lambda options: options
    for name, module in {
        'homeassistant': ha,
        'homeassistant.config_entries': entries,
        'homeassistant.helpers': helpers,
        'homeassistant.helpers.aiohttp_client': aiohttp_client,
        'homeassistant.helpers.selector': selector,
        'voluptuous': vol,
    }.items():
        monkeypatch.setitem(sys.modules, name, module)

    path = (Path(__file__).resolve().parents[1] / 'custom_components'
            / 'comexio_local' / 'config_flow.py')
    spec = importlib.util.spec_from_file_location('comexio_local.input_flow_03633_test', path)
    module = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, spec.name, module)
    spec.loader.exec_module(module)
    return module


def _default(form, field):
    for marker in form['data_schema'].schema:
        if marker.name == field:
            return marker.default
    raise AssertionError(f'Missing form field {field}')


def _choices(form):
    for marker, select in form['data_schema'].schema.items():
        if marker.name == 'sources':
            return select.config.options
    raise AssertionError('Missing select options')


def _flow_with_inputs(flow_module):
    channels = {
        KEY: Channel(kind='input', name='Flur Licht Rot', key=KEY,
                     extension='IO-Ext-3', identifier='I1', io_id=11),
        'io:IO-Ext-3/I2': Channel(kind='input', name='Test 2',
                     key='io:IO-Ext-3/I2', extension='IO-Ext-3',
                     identifier='I2', io_id=12),
    }

    class Runtime:
        def __init__(self):
            self.raw_channels = channels
            self.fail = True
            self.received = []

        async def preview_input_push(self, chosen):
            self.received.append(dict(chosen))
            if self.fail:
                raise AdminError('COMEXIO GET /admin/function_function_module/loadelements/: HTTP 500')
            return {'fingerprint': 'fresh', 'sources': []}

    runtime = Runtime()
    flow = flow_module.ComexioLocalOptionsFlow()
    flow.config_entry = SimpleNamespace(options={}, entry_id='entry-1')
    flow._runtime = lambda: runtime
    return flow, runtime


def test_initial_input_select_has_no_bulk_default_and_failed_preview_keeps_user_choice(monkeypatch):
    module = _load_options_flow(monkeypatch)
    flow, runtime = _flow_with_inputs(module)

    empty = asyncio.run(flow.async_step_input_select())
    assert empty['step_id'] == 'input_select'
    assert _default(empty, 'sources') == []
    assert _choices(empty)[-1]['value'] == '__all_i__'

    failed = asyncio.run(flow.async_step_input_select({
        'sources': [KEY], 'input_mode': 'taster',
    }))
    assert failed['errors']['base'] == 'input_preview_failed'
    assert _default(failed, 'sources') == [KEY]
    assert _default(failed, 'input_mode') == 'taster'
    assert '__all_i__' not in _default(failed, 'sources')
    assert 'HTTP 500' in failed['description_placeholders']['diagnostic']
    assert runtime.received == [{KEY: 'taster'}]

    runtime.fail = False
    successful = asyncio.run(flow.async_step_input_select({
        'sources': [KEY], 'input_mode': 'taster',
    }))
    assert successful['step_id'] == 'input_review'
    assert runtime.received[-1] == {KEY: 'taster'}


def test_preview_error_keeps_nondefault_switch_mode(monkeypatch):
    module = _load_options_flow(monkeypatch)
    flow, _runtime = _flow_with_inputs(module)
    failed = asyncio.run(flow.async_step_input_select({
        'sources': [KEY], 'input_mode': 'schalter',
    }))
    assert failed['errors']['base'] == 'input_preview_failed'
    assert _default(failed, 'sources') == [KEY]
    assert _default(failed, 'input_mode') == 'schalter'


def test_safe_diagnostics_hide_webhook_and_credentials(monkeypatch):
    module = _load_options_flow(monkeypatch)
    error = AdminError('POST http://192.168.10.6:8123/api/webhook/VERY_PRIVATE '
                       'path=/api/webhook/SECRET_123 token=abc password=def HTTP 500')
    detail = module._safe_admin_reason(error)
    assert 'VERY_PRIVATE' not in detail
    assert 'SECRET_123' not in detail
    assert 'token=abc' not in detail
    assert 'password=def' not in detail
    assert 'HTTP 500' in detail


def test_safe_diagnostics_include_nested_http_status_without_the_url(monkeypatch):
    module = _load_options_flow(monkeypatch)
    try:
        raise SimpleNamespaceError(503, 'http://192.168.10.254/private?token=secret')
    except SimpleNamespaceError as exc:
        try:
            raise AdminError('COMEXIO configuration discovery failed') from exc
        except AdminError as admin_err:
            detail = module._safe_admin_reason(admin_err)
    assert 'HTTP 503' in detail
    assert 'secret' not in detail
    assert '192.168.10.254' not in detail


class SimpleNamespaceError(Exception):
    def __init__(self, status, url):
        self.status = status
        super().__init__(url)


def test_configuration_abort_carries_safe_error_reason(monkeypatch):
    module = _load_options_flow(monkeypatch)
    flow, runtime = _flow_with_inputs(module)
    flow._input_preview = {'sources': [], 'fingerprint': 'fresh'}
    flow._input_selected = {KEY: 'taster'}

    async def fail_configure(chosen, fingerprint):
        raise AdminError('Falscher Parameter /api/webhook/PRIVATE_CALLBACK')

    runtime.configure_input_push = fail_configure
    result = asyncio.run(flow.async_step_input_review({'backup_confirmed': True}))
    assert result['type'] == 'abort'
    assert result['reason'] == 'input_failed'
    assert 'PRIVATE_CALLBACK' not in result['description_placeholders']['reason']
    assert 'Falscher Parameter' in result['description_placeholders']['reason']


def test_preview_identifies_failed_comexio_plan_read_and_does_not_write():
    admin = InputAdminFake(with_inputs(_config()))
    raw = discover(admin.config)
    chosen = {'io:IO-Ext-2/I1': 'taster'}

    async def run():
        original = await inspect_input_push(admin, raw, ENTRY, PATH, BASE, chosen)
        name = original['sources'][0]['plan']
        admin.config.setdefault('Fubs', {})['123'] = {
            'Name': name,
            'Comment': f'Managed exclusively by COMEXIO Local INPUT ({ENTRY}); do not rename',
            'Active': False,
        }

        async def failed_plan(fid):
            raise AdminError('COMEXIO GET /admin/function_function_module/loadelements/: HTTP 500')

        admin.read_plan = failed_plan
        with pytest.raises(AdminError, match='Logikplan.*HTTP 500'):
            await inspect_input_push(admin, raw, ENTRY, PATH, BASE, chosen)
        assert admin.writes == []

    asyncio.run(run())


def test_preview_identifies_failed_config_read_and_does_not_write():
    admin = InputAdminFake(with_inputs(_config()))
    raw = discover(admin.config)
    chosen = {'io:IO-Ext-2/I1': 'taster'}

    async def failed_config():
        raise AdminError('COMEXIO configuration discovery failed')

    admin.read_config = failed_config
    with pytest.raises(AdminError, match='COMEXIO-Konfiguration lesen'):
        asyncio.run(inspect_input_push(admin, raw, ENTRY, PATH, BASE, chosen))
    assert admin.writes == []


def test_diagnostic_translation_placeholders_exist_in_all_locales():
    import json
    root = Path(__file__).resolve().parents[1] / 'custom_components/comexio_local'
    for path in (root / 'strings.json', root / 'translations/de.json',
                 root / 'translations/en.json'):
        data = json.loads(path.read_text(encoding='utf-8'))['options']
        assert '{diagnostic}' in data['step']['input_select']['description']
        assert 'input_preview_failed' in data['error']
        assert '{reason}' in data['abort']['input_failed']
