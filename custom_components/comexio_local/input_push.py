"""Additive, opt-in Web-IO push for physical COMEXIO inputs (v0.3.6.3).

Input push is deliberately isolated from the already working light/cover push:
its own Web-IO class, owned plans and a preview fingerprint. No existing
COMEXIO room plans, Q push plans or commands are rewritten or deleted.

I channels are digital. AI channels are eligible only after the user explicitly
chooses a *digital* use. Analog sensors must not be subscribed with TypeId 1.
"""
from __future__ import annotations

import hashlib
import ipaddress
import logging
import json
import re
from dataclasses import replace
from urllib.parse import urlsplit

from .admin_api import AdminError, ComexioAdmin, make_push_command
from .discovery import Channel
from .push_labels import hardware_label
from .push_setup import _append_command, _get_base_id, _plan_elements

_LOGGER = logging.getLogger(__name__)

INPUT_MODES = ('taster', 'schalter')
MAX_INPUT_SELECTION = 90
INPUTS_PER_PLAN = 18


def _target_address(push_base: str) -> str:
    """COMEXIO callbacks must remain on the local IPv4 LAN (no credentials)."""
    try:
        parsed = urlsplit(push_base)
        if (parsed.scheme != 'http' or parsed.hostname is None or parsed.port is None
                or parsed.username or parsed.password or parsed.path not in ('', '/')
                or parsed.query or parsed.fragment):
            raise ValueError('invalid URL shape')
        ip = ipaddress.ip_address(parsed.hostname)
        if not isinstance(ip, ipaddress.IPv4Address) or not ip.is_private:
            raise ValueError('not private IPv4')
    except ValueError as err:
        raise AdminError('Push-Ziel muss eine private LAN-HTTP-IPv4-Adresse mit Port sein') from err
    return f'{parsed.hostname}:{parsed.port}'


def input_catalog(raw: dict[str, Channel]) -> dict[str, Channel]:
    """All discovered physical I/AI connections, not COMEXIO logic outputs."""
    return {key: c for key, c in raw.items()
            if c.kind in ('input', 'analog_input')
            and re.fullmatch(r'(?:I|AI)\d+', c.identifier, re.I)
            and c.io_id is not None and c.extension}


def input_device_name(entry_id: str) -> str:
    return f'CL Input {entry_id[:8].upper()}'


def input_command_name(c: Channel) -> str:
    # Hardware addresses are stable; changing a room name must not duplicate
    # a Web-IO command after an upgrade/rescan.
    return f'CL Eingang {hardware_label(c.extension)}/{c.identifier}'


def _groups(raw: dict[str, Channel], entry_id: str) -> dict[str, tuple[str, tuple[Channel, ...], int]]:
    """Use address-stable 18-port blocks; adding channels cannot move old plans.

    I1..I18 and AI1..AI18 belong to *different* plans. The grouping is
    independent of which subset the user selects for installation.
    """
    catalog = input_catalog(raw)
    modules: dict[tuple[str, str, int], list[Channel]] = {}
    for c in catalog.values():
        found = re.fullmatch(r'(AI|I)(\d+)', c.identifier, re.I)
        family, channel_number = found.group(1).upper(), int(found.group(2))
        if channel_number < 1:
            raise AdminError('Ungültige COMEXIO-Eingangsnummer: ' + c.identifier)
        chunk = (channel_number - 1) // INPUTS_PER_PLAN
        modules.setdefault((c.extension, family, chunk), []).append(c)
    result = {}
    all_names = set()
    for (ext, family, chunk), elements in sorted(modules.items()):
        group = tuple(sorted(elements, key=lambda c: int(re.search(r'(\d+)$', c.identifier).group(1))))
        name = f'CL Eing {entry_id[:4].upper()} {hardware_label(ext)}{family}{chunk+1}'
        if name in all_names:
            raise AdminError('Mehrdeutige COMEXIO-Erweiterungsnamen: Eingangs-Plan könnte kollidieren')
        all_names.add(name)
        for signal in group:
            port_number = int(re.search(r'(\d+)$', signal.identifier).group(1))
            result[signal.key] = name, group, (port_number - 1) % INPUTS_PER_PLAN
    return result


