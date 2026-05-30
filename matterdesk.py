import tkinter as tk
from tkinter import font
import evdev
import threading
import time
import os
import subprocess

BACKLIGHT_PATH = '/sys/class/backlight/10-0045/bl_power'
TOUCH_DEVICE = '/dev/input/event4'
ASSET_DIR = os.path.join(os.path.dirname(__file__), 'images')

class MatterDeskCore:
    def __init__(self):
        self.root = tk.Tk()
        self.root.overrideredirect(True)
        self.root.attributes('-topmost', True)
        self.root.geometry("800x480+0+0")
        self.root.configure(bg="#0a0a0a", cursor="arrow")
        
        self.is_asleep = False
        self.active_process = None
        
        # UI Typography
        self.font_header = font.Font(family="Helvetica", size=24, weight="bold")
        self.font_sub = font.Font(family="Helvetica", size=14)
        
        self.build_dashboard()
        
        listener_thread = threading.Thread(target=self.touch_listener, daemon=True)
        listener_thread.start()

    def build_dashboard(self):
        for widget in self.root.winfo_children():
            widget.destroy()
            
        self.root.configure(bg="#0a0a0a", cursor="arrow")
        
        # Header Layout
        header = tk.Frame(self.root, bg="#0a0a0a", height=60)
        header.pack(fill="x", pady=(20, 0), padx=30)
        tk.Label(header, text="DRAFTSMAN", font=self.font_header, fg="#ffffff", bg="#0a0a0a", anchor="w").pack(side="left")
        tk.Label(header, text="MATTERDESK v1.0", font=self.font_sub, fg="#444444", bg="#0a0a0a", anchor="e").pack(side="right", pady=8)

        # Main Grid Layout
        grid = tk.Frame(self.root, bg="#0a0a0a")
        grid.pack(expand=True, fill="both", padx=30, pady=30)
        
        grid.columnconfigure((0, 1, 2), weight=1, uniform="col")
        grid.rowconfigure(0, weight=1)

        btn_style = {"font": self.font_header, "highlightthickness": 0, "bd": 0, "activebackground": "#333333"}
        
        tk.Button(grid, text="AirPlay\n(UxPlay)", bg="#1a1a1a", fg="#ffffff", command=self.launch_uxplay, **btn_style)\
            .grid(row=0, column=0, sticky="nsew", padx=10)
                  
        tk.Button(grid, text="CarPlay\n(LIVI)", bg="#1a1a1a", fg="#555555", command=self.launch_carplay, **btn_style)\
            .grid(row=0, column=1, sticky="nsew", padx=10)
                  
        tk.Button(grid, text="Standby", bg="#2a0000", fg="#ff4444", command=self.sleep_display, **btn_style)\
            .grid(row=0, column=2, sticky="nsew", padx=10)

    def launch_uxplay(self):
        self.kill_active_processes()
        self.active_process = subprocess.Popen(["uxplay", "-n", "MatterDesk", "-p"])
        
    def launch_carplay(self):
        pass

    def kill_active_processes(self):
        if self.active_process:
            self.active_process.terminate()
            os.system("killall uxplay > /dev/null 2>&1")

    def build_asleep_ui(self):
        for widget in self.root.winfo_children():
            widget.destroy()
        self.root.configure(bg="#000000", cursor="none")

    def sleep_display(self):
        if not self.is_asleep:
            self.is_asleep = True
            self.kill_active_processes()
            self.build_asleep_ui()
            os.system(f'echo 1 | sudo tee {BACKLIGHT_PATH} > /dev/null')

    def wake_display(self):
        if self.is_asleep:
            self.is_asleep = False
            os.system(f'echo 0 | sudo tee {BACKLIGHT_PATH} > /dev/null')
            self.build_dashboard()

    def touch_listener(self):
        try:
            device = evdev.InputDevice(TOUCH_DEVICE)
            last_tap = 0
            for event in device.read_loop():
                if self.is_asleep and event.type == evdev.ecodes.EV_KEY and event.value == 1:
                    current_time = time.time()
                    if current_time - last_tap < 0.6:
                        self.root.after(0, self.wake_display)
                    last_tap = current_time
        except Exception:
            pass

    def run(self):
        self.root.mainloop()

if __name__ == "__main__":
    app = MatterDeskCore()
    app.run()