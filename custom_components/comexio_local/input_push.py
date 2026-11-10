"""Additive, opt-in Web-IO push for COMEXIO I/AI and EnOcean EI inputs.

The existing input namespace, read-only preview, ownership checks and explicit
backup confirmation are shared. No room plan or light/cover push is changed.
An EI signal's actual COMEXIO transport type (22 or 23) always wins; unlike
physical AI, analog EnOcean measurement channels are never coerced to digital.
"""
from __future__ import annotations

import hashlib
import logging
import json
import re
from dataclasses import replace
from urllib.parse import urlsplit

from .admin_api import AdminError, ComexioAdmin, make_push_command
from .discovery import Channel
from .push_labels import readable_hardware_name
from .managed_resources import (is_owned_plan, plan_comment, find_unique_named_plan,
                                unique_webio_commands)
from .managed_graph import PLAN_ROWS, ensure_webio_link
from .push_target import private_lan_host_port
from .push_setup import _append_command, _device_base_id, _plan_elements

_LOGGER = logging.getLogger(__name__)

INPUT_MODES = ('taster', 'schalter')
MAX_INPUT_SELECTION = 90
INPUTS_PER_PLAN = PLAN_ROWS
PREFERRED_INPUT_CLASS = 'CL Eingänge Home Assistant'


def _target_address(push_base: str) -> str:
    target = private_lan_host_port(push_base)
    if target is None:
        raise AdminError('Push-Ziel muss eine private LAN-HTTP-IPv4-Adresse mit Port sein')
    return target


def input_catalog(raw: dict[str, Channel]) -> dict[str, Channel]:
    """Physical I/AI and metadata-validated EI signals; never Q or markers."""
    return {key: c for key, c in raw.items()
            if c.io_id is not None and c.extension
            and ((c.kind in ('input', 'analog_input') and not c.is_enocean
                  and re.fullmatch(r'(?:I|AI)\d+', c.identifier, re.I))
                 or (c.is_enocean and c.kind in ('binary_input', 'enocean_sensor')))}


def input_device_name(entry_id: str) -> str:
    """Human-readable class name; the entry ID stays internal to the plan owner tag."""
    return PREFERRED_INPUT_CLASS


def input_command_name(c: Channel) -> str:
    # The full physical address is stable across room renames and readable.
    return f'CL Eingang {readable_hardware_name(c.extension)}/{c.identifier}'


def _command_for(commands: dict[str, tuple[int, dict]], c: Channel) -> tuple[int, dict] | None:
    """Only a command with the canonical name belongs to this input."""
    return commands.get(input_command_name(c))


