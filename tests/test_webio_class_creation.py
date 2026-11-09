"""Web-IO device creation must never inherit a reused COMEXIO template."""
import asyncio
from copy import deepcopy

import pytest

from comexio_local.admin_api import ComexioAdmin, AdminError, make_push_command
from comexio_local.discovery import Channel


SIGNAL = Channel(kind='light', name='Test', key='io:IO-Ext-1/Q1',
                 extension='IO-Ext-1', identifier='Q1', io_id=4)
NAME = 'CL TEST Push'
CMD = make_push_command(SIGNAL, '/api/webhook/test-token',
                        name='CL Licht Test IO-Ext-1/Q1')


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
        assert kwargs['data']['name'] == NAME
        return Response(self.admin)


class AdminStub(ComexioAdmin):
    def __init__(self, upload_reply, *, existing=False, collision=False,
                 extra=False, omit=False, mismatched_base=False, wrong_type=False,
                 existing_device=False):
        super().__init__(None, 'comexio.local', 'test', 'no-password')
        self.session = Session(self)
        self.write_gap = 0
        self.upload_reply = upload_reply
        self.base_id = 37
        self.preexisting = existing
        self.existing_device = existing_device
        self.collision = collision
        self.extra = extra
        self.omit = omit
        self.mismatched_base = mismatched_base
        self.wrong_type = wrong_type
        self.saved_device = False
        self.upload_count = 0
        self.imported_name = None

    async def _get_html(self, route, **kwargs):
        assert route == '/admin/web_io/add'
        options = '<option value="7">CL TEST Push</option>' if self.preexisting else ''
        if self.imported_name:
            options += f'<option value="37">{self.imported_name}</option>'
        return '<select>' + options + '</select>'

    async def request_json(self, method, route, **kwargs):
        assert (method, route) == ('POST', '/admin/web_io/upload_device_settings')
        self.upload_count += 1
        # This is the NEW base identifier; never the existing live device name.
        fields = kwargs['data']._fields
        names = {field[0]['name']: field[2] for field in fields}
        self.imported_name = names['set_name']
        assert self.imported_name.startswith('CL Vorlage ')
        assert self.imported_name != NAME
        return self.upload_reply

    async def read_config(self):
        if not self.saved_device:
            return {'WebDevices': {'91': {'Name': NAME, 'WebDeviceBaseId': 7}}
                    if self.existing_device else {}, 'FubModules': {'10': {}}}
        commands = {}
        if not self.omit:
            first = {**CMD, 'Id': 22, 'WebDeviceId': 12}
            if self.wrong_type:
                first['TypeId'] = 2
            commands['22'] = first
        if self.extra:
            commands['23'] = {**CMD, 'Id': 23, 'Name': 'UNEXPECTED', 'WebDeviceId': 12}
        return {
            'WebDevices': {'12': {'Name': NAME, 'WebDeviceBaseId':
                             999 if self.mismatched_base else self.base_id}},
            'FubModules': {'10': {'12': commands}},
        }


def run(admin, monkeypatch):
    from comexio_local import admin_api
    async def no_wait(_):
        pass
    monkeypatch.setattr(admin_api.asyncio, 'sleep', no_wait)
    return asyncio.run(admin.create_push_class(NAME, [CMD], '192.168.10.6:8123'))


def test_nonstandard_reply_uses_new_template_from_server_base_list(monkeypatch):
    admin = AdminStub({'status': 'ok', 'message': 'imported'})
    run(admin, monkeypatch)
    assert admin.saved_device and admin.upload_count == 1


def test_explicit_positive_base_id_is_accepted(monkeypatch):
    admin = AdminStub({'ok': True, 'base_id': '37'})
    run(admin, monkeypatch)
    assert admin.saved_device


def test_rejected_upload_never_creates_device(monkeypatch):
    admin = AdminStub({'ok': False, 'base_id': '37', 'error': 'rejected'})
    with pytest.raises(AdminError, match='Import meldet einen Fehler'):
        run(admin, monkeypatch)
    assert not admin.saved_device


def test_existing_same_named_template_is_not_reused(monkeypatch):
    admin = AdminStub({'ok': True, 'base_id': '37'}, existing=True)
    run(admin, monkeypatch)
    assert admin.saved_device and admin.upload_count == 1
    assert admin.imported_name != NAME


def test_generated_template_collision_fails_before_upload(monkeypatch):
    admin = AdminStub({'ok': True, 'base_id': '37'})
    async def existing_generated(route, **kwargs):
        assert route == '/admin/web_io/add'
        return '<option value="73">CL Vorlage ABCDEF1234</option>'
    from comexio_local import admin_api
    monkeypatch.setattr(admin_api.secrets, 'token_hex', lambda n: 'abcdef1234')
    admin._get_html = existing_generated
    with pytest.raises(AdminError, match='bereits vorhanden'):
        run(admin, monkeypatch)
    assert admin.upload_count == 0 and not admin.saved_device


@pytest.mark.parametrize('reason,expected', [
    ({'omit': True}, 'Import ist unvollständig'),
    ({'extra': True}, 'unerwartete Befehle'),
    ({'wrong_type': True}, 'falschen Typ'),
    ({'mismatched_base': True}, 'unerwarteten Basistyp'),
])
def test_only_exact_current_import_is_allowed(monkeypatch, reason, expected):
    admin = AdminStub({'ok': True, 'base_id': 37}, **reason)
    with pytest.raises(AdminError, match=expected):
        run(admin, monkeypatch)


def test_missing_base_reports_only_response_keys(monkeypatch):
    admin = AdminStub({'status': 'unknown', 'webhook_token': 'should-never-be-echoed'})
    async def no_base(route, **kwargs):
        return '<select></select>'
    admin._get_html = no_base
    with pytest.raises(AdminError, match='nicht nachweisbar') as error:
        run(admin, monkeypatch)
    assert 'should-never-be-echoed' not in str(error.value)
    assert not admin.saved_device


def test_existing_live_device_stops_before_template_upload(monkeypatch):
    admin = AdminStub({'ok': True, 'base_id': 37}, existing_device=True)
    with pytest.raises(AdminError, match='bereits vorhanden'):
        run(admin, monkeypatch)
    assert admin.upload_count == 0 and not admin.saved_device


def test_unnamed_import_command_rejected_before_upload(monkeypatch):
    admin = AdminStub({'ok': True, 'base_id': 37})
    with pytest.raises(AdminError, match='unbenannte'):
        asyncio.run(admin.create_push_class(NAME, [{**CMD, 'Name': ''}], '192.168.10.6:8123'))
    assert admin.upload_count == 0 and not admin.saved_device
