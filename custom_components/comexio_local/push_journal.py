"""Bounded, in-memory diagnostic journal for accepted COMEXIO webhook events.

No background tasks, remote requests, credentials, or persistent payload logging.
"""
from __future__ import annotations

from collections import deque
from datetime import datetime, timezone
from typing import Any

MAX_EVENTS = 80
SENSOR_EVENTS = 12
DEFAULT_REPORT_EVENTS = 30


def _normalise(value: Any) -> int | float | None:
    """Convert boolean light values to 0/1 without changing analog positions."""
    if value is None:
        return None
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, (int, float)):
        return value
    raise TypeError("Unexpected accepted COMEXIO event value")


class PushJournal:
    """Keep a small tail plus per-source statistics for the current HA run."""

    def __init__(self, capacity: int = MAX_EVENTS) -> None:
        self._events: deque[dict[str, Any]] = deque(maxlen=capacity)
        self._sources: dict[str, dict[str, Any]] = {}
        self.total = 0
        self.same_as_cached = 0

    def record(
        self,
        *,
        source: str,
        name: str,
        kind: str,
        value: int | float | bool,
        previous: int | float | bool | None,
        entity_id: str | None = None,
        received_at: datetime | None = None,
    ) -> dict[str, Any]:
        timestamp = (received_at or datetime.now(timezone.utc)).astimezone(timezone.utc)
        now = timestamp.isoformat(timespec="milliseconds")
        current = _normalise(value)
        old = _normalise(previous)
        changed_since_cached = None if old is None else old != current

        self.total += 1
        if changed_since_cached is False:
            self.same_as_cached += 1
        event = {
            "seq": self.total,
            "received_at_utc": now,
            "source": source,
            "name": name,
            "kind": kind,
            "value": current,
            "previous_cached_value": old,
            "changed_since_cached": changed_since_cached,
            "entity_id": entity_id,
        }
        self._events.appendleft(event)
        summary = self._sources.setdefault(source, {
            "name": name,
            "kind": kind,
            "count": 0,
            "same_as_cached": 0,
            "last_value": None,
            "last_received_at_utc": None,
            "entity_id": entity_id,
        })
        summary["count"] += 1
        if changed_since_cached is False:
            summary["same_as_cached"] += 1
        summary.update({
            "name": name,
            "kind": kind,
            "last_value": current,
            "last_received_at_utc": now,
            "entity_id": entity_id,
        })
        return event

    def recent(self, limit: int = DEFAULT_REPORT_EVENTS) -> list[dict[str, Any]]:
        return [dict(event) for event in list(self._events)[:limit]]

    def sources(self) -> dict[str, dict[str, Any]]:
        """Most active sources first. Empty means no push has reached HA yet."""
        return {
            source: dict(summary)
            for source, summary in sorted(
                self._sources.items(), key=lambda item: (-item[1]["count"], item[0])
            )
        }

    def report(self, limit: int = DEFAULT_REPORT_EVENTS) -> dict[str, Any]:
        return {
            "total_since_start": self.total,
            "unique_sources": len(self._sources),
            "same_as_cached": self.same_as_cached,
            "retained_events": len(self._events),
            "last_events": self.recent(limit),
            "sources": self.sources(),
        }
