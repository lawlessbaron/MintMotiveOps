import re
from flask import Blueprint, render_template, request, redirect, url_for, flash
from werkzeug.security import generate_password_hash
from ..db import get_db
from ..utils import save_upload
from .. import stripe_client

bp = Blueprint("admin", __name__, url_prefix="/admin")

# Simple reference lists: table -> (display label, has_margin_field)
SIMPLE_REF_LISTS = {
    "part_categories": ("Part Categories", True),
    "kit_categories": ("Kit Categories", True),
    "asset_types": ("Asset Types", False),
    "document_types": ("Document Types", False),
    "supplier_payment_terms": ("Supplier Payment Terms", False),
    "client_payment_terms": ("Client Payment Terms", False),
    "order_sources": ("Order Sources", False),
}


@bp.route("/")
def index():
    db = get_db()
    numbering_count = db.execute("SELECT COUNT(*) c FROM numbering_sequences").fetchone()["c"]
    next_invoice = db.execute("SELECT prefix, next_number, padding_length FROM numbering_sequences WHERE entity_name='Invoice'").fetchone()
    ref_list_count = len(SIMPLE_REF_LISTS)
    shopify = db.execute("SELECT * FROM integration_settings WHERE integration_name='Shopify'").fetchone()
    company = db.execute("SELECT * FROM company_settings WHERE id=1").fetchone()
    role_counts = db.execute("SELECT role, COUNT(*) c FROM users GROUP BY role").fetchall()
    next_invoice_str = None
    if next_invoice:
        next_invoice_str = f"{next_invoice['prefix']}{str(next_invoice['next_number']).zfill(next_invoice['padding_length'])}"
    return render_template(
        "admin/overview.html", numbering_count=numbering_count, next_invoice_str=next_invoice_str,
        ref_list_count=ref_list_count, shopify=shopify, company=company, role_counts=role_counts,
    )


# ---------------- Company (+ Reference Lists, Duties & Shipping, Packing, Email Templates) ----------------

@bp.route("/company", methods=["GET", "POST"])
def company():
    db = get_db()
    if request.method == "POST":
        f = request.form
        logo_path = save_upload(request.files.get("logo"), "company")
        extra = ", logo_path=?" if logo_path else ""
        args = [f.get("company_name"), f.get("abn"), f.get("address"), f.get("default_currency", "AUD"),
                float(f.get("default_margin_pct") or 0), float(f.get("default_gst_rate_pct") or 0),
                f.get("default_client_payment_term_id") or None, f.get("default_supplier_payment_term_id") or None,
                int(f.get("invoice_reminder_days") or 7),
                1 if f.get("packing_include_weight") else 0, 1 if f.get("packing_include_dimensions") else 0,
                1 if f.get("packing_include_value") else 0, 1 if f.get("packing_include_customs_description") else 0,
                1 if f.get("packing_include_hs_code") else 0, 1 if f.get("packing_include_origin_country") else 0]
        if logo_path:
            args.append(logo_path)
        db.execute(
            "UPDATE company_settings SET company_name=?, abn=?, address=?, default_currency=?, default_margin_pct=?, "
            "default_gst_rate_pct=?, default_client_payment_term_id=?, default_supplier_payment_term_id=?, "
            "invoice_reminder_days=?, packing_include_weight=?, packing_include_dimensions=?, packing_include_value=?, "
            "packing_include_customs_description=?, packing_include_hs_code=?, packing_include_origin_country=?"
            + extra + " WHERE id=1",
            args,
        )
        db.commit()
        flash("Company settings saved.", "success")
        return redirect(url_for("admin.company"))
    company = db.execute("SELECT * FROM company_settings WHERE id=1").fetchone()
    client_terms = db.execute("SELECT * FROM client_payment_terms WHERE active=1 ORDER BY name").fetchall()
    supplier_terms = db.execute("SELECT * FROM supplier_payment_terms WHERE active=1 ORDER BY name").fetchall()
    email_templates = db.execute("SELECT * FROM email_templates ORDER BY template_name").fetchall()
    ref_list_items = {
        table: db.execute(f"SELECT * FROM {table} ORDER BY name").fetchall()
        for table in SIMPLE_REF_LISTS
    }
    return render_template(
        "admin/company.html", company=company, client_terms=client_terms, supplier_terms=supplier_terms,
        ref_lists=SIMPLE_REF_LISTS, ref_list_items=ref_list_items, email_templates=email_templates,
    )


