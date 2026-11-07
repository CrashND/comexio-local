"""Explicit, incremental Web-IO push installation.

Unlike an unrestricted full sync, only confirmed light outputs and actual cover
position markers are linked. Never touches the original user room plans.
"""
from __future__ import annotations
import asyncio
import base64
import logging
import zlib
from .admin_api import AdminError, ComexioAdmin, command_name, make_push_command
from .discovery import Channel
from .push_labels import command_candidates, friendly_command_name, plan_candidates, push_class_candidates
from .managed_resources import (is_owned_plan, plan_comment, find_unique_named_plan,
                                unique_webio_commands)
from .managed_graph import PLAN_ROWS, ensure_webio_link, plan_elements as _plan_elements
from .push_target import private_lan_host_port

_LOGGER=logging.getLogger(__name__)
MAX_SIGNALS_PER_PLAN=PLAN_ROWS


def push_sources(channels: dict[str, Channel]) -> list[Channel]:
    return sorted((c for c in channels.values() if c.is_push_source and c.kind != "binary_input"),key=lambda c:c.key)


def _stable_groups(signals: list[Channel]) -> list[tuple[str, list[Channel]]]:
    """Keep device-to-plan association stable as new IOs are added in other modules."""
    groups: dict[str, list[Channel]] = {}
    for signal in signals:
        bucket = signal.extension if signal.kind != "cover" else "POSITIONEN"
        groups.setdefault(bucket, []).append(signal)
    grouped = []
    for bucket in sorted(groups):
        signals_in_module = sorted(groups[bucket], key=lambda s: s.key)
        # Short deterministic name avoids COMEXIO plan-name length/character limitations.
        label = f"G{zlib.crc32(bucket.encode()):08X}"
        for start in range(0,len(signals_in_module),MAX_SIGNALS_PER_PLAN):
            suffix = start // MAX_SIGNALS_PER_PLAN
            grouped.append((f"{label}-{suffix}", signals_in_module[start:start+MAX_SIGNALS_PER_PLAN]))
    return grouped


def _existing_commands(config: dict, device_id: str) -> dict[str, int]:
    """Compact name-to-ID view of the shared, collision-safe command index."""
    return {name: cid for name, (cid, _) in unique_webio_commands(config, device_id, allow_staged=True).items()}


def _find_push_device(config: dict, prefix: str) -> tuple[str | None, str]:
    """Find one owned-class name, refusing ambiguous old/new duplicates.

    The readable class name applies to freshly provisioned objects. Do not
    rename an existing class or silently create a parallel one on upgrades.
    """
    names = push_class_candidates(prefix)
    matches = [(str(did), str(dev.get('Name'))) for did, dev in
               (config.get('WebDevices') or {}).items()
               if isinstance(dev, dict) and dev.get('Name') in names]
    if len(matches) > 1:
        raise AdminError('Mehrere COMEXIO-Local-Push-Klassen gefunden; keine automatische Aenderung')
    return matches[0] if matches else (None, names[-1])


def _find_plan(config: dict, name: str) -> tuple[int, dict] | None:
    """Compatibility wrapper for the shared unique plan resolver."""
    return find_unique_named_plan(config, name)


async def _get_base_id(admin: ComexioAdmin, name: str) -> str:
    """Use the single, HTML-tolerant COMEXIO Web-IO base-ID parser."""
    base_id = await admin._base_id_by_name(name)
    if base_id is None:
        raise AdminError('COMEXIO-Web-IO-Basistyp nicht eindeutig vorhanden: ' + name)
    return base_id


