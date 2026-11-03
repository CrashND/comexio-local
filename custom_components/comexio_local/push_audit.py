"""Read-only COMEXIO Web-IO push audit.

No COMEXIO mutation is performed here.  The audit uses the current dynamic
catalogue, existing Web-IO objects and only our namespaced function plans.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any
from urllib.parse import urlsplit

from .admin_api import ComexioAdmin, command_name, make_push_command
from .discovery import Channel
from .push_labels import command_candidates, plan_candidates
from .push_setup import _find_device, _find_plan, _plan_elements, _stable_groups, push_sources


@dataclass
class PushAudit:
    sources: int = 0
    linked: int = 0
    missing_commands: list[str] = field(default_factory=list)
    missing_links: list[str] = field(default_factory=list)
    wrong_settings: list[str] = field(default_factory=list)
    unknown_settings: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    plans_inspected: int = 0

    @property
    def ready(self) -> bool:
        return (
            self.sources > 0 and self.linked == self.sources
            and not (self.missing_commands or self.missing_links
                     or self.wrong_settings or self.unknown_settings or self.errors)
        )

    def as_dict(self) -> dict[str, Any]:
        return {
            "status": "ready" if self.ready else ("linked_unverified" if self.sources > 0 and self.linked == self.sources and not (self.missing_links or self.missing_commands or self.wrong_settings or self.errors) else "incomplete"),
            "sources": self.sources,
            "linked": self.linked,
            "plans_inspected": self.plans_inspected,
            "missing_commands": self.missing_commands,
            "missing_links": self.missing_links,
            "wrong_settings": self.wrong_settings,
            "unknown_settings": self.unknown_settings,
            "errors": self.errors,
        }


def audit_config(config: dict, plans: dict[str, dict], channels: dict[str, Channel],
                 entry_id: str, webhook_path: str, push_base: str) -> PushAudit:
    """Evaluate COMEXIO snapshot; never infer 'ready' from HTTP 200 alone."""
    targets = push_sources(channels)
    result = PushAudit(sources=len(targets))
    if not targets:
        result.errors.append("Keine Licht- oder Istpositions-Quellen erkannt")
        return result

    prefix = f"CL{entry_id[:8].upper()}"
    class_name = f"{prefix} Push"
    device_id = _find_device(config, class_name)
    if device_id is None:
        result.missing_commands.extend(c.key for c in targets)
        result.missing_links.extend(c.key for c in targets)
        return result

    device = (config.get("WebDevices") or {}).get(str(device_id), {})
    parsed = urlsplit(push_base)
    expected_address = f"{parsed.hostname}:{parsed.port}"
    address = str(device.get("Ip") or "").strip()
    if not address:
        result.unknown_settings.append("Web-IO-Zieladresse nicht auslesbar")
    elif address != expected_address:
        result.wrong_settings.append("Web-IO-Zieladresse weicht von der HA-LAN-Adresse ab")

    stored = (config.get("FubModules") or {}).get("10", {}).get(str(device_id), {})
    if not isinstance(stored, dict):
        result.errors.append("Web-IO-Kommandodaten besitzen ein unerwartetes Format")
        return result

    by_name: dict[str, list[tuple[str, dict]]] = {}
    for cmd_id, command in stored.items():
        if isinstance(command, dict) and command.get("Name"):
            by_name.setdefault(str(command["Name"]), []).append((str(cmd_id), command))

    available_cmd_ids: dict[str, int] = {}
    for channel in targets:
        candidates = [item for name in command_candidates(prefix, channel)
                      for item in by_name.get(name, [])]
        if not candidates:
            result.missing_commands.append(channel.key)
            continue
        if len(candidates) > 1:
            result.errors.append(f"Mehrere Web-IO-Kommandos für {channel.key}")
            continue
        cmd_id, stored_cmd = candidates[0]
        try:
            available_cmd_ids[channel.key] = int(cmd_id)
        except ValueError:
            result.errors.append(f"Ungültige Web-IO-Kommando-ID: {channel.key}")
            continue
        expected = make_push_command(prefix, channel, webhook_path)
        for key in ("Parameter", "Data", "HeaderModifier", "TypeId"):
            actual = stored_cmd.get(key)
            if actual is None:
                result.unknown_settings.append(f"{channel.key}: {key} nicht auslesbar")
                continue
            normalized = lambda v: str(v).replace("\r\n", "\n").strip()
            if normalized(actual) != normalized(expected[key]):
                result.wrong_settings.append(f"{channel.key}: {key} weicht ab")

    for bucket, group in _stable_groups(targets):
        candidates = [(name, match) for name in plan_candidates(prefix, bucket, group)
                      if (match := _find_plan(config, name)) is not None]
        if len(candidates) > 1:
            result.errors.append(f"Mehrere verwaltete Push-Logikplaene fuer {bucket}")
            result.missing_links.extend(c.key for c in group)
            continue
        identified = candidates[0][1] if candidates else None
        name = candidates[0][0] if candidates else plan_candidates(prefix, bucket, group)[-1]
        if not identified:
            result.missing_links.extend(c.key for c in group)
            continue
        plan_id, metadata = identified
        if entry_id not in str(metadata.get("Comment", "")):
            result.errors.append(f"Logikplan {name} hat keine bestätigte Eigentümerkennung")
            result.missing_links.extend(c.key for c in group)
            continue
        plan = plans.get(str(plan_id))
        if not isinstance(plan, dict):
            result.errors.append(f"Logikplan {name} konnte nicht vollständig gelesen werden")
            result.missing_links.extend(c.key for c in group)
            continue
        result.plans_inspected += 1
        refs, connections = _plan_elements(plan)
        active = metadata.get("Active")
        if str(active).lower() not in ("true", "1"):
            result.errors.append(f"Logikplan {name} ist nicht aktiv")
        for c in group:
            cmd_id = available_cmd_ids.get(c.key)
            if cmd_id is None:
                result.missing_links.append(c.key)
                continue
            kind = 2 if c.kind == "cover" else 1
            ref_id = c.marker_id if c.kind == "cover" else c.io_id
            src = refs.get((kind, int(ref_id))) if ref_id is not None else None
            dst = refs.get((10, cmd_id))
            if src is not None and dst is not None and any(src in edge and dst in edge for edge in connections):
                result.linked += 1
            else:
                result.missing_links.append(c.key)
    return result


async def audit_push(admin: ComexioAdmin, channels: dict[str, Channel], entry_id: str,
                     webhook_path: str, push_base: str) -> PushAudit:
    """Single on-demand configuration read and only our own plan inspections."""
    config = await admin.read_config()
    prefix = f"CL{entry_id[:8].upper()}"
    plans: dict[str, dict] = {}
    for bucket, _ in _stable_groups(push_sources(channels)):
        info = next((match for name in plan_candidates(prefix, bucket, group)
                     if (match := _find_plan(config, name)) is not None), None)
        if info:
            plan_id, metadata = info
            if entry_id in str(metadata.get("Comment", "")):
                plans[str(plan_id)] = await admin.read_plan(plan_id)
    return audit_config(config, plans, channels, entry_id, webhook_path, push_base)
