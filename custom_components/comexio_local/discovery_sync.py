"""Read-only COMEXIO discovery diff for a user-confirmed, manual refresh.

Never issue COMEXIO writes; compare physical addresses, not room labels.
"""
from __future__ import annotations
import hashlib
import json


def compare_catalog(previous: dict, current: dict, options: dict) -> dict:
    """Return a stable fingerprint of the entire read-only catalog comparison."""
    rows = []
    for key in sorted(set(previous) | set(current)):
        old = previous.get(key)
        new = current.get(key)
        if old is None:
            action = 'added'
        elif new is None:
            action = 'removed'
        elif old.kind != new.kind:
            action = 'type_changed'
        elif old.name != new.name:
            action = 'renamed'
        else:
            action = 'unchanged'
        rows.append({
            'key': key, 'action': action,
            'old_name': old.name if old else None,
            'new_name': new.name if new else None,
            'old_kind': old.kind if old else None,
            'new_kind': new.kind if new else None,
        })
    relevant_options = {k: options.get(k) for k in (
        'channel_kind_overrides', 'known_channel_kinds', 'cover_invert_default', 'cover_invert_overrides')}
    fingerprint = hashlib.sha256(json.dumps({
        'rows': rows, 'options': relevant_options,
    }, sort_keys=True).encode()).hexdigest()
    changed = [r for r in rows if r['action'] != 'unchanged']
    return {
        'fingerprint': fingerprint, 'rows': rows, 'changes': changed,
        'counts': {action: sum(r['action'] == action for r in rows)
                   for action in ('added', 'removed', 'renamed', 'type_changed')},
        'requires_manual_classification': any(r['action'] == 'type_changed' for r in rows),
    }
