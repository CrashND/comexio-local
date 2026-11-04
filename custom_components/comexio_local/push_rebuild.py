"""Resumable COMEXIO Local push provisioning with conservative ownership checks.

Only COMEXIO Local Web-IO resources can be rebuilt. This version deliberately
requires manual cleanup of an existing Web-IO class / push plans: the currently
implemented admin client has no proven destructive API. A working manual UI
Delete operation is NOT evidence of a known/verified HTTP delete endpoint.

Each additive configuration step is checkpointed to HA storage. A crash after a
write but before its checkpoint causes a topology mismatch, never a blind retry.
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
from .push_labels import command_candidates, friendly_command_name, plan_candidates
from .push_setup import (
    _append_command, _existing_commands, _find_device, _find_plan,
    _get_base_id, _plan_elements, _stable_groups, _wire_pair, push_sources,
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
            + [{'kind': 'activate', 'key': bucket, 'label': bucket} for bucket, _ in groups]
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

    async def initialize(self):
        loaded = await self._store.async_load()
        if isinstance(loaded, dict) and loaded.get('entry_id') == self.runtime.entry.entry_id:
            self._state = loaded
            if self._state.get('status') == 'running':
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
        prefix = f'CL{self.runtime.entry.entry_id[:8].upper()}'
        class_name = f'{prefix} Push'
        dev_id = _find_device(config, class_name)
        if dev_id:
            device = (config.get('WebDevices') or {}).get(str(dev_id), {})
            commands = ((config.get('FubModules') or {}).get('10') or {}).get(str(dev_id), {})
            if not isinstance(commands, dict):
                raise RebuildError('Unbekannte Web-IO-Befehlsstruktur; kein Schreibzugriff')
        else:
            device, commands = {}, {}
        expected = {n for c in push_sources(self.runtime.channels)
                    for n in command_candidates(prefix, c)}
        unexpected = [cmd.get('Name') for cmd in commands.values()
                      if not isinstance(cmd, dict) or cmd.get('Name') not in expected]
        if unexpected:
            raise RebuildError('Fremde/unbekannte Befehle in eigener Web-IO-Klasse: ' + str(unexpected[:5]))
        plan_data = {}
        own_plans = {}
        allowed = {n for group_name, group in _groups(self.runtime.channels)
                   for n in plan_candidates(prefix, group_name, group)}
        for fid, meta in (config.get('Fubs') or {}).items():
            if not isinstance(meta, dict):
                continue
            name = meta.get('Name')
            owned = self.runtime.entry.entry_id in str(meta.get('Comment', ''))
            if name in allowed or owned:
                if not owned:
                    raise RebuildError('Push-Plan nicht eindeutig im Besitz dieser Integration: ' + str(name))
                own_plans[str(fid)] = {'name': name, 'active': meta.get('Active')}
                plan = await admin.read_plan(int(fid))
                refs, edges = _plan_elements(plan)
                plan_data[str(fid)] = {'refs': sorted([list(k) + [v] for k,v in refs.items()]),
                                       'edges': sorted([sorted(e) for e in edges])}
        managed = {'device_id': dev_id, 'device_name': device.get('Name'),
                   'commands': sorted((str(cid), str(cmd.get('Name')), str(cmd.get('TypeId')))
                                      for cid, cmd in commands.items()),
                   'plans': own_plans, 'plan_data': plan_data}
        digest = hashlib.sha256(json.dumps(managed, sort_keys=True, default=str).encode()).hexdigest()
        return config, managed, digest

    async def preview(self):
        async with self.runtime.maintenance_lock:
            _, topology, digest = await self._snapshot()
            signals = push_sources(self.runtime.channels)
            return {
                'fingerprint': digest, 'sources': len(signals),
                'commands': len(topology['commands']),
                'plans': len(topology['plans']),
                'device_present': bool(topology['device_id']),
                'steps': len(_make_steps(self.runtime.channels)),
                'write_gap_seconds': WRITE_GAP,
                'requires_cleanup': bool(topology['device_id'] or topology['plans']),
                'note': ('Vorhandene eigene Push-Pläne und die eigene Web-IO-Klasse müssen '
                         'vorerst einmalig in COMEXIO entfernt werden. Die Integration enthält '
                         'noch keinen bestätigten API-Löschaufruf. Raum-/Zentralpläne nie löschen.'),
            }

    async def start(self, fingerprint: str, confirmed: bool):
        if not confirmed:
            raise RebuildError('Aktuelle COMEXIO-Sicherung und Neuaufbau bestätigen')
        async with self._lock:
            if self._state and self._state.get('status') not in TERMINAL:
                raise RebuildError('Ein Neuaufbau ist bereits vorhanden; erst fortsetzen oder abbrechen')
            async with self.runtime.maintenance_lock:
                _, topology, digest = await self._snapshot()
                if digest != fingerprint:
                    raise RebuildError('Topologie seit Vorschau verändert; Vorschau neu öffnen')
                signals = push_sources(self.runtime.channels)
                if not signals or len(signals) > MAX_SOURCES:
                    raise RebuildError('Keine zulässigen Push-Quellen gefunden')
                awaiting = bool(topology['device_id'] or topology['plans'])
                self._state = {
                    'version': 1, 'entry_id': self.runtime.entry.entry_id,
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
        async with self._lock:
            if not self._state:
                raise RebuildError('Kein gespeicherter Neuaufbau vorhanden')
            if self._state['status'] not in ('paused', 'interrupted', 'failed', 'awaiting_cleanup'):
                raise RebuildError('Neuaufbau kann in diesem Zustand nicht fortgesetzt werden')
            if self._state['catalog_hash'] != _catalog_hash(push_sources(self.runtime.channels)):
                raise RebuildError('COMEXIO-Quellen geändert; Neuaufbau nicht blind fortsetzen')
            async with self.runtime.maintenance_lock:
                _, topology, digest = await self._snapshot()
                if self._state['status'] == 'awaiting_cleanup':
                    if topology['device_id'] or topology['plans']:
                        raise RebuildError('Eigene Push-Ressourcen sind noch vorhanden; keine Schreiboperation')
                    # One-time, explicit operator reconciliation after manual cleanup.
                    self._state['topology_digest'] = digest
                elif self._state['topology_digest'] != digest:
                    raise RebuildError('Topologie weicht vom gespeicherten Checkpoint ab. '
                                       'Keine automatische Fortsetzung; manuell prüfen.')
                await self._launch_locked()
            return self.status()

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
        previous_gap = self.runtime.admin.write_gap
        self.runtime.admin.write_gap = max(previous_gap, WRITE_GAP)
        try:
            async with self.runtime.maintenance_lock:
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
                    config, _, current_digest = await self._snapshot()
                    if current_digest != state['topology_digest']:
                        raise RebuildError('COMEXIO-Topologie weicht vom Checkpoint ab; '
                                           'manuelle Prüfung statt blindem Wiederholen')
                    if state['cursor'] >= len(state['steps']):
                        self._freeze_elapsed()
                        state['status'] = 'completed'
                        state['message'] = 'Neuaufbau abgeschlossen; Live-Push durch Wandtaster prüfen.'
                        await self._save()
                        return
                    step = state['steps'][state['cursor']]
                    state['message'] = f"{step['kind']}: {step['label']}"
                    await self._save()
                    await self._execute_step(step, config)
                    _, _, new_digest = await self._snapshot()
                    state['topology_digest'] = new_digest
                    state['cursor'] += 1
                    await self._save()
        except asyncio.CancelledError:
            # If cancelled DURING a COMEXIO write, checkpoint cannot establish whether
            # it succeeded; do NOT advance the cursor. Next resume checks topology.
            if self._state:
                self._freeze_elapsed()
                self._state['status'] = 'interrupted'
                self._state['message'] = 'Unterbrochen; COMEXIO wird vor dem Fortsetzen abgeglichen.'
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

    async def _execute_step(self, step: dict, config: dict):
        admin = self.runtime.admin
        entry = self.runtime.entry
        prefix = f'CL{entry.entry_id[:8].upper()}'
        class_name = f'{prefix} Push'
        signal_map = _source_map(self.runtime.channels)
        from .constants import CONF_WEBHOOK_ID, CONF_PUSH_BASE
        webhook_path = f"/api/webhook/{entry.data[CONF_WEBHOOK_ID]}"
        parsed = urlsplit(entry.data[CONF_PUSH_BASE])
        if parsed.scheme != 'http' or not parsed.hostname or not parsed.port:
            raise RebuildError('Ungültiges Push-Ziel')
        host_port = f'{parsed.hostname}:{parsed.port}'
        device_id = _find_device(config, class_name)
        kind = step['kind']
        if kind == 'command':
            signal = signal_map[step['key']]
            if not device_id:
                # First signal seeds the COMEXIO Web-IO class: two paced writes.
                await admin.create_push_class(class_name, [make_push_command(
                    prefix, signal, webhook_path, name=friendly_command_name(signal))], host_port)
                await asyncio.sleep(SETTLE_GAP)
            else:
                existing = _existing_commands(config, device_id)
                matches = [existing[n] for n in command_candidates(prefix, signal) if n in existing]
                if len(matches) > 1:
                    raise RebuildError('Mehrere Web-IO-Befehle für ' + signal.key)
                if not matches:
                    base_id = str((config.get('WebDevices') or {}).get(str(device_id), {}).get('BaseId') or '')
                    if not base_id:
                        base_id = await _get_base_id(admin, class_name)
                    await _append_command(admin, device_id, base_id, make_push_command(
                        prefix, signal, webhook_path, name=friendly_command_name(signal)))
                    await asyncio.sleep(SETTLE_GAP)
            refreshed = await admin.read_config()
            new_id = _find_device(refreshed, class_name)
            names = _existing_commands(refreshed, new_id) if new_id else {}
            if len([n for n in command_candidates(prefix, signal) if n in names]) != 1:
                raise RebuildError('Web-IO-Befehl nach Erstellung nicht eindeutig sichtbar: ' + signal.key)
            return
        if kind == 'link':
            signal = signal_map[step['key']]
            groups = {c.key: (bucket, group) for bucket, group in _groups(self.runtime.channels)
                      for c in group}
            bucket, group = groups[signal.key]
            candidates = plan_candidates(prefix, bucket, group)
            matches = [(n, found) for n in candidates if (found := _find_plan(config, n))]
            if len(matches) > 1:
                raise RebuildError('Mehrere Push-Pläne: ' + signal.key)
            if matches:
                plan_id, meta = matches[0][1]
                if entry.entry_id not in str(meta.get('Comment', '')):
                    raise RebuildError('Fremder Push-Plan: ' + signal.key)
            else:
                plan_id = await admin.create_plan(candidates[-1],
                    f'Managed exclusively by COMEXIO Local ({entry.entry_id}); do not rename')
            newconfig = await admin.read_config()
            dev_id = _find_device(newconfig, class_name)
            cmds = _existing_commands(newconfig, dev_id) if dev_id else {}
            refs = [cmds[n] for n in command_candidates(prefix, signal) if n in cmds]
            if len(refs) != 1:
                raise RebuildError('Web-IO-Referenz fehlt/ist mehrfach: ' + signal.key)
            plan = await admin.read_plan(plan_id)
            index = next(i for i, c in enumerate(group) if c.key == signal.key)
            if await _wire_pair(admin, plan_id, signal, refs[0], index, plan):
                await asyncio.sleep(SETTLE_GAP)
            check = await admin.read_plan(plan_id)
            refs_map, edges = _plan_elements(check)
            s_type = 2 if signal.kind == 'cover' else 1
            s_ref = signal.marker_id if signal.kind == 'cover' else signal.io_id
            src = refs_map.get((s_type, int(s_ref))) if s_ref is not None else None
            dst = refs_map.get((10, refs[0]))
            if src is None or dst is None or not any(src in e and dst in e for e in edges):
                raise RebuildError('COMEXIO-Verbindung nicht nachweisbar: ' + signal.key)
            return
        if kind == 'activate':
            bucket = step['key']
            groups = dict(_groups(self.runtime.channels))
            group = groups[bucket]
            matches = [found for n in plan_candidates(prefix, bucket, group)
                       if (found := _find_plan(config, n))]
            if len(matches) != 1 or entry.entry_id not in str(matches[0][1].get('Comment', '')):
                raise RebuildError('Aktivierung verweigert: Planbesitz nicht eindeutig')
            await admin.run_plan(matches[0][0])
            return
        if kind == 'verify':
            result = await audit_push(admin, self.runtime.channels, entry.entry_id,
                                      webhook_path, entry.data[CONF_PUSH_BASE])
            if (result.missing_links or result.missing_commands or result.wrong_settings or result.errors
                    or result.linked != len(push_sources(self.runtime.channels))):
                raise RebuildError('Abschlussprüfung nicht erfolgreich: ' + str(result.as_dict())[:170])
            return
        raise RebuildError('Unbekannter Neuaufbauschritt')
