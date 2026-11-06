"""HA 2026.11 DeviceInfo migration without changing HA device identity."""
from dataclasses import dataclass, is_dataclass
from types import SimpleNamespace
import sys
import types

from comexio_local.device_metadata import device_info, firmware_from_config


NOT_SET = object()


@dataclass(kw_only=True)
class MockHA202611DeviceInfo:
    identifiers: set
    name: str
    manufacturer: str
    model: str
    configuration_url: str
    sw_version: object = NOT_SET

    def as_dict(self):
        return {name: value for name, value in vars(self).items() if value is not NOT_SET}


def _runtime(firmware, unique_id=None):
    entry = SimpleNamespace(unique_id=unique_id, entry_id='entry-1', data={'host': '192.168.10.254'})
    return SimpleNamespace(entry=entry, firmware_version=firmware)


def _device_registry_stub(monkeypatch):
    registry = types.ModuleType('homeassistant.helpers.device_registry')
    registry.DeviceInfo = MockHA202611DeviceInfo
    # Only the registry module is needed in this unit; the rest is HA-free.
    monkeypatch.setitem(sys.modules, 'homeassistant.helpers.device_registry', registry)


def test_metadata_matches_ha_202611_dataclass_and_identity(monkeypatch):
    _device_registry_stub(monkeypatch)
    obj = device_info(_runtime('11.1.5', unique_id='comexio-io-1'))
    assert is_dataclass(obj)
    assert obj.identifiers == {('comexio_local', 'comexio-io-1')}
    assert obj.name == 'COMEXIO IO-Server'
    assert obj.manufacturer == 'COMEXIO'
    assert obj.model == 'IO-Server 2G'
    assert obj.configuration_url == 'http://192.168.10.254/'
    assert obj.sw_version == '11.1.5'
    assert obj.as_dict()['sw_version'] == '11.1.5'


def test_metadata_fallback_id_and_missing_firmware_stays_unset(monkeypatch):
    _device_registry_stub(monkeypatch)
    obj = device_info(_runtime(None))
    assert obj.identifiers == {('comexio_local', 'entry-1')}
    assert obj.sw_version is NOT_SET
    assert 'sw_version' not in obj.as_dict()


def test_firmware_parsing_is_still_conservative():
    assert firmware_from_config({'FirmwareVersion': '11.1.5'}) == '11.1.5'
    assert firmware_from_config({'Version': '11.1.5'}) is None
    assert firmware_from_config({'SystemInfo': {'Firmware': '11.1.5'}}) == '11.1.5'
    assert firmware_from_config({'FirmwareVersion': 'not-a-version'}) is None


def test_home_assistant_202611_flow_calls_have_explicit_step_ids():
    """Avoid 2027.5 flow warnings already announced with HA 2026.11."""
    import ast
    from pathlib import Path
    path = Path(__file__).resolve().parents[1] / 'custom_components/comexio_local/config_flow.py'
    calls = []
    for node in ast.walk(ast.parse(path.read_text(encoding='utf-8'))):
        if not isinstance(node, ast.Call):
            continue
        if not isinstance(node.func, ast.Attribute):
            continue
        if node.func.attr in {'async_show_form', 'async_show_menu', 'async_show_progress', 'async_external_step'}:
            calls.append(node)
            assert any(kw.arg == 'step_id' for kw in node.keywords), f'No step_id on line {node.lineno}'
    assert len(calls) >= 20


def test_metadata_compatible_with_pre_202611_typeddict(monkeypatch):
    """Earlier HA releases accepted the same DeviceInfo keyword constructor."""
    from typing import TypedDict

    class OldDeviceInfo(TypedDict, total=False):
        identifiers: set
        name: str
        manufacturer: str
        model: str
        configuration_url: str
        sw_version: str

    registry = types.ModuleType('homeassistant.helpers.device_registry')
    registry.DeviceInfo = OldDeviceInfo
    monkeypatch.setitem(sys.modules, 'homeassistant.helpers.device_registry', registry)
    result = device_info(_runtime('11.1.5'))
    assert result['identifiers'] == {('comexio_local', 'entry-1')}
    assert result['sw_version'] == '11.1.5'