@bp.route("/company/reference-lists/<table>/add", methods=["POST"])
def ref_list_add(table):
    if table not in SIMPLE_REF_LISTS:
        flash("Unknown list.", "error")
        return redirect(url_for("admin.company"))
    db = get_db()
    f = request.form
    _, has_margin = SIMPLE_REF_LISTS[table]
    if has_margin:
        db.execute(f"INSERT INTO {table} (name, default_margin_pct) VALUES (?,?)",
                   (f["name"], f.get("default_margin_pct") or None))
    else:
        db.execute(f"INSERT INTO {table} (name) VALUES (?)", (f["name"],))
    db.commit()
    flash("Added.", "success")
    return redirect(url_for("admin.company") + f"#{table}")


@bp.route("/company/reference-lists/<table>/<int:item_id>/edit", methods=["POST"])
def ref_list_edit(table, item_id):
    if table not in SIMPLE_REF_LISTS:
        flash("Unknown list.", "error")
        return redirect(url_for("admin.company"))
    db = get_db()
    f = request.form
    _, has_margin = SIMPLE_REF_LISTS[table]
    if has_margin:
        db.execute(f"UPDATE {table} SET name=?, active=?, default_margin_pct=? WHERE id=?",
                   (f["name"], 1 if f.get("active") else 0, f.get("default_margin_pct") or None, item_id))
    else:
        db.execute(f"UPDATE {table} SET name=?, active=? WHERE id=?",
                   (f["name"], 1 if f.get("active") else 0, item_id))
    db.commit()
    flash("Updated.", "success")
    return redirect(url_for("admin.company") + f"#{table}")


# ---------------- Duties & Shipping (5 sub-types, dropdown-then-edit) ----------------

@bp.route("/duties-shipping", methods=["GET"])
def duties_shipping():
    db = get_db()
    countries = db.execute("SELECT * FROM countries ORDER BY country_name").fetchall()
    hs_codes = db.execute("SELECT * FROM harmonised_codes ORDER BY code").fetchall()
    agents = db.execute("SELECT * FROM customs_agents ORDER BY agent_name").fetchall()
    carriers = db.execute("SELECT * FROM shipping_carriers ORDER BY carrier_name").fetchall()
    rates = db.execute(
        "SELECT r.*, c.carrier_name, co.country_name FROM shipping_rates r "
        "JOIN shipping_carriers c ON c.id=r.carrier_id JOIN countries co ON co.id=r.destination_country_id"
    ).fetchall()
    return render_template("admin/duties_shipping.html", countries=countries, hs_codes=hs_codes,
                            agents=agents, carriers=carriers, rates=rates)


@bp.route("/duties-shipping/countries/save", methods=["POST"])
def save_country():
    db = get_db()
    f = request.form
    if f.get("id"):
        db.execute("UPDATE countries SET country_name=?, iso_code=?, default_import_duty_rate_pct=?, gst_tax_note=?, active=? WHERE id=?",
                   (f["country_name"], f.get("iso_code"), f.get("default_import_duty_rate_pct") or None,
                    f.get("gst_tax_note"), 1 if f.get("active") else 0, f["id"]))
    else:
        db.execute("INSERT INTO countries (country_name, iso_code, default_import_duty_rate_pct, gst_tax_note) VALUES (?,?,?,?)",
                   (f["country_name"], f.get("iso_code"), f.get("default_import_duty_rate_pct") or None, f.get("gst_tax_note")))
    db.commit()
    flash("Country saved.", "success")
    return redirect(url_for("admin.duties_shipping") + "#countries")


@bp.route("/duties-shipping/hs-codes/save", methods=["POST"])
def save_hs_code():
    db = get_db()
    f = request.form
    if f.get("id"):
        db.execute("UPDATE harmonised_codes SET code=?, description=?, default_duty_rate_pct=?, notes=? WHERE id=?",
                   (f["code"], f.get("description"), f.get("default_duty_rate_pct") or None, f.get("notes"), f["id"]))
    else:
        db.execute("INSERT INTO harmonised_codes (code, description, default_duty_rate_pct, notes) VALUES (?,?,?,?)",
                   (f["code"], f.get("description"), f.get("default_duty_rate_pct") or None, f.get("notes")))
    db.commit()
    flash("Harmonised Code saved.", "success")
    return redirect(url_for("admin.duties_shipping") + "#hscodes")


