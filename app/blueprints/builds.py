from flask import Blueprint, render_template, request, redirect, url_for, flash, current_app
from ..db import get_db, apply_build_status_change, now_str, build_labor_cost, build_true_cogs
from ..utils import save_upload
from .. import email_client

bp = Blueprint("builds", __name__, url_prefix="/builds")


@bp.route("/<int:build_id>")
def detail(build_id):
    db = get_db()
    build = db.execute(
        "SELECT b.*, k.kit_name FROM builds b JOIN kits k ON k.id=b.kit_id WHERE b.id=?", (build_id,)
    ).fetchone()
    if build is None:
        flash("Build not found.", "error")
        return redirect(url_for("kits.index"))
    clients = db.execute("SELECT * FROM clients WHERE status='Active' ORDER BY client_name").fetchall()
    carriers = db.execute("SELECT * FROM shipping_carriers ORDER BY carrier_name").fetchall()
    firmware_versions = db.execute(
        "SELECT * FROM firmware_versions WHERE kit_id=? ORDER BY released_at DESC", (build["kit_id"],)
    ).fetchall()
    quotes = db.execute("SELECT * FROM quotes WHERE client_id=? ORDER BY quote_date DESC", (build["client_id"],)).fetchall() if build["client_id"] else []
    invoices = db.execute("SELECT * FROM invoices WHERE client_id=? ORDER BY invoice_date DESC", (build["client_id"],)).fetchall() if build["client_id"] else []
    email_tpl = db.execute("SELECT * FROM email_templates WHERE template_name='Build Complete'").fetchone()
    client = db.execute("SELECT * FROM clients WHERE id=?", (build["client_id"],)).fetchone() if build["client_id"] else None
    show_email_draft = request.args.get("show_email") == "1"
    draft_subject = draft_body = None
    if show_email_draft and email_tpl:
        draft_subject = (email_tpl["subject"] or "Your MintMotive build is complete!").replace("{ClientName}", client["client_name"] if client else "")
        draft_body = (email_tpl["body"] or "Hi {ClientName},\n\nYour build {BuildNumber} is complete and ready to ship!").replace(
            "{ClientName}", client["client_name"] if client else "").replace("{BuildNumber}", build["build_number"])
    photos = (build["build_photos"] or "").split(",") if build["build_photos"] else []

    # BOM overrides (CPQ) — the Kit's normal BOM lines plus the current
    # override rows, side by side, so it's obvious which lines are custom
    # to this one physical unit.
    kit_bom_lines = db.execute(
        "SELECT kp.id, kp.quantity_required, p.part_name, p.part_number FROM kit_parts kp "
        "JOIN parts p ON p.id=kp.part_id WHERE kp.kit_id=? AND kp.part_id IS NOT NULL", (build["kit_id"],)
    ).fetchall()
    overrides = db.execute(
        "SELECT bo.*, p.part_name AS substitute_part_name, k.kit_name AS substitute_kit_name, "
        "okp.quantity_required AS original_quantity "
        "FROM build_bom_overrides bo LEFT JOIN parts p ON p.id=bo.substitute_part_id "
        "LEFT JOIN kits k ON k.id=bo.substitute_component_kit_id "
        "LEFT JOIN kit_parts okp ON okp.id=bo.original_kit_part_id "
        "WHERE bo.build_id=?", (build_id,)
    ).fetchall()
    all_parts = db.execute("SELECT * FROM parts ORDER BY part_name").fetchall()

    # Routings & Operations — the Kit's steps, with this Build's logged
    # time against each, plus the rolled-up true COGS (parts + labor).
    routing_steps = db.execute(
        "SELECT rs.*, sl.id AS log_id, sl.started_at, sl.completed_at, sl.actual_minutes "
        "FROM routing_steps rs LEFT JOIN build_step_logs sl ON sl.routing_step_id=rs.id AND sl.build_id=? "
        "WHERE rs.kit_id=? ORDER BY rs.step_number", (build_id, build["kit_id"])
    ).fetchall()
    labor_cost = build_labor_cost(db, build_id)
    true_cogs = build_true_cogs(db, build_id)

    flash_log = db.execute(
        "SELECT ffl.*, fv.version_label FROM firmware_flash_log ffl "
        "LEFT JOIN firmware_versions fv ON fv.id=ffl.firmware_version_id "
        "WHERE ffl.build_id=? ORDER BY ffl.flashed_at DESC", (build_id,)
    ).fetchall()
    agent_key_set = bool(db.execute("SELECT local_agent_api_key FROM company_settings WHERE id=1").fetchone()["local_agent_api_key"])

    return render_template(
        "builds/detail.html", build=build, clients=clients, carriers=carriers, quotes=quotes,
        invoices=invoices, client=client, show_email_draft=show_email_draft,
        draft_subject=draft_subject, draft_body=draft_body, photos=photos,
        firmware_versions=firmware_versions, kit_bom_lines=kit_bom_lines, overrides=overrides,
        all_parts=all_parts, routing_steps=routing_steps, labor_cost=labor_cost, true_cogs=true_cogs,
        flash_log=flash_log, agent_key_set=agent_key_set,
    )


