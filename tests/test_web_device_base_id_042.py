"""COMEXIO 11.1.5 exposes WebDevices[*].WebDeviceBaseId, not BaseId.

The captured firmware record is e.g.:
    WebDevices["8"] = {"Id": 8, "Name": "CL Push Home Assistant",
                       "WebDeviceBaseId": 16, "Ip": "..."}
The BaseId on an individual Web-IO command is a DIFFERENT field.
"""
from __future__ import annotations

import pytest

from comexio_local.admin_api import AdminError, web_device_base_id
from comexio_local.push_setup import _device_base_id
from comexio_local.webio_command import WebIOCommand
from test_webio_class_creation import AdminStub, CMD, run


@pytest.mark.parametrize('value', [16, '16', '0016'])
def test_actual_firmware_field_yields_positive_base_id(value):
    config = {'WebDevices': {'8': {'Id': 8, 'Name': 'CL Push Home Assistant',
                                   'WebDeviceBaseId': value, 'Ip': 'local'}}}
    assert _device_base_id(config, '8') == '16'


def test_command_base_id_does_not_override_live_device_base_id():
    config = {'WebDevices': {'8': {'WebDeviceBaseId': 16, 'BaseId': 876}},
              'FubModules': {'10': {'8': {'126': {'BaseId': 0}}}}}
    assert _device_base_id(config, '8') == '16'
    form = WebIOCommand.from_import(CMD).as_append_form('8', _device_base_id(config, '8'))
    assert form['dlg_web_device_id'] == '8'
    assert form['deviceBaseId'] == '16'
    assert CMD['BaseId'] == 0


@pytest.mark.parametrize('device', [
    None, {}, {'BaseId': 16}, {'WebDeviceBaseId': None},
    {'WebDeviceBaseId': ''}, {'WebDeviceBaseId': 0},
    {'WebDeviceBaseId': False}, {'WebDeviceBaseId': True},
    {'WebDeviceBaseId': -1}, {'WebDeviceBaseId': 16.0},
    {'WebDeviceBaseId': '16.0'}, {'WebDeviceBaseId': ' 16'},
    {'WebDeviceBaseId': 'NaN'},
])
def test_no_fallback_to_wrong_field_or_unverified_id(device):
    with pytest.raises(AdminError, match='WebDeviceBaseId'):
        web_device_base_id(device)


def test_new_webio_device_readback_uses_real_firmware_field(monkeypatch):
    admin = AdminStub({'ok': True, 'base_id': 37})
    before = admin.read_config

    async def read_config():
        config = await before()
        if admin.saved_device:
            # A stale/unrelated BaseId MUST NOT be compared with the upload.
            config['WebDevices']['12']['BaseId'] = 999
        return config

    admin.read_config = read_config
    run(admin, monkeypatch)
    assert admin.saved_device


def test_new_webio_device_readback_rejects_missing_real_firmware_field(monkeypatch):
    admin = AdminStub({'ok': True, 'base_id': 37})
    before = admin.read_config

    async def read_config():
        config = await before()
        if admin.saved_device:
            config['WebDevices']['12']['BaseId'] = 37
            del config['WebDevices']['12']['WebDeviceBaseId']
        return config

    admin.read_config = read_config
    with pytest.raises(AdminError, match='WebDeviceBaseId'):
        run(admin, monkeypatch)
