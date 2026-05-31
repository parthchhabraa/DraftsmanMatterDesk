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

# --- System Paths ---
BACKLIGHT_POWER = '/sys/class/backlight/10-0045/bl_power'
BACKLIGHT_BRIGHT = '/sys/class/backlight/10-0045/brightness'
TOUCH_DEVICE = '/dev/input/event4'
CARPLAY_DIR = '/home/st6b/matterdesk/carplay-engine'
BOOTLOADER_IMG = '/home/st6b/matterdesk/images/bootloader.png'
FIREBASE_KEY_PATH = '/home/st6b/matterdesk/serviceAccountKey.json'

# --- API Context ---
SPOTIFY_CLIENT_ID = '515b520ddd7b4ed2a33fdd1091c9ef00'
SPOTIFY_CLIENT_SECRET = 'e24611ecfa1c4be2b28c1d59e40af0b8'
SPOTIFY_REDIRECT_URI = 'http://127.0.0.1:8080/callback'
SPOTIFY_CACHE_PATH = '/home/st6b/matterdesk/.cache'

class TouchModal(tk.Toplevel):
    """Hardware-optimized, touch-friendly selection overlay"""
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
        self._build_monk_mode_ui()
        self._build_settings_ui()
        self._build_system_ui()
        
        self.nav_to("main")
        threading.Thread(target=self.touch_listener, daemon=True).start()

    def nav_to(self, frame_name):
        self.frames[frame_name].tkraise()
        self.vinyl_active = (frame_name == "spotify")
        if self.vinyl_active and not self.vinyl_job: self._animate_vinyl()

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
    # UI BUILDERS
    # ==========================================
    def _build_main_menu(self):
        f = tk.Frame(self.root)
        f.place(x=0, y=0, relwidth=1, relheight=1)
        self.frames["main"] = f
        
        canvas = tk.Canvas(f, width=800, height=480, highlightthickness=0)
        canvas.pack(fill="both", expand=True)
        canvas.create_image(0, 0, image=self.bg_image, anchor="nw")
        canvas.create_text(30, 40, text="DRAFTSMAN", font=self.font_header, fill="#ffffff", anchor="w")
        canvas.create_text(770, 40, text="v2.0 | OPTIMIZED", font=self.font_body, fill="#888888", anchor="e")

        grid = tk.Frame(canvas, bg="#050505") 
        canvas.create_window(400, 260, window=grid, width=760, height=360)
        grid.columnconfigure((0, 1, 2, 3, 4), weight=1, uniform="col")
        grid.rowconfigure((0, 1), weight=1, uniform="row")

        btn_style = {"font": self.font_sub, "highlightthickness": 0, "bd": 0, "activebackground": "#333333"}
        
        tk.Button(grid, text="AirPlay", bg="#1a1a1a", fg="#fff", command=self.launch_uxplay, **btn_style).grid(row=0, column=0, sticky="nsew", padx=5, pady=5)
        tk.Button(grid, text="CarPlay", bg="#1a1a1a", fg="#aaa", command=self.launch_carplay, **btn_style).grid(row=0, column=1, sticky="nsew", padx=5, pady=5)
        tk.Button(grid, text="Spotify", bg="#0a2a10", fg="#1db954", command=lambda: self.nav_to("spotify"), **btn_style).grid(row=0, column=2, sticky="nsew", padx=5, pady=5)
        tk.Button(grid, text="Monk Mode", bg="#12123a", fg="#88aaff", command=lambda: self.nav_to("monk"), **btn_style).grid(row=0, column=3, sticky="nsew", padx=5, pady=5)
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
    # SPOTIFY SUBSYSTEM
    # ==========================================
    def _init_spotify(self):
        self.sp = None
        if os.path.exists(SPOTIFY_CACHE_PATH):
            try:
                self.sp = spotipy.Spotify(auth_manager=SpotifyOAuth(
                    client_id=SPOTIFY_CLIENT_ID, client_secret=SPOTIFY_CLIENT_SECRET,
                    redirect_uri=SPOTIFY_REDIRECT_URI, cache_path=SPOTIFY_CACHE_PATH, open_browser=False,
                    scope='user-read-playback-state user-modify-playback-state playlist-read-private playlist-read-collaborative'
                ))
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
        opts = [d['name'] for d in self.sp.devices().get('devices', [])] if self.sp else ["No devices"]
        TouchModal(self.root, "Select Output Device", opts, self._sp_transfer)

    def _trigger_playlist_modal(self):
        opts = list(self.playlist_dict.keys()) if hasattr(self, 'playlist_dict') else ["No playlists"]
        TouchModal(self.root, "Select Playlist", opts, self._sp_play_playlist)

    def _sp_transfer(self, target_name):
        for d in self.sp.devices().get('devices', []):
            if d['name'] == target_name:
                try: self.sp.transfer_playback(device_id=d['id'], force_play=True)
                except: pass
                break

    def _sp_play_playlist(self, p_name):
        p_uri = self.playlist_dict.get(p_name)
        if p_uri:
            try: self.sp.start_playback(context_uri=p_uri)
            except: pass

    def _poll_spotify_state(self):
        try:
            playlists = self.sp.current_user_playlists(limit=20).get('items', [])
            self.playlist_dict = {p['name']: p['uri'] for p in playlists if p}
        except: pass
        while True:
            if self.vinyl_active:
                try:
                    pb = self.sp.current_playback()
                    if pb and pb.get('item'):
                        t = pb['item']
                        t_id, t_name, a_name = t['id'], t['name'], t['artists'][0]['name']
                        if t_id != self.current_track_id:
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
        if not self.vinyl_active: return
        self.lbl_track.config(text=n[:25])
        self.lbl_artist.config(text=a)
        self.btn_play.config(text="⏸" if p else "▶")
        self.vol_canvas.delete("all")
        self.vol_canvas.create_line(0, 10, 200, 10, fill="#404040", width=4, capstyle=tk.ROUND)
        fill_w = max(4, (v/100) * 200) if v else 4
        self.vol_canvas.create_line(0, 10, fill_w, 10, fill="#1db954", width=4, capstyle=tk.ROUND)
        self.vol_canvas.create_oval(fill_w-6, 4, fill_w+6, 16, fill="#fff", outline="")

    def _on_vol_drag(self, e):
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
        if self.album_art_image: img.paste(self.album_art_image, ((s-140)//2, (s-140)//2), self.album_art_image)
        else: d.ellipse((80, 80, 220, 220), fill=(29, 185, 84, 255))
        d.ellipse((145, 145, 155, 155), fill=(18, 18, 18, 255))
        self.base_vinyl = img

    def _animate_vinyl(self):
        if not self.vinyl_active: return
        self.vinyl_angle = getattr(self, 'vinyl_angle', 0)
        self.vinyl_angle = (self.vinyl_angle - 1) % 360
        self.cached_vinyl_img = ImageTk.PhotoImage(self.base_vinyl.rotate(self.vinyl_angle, resample=Image.BICUBIC))
        self.vinyl_canvas.delete("all")
        self.vinyl_canvas.create_image(175, 175, image=self.cached_vinyl_img)
        self.vinyl_job = self.root.after(30, self._animate_vinyl)

    def _sp_play_pause(self):
        if not self.sp: return
        try:
            pb = self.sp.current_playback()
            if pb and pb.get('is_playing'): self.sp.pause_playback()
            else: self.sp.start_playback()
        except Exception: pass

    # ==========================================
    # YPT MONK MODE (FIREBASE SYNC)
    # ==========================================
    def _init_firebase(self):
        self.study_active = False
        self.study_seconds = 0
        self.current_subject = tk.StringVar(value="Maths")
        self.study_job = None
        self.task_widgets = []
        try:
            cred = credentials.Certificate(FIREBASE_KEY_PATH)
            firebase_admin.initialize_app(cred, {'databaseURL': 'https://YOUR-PROJECT-ID.firebaseio.com/'})
            self.firebase_active = True
        except Exception:
            self.firebase_active = False

    def _build_monk_mode_ui(self):
        f = tk.Frame(self.root, bg="#050505")
        f.place(x=0, y=0, relwidth=1, relheight=1)
        self.frames["monk"] = f
        
        eng = tk.Frame(f, bg="#050505", width=400)
        eng.pack(side="left", fill="y", padx=30, pady=30)
        
        tk.Button(eng, text="< ABORT", font=self.font_body, bg="#1a1a1a", fg="#ff4444", bd=0, command=self._exit_monk).pack(anchor="w")
        self.lbl_timer = tk.Label(eng, text="00:00:00", font=font.Font(family="Helvetica", size=60, weight="bold"), fg="#fff", bg="#050505")
        self.lbl_timer.pack(pady=(40, 10))
        
        self.current_subj_lbl = tk.Button(eng, text="Subject: Maths", font=self.font_sub, bg="#1a1a1a", fg="#aaa", bd=0, command=self._trigger_subj_modal)
        self.current_subj_lbl.pack(fill="x", pady=10, ipady=10)
        
        self.btn_toggle_timer = tk.Button(eng, text="START SPRINT", font=self.font_header, bg="#1db954", fg="#fff", bd=0, command=self._toggle_timer)
        self.btn_toggle_timer.pack(fill="x", pady=20, ipady=15)

        tsk = tk.Frame(f, bg="#121212")
        tsk.pack(side="right", fill="both", expand=True, padx=20, pady=20)
        tk.Label(tsk, text="Active Pipeline", font=self.font_header, fg="#fff", bg="#121212", anchor="w").pack(fill="x", padx=20, pady=20)
        
        self.task_list_canvas = tk.Canvas(tsk, bg="#121212", highlightthickness=0)
        self.task_list_canvas.pack(fill="both", expand=True, padx=20)
        
        if self.firebase_active: threading.Thread(target=self._poll_tasks, daemon=True).start()
        else: tk.Label(self.task_list_canvas, text="Firebase Offline.", fg="#ff4444", bg="#121212").pack()

    def _trigger_subj_modal(self):
        TouchModal(self.root, "Select Subject", ["Maths", "Physics", "Ochem", "Pchem", "Ichem", "Other"], lambda s: (self.current_subject.set(s), self.current_subj_lbl.config(text=f"Subject: {s}")))

    def _exit_monk(self):
        if self.study_active: self._toggle_timer()
        self.nav_to("main")

    def _toggle_timer(self):
        if self.study_active:
            self.study_active = False
            self.btn_toggle_timer.config(text="START SPRINT", bg="#1db954")
            if self.study_job: self.root.after_cancel(self.study_job)
            if self.firebase_active and self.study_seconds > 60:
                threading.Thread(target=self._push_session, args=(self.current_subject.get(), self.study_seconds), daemon=True).start()
            self.study_seconds = 0
            self.lbl_timer.config(text="00:00:00")
        else:
            self.study_active = True
            self.btn_toggle_timer.config(text="END SPRINT", bg="#ff4444")
            self._tick_timer()

    def _tick_timer(self):
        if not self.study_active: return
        self.study_seconds += 1
        h, m, s = self.study_seconds // 3600, (self.study_seconds % 3600) // 60, self.study_seconds % 60
        self.lbl_timer.config(text=f"{h:02d}:{m:02d}:{s:02d}")
        self.study_job = self.root.after(1000, self._tick_timer)

    def _poll_tasks(self):
        while True:
            try:
                raw = db.reference('tasks').order_by_child('completed').equal_to(False).get()
                self.root.after(0, lambda: self._render_tasks(raw))
            except Exception: pass
            time.sleep(5)

    def _render_tasks(self, tasks_dict):
        for w in self.task_widgets: w.destroy()
        self.task_widgets.clear()
        if not tasks_dict:
            lbl = tk.Label(self.task_list_canvas, text="Pipeline Clear.", fg="#666", bg="#121212")
            lbl.pack(anchor="w", pady=10)
            self.task_widgets.append(lbl)
            return
        for t_id, t_data in tasks_dict.items():
            f = tk.Frame(self.task_list_canvas, bg="#222")
            f.pack(fill="x", pady=5)
            tk.Label(f, text=t_data.get('subject', 'N/A'), font=font.Font(weight="bold"), fg="#1db954", bg="#222", width=8).pack(side="left", padx=10)
            tk.Label(f, text=t_data.get('title', 'Task'), fg="#fff", bg="#222").pack(side="left", pady=15)
            tk.Button(f, text="DONE", bg="#333", fg="#fff", bd=0, command=lambda k=t_id: self._complete_task(k)).pack(side="right", padx=10)
            self.task_widgets.append(f)

    def _complete_task(self, task_id):
        if self.firebase_active:
            threading.Thread(target=lambda: db.reference(f'tasks/{task_id}').update({'completed': True}), daemon=True).start()

    def _push_session(self, subject, duration):
        try: db.reference('sessions').push({'subject': subject, 'duration_seconds': duration, 'timestamp': int(time.time())})
        except Exception: pass

    # ==========================================
    # SETTINGS: NETWORK OPERATIONS
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
        tk.Button(right_frame, text="UPDATE SYSTEM (GITHUB OTA)", font=self.font_sub, bg="#1a2a4a", fg="#88aaff", bd=0, command=self._exec_ota).pack(fill="x", pady=(0, 20), ipady=15)
        self._build_osk(right_frame)

    def _trigger_wifi_modal(self):
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
        threading.Thread(target=self._exec_connect, args=(ssid, pw), daemon=True).start()

    def _exec_connect(self, ssid, pw):
        try:
            cmd = ['nmcli', 'dev', 'wifi', 'connect', ssid]
            if pw: cmd.extend(['password', pw])
            subprocess.check_call(cmd)
            self.root.after(0, lambda: self.btn_connect.config(text="CONNECTED", fg="#1db954"))
        except Exception:
            self.root.after(0, lambda: self.btn_connect.config(text="FAILED", fg="#ff4444"))

    def _exec_ota(self):
        try:
            subprocess.Popen(["git", "fetch", "--all"], cwd="/home/st6b/matterdesk").wait()
            subprocess.Popen(["git", "reset", "--hard", "origin/main"], cwd="/home/st6b/matterdesk").wait()
            os.system("sudo systemctl restart matterdesk.service")
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
        if self.active_process: self.active_process.terminate()
        if self.aux_process: self.aux_process.terminate()
        self.active_process = self.aux_process = None
        os.system("killall uxplay node chromium-browser > /dev/null 2>&1")

    def sleep_display(self):
        if not self.is_asleep:
            self.is_asleep = True
            self.kill_active_processes()
            self.nav_to("waiting")
            self.lbl_waiting.config(text="")
            os.system(f'echo 1 | sudo tee {BACKLIGHT_POWER} > /dev/null')

    def reboot_system(self): self.kill_active_processes(); os.system("sudo reboot")
    def poweroff_system(self): self.kill_active_processes(); os.system("sudo poweroff")

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