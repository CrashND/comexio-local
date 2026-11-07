"""Compatibility, collision and read-only migration preview."""
from comexio_local.discovery import discover, extract_plan_assignments
from comexio_local.name_migration import inspect_names
from comexio_local.push_labels import (
    hardware_label, friendly_command_name, command_candidates,
    plan_candidates, friendly_plan_name,
)
from comexio_local.push_setup import _stable_groups, push_sources
from test_push_audit import _installed, ENTRY


def test_hardware_labels_and_new_names():
    assert hardware_label('IO-Ext-2') == 'E2'
    assert hardware_label('IO-Server-1') == 'S1'
    assert hardware_label('Universal-Aktor-4') != 'E4'
    cfg, plans, channels = _installed()
    for channel in push_sources(channels):
        new_name = friendly_command_name(channel)
        assert new_name.startswith('CL ')
        assert new_name in command_candidates('CLABCDEFGH', channel)
    assert len({friendly_command_name(c) for c in push_sources(channels)}) == 2


def test_legacy_and_033_names_are_recognized():
    cfg, plans, channels = _installed()
    prefix = 'CL' + ENTRY[:8].upper()
    for c in push_sources(channels):
        assert len(command_candidates(prefix, c))>=3
    for bucket, group in _stable_groups(push_sources(channels)):
        assert len(plan_candidates(prefix,bucket,group))>=4
        assert friendly_plan_name(group,bucket).startswith('CL Push')


def test_migration_preview_never_writes():
    cfg, plans, channels = _installed()
    result = inspect_names(cfg, channels, ENTRY)
    assert result['write_supported'] is False
    assert len(result['changes'])==4
    assert not result['blockers']
    assert all(row['old'] != row['new'] for row in result['changes'])
    assert {'plan','command'}=={row['type'] for row in result['changes']}


def test_discovery_does_not_take_managed_cl_plan_as_room():
    cfg, plans, channels=_installed()
    prefix = 'CL' + ENTRY[:8].upper()
    # Make managed push plan first to catch accidental room assignment.
    fid = next(iter(plans))
    fake_plans = {fid: plans[fid], '13': {'elements': {'1': {'reference': {'type': 1, 'ref_id': 4}}}}}
    result = extract_plan_assignments(fake_plans, cfg['Fubs'])
    assert result[(1,4)]=='Gaestezimmer'


def test_push_audit_reads_three_name_generations():
    from comexio_local.push_audit import audit_config
    from comexio_local.push_labels import (
        legacy_friendly_command_name, legacy_friendly_plan_name,
    )
    from test_push_audit import PATH, BASE
    for style in ('legacy', 'ha_033', 'cl_034'):
        cfg, plans, channels = _installed()
        sources = push_sources(channels)
        prefix = 'CL' + ENTRY[:8].upper()
        for bucket, group in _stable_groups(sources):
            original_plan = f'{prefix} {bucket}'
            for fid, plan in cfg['Fubs'].items():
                if plan['Name'] == original_plan:
                    if style == 'ha_033':
                        plan['Name'] = legacy_friendly_plan_name(group, bucket)
                    elif style == 'cl_034':
                        plan['Name'] = friendly_plan_name(group, bucket)
                    break
        for signal in sources:
            original = command_candidates(prefix, signal)[0]
            for cmd in cfg['FubModules']['10']['19'].values():
                if cmd['Name'] == original:
                    if style == 'ha_033':
                        cmd['Name'] = command_candidates(prefix, signal)[1]
                    elif style == 'cl_034':
                        cmd['Name'] = friendly_command_name(signal)
                    break
        report = audit_config(cfg, plans, channels, ENTRY, PATH, BASE)
        assert report.linked == report.sources == len(sources), (style, report.as_dict())
        assert not report.errors, (style, report.errors)
        assert not report.missing_commands


def test_existing_new_names_do_not_need_migration():
    cfg, plans, channels = _installed()
    sources = push_sources(channels)
    prefix = 'CL' + ENTRY[:8].upper()
    for bucket, group in _stable_groups(sources):
        original_plan = f'{prefix} {bucket}'
        for plan in cfg['Fubs'].values():
            if plan['Name'] == original_plan:
                plan['Name'] = friendly_plan_name(group, bucket)
                break
    for signal in sources:
        original = command_candidates(prefix, signal)[0]
        for cmd in cfg['FubModules']['10']['19'].values():
            if cmd['Name'] == original:
                cmd['Name'] = friendly_command_name(signal)
                break
    report = inspect_names(cfg, channels, ENTRY)
    assert report['changes'] == []
    assert not report['blockers']
