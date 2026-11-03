"""Stable, human-readable labels for *new* COMEXIO Local push resources.

Legacy CL-prefixed names stay discoverable and are never silently renamed.
"""
from __future__ import annotations

import re
import unicodedata
import zlib

from .admin_api import command_name
from .discovery import Channel


def _slug(value: str, max_len: int = 14) -> str:
    ascii_text = unicodedata.normalize('NFKD', value).encode('ascii', 'ignore').decode('ascii')
    text = re.sub(r'[^A-Za-z0-9]+', ' ', ascii_text).strip()
    return (text[:max_len].rstrip() or 'Quelle')


def friendly_command_name(signal: Channel) -> str:
    """Keep unique addresses in each readable name; max ~35 characters."""
    if signal.kind == 'cover':
        marker = f'M{signal.marker_id}'
        room = signal.name.removeprefix('Rollladen ').strip()
        return f'HA Rollo {_slug(room, 15)} {marker}'
    room = signal.plan or signal.name or signal.extension
    suffix = re.search(r'(\d+)$', signal.extension)
    ext = (('E' if 'Ext' in signal.extension else 'S') + suffix.group(1)) if suffix else _slug(signal.extension, 5)
    return f'HA Licht {_slug(room, 12)} {signal.identifier} {ext}'


def command_candidates(prefix: str, signal: Channel) -> tuple[str, ...]:
    legacy = command_name(prefix, signal)
    friendly = friendly_command_name(signal)
    return (legacy,) if legacy == friendly else (legacy, friendly)


def friendly_plan_name(group: list[Channel], bucket: str) -> str:
    """Group identity is computed independently of other modules."""
    suffix = int(bucket.rsplit('-', 1)[-1]) + 1
    if group[0].kind == 'cover':
        return f'HA Push Rollladen {suffix}'
    extension = group[0].extension
    label = extension if re.fullmatch(r'[A-Za-z0-9-]{1,17}', extension) else _slug(extension, 17)
    # Avoid names colliding after normalization/truncation.
    if len(extension) > 17:
        label = _slug(extension, 11) + f'{zlib.crc32(extension.encode()):04X}'[-4:]
    return f'HA Push {label} {suffix}'


def plan_candidates(prefix: str, bucket: str, group: list[Channel]) -> tuple[str, ...]:
    old = f'{prefix} {bucket}'
    new = friendly_plan_name(group, bucket)
    return (old,) if old == new else (old, new)
