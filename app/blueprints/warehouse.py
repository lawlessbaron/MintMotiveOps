from flask import Blueprint, render_template, request, redirect, url_for, flash
from ..db import get_db

bp = Blueprint("warehouse", __name__, url_prefix="/warehouse")


@bp.route("/")
def index():
    db = get_db()
    locations = db.execute(
        """SELECT l.*,
                  (SELECT COUNT(*) FROM parts p WHERE p.bin_location_id = l.id) AS part_count,
                  (SELECT COALESCE(SUM(p.quantity_on_hand), 0) FROM parts p WHERE p.bin_location_id = l.id) AS total_qty
           FROM locations l ORDER BY l.type, l.name"""
    ).fetchall()
    unassigned = db.execute(
        "SELECT COUNT(*) c FROM parts WHERE bin_location_id IS NULL"
    ).fetchone()["c"]
    return render_template("warehouse/index.html", locations=locations, unassigned=unassigned)


@bp.route("/locations/add", methods=["POST"])
def add_location():
    db = get_db()
    f = request.form
    db.execute(
        "INSERT INTO locations (name, type, baseplate_name, grid_x, grid_y) VALUES (?,?,?,?,?)",
        (f["name"], f.get("type") or None, f.get("baseplate_name") or None,
         f.get("grid_x") or None, f.get("grid_y") or None),
    )
    db.commit()
    flash("Location added.", "success")
    return redirect(url_for("warehouse.index"))


@bp.route("/locations/<int:location_id>/edit", methods=["POST"])
def edit_location(location_id):
    db = get_db()
    f = request.form
    db.execute(
        "UPDATE locations SET name=?, type=?, baseplate_name=?, grid_x=?, grid_y=? WHERE id=?",
        (f["name"], f.get("type") or None, f.get("baseplate_name") or None,
         f.get("grid_x") or None, f.get("grid_y") or None, location_id),
    )
    db.commit()
    flash("Location updated.", "success")
    return redirect(url_for("warehouse.index"))


@bp.route("/locations/<int:location_id>")
def detail(location_id):
    db = get_db()
    location = db.execute("SELECT * FROM locations WHERE id=?", (location_id,)).fetchone()
    if location is None:
        flash("Location not found.", "error")
        return redirect(url_for("warehouse.index"))
    parts = db.execute(
        "SELECT * FROM parts WHERE bin_location_id=? ORDER BY part_name", (location_id,)
    ).fetchall()
    return render_template("warehouse/detail.html", location=location, parts=parts)
