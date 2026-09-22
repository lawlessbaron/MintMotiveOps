from flask import Blueprint, render_template, request, jsonify
from ..db import get_db, apply_build_status_change

bp = Blueprint("workshop", __name__, url_prefix="/workshop")

BOARD_STATUSES = ["Queued", "Printing", "Assembly", "QC", "Ready to Ship", "Shipped"]


@bp.route("/")
def board():
    db = get_db()
    builds = db.execute(
        "SELECT b.*, k.kit_name, c.client_name FROM builds b JOIN kits k ON k.id=b.kit_id "
        "LEFT JOIN clients c ON c.id=b.client_id WHERE b.status != 'Complete' ORDER BY b.created_at"
    ).fetchall()
    columns = {status: [] for status in BOARD_STATUSES}
    for b in builds:
        columns.setdefault(b["status"], []).append(b)
    return render_template("workshop/board.html", columns=columns, statuses=BOARD_STATUSES)


@bp.route("/move", methods=["POST"])
def move():
    """Vanilla-JS drag-and-drop drop target — same status-change logic
    (stock reservation/consumption) as the Build detail page's status
    dropdown, just reachable without a full page reload."""
    db = get_db()
    build_id = request.form.get("build_id", type=int)
    new_status = request.form.get("status")
    if not build_id or new_status not in BOARD_STATUSES + ["Complete"]:
        return jsonify({"ok": False, "error": "Invalid request"}), 400
    apply_build_status_change(db, build_id, new_status)
    return jsonify({"ok": True})
