from __future__ import annotations

import time

from .base import Engine

SCOPE = "user-read-playback-state user-modify-playback-state playlist-read-private playlist-read-collaborative"


def make_auth(cfg):
    from spotipy.oauth2 import SpotifyOAuth
    s = cfg.spotify
    return SpotifyOAuth(client_id=s.client_id, client_secret=s.client_secret, redirect_uri=s.redirect_uri,
                        cache_path=s.cache_path, open_browser=False, scope=SCOPE)


class SpotifyEngine(Engine):
    name = "spotify"

    def __init__(self, desk):
        super().__init__(desk)
        self.sp = None
        self.playlists: dict[str, str] = {}
        self._demo_t = time.time()
        self._demo_playing = True

    def start(self):
        if self.demo:
            self.every(1, self._demo_tick)
            return
        s = self.cfg.spotify
        if not (s.client_id and s.client_secret):
            self.hub.publish("music", {"state": "unconfigured"})
            return
        try:
            import spotipy
            auth = make_auth(self.cfg)
            if not auth.get_cached_token():
                self.hub.publish("music", {"state": "needs-auth"})
                return
            self.sp = spotipy.Spotify(auth_manager=auth, requests_timeout=6)
        except Exception as e:  # noqa: BLE001
            self.hub.note(f"spotify: {e}", "error")
            self.hub.publish("music", {"state": "error"})
            return
        self.spawn(self._load_playlists)
        self.every(lambda: 15 if self.desk.system.asleep else 2.5, self.refresh)

    def _load_playlists(self):
        items = self.sp.current_user_playlists(limit=50).get("items", [])
        self.playlists = {p["name"]: p["uri"] for p in items if p}

    def refresh(self):
        pb = self.sp.current_playback()
        if not pb or not pb.get("item"):
            self.hub.publish("music", {"state": "idle", "playlists": sorted(self.playlists)})
            return
        t = pb["item"]
        imgs = t.get("album", {}).get("images") or []
        self.hub.publish("music", {
            "state": "playing" if pb.get("is_playing") else "paused",
            "track": t["name"], "artist": ", ".join(a["name"] for a in t["artists"][:2]),
            "album": t.get("album", {}).get("name", ""), "art": imgs[0]["url"] if imgs else None,
            "progress_ms": pb.get("progress_ms") or 0, "duration_ms": t.get("duration_ms") or 1,
            "volume": (pb.get("device") or {}).get("volume_percent"),
            "device": (pb.get("device") or {}).get("name"), "at": time.time(),
            "playlists": sorted(self.playlists),
        })

    # ---------- controls ----------
    def control(self, action: str, value=None):
        if self.demo:
            if action == "toggle":
                self._demo_playing = not self._demo_playing
            elif action in ("next", "prev"):
                self._demo_t = time.time()
            return
        if not self.sp:
            raise RuntimeError("Spotify is not connected")
        sp = self.sp
        if action == "toggle":
            pb = sp.current_playback()
            sp.pause_playback() if pb and pb.get("is_playing") else sp.start_playback()
        elif action == "next":
            sp.next_track()
        elif action == "prev":
            sp.previous_track()
        elif action == "volume":
            sp.volume(max(0, min(100, int(value))))
        elif action == "playlist":
            uri = self.playlists.get(value)
            if uri:
                sp.start_playback(context_uri=uri)
        elif action == "device":
            for d in sp.devices().get("devices", []):
                if d["name"] == value:
                    sp.transfer_playback(device_id=d["id"], force_play=True)
        time.sleep(0.3)
        self.refresh()

    def devices(self) -> list[str]:
        if self.demo:
            return ["Parth's MacBook Air", "MatterDesk", "iPhone"]
        if not self.sp:
            return []
        return [d["name"] for d in self.sp.devices().get("devices", [])]

    def _demo_tick(self):
        el = (time.time() - self._demo_t) * 1000 % 214000
        self.hub.publish("music", {
            "state": "playing" if self._demo_playing else "paused", "track": "Location Unknown",
            "artist": "HONNE, BEKA", "album": "Love Me / Love Me Not", "art": None,
            "progress_ms": int(el), "duration_ms": 214000, "volume": 46, "device": "Parth's MacBook Air",
            "at": time.time(), "playlists": ["Lock in", "Late night", "Physics grind", "Car"],
        })