async def _append_command(admin: ComexioAdmin, device_id: str, base_id: str, cmd: dict) -> None:
    """Append one command without modifying any existing Web-IO command."""
    empty_ref=base64.b64encode(b'{"src":"command","id":null}').decode("ascii")
    data={
      "dlg_web_device_id":str(device_id),"protocol":0,"parameter":cmd["Parameter"],
      "header_modifier":cmd["HeaderModifier"],"data":cmd["Data"],"port":"",
      "post_get":1,"authentication":0,"req_freq":"","reply_interpreter":"",
      "id_cmd_io_0":empty_ref,"name_cmd_io_0":cmd["Name"],
      "function_cmd_io_0":"1_1_0","input_cmd_io_0":1,
      "type_cmd_io_0":cmd["TypeId"],"send_on_one_cmd_io_0":0,
      "min_cmd_io_0":0,"max_cmd_io_0":cmd["Max"],"default_value_cmd_io_0":"",
      "id_cmd_io_sample":"","name_cmd_io_sample":"","function_cmd_io_sample":"0_1_0",
      "input_cmd_io_sample":1,"type_cmd_io_sample":2,"send_on_one_cmd_io_sample":0,
      "min_cmd_io_sample":0,"max_cmd_io_sample":1,"default_value_cmd_io_sample":"",
      "DefaultActive":1,"deviceBaseId":str(base_id),
    }
    # COMEXIO save_command returns 200 on success; inspect later via raw discovery.
    async with admin._lock:
        await admin._wait_write_slot()
        async with admin.session.post(admin.base+"/admin/web_io/save_command",data=data,headers=admin._headers) as response:
            if response.status != 200:
                raise AdminError(f"Web-IO command '{cmd['Name']}' failed: HTTP {response.status}")


async def _wire_pair(admin: ComexioAdmin, plan_id: int, signal: Channel, command_id: int,
                     index: int, plan: dict) -> bool:
    return await ensure_webio_link(admin, plan_id, signal, command_id, index,
                                   plan, update_cache=False)


