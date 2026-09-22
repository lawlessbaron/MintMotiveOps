from flask import Blueprint, render_template, request, redirect, url_for, flash
from ..db import get_db, procurement_suggestions, generate_number

bp = Blueprint("procurement", __name__, url_prefix="/procurement")


@bp.route("/")
def index():
    db = get_db()
    suggestions = procurement_suggestions(db)
    return render_template("procurement/index.html", suggestions=suggestions)


@bp.route("/create-draft-po", methods=["POST"])
def create_draft_po():
    """Builds a Draft PO from a supplier's suggested parts (checkboxes on
    the Procurement Queue page), pre-filled with each part's suggested
    reorder quantity and current unit_cost. Still lands as a Draft, so
    nothing gets sent without a human reviewing quantities first — and if
    that supplier is in a blackout period, this still lets it be created
    (a draft costs nothing) but the page flags it clearly before the click."""
    db = get_db()
    f = request.form
    supplier_id = f.get("supplier_id")
    part_ids = request.form.getlist("part_id")
    qtys = request.form.getlist("suggested_qty")
    costs = request.form.getlist("unit_cost")
    if not supplier_id or not part_ids:
        flash("Pick a supplier and at least one part.", "error")
        return redirect(url_for("procurement.index"))
    number = generate_number("Purchase Order")
    cur = db.execute(
        "INSERT INTO purchase_orders (po_number, supplier_id, notes) VALUES (?,?,?)",
        (number, supplier_id, "Auto-generated from the Procurement Queue."),
    )
    po_id = cur.lastrowid
    for part_id, qty, cost in zip(part_ids, qtys, costs):
        db.execute(
            "INSERT INTO purchase_order_lines (purchase_order_id, part_id, quantity_ordered, unit_cost) VALUES (?,?,?,?)",
            (po_id, part_id, int(float(qty)), float(cost or 0)),
        )
    db.commit()
    flash(f"Draft PO {number} created from the procurement queue — review before sending.", "success")
    return redirect(url_for("purchase_orders.detail", po_id=po_id))
