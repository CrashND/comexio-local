"""Single-screen initial setup and reconfigurable options."""

from __future__ import annotations

import logging

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.helpers import config_validation as cv

from .catalog import CHANNEL_BY_ID, CHANNELS, DEFAULT_CHANNEL_IDS
from .const import (
    CONF_ALLOW_WRITES,
    CONF_CHANNELS,
    CONF_HOST,
    CONF_PORT,
    CONF_SCAN_INTERVAL,
    DEFAULT_ALLOW_WRITES,
    DEFAULT_HOST,
    DEFAULT_PORT,
    DEFAULT_SCAN_INTERVAL,
    DOMAIN,
)
from .tcp_client import ComexioError, ComexioTCPClient

_LOGGER = logging.getLogger(__name__)


def _schema(values: dict, include_host: bool) -> vol.Schema:
    schema = {}
    if include_host:
        schema[vol.Required(CONF_HOST, default=values.get(CONF_HOST, DEFAULT_HOST))] = cv.string
        schema[vol.Required(CONF_PORT, default=values.get(CONF_PORT, DEFAULT_PORT))] = vol.All(
            vol.Coerce(int), vol.Range(min=1, max=65535)
        )
    schema[vol.Required(CONF_SCAN_INTERVAL, default=values.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL))] = vol.All(
        vol.Coerce(int), vol.Range(min=5, max=300)
    )
    schema[vol.Required(CONF_CHANNELS, default=values.get(CONF_CHANNELS, DEFAULT_CHANNEL_IDS))] = cv.multi_select(
        {item.id: item.name for item in CHANNELS}
    )
    schema[vol.Required(CONF_ALLOW_WRITES, default=values.get(CONF_ALLOW_WRITES, DEFAULT_ALLOW_WRITES))] = cv.boolean
    return vol.Schema(schema)


async def _validate(host: str, port: int, selection: list[str]) -> None:
    channels = [CHANNEL_BY_ID[key] for key in selection if key in CHANNEL_BY_ID]
    if not channels:
        raise ValueError("No valid channels selected")
    values = await ComexioTCPClient(host, port).read_channels(channels)
    if not any(value is not None for value in values.values()):
        raise ComexioError("No readable channels; check names and API")


class ComexioLocalConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    VERSION = 1

    async def async_step_user(self, user_input=None):
        errors = {}
        if user_input is not None:
            host = user_input[CONF_HOST].strip()
            port = int(user_input[CONF_PORT])
            selection = user_input[CONF_CHANNELS]
            if not selection:
                errors["base"] = "no_channels"
            else:
                await self.async_set_unique_id(f"{host}:{port}")
                self._abort_if_unique_id_configured()
                try:
                    await _validate(host, port, selection)
                except (ComexioError, OSError, TimeoutError) as exc:
                    _LOGGER.warning("COMEXIO cannot be read during setup: %s", exc)
                    errors["base"] = "cannot_connect"
                except ValueError:
                    errors["base"] = "no_channels"
                else:
                    return self.async_create_entry(title=f"COMEXIO {host}", data={**user_input, CONF_HOST: host})
        return self.async_show_form(step_id="user", data_schema=_schema(user_input or {}, include_host=True), errors=errors)

    @staticmethod
    def async_get_options_flow(config_entry):
        return ComexioLocalOptionsFlow()


class ComexioLocalOptionsFlow(config_entries.OptionsFlow):
    async def async_step_init(self, user_input=None):
        errors = {}
        current = {**self.config_entry.data, **self.config_entry.options}
        if user_input is not None:
            if not user_input[CONF_CHANNELS]:
                errors["base"] = "no_channels"
            else:
                return self.async_create_entry(title="", data=user_input)
        return self.async_show_form(step_id="init", data_schema=_schema(user_input or current, include_host=False), errors=errors)
