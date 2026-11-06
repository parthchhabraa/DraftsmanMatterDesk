#!/bin/bash
# Installs the MatterDesk agent on this Mac. Run: ./install.sh http://matterdesk:8420 <device_key>
set -euo pipefail
DESK="${1:-}"; KEY="${2:-}"
[ -n "$DESK" ] && [ -n "$KEY" ] || { echo "usage: ./install.sh http://<pi-tailscale-name>:8420 <device_key>"; exit 2; }
DIR="$HOME/Library/Application Support/MatterDesk"
PLIST="$HOME/Library/LaunchAgents/com.parthchhabra.matterdesk-agent.plist"
mkdir -p "$DIR" "$HOME/Library/LaunchAgents"
cp "$(dirname "$0")/desk_agent.py" "$DIR/desk_agent.py"
printf '{"desk": "%s", "key": "%s"}\n' "$DESK" "$KEY" > "$DIR/agent.json"
chmod 600 "$DIR/agent.json"
cat > "$PLIST" <<PL
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>Label</key><string>com.parthchhabra.matterdesk-agent</string>
  <key>ProgramArguments</key><array><string>/usr/bin/python3</string><string>$DIR/desk_agent.py</string></array>
  <key>RunAtLoad</key><true/>
  <key>KeepAlive</key><true/>
  <key>StandardErrorPath</key><string>$DIR/agent.log</string>
</dict></plist>
PL
launchctl bootout "gui/$(id -u)" "$PLIST" 2>/dev/null || true
launchctl bootstrap "gui/$(id -u)" "$PLIST"
sleep 3
curl -fsS -H "X-Device-Key: $KEY" -H 'content-type: application/json' -d '{"device":"mac","agent":true}' "$DESK/api/devices/report" >/dev/null \
  && echo "Agent running. The Mac shows up on the desk's Devices page within a minute." \
  || echo "Installed, but the desk did not answer at $DESK. Check Tailscale and the address."