@bp.route("/duties-shipping/agents/save", methods=["POST"])
def save_agent():
    db = get_db()
    f = request.form
    if f.get("id"):
        db.execute("UPDATE customs_agents SET agent_name=?, company=?, contact_email=?, contact_phone=?, services=?, notes=? WHERE id=?",
                   (f["agent_name"], f.get("company"), f.get("contact_email"), f.get("contact_phone"), f.get("services"), f.get("notes"), f["id"]))
    else:
        db.execute("INSERT INTO customs_agents (agent_name, company, contact_email, contact_phone, services, notes) VALUES (?,?,?,?,?,?)",
                   (f["agent_name"], f.get("company"), f.get("contact_email"), f.get("contact_phone"), f.get("services"), f.get("notes")))
    db.commit()
    flash("Customs Agent saved.", "success")
    return redirect(url_for("admin.duties_shipping") + "#agents")


@bp.route("/duties-shipping/carriers/save", methods=["POST"])
def save_carrier():
    db = get_db()
    f = request.form
    if f.get("id"):
        db.execute("UPDATE shipping_carriers SET carrier_name=?, account_reference=?, notes=? WHERE id=?",
                   (f["carrier_name"], f.get("account_reference"), f.get("notes"), f["id"]))
    else:
        db.execute("INSERT INTO shipping_carriers (carrier_name, account_reference, notes) VALUES (?,?,?)",
                   (f["carrier_name"], f.get("account_reference"), f.get("notes")))
    db.commit()
    flash("Shipping Carrier saved.", "success")
    return redirect(url_for("admin.duties_shipping") + "#carriers")


@bp.route("/duties-shipping/rates/save", methods=["POST"])
def save_rate():
    db = get_db()
    f = request.form
    if f.get("id"):
        db.execute("UPDATE shipping_rates SET carrier_id=?, destination_country_id=?, service_level=?, base_fee=?, fee_per_kg=?, estimated_transit_days=? WHERE id=?",
                   (f["carrier_id"], f["destination_country_id"], f.get("service_level"), float(f.get("base_fee") or 0),
                    float(f.get("fee_per_kg") or 0), f.get("estimated_transit_days") or None, f["id"]))
    else:
        db.execute("INSERT INTO shipping_rates (carrier_id, destination_country_id, service_level, base_fee, fee_per_kg, estimated_transit_days) VALUES (?,?,?,?,?,?)",
                   (f["carrier_id"], f["destination_country_id"], f.get("service_level"), float(f.get("base_fee") or 0),
                    float(f.get("fee_per_kg") or 0), f.get("estimated_transit_days") or None))
    db.commit()
    flash("Shipping Rate saved.", "success")
    return redirect(url_for("admin.duties_shipping") + "#rates")


# ---------------- Numbering ----------------

@bp.route("/numbering", methods=["GET", "POST"])
def numbering():
    db = get_db()
    if request.method == "POST":
        f = request.form
        db.execute("UPDATE numbering_sequences SET prefix=?, next_number=?, padding_length=? WHERE id=?",
                   (f.get("prefix", ""), int(f.get("next_number", 1)), int(f.get("padding_length", 6)), f["id"]))
        db.commit()
        flash("Numbering sequence updated.", "success")
        return redirect(url_for("admin.numbering"))
    sequences = db.execute("SELECT * FROM numbering_sequences ORDER BY entity_name").fetchall()
    return render_template("admin/numbering.html", sequences=sequences)


# ---------------- Integrations ----------------

@bp.route("/integrations", methods=["GET", "POST"])
def integrations():
    db = get_db()
    for name in ("Shopify", "Stripe"):
        if db.execute("SELECT 1 FROM integration_settings WHERE integration_name=?", (name,)).fetchone() is None:
            db.execute("INSERT INTO integration_settings (integration_name, status) VALUES (?, 'Inactive')", (name,))
    db.commit()
    if request.method == "POST":
        f = request.form
        db.execute("UPDATE integration_settings SET connection_reference=? WHERE integration_name=?",
                   (f.get("connection_reference"), f["integration_name"]))
        db.commit()
        flash("Integration settings saved.", "success")
        return redirect(url_for("admin.integrations"))
    integrations = db.execute("SELECT * FROM integration_settings ORDER BY integration_name").fetchall()
    return render_template(
        "admin/integrations.html", integrations=integrations, stripe_configured=stripe_client.is_configured()
    )


