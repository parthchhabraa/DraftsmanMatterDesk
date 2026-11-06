#!/bin/bash
# Makes the kiosk start on login, for every Raspberry Pi OS desktop (labwc, wayfire, X11).
# Safe to re-run. Usage: scripts/kiosk-setup.sh [--now]
set -euo pipefail
DIR="$(cd "$(dirname "$0")/.." && pwd)"
K="$DIR/scripts/kiosk.sh"
chmod +x "$K"

# 1. Standard XDG autostart: read by lxsession on labwc, wayfire and X11 alike.
mkdir -p ~/.config/autostart
cat > ~/.config/autostart/matterdesk-kiosk.desktop <<D
[Desktop Entry]
Type=Application
Name=MatterDesk
Exec=$K
X-GNOME-Autostart-enabled=true
D

# 2. labwc: an earlier installer created ~/.config/labwc/autostart holding only our line,
#    which hides the system autostart (panel, desktop). Put that back.
LA=~/.config/labwc/autostart
if [ -f "$LA" ]; then
  sed -i '\#scripts/kiosk.sh#d' "$LA"
  [ -s "$LA" ] || { rm -f "$LA"; echo "restored the system labwc autostart"; }
fi
# 3. wayfire: drop the old direct hook, XDG autostart covers it now.
[ -f ~/.config/wayfire.ini ] && sed -i '/^matterdesk *=/d' ~/.config/wayfire.ini

# 4. Old v5 autostart entries that would fight for the screen.
for f in ~/.config/autostart/*.desktop; do
  [ "$f" = ~/.config/autostart/matterdesk-kiosk.desktop ] && continue
  grep -q "matterdesk.py" "$f" 2>/dev/null && { mv "$f" "$f.v5-disabled"; echo "disabled v5 autostart $f"; }
done

echo "kiosk autostart installed"
if [ "${1:-}" = "--now" ]; then
  RT="/run/user/$(id -u)"
  export XDG_RUNTIME_DIR="$RT"
  export WAYLAND_DISPLAY="${WAYLAND_DISPLAY:-$(ls "$RT" 2>/dev/null | grep -m1 '^wayland-[0-9]$' || true)}"
  [ -n "$WAYLAND_DISPLAY" ] || export DISPLAY="${DISPLAY:-:0}"
  pkill -f "scripts/kiosk.sh" 2>/dev/null || true; pkill -f "matterdesk-kiosk" 2>/dev/null || true; rm -f ~/.cache/matterdesk-kiosk.lock; sleep 1
  setsid "$K" >/dev/null 2>&1 < /dev/null &
  echo "kiosk starting on ${WAYLAND_DISPLAY:-X $DISPLAY}. Log: ~/.cache/matterdesk-kiosk.log"
fi
