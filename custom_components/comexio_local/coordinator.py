"""Bounded poll coordinator for COMEXIO Local."""

from __future__ import annotations

from datetime import timedelta
import logging

from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .catalog import Channel
from .tcp_client import ComexioError, ComexioTCPClient

_LOGGER = logging.getLogger(__name__)


class ComexioCoordinator(DataUpdateCoordinator[dict[str, bool | None]]):
    """One batched read per interval, with no background repair operations."""

    def __init__(
        self,
        hass: HomeAssistant,
        client: ComexioTCPClient,
        channels: tuple[Channel, ...],
        interval_seconds: int,
    ) -> None:
        super().__init__(
            hass,
            _LOGGER,
            name="COMEXIO Local lights",
            update_interval=timedelta(seconds=interval_seconds),
        )
        self.client = client
        self.channels = channels

    async def _async_update_data(self) -> dict[str, bool | None]:
        try:
            result = await self.client.read_channels(self.channels)
        except ComexioError as err:
            raise UpdateFailed(str(err)) from err
        if not any(value is not None for value in result.values()):
            raise UpdateFailed("No usable values in the COMEXIO GET response")
        return result

    async def async_write_output(self, channel: Channel, state: bool) -> None:
        """Write a single channel, then get its real state before updating HA."""
        await self.client.set_channel(channel, state)
        observed = await self.client.read_channels((channel,))
        actual = observed.get(channel.id)
        if actual is None:
            raise ComexioError("SET was sent but output confirmation GET failed")
        self.async_set_updated_data({**(self.data or {}), channel.id: actual})
