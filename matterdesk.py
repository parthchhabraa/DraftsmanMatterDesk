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

# --- System Paths ---
BACKLIGHT_POWER = '/sys/class/backlight/10-0045/bl_power'
BACKLIGHT_BRIGHT = '/sys/class/backlight/10-0045/brightness'
TOUCH_DEVICE = '/dev/input/event4'
CARPLAY_DIR = '/home/st6b/matterdesk/carplay-engine'
BOOTLOADER_IMG = '/home/st6b/matterdesk/images/bootloader.png'
LOGO_IMG_PATH = '/home/st6b/matterdesk/images/logo.png'
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
        self.log("System Initializing - MatterDesk v3.4 (macOS UX Engine)")
        
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
        
        self._build_boot_ui()
        self._build_ota_ui()
        self._build_main_menu()
        self._build_spotify_ui()
        self._build_study_ui()
        self._build_settings_ui()
        self._build_logs_ui()
        self._build_diagnostics_ui()
        self._build_system_ui()
        self._build_telemetry_bar()
        self._build_thermal_panic_ui()
        
        self.tap_times = []
        self.root.bind("<Button-1>", self._global_tap_handler, add="+")
        
        self.nav_to("boot")
        self.root.after(100, self._animate_boot_screen)
        
        threading.Thread(target=self.touch_listener, daemon=True).start()
        threading.Thread(target=self._hardware_telemetry_loop, daemon=True).start()
        threading.Thread(target=self._weather_telemetry_loop, daemon=True).start()
        if getattr(self, 'firebase_active', False):
            threading.Thread(target=self._battery_telemetry_loop, daemon=True).start()
            
        self._clock_tick()
        self.log("Boot Sequence Complete.")

    def log(self, message):
        ts = datetime.datetime.now().strftime("%H:%M:%S")
        entry = f"[{ts}] {message}"
        self.system_logs.insert(0, entry)
        if len(self.system_logs) > 100: self.system_logs.pop()
        
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

    def _create_round_rect(self, canvas, x1, y1, x2, y2, radius=20, **kwargs):
        points = [x1+radius, y1, x1+radius, y1, x2-radius, y1, x2-radius, y1, x2, y1, x2, y1+radius, x2, y1+radius, x2, y2-radius, x2, y2-radius, x2, y2, x2-radius, y2, x2-radius, y2, x1+radius, y2, x1+radius, y2, x1, y2, x1, y2-radius, x1, y2-radius, x1, y1+radius, x1, y1+radius, x1, y1]
        return canvas.create_polygon(points, **kwargs, smooth=True)

    def _global_tap_handler(self, event):
        now = time.time()
        self.tap_times.append(now)
        self.tap_times = [t for t in self.tap_times if now - t < 0.8]
        if len(self.tap_times) >= 3:
            self.tap_times.clear()
            if not self.is_asleep:
                self.sleep_display()

    # ==========================================
    # macOS STYLE BOOT & OTA UX
    # ==========================================
    def _build_boot_ui(self):
        f = tk.Frame(self.root, bg="#000000")
        f.place(x=0, y=0, relwidth=1, relheight=1)
        self.frames["boot"] = f
        self.boot_canvas = tk.Canvas(f, width=800, height=480, bg="#000000", highlightthickness=0)
        self.boot_canvas.pack()
        
        try:
            self.boot_logo_img = ImageTk.PhotoImage(Image.open(LOGO_IMG_PATH).resize((120, 120), Image.LANCZOS))
            self.boot_canvas.create_image(400, 200, image=self.boot_logo_img)
        except Exception:
            self.boot_canvas.create_text(400, 200, text="D", font=font.Font(family="Horizon", size=80), fill="#ffffff")

        self.boot_canvas.create_rectangle(300, 320, 500, 324, fill="#333333", outline="")
        self.boot_bar = self.boot_canvas.create_rectangle(300, 320, 300, 324, fill="#ffffff", outline="")

    def _animate_boot_screen(self, progress=0):
        if progress > 200:
            self.nav_to("main")
            return
        
        self.boot_canvas.coords(self.boot_bar, 300, 320, 300 + progress, 324)

        step = 6 if progress < 120 else 3
        self.root.after(40, self._animate_boot_screen, progress + step)

    def _build_ota_ui(self):
        f = tk.Frame(self.root, bg="#000000")
        f.place(x=0, y=0, relwidth=1, relheight=1)
        self.frames["ota"] = f
        self.ota_canvas = tk.Canvas(f, width=800, height=480, bg="#000000", highlightthickness=0)
        self.ota_canvas.pack()
        
        try:
            self.ota_logo_img = ImageTk.PhotoImage(Image.open(LOGO_IMG_PATH).resize((120, 120), Image.LANCZOS))
            self.ota_canvas.create_image(400, 200, image=self.ota_logo_img)
        except Exception:
            self.ota_canvas.create_text(400, 200, text="D", font=font.Font(family="Horizon", size=80), fill="#ffffff")

        self.ota_canvas.create_rectangle(300, 320, 500, 324, fill="#333333", outline="")
        self.ota_bar = self.ota_canvas.create_rectangle(300, 320, 300, 324, fill="#ffffff", outline="")
        self.ota_text = self.ota_canvas.create_text(400, 350, text="Preparing Update...", font=font.Font(family="Helvetica", size=12), fill="#aaaaaa")

    def _animate_ota_bar(self):
        if getattr(self, 'ota_finished', False):
            self.ota_canvas.coords(self.ota_bar, 300, 320, 500, 324)
            self.ota_canvas.itemconfig(self.ota_text, text="Restarting Firmware...")
            return
        if getattr(self, 'ota_error', False):
            self.ota_canvas.itemconfig(self.ota_text, text="Verification Failed. Rebooting...", fill="#ff4444")
            return
            
        if not hasattr(self, 'ota_progress'): self.ota_progress = 0
        if self.ota_progress < 180:
            self.ota_progress += 2
            self.ota_canvas.coords(self.ota_bar, 300, 320, 300 + self.ota_progress, 324)
        self.root.after(50, self._animate_ota_bar)

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
                    with open('/sys/class/thermal/thermal_zone0/temp', 'r') as f: temp_c = float(f.read()) / 1000.0
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
        if self.panic_countdown <= 0: self.poweroff_system()
        else:
            self.panic_countdown -= 1
            self.root.after(1000, self._panic_tick)

    def _cancel_panic(self):
        self.log("Thermal shutdown overridden by user.")
        self.thermal_panic = False
        self.nav_to("main")

    # ==========================================
    # MAIN MENU (BENTO GRID)
    # ==========================================
    def _build_main_menu(self):
        f = tk.Frame(self.root)
        f.place(x=0, y=0, relwidth=1, relheight=1)
        self.frames["main"] = f
        
        self.home_canvas = tk.Canvas(f, width=800, height=480, highlightthickness=0)
        self.home_canvas.pack(fill="both", expand=True)
        self.home_canvas.create_image(0, 0, image=self.bg_image, anchor="nw")

        self._create_round_rect(self.home_canvas, 20, 20, 320, 220, radius=25, fill="#121212", stipple="gray50")
        self.home_canvas.create_text(40, 50, text="DRAFTSMAN", font=font.Font(family="Horizon", size=14, weight="bold"), fill="#1db954", anchor="w")
        self.clock_id = self.home_canvas.create_text(40, 100, text="00:00", font=font.Font(family="Helvetica", size=55, weight="bold"), fill="#ffffff", anchor="w")
        self.greet_id = self.home_canvas.create_text(40, 160, text="Loading...", font=font.Font(family="Helvetica", size=14), fill="#aaaaaa", anchor="w")
        self.home_canvas.create_text(40, 185, text="Parth Chhabra", font=font.Font(family="Helvetica", size=16, weight="bold"), fill="#ffffff", anchor="w")

        self._create_round_rect(self.home_canvas, 20, 240, 320, 440, radius=25, fill="#121212", stipple="gray50")
        self.weather_temp_id = self.home_canvas.create_text(40, 290, text="--°C", font=font.Font(family="Helvetica", size=45, weight="bold"), fill="#ffffff", anchor="w")
        self.home_canvas.create_text(40, 350, text="Udaipur, Rajasthan", font=font.Font(family="Helvetica", size=12, weight="bold"), fill="#1db954", anchor="w")
        self.weather_pop_id = self.home_canvas.create_text(40, 390, text="Precipitation: --%", font=font.Font(family="Helvetica", size=12), fill="#aaaaaa", anchor="w")
        self.weather_desc_id = self.home_canvas.create_text(40, 410, text="Syncing Meteorology...", font=font.Font(family="Helvetica", size=12), fill="#aaaaaa", anchor="w")

        self._create_round_rect(self.home_canvas, 340, 20, 780, 200, radius=25, fill="#121212", stipple="gray50")
        self.batt_ui = {}
        devices = ["iPhone", "MacBook", "iPad", "Watch"]
        colors = ["#1db954", "#ffffff", "#88aaff", "#ffaa00"]
        for i, (dev, col) in enumerate(zip(devices, colors)):
            y_offset = 45 + (i * 35)
            self.home_canvas.create_text(370, y_offset, text=dev, font=font.Font(family="Helvetica", size=12, weight="bold"), fill="#fff", anchor="w")
            self.home_canvas.create_rectangle(480, y_offset-8, 720, y_offset+8, fill="#222222", outline="")
            bar_id = self.home_canvas.create_rectangle(480, y_offset-8, 480, y_offset+8, fill=col, outline="")
            text_id = self.home_canvas.create_text(750, y_offset, text="--%", font=font.Font(family="Helvetica", size=12), fill="#aaa", anchor="e")
            self.batt_ui[dev.lower()] = {"bar": bar_id, "text": text_id}

        apps = [
            ("AirPlay", "#1a1a1a", "#fff", self.launch_uxplay),
            ("CarPlay", "#1a1a1a", "#aaa", self.launch_carplay),
            ("Spotify", "#0a2a10", "#1db954", lambda: self.nav_to("spotify")),
            ("Study", "#12123a", "#88aaff", lambda: self.nav_to("study")),
            ("Settings", "#222222", "#ddd", lambda: self.nav_to("settings")),
            ("Power", "#2a0000", "#ff4444", self._show_power_menu)
        ]
        
        self.app_hitboxes = []
        for i, (name, bg, fg, cmd) in enumerate(apps):
            col = i % 3
            row = i // 3
            x1 = 340 + (col * 150)
            y1 = 220 + (row * 115)
            x2 = x1 + 130
            y2 = y1 + 95
            
            self._create_round_rect(self.home_canvas, x1, y1, x2, y2, radius=15, fill=bg)
            self.home_canvas.create_text(x1+65, y1+47, text=name, font=font.Font(family="Helvetica", size=14, weight="bold"), fill=fg)
            self.app_hitboxes.append((x1, y1, x2, y2, cmd))
            
        self.home_canvas.bind("<Button-1>", self._handle_home_click)

    def _handle_home_click(self, event):
        for x1, y1, x2, y2, cmd in self.app_hitboxes:
            if x1 <= event.x <= x2 and y1 <= event.y <= y2:
                cmd()
                break

    # --- Active Telemetry Threads ---
    def _clock_tick(self):
        now = datetime.datetime.now()
        self.home_canvas.itemconfig(self.clock_id, text=now.strftime("%H:%M"))
        
        h = now.hour
        if h < 12: greet = "Good morning,"
        elif h < 17: greet = "Good afternoon,"
        else: greet = "Good evening,"
        
        self.home_canvas.itemconfig(self.greet_id, text=greet)
        self.root.after(1000, self._clock_tick)

    def _weather_telemetry_loop(self):
        while True:
            try:
                url = "https://api.open-meteo.com/v1/forecast?latitude=24.5854&longitude=73.6855&current=temperature_2m,precipitation_probability,weather_code&timezone=Asia%2FKolkata"
                res = requests.get(url, timeout=10).json()
                temp = res["current"]["temperature_2m"]
                pop = res["current"]["precipitation_probability"]
                code = res["current"]["weather_code"]
                
                desc = "Clear"
                if code in [1, 2, 3]: desc = "Partly Cloudy"
                elif code in [45, 48]: desc = "Fog"
                elif code in [51, 53, 55, 61, 63, 65, 80, 81, 82]: desc = "Rain"
                elif code in [95, 96, 99]: desc = "Thunderstorm"

                self.root.after(0, lambda t=temp, p=pop, d=desc: self._update_weather_ui(t, p, d))
            except Exception as e: self.log(f"Weather Fetch Error: {e}")
            time.sleep(900) 

    def _update_weather_ui(self, temp, pop, desc):
        self.home_canvas.itemconfig(self.weather_temp_id, text=f"{temp:.1f}°C")
        self.home_canvas.itemconfig(self.weather_pop_id, text=f"Precipitation: {pop}%")
        self.home_canvas.itemconfig(self.weather_desc_id, text=desc)

    def _battery_telemetry_loop(self):
        while True:
            try:
                data = db.reference('telemetry/batteries').get() or {}
                self.root.after(0, lambda d=data: self._update_battery_ui(d))
            except Exception: pass
            time.sleep(60)

    def _update_battery_ui(self, data):
        keys_map = {"iphone": "iphone", "macbook": "mac", "ipad": "ipad", "watch": "watch"}
        for ui_key, db_key in keys_map.items():
            val = data.get(db_key)
            if val is not None:
                width = int((val / 100.0) * 240)
                self.home_canvas.coords(self.batt_ui[ui_key]["bar"], 480, self.home_canvas.coords(self.batt_ui[ui_key]["bar"])[1], 480 + width, self.home_canvas.coords(self.batt_ui[ui_key]["bar"])[3])
                self.home_canvas.itemconfig(self.batt_ui[ui_key]["text"], text=f"{val}%")

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
                firebase_admin.initialize_app(cred, {'databaseURL': 'https://draftsman-matterdesk-default-rtdb.firebaseio.com/'})
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
        
        if getattr(self, 'firebase_active', False): threading.Thread(target=self._poll_tasks, daemon=True).start()
        else: tk.Label(self.task_list_canvas, text="Firebase Offline.", fg="#ff4444", bg="#121212").pack()
        self._draw_visceral_ring(360, "#333333")

    def _draw_visceral_ring(self, extent, color):
        self.ring_canvas.delete("ring")
        self.ring_canvas.create_oval(10, 10, 190, 190, outline="#1a1a1a", width=10, tags="ring")
        if extent > 0: self.ring_canvas.create_arc(10, 10, 190, 190, start=90, extent=-extent, outline=color, style=tk.ARC, width=10, tags="ring")

    def _trigger_subj_modal(self): TouchModal(self.root, "Select Subject", ["Maths", "Physics", "Ochem", "Pchem", "Ichem", "Other"], lambda s: (self.current_subject.set(s), self.btn_subj.config(text=s)))
    def _trigger_dur_modal(self):
        opts = {"30 Mins": 1800, "45 Mins": 2700, "1 Hr": 3600, "1 Hr 30 Mins": 5400, "2 Hrs": 7200}
        TouchModal(self.root, "Select Duration", list(opts.keys()), lambda s: self._set_target(s, opts[s]))

    def _set_target(self, label, seconds):
        self.total_target_seconds = seconds
        self.lbl_target.config(text=f"Target: {label}")
        
    def _exit_study(self):
        if getattr(self, 'study_active', False): self._toggle_timer()
        self.nav_to("main")

    def _toggle_timer(self):
        if self.study_active:
            self.study_active = False
            self.btn_toggle_timer.config(text="START SPRINT", bg="#1db954")
            if self.study_job: self.root.after_cancel(self.study_job)
            if getattr(self, 'firebase_active', False) and self.study_seconds >= 5:
                self.log(f"Initiating Firebase sync for {self.study_seconds}s of {self.current_subject.get()}")
                threading.Thread(target=self._push_session, args=(self.current_subject.get(), self.study_seconds), daemon=True).start()
            else: self.log(f"Session discarded: Only {self.study_seconds}s recorded.")
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
        except Exception as e: self.log(f"Firebase Sync Error: {e}")

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
        except Exception as e: self.log(f"Heatmap Render Error: {e}")

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
        if getattr(self, 'firebase_active', False): threading.Thread(target=lambda: db.reference(f'tasks/{task_id}').update({'completed': True}), daemon=True).start()

    def _trigger_analytics(self):
        self.nav_to("waiting")
        self.lbl_waiting.config(text="Compiling Cloud Telemetry...")
        threading.Thread(target=self._compile_and_launch_web_dashboard, daemon=True).start()

    def _compile_and_launch_web_dashboard(self):
        try:
            sessions = db.reference('sessions').get() if getattr(self, 'firebase_active', False) else {}
            with open('/home/st6b/matterdesk/telemetry_data.json', 'w') as f: json.dump(sessions, f)
            env = os.environ.copy()
            env.update({"WAYLAND_DISPLAY": "wayland-1", "XDG_RUNTIME_DIR": "/run/user/1000"})
            self.root.after(0, lambda: self.lbl_waiting.config(text="Launching Visualizer..."))
            self.active_process = subprocess.Popen(["chromium-browser", "--kiosk", "--app=file:///home/st6b/matterdesk/telemetry.html", "--enable-features=UseOzonePlatform", "--ozone-platform=wayland", "--disable-infobars"], env=env)
            threading.Thread(target=self._monitor_analytics_closure, daemon=True).start()
        except Exception: self.root.after(0, lambda: self.lbl_waiting.config(text="Telemetry Failed."))

    def _monitor_analytics_closure(self):
        if getattr(self, 'active_process', None):
            self.active_process.wait()
            self.active_process = None
            self.root.after(0, lambda: self.nav_to("study"))

    # ==========================================
    # SYSTEM LOGS & DIAGNOSTICS
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
            with open('/sys/class/thermal/thermal_zone0/temp', 'r') as f: temp = float(f.read()) / 1000.0
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
        keys = [['1','2','3','4','5','6','7','8','9','0'], ['q','w','e','r','t','y','u','i','o','p'], ['a','s','d','f','g','h','j','k','l','DEL'], ['z','x','c','v','b','n','m','_','@','!']]
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
        self.log("Triggering Apple-Style OTA GUI.")
        self.nav_to("ota")
        self.ota_progress = 0
        self.ota_finished = False
        self.ota_error = False
        self._animate_ota_bar()
        threading.Thread(target=self._ota_thread, daemon=True).start()

    def _ota_thread(self):
        try:
            cwd = "/home/st6b/matterdesk"
            subprocess.run(["git", "config", "--global", "--add", "safe.directory", cwd], check=False)
            subprocess.run(["git", "remote", "remove", "origin"], cwd=cwd, stderr=subprocess.DEVNULL)
            subprocess.run(["git", "remote", "add", "origin", GITHUB_REPO_URL], cwd=cwd)
            fetch = subprocess.run(["git", "fetch", "origin", "main"], cwd=cwd, capture_output=True, text=True)
            if fetch.returncode != 0: raise Exception(f"Fetch failed: {fetch.stderr}")
            reset = subprocess.run(["git", "reset", "--hard", "origin/main"], cwd=cwd, capture_output=True, text=True)
            if reset.returncode != 0: raise Exception(f"Reset failed: {reset.stderr}")
            
            self.log("OTA firmware updated successfully.")
            self.ota_finished = True
            time.sleep(1.5)
            os.system("sudo systemctl restart matterdesk.service")
        except Exception as e:
            self.log(f"OTA Failed: {e}")
            self.ota_error = True
            time.sleep(3)
            self.root.after(0, lambda: self.nav_to("settings"))

    # ==========================================
    # SPOTIFY SUBSYSTEM
    # ==========================================
    def _init_spotify(self):
        self.sp = None
        if os.path.exists(SPOTIFY_CACHE_PATH):
            try:
                self.sp = spotipy.Spotify(auth_manager=SpotifyOAuth(client_id=SPOTIFY_CLIENT_ID, client_secret=SPOTIFY_CLIENT_SECRET, redirect_uri=SPOTIFY_REDIRECT_URI, cache_path=SPOTIFY_CACHE_PATH, open_browser=False, scope='user-read-playback-state user-modify-playback-state playlist-read-private playlist-read-collaborative'))
            except Exception: pass
        self.vinyl_active = False
        self.vinyl_job = None
        self.current_track_id = None
        self.album_art_image = None
        self.playlist_dict = {}

    def _build_spotify_ui(self):
        f = tk.Frame(self.root, bg="#121212")
        f.place(x=0, y=0, relwidth=1, relheight=1)
        self.frames["spotify"] = f
        if not self.sp:
            tk.Label(f, text="Auth Missing: run auth.py", font=self.font_header, fg="#ff4444", bg="#121212").pack(pady=(150, 10))
            tk.Button(f, text="< BACK", font=self.font_sub, bg="#222", fg="#fff", bd=0, command=lambda: self.nav_to("main")).pack(pady=40, ipadx=20, ipady=10)
            return
        top = tk.Frame(f, bg="#121212", height=40)
        top.pack(fill="x", padx=10, pady=5)
        tk.Button(top, text="< BACK", font=self.font_body, bg="#121212", fg="#fff", bd=0, command=lambda: self.nav_to("main")).pack(side="left")
        self.vinyl_canvas = tk.Canvas(f, width=350, height=350, bg="#121212", highlightthickness=0)
        self.vinyl_canvas.pack(side="left", padx=30)
        self._draw_vinyl()
        ctrl = tk.Frame(f, bg="#121212")
        ctrl.pack(side="left", fill="both", expand=True, padx=20)
        self.lbl_track = tk.Label(ctrl, text="Loading...", font=self.font_header, fg="#fff", bg="#121212", anchor="w")
        self.lbl_track.pack(fill="x", pady=(20,0))
        self.lbl_artist = tk.Label(ctrl, text="", font=self.font_sub, fg="#1db954", bg="#121212", anchor="w")
        self.lbl_artist.pack(fill="x")
        btn = tk.Frame(ctrl, bg="#121212")
        btn.pack(pady=20)
        c_style = {"font": font.Font(family="Helvetica", size=20, weight="bold"), "bg": "#121212", "fg": "#fff", "bd": 0, "activebackground": "#222"}
        tk.Button(btn, text="⏮", command=lambda: self.sp.previous_track() if self.sp else None, **c_style).pack(side="left", padx=15)
        self.btn_play = tk.Button(btn, text="▶", font=font.Font(size=24), bg="#1db954", fg="#fff", bd=0, command=self._sp_play_pause, width=3)
        self.btn_play.pack(side="left", padx=15)
        tk.Button(btn, text="⏭", command=lambda: self.sp.next_track() if self.sp else None, **c_style).pack(side="left", padx=15)
        self.vol_canvas = tk.Canvas(ctrl, width=200, height=20, bg="#121212", highlightthickness=0)
        self.vol_canvas.pack(pady=(10, 20))
        self.vol_canvas.bind("<B1-Motion>", self._on_vol_drag)
        self.vol_canvas.bind("<Button-1>", self._on_vol_drag)
        b_frame = tk.Frame(ctrl, bg="#121212")
        b_frame.pack(fill="x", side="bottom", pady=20)
        tk.Button(b_frame, text="Select Output", bg="#222", fg="#fff", bd=0, font=self.font_body, command=self._trigger_device_modal).pack(side="left", ipady=10, ipadx=10)
        tk.Button(b_frame, text="Select Playlist", bg="#222", fg="#fff", bd=0, font=self.font_body, command=self._trigger_playlist_modal).pack(side="right", ipady=10, ipadx=10)
        threading.Thread(target=self._poll_spotify_state, daemon=True).start()

    def _trigger_device_modal(self):
        opts = [d['name'] for d in getattr(self, 'sp', None).devices().get('devices', [])] if getattr(self, 'sp', None) else ["No devices"]
        TouchModal(self.root, "Select Output Device", opts, self._sp_transfer)

    def _trigger_playlist_modal(self):
        opts = list(getattr(self, 'playlist_dict', {}).keys()) if getattr(self, 'playlist_dict', None) else ["No playlists"]
        TouchModal(self.root, "Select Playlist", opts, self._sp_play_playlist)

    def _sp_transfer(self, target_name):
        if not getattr(self, 'sp', None): return
        for d in self.sp.devices().get('devices', []):
            if d['name'] == target_name:
                try: self.sp.transfer_playback(device_id=d['id'], force_play=True)
                except: pass
                break

    def _sp_play_playlist(self, p_name):
        if not getattr(self, 'sp', None): return
        p_uri = getattr(self, 'playlist_dict', {}).get(p_name)
        if p_uri:
            try: self.sp.start_playback(context_uri=p_uri)
            except: pass

    def _poll_spotify_state(self):
        if not getattr(self, 'sp', None): return
        try:
            playlists = self.sp.current_user_playlists(limit=20).get('items', [])
            self.playlist_dict = {p['name']: p['uri'] for p in playlists if p}
        except: pass
        while True:
            if getattr(self, 'vinyl_active', False):
                try:
                    pb = self.sp.current_playback()
                    if pb and pb.get('item'):
                        t = pb['item']
                        t_id, t_name, a_name = t['id'], t['name'], t['artists'][0]['name']
                        if t_id != getattr(self, 'current_track_id', None):
                            self.current_track_id = t_id
                            try:
                                res = requests.get(t['album']['images'][0]['url'], timeout=5)
                                img = Image.open(io.BytesIO(res.content)).convert("RGBA")
                                self.album_art_image = self._mask_circle(img, 140)
                                self.root.after(0, self._draw_vinyl)
                            except: pass
                        self.root.after(0, lambda n=t_name, a=a_name, p=pb['is_playing'], v=pb['device']['volume_percent']: self._update_sp_ui(n, a, p, v))
                except: pass
            time.sleep(3)

    def _update_sp_ui(self, n, a, p, v):
        if not getattr(self, 'vinyl_active', False): return
        self.lbl_track.config(text=n[:25])
        self.lbl_artist.config(text=a)
        self.btn_play.config(text="⏸" if p else "▶")
        self.vol_canvas.delete("all")
        self.vol_canvas.create_line(0, 10, 200, 10, fill="#404040", width=4, capstyle=tk.ROUND)
        fill_w = max(4, (v/100) * 200) if v else 4
        self.vol_canvas.create_line(0, 10, fill_w, 10, fill="#1db954", width=4, capstyle=tk.ROUND)
        self.vol_canvas.create_oval(fill_w-6, 4, fill_w+6, 16, fill="#fff", outline="")

    def _on_vol_drag(self, e):
        if not getattr(self, 'sp', None): return
        v = int((max(0, min(e.x, 200)) / 200) * 100)
        self._update_sp_ui("...", "...", False, v)
        if hasattr(self, '_vol_timer'): self.root.after_cancel(self._vol_timer)
        self._vol_timer = self.root.after(300, lambda: self.sp.volume(v) if self.sp else None)

    def _mask_circle(self, img, size):
        img = img.resize((size, size), Image.LANCZOS)
        mask = Image.new('L', (size, size), 0)
        ImageDraw.Draw(mask).ellipse((0, 0, size, size), fill=255)
        out = Image.new('RGBA', (size, size), (0,0,0,0))
        out.paste(img, (0,0), mask)
        return out

    def _draw_vinyl(self):
        s = 300
        img = Image.new('RGBA', (s, s), (18, 18, 18, 0))
        d = ImageDraw.Draw(img)
        d.ellipse((0, 0, s, s), fill=(20, 20, 20, 255), outline=(40, 40, 40, 255))
        for i in range(20, 100, 15): d.ellipse((i, i, s-i, s-i), outline=(30, 30, 30, 255))
        if getattr(self, 'album_art_image', None): img.paste(self.album_art_image, ((s-140)//2, (s-140)//2), self.album_art_image)
        else: d.ellipse((80, 80, 220, 220), fill=(29, 185, 84, 255))
        d.ellipse((145, 145, 155, 155), fill=(18, 18, 18, 255))
        self.base_vinyl = img

    def _animate_vinyl(self):
        if not getattr(self, 'vinyl_active', False): return
        self.vinyl_angle = getattr(self, 'vinyl_angle', 0)
        self.vinyl_angle = (self.vinyl_angle - 1) % 360
        self.cached_vinyl_img = ImageTk.PhotoImage(getattr(self, 'base_vinyl', Image.new('RGBA', (300,300))).rotate(self.vinyl_angle, resample=Image.BICUBIC))
        self.vinyl_canvas.delete("all")
        self.vinyl_canvas.create_image(175, 175, image=self.cached_vinyl_img)
        self.vinyl_job = self.root.after(30, self._animate_vinyl)

    def _sp_play_pause(self):
        if not getattr(self, 'sp', None): return
        try:
            pb = self.sp.current_playback()
            if pb and pb.get('is_playing'): self.sp.pause_playback()
            else: self.sp.start_playback()
        except Exception: pass

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

    def _show_power_menu(self):
        TouchModal(self.root, "System Power", ["Standby", "Reboot", "Power Off"], self._handle_power_choice)

    def _handle_power_choice(self, choice):
        if choice == "Standby": self.sleep_display()
        elif choice == "Reboot": self.reboot_system()
        elif choice == "Power Off": self.poweroff_system()

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
        except: self.lbl_waiting.config(text="bootloader.png not found")

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