@bp.route("/<int:build_id>/update", methods=["POST"])
def update(build_id):
    db = get_db()
    f = request.form
    build = db.execute("SELECT * FROM builds WHERE id=?", (build_id,)).fetchone()
    old_status = build["status"]
    new_status = f.get("status", old_status)

    db.execute(
        "UPDATE builds SET client_id=?, linked_sales_order_id=?, related_quote_id=?, related_invoice_id=?, "
        "serial_number=?, firmware_version_id=?, start_date=?, shipping_carrier_id=?, tracking_number=?, ship_date=?, notes=? WHERE id=?",
        (f.get("client_id") or None, f.get("linked_sales_order_id") or None, f.get("related_quote_id") or None,
         f.get("related_invoice_id") or None, f.get("serial_number") or None, f.get("firmware_version_id") or None,
         f.get("start_date") or None,
         f.get("shipping_carrier_id") or None, f.get("tracking_number"), f.get("ship_date") or None,
         f.get("notes"), build_id),
    )
    db.commit()

    if new_status != old_status:
        apply_build_status_change(db, build_id, new_status)
        if new_status in ("Shipped", "Complete") and old_status not in ("Shipped", "Complete"):
            db.execute("UPDATE builds SET completed_date = COALESCE(completed_date, ?) WHERE id=?", (now_str(), build_id))
            db.commit()
            flash("Status updated — stock consumed, and a completion email draft is ready below.", "success")
            return redirect(url_for("builds.detail", build_id=build_id, show_email=1))

    flash("Build updated.", "success")
    return redirect(url_for("builds.detail", build_id=build_id))


@bp.route("/<int:build_id>/photos", methods=["POST"])
def add_photo(build_id):
    db = get_db()
    path = save_upload(request.files.get("photo"), "builds")
    if path:
        build = db.execute("SELECT build_photos FROM builds WHERE id=?", (build_id,)).fetchone()
        existing = build["build_photos"]
        new_val = f"{existing},{path}" if existing else path
        db.execute("UPDATE builds SET build_photos=? WHERE id=?", (new_val, build_id))
        db.commit()
    return redirect(url_for("builds.detail", build_id=build_id))


@bp.route("/<int:build_id>/bom-override/add", methods=["POST"])
def add_bom_override(build_id):
    db = get_db()
    f = request.form
    component_kit_id = f.get("substitute_component_kit_id") or None
    part_id = f.get("substitute_part_id") or None
    db.execute(
        "INSERT INTO build_bom_overrides (build_id, original_kit_part_id, substitute_part_id, "
        "substitute_component_kit_id, quantity_required, notes) VALUES (?,?,?,?,?,?)",
        (build_id, f.get("original_kit_part_id") or None, part_id, component_kit_id,
         int(f.get("quantity_required", 1)), f.get("notes")),
    )
    db.commit()
    flash("BOM override added — will apply next time stock is reserved/consumed for this build.", "success")
    return redirect(url_for("builds.detail", build_id=build_id))


