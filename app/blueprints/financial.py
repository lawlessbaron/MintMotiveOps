from flask import Blueprint, render_template, request, redirect, url_for, flash
from ..db import get_db, generate_bas_report, capex_breakeven_months, now_str

bp = Blueprint("financial", __name__, url_prefix="/financial")


@bp.route("/bas", methods=["GET", "POST"])
def bas():
    db = get_db()
    report = None
    if request.method == "POST":
        f = request.form
        period_start = f.get("period_start")
        period_end = f.get("period_end")
        if period_start and period_end:
            report = generate_bas_report(db, period_start, period_end)
            flash("BAS estimate generated — see disclaimer on GST paid below.", "success")
        else:
            flash("Pick a period start and end date.", "error")
    history = db.execute("SELECT * FROM bas_reports ORDER BY generated_at DESC LIMIT 12").fetchall()
    return render_template("financial/bas.html", report=report, history=history)


@bp.route("/capex", methods=["GET", "POST"])
def capex():
    db = get_db()
    if request.method == "POST":
        f = request.form
        equipment_cost = float(f.get("equipment_cost") or 0)
        monthly_revenue_increase = float(f.get("monthly_revenue_increase") or 0)
        monthly_cost_increase = float(f.get("monthly_cost_increase") or 0)
        db.execute(
            "INSERT INTO capex_scenarios (scenario_name, equipment_cost, monthly_revenue_increase, "
            "monthly_cost_increase, notes) VALUES (?,?,?,?,?)",
            (f.get("scenario_name") or "Untitled Scenario", equipment_cost, monthly_revenue_increase,
             monthly_cost_increase, f.get("notes")),
        )
        db.commit()
        flash("Scenario saved.", "success")
        return redirect(url_for("financial.capex"))
    scenarios = db.execute("SELECT * FROM capex_scenarios ORDER BY created_at DESC").fetchall()
    enriched = [
        {**dict(s), "breakeven_months": capex_breakeven_months(
            s["equipment_cost"], s["monthly_revenue_increase"], s["monthly_cost_increase"]
        )}
        for s in scenarios
    ]
    return render_template("financial/capex.html", scenarios=enriched)


@bp.route("/capex/<int:scenario_id>/delete", methods=["POST"])
def delete_capex(scenario_id):
    db = get_db()
    db.execute("DELETE FROM capex_scenarios WHERE id=?", (scenario_id,))
    db.commit()
    return redirect(url_for("financial.capex"))


@bp.route("/expenses", methods=["GET", "POST"])
def expenses():
    db = get_db()
    if request.method == "POST":
        f = request.form
        amount_ex_gst = float(f.get("amount_ex_gst") or 0)
        gst_amount = f.get("gst_amount")
        gst_amount = float(gst_amount) if gst_amount not in (None, "") else round(amount_ex_gst * 0.1, 2)
        db.execute(
            "INSERT INTO expenses (expense_date, category, description, supplier_id, amount_ex_gst, "
            "gst_amount, source, notes) VALUES (?,?,?,?,?,?,?,?)",
            (f.get("expense_date") or now_str(), f.get("category") or "Other", f.get("description"),
             f.get("supplier_id") or None, amount_ex_gst, gst_amount, "Manual", f.get("notes")),
        )
        db.commit()
        flash("Expense recorded.", "success")
        return redirect(url_for("financial.expenses"))
    category = request.args.get("category", "")
    sql = (
        "SELECT e.*, s.supplier_name FROM expenses e LEFT JOIN suppliers s ON s.id = e.supplier_id WHERE 1=1"
    )
    args = []
    if category:
        sql += " AND e.category = ?"
        args.append(category)
    sql += " ORDER BY e.expense_date DESC, e.id DESC"
    rows = db.execute(sql, args).fetchall()
    totals = db.execute(
        "SELECT COALESCE(SUM(amount_ex_gst),0) AS ex_gst, COALESCE(SUM(gst_amount),0) AS gst "
        "FROM expenses" + (" WHERE category = ?" if category else ""),
        args,
    ).fetchone()
    suppliers = db.execute("SELECT id, supplier_name FROM suppliers ORDER BY supplier_name").fetchall()
    categories = ["Stock Purchases", "Rent", "Software & Subscriptions", "Shipping & Freight",
                  "Tools & Equipment", "Utilities", "Professional Services", "Other"]
    return render_template(
        "financial/expenses.html", rows=rows, totals=totals, suppliers=suppliers,
        categories=categories, category_filter=category,
    )


@bp.route("/expenses/<int:expense_id>/delete", methods=["POST"])
def delete_expense(expense_id):
    db = get_db()
    db.execute("DELETE FROM expenses WHERE id=?", (expense_id,))
    db.commit()
    flash("Expense removed.", "success")
    return redirect(url_for("financial.expenses"))
