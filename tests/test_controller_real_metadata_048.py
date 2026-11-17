"""v0.4.8: verified System Info route and HA registry propagation."""
from __future__ import annotations

import asyncio
from types import SimpleNamespace

from comexio_local.admin_api import ComexioAdmin
from comexio_local.hardware_devices import sync_hardware_registry
from test_controller_real_metadata_047 import DOM_PAGE, _Session
from test_hardware_devices_040 import (
    ENTRY, FakeEntityRegistry, FakeHardwareRegistry, _stub_registry,
)


def test_confirmed_system_info_endpoint_populates_existing_ha_device(monkeypatch):
    """Read-only GET, parse, then update the original IO-Server registry ID."""
    session = _Session(200, DOM_PAGE)
    admin = ComexioAdmin(session, '192.0.2.15', 'user', 'secret')
    admin._authenticated = True
    actual = asyncio.run(admin.read_system_info())

    assert len(session.calls) == 1
    url, opts = session.calls[0]
    assert url == 'http://192.0.2.15/admin/system_info/home'
    assert opts['headers'] == {}
    assert opts['allow_redirects'] is False
    assert actual.firmware_version == '11.1.5'
    assert actual.model == 'IO-Server 3G'  # from page, not a hard-coded 2G
    assert actual.serial_number == '1234-5678-9012'

    registry, entities = FakeHardwareRegistry(), FakeEntityRegistry([])
    _stub_registry(monkeypatch, registry, entities)
    sync_hardware_registry(
        SimpleNamespace(), ENTRY, {}, {}, {},
        controller_model=actual.model,
        controller_firmware=actual.firmware_version,
        controller_serial=actual.serial_number,
    )
    assert len(registry.created) == 1
    row = registry.created[0]
    assert row['identifiers'] == {('comexio_local', 'server-unique')}
    assert (row['model'], row['sw_version'], row['serial_number']) == (
        'IO-Server 3G', '11.1.5', '1234-5678-9012')
    assert row['name'] == 'COMEXIO IO-Server'
