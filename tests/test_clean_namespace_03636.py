"""Regression tests for the intentionally clean v0.3.6.3.6 namespace."""
import asyncio
import sys
import types

import pytest

from comexio_local.admin_api import AdminError
from comexio_local.discovery import Channel, discover
from comexio_local.managed_resources import is_owned_plan, plan_comment
from comexio_local.name_inspection import inspect_names
from comexio_local.push_labels import friendly_plan_name
from comexio_local.push_rebuild import PushRebuild, RebuildError
from comexio_local.push_setup import _stable_groups, _stable_plan_slot
from test_discovery import _config
from test_input_push_0363 import with_inputs
from test_push_audit import _installed, ENTRY
from test_push_rebuild import AdminFake, FakeRuntime, MemoryStore


def _light(module, number, ref):
    return Channel(kind='light', name=f'Licht {number}', key=f'io:{module}/Q{number}',
                   extension=module, identifier=f'Q{number}', io_id=ref)


def _cover(number):
    return Channel(kind='cover', name=f'Rollladen {number}', key=f'cover:M{number}',
                   marker_id=number, target_marker_id=number + 100)


def test_existing_physical_plan_and_row_stay_fixed_when_channel_is_added():
    q7 = _light('IO-Ext-3', 7, 71)
    original = _stable_groups([q7])
    expanded = _stable_groups([q7, _light('IO-Ext-3', 1, 72),
                               _light('IO-Ext-3', 19, 73)])
    assert original[0][0] == 'IO-Ext-3 Q1-Q18'
    assert expanded[0][0] == original[0][0]
    assert friendly_plan_name(original[0][1], original[0][0]) == 'CL Push IO-Ext-3 Q1-Q18'
    assert _stable_plan_slot(q7) == 6
    assert _stable_plan_slot(q7) == _stable_plan_slot(expanded[0][1][1])
    assert expanded[1][0] == 'IO-Ext-3 Q19-Q36'
    assert _stable_plan_slot(expanded[1][1][0]) == 0


def test_cover_marker_blocks_are_physical_and_not_catalog_count():
    groups = _stable_groups([_cover(90), _cover(91), _cover(72)])
    assert [name for name, _ in groups] == [
        'Rollläden M55-M72', 'Rollläden M73-M90', 'Rollläden M91-M108']
    assert _stable_plan_slot(_cover(90)) == 17
    assert _stable_plan_slot(_cover(91)) == 0


def test_colliding_sanitized_extension_names_fail_closed():
    signals = [_light('IO-Ext-3', 1, 10), _light('IO-Ext-3*', 2, 11)]
    with pytest.raises(AdminError, match='Mehrdeutige Hardwarebezeichnungen'):
        _stable_groups(signals)


def test_empty_or_nonphysical_source_fails_before_plan_creation():
    with pytest.raises(AdminError, match='Push-Ausgangsadresse'):
        _stable_groups([Channel(kind='light', name='Bad', key='io:bad/I1',
                                extension='IO-Ext-3', identifier='I1', io_id=1)])
    with pytest.raises(AdminError, match='Merker-ID'):
        _stable_groups([_cover(0)])


def test_owner_marker_checks_family_and_exact_entry_not_label():
    assert is_owned_plan({'Comment': plan_comment(ENTRY, 'push')}, ENTRY, 'push')
    assert is_owned_plan({'Comment': plan_comment(ENTRY, 'input')}, ENTRY, 'input')
    assert is_owned_plan({'Comment': f'Managed exclusively by COMEXIO Local ({ENTRY})'},
                         ENTRY, 'push')
    assert is_owned_plan({'Comment': f'Managed exclusively by COMEXIO Local INPUT ({ENTRY})'},
                         ENTRY, 'input')
    assert not is_owned_plan({'Name': 'CL Push IO-Ext-3 Q1-Q18'}, ENTRY, 'push')
    assert not is_owned_plan({'Comment': plan_comment(ENTRY + '2', 'push')}, ENTRY, 'push')


def test_input_inspection_does_not_infer_command_from_other_webio_class():
    config, plans, channels = _installed()
    raw = discover(with_inputs(_config()))
    from comexio_local.input_push import input_command_name
    candidate = next(c for c in raw.values() if c.kind == 'input')
    config['FubModules']['10']['19']['999'] = {'Name': input_command_name(candidate)}
    result = inspect_names(config, channels, ENTRY, raw_channels=raw)
    assert not any(line.startswith('Eingangs-Befehl:') for line in result['found'])
    assert any('Unbekannter Befehl' in line for line in result['blockers'])


def test_pre_upgrade_checkpoint_is_retired_and_not_resumed(monkeypatch):
    config = _config()
    runtime = FakeRuntime(AdminFake(config), discover(config))
    store = MemoryStore({'version': 2, 'entry_id': ENTRY, 'status': 'failed',
                         'cursor': 0, 'steps': [], 'catalog_hash': 'old',
                         'started_at_utc': '2026-11-01T10:00:00+00:00',
                         'elapsed_seconds': 0})
    manager = PushRebuild(runtime, store)
    dispatcher = types.ModuleType('homeassistant.helpers.dispatcher')
    dispatcher.async_dispatcher_send = lambda *_args: None
    monkeypatch.setitem(sys.modules, 'homeassistant', types.ModuleType('homeassistant'))
    monkeypatch.setitem(sys.modules, 'homeassistant.helpers', types.ModuleType('homeassistant.helpers'))
    monkeypatch.setitem(sys.modules, 'homeassistant.helpers.dispatcher', dispatcher)

    async def run():
        await manager.initialize()
        assert store.data['status'] == 'cancelled'
        with pytest.raises(RebuildError, match='nicht fortgesetzt'):
            await manager.resume()
        assert runtime.admin.writes == []

    asyncio.run(run())
