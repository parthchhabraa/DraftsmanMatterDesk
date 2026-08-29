import json
import os
import threading
import time

import requests

# --- Config resolution: env vars win; falls back to a local JSON file. ---
# Never hardcode BRAIN_TOKEN here — set it via env or data/brain_config.json.
CONFIG_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "brain_config.json"
)

POLL_INTERVAL_SECONDS = 5
REQUEST_TIMEOUT_SECONDS = 4

# Palette values copied from BASE_BG/CARD_BG/ACCENT_* at the top of
# matterdesk.py (modules/*.py don't import matterdesk.py, matching how
# telemetry.py hardcodes its own color literals) — keep these in sync if
# the palette at the top of matterdesk.py ever changes.
STATUS_COLORS = {
    "ONLINE": "#1db954",       # ACCENT_GREEN
    "DEGRADED": "#ffb020",     # ACCENT_AMBER
    "UNREACHABLE": "#ff4d4d",  # ACCENT_RED
}
TEXT_MUTED = "#7a8394"


class BrainEngine:
    """
    Talks to the DraftsmanBrain companion API (brain-api, on draftsmanbrain)
    over Tailscale: polls /status for host + antara-* service health, and can
    fire Wake-on-LAN requests via /wol/{target}.
    """

    def __init__(self, core):
        self.core = core
        self.brain_url, self.brain_token = self._load_config()
        self.status = "UNREACHABLE"
        self.last_payload = None

    def _load_config(self):
        url = os.environ.get("BRAIN_URL")
        token = os.environ.get("BRAIN_TOKEN")
        if url and token:
            return url.rstrip("/"), token
        try:
            with open(CONFIG_PATH, "r") as f:
                cfg = json.load(f)
            return cfg.get("brain_url", "").rstrip("/"), cfg.get("brain_token", "")
        except (OSError, json.JSONDecodeError):
            return "", ""

    def start_loop(self):
        threading.Thread(target=self._poll_loop, daemon=True).start()

    def _poll_loop(self):
        while True:
            state, payload = self._fetch_status()
            self.core.root.after(0, lambda s=state, p=payload: self._update_status_ui(s, p))
            time.sleep(POLL_INTERVAL_SECONDS)

    def _fetch_status(self):
        if not self.brain_url or not self.brain_token:
            return "UNREACHABLE", None
        try:
            res = requests.get(
                f"{self.brain_url}/status",
                headers={"X-Brain-Token": self.brain_token},
                timeout=REQUEST_TIMEOUT_SECONDS,
            )
            if res.status_code != 200:
                return "UNREACHABLE", None
            data = res.json()
            services = data.get("services", {})
            if services and any(v != "active" for v in services.values()):
                return "DEGRADED", data
            return "ONLINE", data
        except requests.RequestException:
            return "UNREACHABLE", None

    def _update_status_ui(self, state, payload):
        self.status = state
        self.last_payload = payload
        if not hasattr(self.core, "brain_status_id"):
            return
        canvas = getattr(self.core, "home_canvas", None)
        if not canvas or not canvas.winfo_exists():
            return
        canvas.itemconfig(
            self.core.brain_status_id,
            text=state,
            fill=STATUS_COLORS.get(state, TEXT_MUTED),
        )

    def wake_target(self, target="desktop"):
        """Fire-and-forget: matches DpnEngine.toggle_dpn_engine's pattern of
        firing a background thread and not blocking the UI thread on it."""
        threading.Thread(target=self._wake_worker, args=(target,), daemon=True).start()

    def _wake_worker(self, target):
        if not self.brain_url or not self.brain_token:
            return
        try:
            requests.post(
                f"{self.brain_url}/wol/{target}",
                headers={"X-Brain-Token": self.brain_token},
                timeout=REQUEST_TIMEOUT_SECONDS,
            )
        except requests.RequestException:
            pass
