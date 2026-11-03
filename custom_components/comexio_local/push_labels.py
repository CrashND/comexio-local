"""Stable, human-readable labels for COMEXIO Local-owned push resources.

Legacy CL names and 0.3.3 HA names remain valid identities. Never infer
resource ownership from a human-readable label alone.
"""
from __future__ import annotations

import re
import unicodedata
import zlib

from .admin_api import command_name
from .discovery import Channel


def _slug(value: str, max_len: int = 14) -> str:
    value = unicodedata.normalize('NFKD', value).encode('ascii', 'ignore').decode('ascii')
    text = re.sub(r'[^A-Za-z0-9]+', ' ', value).strip()
    if len(text) > max_len:
        # A suffix avoids collapsing different long room names into identical ones.
        return text[:max_len - 5].rstrip() + '-' + f'{zlib.crc32(text.encode()):08X}'[:4]
    return text or 'Quelle'


def hardware_label(extension: str) -> str:
    """Format only known COMEXIO addresses; don't guess module classes."""
    ext = re.fullmatch(r'IO-Ext-(\d+)', extension, re.I)
    if ext:
        return f'E{ext.group(1)}'
    server = re.fullmatch(r'IO-Server-(\d+)', extension, re.I)
    if server:
        return f'S{server.group(1)}'
    return _slug(extension, 15)


def _legacy_slug(value: str, max_len: int = 14) -> str:
    ascii_text = unicodedata.normalize('NFKD', value).encode('ascii', 'ignore').decode('ascii')
    text = re.sub(r'[^A-Za-z0-9]+', ' ', ascii_text).strip()
    return text[:max_len].rstrip() or 'Quelle'


def legacy_friendly_command_name(signal: Channel) -> str:
    """0.3.3 naming retained to recognize existing objects after upgrade."""
    if signal.kind == 'cover':
        room = signal.name.removeprefix('Rollladen ').strip()
        return f'HA Rollo {_legacy_slug(room, 15)} M{signal.marker_id}'
    room = signal.plan or signal.name or signal.extension
    suffix = re.search(r'(\d+)$', signal.extension)
    ext = (('E' if 'Ext' in signal.extension else 'S') + suffix.group(1)) if suffix else _legacy_slug(signal.extension, 5)
    return f'HA Licht {_legacy_slug(room, 12)} {signal.identifier} {ext}'


def friendly_command_name(signal: Channel) -> str:
    """New v0.3.4 convention: CL [type] [room] [hardware/channel]."""
    if signal.kind == 'cover':
        room = _slug(signal.name.removeprefix('Rollladen ').strip(), 16)
        return f'CL Rollladen {room} M{signal.marker_id}'
    room = _slug(signal.plan or signal.name or signal.extension, 16)
    return f'CL Licht {room} {hardware_label(signal.extension)}/{signal.identifier}'


def command_candidates(prefix: str, signal: Channel) -> tuple[str, ...]:
    return tuple(dict.fromkeys((command_name(prefix, signal),
                               legacy_friendly_command_name(signal),
                               friendly_command_name(signal))))


def legacy_friendly_plan_name(group: list[Channel], bucket: str) -> str:
    """0.3.3 naming retained for compatibility."""
    suffix = int(bucket.rsplit('-', 1)[-1]) + 1
    if group[0].kind == 'cover':
        return f'HA Push Rollladen {suffix}'
    extension = group[0].extension
    label = extension if re.fullmatch(r'[A-Za-z0-9-]{1,17}', extension) else _legacy_slug(extension, 17)
    if len(extension) > 17:
        label = _legacy_slug(extension, 11) + f'{zlib.crc32(extension.encode()):04X}'[-4:]
    return f'HA Push {label} {suffix}'


def friendly_plan_name(group: list[Channel], bucket: str) -> str:
    chunk = int(bucket.rsplit('-', 1)[-1]) + 1
    kind = 'Rolllaeden' if group[0].kind == 'cover' else hardware_label(group[0].extension)
    return f'CL Push {kind}' + (f'-{chunk}' if chunk > 1 else '')


def plan_candidates(prefix: str, bucket: str, group: list[Channel]) -> tuple[str, ...]:
    return tuple(dict.fromkeys((f'{prefix} {bucket}',
                               legacy_friendly_plan_name(group, bucket),
                               friendly_plan_name(group, bucket))))
