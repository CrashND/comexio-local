"""Other relay statuses are visible read-only, not silently reclassified as lights."""
from homeassistant.components.binary_sensor import BinarySensorEntity
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from .entities import BaseChannel

async def async_setup_entry(hass,entry,async_add_entities):
    runtime=hass.data['comexio_local'][entry.entry_id]
    known=set()
    def update():
        new=[c for c in runtime.channels.values() if c.kind in ('relay', 'binary_input') and c.key not in known]
        if new:
            known.update(c.key for c in new)
            async_add_entities([ComexioRelay(runtime,c) if c.kind == 'relay' else ComexioInput(runtime,c) for c in new])
    update()
    entry.async_on_unload(async_dispatcher_connect(hass,runtime.discovery_signal,update))

class ComexioRelay(BaseChannel,BinarySensorEntity):
    @property
    def is_on(self):
        return self.runtime.value(self.channel.key)


class ComexioInput(BaseChannel, BinarySensorEntity):
    """Physical COMEXIO input state, updated only by Web-IO push and initial GET.

    Both momentary buttons and latching switches are binary sensors. Their
    interpretation is available as an attribute and in comexio_local_input.
    """

    @property
    def is_on(self):
        return self.runtime.value(self.channel.key)

    @property
    def extra_state_attributes(self):
        return {
            'eingangsart': self.channel.input_mode,
            'comexio_anschluss': f'{self.channel.extension}/{self.channel.identifier}',
        }
