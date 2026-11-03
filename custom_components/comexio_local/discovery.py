"""Dynamic COMEXIO topology inference.  No addresses, room mappings, or channel numbers.

COMEXIO exposes extension IOs as $FubModules['1'], markers as $FubModules['2'],
and plan names as $Fubs.  The names are user-supplied, so ambiguous outputs
are *never* assumed to be lights or individually switchable shutter motors.
"""
from __future__ import annotations
from dataclasses import dataclass
import re
from typing import Any

LIGHT = re.compile(r"\b(licht|leuchte|beleuchtung|lampe|led|spot|spots|indirekt|deckenlicht|wandlicht|downlight|light)\b", re.I)
MOTOR = re.compile(r"\b(roll|rollo|rollladen|rolladen|jalousie|markis\w*|raffstore|blind|motor|antrieb)\b", re.I)
POSITION = re.compile(r"^R[_\s-]*(.+?)[_\s-]+(soll|ist)$", re.I)
BINARY_OUT = re.compile(r"^Q\d+$", re.I)
INPUT = re.compile(r"^(?:I|AI|QI)\d+$", re.I)

@dataclass(frozen=True)
class Channel:
    kind: str                   # light, relay, motor, input, analog_input, cover
    name: str
    key: str                    # immutable COMEXIO address for stable IDs
    extension: str = ""
    identifier: str = ""
    io_id: int | None = None
    marker_id: int | None = None # cover *actual* marker ID
    target_marker_id: int | None = None
    analog: bool = False
    plan: str = ""
    unit: str = ""

    @property
    def source(self) -> tuple[str, str, str]:
        if self.kind == "cover":
            return ("marker", str(self.marker_id), "")
        return ("io", self.extension, self.identifier)

    @property
    def is_push_source(self) -> bool:
        return self.kind in ("light", "cover")


def _items(data: Any):
    return data.values() if isinstance(data, dict) else data if isinstance(data, list) else ()


def _flag(value: Any) -> bool:
    return value is True or value == 1 or str(value).lower() in ("true", "1")


def _text(value: Any) -> str:
    return " ".join(str(value or "").split())


def _stem(value: str) -> str:
    return re.sub(r"[\W_]+", "", value, flags=re.UNICODE).casefold()


def extract_plan_assignments(plans: dict[str, Any], fubs: dict[str, Any]) -> dict[tuple[int, int], str]:
    """Match raw IO/marker references to existing room plan names.

    This is used only for naming/classification.  It never edits an existing plan.
    """
    result: dict[tuple[int, int], str] = {}
    for plan_id, payload in plans.items():
        plan = fubs.get(str(plan_id), {})
        plan_name = _text(plan.get("Name"))
        if not plan_name or plan_name.casefold().startswith(("ha ", "homeassistant", "cl push")) or re.match(r"^CL[A-Z0-9]{8}\b", plan_name, re.I):
            continue
        for element in _items(payload.get("elements", {})):
            reference = element.get("reference", {}) if isinstance(element, dict) else {}
            try:
                pair = (int(reference.get("type")), int(reference.get("ref_id")))
            except (TypeError, ValueError):
                continue
            if pair[0] in (1, 2):
                result.setdefault(pair, plan_name)
    return result


def discover(config: dict[str, Any], plans: dict[str, Any] | None = None) -> dict[str, Channel]:
    """Discover from live COMEXIO configuration, never a predefined catalogue."""
    modules = config.get("FubModules") or {}
    fubs = config.get("Fubs") or {}
    assignment = extract_plan_assignments(plans or {}, fubs)
    found: dict[str, Channel] = {}

    for extension in _items(modules.get("1", {})):
        if not isinstance(extension, dict):
            continue
        metadata = extension.get("extension", {})
        ext_name = _text(metadata.get("Name"))
        if not ext_name:
            continue
        for item in _items(extension.get("inoutput", {})):
            if not isinstance(item, dict) or not _flag(item.get("Active")):
                continue
            identifier = _text(item.get("Identifier"))
            if not identifier:
                continue
            raw_id = item.get("Id")
            try:
                io_id = int(raw_id)
            except (TypeError, ValueError):
                continue
            desc = _text(item.get("Description"))
            plan_name = assignment.get((1, io_id), "")
            # Plan context identifies the room. Physical wiring / signal type wins.
            label = " ".join(x for x in (plan_name, desc or f"{ext_name} {identifier}") if x)
            if BINARY_OUT.fullmatch(identifier):
                if MOTOR.search(desc):
                    kind = "motor"  # never expose motors as individual switches
                elif LIGHT.search(desc):
                    kind = "light"
                else:
                    kind = "relay"  # safe read-only discovery, not auto-writable
            elif INPUT.fullmatch(identifier):
                kind = "input" if identifier.upper().startswith("I") else "analog_input"
            else:
                continue
            address = f"{ext_name}/{identifier}"
            found[f"io:{address}"] = Channel(
                kind=kind, name=label, key=f"io:{address}", extension=ext_name,
                identifier=identifier, io_id=io_id, plan=plan_name,
                analog=kind == "analog_input",
            )

    # COMEXIO roller/function plans use dedicated R_<room>_soll and R_<room>_ist markers.
    # Pair by dynamic name stems; marker IDs may change without any code change.
    positions: dict[str, dict[str, tuple[int, str]]] = {}
    for marker in _items(modules.get("2", {})):
        if not isinstance(marker, dict):
            continue
        title = _text(marker.get("Name"))
        if marker.get("Type") is not None and str(marker["Type"]) not in ("2", "3"):
            continue
        match = POSITION.match(title)
        if match is None:
            continue
        try:
            marker_id = int(marker["Id"])
        except (KeyError, ValueError, TypeError):
            continue
        key = _stem(match[1]); role = match[2].casefold()
        positions.setdefault(key, {})[role] = (marker_id, match[1])

    for role_pair in positions.values():
        if "soll" not in role_pair or "ist" not in role_pair:
            continue
        actual_id, title = role_pair["ist"]
        target_id, _ = role_pair["soll"]
        friendly = title.replace("_", " ").strip()
        found[f"cover:M{actual_id}"] = Channel(
            kind="cover", name=f"Rollladen {friendly}", key=f"cover:M{actual_id}",
            marker_id=actual_id, target_marker_id=target_id, analog=True,
        )
    return found


def event_address(data: dict[str, Any]) -> str | None:
    """Return an immutable COMEXIO event source matching the dynamic catalogue."""
    typ = str(data.get("type", "")).casefold()
    if typ == "io":
        ext = data.get("ext"); io = data.get("io")
        return f"io:{ext}/{io}" if isinstance(ext, str) and isinstance(io, str) else None
    if typ == "marker":
        ident = str(data.get("id", ""))
        if ident.upper().startswith("M"):
            ident = ident[1:]
        return f"cover:M{ident}" if ident.isdecimal() else None
    return None
