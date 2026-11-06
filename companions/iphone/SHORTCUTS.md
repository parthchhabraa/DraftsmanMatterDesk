# iPhone and iPad shortcuts for MatterDesk

Three shortcuts. Each one is a single **Get Contents of URL** action, so they take a
couple of minutes to build in the Shortcuts app. The phone must be on Tailscale.

You need two values from `config/desk.toml` on the Pi:

- **Desk address**: `http://matterdesk:8420` (the Pi's Tailscale name)
- **Device key**: `[devices] device_key`

## 1. Report battery

New shortcut, name it **Desk battery**:

1. **Get Battery Level**
2. **Get Contents of URL**
   - URL: `http://matterdesk:8420/api/devices/report`
   - Method: `POST`
   - Headers: `X-Device-Key` = your device key
   - Request Body: `JSON`
     - `device` (Text) = `iphone` (use `ipad` on the iPad)
     - `battery` (Number) = *Battery Level* (the variable from step 1)
     - `charging` (Boolean) = leave out, or add **Is Charging** before step 2 and pass it here

Then **Automation, New, Battery Level**: "Falls below 50%", "Falls below 20%" and
"Rises above 80%", plus **Charger: is connected / disconnected**. Each runs
*Desk battery*, set to **Run Immediately**.

## 2. Study Focus starts lock-in

The desk starts a lock-in sprint when the iPhone reports a Focus named like
`[study] focus_name` (default `Study`) and ends it when the Focus turns off.

New shortcut **Desk focus on**: one **Get Contents of URL**, same URL, method and
header as above, JSON body `device` = `iphone`, `focus` = `Study`.

New shortcut **Desk focus off**: same, with `focus` set to an empty Text.

**Automation, New, Focus, Study**: "When turning on" runs *Desk focus on*;
a second automation "When turning off" runs *Desk focus off*. Run Immediately.

Lock-in then blocks the services in `[study] lockin_block` through AdGuard on every
device on the tailnet, and lifts the block when the sprint ends.

## 3. Send to Desk (share sheet)

New shortcut **Send to Desk**, turn on **Show in Share Sheet** and accept
Images, URLs, Text and Files.

1. **Get Contents of URL**
   - URL: `http://matterdesk:8420/api/inbox`
   - Method: `POST`
   - Headers: `X-Device-Key` = your device key
   - Request Body: `Form`
     - `source` (Text) = `iphone`
     - for a photo or file: `file` (File) = *Shortcut Input*
     - for a link or text: `text` (Text) = *Shortcut Input*

The item lands in the brain inbox and shows on the desk. A claude.ai artifact link goes
straight onto the desk's Claude shelf instead: in the Claude app, Share on an artifact, then Send to Desk. From the desk you can
send it straight on to the Mac.

Penotron and Anamnis post to the same place on draftsmanbrain directly
(`POST /inbox` on brain-api with `X-Brain-Token`, form fields `source` and `file`).
