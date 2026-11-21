"""v0.4.10: typed plans, additive extensions, 2G write containment.

Firmware and Home Assistant are not available here; these are offline mocks.
"""
from __future__ import annotations

import asyncio
from copy import deepcopy

import pytest

from comexio_local.admin_api import AdminError
from comexio_local.discovery import discover
from comexio_local.input_push import _groups, _enocean_category, apply_input_push, inspect_input_push
from comexio_local.managed_resources import plan_comment
from test_enocean_044 import enocean_config
from test_input_push_0363 import InputAdminFake
from test_push_audit import ENTRY, PATH, BASE, _installed


class CoordinateInputAdmin(InputAdminFake):
    def __init__(self, config, plans=None):
        super().__init__(config, plans)
        self.coordinates = []

    async def add_element(self, fid, ref, typ, x, y, connection=None, *, name=''):
        result = await super().add_element(fid, ref, typ, x, y, connection, name=name)
        self.coordinates.append((fid, ref, typ, x, y))
        self.plans[str(fid)]['elements'][str(result)].update(
            {'position_x': x, 'position_y': y})
        return result


def extra_contacts(config, last_slot: int):
    config = deepcopy(config)
    records = config['FubModules']['1']['9']['inoutput']
    for slot in range(8, last_slot + 1):
        ident = f'EI{slot}_CO'
        records[str(300 + slot)] = {'Id': 300 + slot, 'Identifier': ident,
                                    'Description': 'Neuer Kontakt', 'Active': 1,
                                    'InOutputTypeId': 23, 'ConnectionType': 1,
                                    'IntIsOutput': 0}
    return config


def test_metadata_typeid_is_not_confused_with_sensor_function():
    raw = discover(enocean_config())
    grouping = _groups(raw, ENTRY)
    assert len({row[0] for row in grouping.values() if 'EnOcean/' in row[1][0].key}) == 5
    assert grouping['io:EnOcean/EI2_PIRS'][0] == grouping['io:EnOcean/EI3_PIRS'][0]
    assert raw['io:EnOcean/EI2_PIRS'].analog is True
    assert raw['io:EnOcean/EI3_PIRS'].analog is False
    assert _enocean_category(raw['io:EnOcean/EI2_PIRS']) == 'Bewegung'
    assert grouping['io:EnOcean/EI5_CO'][0] == 'CL Eingänge EnOcean Kontakte'
    assert grouping['io:EnOcean/EI7_A0'][0] == 'CL Eingänge EnOcean Taster'


def test_many_later_contacts_share_one_plan_and_never_reposition_existing(monkeypatch):
    from comexio_local import input_push
    config, protected_plans, _ = _installed()
    config['FubModules']['1']['9'] = extra_contacts(enocean_config(), 27)['FubModules']['1']['9']
    admin = CoordinateInputAdmin(config, protected_plans)
    original_light_plans = deepcopy(admin.plans)
    original_light_commands = deepcopy(admin.config['FubModules']['10']['19'])
    raw = discover(admin.config)
    all_contacts = {key: 'auto' for key, c in raw.items()
                    if c.is_enocean and c.enocean_signal == 'CO'}
    assert len(all_contacts) == 21
    assert {row[0] for key, row in _groups(raw, ENTRY).items() if key in all_contacts} == {
        'CL Eingänge EnOcean Kontakte'}

    async def append(fake, device_id, base_id, command):
        fake.writes.append(('append', command['Name'], fake.write_gap))
        fake.next_cmd += 1
        fake.config['FubModules']['10'][str(device_id)][str(fake.next_cmd)] = deepcopy(command)

    monkeypatch.setattr(input_push, '_append_command', append)

    async def go():
        # Initial setup with two sources, then a later expanded discovery pass.
        initial = {key: 'auto' for key in all_contacts
                   if key.endswith(('EI5_CO', 'EI8_CO'))}
        first = await inspect_input_push(admin, raw, ENTRY, PATH, BASE, initial)
        result = await apply_input_push(admin, raw, ENTRY, PATH, BASE,
                                        initial, first['fingerprint'], True)
        assert result['verified'] == 2
        assert result['activated_plans'] == 1
        old_positions = list(admin.coordinates)
        old_elements = deepcopy({pid: value for pid, value in admin.plans.items()
                                 if pid not in original_light_plans})
        assert len(old_elements) == 1

        later = await inspect_input_push(admin, raw, ENTRY, PATH, BASE, all_contacts)
        assert later['plan_count'] == 1
        assert sum(row['action'] == 'vorhanden' for row in later['sources']) == 2
        result = await apply_input_push(admin, raw, ENTRY, PATH, BASE,
                                        all_contacts, later['fingerprint'], True)
        assert result['verified'] == 21
        assert result['added_links'] == 19
        assert len([w for w in admin.writes if w[0] == 'plan'
                    and w[1] == 'CL Eingänge EnOcean Kontakte']) == 1
        assert admin.coordinates[:len(old_positions)] == old_positions
        pairs = [row for row in admin.coordinates if row[2] == 1]
        assert len(pairs) == 21
        assert len({(row[3],row[4]) for row in pairs}) == 21
        # Signals 19, 20 and 21 flow into the next column, not row 1 again.
        assert pairs[18][3] > pairs[0][3]
        assert all(admin.plans[pid] == plan for pid, plan in original_light_plans.items())
        assert admin.config['FubModules']['10']['19'] == original_light_commands
        again = await inspect_input_push(admin, raw, ENTRY, PATH, BASE, all_contacts)
        assert all(row['action'] == 'vorhanden' for row in again['sources'])
        writes = len(admin.writes)
        await apply_input_push(admin, raw, ENTRY, PATH, BASE,
                               all_contacts, again['fingerprint'], True)
        assert len(admin.writes) == writes
    asyncio.run(go())


def test_legacy_owned_ei_slot_plan_blocks_migration_before_writes():
    config = enocean_config()
    config['Fubs']['555'] = {'Name':'CL Eingänge EnOcean EI5',
                             'Comment':plan_comment(ENTRY, 'input'), 'Active':1}
    admin = CoordinateInputAdmin(config)
    raw = discover(config)
    async def go():
        with pytest.raises(AdminError, match='außerhalb des aktuellen Namensschemas'):
            await inspect_input_push(admin, raw, ENTRY, PATH, BASE,
                                     {'io:EnOcean/EI5_CO':'auto'})
        assert admin.writes == []
    asyncio.run(go())


def test_unknown_suffixes_fall_back_to_transport_based_other_plans():
    config = extra_contacts(enocean_config(), 8)
    records = config['FubModules']['1']['9']['inoutput']
    records['880']={'Id':880,'Identifier':'EI40_HUM', 'Active':1,
                    'InOutputTypeId':22,'ConnectionType':2}
    records['881']={'Id':881,'Identifier':'EI41_ALARM','Active':1,
                    'InOutputTypeId':23,'ConnectionType':1}
    plans = _groups(discover(config),ENTRY)
    assert plans['io:EnOcean/EI40_HUM'][0] == 'CL Eingänge EnOcean Weitere Analogsignale'
    assert plans['io:EnOcean/EI41_ALARM'][0] == 'CL Eingänge EnOcean Weitere Digitalsignale'