@bp.route("/integrations/<name>/test-sync", methods=["POST"])
def test_sync(name):
    import datetime
    db = get_db()
    if name == "Shopify":
        # This sandbox has no outbound access to Shopify's API either, so this
        # reports the real, honest outcome instead of faking a success.
        result = "Failed — this environment can't reach the Shopify API (no outbound network access). On a deployed copy with a real Shopify API key and internet access, this pulls Products/Customers/Orders."
        status = "Error"
    elif name == "Stripe":
        if stripe_client.is_configured():
            status = "Active"
            result = "STRIPE_SECRET_KEY is set for this instance — Checkout Sessions and the /webhook/stripe endpoint are live. This does not call the Stripe API; it only confirms the key is present in the environment."
        else:
            status = "Inactive"
            result = "STRIPE_SECRET_KEY is not set in this environment — add it (and STRIPE_WEBHOOK_SECRET) in your deployment's environment variables, then re-run Test Sync."
    else:
        result = "No test defined for this integration."
        status = "Inactive"
    db.execute("UPDATE integration_settings SET status=?, last_sync_at=?, last_sync_result=? WHERE integration_name=?",
               (status, datetime.datetime.utcnow().isoformat(timespec="seconds"), result, name))
    db.commit()
    flash(f"Test sync ran — see result below.", "success")
    return redirect(url_for("admin.integrations"))


# ---------------- Security ----------------

@bp.route("/security")
def security():
    db = get_db()
    users = db.execute("SELECT * FROM users ORDER BY name").fetchall()
    return render_template("admin/security.html", users=users)


@bp.route("/security/users/add", methods=["POST"])
def add_user():
    from flask import session
    db = get_db()
    f = request.form
    existing = db.execute("SELECT id FROM users WHERE email=?", (f.get("email"),)).fetchone()
    if existing:
        flash("A user with that email already exists.", "error")
        return redirect(url_for("admin.security"))
    db.execute(
        "INSERT INTO users (name, email, password_hash, role) VALUES (?, ?, ?, ?)",
        (f.get("name"), f.get("email"), generate_password_hash(f.get("password") or "changeme123"), f.get("role", "Workshop")),
    )
    db.commit()
    flash(f"User {f.get('name')} added.", "success")
    return redirect(url_for("admin.security"))


@bp.route("/security/users/<int:user_id>/edit", methods=["POST"])
def edit_user(user_id):
    db = get_db()
    f = request.form
    if f.get("password"):
        db.execute(
            "UPDATE users SET name=?, email=?, role=?, password_hash=? WHERE id=?",
            (f.get("name"), f.get("email"), f.get("role"), generate_password_hash(f.get("password")), user_id),
        )
    else:
        db.execute(
            "UPDATE users SET name=?, email=?, role=? WHERE id=?",
            (f.get("name"), f.get("email"), f.get("role"), user_id),
        )
    db.commit()
    flash("User updated.", "success")
    return redirect(url_for("admin.security"))


@bp.route("/security/users/<int:user_id>/delete", methods=["POST"])
def delete_user(user_id):
    db = get_db()
    remaining_owners = db.execute("SELECT COUNT(*) c FROM users WHERE role='Owner' AND id != ?", (user_id,)).fetchone()["c"]
    user = db.execute("SELECT role FROM users WHERE id=?", (user_id,)).fetchone()
    if user and user["role"] == "Owner" and remaining_owners == 0:
        flash("Can't remove the last Owner account.", "error")
        return redirect(url_for("admin.security"))
    db.execute("DELETE FROM users WHERE id=?", (user_id,))
    db.commit()
    flash("User removed.", "success")
    return redirect(url_for("admin.security"))


# ---------------- Appearance ----------------

APPEARANCE_FIELDS = [
    "light_page_bg", "light_card_bg", "light_text_primary", "light_text_secondary",
    "light_accent", "light_border", "light_sidebar_bg", "light_sidebar_text", "light_text_on_accent",
    "dark_page_bg", "dark_card_bg", "dark_text_primary", "dark_text_secondary",
    "dark_accent", "dark_border", "dark_sidebar_bg", "dark_sidebar_text", "dark_text_on_accent",
]
BRAND_DEFAULTS = {
    "light_page_bg": "#F6EED9", "light_card_bg": "#FFFFFF", "light_text_primary": "#1E2124",
    "light_text_secondary": "#494949", "light_accent": "#9EC4B5", "light_border": "#494949",
    "light_sidebar_bg": "#1E2124", "light_sidebar_text": "#F6EED9", "light_text_on_accent": "#1E2124",
    "dark_page_bg": "#1E2124", "dark_card_bg": "#494949", "dark_text_primary": "#F6EED9",
    "dark_text_secondary": "#C9C9C9", "dark_accent": "#9EC4B5", "dark_border": "#6A6A6A",
    "dark_sidebar_bg": "#000000", "dark_sidebar_text": "#F6EED9", "dark_text_on_accent": "#1E2124",
}


