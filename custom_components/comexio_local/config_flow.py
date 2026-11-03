"""COMEXIO Local UI setup: transport and admin access only, never fixed channels."""
from __future__ import annotations
import secrets

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

    def _runtime(self):
        return self.hass.data.get(DOMAIN, {}).get(self.config_entry.entry_id)

    async def async_step_init(self, user_input=None):
        if self._runtime() is None:
            return self.async_abort(reason='not_loaded')
        return self.async_show_menu(step_id='init', menu_options=['repair_select', 'area_auto', 'area_manual', 'names_preview'])

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
