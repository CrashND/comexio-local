"""Conservative COMEXIO device metadata; never invent firmware versions."""
import re

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


def device_info(runtime) -> dict:
    result = {
        'identifiers': {('comexio_local', runtime.entry.unique_id or runtime.entry.entry_id)},
        'name': 'COMEXIO IO-Server',
        'manufacturer': 'COMEXIO',
        'model': 'IO-Server 2G',
        'configuration_url': f"http://{runtime.entry.data['host']}/",
    }
    if runtime.firmware_version:
        result['sw_version'] = runtime.firmware_version
    return result
