from datetime import datetime, timedelta
from flask import Blueprint, render_template
from ..db import get_db

bp = Blueprint("dashboard", __name__)


def _day_bounds(d):
    """(start, end) TEXT bounds for one calendar day, for lexical range
    comparison against 'YYYY-MM-DD HH:MM:SS' columns — works identically on
    SQLite and Postgres, same convention as now_str() elsewhere in db.py."""
    start = d.strftime("%Y-%m-%d 00:00:00")
    end = d.strftime("%Y-%m-%d 23:59:59")
    return start, end


def _count_and_value_for_day(db, d):
    start, end = _day_bounds(d)
    orders = db.execute(
        "SELECT COUNT(*) c FROM sales_orders WHERE order_date >= ? AND order_date <= ?",
        (start, end),
    ).fetchone()["c"]
    revenue = db.execute(
        "SELECT COALESCE(SUM(l.quantity*l.unit_price),0) v FROM invoices i "
        "JOIN invoice_lines l ON l.invoice_id = i.id WHERE i.invoice_date >= ? AND i.invoice_date <= ?",
        (start, end),
    ).fetchone()["v"]
    return orders, revenue


def _month_start_str(d):
    return d.replace(day=1).strftime("%Y-%m-%d 00:00:00")


def _monthly_revenue(db, months=6):
    """Revenue per calendar month for the trailing N months, oldest first.
    Bucketed in Python rather than SQL date-trunc, which differs enough
    between SQLite and Postgres to not be worth hand-rolling twice."""
    today = datetime.utcnow().date()
    first_of_this_month = today.replace(day=1)
    # Walk back `months - 1` month boundaries to find the earliest bucket start.
    boundaries = [first_of_this_month]
    cursor = first_of_this_month
    for _ in range(months - 1):
        cursor = (cursor - timedelta(days=1)).replace(day=1)
        boundaries.append(cursor)
    boundaries.reverse()  # oldest first
    range_start = boundaries[0].strftime("%Y-%m-%d 00:00:00")

    rows = db.execute(
        "SELECT i.invoice_date, l.quantity, l.unit_price FROM invoices i "
        "JOIN invoice_lines l ON l.invoice_id = i.id WHERE i.invoice_date >= ?",
        (range_start,),
    ).fetchall()

    buckets = {b.strftime("%Y-%m"): 0.0 for b in boundaries}
    for r in rows:
        key = (r["invoice_date"] or "")[:7]
        if key in buckets:
            buckets[key] += (r["quantity"] or 0) * (r["unit_price"] or 0)

    return [{"label": b.strftime("%b"), "value": round(buckets[b.strftime("%Y-%m")], 2)} for b in boundaries]


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
        "pending_po_approvals": db.execute(
            "SELECT COUNT(*) c FROM purchase_orders WHERE approval_status = 'Pending'"
        ).fetchone()["c"],
        "outstanding_value": db.execute(
            "SELECT COALESCE(SUM(l.quantity*l.unit_price),0) v FROM invoices i "
            "JOIN invoice_lines l ON l.invoice_id = i.id WHERE i.status IN ('Sent','Overdue')"
        ).fetchone()["v"],
        # Inventory asset value at cost — quantity_on_hand includes reserved
        # stock (it's still owned and on the shelf, just earmarked), unlike
        # the "Available" figure used for reorder decisions elsewhere.
        "stock_value": db.execute(
            "SELECT COALESCE(SUM(quantity_on_hand * unit_cost),0) v FROM parts"
        ).fetchone()["v"],
        "expenses_this_month": db.execute(
            "SELECT COALESCE(SUM(amount_ex_gst + gst_amount),0) v FROM expenses WHERE expense_date >= ?",
            (_month_start_str(datetime.utcnow().date()),),
        ).fetchone()["v"],
    }

    today = datetime.utcnow().date()
    last_week = today - timedelta(days=7)
    orders_today, revenue_today = _count_and_value_for_day(db, today)
    orders_last_week, revenue_last_week = _count_and_value_for_day(db, last_week)
    trends = {
        "orders_today": orders_today,
        "orders_delta": orders_today - orders_last_week,
        "revenue_today": revenue_today,
        "revenue_delta": round(revenue_today - revenue_last_week, 2),
    }

    revenue_chart = _monthly_revenue(db)
    revenue_chart_max = max([b["value"] for b in revenue_chart] + [1])

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
    # What the flagged-low parts are worth on the shelf right now — makes
    # the alert banner say something concrete ("$X across N parts") instead
    # of just a bare count, same "everything to do with money" framing as
    # the rest of this pass.
    low_stock_value = db.execute(
        "SELECT COALESCE(SUM(quantity_on_hand * unit_cost),0) v FROM parts "
        "WHERE (quantity_on_hand - quantity_reserved) <= reorder_threshold"
    ).fetchone()["v"]
    return render_template(
        "dashboard/index.html", stats=stats, trends=trends, revenue_chart=revenue_chart,
        revenue_chart_max=revenue_chart_max, recent_orders=recent_orders,
        active_builds=active_builds, low_stock=low_stock, low_stock_value=low_stock_value,
    )
