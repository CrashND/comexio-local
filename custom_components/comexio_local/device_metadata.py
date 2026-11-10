"""Conservative COMEXIO device metadata; never invent firmware versions."""
from __future__ import annotations

import re
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from homeassistant.helpers.device_registry import DeviceInfo

_FIRMWARE = re.compile(r'^\d+\.\d+\.\d+(?:[.-][A-Za-z0-9]+)?$')


def firmware_from_config(config: dict) -> str | None:
    """Only explicitly firmware-labelled version fields are trustworthy."""
    fields = [config.get('FirmwareVersion'), config.get('Firmware')]
    for group in ('SystemInfo', 'DeviceInfo'):
        info = config.get(group)
        if isinstance(info, dict):
            fields.extend((info.get('FirmwareVersion'), info.get('Firmware')))
    for value in fields:
        if isinstance(value, str) and _FIRMWARE.fullmatch(value.strip()):
            return value.strip()
    return None


def device_info(runtime, channel=None) -> DeviceInfo:
    """Create HA DeviceInfo without dict-style access or unset field writes.

    DeviceInfo accepts keyword construction both as the former TypedDict and
    as the Home Assistant 2026.11 dataclass. Never replace stable identifiers.
    The import is local so firmware parsing can also be tested without HA.
    """
    from homeassistant.helpers.device_registry import DeviceInfo

    from .hardware_devices import device_identifier

    if channel is not None and channel.kind != 'cover':
        physical = getattr(runtime, 'hardware_by_source', {}).get(channel.extension)
        if physical is not None:
            if channel.is_enocean:
                logical_key = f'{physical.key}:EI{channel.enocean_slot}'
                physical = getattr(runtime, 'hardware_devices', {}).get(logical_key, physical)
            return DeviceInfo(
                identifiers={device_identifier(runtime.entry, physical)},
                name=physical.name,
                manufacturer='COMEXIO',
                model=physical.model,
                configuration_url=f"http://{runtime.entry.data['host']}/",
            )

    optional = {'sw_version': runtime.firmware_version} if runtime.firmware_version else {}
    return DeviceInfo(
        identifiers={('comexio_local', runtime.entry.unique_id or runtime.entry.entry_id)},
        name='COMEXIO IO-Server',
        manufacturer='COMEXIO',
        model='IO-Server 2G',
        configuration_url=f"http://{runtime.entry.data['host']}/",
        **optional,
    )
