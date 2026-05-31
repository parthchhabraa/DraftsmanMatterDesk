#!/bin/bash
echo ">>> INITIALIZING MATTERDESK ARCHITECTURE <<<"

# 1. System Dependencies
sudo apt update
sudo apt install -y python3-tk nodejs npm libusb-1.0-0-dev cmake chromium-browser network-manager coreutils
sudo pip3 install spotipy pillow requests firebase-admin evdev --break-system-packages

# 2. USB Permissions (Carlinkit)
echo 'SUBSYSTEM=="usb", ATTR{idVendor}=="1314", ATTR{idProduct}=="152*", MODE="0666", GROUP="plugdev"' | sudo tee /etc/udev/rules.d/50-carplay.rules
sudo udevadm control --reload-rules && sudo udevadm trigger

# 3. Systemd Daemon Deployment
cat <<EOF | sudo tee /etc/systemd/system/matterdesk.service
[Unit]
Description=Draftsman MatterDesk Core
After=graphical.target

[Service]
User=st6b
Environment=DISPLAY=:0
Environment=WAYLAND_DISPLAY=wayland-1
Environment=XDG_RUNTIME_DIR=/run/user/1000
WorkingDirectory=/home/st6b/matterdesk
ExecStart=/usr/bin/python3 /home/st6b/matterdesk/matterdesk.py
Restart=always
RestartSec=5

[Install]
WantedBy=graphical.target
EOF

sudo systemctl daemon-reload
sudo systemctl enable matterdesk.service

# 4. Plymouth Silent Boot (Optional)
echo "disable_splash=1" | sudo tee -a /boot/firmware/config.txt > /dev/null

echo ">>> DEPLOYMENT COMPLETE. PLEASE REBOOT. <<<"