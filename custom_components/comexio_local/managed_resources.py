"""Shared ownership markers for COMEXIO Local's managed logic plans.

Display names are never proof of ownership. An explicit tagged comment
identifies a COMEXIO Local plan and its family, including the exact entry ID.
"""
from __future__ import annotations

import re
import unicodedata
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


def _historical_label_key(text: str) -> str:
    """Compact a stored label without erasing non-German name characters.

    Legacy COMEXIO Local used e.g. ``GaesteWC`` in place of ``Gäste WC``.
    German transliterations are resolved against *expected* room spellings;
    never strip every letter 'e' after a vowel from arbitrary stored names.
    """
    folded = (unicodedata.normalize('NFC', text).casefold()
              .replace('ä', 'ae').replace('ö', 'oe')
              .replace('ü', 'ue').replace('ß', 'ss'))
    return re.sub(r'[\W_]+', '', folded, flags=re.UNICODE)


def _expected_label_spellings(text: str) -> set[str]:
    """Derive *only* genuine umlaut/Eszett spellings from a known CL label.

    ``Küche`` allows ``Kueche`` and ``Kuche``; ``Gäste WC`` allows
    ``GaesteWC`` and ``GasteWC``. But an unrelated ``Bauer`` must **not**
    match ``Baur`` just because it happens to contain ASCII ``ue``.
    Retain exact matching if a pathological name would create too many
    alternatives, instead of silently widening the ownership check.
    """
    options = {'ä': ('ae', 'a'), 'ö': ('oe', 'o'),
               'ü': ('ue', 'u'), 'ß': ('ss',)}
    values = {''}
    for char in unicodedata.normalize('NFC', text).lower():
        alternatives = options.get(char, (char if char.isalnum() else '',))
        if len(values) * len(alternatives) > 256:
            return {_historical_label_key(text)}
        values = {prefix + suffix for prefix in values for suffix in alternatives}
    return values


def _push_name_matches_signal(name: str, signal) -> bool:
    """Recognize canonical, transliterated or historical shortened/hash names.

    Earlier CL builds used abbreviated hardware (E1/S1) and German ASCII
    room names (GaesteWC/GasteWC), or shortened long labels to ``<prefix>-AB12``.
    A matching ``CL`` prefix alone is insufficient: role, complete physical
    Q/marker address and stable room identity must all agree.  Exact matching
    without a graph link is important because cleanup revalidates commands
    after deleting the exclusively owned graph plans.
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

    canonical_stem = canonical.rsplit(' ', 1)[0]
    role = canonical.split(' ', 2)[1]
    role_prefix = f'CL {role} '
    if not canonical_stem.startswith(role_prefix):
        return False
    canonical_room = canonical_stem[len(role_prefix):]
    for ending in endings:
        if not name.endswith(ending):
            continue
        stem = name[:-len(ending)]
        # Older, non-hashed CL labels: transliteration, whitespace and the
        # E1/S1 hardware shorthand may differ, but the *entire* room identity
        # and the physical address must remain the same.  This comparison can
        # safely be repeated after own graph plans have been deleted.
        if stem.startswith(role_prefix):
            old_room = stem[len(role_prefix):]
            if (old_room.strip() and
                    _historical_label_key(old_room) in _expected_label_spellings(canonical_room)):
                return True
        # The older fixed-size shortening preserved a recognizable prefix,
        # four-character suffix and the full physical address.
        shortened = _LEGACY_SHORT_NAME.fullmatch(stem)
        if shortened is None:
            continue
        prefix = shortened['prefix']
        if (len(prefix) >= 20 and prefix.startswith('CL ') and
                any(expected.startswith(_historical_label_key(prefix))
                    for expected in _expected_label_spellings(canonical_stem))):
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
    used_sources = {}
    conflicts = []
    for name, (cid, record) in indexed.items():
        problems = []
        if cid <= 0:
            problems.append('Ungültige Web-IO-Befehls-ID')
        if record.get('WebDeviceId') not in (None, '', 0, '0') and str(record['WebDeviceId']) != str(device_id):
            problems.append('Widersprüchliche Web-IO-Geräte-ID')
        matches = [(ref, sig) for ref, sig in source_refs.items()
                   if _push_name_matches_signal(name, sig)]
        if len(matches) != 1:
            problems.append('Name und physische Quelle nicht eindeutig zuordenbar')
            signal = None
        else:
            source_ref, signal = matches[0]
            if source_ref in used_sources:
                problems.append('Mehrere Web-IO-Befehle für dieselbe Quelle'
                                ' (auch: ' + used_sources[source_ref] + ')')
            else:
                used_sources[source_ref] = name
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
            conflicts.append(name + ' (' + ', '.join(problems) + ')')
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
