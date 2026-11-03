"""Offline protocol tests with a fake COMEXIO JSON/TCP server."""

import asyncio
import importlib.util
import pathlib
import sys
import types
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
PARTS = ROOT / "custom_components" / "comexio_local"
PACKAGE = "comexio_local"
package = types.ModuleType(PACKAGE)
package.__path__ = [str(PARTS)]
sys.modules[PACKAGE] = package


def load_module(name):
    spec = importlib.util.spec_from_file_location(f"{PACKAGE}.{name}", PARTS / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


catalog = load_module("catalog")
load_module("const")
protocol = load_module("tcp_client")


class ApiServer:
    def __init__(self):
        self.states = {(ch.extension, ch.io): 0 for ch in catalog.CHANNELS}
        self.requests = []
        self.server = None

    async def handler(self, reader, writer):
        data = await reader.readline()
        if data:
            import json
            req = json.loads(data)
            self.requests.append(req)
            resp = {}
            for key, item in req.items():
                address = (item.get("ext"), item.get("io"))
                if address not in self.states:
                    continue
                if item["action"] == "set":
                    self.states[address] = item["value"]
                resp[key] = self.states[address]
            writer.write((json.dumps(resp) + "\n").encode())
            await writer.drain()
        writer.close()
        await writer.wait_closed()

    async def __aenter__(self):
        self.server = await asyncio.start_server(self.handler, "127.0.0.1", 0)
        return self

    async def __aexit__(self, *args):
        self.server.close()
        await self.server.wait_closed()

    @property
    def port(self):
        return self.server.sockets[0].getsockname()[1]


class ProtocolTests(unittest.IsolatedAsyncioTestCase):
    async def test_all_16_channels_in_single_get_and_physical_change(self):
        async with ApiServer() as server:
            client = protocol.ComexioTCPClient("127.0.0.1", server.port)
            first = await client.read_channels(catalog.CHANNELS)
            self.assertEqual(len(first), 16)
            self.assertTrue(all(value is False for value in first.values()))
            server.states[("IO-Ext-2", "Q1")] = 1  # a physical wall switch changed the relay
            second = await client.read_channels(catalog.CHANNELS)
            self.assertTrue(second["guest_room"])
            self.assertEqual(client.request_count, 2)
            self.assertEqual(len(server.requests), 2)
            self.assertEqual(len(server.requests[0]), 16)

    async def test_explicit_set_then_get_confirmation(self):
        async with ApiServer() as server:
            client = protocol.ComexioTCPClient("127.0.0.1", server.port)
            ch = catalog.CHANNEL_BY_ID["guest_room"]
            await client.set_channel(ch, True)
            state = await client.read_channels((ch,))
            self.assertIs(state["guest_room"], True)
            self.assertEqual([list(x.values())[0]["action"] for x in server.requests], ["set", "get"])

    async def test_missing_value_is_unavailable_not_off(self):
        async with ApiServer() as server:
            client = protocol.ComexioTCPClient("127.0.0.1", server.port)
            unknown = catalog.Channel("missing", "Unknown", "IO-Ext-Missing", "Q1")
            data = await client.read_channels((unknown,))
            self.assertEqual(data, {"missing": None})

    def test_wrong_value_rejected(self):
        for value in (2, "invalid", {}, [], None):
            with self.assertRaises(protocol.ComexioError):
                protocol.ComexioTCPClient._read_onoff(value, "x")

    async def test_connection_failure_does_not_retry(self):
        client = protocol.ComexioTCPClient("127.0.0.1", 1, timeout=0.1)
        with self.assertRaises(protocol.ComexioError):
            await client.read_channels((catalog.CHANNEL_BY_ID["guest_room"],))
        self.assertEqual(client.request_count, 1)
        self.assertEqual(client.error_count, 1)


if __name__ == "__main__":
    unittest.main()
