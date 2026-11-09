"""One canonical, readable namespace for COMEXIO Local push resources.

All generated labels follow this one current schema.
Ownership is verified separately using the COMEXIO plan comment.
"""
from __future__ import annotations

import re

from .discovery import Channel

PREFERRED_PUSH_CLASS = 'CL Push Home Assistant'


def readable_hardware_name(extension: str) -> str:
    """Use the full known module address; avoid opaque hardware abbreviations."""
    if re.fullmatch(r'IO-(?:Ext|Server)-\d+', extension, re.I):
        return extension
    text = re.sub(r'[^\w -]+', ' ', extension, flags=re.UNICODE).strip()
    return ' '.join(text.split())[:32].rstrip() or 'COMEXIO-Modul'


def _readable_room(value: str) -> str:
    """Keep useful context while the physical address ensures uniqueness."""
    text = re.sub(r'[^\w -]+', ' ', value, flags=re.UNICODE).strip()
    text = ' '.join(text.split())
    if len(text) > 32:
        text = text[:32].rsplit(' ', 1)[0] or text[:32]
    return text or 'Quelle'


def friendly_command_name(signal: Channel) -> str:
    """Stable canonical COMEXIO command label, independent of HA entry IDs."""
    if signal.kind == 'cover':
        room = _readable_room(signal.name.removeprefix('Rollladen ').strip())
        return f'CL Rollladen {room} M{signal.marker_id}'
    room = _readable_room(signal.plan or signal.name or signal.extension)
    kind = {'switch': 'Schalter', 'relay': 'Status'}.get(signal.kind, 'Licht')
    return f'CL {kind} {room} {readable_hardware_name(signal.extension)}/{signal.identifier}'


def friendly_plan_name(group: list[Channel], bucket: str) -> str:
    """Only the canonical, address-stable physical range is a plan identity."""
    if not group or not bucket:
        raise ValueError('Leere COMEXIO-Quellgruppe')
    return f'CL Push {bucket}'
