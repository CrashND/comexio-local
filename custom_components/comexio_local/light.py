"""Light output entities; relay identity always determined at discovery."""
from homeassistant.components.light import ColorMode, LightEntity
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from .entities import BaseChannel
from .tcp_client import ComexioError

async def async_setup_entry(hass, entry, async_add_entities):
    runtime=hass.data["comexio_local"][entry.entry_id]
    known=set()
    def update():
        new=[c for c in runtime.channels.values() if c.kind=="light" and c.key not in known]
        if new:
            known.update(c.key for c in new)
            async_add_entities([ComexioLight(runtime,c) for c in new])
    update()
    entry.async_on_unload(async_dispatcher_connect(hass,runtime.discovery_signal,update))

class ComexioLight(BaseChannel,LightEntity):
    _attr_supported_color_modes={ColorMode.ONOFF}
    _attr_color_mode=ColorMode.ONOFF

    @property
    def is_on(self):
        return self.runtime.value(self.channel.key)

    async def async_turn_on(self,**kwargs):
        await self._set(True)

    async def async_turn_off(self,**kwargs):
        await self._set(False)

    async def _set(self, value):
        try:
            await self.runtime.change_light(self.channel,value)
        except ComexioError as exc:
            raise HomeAssistantError(f"COMEXIO light operation failed: {exc}") from exc