def _select(raw: dict[str, Channel], chosen: dict[str, str]) -> dict[str, Channel]:
    catalog = input_catalog(raw)
    if not isinstance(chosen, dict) or not chosen or len(chosen) > MAX_INPUT_SELECTION:
        raise AdminError('Bitte 1 bis 90 digitale Eingänge auswählen')
    if any(key not in catalog or mode not in INPUT_MODES for key, mode in chosen.items()):
        raise AdminError('Unbekannter Eingang oder ungültige Taster-/Schalterart')
    # For AI only user-confirmed digital operation is allowed. Never apply to
    # all AI by default; the UI labels these explicitly as potentially analog.
    return {key: replace(catalog[key], kind='binary_input', analog=False,
                         input_mode=chosen[key]) for key in sorted(chosen)}


def _device(config: dict, entry_id: str) -> tuple[str | None, dict]:
    matches = [(str(i), d) for i, d in (config.get('WebDevices') or {}).items()
               if isinstance(d, dict) and d.get('Name') == input_device_name(entry_id)]
    if len(matches) > 1:
        raise AdminError('Mehrere Eingangs-Web-IO-Klassen gefunden; keine Änderung')
    return matches[0] if matches else (None, {})


def _commands(config: dict, device_id: str | None) -> dict[str, tuple[int, dict]]:
    if device_id is None:
        return {}
    module = ((config.get('FubModules') or {}).get('10') or {}).get(str(device_id), {})
    if not isinstance(module, dict):
        raise AdminError('Unerwartete COMEXIO-Eingangs-Web-IO-Struktur')
    result = {}
    for cid, value in module.items():
        if not isinstance(value, dict) or not value.get('Name'):
            continue
        name = str(value['Name'])
        if name in result or not str(cid).isdigit():
            raise AdminError('Doppelte oder ungültige COMEXIO-Eingangs-Kommandos')
        result[name] = (int(cid), value)
    return result


def _plan_meta(config: dict, name: str, entry_id: str) -> tuple[int, dict] | None:
    matches = [(int(fid), metadata) for fid, metadata in (config.get('Fubs') or {}).items()
               if isinstance(metadata, dict) and metadata.get('Name') == name]
    if len(matches) > 1:
        raise AdminError('Mehrere COMEXIO-Eingangspläne namens ' + name)
    if matches:
        comment = str(matches[0][1].get('Comment') or '')
        if entry_id not in comment or 'COMEXIO Local INPUT' not in comment:
            raise AdminError('Fremder oder nicht eindeutig eigener Eingangsplan: ' + name)
    return matches[0] if matches else None


def _validate_existing_plan(plan: dict, name: str, group: tuple[Channel, ...],
                            known_commands: dict[str, tuple[int, dict]]) -> None:
    """Refuse foreign/ambiguous objects in the integration-owned input plan."""
    legitimate_sources = {int(c.io_id) for c in group}
    legitimate_commands = {cid for cid, _ in known_commands.values()}
    if not isinstance(plan.get('elements'), dict) or not isinstance(plan.get('connections', {}), dict):
        raise AdminError('Unbekanntes Eingangs-Planformat: ' + name)
    references = set()
    for element in plan['elements'].values():
        if not isinstance(element, dict):
            raise AdminError('Nicht lesbarer Eingangs-Planinhalt: ' + name)
        ref = element.get('reference') or {}
        try:
            typ, rid = int(ref['type']), int(ref['ref_id'])
        except (KeyError, ValueError, TypeError):
            raise AdminError('Unbekannte Eingangs-Planreferenz: ' + name) from None
        if not ((typ == 1 and rid in legitimate_sources)
                or (typ == 10 and rid in legitimate_commands)):
            raise AdminError('Fremder Baustein im Eingangs-Plan: ' + name)
        if (typ, rid) in references:
            raise AdminError('Doppelte Bausteinreferenz im Eingangs-Plan: ' + name)
        references.add((typ, rid))
    _refs, edges = _plan_elements(plan)
    elements = {int(eid) for eid in plan['elements'] if str(eid).isdigit()}
    if any(not edge or not edge <= elements for edge in edges):
        raise AdminError('Unbekannte Verbindung im Eingangs-Plan: ' + name)



