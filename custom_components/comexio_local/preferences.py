"""Validated, persistent Home Assistant preferences; never write to COMEXIO."""
from __future__ import annotations
from dataclasses import replace

from .discovery import Channel

COVER_DEFAULT = 'cover_invert_default'
COVER_OVERRIDES = 'cover_invert_overrides'
CHANNEL_KINDS = 'channel_kind_overrides'
KNOWN_KINDS = 'known_channel_kinds'
CLASSIFICATION_AREAS = 'classification_areas'
USER_KINDS = ('light', 'switch', 'relay')
AUTO_KINDS = ('light', 'relay', 'motor')


def is_classifiable(channel: Channel) -> bool:
    """Never enable direct writing of COMEXIO motor control relays."""
    return (channel.key.startswith('io:') and channel.identifier.upper().startswith('Q')
            and channel.identifier[1:].isdigit() and channel.kind in (*USER_KINDS,))


def configured_kind(options: dict, channel: Channel) -> str:
    """Explicit choice wins, then sticky initial classification, then live detection."""
    if channel.kind == 'motor' or options.get(KNOWN_KINDS, {}).get(channel.key) == 'motor':
        return 'motor'  # fail closed: protect observed motor relays even after a rename
    chosen = options.get(CHANNEL_KINDS, {}).get(channel.key)
    if chosen in USER_KINDS and is_classifiable(channel):
        return chosen
    old = options.get(KNOWN_KINDS, {}).get(channel.key)
    if old in USER_KINDS and is_classifiable(channel):
        return old
    return channel.kind


def apply_classifications(channels: dict[str, Channel], options: dict) -> dict[str, Channel]:
    results = {}
    for key, channel in channels.items():
        kind = configured_kind(options, channel)
        results[key] = replace(channel, kind=kind, manually_classified=(key in options.get(CHANNEL_KINDS, {})))
    return results


def cover_is_inverted(options: dict, key: str) -> bool:
    overrides = options.get(COVER_OVERRIDES, {})
    if key in overrides and type(overrides[key]) is bool:
        return overrides[key]
    return options.get(COVER_DEFAULT, False) is True


def ha_cover_position(value: float | None, inverted: bool) -> int | None:
    if value is None:
        return None
    raw = max(0.0, min(100.0, float(value)))
    return round(100 - raw if inverted else raw)


def comexio_cover_target(ha_position: float, inverted: bool) -> float:
    position = float(ha_position)
    if not 0 <= position <= 100:
        raise ValueError('Cover position must be between 0 and 100')
    return 100.0 - position if inverted else position


def pin_existing_kinds(raw: dict[str, Channel], options: dict) -> dict:
    """Remember the original auto-detection, so renames cannot change domains silently."""
    result = dict(options.get(KNOWN_KINDS, {}))
    for key, channel in raw.items():
        if channel.kind in AUTO_KINDS and key.startswith('io:'):
            result.setdefault(key, channel.kind)
    return result
