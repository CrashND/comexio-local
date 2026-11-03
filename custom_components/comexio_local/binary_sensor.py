"""Default read-only relay states; safe when RS logic is not mapped."""

from homeassistant.components.binary_sensor import BinarySensorDeviceClass, BinarySensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN
from .entity import ComexioChannelEntity


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback):
    runtime = hass.data[DOMAIN][entry.entry_id]
    if not runtime["allow_writes"]:
        async_add_entities(ComexioLightState(runtime["coordinator"], channel) for channel in runtime["coordinator"].channels)


class ComexioLightState(ComexioChannelEntity, BinarySensorEntity):
    _attr_device_class = BinarySensorDeviceClass.LIGHT

    @property
    def is_on(self):
        return (self.coordinator.data or {}).get(self.channel.id)