def _callback_matches(raw: object, webhook_path: str, target: str) -> bool:
    """Accept only the exact webhook path or the same URL on our LAN target.

    COMEXIO firmware variants may persist the command's Parameter as an
    absolute HTTP URL rather than the relative path originally submitted.
    We do not strip arbitrary prefixes, queries, credentials or fragments.
    """
    if not isinstance(raw, str):
        return False
    value = raw.strip()
    if value == webhook_path:
        return True
    try:
        parsed = urlsplit(value)
        return (parsed.scheme == 'http' and parsed.netloc == target
                and not parsed.username and not parsed.password
                and not parsed.query and not parsed.fragment
                and parsed.path == webhook_path)
    except ValueError:
        return False


def _verified_command(stored: dict, expected: dict, key: str, target: str) -> bool:
    """Validate available Web-IO metadata without modifying existing commands.

    Return False when COMEXIO omits the callback from its config snapshot;
    this is *not* proof of a different callback. The independently owned
    command, exact data template, type, header and target must still match.
    A present but wrong parameter always blocks further writes.
    """
    if not isinstance(stored, dict):
        raise AdminError(f'Web-IO-Kommando {key}: unbekanntes Antwortformat; keine Änderung')
    for field in ('Data', 'HeaderModifier', 'TypeId'):
        actual = stored.get(field)
        if (actual is None or str(actual).replace('\r\n', '\n').strip()
                != str(expected[field]).replace('\r\n', '\n').strip()):
            raise AdminError(f'Web-IO-Kommando {key}: {field} nicht eindeutig passend; keine Änderung')

    # COMEXIO may expose either field spelling or omit the callback from
    # FubModules type 10 completely. Treat a missing field as *unverified*,
    # never as a proven match. Empty or mismatched fields are real failures.
    parameters = [stored[field] for field in ('Parameter', 'parameter') if field in stored]
    if not parameters:
        return False
    if not all(_callback_matches(p, str(expected['Parameter']), target) for p in parameters):
        raise AdminError(
            f'Web-IO-Kommando {key}: Parameter weicht vom Home-Assistant-Webhook ab; '
            'keine Änderung (Webhook-Adresse nicht protokolliert)'
        )
    return True


def _graph_linked(plan: dict, c: Channel, command_id: int) -> bool:
    refs, edges = _plan_elements(plan)
    src = refs.get((1, int(c.io_id)))
    dest = refs.get((10, int(command_id)))
    return src is not None and dest is not None and any(src in e and dest in e for e in edges)


