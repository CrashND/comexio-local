"""Conservative COMEXIO device metadata; never invent firmware versions."""
from __future__ import annotations

import re
from dataclasses import dataclass
from html.parser import HTMLParser
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from homeassistant.helpers.device_registry import DeviceInfo

_FIRMWARE = re.compile(r'^\d+\.\d+\.\d+(?:[.-][A-Za-z0-9]+)?$')


@dataclass(frozen=True)
class ControllerSystemInfo:
    """Optional identity information from COMEXIO's system overview."""

    firmware_version: str | None = None
    model: str | None = None
    serial_number: str | None = None


class _DashboardBodyText(HTMLParser):
    """Extract visible body text, excluding JavaScript and style content."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self._in_body = False
        self._skip = 0

    def handle_starttag(self, tag: str, attrs: list) -> None:
        if tag == 'body':
            self._in_body = True
        elif self._in_body and tag in ('script', 'style'):
            self._skip += 1

    def handle_endtag(self, tag: str) -> None:
        if tag in ('script', 'style') and self._skip:
            self._skip -= 1
        elif tag == 'body':
            self._in_body = False

    def handle_data(self, data: str) -> None:
        if self._in_body and not self._skip:
            self.parts.append(data)


def system_info_from_html(page: str) -> ControllerSystemInfo:
    """Read only labelled COMEXIO system fields; do not guess a version.

    The system overview (``/admin/admin_dashboard/home``) exposes these
    values as HTML text on COMEXIO OS 11.1.5. Hardware 'IO-Server 2G' is
    a product model, *not* evidence of a distinct hardware revision.
    """
    parser = _DashboardBodyText()
    parser.feed(page)
    text = re.sub(r'\s+', ' ', ' '.join(parser.parts))
    firmware = re.search(
        r'\bCOMEXIO\s+Firmware\s+Version\s*:\s*'
        r'(?:Comexio\s+OS\s*)?(\d+\.\d+\.\d+(?:[.-][A-Za-z0-9]+)?)',
        text, re.IGNORECASE,
    )
    hardware = re.search(
        r'\bCOMEXIO\s+Hardware\s+Version\s*:\s*'
        r'(IO[- ]Server\s+[A-Za-z0-9.-]+)', text, re.IGNORECASE,
    )
    serial = re.search(
        r'\bSeriennummer\s*:\s*(\d[0-9A-Za-z.-]{6,38})\b',
        text, re.IGNORECASE,
    )
    return ControllerSystemInfo(
        firmware_version=firmware.group(1) if firmware else None,
        model=hardware.group(1) if hardware else None,
        serial_number=serial.group(1) if serial else None,
    )


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
            return DeviceInfo(
                identifiers={device_identifier(runtime.entry, physical)},
                name=physical.name,
                manufacturer='COMEXIO',
                model=physical.model,
                configuration_url=f"http://{runtime.entry.data['host']}/",
            )

    optional = {}
    if runtime.firmware_version:
        optional['sw_version'] = runtime.firmware_version
    if runtime.controller_serial_number:
        optional['serial_number'] = runtime.controller_serial_number
    return DeviceInfo(
        identifiers={('comexio_local', runtime.entry.unique_id or runtime.entry.entry_id)},
        name='COMEXIO IO-Server',
        manufacturer='COMEXIO',
        model=runtime.controller_model,
        configuration_url=f"http://{runtime.entry.data['host']}/",
        **optional,
    )
