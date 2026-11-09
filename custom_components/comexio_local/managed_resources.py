"""Shared ownership markers for COMEXIO Local's managed logic plans.

Display names are never proof of ownership. An explicit tagged comment
identifies a COMEXIO Local plan and its family, including the exact entry ID.
"""
from __future__ import annotations

import re
from typing import Literal

from .admin_api import AdminError

PlanFamily = Literal['push', 'input']

_OWNER = re.compile(
    r'^Managed exclusively by COMEXIO Local(?P<input> INPUT)? '
    r'\((?P<entry>[^()]+)\)(?:[,;] do not rename)?$'
)


def plan_comment(entry_id: str, family: PlanFamily) -> str:
    """Generate the existing, firmware-compatible ownership comments."""
    if family == 'input':
        return f'Managed exclusively by COMEXIO Local INPUT ({entry_id}); do not rename'
    if family == 'push':
        return f'Managed exclusively by COMEXIO Local ({entry_id}), do not rename'
    raise ValueError('Unknown COMEXIO Local plan family')


def plan_family(meta: dict, entry_id: str) -> PlanFamily | None:
    """Match explicit plan ownership, never a visible name or partial entry ID.

    COMEXIO may preserve or omit the trailing editorial comment suffix;
    that formatting does not change the plan's verified identity.
    """
    if not isinstance(meta, dict):
        return None
    match = _OWNER.fullmatch(str(meta.get('Comment') or '').strip())
    if match is None or match.group('entry') != entry_id:
        return None
    return 'input' if match.group('input') else 'push'


def is_owned_plan(meta: dict, entry_id: str, family: PlanFamily) -> bool:
    return plan_family(meta, entry_id) == family


def find_unique_named_plan(config: dict, name: str) -> tuple[int, dict] | None:
    """Resolve a single COMEXIO logic plan; never choose an arbitrary match."""
    matches = [(fid, meta) for fid, meta in (config.get('Fubs') or {}).items()
               if isinstance(meta, dict) and meta.get('Name') == name]
    if len(matches) > 1:
        raise AdminError('Mehrere COMEXIO-Logikpläne mit gleichem Namen: ' + name)
    if not matches:
        return None
    try:
        return int(matches[0][0]), matches[0][1]
    except (TypeError, ValueError):
        raise AdminError('Ungültige COMEXIO-Logikplan-ID: ' + name) from None


def unique_webio_commands(config: dict, device_id: str | None, *,
                          allow_staged: bool = False) -> dict[str, tuple[int, dict]]:
    """Unique, typed command index shared by input and light/cover maintenance.

    Never silently overwrite duplicate display names: subsequent provisioning
    must not guess which COMEXIO command a graph reference should target.
    """
    if device_id is None:
        return {}
    module = ((config.get('FubModules') or {}).get('10') or {}).get(str(device_id), {})
    if not isinstance(module, dict):
        raise AdminError('Unbekannte COMEXIO-Web-IO-Befehlsstruktur; keine Änderung')
    result: dict[str, tuple[int, dict]] = {}
    for cid, item in module.items():
        if not isinstance(item, dict) or not item.get('Name'):
            continue
        name = str(item['Name'])
        try:
            identifier = int(cid)
        except (TypeError, ValueError):
            raise AdminError('Ungültige COMEXIO-Web-IO-Befehls-ID; keine Änderung') from None
        if identifier < 0 and not (allow_staged and item.get('_local_staged') is True):
            raise AdminError('Ungültige COMEXIO-Web-IO-Befehls-ID; keine Änderung')
        if name in result:
            raise AdminError('Doppelter COMEXIO-Web-IO-Befehlsname: ' + name)
        result[name] = (identifier, item)
    return result


