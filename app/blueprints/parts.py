from flask import Blueprint, render_template, request, redirect, url_for, flash
from ..db import get_db, generate_number, default_margin_for_part, part_sell_price, part_available_qty
from ..utils import save_upload

bp = Blueprint("parts", __name__, url_prefix="/inventory")


@bp.route("/")
def index():
    db = get_db()
    q = request.args.get("q", "").strip()
    category_id = request.args.get("category_id", "")
    sql = ("SELECT p.*, pc.name AS category_name FROM parts p "
           "LEFT JOIN part_categories pc ON pc.id = p.category_id WHERE 1=1")
    args = []
    if q:
        sql += " AND (p.part_name LIKE ? OR p.part_number LIKE ?)"
        args += [f"%{q}%", f"%{q}%"]
    if category_id:
        sql += " AND p.category_id = ?"
        args.append(category_id)
    sql += " ORDER BY p.part_name"
    parts = db.execute(sql, args).fetchall()
    categories = db.execute("SELECT * FROM part_categories WHERE active=1 ORDER BY name").fetchall()
    return render_template("parts/index.html", parts=parts, categories=categories, q=q, category_id=category_id,
                            sell_price=part_sell_price, available_qty=part_available_qty)


def _lookups(db):
    return dict(
        categories=db.execute("SELECT * FROM part_categories WHERE active=1 ORDER BY name").fetchall(),
        suppliers=db.execute("SELECT * FROM suppliers ORDER BY supplier_name").fetchall(),
        harmonised_codes=db.execute("SELECT * FROM harmonised_codes ORDER BY code").fetchall(),
        countries=db.execute("SELECT * FROM countries WHERE active=1 ORDER BY country_name").fetchall(),
        locations=db.execute("SELECT * FROM locations ORDER BY name").fetchall(),
    )


@bp.route("/new", methods=["GET", "POST"])
def new():
    db = get_db()
    if request.method == "POST":
        f = request.form
        margin = f.get("margin_pct")
        margin = float(margin) if margin else default_margin_for_part(f.get("category_id") or None)
        number = f.get("part_number") or generate_number("Part")
        image_path = save_upload(request.files.get("product_image"), "parts")
        cur = db.execute(
            "INSERT INTO parts (part_name, part_number, product_image_path, category_id, quantity_on_hand, reorder_threshold, "
            "unit_cost, margin_pct, preferred_supplier_id, harmonised_code_id, country_of_origin_id, "
            "weight_kg, length_cm, width_cm, height_cm, bin_location_id, notes) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (f["part_name"], number, image_path, f.get("category_id") or None, int(f.get("quantity_on_hand") or 0),
             int(f.get("reorder_threshold") or 0), float(f.get("unit_cost") or 0), margin,
             f.get("preferred_supplier_id") or None, f.get("harmonised_code_id") or None,
             f.get("country_of_origin_id") or None, f.get("weight_kg") or None, f.get("length_cm") or None,
             f.get("width_cm") or None, f.get("height_cm") or None, f.get("bin_location_id") or None,
             f.get("notes")),
        )
        db.commit()
        flash("Part created.", "success")
        return redirect(url_for("parts.detail", part_id=cur.lastrowid))
    return render_template("parts/form.html", part=None, **_lookups(db))


@bp.route("/<int:part_id>")
def detail(part_id):
    db = get_db()
    part = db.execute("SELECT * FROM parts WHERE id=?", (part_id,)).fetchone()
    if part is None:
        flash("Part not found.", "error")
        return redirect(url_for("parts.index"))
    part_suppliers = db.execute(
        "SELECT ps.*, s.supplier_name FROM part_suppliers ps JOIN suppliers s ON s.id=ps.supplier_id WHERE part_id=?",
        (part_id,),
    ).fetchall()
    used_in_kits = db.execute(
        "SELECT k.id, k.kit_name, kp.quantity_required FROM kit_parts kp JOIN kits k ON k.id=kp.kit_id WHERE kp.part_id=?",
        (part_id,),
    ).fetchall()
    return render_template(
        "parts/detail.html", part=part, part_suppliers=part_suppliers, used_in_kits=used_in_kits,
        sell_price=part_sell_price(part["unit_cost"], part["margin_pct"]),
        available_qty=part_available_qty(part["quantity_on_hand"], part["quantity_reserved"]),
        **_lookups(db),
    )


@bp.route("/<int:part_id>/edit", methods=["POST"])
def edit(part_id):
    db = get_db()
    f = request.form
    image_path = save_upload(request.files.get("product_image"), "parts")
    extra_sql = ", product_image_path=?" if image_path else ""
    args = [f["part_name"], f.get("part_number"), f.get("category_id") or None, int(f.get("quantity_on_hand") or 0),
            int(f.get("reorder_threshold") or 0), float(f.get("unit_cost") or 0), float(f.get("margin_pct") or 0),
            f.get("preferred_supplier_id") or None, f.get("harmonised_code_id") or None,
            f.get("country_of_origin_id") or None, f.get("weight_kg") or None, f.get("length_cm") or None,
            f.get("width_cm") or None, f.get("height_cm") or None, f.get("bin_location_id") or None,
            f.get("notes")]
    if image_path:
        args.append(image_path)
    args.append(part_id)
    db.execute(
        "UPDATE parts SET part_name=?, part_number=?, category_id=?, quantity_on_hand=?, reorder_threshold=?, "
        "unit_cost=?, margin_pct=?, preferred_supplier_id=?, harmonised_code_id=?, country_of_origin_id=?, "
        "weight_kg=?, length_cm=?, width_cm=?, height_cm=?, bin_location_id=?, notes=?" + extra_sql + " WHERE id=?",
        args,
    )
    db.commit()
    flash("Part updated.", "success")
    return redirect(url_for("parts.detail", part_id=part_id))


@bp.route("/<int:part_id>/suppliers/new", methods=["POST"])
def add_supplier_link(part_id):
    db = get_db()
    f = request.form
    db.execute(
        "INSERT INTO part_suppliers (part_id, supplier_id, supplier_part_number, supplier_cost, lead_time_days, "
        "source_url, preferred) VALUES (?,?,?,?,?,?,?)",
        (part_id, f["supplier_id"], f.get("supplier_part_number"), f.get("supplier_cost") or None,
         f.get("lead_time_days") or None, f.get("source_url"), 1 if f.get("preferred") else 0),
    )
    db.commit()
    return redirect(url_for("parts.detail", part_id=part_id))
