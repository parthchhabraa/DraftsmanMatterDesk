#!/bin/bash
# MatterDesk v6 installer for the Raspberry Pi. Run from the repo folder: ./install.sh
# Safe to re-run. Moves your v5 data, Spotify login, Firebase key and brain link across.
set -euo pipefail
cd "$(dirname "$0")"
DIR="$(pwd)"; ME="$(whoami)"; UID_="$(id -u)"
say(){ printf '\n== %s\n' "$*"; }

say "system packages"
sudo apt-get update -qq
sudo apt-get install -y -qq python3-venv python3-evdev curl git util-linux network-manager hostapd dnsmasq wireguard-tools nmap >/dev/null
sudo apt-get install -y -qq chromium-browser >/dev/null 2>&1 || sudo apt-get install -y -qq chromium >/dev/null
sudo apt-get install -y -qq uxplay >/dev/null 2>&1 || echo "uxplay not in apt here; AirPlay stays off until it is installed"
sudo systemctl disable --now hostapd dnsmasq >/dev/null 2>&1 || true   # the desk starts them when the hotspot is on

say "python env"
[ -d .venv ] || python3 -m venv --system-site-packages .venv
.venv/bin/pip install -q -r requirements.txt

say "settings"
mkdir -p data
if [ ! -f config/desk.toml ]; then
  cp config/desk.example.toml config/desk.toml
  key(){ python3 -c 'import secrets;print(secrets.token_urlsafe(18))'; }
  sed -i "s|^remote_key = \"\"|remote_key = \"$(key)\"|; s|^device_key = \"\"|device_key = \"$(key)\"|" config/desk.toml
  # carry v5 state across
  if [ -f data/brain_config.json ]; then
    BURL=$(python3 -c 'import json;print(json.load(open("data/brain_config.json")).get("brain_url",""))')
    BTOK=$(python3 -c 'import json;print(json.load(open("data/brain_config.json")).get("brain_token",""))')
    python3 - "$BURL" "$BTOK" <<'PY'
import sys,re
p="config/desk.toml"; s=open(p).read()
s=re.sub(r'(\[brain\]\nurl = )""', r'\1"%s"' % sys.argv[1], s); s=re.sub(r'(\ntoken = )""(\s+# BRAIN_API_TOKEN)', r'\1"%s"\2' % sys.argv[2], s, count=1)
open(p,"w").write(s)
PY
    echo "brain link copied from v5"
    case "$BURL" in http://100.*) echo "!! v5 used $BURL. brain-api v2 is reached at its https ts.net address; update [brain] url.";; esac
  fi
  [ -f .cache ] && cp .cache data/spotify.cache && echo "Spotify login copied from v5 (needs your new client secret too)"
  [ -f serviceAccountKey.json ] && sed -i "s|^key_path = \"\"|key_path = \"$DIR/serviceAccountKey.json\"|" config/desk.toml && echo "Firebase key found, old sessions will be imported"
  chmod 600 config/desk.toml
fi

say "permissions the desk needs"
cat <<SUDO | sudo tee /etc/sudoers.d/matterdesk >/dev/null
$ME ALL=(root) NOPASSWD: /usr/bin/sh -c echo [01] > /sys/class/backlight/*, /usr/bin/systemctl reboot, /usr/bin/systemctl poweroff, /usr/bin/systemctl restart matterdesk.service, /usr/bin/systemctl restart dnsmasq, /usr/bin/systemctl restart hostapd, /usr/bin/systemctl stop hostapd dnsmasq, /usr/bin/systemctl unmask hostapd, /usr/bin/nmcli, /usr/sbin/iptables, /usr/sbin/sysctl -w net.ipv4.ip_forward=1, /usr/sbin/ip, /usr/bin/ip, /usr/bin/wg-quick, /usr/bin/install -m 600 * /etc/hostapd/hostapd.conf, /usr/bin/install -m 600 * /etc/dnsmasq.d/dpn.conf
SUDO
sudo chmod 440 /etc/sudoers.d/matterdesk && sudo visudo -cf /etc/sudoers.d/matterdesk >/dev/null
sudo usermod -aG input "$ME"

say "desk service"
WL=$(ls /run/user/$UID_ 2>/dev/null | grep -m1 '^wayland-[0-9]$' || echo wayland-0)
sed -e "s|__USER__|$ME|g" -e "s|__DIR__|$DIR|g" -e "s|__UID__|$UID_|g" -e "s|__WAYLAND__|$WL|g" systemd/matterdesk.service \
  | sudo tee /etc/systemd/system/matterdesk.service >/dev/null
systemctl --user disable --now matterdesk.service >/dev/null 2>&1 || true   # v5 ran as a user service on some setups
sudo systemctl daemon-reload
sudo systemctl enable --now matterdesk.service
sudo systemctl restart matterdesk.service

say "kiosk on boot"
"$DIR/scripts/kiosk-setup.sh"

say "check"
for i in $(seq 1 40); do curl -fsS http://127.0.0.1:8420/api/health 2>/dev/null && { echo; break; }; sleep 1; done
if ! curl -fs http://127.0.0.1:8420/api/health >/dev/null 2>&1; then
  echo "!! desk service did not come up in 40 s. Last log lines:"
  sudo journalctl -u matterdesk -n 25 --no-pager
fi
command -v tailscale >/dev/null || echo "!! Tailscale is not installed: curl -fsSL https://tailscale.com/install.sh | sh && sudo tailscale up --hostname matterdesk"
echo
echo "Next:"
echo "  1. Fill [brain], [murmur] and [spotify] in $DIR/config/desk.toml, then: sudo systemctl restart matterdesk"
echo "  2. Spotify (new secret first): .venv/bin/python -m desk spotify-auth"
echo "  3. Reboot to start the kiosk: sudo reboot"
echo "  Phone/Mac: http://matterdesk:8420/?key=$(sed -n 's/^remote_key = "\(.*\)"/\1/p' config/desk.toml)"
