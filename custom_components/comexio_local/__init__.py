"""COMEXIO Local - dynamic COMEXIO IO discovery and event-driven state updates.

No periodic polling and no COMEXIO configuration writes on startup.  A manual
service explicitly creates namespaced Web-IO push resources after backup.
"""
from __future__ import annotations

import ipaddress
import logging
from urllib.parse import urlsplit

import voluptuous as vol
from homeassistant.components import webhook
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.exceptions import ConfigEntryNotReady, HomeAssistantError
from homeassistant.helpers.aiohttp_client import async_create_clientsession
from aiohttp import CookieJar

from .admin_api import AdminError, ComexioAdmin
from .constants import (
    CONF_ADMIN_PASSWORD, CONF_ADMIN_USER, CONF_HOST, CONF_PUSH_BASE,
    CONF_TCP_PORT, CONF_WEBHOOK_ID, DOMAIN,
)
from .push_setup import configure_push
from .runtime import Runtime
from .tcp_client import ComexioTCPClient

_LOGGER = logging.getLogger(__name__)
PLATFORMS = [Platform.LIGHT, Platform.COVER, Platform.BINARY_SENSOR, Platform.SENSOR]


def _get_runtime(hass: HomeAssistant, call: ServiceCall) -> Runtime:
    entries = hass.data.get(DOMAIN, {})
    selected = call.data.get("entry_id")
    if selected:
        runtime = entries.get(selected)
    elif len(entries) == 1:
        runtime = next(iter(entries.values()))
    else:
        runtime = None
    if runtime is None:
        raise HomeAssistantError("COMEXIO Local entry not found or entry_id is required")
    return runtime


def _valid_private_http_base(url: str) -> bool:
    parsed = urlsplit(url)
    if parsed.scheme != "http" or not parsed.hostname or parsed.port is None:
        return False
    if parsed.username or parsed.password or parsed.path not in ("", "/") or parsed.query or parsed.fragment:
        return False
    try:
        return ipaddress.ip_address(parsed.hostname).is_private
    except ValueError:
        return False


async def async_setup(hass: HomeAssistant, config: dict) -> bool:
    """Expose explicit services, never a periodic background task."""
    hass.data.setdefault(DOMAIN, {})

    async def refresh(call: ServiceCall) -> None:
        runtime = _get_runtime(hass, call)
        try:
            await runtime.refresh_discovery()
        except AdminError as err:
            raise HomeAssistantError(f"COMEXIO discovery failed: {err}") from err

    async def snapshot(call: ServiceCall) -> None:
        runtime = _get_runtime(hass, call)
        await runtime.snapshot()
        from homeassistant.helpers.dispatcher import async_dispatcher_send
        async_dispatcher_send(hass, runtime.state_signal)

    async def install_push(call: ServiceCall) -> None:
        runtime = _get_runtime(hass, call)
        if call.data.get("confirm") is not True:
            raise HomeAssistantError("Requires confirm: true and a current COMEXIO configuration backup")
        push_base = runtime.entry.data[CONF_PUSH_BASE]
        if not _valid_private_http_base(push_base):
            raise HomeAssistantError("Push target must be a private LAN IPv4 URL, e.g. http://192.168.10.6:8123")
        path = f"/api/webhook/{runtime.entry.data[CONF_WEBHOOK_ID]}"
        try:
            results = await configure_push(
                runtime.admin, runtime.channels, runtime.entry.entry_id, path, push_base
            )
            _LOGGER.info("COMEXIO Local push resources applied: %s", results)
        except AdminError as err:
            raise HomeAssistantError(f"COMEXIO push provisioning failed; inspect partial changes: {err}") from err

    optional_entry = vol.Optional("entry_id")
    hass.services.async_register(DOMAIN, "refresh_discovery", refresh, schema=vol.Schema({optional_entry: str}))
    hass.services.async_register(DOMAIN, "snapshot_once", snapshot, schema=vol.Schema({optional_entry: str}))
    hass.services.async_register(
        DOMAIN, "configure_push", install_push,
        schema=vol.Schema({optional_entry: str, vol.Required("confirm"): vol.In([True])}),
    )
    return True


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    session = async_create_clientsession(hass, cookie_jar=CookieJar(unsafe=True))
    admin = ComexioAdmin(
        session, entry.data[CONF_HOST], entry.data[CONF_ADMIN_USER], entry.data[CONF_ADMIN_PASSWORD]
    )
    tcp = ComexioTCPClient(entry.data[CONF_HOST], int(entry.data[CONF_TCP_PORT]))
    runtime = Runtime(hass, entry, admin, tcp)

    try:
        await runtime.refresh_discovery()  # configuration read and one state snapshot only
    except AdminError as err:
        raise ConfigEntryNotReady(f"COMEXIO admin discovery unavailable: {err}") from err

    webhook_id = entry.data[CONF_WEBHOOK_ID]

    async def handle_webhook(hass: HomeAssistant, webhook_id: str, request):
        try:
            if request.content_length is not None and request.content_length > 4096:
                from aiohttp.web import Response
                return Response(status=413)
            payload = await request.json()
            if not isinstance(payload, dict) or not runtime.apply_event(payload):
                from aiohttp.web import Response
                return Response(status=400)
            from aiohttp.web import Response
            return Response(status=204)
        except (ValueError, UnicodeError):
            from aiohttp.web import Response
            return Response(status=400)

    webhook.async_register(hass, DOMAIN, "COMEXIO Local Push", webhook_id, handle_webhook, local_only=True)
    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = runtime
    entry.runtime_data = runtime
    try:
        await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    except Exception:
        webhook.async_unregister(hass, webhook_id)
        hass.data[DOMAIN].pop(entry.entry_id, None)
        raise
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    if await hass.config_entries.async_unload_platforms(entry, PLATFORMS):
        webhook.async_unregister(hass, entry.data[CONF_WEBHOOK_ID])
        hass.data.get(DOMAIN, {}).pop(entry.entry_id, None)
        return True
    return False
