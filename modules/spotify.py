import os
import time
import requests
import io
import threading
import tkinter as tk
from PIL import Image, ImageTk, ImageDraw
import spotipy
from spotipy.oauth2 import SpotifyOAuth

class SpotifyEngine:
    def __init__(self, core):
        self.core = core
        self.sp = None
        self.vinyl_active = False
        self.vinyl_job = None
        self.current_track_id = None
        self.album_art_image = None
        self.playlist_dict = {}

    def init_session(self, cid, secret, uri, cache):
        if os.path.exists(cache):
            try: self.sp = spotipy.Spotify(auth_manager=SpotifyOAuth(client_id=cid, client_secret=secret, redirect_uri=uri, cache_path=cache, open_browser=False, scope='user-read-playback-state user-modify-playback-state playlist-read-private'))
            except Exception: pass

    def start_polling(self):
        threading.Thread(target=self._poll_spotify_state, daemon=True).start()

    def _poll_spotify_state(self):
        if not self.sp: return
        try: self.playlist_dict = {p['name']: p['uri'] for p in self.sp.current_user_playlists(limit=20).get('items', []) if p}
        except Exception: pass
        while True:
            if getattr(self.core, 'vinyl_active', False):
                try:
                    pb = self.sp.current_playback()
                    if pb and pb.get('item'):
                        t = pb['item']
                        if t['id'] != self.current_track_id:
                            self.current_track_id = t['id']
                            res = requests.get(t['album']['images'][0]['url'], timeout=5)
                            img = Image.open(io.BytesIO(res.content)).convert("RGBA").resize((140, 140), Image.LANCZOS)
                            mask = Image.new('L', (140, 140), 0)
                            ImageDraw.Draw(mask).ellipse((0, 0, 140, 140), fill=255)
                            out = Image.new('RGBA', (140, 140), (0,0,0,0))
                            out.paste(img, (0,0), mask)
                            self.album_art_image = out
                            self.core.root.after(0, self._draw_vinyl)
                        self.core.root.after(0, lambda: self._update_ui(t['name'], t['artists'][0]['name'], pb['is_playing'], pb['device']['volume_percent']))
                except Exception: pass
            time.sleep(3)

    def _draw_vinyl(self):
        img = Image.new('RGBA', (300, 300), (18, 18, 18, 0))
        d = ImageDraw.Draw(img)
        d.ellipse((0, 0, 300, 300), fill=(20, 20, 20, 255), outline=(40, 40, 40, 255))
        if self.album_art_image: img.paste(self.album_art_image, (80, 80), self.album_art_image)
        d.ellipse((145, 145, 155, 155), fill=(18, 18, 18, 255))
        self.base_vinyl = img

    def animate_vinyl(self):
        if not getattr(self.core, 'vinyl_active', False): return
        self.core.vinyl_angle = (getattr(self.core, 'vinyl_angle', 0) - 1) % 360
        self.core.cached_vinyl_img = ImageTk.PhotoImage(getattr(self, 'base_vinyl', Image.new('RGBA', (300,300))).rotate(self.core.vinyl_angle, resample=Image.BICUBIC))
        self.core.vinyl_canvas.delete("all")
        self.core.vinyl_canvas.create_image(175, 175, image=self.core.cached_vinyl_img)
        self.core.vinyl_job = self.core.root.after(30, self.animate_vinyl)

    def _update_ui(self, name, artist, playing, vol):
        if not getattr(self.core, 'vinyl_active', False): return
        self.core.lbl_track.config(text=name[:25])
        self.core.lbl_artist.config(text=artist)
        self.core.btn_play.config(text="⏸" if playing else "▶")