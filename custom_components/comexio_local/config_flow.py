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
