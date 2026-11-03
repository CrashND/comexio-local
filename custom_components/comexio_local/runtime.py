"""No scheduler: COMEXIO pushes actual changes into Home Assistant."""
from __future__ import annotations
import asyncio
from datetime import datetime, timezone
import logging
from homeassistant.helpers.dispatcher import async_dispatcher_send
from .admin_api import ComexioAdmin
from .discovery import Channel, discover, event_address
from .tcp_client import ComexioTCPClient, ComexioError

_LOGGER=logging.getLogger(__name__)

class Runtime:
    def __init__(self, hass, entry, admin:ComexioAdmin, tcp:ComexioTCPClient):
        self.hass=hass; self.entry=entry; self.admin=admin; self.tcp=tcp
        self.channels:dict[str,Channel]={}
        self.values:dict[str,bool|float|None]={}
        self.last_event:datetime|None=None
        self.events=0
        self.rejected_events=0
        self.last_rejection: str | None = None
        self.push_diagnostics: dict | None = None
        self.errors=0
        self._lock=asyncio.Lock()
        self.discovery_signal=f"comexio_local_discovery_{entry.entry_id}"
        self.state_signal=f"comexio_local_state_{entry.entry_id}"
        self._initialised=False

    async def refresh_discovery(self) -> tuple[int,int]:
        """One-off live discovery, with an optional single initial snapshot."""
        async with self._lock:
            config=await self.admin.read_config()
            plans=await self.admin.read_plans(config)
            new_channels=discover(config,plans)
            added=set(new_channels)-set(self.channels)
            removed=set(self.channels)-set(new_channels)
            self.channels=new_channels
            for key in removed:
                self.values.pop(key,None)
            for key in added:
                self.values.setdefault(key,None)
            # A rescan is explicit and may seed live states once. No background timer.
            await self.snapshot()
            self._initialised=True
            async_dispatcher_send(self.hass,self.discovery_signal)
            async_dispatcher_send(self.hass,self.state_signal)
            _LOGGER.info("COMEXIO discovered %d signals (lights=%d, covers=%d, new=%d)",
                len(self.channels),sum(c.kind=='light' for c in self.channels.values()),
                sum(c.kind=='cover' for c in self.channels.values()),len(added))
            return len(added),len(removed)

    async def snapshot(self):
        sources=[c for c in self.channels.values() if c.kind in ("light","relay","cover")]
        for start in range(0,len(sources),30):
            batch=sources[start:start+30]
            try:
                data=await self.tcp.read_sources(batch)
                self.values.update(data)
            except ComexioError:
                self.errors+=1
                _LOGGER.warning("COMEXIO initial GET failed for batch %d; no repeated probing",start//30+1)

    async def diagnose_push(self) -> dict:
        """Read-only on-demand Web-IO topology and callback configuration audit."""
        from .constants import CONF_PUSH_BASE, CONF_WEBHOOK_ID
        from .push_audit import audit_push
        path = f"/api/webhook/{self.entry.data[CONF_WEBHOOK_ID]}"
        report = await audit_push(self.admin, self.channels, self.entry.entry_id,
                                  path, self.entry.data[CONF_PUSH_BASE])
        self.push_diagnostics = report.as_dict()
        async_dispatcher_send(self.hass, self.state_signal)
        return self.push_diagnostics

    def apply_event(self, payload:dict) -> bool:
        """Accept only a known source and a valid value. No GET triggered by the event."""
        address=event_address(payload)
        if address is None or address not in self.channels:
            self.note_rejection("Unbekannte COMEXIO-Quelladresse")
            return False
        channel=self.channels[address]
        if not channel.is_push_source:
            self.note_rejection("Quelle ist kein Push-Ziel")
            return False
        raw=payload.get("value")
        try:
            if channel.analog:
                if isinstance(raw,bool) or raw is None:
                    self.note_rejection("Ungueltiger Analogwert")
                    return False
                value=float(raw)
                if not (0<=value<=100):
                    self.note_rejection("Analogwert ausserhalb 0 bis 100")
                    return False
            else:
                if raw not in (0,1,"0","1",False,True):
                    self.note_rejection("Ungueltiger Digitalwert")
                    return False
                value=bool(int(raw))
        except (ValueError,TypeError):
            self.note_rejection("Ereigniswert konnte nicht gelesen werden")
            return False
        self.values[address]=value
        self.last_event=datetime.now(timezone.utc)
        self.events+=1
        async_dispatcher_send(self.hass,self.state_signal)
        return True

    def note_rejection(self, reason: str) -> None:
        # Never log the request body or the secret webhook path.
        self.rejected_events += 1
        self.last_rejection = reason
        async_dispatcher_send(self.hass, self.state_signal)
        _LOGGER.warning("COMEXIO Push Ereignis abgelehnt: %s", reason)

    async def change_light(self, channel:Channel, value:bool) -> None:
        """Never optimistic. Only a bounded one-shot GET after TCP SET."""
        await self.tcp.set_channel(channel,value)
        result=await self.tcp.read_sources([channel])
        if result.get(channel.key) is None:
            raise ComexioError("COMEXIO output state not confirmed after SET")
        self.values.update(result)
        async_dispatcher_send(self.hass,self.state_signal)

    async def change_cover(self, channel:Channel, pos:float) -> None:
        if channel.target_marker_id is None: raise ComexioError("No target marker")
        await self.tcp.write_marker(channel.target_marker_id, pos)
        # Position change is confirmed only when COMEXIO sends the *actual* marker event.

    def value(self, key:str):
        return self.values.get(key)
