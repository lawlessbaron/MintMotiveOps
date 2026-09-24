"""Local Agent API — the small set of endpoints the local hardware agent
(local_agent/flasher_agent.py, running on the workshop PC) calls to report
firmware-flash results and smart-plug wattage readings back into MintMotive
Ops. Every route here is authenticated by the X-API-Key header (generated
and shown at Administration > Local Agent) instead of the normal browser
login session, and this blueprint is exempted from the app's login gate in
app/__init__.py — see require_login()."""
import functools
from datetime import datetime, timedelta
from flask import Blueprint, request, jsonify
from ..db import get_db, now_str
from .. import email_client

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


def _require_tasks_key(view):
    """Separate from _require_api_key/local_agent_api_key on purpose — this
    key is handed to an external cron service (e.g. cron-job.org) to ping
    this endpoint daily, a different trust boundary than the workshop PC's
    local agent, so rotating one never affects the other."""
    @functools.wraps(view)
    def wrapped(*args, **kwargs):
        db = get_db()
        company = db.execute("SELECT tasks_api_key FROM company_settings WHERE id=1").fetchone()
        expected = company["tasks_api_key"] if company else None
        provided = request.args.get("key") or request.headers.get("X-API-Key")
        if not expected or not provided or provided != expected:
            return jsonify({"ok": False, "error": "invalid or missing key"}), 401
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


@bp.route("/tasks/send-review-requests")
@_require_tasks_key
def send_review_requests():
    """Meant to be pinged daily by an external scheduler (this app has no
    background job runner of its own — see Administration > Scheduled
    Tasks for the URL + key to give a free cron service). Idempotent: a
    build only ever gets review_request_sent_at set once, so pinging this
    ten times a day or once a week both do the same thing — only genuinely
    new due units go out each time."""
    db = get_db()
    company = db.execute("SELECT review_request_days FROM company_settings WHERE id=1").fetchone()
    days = company["review_request_days"] or 7
    cutoff = (datetime.utcnow() - timedelta(days=days)).strftime("%Y-%m-%d")

    review_link = db.execute(
        "SELECT url FROM quick_links WHERE link_type='Google Review Page' AND active=1 ORDER BY id LIMIT 1"
    ).fetchone()

    due_builds = db.execute(
        "SELECT b.id, b.build_number, c.client_name, c.email AS client_email FROM builds b "
        "JOIN clients c ON c.id = b.client_id "
        "WHERE b.status IN ('Shipped','Complete') AND b.ship_date IS NOT NULL "
        "AND b.ship_date <= ? AND b.review_request_sent_at IS NULL",
        (cutoff,),
    ).fetchall()

    sent, skipped = [], []
    for b in due_builds:
        if not b["client_email"]:
            skipped.append({"build_number": b["build_number"], "reason": "client has no email"})
            continue
        if not review_link:
            skipped.append({"build_number": b["build_number"], "reason": "no active Google Review Page quick link configured"})
            continue
        body = (
            f"Hi {b['client_name']},\n\nHope you're enjoying your {b['build_number']} build! "
            f"If you have a minute, a quick review would really help us out:\n{review_link['url']}\n\n"
            f"Thanks,\nMintMotive"
        )
        try:
            ok = email_client.send_email(b["client_email"], "How's everything going?", body)
        except Exception:
            ok = False
        if ok:
            db.execute("UPDATE builds SET review_request_sent_at=? WHERE id=?", (now_str(), b["id"]))
            db.commit()
            sent.append(b["build_number"])
        else:
            skipped.append({"build_number": b["build_number"], "reason": "SMTP not configured or send failed — will retry next run"})

    return jsonify({"ok": True, "sent": sent, "skipped": skipped})