def _groups(raw: dict[str, Channel], entry_id: str) -> dict[str, tuple[str, tuple[Channel, ...], int]]:
    """Deterministic, channel-addressed plans with separate I/AI and EI groups.

    Ordinary I1..I18 / AI1..AI18 retain their exact v0.4.3 plan names and
    positions. EnOcean EI<N>_<signal> belongs to its own logical participant
    plan so new channels never shift a different participant's resources.
    """
    catalog = input_catalog(raw)
    modules: dict[tuple[str, str, int], list[Channel]] = {}
    for c in catalog.values():
        if c.is_enocean:
            modules.setdefault((c.extension, 'EI', c.enocean_slot), []).append(c)
            continue
        found = re.fullmatch(r'(AI|I)(\d+)', c.identifier, re.I)
        family, number = found.group(1).upper(), int(found.group(2))
        if number < 1:
            raise AdminError('Ungültige COMEXIO-Eingangsnummer: ' + c.identifier)
        modules.setdefault((c.extension, family, (number - 1) // INPUTS_PER_PLAN), []).append(c)

    result: dict[str, tuple[str, tuple[Channel, ...], int]] = {}
    names = set()
    for (ext, family, group_number), elements in sorted(modules.items()):
        if family == 'EI':
            group = tuple(sorted(elements, key=lambda c: c.enocean_signal))
            if len(group) > INPUTS_PER_PLAN:
                raise AdminError(f'Zu viele EnOcean-Signale für EI{group_number}-Plan')
            name = f'CL Eingänge {readable_hardware_name(ext)} EI{group_number}'
            indices = {c.key: index for index, c in enumerate(group)}
        else:
            group = tuple(sorted(elements,
                                 key=lambda c: int(re.search(r'(\d+)$', c.identifier).group(1))))
            start = group_number * INPUTS_PER_PLAN + 1
            end = (group_number + 1) * INPUTS_PER_PLAN
            name = f'CL Eingänge {readable_hardware_name(ext)} {family}{start}-{family}{end}'
            indices = {c.key: (int(re.search(r'(\d+)$', c.identifier).group(1)) - 1)
                       % INPUTS_PER_PLAN for c in group}
        if name in names:
            raise AdminError('Mehrdeutige COMEXIO-Erweiterungsnamen: Eingangs-Plan könnte kollidieren')
        names.add(name)
        for c in group:
            result[c.key] = (name, group, indices[c.key])
    return result


def _select(raw: dict[str, Channel], chosen: dict[str, str]) -> dict[str, Channel]:
    catalog = input_catalog(raw)
    if not isinstance(chosen, dict) or not chosen or len(chosen) > MAX_INPUT_SELECTION:
        raise AdminError('Bitte 1 bis 90 COMEXIO-Eingänge auswählen')
    if any(key not in catalog or mode not in (('auto',) if catalog[key].is_enocean else INPUT_MODES)
           for key, mode in chosen.items()):
        raise AdminError('Unbekannter Eingang oder ungültige Taster-/Schalterart')
    # Physical AI requires explicit digital consent. EI uses COMEXIO type
    # metadata and never inherits the UI's global taster/schalter choice.
    return {key: (catalog[key] if catalog[key].is_enocean else
                  replace(catalog[key], kind='binary_input', analog=False,
                          input_mode=chosen[key])) for key in sorted(chosen)}


def _device(config: dict, entry_id: str) -> tuple[str | None, dict]:
    """Resolve the canonical input class by exact device identity."""
    matches = [(str(i), d) for i, d in (config.get('WebDevices') or {}).items()
               if isinstance(d, dict) and d.get('Name') == input_device_name(entry_id)]
    if len(matches) > 1:
        raise AdminError('Mehrere Eingangs-Web-IO-Klassen gefunden; keine Änderung')
    return matches[0] if matches else (None, {})


def _reject_unexpected_input_plans(config: dict, raw: dict[str, Channel], entry_id: str) -> None:
    """Fail closed on an owned input plan outside the current canonical namespace.

    This is a strict ownership check using the current device and plan IDs.
    It also catches leftovers when the Web-IO class has been manually removed.
    """
    expected = {group[0] for group in _groups(raw, entry_id).values()}
    for meta in (config.get('Fubs') or {}).values():
        if not isinstance(meta, dict) or not is_owned_plan(meta, entry_id, 'input'):
            continue
        if meta.get('Name') not in expected:
            raise AdminError('Eingangsplan außerhalb des aktuellen Namensschemas vorhanden: '
                             + str(meta.get('Name')) + '. Vor Neuaufbau gezielt bereinigen')


def _commands(config: dict, device_id: str | None) -> dict[str, tuple[int, dict]]:
    """Shared command parser; duplicate IDs and display names fail closed."""
    return unique_webio_commands(config, device_id)


def _plan_meta(config: dict, name: str, entry_id: str) -> tuple[int, dict] | None:
    found = find_unique_named_plan(config, name)
    if found and not is_owned_plan(found[1], entry_id, 'input'):
        raise AdminError('Fremder oder nicht eindeutig eigener Eingangsplan: ' + name)
    return found


def _validate_existing_plan(plan: dict, name: str, group: tuple[Channel, ...],
                            known_commands: dict[str, tuple[int, dict]]) -> None:
    """Refuse foreign/ambiguous objects in the integration-owned input plan."""
    legitimate_sources = {int(c.io_id) for c in group}
    legitimate_commands = {match[0] for c in group
                           if (match := _command_for(known_commands, c)) is not None}
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


def _same_lua_script(stored: object, expected: str) -> bool:
    """Compare the *full* Lua body, tolerating only transport encodings.

    Do not normalize arbitrary whitespace inside Lua strings or expressions:
    two different scripts must never be mistaken for equivalent commands.
    """
    if not isinstance(stored, str):
        return False
    value = stored.replace('\r\n', '\n').replace('\r', '\n').strip()
    # Some readbacks include one additional JSON string-encoding layer.
    if value.startswith('"') and value.endswith('"'):
        try:
            decoded = json.loads(value)
        except json.JSONDecodeError:
            return False
        if not isinstance(decoded, str):
            return False
        value = decoded.replace('\r\n', '\n').replace('\r', '\n').strip()
    return value == expected.replace('\r\n', '\n').replace('\r', '\n').strip()


def _verified_command(stored: dict, expected: dict, key: str, target: str) -> bool:
    """Safely classify command readback: verified, unverified, or mismatched.

    Missing/blank Data or missing Parameter in the FubModules snapshot does not
    prove a different script or callback. It is *not verified*, and provisioning
    is permitted only because the caller first established the exact dedicated
    input class, its LAN destination and the immutable command name. Explicit
    different nonempty scripts or callbacks always block further writes.
    """
    if not isinstance(stored, dict):
        raise AdminError(f'Web-IO-Kommando {key}: unbekanntes Antwortformat; keine Änderung')
    for field in ('HeaderModifier', 'TypeId'):
        actual = stored.get(field)
        if (actual is None or str(actual).replace('\r\n', '\n').strip()
                != str(expected[field]).replace('\r\n', '\n').strip()):
            raise AdminError(f'Web-IO-Kommando {key}: {field} nicht eindeutig passend; keine Änderung')
    # Preserve the persisted range of the *existing* command, including 10-bit
    # EI values. Missing bounds are unverified, explicit contradictions block.
    range_verified = True
    for field in ('Min', 'Max'):
        actual = stored.get(field)
        if actual is None or actual == '':
            range_verified = False
            continue
        try:
            same = not isinstance(actual, bool) and float(actual) == float(expected[field])
        except (ValueError, TypeError):
            same = False
        if not same:
            raise AdminError(f'Web-IO-Kommando {key}: {field} weicht ab; keine Änderung')

    # Readbacks may spell the field Data or data. Every provided, nonempty
    # variant must match; an omitted/empty field is only "unverified".
    data_values = [stored[field] for field in ('Data', 'data') if field in stored]
    data_verified = False
    for data in data_values:
        if data is None or data == '':
            continue
        if not isinstance(data, str):
            raise AdminError(f'Web-IO-Kommando {key}: unbekanntes Data-Format; keine Änderung')
        if not data.strip():
            continue
        if not _same_lua_script(data, str(expected['Data'])):
            raise AdminError(f'Web-IO-Kommando {key}: Data weicht vom erwarteten Lua-Skript ab; '
                             'keine Änderung')
        data_verified = True

    # The callback can be absent from the FubModules readback; if present,
    # even an empty or foreign address is an explicit mismatch, never accepted.
    parameters = [stored[field] for field in ('Parameter', 'parameter') if field in stored]
    if parameters and not all(_callback_matches(p, str(expected['Parameter']), target)
                              for p in parameters):
        raise AdminError(
            f'Web-IO-Kommando {key}: Parameter weicht vom Home-Assistant-Webhook ab; '
            'keine Änderung (Webhook-Adresse nicht protokolliert)'
        )
    return data_verified and bool(parameters) and range_verified


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
    try:
        config = await admin.read_config()
    except AdminError as err:
        raise AdminError(f'Eingangs-Vorschau: COMEXIO-Konfiguration lesen: {err}') from err
    device_id, device_meta = _device(config, entry_id)
    _reject_unexpected_input_plans(config, raw, entry_id)
    if device_id is not None and str(device_meta.get('Ip') or '').strip() != target:
        raise AdminError('Eingangs-Web-IO-Klasse hat eine andere oder nicht lesbare Zieladresse')
    known_commands = _commands(config, device_id)
    expected_names = [input_command_name(c) for c in input_catalog(raw).values()]
    if len(set(expected_names)) != len(expected_names):
        raise AdminError('Mehrdeutige Eingangsnamen; keine automatische Web-IO-Anlage')
    if set(known_commands) - set(expected_names):
        raise AdminError('Fremde/umbenannte Web-IO-Befehle in Eingangs-Klasse; keine Änderung')
    # Validate the selected canonical input command against the full catalogue.
    for c in input_catalog(raw).values():
        _command_for(known_commands, c)

    plan_payloads: dict[str, dict] = {}
    plan_metas: dict[str, dict] = {}
    for name in {grouping[key][0] for key in selected}:
        match = _plan_meta(config, name, entry_id)
        if match:
            fid, metadata = match
            try:
                plan_payloads[name] = await admin.read_plan(fid)
            except AdminError as err:
                raise AdminError(
                    f'Eingangs-Vorschau: Logikplan {name} (ID {fid}) lesen: {err}'
                ) from err
            group = next(group for key, (gname, group, index) in grouping.items()
                         if gname == name)
            _validate_existing_plan(plan_payloads[name], name, group, known_commands)
            plan_metas[name] = {'id': fid, 'meta': metadata}

    rows = []
    for key, c in selected.items():
        name, _group, _index = grouping[key]
        cmd_name = input_command_name(c)
        stored = _command_for(known_commands, c)
        callback_verified = False
        if stored:
            callback_verified = _verified_command(
                stored[1], make_push_command(c, webhook_path, name=cmd_name),
                key, target)
        if stored and name in plan_payloads and _graph_linked(plan_payloads[name], c, stored[0]):
            plan_active = plan_metas[name]['meta'].get('Active')
            command_active = stored[1].get('Active')
            action = ('vorhanden' if str(plan_active).lower() in ('true', '1')
                      and str(command_active).strip().lower() in ('true', '1')
                      else 'aktivieren')
        elif stored:
            action = 'verknuepfen'
        else:
            action = 'anlegen'
        display_mode = ('Analogwert' if c.is_enocean and c.kind == 'enocean_sensor'
                        else 'Präsenz/Bewegung' if c.is_enocean and c.enocean_signal == 'PIRS'
                        else 'Türkontakt' if c.is_enocean and c.enocean_signal == 'CO'
                        else c.input_mode)
        rows.append({'key':key,'name':c.name, 'address':f'{c.extension}/{c.identifier}',
                     'mode': display_mode, 'action':action, 'command':cmd_name, 'plan':name,
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
    return await ensure_webio_link(admin, fid, c, command_id, index,
                                   plan, update_cache=True,
                                   command_name=input_command_name(c))


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
    created_names: set[str] = set()
    old_gap = admin.write_gap
    admin.write_gap = max(admin.write_gap, 2.0)
    try:
        config = await admin.read_config()
        device_id, device_meta = _device(config, entry_id)
        if device_id is None:
            first = next(iter(selected.values()))
            await admin.create_push_class(input_device_name(entry_id), [make_push_command(
                first, webhook_path, name=input_command_name(first))], target)
            stats['created_commands'] += 1
            created_names.add(input_command_name(first))
            config = await admin.read_config()
            device_id, device_meta = _device(config, entry_id)
            if device_id is None:
                raise AdminError('Neue Eingangs-Web-IO-Klasse nicht sichtbar')
        commands = _commands(config, device_id)
        missing = [c for c in selected.values() if _command_for(commands, c) is None]
        if missing:
            base_id = _device_base_id(config, device_id)
            for c in missing:
                await _append_command(admin, device_id, base_id,
                                      make_push_command(c, webhook_path, name=input_command_name(c)))
                stats['created_commands'] += 1
                created_names.add(input_command_name(c))
            # One read for all assigned COMEXIO command IDs, not one per command.
            config = await admin.read_config()
            commands = _commands(config, device_id)
        for c in selected.values():
            command = _command_for(commands, c)
            if command is None:
                raise AdminError('Eingangs-Web-IO-Befehl nach Anlage nicht sichtbar: ' + c.key)
            callback_verified = _verified_command(
                command[1], make_push_command(c, webhook_path,
                name=input_command_name(c)), c.key, target)
            if not callback_verified:
                _LOGGER.warning(
                    'COMEXIO Eingangs-Push %s: Data und/oder Parameter in COMEXIO-Konfiguration '
                    'nicht vollständig zurücklesbar; Befehl eindeutig eigener Eingangs-Klasse '
                    'zugeordnet. Übertragung erst durch echten Push-Test bestätigbar.', c.key)

        config = await admin.ensure_webio_commands_active(
            config, device_id, [input_command_name(c) for c in selected.values()],
            force_names=created_names)
        commands = _commands(config, device_id)
        groups_to_write: dict[str, list[Channel]] = {}
        for key, c in selected.items():
            groups_to_write.setdefault(grouping[key][0], []).append(c)
        for name, group_selected in sorted(groups_to_write.items()):
            match = _plan_meta(config, name, entry_id)
            if match:
                fid, meta = match
                plan = await admin.read_plan(fid)
            else:
                comment = plan_comment(entry_id, 'input')
                fid = await admin.create_plan(name, comment)
                meta = {'Active':False}
                plan = {'elements':{}, 'connections':{}}
            changed = False
            for c in group_selected:
                index = grouping[c.key][2]
                cmd = _command_for(commands, c)
                if cmd is None:
                    raise AdminError('Verknüpfungsbefehl fehlt: ' + c.key)
                added = await _wire_input(admin, fid, c, cmd[0],
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
