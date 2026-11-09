"""Read-only checking of a single readable CL naming convention."""
from copy import deepcopy

from comexio_local.discovery import extract_plan_assignments
from comexio_local.name_inspection import inspect_names
from comexio_local.push_labels import friendly_command_name, friendly_plan_name, readable_hardware_name
from comexio_local.push_setup import _stable_groups, push_sources
from test_push_audit import _installed, ENTRY


def test_every_push_resource_has_canonical_readable_label():
    config, _, channels = _installed()
    assert readable_hardware_name('IO-Ext-2') == 'IO-Ext-2'
    names = [friendly_command_name(c) for c in push_sources(channels)]
    assert len(set(names)) == len(names)
    assert all(name.startswith('CL ') and ENTRY[:8].upper() not in name for name in names)
    plans = [friendly_plan_name(group, bucket) for bucket, group
             in _stable_groups(push_sources(channels))]
    assert len(set(plans)) == len(plans)
    assert all(p.startswith('CL Push ') for p in plans)


def test_inspection_reports_canonical_resources_and_no_migration():
    config, _, channels = _installed()
    result = inspect_names(config, channels, ENTRY)
    assert result['write_supported'] is False
    assert result['missing'] == []
    assert result['blockers'] == []
    assert len(result['found']) >= 5


def test_owned_nonnormalized_plan_is_not_treated_as_current():
    config, _, channels = _installed()
    plan_id = next(k for k,v in config['Fubs'].items() if v['Name'].startswith('CL Push'))
    config['Fubs'][plan_id]['Name'] = 'Nicht verwaltete Funktion'
    result = inspect_names(config, channels, ENTRY)
    assert any('außerhalb' in msg for msg in result['blockers'])
    assert result['missing']


def test_discovery_does_not_infer_room_from_own_cl_plan():
    config, plans, channels = _installed()
    fid = next(iter(plans))
    fake_plans = {fid: plans[fid], '13': {'elements': {
        '1': {'reference': {'type': 1, 'ref_id': 4}}}}}
    assignment = extract_plan_assignments(fake_plans, config['Fubs'])
    assert assignment[(1, 4)] == 'Gaestezimmer'


def test_inspection_does_not_mutate_config():
    config, _, channels = _installed()
    before = deepcopy(config)
    inspect_names(config, channels, ENTRY)
    assert config == before


def test_name_inspection_rejects_foreign_plan_with_canonical_name():
    config, _, channels = _installed()
    fid = next(i for i, m in config['Fubs'].items() if m.get('Name', '').startswith('CL Push '))
    config['Fubs'][fid]['Comment'] = 'Fremde Konfiguration'
    report = inspect_names(config, channels, ENTRY)
    assert any('Fremder Plan mit erwartetem Push-Namen' in issue
               for issue in report['blockers'])


def test_input_inspection_rejects_duplicate_input_plan():
    from comexio_local.managed_resources import plan_comment
    from comexio_local.input_push import _groups
    from test_input_push_0363 import with_inputs
    from test_discovery import _config
    from comexio_local.discovery import discover
    config, _, channels = _installed()
    raw = discover(with_inputs(_config()))
    name = next(iter(_groups(raw, ENTRY).values()))[0]
    for fid in ('899', '900'):
        config['Fubs'][fid] = {'Name': name, 'Comment': plan_comment(ENTRY, 'input')}
    result = inspect_names(config, channels, ENTRY, raw_channels=raw)
    assert any('Doppelter eigener Eingangsplan' in b for b in result['blockers'])
