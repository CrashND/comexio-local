"""Firmware-reply compatibility and safety when creating the managed Web-IO class."""
import asyncio
import pytest

from comexio_local.admin_api import ComexioAdmin, AdminError


class Response:
    status = 200

    def __init__(self, admin):
        self.admin = admin

    async def __aenter__(self):
        self.admin.saved_device = True
        return self

    async def __aexit__(self, *_):
        pass


class Session:
    def __init__(self, admin):
        self.admin = admin

    def post(self, url, **kwargs):
        assert url.endswith('/admin/web_io/saveDeviceWindow')
        assert kwargs['data']['web_device_base'] == str(self.admin.base_id)
        return Response(self.admin)


class AdminStub(ComexioAdmin):
    def __init__(self, upload_reply, *, existing=False, multi=False, omit_command=False):
        super().__init__(None, 'comexio.local', 'test', 'no-password')
        self.session = Session(self)
        self.write_gap = 0
        self.upload_reply = upload_reply
        self.base_id = 37
        self.base_available = existing
        self.multi = multi
        self.omit_command = omit_command
        self.saved_device = False
        self.upload_count = 0
        self.first_command = {'Name': 'CL Licht Test E1/Q1'}

    async def _get_html(self, route, **kwargs):
        assert route == '/admin/web_io/add'
        options = '<option value="37">CL TEST Push</option>' if self.base_available else ''
        if self.multi and self.base_available:
            options += '<option value="44">CL TEST Push</option>'
        return '<select>' + options + '</select>'

    async def request_json(self, method, route, **kwargs):
        assert route == '/admin/web_io/upload_device_settings'
        self.upload_count += 1
        if not self.upload_reply.get('error') and self.upload_reply.get('ok') is not False:
            self.base_available = True
        return self.upload_reply

    async def read_config(self):
        if not self.saved_device:
            return {'WebDevices': {}, 'FubModules': {'10': {}}}
        return {
            'WebDevices': {'12': {'Name': 'CL TEST Push', 'BaseId': self.base_id}},
            'FubModules': {'10': {'12': {} if self.omit_command else {'22': self.first_command}}},
        }


def test_nonstandard_success_reply_is_reconciled_with_server_base_list(monkeypatch):
    from comexio_local import admin_api

    async def no_wait(t):
        pass
    monkeypatch.setattr(admin_api.asyncio, 'sleep', no_wait)
    admin = AdminStub({'status': 'ok', 'message': 'imported'})
    asyncio.run(admin.create_push_class('CL TEST Push', [admin.first_command], '192.168.10.6:8123'))
    assert admin.saved_device and admin.upload_count == 1


def test_explicit_positive_base_id_is_accepted(monkeypatch):
    from comexio_local import admin_api

    async def no_wait(t):
        pass
    monkeypatch.setattr(admin_api.asyncio, 'sleep', no_wait)
    admin = AdminStub({'ok': True, 'base_id': '37'})
    asyncio.run(admin.create_push_class('CL TEST Push', [admin.first_command], '192.168.10.6:8123'))
    assert admin.saved_device


def test_rejected_upload_never_creates_device():
    admin = AdminStub({'ok': False, 'base_id': '37', 'error': 'rejected'})
    with pytest.raises(AdminError, match='Import meldet einen Fehler'):
        asyncio.run(admin.create_push_class('CL TEST Push', [admin.first_command], '192.168.10.6:8123'))
    assert not admin.saved_device


def test_resume_reuses_exact_base_type_without_upload(monkeypatch):
    from comexio_local import admin_api

    async def no_wait(t):
        pass
    monkeypatch.setattr(admin_api.asyncio, 'sleep', no_wait)
    admin = AdminStub({}, existing=True)
    asyncio.run(admin.create_push_class('CL TEST Push', [admin.first_command], '192.168.10.6:8123'))
    assert admin.saved_device and admin.upload_count == 0


def test_duplicate_base_types_stop_before_any_write():
    admin = AdminStub({}, existing=True, multi=True)
    with pytest.raises(AdminError, match='mehrere Web-IO-Basistypen'):
        asyncio.run(admin.create_push_class('CL TEST Push', [admin.first_command], '192.168.10.6:8123'))
    assert admin.upload_count == 0 and not admin.saved_device


def test_missing_imported_command_is_not_reported_as_success(monkeypatch):
    from comexio_local import admin_api

    async def no_wait(t):
        pass
    monkeypatch.setattr(admin_api.asyncio, 'sleep', no_wait)
    admin = AdminStub({'ok': True, 'base_id': 37}, omit_command=True)
    with pytest.raises(AdminError, match='importierte Befehle sind nicht sichtbar'):
        asyncio.run(admin.create_push_class('CL TEST Push', [admin.first_command], '192.168.10.6:8123'))


def test_missing_base_reports_safe_response_shape_without_echoing_secret():
    admin = AdminStub({'status': 'unknown', 'webhook_token': 'should-never-be-echoed'})
    async def html_no_base(route, **kwargs):
        return '<select></select>'
    admin._get_html = html_no_base
    with pytest.raises(AdminError, match='nicht nachweisbar') as error:
        asyncio.run(admin.create_push_class('CL TEST Push', [admin.first_command], '192.168.10.6:8123'))
    assert 'should-never-be-echoed' not in str(error.value)
    assert not admin.saved_device
