#!/bin/bash
# Installs brain-api v2 on draftsmanbrain. Run from this folder: ./setup.sh
# Safe to re-run. Keeps the token your v1 brain-api already uses.
set -euo pipefail
cd "$(dirname "$0")"
DIR="$HOME/brain-api"
ME="$(whoami)"
say(){ printf '\n== %s\n' "$*"; }

say "copying to $DIR"
mkdir -p "$DIR"
cp brain_api.py requirements.txt "$DIR/"

say "python env"
sudo apt-get install -y -qq python3-venv wireguard-tools >/dev/null
[ -d "$DIR/.venv" ] || python3 -m venv "$DIR/.venv"
"$DIR/.venv/bin/pip" install -q -r "$DIR/requirements.txt"

say "settings"
if [ ! -f "$DIR/.env" ]; then
  sed "s/__USER__/$ME/g" brain.example.env > "$DIR/.env"
  OLD=""
  OLDENV=$(systemctl cat brain-api.service 2>/dev/null | sed -n 's/^EnvironmentFile=-\{0,1\}//p' | head -1 || true)
  [ -n "$OLDENV" ] && [ -f "$OLDENV" ] && OLD=$(sed -n 's/^BRAIN_API_TOKEN=//p' "$OLDENV" | tr -d '"' | head -1)
  TOKEN="${OLD:-$(python3 -c 'import secrets;print(secrets.token_urlsafe(32))')}"
  sed -i "s|^BRAIN_API_TOKEN=.*|BRAIN_API_TOKEN=$TOKEN|" "$DIR/.env"
  [ -n "$OLD" ] && echo "kept the v1 token from $OLDENV" || echo "new token generated"
  chmod 600 "$DIR/.env"
  echo "!! edit $DIR/.env: real desktop MAC in BRAIN_WOL, AdGuard login, Murmur token"
fi

say "exit-location helper + sudo rules"
sudo install -m 755 bin/brain-exit-location /usr/local/bin/brain-exit-location
sudo mkdir -p /etc/wireguard/proton && sudo chmod 700 /etc/wireguard/proton
SVCS=$(sed -n 's/^BRAIN_SERVICES=//p' "$DIR/.env" | tr ',' '\n' | sed 's/.*/\/usr\/bin\/systemctl restart &.service/' | paste -sd, -)
echo "$ME ALL=(root) NOPASSWD: /usr/local/bin/brain-exit-location, /usr/bin/tailscale set --advertise-exit-node=true, /usr/bin/tailscale set --advertise-exit-node=false, $SVCS" \
  | sudo tee /etc/sudoers.d/brain-api >/dev/null
sudo chmod 440 /etc/sudoers.d/brain-api && sudo visudo -cf /etc/sudoers.d/brain-api >/dev/null
groups "$ME" | grep -q docker || echo "!! $ME is not in the docker group, container status will be empty (sudo usermod -aG docker $ME)"

say "service"
sed -e "s|__USER__|$ME|g" -e "s|__DIR__|$DIR|g" brain-api.service | sudo tee /etc/systemd/system/brain-api.service >/dev/null
sudo systemctl daemon-reload
sudo systemctl enable --now brain-api.service
sudo systemctl restart brain-api.service
sleep 2
TOKEN=$(sed -n 's/^BRAIN_API_TOKEN=//p' "$DIR/.env")
curl -fsS -H "X-Brain-Token: $TOKEN" http://127.0.0.1:8010/status | head -c 300; echo
sudo tailscale serve --bg 8010 >/dev/null 2>&1 || true
say "done. brain-api v2 is up. Desk config needs:"
echo "  [brain] url = \"$(tailscale status --json 2>/dev/null | python3 -c 'import sys,json;print("https://"+json.load(sys.stdin)["Self"]["DNSName"].rstrip("."))' 2>/dev/null || echo https://draftsmanbrain.<tailnet>.ts.net)\""
echo "  [brain] token = (BRAIN_API_TOKEN in $DIR/.env)"
