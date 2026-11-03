"""Offline tests for explicit HA area changes (no real HA runtime required)."""
from __future__ import annotations

from types import ModuleType, SimpleNamespace
import sys
import pytest

from comexio_local.discovery import Channel
from comexio_local.area_assignment import (
    normalize_room, match_area, preview_area_assignment, apply_area_assignment,
)


def _fake_registry(monkeypatch, *, explicit=None, device_area=None):
    helpers = ModuleType('homeassistant.helpers')
    ar_module = ModuleType('homeassistant.helpers.area_registry')
    er_module = ModuleType('homeassistant.helpers.entity_registry')
    areas = {
        'buero': SimpleNamespace(id='buero', name='B\u00fcro', aliases=set()),
        'schlafen': SimpleNamespace(id='schlafen', name='Schlafzimmer', aliases={'SZ'}),
        'flur': SimpleNamespace(id='flur', name='Flur', aliases=set()),
    }
    area_registry = SimpleNamespace(areas=areas)
    entry = SimpleNamespace(entry_id='entry-1', unique_id='uuid-1')
    ent = SimpleNamespace(entity_id='light.comexio_buero', area_id=explicit,
                          config_entry_id=entry.entry_id)
    ent_map = {ent.entity_id: ent}
    key = 'io:IO-Ext-2/Q2'
    channel = Channel(kind='light', name='Buero Licht', key=key,
                      extension='IO-Ext-2', identifier='Q2', plan='Buero')
    class Registry:
        def __init__(self):
            self.writes=[]
        def async_get_entity_id(self, kind, domain, unique_id):
            if (kind, domain, unique_id) == ('light','comexio_local','uuid-1:'+key):
                return ent.entity_id
            return None
        def async_get(self, entity_id):
            return ent_map.get(entity_id)
        def async_update_entity(self, entity_id, *, area_id):
            self.writes.append((entity_id, area_id))
            ent_map[entity_id].area_id=area_id
    registry=Registry()
    ar_module.async_get=lambda hass: area_registry
    er_module.async_get=lambda hass: registry
    er_module.async_get_effective_area_id=lambda hass, entity: entity.area_id or device_area
    helpers.area_registry=ar_module
    helpers.entity_registry=er_module
    monkeypatch.setitem(sys.modules,'homeassistant',ModuleType('homeassistant'))
    monkeypatch.setitem(sys.modules,'homeassistant.helpers',helpers)
    monkeypatch.setitem(sys.modules,'homeassistant.helpers.area_registry',ar_module)
    monkeypatch.setitem(sys.modules,'homeassistant.helpers.entity_registry',er_module)
    return SimpleNamespace(),entry,{key:channel},registry,ent


def test_room_matching_is_unambiguous_and_unicode_safe():
    assert normalize_room('B\u00fcro') == normalize_room('Buero')
    assert match_area('Buero', {'x':('B\u00fcro',)})=='x'
    assert match_area('Flur', {'x':('Flur',), 'y':('Flur',)}) is None
    assert match_area('WZ', {'x':('Wohnzimmer',)}) is None
    assert match_area('Buero', {'x':('OG B\u00fcro',)}) is None
    assert match_area('OG Buero', {'x':('OG B\u00fcro',)}) == 'x'
    assert match_area('OG', {'x':('OG Schlafzimmer',)}) is None
    assert match_area('EG-WZ', {'x':('EG WZ',)}) is None


def test_read_only_preview_and_confirmation(monkeypatch):
    hass,entry,channels,registry,entity=_fake_registry(monkeypatch)
    report=preview_area_assignment(hass,entry,channels)
    assert report['assignments']==1
    assert report['rows'][0]['target']=='buero'
    assert registry.writes==[]
    with pytest.raises(ValueError,match='Explicit'):
        apply_area_assignment(hass,entry,channels,fingerprint=report['fingerprint'])
    assert registry.writes==[]
    done=apply_area_assignment(hass,entry,channels,fingerprint=report['fingerprint'],confirm=True)
    assert done['updated']==1
    assert entity.area_id=='buero'
    assert registry.writes==[(entity.entity_id,'buero')]


def test_preserve_explicit_assignments_except_user_override(monkeypatch):
    hass,entry,channels,registry,entity=_fake_registry(monkeypatch,explicit='flur')
    report=preview_area_assignment(hass,entry,channels)
    assert report['rows'][0]['action']=='keep_existing'
    assert report['assignments']==0
    report=preview_area_assignment(hass,entry,channels,overwrite=True)
    assert report['assignments']==1
    apply_area_assignment(hass,entry,channels,fingerprint=report['fingerprint'],overwrite=True,confirm=True)
    assert entity.area_id=='buero'


def test_detect_stale_area_before_any_write(monkeypatch):
    hass,entry,channels,registry,entity=_fake_registry(monkeypatch)
    report=preview_area_assignment(hass,entry,channels)
    entity.area_id='flur'
    with pytest.raises(ValueError,match='changed'):
        apply_area_assignment(hass,entry,channels,fingerprint=report['fingerprint'],confirm=True)
    assert registry.writes==[]


def test_inherited_device_area_may_be_overridden_with_explicit_choice(monkeypatch):
    hass,entry,channels,registry,entity=_fake_registry(monkeypatch,device_area='flur')
    report=preview_area_assignment(hass,entry,channels)
    assert report['rows'][0]['before']=='flur'
    assert report['rows'][0]['action']=='assign'


def test_manual_selection_and_unknown_area(monkeypatch):
    hass,entry,channels,registry,entity=_fake_registry(monkeypatch)
    report=preview_area_assignment(hass,entry,channels,
        selected=list(channels),target_area='schlafen')
    assert report['rows'][0]['target']=='schlafen'
    with pytest.raises(ValueError,match='Unknown'):
        preview_area_assignment(hass,entry,channels,target_area='missing')


def test_different_integration_entry_cannot_be_changed(monkeypatch):
    hass,entry,channels,registry,entity=_fake_registry(monkeypatch)
    entity.config_entry_id='foreign-entry'
    report=preview_area_assignment(hass,entry,channels)
    assert report['rows'][0]['action']=='unavailable'
    assert report['assignments']==0
