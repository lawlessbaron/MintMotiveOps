from flask import Blueprint, render_template, request, redirect, url_for, flash
from ..db import (
    get_db, generate_number, default_margin_for_kit, kit_total_part_cost, kit_sell_price,
    kit_bom_would_cycle, record_kit_eco,
)
from ..utils import save_upload

bp = Blueprint("kits", __name__, url_prefix="/kits")


@bp.route("/")
def index():
    db = get_db()
    kits = db.execute(
        "SELECT k.*, kc.name AS category_name FROM kits k LEFT JOIN kit_categories kc ON kc.id=k.category_id ORDER BY k.kit_name"
    ).fetchall()
    enriched = []
    for k in kits:
        cost = kit_total_part_cost(db, k["id"])
        price = kit_sell_price(db, k["id"], k["margin_pct"], k["freight_included_in_price"], k["estimated_freight_allowance"])
        enriched.append({**dict(k), "total_cost": cost, "sell_price": price})
    return render_template("kits/index.html", kits=enriched)


@bp.route("/new", methods=["GET", "POST"])
def new():
    db = get_db()
    categories = db.execute("SELECT * FROM kit_categories WHERE active=1 ORDER BY name").fetchall()
    if request.method == "POST":
        f = request.form
        margin = f.get("margin_pct")
        margin = float(margin) if margin else default_margin_for_kit(f.get("category_id") or None)
        sku = f.get("sku") or generate_number("Kit")
        image_path = save_upload(request.files.get("kit_image"), "kits")
        cur = db.execute(
            "INSERT INTO kits (kit_name, sku, category_id, screen_size, status, kit_image_path, description, "
            "margin_pct, freight_included_in_price, estimated_freight_allowance, is_subassembly) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            (f["kit_name"], sku, f.get("category_id") or None, f.get("screen_size"), f.get("status", "In Development"),
             image_path, f.get("description"), margin, 1 if f.get("freight_included_in_price") else 0,
             f.get("estimated_freight_allowance") or 0, 1 if f.get("is_subassembly") else 0),
        )
        db.commit()
        flash("Kit created.", "success")
        return redirect(url_for("kits.detail", kit_id=cur.lastrowid))
    return render_template("kits/form.html", categories=categories)


