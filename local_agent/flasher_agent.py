#!/usr/bin/env python3
"""MintMotive Ops — Local Agent.

Runs on the workshop PC that has the USB programmer (and/or is on the same
LAN as any IoT smart plugs) physically attached to it. A browser can't shell
out to avrdude or poll a plug on the LAN directly — but a MintMotive Ops
page served over HTTPS/HTTP CAN fetch() a plain http://localhost:<port>
endpoint, because browsers treat localhost/127.0.0.1 as a "potentially
trustworthy" exception to mixed-content blocking. So the Flash-to-Device
button on a Build's detail page (and the Kit Firmware Versions page) talks
to THIS process on http://localhost:8765, this process does the real
USB/network work, and it reports results back into MintMotive Ops itself
over its /api/* endpoints (see app/blueprints/api.py), authenticated with
the shared API key from Administration > Local Agent.

Two jobs:
  1. POST /flash — download a firmware file from MintMotive Ops, flash it to
     a USB-connected board with avrdude, and report the result back.
  2. A background thread that polls every smart-plug-monitored Asset on a
     timer and reports wattage readings back.

Setup: see README.md in this folder.
"""
import glob
import json
import os
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path

try:
    from flask import Flask, request, jsonify
except ImportError:
    sys.exit("Missing dependency 'flask' — run: pip install -r requirements.txt")
try:
    import requests
except ImportError:
    sys.exit("Missing dependency 'requests' — run: pip install -r requirements.txt")

CONFIG_PATH = Path(__file__).parent / "config.json"


def load_config():
    if not CONFIG_PATH.exists():
        sys.exit(
            f"Missing {CONFIG_PATH} — copy config.example.json to config.json "
            "and fill in mintmotive_url + api_key (from Administration > Local Agent)."
        )
    with open(CONFIG_PATH) as f:
        return json.load(f)


config = load_config()
app = Flask(__name__)


@app.after_request
def add_cors(resp):
    # The MintMotive Ops page (a different origin/port) calls this process
    # from browser JS, so every response needs CORS headers, and POST with a
    # JSON body triggers a preflight OPTIONS request the browser expects a
    # 2xx + these same headers on.
    resp.headers["Access-Control-Allow-Origin"] = "*"
    resp.headers["Access-Control-Allow-Methods"] = "GET, POST, OPTIONS"
    resp.headers["Access-Control-Allow-Headers"] = "Content-Type"
    return resp


# ---------------------------------------------------------------------------
# Firmware flashing
# ---------------------------------------------------------------------------

@app.route("/flash", methods=["POST", "OPTIONS"])
def flash():
    if request.method == "OPTIONS":
        return "", 204
    payload = request.get_json(silent=True) or {}
    firmware_url = payload.get("firmware_url")
    build_id = payload.get("build_id")
    firmware_version_id = payload.get("firmware_version_id")
    if not firmware_url:
        return jsonify({"result": "Failed", "error": "no firmware_url supplied"}), 400

    try:
        r = requests.get(firmware_url, timeout=30)
        r.raise_for_status()
    except Exception as e:
        return _report(build_id, firmware_version_id, None, "Failed", f"Firmware download failed: {e}")

    suffix = os.path.splitext(firmware_url)[1] or ".hex"
    tmp_path = None
    try:
        with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
            tmp.write(r.content)
            tmp_path = tmp.name

        port = config.get("port_override") or _detect_port()
        if not port:
            return _report(build_id, firmware_version_id, None, "Failed",
                            "No USB serial device found — check the board is connected and drivers are installed.")

        cmd = [
            config.get("avrdude_path", "avrdude"),
            "-c", config.get("programmer", "arduino"),
            "-p", config.get("mcu", "atmega328p"),
            "-P", port,
            "-b", str(config.get("baud_rate", 115200)),
            "-U", f"flash:w:{tmp_path}:i",
        ]
        try:
            proc = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
            log_output = (proc.stdout or "") + (proc.stderr or "")
            result = "Success" if proc.returncode == 0 else "Failed"
        except FileNotFoundError:
            return _report(build_id, firmware_version_id, port, "Failed",
                            f"avrdude not found at '{config.get('avrdude_path', 'avrdude')}' — "
                            "install it or set avrdude_path in config.json.")
        except subprocess.TimeoutExpired:
            return _report(build_id, firmware_version_id, port, "Failed", "avrdude timed out after 120s.")

        return _report(build_id, firmware_version_id, port, result, log_output)
    finally:
        if tmp_path:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass


