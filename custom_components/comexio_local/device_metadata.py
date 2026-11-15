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
    """Collect visible nodes and embedded scripts separately.

    COMEXIO may place dashboard information in JavaScript-rendered HTML.
    Unlike v0.4.6, do not silently discard script text: the browser test
    showed the labels in the fetched HTML, not necessarily as plain DOM nodes.
    """

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self.scripts: list[str] = []
        self._in_body = False
        self._in_script = False
        self._in_style = False

    def handle_starttag(self, tag: str, attrs: list) -> None:
        if tag == 'body':
            self._in_body = True
        elif tag == 'script':
            self._in_script = True
        elif tag == 'style':
            self._in_style = True

    def handle_endtag(self, tag: str) -> None:
        if tag == 'script':
            self._in_script = False
        elif tag == 'style':
            self._in_style = False
        elif tag == 'body':
            self._in_body = False

    def handle_data(self, data: str) -> None:
        if self._in_script:
            self.scripts.append(data)
        elif self._in_body and not self._in_style:
            self.parts.append(data)


_LABELS = re.compile(
    r'COMEXIO\s+(?:Firmware|Hardware)\s+Version\s*:|Seriennummer\s*:|'
    r'Netzwerk\s*:', re.IGNORECASE,
)
_VALID_MODEL = re.compile(r'[A-Za-z0-9][A-Za-z0-9 ._+()/\-]{2,79}\Z')
_VALID_SERIAL = re.compile(r'[A-Za-z0-9][A-Za-z0-9.\-]{5,63}\Z')
_MISSING_MODEL = {'unbekannt', 'unknown', 'nicht verfuegbar', 'nicht verfügbar', 'n/a', 'none', 'null', '-'}
_FIRMWARE_LABEL = re.compile(r'\bCOMEXIO\s+Firmware\s+Version\s*:', re.I)
_HARDWARE_LABEL = re.compile(r'\bCOMEXIO\s+Hardware\s+Version\s*:', re.I)
_SERIAL_LABEL = re.compile(r'\bSeriennummer\s*:', re.I)
_VERSION_IN_VALUE = re.compile(r'(?i)(?:Comexio\s+OS\s*)?(\d+\.\d+\.\d+(?:[.-][A-Za-z0-9]+)?)')


def _system_info_from_text(text: str) -> ControllerSystemInfo:
    """Only accept values immediately following actual system-field labels."""
    fields: dict[str, str | None] = {}
    for label, key in ((_FIRMWARE_LABEL, 'firmware'),
                       (_HARDWARE_LABEL, 'model'),
                       (_SERIAL_LABEL, 'serial')):
        m = label.search(text)
        if m is None:
            continue
        value = text[m.end():]
        stop = _LABELS.search(value)
        if stop:
            value = value[:stop.start()]
        # A dashboard text value must never spill into another markup, JS
        # statement, literal, or navigation item.
        value = re.split(r'[;\r\n<>"\'`]', value, maxsplit=1)[0].strip(' \t:=')
        if key == 'firmware':
            version = _VERSION_IN_VALUE.match(value)
            fields[key] = version.group(1) if version else None
        elif key == 'model':
            fields[key] = (value if _VALID_MODEL.fullmatch(value) and
                           value.casefold() not in _MISSING_MODEL else None)
        else:
            fields[key] = value if _VALID_SERIAL.fullmatch(value) else None
    return ControllerSystemInfo(firmware_version=fields.get('firmware'),
                                model=fields.get('model'),
                                serial_number=fields.get('serial'))


def _merge_info(first: ControllerSystemInfo, second: ControllerSystemInfo) -> ControllerSystemInfo:
    """Prefer an explicitly read primary field; fill only missing fields."""
    return ControllerSystemInfo(
        firmware_version=first.firmware_version or second.firmware_version,
        model=first.model or second.model,
        serial_number=first.serial_number or second.serial_number,
    )


