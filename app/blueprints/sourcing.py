from flask import Blueprint, render_template, request, redirect, url_for, flash
from ..db import get_db, now_str
from ..utils import save_upload

bp = Blueprint("sourcing", __name__, url_prefix="/sourcing")


@bp.route("/")
def index():
    db = get_db()
    status = request.args.get("status", "")
    sql = "SELECT * FROM sourcing_prospects WHERE 1=1"
    args = []
    if status:
        sql += " AND status=?"
        args.append(status)
    sql += " ORDER BY date_added DESC"
    prospects = db.execute(sql, args).fetchall()
    return render_template("sourcing/index.html", prospects=prospects, status=status)


@bp.route("/new", methods=["GET", "POST"])
def new():
    db = get_db()
    categories = db.execute("SELECT * FROM part_categories WHERE active=1 ORDER BY name").fetchall()
    suppliers = db.execute("SELECT * FROM suppliers ORDER BY supplier_name").fetchall()
    if request.method == "POST":
        f = request.form
        image_path = save_upload(request.files.get("product_image"), "sourcing")
        db.execute(
            "INSERT INTO sourcing_prospects (prospect_name, product_image_path, source_link, source_platform, "
            "supplier_name_listed, linked_supplier_id, quoted_unit_price, currency, minimum_order_quantity, "
            "lead_time_days, potential_category_id, status, notes) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (f["prospect_name"], image_path, f.get("source_link"), f.get("source_platform"),
             f.get("supplier_name_listed"), f.get("linked_supplier_id") or None,
             f.get("quoted_unit_price") or None, f.get("currency", "USD"), f.get("minimum_order_quantity") or None,
             f.get("lead_time_days") or None, f.get("potential_category_id") or None,
             f.get("status", "Researching"), f.get("notes")),
        )
        db.commit()
        flash("Prospect added.", "success")
        return redirect(url_for("sourcing.index"))
    return render_template("sourcing/form.html", categories=categories, suppliers=suppliers)


@bp.route("/<int:prospect_id>/status", methods=["POST"])
def update_status(prospect_id):
    db = get_db()
    db.execute("UPDATE sourcing_prospects SET status=?, last_reviewed_date=? WHERE id=?",
               (request.form["status"], now_str(), prospect_id))
    db.commit()
    return redirect(url_for("sourcing.index"))


@bp.route("/<int:prospect_id>/convert", methods=["POST"])
def convert(prospect_id):
    db = get_db()
    p = db.execute("SELECT * FROM sourcing_prospects WHERE id=?", (prospect_id,)).fetchone()
    from ..db import generate_number, default_margin_for_part
    number = generate_number("Part")
    margin = default_margin_for_part(p["potential_category_id"])
    cur = db.execute(
        "INSERT INTO parts (part_name, part_number, product_image_path, category_id, unit_cost, margin_pct, "
        "preferred_supplier_id, notes) VALUES (?,?,?,?,?,?,?,?)",
        (p["prospect_name"], number, p["product_image_path"], p["potential_category_id"],
         p["quoted_unit_price"] or 0, margin, p["linked_supplier_id"], f"Converted from Sourcing Prospect #{p['id']}"),
    )
    db.execute("UPDATE sourcing_prospects SET status='Approved', converted_to_part_id=? WHERE id=?",
               (cur.lastrowid, prospect_id))
    db.commit()
    flash("Converted to a real Part.", "success")
    return redirect(url_for("parts.detail", part_id=cur.lastrowid))
