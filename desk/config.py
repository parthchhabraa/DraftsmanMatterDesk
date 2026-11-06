"""MatterDesk configuration.

Everything lives in config/desk.toml (gitignored). config/desk.example.toml is the
template. Environment variables override single keys: MATTERDESK__BRAIN__TOKEN=...
sets [brain] token. No secret is ever read from source code.
"""
from __future__ import annotations

import os

try:
    import tomllib
except ModuleNotFoundError:   # Python 3.9/3.10 (macOS system python)
    import tomli as tomllib
from dataclasses import dataclass, field, fields, is_dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CONFIG_PATH = Path(os.environ.get("MATTERDESK_CONFIG", ROOT / "config" / "desk.toml"))


@dataclass
class Server:
    host: str = "0.0.0.0"
    port: int = 8420
    # Required for any request that is not from the Pi itself (phone, Mac, iPad on the tailnet).
    remote_key: str = ""
    data_dir: str = str(ROOT / "data")


@dataclass
class Display:
    backlight_power: str = "/sys/class/backlight/10-0045/bl_power"
    backlight_brightness: str = "/sys/class/backlight/10-0045/brightness"
    touch_device: str = "/dev/input/event4"
    idle_timeout_s: int = 600
    # "auto" switches the sheet to night ink between night_from and day_from (24h clock).
    theme: str = "auto"
    night_from: int = 19
    day_from: int = 7


@dataclass
class Location:
    name: str = "Udaipur"
    latitude: float = 24.5854
    longitude: float = 73.6855
    timezone: str = "Asia/Kolkata"


@dataclass
class Brain:
    url: str = ""          # https://draftsmanbrain.<tailnet>.ts.net
    token: str = ""        # X-Brain-Token shared with brain-api
    poll_s: int = 5
    wol_targets: list = field(default_factory=lambda: ["desktop"])


@dataclass
class Murmur:
    url: str = ""          # https://draftsmanbrain.<tailnet>.ts.net:7341
    token: str = ""


@dataclass
class Spotify:
    client_id: str = ""
    client_secret: str = ""
    redirect_uri: str = "http://127.0.0.1:8080/callback"
    cache_path: str = str(ROOT / "data" / "spotify.cache")


@dataclass
class Devices:
    # Mac agent and iPhone Shortcuts send this in X-Device-Key.
    device_key: str = ""
    stale_after_s: int = 900


@dataclass
class Study:
    subjects: list = field(default_factory=lambda: ["Maths", "Physics", "P Chem", "O Chem", "I Chem", "English", "Other"])
    # Services AdGuard blocks during Lock-in (AdGuard Home blocked-service ids).
    lockin_block: list = field(default_factory=lambda: ["instagram", "youtube", "snapchat", "netflix", "reddit", "twitter"])
    lockin_playlist: str = ""   # Spotify playlist name to start with Lock-in, empty = leave music alone
    lockin_lock_mac: bool = False
    daily_goal_min: int = 360
    # iPhone Focus with this name (sent by the Shortcuts automation) starts/ends a lock-in sprint.
    focus_name: str = "Study"
    focus_starts_sprint: bool = True


@dataclass
class Network:
    ap_iface: str = "wlan1"
    wan_iface: str = "wlan0"
    wg_iface: str = "wg0"
    dpn_ssid: str = "Draftsman DPN"
    dpn_passphrase: str = ""
    dpn_subnet: str = "10.45.0"
    scan_subnet: str = ""   # e.g. 192.168.1.0/24 for the deep nmap sweep; empty = DPN subnet


@dataclass
class Firebase:
    # Optional, legacy: the old desk read batteries/bookmarks/sessions from here.
    key_path: str = ""
    database_url: str = ""


@dataclass
class Ota:
    repo_url: str = "https://github.com/parthchhabraa/DraftsmanMatterDesk.git"
    branch: str = "main"


@dataclass
class Config:
    demo: bool = False
    owner: str = "Parth Chhabra"
    server: Server = field(default_factory=Server)
    display: Display = field(default_factory=Display)
    location: Location = field(default_factory=Location)
    brain: Brain = field(default_factory=Brain)
    murmur: Murmur = field(default_factory=Murmur)
    spotify: Spotify = field(default_factory=Spotify)
    devices: Devices = field(default_factory=Devices)
    study: Study = field(default_factory=Study)
    network: Network = field(default_factory=Network)
    firebase: Firebase = field(default_factory=Firebase)
    ota: Ota = field(default_factory=Ota)

    @property
    def data_dir(self) -> Path:
        p = Path(self.server.data_dir)
        p.mkdir(parents=True, exist_ok=True)
        return p


def _coerce(current, raw: str):
    if isinstance(current, bool):
        return raw.strip().lower() in ("1", "true", "yes", "on")
    if isinstance(current, int):
        return int(raw)
    if isinstance(current, float):
        return float(raw)
    if isinstance(current, list):
        return [x.strip() for x in raw.split(",") if x.strip()]
    return raw


def _apply(obj, data: dict):
    for f in fields(obj):
        if f.name not in data:
            continue
        cur = getattr(obj, f.name)
        val = data[f.name]
        if is_dataclass(cur) and isinstance(val, dict):
            _apply(cur, val)
        else:
            setattr(obj, f.name, val)


def load_config(path: Path | None = None) -> Config:
    cfg = Config()
    path = Path(path) if path else CONFIG_PATH
    if path.exists():
        with open(path, "rb") as fh:
            _apply(cfg, tomllib.load(fh))
    # MATTERDESK__SECTION__KEY=value overrides
    for key, raw in os.environ.items():
        if not key.startswith("MATTERDESK__"):
            continue
        parts = key[len("MATTERDESK__"):].lower().split("__")
        target = cfg
        for p in parts[:-1]:
            target = getattr(target, p, None)
            if target is None:
                break
        if target is not None and hasattr(target, parts[-1]):
            setattr(target, parts[-1], _coerce(getattr(target, parts[-1]), raw))
    if os.environ.get("MATTERDESK_DEMO") == "1":
        cfg.demo = True
    return cfg
