"""Safe on-demand push repair: read-only preview and additive, confirmed repairs.

Only missing integration-owned resources are created. Replacing an EXISTING command
requires COMEXIO deletion calls which are not verified against firmware 11.1.5;
never guess destructive endpoints. Such cases are shown as guided manual rebuilds.
"""
from __future__ import annotations

import asyncio
from dataclasses import dataclass
import hashlib
import json
from urllib.parse import urlsplit

from .admin_api import AdminError, ComexioAdmin, make_push_command
from .discovery import Channel
from .push_labels import friendly_command_name, friendly_plan_name
from .managed_resources import is_owned_plan, plan_comment, unique_webio_commands
from .push_target import private_lan_host_port
from .push_setup import (
    _append_command, _existing_commands, _find_push_device, _find_plan, _get_base_id,
    _plan_elements, _stable_groups, _wire_pair, push_sources,
)


class RepairError(AdminError):
    """Preview or safe execution refused; no arbitrary COMEXIO writes."""


@dataclass(frozen=True)
class SourceInspection:
    key: str
    name: str
    kind: str
    address: str
    command_name: str
    plan_name: str
    action: str  # none, create_command, restore_link, manual_rebuild, blocked
    detail: str
    last_event_utc: str | None = None

    def as_dict(self) -> dict:
        return vars(self).copy()


@dataclass(frozen=True)
class RepairPreview:
    mode: str
    fingerprint: str
    inspections: tuple[SourceInspection, ...]

    @property
    def has_blocks(self) -> bool:
        return any(i.action in ('blocked', 'manual_rebuild') for i in self.inspections)

    @property
    def needs_write(self) -> bool:
        return any(i.action in ('create_command', 'restore_link') for i in self.inspections)

    def as_dict(self) -> dict:
        return {
            'mode': self.mode,
            'fingerprint': self.fingerprint,
            'sources': [i.as_dict() for i in self.inspections],
            'blocked': self.has_blocks,
            'needs_write': self.needs_write,
            'writes_require_backup': self.needs_write,
            'note': 'Die Vorschau ist rein lesend. Empfangene Ereignisse sind kein Funktionsnachweis fuer ungetestete Quellen.',
        }


def _source_groups(channels: dict[str, Channel]) -> dict[str, tuple[str, list[Channel]]]:
    return {signal.key: (bucket, group) for bucket, group in _stable_groups(push_sources(channels))
            for signal in group}


def _fingerprint(config: dict, plan_payloads: dict[int, dict], device_id: str | None,
                 relevant_plan_ids: set[int]) -> str:
    """Hash configuration topology only; exclude volatile IO values and secrets."""
    commands = ((config.get('FubModules') or {}).get('10') or {}).get(str(device_id), {}) if device_id else {}
    mapped_plans = {}
    for plan_id in sorted(relevant_plan_ids):
        plan = plan_payloads.get(plan_id) or {}
        refs, edges = _plan_elements(plan)
        mapped_plans[str(plan_id)] = {
            'references': sorted((str(k[0]), str(k[1]), int(v)) for k, v in refs.items()),
            'edges': sorted([sorted(edge) for edge in edges]),
            'metadata': (config.get('Fubs') or {}).get(str(plan_id)),
        }
    value = {
        'device_id': device_id,
        'device': (config.get('WebDevices') or {}).get(str(device_id)) if device_id else None,
        'commands': commands,
        'plans': mapped_plans,
    }
    return hashlib.sha256(json.dumps(value, sort_keys=True, default=str).encode()).hexdigest()


