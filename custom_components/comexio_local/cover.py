"""Real cover entities based on Soll-/Ist markers, never raw motor relays."""
from homeassistant.components.cover import CoverDeviceClass, CoverEntity, CoverEntityFeature
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from .entities import BaseChannel
from .tcp_client import ComexioError
from .preferences import cover_is_inverted, ha_cover_position, comexio_cover_target

async def async_setup_entry(hass,entry,async_add_entities):
    runtime=hass.data["comexio_local"][entry.entry_id]
    known=set()
    def update():
        new=[c for c in runtime.channels.values() if c.kind=="cover" and c.key not in known]
        if new:
            known.update(c.key for c in new)
            async_add_entities([ComexioCover(runtime,c) for c in new])
    update()
    entry.async_on_unload(async_dispatcher_connect(hass,runtime.discovery_signal,update))

class ComexioCover(BaseChannel,CoverEntity):
    _attr_supported_features=CoverEntityFeature.OPEN|CoverEntityFeature.CLOSE|CoverEntityFeature.SET_POSITION

    @property
    def device_class(self):
        return CoverDeviceClass.AWNING if "markis" in self.channel.name.casefold() else CoverDeviceClass.SHUTTER

    @property
    def current_cover_position(self):
        value=self.runtime.value(self.channel.key)
        return ha_cover_position(value, cover_is_inverted(self.runtime.entry.options, self.channel.key))

    @property
    def is_closed(self):
        position=self.current_cover_position
        return position==0 if position is not None else None

    async def async_open_cover(self,**kwargs):
        await self._set(100)
    async def async_close_cover(self,**kwargs):
        await self._set(0)
    async def async_set_cover_position(self,**kwargs):
        await self._set(kwargs['position'])
    async def _set(self,pos):
        try:
            await self.runtime.change_cover(self.channel, comexio_cover_target(
                pos, cover_is_inverted(self.runtime.entry.options, self.channel.key)))
        except ComexioError as exc:
            raise HomeAssistantError(f"COMEXIO cover operation failed: {exc}") from exc
