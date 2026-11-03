"""Small, independent implementation of the COMEXIO newline JSON TCP API.

Every request is one JSON object and a trailing newline. Connections are
short-lived. No configuration changes, no retries, no persistent sessions.
"""

from __future__ import annotations

import asyncio
import json
import time
from typing import Any, Sequence

from .catalog import Channel
from .const import DEFAULT_TCP_TIMEOUT, MIN_SECONDS_BETWEEN_REQUESTS


class ComexioError(Exception):
    """COMEXIO communication or response failure."""


class ComexioTCPClient:
    """Serialize this integration's requests, avoiding request bursts."""

    def __init__(self, host: str, port: int, timeout: float = DEFAULT_TCP_TIMEOUT):
        self.host = host
        self.port = port
        self.timeout = timeout
        self._lock = asyncio.Lock()
        self._last_request_started = 0.0
        self.request_count = 0
        self.error_count = 0
        self.last_latency_ms: float | None = None

    async def _request(self, request: dict[str, Any]) -> dict[str, Any]:
        if not request:
            raise ComexioError("Empty request")

        async with self._lock:
            wait = MIN_SECONDS_BETWEEN_REQUESTS - (time.monotonic() - self._last_request_started)
            if wait > 0:
                await asyncio.sleep(wait)

            self._last_request_started = time.monotonic()
            self.request_count += 1
            writer = None
            try:
                reader, writer = await asyncio.wait_for(
                    asyncio.open_connection(self.host, self.port), timeout=self.timeout
                )
                encoded = (json.dumps(request, ensure_ascii=True, separators=(",", ":")) + "\n").encode()
                writer.write(encoded)
                await asyncio.wait_for(writer.drain(), timeout=self.timeout)
                raw = await asyncio.wait_for(reader.readline(), timeout=self.timeout)
                if not raw:
                    raise ComexioError("Server closed connection without a response")
                try:
                    response = json.loads(raw.decode("utf-8"))
                except (UnicodeError, json.JSONDecodeError) as err:
                    raise ComexioError("Server response is not valid JSON") from err
                if not isinstance(response, dict):
                    raise ComexioError("Server returned a non-object response")
                self.last_latency_ms = round(1000 * (time.monotonic() - self._last_request_started), 1)
                return response
            except (ComexioError, OSError, TimeoutError, ValueError) as err:
                self.error_count += 1
                if isinstance(err, ComexioError):
                    raise
                raise ComexioError(f"TCP communication failed: {type(err).__name__}") from err
            finally:
                if writer is not None:
                    writer.close()
                    try:
                        await asyncio.wait_for(writer.wait_closed(), timeout=0.5)
                    except (OSError, TimeoutError):
                        pass

    @staticmethod
    def _read_onoff(value: Any, key: str) -> bool:
        if isinstance(value, bool):
            return value
        if isinstance(value, (int, float)) and value in (0, 1):
            return bool(value)
        if isinstance(value, str) and value.strip() in ("0", "1"):
            return value.strip() == "1"
        raise ComexioError(f"Unexpected digital value for {key}: {value!r}")

    async def read_channels(self, channels: Sequence[Channel]) -> dict[str, bool | None]:
        """Read all selected channels in a single keyed JSON GET request.

        Missing fields become None (unavailable), never false. No automatic
        fallback to N individual requests on an overloaded legacy controller.
        """
        if not channels:
            return {}
        request = {
            f"c{i}": {"action": "get", "ext": channel.extension, "io": channel.io}
            for i, channel in enumerate(channels)
        }
        response = await self._request(request)
        states: dict[str, bool | None] = {}
        for index, channel in enumerate(channels):
            key = f"c{index}"
            value = response.get(key)
            if value is None:
                states[channel.id] = None
                continue
            try:
                states[channel.id] = self._read_onoff(value, key)
            except ComexioError:
                states[channel.id] = None
        return states

    async def set_channel(self, channel: Channel, state: bool) -> None:
        """Send an explicitly enabled direct IO command.

        A SET acknowledgement is not the confirmed light state. Call a GET
        afterward; the server-side RS/impulse logic may override direct writes.
        """
        response = await self._request(
            {"set": {"action": "set", "ext": channel.extension, "io": channel.io, "value": int(state)}}
        )
        if "set" not in response:
            raise ComexioError("SET response missing expected key")
        result = response["set"]
        if not (isinstance(result, (int, float, bool)) and result in (0, 1)) and not (isinstance(result, str) and result.strip() in ("0", "1")):
            raise ComexioError("Unexpected SET acknowledgement")
