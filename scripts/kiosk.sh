#!/bin/bash
# Opens the desk fullscreen in Chromium on the Pi's touchscreen and keeps it open.
# Log: ~/.cache/matterdesk-kiosk.log
BASE="http://127.0.0.1:8420"
LOG="$HOME/.cache/matterdesk-kiosk.log"
mkdir -p "$HOME/.cache"
exec >>"$LOG" 2>&1
echo "---- $(date) kiosk start, session=${XDG_SESSION_TYPE:-?} wayland=${WAYLAND_DISPLAY:-none} x=${DISPLAY:-none}"

# one launcher only, however many autostart hooks fire
exec 9>"$HOME/.cache/matterdesk-kiosk.lock"
flock -n 9 || { echo "already running"; exit 0; }

BROWSER=$(command -v chromium-browser || command -v chromium)
[ -n "$BROWSER" ] || { echo "chromium not installed"; exit 1; }

for i in $(seq 1 120); do curl -fs "$BASE/api/health" >/dev/null && break; sleep 1; done
echo "desk answered after ${i}s"

if [ -n "${WAYLAND_DISPLAY:-}" ]; then PLATFORM="--ozone-platform=wayland"; else PLATFORM="--ozone-platform=x11"; fi
command -v unclutter >/dev/null && [ -n "${DISPLAY:-}" ] && unclutter -idle 0.5 -root &

while true; do
  # 9222 is the localhost-only DevTools port the desk uses to open artifacts and bring you back.
  "$BROWSER" --kiosk --app="$BASE/?kiosk" $PLATFORM \
    --remote-debugging-port=9222 --remote-debugging-address=127.0.0.1 --remote-allow-origins=http://127.0.0.1:8420 \
    --noerrdialogs --disable-infobars --no-first-run --disable-session-crashed-bubble \
    --disable-pinch --overscroll-history-navigation=0 --disable-features=Translate,TouchpadOverscrollHistoryNavigation \
    --check-for-update-interval=31536000 --password-store=basic \
    --use-fake-ui-for-media-stream --autoplay-policy=no-user-gesture-required \
    --user-data-dir="$HOME/.config/matterdesk-kiosk"
  echo "$(date) chromium exited ($?), restarting"
  sleep 2
done
