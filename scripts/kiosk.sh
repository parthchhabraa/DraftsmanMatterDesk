#!/bin/bash
# Opens the desk fullscreen in Chromium on the Pi's touchscreen and keeps it open.
URL="http://127.0.0.1:8420/"
BROWSER=$(command -v chromium-browser || command -v chromium)
until curl -fs "$URL/api/health" >/dev/null 2>&1; do sleep 1; done
while true; do
  "$BROWSER" --kiosk --app="$URL" \
    --ozone-platform=wayland --enable-features=UseOzonePlatform \
    --noerrdialogs --disable-infobars --no-first-run --disable-session-crashed-bubble \
    --disable-pinch --overscroll-history-navigation=0 --disable-features=Translate,TouchpadOverscrollHistoryNavigation \
    --check-for-update-interval=31536000 --password-store=basic \
    --use-fake-ui-for-media-stream --autoplay-policy=no-user-gesture-required \
    --user-data-dir="$HOME/.config/matterdesk-kiosk" >/dev/null 2>&1
  sleep 2
done
