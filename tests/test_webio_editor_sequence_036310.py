"""v0.3.6.3.10: follow captured COMEXIO editor add-then-wire sequence.

These are offline protocol/graph tests, NOT firmware-rendering tests.
The operator observed that a manual type=10, name="", connection-free
add_element POST renders correctly in firmware 11.1.5.
"""
import asyncio
import json

import pytest

from comexio_local.admin_api import AdminError, ComexioAdmin
from comexio_local.discovery import Channel
from comexio_local.managed_graph import ensure_webio_link


class RecordingAdmin(ComexioAdmin):
    def __init__(self):
        super().__init__(None, 'comexio.invalid', 'test', 'unused')
        self.posts = []
        self.next_id = 100
        self.fail_wire_once = False

    async def request_json(self, method, route, *, data=None, **kwargs):
        assert method == 'POST'
        self.posts.append((route, data))
        if route.endswith('/saveconnection/'):
            if self.fail_wire_once:
                self.fail_wire_once = False
                raise AdminError('test: write failed on saveconnection')
            return {'id': 200}
        assert route.endswith('/add_element/')
        self.next_id += 1
        return {'id': self.next_id, 'ref_id': int(data['ref_id'])}


def _light():
    return Channel(kind='light', name='Flurlicht', key='io:IO-Server-1/Q1',
                   extension='IO-Server-1', identifier='Q1', io_id=7, plan='Flur')


def _cover():
    return Channel(kind='cover', name='Buerorollo', key='cover:M85',
                   marker_id=85, target_marker_id=84, analog=True)


def _input():
    return Channel(kind='binary_input', name='Taster', key='io:IO-Ext-3/I1',
                   extension='IO-Ext-3', identifier='I1', io_id=29, input_mode='taster')


def _assert_requests(admin, source_type, source_ref, command_ref, analog):
    assert len(admin.posts) == 3
    add_src, add_webio, conn = admin.posts
    assert add_src[0].endswith('/add_element/')
    assert add_webio[0].endswith('/add_element/')
    assert conn[0].endswith('/saveconnection/')

    assert set(add_webio[1]) == {'fubid', 'name', 'ref_id', 'type', 'id', 'x', 'y', 'timestamp'}
    assert add_webio[1]['fubid'] == '29'
    assert add_webio[1]['name'] == ''
    assert add_webio[1]['type'] == '10'
    assert add_webio[1]['ref_id'] == str(command_ref)
    assert add_webio[1]['id'] == 'undefined'
    assert 'connection' not in add_webio[1]
    assert add_src[1]['type'] == str(source_type)
    assert add_src[1]['ref_id'] == str(source_ref)
    assert add_src[1]['name'] == ''
    assert 'connection' not in add_src[1]

    wire = json.loads(conn[1]['JSON'])
    assert wire['fub_id'] == 29
    assert wire['type'] == ('analog' if analog else 'binary')
    assert wire['input'] == {'element': '101', 'pos': '0', 'inverted': False}
    assert wire['output'] == {'0': {'element': '102', 'pos': '0', 'inverted': False}}
    assert 'new' not in (wire['input']['element'], wire['output']['0']['element'])


@pytest.mark.parametrize('channel,source_type,source_ref,command_ref,command_name,analog', [
    (_light(), 1, 7, 501, 'CL Licht Flur IO-Server-1/Q1', False),
    (_cover(), 2, 85, 502, 'CL Rollladen Buero M85', True),
    (_input(), 1, 29, 503, 'CL Eingang IO-Ext-3/I1', False),
])
def test_all_push_families_create_plain_block_then_wire(
    channel, source_type, source_ref, command_ref, command_name, analog
):
    admin = RecordingAdmin()
    plan = {'elements': {}, 'connections': {}}

    async def run():
        assert await ensure_webio_link(admin, 29, channel, command_ref, 0, plan,
                                       update_cache=True, command_name=command_name)
        # Already linked: no duplicate elements nor connections.
        assert not await ensure_webio_link(admin, 29, channel, command_ref, 0, plan,
                                           update_cache=True, command_name=command_name)

    asyncio.run(run())
    _assert_requests(admin, source_type, source_ref, command_ref, analog)
    assert len(plan['elements']) == 2
    assert len(plan['connections']) == 1


def test_wire_failure_recovery_reuses_both_stored_elements():
    admin = RecordingAdmin()
    admin.fail_wire_once = True
    plan = {'elements': {}, 'connections': {}}

    async def run():
        with pytest.raises(AdminError, match='saveconnection'):
            await ensure_webio_link(admin, 29, _light(), 501, 0, plan,
                                    update_cache=True,
                                    command_name='CL Licht Flur IO-Server-1/Q1')
        # A failed connection must NOT be accepted as a complete graph link.
        assert len(plan['elements']) == 2
        assert plan['connections'] == {}
        assert await ensure_webio_link(admin, 29, _light(), 501, 0, plan,
                                       update_cache=True,
                                       command_name='CL Licht Flur IO-Server-1/Q1')
        assert len(plan['connections']) == 1

    asyncio.run(run())
    # Two element POSTs, then failed wire POST, then only one repeated wire POST.
    assert [r.split('/')[-2] for r, _ in admin.posts] == [
        'add_element', 'add_element', 'saveconnection', 'saveconnection']


def test_existing_unconnected_firmware_graph_wires_without_new_elements():
    admin = RecordingAdmin()
    plan = {'elements': {
        '1': {'id': 1, 'fub_id': 29, 'name': '',
              'reference': {'type': 1, 'ref_id': 7}},
        '2': {'id': 2, 'fub_id': 29, 'name': '',
              'reference': {'type': 10, 'ref_id': 501}},
    }, 'connections': {}}

    async def run():
        assert await ensure_webio_link(admin, 29, _light(), 501, 0, plan,
                                       update_cache=True,
                                       command_name='CL Licht Flur IO-Server-1/Q1')
        assert not await ensure_webio_link(admin, 29, _light(), 501, 0, plan,
                                           update_cache=True,
                                           command_name='CL Licht Flur IO-Server-1/Q1')

    asyncio.run(run())
    assert len(admin.posts) == 1
    assert admin.posts[0][0].endswith('/saveconnection/')
    saved = json.loads(admin.posts[0][1]['JSON'])
    assert saved['input']['element'] == '1'
    assert saved['output']['0']['element'] == '2'


def test_existing_firmware_graph_connection_means_no_writes():
    admin = RecordingAdmin()
    plan = {'elements': {
        '1': {'reference': {'type': 1, 'ref_id': 7}},
        '2': {'reference': {'type': 10, 'ref_id': 501}},
    }, 'connections': {
        '42': {'input': {'FubElementId': 1, 'IOPos': 0, 'Inverted': False},
               'output': [{'FubElementId': 2, 'IOPos': 0, 'Inverted': False}]},
    }}
    assert asyncio.run(ensure_webio_link(admin, 29, _light(), 501, 0, plan,
                                         update_cache=True,
                                         command_name='CL Licht Flur IO-Server-1/Q1')) is False
    assert admin.posts == []


def test_invalid_command_name_is_rejected_before_post():
    admin = RecordingAdmin()
    plan = {'elements': {}, 'connections': {}}
    with pytest.raises(AdminError, match='CL-Befehlsnamen'):
        asyncio.run(ensure_webio_link(admin, 29, _light(), 501, 0, plan,
                                      update_cache=True, command_name='wrong'))
    assert admin.posts == []
