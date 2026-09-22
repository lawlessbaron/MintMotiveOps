from flask import Blueprint, render_template, request, redirect, url_for, flash
from ..db import get_db, generate_number, line_total

bp = Blueprint("sales_orders", __name__, url_prefix="/sales-orders")


@bp.route("/")
def index():
    db = get_db()
    orders = db.execute(
        "SELECT so.*, c.client_name FROM sales_orders so JOIN clients c ON c.id=so.client_id ORDER BY so.order_date DESC"
    ).fetchall()
    totals = {o["id"]: _order_total(db, o["id"]) for o in orders}
    return render_template("sales_orders/index.html", orders=orders, totals=totals)


def _order_total(db, order_id):
    row = db.execute(
        "SELECT COALESCE(SUM(quantity*unit_price),0) t FROM sales_order_lines WHERE sales_order_id=?", (order_id,)
    ).fetchone()
    return row["t"]


@bp.route("/new", methods=["GET", "POST"])
def new():
    db = get_db()
    clients = db.execute("SELECT * FROM clients ORDER BY client_name").fetchall()
    sources = db.execute("SELECT * FROM order_sources WHERE active=1 ORDER BY name").fetchall()
    if request.method == "POST":
        f = request.form
        number = generate_number("Sales Order")
        cur = db.execute(
            "INSERT INTO sales_orders (order_number, client_id, source_id, notes) VALUES (?,?,?,?)",
            (number, f["client_id"], f.get("source_id") or None, f.get("notes")),
        )
        db.commit()
        flash("Sales order created — add line items below.", "success")
        return redirect(url_for("sales_orders.detail", order_id=cur.lastrowid))
    return render_template("sales_orders/form.html", clients=clients, sources=sources)


@bp.route("/<int:order_id>")
def detail(order_id):
    db = get_db()
    order = db.execute(
        "SELECT so.*, c.client_name FROM sales_orders so JOIN clients c ON c.id=so.client_id WHERE so.id=?", (order_id,)
    ).fetchone()
    if order is None:
        flash("Sales order not found.", "error")
        return redirect(url_for("sales_orders.index"))
    lines = db.execute(
        "SELECT l.*, k.kit_name, p.part_name FROM sales_order_lines l "
        "LEFT JOIN kits k ON k.id=l.kit_id LEFT JOIN parts p ON p.id=l.part_id WHERE l.sales_order_id=?", (order_id,)
    ).fetchall()
    kits = db.execute("SELECT * FROM kits ORDER BY kit_name").fetchall()
    parts = db.execute("SELECT * FROM parts ORDER BY part_name").fetchall()
    addresses = db.execute("SELECT * FROM client_addresses WHERE client_id=?", (order["client_id"],)).fetchall()
    total = sum(line_total(l["quantity"], l["unit_price"]) for l in lines)
    return render_template("sales_orders/detail.html", order=order, lines=lines, kits=kits, parts=parts,
                            addresses=addresses, total=total, line_total=line_total)


@bp.route("/<int:order_id>/status", methods=["POST"])
def update_status(order_id):
    db = get_db()
    db.execute("UPDATE sales_orders SET status=? WHERE id=?", (request.form["status"], order_id))
    db.commit()
    return redirect(url_for("sales_orders.detail", order_id=order_id))


@bp.route("/<int:order_id>/lines/add", methods=["POST"])
def add_line(order_id):
    db = get_db()
    f = request.form
    item_type = f.get("item_type", "Kit")
    kit_id = part_id = None
    description = f.get("description", "")
    unit_price = float(f.get("unit_price") or 0)
    if item_type == "Kit" and f.get("kit_id"):
        kit = db.execute("SELECT * FROM kits WHERE id=?", (f["kit_id"],)).fetchone()
        kit_id = kit["id"]
        description = kit["kit_name"]
        from ..db import kit_total_part_cost, kit_sell_price
        unit_price = kit_sell_price(db, kit_id, kit["margin_pct"], kit["freight_included_in_price"], kit["estimated_freight_allowance"])
    elif item_type == "Part" and f.get("part_id"):
        part = db.execute("SELECT * FROM parts WHERE id=?", (f["part_id"],)).fetchone()
        part_id = part["id"]
        description = part["part_name"]
        from ..db import part_sell_price
        unit_price = part_sell_price(part["unit_cost"], part["margin_pct"])
    db.execute(
        "INSERT INTO sales_order_lines (sales_order_id, item_type, kit_id, part_id, description, quantity, unit_price) "
        "VALUES (?,?,?,?,?,?,?)",
        (order_id, item_type, kit_id, part_id, description, int(f.get("quantity", 1)), unit_price),
    )
    db.commit()
    return redirect(url_for("sales_orders.detail", order_id=order_id))


@bp.route("/<int:order_id>/lines/<int:line_id>/remove", methods=["POST"])
def remove_line(order_id, line_id):
    db = get_db()
    db.execute("DELETE FROM sales_order_lines WHERE id=? AND sales_order_id=?", (line_id, order_id))
    db.commit()
    return redirect(url_for("sales_orders.detail", order_id=order_id))