_HEX_COLOR_RE = re.compile(r"^#[0-9a-fA-F]{3}$|^#[0-9a-fA-F]{6}$")


@bp.route("/appearance", methods=["GET", "POST"])
def appearance():
    db = get_db()
    if request.method == "POST":
        f = request.form
        # These values are written straight into an inline <style> block on
        # every page (base.html's theme-token :root block) with no further
        # escaping — a non-color value here isn't just a display bug, it's a
        # stored CSS-injection point. Reject the whole submission rather
        # than silently substituting defaults for bad fields, so a bad
        # paste is obvious instead of quietly losing part of the change.
        values = [f.get(field, BRAND_DEFAULTS[field]) for field in APPEARANCE_FIELDS]
        bad_fields = [
            field for field, value in zip(APPEARANCE_FIELDS, values) if not _HEX_COLOR_RE.match(value or "")
        ]
        if bad_fields:
            flash(
                f"Not saved — these aren't valid hex colors (e.g. #9EC4B5): {', '.join(bad_fields)}.",
                "error",
            )
            return redirect(url_for("admin.appearance"))
        set_clause = ", ".join(f"{field}=?" for field in APPEARANCE_FIELDS)
        db.execute(f"UPDATE company_settings SET {set_clause} WHERE id=1", values)
        db.commit()
        flash("Appearance updated — applied everywhere immediately.", "success")
        return redirect(url_for("admin.appearance"))
    company = db.execute("SELECT * FROM company_settings WHERE id=1").fetchone()
    return render_template("admin/appearance.html", company=company, fields=APPEARANCE_FIELDS)


@bp.route("/appearance/reset", methods=["POST"])
def appearance_reset():
    db = get_db()
    set_clause = ", ".join(f"{field}=?" for field in APPEARANCE_FIELDS)
    db.execute(f"UPDATE company_settings SET {set_clause} WHERE id=1", [BRAND_DEFAULTS[f] for f in APPEARANCE_FIELDS])
    db.commit()
    flash("Reset to brand defaults.", "success")
    return redirect(url_for("admin.appearance"))


# ---------------- Email Templates ----------------

@bp.route("/audit-log")
def audit_log():
    db = get_db()
    table_filter = request.args.get("table", "")
    sql = "SELECT * FROM audit_logs"
    args = []
    if table_filter:
        sql += " WHERE table_name=?"
        args.append(table_filter)
    sql += " ORDER BY changed_at DESC LIMIT 200"
    logs = db.execute(sql, args).fetchall()
    tables = db.execute("SELECT DISTINCT table_name FROM audit_logs ORDER BY table_name").fetchall()
    return render_template("admin/audit_log.html", logs=logs, tables=tables, table_filter=table_filter)


@bp.route("/local-agent", methods=["GET", "POST"])
def local_agent():
    db = get_db()
    if request.method == "POST":
        import secrets
        new_key = secrets.token_hex(24)
        db.execute("UPDATE company_settings SET local_agent_api_key=? WHERE id=1", (new_key,))
        db.commit()
        flash("API key generated — update local_agent/config.json on the workshop PC with this new key.", "success")
        return redirect(url_for("admin.local_agent"))
    company = db.execute("SELECT * FROM company_settings WHERE id=1").fetchone()
    monitored_assets = db.execute(
        "SELECT id, asset_name, power_plug_reference FROM assets "
        "WHERE power_plug_reference IS NOT NULL AND power_plug_reference != '' ORDER BY asset_name"
    ).fetchall()
    recent_flashes = db.execute(
        "SELECT ffl.*, b.build_number, fv.version_label FROM firmware_flash_log ffl "
        "LEFT JOIN builds b ON b.id=ffl.build_id LEFT JOIN firmware_versions fv ON fv.id=ffl.firmware_version_id "
        "ORDER BY ffl.flashed_at DESC LIMIT 20"
    ).fetchall()
    return render_template(
        "admin/local_agent.html", company=company, monitored_assets=monitored_assets,
        recent_flashes=recent_flashes,
    )


@bp.route("/email-templates/<int:tpl_id>/save", methods=["POST"])
def save_email_template(tpl_id):
    db = get_db()
    f = request.form
    db.execute("UPDATE email_templates SET subject=?, body=?, active=? WHERE id=?",
               (f.get("subject"), f.get("body"), 1 if f.get("active") else 0, tpl_id))
    db.commit()
    flash("Email template saved.", "success")
    return redirect(url_for("admin.company") + "#email-templates")
