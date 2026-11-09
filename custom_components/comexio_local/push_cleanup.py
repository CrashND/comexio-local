"""Explicitly confirmed, fail-closed cleanup before a CL Push rebuild.

COMEXIO 11.1.5 editor traces establish two distinct destructive GET routes.
They are NOT safe solely because a response is HTTP 200/302. Every operation
requires verified ownership and a fresh readback. No original logic is edited.
"""
from __future__ import annotations

from collections import Counter
from typing import Callable

from .admin_api import AdminError
from .managed_resources import is_owned_plan, unique_webio_commands
from .push_labels import PREFERRED_PUSH_CLASS, friendly_command_name, friendly_plan_name
from .push_setup import _find_push_device, _stable_groups, push_sources
from .push_target import private_lan_host_port


def _ref(element: dict) -> tuple[int, int]:
    if not isinstance(element, dict) or not isinstance(element.get('reference'), dict):
        raise AdminError('Unbekanntes Logikelement; Push-Bereinigung verweigert')
    reference = element['reference']
    try:
        return int(reference['type']), int(reference['ref_id'])
    except (ValueError, TypeError, KeyError) as exc:
        raise AdminError('Unbekannte Elementreferenz; keine Push-Bereinigung') from exc


async def _preflight(admin, entry_id: str, channels, push_base: str):
    """Read and validate ALL logic plans before permitting deletion.

    Do not rely on a displayed CL name alone. Every deleted plan must bear
    this HA entry's exact owner comment. Every command in the exclusively
    managed device must have an expected label and valid ID. Foreign plans
    referencing those commands block deletion of ANYTHING in this pass.
    """
    config = await admin.read_config()
    fubs = config.get('Fubs')
    if not isinstance(fubs, dict):
        raise AdminError('COMEXIO-Planliste nicht lesbar; keine Löschung')
    device_id, _ = _find_push_device(config)
    expected_commands = {friendly_command_name(s) for s in push_sources(channels)}
    allowed_plan_names = {
        friendly_plan_name(group, bucket)
        for bucket, group in _stable_groups(push_sources(channels))
    }
    allowed_sources = {
        (2, int(s.marker_id)) if s.kind == 'cover' else (1, int(s.io_id))
        for s in push_sources(channels)
    }
    owned_plans = {}
    for fid, meta in fubs.items():
        if not isinstance(meta, dict):
            raise AdminError('Ungültige COMEXIO-Planmetadaten; keine Löschung')
        owned = is_owned_plan(meta, entry_id, 'push')
        if meta.get('Name') in allowed_plan_names and not owned:
            raise AdminError('Push-Planname ohne Eigentumsnachweis; keine Löschung')
        if owned:
            if meta.get('Name') not in allowed_plan_names:
                raise AdminError('Eigener Push-Plan mit unerwartetem Namen; keine Löschung')
            if not str(fid).isdigit() or int(fid) <= 0:
                raise AdminError('Ungültige eigene Push-Plan-ID; keine Löschung')
            owned_plans[str(fid)] = str(meta['Name'])

    command_ids = set()
    if device_id is not None:
        devices = config.get('WebDevices') or {}
        device = devices.get(str(device_id)) if isinstance(devices, dict) else None
        if not isinstance(device, dict) or device.get('Name') != PREFERRED_PUSH_CLASS:
            raise AdminError('Verwaltete Web-IO-Klasse nicht eindeutig; keine Löschung')
        target = private_lan_host_port(push_base)
        if not target or str(device.get('Ip') or '').strip() != target:
            raise AdminError('Web-IO-Gerät hat abweichendes Ziel; keine Löschung')
        commands = ((config.get('FubModules') or {}).get('10') or {}).get(str(device_id))
        if not isinstance(commands, dict) or not commands:
            raise AdminError('Web-IO-Gerät ohne prüfbare eigene Befehle; keine Löschung')
        index = unique_webio_commands(config, str(device_id))
        if len(index) != len(commands) or set(index) - expected_commands:
            raise AdminError('Fremde/unbekannte Web-IO-Befehle; keine Löschung')
        for name, (cid, record) in index.items():
            if cid <= 0 or record.get('Name') != name:
                raise AdminError('Ungültige Web-IO-Befehls-ID; keine Löschung')
            if record.get('WebDeviceId') not in (None, '', 0, '0') and str(
                    record['WebDeviceId']) != str(device_id):
                raise AdminError('Widersprüchliche Web-IO-Geräte-ID; keine Löschung')
            command_ids.add(cid)
        # Graph reference ID is global (type 10). A collision across devices
        # would make ownership of references ambiguous: refuse destruction.
        modules = (config.get('FubModules') or {}).get('10') or {}
        if not isinstance(modules, dict):
            raise AdminError('Web-IO-Referenzliste nicht lesbar; keine Löschung')
        for other_id, module in modules.items():
            if str(other_id) == str(device_id):
                continue
            if not isinstance(module, dict):
                raise AdminError('Weitere Web-IO-Klasse unlesbar; keine Löschung')
            if any(str(key).isdigit() and int(key) in command_ids for key in module):
                raise AdminError('Mehrdeutige Web-IO-Referenz in anderer Klasse')

    if not device_id and not owned_plans:
        return config, owned_plans, device_id
    # Existing strict COMEXIO reads: no assumed empty/missing plan on failure.
    plans = await admin.read_plans(config, limit=None, strict=True)
    if set(plans) != set(fubs):
        raise AdminError('COMEXIO-Logikpläne unvollständig gelesen; keine Löschung')
    for fid, plan in plans.items():
        elements = plan.get('elements') if isinstance(plan, dict) else None
        if not isinstance(elements, dict):
            raise AdminError('COMEXIO-Plan enthält unbekannte Elemente; keine Löschung')
        refs = [_ref(e) for e in elements.values()]
        if fid in owned_plans:
            allowed = allowed_sources | {(10, cid) for cid in command_ids}
            if any(r not in allowed for r in refs):
                raise AdminError('Eigener Push-Plan enthält fremde Elemente; keine Löschung')
            if any(count > 1 for count in Counter(refs).values()):
                raise AdminError('Eigener Push-Plan enthält doppelte Elemente; keine Löschung')
        elif any(typ == 10 and ref in command_ids for typ, ref in refs):
            raise AdminError('Fremder Logikplan verwendet das Web-IO-Gerät; keine Löschung')
    return config, owned_plans, device_id


