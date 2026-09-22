# MintMotive Ops — Local Agent

A browser can't talk to a USB programmer or poll a smart plug on your LAN
directly. This small helper program runs on the workshop PC that has that
hardware physically attached (or is on the same LAN as your smart plugs)
and does that work on behalf of the MintMotive Ops pages open in your
browser — Firmware Flashing (a Build's detail page, or Kit Firmware
Versions) and IoT Power Monitoring (an Asset's detail page).

It listens on `http://localhost:8765` only — a MintMotive Ops page open in
a browser on that *same* PC can reach it (browsers allow a page to call
`localhost` even when the page itself is served from elsewhere), but
nothing outside that machine can.

## Setup

1. Copy this whole `local_agent/` folder onto the workshop PC (the one with
   the USB programmer plugged in, or on the same network as your smart
   plugs).
2. Install Python 3.9+ if it isn't already there.
3. Install dependencies:
   ```
   pip install -r requirements.txt
   ```
4. For firmware flashing, install `avrdude` and make sure it's on your
   system PATH (or set `avrdude_path` in config.json to its full path).
   - Windows: install via [avrdude's releases](https://github.com/avrdudes/avrdude/releases) or through an Arduino IDE install (it ships avrdude bundled — point `avrdude_path` at that copy).
   - macOS: `brew install avrdude`
   - Linux: `sudo apt install avrdude` (or your distro's equivalent)
5. Copy `config.example.json` to `config.json` and fill in:
   - `mintmotive_url` — the URL you use to reach MintMotive Ops in your browser (e.g. `http://192.168.1.50:5000`).
   - `api_key` — from **Administration > Local Agent** in the app (generate one there if you haven't).
   - `programmer` / `mcu` / `baud_rate` — match your board (defaults suit a typical Arduino Uno/Nano-class AVR board; check your board's datasheet or existing avrdude command if it's different).
6. Run it:
   ```
   python3 flasher_agent.py
   ```
   You should see `MintMotive Ops Local Agent listening on http://localhost:8765`.
   Leave this running while you're flashing boards or want power readings
   collected — it's a normal foreground process; close the terminal (or
   Ctrl+C) to stop it. Set it up as a background/startup service later if
   you want it always running.
7. On that same PC, open MintMotive Ops in your browser, go to a Build's
   detail page, pick a firmware version under **Flash to Device**, and
   click the button. The page will report back the real result once
   avrdude finishes.

## What it does

- **`POST /flash`** — MintMotive Ops' browser page sends it a firmware
  file's URL plus the build/firmware-version being flashed. It downloads
  the file, auto-detects the USB serial port (or uses `port_override` if
  you set one), runs `avrdude`, and reports the result back to MintMotive
  Ops' `/api/firmware-flash-log` — which is what shows up in the Build's
  Flash History and Administration > Local Agent.
- **Background power polling** — every `power_poll_interval_seconds`
  (default 30s), it asks MintMotive Ops which Assets have a
  `power_plug_reference` set, polls each one over HTTP (Shelly Gen1 and
  Tasmota-style APIs are built in — add another branch to
  `_read_plug_watts()` in `flasher_agent.py` for a different smart-plug
  brand), and reports wattage back to `/api/power-readings`. This only
  starts if `mintmotive_url` and `api_key` are set in `config.json`.

## Troubleshooting

- **"Can't reach the Local Agent" in the browser** — make sure
  `flasher_agent.py` is running, and that you're opening MintMotive Ops
  from the *same PC* the agent is running on (it only listens on
  localhost).
- **"No USB serial device found"** — check the board is plugged in, its
  drivers are installed, and no other program (like the Arduino IDE's
  Serial Monitor) has the port open.
- **avrdude errors** — the raw avrdude output is included in the Flash
  History log line so you can see exactly what it reported.
- **No power readings showing up** — confirm `mintmotive_url`/`api_key`
  are set in `config.json` (the agent prints a message on startup if
  they're missing) and that the plug's IP/hostname in the Asset's Power
  Plug Reference field is reachable from the workshop PC.
