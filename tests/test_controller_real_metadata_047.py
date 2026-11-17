"""v0.4.7: no invented device data; robust read-only COMEXIO metadata."""
from __future__ import annotations

import asyncio
import logging
from types import SimpleNamespace

import pytest

from comexio_local.admin_api import ComexioAdmin
from comexio_local.device_metadata import (
    ControllerSystemInfo,
    system_info_from_config,
    system_info_from_html,
)
from comexio_local.hardware_devices import sync_hardware_registry
from test_hardware_devices_040 import ENTRY, FakeEntityRegistry, FakeHardwareRegistry, _stub_registry


DOM_PAGE = '''<html><head><title>System</title></head><body>
<table>
<tr><td>COMEXIO Firmware Version:</td><td>Comexio OS 11.1.5 - 23.10.2026</td></tr>
<tr><td>COMEXIO Hardware Version:</td><td>IO-Server 3G</td></tr>
<tr><td>Seriennummer:</td><td>1234-5678-9012</td></tr>
<tr><td>Netzwerk:</td><td>Gateway: ...</td></tr>
</table></body></html>'''


JS_PAGE = '''<html><head><title>System</title></head><body>
<div id="device-info"></div>
<script>
window.deviceData = `
  <div>COMEXIO Firmware Version: Comexio OS 12.4.6 - 21.10.2027</div>
  <div>COMEXIO Hardware Version: IO-Server 4G</div>
  <div>Seriennummer: 5678-9012-3456</div>
`;
</script></body></html>'''


def test_html_parser_reads_dom_cells_without_hardcoded_model():
    assert system_info_from_html(DOM_PAGE) == ControllerSystemInfo(
        firmware_version='11.1.5', model='IO-Server 3G', serial_number='1234-5678-9012')


def test_html_parser_reads_script_rendered_value_pairs():
    # This was excluded entirely by the v0.4.6 parser.
    assert system_info_from_html(JS_PAGE) == ControllerSystemInfo(
        firmware_version='12.4.6', model='IO-Server 4G', serial_number='5678-9012-3456')


def test_script_json_fields_preserve_real_values():
    page = '''<html><body><script>
    const info = {"COMEXIO Firmware Version:":"Comexio OS 11.1.5 - 23.10.2026",
                  "COMEXIO Hardware Version:":"IO-Server 2G",
                  "Seriennummer:":"1234-5678-9012"};
    </script></body></html>'''
    assert system_info_from_html(page) == ControllerSystemInfo(
        firmware_version='11.1.5', model='IO-Server 2G', serial_number='1234-5678-9012')


def test_visible_unavailable_information_is_not_overwritten_by_script_demo():
    page = '''<html><body>
    <div>COMEXIO Firmware Version: Unbekannt</div>
    <div>COMEXIO Hardware Version: Unbekannt</div>
    <div>Seriennummer: —</div>
    <script>const demo = 'COMEXIO Firmware Version: Comexio OS 99.9.9;
    COMEXIO Hardware Version: IO-Server 99G; Seriennummer: 9999-9999-9999';</script>
    </body></html>'''
    assert system_info_from_html(page) == ControllerSystemInfo()


def test_html_parser_ignores_unrelated_version_and_unauthenticated_page():
    page = '''<html><body>Konfigurations-Version: 1; App-Version: 11.1.5
    <script>const appVersion = '12.1.1';</script></body></html>'''
    assert system_info_from_html(page) == ControllerSystemInfo()
    assert system_info_from_html('<html><body>Login required</body></html>') == ControllerSystemInfo()


def test_explicit_config_metadata_only_and_zero_invented_defaults():
    assert system_info_from_config({'FubModules': {'1': {'1': {
        'extension': {'Name': 'IO-Server-1'}}}}}) == ControllerSystemInfo()
    assert system_info_from_config({'Version': '11.1.5', 'FubModules': {}}) == ControllerSystemInfo()
    config = {'DeviceInfo': {'SerialNumber': '1234-5678-9012'},
              'SystemInfo': {'FirmwareVersion': '12.4.6'},
              'FubModules': {'1': {
                  '1': {'extension': {'Name': 'IO-Server-1', 'HardwareModel': 'IO-Server 5G'}},
                  '2': {'extension': {'Name': 'IO-Ext-2', 'HardwareModel': 'IO-Extension 2G'}}
              }}}
    assert system_info_from_config(config) == ControllerSystemInfo(
        firmware_version='12.4.6', model='IO-Server 5G', serial_number='1234-5678-9012')


