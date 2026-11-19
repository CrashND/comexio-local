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
# Extension TypeIds observed in the owner's COMEXIO OS 11.1.5 configuration.
# This is a *type translation*, never a default model for arbitrary modules.
# Unknown future TypeIds are intentionally left without an HA model.
_KNOWN_EXTENSION_MODELS = {
    4: 'EnOcean-Bridge',
    10: 'IO-Extension',
    14: 'Universal-Aktor',
    16: 'Doorstation',
}
# COMEXIO uses Identifier as the extension serial number (manufacturer's
# extension setup documentation). Accept only the confirmed hardware format,
# never arbitrary IO identifiers, IP addresses or unvalidated strings.
_EXTENSION_SERIAL = re.compile(r'^[0-9]{4}-[0-9]{4}-[0-9]{4}$')
_EXPLICIT_SERIAL = re.compile(r'^[A-Za-z0-9][A-Za-z0-9.-]{5,63}$')
_UNSPECIFIED = {'comexio erweiterung', 'unknown', 'unbekannt', 'n/a', 'none', 'null', '-'}
_FIRMWARE = re.compile(r'^\d+\.\d+\.\d+(?:[.-][A-Za-z0-9]+)?$')


@dataclass(frozen=True)
class HardwareDevice:
    key: str                      # independent of the UI/device display name
    name: str                     # exactly as reported by COMEXIO
    model: str | None             # explicit COMEXIO model or known TypeId translation
    source_name: str              # COMEXIO's physical ext value in IO event keys
    serial_number: str | None = None  # validated COMEXIO extension Identifier
    firmware_version: str | None = None  # only if explicitly supplied per module


def _name(value) -> str:
    return str(value).strip() if isinstance(value, str) else ''


def _type_id(meta: dict, record: dict) -> int | None:
    """Read the physical module's type; never guess one from its mutable name."""
    for item in (meta, record):
        value = item.get('TypeId')
        if type(value) is int and value >= 0:
            return value
        if isinstance(value, str) and re.fullmatch(r'[0-9]{1,5}', value.strip()):
            return int(value.strip())
    return None


def _model(meta: dict, record: dict) -> str | None:
    """Prefer an explicit model, else translate only confirmed COMEXIO TypeIds."""
    for item in (meta, record):
        for field in ('Model', 'TypeName', 'HardwareType', 'HardwareName'):
            name = _name(item.get(field))
            if name and len(name) <= 90 and name.casefold() not in _UNSPECIFIED:
                return name
    return _KNOWN_EXTENSION_MODELS.get(_type_id(meta, record))


def _serial(meta: dict, record: dict) -> str | None:
    """Only validated, directly reported hardware serial numbers."""
    for item in (meta, record):
        for field in ('SerialNumber', 'SerialNo', 'Serial'):
            number = _name(item.get(field))
            if (_EXPLICIT_SERIAL.fullmatch(number) and
                    number.casefold() not in _UNSPECIFIED and
                    number not in ('0000-0000-0000',)):
                return number
    for item in (meta, record):
        number = _name(item.get('Identifier'))
        if (_EXTENSION_SERIAL.fullmatch(number) and
                number != '0000-0000-0000'):
            return number
    return None


def _firmware(meta: dict, record: dict) -> str | None:
    """Never inherit the IO-Server firmware or generic software Version."""
    for item in (meta, record):
        for field in ('FirmwareVersion', 'Firmware'):
            version = _name(item.get(field))
            if _FIRMWARE.fullmatch(version):
                return version
    return None


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
                serial_number=_serial(ext, record),
                firmware_version=_firmware(ext, record),
            )

    counts = Counter(device.source_name for device in devices.values())
    unique_names = {device.source_name: device for device in devices.values()
                    if counts[device.source_name] == 1}

    # COMEXIO already exposes EnOcean inputs on its *one* physical bridge.
    # EI1/EI2/... are signal address groups, not additional HA devices.
    # Keeping only actual COMEXIO modules avoids UI placeholder devices.
    return devices, unique_names


def device_identifier(entry, device: HardwareDevice) -> tuple[str, str]:
    """Scope every real module to the existing COMEXIO Local config entry."""
    prefix = entry.unique_id or entry.entry_id
    return DOMAIN, f'{prefix}:{device.key}'


def sync_hardware_registry(hass, entry, channels: dict,
                           devices: dict[str, HardwareDevice],
                           by_source: dict[str, HardwareDevice], *,
                           controller_model: str | None = None,
                           controller_firmware: str | None = None,
                           controller_serial: str | None = None) -> None:
    """Register physical modules, moving only own existing entities to them.

    Never change an entity unique ID, entity_id, custom name, area, labels or
    disabled status. Covers and diagnostics remain at the IO-Server. EnOcean
    channels belong to the existing physical EnOcean bridge, not EI devices.
    No HA device deletion or compatibility repair is performed here.
    """
    from homeassistant.helpers import device_registry as dr, entity_registry as er
    registry = dr.async_get(hass)
    root_kwargs = dict(
        config_entry_id=entry.entry_id,
        identifiers={(DOMAIN, entry.unique_id or entry.entry_id)},
        name='COMEXIO IO-Server',
        manufacturer='COMEXIO',
        configuration_url=f"http://{entry.data['host']}/",
    )
    # A temporary failure of the optional System Info page must not erase
    # previously verified HA device metadata. Fresh, real values still update.
    if controller_model:
        root_kwargs['model'] = controller_model
    if controller_firmware:
        root_kwargs['sw_version'] = controller_firmware
    if controller_serial:
        root_kwargs['serial_number'] = controller_serial
    root = registry.async_get_or_create(**root_kwargs)
    module_ids: dict[str, str] = {}
    url = f"http://{entry.data['host']}/"
    for device in devices.values():
        kwargs = dict(
            config_entry_id=entry.entry_id,
            identifiers={device_identifier(entry, device)},
            name=device.name,
            manufacturer='COMEXIO',  # actual extension, not a radio participant
            model=device.model,
            # None clears the old generic model for unknown TypeIds, without
            # touching identifiers, user names, areas or entity settings.
            configuration_url=url,
        )
        # Preserve already known serial / firmware when the config omits them
        # temporarily; never infer firmware from the controller.
        if device.serial_number:
            kwargs['serial_number'] = device.serial_number
        if device.firmware_version:
            kwargs['sw_version'] = device.firmware_version
        result = registry.async_get_or_create(**kwargs)
        module_ids[device.key] = result.id

    wanted: dict[str, str] = {}
    prefix = entry.unique_id or entry.entry_id
    for channel in channels.values():
        # Channel.unique_id remains based ONLY on its stable physical key.
        # Marker-paired covers are controller-owned regardless of IO relays.
        if channel.kind == 'cover' or _CONTROLLER.fullmatch(channel.extension):
            target = root.id
        elif channel.extension in by_source:
            parent = by_source[channel.extension]
            target = module_ids[parent.key]
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


