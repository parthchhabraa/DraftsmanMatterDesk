# MatterDesk v6

The touchscreen on Parth's study desk: a Raspberry Pi 4 with an 800x480 display,
wired into draftsmanbrain, the Mac and the iPhone.

v6 replaces the single-file Tkinter app with a small Python service and a web UI
that runs fullscreen in Chromium. The same desk also opens on the phone or Mac over
Tailscale.

a parthchhabra production

## What it does

| Page | What is on it |
|---|---|
| Home | The day dial: daylight, your plan, study done, goal ring, now hand. Now row with one-tap start for the planned block, next countdown, next task, music, brain LEDs, batteries |
| Study | **Sprint** ring timer with Lock-in. **Plan** your routine (fixed blocks like school, study blocks). **Insights**: 14-day chart, 30-day subject split, heatmap. **Mock scores** plotted against your target |
| Brain | draftsmanbrain CPU/RAM/disk, every service and container with Restart, Wake desktop, Inbox |
| Ask | Chat with the Ollama model on draftsmanbrain, streamed. Mic goes through Murmur |
| Claude | A shelf of your Claude artifacts. Tap one and it opens full screen on the desk; Back to desk (or a triple-tap) returns. Share an artifact link from the iPhone with Send to Desk to add it |
| Network | Tailnet devices, exit node on/off and Proton exit location, AdGuard stats, home Wi-Fi map with block, the DPN hotspot with QR |
| Devices | Mac battery/CPU/front app, Lock, Display off, Send text to clipboard, Notify, Keep awake. iPhone and iPad battery and Focus |
| Music | Spotify now playing, transport, volume, playlists, output device. AirPlay receiver |
| Desk | Tasks, notes, flashcards with spaced repetition, countdowns, **alarms and quick timers** (full-screen ring, snooze, Mac notification) |
| System | Pi health, Wi-Fi, checks, log, colours, update, power |

**Lock-in** is the headline feature: start a sprint with Lock-in on (or turn on the
Study Focus on the iPhone) and AdGuard blocks Instagram, YouTube and the rest on
every device on the tailnet until the sprint ends. Optional: start a playlist, lock the Mac.

## How it fits together

```
 iPhone (Shortcuts) ─┐                      ┌─ Ollama, Murmur, AdGuard, Docker
 Mac (desk_agent) ───┼─> Pi: desk service ──┼─> draftsmanbrain: brain-api v2 (:8010)
 Phone/Mac browser ──┘   :8420, ui/ in      └─ Spotify, Open-Meteo
                         Chromium kiosk
```

- `desk/` the Pi service (FastAPI). Each feature is an engine in `desk/engines/`; they
  publish live state through one websocket, so every open screen updates together.
- `ui/` the interface. Plain ES modules, no build step.
- `brain/` brain-api v2 for draftsmanbrain. Drop-in for v1 (same token, same `/status` and `/wol`).
- `companions/mac` the Mac agent. `companions/iphone` the Shortcuts recipes.

Secrets live only in `config/desk.toml` (Pi) and `~/brain-api/.env` (server). Both are gitignored.

## Install

### 1. draftsmanbrain

```
scp -r brain parthchhabra@100.103.94.116:~/brain-src
ssh -t parthchhabra@100.103.94.116 'cd ~/brain-src && ./setup.sh'
```
Then edit `~/brain-api/.env`: the desktop's real MAC in `BRAIN_WOL`, the AdGuard login,
the Murmur token. `sudo systemctl restart brain-api`.

brain-api listens on 127.0.0.1 and is reached through `tailscale serve`, so the desk's
`[brain] url` must be the `https://draftsmanbrain.<tailnet>.ts.net` address that `setup.sh` prints,
not `http://100.103.94.116:8010`.

For exit locations, download WireGuard configs from Proton into `/etc/wireguard/proton/<name>.conf`
(for example `netherlands.conf`). Test one with your phone on the exit node before relying on it.

### 2. The Pi

```
cd ~/matterdesk          # the existing clone
git fetch && git checkout v6
./install.sh
```
It keeps your v5 notes, tasks, flashcards, countdown, brain link, Spotify login and
Firebase sessions. Fill `[brain]`, `[murmur]` and `[spotify]` in `config/desk.toml`, then reboot.

The Pi should be on Tailscale with the name `matterdesk`.

### 3. Mac

```
cd companions/mac && ./install.sh http://matterdesk:8420 <device_key from desk.toml>
```

### 4. iPhone and iPad

Follow `companions/iphone/SHORTCUTS.md`.

### Phone or Mac browser

Open `http://matterdesk:8420/?key=<remote_key>` once. The key is printed at the end of `install.sh`.

## Work on it without the Pi

```
pip install -r requirements.txt
python -m desk demo        # fake data, http://127.0.0.1:8420/?kiosk shows the Pi layout
python -m pytest tests -q
```

## Updating

System, Update pulls `[ota] branch` from GitHub, installs requirements and restarts.
While v6 is being tried out it points at `v6`. After merging to `main`, set `branch = "main"`.

## Security note

The v5 code had the Spotify client secret in `matterdesk.py` and `auth.py`, and this repo is public.
Rotate it in the Spotify developer dashboard and put the new one only in `config/desk.toml`.
The old DPN hotspot password was also in the code; v6 generates a new one per desk.
