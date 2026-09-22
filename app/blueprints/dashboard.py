from flask import Blueprint, render_template
from ..db import get_db

bp = Blueprint("dashboard", __name__)


@bp.route("/")
def index():
    db = get_db()
    stats = {
        "open_sales_orders": db.execute(
            "SELECT COUNT(*) c FROM sales_orders WHERE status NOT IN ('Completed','Cancelled')"
        ).fetchone()["c"],
        "active_builds": db.execute(
            "SELECT COUNT(*) c FROM builds WHERE status NOT IN ('Shipped','Complete')"
        ).fetchone()["c"],
        "unpaid_invoices": db.execute(
            "SELECT COUNT(*) c FROM invoices WHERE status IN ('Sent','Overdue')"
        ).fetchone()["c"],
        "low_stock_parts": db.execute(
            "SELECT COUNT(*) c FROM parts WHERE (quantity_on_hand - quantity_reserved) <= reorder_threshold"
        ).fetchone()["c"],
        "total_clients": db.execute("SELECT COUNT(*) c FROM clients").fetchone()["c"],
        "outstanding_value": db.execute(
            "SELECT COALESCE(SUM(l.quantity*l.unit_price),0) v FROM invoices i "
            "JOIN invoice_lines l ON l.invoice_id = i.id WHERE i.status IN ('Sent','Overdue')"
        ).fetchone()["v"],
    }
    recent_orders = db.execute(
        "SELECT so.*, c.client_name FROM sales_orders so JOIN clients c ON c.id = so.client_id "
        "ORDER BY so.created_at DESC LIMIT 8"
    ).fetchall()
    active_builds = db.execute(
        "SELECT b.*, k.kit_name, c.client_name FROM builds b JOIN kits k ON k.id=b.kit_id "
        "LEFT JOIN clients c ON c.id=b.client_id WHERE b.status NOT IN ('Shipped','Complete') "
        "ORDER BY b.created_at DESC LIMIT 8"
    ).fetchall()
    low_stock = db.execute(
        "SELECT * FROM parts WHERE (quantity_on_hand - quantity_reserved) <= reorder_threshold "
        "ORDER BY (quantity_on_hand - quantity_reserved) ASC LIMIT 8"
    ).fetchall()
    return render_template(
        "dashboard/index.html", stats=stats, recent_orders=recent_orders,
        active_builds=active_builds, low_stock=low_stock,
    )