async def inspect_input_push(admin: ComexioAdmin, raw: dict[str, Channel],
                             entry_id: str, webhook_path: str, push_base: str,
                             chosen: dict[str, str]) -> dict:
    """Read-only preview, with a fingerprint to prevent TOCTOU writes."""
    selected = _select(raw, chosen)
    grouping = _groups(raw, entry_id)
    target = _target_address(push_base)
    config = await admin.read_config()
    device_id, device_meta = _device(config, entry_id)
    if device_id is not None and str(device_meta.get('Ip') or '').strip() != target:
        raise AdminError('Eingangs-Web-IO-Klasse hat eine andere oder nicht lesbare Zieladresse')
    known_commands = _commands(config, device_id)
    expected_names = [input_command_name(c) for c in input_catalog(raw).values()]
    if len(set(expected_names)) != len(expected_names):
        raise AdminError('Mehrdeutige Eingangsnamen; keine automatische Web-IO-Anlage')
    if set(known_commands) - set(expected_names):
        raise AdminError('Fremde/umbenannte Web-IO-Befehle in Eingangs-Klasse; keine Änderung')

    plan_payloads: dict[str, dict] = {}
    plan_metas: dict[str, dict] = {}
    for name in {grouping[key][0] for key in selected}:
        match = _plan_meta(config, name, entry_id)
        if match:
            fid, metadata = match
            plan_payloads[name] = await admin.read_plan(fid)
            group = next(group for key, (gname, group, index) in grouping.items()
                         if gname == name)
            _validate_existing_plan(plan_payloads[name], name, group, known_commands)
            plan_metas[name] = {'id': fid, 'meta': metadata}

    rows = []
    for key, c in selected.items():
        name, _group, _index = grouping[key]
        cmd_name = input_command_name(c)
        stored = known_commands.get(cmd_name)
        callback_verified = False
        if stored:
            callback_verified = _verified_command(
                stored[1], make_push_command('', c, webhook_path, name=cmd_name),
                key, target)
        if stored and name in plan_payloads and _graph_linked(plan_payloads[name], c, stored[0]):
            active = plan_metas[name]['meta'].get('Active')
            action = 'vorhanden' if str(active).lower() in ('true', '1') else 'aktivieren'
        elif stored:
            action = 'verknuepfen'
        else:
            action = 'anlegen'
        rows.append({'key':key,'name':c.name, 'address':f'{c.extension}/{c.identifier}',
                     'mode': c.input_mode, 'action':action, 'command':cmd_name, 'plan':name,
                     'callback_verified':callback_verified if stored else None})

    fingerprint = hashlib.sha256(json.dumps({
        'selected': chosen,
        'raw': [(c.key,c.io_id,c.extension,c.identifier) for c in selected.values()],
        'device_id': device_id,
        'device': device_meta,
        'commands': ((config.get('FubModules') or {}).get('10') or {}).get(str(device_id)) if device_id else None,
        'plans': {name: {'metadata':plan_metas[name], 'payload':plan_payloads[name]}
                  for name in sorted(plan_payloads)},
    }, sort_keys=True, default=str).encode()).hexdigest()
    return {'fingerprint':fingerprint, 'sources':rows,
            'needs_write':any(row['action'] != 'vorhanden' for row in rows),
            'note':'Nur neue, eigens verwaltete Eingangs-Web-IO-Komponenten. Bestehende Licht-/Rollladenpläne werden nicht verändert.',
            'plan_count':len({row['plan'] for row in rows}),
            'callback_unverified': sum(row['callback_verified'] is False for row in rows)}


async def _wire_input(admin: ComexioAdmin, fid: int, c: Channel, command_id: int,
                      index: int, plan: dict) -> bool:
    """Idempotent additive wire with an in-memory graph for the current batch."""
    refs, edges = _plan_elements(plan)
    src = refs.get((1, int(c.io_id)))
    dest = refs.get((10, int(command_id)))
    if src is not None and dest is not None and any(src in e and dest in e for e in edges):
        return False
    x0, x1, y = 40, 400, 25 + index * 35
    if src is None:
        src = await admin.add_element(fid, int(c.io_id), 1, x0, y)
        plan.setdefault('elements', {})[str(src)] = {'reference': {'type':1,'ref_id':int(c.io_id)}}
    if dest is None:
        link = {'0': {'id':'new', 'fub_id':fid, 'type':'binary',
                'input': {'element':str(src), 'pos':'0', 'inverted':False},
                'output': {'0':{'element':'new','pos':'0','inverted':False}}}}
        dest = await admin.add_element(fid, int(command_id), 10, x1, y, connection=link)
        plan.setdefault('elements', {})[str(dest)] = {'reference': {'type':10,'ref_id':int(command_id)}}
    else:
        await admin.wire(fid, src, dest, False)
    plan.setdefault('connections', {})[f'new-{src}-{dest}'] = {
        'input':{'element':str(src)}, 'output':{'0':{'element':str(dest)}}}
    return True


