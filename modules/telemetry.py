import time
import datetime
import psutil
import requests
import random
import tkinter as tk

class TelemetryEngine:
    def __init__(self, core):
        self.core = core
        self.net_history_tx = [0] * 40
        self.net_history_rx = [0] * 40
        self.last_net_bytes_tx = psutil.net_io_counters().bytes_sent
        self.last_net_bytes_rx = psutil.net_io_counters().bytes_recv
        self.current_weather_type = "Clear"
        self.rain_particles = []
        self.sun_angle = 0
        self.last_h = self.last_m = self.last_s = ""

    def start_loops(self):
        import threading
        threading.Thread(target=self._hardware_telemetry_loop, daemon=True).start()
        threading.Thread(target=self._weather_telemetry_loop, daemon=True).start()

    def _hardware_telemetry_loop(self):
        while True:
            try:
                time_since_interaction = time.time() - self.core.last_interaction
                remaining_idle = max(0, self.core.idle_timeout - time_since_interaction)
                
                up_sec = time.time() - psutil.boot_time()
                up_d, up_h, up_m = int(up_sec // 86400), int((up_sec % 86400) // 3600), int((up_sec % 3600) // 60)
                up_str = f"UP: {up_d}d {up_h}h" if up_d > 0 else f"UP: {up_h}h {up_m}m"
                
                if not self.core.is_asleep and not getattr(self.core, 'prevent_sleep', False):
                    sleep_str = f"SLEEP: {int(remaining_idle // 60):02d}:{int(remaining_idle % 60):02d}"
                    if remaining_idle <= 0:
                        self.core.root.after(0, self.core.sleep_display)
                else:
                    sleep_str = "SLEEP: WKLK" if getattr(self.core, 'prevent_sleep', False) else "SLEEP: OFF"
                
                cpu = psutil.cpu_percent()
                ram = psutil.virtual_memory().percent
                
                io_curr_tx = psutil.net_io_counters().bytes_sent
                io_curr_rx = psutil.net_io_counters().bytes_recv
                delta_tx = (io_curr_tx - self.last_net_bytes_tx) / 1024.0
                delta_rx = (io_curr_rx - self.last_net_bytes_rx) / 1024.0
                self.last_net_bytes_tx, self.last_net_bytes_rx = io_curr_tx, io_curr_rx
                
                self.net_history_tx.append(delta_tx)
                self.net_history_rx.append(delta_rx)
                self.net_history_tx.pop(0)
                self.net_history_rx.pop(0)
                
                temp_c = 0.0
                try:
                    with open('/sys/class/thermal/thermal_zone0/temp', 'r') as f: temp_c = float(f.read()) / 1000.0
                except: pass
                
                if temp_c >= 82.0 and not self.core.thermal_panic:
                    self.core.thermal_panic = True
                    self.core.root.after(0, self.core._trigger_panic)

                self.core.root.after(0, lambda c=cpu, r=ram, t=temp_c, u=up_str, s=sleep_str: self._update_telemetry_ui(c, r, t, u, s))
            except Exception: pass
            time.sleep(1)

    def _update_telemetry_ui(self, c, r, t, u, s):
        if not hasattr(self.core, 'lbl_hw_cpu') or not self.core.lbl_hw_cpu.winfo_exists(): return
        self.core.lbl_hw_cpu.config(text=f"CPU: {c}%", fg="#ff4444" if c > 85 else "#888")
        self.core.lbl_hw_ram.config(text=f"RAM: {r}%", fg="#ff4444" if r > 85 else "#888")
        self.core.lbl_hw_up.config(text=u)
        self.core.lbl_hw_sleep.config(text=s)
        self.core.lbl_hw_temp.config(text=f"TEMP: {t:.1f}°C", fg="#ff4444" if t > 75 else "#888")
        
        self.core.telemetry_graph.delete("all")
        max_val = max(max(self.net_history_tx), max(self.net_history_rx), 1.0)
        for i in range(39):
            x1, x2 = i * 3, (i + 1) * 3
            self.core.telemetry_graph.create_line(x1, 18 - int((self.net_history_tx[i] / max_val) * 16), x2, 18 - int((self.net_history_tx[i+1] / max_val) * 16), fill="#1db954", width=1)
            self.core.telemetry_graph.create_line(x1, 18 - int((self.net_history_rx[i] / max_val) * 16), x2, 18 - int((self.net_history_rx[i+1] / max_val) * 16), fill="#88aaff", width=1)

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
                elif code in [51, 53, 55, 61, 63, 65, 80, 81, 82, 95, 96, 99]:
                    desc = "Rain"
                    self.current_weather_type = "Rain"
                self.core.root.after(0, lambda t=temp, p=pop, d=desc: self._update_weather_ui(t, p, d))
            except Exception: pass
            time.sleep(900)

    def _update_weather_ui(self, temp, pop, desc):
        if hasattr(self.core, 'wx_canvas') and self.core.wx_canvas.winfo_exists():
            self.core.wx_canvas.itemconfig(self.core.weather_temp_id, text=f"{temp}°C")
            self.core.wx_canvas.itemconfig(self.core.weather_pop_id, text=f"Precipitation: {pop}%")
            self.core.wx_canvas.itemconfig(self.core.weather_desc_id, text=desc)