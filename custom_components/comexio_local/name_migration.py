"""Read-only COMEXIO name migration inspection.

Writing to an undocumented COMEXIO rename endpoint is intentionally unsupported.
This inspection never re-creates a push plan or sends a COMEXIO command.
"""
from __future__ import annotations

from .push_labels import (command_candidates, friendly_command_name,
                          friendly_plan_name, plan_candidates)
from .push_setup import _find_push_device, _stable_groups, push_sources


def inspect_names(config: dict, channels: dict, entry_id: str) -> dict:
    prefix = 'CL' + entry_id[:8].upper()
    device_id, _ = _find_push_device(config, prefix)
    commands = ((config.get('FubModules') or {}).get('10') or {}).get(str(device_id), {}) if device_id else {}
    if not isinstance(commands, dict):
        commands = {}
    groups = _stable_groups(push_sources(channels))
    changes = []
    blockers = []
    expected: set[str] = set()
    for bucket, group in groups:
        old_plan_names = plan_candidates(prefix, bucket, group)
        matching_plans = [(fid, plan) for fid, plan in (config.get('Fubs') or {}).items()
                          if isinstance(plan, dict) and plan.get('Name') in old_plan_names]
        target_plan = friendly_plan_name(group, bucket)
        if len(matching_plans) != 1:
            blockers.append(f'Plan {target_plan}: not uniquely identified')
        else:
            fid, plan = matching_plans[0]
            if entry_id not in str(plan.get('Comment', '')):
                blockers.append(f'Plan {target_plan}: ownership unverified')
            elif plan['Name'] != target_plan:
                changes.append({'type': 'plan', 'id': str(fid), 'old': plan['Name'],
                                'new': target_plan, 'status': 'manual_pending_api'})
        for signal in group:
            target = friendly_command_name(signal)
            candidates = command_candidates(prefix, signal)
            matches = [(cid, item) for cid, item in commands.items()
                       if isinstance(item, dict) and item.get('Name') in candidates]
            if len(matches) != 1:
                blockers.append(f'{signal.key}: command not uniquely identified')
                continue
            cid, item = matches[0]
            if item['Name'] != target:
                changes.append({'type': 'command', 'id': str(cid), 'key': signal.key,
                                'old': item['Name'], 'new': target,
                                'status': 'manual_pending_api'})
            expected.add(target)
    # A target already used for a different object must not be migrated.
    for change in changes:
        if any(isinstance(obj, dict) and obj.get('Name') == change['new']
               for cid, obj in commands.items() if str(cid) != change['id']):
            blockers.append(f"Target name already used: {change['new']}")
        if change['type'] == 'plan' and any(
                isinstance(obj, dict) and obj.get('Name') == change['new']
                for fid, obj in (config.get('Fubs') or {}).items() if str(fid) != change['id']):
            blockers.append(f"Target plan name already used: {change['new']}")
    return {'changes': changes, 'blockers': sorted(set(blockers)),
            'write_supported': False,
            'note': 'Only a preview: COMEXIO rename endpoints are not yet verified.'}
