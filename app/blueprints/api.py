"""Local Agent API — the small set of endpoints the local hardware agent
(local_agent/flasher_agent.py, running on the workshop PC) calls to report
firmware-flash results and smart-plug wattage readings back into MintMotive
Ops. Every route here is authenticated by the X-API-Key header (generated
and shown at Administration > Local Agent) instead of the normal browser
login session, and this blueprint is exempted from the app's login gate in
app/__init__.py — see require_login()."""
import functools
from flask import Blueprint, request, jsonify
from ..db import get_db

bp = Blueprint("api", __name__, url_prefix="/api")


def _require_api_key(view):
    @functools.wraps(view)
    def wrapped(*args, **kwargs):
        db = get_db()
        company = db.execute("SELECT local_agent_api_key FROM company_settings WHERE id=1").fetchone()
        expected = company["local_agent_api_key"] if company else None
        provided = request.headers.get("X-API-Key")
        if not expected or not provided or provided != expected:
            return jsonify({"ok": False, "error": "invalid or missing X-API-Key"}), 401
        return view(*args, **kwargs)
    return wrapped


@bp.route("/ping")
@_require_api_key
def ping():
    """The local agent (and the Administration > Local Agent 'Test Connection'
    button, if added later) calls this first to confirm the API key is valid
    and the app is reachable."""
    return jsonify({"ok": True, "app": "MintMotive Ops"})


@bp.route("/power-monitored-assets")
@_require_api_key
def power_monitored_assets():
    """Tells the local agent which assets to poll — anything with a
    power_plug_reference set (its LAN IP or hostname)."""
    db = get_db()
    rows = db.execute(
        "SELECT id, asset_name, power_plug_reference FROM assets "
        "WHERE power_plug_reference IS NOT NULL AND power_plug_reference != ''"
    ).fetchall()
    return jsonify({"ok": True, "assets": [dict(r) for r in rows]})


@bp.route("/firmware-flash-log", methods=["POST"])
@_require_api_key
def firmware_flash_log():
    """Called by the local agent immediately after it finishes an avrdude
    (or similar) flash attempt against a USB-connected board. The browser
    page tells the agent which build_id/firmware_version_id it's flashing;
    the agent reports back here with the real result."""
    db = get_db()
    payload = request.get_json(silent=True) or {}
    result = payload.get("result")
    if result not in ("Success", "Failed"):
        return jsonify({"ok": False, "error": "result must be 'Success' or 'Failed'"}), 400
    cur = db.execute(
        "INSERT INTO firmware_flash_log (build_id, firmware_version_id, device_port, result, log_output) "
        "VALUES (?,?,?,?,?)",
        (payload.get("build_id") or None, payload.get("firmware_version_id") or None,
         payload.get("device_port"), result, payload.get("log_output")),
    )
    db.commit()
    return jsonify({"ok": True, "id": cur.lastrowid})


@bp.route("/power-readings", methods=["POST"])
@_require_api_key
def power_readings():
    """Accepts either a single reading {asset_id, watts} or a batch
    {readings: [{asset_id, watts}, ...]} — the local agent polls all its
    configured plugs on a timer and can report them together."""
    db = get_db()
    payload = request.get_json(silent=True) or {}
    items = payload.get("readings") if "readings" in payload else [payload]
    inserted = 0
    for item in items:
        asset_id = item.get("asset_id")
        watts = item.get("watts")
        if asset_id is None or watts is None:
            continue
        db.execute("INSERT INTO power_readings (asset_id, watts) VALUES (?,?)", (asset_id, watts))
        inserted += 1
    db.commit()
    return jsonify({"ok": True, "inserted": inserted})
