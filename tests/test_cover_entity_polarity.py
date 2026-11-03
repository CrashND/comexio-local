"""Confirm real HA-facing cover commands use the inverse mapping both ways."""
from __future__ import annotations
import importlib
import sys
import types
from enum import IntFlag
from types import SimpleNamespace

import pytest


def test_cover_open_close_and_position_are_inverted(monkeypatch):
    # Mock only HA's shell: exercise the production Cover class and preferences.
    class Feature(IntFlag):
        OPEN = 1
        CLOSE = 2
        SET_POSITION = 4
    cover_mod = types.ModuleType('homeassistant.components.cover')
    cover_mod.CoverEntity = type('CoverEntity', (), {})
    cover_mod.CoverDeviceClass = SimpleNamespace(AWNING='awning', SHUTTER='shutter')
    cover_mod.CoverEntityFeature = Feature
    exceptions = types.ModuleType('homeassistant.exceptions')
    exceptions.HomeAssistantError = type('HomeAssistantError', (Exception,), {})
    dispatcher = types.ModuleType('homeassistant.helpers.dispatcher')
    dispatcher.async_dispatcher_connect = lambda *args, **kwargs: None
    entities = types.ModuleType('comexio_local.entities')
    entities.BaseChannel = type('BaseChannel', (), {
        '__init__':lambda self, runtime, channel: (setattr(self,'runtime',runtime),setattr(self,'channel',channel),None)[-1],
    })
    for key, module in [('homeassistant',types.ModuleType('homeassistant')),
                        ('homeassistant.components',types.ModuleType('homeassistant.components')),
                        ('homeassistant.components.cover',cover_mod),
                        ('homeassistant.exceptions',exceptions),
                        ('homeassistant.helpers',types.ModuleType('homeassistant.helpers')),
                        ('homeassistant.helpers.dispatcher',dispatcher),
                        ('comexio_local.entities',entities)]:
        monkeypatch.setitem(sys.modules,key,module)
    monkeypatch.delitem(sys.modules,'comexio_local.cover',raising=False)
    module = importlib.import_module('comexio_local.cover')
    from comexio_local.discovery import Channel
    key = 'cover:M85'
    actual = Channel(kind='cover', name='Rollladen Buero', key=key,
                     marker_id=85,target_marker_id=84,analog=True)
    import asyncio
    writes=[]
    async def change_cover(channel, position):
        writes.append((channel.key, position))
    runtime=SimpleNamespace(values={key:0}, entry=SimpleNamespace(options={'cover_invert_default':True}),
                            value=lambda source: runtime.values[source], change_cover=change_cover)
    cover=module.ComexioCover(runtime, actual)
    assert cover.current_cover_position == 100
    assert cover.is_closed is False
    asyncio.run(cover.async_open_cover())
    asyncio.run(cover.async_close_cover())
    asyncio.run(cover.async_set_cover_position(position=35))
    assert writes == [(key,0),(key,100),(key,65)]
    runtime.values[key]=100
    assert cover.current_cover_position == 0
    assert cover.is_closed is True
    runtime.entry.options={'cover_invert_default':True, 'cover_invert_overrides':{key:False}}
    assert cover.current_cover_position == 100
    asyncio.run(cover.async_open_cover())
    assert writes[-1] == (key,100)
