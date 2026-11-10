"""Shared, strict COMEXIO Local Push verification.

All provisioning entry points use these firmware readback rules.  An HTTP 200
or a successful mock write is not proof that a plan is active or connected.
"""
from __future__ import annotations

from .admin_api import AdminError
from .managed_graph import plan_elements
from .managed_resources import is_owned_plan, unique_webio_commands
from .push_labels import friendly_command_name


def assert_group_complete(config: dict, plan: dict, plan_id: int, group,
                          entry_id: str, device_id: str, *, require_active: bool) -> None:
    """Accept exactly one physical-source -> command pair for EVERY group member.

    Reject extraneous blocks, duplicate references, unexpected edges, foreign
    plans, and unsuccessful activation.  Called on real COMEXIO GET results.
    """
    metadata = (config.get('Fubs') or {}).get(str(plan_id))
    if not is_owned_plan(metadata, entry_id, 'push'):
        raise AdminError('Logikplan ohne eindeutigen Besitzer; keine Fortsetzung')
    if not isinstance(plan, dict) or not isinstance(plan.get('elements'), dict) or not isinstance(plan.get('connections'), dict):
        raise AdminError('Logikplan nicht vollständig lesbar; keine Fortsetzung')
    refs, edges = plan_elements(plan)
    if len(refs) != len(plan['elements']):
        raise AdminError('Doppelte oder ungültige Logikbausteine; keine Fortsetzung')
    commands = unique_webio_commands(config, device_id)
    expected_refs: set[tuple[int, int]] = set()
    expected_edges: set[frozenset[int]] = set()
    for source in group:
        physical_id = source.marker_id if source.kind == 'cover' else source.io_id
        if physical_id is None:
            raise AdminError('Quelladresse nicht lesbar: ' + source.key)
        command = commands.get(friendly_command_name(source))
        if command is None:
            raise AdminError('Web-IO-Befehl nicht lesbar: ' + source.key)
        src = (2 if source.kind == 'cover' else 1, int(physical_id))
        dst = (10, int(command[0]))
        expected_refs.update((src, dst))
        if src not in refs or dst not in refs:
            raise AdminError('Push-Baustein fehlt nach Schreiben: ' + source.key)
        expected_edges.add(frozenset((refs[src], refs[dst])))
    actual_edges = [frozenset(edge) for edge in edges]
    if set(refs) != expected_refs or len(actual_edges) != len(expected_edges) or set(actual_edges) != expected_edges:
        raise AdminError('Logikplan enthält fehlende, doppelte oder fremde Verbindungen')
    if require_active and str(metadata.get('Active')).lower() not in ('1', 'true'):
        raise AdminError('COMEXIO meldet Logikplan weiterhin inaktiv; keine Erfolgsmeldung')


def push_audit_acceptable(result) -> bool:
    """The final diagnostic is authoritative, with concealed fields unverified.

    COMEXIO 11.1.5 may conceal Parameter/Data/HeaderModifier.  Those are not
    proof of success, but are not a reason to duplicate a correct physical
    graph. Missing activation or network target metadata IS a blocking gap.
    """
    if (result.sources == 0 or result.linked != result.sources or
            result.missing_commands or result.missing_links or
            result.wrong_settings or result.errors):
        return False
    return not any('Active nicht auslesbar' in item or
                   'Web-IO-Zieladresse nicht auslesbar' in item
                   for item in result.unknown_settings)
