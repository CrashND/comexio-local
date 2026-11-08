"""Regression: every new Web-IO plan block carries a canonical display name.

The COMEXIO firmware 11.1.5 visual result must still be verified on hardware.
"""
from __future__ import annotations

import asyncio

import pytest

from comexio_local.admin_api import AdminError, ComexioAdmin
from comexio_local.discovery import Channel
from comexio_local.managed_graph import ensure_webio_link
from comexio_local.push_labels import friendly_command_name
from comexio_local.input_push import input_command_name


class CapturingAdmin(ComexioAdmin):
    def __init__(self):
        super().__init__(None, "comexio.invalid", "user", "pw")
        self.posts = []

    async def request_json(self, method, route, *, data=None, **_kwargs):
        self.posts.append((method, route, data))
        return {"id": len(self.posts) + 1000}


def test_add_element_posts_webio_name_and_keeps_source_behavior():
    admin = CapturingAdmin()

    async def go():
        await admin.add_element(22, 101, 1, 40, 60)
        await admin.add_element(22, 515, 10, 400, 60,
                                connection={"0": {"id": "new"}},
                                name="CL Licht Flur IO-Server-1/Q1")
        with pytest.raises(AdminError, match="CL-Namen"):
            await admin.add_element(22, 515, 10, 400, 60)

    asyncio.run(go())
    assert len(admin.posts) == 2  # invalid data must fail BEFORE POST
    assert admin.posts[0][2]["name"] == ""
    assert admin.posts[1][2]["name"] == "CL Licht Flur IO-Server-1/Q1"
    assert admin.posts[1][2]["ref_id"] == "515"
    assert admin.posts[1][2]["type"] == "10"
    assert "connection" in admin.posts[1][2]


@pytest.mark.parametrize(
    "channel,expected_name,analog",
    [
        (Channel(kind="light", name="Licht Flur", key="io:IO-Server-1/Q1",
                 extension="IO-Server-1", identifier="Q1", io_id=7, plan="Flur"),
         "CL Licht Flur IO-Server-1/Q1", False),
        (Channel(kind="cover", name="Rollladen Buero", key="cover:M85",
                 marker_id=85, target_marker_id=84, analog=True),
         "CL Rollladen Buero M85", True),
        (Channel(kind="binary_input", name="Flur Licht Rot", key="io:IO-Ext-3/I1",
                 extension="IO-Ext-3", identifier="I1", io_id=29, input_mode="taster"),
         "CL Eingang IO-Ext-3/I1", False),
    ],
)
def test_link_graph_names_new_webio_block(channel, expected_name, analog):
    admin = CapturingAdmin()
    async def go():
        plan = {"elements": {}, "connections": {}}
        assert await ensure_webio_link(admin, 22, channel, 515, 0, plan,
                                       update_cache=True, command_name=expected_name)
        assert await ensure_webio_link(admin, 22, channel, 515, 0, plan,
                                       update_cache=True, command_name=expected_name) is False

    asyncio.run(go())
    assert len(admin.posts) == 2  # exactly two elements, no repeated writes
    source, webio = (record[2] for record in admin.posts)
    assert source["name"] == ""
    assert webio["name"] == expected_name
    assert webio["type"] == "10"
    assert analog == ("analog" in webio["connection"])


def test_channel_label_matches_command_name_generators():
    light = Channel(kind="light", name="Flurlicht", key="io:IO-Server-1/Q1",
                    extension="IO-Server-1", identifier="Q1", io_id=7, plan="Flur")
    button = Channel(kind="binary_input", name="Flur Licht Rot", key="io:IO-Ext-3/I1",
                     extension="IO-Ext-3", identifier="I1", io_id=29)
    assert friendly_command_name(light) == "CL Licht Flur IO-Server-1/Q1"
    assert input_command_name(button) == "CL Eingang IO-Ext-3/I1"
