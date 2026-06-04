import tkinter as tk
from tkinter import font
from PIL import Image, ImageTk, ImageDraw
import evdev
import threading
import time
import os
import subprocess
import spotipy
from spotipy.oauth2 import SpotifyOAuth
import requests
import io
import firebase_admin
from firebase_admin import credentials, db
import json
import psutil
import datetime
import math

# --- System Paths ---
BACKLIGHT_POWER = '/sys/class/backlight/10-0045/bl_power'
BACKLIGHT_BRIGHT = '/sys/class/backlight/10-0045/brightness'
TOUCH_DEVICE = '/dev/input/event4'
CARPLAY_DIR = '/home/st6b/matterdesk/carplay-engine'
BOOTLOADER_IMG = '/home/st6b/matterdesk/images/bootloader.png'
FIREBASE_KEY_PATH = '/home/st6b/matterdesk/serviceAccountKey.json'
GITHUB_REPO_URL = 'https://github.com/parthchhabraa/DraftsmanMatterDesk.git'

# --- API Context ---
SPOTIFY_CLIENT_ID = '515b520ddd7b4ed2a33fdd1091c9ef00'
SPOTIFY_CLIENT_SECRET = 'e24611ecfa1c4be2b28c1d59e40af0b8'
SPOTIFY_REDIRECT_URI = 'http://127.0.0.1:8080/callback'
SPOTIFY_CACHE_PATH = '/home/st6b/matterdesk/.cache'

