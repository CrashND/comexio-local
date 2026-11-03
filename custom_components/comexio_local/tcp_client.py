"""Small, independent implementation of the COMEXIO newline JSON TCP API.

Every request is one JSON object and a trailing newline. Connections are
short-lived. No configuration changes, no retries, no persistent sessions.
"""

from __future__ import annotations

import asyncio
import json
import time
from typing import Any, Sequence

from .discovery import Channel
from .constants import TIMEOUT, MIN_REQUEST_GAP


class ComexioError(Exception):
    """COMEXIO communication or response failure."""


class ComexioTCPClient:
    """Serialize this integration's requests, avoiding request bursts."""

    def __init__(self, host: str, port: int, timeout: float = TIMEOUT):
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
            wait = MIN_REQUEST_GAP - (time.monotonic() - self._last_request_started)
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

    async def set_channel(self, channel: Channel, state: bool) -> None:
        """Send an explicitly enabled direct IO command.

        A SET acknowledgement is not the confirmed light state. Call a GET
        afterward; the server-side RS/impulse logic may override direct writes.
        """
        response = await self._request(
            {"set": {"action": "set", "ext": channel.extension, "io": channel.identifier, "value": int(state)}}
        )
        if "set" not in response or response["set"] is None:
            raise ComexioError("SET response missing expected key or value")

    async def read_sources(self, channels: Sequence[Channel]) -> dict[str, float | bool | None]:
        """A single batch GET for digital IOs plus analog marker positions."""
        if not channels:
            return {}
        request: dict[str, Any] = {}
        for i, channel in enumerate(channels):
            if channel.kind == "cover":
                request[f"s{i}"] = {"action": "get", "marker": f"M{channel.marker_id}"}
            else:
                request[f"s{i}"] = {"action": "get", "ext": channel.extension, "io": channel.identifier}
        response = await self._request(request)
        found: dict[str, float | bool | None] = {}
        for i, channel in enumerate(channels):
            raw = response.get(f"s{i}")
            try:
                found[channel.key] = None if raw is None else (float(raw) if channel.analog else self._read_onoff(raw, channel.key))
            except (ValueError, TypeError, ComexioError):
                found[channel.key] = None
        return found

    async def write_marker(self, marker_id: int, position: float) -> None:
        result = await self._request({"set": {"action": "set", "marker": f"M{marker_id}", "value": position}})
        if "set" not in result:
            raise ComexioError("Marker write not acknowledged")