@bp.route("/<int:kit_id>")
def detail(kit_id):
    db = get_db()
    kit = db.execute("SELECT * FROM kits WHERE id=?", (kit_id,)).fetchone()
    if kit is None:
        flash("Kit not found.", "error")
        return redirect(url_for("kits.index"))

    # BOM lines are either a raw Part or another Kit (sub-assembly) — pull
    # both kinds and normalize into one shape the template can render
    # without caring which it is.
    part_lines = db.execute(
        "SELECT kp.id, kp.quantity_required, p.id AS part_id, p.part_name AS name, p.part_number, "
        "p.unit_cost AS unit_cost, 'Part' AS component_type "
        "FROM kit_parts kp JOIN parts p ON p.id=kp.part_id WHERE kp.kit_id=? AND kp.part_id IS NOT NULL",
        (kit_id,),
    ).fetchall()
    kit_lines_raw = db.execute(
        "SELECT kp.id, kp.quantity_required, k2.id AS component_kit_id, k2.kit_name AS name, k2.sku AS part_number "
        "FROM kit_parts kp JOIN kits k2 ON k2.id=kp.component_kit_id WHERE kp.kit_id=? AND kp.component_kit_id IS NOT NULL",
        (kit_id,),
    ).fetchall()
    bom = list(part_lines) + [
        {**dict(row), "component_type": "Sub-Assembly", "unit_cost": kit_total_part_cost(db, row["component_kit_id"])}
        for row in kit_lines_raw
    ]

    parts = db.execute("SELECT * FROM parts ORDER BY part_name").fetchall()
    # Any OTHER kit can be added as a sub-assembly component, except this
    # one itself (self-reference is also blocked at the DB/route level).
    available_subassemblies = db.execute(
        "SELECT * FROM kits WHERE id != ? ORDER BY kit_name", (kit_id,)
    ).fetchall()
    categories = db.execute("SELECT * FROM kit_categories WHERE active=1 ORDER BY name").fetchall()
    active_builds = db.execute(
        "SELECT b.*, c.client_name, fv.version_label FROM builds b LEFT JOIN clients c ON c.id=b.client_id "
        "LEFT JOIN firmware_versions fv ON fv.id=b.firmware_version_id "
        "WHERE b.kit_id=? AND b.status NOT IN ('Shipped','Complete') ORDER BY b.created_at DESC", (kit_id,)
    ).fetchall()
    archived_builds = db.execute(
        "SELECT b.*, c.client_name FROM builds b LEFT JOIN clients c ON c.id=b.client_id "
        "WHERE b.kit_id=? AND b.status IN ('Shipped','Complete') ORDER BY b.ship_date DESC", (kit_id,)
    ).fetchall()
    total_cost = kit_total_part_cost(db, kit_id)
    sell_price = kit_sell_price(db, kit_id, kit["margin_pct"], kit["freight_included_in_price"], kit["estimated_freight_allowance"])
    clients = db.execute("SELECT * FROM clients WHERE status='Active' ORDER BY client_name").fetchall()
    firmware_versions = db.execute(
        "SELECT * FROM firmware_versions WHERE kit_id=? ORDER BY released_at DESC", (kit_id,)
    ).fetchall()
    ecos = db.execute(
        "SELECT * FROM kit_ecos WHERE kit_id=? ORDER BY created_at DESC", (kit_id,)
    ).fetchall()
    routing_steps = db.execute(
        "SELECT * FROM routing_steps WHERE kit_id=? ORDER BY step_number", (kit_id,)
    ).fetchall()
    return render_template(
        "kits/detail.html", kit=kit, bom=bom, parts=parts, categories=categories,
        available_subassemblies=available_subassemblies,
        active_builds=active_builds, archived_builds=archived_builds,
        total_cost=total_cost, sell_price=sell_price, clients=clients,
        firmware_versions=firmware_versions, ecos=ecos, routing_steps=routing_steps,
    )


@bp.route("/<int:kit_id>/edit", methods=["POST"])
def edit(kit_id):
    db = get_db()
    f = request.form
    image_path = save_upload(request.files.get("kit_image"), "kits")
    extra = ", kit_image_path=?" if image_path else ""
    args = [f["kit_name"], f.get("sku"), f.get("category_id") or None, f.get("screen_size"), f.get("status"),
            f.get("description"), float(f.get("margin_pct") or 0), 1 if f.get("freight_included_in_price") else 0,
            float(f.get("estimated_freight_allowance") or 0), f.get("primary_cad_file_link"), f.get("project_name"),
            1 if f.get("is_subassembly") else 0]
    if image_path:
        args.append(image_path)
    args.append(kit_id)
    db.execute(
        "UPDATE kits SET kit_name=?, sku=?, category_id=?, screen_size=?, status=?, description=?, margin_pct=?, "
        "freight_included_in_price=?, estimated_freight_allowance=?, primary_cad_file_link=?, project_name=?, "
        "is_subassembly=?" + extra + " WHERE id=?",
        args,
    )
    db.commit()
    flash("Kit updated.", "success")
    return redirect(url_for("kits.detail", kit_id=kit_id))


@bp.route("/<int:kit_id>/bom/add", methods=["POST"])
def add_bom_line(kit_id):
    db = get_db()
    f = request.form
    qty = int(f.get("quantity_required", 1))
    component_kit_id = f.get("component_kit_id") or None

    if component_kit_id:
        component_kit_id = int(component_kit_id)
        if kit_bom_would_cycle(db, kit_id, component_kit_id):
            flash("Can't add that kit as a sub-assembly — it would create a circular BOM "
                  "(it already includes this kit somewhere in its own BOM).", "error")
            return redirect(url_for("kits.detail", kit_id=kit_id))
        existing = db.execute(
            "SELECT id FROM kit_parts WHERE kit_id=? AND component_kit_id=?", (kit_id, component_kit_id)
        ).fetchone()
        if existing:
            db.execute("UPDATE kit_parts SET quantity_required = quantity_required + ? WHERE id=?",
                       (qty, existing["id"]))
        else:
            db.execute("INSERT INTO kit_parts (kit_id, component_kit_id, quantity_required) VALUES (?,?,?)",
                       (kit_id, component_kit_id, qty))
    else:
        part_id = f["part_id"]
        existing = db.execute("SELECT id FROM kit_parts WHERE kit_id=? AND part_id=?", (kit_id, part_id)).fetchone()
        if existing:
            db.execute("UPDATE kit_parts SET quantity_required = quantity_required + ? WHERE id=?",
                       (qty, existing["id"]))
        else:
            db.execute("INSERT INTO kit_parts (kit_id, part_id, quantity_required) VALUES (?,?,?)",
                       (kit_id, part_id, qty))
    db.commit()
    return redirect(url_for("kits.detail", kit_id=kit_id))


