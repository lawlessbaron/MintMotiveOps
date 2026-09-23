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
    other_locations = db.execute(
        "SELECT * FROM locations WHERE id != ? ORDER BY type, name", (location_id,)
    ).fetchall()
    return render_template("warehouse/detail.html", location=location, parts=parts, other_locations=other_locations)


@bp.route("/locations/<int:location_id>/move-parts", methods=["POST"])
def move_parts(location_id):
    db = get_db()
    dest_id = request.form.get("destination_location_id") or None
    dest = None
    if dest_id:
        dest = db.execute("SELECT * FROM locations WHERE id=?", (dest_id,)).fetchone()
        if dest is None:
            flash("Destination location not found.", "error")
            return redirect(url_for("warehouse.detail", location_id=location_id))
    count = db.execute("SELECT COUNT(*) c FROM parts WHERE bin_location_id=?", (location_id,)).fetchone()["c"]
    db.execute("UPDATE parts SET bin_location_id=? WHERE bin_location_id=?", (dest_id, location_id))
    db.commit()
    if dest:
        flash(f"Moved {count} part(s) to {dest['name']}.", "success")
    else:
        flash(f"Unassigned {count} part(s) from this location.", "success")
    return redirect(url_for("warehouse.detail", location_id=location_id))


@bp.route("/locations/<int:location_id>/delete", methods=["POST"])
def delete_location(location_id):
    db = get_db()
    location = db.execute("SELECT * FROM locations WHERE id=?", (location_id,)).fetchone()
    if location is None:
        flash("Location not found.", "error")
        return redirect(url_for("warehouse.index"))
    count = db.execute("SELECT COUNT(*) c FROM parts WHERE bin_location_id=?", (location_id,)).fetchone()["c"]
    if count > 0:
        flash(
            f"Can't delete {location['name']} — {count} part(s) are still assigned to it. "
            f"Move or unassign them first using the form below, then delete.",
            "error",
        )
        return redirect(url_for("warehouse.detail", location_id=location_id))
    db.execute("DELETE FROM locations WHERE id=?", (location_id,))
    db.commit()
    flash(f"{location['name']} deleted.", "success")
    return redirect(url_for("warehouse.index"))
