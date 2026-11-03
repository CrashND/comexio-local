"""Known COMEXIO relay lights from the owner's exported logic plans.

Names on hardware can be historical; IDs are deliberately stable.
This catalog does NOT include Shelly-operated stairwell lights.
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class Channel:
    id: str
    name: str
    extension: str
    io: str


CHANNELS: tuple[Channel, ...] = (
    Channel("living_main", "Wohnzimmer Hauptlicht", "IO-Ext-2", "Q4"),
    Channel("living_led", "Wohnzimmer LED", "IO-Ext-2", "Q5"),
    Channel("living_indirect", "Wohnzimmer indirekt", "IO-Ext-2", "Q6"),
    Channel("dining_main", "Esszimmer Hauptlicht", "IO-Ext-2", "Q7"),
    Channel("dining_indirect", "Esszimmer indirekt", "IO-Ext-2", "Q8"),
    Channel("kitchen", "K\u00fcche Licht", "IO-Ext-2", "Q9"),
    Channel("bedroom", "Schlafzimmer Licht", "IO-Ext-3", "Q7"),
    Channel("child_room", "Kinderzimmer Licht", "IO-Ext-2", "Q3"),
    Channel("guest_room", "G\u00e4stezimmer Licht", "IO-Ext-2", "Q1"),
    Channel("office", "B\u00fcro Licht", "IO-Ext-2", "Q2"),
    Channel("bathroom", "Wannenbad Licht", "IO-Ext-1", "Q7"),
    Channel("shower", "Duschbad Licht", "IO-Ext-1", "Q4"),
    Channel("guest_wc", "G\u00e4ste-WC Licht", "IO-Ext-1", "Q1"),
    Channel("hallway", "Flur Licht", "IO-Server-1", "Q1"),
    Channel("library", "Bibliothek Licht", "IO-Server-1", "Q2"),
    Channel("small_hallway", "Kleiner Flur Licht", "IO-Server-1", "Q3"),
)

CHANNEL_BY_ID = {channel.id: channel for channel in CHANNELS}
DEFAULT_CHANNEL_IDS = [channel.id for channel in CHANNELS]
