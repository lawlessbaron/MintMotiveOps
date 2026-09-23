import csv
import io
from datetime import datetime, timedelta
from flask import Blueprint, render_template, Response, current_app, request, redirect, url_for, session, flash
from ..db import get_db
from .. import currency

bp = Blueprint("analytics", __name__, url_prefix="/analytics")

# The "Manage Widgets" toggle list — order here is display order. A widget
# id must match one of these to mean anything; unrecognized ids stored in
# a stale hidden_analytics_widgets (e.g. from a widget since renamed) are
# just ignored rather than erroring.
ANALYTICS_WIDGETS = [
    ("inventory_value", "Inventory Value"),
    ("avg_cycle", "Avg Build Cycle Time"),
    ("outstanding_invoices", "Outstanding Invoices"),
    ("revenue_chart", "Revenue by Month"),
    ("top_kits", "Top Kits by Revenue"),
    ("build_stats", "Builds by Status"),
    ("currency_converter", "Currency Converter"),
    ("fx_chart", "Exchange Rate Chart"),
]


def _hidden_widgets(db):
    row = db.execute(
        "SELECT hidden_analytics_widgets FROM users WHERE id = ?", (session.get("user_id"),)
    ).fetchone()
    raw = row["hidden_analytics_widgets"] if row else None
    return set(raw.split(",")) if raw else set()


@bp.route("/widgets", methods=["POST"])
def save_widgets():
    """Manage Widgets panel submits the *visible* ids it's showing
    checkboxes for; stored as the inverse (hidden) so a widget added to
    ANALYTICS_WIDGETS later defaults to visible for everyone already using
    the app, rather than needing an opt-in."""
    visible = set(request.form.getlist("visible"))
    all_ids = {w[0] for w in ANALYTICS_WIDGETS}
    hidden = all_ids - visible
    db = get_db()
    db.execute(
        "UPDATE users SET hidden_analytics_widgets = ? WHERE id = ?",
        (",".join(sorted(hidden)) if hidden else None, session.get("user_id")),
    )
    db.commit()
    flash("Widget layout saved.", "success")
    return redirect(url_for("analytics.index"))


def _fx_chart_geometry(series, dates):
    """Turns {currency, color, points:[{date,rate,indexed}]} series into
    ready-to-render SVG pixel geometry — an explicit points-in/points-out
    computation here beats doing this arithmetic inside the template.
    Indexed to day 1 = 100 rather than raw rates: AUD/JPY (~114) and
    AUD/GBP (~0.53) differ by ~200x, unreadable on one axis together: see
    the dataviz skill's "two measures of different scale -> index to a
    common base" rule. Returns None if there's no data (a broken/empty
    live lookup) — a chart with no real data shouldn't pretend to be one."""
    if not dates:
        return None
    w, h = 780, 230
    margin = {"left": 40, "right": 12, "top": 12, "bottom": 26}
    plot_w = w - margin["left"] - margin["right"]
    plot_h = h - margin["top"] - margin["bottom"]

    all_indexed = [pt["indexed"] for s in series for pt in s["points"] if pt["indexed"] is not None]
    if not all_indexed:
        return None
    y_min, y_max = min(all_indexed), max(all_indexed)
    if y_min == y_max:
        y_min, y_max = y_min - 1, y_max + 1
    pad = (y_max - y_min) * 0.1
    y_min, y_max = y_min - pad, y_max + pad

    n = len(dates)

    def x_for(i):
        return margin["left"] + (i / (n - 1) if n > 1 else 0) * plot_w

    def y_for(v):
        return margin["top"] + (1 - (v - y_min) / (y_max - y_min)) * plot_h

    out_series = []
    for s in series:
        pts = []
        path_parts = []
        for i, pt in enumerate(s["points"]):
            if pt["indexed"] is None:
                continue
            x, y = x_for(i), y_for(pt["indexed"])
            pts.append({**pt, "x": round(x, 1), "y": round(y, 1)})
            path_parts.append(f"{'M' if not path_parts else 'L'}{x:.1f},{y:.1f}")
        out_series.append({**s, "points": pts, "path": " ".join(path_parts)})

    # A handful of evenly-spaced x-axis date labels — one per day for 30
    # days would collide into an unreadable smear of text.
    label_count = min(6, n)
    label_idxs = sorted(set(round(i * (n - 1) / (label_count - 1)) for i in range(label_count))) if n > 1 else [0]
    x_labels = [{"x": round(x_for(i), 1), "label": dates[i][5:]} for i in label_idxs]

    y_ticks = []
    for frac in (0, 0.5, 1):
        v = y_min + frac * (y_max - y_min)
        y_ticks.append({"y": round(y_for(v), 1), "label": f"{v:.1f}"})

    return {
        "w": w, "h": h, "plot_top": margin["top"], "plot_bottom": h - margin["bottom"],
        "plot_left": margin["left"], "plot_right": w - margin["right"],
        "series": out_series, "x_labels": x_labels, "y_ticks": y_ticks,
    }


