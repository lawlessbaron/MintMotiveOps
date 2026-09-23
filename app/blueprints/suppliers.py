from flask import Blueprint, render_template, request, redirect, url_for, flash
from ..db import get_db, generate_number, default_payment_term, supplier_reliability_stats

bp = Blueprint("suppliers", __name__, url_prefix="/suppliers")


@bp.route("/")
def index():
    db = get_db()
    q = request.args.get("q", "").strip()
    sql = "SELECT * FROM suppliers WHERE 1=1"
    args = []
    if q:
        sql += " AND (supplier_name LIKE ? OR supplier_code LIKE ?)"
        args += [f"%{q}%", f"%{q}%"]
    sql += " ORDER BY supplier_name"
    suppliers = db.execute(sql, args).fetchall()
    reliability = {r["supplier_id"]: r for r in supplier_reliability_stats(db)}
    return render_template("suppliers/index.html", suppliers=suppliers, q=q, reliability=reliability)


@bp.route("/new", methods=["GET", "POST"])
def new():
    db = get_db()
    terms = db.execute("SELECT * FROM supplier_payment_terms WHERE active=1 ORDER BY name").fetchall()
    if request.method == "POST":
        f = request.form
        code = f.get("supplier_code") or generate_number("Supplier")
        pt = f.get("payment_term_id") or default_payment_term("supplier")
        cur = db.execute(
            "INSERT INTO suppliers (supplier_name, supplier_code, contact_name, email, phone, website, "
            "address, payment_term_id, tax_business_number, currency, status, notes) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
            (f["supplier_name"], code, f.get("contact_name"), f.get("email"), f.get("phone"), f.get("website"),
             f.get("address"), pt, f.get("tax_business_number"), f.get("currency", "AUD"),
             f.get("status", "Active"), f.get("notes")),
        )
        db.commit()
        flash("Supplier created.", "success")
        return redirect(url_for("suppliers.detail", supplier_id=cur.lastrowid))
    return render_template("suppliers/form.html", terms=terms)


@bp.route("/<int:supplier_id>")
def detail(supplier_id):
    db = get_db()
    supplier = db.execute("SELECT * FROM suppliers WHERE id=?", (supplier_id,)).fetchone()
    if supplier is None:
        flash("Supplier not found.", "error")
        return redirect(url_for("suppliers.index"))
    parts = db.execute(
        "SELECT p.id, p.part_name, ps.supplier_part_number, ps.supplier_cost, ps.source_url FROM part_suppliers ps "
        "JOIN parts p ON p.id=ps.part_id WHERE ps.supplier_id=?", (supplier_id,)
    ).fetchall()
    pos = db.execute("SELECT * FROM purchase_orders WHERE supplier_id=? ORDER BY order_date DESC", (supplier_id,)).fetchall()
    terms = db.execute("SELECT * FROM supplier_payment_terms WHERE active=1 ORDER BY name").fetchall()
    blackout_periods = db.execute(
        "SELECT * FROM supplier_blackout_periods WHERE supplier_id=? ORDER BY start_date DESC", (supplier_id,)
    ).fetchall()
    reliability = next((r for r in supplier_reliability_stats(db) if r["supplier_id"] == supplier_id), None)
    return render_template(
        "suppliers/detail.html", supplier=supplier, parts=parts, pos=pos, terms=terms,
        blackout_periods=blackout_periods, reliability=reliability,
    )


@bp.route("/<int:supplier_id>/edit", methods=["POST"])
def edit(supplier_id):
    db = get_db()
    f = request.form
    db.execute(
        "UPDATE suppliers SET supplier_name=?, supplier_code=?, contact_name=?, email=?, phone=?, website=?, "
        "address=?, payment_term_id=?, tax_business_number=?, currency=?, status=?, notes=? WHERE id=?",
        (f["supplier_name"], f.get("supplier_code"), f.get("contact_name"), f.get("email"), f.get("phone"),
         f.get("website"), f.get("address"), f.get("payment_term_id") or None, f.get("tax_business_number"),
         f.get("currency"), f.get("status"), f.get("notes"), supplier_id),
    )
    db.commit()
    flash("Supplier updated.", "success")
    return redirect(url_for("suppliers.detail", supplier_id=supplier_id))


@bp.route("/<int:supplier_id>/blackout/add", methods=["POST"])
def add_blackout(supplier_id):
    db = get_db()
    f = request.form
    db.execute(
        "INSERT INTO supplier_blackout_periods (supplier_id, start_date, end_date, reason) VALUES (?,?,?,?)",
        (supplier_id, f["start_date"], f["end_date"], f.get("reason")),
    )
    db.commit()
    flash("Blackout period added — the Procurement Queue will flag it while it's active.", "success")
    return redirect(url_for("suppliers.detail", supplier_id=supplier_id))


@bp.route("/<int:supplier_id>/blackout/<int:period_id>/remove", methods=["POST"])
def remove_blackout(supplier_id, period_id):
    db = get_db()
    db.execute("DELETE FROM supplier_blackout_periods WHERE id=? AND supplier_id=?", (period_id, supplier_id))
    db.commit()
    return redirect(url_for("suppliers.detail", supplier_id=supplier_id))
