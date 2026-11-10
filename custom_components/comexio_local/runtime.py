"""No scheduler: COMEXIO pushes actual changes into Home Assistant."""
from __future__ import annotations
import asyncio
from datetime import datetime, timezone
import math
import logging
from homeassistant.helpers.dispatcher import async_dispatcher_send
from .admin_api import ComexioAdmin
from .discovery import Channel, discover, event_address
from .tcp_client import ComexioTCPClient, ComexioError
from .push_journal import PushJournal
from .constants import DOMAIN

_LOGGER=logging.getLogger(__name__)

class Runtime:
    def __init__(self, hass, entry, admin:ComexioAdmin, tcp:ComexioTCPClient):
        self.hass=hass; self.entry=entry; self.admin=admin; self.tcp=tcp
        self.channels:dict[str,Channel]={}
        self.hardware_devices = {}
        self.hardware_by_source = {}
        self.raw_channels:dict[str,Channel]={}
        self.values:dict[str,bool|float|None]={}
        self.last_event:datetime|None=None
        self.events=0
        self.firmware_version: str | None = None
        self.push_journal=PushJournal()
        self.rejected_events=0
        self.last_rejection: str | None = None
        self.push_diagnostics: dict | None = None
        self.errors=0
        self._lock=asyncio.Lock()
        self.maintenance_lock=asyncio.Lock()  # serialize configuration changes
        self.discovery_signal=f"comexio_local_discovery_{entry.entry_id}"
        self.state_signal=f"comexio_local_state_{entry.entry_id}"
        self._initialised=False
        self.push_rebuild = None  # initialized after discovery in async_setup_entry
        self._input_push_task: asyncio.Task | None = None
        self._input_push_status: dict = {'status': 'not_started', 'total': 0}

    async def refresh_discovery(self) -> tuple[int,int]:
        """One-off live discovery, with an optional single initial snapshot."""
        async with self._lock:
            config=await self.admin.read_config()
            from .device_metadata import firmware_from_config
            self.firmware_version = firmware_from_config(config)
            plans=await self.admin.read_plans(config)
            from .preferences import apply_classifications, pin_existing_kinds, KNOWN_KINDS
            raw = discover(config, plans)
            pinned = pin_existing_kinds(raw, dict(self.entry.options))
            if pinned != self.entry.options.get(KNOWN_KINDS, {}):
                updated = dict(self.entry.options)
                updated[KNOWN_KINDS] = pinned
                self.hass.config_entries.async_update_entry(self.entry, options=updated)
            self.raw_channels = raw
            new_channels = apply_classifications(raw, dict(self.entry.options))
            from .hardware_devices import discover_hardware, sync_hardware_registry
            new_devices, new_by_source = discover_hardware(config)
            added=set(new_channels)-set(self.channels)
            removed=set(self.channels)-set(new_channels)
            self.channels=new_channels
            # Read-only COMEXIO discovery; HA registry changes are limited to
            # adding real device records and assigning existing own entities.
            try:
                sync_hardware_registry(self.hass, self.entry, new_channels,
                                       new_devices, new_by_source)
            except Exception:
                # A new HA device-registry feature must never prevent the
                # existing COMEXIO channels and control path from starting.
                # Log the failure and retain the original IO-Server mapping.
                _LOGGER.exception('COMEXIO hardware device registry sync failed; '
                                  'keeping existing controller assignment')
                new_by_source = {}
            self.hardware_devices = new_devices
            self.hardware_by_source = new_by_source
            for key in removed:
                self.values.pop(key,None)
            for key in added:
                self.values.setdefault(key,None)
            # A rescan is explicit and may seed live states once. No background timer.
            await self.snapshot()
            self._initialised=True
            async_dispatcher_send(self.hass,self.discovery_signal)
            async_dispatcher_send(self.hass,self.state_signal)
            _LOGGER.info("COMEXIO discovered %d signals (lights=%d, covers=%d, new=%d)",
                len(self.channels),sum(c.kind=='light' for c in self.channels.values()),
                sum(c.kind=='cover' for c in self.channels.values()),len(added))
            return len(added),len(removed)

    async def snapshot(self):
        # Keep the verified v0.4.3 light/cover batches isolated: an unknown EI
        # TCP GET must not prevent existing lighting states from loading.
        standard = [c for c in self.channels.values() if not c.is_enocean
                    and c.kind in ("light", "relay", "switch", "cover", "binary_input")]
        enocean = [c for c in self.channels.values() if c.is_enocean]
        for family, sources in (('standard', standard), ('enocean', enocean)):
            for start in range(0, len(sources), 30):
                batch = sources[start:start + 30]
                try:
                    data = await self.tcp.read_sources(batch)
                    for c in batch:
                        value = data.get(c.key)
                        if c.is_enocean and c.kind == 'binary_input' and c.analog and value is not None:
                            data[c.key] = bool(value)
                    self.values.update(data)
                except ComexioError:
                    self.errors += 1
                    _LOGGER.warning('COMEXIO %s initial GET failed for batch %d; '
                                    'no repeated probing', family, start // 30 + 1)

    async def diagnose_push(self) -> dict:
        """Read-only on-demand Web-IO topology and callback configuration audit."""
        from .constants import CONF_PUSH_BASE, CONF_WEBHOOK_ID
        from .push_audit import audit_push
        path = f"/api/webhook/{self.entry.data[CONF_WEBHOOK_ID]}"
        report = await audit_push(self.admin, self.channels, self.entry.entry_id,
                                  path, self.entry.data[CONF_PUSH_BASE])
        self.push_diagnostics = report.as_dict()
        async_dispatcher_send(self.hass, self.state_signal)
        return self.push_diagnostics

    async def preview_push_repair(self, selected: list[str], mode: str = "repair") -> dict:
        """Inspect on demand, without COMEXIO writes."""
        from .constants import CONF_PUSH_BASE, CONF_WEBHOOK_ID
        from .push_repair import inspect_push_repair
        async with self.maintenance_lock:
            preview = await inspect_push_repair(
                self.admin, self.channels, self.entry.entry_id,
                f"/api/webhook/{self.entry.data[CONF_WEBHOOK_ID]}",
                self.entry.data[CONF_PUSH_BASE], selected, mode=mode,
                observed=self.push_journal.sources())
            return preview.as_dict()

    async def repair_push(self, selected: list[str], mode: str,
                          fingerprint: str, backup_confirmed: bool) -> dict:
        """Queue the shared, durable PushRebuild worker (no blocking HTTP loop)."""
        return await self.push_rebuild.start_repair(
            selected, mode=mode, fingerprint=fingerprint,
            confirmed=backup_confirmed, observed=self.push_journal.sources())

    async def preview_input_push(self, selected: dict[str, str]) -> dict:
        """Read-only preview of opt-in I/AI Web-IO events."""
        from .constants import CONF_PUSH_BASE, CONF_WEBHOOK_ID
        from .input_push import inspect_input_push
        async with self.maintenance_lock:
            return await inspect_input_push(
                self.admin, self.raw_channels, self.entry.entry_id,
                f"/api/webhook/{self.entry.data[CONF_WEBHOOK_ID]}",
                self.entry.data[CONF_PUSH_BASE], selected)

    async def configure_input_push(self, selected: dict[str, str],
                                   fingerprint: str) -> dict:
        """Add only new INPUT-owned resources after a confirmed preview."""
        from .constants import CONF_PUSH_BASE, CONF_WEBHOOK_ID
        from .input_push import apply_input_push
        async with self.maintenance_lock:
            return await apply_input_push(
                self.admin, self.raw_channels, self.entry.entry_id,
                f"/api/webhook/{self.entry.data[CONF_WEBHOOK_ID]}",
                self.entry.data[CONF_PUSH_BASE], selected, fingerprint, True)

    def input_push_status(self) -> dict:
        """In-memory status of the independent opt-in input installation."""
        return dict(self._input_push_status)

    async def start_input_push(self, selected: dict[str, str], fingerprint: str) -> dict:
        """Start a background input job; never tie COMEXIO writes to an HA form request.

        Existing v0.4.3 physical I/AI UI remains synchronous; the new EnOcean
        option uses this job. A partial failure is repaired by a fresh preview
        and idempotent re-invocation, not by blind automatic retries.
        """
        from .admin_api import AdminError
        if self._input_push_task is not None and not self._input_push_task.done():
            raise AdminError('Eingangs-Push-Auftrag läuft bereits')
        if self.push_rebuild is not None and self.push_rebuild.status()['status'] == 'running':
            raise AdminError('Licht-/Rollladen-Push-Auftrag läuft bereits')
        self._input_push_status = {'status': 'running', 'total': len(selected), 'message':
                                  'Eigene Eingangs-Kommandos und Logikpläne werden ergänzt'}
        self._input_push_task = self.hass.async_create_task(
            self._run_input_push(dict(selected), fingerprint))
        async_dispatcher_send(self.hass, self.state_signal)
        return self.input_push_status()

    async def _run_input_push(self, selected: dict[str, str], fingerprint: str) -> None:
        try:
            stats = await self.configure_input_push(selected, fingerprint)
        except asyncio.CancelledError:
            self._input_push_status = {'status': 'interrupted', 'total': len(selected),
                                       'message': 'Unterbrochen; neue Vorschau vor Fortsetzung nötig'}
            raise
        except Exception as exc:
            # Never leak Webhook URLs, credentials, or HTTP body into status.
            from .error_text import safe_admin_reason
            reason = safe_admin_reason(exc)
            self._input_push_status = {'status': 'failed', 'total': len(selected),
                                       'message': reason}
            _LOGGER.warning('COMEXIO Eingangs-Push-Auftrag fehlgeschlagen: %s', reason)
        else:
            self._input_push_status = {'status': 'completed', 'total': len(selected),
                                       'stats': stats, 'message': 'Abschluss geprüft'}
            # Only physical I/AI selections persist a user-chosen input mode.
            physical = {key: mode for key, mode in selected.items()
                        if key in self.raw_channels and not self.raw_channels[key].is_enocean}
            if physical:
                from .preferences import INPUT_MODES
                options = dict(self.entry.options)
                modes = dict(options.get(INPUT_MODES, {}))
                modes.update(physical)
                if modes != options.get(INPUT_MODES, {}):
                    options[INPUT_MODES] = modes
                    self.hass.config_entries.async_update_entry(self.entry, options=options)
                    self.hass.async_create_task(
                        self.hass.config_entries.async_reload(self.entry.entry_id))
        finally:
            async_dispatcher_send(self.hass, self.state_signal)

    async def stop_input_push(self) -> None:
        """Terminate on integration unload; next run must re-check COMEXIO."""
        task = self._input_push_task
        if task is not None and not task.done():
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass

    async def preview_names(self) -> dict:
        """Read-only proposed COMEXIO renames."""
        from .name_inspection import inspect_names
        async with self.maintenance_lock:
            config = await self.admin.read_config()
            return inspect_names(config, self.channels, self.entry.entry_id, self.raw_channels)

    async def _complete_sync_catalog(self, options: dict) -> dict[str, Channel]:
        """Read *every* COMEXIO plan or fail before planning any HA deletions."""
        from .preferences import apply_classifications
        config = await self.admin.read_config()
        modules = config.get('FubModules')
        if (not isinstance(modules, dict) or not isinstance(modules.get('1'), dict)
                or not isinstance(config.get('Fubs'), dict)):
            raise ValueError('COMEXIO-Konfiguration unvollständig; keine Entitätsbereinigung')
        plans = await self.admin.read_plans(config, limit=None, strict=True)
        raw = discover(config, plans)
        if self.channels and not raw:
            raise ValueError('COMEXIO liefert plötzlich keinen einzigen Kanal; '
                             'keine HA-Entitätsbereinigung')
        return apply_classifications(raw, options)

    def _entity_sync_plan(self, new: dict[str, Channel], options: dict) -> dict:
        from .entity_sync import build_entity_plan, registry_rows_for_entry, entity_domain, unique_id_for
        registry, registered = registry_rows_for_entry(self.hass, self.entry)
        foreign = {}
        for key, channel in new.items():
            domain = entity_domain(channel.kind)
            if domain is None:
                continue
            uid = unique_id_for(self.entry, key)
            eid = registry.async_get_entity_id(domain, DOMAIN, uid)
            if eid is not None:
                existing = registry.async_get(eid)
                if existing is not None and existing.config_entry_id != self.entry.entry_id:
                    foreign[(domain, uid)] = existing.config_entry_id
        return build_entity_plan(self.entry, self.channels, new, options,
                                 registered, foreign_ids=foreign)

    async def preview_sync(self) -> dict:
        """Compare one *complete* COMEXIO snapshot and live HA registry."""
        async with self.maintenance_lock, self._lock:
            options = dict(self.entry.options)
            new = await self._complete_sync_catalog(options)
            return self._entity_sync_plan(new, options)

    def _commit_entity_registry(self, report: dict, options: dict, new: dict) -> None:
        """Registry-only changes; never write to COMEXIO administration endpoints."""
        from .entity_sync import (registry_rows_for_entry, saved_user_choices,
                                  verify_registry_candidates)
        registry, _ = registry_rows_for_entry(self.hass, self.entry)
        removals = report['registry_removals']
        verify_registry_candidates(registry, self.entry, removals)
        saved = saved_user_choices(removals, new)
        if saved:
            retained = dict(options.get('classification_areas') or {})
            retained.update(saved)
            options['classification_areas'] = retained
        if options != dict(self.entry.options):
            self.hass.config_entries.async_update_entry(self.entry, options=options)
        removed = 0
        try:
            for item in removals:
                registry.async_remove(item['entity_id'])
                removed += 1
        except Exception as exc:
            # The registry API has no transaction/rollback. Report the exact
            # partial result instead of claiming an all-or-nothing commit.
            raise ValueError(f'HA-Registry-Bereinigung nach {removed} Entitäten '
                             'abgebrochen. Bestand prüfen; keine automatische Wiederholung') from exc
        self.hass.config_entries.async_schedule_reload(self.entry.entry_id)

    async def apply_sync(self, fingerprint: str) -> dict:
        """Recheck all evidence before confirmed, registry-only reconciliation."""
        async with self.maintenance_lock, self._lock:
            options = dict(self.entry.options)
            new = await self._complete_sync_catalog(options)
            report = self._entity_sync_plan(new, options)
            if report['fingerprint'] != fingerprint:
                raise ValueError('COMEXIO/HA-Bestand hat sich seit Vorschau geändert')
            if report['blockers']:
                raise ValueError('Mehrdeutige Entitätszuordnung: ' + ', '.join(report['blockers']))
            if not report['requires_confirmation']:
                return report
            # No second COMEXIO read: exactly the validated snapshot is used.
            self._commit_entity_registry(report, options, new)
            return report

    async def preview_manual_classification(self, options: dict, key: str) -> dict:
        """Classify one source; do not clean unrelated stale Registry entries."""
        async with self.maintenance_lock, self._lock:
            new = await self._complete_sync_catalog(options)
            if key not in new or key not in self.channels:
                raise ValueError('Ausgewählter Ausgang nicht mehr vorhanden')
            report = self._entity_sync_plan(new, options)
            report['registry_removals'] = [r for r in report['registry_removals']
                                           if r['source'] == key]
            return report

    async def apply_manual_classification(self, options: dict, fingerprint: str,
                                          key: str) -> dict:
        async with self.maintenance_lock, self._lock:
            new = await self._complete_sync_catalog(options)
            if key not in new or key not in self.channels:
                raise ValueError('Ausgewählter Ausgang nicht mehr vorhanden')
            report = self._entity_sync_plan(new, options)
            if report['fingerprint'] != fingerprint or report['blockers']:
                raise ValueError('Klassifizierung/Registry seit Vorschau geändert')
            report['registry_removals'] = [r for r in report['registry_removals']
                                           if r['source'] == key]
            self._commit_entity_registry(report, options, new)
            return report

    def apply_event(self, payload:dict) -> bool:
        """Accept only a known source and a valid value. No GET triggered by the event."""
        address=event_address(payload)
        if address is None or address not in self.channels:
            self.note_rejection("Unbekannte COMEXIO-Quelladresse")
            return False
        channel=self.channels[address]
        if not channel.is_push_source:
            self.note_rejection("Quelle ist kein Push-Ziel")
            return False
        raw=payload.get("value")
        try:
            if channel.analog:
                if isinstance(raw,bool) or raw is None:
                    self.note_rejection("Ungueltiger Analogwert")
                    return False
                value=float(raw)
                if not math.isfinite(value):
                    self.note_rejection("Analogwert ist nicht endlich")
                    return False
                maximum = channel.push_maximum
                if not (0 <= value <= maximum):
                    self.note_rejection(f"Analogwert ausserhalb 0 bis {maximum}")
                    return False
                # A COMEXIO presence signal may use analog transport (EI2_PIRS)
                # while its HA semantics are binary. Preserve numeric values
                # for real EnOcean measurements such as ILL/SVC.
                if channel.is_enocean and channel.kind == 'binary_input':
                    value = value > 0
            else:
                if raw not in (0,1,"0","1",False,True):
                    self.note_rejection("Ungueltiger Digitalwert")
                    return False
                value=bool(int(raw))
        except (ValueError,TypeError):
            self.note_rejection("Ereigniswert konnte nicht gelesen werden")
            return False
        previous = self.values.get(address)
        self.values[address]=value
        self.last_event=datetime.now(timezone.utc)
        self.events+=1
        event = self.push_journal.record(
            source=address,
            name=channel.name,
            kind=channel.kind,
            value=value,
            previous=previous,
            entity_id=self._entity_id_for(channel),
            received_at=self.last_event,
        )
        # The HA event bus allows optional user-side event inspection/automations.
        # No webhook credentials or raw HTTP payloads are exposed here.
        self.hass.bus.async_fire(f"{DOMAIN}_push", dict(event))
        button_press = (channel.is_enocean and channel.input_mode == 'taster'
                        and value is True)
        if (channel.kind == 'binary_input'
                and ((previous != value and (previous is not None or value is True))
                     or button_press)):
            # A separate event provides a stable automation API. Do not synthesize
            # short/long/double clicks from raw edges in this release.
            action = ('gedrueckt' if value else 'losgelassen') if channel.input_mode == 'taster' else ('ein' if value else 'aus')
            self.hass.bus.async_fire(f'{DOMAIN}_input', {
                'source': address,
                'name': channel.name,
                'mode': channel.input_mode,
                'action': action,
                'value': int(value),
                'entity_id': self._entity_id_for(channel),
            })
        async_dispatcher_send(self.hass,self.state_signal)
        return True

    def _entity_id_for(self, channel: Channel) -> str | None:
        """Look up the existing HA entity; do not generate guessed entity IDs."""
        if channel.kind not in ("light", "cover", "switch", "relay", "binary_input") \
                and not (channel.is_enocean and channel.kind == 'enocean_sensor'):
            return None
        from homeassistant.helpers.entity_registry import async_get
        registry = async_get(self.hass)
        unique_id = f"{self.entry.unique_id or self.entry.entry_id}:{channel.key}"
        return registry.async_get_entity_id(
            ("binary_sensor" if channel.kind in ("relay", "binary_input") else
             "sensor" if channel.kind == 'enocean_sensor' else channel.kind), DOMAIN, unique_id)

    def push_events_report(self, limit: int = 30) -> dict:
        """Return local event history without contacting the IO server."""
        return self.push_journal.report(limit)

    def note_rejection(self, reason: str) -> None:
        # Never log the request body or the secret webhook path.
        self.rejected_events += 1
        self.last_rejection = reason
        async_dispatcher_send(self.hass, self.state_signal)
        _LOGGER.warning("COMEXIO Push Ereignis abgelehnt: %s", reason)

    async def change_light(self, channel:Channel, value:bool) -> None:
        """Never optimistic. Only a bounded one-shot GET after TCP SET."""
        await self.tcp.set_channel(channel,value)
        result=await self.tcp.read_sources([channel])
        if result.get(channel.key) is None:
            raise ComexioError("COMEXIO output state not confirmed after SET")
        self.values.update(result)
        async_dispatcher_send(self.hass,self.state_signal)

    async def change_cover(self, channel:Channel, pos:float) -> None:
        if channel.target_marker_id is None: raise ComexioError("No target marker")
        await self.tcp.write_marker(channel.target_marker_id, pos)
        # Position change is confirmed only when COMEXIO sends the *actual* marker event.

    def value(self, key:str):
        return self.values.get(key)
