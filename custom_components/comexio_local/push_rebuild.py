"""Resumable COMEXIO Local push provisioning with conservative ownership checks.

Only COMEXIO Local Web-IO resources can be rebuilt. This version deliberately
requires manual cleanup of an existing Web-IO class / push plans: the currently
implemented admin client has no proven destructive API. A working manual UI
Delete operation is NOT evidence of a known/verified HTTP delete endpoint.

Each completed configuration step is checkpointed to HA storage. After a crash,
read-only reconciliation checks completed and partially executed work before
allowing a retry; no automatic write resumes after restart.
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone
import hashlib
import json
import logging
import time
from urllib.parse import urlsplit

from .admin_api import AdminError, make_push_command
from .push_audit import audit_push
from .managed_resources import is_owned_plan, plan_comment, unique_webio_commands
from .webio_command import WebIOCommand
from .managed_graph import ensure_webio_link
from .push_target import private_lan_host_port
from .push_labels import friendly_command_name, friendly_plan_name
from .push_setup import (
    _append_command, _existing_commands, _find_push_device, _find_plan,
    _get_base_id, _plan_elements, _stable_groups, _stable_plan_slot, push_sources,
)

_LOGGER = logging.getLogger(__name__)
WRITE_GAP = 2.0
SETTLE_GAP = 0.8
MAX_SOURCES = 90
TERMINAL = frozenset({'completed', 'cancelled', 'failed', 'interrupted'})


class RebuildError(AdminError):
    """Unsafe or invalid rebuild operation."""


def _utc() -> str:
    return datetime.now(timezone.utc).isoformat(timespec='seconds')


def _catalog_hash(signals) -> str:
    fields = [(s.key, s.kind, s.extension, s.identifier, s.io_id, s.marker_id)
              for s in signals]
    return hashlib.sha256(json.dumps(fields, sort_keys=True, default=str).encode()).hexdigest()


def _source_map(channels):
    return {s.key: s for s in push_sources(channels)}


def _groups(channels):
    return _stable_groups(push_sources(channels))


def _make_steps(channels):
    groups = _groups(channels)
    signals = push_sources(channels)
    return ([{'kind': 'command', 'key': s.key, 'label': s.name} for s in signals]
            + [{'kind': 'link', 'key': s.key, 'label': s.name} for s in signals]
            + [{'kind': 'activate', 'key': bucket, 'label': friendly_plan_name(group, bucket)}
               for bucket, group in groups]
            + [{'kind': 'verify', 'key': 'all', 'label': 'Abschlusskontrolle'}])


class PushRebuild:
    """Persistent state machine, independent of any frontend options flow."""

    def __init__(self, runtime, store=None):
        self.runtime = runtime
        self.hass = runtime.hass
        if store is None:
            from homeassistant.helpers.storage import Store
            store = Store(self.hass, 1, f'comexio_local_push_rebuild_{runtime.entry.entry_id}')
        self._store = store
        self._state: dict | None = None
        self._task: asyncio.Task | None = None
        self._lock = asyncio.Lock()
        # Per-run local workset. Never persisted or reused across HA restarts.
        self._working_config: dict | None = None
        self._working_plans: dict[str, dict] | None = None
        self._command_ids_refreshed = False

    async def initialize(self):
        loaded = await self._store.async_load()
        if isinstance(loaded, dict) and loaded.get('entry_id') == self.runtime.entry.entry_id:
            self._state = loaded
            if self._state.get('version') != 3:
                # A new canonical name set cannot resume an old partially built
                # graph by index. Retire its checkpoint; never resume writes.
                self._state['status'] = 'cancelled'
                self._state['active_since'] = None
                self._state['message'] = (
                    'Früherer Neuaufbau-Checkpoint durch das einheitliche Namensschema '
                    'ungültig. COMEXIO-Local-Ressourcen manuell bereinigen und '
                    'einen neuen Aufbau mit aktueller Vorschau starten.')
                await self._save()
            elif self._state.get('status') == 'running':
                # Restart NEVER resumes destructive/configuration work automatically.
                self._state['status'] = 'interrupted'
                self._state['active_since'] = None
                self._state['message'] = ('Home Assistant wurde während des Neuaufbaus beendet. '
                                          'Vor einer Fortsetzung wird die Topologie erneut geprüft.')
                await self._save()

    def _elapsed(self) -> float:
        state = self._state or {}
        elapsed = float(state.get('elapsed_seconds', 0))
        if state.get('status') == 'running' and state.get('active_since_monotonic'):
            elapsed += max(0.0, time.monotonic() - float(state['active_since_monotonic']))
        return elapsed

    def status(self):
        if not self._state:
            return {'status': 'not_started', 'total': 0, 'done': 0, 'percent': 0,
                    'elapsed_seconds': 0, 'eta_seconds': None, 'write_gap_seconds': WRITE_GAP}
        state = self._state
        done = int(state['cursor'])
        total = len(state['steps'])
        elapsed = self._elapsed()
        eta = (round(elapsed / done * (total - done)) if done and state['status'] == 'running'
               else None)
        return {
            'status': state['status'], 'done': done, 'total': total,
            'percent': round(done * 100 / total, 1) if total else 0,
            'current': state['steps'][done]['label'] if done < total else 'Abgeschlossen',
            'phase': state['steps'][done]['kind'] if done < total else 'fertig',
            'elapsed_seconds': round(elapsed), 'eta_seconds': eta,
            'started_at_utc': state['started_at_utc'],
            'updated_at_utc': state.get('updated_at_utc'),
            'last_completed_at_utc': state.get('last_completed_at_utc'),
            'message': state.get('message', ''),
            'write_gap_seconds': WRITE_GAP,
            'completed_sources': sum(1 for s in state['steps'][:done] if s['kind'] == 'link'),
            'sources': sum(1 for s in state['steps'] if s['kind'] == 'link'),
            'requires_manual_cleanup': state['status'] == 'awaiting_cleanup',
        }

    async def _save(self):
        if not self._state:
            return
        self._state['updated_at_utc'] = _utc()
        # Monotonic clock values MUST NOT be persisted across restarts.
        snapshot = {k: v for k, v in self._state.items() if k != 'active_since_monotonic'}
        await self._store.async_save(snapshot)
        from homeassistant.helpers.dispatcher import async_dispatcher_send
        async_dispatcher_send(self.hass, self.runtime.state_signal)

    def _freeze_elapsed(self):
        if not self._state:
            return
        start = self._state.pop('active_since_monotonic', None)
        if start is not None:
            self._state['elapsed_seconds'] += max(0.0, time.monotonic() - start)
        self._state['active_since'] = None

    async def _snapshot(self):
        """Read all managed topology, without reading or touching room logic."""
        admin = self.runtime.admin
        config = await admin.read_config()
        dev_id, class_name = _find_push_device(config)
        if dev_id:
            device = (config.get('WebDevices') or {}).get(str(dev_id), {})
            commands = ((config.get('FubModules') or {}).get('10') or {}).get(str(dev_id), {})
            if not isinstance(commands, dict):
                raise RebuildError('Unbekannte Web-IO-Befehlsstruktur; kein Schreibzugriff')
        else:
            device, commands = {}, {}
        expected = {friendly_command_name(c) for c in push_sources(self.runtime.channels)}
        unexpected = [(cmd.get('Name') if isinstance(cmd, dict) else '(ungültiger Befehl)')
                      for cmd in commands.values()
                      if not isinstance(cmd, dict) or cmd.get('Name') not in expected]
        if unexpected:
            raise RebuildError('Fremde/unbekannte Befehle in eigener Web-IO-Klasse: ' + str(unexpected[:5]))
        plan_data = {}
        raw_plans = {}
        own_plans = {}
        allowed = {friendly_plan_name(group, group_name)
                   for group_name, group in _groups(self.runtime.channels)}
        for fid, meta in (config.get('Fubs') or {}).items():
            if not isinstance(meta, dict):
                continue
            name = meta.get('Name')
            owned = is_owned_plan(meta, self.runtime.entry.entry_id, 'push')
            # Separate INPUT plans are identified by their explicit owner tag,
            # not by their displayed labels.
            # Never include them in light/cover rebuilds or recovery checkpoints.
            if is_owned_plan(meta, self.runtime.entry.entry_id, 'input'):
                continue
            if name in allowed or owned or self.runtime.entry.entry_id in str(meta.get('Comment', '')):
                if not owned:
                    raise RebuildError('Push-Plan nicht eindeutig im Besitz dieser Integration: ' + str(name))
                own_plans[str(fid)] = {'name': name, 'active': meta.get('Active')}
                plan = await admin.read_plan(int(fid))
                raw_plans[str(fid)] = plan
                refs, edges = _plan_elements(plan)
                plan_data[str(fid)] = {'refs': sorted([list(k) + [v] for k,v in refs.items()]),
                                       'edges': sorted([sorted(e) for e in edges])}
        managed = {'device_id': dev_id, 'device_name': device.get('Name'),
                   'commands': sorted((str(cid), str(cmd.get('Name')), str(cmd.get('TypeId')))
                                      for cid, cmd in commands.items()),
                   'plans': own_plans, 'plan_data': plan_data}
        digest = hashlib.sha256(json.dumps(managed, sort_keys=True, default=str).encode()).hexdigest()
        return config, managed, digest, raw_plans

    async def preview(self):
        async with self.runtime.maintenance_lock:
            _, topology, digest, _ = await self._snapshot()
            signals = push_sources(self.runtime.channels)
            return {
                'fingerprint': digest, 'sources': len(signals),
                'commands': len(topology['commands']),
                'plans': len(topology['plans']),
                'device_present': bool(topology['device_id']),
                'steps': len(_make_steps(self.runtime.channels)),
                'write_gap_seconds': WRITE_GAP,
                'requires_cleanup': bool(topology['device_id'] or topology['plans']),
                'note': (
                    'Vorhandene eigene Push-Pläne und die eigene Web-IO-Klasse müssen '
                    'vorerst einmalig in COMEXIO entfernt werden. Die Integration enthält '
                    'noch keinen bestätigten API-Löschaufruf. Raum-/Zentralpläne nie löschen.'
                    if topology['device_id'] or topology['plans'] else
                    'Keine verwalteten CL-Push-Pläne oder Web-IO-Klasse gefunden. '
                    'Der kontrollierte Neuaufbau kann nach Bestätigung starten. '
                    'Raum- und Zentralpläne bleiben unangetastet.'
                ),
            }

    async def start(self, fingerprint: str, confirmed: bool):
        if not confirmed:
            raise RebuildError('Aktuelle COMEXIO-Sicherung und Neuaufbau bestätigen')
        async with self._lock:
            if self._state and self._state.get('status') not in TERMINAL:
                raise RebuildError('Ein Neuaufbau ist bereits vorhanden; erst fortsetzen oder abbrechen')
            async with self.runtime.maintenance_lock:
                config, topology, digest, plans = await self._snapshot()
                if digest != fingerprint:
                    raise RebuildError('Topologie seit Vorschau verändert; Vorschau neu öffnen')
                signals = push_sources(self.runtime.channels)
                if not signals or len(signals) > MAX_SOURCES:
                    raise RebuildError('Keine zulässigen Push-Quellen gefunden')
                awaiting = bool(topology['device_id'] or topology['plans'])
                self._state = {
                    'version': 3, 'entry_id': self.runtime.entry.entry_id,
                    'status': 'awaiting_cleanup' if awaiting else 'paused',
                    'steps': _make_steps(self.runtime.channels), 'cursor': 0,
                    'catalog_hash': _catalog_hash(signals),
                    'topology_digest': digest,
                    'started_at_utc': _utc(), 'active_since': None,
                    'elapsed_seconds': 0, 'pause_requested': False,
                    'cancel_requested': False,
                    'message': ('Zuerst die eigenen CL-Push-Pläne und die eigene Web-IO-Klasse '
                                'in COMEXIO entfernen; danach „Fortsetzen“ wählen.' if awaiting
                                else 'Bereit zum kontrollierten Neuaufbau.'),
                }
                await self._save()
            if not awaiting:
                self._working_config, self._working_plans = config, plans
                self._command_ids_refreshed = False
                await self._launch_locked()
            return self.status()

    async def _launch_locked(self):
        if self._task and not self._task.done():
            raise RebuildError('Neuaufbau läuft bereits')
        self._state['status'] = 'running'
        self._state['pause_requested'] = False
        self._state['cancel_requested'] = False
        self._state['active_since'] = _utc()
        self._state['active_since_monotonic'] = time.monotonic()
        self._state['message'] = 'Neuaufbau läuft mit mindestens 2 Sekunden Schreibabstand.'
        await self._save()
        # Independent of any options-flow dialog; HA unload cancels the task.
        self._task = self.hass.async_create_task(self._run())

    async def resume(self):
        """Read COMEXIO once; validate completed steps before any new writes.

        A partially written current IO-link step can be reconciled, but only
        after validating all completed steps. Never trust the cursor alone.
        """
        async with self._lock:
            if not self._state:
                raise RebuildError('Kein gespeicherter Neuaufbau vorhanden')
            state = self._state
            if state['status'] not in ('paused', 'interrupted', 'failed', 'awaiting_cleanup'):
                raise RebuildError('Neuaufbau kann in diesem Zustand nicht fortgesetzt werden')
            if state.get('version') != 3:
                raise RebuildError('Checkpoint verwendet ein anderes Namensschema; neuen Neuaufbau starten')
            if state['catalog_hash'] != _catalog_hash(push_sources(self.runtime.channels)):
                raise RebuildError('COMEXIO-Quellen geändert; Neuaufbau nicht blind fortsetzen')
            async with self.runtime.maintenance_lock:
                config, topology, digest, plans = await self._snapshot()
                if state['status'] == 'awaiting_cleanup':
                    if topology['device_id'] or topology['plans']:
                        raise RebuildError('Eigene Push-Ressourcen sind noch vorhanden; keine Schreiboperation')
                # Incomplete current work is reconciled in _validate_checkpoint.
                # Never reject its partial topology solely due to a changed digest.
                self._validate_checkpoint(config, plans)
                state['topology_digest'] = digest  # baseline of this resumed run
                state['version'] = 3
                self._working_config, self._working_plans = config, plans
                self._command_ids_refreshed = state['cursor'] >= sum(
                    step['kind'] == 'command' for step in state['steps'])
                await self._launch_locked()
            return self.status()

    def _validate_checkpoint(self, config: dict, plans: dict[str, dict]) -> None:
        """Validate exactly the completed steps plus at most the current step.

        This is read-only, uses physical refs and plan ownership, rejects any
        unexpected Web-IO command, plan element, link or early activation.
        Only checkpoints created with the current canonical name schema are valid.
        """
        state = self._state
        cursor = int(state['cursor'])
        steps = state['steps']
        if not (0 <= cursor <= len(steps)):
            raise RebuildError('Ungültiger gespeicherter Checkpoint')
        device_id, _ = _find_push_device(config)
        source_map = _source_map(self.runtime.channels)
        existing = _existing_commands(config, device_id) if device_id else {}
        present = {}
        for key, channel in source_map.items():
            cmd_id = existing.get(friendly_command_name(channel))
            if cmd_id is not None:
                present[key] = cmd_id
        allowed_names = {friendly_command_name(channel)
                         for channel in source_map.values()}
        if set(existing) - allowed_names:
            raise RebuildError('Unerwartete Web-IO-Befehle; Wiederaufnahme blockiert')
        for index, step in enumerate(steps):
            if step['kind'] != 'command':
                continue
            count = int(step['key'] in present)
            if index < cursor and count != 1:
                raise RebuildError('Abgeschlossener Web-IO-Befehl fehlt: ' + step['key'])
            if index > cursor and count:
                raise RebuildError('Noch nicht bearbeiteter Web-IO-Befehl vorhanden: ' + step['key'])
        if cursor and steps[0]['kind'] == 'command' and device_id is None:
            raise RebuildError('Verwaltete Web-IO-Klasse fehlt')
        if device_id is not None:
            parsed = urlsplit(self.runtime.entry.data['push_base'])
            expected = f'{parsed.hostname}:{parsed.port}'
            address = str((config.get('WebDevices') or {}).get(str(device_id), {}).get('Ip') or '').strip()
            if address and address != expected:
                raise RebuildError('Topologie verändert: Push-Zieladresse wurde geändert; nicht fortsetzen')
        by_bucket = {bucket: group for bucket, group in _groups(self.runtime.channels)}
        link_indices = {step['key']: i for i, step in enumerate(steps) if step['kind'] == 'link'}
        activation_indices = {step['key']: i for i, step in enumerate(steps)
                              if step['kind'] == 'activate'}
        identified = set()
        for bucket, group in by_bucket.items():
            name = friendly_plan_name(group, bucket)
            match = _find_plan(config, name)
            if match is None:
                if any(link_indices[c.key] < cursor for c in group):
                    raise RebuildError('Abgeschlossener Push-Plan fehlt: ' + name)
                continue
            fid_num, meta = match
            fid = str(fid_num)
            identified.add(fid)
            if not is_owned_plan(meta, self.runtime.entry.entry_id, 'push'):
                raise RebuildError('Push-Plan ohne Eigentumsnachweis: ' + bucket)
            plan = plans.get(fid)
            if not isinstance(plan, dict):
                raise RebuildError('Push-Plan kann nicht geprüft werden: ' + bucket)
            refs, edges = _plan_elements(plan)
            if len(refs) != len(plan.get('elements') or {}):
                raise RebuildError('Doppelte oder ungültige Push-Elemente in ' + bucket)
            allowed_refs = set()
            expected_edges = set()
            for channel in group:
                index = link_indices[channel.key]
                permitted = index <= cursor  # at most the currently executing step
                cmd_id = present.get(channel.key)
                typ = 2 if channel.kind == 'cover' else 1
                address = channel.marker_id if channel.kind == 'cover' else channel.io_id
                if address is None:
                    raise RebuildError('Quellenreferenz fehlt: ' + channel.key)
                src_ref = (typ, int(address))
                dst_ref = (10, int(cmd_id)) if cmd_id is not None else None
                src = refs.get(src_ref)
                dst = refs.get(dst_ref) if dst_ref else None
                if permitted:
                    allowed_refs.add(src_ref)
                    if dst_ref:
                        allowed_refs.add(dst_ref)
                if index < cursor and (src is None or dst is None):
                    raise RebuildError('Abgeschlossene Verbindung fehlt: ' + channel.key)
                if src is not None and dst is not None and permitted:
                    expected_edges.add(frozenset((src, dst)))
                    if index < cursor and frozenset((src, dst)) not in map(frozenset, edges):
                        raise RebuildError('Abgeschlossene Verknüpfung fehlt: ' + channel.key)
            if set(refs) - allowed_refs:
                raise RebuildError('Unerwartete Push-Elemente in ' + bucket)
            normalized_edges = [frozenset(edge) for edge in edges]
            if (any(edge not in expected_edges for edge in normalized_edges)
                    or len(normalized_edges) != len(set(normalized_edges))):
                raise RebuildError('Unerwartete oder doppelte Push-Verbindung in ' + bucket)
            activate_at = activation_indices[bucket]
            if str(meta.get('Active')).lower() in ('true', '1') and activate_at > cursor:
                raise RebuildError('Push-Plan unerwartet bereits aktiv: ' + bucket)
            if activate_at < cursor and str(meta.get('Active')).lower() not in ('true', '1'):
                raise RebuildError('Bereits aktivierter Push-Plan ist deaktiviert: ' + bucket)
        for fid, meta in (config.get('Fubs') or {}).items():
            if (isinstance(meta, dict) and not is_owned_plan(meta, self.runtime.entry.entry_id, 'input')
                    and (is_owned_plan(meta, self.runtime.entry.entry_id, 'push')
                         or self.runtime.entry.entry_id in str(meta.get('Comment', '')))
                    and str(fid) not in identified):
                raise RebuildError('Nicht zugeordneter eigener Push-Plan: ' + str(meta.get('Name')))

    async def pause(self):
        if not self._state or self._state['status'] != 'running':
            raise RebuildError('Kein laufender Neuaufbau')
        self._state['pause_requested'] = True
        self._state['message'] = 'Pause angefordert – aktueller Arbeitsschritt wird abgeschlossen.'
        await self._save()
        return self.status()

    async def cancel(self):
        if not self._state or self._state['status'] in TERMINAL:
            raise RebuildError('Kein aktiver Neuaufbau')
        if self._state['status'] == 'running':
            self._state['cancel_requested'] = True
            self._state['message'] = 'Abbruch angefordert – aktueller Arbeitsschritt wird abgeschlossen.'
        else:
            self._freeze_elapsed()
            self._state['status'] = 'cancelled'
            self._state['message'] = 'Neuaufbau abgebrochen. Bereits erstellte Komponenten bleiben erhalten.'
        await self._save()
        return self.status()

    async def stop_for_unload(self):
        if self._task and not self._task.done():
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass

    async def _run(self):
        """No full config/plan reads between successful individual steps.

        Configuration is read once at start/resume, once at the command->link
        boundary (for newly issued command IDs), once at the final audit.
        Any unexpected error fails closed and leaves its checkpoint intact.
        """
        previous_gap = self.runtime.admin.write_gap
        self.runtime.admin.write_gap = max(previous_gap, WRITE_GAP)
        try:
            async with self.runtime.maintenance_lock:
                if self._working_config is None or self._working_plans is None:
                    raise RebuildError('Kein geprüfter Arbeitsstand – Auftrag nicht starten')
                while self._state and self._state['status'] == 'running':
                    state = self._state
                    if state['cancel_requested'] or state['pause_requested']:
                        self._freeze_elapsed()
                        state['status'] = 'cancelled' if state['cancel_requested'] else 'paused'
                        state['message'] = ('Abgebrochen; bisherige Quellen bleiben erhalten.'
                                            if state['cancel_requested'] else 'Pausiert nach abgeschlossenem Schritt.')
                        await self._save()
                        return
                    if state['catalog_hash'] != _catalog_hash(push_sources(self.runtime.channels)):
                        raise RebuildError('Quellkatalog geändert; Neuaufbau gestoppt')
                    if state['cursor'] >= len(state['steps']):
                        self._freeze_elapsed()
                        state['status'] = 'completed'
                        state['message'] = 'Neuaufbau abgeschlossen; Live-Push durch Wandtaster prüfen.'
                        await self._save()
                        return
                    step = state['steps'][state['cursor']]
                    state['message'] = f"{step['kind']}: {step['label']}"
                    await self._save()
                    await self._execute_step(step, self._working_config, self._working_plans)
                    # Save the cursor after each successful step; only the local
                    # checkpoint is persisted, no additional COMEXIO GET.
                    state['cursor'] += 1
                    state['version'] = 3
                    state['last_completed_at_utc'] = _utc()
                    state['message'] = f"Abgeschlossen: {step['label']}"
                    await self._save()
        except asyncio.CancelledError:
            if self._state:
                self._freeze_elapsed()
                self._state['status'] = 'interrupted'
                self._state['message'] = 'Unterbrochen; vor Fortsetzung COMEXIO-Zustand abgleichen.'
                await asyncio.shield(self._save())
            raise
        except Exception as err:
            _LOGGER.warning('COMEXIO Push-Neuaufbau angehalten: %s', err)
            if self._state:
                self._freeze_elapsed()
                self._state['status'] = 'failed'
                self._state['message'] = str(err)[:200]
                await self._save()
        finally:
            self.runtime.admin.write_gap = previous_gap
            self._working_config, self._working_plans = None, None
            self._command_ids_refreshed = False

    async def _verify_initial_append(self, config: dict, appended_signal) -> None:
        """Read once after the first form-created command and compare it with import.

        The initial import and the later save_command POST use different
        firmware write paths. A successful HTTP reply and a catalog entry do
        not prove equivalent command metadata. Refuse all subsequent writes
        before any plans are created if their visible structures diverge.

        This is a fail-closed diagnostic guard, NOT proof of Studio rendering.
        """
        fresh = await self.runtime.admin.read_config()
        device_id, _ = _find_push_device(fresh)
        if device_id is None:
            raise RebuildError('Web-IO-Klasse nach zweitem Befehl nicht lesbar')
        existing = unique_webio_commands(fresh, device_id)
        first = push_sources(self.runtime.channels)[0]
        from .constants import CONF_WEBHOOK_ID
        path = f"/api/webhook/{self.runtime.entry.data[CONF_WEBHOOK_ID]}"
        imported_label = friendly_command_name(first)
        appended_label = friendly_command_name(appended_signal)
        if imported_label not in existing or appended_label not in existing:
            raise RebuildError('COMEXIO-Web-IO-Befehle nach Anlegen nicht vollständig auslesbar')
        imported = existing[imported_label][1]
        appended = existing[appended_label][1]
        errors: list[str] = []
        for signal, stored in ((first, imported), (appended_signal, appended)):
            label = friendly_command_name(signal)
            expected = WebIOCommand.from_import(make_push_command(signal, path, name=label))
            errors.extend(expected.readback_mismatch(stored))
        if errors:
            raise RebuildError('Web-IO-Befehlswerte nach Speichern abweichend: '
                               + ', '.join(sorted(set(errors))) + '; keine Logikpläne angelegt')
        # Firmware snapshots may hide fields in both commands, but must not
        # expose different metadata schemas for two commands of our own class.
        comparable = ('TypeId', 'Min', 'Max', 'Protocol', 'PostGet',
                      'Authentication', 'Input', 'SendOnOne', 'Changed',
                      'DefaultActive', 'DefaultValue', 'BaseId', 'WebDeviceId',
                      'Parameter', 'Data', 'HeaderModifier', 'Port', 'ReqFreq',
                      'ReplyInterpreter', 'io')
        asymmetric = [field for field in comparable
                      if (field in imported and imported[field] is not None)
                      != (field in appended and appended[field] is not None)]
        if asymmetric:
            raise RebuildError('COMEXIO speichert importierte und ergänzte Web-IO-Befehle '
                               'mit unterschiedlichen Feldern: ' + ', '.join(asymmetric)
                               + '; keine Logikpläne angelegt')
        # Common transport/config fields must also have the same *values*.
        # Per-signal TypeId, Max and Lua Data are already checked separately
        # against their own expected command and intentionally differ.
        constant_fields = ('Protocol', 'PostGet', 'Authentication', 'Input',
                           'SendOnOne', 'Changed', 'DefaultActive', 'DefaultValue',
                           'BaseId', 'WebDeviceId', 'Parameter', 'HeaderModifier',
                           'Port', 'ReqFreq', 'ReplyInterpreter')
        divergent = [field for field in constant_fields
                     if field in imported and field in appended
                     and str(imported[field]).strip() != str(appended[field]).strip()]
        if divergent:
            raise RebuildError('COMEXIO speichert importierte und ergänzte Web-IO-Befehle '
                               'mit unterschiedlichen Einstellungen: '
                               + ', '.join(divergent) + '; keine Logikpläne angelegt')
        # IDs obtained from the firmware now supersede the temporary staged
        # reference. A resumed job can re-verify those IDs without repeating a POST.
        config.clear()
        config.update(fresh)

    async def _refresh_command_ids(self, config: dict) -> None:
        """One read after the complete command phase to resolve actual IDs."""
        fresh = await self.runtime.admin.read_config()
        dev_id, _ = _find_push_device(fresh)
        if not dev_id:
            raise RebuildError('Web-IO-Klasse nach Befehlserstellung nicht lesbar')
        existing = unique_webio_commands(fresh, dev_id)
        from .constants import CONF_WEBHOOK_ID
        path = f"/api/webhook/{self.runtime.entry.data[CONF_WEBHOOK_ID]}"
        for channel in push_sources(self.runtime.channels):
            label = friendly_command_name(channel)
            if label not in existing:
                raise RebuildError('Web-IO-Befehl fehlt: ' + channel.key)
            expected = WebIOCommand.from_import(make_push_command(channel, path, name=label))
            mismatches = expected.readback_mismatch(existing[label][1])
            if mismatches:
                raise RebuildError('COMEXIO hat Web-IO-Befehlswerte abweichend gespeichert '
                                   f'({channel.key}: {", ".join(mismatches)}); '
                                   'vor dem Verknüpfen gestoppt')
        fresh = await self.runtime.admin.ensure_webio_commands_active(
            fresh, dev_id,
            [friendly_command_name(c) for c in push_sources(self.runtime.channels)])
        config.clear()
        config.update(fresh)
        self._command_ids_refreshed = True

    async def _wire_cached(self, plan_id: int, signal, command_id: int,
                           index: int, plan: dict) -> None:
        """Write once, update local topology; retry only via checked recovery."""
        await ensure_webio_link(self.runtime.admin, plan_id, signal, command_id,
                                index, plan, update_cache=True,
                                command_name=friendly_command_name(signal))

    async def _execute_step(self, step: dict, config: dict, plans: dict[str, dict]):
        admin = self.runtime.admin
        entry = self.runtime.entry
        signal_map = _source_map(self.runtime.channels)
        from .constants import CONF_WEBHOOK_ID, CONF_PUSH_BASE
        webhook_path = f"/api/webhook/{entry.data[CONF_WEBHOOK_ID]}"
        host_port = private_lan_host_port(entry.data[CONF_PUSH_BASE])
        if host_port is None:
            raise RebuildError('Ungültiges oder nicht lokales Push-Ziel')
        device_id, class_name = _find_push_device(config)
        kind = step['kind']
        if kind == 'command':
            signal = signal_map[step['key']]
            if not device_id:
                await admin.create_push_class(class_name, [make_push_command(
                    signal, webhook_path, name=friendly_command_name(signal))], host_port)
                # Creation verifies its class internally. Read once here so
                # subsequent commands know the assigned device ID and BaseId.
                config.clear()
                config.update(await admin.read_config())
            else:
                existing = _existing_commands(config, device_id)
                first_append = len(existing) == 1
                if friendly_command_name(signal) not in existing:
                    base_id = str((config.get('WebDevices') or {}).get(str(device_id), {}).get('BaseId') or '')
                    if not base_id:
                        base_id = await _get_base_id(admin, class_name)
                    cmd = make_push_command(signal, webhook_path,
                                            name=friendly_command_name(signal))
                    await _append_command(admin, device_id, base_id, cmd)
                    # COMEXIO's save_command does not return a usable ID.
                    # Stage by name; resolve all physical IDs in one read after
                    # the full command phase (not after every command).
                    staged = (config.setdefault('FubModules', {})
                              .setdefault('10', {}).setdefault(str(device_id), {}))
                    staged[str(-1 - len(staged))] = {**cmd, '_local_staged': True}
                    if first_append:
                        # One read after the second command, not per command.
                        # Stop before further writes on incompatible firmware records.
                        await self._verify_initial_append(config, signal)
            return
        if kind == 'link':
            if not self._command_ids_refreshed:
                await self._refresh_command_ids(config)
                device_id, _ = _find_push_device(config)
            signal = signal_map[step['key']]
            groups = {c.key: (bucket, group) for bucket, group in _groups(self.runtime.channels)
                      for c in group}
            bucket, group = groups[signal.key]
            plan_name = friendly_plan_name(group, bucket)
            matched_plan = _find_plan(config, plan_name)
            if matched_plan:
                plan_id, meta = matched_plan
                if not is_owned_plan(meta, entry.entry_id, 'push'):
                    raise RebuildError('Fremder Push-Plan: ' + signal.key)
            else:
                name = plan_name
                comment = plan_comment(entry.entry_id, 'push')
                plan_id = await admin.create_plan(name, comment)
                config.setdefault('Fubs', {})[str(plan_id)] = {
                    'Name': name, 'Comment': comment, 'Active': False}
                plans[str(plan_id)] = {'elements': {}, 'connections': {}}
            existing = _existing_commands(config, device_id) if device_id else {}
            cmd_id = existing.get(friendly_command_name(signal))
            if cmd_id is None:
                raise RebuildError('Web-IO-Referenz fehlt: ' + signal.key)
            plan = plans.get(str(plan_id))
            if plan is None:
                raise RebuildError('Push-Plan nach Wiederaufnahme nicht lesbar: ' + signal.key)
            index = _stable_plan_slot(signal)
            await self._wire_cached(plan_id, signal, cmd_id, index, plan)
            return
        if kind == 'activate':
            bucket = step['key']
            groups = dict(_groups(self.runtime.channels))
            group = groups[bucket]
            match = _find_plan(config, friendly_plan_name(group, bucket))
            if match is None or not is_owned_plan(match[1], entry.entry_id, 'push'):
                raise RebuildError('Aktivierung verweigert: Planbesitz nicht eindeutig')
            fid, meta = match
            if str(meta.get('Active')).lower() not in ('true', '1'):
                # COMEXIO requires one plan GET for activation; read_plan has
                # bounded HTTP-500 retries. No full configuration scans.
                await admin.run_plan(fid)
                meta['Active'] = True
            return
        if kind == 'verify':
            result = await audit_push(admin, self.runtime.channels, entry.entry_id,
                                      webhook_path, entry.data[CONF_PUSH_BASE])
            if (result.missing_links or result.missing_commands or result.wrong_settings or result.errors
                    or result.linked != len(push_sources(self.runtime.channels))):
                raise RebuildError('Abschlussprüfung nicht erfolgreich: ' + str(result.as_dict())[:170])
            return
        raise RebuildError('Unbekannter Neuaufbauschritt')
