#!/bin/bash
# Draftsman MatterDesk - Automated Deployment Pipeline

REPO_URL="https://github.com/YOUR_USERNAME/Draftsman-MatterDesk.git"
INSTALL_DIR="/home/st6b/matterdesk"

# 1. Dependency Injection
sudo apt update
sudo apt install -y git python3-tk python3-evdev python3-pil python3-pil.imagetk uxplay procps

# 2. Hardware Permissions
sudo usermod -aG input st6b

# 3. Repository Instantiation
if [ -d "$INSTALL_DIR" ]; then
    rm -rf "$INSTALL_DIR"
fi
git clone $REPO_URL $INSTALL_DIR

# 4. Wallpaper Configuration (Wayland/Wayfire)
CONF_FILE="$HOME/.config/pcmanfm/LXDE-pi/desktop-items-0.conf"
mkdir -p ~/.config/pcmanfm/LXDE-pi/
cp /etc/xdg/pcmanfm/LXDE-pi/desktop-items-0.conf ~/.config/pcmanfm/LXDE-pi/ 2>/dev/null
sed -i "s|^wallpaper=.*|wallpaper=$INSTALL_DIR/images/wallpaper.png|" $CONF_FILE
sed -i "s|^wallpaper_mode=.*|wallpaper_mode=stretch|" $CONF_FILE

# 5. Systemd Daemon Registration (OTA & Autostart)
sudo cp $INSTALL_DIR/matterdesk.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable matterdesk.service

# 6. Reboot to Finalize Kernel/Group Changes
sudo reboot