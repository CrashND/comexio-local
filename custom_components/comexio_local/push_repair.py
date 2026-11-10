"""Safe on-demand push repair: read-only preview and additive, confirmed repairs.

Only missing integration-owned resources are created. Replacing an EXISTING command
requires COMEXIO deletion calls which are not verified against firmware 11.1.5;
never guess destructive endpoints. Such cases are shown as guided manual rebuilds.
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from urllib.parse import urlsplit

from .admin_api import AdminError, ComexioAdmin, make_push_command
from .discovery import Channel
from .push_labels import friendly_command_name, friendly_plan_name
from .managed_resources import (is_owned_plan, verify_current_push_inventory)
from .push_target import private_lan_host_port
from .push_setup import (_find_push_device, _find_plan, _plan_elements,
                         _stable_groups, push_sources)


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
    action: str  # none, create_command, restore_link, activate_plan, activate_command, manual_rebuild, blocked
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
        return any(i.action in ('create_command', 'restore_link', 'activate_plan', 'activate_command')
                   for i in self.inspections)

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
        # Inspect the WHOLE device, not just the selected repair sources.
        verify_current_push_inventory(config, device_id, catalog.values())
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
                        plan_active = matches[0][1][1].get('Active')
                        action = ('none' if str(plan_active).lower() in ('1', 'true')
                                  else 'activate_plan')
                        detail = ('Befehl und Verbindung vorhanden; '
                                  + ('eigener Logikplan inaktiv und muss aktiviert werden. '
                                     if action == 'activate_plan' else 'kein automatischer Eingriff. ')
                                  + ('Nicht auslesbare Felder: ' + ', '.join(unavailable)
                                     + '; Push-Funktion nicht bestätigt.' if unavailable
                                     else 'Lesbare Felder geprüft; physischer Push-Test noch erforderlich.'))
                else:
                    action, detail = 'restore_link', 'Quellverknüpfung fehlt; ergänzen und Plan aktivieren'
        if action == 'none' and len(command_matches) == 1:
            active = command_matches[0][1].get('Active')
            if str(active).lower() not in ('1', 'true'):
                action, detail = ('activate_command',
                                  'Befehl ist deaktiviert oder Active nicht auslesbar; '
                                  'Befehl und eigenen Plan kontrolliert aktivieren')
        address = (f'M{signal.marker_id}' if signal.kind == 'cover'
                   else f'{signal.extension}/{signal.identifier}')
        inspections.append(SourceInspection(key, signal.name, signal.kind, address,
                                            command_label, display_plan, action, detail, last_at))
    # A COMEXIO plan cannot be safely activated as "complete" when a
    # separately unselected source in that SAME physical plan is still absent.
    # Require the operator to preview/select the whole affected group first.
    if mode == 'repair' and any(i.action in ('create_command', 'restore_link', 'activate_plan', 'activate_command')
                                for i in inspections):
        selected_keys = set(keys)
        incomplete_unselected = set()
        for bucket, group in _stable_groups(push_sources(channels)):
            group_keys = {signal.key for signal in group}
            if not (group_keys & selected_keys) or group_keys <= selected_keys:
                continue
            plan_name = friendly_plan_name(group, bucket)
            match = _find_plan(config, plan_name)
            plan = plan_payloads.get(match[0]) if match else None
            refs, edges = _plan_elements(plan) if plan else ({}, [])
            for signal in group:
                if signal.key in selected_keys:
                    continue
                command_id = next((int(cid) for cid, c in command_map.items()
                                   if isinstance(c, dict) and c.get('Name') ==
                                   friendly_command_name(signal)), None)
                src_id = signal.marker_id if signal.kind == 'cover' else signal.io_id
                src = refs.get((2 if signal.kind == 'cover' else 1, int(src_id))) if src_id else None
                dst = refs.get((10, command_id)) if command_id is not None else None
                if src is None or dst is None or not any(src in e and dst in e for e in edges):
                    incomplete_unselected.add(bucket)
        if incomplete_unselected:
            inspections = [SourceInspection(
                i.key, i.name, i.kind, i.address, i.command_name, i.plan_name,
                'blocked', 'Weitere Quellen im gleichen Push-Plan fehlen. '
                'Bitte alle betroffenen Quellen in der Vorschau auswählen.',
                i.last_event_utc) if _source_groups(channels)[i.key][0] in incomplete_unselected
                and i.action in ('create_command', 'restore_link', 'activate_plan', 'activate_command') else i
                for i in inspections]
    return RepairPreview(mode, _fingerprint(config, plan_payloads, device_id, relevant_plan_ids),
                         tuple(inspections))


# All COMEXIO writes now run through PushRebuild.start_repair().  Keep the
# read-only inspection above; there is deliberately NO parallel, synchronous
# repair writer here.
