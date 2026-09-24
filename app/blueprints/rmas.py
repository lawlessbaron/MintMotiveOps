from flask import Blueprint, render_template, request, redirect, url_for, flash
from ..db import get_db, generate_number, process_rma_teardown, now_str

bp = Blueprint("rmas", __name__, url_prefix="/rmas")


@bp.route("/")
def index():
    db = get_db()
    rmas = db.execute(
        "SELECT r.*, b.build_number, c.client_name FROM rmas r "
        "LEFT JOIN builds b ON b.id=r.build_id LEFT JOIN clients c ON c.id=r.client_id "
        "ORDER BY r.received_date DESC"
    ).fetchall()
    return render_template("rmas/index.html", rmas=rmas)


@bp.route("/new", methods=["GET", "POST"])
def new():
    db = get_db()
    builds = db.execute(
        "SELECT b.*, k.kit_name FROM builds b JOIN kits k ON k.id=b.kit_id "
        "WHERE b.status IN ('Shipped','Complete') ORDER BY b.created_at DESC"
    ).fetchall()
    clients = db.execute("SELECT * FROM clients ORDER BY client_name").fetchall()
    if request.method == "POST":
        f = request.form
        number = generate_number("RMA")
        build_id = f.get("build_id") or None
        client_id = f.get("client_id") or None
        # Default the client from the chosen build if one wasn't picked directly.
        if build_id and not client_id:
            b = db.execute("SELECT client_id FROM builds WHERE id=?", (build_id,)).fetchone()
            client_id = b["client_id"] if b else None
        cur = db.execute(
            "INSERT INTO rmas (rma_number, build_id, client_id, reason, received_date) VALUES (?,?,?,?,?)",
            (number, build_id, client_id, f.get("reason"), now_str()),
        )
        db.commit()
        flash(f"RMA {number} logged.", "success")
        return redirect(url_for("rmas.detail", rma_id=cur.lastrowid))
    preselect_build_id = request.args.get("build_id", type=int)
    return render_template("rmas/form.html", builds=builds, clients=clients, preselect_build_id=preselect_build_id)


@bp.route("/<int:rma_id>")
def detail(rma_id):
    db = get_db()
    rma = db.execute(
        "SELECT r.*, b.build_number, b.kit_id, c.client_name FROM rmas r "
        "LEFT JOIN builds b ON b.id=r.build_id LEFT JOIN clients c ON c.id=r.client_id WHERE r.id=?",
        (rma_id,),
    ).fetchone()
    if rma is None:
        flash("RMA not found.", "error")
        return redirect(url_for("rmas.index"))
    lines = db.execute(
        "SELECT tl.*, p.part_name, p.part_number, k.kit_name AS component_kit_name "
        "FROM rma_teardown_lines tl LEFT JOIN parts p ON p.id=tl.part_id "
        "LEFT JOIN kits k ON k.id=tl.component_kit_id WHERE tl.rma_id=?",
        (rma_id,),
    ).fetchall()
    # Offer this build's BOM (part lines only — sub-assemblies aren't
    # stocked individually) as quick-pick teardown candidates.
    bom_parts = []
    if rma["kit_id"]:
        bom_parts = db.execute(
            "SELECT p.id, p.part_name, p.part_number FROM kit_parts kp JOIN parts p ON p.id=kp.part_id "
            "WHERE kp.kit_id=? ORDER BY p.part_name",
            (rma["kit_id"],),
        ).fetchall()
    all_parts = db.execute("SELECT id, part_name, part_number FROM parts ORDER BY part_name").fetchall()
    return render_template("rmas/detail.html", rma=rma, lines=lines, bom_parts=bom_parts, all_parts=all_parts)


@bp.route("/<int:rma_id>/teardown/add", methods=["POST"])
def add_teardown_line(rma_id):
    db = get_db()
    f = request.form
    db.execute(
        "INSERT INTO rma_teardown_lines (rma_id, part_id, quantity, disposition, notes) VALUES (?,?,?,?,?)",
        (rma_id, f["part_id"], int(f.get("quantity", 1)), f.get("disposition", "Scrap"), f.get("notes")),
    )
    db.commit()
    return redirect(url_for("rmas.detail", rma_id=rma_id))


@bp.route("/<int:rma_id>/teardown/process", methods=["POST"])
def process_teardown(rma_id):
    db = get_db()
    process_rma_teardown(db, rma_id)
    flash("Teardown processed — Restock lines returned to inventory.", "success")
    return redirect(url_for("rmas.detail", rma_id=rma_id))


@bp.route("/<int:rma_id>/resolve", methods=["POST"])
def resolve(rma_id):
    db = get_db()
    f = request.form
    db.execute(
        "UPDATE rmas SET status='Resolved', resolution=?, resolved_date=?, notes=? WHERE id=?",
        (f.get("resolution"), now_str(), f.get("notes"), rma_id),
    )
    db.commit()
    flash("RMA marked resolved.", "success")
    return redirect(url_for("rmas.detail", rma_id=rma_id))
