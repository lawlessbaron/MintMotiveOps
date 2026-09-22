import csv
import io
from flask import Blueprint, render_template, Response, current_app
from ..db import get_db

bp = Blueprint("analytics", __name__, url_prefix="/analytics")


@bp.route("/")
def index():
    db = get_db()
    is_pg = current_app.config.get("DB_BACKEND") == "postgres"

    # Date-grouping functions aren't portable between SQLite and Postgres,
    # so these two picks the right expression for whichever backend is
    # active — everything else in this module is plain SQL that both
    # understand identically.
    month_expr = (
        "to_char(i.paid_at::timestamp, 'YYYY-MM')" if is_pg
        else "strftime('%Y-%m', i.paid_at)"
    )
    revenue_by_month = db.execute(
        f"""SELECT {month_expr} AS month, COALESCE(SUM(l.quantity * l.unit_price), 0) AS total
           FROM invoices i JOIN invoice_lines l ON l.invoice_id = i.id
           WHERE i.status = 'Paid' AND i.paid_at IS NOT NULL
           GROUP BY month ORDER BY month DESC LIMIT 6"""
    ).fetchall()
    revenue_by_month = list(reversed(revenue_by_month))
    max_revenue = max([r["total"] for r in revenue_by_month], default=0) or 1

    top_kits = db.execute(
        """SELECT k.kit_name, SUM(sol.quantity) AS units, SUM(sol.quantity * sol.unit_price) AS revenue
           FROM sales_order_lines sol JOIN kits k ON k.id = sol.kit_id
           WHERE sol.item_type = 'Kit'
           GROUP BY k.id ORDER BY revenue DESC LIMIT 5"""
    ).fetchall()
    max_kit_revenue = max([k["revenue"] for k in top_kits], default=0) or 1

    inventory_value = db.execute(
        "SELECT COALESCE(SUM(quantity_on_hand * unit_cost), 0) AS v FROM parts"
    ).fetchone()["v"]

    build_stats = db.execute(
        """SELECT status, COUNT(*) c FROM builds GROUP BY status"""
    ).fetchall()

    cycle_expr = (
        "AVG(EXTRACT(EPOCH FROM (completed_date::timestamp - start_date::timestamp)) / 86400.0)" if is_pg
        else "AVG(julianday(completed_date) - julianday(start_date))"
    )
    avg_cycle_days = db.execute(
        f"""SELECT {cycle_expr} AS d
           FROM builds WHERE start_date IS NOT NULL AND completed_date IS NOT NULL"""
    ).fetchone()["d"]

    outstanding_by_status = db.execute(
        """SELECT i.status, COUNT(*) c, COALESCE(SUM(l.quantity*l.unit_price),0) v
           FROM invoices i JOIN invoice_lines l ON l.invoice_id = i.id
           WHERE i.status IN ('Sent','Overdue') GROUP BY i.status"""
    ).fetchall()

    return render_template(
        "analytics/index.html",
        revenue_by_month=revenue_by_month, max_revenue=max_revenue,
        top_kits=top_kits, max_kit_revenue=max_kit_revenue,
        inventory_value=inventory_value, build_stats=build_stats,
        avg_cycle_days=round(avg_cycle_days, 1) if avg_cycle_days else None,
        outstanding_by_status=outstanding_by_status,
    )


@bp.route("/reports")
def reports():
    return render_template("analytics/reports.html")


def _csv_response(headers, rows, filename):
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(headers)
    writer.writerows(rows)
    return Response(
        buf.getvalue(), mimetype="text/csv",
        headers={"Content-Disposition": f"attachment; filename={filename}"},
    )


@bp.route("/reports/inventory-valuation.csv")
def export_inventory_valuation():
    db = get_db()
    rows = db.execute(
        """SELECT p.part_name, p.part_number, p.quantity_on_hand, p.unit_cost,
                  (p.quantity_on_hand * p.unit_cost) AS total_value
           FROM parts p ORDER BY total_value DESC"""
    ).fetchall()
    return _csv_response(
        ["Part Name", "Part Number", "Quantity On Hand", "Unit Cost", "Total Value"],
        [[r["part_name"], r["part_number"], r["quantity_on_hand"], r["unit_cost"], r["total_value"]] for r in rows],
        "inventory_valuation.csv",
    )


@bp.route("/reports/sales-orders.csv")
def export_sales_orders():
    db = get_db()
    rows = db.execute(
        """SELECT so.order_number, c.client_name, so.status, so.order_date,
                  COALESCE(SUM(sol.quantity * sol.unit_price), 0) AS total
           FROM sales_orders so JOIN clients c ON c.id = so.client_id
           LEFT JOIN sales_order_lines sol ON sol.sales_order_id = so.id
           GROUP BY so.id ORDER BY so.order_date DESC"""
    ).fetchall()
    return _csv_response(
        ["Order Number", "Client", "Status", "Order Date", "Total"],
        [[r["order_number"], r["client_name"], r["status"], r["order_date"], r["total"]] for r in rows],
        "sales_orders.csv",
    )


@bp.route("/reports/outstanding-invoices.csv")
def export_outstanding_invoices():
    db = get_db()
    rows = db.execute(
        """SELECT i.invoice_number, c.client_name, i.status, i.due_date,
                  COALESCE(SUM(l.quantity * l.unit_price), 0) AS total
           FROM invoices i JOIN clients c ON c.id = i.client_id
           JOIN invoice_lines l ON l.invoice_id = i.id
           WHERE i.status IN ('Sent', 'Overdue')
           GROUP BY i.id ORDER BY i.due_date"""
    ).fetchall()
    return _csv_response(
        ["Invoice Number", "Client", "Status", "Due Date", "Total"],
        [[r["invoice_number"], r["client_name"], r["status"], r["due_date"], r["total"]] for r in rows],
        "outstanding_invoices.csv",
    )
