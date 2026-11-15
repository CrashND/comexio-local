"""v0.4.6: optional read-only COMEXIO system information."""
from __future__ import annotations

import asyncio

from comexio_local.admin_api import ComexioAdmin
from comexio_local.device_metadata import ControllerSystemInfo, system_info_from_html


SAMPLE_PAGE = """<!doctype html><html><head><title>COMEXIO System</title></head>
<body>
  <section>
    <div><span>COMEXIO Firmware Version:</span> <span>Comexio OS 11.1.5 - 23.10.2026</span></div>
    <div><span>COMEXIO Hardware Version:</span> <span>IO-Server 2G</span></div>
    <div><span>Seriennummer:</span> <span>1234-5678-9012</span></div>
  </section>
</body></html>"""


def test_parses_firmware_model_and_serial_from_system_dashboard():
    info = system_info_from_html(SAMPLE_PAGE)
    assert info == ControllerSystemInfo(
        firmware_version='11.1.5', model='IO-Server 2G',
        serial_number='1234-5678-9012')


def test_html_parser_ignores_scripts_and_missing_values():
    page = '''<html><body><script>COMEXIO Firmware Version: Comexio OS 99.8.7;
    COMEXIO Hardware Version: IO-Server 8G; Seriennummer: 7777-7777-7777</script>
    <div>COMEXIO Firmware Version: Unbekannt</div>
    <div>COMEXIO Hardware Version: Unbekannt</div>
    <div>Seriennummer: —</div></body></html>'''
    assert system_info_from_html(page) == ControllerSystemInfo()
    assert system_info_from_html('<html><body>Bitte anmelden</body></html>') == ControllerSystemInfo()


def test_admin_uses_already_authenticated_session_for_read_only_dashboard():
    admin = ComexioAdmin(None, '192.0.2.15', 'u', 'p')
    admin._authenticated = True
    calls = []

    async def fake_get(route, **kwargs):
        calls.append((route, kwargs))
        return SAMPLE_PAGE

    admin._get_html = fake_get
    result = asyncio.run(admin.read_system_info())
    assert result.firmware_version == '11.1.5'
    assert len(calls) == 1
    route, kwargs = calls[0]
    assert route == '/admin/admin_dashboard/home'
    assert kwargs['headers'] == {'Referer': 'http://192.0.2.15/admin/admin_dashboard/home'}
    assert kwargs['allow_redirects'] is False
    assert kwargs['required_status'] == 200
    assert kwargs['timeout'].total == 10


def test_unavailable_system_page_does_not_abort_discovery():
    admin = ComexioAdmin(None, '192.0.2.15', 'u', 'p')
    admin._authenticated = True

    async def unavailable(*args, **kwargs):
        raise OSError('optional dashboard offline')

    admin._get_html = unavailable
    assert asyncio.run(admin.read_system_info()) == ControllerSystemInfo()
