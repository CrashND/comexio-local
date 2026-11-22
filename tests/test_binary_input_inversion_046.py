"""v0.4.6: generic HA-only input polarity, with stable identity and raw push."""
from __future__ import annotations

import asyncio
import importlib.util
import sys
import types
from types import SimpleNamespace
from pathlib import Path

import pytest

from comexio_local.discovery import Channel
from comexio_local.preferences import (
    INPUT_INVERT_OVERRIDES, binary_input_is_inverted, ha_binary_input_state,
)
from test_input_flow_03633 import _load_options_flow, _default


def _signals():
    contact = Channel(kind='binary_input', name='OG Eingangstuer',
                      key='io:EnOcean/EI5_CO', extension='EnOcean', identifier='EI5_CO',
                      enocean_slot=5, enocean_signal='CO')
    motion = Channel(kind='binary_input', name='Treppenhaus EG',
                     key='io:EnOcean/EI3_PIRS', extension='EnOcean', identifier='EI3_PIRS',
                     enocean_slot=3, enocean_signal='PIRS')
    relay = Channel(kind='relay', name='Statusausgang',
                    key='io:IO-Ext-1/Q2', extension='IO-Ext-1', identifier='Q2')
    return {c.key: c for c in (contact, motion, relay)}


def test_binary_input_conversion_follows_opt_in_and_preserves_missing_state():
    key = 'io:EnOcean/EI5_CO'
    assert binary_input_is_inverted({}, key) is False
    assert binary_input_is_inverted({INPUT_INVERT_OVERRIDES: {key: True}}, key) is True
    for wrong in (1, 'true', 'yes', None, False):
        assert binary_input_is_inverted({INPUT_INVERT_OVERRIDES: {key: wrong}}, key) is False
    assert binary_input_is_inverted({INPUT_INVERT_OVERRIDES: 'broken'}, key) is False
    assert ha_binary_input_state(None, True) is None
    assert ha_binary_input_state(None, False) is None
    assert ha_binary_input_state(0, True) is True
    assert ha_binary_input_state(1, True) is False
    assert ha_binary_input_state(0, False) is False
    assert ha_binary_input_state(1, False) is True


def test_entity_applies_preference_at_render_time_for_snapshot_and_live_events(monkeypatch):
    """Only the HA entity changes. Runtime's raw value is always 1/0."""
    hass_module = types.ModuleType('homeassistant.components.binary_sensor')
    hass_module.BinarySensorEntity = type('BinarySensorEntity', (), {})
    hass_module.BinarySensorDeviceClass = SimpleNamespace(OCCUPANCY='occupancy', MOTION='motion')
    dispatcher = types.ModuleType('homeassistant.helpers.dispatcher')
    dispatcher.async_dispatcher_connect = lambda *args, **kwargs: None
    ha_core = types.ModuleType('homeassistant.core')
    ha_core.callback = lambda fn: fn
    base_module = types.ModuleType('comexio_local.entities')
    class BaseChannel:
        def __init__(self, runtime, channel):
            self.runtime = runtime
            self.channel = channel
            self.unique_id = f'controller:{channel.key}'
        @property
        def extra_state_attributes(self):
            return {'comexio_quelle': self.channel.key}
    base_module.BaseChannel = BaseChannel
    for name, mod in {
        'homeassistant': types.ModuleType('homeassistant'),
        'homeassistant.core': ha_core,
        'homeassistant.components': types.ModuleType('homeassistant.components'),
        'homeassistant.components.binary_sensor': hass_module,
        'homeassistant.helpers': types.ModuleType('homeassistant.helpers'),
        'homeassistant.helpers.dispatcher': dispatcher,
        'comexio_local.entities': base_module,
    }.items():
        monkeypatch.setitem(sys.modules, name, mod)
    path = Path(__file__).resolve().parents[1] / 'custom_components/comexio_local/binary_sensor.py'
    spec = importlib.util.spec_from_file_location('comexio_local.binary_sensor_046_test', path)
    module = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, spec.name, module)
    spec.loader.exec_module(module)
    channels = _signals()
    contact = channels['io:EnOcean/EI5_CO']
    another = channels['io:EnOcean/EI3_PIRS']
    values = {contact.key: 1, another.key: 0}
    entry = SimpleNamespace(options={})
    runtime = SimpleNamespace(entry=entry, value=lambda key: values.get(key))
    obj = module.ComexioInput(runtime, contact)
    other = module.ComexioInput(runtime, another)
    identity = obj.unique_id
    assert obj.is_on is True  # default unchanged (closed raw=1)
    entry.options = {INPUT_INVERT_OVERRIDES: {contact.key: True}}
    assert obj.is_on is False  # closed => HA off; previously customized Door class shows Closed
    assert other.is_on is False  # other channel remains independent
    assert obj.extra_state_attributes['signal_invertiert'] is True
    assert obj.extra_state_attributes['comexio_quelle'] == contact.key
    assert values[contact.key] == 1  # no mutation
    # Live webhook writes raw 0 into the *same* runtime value cache.
    values[contact.key] = 0
    assert obj.is_on is True
    assert obj.unique_id == identity
    values[contact.key] = None
    assert obj.is_on is None
    # Current options can be changed without rebuilding the entity.
    entry.options = {}
    values[contact.key] = 1
    assert obj.is_on is True
    assert obj.unique_id == identity


