"""COMEXIO Local UI setup: transport and admin access only, never fixed channels."""
from __future__ import annotations
import secrets
import hashlib
import json

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
        self._sync_preview = None
        self._rebuild_preview = None
        self._rebuild_observer = None

    def _runtime(self):
        return self.hass.data.get(DOMAIN, {}).get(self.config_entry.entry_id)

    async def async_step_init(self, user_input=None):
        if self._runtime() is None:
            return self.async_abort(reason='not_loaded')
        return self.async_show_menu(step_id='init', menu_options=['push_management', 'area_auto', 'area_manual', 'cover_global', 'cover_single', 'classify_select', 'sync_preview', 'names_preview'])

    async def async_step_push_management(self, user_input=None):
        """One entry point for inspection, repair and long-running rebuild jobs."""
        runtime = self._runtime()
        if runtime is None:
            return self.async_abort(reason='not_loaded')
        options = ['repair_select', 'rebuild_preview', 'rebuild_status']
        if runtime.push_rebuild.status()['status'] not in ('not_started', 'completed', 'cancelled'):
            options = ['rebuild_status', 'repair_select', 'rebuild_preview']
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
        if user_input is not None:
            if user_input.get('backup_confirmed') is not True:
                return self.async_show_form(
                    step_id='rebuild_review',
                    data_schema=vol.Schema({vol.Required('backup_confirmed', default=False): bool}),
                    description_placeholders={'summary': summary},
                    errors={'base': 'backup_required'})
            try:
                status = await runtime.push_rebuild.start(preview['fingerprint'], True)
            except AdminError:
                return self.async_abort(reason='rebuild_failed')
            if status['status'] == 'awaiting_cleanup':
                return self.async_abort(reason='rebuild_cleanup_required')
            return await self.async_step_rebuild_progress()
        return self.async_show_form(
            step_id='rebuild_review',
            data_schema=vol.Schema({vol.Required('backup_confirmed', default=False): bool}),
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
        }
        phase_names = {
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
                await runtime.repair_push(self._selected, self._mode, preview['fingerprint'], True)
            except AdminError as err:
                import logging
                logging.getLogger(__name__).warning('Push-Reparatur abgebrochen: %s', err)
                return self.async_abort(reason='repair_failed')
            return self.async_abort(reason='repair_completed')
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
        """Read-only name migration audit; never rename an existing COMEXIO object."""
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
        summary = [f"**{x['type']}**: `{x['old']}` -> `{x['new']}`"
                   for x in result['changes']]
        summary.extend(f"**Nicht eindeutig:** {x}" for x in result['blockers'])
        if not summary:
            summary = ['Keine Umbenennungen notwendig.']
        summary.append('**Keine Aenderung in COMEXIO:** Der Rename-Schreibzugriff '
                       'ist fuer Firmware 11.1.5 noch nicht verifiziert.')
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
        from .preferences import CHANNEL_KINDS, apply_classifications
        from homeassistant.helpers import entity_registry as er
        preview = self._class_preview
        runtime = self._runtime()
        if preview is None or runtime is None:
            return self.async_abort(reason='not_loaded')
        payload = {k:v for k,v in preview.items() if k != 'fingerprint'}
        if preview['fingerprint'] != self._local_fingerprint('classification', payload):
            return self.async_abort(reason='settings_changed')
        key = preview['source']
        current = runtime.channels.get(key)
        raw = runtime.raw_channels.get(key)
        if not current or not raw:
            return self.async_abort(reason='settings_changed')
        options = dict(self.config_entry.options)
        overrides = dict(options.get(CHANNEL_KINDS, {}))
        if preview['kind'] == 'auto':
            overrides.pop(key, None)
            # A consciously selected automatic re-detection also unpins the old
            # inferred type; the subsequent reload pins the new raw type.
            previous = dict(options.get('known_channel_kinds', {}))
            previous.pop(key, None)
            options['known_channel_kinds'] = previous
        else:
            overrides[key] = preview['kind']
        options[CHANNEL_KINDS] = overrides
        new = apply_classifications({key: raw}, options)[key]
        registry = er.async_get(self.hass)
        unique_id = f"{self.config_entry.unique_id or self.config_entry.entry_id}:{key}"
        old_id = registry.async_get_entity_id(current.kind if current.kind != 'relay' else 'binary_sensor',
                                              DOMAIN, unique_id)
        domain_new = 'binary_sensor' if new.kind == 'relay' else new.kind
        domain_old = 'binary_sensor' if current.kind == 'relay' else current.kind
        if domain_new != domain_old and registry.async_get_entity_id(domain_new, DOMAIN, unique_id):
            return self.async_abort(reason='classification_conflict')
        message = (f"**{current.name}** ({key}): "
                   f"**{domain_old} → {domain_new}**. "
                   'Manuelle Auswahl wird dauerhaft in Home Assistant gespeichert; '
                   'COMEXIO-Konfiguration wird nicht verändert.')
        if domain_old != domain_new:
            message += (f'\n\n**Achtung:** Bestehende Entität `{old_id or domain_old + ".…"}` '
                        f'wird durch eine neue `{domain_new}`-Entität ersetzt. '
                        'Automationen und Dashboards mit der alten Entity-ID müssen ggf. angepasst werden. '
                        'Eine Entitäts-ID kann nicht über verschiedene HA-Domänen erhalten bleiben.')
        if new.kind in ('light','switch'):
            message += ('\n\n**Schaltausgang:** Das Schalten schreibt direkt auf den COMEXIO-Relaisausgang. '
                        'Nur freigeben, wenn das zur bestehenden COMEXIO-Logik passt.')
        if user_input is not None:
            if user_input.get('confirm') is not True:
                return self.async_show_form(step_id='classify_review',
                    data_schema=vol.Schema({vol.Required('confirm', default=False): bool}),
                    description_placeholders={'summary': message},
                    errors={'base': 'confirmation_required'})
            if options == dict(self.config_entry.options):
                return self.async_abort(reason='no_changes')
            if domain_old != domain_new and old_id is not None:
                existing = registry.async_get(old_id)
                if existing is None or existing.config_entry_id != self.config_entry.entry_id:
                    return self.async_abort(reason='settings_changed')
                # Preserve explicit HA user area and custom display name.
                remembered = dict(options.get('classification_areas', {}))
                remembered[key] = {'area_id': existing.area_id, 'name': existing.name}
                options['classification_areas'] = remembered
                registry.async_remove(old_id)
            self._save_options(options, reload=True)
            return self.async_abort(reason='classification_saved')
        return self.async_show_form(step_id='classify_review',
            data_schema=vol.Schema({vol.Required('confirm', default=False): bool}),
            description_placeholders={'summary': message})

    async def async_step_sync_preview(self, user_input=None):
        """COMEXIO GET/read only, compare with Home Assistant catalog."""
        from .admin_api import AdminError
        runtime = self._runtime()
        if runtime is None:
            return self.async_abort(reason='not_loaded')
        try:
            self._sync_preview = await runtime.preview_sync()
        except AdminError:
            return self.async_abort(reason='cannot_connect')
        return await self.async_step_sync_review()

    async def async_step_sync_review(self, user_input=None):
        from .admin_api import AdminError
        runtime = self._runtime()
        report = self._sync_preview
        if runtime is None or report is None:
            return self.async_abort(reason='not_loaded')
        labels = {'added':'Neu', 'removed':'Entfernt', 'renamed':'Umbenannt',
                  'type_changed':'Typ geändert'}
        lines = [f"**{labels[row['action']]}:** {row['old_name'] or '–'} → "
                 f"{row['new_name'] or '–'} (`{row['key']}`)"
                 for row in report['changes']]
        if not lines:
            lines = ['Keine Unterschiede gefunden.']
        lines.append('Es werden nur COMEXIO-Konfigurationen gelesen und Home-Assistant-Entitäten '
                     'aktualisiert. Bestehende IDs und manuelle Klassifizierungen bleiben erhalten. '
                     'Keine COMEXIO-Schreibzugriffe.')
        if report['requires_manual_classification']:
            lines.append('**Blockiert:** Ein Entitätstyp hat sich geändert. '
                         'Bitte zuerst die manuelle Geräteklassifizierung verwenden; '
                         'es erfolgt kein automatischer Typwechsel.')
        if user_input is not None:
            if not report['changes']:
                return self.async_abort(reason='no_changes')
            if report['requires_manual_classification']:
                return self.async_abort(reason='sync_type_change')
            if user_input.get('confirm') is not True:
                return self.async_show_form(step_id='sync_review',
                    data_schema=vol.Schema({vol.Required('confirm', default=False): bool}),
                    description_placeholders={'summary': '\n\n'.join(lines)},
                    errors={'base': 'confirmation_required'})
            try:
                await runtime.apply_sync(report['fingerprint'])
            except (AdminError, ValueError):
                return self.async_abort(reason='sync_changed')
            return self.async_abort(reason='sync_completed')
        can_apply = bool(report['changes']) and not report['requires_manual_classification']
        return self.async_show_form(step_id='sync_review',
            data_schema=(vol.Schema({vol.Required('confirm', default=False): bool})
                         if can_apply else vol.Schema({})),
            description_placeholders={'summary': '\n\n'.join(lines)})

