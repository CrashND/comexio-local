"""Explicitly classified, directly switchable COMEXIO relay outputs."""
from homeassistant.components.switch import SwitchEntity
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.dispatcher import async_dispatcher_connect

from .entities import BaseChannel
from .tcp_client import ComexioError


async def async_setup_entry(hass, entry, async_add_entities):
    runtime = hass.data['comexio_local'][entry.entry_id]
    known = set()

    def update():
        new = [c for c in runtime.channels.values() if c.kind == 'switch' and c.key not in known]
        if new:
            known.update(c.key for c in new)
            async_add_entities([ComexioSwitch(runtime, c) for c in new])

    update()
    entry.async_on_unload(async_dispatcher_connect(hass, runtime.discovery_signal, update))


class ComexioSwitch(BaseChannel, SwitchEntity):
    @property
    def is_on(self):
        return self.runtime.value(self.channel.key)

    async def async_turn_on(self, **kwargs):
        await self._set(True)

    async def async_turn_off(self, **kwargs):
        await self._set(False)

    async def _set(self, value):
        try:
            await self.runtime.change_light(self.channel, value)
        except ComexioError as exc:
            raise HomeAssistantError(f'COMEXIO switch operation failed: {exc}') from exc