class _Reply:
    def __init__(self, status: int, body: str):
        self.status = status
        self.body = body
    async def __aenter__(self):
        return self
    async def __aexit__(self, *args):
        pass
    def raise_for_status(self):
        if self.status >= 400:
            raise OSError(f'HTTP {self.status}')
    async def text(self, errors='replace'):
        return self.body


class _Session:
    def __init__(self, status: int, body: str):
        self.reply = _Reply(status, body)
        self.calls = []
    def get(self, url, **kwargs):
        self.calls.append((url, kwargs))
        return self.reply


def test_real_get_path_reads_auth_session_and_logs_no_serial(caplog):
    session = _Session(200, DOM_PAGE)
    admin = ComexioAdmin(session, '192.0.2.15', 'user', 'private')
    admin._authenticated = True
    with caplog.at_level(logging.INFO):
        info = asyncio.run(admin.read_system_info())
    assert info.model == 'IO-Server 3G'
    assert info.serial_number == '1234-5678-9012'
    assert len(session.calls) == 1
    url, kwargs = session.calls[0]
    assert url.endswith('/admin/system_info/home')
    assert kwargs['allow_redirects'] is False
    assert kwargs['timeout'].total == 10
    assert kwargs['headers'] == {}
    assert '1234-5678-9012' not in caplog.text
    assert 'private' not in caplog.text
    assert 'firmware=True, model=True, serial=True' in caplog.text


def test_http_redirect_is_not_silently_accepted_or_followed(caplog):
    session = _Session(302, '<html><body>Login</body></html>')
    admin = ComexioAdmin(session, '192.0.2.15', 'user', 'private')
    admin._authenticated = True
    with caplog.at_level(logging.WARNING):
        assert asyncio.run(admin.read_system_info()) == ControllerSystemInfo()
    assert len(session.calls) == 1
    assert 'HTTP 302' in caplog.text
    assert 'private' not in caplog.text


def test_empty_dashboard_warns_but_does_not_interrupt_discovery(caplog):
    admin = ComexioAdmin(_Session(200, '<html><body>Login</body></html>'),
                         '192.0.2.15', 'user', 'private')
    admin._authenticated = True
    with caplog.at_level(logging.WARNING):
        assert asyncio.run(admin.read_system_info()) == ControllerSystemInfo()
    assert 'no labelled device data' in caplog.text
    assert 'private' not in caplog.text


def test_existing_registry_gets_actual_values_and_clears_old_hardcoded_defaults(monkeypatch):
    dr, er = FakeHardwareRegistry(), FakeEntityRegistry([])
    _stub_registry(monkeypatch, dr, er)
    first = dict(controller_model='IO-Server 3G', controller_firmware='12.4.6',
                 controller_serial='1234-5678-9012')
    sync_hardware_registry(SimpleNamespace(), ENTRY, {}, {}, {}, **first)
    assert dr.created[-1]['model'] == 'IO-Server 3G'
    assert dr.created[-1]['sw_version'] == '12.4.6'
    assert dr.created[-1]['serial_number'] == '1234-5678-9012'
    # No stale fields if the real source stops supplying them. Other
    # identifiers and actual entity assignments stay untouched.
    sync_hardware_registry(SimpleNamespace(), ENTRY, {}, {}, {},
                           controller_model=None, controller_firmware=None,
                           controller_serial=None)
    assert dr.created[-1]['identifiers'] == dr.created[0]['identifiers']
    assert dr.created[-1]['model'] is None
    assert dr.created[-1]['sw_version'] is None
    assert dr.created[-1]['serial_number'] is None