@bp.route("/<int:build_id>/bom-override/<int:override_id>/remove", methods=["POST"])
def remove_bom_override(build_id, override_id):
    db = get_db()
    db.execute("DELETE FROM build_bom_overrides WHERE id=? AND build_id=?", (override_id, build_id))
    db.commit()
    return redirect(url_for("builds.detail", build_id=build_id))


@bp.route("/<int:build_id>/steps/<int:step_id>/start", methods=["POST"])
def start_step(build_id, step_id):
    db = get_db()
    existing = db.execute(
        "SELECT id FROM build_step_logs WHERE build_id=? AND routing_step_id=?", (build_id, step_id)
    ).fetchone()
    if existing is None:
        db.execute(
            "INSERT INTO build_step_logs (build_id, routing_step_id, started_at) VALUES (?,?,?)",
            (build_id, step_id, now_str()),
        )
        db.commit()
    return redirect(url_for("builds.detail", build_id=build_id))


@bp.route("/<int:build_id>/steps/<int:step_id>/complete", methods=["POST"])
def complete_step(build_id, step_id):
    db = get_db()
    log = db.execute(
        "SELECT * FROM build_step_logs WHERE build_id=? AND routing_step_id=?", (build_id, step_id)
    ).fetchone()
    completed_at = now_str()
    actual_minutes = request.form.get("actual_minutes")
    if actual_minutes:
        actual_minutes = float(actual_minutes)
    elif log and log["started_at"]:
        from datetime import datetime
        started = datetime.strptime(log["started_at"], "%Y-%m-%d %H:%M:%S")
        actual_minutes = round((datetime.utcnow() - started).total_seconds() / 60.0, 1)
    else:
        actual_minutes = None
    if log:
        db.execute(
            "UPDATE build_step_logs SET completed_at=?, actual_minutes=? WHERE id=?",
            (completed_at, actual_minutes, log["id"]),
        )
    else:
        db.execute(
            "INSERT INTO build_step_logs (build_id, routing_step_id, started_at, completed_at, actual_minutes) "
            "VALUES (?,?,?,?,?)",
            (build_id, step_id, completed_at, completed_at, actual_minutes or 0),
        )
    db.commit()
    return redirect(url_for("builds.detail", build_id=build_id))


@bp.route("/<int:build_id>/send-completion-email", methods=["POST"])
def send_completion_email(build_id):
    db = get_db()
    build = db.execute(
        "SELECT b.build_number, c.email AS client_email FROM builds b "
        "LEFT JOIN clients c ON c.id=b.client_id WHERE b.id=?", (build_id,),
    ).fetchone()
    subject = request.form.get("subject", "")
    body = request.form.get("body", "")
    sent = False
    if build and build["client_email"]:
        try:
            sent = email_client.send_email(build["client_email"], subject, body)
        except Exception:
            current_app.logger.warning(
                f"Failed to email build completion for {build['build_number']} to {build['client_email']}",
                exc_info=True,
            )
    db.execute("UPDATE builds SET notes = COALESCE(notes,'') || '\n[Completion email sent: ' || ? || ']' WHERE id=?",
               (subject, build_id))
    db.commit()
    if sent:
        flash(f"Completion email sent to {build['client_email']}.", "success")
    elif not (build and build["client_email"]):
        flash("Marked as sent, but this build's client has no email address on file — add one from Clients.", "error")
    else:
        flash("Marked as sent, but the send failed — check SMTP settings in Administration > Integrations.", "error")
    return redirect(url_for("builds.detail", build_id=build_id))