@bp.route("/")
def index():
    db = get_db()
    is_pg = current_app.config.get("DB_BACKEND") == "postgres"
    hidden = _hidden_widgets(db)

    # Each block below only runs its query (or, for the two currency
    # widgets, its live network call) when that widget is actually visible
    # — the whole point of a per-user hide list is that a hidden widget
    # costs nothing, not just that it isn't rendered.
    revenue_by_month, max_revenue = [], 1
    if "revenue_chart" not in hidden:
        # Date-grouping functions aren't portable between SQLite and
        # Postgres, so this picks the right expression for whichever
        # backend is active — everything else here is plain SQL both
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

    top_kits, max_kit_revenue = [], 1
    if "top_kits" not in hidden:
        top_kits = db.execute(
            """SELECT k.kit_name, SUM(sol.quantity) AS units, SUM(sol.quantity * sol.unit_price) AS revenue
               FROM sales_order_lines sol JOIN kits k ON k.id = sol.kit_id
               WHERE sol.item_type = 'Kit'
               GROUP BY k.id ORDER BY revenue DESC LIMIT 5"""
        ).fetchall()
        max_kit_revenue = max([k["revenue"] for k in top_kits], default=0) or 1

    inventory_value = None
    if "inventory_value" not in hidden:
        inventory_value = db.execute(
            "SELECT COALESCE(SUM(quantity_on_hand * unit_cost), 0) AS v FROM parts"
        ).fetchone()["v"]

    build_stats = []
    if "build_stats" not in hidden:
        build_stats = db.execute(
            """SELECT status, COUNT(*) c FROM builds GROUP BY status"""
        ).fetchall()

    avg_cycle_days = None
    if "avg_cycle" not in hidden:
        cycle_expr = (
            "AVG(EXTRACT(EPOCH FROM (completed_date::timestamp - start_date::timestamp)) / 86400.0)" if is_pg
            else "AVG(julianday(completed_date) - julianday(start_date))"
        )
        avg_cycle_days = db.execute(
            f"""SELECT {cycle_expr} AS d
               FROM builds WHERE start_date IS NOT NULL AND completed_date IS NOT NULL"""
        ).fetchone()["d"]

    outstanding_by_status = []
    if "outstanding_invoices" not in hidden:
        outstanding_by_status = db.execute(
            """SELECT i.status, COUNT(*) c, COALESCE(SUM(l.quantity*l.unit_price),0) v
               FROM invoices i JOIN invoice_lines l ON l.invoice_id = i.id
               WHERE i.status IN ('Sent','Overdue') GROUP BY i.status"""
        ).fetchall()

    converter = None
    if "currency_converter" not in hidden:
        base = request.args.get("base", "AUD").upper()
        if base not in ([*currency.COMMON_CURRENCIES, "AUD"]):
            base = "AUD"
        try:
            amount = float(request.args.get("amount", "100"))
        except ValueError:
            amount = 100.0
        targets = [c for c in ["AUD", *currency.COMMON_CURRENCIES] if c != base]
        rates, rates_is_live = currency.get_rates(base, targets)
        converter = {
            "base": base, "amount": amount, "is_live": rates_is_live,
            "results": [{"currency": c, "value": round(amount * rates.get(c, 1.0), 2)} for c in targets],
            "all_currencies": ["AUD", *currency.COMMON_CURRENCIES],
        }

    fx_chart = None
    if "fx_chart" not in hidden:
        end = datetime.utcnow().date()
        start = end - timedelta(days=30)
        rows, fx_is_live = currency.get_historical_rates(
            "AUD", currency.COMMON_CURRENCIES, start.isoformat(), end.isoformat()
        )
        series = {c: [] for c in currency.COMMON_CURRENCIES}
        dates = []
        first_rates = rows[0]["rates"] if rows else {}
        for row in rows:
            dates.append(row["date"])
            for c in currency.COMMON_CURRENCIES:
                base_rate = first_rates.get(c)
                rate = row["rates"].get(c)
                indexed = round((rate / base_rate) * 100, 3) if base_rate and rate else None
                series[c].append({"date": row["date"], "rate": rate, "indexed": indexed})
        raw_series = [
            {"currency": c, "color": currency.CHART_COLORS[c], "points": series[c]}
            for c in currency.COMMON_CURRENCIES
        ]
        fx_chart = {"is_live": fx_is_live, "geometry": _fx_chart_geometry(raw_series, dates)}

    return render_template(
        "analytics/index.html",
        revenue_by_month=revenue_by_month, max_revenue=max_revenue,
        top_kits=top_kits, max_kit_revenue=max_kit_revenue,
        inventory_value=inventory_value, build_stats=build_stats,
        avg_cycle_days=round(avg_cycle_days, 1) if avg_cycle_days else None,
        outstanding_by_status=outstanding_by_status,
        converter=converter, fx_chart=fx_chart,
        all_widgets=ANALYTICS_WIDGETS, hidden_widgets=hidden,
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
