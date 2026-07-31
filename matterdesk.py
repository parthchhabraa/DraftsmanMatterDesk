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
import socket
import math
import random

# --- System Paths ---
BACKLIGHT_POWER = '/sys/class/backlight/10-0045/bl_power'
BACKLIGHT_BRIGHT = '/sys/class/backlight/10-0045/brightness'
TOUCH_DEVICE = '/dev/input/event4'
LOGO_IMG_PATH = '/home/st6b/matterdesk/images/logo.png'
FIREBASE_KEY_PATH = '/home/st6b/matterdesk/serviceAccountKey.json'
GITHUB_REPO_URL = 'https://github.com/parthchhabraa/DraftsmanMatterDesk.git'

# --- API Context ---
SPOTIFY_CLIENT_ID = '515b520ddd7b4ed2a33fdd1091c9ef00'
SPOTIFY_CLIENT_SECRET = 'e24611ecfa1c4be2b28c1d59e40af0b8'
SPOTIFY_REDIRECT_URI = 'http://127.0.0.1:8080/callback'
SPOTIFY_CACHE_PATH = '/home/st6b/matterdesk/.cache'

# --- Local Data Files (new apps) ---
DATA_DIR = '/home/st6b/matterdesk/data'
NOTES_FILE = f'{DATA_DIR}/notes.json'
FLASHCARDS_FILE = f'{DATA_DIR}/flashcards.json'
TASKS_FILE = f'{DATA_DIR}/tasks.json'
COUNTDOWN_FILE = f'{DATA_DIR}/countdown.json'

# --- DPN / Network Hardware Configuration ---
# EDIT THESE TWO LINES to match your actual hardware if the guess below is wrong.
# DPN_AP_IFACE  = the interface that BROADCASTS the DPN hotspot (recommend: your TP-Link adapter)
# DPN_WAN_IFACE = the interface that connects OUT to your home router (recommend: the Pi's onboard wifi)
DPN_AP_IFACE = 'wlan1'
DPN_WAN_IFACE = 'wlan0'
WG_IFACE = 'wg0'
HOSTAPD_CONF = '/etc/hostapd/hostapd.conf'
DNSMASQ_CONF = '/etc/dnsmasq.d/dpn.conf'
DNSMASQ_LEASES = '/var/lib/misc/dnsmasq.leases'

# Very small best-effort OUI -> vendor table for the network mapper. Not exhaustive.
OUI_VENDORS = {
    "B8:27:EB": "Raspberry Pi Foundation", "DC:A6:32": "Raspberry Pi Foundation", "E4:5F:01": "Raspberry Pi Foundation",
    "D8:3A:DD": "Raspberry Pi Foundation", "28:CD:C1": "Raspberry Pi Foundation",
    "AC:84:C6": "TP-Link", "50:C7:BF": "TP-Link", "C4:6E:1F": "TP-Link", "A4:2B:B0": "TP-Link",
    "F0:18:98": "Apple", "3C:22:FB": "Apple", "AC:BC:32": "Apple", "40:B0:34": "Apple", "00:16:CB": "Apple",
    "94:B8:6D": "Samsung", "5C:0A:5B": "Samsung", "A0:07:98": "Samsung",
    "F4:F5:D8": "Google", "00:1A:11": "Google",
    "3C:5A:B4": "Google (Nest)", "18:B4:30": "Google (Nest)",
}

def guess_vendor(mac):
    try:
        prefix = mac.upper()[0:8]
        return OUI_VENDORS.get(prefix, "Unknown")
    except Exception:
        return "Unknown"


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


class ActiveTextProxy:
    """Lets one on-screen keyboard type into whichever of several Text widgets was last tapped."""
    def __init__(self, get_active):
        self.get_active = get_active

    def insert(self, index, text):
        w = self.get_active()
        w.insert(tk.INSERT if hasattr(w, 'index') else tk.END, text)

    def delete(self, a, b=None):
        w = self.get_active()
        try:
            w.delete("insert-1c", "insert")
        except Exception:
            pass


class FlashcardModal(tk.Toplevel):
    def __init__(self, root, app, on_save):
        super().__init__(root)
        self.overrideredirect(True)
        self.geometry("800x480+0+0")
        self.configure(bg="#050505")
        self.attributes('-topmost', True)
        self.on_save = on_save

        tk.Label(self, text="New Flashcard", font=font.Font(size=18, weight="bold"), fg="#88aaff", bg="#050505").pack(pady=(15, 5))
        tk.Label(self, text="Front (Question):", fg="#fff", bg="#050505", font=app.font_body).pack(anchor="w", padx=20)
        self.front = tk.Text(self, height=3, bg="#111111", fg="#fff", font=app.font_body)
        self.front.pack(fill="x", padx=20, pady=5)
        tk.Label(self, text="Back (Answer):", fg="#fff", bg="#050505", font=app.font_body).pack(anchor="w", padx=20)
        self.back = tk.Text(self, height=3, bg="#111111", fg="#fff", font=app.font_body)
        self.back.pack(fill="x", padx=20, pady=5)

        self.active_target = self.front
        self.front.bind("<Button-1>", lambda e: setattr(self, 'active_target', self.front))
        self.back.bind("<Button-1>", lambda e: setattr(self, 'active_target', self.back))

        kbd = tk.Frame(self, bg="#050505")
        kbd.pack(fill="both", expand=True, padx=20, pady=5)
        proxy = ActiveTextProxy(lambda: self.active_target)
        app._build_generic_osk(kbd, proxy)

        btn_row = tk.Frame(self, bg="#050505")
        btn_row.pack(fill="x", padx=20, pady=10)
        tk.Button(btn_row, text="SAVE CARD", font=app.font_sub, bg="#0a2a10", fg="#1db954", bd=0, command=self._save).pack(side="left", ipadx=20, ipady=10)
        tk.Button(btn_row, text="CANCEL", font=app.font_sub, bg="#2a0000", fg="#ff4444", bd=0, command=self.destroy).pack(side="right", ipadx=20, ipady=10)

    def _save(self):
        f_txt = self.front.get("1.0", "end-1c").strip()
        b_txt = self.back.get("1.0", "end-1c").strip()
        if f_txt and b_txt:
            self.on_save(f_txt, b_txt)
        self.destroy()


