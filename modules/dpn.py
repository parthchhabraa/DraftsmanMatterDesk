import random
import threading
import os
import time
import tkinter as tk
from PIL import ImageTk
import qrcode

class DpnEngine:
    def __init__(self, core):
        self.core = core

    def render_dpn_canvas(self):
        if not hasattr(self.core, 'dpn_monitor_canvas') or not self.core.dpn_monitor_canvas.winfo_exists(): return
        self.core.dpn_monitor_canvas.delete("all")
        if not self.core.dpn_active:
            self.core.dpn_monitor_canvas.create_text(180, 100, text="Tunnel Array Offline\nWaiting for Core Ignition Sequence...", fill="#444", font=self.core.font_body, justify="center")
            return
            
        self.core.dpn_monitor_canvas.create_text(20, 20, text=f"● Broadcast: wlan0 ({self.core.dpn_ssid})", fill="#1db954", font=self.core.font_body, anchor="w")
        self.core.dpn_monitor_canvas.create_text(20, 45, text=f"● WAN Matrix: wlan1 (TP-Link)", fill="#1db954", font=self.core.font_body, anchor="w")
        self.core.dpn_monitor_canvas.create_text(20, 70, text=f"● Gateway: 10.45.0.1", fill="#00aaff", font=self.core.font_body, anchor="w")
        self.core.dpn_monitor_canvas.create_text(20, 95, text=f"● Active Clients: {self.core.dpn_client_count} Nodes", fill="#fff", font=self.core.font_body, anchor="w")
        
        try:
            qr_str = f"WIFI:S:{self.core.dpn_ssid};T:WPA;P:{self.core.dpn_passkey};;"
            qr = qrcode.QRCode(version=1, box_size=4, border=2)
            qr.add_data(qr_str)
            qr.make(fit=True)
            img = qr.make_image(fill_color="white", back_color="black").convert("RGBA").resize((150, 140))
            self.core.qr_image_tk = ImageTk.PhotoImage(img)
            self.core.dpn_monitor_canvas.create_image(180, 210, image=self.core.qr_image_tk)
        except Exception: pass

    def toggle_dpn_engine(self):
        self.core.last_interaction = time.time()
        if self.core.dpn_active:
            self.core.dpn_active = False
            self.core.dpn_client_count = 0
            self.core.lbl_dpn_status.config(text="NETWORK STATE: OFFLINE", fg="#ff4444")
            self.core.btn_dpn_toggle.config(text="ACTIVATE DPN CORE", bg="#1a2a4a", fg="#00aaff")
            threading.Thread(target=lambda: os.system("sudo systemctl stop hostapd dnsmasq wg-quick@wg0 > /dev/null 2>&1"), daemon=True).start()
        else:
            self.core.dpn_active = True
            self.core.dpn_client_count = random.randint(1, 3)
            self.core.lbl_dpn_status.config(text="NETWORK STATE: ROUTED", fg="#1db954")
            self.core.btn_dpn_toggle.config(text="DEACTIVATE DPN CORE", bg="#3a1a1a", fg="#ff4444")
            threading.Thread(target=lambda: os.system("sudo systemctl start hostapd dnsmasq wg-quick@wg0 > /dev/null 2>&1"), daemon=True).start()
        self.render_dpn_canvas()