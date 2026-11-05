"""Optional bridge to the v5 Firebase database (batteries, bookmarks, sessions).

firebase-admin is heavy on a 1 GB Pi, so it is only imported when
[firebase] key_path is set and the file exists.
"""
from __future__ import annotations

import os


class FirebaseLink:
    def __init__(self, cfg, hub):
        self.hub = hub
        self.db = None
        fb = cfg.firebase
        if cfg.demo or not fb.key_path or not os.path.exists(fb.key_path):
            return
        try:
            import firebase_admin
            from firebase_admin import credentials, db
            if not firebase_admin._apps:
                firebase_admin.initialize_app(credentials.Certificate(fb.key_path), {"databaseURL": fb.database_url})
            self.db = db
            hub.note("Firebase link active")
        except Exception as e:  # noqa: BLE001
            hub.note(f"Firebase: {e}", "warn")

    @property
    def ready(self) -> bool:
        return self.db is not None

    def _get(self, path):
        try:
            return self.db.reference(path).get() if self.db else None
        except Exception as e:  # noqa: BLE001
            self.hub.note(f"Firebase read {path}: {e}", "warn")
            return None

    def batteries(self) -> dict:
        return self._get("telemetry/batteries") or {}

    def bookmarks(self, device: str) -> list[dict]:
        raw = self._get(f"telemetry/bookmarks/{device.lower()}")
        items = [raw[k] for k in sorted(raw)] if isinstance(raw, dict) else (raw or [])
        return [i for i in items if isinstance(i, dict)]

    def sessions(self) -> list[dict]:
        raw = self._get("sessions") or {}
        return list(raw.values()) if isinstance(raw, dict) else []

    def push_session(self, subject: str, seconds: int, started: int):
        if not self.db:
            return
        try:
            self.db.reference("sessions").push({"subject": subject, "duration_seconds": seconds, "timestamp": started})
        except Exception as e:  # noqa: BLE001
            self.hub.note(f"Firebase push: {e}", "warn")
