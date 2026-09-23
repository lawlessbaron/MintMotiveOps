from flask import Blueprint, render_template, request, redirect, url_for, flash, session, abort
from ..db import (
    get_db, generate_number, receive_po_line, apply_landed_cost, now_str,
    spending_approval_needed, purchase_order_total,
)

bp = Blueprint("purchase_orders", __name__, url_prefix="/purchase-orders")


@bp.route("/")
def index():
    db = get_db()
    pos = db.execute(
        "SELECT po.*, s.supplier_name, ru.name AS requested_by_name FROM purchase_orders po "
        "JOIN suppliers s ON s.id=po.supplier_id LEFT JOIN users ru ON ru.id=po.requested_by "
        "ORDER BY po.order_date DESC"
    ).fetchall()
    return render_template("purchase_orders/index.html", pos=pos)


@bp.route("/new", methods=["GET", "POST"])
def new():
    db = get_db()
    suppliers = db.execute("SELECT * FROM suppliers ORDER BY supplier_name").fetchall()
    if request.method == "POST":
        f = request.form
        number = generate_number("Purchase Order")
        cur = db.execute(
            "INSERT INTO purchase_orders (po_number, supplier_id, expected_delivery_date, notes, requested_by) "
            "VALUES (?,?,?,?,?)",
            (number, f["supplier_id"], f.get("expected_delivery_date") or None, f.get("notes"),
             session.get("user_id")),
        )
        db.commit()
        flash("Purchase order created — add line items below.", "success")
        return redirect(url_for("purchase_orders.detail", po_id=cur.lastrowid))
    return render_template("purchase_orders/form.html", suppliers=suppliers)


@bp.route("/<int:po_id>")
def detail(po_id):
    db = get_db()
    po = db.execute(
        "SELECT po.*, s.supplier_name, ru.name AS requested_by_name, au.name AS approved_by_name "
        "FROM purchase_orders po JOIN suppliers s ON s.id=po.supplier_id "
        "LEFT JOIN users ru ON ru.id=po.requested_by LEFT JOIN users au ON au.id=po.approved_by "
        "WHERE po.id=?",
        (po_id,),
    ).fetchone()
    if po is None:
        flash("Purchase order not found.", "error")
        return redirect(url_for("purchase_orders.index"))
    lines = db.execute(
        "SELECT l.*, p.part_name, p.part_number FROM purchase_order_lines l JOIN parts p ON p.id=l.part_id WHERE l.purchase_order_id=?",
        (po_id,),
    ).fetchall()
    parts = db.execute("SELECT * FROM parts ORDER BY part_name").fetchall()
    agents = db.execute("SELECT * FROM customs_agents ORDER BY agent_name").fetchall()
    total = sum(l["quantity_ordered"] * l["unit_cost"] for l in lines)
    return render_template("purchase_orders/detail.html", po=po, lines=lines, parts=parts, agents=agents, total=total)


@bp.route("/<int:po_id>/status", methods=["POST"])
def update_status(po_id):
    db = get_db()
    status = request.form["status"]
    po = db.execute("SELECT * FROM purchase_orders WHERE id=?", (po_id,)).fetchone()
    if po is None:
        flash("Purchase order not found.", "error")
        return redirect(url_for("purchase_orders.index"))

    # Draft -> anything else is the actual commitment to the supplier —
    # that's the point a spending limit has to gate, not creation or
    # editing lines, which don't commit the business to anything yet.
    if po["status"] == "Draft" and status != "Draft" and po["approval_status"] != "Approved":
        total = purchase_order_total(db, po_id)
        if spending_approval_needed(db, po["requested_by"], total):
            db.execute(
                "UPDATE purchase_orders SET approval_status='Pending' WHERE id=?", (po_id,)
            )
            db.commit()
            flash(
                f"This PO (${total:,.2f}) is over your spending limit — sent for Owner approval "
                f"instead of being marked {status}. It'll stay in Draft until approved.",
                "error",
            )
            return redirect(url_for("purchase_orders.detail", po_id=po_id))

    db.execute("UPDATE purchase_orders SET status=? WHERE id=?", (status, po_id))
    db.commit()
    flash("Status updated.", "success")
    return redirect(url_for("purchase_orders.detail", po_id=po_id))


