"""COMEXIO Local UI setup: transport and admin access only, never fixed channels."""
from __future__ import annotations
import secrets
import hashlib
import json
import logging
import re

import voluptuous as vol
from homeassistant import config_entries
from homeassistant.helpers.aiohttp_client import async_create_clientsession
from aiohttp import CookieJar
from .admin_api import AdminError, ComexioAdmin
from .constants import (
    CONF_ADMIN_PASSWORD, CONF_ADMIN_USER, CONF_HOST, CONF_PUSH_BASE,
    CONF_TCP_PORT, CONF_WEBHOOK_ID, DEFAULT_HA_PUSH_URL,
    DEFAULT_HOST, DEFAULT_TCP_PORT, DOMAIN,
)


_LOGGER = logging.getLogger(__name__)


def _safe_admin_reason(err: AdminError) -> str:
    """Human-readable diagnostics without webhook IDs or credentials."""
    reason = str(err).replace('\r', ' ').replace('\n', ' ').strip()
    # read_config wraps low-level HTTP errors; recover only their status code,
    # never an exception URL or response body that could contain credentials.
    cause = err.__cause__
    status = getattr(cause, 'status', None)
    if isinstance(status, int) and status >= 100 and f'HTTP {status}' not in reason:
        reason += f' (HTTP {status})'
    elif isinstance(cause, TimeoutError):
        reason += ' (Zeitlimit bei COMEXIO-Anfrage)'
    reason = re.sub(r'(?i)(/api/webhook/)[^\s/?&#<>]+',
                    r'\1[geschuetzt]', reason)
    reason = re.sub(r'(?i)https?://[^\s<>]+', '[URL geschuetzt]', reason)
    reason = re.sub(r'(?i)\b(password|token|secret|api_key)\s*[:=]\s*[^\s,;]+',
                    r'\1=[geschuetzt]', reason)
    return (reason or 'COMEXIO lieferte keine Fehlerdetails')[:300]


class ComexioLocalConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    VERSION = 1

    async def async_step_user(self, user_input=None):
        errors = {}
        if user_input is not None:
            host = user_input[CONF_HOST].strip()
            admin = ComexioAdmin(
                async_create_clientsession(self.hass, cookie_jar=CookieJar(unsafe=True)), host,
                user_input[CONF_ADMIN_USER], user_input[CONF_ADMIN_PASSWORD]
            )
            try:
                config = await admin.read_config()
                if "FubModules" not in config:
                    raise AdminError("COMEXIO configuration not found")
            except AdminError:
                errors["base"] = "cannot_connect"
            else:
                await self.async_set_unique_id(f"comexio_local:{host}")
                self._abort_if_unique_id_configured()
                data = dict(user_input)
                data[CONF_HOST] = host
                data[CONF_WEBHOOK_ID] = secrets.token_urlsafe(36)
                return self.async_create_entry(title=f"COMEXIO {host}", data=data)

        schema = vol.Schema({
            vol.Required(CONF_HOST, default=DEFAULT_HOST): str,
            vol.Required(CONF_TCP_PORT, default=DEFAULT_TCP_PORT): vol.All(vol.Coerce(int), vol.Range(min=1,max=65535)),
            vol.Required(CONF_ADMIN_USER, default="admin"): str,
            vol.Required(CONF_ADMIN_PASSWORD): str,
            vol.Required(CONF_PUSH_BASE, default=DEFAULT_HA_PUSH_URL): str,
        })
        return self.async_show_form(step_id="user", data_schema=schema, errors=errors)


    @staticmethod
    def async_get_options_flow(config_entry):
        """Home Assistant's Configure button opens an explicit maintenance wizard."""
        return ComexioLocalOptionsFlow()