async def configure_push(admin:ComexioAdmin, channels:dict[str,Channel],entry_id:str,
                         webhook_path:str,push_base:str) -> dict[str,int]:
    """Apply after explicit user consent and existing full COMEXIO backup."""
    signals=push_sources(channels)
    if not signals:
        raise AdminError("No lights or actual cover position markers discovered")
    if len(signals)>90:
        raise AdminError("Too many push sources; select a smaller installation before setup")
    host_port = private_lan_host_port(push_base)
    if host_port is None:
        raise AdminError('Push-Ziel muss eine private LAN-HTTP-IPv4-Adresse mit Port sein')
    short=entry_id[:8].upper()
    prefix=f"CL{short}"
    class_name = push_class_candidates(prefix)[-1]
    marker_comment=plan_comment(entry_id, 'push')
    status={"created_commands":0,"added_pairs":0,"activated_plans":0}
    # Fail closed on a stale callback or a conflicting, unexpected installation.
    # Never rewrite an existing Web-IO endpoint behind the user's back.
    from .push_audit import audit_push
    preflight = await audit_push(admin, channels, entry_id, webhook_path, push_base)
    if preflight.wrong_settings:
        raise AdminError("Bestehende COMEXIO-Web-IO-Einstellungen weichen ab: " + "; ".join(preflight.wrong_settings[:4]) + ". Keine Aenderungen vorgenommen.")
    if any("Eigentümerkennung" in err or "Mehrere Web-IO" in err for err in preflight.errors):
        raise AdminError("Mehrdeutige vorhandene Push-Konfiguration: " + "; ".join(preflight.errors[:4]))
    if preflight.unknown_settings and preflight.linked:
        raise AdminError("Vorhandene Push-Einstellungen lassen sich nicht sicher verifizieren. Keine automatische Reparatur.")
    config=await admin.read_config()
    device_id, class_name = _find_push_device(config, prefix)
    if device_id is None:
        # COMEXIO can miss internal bindings when too many commands are uploaded at once.
        # Seed only ONE command in the device import, then append the rest serially.
        first = signals[0]
        await admin.create_push_class(class_name, [make_push_command(
            prefix, first, webhook_path, name=friendly_command_name(first))], host_port)
        await asyncio.sleep(0.8)
        config = await admin.read_config()
        device_id, _ = _find_push_device(config, prefix)
        if device_id is None:
            raise AdminError("Web-IO device not visible after creation; not retrying the write")
        status["created_commands"] = 1
    existing = _existing_commands(config, device_id)
    def command_id_for(c):
        hits = [existing[name] for name in command_candidates(prefix, c) if name in existing]
        if len(hits) > 1:
            raise AdminError("Mehrere COMEXIO-Local-Befehle fuer " + c.key)
        return hits[0] if hits else None
    missing = [c for c in signals if command_id_for(c) is None]
    if missing:
        base_id = str((config.get("WebDevices") or {}).get(str(device_id), {}).get("BaseId") or "")
        if not base_id:
            base_id = await _get_base_id(admin, class_name)
        for c in missing:
            await _append_command(admin, device_id, base_id, make_push_command(
                prefix, c, webhook_path, name=friendly_command_name(c)))
            await asyncio.sleep(0.8)  # allow COMEXIO's internal reference table to settle
            config = await admin.read_config()
            existing = _existing_commands(config, device_id)
            if command_id_for(c) is None:
                raise AdminError(f"Web-IO-Befehl {c.key} nach Schreiben nicht sichtbar; Vorgang gestoppt")
            status["created_commands"] += 1
    for group_name, group in _stable_groups(signals):
        matches = [(name, found) for name in plan_candidates(prefix, group_name, group)
                   if (found := _find_plan(config, name)) is not None]
        if len(matches) > 1:
            raise AdminError("Mehrere verwaltete Push-Plaene fuer " + group_name)
        name = matches[0][0] if matches else plan_candidates(prefix, group_name, group)[-1]
        info = matches[0][1] if matches else None
        if info:
            plan_id,meta=info
            if not is_owned_plan(meta, entry_id, 'push'):
                raise AdminError(f"Refusing to modify unowned plan {name}")
        else:
            plan_id=await admin.create_plan(name,marker_comment)
            config=await admin.read_config()
        plan=await admin.read_plan(plan_id)
        changed=False
        for k,signal in enumerate(group):
            command_id=command_id_for(signal)
            if command_id is None:
                raise AdminError("Web-IO command ID not visible: " + signal.name)
            if await _wire_pair(admin,plan_id,signal,command_id,k,plan):
                await asyncio.sleep(0.8)
                status["added_pairs"]+=1
                changed=True
                plan=await admin.read_plan(plan_id)
                src_type=2 if signal.kind=="cover" else 1
                src_ref=signal.marker_id if signal.kind=="cover" else signal.io_id
                refs,edges=_plan_elements(plan)
                src=refs.get((src_type,int(src_ref)))
                dst=refs.get((10,int(command_id)))
                if src is None or dst is None or not any(src in e and dst in e for e in edges):
                    raise AdminError("COMEXIO-Link nach Schreiben nicht sichtbar: " + signal.key)
        plan_active = (config.get("Fubs") or {}).get(str(plan_id),{}).get("Active")
        if changed or str(plan_active).lower() not in ("1", "true"):
            await admin.run_plan(plan_id)
            status["activated_plans"]+=1
    # Verify resulting COMEXIO topology once, not by polling indefinitely.
    verified = await audit_push(admin, channels, entry_id, webhook_path, push_base)
    status["linked"] = verified.linked
    status["targets"] = verified.sources
    status["verified_status"] = verified.as_dict()["status"]
    if verified.missing_links or verified.missing_commands or verified.wrong_settings or verified.errors:
        raise AdminError("Push-Konfiguration unvollstaendig nach Anlage; moegliche Teilaenderungen. Zuerst Diagnose und COMEXIO-Backup pruefen. "
                         + str(verified.as_dict()))
    _LOGGER.info("COMEXIO Local push installed: %s",status)
    return status