@bp.route("/<int:po_id>/approval/approve", methods=["POST"])
def approve(po_id):
    if session.get("user_role") != "Owner":
        abort(403, description="Only Owners can approve a purchase order that's over the requester's spending limit.")
    db = get_db()
    db.execute(
        "UPDATE purchase_orders SET approval_status='Approved', approved_by=?, approved_at=?, approval_notes=NULL "
        "WHERE id=?",
        (session.get("user_id"), now_str(), po_id),
    )
    db.commit()
    flash("Approved — it can now be moved out of Draft.", "success")
    return redirect(url_for("purchase_orders.detail", po_id=po_id))


@bp.route("/<int:po_id>/approval/reject", methods=["POST"])
def reject(po_id):
    if session.get("user_role") != "Owner":
        abort(403, description="Only Owners can reject a purchase order that's over the requester's spending limit.")
    db = get_db()
    db.execute(
        "UPDATE purchase_orders SET approval_status='Rejected', approved_by=?, approved_at=?, approval_notes=? "
        "WHERE id=?",
        (session.get("user_id"), now_str(), request.form.get("approval_notes"), po_id),
    )
    db.commit()
    flash("Rejected — it'll stay in Draft. The requester can revise it and resubmit.", "success")
    return redirect(url_for("purchase_orders.detail", po_id=po_id))


@bp.route("/<int:po_id>/reopen", methods=["POST"])
def reopen(po_id):
    db = get_db()
    db.execute(
        "UPDATE purchase_orders SET status='Confirmed', reopened=1, reopened_notes=?, closed_date=NULL WHERE id=?",
        (request.form.get("reopened_notes", ""), po_id),
    )
    db.commit()
    flash("Purchase order reopened.", "success")
    return redirect(url_for("purchase_orders.detail", po_id=po_id))


@bp.route("/<int:po_id>/lines/add", methods=["POST"])
def add_line(po_id):
    db = get_db()
    f = request.form
    db.execute(
        "INSERT INTO purchase_order_lines (purchase_order_id, part_id, quantity_ordered, unit_cost) VALUES (?,?,?,?)",
        (po_id, f["part_id"], int(f.get("quantity_ordered", 1)), float(f.get("unit_cost", 0))),
    )
    db.commit()
    return redirect(url_for("purchase_orders.detail", po_id=po_id))


@bp.route("/<int:po_id>/lines/<int:line_id>/receive", methods=["POST"])
def receive_line(po_id, line_id):
    db = get_db()
    qty = int(request.form.get("quantity", 0))
    receive_po_line(db, line_id, qty)
    flash(f"Received {qty} units — stock updated.", "success")
    return redirect(url_for("purchase_orders.detail", po_id=po_id))


@bp.route("/<int:po_id>/landed-cost", methods=["POST"])
def set_landed_cost(po_id):
    """Records the PO's actual freight/duty paid and its real received
    date (drives Supplier Reliability), then applies it — see the Apply
    button below for the actual cost-spreading step."""
    db = get_db()
    f = request.form
    db.execute(
        "UPDATE purchase_orders SET actual_freight_paid=?, actual_duty_paid=?, received_date=? WHERE id=?",
        (float(f.get("actual_freight_paid") or 0), float(f.get("actual_duty_paid") or 0),
         f.get("received_date") or None, po_id),
    )
    db.commit()
    flash("Landed cost figures saved.", "success")
    return redirect(url_for("purchase_orders.detail", po_id=po_id))


@bp.route("/<int:po_id>/landed-cost/apply", methods=["POST"])
def apply_landed_cost_route(po_id):
    applied = apply_landed_cost(get_db(), po_id)
    if applied:
        flash("Landed cost distributed across received lines — part unit costs updated (moving average).", "success")
    else:
        flash("Nothing to apply — either it's already been applied, or there's no freight/duty/received quantity recorded yet.", "error")
    return redirect(url_for("purchase_orders.detail", po_id=po_id))