def verify_current_push_inventory(config: dict, device_id: str, signals,
                                  *, require_complete: bool = False) -> dict[str, tuple[int, dict]]:
    """Only canonical, physically matched commands are accepted in our device.

    This is not a name-conversion or ownership-migration feature. An extra,
    unnamed, mis-typed or foreign-device command is a hard failure before any
    new link/activation is written. Report IDs, not untrusted stored labels.
    """
    from .push_labels import friendly_command_name
    raw = ((config.get('FubModules') or {}).get('10') or {}).get(str(device_id))
    if not isinstance(raw, dict):
        raise AdminError('Web-IO-Befehlsliste nicht lesbar; keine Änderung')
    indexed = unique_webio_commands(config, str(device_id))
    if len(indexed) != len(raw):
        raise AdminError('Web-IO-Gerät enthält unvollständige Befehle; keine Änderung')
    expected = {}
    for signal in signals:
        name = friendly_command_name(signal)
        if name in expected:
            raise AdminError('Mehrdeutig erzeugter Web-IO-Befehlsname; keine Änderung')
        expected[name] = signal
    for name, (cid, record) in indexed.items():
        signal = expected.get(name)
        if signal is None:
            raise AdminError(f'Zusätzlicher Befehl im Push-Gerät (ID {cid}); keine Änderung')
        if cid <= 0 or (record.get('Id') is not None and str(record['Id']) != str(cid)):
            raise AdminError(f'Widersprüchliche Push-Befehls-ID {cid}; keine Änderung')
        if (record.get('WebDeviceId') not in (None, '', 0, '0')
                and str(record['WebDeviceId']) != str(device_id)):
            raise AdminError(f'WebDeviceId widersprüchlich (Befehl {cid}); keine Änderung')
        if str(record.get('TypeId')) != str(2 if signal.analog else 1):
            raise AdminError(f'Web-IO-TypeId widersprüchlich (Befehl {cid}); keine Änderung')
    if require_complete and set(indexed) != set(expected):
        raise AdminError('Push-Gerät enthält nicht alle vorgesehenen Befehle; keine Änderung')
    return indexed


