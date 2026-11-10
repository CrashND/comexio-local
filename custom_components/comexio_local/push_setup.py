"""Explicit, incremental Web-IO push installation.

Unlike an unrestricted full sync, only confirmed light outputs and actual cover
position markers are linked. Never touches the original user room plans.
"""
from __future__ import annotations
import re
from .admin_api import AdminError, ComexioAdmin, web_device_base_id
from .webio_command import WebIOCommand
from .discovery import Channel
from .push_labels import PREFERRED_PUSH_CLASS, friendly_command_name, friendly_plan_name, readable_hardware_name
from .managed_resources import (find_unique_named_plan, unique_webio_commands)
from .managed_graph import PLAN_ROWS, ensure_webio_link, plan_elements as _plan_elements
from .push_target import private_lan_host_port

MAX_SIGNALS_PER_PLAN=PLAN_ROWS


def push_sources(channels: dict[str, Channel]) -> list[Channel]:
    return sorted((c for c in channels.values() if c.is_push_source and not c.is_enocean and c.kind != "binary_input"),key=lambda c:c.key)


def _stable_plan_slot(signal: Channel) -> int:
    """Immutable 0..17 drawing row derived from the physical Q/marker ID."""
    if signal.kind == 'cover':
        number = signal.marker_id
        if number is None or number < 1:
            raise AdminError('Ungültige Rollladen-Istpositions-Merker-ID')
    else:
        match = re.fullmatch(r'Q(\d+)', signal.identifier, re.I)
        if match is None or not signal.extension or int(match[1]) < 1:
            raise AdminError('Ungültige physische Push-Ausgangsadresse: ' + signal.key)
        number = int(match[1])
    return (number - 1) % MAX_SIGNALS_PER_PLAN


def _stable_groups(signals: list[Channel]) -> list[tuple[str, list[Channel]]]:
    """Group by immutable 18-port ranges and never by catalog order.

    The internal key retains the *raw* device address. This makes collisions
    between two different hardware names detectable instead of accidentally
    merging physical sources into the same plan.
    """
    groups: dict[tuple[str, str, int], list[Channel]] = {}
    labels: dict[tuple[str, str, int], str] = {}
    seen_labels: set[str] = set()
    for signal in signals:
        offset = _stable_plan_slot(signal)
        if signal.kind == 'cover':
            number = int(signal.marker_id)
            start = number - offset
            key = ('cover', '', start)
            label = f'Rollläden M{start}-M{start + MAX_SIGNALS_PER_PLAN - 1}'
        else:
            number = int(signal.identifier[1:])
            start = number - offset
            key = ('output', signal.extension, start)
            label = (f'{readable_hardware_name(signal.extension)} '
                     f'Q{start}-Q{start + MAX_SIGNALS_PER_PLAN - 1}')
        if key not in groups:
            if label in seen_labels:
                raise AdminError('Mehrdeutige Hardwarebezeichnungen erzeugen gleichen Push-Plannamen: ' + label)
            seen_labels.add(label)
            labels[key] = label
            groups[key] = []
        groups[key].append(signal)
    return [(labels[key], sorted(items, key=_stable_plan_slot))
            for key, items in sorted(groups.items(), key=lambda entry: labels[entry[0]])]


def _existing_commands(config: dict, device_id: str) -> dict[str, int]:
    """Compact name-to-ID view of the shared, collision-safe command index."""
    return {name: cid for name, (cid, _) in unique_webio_commands(config, device_id).items()}


def _find_push_device(config: dict) -> tuple[str | None, str]:
    """Resolve exactly one canonical Web-IO class; ambiguous names block writes."""
    matches = [(str(did), str(dev.get('Name'))) for did, dev in
               (config.get('WebDevices') or {}).items()
               if isinstance(dev, dict) and dev.get('Name') == PREFERRED_PUSH_CLASS]
    if len(matches) > 1:
        raise AdminError('Mehrere COMEXIO-Local-Push-Klassen gefunden; keine Änderung')
    return matches[0] if matches else (None, PREFERRED_PUSH_CLASS)


def _find_plan(config: dict, name: str) -> tuple[int, dict] | None:
    """Resolve a uniquely named plan using the shared guard."""
    return find_unique_named_plan(config, name)


def _device_base_id(config: dict, device_id: str) -> str:
    """Return only the base ID explicitly bound to this live Web-IO device.

    Never search by the device's display name: a COMEXIO base template and
    its live device have different identities and lifecycles.
    """
    devices = config.get('WebDevices')
    device = devices.get(str(device_id)) if isinstance(devices, dict) else None
    return web_device_base_id(device)


async def _append_command(admin: ComexioAdmin, device_id: str, base_id: str, cmd: dict) -> None:
    """Append one command without modifying any existing Web-IO command."""
    try:
        data = WebIOCommand.from_import(cmd).as_append_form(device_id, base_id)
    except ValueError as err:
        raise AdminError(f"Web-IO-Befehlsdefinition für '{cmd.get('Name', '?')}' ungültig") from err
    # COMEXIO save_command returns 200 on success; inspect later via raw discovery.
    async with admin._lock:
        await admin._wait_write_slot()
        async with admin.session.post(admin.base+"/admin/web_io/save_command",data=data,headers=admin._headers) as response:
            if response.status != 200:
                raise AdminError(f"Web-IO command '{cmd['Name']}' failed: HTTP {response.status}")


async def _wire_pair(admin: ComexioAdmin, plan_id: int, signal: Channel, command_id: int,
                     index: int, plan: dict) -> bool:
    return await ensure_webio_link(admin, plan_id, signal, command_id, index,
                                   plan, update_cache=False,
                                   command_name=friendly_command_name(signal))


# All light/cover Push provisioning is executed by PushRebuild in the
# background, including additive repairs and the configure_push HA service.
# Only low-level source/group/command/graph helpers live in this module.