class TouchModal(tk.Toplevel):
    def __init__(self, parent, title, options, callback):
        super().__init__(parent)
        self.overrideredirect(True)
        self.geometry("800x480+0+0")
        self.configure(bg="#050505")
        self.attributes('-topmost', True)
        self.callback = callback
        
        lbl_font = font.Font(family="Helvetica", size=18, weight="bold")
        btn_font = font.Font(family="Helvetica", size=14, weight="bold")
        
        top = tk.Frame(self, bg="#121212", height=60)
        top.pack(fill="x")
        tk.Label(top, text=title, font=lbl_font, fg="#1db954", bg="#121212").pack(side="left", padx=20, pady=15)
        tk.Button(top, text="✕ CANCEL", font=btn_font, bg="#121212", fg="#ff4444", bd=0, command=self.destroy).pack(side="right", padx=20)

        canvas = tk.Canvas(self, bg="#050505", highlightthickness=0)
        scrollbar = tk.Scrollbar(self, orient="vertical", command=canvas.yview, width=30)
        scroll_frame = tk.Frame(canvas, bg="#050505")
        
        scroll_frame.bind("<Configure>", lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.create_window((0, 0), window=scroll_frame, anchor="nw", width=750)
        canvas.configure(yscrollcommand=scrollbar.set)
        
        canvas.pack(side="left", fill="both", expand=True, padx=20, pady=20)
        scrollbar.pack(side="right", fill="y")
        
        for opt in options:
            btn = tk.Button(scroll_frame, text=opt, font=btn_font, bg="#1a1a1a", fg="#ffffff", bd=0, activebackground="#333333", anchor="w", padx=20)
            btn.pack(fill="x", pady=5, ipady=15)
            btn.config(command=lambda o=opt: self._select(o))
            
    def _select(self, option):
        self.callback(option)
        self.destroy()

class MatterDeskCore:
    def __init__(self):
        self.system_logs = []
        self.log("System Initializing - MatterDesk v2.4.1 (OTA Patch)")
        
        self.root = tk.Tk()
        self.root.overrideredirect(True)
        self.root.attributes('-topmost', True)
        self.root.geometry("800x480+0+0")
        self.root.configure(bg="#050505", cursor="arrow")
        
        self.is_asleep = False
        self.active_process = self.aux_process = None 
        
        self.font_header = font.Font(family="Helvetica", size=22, weight="bold")
        self.font_sub = font.Font(family="Helvetica", size=14, weight="bold")
        self.font_body = font.Font(family="Helvetica", size=12)
        
        self.frames = {}
        self.bg_image = self._generate_gradient(800, 480, (5, 5, 5), (10, 20, 45))
        
        self._init_spotify()
        self._init_firebase()
        
        self._build_main_menu()
        self._build_spotify_ui()
        self._build_study_ui()
        self._build_settings_ui()
        self._build_logs_ui()
        self._build_diagnostics_ui()
        self._build_system_ui()
        self._build_telemetry_bar()
        self._build_thermal_panic_ui()
        
        self.nav_to("main")
        threading.Thread(target=self.touch_listener, daemon=True).start()
        threading.Thread(target=self._hardware_telemetry_loop, daemon=True).start()
        self.log("Boot Sequence Complete.")

    def log(self, message):
        ts = datetime.datetime.now().strftime("%H:%M:%S")
        entry = f"[{ts}] {message}"
        self.system_logs.insert(0, entry)
        if len(self.system_logs) > 100:
            self.system_logs.pop()
        
        if hasattr(self, 'txt_logs') and self.txt_logs.winfo_exists():
            self.txt_logs.config(state="normal")
            self.txt_logs.delete(1.0, tk.END)
            self.txt_logs.insert(tk.END, "\n".join(self.system_logs))
            self.txt_logs.config(state="disabled")

    def nav_to(self, frame_name):
        self.frames[frame_name].tkraise()
        self.frames["telemetry_bar"].tkraise()
        self.vinyl_active = (frame_name == "spotify")
        if self.vinyl_active and getattr(self, 'vinyl_job', None) is None: 
            self._animate_vinyl()
        if frame_name == "study" and getattr(self, 'firebase_active', False): 
            self._render_github_heatmap()

    def _generate_gradient(self, w, h, color1, color2):
        img = Image.new("RGB", (w, h))
        draw = ImageDraw.Draw(img)
        for i in range(h):
            r = int(color1[0] + (color2[0] - color1[0]) * i / h)
            g = int(color1[1] + (color2[1] - color1[1]) * i / h)
            b = int(color1[2] + (color2[2] - color1[2]) * i / h)
            draw.line([(0, i), (w, i)], fill=(r, g, b))
        return ImageTk.PhotoImage(img)

    # ==========================================
    # GLOBAL HARDWARE TELEMETRY & THERMALS
    # ==========================================
    def _build_telemetry_bar(self):
        f = tk.Frame(self.root, bg="#000000", height=15)
        f.place(x=0, y=465, width=800, height=15)
        self.frames["telemetry_bar"] = f
        self.lbl_hw_cpu = tk.Label(f, text="CPU: 0%", font=("Helvetica", 8, "bold"), fg="#888", bg="#000")
        self.lbl_hw_cpu.pack(side="left", padx=10)
        self.lbl_hw_ram = tk.Label(f, text="RAM: 0%", font=("Helvetica", 8, "bold"), fg="#888", bg="#000")
        self.lbl_hw_ram.pack(side="left", padx=10)
        self.lbl_hw_temp = tk.Label(f, text="TEMP: 0°C", font=("Helvetica", 8, "bold"), fg="#888", bg="#000")
        self.lbl_hw_temp.pack(side="right", padx=10)
        self.thermal_panic = False

    def _build_thermal_panic_ui(self):
        f = tk.Frame(self.root, bg="#1a0000")
        f.place(x=0, y=0, relwidth=1, relheight=1)
        self.frames["panic"] = f
        tk.Label(f, text="CRITICAL THERMAL EVENT", font=font.Font(family="Helvetica", size=30, weight="bold"), fg="#ff4444", bg="#1a0000").pack(pady=(120, 10))
        self.lbl_panic_temp = tk.Label(f, text="Hardware Core: 82°C+", font=self.font_sub, fg="#ffaa00", bg="#1a0000")
        self.lbl_panic_temp.pack()
        self.lbl_panic_count = tk.Label(f, text="Powering off in 60s to prevent degradation.", font=self.font_header, fg="#fff", bg="#1a0000")
        self.lbl_panic_count.pack(pady=40)
        tk.Button(f, text="OVERRIDE (RISK DAMAGE)", font=self.font_sub, bg="#330000", fg="#ff4444", bd=0, command=self._cancel_panic).pack(ipady=10, ipadx=20)

    def _hardware_telemetry_loop(self):
        while True:
            try:
                cpu = psutil.cpu_percent()
                ram = psutil.virtual_memory().percent
                temp_c = 0.0
                try:
                    with open('/sys/class/thermal/thermal_zone0/temp', 'r') as f:
                        temp_c = float(f.read()) / 1000.0
                except: pass

                cpu_col = "#ff4444" if cpu > 85 else "#888"
                ram_col = "#ff4444" if ram > 85 else "#888"
                tmp_col = "#ff4444" if temp_c > 75 else ("#ffaa00" if temp_c > 65 else "#888")

                self.root.after(0, lambda c=cpu, r=ram, t=temp_c, cc=cpu_col, rc=ram_col, tc=tmp_col: self._update_telemetry(c, r, t, cc, rc, tc))

                if temp_c >= 82.0 and not self.thermal_panic:
                    self.thermal_panic = True
                    self.panic_countdown = 60
                    self.root.after(0, self._trigger_panic)

            except Exception: pass
            time.sleep(2)

    def _update_telemetry(self, c, r, t, cc, rc, tc):
        self.lbl_hw_cpu.config(text=f"CPU: {c}%", fg=cc)
        self.lbl_hw_ram.config(text=f"RAM: {r}%", fg=rc)
        self.lbl_hw_temp.config(text=f"TEMP: {t:.1f}°C", fg=tc)

    def _trigger_panic(self):
        self.log("CRITICAL: Thermal shutdown initiated.")
        self.frames["panic"].tkraise()
        self.kill_active_processes()
        self._panic_tick()

    def _panic_tick(self):
        if not self.thermal_panic: return
        self.lbl_panic_count.config(text=f"Powering off in {self.panic_countdown}s...")
        if self.panic_countdown <= 0:
            self.poweroff_system()
        else:
            self.panic_countdown -= 1
            self.root.after(1000, self._panic_tick)

    def _cancel_panic(self):
        self.log("Thermal shutdown overridden by user.")
        self.thermal_panic = False
        self.nav_to("main")

    # ==========================================
    # UI BUILDERS: MAIN
    # ==========================================
    def _build_main_menu(self):
        f = tk.Frame(self.root)
        f.place(x=0, y=0, relwidth=1, relheight=1)
        self.frames["main"] = f
        
        canvas = tk.Canvas(f, width=800, height=480, highlightthickness=0)
        canvas.pack(fill="both", expand=True)
        canvas.create_image(0, 0, image=self.bg_image, anchor="nw")
        canvas.create_text(30, 40, text="DRAFTSMAN", font=self.font_header, fill="#ffffff", anchor="w")
        canvas.create_text(770, 40, text="v2.4.1 | SYSTEM CORE", font=self.font_body, fill="#888888", anchor="e")

        grid = tk.Frame(canvas, bg="#050505") 
        canvas.create_window(400, 260, window=grid, width=760, height=360)
        grid.columnconfigure((0, 1, 2, 3, 4), weight=1, uniform="col")
        grid.rowconfigure((0, 1), weight=1, uniform="row")

        btn_style = {"font": self.font_sub, "highlightthickness": 0, "bd": 0, "activebackground": "#333333"}
        
        tk.Button(grid, text="AirPlay", bg="#1a1a1a", fg="#fff", command=self.launch_uxplay, **btn_style).grid(row=0, column=0, sticky="nsew", padx=5, pady=5)
        tk.Button(grid, text="CarPlay", bg="#1a1a1a", fg="#aaa", command=self.launch_carplay, **btn_style).grid(row=0, column=1, sticky="nsew", padx=5, pady=5)
        tk.Button(grid, text="Spotify", bg="#0a2a10", fg="#1db954", command=lambda: self.nav_to("spotify"), **btn_style).grid(row=0, column=2, sticky="nsew", padx=5, pady=5)
        tk.Button(grid, text="Study", bg="#12123a", fg="#88aaff", command=lambda: self.nav_to("study"), **btn_style).grid(row=0, column=3, sticky="nsew", padx=5, pady=5)
        tk.Button(grid, text="Settings", bg="#222222", fg="#ddd", command=lambda: self.nav_to("settings"), **btn_style).grid(row=0, column=4, sticky="nsew", padx=5, pady=5)
        
        tk.Button(grid, text="Desktop", bg="#1a1a1a", fg="#aaa", command=self.launch_desktop, **btn_style).grid(row=1, column=0, sticky="nsew", padx=5, pady=5)
        tk.Button(grid, text="Show Mode", bg="#1a1a2a", fg="#6688ff", command=self.launch_show_mode, **btn_style).grid(row=1, column=1, sticky="nsew", padx=5, pady=5)
        tk.Button(grid, text="Standby", bg="#2a0000", fg="#ff4444", command=self.sleep_display, **btn_style).grid(row=1, column=2, sticky="nsew", padx=5, pady=5)
        tk.Button(grid, text="Reboot", bg="#2a1a00", fg="#ffaa00", command=self.reboot_system, **btn_style).grid(row=1, column=3, sticky="nsew", padx=5, pady=5)
        tk.Button(grid, text="Power Off", bg="#1a1a1a", fg="#ff4444", command=self.poweroff_system, **btn_style).grid(row=1, column=4, sticky="nsew", padx=5, pady=5)

    def _build_system_ui(self):
        f_pill = tk.Frame(self.root, bg="#2a0000")
        f_pill.place(x=0, y=0, relwidth=1, relheight=1)
        self.frames["pill"] = f_pill
        tk.Button(f_pill, text="✕ CLOSE", font=self.font_sub, bg="#2a0000", fg="#ff4444", activebackground="#4a0000", bd=0, command=self.wake_display).pack(expand=True, fill="both")
        
        f_wait = tk.Frame(self.root, bg="#050505")
        f_wait.place(x=0, y=0, relwidth=1, relheight=1)
        self.frames["waiting"] = f_wait
        self.lbl_waiting = tk.Label(f_wait, text="Waiting...", font=self.font_header, fg="#ffffff", bg="#050505")
        self.lbl_waiting.pack(pady=(150, 20))
        tk.Button(f_wait, text="Cancel", font=self.font_sub, bg="#1a1a1a", fg="#ff4444", bd=0, command=self.wake_display).pack(ipadx=20, ipady=10)

    # ==========================================
    # STUDY ENGINE
    # ==========================================
    def _init_firebase(self):
        self.study_active = False
        self.study_seconds = 0
        self.total_target_seconds = 0
        self.current_subject = tk.StringVar(value="Maths")
        self.study_job = None
        
        try:
            if not firebase_admin._apps:
                cred = credentials.Certificate(FIREBASE_KEY_PATH)
                firebase_admin.initialize_app(cred, {'databaseURL': 'https://YOUR-PROJECT-ID.firebaseio.com/'})
            self.firebase_active = True
            self.log("Firebase Database link active.")
        except Exception as e:
            self.firebase_active = False
            self.log(f"Firebase Init Error: {e}")

    def _build_study_ui(self):
        f = tk.Frame(self.root, bg="#050505")
        f.place(x=0, y=0, relwidth=1, relheight=1)
        self.frames["study"] = f
        
        eng = tk.Frame(f, bg="#050505", width=350)
        eng.pack(side="left", fill="y", padx=20, pady=20)
        eng.pack_propagate(False)
        
        tk.Button(eng, text="< ABORT", font=self.font_body, bg="#1a1a1a", fg="#ff4444", bd=0, command=self._exit_study).pack(anchor="w")
        
        tk.Label(eng, text="Hello Parth Chhabra,", font=self.font_sub, fg="#88aaff", bg="#050505", anchor="w").pack(fill="x", pady=(20,0))
        tk.Label(eng, text="What would you like to study today?", font=self.font_body, fg="#888", bg="#050505", anchor="w").pack(fill="x", pady=(0,20))
        
        self.ring_canvas = tk.Canvas(eng, width=200, height=200, bg="#050505", highlightthickness=0)
        self.ring_canvas.pack(pady=10)
        
        self.lbl_timer = tk.Label(eng, text="00:00:00", font=font.Font(family="Helvetica", size=40, weight="bold"), fg="#fff", bg="#050505")
        self.lbl_timer.place(relx=0.5, rely=0.45, anchor="center")
        
        self.lbl_target = tk.Label(eng, text="Target: None", font=self.font_body, fg="#888", bg="#050505")
        self.lbl_target.place(relx=0.5, rely=0.65, anchor="center")

        ctrl_frame = tk.Frame(eng, bg="#050505")
        ctrl_frame.pack(fill="x", pady=10)
        
        self.btn_subj = tk.Button(ctrl_frame, text="Maths", font=font.Font(size=10, weight="bold"), bg="#1a1a1a", fg="#fff", bd=0, command=self._trigger_subj_modal)
        self.btn_subj.pack(side="left", fill="x", expand=True, padx=5, ipady=8)
        
        self.btn_dur = tk.Button(ctrl_frame, text="Set Time", font=font.Font(size=10, weight="bold"), bg="#1a1a1a", fg="#fff", bd=0, command=self._trigger_dur_modal)
        self.btn_dur.pack(side="left", fill="x", expand=True, padx=5, ipady=8)
        
        self.btn_toggle_timer = tk.Button(eng, text="START SPRINT", font=self.font_sub, bg="#1db954", fg="#fff", bd=0, command=self._toggle_timer)
        self.btn_toggle_timer.pack(fill="x", ipady=12)

        tsk = tk.Frame(f, bg="#121212")
        tsk.pack(side="right", fill="both", expand=True, padx=20, pady=20)
        
        top_right = tk.Frame(tsk, bg="#121212")
        top_right.pack(fill="x", padx=10, pady=10)
        tk.Label(top_right, text="Study History", font=self.font_sub, fg="#fff", bg="#121212").pack(side="left")
        tk.Button(top_right, text="LAUNCH TELEMETRY", font=font.Font(size=10, weight="bold"), bg="#1a2a4a", fg="#88aaff", bd=0, command=self._trigger_analytics).pack(side="right", ipadx=10, ipady=5)
        
        self.heatmap_canvas = tk.Canvas(tsk, height=120, bg="#121212", highlightthickness=0)
        self.heatmap_canvas.pack(fill="x", padx=10, pady=10)
        
        tk.Label(tsk, text="Active Firebase Pipeline", font=self.font_body, fg="#888", bg="#121212", anchor="w").pack(fill="x", padx=10, pady=10)
        self.task_list_canvas = tk.Canvas(tsk, bg="#121212", highlightthickness=0)
        self.task_list_canvas.pack(fill="both", expand=True, padx=10)
        
        if getattr(self, 'firebase_active', False): 
            threading.Thread(target=self._poll_tasks, daemon=True).start()
        else: 
            tk.Label(self.task_list_canvas, text="Firebase Offline.", fg="#ff4444", bg="#121212").pack()
        
        self._draw_visceral_ring(360, "#333333")

    def _draw_visceral_ring(self, extent, color):
        self.ring_canvas.delete("ring")
        self.ring_canvas.create_oval(10, 10, 190, 190, outline="#1a1a1a", width=10, tags="ring")
        if extent > 0:
            self.ring_canvas.create_arc(10, 10, 190, 190, start=90, extent=-extent, outline=color, style=tk.ARC, width=10, tags="ring")

    def _trigger_subj_modal(self):
        TouchModal(self.root, "Select Subject", ["Maths", "Physics", "Ochem", "Pchem", "Ichem", "Other"], lambda s: (self.current_subject.set(s), self.btn_subj.config(text=s)))

    def _trigger_dur_modal(self):
        opts = {"30 Mins": 1800, "45 Mins": 2700, "1 Hr": 3600, "1 Hr 30 Mins": 5400, "2 Hrs": 7200}
        TouchModal(self.root, "Select Duration", list(opts.keys()), lambda s: self._set_target(s, opts[s]))

    def _set_target(self, label, seconds):
        self.total_target_seconds = seconds
        self.lbl_target.config(text=f"Target: {label}")
        
    def _exit_study(self):
        if getattr(self, 'study_active', False): 
            self._toggle_timer()
        self.nav_to("main")

    def _toggle_timer(self):
        if self.study_active:
            self.study_active = False
            self.btn_toggle_timer.config(text="START SPRINT", bg="#1db954")
            if self.study_job: self.root.after_cancel(self.study_job)
            
            if self.firebase_active and self.study_seconds >= 5:
                self.log(f"Initiating Firebase sync for {self.study_seconds}s of {self.current_subject.get()}")
                threading.Thread(target=self._push_session, args=(self.current_subject.get(), self.study_seconds), daemon=True).start()
            else:
                self.log(f"Session discarded: Only {self.study_seconds}s recorded.")
            
            self.study_seconds = 0
            self.total_target_seconds = 0
            self.lbl_timer.config(text="00:00:00")
            self.lbl_target.config(text="Target: None")
            self._draw_visceral_ring(360, "#333")
        else:
            if self.total_target_seconds == 0:
                self.lbl_target.config(text="SELECT DURATION FIRST", fg="#ff4444")
                self.root.after(2000, lambda: self.lbl_target.config(text="Target: None", fg="#888"))
                return
            
            self.study_active = True
            self.log(f"Sprint Started: {self.current_subject.get()} for {self.total_target_seconds}s")
            self.btn_toggle_timer.config(text="END SPRINT & LOG", bg="#ff4444")
            self._tick_timer()

    def _tick_timer(self):
        if not getattr(self, 'study_active', False): return
        self.study_seconds += 1
        remaining = max(0, self.total_target_seconds - self.study_seconds)
        h, m, s = remaining // 3600, (remaining % 3600) // 60, remaining % 60
        self.lbl_timer.config(text=f"{h:02d}:{m:02d}:{s:02d}")
        
        ratio = remaining / self.total_target_seconds if self.total_target_seconds else 0
        extent = ratio * 360
        color = "#1db954" if ratio > 0.5 else ("#ffaa00" if ratio > 0.2 else "#ff4444")
        self._draw_visceral_ring(extent, color)
        
        if remaining <= 0:
            self._toggle_timer()
            return
            
        self.study_job = self.root.after(1000, self._tick_timer)

    def _push_session(self, subject, duration):
        try:
            db.reference('sessions').push({'subject': subject, 'duration_seconds': duration, 'timestamp': int(time.time())})
            self.log("Firebase sync successful.")
            self.root.after(0, self._render_github_heatmap)
        except Exception as e:
            self.log(f"Firebase Sync Error: {e}")

    def _render_github_heatmap(self):
        if not getattr(self, 'firebase_active', False): return
        try:
            sessions = db.reference('sessions').get() or {}
            daily_totals = {}
            for k, data in sessions.items():
                ts = data.get('timestamp', 0)
                date_str = datetime.datetime.fromtimestamp(ts).strftime('%Y-%m-%d')
                daily_totals[date_str] = daily_totals.get(date_str, 0) + data.get('duration_seconds', 0)
            self.root.after(0, lambda: self._draw_heatmap(daily_totals))
        except Exception as e:
            self.log(f"Heatmap Render Error: {e}")

    def _draw_heatmap(self, daily_totals):
        self.heatmap_canvas.delete("all")
        box_size = 12
        padding = 3
        cols = 20
        rows = 7
        start_x = 10
        start_y = 10
        today = datetime.datetime.now()
        start_date = today - datetime.timedelta(days=(cols * rows) - 1)
        
        for c in range(cols):
            for r in range(rows):
                current_day = start_date + datetime.timedelta(days=(c * rows) + r)
                date_str = current_day.strftime('%Y-%m-%d')
                sec = daily_totals.get(date_str, 0)
                
                if sec == 0: col = "#1a1a1a"
                elif sec < 1800: col = "#0e4429"
                elif sec < 5400: col = "#006d32"
                elif sec < 10800: col = "#26a641"
                else: col = "#39d353"
                
                x1 = start_x + (c * (box_size + padding))
                y1 = start_y + (r * (box_size + padding))
                self.heatmap_canvas.create_rectangle(x1, y1, x1+box_size, y1+box_size, fill=col, outline="")

    def _poll_tasks(self):
        while True:
            if getattr(self, 'firebase_active', False):
                try:
                    raw = db.reference('tasks').order_by_child('completed').equal_to(False).get()
                    self.root.after(0, lambda: self._render_tasks(raw))
                except Exception: pass
            time.sleep(5)

    def _render_tasks(self, tasks_dict):
        self.task_list_canvas.delete("all")
        if not tasks_dict:
            self.task_list_canvas.create_text(10, 10, text="Pipeline Clear.", fill="#666", anchor="w", font=self.font_body)
            return
        y = 0
        for t_id, t_data in tasks_dict.items():
            subj = t_data.get('subject', 'N/A')
            title = t_data.get('title', 'Task')
            f = tk.Frame(self.task_list_canvas, bg="#222")
            f.place(x=0, y=y, relwidth=1, height=40)
            tk.Label(f, text=subj, font=font.Font(weight="bold"), fg="#1db954", bg="#222", width=8).pack(side="left", padx=10)
            tk.Label(f, text=title[:30], fg="#fff", bg="#222").pack(side="left", pady=10)
            tk.Button(f, text="DONE", bg="#333", fg="#fff", bd=0, command=lambda k=t_id: self._complete_task(k)).pack(side="right", padx=10, pady=5)
            y += 45

    def _complete_task(self, task_id):
        if getattr(self, 'firebase_active', False):
            threading.Thread(target=lambda: db.reference(f'tasks/{task_id}').update({'completed': True}), daemon=True).start()

    def _trigger_analytics(self):
        self.nav_to("waiting")
        self.lbl_waiting.config(text="Compiling Cloud Telemetry...")
        threading.Thread(target=self._compile_and_launch_web_dashboard, daemon=True).start()

    def _compile_and_launch_web_dashboard(self):
        try:
            sessions = db.reference('sessions').get() if getattr(self, 'firebase_active', False) else {}
            with open('/home/st6b/matterdesk/telemetry_data.json', 'w') as f:
                json.dump(sessions, f)
            env = os.environ.copy()
            env.update({"WAYLAND_DISPLAY": "wayland-1", "XDG_RUNTIME_DIR": "/run/user/1000"})
            self.root.after(0, lambda: self.lbl_waiting.config(text="Launching Visualizer..."))
            self.active_process = subprocess.Popen([
                "chromium-browser", "--kiosk", "--app=file:///home/st6b/matterdesk/telemetry.html", 
                "--enable-features=UseOzonePlatform", "--ozone-platform=wayland", "--disable-infobars"
            ], env=env)
            threading.Thread(target=self._monitor_analytics_closure, daemon=True).start()
        except Exception:
            self.root.after(0, lambda: self.lbl_waiting.config(text="Telemetry Failed."))

    def _monitor_analytics_closure(self):
        if getattr(self, 'active_process', None):
            self.active_process.wait()
            self.active_process = None
            self.root.after(0, lambda: self.nav_to("study"))

    # ==========================================
    # SYSTEM LOGS & HARDWARE DIAGNOSTICS
    # ==========================================
    def _build_logs_ui(self):
        f = tk.Frame(self.root, bg="#121212")
        f.place(x=0, y=0, relwidth=1, relheight=1)
        self.frames["logs"] = f
        
        top = tk.Frame(f, bg="#121212", height=40)
        top.pack(fill="x", padx=10, pady=10)
        tk.Button(top, text="< BACK", font=self.font_body, bg="#121212", fg="#fff", bd=0, command=lambda: self.nav_to("settings")).pack(side="left")
        tk.Label(top, text="SYSTEM EVENTS", font=self.font_sub, fg="#888", bg="#121212").pack(side="right", padx=20)
        
        self.txt_logs = tk.Text(f, bg="#050505", fg="#1db954", font=("Courier", 10), bd=0, highlightthickness=0)
        self.txt_logs.pack(fill="both", expand=True, padx=20, pady=10)
        self.txt_logs.insert(tk.END, "Logs initialized...\n")
        self.txt_logs.config(state="disabled")

    def _build_diagnostics_ui(self):
        f = tk.Frame(self.root, bg="#121212")
        f.place(x=0, y=0, relwidth=1, relheight=1)
        self.frames["diagnostics"] = f
        
        top = tk.Frame(f, bg="#121212", height=40)
        top.pack(fill="x", padx=10, pady=10)
        tk.Button(top, text="< BACK", font=self.font_body, bg="#121212", fg="#fff", bd=0, command=lambda: self.nav_to("settings")).pack(side="left")
        tk.Label(top, text="HARDWARE TESTS", font=self.font_sub, fg="#888", bg="#121212").pack(side="right", padx=20)
        
        btn_frame = tk.Frame(f, bg="#121212")
        btn_frame.pack(expand=True)
        
        tk.Button(btn_frame, text="Touch Calibration", font=self.font_sub, bg="#1a1a1a", fg="#fff", bd=0, command=self._test_touch, width=20).grid(row=0, column=0, padx=10, pady=10, ipady=15)
        tk.Button(btn_frame, text="Display Integrity", font=self.font_sub, bg="#1a1a1a", fg="#fff", bd=0, command=self._test_display, width=20).grid(row=0, column=1, padx=10, pady=10, ipady=15)
        tk.Button(btn_frame, text="Network Ping", font=self.font_sub, bg="#1a1a1a", fg="#fff", bd=0, command=self._test_network, width=20).grid(row=1, column=0, padx=10, pady=10, ipady=15)
        tk.Button(btn_frame, text="Firebase Health", font=self.font_sub, bg="#1a1a1a", fg="#fff", bd=0, command=self._test_firebase, width=20).grid(row=1, column=1, padx=10, pady=10, ipady=15)
        tk.Button(btn_frame, text="GitHub Access", font=self.font_sub, bg="#1a2a4a", fg="#88aaff", bd=0, command=self._test_github, width=20).grid(row=2, column=0, padx=10, pady=10, ipady=15)
        tk.Button(btn_frame, text="Thermal Sensors", font=self.font_sub, bg="#3a1a1a", fg="#ff8888", bd=0, command=self._test_thermal, width=20).grid(row=2, column=1, padx=10, pady=10, ipady=15)

    def _test_touch(self):
        self.nav_to("waiting")
        self.lbl_waiting.config(text="")
        c = tk.Canvas(self.frames["waiting"], bg="white")
        c.place(relwidth=1, relheight=1)
        tk.Label(c, text="Drag to Draw. Tap top-left to exit.", bg="white", fg="black", font=self.font_sub).pack(pady=20)
        def paint(event): c.create_oval(event.x-5, event.y-5, event.x+5, event.y+5, fill="black")
        c.bind("<B1-Motion>", paint)
        btn = tk.Button(c, text="EXIT", bg="red", fg="white", bd=0, command=lambda: (c.destroy(), self.nav_to("diagnostics")))
        btn.place(x=10, y=10)

    def _test_display(self):
        colors = ["red", "green", "blue", "white", "black"]
        self.nav_to("waiting")
        self.lbl_waiting.config(text="")
        c = tk.Canvas(self.frames["waiting"])
        c.place(relwidth=1, relheight=1)
        def cycle(idx):
            if idx >= len(colors):
                c.destroy()
                self.nav_to("diagnostics")
                return
            c.config(bg=colors[idx])
            self.root.after(1000, lambda: cycle(idx+1))
        cycle(0)

    def _test_network(self):
        self.log("Running Ping Test to 8.8.8.8...")
        try:
            subprocess.check_output(["ping", "-c", "3", "8.8.8.8"]).decode()
            self.log("Ping successful.")
            TouchModal(self.root, "Network Test", ["Ping Success: Reached 8.8.8.8"], lambda x: None)
        except Exception as e:
            self.log(f"Ping Failed: {e}")
            TouchModal(self.root, "Network Test", ["Ping Failed. Check Wi-Fi."], lambda x: None)

    def _test_firebase(self):
        self.log("Testing Firebase connectivity...")
        if not getattr(self, 'firebase_active', False):
            TouchModal(self.root, "Firebase Check", ["Offline. Missing/Invalid Key."], lambda x: None)
            return
        try:
            db.reference('ping_test').set({'ts': int(time.time())})
            self.log("Firebase Write Access OK.")
            TouchModal(self.root, "Firebase Check", ["Connection & Rules OK!"], lambda x: None)
        except Exception as e:
            self.log(f"Firebase Rules Error: {e}")
            TouchModal(self.root, "Firebase Check", ["Error (Check DB Rules/Log)"], lambda x: None)

    def _test_github(self):
        self.log("Testing GitHub connection (Public Repo)...")
        try:
            cwd = "/home/st6b/matterdesk"
            subprocess.run(["git", "config", "--global", "--add", "safe.directory", cwd], check=False)
            subprocess.run(["git", "remote", "remove", "origin"], cwd=cwd, stderr=subprocess.DEVNULL)
            subprocess.run(["git", "remote", "add", "origin", GITHUB_REPO_URL], cwd=cwd)
            
            res = subprocess.run(["git", "ls-remote", "origin"], cwd=cwd, capture_output=True, text=True, timeout=10)
            if res.returncode == 0:
                self.log("GitHub Remote OK. Origin bonded.")
                TouchModal(self.root, "GitHub Check", ["Connection OK!", "Ready for OTA."], lambda x: None)
            else:
                self.log(f"GitHub Error: {res.stderr}")
                TouchModal(self.root, "GitHub Check", ["Failed to reach origin.", "Check System Logs."], lambda x: None)
        except Exception as e:
            self.log(f"Git Exception: {e}")
            TouchModal(self.root, "GitHub Check", ["Execution Error.", str(e)], lambda x: None)

    def _test_thermal(self):
        self.log("Running Thermal Diagnostic...")
        try:
            with open('/sys/class/thermal/thermal_zone0/temp', 'r') as f:
                temp = float(f.read()) / 1000.0
            throttle_state = "Unknown"
            try: throttle_state = subprocess.check_output(["vcgencmd", "get_throttled"]).decode().strip()
            except: pass
            self.log(f"Temp: {temp}°C, {throttle_state}")
            TouchModal(self.root, "Thermal Readout", [f"Core Temp: {temp:.1f}°C", f"State: {throttle_state}"], lambda x: None)
        except Exception as e:
            self.log(f"Thermal Error: {e}")
            TouchModal(self.root, "Thermal Readout", ["Sensor read failed."], lambda x: None)

    # ==========================================
    # SETTINGS & OTA UPDATER
    # ==========================================
    def _build_settings_ui(self):
        f = tk.Frame(self.root, bg="#121212")
        f.place(x=0, y=0, relwidth=1, relheight=1)
        self.frames["settings"] = f
        
        top = tk.Frame(f, bg="#121212", height=40)
        top.pack(fill="x", padx=10, pady=10)
        tk.Button(top, text="< BACK", font=self.font_body, bg="#121212", fg="#fff", bd=0, command=lambda: self.nav_to("main")).pack(side="left")
        
        wifi_frame = tk.Frame(f, bg="#121212")
        wifi_frame.pack(side="left", fill="both", expand=True, padx=20)
        tk.Label(wifi_frame, text="NETWORK", font=self.font_sub, fg="#1db954", bg="#121212").pack(anchor="w")
        
        self.btn_wifi_sel = tk.Button(wifi_frame, text="Select Wi-Fi Network", font=self.font_sub, bg="#1a1a1a", fg="#fff", bd=0, command=self._trigger_wifi_modal)
        self.btn_wifi_sel.pack(fill="x", pady=10, ipady=15)
        self.entry_pass = tk.Entry(wifi_frame, font=self.font_header, bg="#0a0a0a", fg="#fff", bd=0, highlightthickness=1, highlightbackground="#333", show="*")
        self.entry_pass.pack(fill="x", pady=10, ipady=5)
        self.btn_connect = tk.Button(wifi_frame, text="CONNECT", font=self.font_sub, bg="#222", fg="#fff", bd=0, command=self._connect_wifi)
        self.btn_connect.pack(fill="x", ipady=15)

        right_frame = tk.Frame(f, bg="#121212")
        right_frame.pack(side="right", fill="both", expand=True, padx=20)
        
        self.btn_ota = tk.Button(right_frame, text="UPDATE SYSTEM (GITHUB OTA)", font=self.font_sub, bg="#1a2a4a", fg="#88aaff", bd=0, command=self._exec_ota)
        self.btn_ota.pack(fill="x", pady=(0, 10), ipady=10)
        
        row2 = tk.Frame(right_frame, bg="#121212")
        row2.pack(fill="x", pady=(0, 10))
        tk.Button(row2, text="DIAGNOSTICS", font=self.font_sub, bg="#333", fg="#fff", bd=0, command=lambda: self.nav_to("diagnostics")).pack(side="left", fill="x", expand=True, padx=(0,5), ipady=10)
        tk.Button(row2, text="SYSTEM LOGS", font=self.font_sub, bg="#333", fg="#fff", bd=0, command=lambda: self.nav_to("logs")).pack(side="right", fill="x", expand=True, padx=(5,0), ipady=10)
        
        self._build_osk(right_frame)

    def _trigger_wifi_modal(self):
        self.log("Scanning Wi-Fi interfaces...")
        try:
            out = subprocess.check_output(['nmcli', '-t', '-f', 'SSID', 'dev', 'wifi']).decode()
            networks = list(set([n for n in out.split('\n') if n.strip()]))
        except: networks = ["Scan Failed"]
        TouchModal(self.root, "Available Networks", networks, lambda s: self.btn_wifi_sel.config(text=s))

    def _build_osk(self, parent):
        kbd = tk.Frame(parent, bg="#121212")
        kbd.pack(fill="both", expand=True)
        keys = [
            ['1','2','3','4','5','6','7','8','9','0'],
            ['q','w','e','r','t','y','u','i','o','p'],
            ['a','s','d','f','g','h','j','k','l','DEL'],
            ['z','x','c','v','b','n','m','_','@','!']
        ]
        for r, row in enumerate(keys):
            kbd.rowconfigure(r, weight=1)
            for c, key in enumerate(row):
                kbd.columnconfigure(c, weight=1)
                bg = "#333333" if key == "DEL" else "#1a1a1a"
                tk.Button(kbd, text=key, font=self.font_sub, bg=bg, fg="#fff", bd=0, activebackground="#444", command=lambda k=key: self._osk_press(k)).grid(row=r, column=c, sticky="nsew", padx=2, pady=2)

    def _osk_press(self, key):
        if key == "DEL":
            txt = self.entry_pass.get()
            self.entry_pass.delete(0, tk.END)
            self.entry_pass.insert(0, txt[:-1])
        else: self.entry_pass.insert(tk.END, key)

    def _connect_wifi(self):
        ssid = self.btn_wifi_sel.cget("text")
        pw = self.entry_pass.get()
        if ssid == "Select Wi-Fi Network" or not ssid: return
        self.btn_connect.config(text="Linking...", fg="#ffaa00")
        self.log(f"Attempting Wi-Fi connection to: {ssid}")
        threading.Thread(target=self._exec_connect, args=(ssid, pw), daemon=True).start()

    def _exec_connect(self, ssid, pw):
        try:
            cmd = ['nmcli', 'dev', 'wifi', 'connect', ssid]
            if pw: cmd.extend(['password', pw])
            subprocess.check_call(cmd)
            self.log(f"Wi-Fi Connected successfully to {ssid}")
            self.root.after(0, lambda: self.btn_connect.config(text="CONNECTED", fg="#1db954"))
        except Exception as e:
            self.log(f"Wi-Fi Connection Failed: {e}")
            self.root.after(0, lambda: self.btn_connect.config(text="FAILED", fg="#ff4444"))

    def _exec_ota(self):
        self.log("Triggering OTA Git fetch/reset.")
        self.btn_ota.config(text="FETCHING REPOSITORY...", bg="#ffaa00")
        threading.Thread(target=self._ota_thread, daemon=True).start()

    def _ota_thread(self):
        try:
            cwd = "/home/st6b/matterdesk"
            
            subprocess.run(["git", "config", "--global", "--add", "safe.directory", cwd], check=False)
            subprocess.run(["git", "remote", "remove", "origin"], cwd=cwd, stderr=subprocess.DEVNULL)
            subprocess.run(["git", "remote", "add", "origin", GITHUB_REPO_URL], cwd=cwd)
            
            fetch = subprocess.run(["git", "fetch", "origin", "main"], cwd=cwd, capture_output=True, text=True)
            self.log(f"Git Fetch: {fetch.stdout} | {fetch.stderr}")
            if fetch.returncode != 0: raise Exception(f"Fetch failed: {fetch.stderr}")
            
            reset = subprocess.run(["git", "reset", "--hard", "origin/main"], cwd=cwd, capture_output=True, text=True)
            self.log(f"Git Reset: {reset.stdout} | {reset.stderr}")
            if reset.returncode != 0: raise Exception(f"Reset failed: {reset.stderr}")
            
            self.log("OTA updated successfully. Rebooting daemon.")
            self.root.after(0, lambda: self.btn_ota.config(text="RESTARTING DAEMON...", bg="#1db954"))
            time.sleep(1)
            os.system("sudo systemctl restart matterdesk.service")
        except Exception as e:
            self.log(f"OTA Failed: {e}")
            self.root.after(0, lambda: self.btn_ota.config(text="OTA FAILED. CHECK LOGS.", bg="#ff4444"))

    # ==========================================
    # OS PIPELINES
    # ==========================================
    def wake_display(self):
        if self.is_asleep:
            self.is_asleep = False
            os.system(f'echo 0 | sudo tee {BACKLIGHT_POWER} > /dev/null')
        self.kill_active_processes()
        self.root.geometry("800x480+0+0")
        self.nav_to("main")

    def launch_uxplay(self):
        self.kill_active_processes()
        self.lbl_waiting.config(text="Waiting for AirPlay...")
        self.nav_to("waiting")
        env = os.environ.copy()
        env.update({"WAYLAND_DISPLAY": "wayland-1", "XDG_RUNTIME_DIR": "/run/user/1000"})
        self.active_process = subprocess.Popen(["stdbuf", "-oL", "uxplay", "-n", "MatterDesk", "-p", "-avdec", "-vs", "autovideosink"], env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
        threading.Thread(target=self._monitor_stream, args=("starting mirroring", "Begin streaming"), daemon=True).start()
        self.fallback_job = self.root.after(8000, lambda: self._transform_to_pill() if self.active_process and self.active_process.poll() is None else None)

    def _monitor_stream(self, t1, t2):
        if not self.active_process: return
        try:
            for line in iter(self.active_process.stdout.readline, ''):
                if not line: break
                if t1 in line or t2 in line:
                    if hasattr(self, 'fallback_job'): self.root.after_cancel(self.fallback_job)
                    self.root.after(0, self._transform_to_pill)
                    break
        except: pass

    def launch_carplay(self):
        self.kill_active_processes()
        self.lbl_waiting.config(text="Waiting for Carlinkit...")
        self.nav_to("waiting")
        env = os.environ.copy()
        env.update({"WAYLAND_DISPLAY": "wayland-1", "XDG_RUNTIME_DIR": "/run/user/1000"})
        self.aux_process = subprocess.Popen(["npm", "start"], cwd=CARPLAY_DIR, stdout=subprocess.PIPE, text=True)
        threading.Thread(target=self._monitor_carplay, args=(env,), daemon=True).start()

    def _monitor_carplay(self, env):
        if not self.aux_process: return
        try:
            for line in iter(self.aux_process.stdout.readline, ''):
                if not line: break
                if "Server is running" in line or "listening" in line.lower():
                    self.root.after(0, self._transform_to_pill)
                    self.active_process = subprocess.Popen(["chromium-browser", "--kiosk", "--app=http://localhost:3000", "--enable-features=UseOzonePlatform", "--ozone-platform=wayland", "--disable-infobars"], env=env)
                    break
        except: pass

    def launch_desktop(self):
        self.kill_active_processes()
        self._transform_to_pill()

    def _transform_to_pill(self):
        self.nav_to("pill")
        self.root.geometry("150x55+630+15")

    def launch_show_mode(self):
        self.nav_to("waiting")
        self.lbl_waiting.config(text="")
        os.system(f'echo 128 | sudo tee {BACKLIGHT_BRIGHT} > /dev/null')
        try:
            self.show_img = ImageTk.PhotoImage(Image.open(BOOTLOADER_IMG).resize((800, 480), Image.LANCZOS))
            lbl = tk.Label(self.frames["waiting"], image=self.show_img, bg="#000000", bd=0)
            lbl.place(x=0, y=0, relwidth=1, relheight=1)
            lbl.bind("<Button-1>", lambda e: (lbl.destroy(), os.system(f'echo 255 | sudo tee {BACKLIGHT_BRIGHT} > /dev/null'), self.wake_display()))
        except: 
            self.lbl_waiting.config(text="bootloader.png not found")

    def kill_active_processes(self):
        if getattr(self, 'active_process', None): self.active_process.terminate()
        if getattr(self, 'aux_process', None): self.aux_process.terminate()
        self.active_process = self.aux_process = None
        os.system("killall uxplay node chromium-browser > /dev/null 2>&1")

    def sleep_display(self):
        if not self.is_asleep:
            self.is_asleep = True
            self.kill_active_processes()
            self.nav_to("waiting")
            self.lbl_waiting.config(text="")
            os.system(f'echo 1 | sudo tee {BACKLIGHT_POWER} > /dev/null')

    def reboot_system(self): self.log("Reboot command sent."); self.kill_active_processes(); os.system("sudo reboot")
    def poweroff_system(self): self.log("Poweroff command sent."); self.kill_active_processes(); os.system("sudo poweroff")

    def touch_listener(self):
        try:
            device = evdev.InputDevice(TOUCH_DEVICE)
            last = 0
            for event in device.read_loop():
                if self.is_asleep and event.type == evdev.ecodes.EV_KEY and event.value == 1:
                    curr = time.time()
                    if curr - last < 0.6: self.root.after(0, self.wake_display)
                    last = curr
        except: pass

    def run(self):
        self.root.mainloop()

if __name__ == "__main__":
    app = MatterDeskCore()
    app.run()