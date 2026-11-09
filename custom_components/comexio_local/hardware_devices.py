"""COMEXIO physical-device inventory and conservative HA registry association.

The COMEXIO admin configuration is the only source of physical extensions.
Device identities come from the COMEXIO module record, not a hard-coded
catalogue of device families. No virtual Web-IO command or logic plan is a
physical device. Unknown device types retain their reported COMEXIO name.

This module neither provisions COMEXIO hardware nor creates sensor entities.
"""
from __future__ import annotations

from dataclasses import dataclass
from collections import Counter
import re

from .constants import DOMAIN

_CONTROLLER = re.compile(r'^IO-Server-\d+$', re.I)
_ID = re.compile(r'^[0-9]+$')


@dataclass(frozen=True)
class HardwareDevice:
    key: str                      # independent of the UI/device display name
    name: str                     # exactly as reported by COMEXIO
    model: str                    # reported model or neutral fallback
    source_name: str              # COMEXIO's physical ext value in IO event keys


def _name(value) -> str:
    return str(value).strip() if isinstance(value, str) else ''


def _model(meta: dict, record: dict) -> str:
    """Use only descriptive COMEXIO model strings, not opaque numeric type IDs."""
    for item in (meta, record):
        for field in ('Model', 'TypeName', 'HardwareType', 'HardwareName'):
            name = _name(item.get(field))
            if name and len(name) <= 90:
                return name
    return 'COMEXIO Erweiterung'


def discover_hardware(config: dict) -> tuple[dict[str, HardwareDevice], dict[str, HardwareDevice]]:
    """Return discovered modules and unique, safe IO-origin lookups.

    Scan firmware modules generically for explicit ``extension`` objects,
    even if a device has no active IOs. COMEXIO Web-IO and Merker structures
    without a physical extension descriptor are never misidentified as cards.
    An ambiguous physical name is *not* used for entity assignment.
    """
    modules = config.get('FubModules')
    if not isinstance(modules, dict):
        return {}, {}

    devices: dict[str, HardwareDevice] = {}
    for family, group in modules.items():
        if not isinstance(group, dict) or str(family) in ('2', '10'):
            continue
        for record_id, record in group.items():
            if not isinstance(record, dict):
                continue
            ext = record.get('extension')
            if not isinstance(ext, dict):
                continue
            source_name = _name(ext.get('Name'))
            if not source_name or _CONTROLLER.fullmatch(source_name):
                continue  # controller retains its original HA identity
            # The outer COMEXIO module index is a real structural identifier.
            # Never base HA identifiers on a mutable description or name.
            record_key = str(record_id)
            if not _ID.fullmatch(record_key):
                continue
            identity = f'module:{family}:{int(record_key)}'
            devices[identity] = HardwareDevice(
                key=identity,
                name=source_name,
                model=_model(ext, record),
                source_name=source_name,
            )

    counts = Counter(device.source_name for device in devices.values())
    unique_names = {device.source_name: device for device in devices.values()
                    if counts[device.source_name] == 1}
    return devices, unique_names


def device_identifier(entry, device: HardwareDevice) -> tuple[str, str]:
    """Scope every real module to the existing COMEXIO Local config entry."""
    prefix = entry.unique_id or entry.entry_id
    return DOMAIN, f'{prefix}:{device.key}'


def sync_hardware_registry(hass, entry, channels: dict,
                           devices: dict[str, HardwareDevice],
                           by_source: dict[str, HardwareDevice]) -> None:
    """Register physical modules, moving only own existing entities to them.

    Never change a unique ID, entity_id, custom name, area, labels or disabled
    status. Covers (markers) and integration diagnostics stay at the IO-Server.
    On any unknown/duplicate module origin, leave an entity at the controller
    rather than guessing. No automatic registry deletion occurs.
    """
    from homeassistant.helpers import device_registry as dr, entity_registry as er
    registry = dr.async_get(hass)
    root = registry.async_get_or_create(
        config_entry_id=entry.entry_id,
        identifiers={(DOMAIN, entry.unique_id or entry.entry_id)},
        name='COMEXIO IO-Server',
        manufacturer='COMEXIO',
        model='IO-Server 2G',
        configuration_url=f"http://{entry.data['host']}/",
    )
    module_ids: dict[str, str] = {}
    url = f"http://{entry.data['host']}/"
    for device in devices.values():
        result = registry.async_get_or_create(
            config_entry_id=entry.entry_id,
            identifiers={device_identifier(entry, device)},
            name=device.name,
            manufacturer='COMEXIO',
            model=device.model,
            configuration_url=url,
        )
        module_ids[device.key] = result.id

    wanted: dict[str, str] = {}
    prefix = entry.unique_id or entry.entry_id
    for channel in channels.values():
        # Channel.unique_id remains based ONLY on its stable physical key.
        # Marker-paired covers are controller-owned regardless of IO relays.
        if channel.kind == 'cover' or _CONTROLLER.fullmatch(channel.extension):
            target = root.id
        elif channel.extension in by_source:
            target = module_ids[by_source[channel.extension].key]
        else:
            # Incomplete/unrecognised hardware metadata: retain any existing
            # entity association, never guess or move it to another card.
            continue
        wanted[f'{prefix}:{channel.key}'] = target

    entity_registry = er.async_get(hass)
    for row in er.async_entries_for_config_entry(entity_registry, entry.entry_id):
        if row.config_entry_id != entry.entry_id or row.platform != DOMAIN:
            continue
        target = wanted.get(row.unique_id)
        if target is not None and row.device_id != target:
            entity_registry.async_update_entity(row.entity_id, device_id=target)