def _detect_port():
    """Auto-picks the first likely USB serial device. Set port_override in
    config.json instead if you have more than one board/programmer attached
    and need a specific one every time."""
    try:
        import serial.tools.list_ports
        ports = list(serial.tools.list_ports.comports())
        return ports[0].device if ports else None
    except ImportError:
        candidates = glob.glob("/dev/ttyUSB*") + glob.glob("/dev/ttyACM*") + glob.glob("/dev/cu.usb*")
        return candidates[0] if candidates else None


def _report(build_id, firmware_version_id, port, result, log_output):
    """Files the real result with MintMotive Ops (Build detail's Flash
    History and Administration > Local Agent both read this back), then
    returns the same result to the browser that triggered the flash."""
    body = {
        "build_id": build_id,
        "firmware_version_id": firmware_version_id,
        "device_port": port,
        "result": result,
        "log_output": log_output,
    }
    try:
        requests.post(
            f"{config['mintmotive_url'].rstrip('/')}/api/firmware-flash-log",
            json=body, headers={"X-API-Key": config.get("api_key", "")}, timeout=10,
        )
    except Exception:
        pass  # the browser still gets the real result below even if reporting back failed
    return jsonify(body)


@app.route("/status")
def status():
    return jsonify({"ok": True, "detected_port": config.get("port_override") or _detect_port()})


# ---------------------------------------------------------------------------
# IoT power monitoring — polls each Asset with a power_plug_reference set
# (Assets > edit an asset) on a timer and reports wattage back.
# ---------------------------------------------------------------------------

def _read_plug_watts(reference):
    """Tries a couple of common smart-plug HTTP APIs against `reference`
    (its LAN IP or hostname). Add another branch here for your plug brand
    if neither matches — it just needs to return a float watts value or
    None (never raise)."""
    try:  # Shelly Gen1 (e.g. Shelly Plug S)
        r = requests.get(f"http://{reference}/status", timeout=5)
        if r.ok:
            data = r.json()
            meters = data.get("meters") or []
            if meters:
                return float(meters[0].get("power", 0))
    except Exception:
        pass
    try:  # Tasmota
        r = requests.get(f"http://{reference}/cm?cmnd=Status%208", timeout=5)
        if r.ok:
            data = r.json()
            power = data.get("StatusSNS", {}).get("ENERGY", {}).get("Power")
            if power is not None:
                return float(power)
    except Exception:
        pass
    return None


def _power_poll_loop():
    interval = config.get("power_poll_interval_seconds", 30)
    base_url = config["mintmotive_url"].rstrip("/")
    headers = {"X-API-Key": config.get("api_key", "")}
    while True:
        try:
            resp = requests.get(f"{base_url}/api/power-monitored-assets", headers=headers, timeout=10)
            assets = resp.json().get("assets", []) if resp.ok else []
            readings = []
            for a in assets:
                watts = _read_plug_watts(a["power_plug_reference"])
                if watts is not None:
                    readings.append({"asset_id": a["id"], "watts": watts})
            if readings:
                requests.post(f"{base_url}/api/power-readings", json={"readings": readings}, headers=headers, timeout=10)
        except Exception:
            pass  # keep polling across transient network/app-restart issues
        time.sleep(interval)


if __name__ == "__main__":
    if config.get("mintmotive_url") and config.get("api_key"):
        threading.Thread(target=_power_poll_loop, daemon=True).start()
    else:
        print("mintmotive_url/api_key not set in config.json — power monitoring disabled, flashing still works.")
    print("MintMotive Ops Local Agent listening on http://localhost:8765")
    app.run(host="127.0.0.1", port=8765)