async def apply_input_push(admin: ComexioAdmin, raw: dict[str, Channel],
                           entry_id: str, webhook_path: str, push_base: str,
                           chosen: dict[str, str], fingerprint: str,
                           backup_confirmed: bool) -> dict:
    """Only after explicit preview/backup confirmation; safe to rerun after failure."""
    if not backup_confirmed:
        raise AdminError('Eine aktuelle COMEXIO-Konfigurationssicherung ist erforderlich')
    inspected = await inspect_input_push(admin, raw, entry_id, webhook_path, push_base, chosen)
    if inspected['fingerprint'] != fingerprint:
        raise AdminError('COMEXIO-Konfiguration seit der Vorschau geändert; bitte neu prüfen')
    selected = _select(raw, chosen)
    grouping = _groups(raw, entry_id)
    target = _target_address(push_base)
    stats = {'created_commands':0,'added_links':0,'activated_plans':0,'verified':0}
    old_gap = admin.write_gap
    admin.write_gap = max(admin.write_gap, 2.0)
    try:
        config = await admin.read_config()
        device_id, device_meta = _device(config, entry_id)
        if device_id is None:
            first = next(iter(selected.values()))
            await admin.create_push_class(input_device_name(entry_id), [make_push_command(
                '', first, webhook_path, name=input_command_name(first))], target)
            stats['created_commands'] += 1
            config = await admin.read_config()
            device_id, device_meta = _device(config, entry_id)
            if device_id is None:
                raise AdminError('Neue Eingangs-Web-IO-Klasse nicht sichtbar')
        commands = _commands(config, device_id)
        missing = [c for c in selected.values() if input_command_name(c) not in commands]
        if missing:
            base_id = str(device_meta.get('BaseId') or '') or await _get_base_id(admin, input_device_name(entry_id))
            for c in missing:
                await _append_command(admin, device_id, base_id,
                                      make_push_command('', c, webhook_path, name=input_command_name(c)))
                stats['created_commands'] += 1
            # One read for all assigned COMEXIO command IDs, not one per command.
            config = await admin.read_config()
            commands = _commands(config, device_id)
        for c in selected.values():
            command = commands.get(input_command_name(c))
            if command is None:
                raise AdminError('Eingangs-Web-IO-Befehl nach Anlage nicht sichtbar: ' + c.key)
            callback_verified = _verified_command(
                command[1], make_push_command('', c, webhook_path,
                name=input_command_name(c)), c.key, target)
            if not callback_verified:
                _LOGGER.warning(
                    'COMEXIO Eingangs-Push %s: Callback-Parameter nicht in COMEXIO-Konfiguration '
                    'enthalten; Befehl eindeutig der eigenen Klasse zugeordnet, '
                    'Webhook erst durch echten Push-Test bestätigbar.', c.key)

        groups_to_write: dict[str, list[Channel]] = {}
        for key, c in selected.items():
            groups_to_write.setdefault(grouping[key][0], []).append(c)
        for name, group_selected in sorted(groups_to_write.items()):
            match = _plan_meta(config, name, entry_id)
            if match:
                fid, meta = match
                plan = await admin.read_plan(fid)
            else:
                comment = f'Managed exclusively by COMEXIO Local INPUT ({entry_id}); do not rename'
                fid = await admin.create_plan(name, comment)
                meta = {'Active':False}
                plan = {'elements':{}, 'connections':{}}
            changed = False
            for c in group_selected:
                index = grouping[c.key][2]
                added = await _wire_input(admin, fid, c, commands[input_command_name(c)][0],
                                          index, plan)
                changed = added or changed
                if added:
                    stats['added_links'] += 1
            if changed or str(meta.get('Active')).lower() not in ('1','true'):
                await admin.run_plan(fid)
                stats['activated_plans'] += 1

        # Final full inspection only. Abort on missing/reconfigured links.
        verified = await inspect_input_push(admin, raw, entry_id, webhook_path, push_base, chosen)
        remaining = [row['key'] for row in verified['sources'] if row['action'] != 'vorhanden']
        if remaining:
            raise AdminError('Eingangs-Push-Abschlussprüfung fehlgeschlagen: ' + ', '.join(remaining[:8]))
        stats['verified'] = len(verified['sources'])
        stats['callback_unverified'] = sum(
            row['callback_verified'] is False for row in verified['sources'])
        return stats
    finally:
        admin.write_gap = old_gap
