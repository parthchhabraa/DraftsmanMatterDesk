import time
import datetime
import random
import json
import tkinter as tk
from firebase_admin import db

class StudyEngine:
    def __init__(self, core):
        self.core = core

    def draw_visceral_ring(self, extent, color):
        if not hasattr(self.core, 'ring_canvas') or not self.core.ring_canvas.winfo_exists(): return
        self.core.ring_canvas.delete("ring")
        self.core.ring_canvas.create_oval(10, 10, 190, 190, outline="#1a1a1a", width=10, tags="ring")
        if extent > 0:
            self.core.ring_canvas.create_arc(10, 10, 190, 190, start=90, extent=-extent, outline=color, style=tk.ARC, width=10, tags="ring")

    def toggle_timer(self):
        if self.core.study_active:
            self.core.study_active = False
            self.core.prevent_sleep = False
            self.core.btn_toggle_timer.config(text="START SPRINT", bg="#1db954")
            if self.core.study_job: self.core.root.after_cancel(self.core.study_job)
            if getattr(self.core, 'firebase_active', False) and self.core.study_seconds >= 5:
                import threading
                threading.Thread(target=self._push_session, args=(self.core.current_subject.get(), self.core.study_seconds), daemon=True).start()
            self.core.study_seconds = self.core.total_target_seconds = 0
            self.core.lbl_timer.config(text="00:00:00")
            self.core.abs_canvas.itemconfig(self.core.abs_text, text="00:00:00")
            self.core.lbl_target.config(text="Target: None")
            self.draw_visceral_ring(360, "#333")
        else:
            if self.core.total_target_seconds == 0:
                self.core.lbl_target.config(text="SELECT DURATION FIRST", fg="#ff4444")
                return
            self.core.study_active = True
            self.core.prevent_sleep = True
            self.core.btn_toggle_timer.config(text="END SPRINT", bg="#ff4444")
            self.core.root.after(10000, self._check_and_enter_absolute)
            self._tick_timer()

    def _check_and_enter_absolute(self):
        if self.core.study_active and self.core.current_frame == "study":
            self.core.nav_to("study_absolute")

    def _tick_timer(self):
        if not self.core.study_active: return
        self.core.study_seconds += 1
        remaining = max(0, self.core.total_target_seconds - self.core.study_seconds)
        h, m, s = remaining // 3600, (remaining % 3600) // 60, remaining % 60
        time_str = f"{h:02d}:{m:02d}:{s:02d}"
        
        self.core.lbl_timer.config(text=time_str)
        self.core.abs_canvas.itemconfig(self.core.abs_text, text=time_str)
        
        ratio = remaining / self.core.total_target_seconds if self.core.total_target_seconds else 0
        color = "#1db954" if ratio > 0.5 else ("#ffaa00" if ratio > 0.2 else "#ff4444")
        self.draw_visceral_ring(ratio * 360, color)
        
        if remaining <= 0:
            self.toggle_timer()
            self.core.nav_to("study")
            return
        self.core.study_job = self.core.root.after(1000, self._tick_timer)

    def _push_session(self, subject, duration):
        try:
            db.reference('sessions').push({'subject': subject, 'duration_seconds': duration, 'timestamp': int(time.time())})
            self.core.root.after(0, self.render_github_heatmap)
        except Exception: pass

    def render_github_heatmap(self):
        if not getattr(self.core, 'firebase_active', False): return
        try:
            sessions = db.reference('sessions').get() or {}
            daily_totals = {}
            recent_logs = []
            sorted_keys = sorted(sessions.keys(), key=lambda k: sessions[k].get('timestamp', 0))
            for k in sorted_keys:
                data = sessions[k]
                ts = data.get('timestamp', 0)
                date_str = datetime.datetime.fromtimestamp(ts).strftime('%Y-%m-%d')
                daily_totals[date_str] = daily_totals.get(date_str, 0) + data.get('duration_seconds', 0)
                dur_m = data.get('duration_seconds', 0) // 60
                recent_logs.append(f"{datetime.datetime.fromtimestamp(ts).strftime('%b %d')} | {data.get('subject', 'Unknown')} ({dur_m}m)")
            self.core.root.after(0, lambda: self._draw_heatmap_ui(daily_totals, recent_logs[-3:]))
        except Exception: pass

    def _draw_heatmap_ui(self, daily_totals, recent_logs):
        if not hasattr(self.core, 'heatmap_canvas') or not self.core.heatmap_canvas.winfo_exists(): return
        self.core.heatmap_canvas.delete("all")
        box_size, padding, cols, rows = 12, 3, 20, 7
        start_date = datetime.datetime.now() - datetime.timedelta(days=(cols * rows) - 1)
        for c in range(cols):
            for r in range(rows):
                current_day = start_date + datetime.timedelta(days=(c * rows) + r)
                sec = daily_totals.get(current_day.strftime('%Y-%m-%d'), 0)
                col = "#1a1a1a" if sec == 0 else ("#0e4429" if sec < 1800 else ("#006d32" if sec < 5400 else ("#26a641" if sec < 10800 else "#39d353")))
                x1 = 10 + (c * (box_size + padding))
                y1 = 10 + (r * (box_size + padding))
                self.core.heatmap_canvas.create_rectangle(x1, y1, x1+box_size, y1+box_size, fill=col, outline="")
        self.core.history_list_canvas.delete("all")
        y_pos = 10
        for log in reversed(recent_logs):
            self.core.history_list_canvas.create_text(10, y_pos, text=log, fill="#888888", font=self.core.font_body, anchor="w")
            y_pos += 25