async def cleanup_owned_push(admin, entry_id: str, channels, push_base: str,
                             *, should_stop: Callable[[], bool] = lambda: False):
    """Delete own plans first, then device, verifying postconditions each time.

    Called only by the confirmed rebuild, never by periodic discovery.
    A failure/interrupt stops without auto-retrying destructive GET requests.
    A later user-requested resume re-runs the complete safety preflight.
    """
    config, plans, device_id = await _preflight(admin, entry_id, channels, push_base)
    for fid, name in sorted(plans.items(), key=lambda item: int(item[0])):
        if should_stop():
            raise AdminError('Push-Bereinigung angehalten; vor Fortsetzen erneut prüfen')
        await admin.delete_owned_push_plan(int(fid), name=name, entry_id=entry_id)
    if should_stop():
        raise AdminError('Push-Bereinigung angehalten; vor Fortsetzen erneut prüfen')
    # Recheck other plans after deleting the own plans: the 200 HTML from the
    # device endpoint is not a success marker and COMEXIO blocks referenced IO.
    fresh, remaining, fresh_device_id = await _preflight(admin, entry_id, channels, push_base)
    if remaining:
        raise AdminError('Eigene Push-Pläne nach Löschung weiterhin vorhanden')
    if device_id is not None:
        if fresh_device_id != device_id:
            raise AdminError('Web-IO-Geräte-ID während Löschung verändert; gestoppt')
        await admin.delete_owned_push_device(str(device_id), expected_name=PREFERRED_PUSH_CLASS)
    after, final_plans, final_device_id = await _preflight(admin, entry_id, channels, push_base)
    if final_plans or final_device_id is not None:
        raise AdminError('COMEXIO-Push-Bereinigung nicht vollständig; gestoppt')
    return after
