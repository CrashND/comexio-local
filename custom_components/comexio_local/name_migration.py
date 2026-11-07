"""Read-only COMEXIO name migration inspection.

Writing to an undocumented COMEXIO rename endpoint is intentionally unsupported.
This inspection never re-creates a push plan or sends a COMEXIO command.
"""
from __future__ import annotations

from .managed_resources import is_owned_plan
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
    for bucket, group in groups:
        old_plan_names = plan_candidates(prefix, bucket, group)
        matching_plans = [(fid, plan) for fid, plan in (config.get('Fubs') or {}).items()
                          if isinstance(plan, dict) and plan.get('Name') in old_plan_names]
        target_plan = friendly_plan_name(group, bucket)
        if len(matching_plans) != 1:
            blockers.append(f'Plan {target_plan}: not uniquely identified')
        else:
            fid, plan = matching_plans[0]
            if not is_owned_plan(plan, entry_id, 'push'):
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
    # Command and plan labels live in different COMEXIO namespaces.  Only
    # same-kind collisions matter; a command may legitimately share a label
    # with a plan without blocking a read-only migration preview.
    for change in changes:
        family = commands if change['type'] == 'command' else (config.get('Fubs') or {})
        if any(isinstance(obj, dict) and obj.get('Name') == change['new']
               for rid, obj in family.items() if str(rid) != change['id']):
            blockers.append(f"Target {change['type']} name already used: {change['new']}")
    proposed: dict[tuple[str, str], str] = {}
    for change in changes:
        key = (change['type'], change['new'])
        if key in proposed and proposed[key] != change['id']:
            blockers.append(f"Target {change['type']} name proposed twice: {change['new']}")
        proposed[key] = change['id']
    return {'changes': changes, 'blockers': sorted(set(blockers)),
            'write_supported': False,
            'note': 'Only a preview: COMEXIO rename endpoints are not yet verified.'}
