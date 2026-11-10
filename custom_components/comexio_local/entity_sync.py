"""Plan and validate a manual Home Assistant entity-registry reconciliation.

Never performs writes: this module can also be tested without Home Assistant.
Only registry entries that *both* belong to our config entry and match the
established physical COMEXIO unique-ID prefix are candidates for removal.
"""
from __future__ import annotations

from dataclasses import asdict
import hashlib
import json

from .constants import DOMAIN

VISIBLE_DOMAINS = {
    'light': 'light', 'switch': 'switch', 'relay': 'binary_sensor',
    'binary_input': 'binary_sensor', 'cover': 'cover',
    'enocean_sensor': 'sensor',
}


def entity_domain(kind: str | None) -> str | None:
    return VISIBLE_DOMAINS.get(kind)


def unique_id_for(entry, key: str) -> str:
    return f'{entry.unique_id or entry.entry_id}:{key}'


def physical_key(entry, unique_id: str) -> str | None:
    prefix = f'{entry.unique_id or entry.entry_id}:'
    if not isinstance(unique_id, str) or not unique_id.startswith(prefix):
        return None
    key = unique_id[len(prefix):]
    return key if key.startswith(('io:', 'cover:')) else None


def owned_registry_rows(entry, registry_rows) -> list:
    return [item for item in registry_rows
            if item.config_entry_id == entry.entry_id
            and item.platform == DOMAIN
            and physical_key(entry, item.unique_id) is not None]


def _registry_row(item) -> dict:
    return {
        'entity_id': item.entity_id, 'unique_id': item.unique_id,
        'domain': item.domain, 'platform': item.platform,
        'config_entry_id': item.config_entry_id,
        'name': item.name, 'area_id': item.area_id,
        'icon': getattr(item, 'icon', None),
        'labels': sorted(getattr(item, 'labels', ()) or ()),
        'disabled_by': str(getattr(item, 'disabled_by', None)),
        'hidden_by': str(getattr(item, 'hidden_by', None)),
    }


def build_entity_plan(entry, previous: dict, current: dict, options: dict,
                      registry_rows, *, foreign_ids: dict | None = None) -> dict:
    """Produce a deterministic, non-destructive plan using a *complete* read.

    A relay/input class change inside binary_sensor needs a platform reload,
    but not a registry deletion. For cross-domain changes, the old entity must
    be removed explicitly; its previous entity_id cannot survive that change.
    """
    from .discovery_sync import compare_catalog

    rows = sorted(owned_registry_rows(entry, registry_rows), key=lambda x: x.entity_id)
    seen = set()
    blockers = []
    removals = []
    keep = []
    for item in rows:
        key = physical_key(entry, item.unique_id)
        expected = entity_domain(current[key].kind) if key in current else None
        if item.entity_id in seen:
            blockers.append('Doppelter Registry-Eintrag: ' + item.entity_id)
            continue
        seen.add(item.entity_id)
        if expected is None or expected != item.domain:
            removals.append({
                **_registry_row(item), 'source': key,
                'replacement_domain': expected,
                'reason': 'entfernt' if expected is None else 'Domänenwechsel',
                'manual_settings': bool(item.name or item.area_id or
                                        getattr(item, 'icon', None) or
                                        getattr(item, 'labels', None)),
                'manual_follow_up': bool(getattr(item, 'disabled_by', None) or
                                         getattr(item, 'hidden_by', None)),
            })
        else:
            keep.append(item.entity_id)

    wanted = {(entity_domain(c.kind), unique_id_for(entry, key))
              for key, c in current.items() if entity_domain(c.kind) is not None}
    if foreign_ids:
        for (domain, uid), external_entry in foreign_ids.items():
            if (domain, uid) in wanted and external_entry != entry.entry_id:
                blockers.append('Fremder Registry-Eintrag für erwartete Quelle: ' + uid)

    catalog = compare_catalog(previous, current, options)
    signature = {
        'catalog': catalog['fingerprint'],
        'full_previous': [asdict(c) for _, c in sorted(previous.items())],
        'full_current': [asdict(c) for _, c in sorted(current.items())],
        'registry': [_registry_row(item) for item in rows],
        'options': options,
    }
    fingerprint = hashlib.sha256(json.dumps(signature, sort_keys=True,
                                            default=str).encode()).hexdigest()
    return {
        **catalog, 'fingerprint': fingerprint,
        'registry_removals': removals, 'registry_keep': keep,
        'registry_count': len(rows), 'blockers': blockers,
        'requires_confirmation': bool(catalog['changes'] or removals),
        'reload_required': bool(catalog['changes'] or removals),
    }


def registry_rows_for_entry(hass, entry):
    from homeassistant.helpers import entity_registry as er
    registry = er.async_get(hass)
    return registry, er.async_entries_for_config_entry(registry, entry.entry_id)


def verify_registry_candidates(registry, entry, removals: list[dict]) -> None:
    """Preflight all destructive operations; no partial writes on preflight errors."""
    for row in removals:
        original = registry.async_get(row['entity_id'])
        if (original is None or original.config_entry_id != entry.entry_id
                or original.platform != DOMAIN or original.unique_id != row['unique_id']
                or original.domain != row['domain']
                or _registry_row(original) != {k: row[k] for k in _registry_row(original)}):
            raise ValueError('Registry-Eintrag seit Vorschau geändert: ' + row['entity_id'])


def saved_user_choices(removals: list[dict], current: dict) -> dict:
    """Carry user-assigned name/area through cross-domain replacement only."""
    return {row['source']: {'name': row['name'], 'area_id': row['area_id'],
                            'icon': row['icon'], 'labels': row['labels']}
            for row in removals if row['replacement_domain'] is not None
            and row['source'] in current and row['manual_settings']}