async def inspect_push_repair(
    admin: ComexioAdmin, channels: dict[str, Channel], entry_id: str,
    webhook_path: str, push_base: str, selected: list[str], *,
    mode: str = 'repair', observed: dict | None = None,
) -> RepairPreview:
    """Read COMEXIO only, never issue POST or alter any plan."""
    if mode not in ('repair', 'rebuild'):
        raise RepairError('Unbekannter Reparaturmodus')
    catalog = {c.key: c for c in push_sources(channels)}
    keys = list(dict.fromkeys(selected))
    if not keys or len(keys) > 90 or any(key not in catalog for key in keys):
        raise RepairError('Ungültige oder leere Quellenauswahl')
    config = await admin.read_config()
    device_id, class_name = _find_push_device(config)
    command_map = ((config.get('FubModules') or {}).get('10') or {}).get(str(device_id), {}) if device_id else {}
    if device_id and not isinstance(command_map, dict):
        raise RepairError('COMEXIO Web-IO-Befehlsstruktur ist unbekannt')
    if device_id:
        unique_webio_commands(config, device_id)  # No duplicate/invalid command identifiers.
    groups = _source_groups(channels)
    plan_payloads: dict[int, dict] = {}
    relevant_plan_ids: set[int] = set()
    inspections = []
    for key in keys:
        signal = catalog[key]
        group_name, group = groups[key]
        display_plan = friendly_plan_name(group, group_name)
        plan_match = _find_plan(config, display_plan)
        matches = [(display_plan, plan_match)] if plan_match is not None else []
        command_matches = [
            (str(cid), cmd) for cid, cmd in command_map.items()
            if isinstance(cmd, dict) and str(cmd.get('Name', '')) == friendly_command_name(signal)
        ]
        command_label = (str(command_matches[0][1]['Name']) if len(command_matches) == 1
                         else friendly_command_name(signal))
        last = (observed or {}).get(key, {})
        last_at = last.get('last_received_at_utc') if isinstance(last, dict) else None
        detail = ''
        action = 'none'
        if len(matches) > 1:
            action, detail = 'blocked', 'Mehrere passende Logikpläne: manuelle Klärung nötig'
        elif len(command_matches) > 1:
            action, detail = 'blocked', 'Mehrere passende Web-IO-Befehle: manuelle Klärung nötig'
        elif matches and not is_owned_plan(matches[0][1][1], entry_id, 'push'):
            action, detail = 'blocked', 'Plan ist nicht eindeutig dieser Integration zugeordnet'
        elif device_id:
            device = (config.get('WebDevices') or {}).get(str(device_id), {})
            address = str(device.get('Ip') or '').strip()
            parsed = urlsplit(push_base)
            target = f'{parsed.hostname}:{parsed.port}'
            if address and address != target:
                action, detail = 'blocked', 'Web-IO-Zieladresse weicht von Home Assistant ab'
        if matches and action != 'blocked':
            plan_id = matches[0][1][0]
            relevant_plan_ids.add(plan_id)
            if plan_id not in plan_payloads:
                plan_payloads[plan_id] = await admin.read_plan(plan_id)
        if action != 'blocked' and len(command_matches) == 1:
            stored = command_matches[0][1]
            expected = make_push_command(signal, webhook_path, name=command_label)
            differing = [field for field in ('Parameter', 'Data', 'HeaderModifier', 'TypeId')
                         if stored.get(field) is not None
                         and str(stored[field]).replace('\r\n', '\n').strip()
                         != str(expected[field]).replace('\r\n', '\n').strip()]
            if differing:
                action, detail = 'blocked', 'Web-IO-Einstellungen weichen ab: ' + ', '.join(differing)
        if action != 'blocked' and matches:
            refs_in_plan, _ = _plan_elements(plan_payloads[matches[0][1][0]])
            known_ids = {int(i) for i in command_map.keys() if str(i).isdecimal()}
            orphan = {ref for kind, ref in refs_in_plan if kind == 10} - known_ids
            if orphan:
                action, detail = 'blocked', 'Push-Plan enthält verwaiste Web-IO-Bausteine; manuell klären'
        if action != 'blocked':
            if len(command_matches) == 0:
                action, detail = 'create_command', 'Web-IO-Befehl fehlt; anschließend Verknüpfung prüfen/ergänzen'
            elif not matches:
                action, detail = 'restore_link', 'Eigener Push-Plan fehlt; neu anlegen und verbinden'
            else:
                command_id = int(command_matches[0][0])
                refs, edges = _plan_elements(plan_payloads[matches[0][1][0]])
                source_type = 2 if signal.kind == 'cover' else 1
                source_ref = signal.marker_id if signal.kind == 'cover' else signal.io_id
                src = refs.get((source_type, int(source_ref))) if source_ref is not None else None
                dst = refs.get((10, command_id))
                linked = src is not None and dst is not None and any(src in e and dst in e for e in edges)
                if linked:
                    if mode == 'rebuild':
                        action, detail = 'manual_rebuild', (
                            'Verbindung ist vorhanden. Automatisches Löschen eines COMEXIO-Befehls '
                            'wird aus Sicherheitsgründen nicht ausgeführt. '
                            'Geführter Neuaufbau: nur diesen Web-IO-Baustein im eigenen '
                            'Push-Plan und dann seinen Web-IO-Befehl manuell entfernen; '
                            'anschließend Reparatur erneut öffnen.')
                    else:
                        unavailable = [field for field in ('Parameter', 'Data', 'HeaderModifier', 'TypeId')
                                       if command_matches[0][1].get(field) is None]
                        action = 'none'
                        detail = ('Befehl und Verbindung vorhanden; kein automatischer Eingriff. '
                                  + ('Nicht auslesbare Felder: ' + ', '.join(unavailable)
                                     + '; Push-Funktion nicht bestätigt.' if unavailable
                                     else 'Lesbare Felder geprüft; physischer Push-Test noch erforderlich.'))
                else:
                    action, detail = 'restore_link', 'Quellverknüpfung fehlt; ergänzen und Plan aktivieren'
        address = (f'M{signal.marker_id}' if signal.kind == 'cover'
                   else f'{signal.extension}/{signal.identifier}')
        inspections.append(SourceInspection(key, signal.name, signal.kind, address,
                                            command_label, display_plan, action, detail, last_at))
    return RepairPreview(mode, _fingerprint(config, plan_payloads, device_id, relevant_plan_ids),
                         tuple(inspections))


