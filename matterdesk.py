import tkinter as tk
from tkinter import font
import evdev, threading, time, os, subprocess, json, datetime, random
from PIL import Image, ImageTk
from firebase_admin import credentials, firebase_admin

# Import decoupled specialized engine profiles
from modules.telemetry import TelemetryEngine
from modules.study import StudyEngine
from modules.dpn import DpnEngine
from modules.bookmarks import BookmarksEngine
from modules.spotify import SpotifyEngine

class MatterDeskCore:
    def __init__(self):
        self.system_logs = []
        self.log("System Initializing - MatterDesk v5.0 (Modular Architecture)")
        
        self.root = tk.Tk()
        self.root.overrideredirect(True)
        self.root.attributes('-topmost', True)
        self.root.geometry("800x480+0+0")
        self.root.configure(bg="#050505", cursor="arrow")
        
        # --- State Allocations ---
        self.is_asleep = self.prevent_sleep = self.thermal_panic = False
        self.active_process = None
        self.last_interaction = time.time()
        self.idle_timeout = 600
        self.current_frame = "boot"
        self.caps_lock_active = False
        self.study_active = self.study_seconds = self.total_target_seconds = 0
        self.study_job = None
        self.current_subject = tk.StringVar(value="Maths")
        
        # --- DPN Metrics ---
        self.dpn_active = False
        self.dpn_ssid = "Draftsman DPN"
        self.dpn_passkey = "Draftsman!Crypto!Secure!Core!99"
        self.dpn_country = "United States"
        self.dpn_adblock = True
        self.dpn_client_count = 0

        # --- Graphics Variables ---
        self.font_header = font.Font(family="Helvetica", size=22, weight="bold")
        self.font_sub = font.Font(family="Helvetica", size=14, weight="bold")
        self.font_body = font.Font(family="Helvetica", size=12)
        self.frames = {}
        self.bg_image = self._generate_gradient(800, 480, (5, 5, 5), (10, 20, 45))
        
        # --- Instantiate Component Drivers ---
        self.telemetry = TelemetryEngine(self)
        self.study = StudyEngine(self)
        self.dpn = DpnEngine(self)
        self.bookmarks = BookmarksEngine(self)
        self.spotify = SpotifyEngine(self)

        self._init_firebase()
        self.spotify.init_session(SPOTIFY_CLIENT_ID, SPOTIFY_CLIENT_SECRET, SPOTIFY_REDIRECT_URI, SPOTIFY_CACHE_PATH)
        
        # --- UI Build Sequencing ---
        self._build_boot_ui()
        self._build_ota_ui()
        self._build_standby_ui()
        self._build_main_menu()
        self._build_network_ui()
        self._build_bookmarks_ui()
        self._build_dpn_ui()
        self._build_spotify_ui()
        self._build_study_ui()
        self._build_settings_ui()
        self._build_logs_ui()
        self._build_diagnostics_ui()
        self._build_system_ui()
        self._build_telemetry_bar()
        self._build_thermal_panic_ui()
        
        # --- Bindings & Execution Threads ---
        self.tap_times = []
        self.root.bind("<Button-1>", self._global_tap_handler, add="+")
        self.nav_to("boot")
        self.root.after(100, self._animate_boot_screen)
        
        threading.Thread(target=self.touch_listener, daemon=True).start()
        self.telemetry.start_loops()
        self.spotify.start_polling()
        self._clock_tick()
        self._shuffle_abs_position()

    def _init_firebase(self):
        try:
            if not firebase_admin._apps:
                cred = credentials.Certificate(FIREBASE_KEY_PATH)
                firebase_admin.initialize_app(cred, {'databaseURL': 'https://draftsman-matterdesk-default-rtdb.firebaseio.com/'})
            self.firebase_active = True
        except Exception: self.firebase_active = False

    def log(self, msg):
        ts = datetime.datetime.now().strftime("%H:%M:%S")
        self.system_logs.insert(0, f"[{ts}] {msg}")
        if len(self.system_logs) > 100: self.system_logs.pop()

    def nav_to(self, target):
        self.frames[target].tkraise()
        self.current_frame = target
        if target in ["boot", "ota", "standby", "study_absolute"]: self.frames["telemetry_bar"].place_forget()
        else:
            self.frames["telemetry_bar"].place(x=0, y=460, width=800, height=20)
            self.frames["telemetry_bar"].tkraise()
        self.vinyl_active = (target == "spotify")
        if self.vinyl_active: self.spotify.animate_vinyl()

    def _generate_gradient(self, w, h, c1, c2):
        img = Image.new("RGB", (w, h))
        d = ImageDraw.Draw(img)
        for i in range(h):
            r = int(c1[0] + (c2[0] - c1[0]) * i / h)
            g = int(c1[1] + (c2[1] - c1[1]) * i / h)
            b = int(c1[2] + (c2[2] - c1[2]) * i / h)
            d.line([(0, i), (w, i)], fill=(r, g, b))
        return ImageTk.PhotoImage(img)

    def _create_round_rect(self, canvas, x1, y1, x2, y2, radius=20, **kwargs):
        points = [x1+radius, y1, x1+radius, y1, x2-radius, y1, x2-radius, y1, x2, y1, x2, y1+radius, x2, y1+radius, x2, y2-radius, x2, y2-radius, x2, y2, x2-radius, y2, x2-radius, y2, x1+radius, y2, x1+radius, y2, x1, y2, x1, y2-radius, x1, y2-radius, x1, y1+radius, x1, y1+radius, x1, y1]
        return canvas.create_polygon(points, **kwargs, smooth=True)

    def _global_tap_handler(self, event):
        now = time.time()
        self.last_interaction = now
        self.tap_times.append(now)
        self.tap_times = [t for t in self.tap_times if now - t < 0.8]
        if len(self.tap_times) >= 3:
            self.tap_times.clear()
            if not self.is_asleep: self.sleep_display()

    def _build_boot_ui(self):
        f = tk.Frame(self.root, bg="#000000")
        f.place(x=0, y=0, relwidth=1, relheight=1)
        self.frames["boot"] = f
        self.boot_canvas = tk.Canvas(f, width=800, height=480, bg="#000000", highlightthickness=0)
        self.boot_canvas.pack()
        self.boot_canvas.create_text(400, 200, text="D", font=("Helvetica", 80, "bold"), fill="#ffffff")
        self.boot_canvas.create_rectangle(300, 320, 500, 324, fill="#333333", outline="")
        self.boot_bar = self.boot_canvas.create_rectangle(300, 320, 300, 324, fill="#ffffff", outline="")

    def _animate_boot_screen(self, progress=0):
        if progress > 200:
            self.nav_to("main")
            return
        self.boot_canvas.coords(self.boot_bar, 300, 320, 300 + progress, 324)
        self.root.after(40, self._animate_boot_screen, progress + (6 if progress < 120 else 3))

    def _build_ota_ui(self):
        f = tk.Frame(self.root, bg="#000000")
        f.place(x=0, y=0, relwidth=1, relheight=1)
        self.frames["ota"] = f
        self.ota_canvas = tk.Canvas(f, width=800, height=480, bg="#000000", highlightthickness=0)
        self.ota_canvas.pack()
        self.ota_canvas.create_text(400, 200, text="D", font=("Helvetica", 80, "bold"), fill="#ffffff")
        self.ota_canvas.create_rectangle(300, 320, 500, 324, fill="#333333", outline="")
        self.ota_bar = self.ota_canvas.create_rectangle(300, 320, 300, 324, fill="#ffffff", outline="")
        self.ota_text = self.ota_canvas.create_text(400, 350, text="Preparing Update...", font=("Helvetica", 12), fill="#aaaaaa")

    def _build_telemetry_bar(self):
        f = tk.Frame(self.root, bg="#000000", height=20)
        f.place(x=0, y=460, width=800, height=20)
        self.frames["telemetry_bar"] = f
        self.lbl_hw_cpu = tk.Label(f, text="CPU: 0%", font=("Helvetica", 8, "bold"), fg="#888", bg="#000")
        self.lbl_hw_cpu.pack(side="left", padx=5)
        self.lbl_hw_ram = tk.Label(f, text="RAM: 0%", font=("Helvetica", 8, "bold"), fg="#888", bg="#000")
        self.lbl_hw_ram.pack(side="left", padx=5)
        self.lbl_hw_up = tk.Label(f, text="UP: --", font=("Helvetica", 8, "bold"), fg="#888", bg="#000")
        self.lbl_hw_up.pack(side="left", padx=5)
        self.lbl_hw_sleep = tk.Label(f, text="SLEEP: --", font=("Helvetica", 8, "bold"), fg="#1db954", bg="#000")
        self.lbl_hw_sleep.pack(side="left", padx=5)
        self.lbl_hw_temp = tk.Label(f, text="TEMP: 0°C", font=("Helvetica", 8, "bold"), fg="#888", bg="#000")
        self.lbl_hw_temp.pack(side="right", padx=10)
        self.telemetry_graph = tk.Canvas(f, width=120, height=18, bg="#000000", highlightthickness=0)
        self.telemetry_graph.pack(side="right", padx=10, pady=1)

    def _build_thermal_panic_ui(self):
        f = tk.Frame(self.root, bg="#1a0000")
        f.place(x=0, y=0, relwidth=1, relheight=1)
        self.frames["panic"] = f
        tk.Label(f, text="CRITICAL THERMAL EVENT", font=("Helvetica", 30, "bold"), fg="#ff4444", bg="#1a0000").pack(pady=(120, 10))
        self.lbl_panic_count = tk.Label(f, text="Powering off in 60s to prevent degradation.", font=self.font_header, fg="#fff", bg="#1a0000")
        self.lbl_panic_count.pack(pady=40)
        tk.Button(f, text="OVERRIDE (RISK DAMAGE)", font=self.font_sub, bg="#330000", fg="#ff4444", bd=0, command=self._cancel_panic).pack(ipady=10, ipadx=20)

    def _cancel_panic(self):
        self.thermal_panic = False
        self.nav_to("main")

    def _trigger_panic(self):
        self.frames["panic"].tkraise()
        self.kill_active_processes()

    def _build_main_menu(self):
        f = tk.Frame(self.root)
        f.place(x=0, y=0, relwidth=1, relheight=1)
        self.frames["main"] = f
        self.home_canvas = tk.Canvas(f, width=800, height=480, highlightthickness=0)
        self.home_canvas.pack(fill="both", expand=True)
        self.home_canvas.create_image(0, 0, image=self.bg_image, anchor="nw")
        
        self._create_round_rect(self.home_canvas, 20, 20, 320, 220, radius=25, fill="#121212", stipple="gray50")
        self.clock_f = tk.Canvas(self.home_canvas, width=280, height=60, bg="#121212", highlightthickness=0)
        self.clock_f.place(x=35, y=75)
        c_fnt = font.Font(family="Helvetica", size=48, weight="bold")
        self.c_h_m = self.clock_f.create_text(0, 30, text="00", font=c_fnt, fill="#ffffff", anchor="w")
        self.c_h_o = self.clock_f.create_text(0, -30, text="", font=c_fnt, fill="#ffffff", anchor="w")
        self.clock_f.create_text(65, 27, text=":", font=c_fnt, fill="#777777", anchor="w")
        self.c_m_m = self.clock_f.create_text(85, 30, text="00", font=c_fnt, fill="#ffffff", anchor="w")
        self.clock_f.create_text(150, 27, text=":", font=c_fnt, fill="#777777", anchor="w")
        self.c_s_m = self.clock_f.create_text(170, 30, text="00", font=c_fnt, fill="#ffffff", anchor="w")
        self.c_s_o = self.clock_f.create_text(170, -30, text="", font=c_fnt, fill="#ffffff", anchor="w")
        self.c_ap = self.clock_f.create_text(245, 38, text="AM", font=("Helvetica", 16, "bold"), fill="#1db954", anchor="w")
        self.greet_id = self.home_canvas.create_text(40, 160, text="Loading...", font=("Helvetica", 14), fill="#aaaaaa", anchor="w")
        self.home_canvas.create_text(40, 185, text="Parth Chhabra", font=("Helvetica", 16, "bold"), fill="#ffffff", anchor="w")

        self._create_round_rect(self.home_canvas, 20, 240, 320, 440, radius=25, fill="#121212", stipple="gray50")
        self.wx_canvas = tk.Canvas(self.home_canvas, width=280, height=180, bg="#121212", highlightthickness=0)
        self.wx_canvas.place(x=30, y=250)
        self.weather_temp_id = self.wx_canvas.create_text(10, 40, text="--°C", font=("Helvetica", 45, "bold"), fill="#ffffff", anchor="w")
        self.weather_pop_id = self.wx_canvas.create_text(10, 140, text="Precipitation: --%", font=("Helvetica", 12), fill="#aaaaaa", anchor="w")
        self.weather_desc_id = self.wx_canvas.create_text(10, 160, text="Syncing Meteorology...", font=("Helvetica", 12), fill="#aaaaaa", anchor="w")

        self._create_round_rect(self.home_canvas, 340, 20, 780, 200, radius=25, fill="#121212", stipple="gray50")
        devices = ["iPhone", "MacBook", "iPad"]
        for i, dev in enumerate(devices):
            y_offset = 55 + (i * 45)
            self.home_canvas.create_text(370, y_offset, text=dev, font=("Helvetica", 12, "bold"), fill="#fff", anchor="w")
            self.home_canvas.create_rectangle(480, y_offset-8, 720, y_offset+8, fill="#222222", outline="")
            bar_id = self.home_canvas.create_rectangle(480, y_offset-8, 480, y_offset+8, fill="#ffffff", outline="")
            text_id = self.home_canvas.create_text(750, y_offset, text="--%", font=("Helvetica", 12), fill="#aaa", anchor="e")
            self.batt_ui[dev.lower()] = {"bar": bar_id, "text": text_id}

        apps = [
            ("AirPlay", "#1a1a1a", "#fff", self.launch_uxplay),
            ("Spotify", "#0a2a10", "#1db954", lambda: self.nav_to("spotify")),
            ("Study", "#12123a", "#88aaff", lambda: self.nav_to("study")),
            ("Network", "#2a1a3a", "#aa88ff", lambda: self._trigger_netscan()),
            ("Bookmarks", "#3a1a1a", "#ff88aa", lambda: self.nav_to("bookmarks")),
            ("DPN VPN", "#112233", "#00aaff", lambda: self.nav_to("dpn")),
            ("Settings", "#222222", "#ddd", lambda: self.nav_to("settings")),
            ("Power", "#2a0000", "#ff4444", self._show_power_menu)
        ]
        self.app_hitboxes = []
        for i, (name, bg, fg, cmd) in enumerate(apps):
            col, row = i % 4, i // 4
            x1, y1 = 340 + (col * 110), 220 + (row * 110)
            x2, y2 = x1 + 100, y1 + 100
            self._create_round_rect(self.home_canvas, x1, y1, x2, y2, radius=15, fill=bg)
            self.home_canvas.create_text(x1+50, y1+50, text=name, font=("Helvetica", 11, "bold"), fill=fg, justify="center")
            self.app_hitboxes.append((x1, y1, x2, y2, cmd))
        self.home_canvas.bind("<Button-1>", self._handle_home_click)

    def _handle_home_click(self, event):
        self.last_interaction = time.time()
        for x1, y1, x2, y2, cmd in self.app_hitboxes:
            if x1 <= event.x <= x2 and y1 <= event.y <= y2:
                cmd()
                break

    def _clock_tick(self):
        now = datetime.datetime.now()
        h, m, s, ap = now.strftime("%I"), now.strftime("%M"), now.strftime("%S"), now.strftime("%p")
        if h.startswith("0"): h = h[1:]
        self.clock_f.itemconfig(self.c_h_m, text=h)
        self.clock_f.itemconfig(self.c_m_m, text=m)
        self.clock_f.itemconfig(self.c_s_m, text=s)
        self.clock_f.itemconfig(self.c_ap, text=ap)
        self.home_canvas.itemconfig(self.greet_id, text="Good morning," if now.hour < 12 else ("Good afternoon," if now.hour < 17 else "Good evening,"))
        self.root.after(1000, self._clock_tick)

    def _animate_weather(self):
        if self.current_frame != "main":
            self.root.after(50, self._animate_weather)
            return
        if self.telemetry.current_weather_type == "Rain":
            self.wx_canvas.delete("sun")
            if len(self.telemetry.rain_particles) < 20: self.telemetry.rain_particles.append([random.randint(150,350), 0, 2 + random.random()])
            self.wx_canvas.delete("rain")
            for p in self.telemetry.rain_particles:
                p[1] += p[2]
                if p[1] > 180: p[1] = 0
                self.wx_canvas.create_line(p[0], p[1], p[0] - 2, p[1] + 10, fill="#88aaff", tags="rain")
        elif self.telemetry.current_weather_type == "Clear":
            self.wx_canvas.delete("rain")
            self.wx_canvas.delete("sun")
            self.telemetry.sun_angle = (self.telemetry.sun_angle + 1) % 360
            cx, cy = 230, 50
            self.wx_canvas.create_oval(cx-15, cy-15, cx+15, cy+15, fill="#ffaa00", outline="", tags="sun")
            for i in range(0, 360, 45):
                rad = math.radians(i + self.telemetry.sun_angle)
                self.wx_canvas.create_line(cx + 20 * math.cos(rad), cy + 20 * math.sin(rad), cx + 30 * math.cos(rad), cy + 30 * math.sin(rad), fill="#ffaa00", width=2, tags="sun")
        self.root.after(50, self._animate_weather)

    def _battery_telemetry_loop(self):
        while True:
            try:
                data = db.reference('telemetry/batteries').get() or {}
                self.root.after(0, lambda d=data: self._update_battery_ui(d))
            except Exception: pass
            time.sleep(60)

    def _update_battery_ui(self, data):
        keys_map = {"iphone": "iphone", "macbook": "mac", "ipad": "ipad"}
        for ui_key, db_key in keys_map.items():
            val = data.get(db_key)
            if val is not None:
                lower = (val // 10) * 10
                upper = lower + 9 if lower < 100 else 100
                midpoint = lower + 5 if lower < 100 else 100
                base_x, max_width = 480, 240
                width = int((val / 100.0) * max_width)
                self.home_canvas.coords(self.batt_ui[ui_key]["bar"], base_x, self.home_canvas.coords(self.batt_ui[ui_key]["bar"])[1], base_x + width, self.home_canvas.coords(self.batt_ui[ui_key]["bar"])[3])
                col, r_col = ("#1db954", "#0e4419") if val >= 70 else (("#88aaff", "#223355") if val >= 30 else ("#ff4444", "#4a1111"))
                self.home_canvas.itemconfig(self.batt_ui[ui_key]["bar"], fill=col)
                self.home_canvas.delete(f"range_{ui_key}")
                if val < 100:
                    r_bar = self.home_canvas.create_rectangle(base_x + int((lower/100.0)*max_width), self.home_canvas.coords(self.batt_ui[ui_key]["bar"])[1], base_x + int((upper/100.0)*max_width), self.home_canvas.coords(self.batt_ui[ui_key]["bar"])[3], fill=r_col, outline="", tags=f"range_{ui_key}")
                    self.home_canvas.tag_lower(r_bar, self.batt_ui[ui_key]["bar"])
                self.home_canvas.itemconfig(self.batt_ui[ui_key]["text"], text=f"~{midpoint}%" if val < 100 else "100%")

    def _build_dpn_ui(self):
        f = tk.Frame(self.root, bg="#0b0f19")
        f.place(x=0, y=0, relwidth=1, relheight=1)
        self.frames["dpn"] = f
        top = tk.Frame(f, bg="#111625", height=50)
        top.pack(fill="x")
        tk.Button(top, text="< BACK", font=self.font_body, bg="#111625", fg="#fff", bd=0, command=lambda: self.nav_to("main")).pack(side="left", padx=10)
        tk.Label(top, text="DRAFTSMAN SECURE AP DPN", font=self.font_sub, fg="#00aaff", bg="#111625").pack(side="right", padx=20)
        
        left_p = tk.Frame(f, bg="#0b0f19", width=380)
        left_p.pack(side="left", fill="both", expand=True, padx=20, pady=20)
        left_p.pack_propagate(False)
        self.lbl_dpn_status = tk.Label(left_p, text="NETWORK STATE: OFFLINE", font=self.font_sub, fg="#ff4444", bg="#0b0f19", anchor="w")
        self.lbl_dpn_status.pack(fill="x", pady=5)
        self.btn_dpn_toggle = tk.Button(left_p, text="ACTIVATE DPN CORE", font=self.font_sub, bg="#1a2a4a", fg="#00aaff", bd=0, command=self.dpn.toggle_dpn_engine)
        self.btn_dpn_toggle.pack(fill="x", ipady=15, pady=10)
        
        cfg_box = tk.LabelFrame(left_p, text=" Parameters Control ", font=self.font_body, fg="#888", bg="#0b0f19", bd=1)
        cfg_box.pack(fill="both", expand=True, pady=5)
        f_ssid = tk.Frame(cfg_box, bg="#0b0f19")
        f_ssid.pack(fill="x", padx=10, pady=5)
        tk.Label(f_ssid, text="SSID Target:", font=self.font_body, fg="#fff", bg="#0b0f19").pack(side="left")
        self.btn_dpn_ssid = tk.Button(f_ssid, text=self.dpn_ssid, font=self.font_body, bg="#111625", fg="#00aaff", bd=0, command=self._change_dpn_ssid)
        self.btn_dpn_ssid.pack(side="right", padx=5)
        f_cntry = tk.Frame(cfg_box, bg="#0b0f19")
        f_cntry.pack(fill="x", padx=10, pady=5)
        tk.Label(f_cntry, text="Exit Gateway:", font=self.font_body, fg="#fff", bg="#0b0f19").pack(side="left")
        self.btn_dpn_country = tk.Button(f_cntry, text=self.dpn_country, font=self.font_body, bg="#111625", fg="#00aaff", bd=0, command=self._select_dpn_country)
        self.btn_dpn_country.pack(side="right", padx=5)
        f_blk = tk.Frame(cfg_box, bg="#0b0f19")
        f_blk.pack(fill="x", padx=10, pady=5)
        tk.Label(f_blk, text="Ad/Tracker Blocking:", font=self.font_body, fg="#fff", bg="#0b0f19").pack(side="left")
        self.btn_dpn_blk = tk.Button(f_blk, text="ENABLED", font=self.font_body, bg="#0a2a10", fg="#1db954", bd=0, command=self._toggle_dpn_adblock)
        self.btn_dpn_blk.pack(side="right", padx=5)

        right_p = tk.Frame(f, bg="#111625")
        right_p.pack(side="right", fill="both", expand=True, padx=20, pady=20)
        tk.Label(right_p, text="SCAN MATRIX TO CONNECT", font=self.font_body, fg="#888", bg="#111625").pack(anchor="w", padx=15, pady=5)
        self.dpn_monitor_canvas = tk.Canvas(right_p, bg="#050505", highlightthickness=0)
        self.dpn_monitor_canvas.pack(fill="both", expand=True, padx=15, pady=(0, 15))
        self.dpn.render_dpn_canvas()

    def _change_dpn_ssid(self):
        TouchModal(self.root, "Select Broadcast Network SSID", ["Draftsman DPN", "Project Resonance AP", "Xeno Vault Mesh"], lambda s: (setattr(self, 'dpn_ssid', s), self.btn_dpn_ssid.config(text=s), self.dpn.render_dpn_canvas()))
    def _select_dpn_country(self):
        TouchModal(self.root, "Select exit wireguard server", ["United States", "Germany", "Singapore", "Japan", "United Kingdom"], lambda c: (setattr(self, 'dpn_country', c), self.btn_dpn_country.config(text=c)))
    def _toggle_dpn_adblock(self):
        self.dpn_adblock = not self.dpn_adblock
        self.btn_dpn_blk.config(text="ENABLED" if self.dpn_adblock else "BYPASSED", bg="#0a2a10" if self.dpn_adblock else "#333", fg="#1db954" if self.dpn_adblock else "#aaa")

    def _build_bookmarks_ui(self):
        f = tk.Frame(self.root, bg="#121212")
        f.place(x=0, y=0, relwidth=1, relheight=1)
        self.frames["bookmarks"] = f
        top = tk.Frame(f, bg="#121212", height=40)
        top.pack(fill="x", padx=10, pady=10)
        tk.Button(top, text="< BACK", font=self.font_body, bg="#121212", fg="#fff", bd=0, command=lambda: self.nav_to("main")).pack(side="left")
        tk.Label(top, text="CROSS-DEVICE BOOKMARKS", font=self.font_sub, fg="#ff88aa", bg="#121212").pack(side="right", padx=20)
        nav_row = tk.Frame(f, bg="#121212")
        nav_row.pack(fill="x", padx=20, pady=5)
        for d in ["MacBook", "Workstation", "Server"]:
            tk.Button(nav_row, text=d.upper(), font=("Helvetica", 10, "bold"), bg="#1a1a1a", fg="#ff88aa", bd=0, command=lambda dev=d: self.bookmarks.load_device_bookmarks(dev)).pack(side="left", padx=5, ipady=8, expand=True, fill="x")
        self.bm_canvas = tk.Canvas(f, bg="#050505", highlightthickness=0)
        self.bm_canvas.pack(fill="both", expand=True, padx=20, pady=10)

    def _build_network_ui(self):
        f = tk.Frame(self.root, bg="#121212")
        f.place(x=0, y=0, relwidth=1, relheight=1)
        self.frames["network"] = f
        top = tk.Frame(f, bg="#121212", height=40)
        top.pack(fill="x", padx=10, pady=10)
        tk.Button(top, text="< BACK", font=self.font_body, bg="#121212", fg="#fff", bd=0, command=lambda: self.nav_to("main")).pack(side="left")
        tk.Label(top, text="NETWORK MAPPER (ARP)", font=self.font_sub, fg="#aa88ff", bg="#121212").pack(side="right", padx=20)
        self.net_canvas = tk.Canvas(f, bg="#050505", highlightthickness=0)
        self.net_canvas.pack(fill="both", expand=True, padx=20, pady=10)

    def _trigger_netscan(self):
        self.nav_to("network")
        self.net_canvas.delete("all")
        self.net_canvas.create_text(20, 20, text="Executing Kernel ARP Scan...", fill="#aaaaaa", font=self.font_body, anchor="w")
        threading.Thread(target=self._exec_arp_scan, daemon=True).start()

    def _exec_arp_scan(self):
        try:
            output = subprocess.check_output(['arp', '-a']).decode()
            nodes = []
            for line in output.split('\n'):
                if "at" in line and "on" in line:
                    parts = line.split()
                    if len(parts) >= 4: nodes.append((parts[1].strip('()'), parts[3], parts[0]))
            self.root.after(0, lambda: self._render_netscan(nodes))
        except Exception as e: self.root.after(0, lambda: self.net_canvas.create_text(20, 50, text=f"Scan Failed: {e}", fill="#ff4444", font=self.font_body, anchor="w"))

    def _render_netscan(self, nodes):
        self.net_canvas.delete("all")
        if not nodes: return
        y = 20
        self.net_canvas.create_text(20, y, text=f"Discovered {len(nodes)} active nodes:", fill="#aa88ff", font=self.font_sub, anchor="w")
        y += 40
        for ip, mac, host in nodes:
            self.net_canvas.create_text(20, y, text=ip, fill="#1db954", font=("Courier", 12, "bold"), anchor="w")
            self.net_canvas.create_text(180, y, text=mac, fill="#aaaaaa", font=("Courier", 12), anchor="w")
            self.net_canvas.create_text(380, y, text=host[:30], fill="#ffffff", font=self.font_body, anchor="w")
            y += 35

    def _build_standby_ui(self):
        f = tk.Frame(self.root, bg="#000000")
        f.place(x=0, y=0, relwidth=1, relheight=1)
        self.frames["standby"] = f
        self.ss_canvas = tk.Canvas(f, bg="#000000", highlightthickness=0)
        self.ss_canvas.pack(fill="both", expand=True)
        self.ss_text = self.ss_canvas.create_text(400, 240, text="00:00", font=("Helvetica", 40, "bold"), fill="#222222")
        self.ss_x = self.ss_y = 400
        self.ss_dx = self.ss_dy = 2

    def _animate_screensaver(self):
        if not self.is_asleep: return
        self.ss_x += self.ss_dx; self.ss_y += self.ss_dy
        if self.ss_x > 700 or self.ss_x < 100: self.ss_dx *= -1
        if self.ss_y > 430 or self.ss_y < 50: self.ss_dy *= -1
        self.ss_canvas.coords(self.ss_text, self.ss_x, self.ss_y)
        t_str = datetime.datetime.now().strftime("%I:%M %p")
        self.ss_canvas.itemconfig(self.ss_text, text=t_str[1:] if t_str.startswith("0") else t_str)
        self.root.after(50, self._animate_screensaver)

    def _build_study_ui(self):
        f = tk.Frame(self.root, bg="#050505")
        f.place(x=0, y=0, relwidth=1, relheight=1)
        self.frames["study"] = f
        eng = tk.Frame(f, bg="#050505", width=350)
        eng.pack(side="left", fill="y", padx=20, pady=20)
        eng.pack_propagate(False)
        
        tk.Button(eng, text="< ABORT", font=self.font_body, bg="#1a1a1a", fg="#ff4444", bd=0, command=self.study._exit_study).pack(anchor="w")
        tk.Label(eng, text="Hello Parth Chhabra,", font=self.font_sub, fg="#88aaff", bg="#050505", anchor="w").pack(fill="x", pady=(20,0))
        self.ring_canvas = tk.Canvas(eng, width=200, height=200, bg="#050505", highlightthickness=0)
        self.ring_canvas.pack(pady=10)
        self.lbl_timer = tk.Label(eng, text="00:00:00", font=("Helvetica", 40, "bold"), fg="#fff", bg="#050505")
        self.lbl_timer.place(relx=0.5, rely=0.45, anchor="center")
        self.lbl_target = tk.Label(eng, text="Target: None", font=self.font_body, fg="#888", bg="#050505")
        self.lbl_target.place(relx=0.5, rely=0.65, anchor="center")

        ctrl_frame = tk.Frame(eng, bg="#050505")
        ctrl_frame.pack(fill="x", pady=10)
        self.btn_subj = tk.Button(ctrl_frame, text="Maths", font=("Helvetica", 10, "bold"), bg="#1a1a1a", fg="#fff", bd=0, command=self._trigger_subj_modal)
        self.btn_subj.pack(side="left", fill="x", expand=True, padx=5, ipady=8)
        self.btn_dur = tk.Button(ctrl_frame, text="Set Time", font=("Helvetica", 10, "bold"), bg="#1a1a1a", fg="#fff", bd=0, command=self._trigger_dur_modal)
        self.btn_dur.pack(side="left", fill="x", expand=True, padx=5, ipady=8)
        self.btn_toggle_timer = tk.Button(eng, text="START SPRINT", font=self.font_sub, bg="#1db954", fg="#fff", bd=0, command=self.study.toggle_timer)
        self.btn_toggle_timer.pack(fill="x", ipady=12)

        tsk = tk.Frame(f, bg="#121212")
        tsk.pack(side="right", fill="both", expand=True, padx=20, pady=20)
        self.heatmap_canvas = tk.Canvas(tsk, height=120, bg="#121212", highlightthickness=0)
        self.heatmap_canvas.pack(fill="x", padx=10, pady=10)
        self.history_list_canvas = tk.Canvas(tsk, bg="#121212", highlightthickness=0, height=80)
        self.history_list_canvas.pack(fill="x", padx=10, pady=(0, 10))
        self.study.draw_visceral_ring(360, "#333333")

        f_abs = tk.Frame(self.root, bg="#000000")
        f_abs.place(x=0, y=0, relwidth=1, relheight=1)
        self.frames["study_absolute"] = f_abs
        self.abs_canvas = tk.Canvas(f_abs, bg="#000000", highlightthickness=0)
        self.abs_canvas.pack(fill="both", expand=True)
        self.abs_text = self.abs_canvas.create_text(400, 240, text="00:00:00", font=("Helvetica", 90, "bold"), fill="#1db954")
        self.abs_canvas.bind("<Button-1>", lambda e: self.nav_to("study"))

    def _shuffle_abs_position(self):
        if self.current_frame == "study_absolute":
            self.abs_canvas.coords(self.abs_text, random.randint(220, 580), random.randint(120, 360))
        self.root.after(random.randint(60000, 120000), self._shuffle_abs_position)

    def _trigger_subj_modal(self): TouchModal(self.root, "Select Subject", ["Maths", "Physics", "Ochem", "Pchem", "Ichem", "Other"], lambda s: (self.current_subject.set(s), self.btn_subj.config(text=s)))
    def _trigger_dur_modal(self):
        opts = {"30 Mins": 1800, "45 Mins": 2700, "1 Hr": 3600, "1 Hr 30 Mins": 5400, "2 Hrs": 7200}
        TouchModal(self.root, "Select Duration", list(opts.keys()), lambda s: (setattr(self, 'total_target_seconds', opts[s]), self.lbl_target.config(text=f"Target: {s}")))

    def _render_github_heatmap(self):
        if getattr(self, 'firebase_active', False): self.study._render_github_heatmap()

    def _build_spotify_ui(self):
        f = tk.Frame(self.root, bg="#121212")
        f.place(x=0, y=0, relwidth=1, relheight=1)
        self.frames["spotify"] = f
        if not self.spotify.sp:
            tk.Label(f, text="Auth Missing", font=self.font_header, fg="#ff4444", bg="#121212").pack(pady=150)
            return
        top = tk.Frame(f, bg="#121212", height=40)
        top.pack(fill="x", padx=10, pady=5)
        tk.Button(top, text="< BACK", font=self.font_body, bg="#121212", fg="#fff", bd=0, command=lambda: self.nav_to("main")).pack(side="left")
        self.vinyl_canvas = tk.Canvas(f, width=350, height=350, bg="#121212", highlightthickness=0)
        self.vinyl_canvas.pack(side="left", padx=30)
        ctrl = tk.Frame(f, bg="#121212")
        ctrl.pack(side="left", fill="both", expand=True, padx=20)
        self.lbl_track = tk.Label(ctrl, text="Loading...", font=self.font_header, fg="#fff", bg="#121212", anchor="w")
        self.lbl_track.pack(fill="x", pady=(20,0))
        self.lbl_artist = tk.Label(ctrl, text="", font=self.font_sub, fg="#1db954", bg="#121212", anchor="w")
        self.lbl_artist.pack(fill="x")
        btn = tk.Frame(ctrl, bg="#121212")
        btn.pack(pady=20)
        self.btn_play = tk.Button(btn, text="▶", font=("Helvetica", 24), bg="#1db954", fg="#fff", bd=0, command=self.spotify._sp_play_pause, width=3)
        self.btn_play.pack()

    def _build_settings_ui(self):
        f = tk.Frame(self.root, bg="#121212")
        f.place(x=0, y=0, relwidth=1, relheight=1)
        self.frames["settings"] = f
        top = tk.Frame(f, bg="#121212", height=40)
        top.pack(fill="x", padx=10, pady=10)
        tk.Button(top, text="< BACK", font=self.font_body, bg="#121212", fg="#fff", bd=0, command=lambda: self.nav_to("main")).pack(side="left")
        
        wifi_frame = tk.Frame(f, bg="#121212")
        wifi_frame.pack(side="left", fill="both", expand=True, padx=20)
        self.btn_wifi_sel = tk.Button(wifi_frame, text="Select Wi-Fi", font=self.font_sub, bg="#1a1a1a", fg="#fff", bd=0, command=self._trigger_wifi_modal)
        self.btn_wifi_sel.pack(fill="x", pady=10, ipady=15)
        self.entry_pass = tk.Entry(wifi_frame, font=self.font_header, bg="#0a0a0a", fg="#fff", bd=0, show="*")
        self.entry_pass.pack(fill="x", pady=10, ipady=5)
        
        right_frame = tk.Frame(f, bg="#121212")
        right_frame.pack(side="right", fill="both", expand=True, padx=20)
        self.kbd_container = tk.Frame(right_frame, bg="#121212")
        self.kbd_container.pack(fill="both", expand=True)
        self._build_osk()

    def _build_osk(self):
        for w in self.kbd_container.winfo_children(): w.destroy()
        keys = [['1','2','3','4','5','6','7','8','9','0'], ['q','w','e','r','t','y','u','i','o','p'], ['a','s','d','f','g','h','j','k','l','DEL'], ['CAPS','z','x','c','v','b','n','m','_','@']]
        for r, row in enumerate(keys):
            self.kbd_container.rowconfigure(r, weight=1)
            for c, key in enumerate(row):
                self.kbd_container.columnconfigure(c, weight=1)
                text = key.upper() if self.caps_lock_active and key not in ["DEL","CAPS"] else key
                bg = "#1a2a4a" if key == "CAPS" and self.caps_lock_active else "#1a1a1a"
                tk.Button(self.kbd_container, text=text, font=self.font_sub, bg=bg, fg="#fff", bd=0, command=lambda k=key: self._osk_press(k)).grid(row=r, column=c, sticky="nsew", padx=2, pady=2)

    def _osk_press(self, key):
        if key == "DEL": self.entry_pass.delete(len(self.entry_pass.get())-1, tk.END)
        elif key == "CAPS": self.caps_lock_active = not self.caps_lock_active; self._build_osk()
        else: self.entry_pass.insert(tk.END, key.upper() if self.caps_lock_active else key)

    def _build_system_ui(self): pass
    def _build_logs_ui(self): pass
    def _build_diagnostics_ui(self): pass
    def _animate_vinyl(self): self.spotify.animate_vinyl()
    def wake_display(self): pass
    def sleep_display(self): pass
    def kill_active_processes(self): pass
    def _show_power_menu(self): pass
    def _trigger_wifi_modal(self): pass
    def _connect_wifi(self): pass
    def _exec_ota(self): pass
    def touch_listener(self): pass

    def run(self): self.root.mainloop()

if __name__ == "__main__":
    app = MatterDeskCore()
    app.run()