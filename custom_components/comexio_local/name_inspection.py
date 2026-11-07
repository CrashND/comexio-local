"""Read-only validation of the single canonical COMEXIO Local name schema.

No name migration and no firmware rename calls. Unexpected owned resources are
reported for manual cleanup before provisioning the new namespace.
"""
from __future__ import annotations

from .managed_resources import is_owned_plan, unique_webio_commands
from .push_labels import friendly_command_name, friendly_plan_name
from .push_setup import _find_push_device, _stable_groups, push_sources
from .input_push import input_catalog, input_command_name, input_device_name, _groups


def inspect_names(config: dict, channels: dict, entry_id: str,
                  raw_channels: dict | None = None) -> dict:
    """Inspect only current labels and explicit ownership, never old aliases."""
    found: list[str] = []
    missing: list[str] = []
    blockers: list[str] = []
    device_id, device_name = _find_push_device(config)
    if device_id is None:
        missing.append('Web-IO-Klasse: ' + device_name)
        commands = {}
    else:
        found.append('Web-IO-Klasse: ' + device_name)
        commands = unique_webio_commands(config, device_id)
    expected_commands = {friendly_command_name(s) for s in push_sources(channels)}
    for name in sorted(expected_commands):
        (found if name in commands else missing).append('Web-IO-Befehl: ' + name)
    for name in sorted(set(commands) - expected_commands):
        blockers.append('Unbekannter Befehl in verwalteter Push-Klasse: ' + name)

    expected_plans = {friendly_plan_name(group, bucket)
                      for bucket, group in _stable_groups(push_sources(channels))}
    found_plans = set()
    for meta in (config.get('Fubs') or {}).values():
        if not isinstance(meta, dict):
            continue
        name = str(meta.get('Name') or '')
        owned = is_owned_plan(meta, entry_id, 'push')
        if name in expected_plans and not owned:
            blockers.append('Fremder Plan mit erwartetem Push-Namen: ' + name)
        elif owned and name not in expected_plans:
            blockers.append('Eigener Push-Plan außerhalb des Namensschemas: ' + name)
        elif owned and name in found_plans:
            blockers.append('Doppelter eigener Push-Plan: ' + name)
        elif owned:
            found_plans.add(name)
            found.append('Logikplan: ' + name)
    for name in sorted(expected_plans - found_plans):
        missing.append('Logikplan: ' + name)

    input_raw = raw_channels if raw_channels is not None else channels
    raw_inputs = input_catalog(input_raw)
    devices = [(str(device_id), device) for device_id, device
               in (config.get('WebDevices') or {}).items()
               if isinstance(device, dict) and device.get('Name') == input_device_name(entry_id)]
    if len(devices) > 1:
        blockers.append('Doppelte Web-IO-Klasse: ' + input_device_name(entry_id))
    if devices:
        found.append('Web-IO-Klasse: ' + input_device_name(entry_id))
        input_commands = unique_webio_commands(config, devices[0][0])
        expected_input_commands = {input_command_name(c) for c in raw_inputs.values()}
        for name in sorted(expected_input_commands):
            if name in input_commands:
                found.append('Eingangs-Befehl: ' + name)
        for name in sorted(set(input_commands) - expected_input_commands):
            blockers.append('Unbekannter Befehl in verwalteter Eingangs-Klasse: ' + name)
    expected_input_plans = {group[0] for group in _groups(input_raw, entry_id).values()}
    found_input_plans: set[str] = set()
    for meta in (config.get('Fubs') or {}).values():
        if not isinstance(meta, dict):
            continue
        name = str(meta.get('Name') or '')
        owned = is_owned_plan(meta, entry_id, 'input')
        if name in expected_input_plans and not owned:
            blockers.append('Fremder Plan mit erwartetem Eingangs-Namen: ' + name)
        elif owned and name not in expected_input_plans:
            blockers.append('Eigener Eingangsplan außerhalb des Namensschemas: ' + name)
        elif owned and name in found_input_plans:
            blockers.append('Doppelter eigener Eingangsplan: ' + name)
        elif owned:
            found_input_plans.add(name)
            found.append('Eingangs-Logikplan: ' + name)


    return {'found': sorted(set(found)), 'missing': sorted(set(missing)),
            'blockers': sorted(set(blockers)), 'write_supported': False,
            'note': 'Lesende Prüfung des einzigen aktuellen Namensschemas; keine Migration.'}
