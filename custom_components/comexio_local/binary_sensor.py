"""Other relay statuses are visible read-only, not silently reclassified as lights."""
from homeassistant.components.binary_sensor import BinarySensorDeviceClass, BinarySensorEntity
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
    """Physical or EnOcean COMEXIO input, updated by push and one-time GET.

    Both momentary buttons and latching switches are binary sensors. Their
    interpretation is available as an attribute and in comexio_local_input.
    """

    @property
    def is_on(self):
        value = self.runtime.value(self.channel.key)
        return bool(value) if value is not None else None

    @property
    def device_class(self):
        if self.channel.is_enocean and self.channel.enocean_signal == 'PIRS':
            return (BinarySensorDeviceClass.OCCUPANCY if self.channel.analog
                    else BinarySensorDeviceClass.MOTION)
        # CO polarity (0/1 vs open/closed) is not yet validated; avoid an
        # incorrect door-open icon/state until confirmed on real hardware.
        return None

    @property
    def extra_state_attributes(self):
        attributes = {**super().extra_state_attributes, 'eingangsart': self.channel.input_mode}
        if self.channel.is_enocean:
            attributes['enocean_teilnehmerplatz'] = f'EI{self.channel.enocean_slot}'
            attributes['enocean_signal'] = self.channel.enocean_signal
            if self.channel.enocean_signal == 'CO':
                attributes['kontakt_polaritaet'] = 'nicht verifiziert'
        return attributes