class ComexioLocalOptionsFlow(config_entries.OptionsFlow):
    """No configuration write until selection, preview and backup confirmation."""

    def __init__(self):
        self._selected: list[str] = []
        self._mode = 'repair'
        self._preview: dict | None = None
        self._area_preview: dict | None = None
        self._area_selected: list[str] | None = None
        self._area_target: str | None = None
        self._area_overwrite = False
        self._direction_preview = None
        self._class_preview = None
        self._class_sync_fingerprint = None
        self._class_has_deletions = False
        self._sync_preview = None
        self._rebuild_preview = None
        self._rebuild_observer = None
        self._input_selected: dict[str, str] = {}
        self._input_preview: dict | None = None
        # The options-flow instance survives a form validation error. Preserve
        # the exact form selection instead of silently reverting to "all inputs".
        self._input_ui_sources: list[str] = []
        self._input_ui_mode = 'taster'

    def _runtime(self):
        return self.hass.data.get(DOMAIN, {}).get(self.config_entry.entry_id)

    async def async_step_init(self, user_input=None):
        if self._runtime() is None:
            return self.async_abort(reason='not_loaded')
        return self.async_show_menu(
            step_id='init',
            menu_options=['push_management', 'devices_menu', 'covers_menu', 'maintenance_menu'],
        )

    async def async_step_devices_menu(self, user_input=None):
        """Device classification and HA area assignments in one clearly named group."""
        if self._runtime() is None:
            return self.async_abort(reason='not_loaded')
        return self.async_show_menu(
            step_id='devices_menu',
            menu_options=['area_auto', 'area_manual', 'classify_select'],
        )

    async def async_step_covers_menu(self, user_input=None):
        """Cover position mapping, without changes to COMEXIO hardware."""
        if self._runtime() is None:
            return self.async_abort(reason='not_loaded')
        return self.async_show_menu(
            step_id='covers_menu',
            menu_options=['cover_global', 'cover_single'],
        )

    async def async_step_maintenance_menu(self, user_input=None):
        """Read-only discovery and name diagnostics."""
        if self._runtime() is None:
            return self.async_abort(reason='not_loaded')
        return self.async_show_menu(
            step_id='maintenance_menu',
            menu_options=['sync_preview', 'names_preview'],
        )

    async def async_step_push_management(self, user_input=None):
        """One entry point for inspection, repair and long-running rebuild jobs."""
        runtime = self._runtime()
        if runtime is None:
            return self.async_abort(reason='not_loaded')
        options = ['input_select', 'repair_select', 'rebuild_preview', 'rebuild_status']
        if runtime.push_rebuild.status()['status'] not in ('not_started', 'completed', 'cancelled'):
            options = ['rebuild_status', 'input_select', 'repair_select', 'rebuild_preview']
        return self.async_show_menu(step_id='push_management', menu_options=options)

    async def async_step_rebuild_preview(self, user_input=None):
        runtime = self._runtime()
        if runtime is None:
            return self.async_abort(reason='not_loaded')
        try:
            self._rebuild_preview = await runtime.push_rebuild.preview()
        except AdminError:
            return self.async_abort(reason='cannot_connect')
        return await self.async_step_rebuild_review()

    async def async_step_rebuild_review(self, user_input=None):
        preview = self._rebuild_preview
        runtime = self._runtime()
        if preview is None or runtime is None:
            return self.async_abort(reason='not_loaded')
        status = runtime.push_rebuild.status()
        if status['status'] not in ('not_started', 'completed', 'cancelled', 'failed', 'interrupted'):
            return await self.async_step_rebuild_status()
        summary = (f"**{preview['sources']} Quellen**, {preview['commands']} vorhandene Web-IO-Befehle, "
                   f"{preview['plans']} Push-Pläne. Erwartete Schritte: {preview['steps']}. "
                   "**Mindestens 2 Sekunden Abstand zwischen Schreibzugriffen.**\n\n"
                   + preview['note'])
        schema = {vol.Required('backup_confirmed', default=False): bool}
        if preview.get('requires_cleanup'):
            schema[vol.Required('cleanup_confirmed', default=False)] = bool
        if user_input is not None:
            if (user_input.get('backup_confirmed') is not True or
                (preview.get('requires_cleanup') and
                 user_input.get('cleanup_confirmed') is not True)):
                return self.async_show_form(
                    step_id='rebuild_review',
                    data_schema=vol.Schema(schema),
                    description_placeholders={'summary': summary},
                    errors={'base': 'backup_required'})
            try:
                status = await runtime.push_rebuild.start(
                    preview['fingerprint'], True,
                    cleanup_confirmed=user_input.get('cleanup_confirmed') is True)
            except AdminError:
                return self.async_abort(reason='rebuild_failed')
            return await self.async_step_rebuild_progress()
        return self.async_show_form(
            step_id='rebuild_review',
            data_schema=vol.Schema(schema),
            description_placeholders={'summary': summary},
        )

    async def async_step_rebuild_progress(self, user_input=None):
        """Progress task is only an observer; closing dialog never stops COMEXIO work."""
        runtime = self._runtime()
        if runtime is None:
            return self.async_abort(reason='not_loaded')
        if self._rebuild_observer is None:
            self._rebuild_observer = self.hass.async_create_task(self._watch_rebuild(runtime))
        if not self._rebuild_observer.done():
            return self.async_show_progress(
                step_id='rebuild_progress', progress_action='provisioning',
                progress_task=self._rebuild_observer,
            )
        return self.async_show_progress_done(next_step_id='rebuild_status')

    async def _watch_rebuild(self, runtime):
        """Observe the independently running job without delaying COMEXIO work."""
        import asyncio
        last_progress = None
        while True:
            status = runtime.push_rebuild.status()
            progress = min(1.0, max(0.0, float(status['percent']) / 100.0))
            if progress != last_progress:
                self.async_update_progress(progress)
                last_progress = progress
            if status['status'] != 'running':
                return
            await asyncio.sleep(0.5)

    async def async_step_rebuild_status(self, user_input=None):
        runtime = self._runtime()
        if runtime is None:
            return self.async_abort(reason='not_loaded')
        errors = {}
        if runtime.push_rebuild.status()['status'] == 'completed':
            completed = runtime.push_rebuild.status()
            return self.async_abort(reason='rebuild_completed',
                description_placeholders={'summary':
                    f"{completed['done']}/{completed['total']} Schritte, "
                    f"{completed['elapsed_seconds']} Sekunden; "
                    f"{completed.get('message', 'ohne Fehler abgeschlossen')}"})
        if user_input is not None:
            try:
                action = user_input['operation']
                if action in ('pause', 'resume', 'cancel'):
                    await getattr(runtime.push_rebuild, action)()
            except AdminError:
                errors['base'] = 'rebuild_failed'
            else:
                if action == 'resume' and runtime.push_rebuild.status()['status'] == 'running':
                    self._rebuild_observer = None
                    return await self.async_step_rebuild_progress()
        status = runtime.push_rebuild.status()
        state_names = {
            'not_started': 'Noch nicht begonnen',
            'awaiting_cleanup': 'Wartet auf Bereinigung',
            'running': 'Neuaufbau läuft',
            'paused': 'Pausiert',
            'interrupted': 'Unterbrochen',
            'failed': 'Fehlgeschlagen',
            'cancelled': 'Abgebrochen',
            'completed': 'Abgeschlossen',
            'completed_partial': 'Ausgewählte Pläne geprüft; Gesamtstatus unvollständig',
        }
        phase_names = {
            'cleanup': 'Eigene Push-Ressourcen bereinigen',
            'command': 'Web-IO-Befehl erstellen',
            'link': 'Push-Verbindung anlegen',
            'activate': 'Push-Plan aktivieren',
            'verify': 'Abschlussprüfung',
            'fertig': 'Fertig',
        }
        eta = ('unbekannt' if status['eta_seconds'] is None
               else f"ca. {status['eta_seconds']} Sekunden")
        summary = (f"**Status:** {state_names.get(status['status'], status['status'])}\n\n"
                   f"**Fortschritt:** {status['done']} / {status['total']} "
                   f"({status['percent']} %)\n\n"
                   f"**Aktuell:** {status.get('current', '-')} "
                   f"({phase_names.get(status.get('phase'), status.get('phase', '-'))})\n\n"
                   f"**Vergangen:** {status['elapsed_seconds']} s; **Rest:** {eta}\n\n"
                   f"**Letzter abgeschlossener Schritt:** {status.get('last_completed_at_utc') or '–'}\n\n"
                   f"{status.get('message', '')}")
        available = {'refresh': 'Aktualisieren'}
        if status['status'] == 'running':
            available.update({'pause': 'Nach diesem Schritt pausieren',
                              'cancel': 'Nach diesem Schritt abbrechen'})
        elif status['status'] in ('paused', 'interrupted', 'failed', 'awaiting_cleanup'):
            available.update({'resume': 'Nach Prüfung fortsetzen', 'cancel': 'Abbrechen'})
        return self.async_show_form(
            step_id='rebuild_status',
            data_schema=vol.Schema({vol.Required('operation', default='refresh'): vol.In(available)}),
            errors=errors, description_placeholders={'summary': summary})

    async def async_step_input_select(self, user_input=None):
        """Select arbitrary hardware inputs; AI requires explicit digital consent."""
        from homeassistant.helpers.selector import SelectSelector, SelectSelectorConfig, SelectSelectorMode
        from .input_push import input_catalog
        runtime = self._runtime()
        if runtime is None:
            return self.async_abort(reason='not_loaded')
        catalog = input_catalog(runtime.raw_channels)
        if not catalog:
            return self.async_abort(reason='no_inputs')
        entries = sorted(catalog.values(), key=lambda c: (c.extension, c.identifier))
        choices = []
        standard_i = set()
        for c in entries:
            if c.identifier.upper().startswith('I'):
                standard_i.add(c.key)
            hint = 'AI: nur wählen, wenn als digitaler Eingang konfiguriert' if c.identifier.upper().startswith('AI') else 'Digitaler Eingang'
            current = self.config_entry.options.get('input_modes', {}).get(c.key)
            suffix = f' – bereits: {current}' if current else ''
            choices.append({'value':c.key, 'label':f'{c.name} [{c.extension}/{c.identifier}] – {hint}{suffix}'})
        if standard_i:
            # Keep the bulk action at the end: an empty form must never look
            # as if every physical input had been explicitly selected.
            choices.append({'value':'__all_i__',
                'label':f'Alle {len(standard_i)} normalen I-Eingänge (ohne AI) auswählen'})
        if user_input is not None:
            self._input_ui_sources = list(dict.fromkeys(
                key for key in user_input.get('sources', [])
                if key == '__all_i__' or key in catalog))
            mode = user_input.get('input_mode')
            if mode in ('taster', 'schalter'):
                self._input_ui_mode = mode
        schema = vol.Schema({
            vol.Required('sources', default=list(self._input_ui_sources)):SelectSelector(
                SelectSelectorConfig(options=choices, multiple=True, mode=SelectSelectorMode.DROPDOWN)),
            vol.Required('input_mode', default=self._input_ui_mode):vol.In({
                'taster':'Taster – gedrückt/losgelassen (Impuls)',
                'schalter':'Kipp-/Wippschalter – ein/aus (rastend)',
            }),
        })
        errors = {}
        diagnostic = ''
        if user_input is not None:
            requested = set(user_input['sources'])
            if '__all_i__' in requested:
                requested.remove('__all_i__')
                requested.update(standard_i)
            if not requested or len(requested) > 90:
                errors['base'] = 'empty_selection'
            elif not requested <= set(catalog):
                errors['base'] = 'invalid_selection'
            else:
                self._input_selected = {key:user_input['input_mode'] for key in sorted(requested)}
                self._input_preview = None
                try:
                    self._input_preview = await runtime.preview_input_push(self._input_selected)
                except AdminError as err:
                    errors['base'] = 'input_preview_failed'
                    reason = _safe_admin_reason(err)
                    diagnostic = f'**Diagnose:** {reason}'
                    _LOGGER.warning('COMEXIO Eingangs-Push-Vorschau fehlgeschlagen: %s', reason)
                else:
                    return await self.async_step_input_review()
        return self.async_show_form(
            step_id='input_select', data_schema=schema, errors=errors,
            description_placeholders={'diagnostic': diagnostic})

    async def async_step_input_review(self, user_input=None):
        """Preview fingerprint and backup confirmation; never edit Q push plans."""
        from .preferences import INPUT_MODES
        runtime = self._runtime()
        preview = self._input_preview
        if runtime is None or preview is None or not self._input_selected:
            return self.async_abort(reason='not_loaded')
        lines=[]
        for row in preview['sources']:
            readback = ('; **Web-IO-Rücklesedaten (Data/Parameter) nicht vollständig – '
                        'Live-Push-Test erforderlich**' if row.get('callback_verified') is False else '')
            lines.append(f"**{row['name']}** (`{row['address']}`) – "
                         f"{row['mode']}, **{row['action']}**. "
                         f"Web-IO: `{row['command']}`; Plan: `{row['plan']}`{readback}")
        lines.append('**Wichtig:** AI-Kanäle dürfen nur gewählt werden, wenn sie in '
                     'COMEXIO als Digitaleingang verwendet werden. Die bisherigen '
                     '30 Licht-/Rollladen-Push-Verbindungen bleiben unangetastet. '
                     'Die Tastererkennung (einfach/doppelt/lang) folgt später; '
                     'hier werden rohe 0/1-Flanken übertragen.')
        summary = '\n\n'.join(lines)
        if user_input is not None:
            if user_input.get('backup_confirmed') is not True:
                return self.async_show_form(step_id='input_review',
                    data_schema=vol.Schema({vol.Required('backup_confirmed',default=False):bool}),
                    description_placeholders={'summary':summary},
                    errors={'base':'backup_required'})
            try:
                await runtime.configure_input_push(self._input_selected, preview['fingerprint'])
            except AdminError as err:
                reason = _safe_admin_reason(err)
                _LOGGER.warning('COMEXIO Eingangs-Push gestoppt: %s', reason)
                return self.async_abort(reason='input_failed',
                                        description_placeholders={'reason': reason})
            options = dict(self.config_entry.options)
            modes = dict(options.get(INPUT_MODES, {}))
            modes.update(self._input_selected)
            if modes != options.get(INPUT_MODES, {}):
                options[INPUT_MODES] = modes
                self._save_options(options, reload=True)
            return self.async_abort(reason='input_completed')
        return self.async_show_form(step_id='input_review',
            data_schema=vol.Schema({vol.Required('backup_confirmed',default=False):bool}),
            description_placeholders={'summary':summary})

    async def async_step_repair_select(self, user_input=None):
        from homeassistant.helpers.selector import SelectSelector, SelectSelectorConfig, SelectSelectorMode
        from .push_setup import push_sources

        runtime = self._runtime()
        if runtime is None:
            return self.async_abort(reason='not_loaded')
        choices = []
        for channel in sorted(push_sources(runtime.channels), key=lambda c: (c.kind, c.name.casefold())):
            loc = f'M{channel.marker_id}' if channel.kind == 'cover' else f'{channel.extension}/{channel.identifier}'
            kind = 'Rollladen' if channel.kind == 'cover' else 'Licht'
            choices.append({'value': channel.key, 'label': f'{kind}: {channel.name} [{loc}]'})
        if not choices:
            return self.async_abort(reason='no_sources')
        all_sources = {item['value'] for item in choices}
        choices.insert(0, {'value': '__all__', 'label': f'Alle {len(all_sources)} Push-Quellen auswählen'})
        schema = vol.Schema({
            vol.Required('sources'): SelectSelector(SelectSelectorConfig(
                options=choices, multiple=True, mode=SelectSelectorMode.DROPDOWN)),
            vol.Required('mode', default='repair'): vol.In({
                'repair': 'Fehlende Befehle / Verbindungen ergänzen',
                'rebuild': 'Neuaufbau einer vorhandenen Quelle vorbereiten',
            }),
        })
        errors = {}
        if user_input is not None:
            selected = list(dict.fromkeys(user_input['sources']))
            if '__all__' in selected:
                selected = sorted(all_sources)
            if not selected:
                errors['base'] = 'empty_selection'
            elif not set(selected) <= {choice['value'] for choice in choices}:
                errors['base'] = 'invalid_selection'
            else:
                self._selected, self._mode = selected, user_input['mode']
                try:
                    self._preview = await runtime.preview_push_repair(selected, self._mode)
                except AdminError:
                    errors['base'] = 'cannot_connect'
                else:
                    return await self.async_step_repair_review()
        return self.async_show_form(step_id='repair_select', data_schema=schema, errors=errors)

    async def async_step_repair_review(self, user_input=None):
        preview = self._preview
        runtime = self._runtime()
        if preview is None or runtime is None:
            return self.async_abort(reason='not_loaded')
        lines = []
        action_text = {
            'none': 'Keine Änderung',
            'create_command': 'Fehlenden Web-IO-Befehl anlegen und Verbindung prüfen',
            'restore_link': 'Fehlende Verknüpfung wiederherstellen',
            'activate_plan': 'Vorhandenen eigenen Push-Plan aktivieren',
            'activate_command': 'Vorhandenen Web-IO-Befehl und Push-Plan aktivieren',
            'manual_rebuild': 'Geführter manueller Neuaufbau notwendig',
            'blocked': 'Aus Sicherheitsgründen gesperrt',
        }
        for item in preview['sources']:
            last = item.get('last_event_utc') or 'kein Ereignis seit Integrationsstart'
            lines.append(f"**{item['name']}** ({item['address']}) – "
                         f"**{action_text.get(item['action'], item['action'])}**. "
                         f"Web-IO: `{item['command_name']}`; "
                         f"Push-Plan: `{item['plan_name']}`; "
                         f"letzter Push: {last}. "
                         f"{item['detail']}")
        lines.append('**Hinweis:** Ein CL-Plan kann bei der Aktivierung neu ausgewertet werden. '
                     'Die Sicherung muss vor jeder Konfigurationsänderung vorhanden sein.')
        blocked = preview['blocked']
        changing = preview['needs_write']
        if user_input is not None:
            if blocked:
                return self.async_abort(reason='manual_required')
            if not changing:
                return self.async_abort(reason='no_changes')
            if user_input.get('backup_confirmed') is not True:
                return self.async_show_form(
                    step_id='repair_review',
                    data_schema=vol.Schema({vol.Required('backup_confirmed', default=False): bool}),
                    description_placeholders={'summary': '\n\n'.join(lines)},
                    errors={'base': 'backup_required'},
                )
            try:
                status = await runtime.repair_push(
                    self._selected, self._mode, preview['fingerprint'], True)
            except AdminError as err:
                import logging
                logging.getLogger(__name__).warning('Push-Auftrag nicht gestartet: %s', err)
                return self.async_abort(reason='repair_failed')
            if status.get('status') == 'nothing_to_do':
                return self.async_abort(reason='no_changes')
            self._rebuild_observer = None
            return await self.async_step_rebuild_progress()
        schema = (vol.Schema({vol.Required('backup_confirmed', default=False): bool})
                  if changing and not blocked else vol.Schema({}))
        return self.async_show_form(
            step_id='repair_review', data_schema=schema,
            description_placeholders={'summary': '\n\n'.join(lines)},
        )


    async def async_step_area_auto(self, user_input=None):
        """Preview conservative matches between COMEXIO room names and HA areas."""
        from .area_assignment import preview_area_assignment
        runtime = self._runtime()
        if runtime is None:
            return self.async_abort(reason='not_loaded')
        self._area_selected = None
        self._area_target = None
        self._area_overwrite = False
        self._area_preview = preview_area_assignment(self.hass, self.config_entry, runtime.channels)
        return await self.async_step_area_review()

    async def async_step_area_manual(self, user_input=None):
        """Assign a selected group of sources to one explicitly chosen HA area."""
        from homeassistant.helpers.selector import (
            AreaSelector, AreaSelectorConfig,
            SelectSelector, SelectSelectorConfig, SelectSelectorMode,
        )
        from .area_assignment import preview_area_assignment
        runtime = self._runtime()
        if runtime is None:
            return self.async_abort(reason='not_loaded')
        choices = [
            {'value': c.key, 'label': f'{c.name} [{c.key}]'}
            for c in sorted(runtime.channels.values(), key=lambda c: c.name.casefold())
            if c.kind in ('light', 'cover')
        ]
        if not choices:
            return self.async_abort(reason='no_sources')
        schema = vol.Schema({
            vol.Required('sources'): SelectSelector(SelectSelectorConfig(
                options=choices, multiple=True, mode=SelectSelectorMode.DROPDOWN)),
            vol.Required('area'): AreaSelector(AreaSelectorConfig()),
            vol.Required('overwrite', default=False): bool,
        })
        errors = {}
        if user_input is not None:
            selected = list(dict.fromkeys(user_input['sources']))
            if not selected or not set(selected) <= {c['value'] for c in choices}:
                errors['base'] = 'invalid_selection'
            else:
                try:
                    report = preview_area_assignment(
                        self.hass, self.config_entry, runtime.channels,
                        selected=selected, target_area=user_input['area'],
                        overwrite=user_input['overwrite'])
                except ValueError:
                    errors['base'] = 'area_invalid'
                else:
                    self._area_selected = selected
                    self._area_target = user_input['area']
                    self._area_overwrite = user_input['overwrite']
                    self._area_preview = report
                    return await self.async_step_area_review()
        return self.async_show_form(step_id='area_manual', data_schema=schema, errors=errors)

    async def async_step_area_review(self, user_input=None):
        """Never write before explicit confirmation; recheck registry on apply."""
        from .area_assignment import apply_area_assignment
        runtime = self._runtime()
        preview = self._area_preview
        if runtime is None or preview is None:
            return self.async_abort(reason='not_loaded')
        labels = {
            'assign': 'Zuordnen', 'unchanged': 'Bereits richtig',
            'keep_existing': 'Bestehende Zuordnung bleibt erhalten',
            'no_match': 'Kein eindeutiger Bereich',
            'unavailable': 'HA-Entitaet nicht registriert',
        }
        areas = preview['area_names']
        lines = []
        for item in preview['rows']:
            current = areas.get(item['before']) if item['before'] else 'Keiner'
            target = areas.get(item['target']) if item['target'] else 'Unbekannt'
            lines.append(f"**{item['name']}** ({item['entity_id'] or item['key']}): "
                         f"{current} -> {target}; **{labels[item['action']]}**")
        lines.append(f"\n**Geplante Zuordnungen: {preview['assignments']}**. "
                     'Bestehende eigene Bereiche bleiben ohne explizite Freigabe erhalten.')
        if user_input is not None:
            if not preview['assignments']:
                return self.async_abort(reason='no_changes')
            if user_input.get('confirm') is not True:
                return self.async_show_form(
                    step_id='area_review',
                    data_schema=vol.Schema({vol.Required('confirm', default=False): bool}),
                    description_placeholders={'summary': '\n\n'.join(lines)},
                    errors={'base': 'confirmation_required'},
                )
            try:
                apply_area_assignment(
                    self.hass, self.config_entry, runtime.channels,
                    fingerprint=preview['fingerprint'],
                    selected=self._area_selected, target_area=self._area_target,
                    overwrite=self._area_overwrite, confirm=True)
            except ValueError:
                return self.async_abort(reason='area_changed')
            return self.async_abort(reason='areas_completed')
        schema = (vol.Schema({vol.Required('confirm', default=False): bool})
                  if preview['assignments'] else vol.Schema({}))
        return self.async_show_form(
            step_id='area_review', data_schema=schema,
            description_placeholders={'summary': '\n\n'.join(lines)},
        )

    async def async_step_names_preview(self, user_input=None):
        """Read-only validation of the canonical COMEXIO name schema."""
        from .admin_api import AdminError
        runtime = self._runtime()
        if runtime is None:
            return self.async_abort(reason='not_loaded')
        if user_input is not None:
            return self.async_abort(reason='readonly_preview')
        try:
            result = await runtime.preview_names()
        except AdminError:
            return self.async_abort(reason='cannot_connect')
        summary = [f"**Kanonisch benannte Ressourcen:** {len(result['found'])}",
                   f"**Noch nicht angelegt:** {len(result['missing'])}"]
        summary.extend(f"**Abweichung:** {item}" for item in result['blockers'])
        if result['missing']:
            summary.append('**Fehlende Ressourcen:** ' + ', '.join(result['missing'][:8])
                           + (' …' if len(result['missing']) > 8 else ''))
        if not result['blockers']:
            summary.append('Keine abweichend benannten eigenen Ressourcen erkannt.')
        summary.append('**Rein lesend:** Es werden keine COMEXIO-Namen geändert.')
        return self.async_show_form(
            step_id='names_preview', data_schema=vol.Schema({}),
            description_placeholders={'summary': '\n\n'.join(summary)},
        )


    def _local_fingerprint(self, purpose: str, payload: dict) -> str:
        """Prevent applying a UI proposal after options/catalog changes."""
        runtime = self._runtime()
        value = {
            'purpose': purpose, 'payload': payload,
            'options': dict(self.config_entry.options),
            'catalog': {k: (c.kind, c.name) for k, c in sorted(runtime.channels.items())},
        }
        return hashlib.sha256(json.dumps(value, sort_keys=True, default=str).encode()).hexdigest()

    def _save_options(self, new_options: dict, *, reload: bool = False) -> None:
        from homeassistant.helpers.dispatcher import async_dispatcher_send
        self.hass.config_entries.async_update_entry(self.config_entry, options=new_options)
        runtime = self._runtime()
        if runtime is not None:
            async_dispatcher_send(self.hass, runtime.state_signal)
        if reload:
            # A platform change (light / binary_sensor / switch) needs fresh
            # platform setup; HA does not change entity domains in place.
            self.hass.async_create_task(self.hass.config_entries.async_reload(self.config_entry.entry_id))

    async def async_step_cover_global(self, user_input=None):
        from .preferences import COVER_DEFAULT
        runtime = self._runtime()
        if runtime is None:
            return self.async_abort(reason='not_loaded')
        if user_input is not None:
            self._direction_preview = {
                'global': bool(user_input['inverted']),
                'source': None, 'mode': None,
            }
            self._direction_preview['fingerprint'] = self._local_fingerprint(
                'cover_direction', {k: v for k,v in self._direction_preview.items() if k != 'fingerprint'})
            return await self.async_step_cover_review()
        current = self.config_entry.options.get(COVER_DEFAULT, False) is True
        return self.async_show_form(step_id='cover_global', data_schema=vol.Schema({
            vol.Required('inverted', default=current): bool,
        }))

    async def async_step_cover_single(self, user_input=None):
        from homeassistant.helpers.selector import SelectSelector, SelectSelectorConfig
        from .preferences import COVER_OVERRIDES
        runtime = self._runtime()
        if runtime is None:
            return self.async_abort(reason='not_loaded')
        covers = [c for c in runtime.channels.values() if c.kind == 'cover']
        if not covers:
            return self.async_abort(reason='no_sources')
        choices = [{'label': f'{c.name} [{c.key}]', 'value': c.key}
                   for c in sorted(covers, key=lambda x: x.name.casefold())]
        schema = vol.Schema({
            vol.Required('source'): SelectSelector(SelectSelectorConfig(options=choices)),
            vol.Required('direction', default='inherit'): vol.In({
                'inherit': 'Globale Einstellung verwenden',
                'invert': 'Invertiert (COMEXIO 0 = oben)',
                'normal': 'Nicht invertiert (COMEXIO 100 = oben)',
            }),
        })
        errors = {}
        if user_input is not None:
            source = user_input['source']
            if source not in {c.key for c in covers}:
                errors['base'] = 'invalid_selection'
            else:
                self._direction_preview = {
                    'global': None, 'source': source,
                    'mode': user_input['direction'],
                }
                self._direction_preview['fingerprint'] = self._local_fingerprint(
                    'cover_direction', {k: v for k,v in self._direction_preview.items() if k != 'fingerprint'})
                return await self.async_step_cover_review()
        return self.async_show_form(step_id='cover_single', data_schema=schema, errors=errors)

    async def async_step_cover_review(self, user_input=None):
        from .preferences import COVER_DEFAULT, COVER_OVERRIDES, cover_is_inverted
        preview = self._direction_preview
        runtime = self._runtime()
        if preview is None or runtime is None:
            return self.async_abort(reason='not_loaded')
        payload = {k: v for k,v in preview.items() if k != 'fingerprint'}
        if preview['fingerprint'] != self._local_fingerprint('cover_direction', payload):
            return self.async_abort(reason='settings_changed')
        options = dict(self.config_entry.options)
        if preview['source'] is None:
            old = options.get(COVER_DEFAULT, False) is True
            new = preview['global']
            affected = sum(1 for c in runtime.channels.values()
                           if c.kind == 'cover' and c.key not in options.get(COVER_OVERRIDES, {}))
            description = (f"**Global:** {'invertiert' if old else 'nicht invertiert'} → "
                           f"**{'invertiert' if new else 'nicht invertiert'}**. "
                           f"{affected} Rollläden übernehmen diese Einstellung; individuelle Ausnahmen bleiben erhalten.")
            options[COVER_DEFAULT] = new
        else:
            key = preview['source']
            channel = runtime.channels.get(key)
            if channel is None or channel.kind != 'cover':
                return self.async_abort(reason='settings_changed')
            old = cover_is_inverted(options, key)
            overrides = dict(options.get(COVER_OVERRIDES, {}))
            if preview['mode'] == 'inherit':
                overrides.pop(key, None)
            else:
                overrides[key] = preview['mode'] == 'invert'
            options[COVER_OVERRIDES] = overrides
            new = cover_is_inverted(options, key)
            description = (f"**{channel.name}**: {'invertiert' if old else 'nicht invertiert'} → "
                           f"**{'invertiert' if new else 'nicht invertiert'}** "
                           f"({'Standard' if preview['mode']=='inherit' else 'Einzelregel'}).")
        description += ('\n\n**COMEXIO selbst bleibt unverändert.** Die Umrechnung gilt '
                        'für HA-Anzeige und Fahrbefehle (0 % in Home Assistant = geschlossen). '
                        'Bitte die reale Fahrtrichtung nach dem Speichern zuerst kontrolliert prüfen.')
        if user_input is not None:
            if user_input.get('confirm') is not True:
                return self.async_show_form(step_id='cover_review',
                    data_schema=vol.Schema({vol.Required('confirm', default=False): bool}),
                    description_placeholders={'summary': description},
                    errors={'base': 'confirmation_required'})
            self._save_options(options)
            return self.async_abort(reason='direction_saved')
        return self.async_show_form(step_id='cover_review',
            data_schema=vol.Schema({vol.Required('confirm', default=False): bool}),
            description_placeholders={'summary': description})

    async def async_step_classify_select(self, user_input=None):
        from homeassistant.helpers.selector import SelectSelector, SelectSelectorConfig
        from .preferences import is_classifiable
        runtime = self._runtime()
        if runtime is None:
            return self.async_abort(reason='not_loaded')
        pinned_motors = {k for k, kind in self.config_entry.options.get('known_channel_kinds', {}).items()
                         if kind == 'motor'}
        eligible = [c for c in runtime.raw_channels.values()
                    if is_classifiable(c) and c.key not in pinned_motors]
        if not eligible:
            return self.async_abort(reason='no_sources')
        choices = [{'value': c.key, 'label': f'{c.name} [{c.extension}/{c.identifier}]'}
                   for c in sorted(eligible, key=lambda x: x.name.casefold())]
        schema = vol.Schema({
            vol.Required('source'): SelectSelector(SelectSelectorConfig(options=choices)),
            vol.Required('kind', default='auto'): vol.In({
                'auto': 'Automatisch aus COMEXIO neu erkennen',
                'light': 'Licht (schaltbar)',
                'switch': 'Schalter (schaltbar)',
                'relay': 'Statussensor (nur lesen)',
            }),
        })
        errors = {}
        if user_input is not None:
            if user_input['source'] not in {c.key for c in eligible}:
                errors['base'] = 'invalid_selection'
            else:
                self._class_preview = dict(source=user_input['source'], kind=user_input['kind'])
                self._class_preview['fingerprint'] = self._local_fingerprint(
                    'classification', {k:v for k,v in self._class_preview.items() if k != 'fingerprint'})
                return await self.async_step_classify_review()
        return self.async_show_form(step_id='classify_select', data_schema=schema, errors=errors)

    async def async_step_classify_review(self, user_input=None):
        """Use the same read/registry preflight as COMEXIO sync, never pre-delete."""
        from .preferences import CHANNEL_KINDS, KNOWN_KINDS, apply_classifications
        from .entity_sync import entity_domain
        from .admin_api import AdminError
        preview = self._class_preview
        runtime = self._runtime()
        if preview is None or runtime is None:
            return self.async_abort(reason='not_loaded')
        payload = {'source': preview['source'], 'kind': preview['kind']}
        if preview['fingerprint'] != self._local_fingerprint('classification', payload):
            return self.async_abort(reason='settings_changed')
        key = preview['source']
        current = runtime.channels.get(key)
        raw = runtime.raw_channels.get(key)
        if current is None or raw is None:
            return self.async_abort(reason='settings_changed')
        options = dict(self.config_entry.options)
        overrides = dict(options.get(CHANNEL_KINDS, {}))
        if preview['kind'] == 'auto':
            overrides.pop(key, None)
            known = dict(options.get(KNOWN_KINDS, {}))
            known.pop(key, None)
            options[KNOWN_KINDS] = known
        else:
            overrides[key] = preview['kind']
        options[CHANNEL_KINDS] = overrides
        proposed = apply_classifications({key: raw}, options)[key]
        old_domain, new_domain = entity_domain(current.kind), entity_domain(proposed.kind)
        summary = (f'**{current.name}** (`{key}`): **{old_domain or current.kind} → '
                   f'{new_domain or proposed.kind}**. '
                   'COMEXIO selbst wird nicht verändert.')
        if proposed.kind in ('light', 'switch'):
            summary += ('\n\n**Schaltausgang:** Home Assistant kann den physischen '
                        'Ausgang direkt ansteuern. Nur bewusst bestätigen.')
        if old_domain != new_domain:
            summary += ('\n\n**Domänenwechsel:** Die bisherige Entitäts-ID kann '
                        'nicht erhalten bleiben. Automationen und Dashboards '
                        'mit dieser ID benötigen gegebenenfalls Anpassungen.')
        if options == dict(self.config_entry.options):
            return self.async_abort(reason='no_changes')
        try:
            plan = await runtime.preview_manual_classification(options, key) if user_input is None else None
        except (AdminError, ValueError):
            return self.async_abort(reason='cannot_connect')
        if plan is not None:
            if plan['blockers']:
                return self.async_abort(reason='classification_conflict')
            self._class_sync_fingerprint = plan['fingerprint']
            self._class_has_deletions = bool(plan['registry_removals'])
            for item in plan['registry_removals']:
                summary += (f"\n\n**Registry-Entfernung:** `{item['entity_id']}` "
                            f"({item['reason']})")
        fields = {vol.Required('confirm', default=False): bool}
        if getattr(self, '_class_has_deletions', False):
            fields[vol.Required('confirm_removals', default=False)] = bool
        if user_input is not None:
            if not getattr(self, '_class_sync_fingerprint', None):
                return self.async_abort(reason='settings_changed')
            if not user_input.get('confirm') or (self._class_has_deletions
                                                and not user_input.get('confirm_removals')):
                return self.async_show_form(step_id='classify_review',
                    data_schema=vol.Schema(fields),
                    description_placeholders={'summary': summary},
                    errors={'base': 'confirmation_required'})
            try:
                await runtime.apply_manual_classification(options,
                    self._class_sync_fingerprint, key)
            except (AdminError, ValueError):
                return self.async_abort(reason='settings_changed')
            return self.async_abort(reason='classification_saved')
        return self.async_show_form(step_id='classify_review',
            data_schema=vol.Schema(fields),
            description_placeholders={'summary': summary})

    async def async_step_sync_preview(self, user_input=None):
        """Preview a complete COMEXIO read with exact owned HA registry entries."""
        from .admin_api import AdminError
        runtime = self._runtime()
        if runtime is None:
            return self.async_abort(reason='not_loaded')
        try:
            self._sync_preview = await runtime.preview_sync()
        except (AdminError, ValueError) as exc:
            _LOGGER.warning('COMEXIO-Synchronisierung: vollständiger Lesevorgang abgebrochen: %s',
                            _safe_admin_reason(AdminError(str(exc))))
            return self.async_abort(reason='sync_failed',
                description_placeholders={'reason': _safe_admin_reason(AdminError(str(exc)))})
        return await self.async_step_sync_review()

    async def async_step_sync_review(self, user_input=None):
        from .admin_api import AdminError
        runtime, report = self._runtime(), self._sync_preview
        if runtime is None or report is None:
            return self.async_abort(reason='not_loaded')
        labels = {'added': 'Neu', 'removed': 'Nicht mehr vorhanden',
                  'renamed': 'Umbenannt', 'type_changed': 'Typwechsel',
                  'updated': 'Metadaten geändert'}
        lines = [f"**{labels[row['action']]}:** {row['old_name'] or '–'} → "
                 f"{row['new_name'] or '–'} (`{row['key']}`) "
                 f"[{row['old_kind'] or '–'} → {row['new_kind'] or '–'}]"
                 for row in report['changes']]
        for item in report['registry_removals']:
            consequence = (f" → `{item['replacement_domain']}` (neue Entity-ID)"
                           if item['replacement_domain'] else ' (kein Ersatz)')
            lines.append(f"**HA-Registry entfernen:** `{item['entity_id']}` "
                         f"[{item['source']}] – {item['reason']}{consequence}")
            if item['manual_follow_up']:
                lines.append('**Hinweis:** Versteckt-/Deaktiviert-Einstellungen müssen nach dem '
                             'Domänenwechsel gegebenenfalls erneut gesetzt werden.')
            if item['manual_settings']:
                lines.append('Benutzername/Bereich werden beim Plattformwechsel soweit '
                             'technisch möglich auf die neue Entität übertragen.')
            if item['replacement_domain']:
                lines.append('**Achtung:** Automationen und Dashboards mit der alten '
                             'Entity-ID werden nicht automatisch umgeschrieben.')
        lines.extend('**Sperre:** ' + item for item in report['blockers'])
        if not lines:
            lines.append('Keine Änderungen oder veralteten eigenen HA-Entitäten vorhanden.')
        lines.append('**Nur Home Assistant:** COMEXIO-Web-IO, Logikpläne, '
                     'Push-Verbindungen und fremde Entitäten bleiben unverändert. '
                     'Vor dem Übernehmen werden Konfiguration und Registry erneut geprüft.')
        can_apply = report['requires_confirmation'] and not report['blockers']
        fields = {vol.Required('confirm', default=False): bool} if can_apply else {}
        if can_apply and report['registry_removals']:
            fields[vol.Required('confirm_removals', default=False)] = bool
        schema = vol.Schema(fields)
        if user_input is not None:
            if not can_apply:
                return self.async_abort(reason='no_changes' if not report['blockers']
                                        else 'sync_changed')
            if not user_input.get('confirm') or (
                    report['registry_removals'] and not user_input.get('confirm_removals')):
                return self.async_show_form(step_id='sync_review', data_schema=schema,
                    description_placeholders={'summary': '\n\n'.join(lines)},
                    errors={'base': 'confirmation_required'})
            try:
                await runtime.apply_sync(report['fingerprint'])
            except (AdminError, ValueError) as exc:
                _LOGGER.warning('COMEXIO-Synchronisierung sicher abgebrochen: %s',
                                _safe_admin_reason(AdminError(str(exc))))
                return self.async_abort(reason='sync_failed',
                    description_placeholders={'reason': _safe_admin_reason(AdminError(str(exc)))})
            return self.async_abort(reason='sync_completed')
        return self.async_show_form(step_id='sync_review', data_schema=schema,
            description_placeholders={'summary': '\n\n'.join(lines)})