class MatterDeskCore:
    def __init__(self):
        self.system_logs = []
        self.log("System Initializing - MatterDesk v5.0 (Expanded Deck + Real DPN/Netmap)")
        
        self.root = tk.Tk()
        self.root.overrideredirect(True)
        self.root.attributes('-topmost', True)
        self.root.geometry("800x480+0+0")
        self.root.configure(bg="#050505", cursor="arrow")
        
        # ==========================================
        # 1. CORE STRUCTURAL STATE DECLARATIONS
        # ==========================================
        self.is_asleep = False
        self.prevent_sleep = False
        self.active_process = None 
        self.last_interaction = time.time()
        self.idle_timeout = 600
        self.current_frame = "boot"
        
        # --- Network Graph State Vectors ---
        self.net_history_tx = [0] * 40
        self.net_history_rx = [0] * 40
        self.last_net_bytes_tx = psutil.net_io_counters().bytes_sent
        self.last_net_bytes_rx = psutil.net_io_counters().bytes_recv
        
        # --- DPN State Engine ---
        self.dpn_active = False
        self.dpn_ssid = "Draftsman DPN"
        self.dpn_country = "United States"
        self.dpn_adblock = True
        self.dpn_client_count = 0
        self.dpn_clients = []
        self.dpn_force_vpn = False
        self.dpn_tx_rate = 0.0
        self.dpn_rx_rate = 0.0
        
        # --- Network Mapper State ---
        self.blocked_macs = set()
        self.net_autoscan = True
        
        # --- Keyboard Modification Maps ---
        self.caps_lock_active = False
        
        # --- Study Mechanics State ---
        self.study_active = False
        self.study_seconds = 0
        self.total_target_seconds = 0
        self.current_subject = tk.StringVar(value="Maths")
        self.study_job = None
        
        # --- Graphics Context Allocation ---
        self.font_header = font.Font(family="Helvetica", size=22, weight="bold")
        self.font_sub = font.Font(family="Helvetica", size=14, weight="bold")
        self.font_body = font.Font(family="Helvetica", size=12)
        
        self.frames = {}
        self.bg_image = self._generate_gradient(800, 480, (5, 5, 5), (10, 20, 45))
        
        os.makedirs(DATA_DIR, exist_ok=True)
        
        # ==========================================
        # 2. SUBSYSTEM INTERFACE CONNECTIVITY
        # ==========================================
        self._init_spotify()
        self._init_firebase()
        
        # ==========================================
        # 3. INTERFACE BUILD MATRIX
        # ==========================================
        self._build_boot_ui()
        self._build_ota_ui()
        self._build_standby_ui()
        self._build_main_menu()
        self._build_network_ui()
        self._build_bookmarks_ui()
        self._build_dpn_ui()
        self._build_spotify_ui()
        self._build_study_ui()
        self._build_notes_ui()
        self._build_flashcards_ui()
        self._build_tasks_ui()
        self._build_countdown_ui()
        self._build_settings_ui()
        self._build_logs_ui()
        self._build_diagnostics_ui()
        self._build_system_ui()
        self._build_telemetry_bar()
        self._build_thermal_panic_ui()
        
        # ==========================================
        # 4. RUNTIME THREAD ORCHESTRATION
        # ==========================================
        self.tap_times = []
        self.root.bind("<Button-1>", self._global_tap_handler, add="+")
        
        self.nav_to("boot")
        self.root.after(100, self._animate_boot_screen)
        
        threading.Thread(target=self.touch_listener, daemon=True).start()
        threading.Thread(target=self._hardware_telemetry_loop, daemon=True).start()
        threading.Thread(target=self._weather_telemetry_loop, daemon=True).start()
        threading.Thread(target=self._dpn_telemetry_loop, daemon=True).start()
        threading.Thread(target=self._network_autoscan_loop, daemon=True).start()
        if getattr(self, 'firebase_active', False):
            threading.Thread(target=self._battery_telemetry_loop, daemon=True).start()
            
        self.last_h = self.last_m = self.last_s = ""
        self._clock_tick()
        self._shuffle_abs_position()
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
        self.current_frame = frame_name
        
        if frame_name in ["boot", "ota", "standby", "study_absolute"]:
            self.frames["telemetry_bar"].place_forget()
        else:
            self.frames["telemetry_bar"].place(x=0, y=460, width=800, height=20)
            self.frames["telemetry_bar"].tkraise()
            
        self.vinyl_active = (frame_name == "spotify")
        if self.vinyl_active and getattr(self, 'vinyl_job', None) is None: 
            self._animate_vinyl()
        if frame_name == "study" and getattr(self, 'firebase_active', False): 
            self._render_github_heatmap()
        if frame_name == "countdown":
            self._refresh_countdown()

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
        self.last_interaction = now
        self.tap_times.append(now)
        self.tap_times = [t for t in self.tap_times if now - t < 0.8]
        if len(self.tap_times) >= 3:
            self.tap_times.clear()
            if not self.is_asleep:
                self.sleep_display()

    # ==========================================
    # GENERIC HELPERS: JSON storage + reusable on-screen keyboard
    # ==========================================
    def _load_json(self, path, default):
        try:
            if os.path.exists(path):
                with open(path) as f:
                    return json.load(f)
        except Exception as e:
            self.log(f"JSON load error {path}: {e}")
        return default

    def _save_json(self, path, data):
        try:
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, 'w') as f:
                json.dump(data, f, indent=2)
        except Exception as e:
            self.log(f"JSON save error {path}: {e}")

    def _build_generic_osk(self, container, target_widget):
        """A compact on-screen keyboard that types into any Text widget (or ActiveTextProxy)."""
        keys = [
            ['1', '2', '3', '4', '5', '6', '7', '8', '9', '0'],
            ['q', 'w', 'e', 'r', 't', 'y', 'u', 'i', 'o', 'p'],
            ['a', 's', 'd', 'f', 'g', 'h', 'j', 'k', 'l', 'DEL'],
            ['CAPS', 'z', 'x', 'c', 'v', 'b', 'n', 'm', 'SPACE', 'ENTER']
        ]
        state = {"caps": False}

        def press(k):
            self.last_interaction = time.time()
            if k == "DEL":
                target_widget.delete("insert-1c", "insert")
            elif k == "CAPS":
                state["caps"] = not state["caps"]
                rebuild()
            elif k == "SPACE":
                target_widget.insert(tk.INSERT, " ")
            elif k == "ENTER":
                target_widget.insert(tk.INSERT, "\n")
            else:
                ch = k.upper() if state["caps"] else k
                target_widget.insert(tk.INSERT, ch)

        def rebuild():
            for w in container.winfo_children():
                w.destroy()
            for r, row in enumerate(keys):
                container.rowconfigure(r, weight=1)
                for c, key in enumerate(row):
                    container.columnconfigure(c, weight=1)
                    bg, fg = "#1a1a1a", "#ffffff"
                    if key == "CAPS":
                        bg = "#1a2a4a" if state["caps"] else "#1a1a1a"
                        fg = "#00aaff" if state["caps"] else "#ffffff"
                    if key == "DEL":
                        bg, fg = "#330000", "#ff4444"
                    label = key.upper() if (state["caps"] and len(key) == 1) else key
                    btn = tk.Button(container, text=label, font=font.Font(size=11, weight="bold"), bg=bg, fg=fg, bd=0,
                                     activebackground="#444", command=lambda k=key: press(k))
                    btn.grid(row=r, column=c, sticky="nsew", padx=1, pady=1)
        rebuild()

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
            self.boot_canvas.create_text(400, 200, text="D", font=font.Font(family="Helvetica", size=80, weight="bold"), fill="#ffffff")
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
            self.ota_canvas.create_text(400, 200, text="D", font=font.Font(family="Helvetica", size=80, weight="bold"), fill="#ffffff")
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
    # SYSTEM POWER & TELEMETRY HUB
    # ==========================================
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

    def _cancel_panic(self):
        self.log("Thermal shutdown overridden by user risk authorization.")
        self.thermal_panic = False
        self.nav_to("main")

    def _hardware_telemetry_loop(self):
        while True:
            try:
                time_since_interaction = time.time() - self.last_interaction
                remaining_idle = max(0, self.idle_timeout - time_since_interaction)
                
                up_sec = time.time() - psutil.boot_time()
                up_d = int(up_sec // 86400)
                up_h = int((up_sec % 86400) // 3600)
                up_m = int((up_sec % 3600) // 60)
                up_str = f"UP: {up_d}d {up_h}h" if up_d > 0 else f"UP: {up_h}h {up_m}m"
                
                if not self.is_asleep and not getattr(self, 'prevent_sleep', False):
                    sc_m = int(remaining_idle // 60)
                    sc_s = int(remaining_idle % 60)
                    sleep_str = f"SLEEP: {sc_m:02d}:{sc_s:02d}"
                    if remaining_idle <= 0:
                        self.root.after(0, self.sleep_display)
                else:
                    sleep_str = "SLEEP: WKLK" if getattr(self, 'prevent_sleep', False) else "SLEEP: OFF"
                
                cpu = psutil.cpu_percent()
                ram = psutil.virtual_memory().percent
                
                io_curr_tx = psutil.net_io_counters().bytes_sent
                io_curr_rx = psutil.net_io_counters().bytes_recv
                
                delta_tx = (io_curr_tx - self.last_net_bytes_tx) / 1024.0
                delta_rx = (io_curr_rx - self.last_net_bytes_rx) / 1024.0
                
                self.last_net_bytes_tx = io_curr_tx
                self.last_net_bytes_rx = io_curr_rx
                
                self.net_history_tx.append(delta_tx)
                self.net_history_rx.append(delta_rx)
                self.net_history_tx.pop(0)
                self.net_history_rx.pop(0)
                
                temp_c = 0.0
                try:
                    with open('/sys/class/thermal/thermal_zone0/temp', 'r') as f: temp_c = float(f.read()) / 1000.0
                except: pass
                
                cpu_col = "#ff4444" if cpu > 85 else "#888"
                ram_col = "#ff4444" if ram > 85 else "#888"
                tmp_col = "#ff4444" if temp_c > 75 else ("#ffaa00" if temp_c > 65 else "#888")

                self.root.after(0, lambda c=cpu, r=ram, t=temp_c, u=up_str, s=sleep_str, cc=cpu_col, rc=ram_col, tc=tmp_col: 
                                self._update_telemetry(c, r, t, u, s, cc, rc, tc))
                
                if temp_c >= 82.0 and not self.thermal_panic:
                    self.thermal_panic = True
                    self.panic_countdown = 60
                    self.root.after(0, self._trigger_panic)
            except Exception: pass
            time.sleep(1)

    def _update_telemetry(self, c, r, t, u, s, cc, rc, tc):
        self.lbl_hw_cpu.config(text=f"CPU: {c}%", fg=cc)
        self.lbl_hw_ram.config(text=f"RAM: {r}%", fg=rc)
        self.lbl_hw_up.config(text=u)
        self.lbl_hw_sleep.config(text=s)
        self.lbl_hw_temp.config(text=f"TEMP: {t:.1f}°C", fg=tc)
        
        self.telemetry_graph.delete("all")
        max_val = max(max(self.net_history_tx), max(self.net_history_rx), 1.0)
        
        for i in range(39):
            x1 = i * 3
            x2 = (i + 1) * 3
            y1_tx = 18 - int((self.net_history_tx[i] / max_val) * 16)
            y2_tx = 18 - int((self.net_history_tx[i+1] / max_val) * 16)
            self.telemetry_graph.create_line(x1, y1_tx, x2, y2_tx, fill="#1db954", width=1)
            
            y1_rx = 18 - int((self.net_history_rx[i] / max_val) * 16)
            y2_rx = 18 - int((self.net_history_rx[i+1] / max_val) * 16)
            self.telemetry_graph.create_line(x1, y1_rx, x2, y2_rx, fill="#88aaff", width=1)

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

    # ==========================================
    # MAIN MENU BENTO DESIGN (12-tile grid)
    # ==========================================
    def _build_main_menu(self):
        f = tk.Frame(self.root)
        f.place(x=0, y=0, relwidth=1, relheight=1)
        self.frames["main"] = f
        
        self.home_canvas = tk.Canvas(f, width=800, height=480, highlightthickness=0)
        self.home_canvas.pack(fill="both", expand=True)
        self.home_canvas.create_image(0, 0, image=self.bg_image, anchor="nw")

        self._create_round_rect(self.home_canvas, 20, 20, 320, 220, radius=25, fill="#121212", stipple="gray50")
        self.home_canvas.create_text(40, 50, text="DRAFTSMAN", font=font.Font(family="Helvetica", size=14, weight="bold"), fill="#1db954", anchor="w")
        
        self.clock_f = tk.Canvas(self.home_canvas, width=280, height=60, bg="#121212", highlightthickness=0)
        self.clock_f.place(x=35, y=75)
        c_fnt = font.Font(family="Helvetica", size=48, weight="bold")
        self.c_h_m = self.clock_f.create_text(0, 30, text="00", font=c_fnt, fill="#ffffff", anchor="w")
        self.c_h_o = self.clock_f.create_text(0, -30, text="", font=c_fnt, fill="#ffffff", anchor="w")
        self.clock_f.create_text(65, 27, text=":", font=c_fnt, fill="#777777", anchor="w")
        self.c_m_m = self.clock_f.create_text(85, 30, text="00", font=c_fnt, fill="#ffffff", anchor="w")
        self.c_m_o = self.clock_f.create_text(85, -30, text="", font=c_fnt, fill="#ffffff", anchor="w")
        self.clock_f.create_text(150, 27, text=":", font=c_fnt, fill="#777777", anchor="w")
        self.c_s_m = self.clock_f.create_text(170, 30, text="00", font=c_fnt, fill="#ffffff", anchor="w")
        self.c_s_o = self.clock_f.create_text(170, -30, text="", font=c_fnt, fill="#ffffff", anchor="w")
        self.c_ap = self.clock_f.create_text(245, 38, text="AM", font=font.Font(family="Helvetica", size=16, weight="bold"), fill="#1db954", anchor="w")

        self.greet_id = self.home_canvas.create_text(40, 160, text="Loading...", font=font.Font(family="Helvetica", size=14), fill="#aaaaaa", anchor="w")
        self.home_canvas.create_text(40, 185, text="Parth Chhabra", font=font.Font(family="Helvetica", size=16, weight="bold"), fill="#ffffff", anchor="w")

        self._create_round_rect(self.home_canvas, 20, 240, 320, 440, radius=25, fill="#121212", stipple="gray50")
        self.wx_canvas = tk.Canvas(self.home_canvas, width=280, height=180, bg="#121212", highlightthickness=0)
        self.wx_canvas.place(x=30, y=250)
        self.weather_temp_id = self.wx_canvas.create_text(10, 40, text="--°C", font=font.Font(family="Helvetica", size=45, weight="bold"), fill="#ffffff", anchor="w")
        self.wx_canvas.create_text(10, 100, text="Udaipur, Rajasthan", font=font.Font(family="Helvetica", size=12, weight="bold"), fill="#1db954", anchor="w")
        self.weather_pop_id = self.wx_canvas.create_text(10, 140, text="Precipitation: --%", font=font.Font(family="Helvetica", size=12), fill="#aaaaaa", anchor="w")
        self.weather_desc_id = self.wx_canvas.create_text(10, 160, text="Syncing Meteorology...", font=font.Font(family="Helvetica", size=12), fill="#aaaaaa", anchor="w")
        
        self.rain_particles = []
        self.sun_angle = 0
        self.current_weather_type = "Clear"
        self._animate_weather()

        self._create_round_rect(self.home_canvas, 340, 20, 780, 200, radius=25, fill="#121212", stipple="gray50")
        self.batt_ui = {}
        devices = ["iPhone", "MacBook", "iPad"]
        for i, dev in enumerate(devices):
            y_offset = 55 + (i * 45)
            self.home_canvas.create_text(370, y_offset, text=dev, font=font.Font(family="Helvetica", size=12, weight="bold"), fill="#fff", anchor="w")
            self.home_canvas.create_rectangle(480, y_offset-8, 720, y_offset+8, fill="#222222", outline="")
            bar_id = self.home_canvas.create_rectangle(480, y_offset-8, 480, y_offset+8, fill="#ffffff", outline="")
            text_id = self.home_canvas.create_text(750, y_offset, text="--%", font=font.Font(family="Helvetica", size=12), fill="#aaa", anchor="e")
            self.batt_ui[dev.lower()] = {"bar": bar_id, "text": text_id}

        # 12-tile app grid: 4 columns x 3 rows, fits below the battery card and above the telemetry bar.
        apps = [
            ("AirPlay", "#1a1a1a", "#fff", self.launch_uxplay),
            ("Spotify", "#0a2a10", "#1db954", lambda: self.nav_to("spotify")),
            ("Study", "#12123a", "#88aaff", lambda: self.nav_to("study")),
            ("Network", "#2a1a3a", "#aa88ff", lambda: self._trigger_netscan()),
            ("Bookmarks", "#3a1a1a", "#ff88aa", lambda: self.nav_to("bookmarks")),
            ("DPN VPN", "#112233", "#00aaff", lambda: self.nav_to("dpn")),
            ("Notes", "#2a2a10", "#ffcc66", lambda: self.nav_to("notes")),
            ("Flashcards", "#0a0a2a", "#88aaff", lambda: self.nav_to("flashcards")),
            ("Tasks", "#0a1a0a", "#1db954", lambda: self.nav_to("tasks")),
            ("Countdown", "#2a0a0a", "#ff8888", lambda: self.nav_to("countdown")),
            ("Settings", "#222222", "#ddd", lambda: self.nav_to("settings")),
            ("Power", "#2a0000", "#ff4444", self._show_power_menu)
        ]
        
        self.app_hitboxes = []
        cols = 4
        tile_w, tile_h = 96, 68
        gap_x, gap_y = 8, 8
        start_x, start_y = 340, 220
        for i, (name, bg, fg, cmd) in enumerate(apps):
            col = i % cols
            row = i // cols
            x1 = start_x + col * (tile_w + gap_x)
            y1 = start_y + row * (tile_h + gap_y)
            x2 = x1 + tile_w
            y2 = y1 + tile_h
            
            self._create_round_rect(self.home_canvas, x1, y1, x2, y2, radius=12, fill=bg)
            self.home_canvas.create_text((x1+x2)//2, (y1+y2)//2, text=name, font=font.Font(family="Helvetica", size=10, weight="bold"), fill=fg, justify="center")
            self.app_hitboxes.append((x1, y1, x2, y2, cmd))
            
        self.home_canvas.bind("<Button-1>", self._handle_home_click)

    def _handle_home_click(self, event):
        self.last_interaction = time.time()
        for x1, y1, x2, y2, cmd in self.app_hitboxes:
            if x1 <= event.x <= x2 and y1 <= event.y <= y2:
                cmd()
                break

    # --- Active Clock Processing ---
    def _clock_tick(self):
        now = datetime.datetime.now()
        h = now.strftime("%I")
        if h.startswith("0"): h = h[1:]
        m = now.strftime("%M")
        s = now.strftime("%S")
        ap = now.strftime("%p")
        
        if self.last_h != h: self._slide_part('h', self.c_h_m, self.c_h_o, self.last_h, h)
        if self.last_m != m: self._slide_part('m', self.c_m_m, self.c_m_o, self.last_m, m)
        if self.last_s != s: self._slide_part('s', self.c_s_m, self.c_s_o, self.last_s, s)
        
        self.clock_f.itemconfig(self.c_ap, text=ap)
        self.last_h, self.last_m, self.last_s = h, m, s
        hr24 = now.hour
        if hr24 < 12: greet = "Good morning,"
        elif hr24 < 17: greet = "Good afternoon,"
        else: greet = "Good evening,"
        self.home_canvas.itemconfig(self.greet_id, text=greet)
        self.root.after(1000, self._clock_tick)

    def _slide_part(self, p_type, m_id, o_id, old_val, new_val):
        self.clock_f.itemconfig(o_id, text=old_val)
        self.clock_f.itemconfig(m_id, text=new_val)
        x_coord = 0 if p_type == 'h' else (85 if p_type == 'm' else 170)
        self.clock_f.coords(o_id, x_coord, 30)
        self.clock_f.coords(m_id, x_coord, 80)
        self._animate_slide_part(m_id, o_id, 0)
        
    def _animate_slide_part(self, m_id, o_id, step):
        if step > 50: return
        self.clock_f.move(o_id, 0, -5)
        self.clock_f.move(m_id, 0, -5)
        self.root.after(10, self._animate_slide_part, m_id, o_id, step + 5)

    def _animate_weather(self):
        if getattr(self, 'current_frame', '') != "main":
            self.root.after(50, self._animate_weather)
            return
        if self.current_weather_type == "Rain":
            self.wx_canvas.delete("sun")
            if len(self.rain_particles) < 20:
                self.rain_particles.append([int(time.time() * 1000) % 200 + 150, 0, 2 + (time.time() % 3)])
            self.wx_canvas.delete("rain")
            for p in self.rain_particles:
                p[1] += p[2]
                if p[1] > 180:
                    p[1] = 0
                    p[0] = int(time.time() * 1000) % 200 + 150
                self.wx_canvas.create_line(p[0], p[1], p[0] - 2, p[1] + 10, fill="#88aaff", tags="rain")
        elif self.current_weather_type == "Clear":
            self.wx_canvas.delete("rain")
            self.wx_canvas.delete("sun")
            self.sun_angle = (self.sun_angle + 1) % 360
            cx, cy = 230, 50
            self.wx_canvas.create_oval(cx-15, cy-15, cx+15, cy+15, fill="#ffaa00", outline="", tags="sun")
            for i in range(0, 360, 45):
                rad = math.radians(i + self.sun_angle)
                x1, y1 = cx + 20 * math.cos(rad), cy + 20 * math.sin(rad)
                x2, y2 = cx + 30 * math.cos(rad), cy + 30 * math.sin(rad)
                self.wx_canvas.create_line(x1, y1, x2, y2, fill="#ffaa00", width=2, tags="sun", capstyle=tk.ROUND)
        self.root.after(50, self._animate_weather)

    def _weather_telemetry_loop(self):
        while True:
            try:
                url = "https://api.open-meteo.com/v1/forecast?latitude=24.5854&longitude=73.6855&current=temperature_2m,precipitation_probability,weather_code&timezone=Asia%2FKolkata"
                res = requests.get(url, timeout=10).json()
                temp = round(res["current"]["temperature_2m"])
                pop = res["current"]["precipitation_probability"]
                code = res["current"]["weather_code"]
                desc = "Clear"
                self.current_weather_type = "Clear"
                if code in [1, 2, 3]: desc = "Partly Cloudy"
                elif code in [45, 48]: desc = "Fog"
                elif code in [51, 53, 55, 61, 63, 65, 80, 81, 82]:
                    desc = "Rain"
                    self.current_weather_type = "Rain"
                elif code in [95, 96, 99]: 
                    desc = "Thunderstorm"
                    self.current_weather_type = "Rain"
                self.root.after(0, lambda t=temp, p=pop, d=desc: self._update_weather_ui(t, p, d))
            except Exception as e: self.log(f"Weather Fetch Error: {e}")
            time.sleep(900) 

    def _update_weather_ui(self, temp, pop, desc):
        self.wx_canvas.itemconfig(self.weather_temp_id, text=f"{temp}°C")
        self.wx_canvas.itemconfig(self.weather_pop_id, text=f"Precipitation: {pop}%")
        self.wx_canvas.itemconfig(self.weather_desc_id, text=desc)

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
                
                base_x = 480
                max_width = 240
                
                width = int((val / 100.0) * max_width)
                self.home_canvas.coords(self.batt_ui[ui_key]["bar"], base_x, self.home_canvas.coords(self.batt_ui[ui_key]["bar"])[1], base_x + width, self.home_canvas.coords(self.batt_ui[ui_key]["bar"])[3])
                
                if val >= 70:
                    col = "#1db954"       
                    range_col = "#0e4419" 
                elif val >= 30:
                    col = "#88aaff"       
                    range_col = "#223355" 
                else:
                    col = "#ff4444"       
                    range_col = "#4a1111" 
                
                self.home_canvas.itemconfig(self.batt_ui[ui_key]["bar"], fill=col)
                
                range_tag = f"range_{ui_key}"
                self.home_canvas.delete(range_tag)
                
                if val < 100:
                    r_start_x = base_x + int((lower / 100.0) * max_width)
                    r_end_x = base_x + int((upper / 100.0) * max_width)
                    y_coords = self.home_canvas.coords(self.batt_ui[ui_key]["bar"])
                    
                    range_bar_id = self.home_canvas.create_rectangle(r_start_x, y_coords[1], r_end_x, y_coords[3], fill=range_col, outline="", tags=range_tag)
                    self.home_canvas.tag_lower(range_bar_id, self.batt_ui[ui_key]["bar"])
                
                display_str = f"~{midpoint}%" if val < 100 else "100%"
                self.home_canvas.itemconfig(self.batt_ui[ui_key]["text"], text=display_str)

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
    # DPN DECENTRALIZED PRIVATE NETWORK SUBSYSTEM (now functional)
    # ==========================================
    def _build_dpn_ui(self):
        f = tk.Frame(self.root, bg="#0b0f19")
        f.place(x=0, y=0, relwidth=1, relheight=1)
        self.frames["dpn"] = f
        
        top = tk.Frame(f, bg="#111625", height=50)
        top.pack(fill="x")
        tk.Button(top, text="< BACK", font=self.font_body, bg="#111625", fg="#fff", bd=0, command=lambda: self.nav_to("main")).pack(side="left", padx=10)
        tk.Label(top, text="DRAFTSMAN DPN ARCHITECTURE", font=self.font_sub, fg="#00aaff", bg="#111625").pack(side="right", padx=20)
        
        left_p = tk.Frame(f, bg="#0b0f19", width=380)
        left_p.pack(side="left", fill="both", expand=True, padx=20, pady=20)
        left_p.pack_propagate(False)
        
        self.lbl_dpn_status = tk.Label(left_p, text="NETWORK STATE: OFFLINE", font=self.font_sub, fg="#ff4444", bg="#0b0f19", anchor="w")
        self.lbl_dpn_status.pack(fill="x", pady=5)
        
        self.btn_dpn_toggle = tk.Button(left_p, text="ACTIVATE DPN CORE", font=self.font_sub, bg="#1a2a4a", fg="#00aaff", bd=0, command=self._toggle_dpn_engine)
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

        f_vpn = tk.Frame(cfg_box, bg="#0b0f19")
        f_vpn.pack(fill="x", padx=10, pady=5)
        tk.Label(f_vpn, text="Force Traffic via WireGuard:", font=self.font_body, fg="#fff", bg="#0b0f19").pack(side="left")
        self.btn_dpn_forcevpn = tk.Button(f_vpn, text="OFF", font=self.font_body, bg="#333333", fg="#aaaaaa", bd=0, command=self._toggle_force_vpn)
        self.btn_dpn_forcevpn.pack(side="right", padx=5)

        tk.Label(cfg_box, text=f"AP iface: {DPN_AP_IFACE}   WAN iface: {DPN_WAN_IFACE}\n(edit at top of matterdesk.py if wrong)",
                 font=font.Font(size=9), fg="#555", bg="#0b0f19", justify="left").pack(anchor="w", padx=10, pady=(10, 0))

        right_p = tk.Frame(f, bg="#111625")
        right_p.pack(side="right", fill="both", expand=True, padx=20, pady=20)
        
        tk.Label(right_p, text="ACTIVE CRYPTO CHANNELS", font=self.font_body, fg="#888", bg="#111625").pack(anchor="w", padx=15, pady=10)
        self.dpn_monitor_canvas = tk.Canvas(right_p, bg="#050505", highlightthickness=0)
        self.dpn_monitor_canvas.pack(fill="both", expand=True, padx=15, pady=(0, 15))
        self._render_dpn_canvas()

    def _render_dpn_canvas(self):
        self.dpn_monitor_canvas.delete("all")
        if not self.dpn_active:
            self.dpn_monitor_canvas.create_text(180, 100, text="Tunnel Array Offline\nWaiting for Core Ignition Sequence...", fill="#444", font=self.font_body, justify="center")
            return

        uplink = WG_IFACE if self.dpn_force_vpn else DPN_WAN_IFACE
        self.dpn_monitor_canvas.create_text(20, 25, text=f"● AP Interface: {DPN_AP_IFACE} ({self.dpn_ssid})", fill="#1db954", font=self.font_body, anchor="w")
        self.dpn_monitor_canvas.create_text(20, 50, text=f"● WAN Uplink: {uplink}", fill="#1db954", font=self.font_body, anchor="w")
        self.dpn_monitor_canvas.create_text(20, 75, text="● Secure Node IP: 10.45.0.1", fill="#00aaff", font=self.font_body, anchor="w")
        self.dpn_monitor_canvas.create_text(20, 100, text=f"● Throughput: ↑{self.dpn_tx_rate:.1f} KB/s   ↓{self.dpn_rx_rate:.1f} KB/s", fill="#fff", font=self.font_body, anchor="w")
        self.dpn_monitor_canvas.create_text(20, 130, text=f"Active Clients ({self.dpn_client_count}):", fill="#888", font=self.font_sub, anchor="w")
        y = 155
        for c in self.dpn_clients[:6]:
            self.dpn_monitor_canvas.create_text(30, y, text=f"{c['host']:<16} {c['ip']:<14} {c['mac']}", fill="#aaaaaa", font=font.Font(family="Courier", size=10), anchor="w")
            y += 22
        if not self.dpn_clients:
            self.dpn_monitor_canvas.create_text(30, y, text="No clients associated yet.", fill="#555", font=self.font_body, anchor="w")

    def _toggle_dpn_engine(self):
        self.last_interaction = time.time()
        if self.dpn_active:
            self.log("DPN Decoupling Sequence Initiated.")
            self.dpn_active = False
            self.lbl_dpn_status.config(text="NETWORK STATE: STOPPING...", fg="#ffaa00")
            self.btn_dpn_toggle.config(text="ACTIVATE DPN CORE", bg="#1a2a4a", fg="#00aaff")
            threading.Thread(target=self._dpn_stop_worker, daemon=True).start()
        else:
            self.lbl_dpn_status.config(text="NETWORK STATE: STARTING...", fg="#ffaa00")
            self.btn_dpn_toggle.config(text="STARTING...", bg="#333333", fg="#aaaaaa")
            threading.Thread(target=self._dpn_start_worker, daemon=True).start()

    def _write_dpn_configs(self):
        """Generates hostapd/dnsmasq config for the AP interface. Requires hostapd+dnsmasq installed."""
        hostapd_conf = (
            f"interface={DPN_AP_IFACE}\n"
            "driver=nl80211\n"
            f"ssid={self.dpn_ssid}\n"
            "hw_mode=g\n"
            "channel=6\n"
            "wmm_enabled=1\n"
            "macaddr_acl=0\n"
            "auth_algs=1\n"
            "ignore_broadcast_ssid=0\n"
            "wpa=2\n"
            "wpa_passphrase=draftsmandpn123\n"
            "wpa_key_mgmt=WPA-PSK\n"
            "rsn_pairwise=CCMP\n"
        )
        with open('/tmp/dpn_hostapd.conf', 'w') as fh:
            fh.write(hostapd_conf)
        os.system(f"sudo cp /tmp/dpn_hostapd.conf {HOSTAPD_CONF}")

        dnsmasq_conf = (
            f"interface={DPN_AP_IFACE}\n"
            "dhcp-range=10.45.0.10,10.45.0.100,12h\n"
            "dhcp-option=3,10.45.0.1\n"
            "dhcp-option=6,10.45.0.1\n"
        )
        if self.dpn_adblock:
            dnsmasq_conf += "address=/doubleclick.net/0.0.0.0\naddress=/googlesyndication.com/0.0.0.0\naddress=/googleadservices.com/0.0.0.0\n"
        with open('/tmp/dpn_dnsmasq.conf', 'w') as fh:
            fh.write(dnsmasq_conf)
        os.system(f"sudo cp /tmp/dpn_dnsmasq.conf {DNSMASQ_CONF}")

        os.system(f"sudo ip addr flush dev {DPN_AP_IFACE} > /dev/null 2>&1")
        os.system(f"sudo ip addr add 10.45.0.1/24 dev {DPN_AP_IFACE} > /dev/null 2>&1")
        os.system(f"sudo ip link set {DPN_AP_IFACE} up > /dev/null 2>&1")
        self.log("DPN hostapd/dnsmasq configs written and applied.")

    def _apply_dpn_nat(self, enable):
        uplink = WG_IFACE if self.dpn_force_vpn else DPN_WAN_IFACE
        if enable:
            os.system("sudo sysctl -w net.ipv4.ip_forward=1 > /dev/null 2>&1")
            os.system(f"sudo iptables -t nat -A POSTROUTING -o {uplink} -j MASQUERADE")
            os.system(f"sudo iptables -A FORWARD -i {DPN_AP_IFACE} -o {uplink} -j ACCEPT")
            os.system(f"sudo iptables -A FORWARD -i {uplink} -o {DPN_AP_IFACE} -m state --state RELATED,ESTABLISHED -j ACCEPT")
        else:
            os.system(f"sudo iptables -t nat -D POSTROUTING -o {uplink} -j MASQUERADE > /dev/null 2>&1")
            os.system(f"sudo iptables -D FORWARD -i {DPN_AP_IFACE} -o {uplink} -j ACCEPT > /dev/null 2>&1")
            os.system(f"sudo iptables -D FORWARD -i {uplink} -o {DPN_AP_IFACE} -m state --state RELATED,ESTABLISHED -j ACCEPT > /dev/null 2>&1")

    def _dpn_start_worker(self):
        try:
            self._write_dpn_configs()
            os.system("sudo systemctl unmask hostapd > /dev/null 2>&1")
            os.system("sudo systemctl restart dnsmasq")
            os.system("sudo systemctl restart hostapd")
            if self.dpn_force_vpn:
                os.system(f"sudo wg-quick up {WG_IFACE} > /dev/null 2>&1")
            self._apply_dpn_nat(True)
            self.dpn_active = True
            self.root.after(0, lambda: (
                self.lbl_dpn_status.config(text="NETWORK STATE: ROUTED", fg="#1db954"),
                self.btn_dpn_toggle.config(text="DEACTIVATE DPN CORE", bg="#3a1a1a", fg="#ff4444"),
                self._render_dpn_canvas()
            ))
            self.log("DPN Hardware Tunnel Matrix Ignited.")
        except Exception as e:
            self.log(f"DPN start failed: {e}")
            self.root.after(0, lambda: (
                self.lbl_dpn_status.config(text="NETWORK STATE: ERROR", fg="#ff4444"),
                self.btn_dpn_toggle.config(text="ACTIVATE DPN CORE", bg="#1a2a4a", fg="#00aaff")
            ))

    def _dpn_stop_worker(self):
        try:
            self._apply_dpn_nat(False)
            os.system("sudo systemctl stop hostapd dnsmasq")
            if self.dpn_force_vpn:
                os.system(f"sudo wg-quick down {WG_IFACE} > /dev/null 2>&1")
            self.dpn_client_count = 0
            self.dpn_clients = []
            self.root.after(0, lambda: (
                self.lbl_dpn_status.config(text="NETWORK STATE: OFFLINE", fg="#ff4444"),
                self._render_dpn_canvas()
            ))
            self.log("DPN core fully offline.")
        except Exception as e:
            self.log(f"DPN stop failed: {e}")

    def _dpn_telemetry_loop(self):
        last_tx = last_rx = None
        while True:
            try:
                if self.dpn_active:
                    clients = []
                    if os.path.exists(DNSMASQ_LEASES):
                        with open(DNSMASQ_LEASES) as fh:
                            for line in fh:
                                parts = line.split()
                                if len(parts) >= 4:
                                    clients.append({'mac': parts[1], 'ip': parts[2], 'host': parts[3] if parts[3] != '*' else 'unknown'})
                    self.dpn_client_count = len(clients)
                    self.dpn_clients = clients
                    counters = psutil.net_io_counters(pernic=True).get(DPN_AP_IFACE)
                    if counters:
                        if last_tx is not None:
                            self.dpn_tx_rate = max(0.0, (counters.bytes_sent - last_tx) / 1024.0 / 5.0)
                            self.dpn_rx_rate = max(0.0, (counters.bytes_recv - last_rx) / 1024.0 / 5.0)
                        last_tx, last_rx = counters.bytes_sent, counters.bytes_recv
                    self.root.after(0, self._render_dpn_canvas)
            except Exception:
                pass
            time.sleep(5)

    def _toggle_force_vpn(self):
        self.dpn_force_vpn = not self.dpn_force_vpn
        if self.dpn_force_vpn:
            self.btn_dpn_forcevpn.config(text="ON (WireGuard)", bg="#0a2a10", fg="#1db954")
        else:
            self.btn_dpn_forcevpn.config(text="OFF", bg="#333333", fg="#aaaaaa")
        self.log(f"DPN uplink preference set to {'WireGuard tunnel' if self.dpn_force_vpn else 'direct WAN'}. Restart DPN core to apply.")

    def _change_dpn_ssid(self):
        TouchModal(self.root, "Select Broadcast Network SSID", ["Draftsman DPN", "Project Resonance AP", "Xeno Vault Mesh"], 
                   lambda s: (setattr(self, 'dpn_ssid', s), self.btn_dpn_ssid.config(text=s), self._render_dpn_canvas()))

    def _select_dpn_country(self):
        TouchModal(self.root, "Select exit wireguard server", ["United States", "Germany", "Singapore", "Japan", "United Kingdom"], 
                   lambda c: (setattr(self, 'dpn_country', c), self.btn_dpn_country.config(text=c), self.log(f"DPN Proxy Node shifted target path -> {c}")))

    def _toggle_dpn_adblock(self):
        self.dpn_adblock = not self.dpn_adblock
        if self.dpn_adblock:
            self.btn_dpn_blk.config(text="ENABLED", bg="#0a2a10", fg="#1db954")
            self.log("Ad/tracker DNS blocklist enabled. Restart DPN core to apply.")
        else:
            self.btn_dpn_blk.config(text="BYPASSED", bg="#333333", fg="#aaaaaa")
            self.log("Ad/tracker DNS blocklist bypassed. Restart DPN core to apply.")

    # ==========================================
    # CROSS-DEVICE BOOKMARKS MODULE
    # ==========================================
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
        devices = ["MacBook", "Workstation", "Server"]
        for d in devices:
            btn = tk.Button(nav_row, text=d.upper(), font=font.Font(size=10, weight="bold"), bg="#1a1a1a", fg="#ff88aa", bd=0, command=lambda dev=d: self._load_device_bookmarks(dev))
            btn.pack(side="left", padx=5, ipady=8, expand=True, fill="x")
            
        self.bm_canvas = tk.Canvas(f, bg="#050505", highlightthickness=0)
        self.bm_canvas.pack(fill="both", expand=True, padx=20, pady=10)
        self._load_device_bookmarks("MacBook")

    def _load_device_bookmarks(self, device):
        self.bm_canvas.delete("all")
        if not getattr(self, 'firebase_active', False):
            self.bm_canvas.create_text(380, 100, text="Firebase Link Dropped.", fill="#ff4444", font=self.font_body)
            return
        
        self.bm_canvas.create_text(20, 20, text=f"Querying nodes for {device}...", fill="#888", font=self.font_body, anchor="w")
        threading.Thread(target=self._fetch_bookmarks_worker, args=(device,), daemon=True).start()

    def _fetch_bookmarks_worker(self, device):
        try:
            node_target = f'telemetry/bookmarks/{device.lower()}'
            raw_data = db.reference(node_target).get()
            
            if isinstance(raw_data, dict):
                links = [raw_data[k] for k in sorted(raw_data.keys())]
            elif isinstance(raw_data, list):
                links = [item for item in raw_data if item is not None]
            else:
                links = []
                
            self.root.after(0, lambda: self._render_bookmarks(links))
        except Exception as e:
            self.root.after(0, lambda: self.bm_canvas.create_text(20, 50, text=f"Fetch Error: {e}", fill="#ff4444", font=self.font_body, anchor="w"))

    def _render_bookmarks(self, links):
        self.bm_canvas.delete("all")
        if not links:
            self.bm_canvas.create_text(20, 30, text="No active bookmarks indexed under this profile node.", fill="#666666", font=self.font_body, anchor="w")
            return
        
        y = 30
        for item in links:
            if not isinstance(item, dict): 
                continue
            title = item.get('title', 'Unknown Tab')
            url = item.get('url', '#')
            
            clean_title = title[:45] + "..." if len(title) > 45 else title
            clean_url = url[:55] + "..." if len(url) > 55 else url
            
            self.bm_canvas.create_text(20, y, text=clean_title, fill="#ffffff", font=self.font_sub, anchor="w")
            self.bm_canvas.create_text(340, y, text=clean_url, fill="#ff88aa", font=font.Font(family="Courier", size=11), anchor="w")
            y += 35

    # ==========================================
    # NETWORK MAPPER (now: ip neigh + vendor guess + block + deep scan)
    # ==========================================
    def _build_network_ui(self):
        f = tk.Frame(self.root, bg="#121212")
        f.place(x=0, y=0, relwidth=1, relheight=1)
        self.frames["network"] = f
        
        top = tk.Frame(f, bg="#121212", height=40)
        top.pack(fill="x", padx=10, pady=10)
        tk.Button(top, text="< BACK", font=self.font_body, bg="#121212", fg="#fff", bd=0, command=lambda: self.nav_to("main")).pack(side="left")
        tk.Label(top, text="NETWORK MAPPER", font=self.font_sub, fg="#aa88ff", bg="#121212").pack(side="left", padx=20)
        self.btn_net_autoscan = tk.Button(top, text="AUTO-SCAN: ON", font=font.Font(size=10, weight="bold"), bg="#0a2a10", fg="#1db954", bd=0, command=self._toggle_net_autoscan)
        self.btn_net_autoscan.pack(side="right", padx=5)
        tk.Button(top, text="DEEP SCAN", font=font.Font(size=10, weight="bold"), bg="#1a2a4a", fg="#88aaff", bd=0, command=self._trigger_deep_scan).pack(side="right", padx=5)
        
        self.net_canvas = tk.Canvas(f, bg="#050505", highlightthickness=0)
        self.net_canvas.pack(fill="both", expand=True, padx=20, pady=10)

    def _toggle_net_autoscan(self):
        self.net_autoscan = not self.net_autoscan
        self.btn_net_autoscan.config(text=f"AUTO-SCAN: {'ON' if self.net_autoscan else 'OFF'}",
                                      bg="#0a2a10" if self.net_autoscan else "#333333",
                                      fg="#1db954" if self.net_autoscan else "#aaaaaa")

    def _trigger_netscan(self):
        self.nav_to("network")
        self.net_canvas.delete("all")
        self.net_canvas.create_text(20, 20, text="Querying kernel neighbor table...", fill="#aaaaaa", font=self.font_body, anchor="w")
        threading.Thread(target=self._exec_network_scan, daemon=True).start()

    def _trigger_deep_scan(self):
        self.net_canvas.delete("all")
        self.net_canvas.create_text(20, 20, text="Running deep nmap sweep (may take up to 30s)...", fill="#aaaaaa", font=self.font_body, anchor="w")
        threading.Thread(target=self._exec_deep_scan, daemon=True).start()

    def _exec_deep_scan(self):
        # Adjust the subnet below if your LAN uses a different range than the DPN's 10.45.0.0/24.
        subnet = "10.45.0.0/24"
        try:
            subprocess.check_output(["nmap", "-sn", subnet], timeout=30)
            self.log("Deep nmap sweep complete.")
        except FileNotFoundError:
            self.log("nmap not installed - run: sudo apt install nmap. Falling back to neighbor table.")
        except Exception as e:
            self.log(f"Deep scan error: {e}")
        self._exec_network_scan()

    def _exec_network_scan(self):
        try:
            output = subprocess.check_output(['ip', 'neigh', 'show']).decode()
            nodes = []
            for line in output.split('\n'):
                if not line.strip() or 'lladdr' not in line:
                    continue
                parts = line.split()
                ip = parts[0]
                mac = parts[parts.index('lladdr') + 1]
                state = parts[-1]
                if state.upper() in ('FAILED', 'INCOMPLETE'):
                    continue
                try:
                    host = socket.gethostbyaddr(ip)[0]
                except Exception:
                    host = "Unknown"
                nodes.append({'ip': ip, 'mac': mac, 'host': host, 'vendor': guess_vendor(mac), 'state': state})
            self.root.after(0, lambda n=nodes: self._render_netscan(n))
        except Exception as e:
            self.root.after(0, lambda: self.net_canvas.create_text(20, 50, text=f"Scan Failed: {e}", fill="#ff4444", font=self.font_body, anchor="w"))

    def _render_netscan(self, nodes):
        self.net_canvas.delete("all")
        if not nodes:
            self.net_canvas.create_text(20, 20, text="No nodes found in the neighbor table.", fill="#aaaaaa", font=self.font_body, anchor="w")
            return

        container = tk.Frame(self.net_canvas, bg="#050505")
        self.net_canvas.create_window((0, 0), window=container, anchor="nw", width=740)
        tk.Label(container, text=f"Discovered {len(nodes)} active nodes:", fg="#aa88ff", bg="#050505", font=self.font_sub, anchor="w").pack(fill="x", pady=(0, 10))
        for n in nodes:
            row = tk.Frame(container, bg="#0a0a0a")
            row.pack(fill="x", pady=2)
            tk.Label(row, text=n['ip'], fg="#1db954", bg="#0a0a0a", font=font.Font(family="Courier", size=11, weight="bold"), width=15, anchor="w").pack(side="left")
            tk.Label(row, text=n['mac'], fg="#aaaaaa", bg="#0a0a0a", font=font.Font(family="Courier", size=11), width=18, anchor="w").pack(side="left")
            tk.Label(row, text=n['vendor'], fg="#88aaff", bg="#0a0a0a", font=self.font_body, width=16, anchor="w").pack(side="left")
            tk.Label(row, text=n['host'][:18], fg="#ffffff", bg="#0a0a0a", font=self.font_body, width=18, anchor="w").pack(side="left")
            blocked = n['mac'].upper() in self.blocked_macs
            tk.Button(row, text="UNBLOCK" if blocked else "BLOCK", font=font.Font(size=9, weight="bold"),
                      bg="#0a2a10" if blocked else "#2a0000", fg="#1db954" if blocked else "#ff4444", bd=0,
                      command=lambda m=n['mac']: self._toggle_block_mac(m)).pack(side="right", padx=5)
        self.net_canvas.update_idletasks()
        self.net_canvas.config(scrollregion=self.net_canvas.bbox("all"))

    def _toggle_block_mac(self, mac):
        key = mac.upper()
        if key in self.blocked_macs:
            os.system(f"sudo iptables -D FORWARD -m mac --mac-source {mac} -j DROP > /dev/null 2>&1")
            self.blocked_macs.discard(key)
            self.log(f"Unblocked {mac} on the forwarding chain.")
        else:
            os.system(f"sudo iptables -I FORWARD -m mac --mac-source {mac} -j DROP")
            self.blocked_macs.add(key)
            self.log(f"Blocked {mac} at the kernel forward chain.")
        self._exec_network_scan()

    def _network_autoscan_loop(self):
        while True:
            if getattr(self, 'current_frame', '') == 'network' and getattr(self, 'net_autoscan', True):
                threading.Thread(target=self._exec_network_scan, daemon=True).start()
            time.sleep(15)

    # ==========================================
    # STANDBY SCREENSAVER MODULE
    # ==========================================
    def _build_standby_ui(self):
        f = tk.Frame(self.root, bg="#000000")
        f.place(x=0, y=0, relwidth=1, relheight=1)
        self.frames["standby"] = f
        self.ss_canvas = tk.Canvas(f, bg="#000000", highlightthickness=0)
        self.ss_canvas.pack(fill="both", expand=True)
        self.ss_text = self.ss_canvas.create_text(400, 240, text="00:00", font=font.Font(family="Helvetica", size=40, weight="bold"), fill="#222222")
        self.ss_x, self.ss_y = 400, 240
        self.ss_dx, self.ss_dy = 2, 2

    def _animate_screensaver(self):
        if not self.is_asleep: return
        self.ss_x += self.ss_dx
        self.ss_y += self.ss_dy
        if self.ss_x > 700 or self.ss_x < 100: self.ss_dx *= -1
        if self.ss_y > 430 or self.ss_y < 50: self.ss_dy *= -1
        self.ss_canvas.coords(self.ss_text, self.ss_x, self.ss_y)
        t_str = datetime.datetime.now().strftime("%I:%M %p")
        if t_str.startswith("0"): t_str = t_str[1:]
        self.ss_canvas.itemconfig(self.ss_text, text=t_str)
        self.root.after(50, self._animate_screensaver)

    # ==========================================
    # STUDY ENGINE & AUTOMATED ABSOLUTE ECO FADE
    # ==========================================
    def _init_firebase(self):
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
        self.history_list_canvas = tk.Canvas(tsk, bg="#121212", highlightthickness=0, height=80)
        self.history_list_canvas.pack(fill="x", padx=10, pady=(0, 10))
        self._draw_visceral_ring(360, "#333333")

        # --- ABSOLUTE FRAME BOUNDING ---
        f_abs = tk.Frame(self.root, bg="#000000")
        f_abs.place(x=0, y=0, relwidth=1, relheight=1)
        self.frames["study_absolute"] = f_abs
        
        self.abs_canvas = tk.Canvas(f_abs, bg="#000000", highlightthickness=0)
        self.abs_canvas.pack(fill="both", expand=True)
        self.abs_text = self.abs_canvas.create_text(400, 240, text="00:00:00", font=font.Font(family="Helvetica", size=90, weight="bold"), fill="#1db954")
        self.abs_canvas.bind("<Button-1>", lambda e: self.nav_to("study"))

    def _draw_visceral_ring(self, extent, color):
        if not hasattr(self, 'ring_canvas') or not self.ring_canvas.winfo_exists():
            return
        self.ring_canvas.delete("ring")
        self.ring_canvas.create_oval(10, 10, 190, 190, outline="#1a1a1a", width=10, tags="ring")
        if extent > 0: 
            self.ring_canvas.create_arc(10, 10, 190, 190, start=90, extent=-extent, outline=color, style=tk.ARC, width=10, tags="ring")

    def _shuffle_abs_position(self):
        if getattr(self, 'current_frame', '') == "study_absolute":
            safe_x = random.randint(220, 580)
            safe_y = random.randint(120, 360)
            self.abs_canvas.coords(self.abs_text, safe_x, safe_y)
            
        next_interval = random.randint(60000, 120000)
        self.root.after(next_interval, self._shuffle_abs_position)

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
            self.prevent_sleep = False
            self.btn_toggle_timer.config(text="START SPRINT", bg="#1db954")
            if self.study_job: self.root.after_cancel(self.study_job)
            if getattr(self, 'firebase_active', False) and self.study_seconds >= 5:
                self.log(f"Initiating Firebase sync for {self.study_seconds}s of {self.current_subject.get()}")
                threading.Thread(target=self._push_session, args=(self.current_subject.get(), self.study_seconds), daemon=True).start()
            else: self.log(f"Session discarded: Only {self.study_seconds}s recorded.")
            self.study_seconds = 0
            self.total_target_seconds = 0
            self.lbl_timer.config(text="00:00:00")
            self.abs_canvas.itemconfig(self.abs_text, text="00:00:00")
            self.lbl_target.config(text="Target: None")
            self._draw_visceral_ring(360, "#333")
        else:
            if self.total_target_seconds == 0:
                self.lbl_target.config(text="SELECT DURATION FIRST", fg="#ff4444")
                self.root.after(2000, lambda: self.lbl_target.config(text="Target: None", fg="#888"))
                return
            self.study_active = True
            self.prevent_sleep = True
            self.log(f"Sprint Started: {self.current_subject.get()} for {self.total_target_seconds}s")
            self.btn_toggle_timer.config(text="END SPRINT", bg="#ff4444")
            self.root.after(10000, self._check_and_enter_absolute)
            self._tick_timer()

    def _check_and_enter_absolute(self):
        if self.study_active and self.current_frame == "study":
            self.nav_to("study_absolute")

    def _tick_timer(self):
        if not getattr(self, 'study_active', False): return
        self.study_seconds += 1
        remaining = max(0, self.total_target_seconds - self.study_seconds)
        h, m, s = remaining // 3600, (remaining % 3600) // 60, remaining % 60
        time_str = f"{h:02d}:{m:02d}:{s:02d}"
        
        self.lbl_timer.config(text=time_str)
        self.abs_canvas.itemconfig(self.abs_text, text=time_str)
        
        ratio = remaining / self.total_target_seconds if self.total_target_seconds else 0
        extent = ratio * 360
        color = "#1db954" if ratio > 0.5 else ("#ffaa00" if ratio > 0.2 else "#ff4444")
        self._draw_visceral_ring(extent, color)
        if remaining <= 0:
            self._toggle_timer()
            self.nav_to("study")
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
            recent_logs = []
            sorted_keys = sorted(sessions.keys(), key=lambda k: sessions[k].get('timestamp', 0))
            for k in sorted_keys:
                data = sessions[k]
                ts = data.get('timestamp', 0)
                date_str = datetime.datetime.fromtimestamp(ts).strftime('%Y-%m-%d')
                daily_totals[date_str] = daily_totals.get(date_str, 0) + data.get('duration_seconds', 0)
                dur_m = data.get('duration_seconds', 0) // 60
                subj = data.get('subject', 'Unknown')
                log_time = datetime.datetime.fromtimestamp(ts).strftime('%b %d')
                recent_logs.append(f"{log_time} | {subj} ({dur_m}m)")
            self.root.after(0, lambda dt=daily_totals, rl=recent_logs[-3:]: self._draw_heatmap(dt, rl))
        except Exception as e: self.log(f"Heatmap Render Error: {e}")

    def _draw_heatmap(self, daily_totals, recent_logs):
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

        self.history_list_canvas.delete("all")
        y_pos = 10
        for log in reversed(recent_logs):
            self.history_list_canvas.create_text(10, y_pos, text=log, fill="#888888", font=self.font_body, anchor="w")
            y_pos += 25

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
    # NOTES APP (new)
    # ==========================================
    def _build_notes_ui(self):
        f = tk.Frame(self.root, bg="#121212")
        f.place(x=0, y=0, relwidth=1, relheight=1)
        self.frames["notes"] = f
        top = tk.Frame(f, bg="#121212", height=40)
        top.pack(fill="x", padx=10, pady=5)
        tk.Button(top, text="< BACK", font=self.font_body, bg="#121212", fg="#fff", bd=0, command=lambda: self.nav_to("main")).pack(side="left")
        tk.Label(top, text="QUICK NOTES", font=self.font_sub, fg="#ffcc66", bg="#121212").pack(side="right", padx=20)

        left = tk.Frame(f, bg="#121212", width=190)
        left.pack(side="left", fill="y", padx=(10, 0), pady=10)
        left.pack_propagate(False)
        tk.Button(left, text="+ NEW NOTE", font=self.font_body, bg="#2a2a10", fg="#ffcc66", bd=0, command=self._new_note).pack(fill="x", pady=(0, 5), ipady=8)
        self.notes_list_frame = tk.Frame(left, bg="#121212")
        self.notes_list_frame.pack(fill="both", expand=True)

        right = tk.Frame(f, bg="#0a0a0a")
        right.pack(side="right", fill="both", expand=True, padx=10, pady=10)
        self.notes_text = tk.Text(right, bg="#0a0a0a", fg="#fff", font=("Helvetica", 13), bd=0, highlightthickness=1, highlightbackground="#333", wrap="word", height=7)
        self.notes_text.pack(fill="x", pady=(0, 5))
        btn_row = tk.Frame(right, bg="#0a0a0a")
        btn_row.pack(fill="x")
        tk.Button(btn_row, text="SAVE", font=self.font_body, bg="#0a2a10", fg="#1db954", bd=0, command=self._save_current_note).pack(side="left", ipadx=15, ipady=8, padx=(0, 5))
        tk.Button(btn_row, text="DELETE", font=self.font_body, bg="#2a0000", fg="#ff4444", bd=0, command=self._delete_current_note).pack(side="left", ipadx=15, ipady=8)
        kbd_frame = tk.Frame(right, bg="#0a0a0a")
        kbd_frame.pack(fill="both", expand=True, pady=10)
        self._build_generic_osk(kbd_frame, self.notes_text)

        self.notes_data = self._load_json(NOTES_FILE, {})
        self.current_note_key = None
        self._refresh_notes_list()

    def _refresh_notes_list(self):
        for w in self.notes_list_frame.winfo_children():
            w.destroy()
        for key in sorted(self.notes_data.keys(), reverse=True):
            title = self.notes_data[key].get('title', key)
            tk.Button(self.notes_list_frame, text=title[:20], font=font.Font(size=10), bg="#1a1a1a", fg="#ddd", bd=0, anchor="w",
                      command=lambda k=key: self._open_note(k)).pack(fill="x", pady=2, ipady=6)

    def _new_note(self):
        key = str(int(time.time() * 1000))
        self.notes_data[key] = {'title': 'New Note', 'body': ''}
        self.current_note_key = key
        self.notes_text.delete("1.0", tk.END)
        self._refresh_notes_list()

    def _open_note(self, key):
        self.current_note_key = key
        self.notes_text.delete("1.0", tk.END)
        self.notes_text.insert("1.0", self.notes_data[key].get('body', ''))

    def _save_current_note(self):
        if not self.current_note_key:
            self._new_note()
        body = self.notes_text.get("1.0", "end-1c")
        title = body.split("\n")[0][:24] if body.strip() else "Untitled"
        self.notes_data[self.current_note_key] = {'title': title, 'body': body}
        self._save_json(NOTES_FILE, self.notes_data)
        self._refresh_notes_list()
        self.log("Note saved.")

    def _delete_current_note(self):
        if self.current_note_key and self.current_note_key in self.notes_data:
            del self.notes_data[self.current_note_key]
            self._save_json(NOTES_FILE, self.notes_data)
            self.current_note_key = None
            self.notes_text.delete("1.0", tk.END)
            self._refresh_notes_list()

    # ==========================================
    # FLASHCARDS APP (new) - JEE revision cards by subject
    # ==========================================
    def _build_flashcards_ui(self):
        f = tk.Frame(self.root, bg="#0a0a1a")
        f.place(x=0, y=0, relwidth=1, relheight=1)
        self.frames["flashcards"] = f
        top = tk.Frame(f, bg="#0a0a1a", height=40)
        top.pack(fill="x", padx=10, pady=5)
        tk.Button(top, text="< BACK", font=self.font_body, bg="#0a0a1a", fg="#fff", bd=0, command=lambda: self.nav_to("main")).pack(side="left")
        tk.Label(top, text="REVISION FLASHCARDS", font=self.font_sub, fg="#88aaff", bg="#0a0a1a").pack(side="right", padx=20)

        subj_row = tk.Frame(f, bg="#0a0a1a")
        subj_row.pack(fill="x", padx=20)
        self.fc_subject = tk.StringVar(value="Maths")
        for s in ["Maths", "Physics", "Ochem", "Pchem", "Ichem", "Other"]:
            tk.Button(subj_row, text=s, font=font.Font(size=10, weight="bold"), bg="#1a1a2a", fg="#88aaff", bd=0,
                      command=lambda s=s: self._switch_fc_subject(s)).pack(side="left", padx=3, ipady=6, expand=True, fill="x")

        self.fc_canvas = tk.Canvas(f, bg="#111133", highlightthickness=0, height=250)
        self.fc_canvas.pack(fill="x", padx=40, pady=15)
        self.fc_canvas.bind("<Button-1>", lambda e: self._flip_fc())

        ctrl = tk.Frame(f, bg="#0a0a1a")
        ctrl.pack(fill="x", padx=20)
        tk.Button(ctrl, text="◀ PREV", font=self.font_body, bg="#1a1a1a", fg="#fff", bd=0, command=lambda: self._nav_fc(-1)).pack(side="left", ipadx=15, ipady=8)
        tk.Button(ctrl, text="+ ADD CARD", font=self.font_body, bg="#1a2a4a", fg="#88aaff", bd=0, command=self._add_fc_card).pack(side="left", padx=10, ipadx=15, ipady=8)
        tk.Button(ctrl, text="NEXT ▶", font=self.font_body, bg="#1a1a1a", fg="#fff", bd=0, command=lambda: self._nav_fc(1)).pack(side="right", ipadx=15, ipady=8)

        self.flashcards_data = self._load_json(FLASHCARDS_FILE, {})
        self.fc_index = 0
        self.fc_showing_back = False
        self._render_fc()

    def _switch_fc_subject(self, s):
        self.fc_subject.set(s)
        self.fc_index = 0
        self.fc_showing_back = False
        self._render_fc()

    def _current_fc_list(self):
        return self.flashcards_data.get(self.fc_subject.get(), [])

    def _render_fc(self):
        self.fc_canvas.delete("all")
        cards = self._current_fc_list()
        if not cards:
            self.fc_canvas.create_text(360, 120, text="No cards yet for this subject.\nTap + ADD CARD to create one.", fill="#666", font=self.font_body, justify="center")
            return
        self.fc_index %= len(cards)
        card = cards[self.fc_index]
        text = card['back'] if self.fc_showing_back else card['front']
        color = "#1db954" if self.fc_showing_back else "#88aaff"
        self.fc_canvas.create_text(360, 25, text=f"Card {self.fc_index+1}/{len(cards)}  ({'ANSWER' if self.fc_showing_back else 'QUESTION'} — tap to flip)", fill="#666", font=self.font_body)
        self.fc_canvas.create_text(360, 135, text=text, fill=color, font=font.Font(size=16, weight="bold"), width=600, justify="center")

    def _flip_fc(self):
        if self._current_fc_list():
            self.fc_showing_back = not self.fc_showing_back
            self._render_fc()

    def _nav_fc(self, delta):
        if self._current_fc_list():
            self.fc_index = (self.fc_index + delta) % len(self._current_fc_list())
            self.fc_showing_back = False
            self._render_fc()

    def _add_fc_card(self):
        def save(front, back):
            subj = self.fc_subject.get()
            self.flashcards_data.setdefault(subj, []).append({'front': front, 'back': back})
            self._save_json(FLASHCARDS_FILE, self.flashcards_data)
            self.fc_index = len(self.flashcards_data[subj]) - 1
            self.fc_showing_back = False
            self._render_fc()
            self.log(f"Flashcard added to {subj}.")
        FlashcardModal(self.root, self, save)

    # ==========================================
    # TASKS APP (new) - simple to-do list
    # ==========================================
    def _build_tasks_ui(self):
        f = tk.Frame(self.root, bg="#0a1a0a")
        f.place(x=0, y=0, relwidth=1, relheight=1)
        self.frames["tasks"] = f
        top = tk.Frame(f, bg="#0a1a0a", height=40)
        top.pack(fill="x", padx=10, pady=5)
        tk.Button(top, text="< BACK", font=self.font_body, bg="#0a1a0a", fg="#fff", bd=0, command=lambda: self.nav_to("main")).pack(side="left")
        tk.Label(top, text="TASK LIST", font=self.font_sub, fg="#1db954", bg="#0a1a0a").pack(side="right", padx=20)
        self.tasks_list_frame = tk.Frame(f, bg="#0a1a0a")
        self.tasks_list_frame.pack(fill="both", expand=True, padx=20, pady=10)
        tk.Button(f, text="+ ADD TASK", font=self.font_sub, bg="#0a2a10", fg="#1db954", bd=0, command=self._add_task_modal).pack(fill="x", padx=20, pady=10, ipady=10)
        self.tasks_data = self._load_json(TASKS_FILE, [])
        self._render_tasks()

    def _render_tasks(self):
        for w in self.tasks_list_frame.winfo_children():
            w.destroy()
        if not self.tasks_data:
            tk.Label(self.tasks_list_frame, text="No tasks yet. Add one below.", fg="#666", bg="#0a1a0a", font=self.font_body).pack(pady=20)
            return
        for i, t in enumerate(self.tasks_data):
            row = tk.Frame(self.tasks_list_frame, bg="#0a1a0a")
            row.pack(fill="x", pady=3)
            done = t.get('done', False)
            tk.Button(row, text="✔" if done else "○", font=font.Font(size=14, weight="bold"), fg="#1db954" if done else "#666",
                      bg="#0a1a0a", bd=0, width=3, command=lambda idx=i: self._toggle_task(idx)).pack(side="left")
            tk.Label(row, text=t.get('text', ''), fg="#666" if done else "#fff", bg="#0a1a0a", font=self.font_body, anchor="w").pack(side="left", fill="x", expand=True, padx=10)
            tk.Button(row, text="✕", font=self.font_body, fg="#ff4444", bg="#0a1a0a", bd=0, command=lambda idx=i: self._delete_task(idx)).pack(side="right")

    def _toggle_task(self, idx):
        self.tasks_data[idx]['done'] = not self.tasks_data[idx].get('done', False)
        self._save_json(TASKS_FILE, self.tasks_data)
        self._render_tasks()

    def _delete_task(self, idx):
        del self.tasks_data[idx]
        self._save_json(TASKS_FILE, self.tasks_data)
        self._render_tasks()

    def _add_task_modal(self):
        top = tk.Toplevel(self.root)
        top.overrideredirect(True)
        top.geometry("800x480+0+0")
        top.configure(bg="#050505")
        top.attributes('-topmost', True)
        tk.Label(top, text="New Task", font=font.Font(size=18, weight="bold"), fg="#1db954", bg="#050505").pack(pady=10)
        entry = tk.Text(top, height=3, bg="#111111", fg="#fff", font=self.font_sub)
        entry.pack(fill="x", padx=20, pady=10)
        kbd = tk.Frame(top, bg="#050505")
        kbd.pack(fill="both", expand=True, padx=20, pady=5)
        self._build_generic_osk(kbd, entry)

        def save():
            text = entry.get("1.0", "end-1c").strip()
            if text:
                self.tasks_data.append({'text': text, 'done': False})
                self._save_json(TASKS_FILE, self.tasks_data)
                self._render_tasks()
            top.destroy()

        btn_row = tk.Frame(top, bg="#050505")
        btn_row.pack(fill="x", padx=20, pady=10)
        tk.Button(btn_row, text="SAVE", font=self.font_sub, bg="#0a2a10", fg="#1db954", bd=0, command=save).pack(side="left", ipadx=20, ipady=10)
        tk.Button(btn_row, text="CANCEL", font=self.font_sub, bg="#2a0000", fg="#ff4444", bd=0, command=top.destroy).pack(side="right", ipadx=20, ipady=10)

    # ==========================================
    # EXAM COUNTDOWN APP (new)
    # ==========================================
    def _build_countdown_ui(self):
        f = tk.Frame(self.root, bg="#050505")
        f.place(x=0, y=0, relwidth=1, relheight=1)
        self.frames["countdown"] = f
        top = tk.Frame(f, bg="#050505", height=40)
        top.pack(fill="x", padx=10, pady=5)
        tk.Button(top, text="< BACK", font=self.font_body, bg="#050505", fg="#fff", bd=0, command=lambda: self.nav_to("main")).pack(side="left")
        tk.Label(top, text="EXAM COUNTDOWN", font=self.font_sub, fg="#ff8888", bg="#050505").pack(side="right", padx=20)
        self.countdown_days_lbl = tk.Label(f, text="--", font=font.Font(size=90, weight="bold"), fg="#ff8888", bg="#050505")
        self.countdown_days_lbl.pack(pady=(50, 0))
        tk.Label(f, text="DAYS REMAINING", font=self.font_sub, fg="#888", bg="#050505").pack()
        self.countdown_date_lbl = tk.Label(f, text="", font=self.font_body, fg="#666", bg="#050505")
        self.countdown_date_lbl.pack(pady=10)
        tk.Button(f, text="SET TARGET DATE", font=self.font_body, bg="#1a1a1a", fg="#ff8888", bd=0, command=self._set_countdown_date).pack(ipadx=20, ipady=10)
        self.countdown_config = self._load_json(COUNTDOWN_FILE, {"date": "2027-04-01"})
        self._refresh_countdown()

    def _refresh_countdown(self):
        try:
            target = datetime.datetime.strptime(self.countdown_config.get("date", "2027-04-01"), "%Y-%m-%d")
            days = (target - datetime.datetime.now()).days
            self.countdown_days_lbl.config(text=str(max(0, days)))
            self.countdown_date_lbl.config(text=f"Target: {target.strftime('%d %b %Y')}")
        except Exception:
            pass

    def _set_countdown_date(self):
        opts = []
        base = datetime.datetime.now().replace(day=1)
        for m in range(1, 13):
            month = base.month + m
            year = base.year + (month - 1) // 12
            month = ((month - 1) % 12) + 1
            opts.append(f"{year:04d}-{month:02d}-01")
        TouchModal(self.root, "Select Target Month (1st)", opts, self._save_countdown_date)

    def _save_countdown_date(self, date_str):
        self.countdown_config["date"] = date_str
        self._save_json(COUNTDOWN_FILE, self.countdown_config)
        self._refresh_countdown()

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
    # SETTINGS & OSK W/PERSISTENT CAPS LOCK
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
        
        self.kbd_container = tk.Frame(right_frame, bg="#121212")
        self.kbd_container.pack(fill="both", expand=True)
        self._build_osk()

    def _trigger_wifi_modal(self):
        self.log("Scanning Wi-Fi interfaces...")
        try:
            out = subprocess.check_output(['nmcli', '-t', '-f', 'SSID', 'dev', 'wifi']).decode()
            networks = list(set([n for n in out.split('\n') if n.strip()]))
        except: networks = ["Scan Failed"]
        TouchModal(self.root, "Available Networks", networks, lambda s: self.btn_wifi_sel.config(text=s))

    def _build_osk(self):
        for widget in self.kbd_container.winfo_children():
            widget.destroy()
            
        keys = [
            ['1','2','3','4','5','6','7','8','9','0'], 
            ['q','w','e','r','t','y','u','i','o','p'], 
            ['a','s','d','f','g','h','j','k','l','DEL'], 
            ['CAPS','z','x','c','v','b','n','m','_','@']
        ]
        
        for r, row in enumerate(keys):
            self.kbd_container.rowconfigure(r, weight=1)
            for c, key in enumerate(row):
                self.kbd_container.columnconfigure(c, weight=1)
                
                if key == "CAPS":
                    bg = "#1a2a4a" if self.caps_lock_active else "#1a1a1a"
                    fg = "#00aaff" if self.caps_lock_active else "#ffffff"
                    display_text = "CAPS"
                elif key == "DEL":
                    bg = "#330000"
                    fg = "#ff4444"
                    display_text = "DEL"
                else:
                    bg = "#1a1a1a"
                    fg = "#ffffff"
                    display_text = key.upper() if self.caps_lock_active else key
                    
                btn = tk.Button(self.kbd_container, text=display_text, font=self.font_sub, bg=bg, fg=fg, bd=0, 
                                activebackground="#444", command=lambda k=key: self._osk_press(k))
                btn.grid(row=r, column=c, sticky="nsew", padx=2, pady=2)

    def _osk_press(self, key):
        self.last_interaction = time.time()
        if key == "DEL":
            txt = self.entry_pass.get()
            self.entry_pass.delete(0, tk.END)
            self.entry_pass.insert(0, txt[:-1])
        elif key == "CAPS":
            self.caps_lock_active = not self.caps_lock_active
            self._build_osk() 
        else:
            char = key.upper() if self.caps_lock_active else key
            self.entry_pass.insert(tk.END, char)

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
        self.last_interaction = time.time()
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
    # DISPLAY WAKELOCK MECHANICS
    # ==========================================
    def wake_display(self):
        if self.is_asleep:
            self.is_asleep = False
            self.last_interaction = time.time()
            os.system(f'echo 0 | sudo tee {BACKLIGHT_POWER} > /dev/null')
        self.kill_active_processes()
        self.root.geometry("800x480+0+0")
        self.nav_to("main")

    def sleep_display(self):
        if not self.is_asleep:
            self.is_asleep = True
            self.kill_active_processes()
            self.nav_to("standby")
            os.system(f'echo 1 | sudo tee {BACKLIGHT_POWER} > /dev/null')
            self._animate_screensaver()

    def _show_power_menu(self):
        TouchModal(self.root, "System Power", ["Standby", "Reboot", "Power Off"], self._handle_power_choice)

    def _handle_power_choice(self, choice):
        if choice == "Standby": self.sleep_display()
        elif choice == "Reboot": self.reboot_system()
        elif choice == "Power Off": self.poweroff_system()

    def launch_uxplay(self):
        self.prevent_sleep = True
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

    def launch_desktop(self):
        self.prevent_sleep = False
        self.kill_active_processes()
        self._transform_to_pill()

    def _transform_to_pill(self):
        self.nav_to("pill")
        self.root.geometry("150x55+630+15")

    def kill_active_processes(self):
        self.prevent_sleep = False
        if getattr(self, 'active_process', None): self.active_process.terminate()
        if getattr(self, 'aux_process', None): self.aux_process.terminate()
        self.active_process = self.aux_process = None
        os.system("killall uxplay node chromium-browser > /dev/null 2>&1")

    def reboot_system(self): self.log("Reboot command sent."); self.kill_active_processes(); os.system("sudo reboot")
    def poweroff_system(self): self.log("Poweroff command sent."); self.kill_active_processes(); os.system("sudo poweroff")

    def touch_listener(self):
        try:
            device = evdev.InputDevice(TOUCH_DEVICE)
            last = 0
            for event in device.read_loop():
                self.last_interaction = time.time()
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
