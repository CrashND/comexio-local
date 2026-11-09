"""No unexpected command can be ignored by push setup, repair or diagnostics."""
from __future__ import annotations

import asyncio
from copy import deepcopy

import pytest

from comexio_local.admin_api import AdminError
from comexio_local.managed_resources import verify_current_push_inventory
from comexio_local.push_audit import audit_config
from comexio_local.push_setup import configure_push, push_sources, _device_base_id
from comexio_local.push_repair import inspect_push_repair
from comexio_local.name_inspection import inspect_names
from test_push_audit import _installed, ENTRY, PATH, BASE
from test_push_rebuild import AdminFake


def _extra():
    config, plans, channels = _installed()
    config['FubModules']['10']['19']['999'] = {
        'Name': 'INVENTORY EXTRA RECORD', 'TypeId': 1, 'Id': 999,
        'WebDeviceId': 19,
    }
    return config, plans, channels


def test_extra_blocks_all_current_inventory_modes():
    config, _, channels = _extra()
    with pytest.raises(AdminError, match='Zusätzlicher Befehl.*999'):
        verify_current_push_inventory(config, '19', push_sources(channels))
    with pytest.raises(AdminError, match='Zusätzlicher Befehl.*999'):
        verify_current_push_inventory(config, '19', push_sources(channels),
                                      require_complete=True)


def test_push_diagnosis_does_not_ignore_or_repeat_unrecognized_names():
    config, plans, channels = _extra()
    report = audit_config(config, plans, channels, ENTRY, PATH, BASE)
    assert report.errors
    assert '999' in str(report.errors)
    assert 'INVENTORY EXTRA RECORD' not in str(report.as_dict())
    names = inspect_names(config, channels, ENTRY)
    assert any('ID 999' in line for line in names['blockers'])
    assert 'INVENTORY EXTRA RECORD' not in str(names)


def test_configure_push_stops_before_any_write_on_extra_record():
    config, plans, channels = _extra()
    admin = AdminFake(config, plans)
    async def go():
        with pytest.raises(AdminError, match='Zusätzlicher Befehl'):
            await configure_push(admin, channels, ENTRY, PATH, BASE)
        assert admin.writes == []
    asyncio.run(go())


def test_repair_preview_blocks_extra_record_even_if_source_selected():
    config, plans, channels = _extra()
    admin = AdminFake(config, plans)
    async def go():
        with pytest.raises(AdminError, match='Zusätzlicher Befehl'):
            await inspect_push_repair(admin, channels, ENTRY, PATH, BASE,
                                      [push_sources(channels)[0].key], mode='repair')
        assert admin.writes == []
    asyncio.run(go())


@pytest.mark.parametrize('bad', [None, '', 0, 'not-a-base', True, -1])
def test_base_id_must_come_from_exact_device_not_template_name(bad):
    config, _, _ = _installed()
    config['WebDevices']['19']['WebDeviceBaseId'] = bad
    with pytest.raises(AdminError, match='BaseId'):
        _device_base_id(config, '19')


def test_noncanonical_type_is_rejected_by_current_inventory():
    config, _, channels = _installed()
    cmd = next(iter(config['FubModules']['10']['19'].values()))
    cmd['TypeId'] = 99
    with pytest.raises(AdminError, match='TypeId'):
        verify_current_push_inventory(config, '19', push_sources(channels))


def test_unnamed_additional_command_is_not_ignored():
    config, _, channels = _installed()
    config['FubModules']['10']['19']['999'] = {'TypeId': 1}
    with pytest.raises(AdminError, match='unvollständige Befehle'):
        verify_current_push_inventory(config, '19', push_sources(channels))