def system_info_from_html(page: str) -> ControllerSystemInfo:
    """Extract real COMEXIO firmware/model/serial from the system dashboard.

    The HTML may contain literal body text, text split across HTML elements,
    or values embedded in JavaScript. The latter was incorrectly excluded in
    v0.4.6. Never infer a model from the integration version or static data.
    """
    import html as html_lib

    parser = _DashboardBodyText()
    parser.feed(page)
    texts: list[str] = []
    # Split nodes come from adjacent table cells in the real COMEXIO UI.
    # Rejoin them with whitespace for exact label/value matching.
    visible_text = ' '.join(parser.parts)
    visible_labels = {
        'firmware_version': bool(_FIRMWARE_LABEL.search(visible_text)),
        'model': bool(_HARDWARE_LABEL.search(visible_text)),
        'serial_number': bool(_SERIAL_LABEL.search(visible_text)),
    }
    if parser.parts:
        texts.append(visible_text)
    for script in parser.scripts:
        # JavaScript may embed already-rendered HTML with escaped newlines,
        # e.g. a string used by the browser to populate the System Info pane.
        flattened = html_lib.unescape(script)
        flattened = re.sub(r'<[^>]{1,400}>', ' ', flattened)
        flattened = flattened.replace(r'\t', ' ').replace(r'\n', ' ').replace(r'\r', ' ')
        # Some firmwares encode the same labelled rows as JSON key/value
        # strings: {"COMEXIO Hardware Version:":"IO-Server ..."}.
        flattened = re.sub(r"(:)\s*['\"]\s*:\s*['\"]", r'\1 ', flattened)
        texts.append(flattened)
    result = ControllerSystemInfo()
    for i, candidate in enumerate(texts):
        # Keep real display labels, stripping only redundant whitespace.
        normalized = re.sub(r'\s+', ' ', candidate)
        parsed = _system_info_from_text(normalized)
        if i and parser.parts:
            # A visible but explicitly unavailable field must not be replaced
            # with a possibly obsolete/demo value from inline JS source.
            parsed = ControllerSystemInfo(**{
                name: None if visible_labels[name] else getattr(parsed, name)
                for name in ('firmware_version', 'model', 'serial_number')
            })
        result = _merge_info(result, parsed)
        if all((result.firmware_version, result.model, result.serial_number)):
            break
    return result


def _text_field(record: dict, *names: str) -> str | None:
    if not isinstance(record, dict):
        return None
    for name in names:
        value = record.get(name)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


def system_info_from_config(config: dict) -> ControllerSystemInfo:
    """Use only explicitly named COMEXIO controller facts, never defaults."""
    sources: list[dict] = [config] if isinstance(config, dict) else []
    for name in ('SystemInfo', 'DeviceInfo'):
        data = config.get(name) if isinstance(config, dict) else None
        if isinstance(data, dict):
            sources.append(data)
    # Any explicit metadata of the *controller* extension is also trusted.
    modules = config.get('FubModules', {}) if isinstance(config, dict) else {}
    if isinstance(modules, dict):
        for record in modules.get('1', {}).values() if isinstance(modules.get('1'), dict) else ():
            if not isinstance(record, dict):
                continue
            extension = record.get('extension')
            if (isinstance(extension, dict) and
                    re.fullmatch(r'IO-Server-\d+', str(extension.get('Name', '')), re.I)):
                sources.append(extension)

    firmware = model = serial = None
    for source in sources:
        raw_firmware = _text_field(source, 'FirmwareVersion', 'Firmware')
        if firmware is None and raw_firmware and _FIRMWARE.fullmatch(raw_firmware):
            firmware = raw_firmware
        raw_model = _text_field(source, 'HardwareModel', 'Model', 'HardwareVersion')
        if model is None and raw_model and _VALID_MODEL.fullmatch(raw_model):
            model = raw_model
        raw_serial = _text_field(source, 'SerialNumber', 'SerialNo', 'Serial')
        if serial is None and raw_serial and _VALID_SERIAL.fullmatch(raw_serial):
            serial = raw_serial
    return ControllerSystemInfo(firmware_version=firmware, model=model, serial_number=serial)


def firmware_from_config(config: dict) -> str | None:
    """Keep the old helper for callers; never accept generic Version fields."""
    return system_info_from_config(config).firmware_version


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