def _input_flow(monkeypatch, options=None, channels=None):
    module = _load_options_flow(monkeypatch)
    channels = _signals() if channels is None else channels
    entry = SimpleNamespace(options=dict(options or {}), entry_id='entry-1')
    runtime = SimpleNamespace(channels=channels, state_signal='comexio-local-state')
    sent = []
    dispatcher = types.ModuleType('homeassistant.helpers.dispatcher')
    dispatcher.async_dispatcher_send = lambda _hass, sig: sent.append(sig)
    monkeypatch.setitem(sys.modules, 'homeassistant.helpers.dispatcher', dispatcher)
    class ConfigEntries:
        def async_update_entry(self, item, *, options):
            assert item is entry
            item.options = options
    hass = SimpleNamespace(config_entries=ConfigEntries())
    flow = module.ComexioLocalOptionsFlow()
    flow.config_entry = entry
    flow.hass = hass
    flow._runtime = lambda: runtime
    return flow, entry, sent


def test_options_flow_selects_only_binary_inputs_and_persists_true_without_comexio(monkeypatch):
    flow, entry, sent = _input_flow(monkeypatch)
    shown = asyncio.run(flow.async_step_input_invert_select())
    assert shown['step_id'] == 'input_invert_select'
    choices = next(value.config.options for key, value in shown['data_schema'].schema.items()
                   if key.name == 'source')
    assert {opt['value'] for opt in choices} == {
        'io:EnOcean/EI5_CO', 'io:EnOcean/EI3_PIRS'}
    shown = asyncio.run(flow.async_step_input_invert_select({'source': 'io:EnOcean/EI5_CO'}))
    assert shown['step_id'] == 'input_invert_edit'
    assert _default(shown, 'inverted') is False
    out = asyncio.run(flow.async_step_input_invert_edit({'inverted': True}))
    assert out['type'] == 'abort'
    assert out['reason'] == 'input_inversion_saved'
    assert entry.options[INPUT_INVERT_OVERRIDES] == {'io:EnOcean/EI5_CO': True}
    assert sent == ['comexio-local-state']  # immediate HA state refresh; no COMEXIO write


def test_options_flow_reopening_restores_setting_and_can_disable(monkeypatch):
    key = 'io:EnOcean/EI5_CO'
    saved = {INPUT_INVERT_OVERRIDES: {key: True, 'io:EnOcean/EI3_PIRS': True},
             'cover_invert_default': True}
    flow, entry, sent = _input_flow(monkeypatch, saved)
    shown = asyncio.run(flow.async_step_input_invert_select({'source': key}))
    assert _default(shown, 'inverted') is True
    out = asyncio.run(flow.async_step_input_invert_edit({'inverted': False}))
    assert out['reason'] == 'input_inversion_saved'
    assert entry.options[INPUT_INVERT_OVERRIDES] == {'io:EnOcean/EI3_PIRS': True}
    assert entry.options['cover_invert_default'] is True
    assert sent == ['comexio-local-state']
    # Repeating with the same setting is a no-op, no unnecessary notifications.
    flow2, entry2, sent2 = _input_flow(monkeypatch, entry.options)
    asyncio.run(flow2.async_step_input_invert_select({'source': key}))
    asyncio.run(flow2.async_step_input_invert_edit({'inverted': False}))
    assert sent2 == []
    assert entry2.options == entry.options


def test_options_flow_rejects_unsupported_channel_and_invalid_payload(monkeypatch):
    flow, entry, sent = _input_flow(monkeypatch)
    invalid = asyncio.run(flow.async_step_input_invert_select({'source': 'io:IO-Ext-1/Q2'}))
    assert invalid['type'] == 'form' and invalid['errors'] == {'base': 'invalid_selection'}
    assert entry.options == {}
    edit = asyncio.run(flow.async_step_input_invert_select({'source': 'io:EnOcean/EI5_CO'}))
    assert edit['step_id'] == 'input_invert_edit'
    invalid = asyncio.run(flow.async_step_input_invert_edit({'inverted': 'true'}))
    assert invalid['errors'] == {'base': 'invalid_selection'}
    assert entry.options == {} and not sent


def test_no_eligible_inputs_does_not_offer_wrong_setting(monkeypatch):
    relay = _signals()['io:IO-Ext-1/Q2']
    flow, _, _ = _input_flow(monkeypatch, channels={relay.key: relay})
    assert asyncio.run(flow.async_step_input_invert_select())['reason'] == 'no_binary_inputs'
