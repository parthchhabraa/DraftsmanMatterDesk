from __future__ import annotations

from .config import Config
from .engines.airplay import AirplayEngine
from .engines.brain import BrainEngine
from .engines.devices import DevicesEngine
from .engines.firebase_link import FirebaseLink
from .engines.network import NetworkEngine
from .engines.spotify import SpotifyEngine
from .engines.store import StoreEngine
from .engines.study import StudyEngine
from .engines.system import SystemEngine
from .engines.weather import WeatherEngine
from .hub import Hub

VERSION = "6.0.0"


class Desk:
    """Owns every engine. Engines reach each other through this object."""

    def __init__(self, cfg: Config, hub: Hub | None = None):
        self.cfg = cfg
        self.hub = hub or Hub()
        self.firebase = FirebaseLink(cfg, self.hub)
        self.system = SystemEngine(self)
        self.airplay = AirplayEngine(self)
        self.weather = WeatherEngine(self)
        self.spotify = SpotifyEngine(self)
        self.store = StoreEngine(self)
        self.brain = BrainEngine(self)
        self.devices = DevicesEngine(self)
        self.study = StudyEngine(self)
        self.network = NetworkEngine(self)
        self.engines = [self.system, self.airplay, self.weather, self.spotify, self.store,
                        self.brain, self.devices, self.study, self.network]

    def call_ui(self, fn, *args):
        """Engines are thread-safe; kept as one place to hop threads if that changes."""
        fn(*args)

    def start(self):
        self.hub.publish("meta", {"version": VERSION, "demo": self.cfg.demo, "owner": self.cfg.owner,
                                  "theme": self.cfg.display.theme, "night_from": self.cfg.display.night_from,
                                  "day_from": self.cfg.display.day_from,
                                  "murmur": bool(self.cfg.murmur.url) or self.cfg.demo,
                                  "location": self.cfg.location.name})
        for e in self.engines:
            try:
                e.start()
            except Exception as ex:  # noqa: BLE001
                self.hub.note(f"{e.name} failed to start: {ex}", "error")
        self.hub.note(f"MatterDesk {VERSION} up{' (demo)' if self.cfg.demo else ''}")

    def stop(self):
        self.airplay.stop()
        for e in self.engines:
            e.stop()
