from flask import Blueprint, render_template, request, redirect, url_for, flash
from ..db import get_db

bp = Blueprint("assets", __name__, url_prefix="/assets")


def _lookups(db):
    return {
        "asset_types": db.execute("SELECT * FROM asset_types WHERE active=1 ORDER BY name").fetchall(),
        "locations": db.execute("SELECT * FROM locations ORDER BY name").fetchall(),
    }


@bp.route("/")
def index():
    db = get_db()
    q = request.args.get("q", "").strip()
    status = request.args.get("status", "")
    sql = (
        "SELECT a.*, t.name AS type_name, l.name AS location_name FROM assets a "
        "LEFT JOIN asset_types t ON t.id = a.asset_type_id "
        "LEFT JOIN locations l ON l.id = a.location_id WHERE 1=1"
    )
    args = []
    if q:
        sql += " AND (a.asset_name LIKE ? OR a.serial_number LIKE ?)"
        args += [f"%{q}%", f"%{q}%"]
    if status:
        sql += " AND a.status = ?"
        args.append(status)
    sql += " ORDER BY a.asset_name"
    assets = db.execute(sql, args).fetchall()
    return render_template("assets/index.html", assets=assets, q=q, status=status)


@bp.route("/new", methods=["GET", "POST"])
def new():
    db = get_db()
    if request.method == "POST":
        f = request.form
        cur = db.execute(
            "INSERT INTO assets (asset_name, asset_type_id, serial_number, purchase_date, purchase_cost, "
            "location_id, status, maintenance_notes, power_plug_reference) VALUES (?,?,?,?,?,?,?,?,?)",
            (f["asset_name"], f.get("asset_type_id") or None, f.get("serial_number"), f.get("purchase_date") or None,
             f.get("purchase_cost") or None, f.get("location_id") or None, f.get("status", "In Service"),
             f.get("maintenance_notes"), f.get("power_plug_reference") or None),
        )
        db.commit()
        flash("Asset added.", "success")
        return redirect(url_for("assets.detail", asset_id=cur.lastrowid))
    return render_template("assets/form.html", asset=None, **_lookups(db))


@bp.route("/<int:asset_id>")
def detail(asset_id):
    db = get_db()
    asset = db.execute(
        "SELECT a.*, t.name AS type_name, l.name AS location_name FROM assets a "
        "LEFT JOIN asset_types t ON t.id = a.asset_type_id LEFT JOIN locations l ON l.id = a.location_id "
        "WHERE a.id=?", (asset_id,),
    ).fetchone()
    if asset is None:
        flash("Asset not found.", "error")
        return redirect(url_for("assets.index"))
    power_readings = db.execute(
        "SELECT * FROM power_readings WHERE asset_id=? ORDER BY recorded_at DESC LIMIT 50", (asset_id,)
    ).fetchall()
    latest_watts = power_readings[0]["watts"] if power_readings else None
    return render_template(
        "assets/detail.html", asset=asset, power_readings=power_readings, latest_watts=latest_watts,
        **_lookups(db),
    )


@bp.route("/<int:asset_id>/edit", methods=["POST"])
def edit(asset_id):
    db = get_db()
    f = request.form
    db.execute(
        "UPDATE assets SET asset_name=?, asset_type_id=?, serial_number=?, purchase_date=?, purchase_cost=?, "
        "location_id=?, status=?, maintenance_notes=?, power_plug_reference=? WHERE id=?",
        (f["asset_name"], f.get("asset_type_id") or None, f.get("serial_number"), f.get("purchase_date") or None,
         f.get("purchase_cost") or None, f.get("location_id") or None, f.get("status"),
         f.get("maintenance_notes"), f.get("power_plug_reference") or None, asset_id),
    )
    db.commit()
    flash("Asset updated.", "success")
    return redirect(url_for("assets.detail", asset_id=asset_id))
