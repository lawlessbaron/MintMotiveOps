from flask import Blueprint, render_template, request, redirect, url_for, flash
from ..db import get_db, generate_number, batch_pick_list, batch_pick_list_grid_maps

bp = Blueprint("batches", __name__, url_prefix="/batches")


@bp.route("/")
def index():
    db = get_db()
    batches = db.execute(
        "SELECT br.*, k.kit_name, "
        "(SELECT COUNT(*) FROM builds b WHERE b.batch_run_id = br.id) AS build_count "
        "FROM batch_runs br JOIN kits k ON k.id=br.kit_id ORDER BY br.created_at DESC"
    ).fetchall()
    return render_template("batches/index.html", batches=batches)


@bp.route("/new", methods=["GET", "POST"])
def new():
    db = get_db()
    kits = db.execute("SELECT * FROM kits WHERE status != 'Discontinued' ORDER BY kit_name").fetchall()
    if request.method == "POST":
        f = request.form
        number = generate_number("Batch Run")
        cur = db.execute(
            "INSERT INTO batch_runs (batch_number, kit_id, quantity, notes) VALUES (?,?,?,?)",
            (number, f["kit_id"], int(f.get("quantity", 1)), f.get("notes")),
        )
        db.commit()
        flash(f"Batch {number} created.", "success")
        return redirect(url_for("batches.detail", batch_id=cur.lastrowid))
    return render_template("batches/form.html", kits=kits)


@bp.route("/<int:batch_id>")
def detail(batch_id):
    db = get_db()
    batch = db.execute(
        "SELECT br.*, k.kit_name FROM batch_runs br JOIN kits k ON k.id=br.kit_id WHERE br.id=?", (batch_id,)
    ).fetchone()
    if batch is None:
        flash("Batch run not found.", "error")
        return redirect(url_for("batches.index"))
    pick_list = batch_pick_list(db, batch_id)
    grid_maps = batch_pick_list_grid_maps(db, pick_list)
    builds = db.execute(
        "SELECT b.*, c.client_name FROM builds b LEFT JOIN clients c ON c.id=b.client_id "
        "WHERE b.batch_run_id=? ORDER BY b.created_at", (batch_id,)
    ).fetchall()
    return render_template("batches/detail.html", batch=batch, pick_list=pick_list, grid_maps=grid_maps, builds=builds)


@bp.route("/<int:batch_id>/status", methods=["POST"])
def update_status(batch_id):
    db = get_db()
    db.execute("UPDATE batch_runs SET status=? WHERE id=?", (request.form["status"], batch_id))
    db.commit()
    flash("Batch status updated.", "success")
    return redirect(url_for("batches.detail", batch_id=batch_id))


@bp.route("/<int:batch_id>/spawn-builds", methods=["POST"])
def spawn_builds(batch_id):
    """Creates one queued Build per unit in the batch quantity (skipping
    however many the batch already has), each auto-serialized and linked
    back to this batch."""
    from ..db import generate_number as gen
    db = get_db()
    batch = db.execute("SELECT * FROM batch_runs WHERE id=?", (batch_id,)).fetchone()
    if batch is None:
        flash("Batch run not found.", "error")
        return redirect(url_for("batches.index"))
    existing = db.execute("SELECT COUNT(*) c FROM builds WHERE batch_run_id=?", (batch_id,)).fetchone()["c"]
    to_create = max(batch["quantity"] - existing, 0)
    for _ in range(to_create):
        number = gen("Build")
        serial = gen("Serial")
        db.execute(
            "INSERT INTO builds (build_number, kit_id, status, serial_number, batch_run_id) VALUES (?,?, 'Queued', ?, ?)",
            (number, batch["kit_id"], serial, batch_id),
        )
    db.execute("UPDATE batch_runs SET status='Picking' WHERE id=? AND status='Planned'", (batch_id,))
    db.commit()
    flash(f"{to_create} build(s) created for this batch." if to_create else "This batch already has all its builds.", "success")
    return redirect(url_for("batches.detail", batch_id=batch_id))
