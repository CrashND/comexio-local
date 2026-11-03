"""Opt-in controllable COMEXIO light entities."""

from homeassistant.components.light import ColorMode, LightEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN
from .entity import ComexioChannelEntity
from .tcp_client import ComexioError


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback):
    runtime = hass.data[DOMAIN][entry.entry_id]
    if runtime["allow_writes"]:
        async_add_entities(ComexioLight(runtime["coordinator"], channel) for channel in runtime["coordinator"].channels)


class ComexioLight(ComexioChannelEntity, LightEntity):
    """Only confirm state through a fresh GET, never an optimistic SET."""

    _attr_supported_color_modes = {ColorMode.ONOFF}

    @property
    def color_mode(self):
        return ColorMode.ONOFF

    @property
    def is_on(self) -> bool | None:
        return (self.coordinator.data or {}).get(self.channel.id)

    async def async_turn_on(self, **kwargs) -> None:
        await self._write(True)

    async def async_turn_off(self, **kwargs) -> None:
        await self._write(False)

    async def _write(self, value: bool) -> None:
        try:
            await self.coordinator.async_write_output(self.channel, value)
        except ComexioError as err:
            raise HomeAssistantError(f"COMEXIO {self.channel.name}: {err}") from err
