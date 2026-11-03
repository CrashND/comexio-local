"""Explicit user-authorized COMEXIO-to-Home-Assistant area assignment.

No changes on discovery/startup. Never create HA areas or edit COMEXIO. The
preview is read-only; apply rechecks every registry state before writing.
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import re
import unicodedata
from typing import Any

from .constants import DOMAIN
from .discovery import Channel


def normalize_room(value: str) -> str:
    """Match German area names without guessing abbreviations."""
    value = value.casefold().replace('ae', '\u00e4').replace('oe', '\u00f6').replace('ue', '\u00fc')
    value = value.replace('\u00e4', 'ae').replace('\u00f6', 'oe').replace('\u00fc', 'ue').replace('\u00df', 'ss')
    value = unicodedata.normalize('NFKD', value)
    return re.sub(r'[^a-z0-9]', '', value.encode('ascii', 'ignore').decode('ascii'))


def room_for_channel(channel: Channel) -> str:
    if channel.kind == 'cover':
        return channel.name.removeprefix('Rollladen ').strip()
    return channel.plan.strip()


def match_area(room: str, areas: dict[str, tuple[str, ...]]) -> str | None:
    """Return a unique area match, otherwise never assume a location."""
    needle = normalize_room(room)
    if not needle:
        return None
    matches = [area_id for area_id, aliases in areas.items()
               if needle in {normalize_room(alias) for alias in aliases}]
    return matches[0] if len(matches) == 1 else None


@dataclass(frozen=True)
class AreaChange:
    key: str
    name: str
    entity_id: str | None
    room: str
    before: str | None
    before_explicit: str | None
    target: str | None
    action: str  # assign, unchanged, keep_existing, no_match, unavailable

    def as_dict(self) -> dict[str, Any]:
        return vars(self).copy()


def _registries(hass):
    from homeassistant.helpers import area_registry as ar, entity_registry as er
    return ar.async_get(hass), er.async_get(hass), er


def _area_index(area_registry) -> dict[str, tuple[str, ...]]:
    return {entry.id: (entry.name, *tuple(entry.aliases or ()))
            for entry in area_registry.areas.values()}


def _source_entries(channels, selected=None):
    all_channels = {k: c for k, c in channels.items() if c.kind in ('light', 'cover')}
    if selected is None:
        return list(all_channels.values())
    if not selected or len(selected) > 90 or any(key not in all_channels for key in selected):
        raise ValueError('Invalid or empty COMEXIO area selection')
    return [all_channels[k] for k in dict.fromkeys(selected)]


def preview_area_assignment(hass, entry, channels: dict[str, Channel], *,
                            selected: list[str] | None = None,
                            target_area: str | None = None,
                            overwrite: bool = False) -> dict[str, Any]:
    """Inspect known COMEXIO entities and HA areas, with no writes."""
    ar, registry, er = _registries(hass)
    area_index = _area_index(ar)
    if target_area is not None and target_area not in area_index:
        raise ValueError('Unknown Home Assistant area')
    rows: list[AreaChange] = []
    for channel in sorted(_source_entries(channels, selected), key=lambda c: (c.kind, c.name.casefold())):
        unique_id = f"{entry.unique_id or entry.entry_id}:{channel.key}"
        entity_id = registry.async_get_entity_id(channel.kind, DOMAIN, unique_id)
        entity = registry.async_get(entity_id) if entity_id else None
        if entity is None or entity.config_entry_id != entry.entry_id:
            rows.append(AreaChange(channel.key, channel.name, entity_id, room_for_channel(channel),
                                   None, None, target_area, 'unavailable'))
            continue
        current = er.async_get_effective_area_id(hass, entity)
        explicit = entity.area_id
        room = room_for_channel(channel)
        proposed = target_area if target_area is not None else match_area(room, area_index)
        if proposed is None:
            action = 'no_match'
        elif current == proposed:
            action = 'unchanged'
        elif explicit is not None and not overwrite:
            action = 'keep_existing'
        else:
            action = 'assign'
        rows.append(AreaChange(channel.key, channel.name, entity_id, room,
                               current, explicit, proposed, action))
    # Capture relevant entity state, proposals and all area aliases so stale UI
    # decisions cannot silently overwrite changes elsewhere in Home Assistant.
    fingerprint_data = {
        'entry_id': entry.entry_id,
        'areas': sorted((k, sorted(v)) for k, v in area_index.items()),
        'rows': [row.as_dict() for row in rows],
    }
    fingerprint = hashlib.sha256(json.dumps(fingerprint_data, sort_keys=True).encode()).hexdigest()
    return {
        'rows': [row.as_dict() for row in rows],
        'fingerprint': fingerprint,
        'assignments': sum(row.action == 'assign' for row in rows),
        'area_names': {k: v[0] for k, v in area_index.items()},
    }


def apply_area_assignment(hass, entry, channels: dict[str, Channel], *,
                          fingerprint: str, selected: list[str] | None = None,
                          target_area: str | None = None,
                          overwrite: bool = False, confirm: bool = False) -> dict:
    """Only a confirmed action, after an unchanged read-only preview."""
    if not confirm:
        raise ValueError('Explicit approval required')
    preview = preview_area_assignment(hass, entry, channels, selected=selected,
                                      target_area=target_area, overwrite=overwrite)
    if preview['fingerprint'] != fingerprint:
        raise ValueError('Area settings changed after preview; retry')
    _, registry, _ = _registries(hass)
    updates = [(row['entity_id'], row['target']) for row in preview['rows']
               if row['action'] == 'assign']
    # Validate the full write set before modifying any registry entries.
    for entity_id, area_id in updates:
        if not entity_id or registry.async_get(entity_id) is None or not area_id:
            raise ValueError('Entity or area missing during apply')
    for entity_id, area_id in updates:
        registry.async_update_entity(entity_id, area_id=area_id)
    return {'updated': len(updates), 'unchanged': len(preview['rows']) - len(updates)}
