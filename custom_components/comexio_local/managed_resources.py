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


_LEGACY_SHORT_NAME = re.compile(r'^(?P<prefix>.+)-[0-9A-Fa-f]{4}$')


def _push_name_matches_signal(name: str, signal) -> bool:
    """Recognize canonical names or the historical shortened/hash form.

    Earlier CL builds shortened long labels to ``<prefix>-AB12`` while
    retaining the physical marker or output address. A matching ``CL`` prefix
    alone is deliberately insufficient; the source identity must also match.
    Do not use this compatibility rule when *creating* new commands.
    """
    from .push_labels import friendly_command_name

    canonical = friendly_command_name(signal)
    if name == canonical:
        return True
    if signal.kind == 'cover':
        endings = (f' M{signal.marker_id}',)
    else:
        endings = [f' {signal.extension}/{signal.identifier}']
        abbreviated = re.fullmatch(r'IO-(Ext|Server)-(\d+)', signal.extension, re.I)
        if abbreviated:
            kind = 'E' if abbreviated[1].lower() == 'ext' else 'S'
            endings.append(f' {kind}{int(abbreviated[2])}/{signal.identifier}')

    for ending in endings:
        if not name.endswith(ending):
            continue
        shortened = _LEGACY_SHORT_NAME.fullmatch(name[:-len(ending)])
        if shortened is None:
            continue
        prefix = shortened['prefix']
        # The original room/role prefix must still be recognizable; a generic
        # ``CL Licht`` or ``CL Rollladen`` plus a guessed address is not enough.
        canonical_stem = canonical.rsplit(' ', 1)[0]
        if (len(prefix) >= 20 and canonical_stem.startswith(prefix)
                and prefix.startswith('CL ')):
            return True
    return False


def validate_owned_push_commands(config: dict, device_id: str, signals,
                                 owned_plans: dict[str, dict]) -> dict[int, object]:
    """Resolve exclusively managed commands without trusting full display names.

    The device must already be identified as ours, and *every* supplied plan
    must already have its exact entry-ID owner comment verified by the caller.
    Only canonical or physical-address-preserving historical labels qualify;
    each may map to exactly one currently discovered source. Existing graph
    links must agree with that source. Unknown commands fail the whole check.

    Accepting a well-formed historical label even when the graph is already
    gone also makes an interrupted, explicitly confirmed cleanup resumable.
    """
    module = ((config.get('FubModules') or {}).get('10') or {}).get(str(device_id))
    if not isinstance(module, dict):
        raise AdminError('Web-IO-Befehlsstruktur nicht lesbar; keine Bereinigung')
    indexed = unique_webio_commands(config, str(device_id))
    if len(indexed) != len(module):
        raise AdminError('Fremde/unvollständige Web-IO-Befehle; keine Bereinigung')

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
    used_sources = set()
    for name, (cid, record) in indexed.items():
        if cid <= 0:
            raise AdminError('Ungültige Web-IO-Befehls-ID; keine Bereinigung')
        if record.get('WebDeviceId') not in (None, '', 0, '0') and str(record['WebDeviceId']) != str(device_id):
            raise AdminError('Widersprüchliche Web-IO-Geräte-ID; keine Bereinigung')
        matches = [(ref, sig) for ref, sig in source_refs.items()
                   if _push_name_matches_signal(name, sig)]
        if len(matches) != 1:
            raise AdminError('Fremde/unbekannte Befehle in eigener Web-IO-Klasse: ' + name)
        source_ref, signal = matches[0]
        if source_ref in used_sources:
            raise AdminError('Mehrere Web-IO-Befehle für dieselbe Quelle; keine Bereinigung')
        used_sources.add(source_ref)
        if cid in linked and linked[cid] != source_ref:
            raise AdminError('Web-IO-Name widerspricht der tatsächlichen Verknüpfung: ' + name)
        try:
            type_id = int(record['TypeId'])
        except (KeyError, ValueError, TypeError) as exc:
            raise AdminError('Web-IO-Befehlstyp nicht prüfbar; keine Bereinigung') from exc
        if type_id != (2 if signal.analog else 1):
            raise AdminError('Web-IO-Befehl hat abweichenden Typ; keine Bereinigung')
        validated[cid] = signal
    if graph_command_ids - set(validated):
        raise AdminError('Fremde Web-IO-Referenz in eigenem Plan; keine Bereinigung')
    return validated
