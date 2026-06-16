import threading
import tkinter as tk
from firebase_admin import db

class BookmarksEngine:
    def __init__(self, core):
        self.core = core

    def load_device_bookmarks(self, device):
        self.core.bm_canvas.delete("all")
        if not getattr(self.core, 'firebase_active', False):
            self.core.bm_canvas.create_text(380, 100, text="Firebase Link Dropped.", fill="#ff4444", font=self.core.font_body)
            return
        self.core.bm_canvas.create_text(20, 20, text=f"Querying nodes for {device}...", fill="#888", font=self.core.font_body, anchor="w")
        threading.Thread(target=self._fetch_bookmarks_worker, args=(device,), daemon=True).start()

    def _fetch_bookmarks_worker(self, device):
        try:
            raw_data = db.reference(f'telemetry/bookmarks/{device.lower()}').get()
            links = [raw_data[k] for k in sorted(raw_data.keys())] if isinstance(raw_data, dict) else (raw_data or [])
            self.core.root.after(0, lambda: self._render_bookmarks([item for item in links if item]))
        except Exception: pass

    def _render_bookmarks(self, links):
        self.core.bm_canvas.delete("all")
        if not links:
            self.core.bm_canvas.create_text(20, 30, text="No active bookmarks indexed.", fill="#666666", font=self.core.font_body, anchor="w")
            return
        y = 30
        for item in links:
            if not isinstance(item, dict): continue
            t, u = item.get('title', 'Unknown Tab')[:45], item.get('url', '#')[:55]
            self.core.bm_canvas.create_text(20, y, text=t, fill="#ffffff", font=self.core.font_sub, anchor="w")
            self.core.bm_canvas.create_text(340, y, text=u, fill="#ff88aa", font=("Courier", 11), anchor="w")
            y += 35