@bp.route("/<int:kit_id>/firmware/add", methods=["POST"])
def add_firmware(kit_id):
    db = get_db()
    f = request.form
    file_path = save_upload(request.files.get("firmware_file"), "firmware")
    db.execute(
        "INSERT INTO firmware_versions (kit_id, version_label, file_path, release_notes) VALUES (?,?,?,?)",
        (kit_id, f["version_label"], file_path, f.get("release_notes")),
    )
    db.commit()
    flash("Firmware version added.", "success")
    return redirect(url_for("kits.detail", kit_id=kit_id))


@bp.route("/<int:kit_id>/bom/<int:line_id>/remove", methods=["POST"])
def remove_bom_line(kit_id, line_id):
    db = get_db()
    db.execute("DELETE FROM kit_parts WHERE id=? AND kit_id=?", (line_id, kit_id))
    db.commit()
    return redirect(url_for("kits.detail", kit_id=kit_id))


@bp.route("/<int:kit_id>/ecos/new", methods=["POST"])
def add_eco(kit_id):
    """Files a numbered Engineering Change Order that snapshots the kit's
    BOM exactly as it stands right now — file this right after making the
    BOM edit(s) it documents, so the snapshot captures the new state."""
    db = get_db()
    description = request.form.get("description", "").strip()
    if not description:
        flash("An ECO needs a description of what changed and why.", "error")
        return redirect(url_for("kits.detail", kit_id=kit_id))
    eco_number = record_kit_eco(db, kit_id, description)
    flash(f"ECO {eco_number} filed — current BOM snapshotted.", "success")
    return redirect(url_for("kits.detail", kit_id=kit_id))


@bp.route("/<int:kit_id>/routing/add", methods=["POST"])
def add_routing_step(kit_id):
    db = get_db()
    f = request.form
    next_step = db.execute(
        "SELECT COALESCE(MAX(step_number), 0) + 1 AS n FROM routing_steps WHERE kit_id=?", (kit_id,)
    ).fetchone()["n"]
    db.execute(
        "INSERT INTO routing_steps (kit_id, step_number, step_name, instructions, estimated_minutes) VALUES (?,?,?,?,?)",
        (kit_id, next_step, f["step_name"], f.get("instructions"), float(f.get("estimated_minutes") or 0)),
    )
    db.commit()
    flash("Routing step added.", "success")
    return redirect(url_for("kits.detail", kit_id=kit_id))


@bp.route("/<int:kit_id>/routing/<int:step_id>/remove", methods=["POST"])
def remove_routing_step(kit_id, step_id):
    db = get_db()
    db.execute("DELETE FROM routing_steps WHERE id=? AND kit_id=?", (step_id, kit_id))
    db.commit()
    return redirect(url_for("kits.detail", kit_id=kit_id))


@bp.route("/<int:kit_id>/builds/new", methods=["POST"])
def new_build(kit_id):
    db = get_db()
    f = request.form
    number = generate_number("Build")
    serial = generate_number("Serial")
    cur = db.execute(
        "INSERT INTO builds (build_number, kit_id, client_id, status, serial_number, firmware_version_id) "
        "VALUES (?,?,?,'Queued',?,?)",
        (number, kit_id, f.get("client_id") or None, serial, f.get("firmware_version_id") or None),
    )
    db.commit()
    flash(f"Build created — serial {serial}.", "success")
    return redirect(url_for("builds.detail", build_id=cur.lastrowid))
