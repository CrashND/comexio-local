"""Current canonical push namespace and safe cleanup boundaries."""
from __future__ import annotations

import asyncio
from copy import deepcopy

import pytest

from comexio_local.admin_api import AdminError
from comexio_local.managed_resources import validate_owned_push_commands
from comexio_local.push_cleanup import _preflight
from comexio_local.push_labels import friendly_command_name
from comexio_local.push_setup import push_sources
from comexio_local.push_rebuild import PushRebuild, CHECKPOINT_VERSION
from test_push_audit import _installed, ENTRY, BASE
from test_push_cleanup_038 import setup_admin
from test_push_rebuild import FakeRuntime, MemoryStore


def _current():
    config, plans, channels = _installed()
    signals = push_sources(channels)
    device_id = '19'
    owned = {fid: plan for fid, plan in plans.items() if fid != '13'}
    return config, device_id, signals, owned


def test_current_namespace_is_exclusively_recognized():
    config, did, signals, plans = _current()
    validated = validate_owned_push_commands(config, did, signals, plans)
    assert validated
    assert len(validated) == len(config['FubModules']['10'][did])


@pytest.mark.parametrize('unrecognized_name', [
    'UNKNOWN PUSH COMMAND',
    'CL Licht anderer Bereich IO-Ext-2/Q1',
    'CL Licht Quelle IO-Ext-9/Q1',
])
def test_unrecognized_names_are_rejected(unrecognized_name):
    config, did, signals, plans = _current()
    first = next(iter(config['FubModules']['10'][did].values()))
    first['Name'] = unrecognized_name
    with pytest.raises(AdminError, match='nicht eindeutig zuordenbar'):
        validate_owned_push_commands(config, did, signals, plans)


def test_present_but_renamed_own_command_is_not_accepted():
    config, did, signals, plans = _current()
    first = next(iter(config['FubModules']['10'][did].values()))
    first['Name'] = friendly_command_name(signals[0]) + ' ALIAS'
    with pytest.raises(AdminError, match='keine Bereinigung'):
        validate_owned_push_commands(config, did, signals, plans)


def test_duplicate_current_source_is_not_silently_accepted():
    config, did, signals, plans = _current()
    records = list(config['FubModules']['10'][did].items())
    name = records[0][1]['Name']
    records[1][1]['Name'] = name
    with pytest.raises(AdminError, match='Doppelter COMEXIO-Web-IO-Befehlsname'):
        validate_owned_push_commands(config, did, signals, plans)


def test_cleanup_does_not_write_if_unexpected_command_exists():
    admin, channels = setup_admin()
    first = next(iter(admin.config['FubModules']['10']['19'].values()))
    first['Name'] = 'UNRECOGNIZED COMMAND'
    async def go():
        with pytest.raises(AdminError, match='keine Bereinigung'):
            await _preflight(admin, ENTRY, channels, BASE)
        assert admin.writes == []
    asyncio.run(go())


def test_checkpoint_schema_requires_a_fresh_v041_job():
    assert CHECKPOINT_VERSION == 5
    assert CHECKPOINT_VERSION != 3
