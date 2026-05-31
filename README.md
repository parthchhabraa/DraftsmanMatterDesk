# MatterDesk v2.0 (System Core)

High-performance, hardware-optimized smart desk dashboard built for Raspberry Pi 4 (Wayland). Features preemptive frame-stacking, eliminating CPU-bound UI destructive rendering to operate within 1GB RAM constraints.

## Subsystem Architecture
* **AirPlay Pipeline:** `uxplay` integration via XWayland surface rendering.
* **CarPlay Engine:** Node-based Carlinkit bridging rendering to Chromium kiosk.
* **Spotify Vinyl Matrix:** Asynchronous API polling, image mask compositing, and OAuth token caching.
* **Monk Mode (YPT):** Firebase real-time database sync, immutable time-logging, task pipeline pulling.
* **NOC (Settings):** Direct `nmcli` network management and GitHub OTA (Over-The-Air) pull routines.

## Deployment Protocol

1. **Clone the Repository**
   ```bash
   cd /home/st6b
   git clone [https://github.com/YOUR_USERNAME/matterdesk.git](https://github.com/YOUR_USERNAME/matterdesk.git)
   cd matterdesk

2. **Execute the Installer**
Automates dependency injection, udev rules for Carlinkit, and systemd daemon registration.
chmod +x install.sh
./install.sh

3. **Cryptographic Authentication Requirements**
Spotify: Execute python3 auth.py via SSH and complete the OAuth flow via your local machine's browser to generate the local .cache token.

Firebase: Place your serviceAccountKey.json directly into the /home/st6b/matterdesk/ root directory.

4. **Wayland Desktop Bypass**
To boot directly into the GUI and suppress the Pi desktop environment, modify the Wayfire autostart configuration (~/.config/wayfire.ini):
[autostart]
# Comment out panel and background
# panel = wf-panel-pi
# background = wf-background-pi
matterdesk = systemctl --user start matterdesk.service