def validate_owned_push_commands(config: dict, device_id: str, signals,
                                 owned_plans: dict[str, dict]) -> dict[int, object]:
    """Validate only current, canonical COMEXIO Local command names.

    The exclusive device, exact plan owner comments, unique physical sources,
    command types and all graph references must agree. Unexpected records
    always stop cleanup before any destructive request.
    """
    module = ((config.get('FubModules') or {}).get('10') or {}).get(str(device_id))
    if not isinstance(module, dict):
        raise AdminError('Web-IO-Befehlsstruktur nicht lesbar; keine Bereinigung')
    indexed = unique_webio_commands(config, str(device_id))
    if len(indexed) != len(module):
        raise AdminError('Fremde/unvollständige Web-IO-Befehle; keine Bereinigung')

    from .push_labels import friendly_command_name

    signals = list(signals)
    source_refs = {}
    for signal in signals:
        value = signal.marker_id if signal.kind == 'cover' else signal.io_id
        if value is None or int(value) <= 0:
            raise AdminError('Unbekannte physische Push-Quelle; keine Bereinigung')
        reference = (2 if signal.kind == 'cover' else 1, int(value))
        if reference in source_refs:
            raise AdminError('Doppelt zugeordnete Push-Quelle; keine Bereinigung')
        source_refs[reference] = signal

    # Cross-check observed links in plans which the caller has verified as
    # owned. A command connected to a different physical source is not ours.
    linked = {}
    graph_command_ids = set()
    for plan in owned_plans.values():
        if not isinstance(plan, dict) or not isinstance(plan.get('elements'), dict) or not isinstance(plan.get('connections'), dict):
            raise AdminError('Eigener Push-Plan nicht vollständig lesbar; keine Bereinigung')
        elements = {}
        for eid, item in plan['elements'].items():
            try:
                ref = item['reference']
                key = (int(ref['type']), int(ref['ref_id']))
                element_id = int(eid)
            except (KeyError, TypeError, ValueError) as exc:
                raise AdminError('Unbekanntes Push-Logikelement; keine Bereinigung') from exc
            if element_id in elements:
                raise AdminError('Doppelte Push-Element-ID; keine Bereinigung')
            elements[element_id] = key
            if key[0] == 10:
                graph_command_ids.add(key[1])

        for connection in plan['connections'].values():
            if not isinstance(connection, dict):
                raise AdminError('Unlesbare Push-Verbindung; keine Bereinigung')
            src = connection.get('input') or {}
            outputs = connection.get('output') or []
            if isinstance(outputs, dict):
                outputs = list(outputs.values())
            if not isinstance(outputs, list):
                raise AdminError('Unbekanntes Push-Verbindungsformat; keine Bereinigung')
            for output in outputs:
                if not isinstance(output, dict):
                    raise AdminError('Unbekanntes Push-Verbindungsziel; keine Bereinigung')
                try:
                    dest_eid = int(output.get('FubElementId', output.get('element')))
                except (TypeError, ValueError):
                    raise AdminError('Ungültige Push-Verbindungs-ID; keine Bereinigung') from None
                dest_ref = elements.get(dest_eid)
                if dest_ref is None or dest_ref[0] != 10:
                    continue
                try:
                    source_eid = int(src.get('FubElementId', src.get('element')))
                except (AttributeError, TypeError, ValueError):
                    raise AdminError('Unbekannte Web-IO-Quellverbindung; keine Bereinigung') from None
                source_ref = elements.get(source_eid)
                if source_ref not in source_refs:
                    raise AdminError('Web-IO-Befehl mit fremder Quelle verbunden; keine Bereinigung')
                command_id = dest_ref[1]
                if command_id in linked:
                    raise AdminError('Web-IO-Befehl mehrfach verbunden; keine Bereinigung')
                linked[command_id] = source_ref

    validated = {}
    used_sources = {}
    conflicts = []
    for name, (cid, record) in indexed.items():
        problems = []
        if cid <= 0:
            problems.append('Ungültige Web-IO-Befehls-ID')
        if record.get('WebDeviceId') not in (None, '', 0, '0') and str(record['WebDeviceId']) != str(device_id):
            problems.append('Widersprüchliche Web-IO-Geräte-ID')
        matches = [(ref, sig) for ref, sig in source_refs.items()
                   if name == friendly_command_name(sig)]
        if len(matches) != 1:
            problems.append('Name und physische Quelle nicht eindeutig zuordenbar')
            signal = None
        else:
            source_ref, signal = matches[0]
            if source_ref in used_sources:
                problems.append('Mehrere Web-IO-Befehle für dieselbe Quelle')
            else:
                used_sources[source_ref] = cid
            if cid in linked and linked[cid] != source_ref:
                problems.append('Web-IO-Name widerspricht der tatsächlichen Verknüpfung')
        try:
            type_id = int(record['TypeId'])
        except (KeyError, ValueError, TypeError):
            problems.append('Web-IO-Befehlstyp nicht prüfbar')
        else:
            if signal is not None and type_id != (2 if signal.analog else 1):
                problems.append('Web-IO-Befehl hat abweichenden Typ')
        if problems:
            conflicts.append('Befehl ID ' + str(cid) + ' (' + ', '.join(problems) + ')')
        else:
            validated[cid] = signal
    unknown_graph_ids = graph_command_ids - {cid for cid, _ in indexed.values()}
    if unknown_graph_ids:
        conflicts.append('Fremde Web-IO-Referenz in eigenem Plan: '
                         + ', '.join(str(cid) for cid in sorted(unknown_graph_ids)))
    if conflicts:
        raise AdminError('Fremde/unbekannte Befehle in eigener Web-IO-Klasse: '
                         + str(len(conflicts)) + ' Konflikt(e): ' + '; '.join(conflicts)
                         + '; keine Bereinigung')
    return validated