async def apply_push_repair(
    admin: ComexioAdmin, channels: dict[str, Channel], entry_id: str,
    webhook_path: str, push_base: str, selected: list[str], *,
    mode: str, expected_fingerprint: str, backup_confirmed: bool,
    observed: dict | None = None,
) -> dict:
    """Only additive writes. Re-check preview fingerprint before the FIRST write."""
    if not backup_confirmed:
        raise RepairError('Aktuelle COMEXIO-Konfigurationssicherung muss bestätigt werden')
    preview = await inspect_push_repair(admin, channels, entry_id, webhook_path, push_base,
                                        selected, mode=mode, observed=observed)
    if preview.fingerprint != expected_fingerprint:
        raise RepairError('COMEXIO-Konfiguration hat sich seit der Vorschau verändert; bitte neu prüfen')
    if preview.has_blocks:
        raise RepairError('Mindestens eine Quelle benötigt eine manuelle Klärung bzw. einen geführten Neuaufbau')
    if not preview.needs_write:
        return {'status': 'nothing_to_do', 'created_commands': 0, 'added_pairs': 0, 'activated_plans': 0}

    config = await admin.read_config()
    device_id, class_name = _find_push_device(config)
    selected_channels = [channels[key] for key in dict.fromkeys(selected)]
    host_port = private_lan_host_port(push_base)
    if host_port is None:
        raise RepairError('Ungültiges oder nicht lokales Home-Assistant-Push-Ziel')
    status = {'created_commands': 0, 'added_pairs': 0, 'activated_plans': 0,
              'requested_sources': [c.key for c in selected_channels]}
    if device_id is None:
        first = selected_channels[0]
        await admin.create_push_class(class_name, [make_push_command(
            first, webhook_path, name=friendly_command_name(first))], host_port)
        status['created_commands'] += 1
        await asyncio.sleep(0.8)
        config = await admin.read_config()
        device_id, _ = _find_push_device(config)
        if device_id is None:
            raise RepairError('COMEXIO-Web-IO-Klasse nach Anlage nicht sichtbar; keine erneute Schreibaktion')
    existing = _existing_commands(config, device_id)
    def command_id(signal):
        return existing.get(friendly_command_name(signal))
    base_id = str((config.get('WebDevices') or {}).get(str(device_id), {}).get('BaseId') or '')
    for signal in selected_channels:
        if command_id(signal) is None:
            if not base_id:
                base_id = await _get_base_id(admin, class_name)
            await _append_command(admin, device_id, base_id, make_push_command(
                signal, webhook_path, name=friendly_command_name(signal)))
            await asyncio.sleep(0.8)
            config = await admin.read_config()
            existing = _existing_commands(config, device_id)
            if command_id(signal) is None:
                raise RepairError('Neu erstellter Web-IO-Befehl nicht lesbar: ' + signal.key)
            status['created_commands'] += 1
    config = await admin.ensure_webio_commands_active(
        config, device_id, [friendly_command_name(c) for c in selected_channels])
    existing = _existing_commands(config, device_id)
    groups = _source_groups(channels)
    touched_plan_ids: set[int] = set()
    for signal in selected_channels:
        bucket, group = groups[signal.key]
        plan_name = friendly_plan_name(group, bucket)
        matched_plan = _find_plan(config, plan_name)
        if matched_plan:
            plan_id, meta = matched_plan
            if not is_owned_plan(meta, entry_id, 'push'):
                raise RepairError('Fremder Push-Plan; nicht geändert: ' + signal.key)
        else:
            plan_id = await admin.create_plan(plan_name,
                plan_comment(entry_id, 'push'))
            config = await admin.read_config()
        plan = await admin.read_plan(plan_id)
        # Never append to a plan containing dangling, unknown Web-IO references.
        refs, _ = _plan_elements(plan)
        all_commands = _existing_commands(config, device_id)
        orphan_ids = {ref for typ, ref in refs if typ == 10} - set(all_commands.values())
        if orphan_ids:
            raise RepairError('Push-Plan enthält verwaiste Web-IO-Bausteine; bitte manuell klären')
        index = next(i for i, c in enumerate(group) if c.key == signal.key)
        if await _wire_pair(admin, plan_id, signal, int(command_id(signal)), index, plan):
            await asyncio.sleep(0.8)
            check = await admin.read_plan(plan_id)
            r, e = _plan_elements(check)
            source_type = 2 if signal.kind == 'cover' else 1
            source_ref = signal.marker_id if signal.kind == 'cover' else signal.io_id
            s_id = r.get((source_type, int(source_ref)))
            d_id = r.get((10, int(command_id(signal))))
            if s_id is None or d_id is None or not any(s_id in link and d_id in link for link in e):
                raise RepairError('Web-IO-Verknüpfung nach Schreiben nicht lesbar: ' + signal.key)
            touched_plan_ids.add(plan_id)
            status['added_pairs'] += 1
    for plan_id in sorted(touched_plan_ids):
        await admin.run_plan(plan_id)
        status['activated_plans'] += 1
    after = await inspect_push_repair(admin, channels, entry_id, webhook_path, push_base,
                                      selected, mode='repair', observed=observed)
    remaining = [i.key for i in after.inspections if i.action != 'none']
    if remaining:
        raise RepairError('Nach Reparatur noch unvollständige Quellen: ' + ', '.join(remaining))
    status['status'] = 'linked_unverified'  # Firmware does not expose all Web-IO fields
    status['verification'] = 'Bitte jede ausgewählte Quelle über lokalen Taster testen'
    return status
