import secrets
from flask import Blueprint, render_template, request, redirect, url_for, flash
from ..db import get_db, generate_number, document_totals

bp = Blueprint("invoices", __name__, url_prefix="/invoices")


@bp.route("/")
def index():
    db = get_db()
    invoices = db.execute(
        "SELECT i.*, c.client_name FROM invoices i JOIN clients c ON c.id=i.client_id ORDER BY i.invoice_date DESC"
    ).fetchall()
    totals = {i["id"]: document_totals(db, "invoices", "invoice_id", i["id"]) for i in invoices}
    return render_template("invoices/index.html", invoices=invoices, totals=totals)


@bp.route("/new", methods=["GET", "POST"])
def new():
    db = get_db()
    clients = db.execute("SELECT * FROM clients ORDER BY client_name").fetchall()
    if request.method == "POST":
        f = request.form
        number = generate_number("Invoice")
        pt = db.execute("SELECT payment_term_id FROM clients WHERE id=?", (f["client_id"],)).fetchone()["payment_term_id"]
        cur = db.execute(
            "INSERT INTO invoices (invoice_number, client_id, payment_term_id) VALUES (?,?,?)",
            (number, f["client_id"], pt),
        )
        db.commit()
        return redirect(url_for("invoices.detail", invoice_id=cur.lastrowid))
    return render_template("invoices/form.html", clients=clients)


@bp.route("/<int:invoice_id>")
def detail(invoice_id):
    db = get_db()
    invoice = db.execute(
        "SELECT i.*, c.client_name, c.email AS client_email FROM invoices i JOIN clients c ON c.id=i.client_id WHERE i.id=?",
        (invoice_id,),
    ).fetchone()
    if invoice is None:
        flash("Invoice not found.", "error")
        return redirect(url_for("invoices.index"))
    lines = db.execute(
        "SELECT l.*, k.kit_name, p.part_name FROM invoice_lines l LEFT JOIN kits k ON k.id=l.kit_id "
        "LEFT JOIN parts p ON p.id=l.part_id WHERE l.invoice_id=?", (invoice_id,)
    ).fetchall()
    kits = db.execute("SELECT * FROM kits ORDER BY kit_name").fetchall()
    parts = db.execute("SELECT * FROM parts ORDER BY part_name").fetchall()
    countries = db.execute("SELECT * FROM countries WHERE active=1 ORDER BY country_name").fetchall()
    payment_terms = db.execute("SELECT * FROM client_payment_terms WHERE active=1 ORDER BY name").fetchall()
    company = db.execute("SELECT * FROM company_settings WHERE id=1").fetchone()
    totals = document_totals(db, "invoices", "invoice_id", invoice_id)
    public_url = url_for("public.view_invoice", token=invoice["public_token"], _external=True) if invoice["public_token"] else None

    email_tpl = db.execute("SELECT * FROM email_templates WHERE template_name='Invoice Sent'").fetchone()
    default_subject = f"{invoice['invoice_number']} from {company['company_name'] if company else 'Mint Motive Solutions'}"
    default_body = f"Hi {invoice['client_name']},\n\nYour invoice {invoice['invoice_number']} is ready — you can review and pay it using the link below.\n\nThanks for your business!"
    draft_subject = (email_tpl["subject"] if email_tpl and email_tpl["active"] else default_subject) or default_subject
    draft_body = (email_tpl["body"] if email_tpl and email_tpl["active"] else default_body) or default_body
    draft_subject = draft_subject.replace("{ClientName}", invoice["client_name"]).replace("{OrderNumber}", invoice["invoice_number"])
    draft_body = draft_body.replace("{ClientName}", invoice["client_name"]).replace("{OrderNumber}", invoice["invoice_number"])
    if public_url:
        draft_body += f"\n\nPay online: {public_url}"

    return render_template(
        "invoices/detail.html", doc=invoice, lines=lines, kits=kits, parts=parts, countries=countries,
        payment_terms=payment_terms, totals=totals, company=company, doc_type="invoice", public_url=public_url,
        draft_subject=draft_subject, draft_body=draft_body,
    )


@bp.route("/<int:invoice_id>/edit", methods=["POST"])
def edit(invoice_id):
    db = get_db()
    f = request.form
    db.execute(
        "UPDATE invoices SET payment_term_id=?, due_date=?, status=?, destination_country_id=?, "
        "shipping_duty_terms=?, display_currency=?, exchange_rate=?, estimated_freight=?, estimated_duty=?, notes=? WHERE id=?",
        (f.get("payment_term_id") or None, f.get("due_date") or None, f.get("status"),
         f.get("destination_country_id") or None, f.get("shipping_duty_terms"), f.get("display_currency"),
         float(f.get("exchange_rate") or 1), float(f.get("estimated_freight") or 0),
         float(f.get("estimated_duty") or 0), f.get("notes"), invoice_id),
    )
    db.commit()
    flash("Invoice updated.", "success")
    return redirect(url_for("invoices.detail", invoice_id=invoice_id))


@bp.route("/<int:invoice_id>/lines/add", methods=["POST"])
def add_line(invoice_id):
    db = get_db()
    f = request.form
    item_type = f.get("item_type", "Kit")
    kit_id = part_id = None
    description = f.get("description", "")
    unit_price = float(f.get("unit_price") or 0)
    if item_type == "Kit" and f.get("kit_id"):
        from ..db import kit_sell_price
        kit = db.execute("SELECT * FROM kits WHERE id=?", (f["kit_id"],)).fetchone()
        kit_id = kit["id"]; description = kit["kit_name"]
        unit_price = kit_sell_price(db, kit_id, kit["margin_pct"], kit["freight_included_in_price"], kit["estimated_freight_allowance"])
    elif item_type == "Part" and f.get("part_id"):
        from ..db import part_sell_price
        part = db.execute("SELECT * FROM parts WHERE id=?", (f["part_id"],)).fetchone()
        part_id = part["id"]; description = part["part_name"]
        unit_price = part_sell_price(part["unit_cost"], part["margin_pct"])
    db.execute(
        "INSERT INTO invoice_lines (invoice_id, item_type, kit_id, part_id, description, quantity, unit_price) VALUES (?,?,?,?,?,?,?)",
        (invoice_id, item_type, kit_id, part_id, description, int(f.get("quantity", 1)), unit_price),
    )
    db.commit()
    return redirect(url_for("invoices.detail", invoice_id=invoice_id))


@bp.route("/<int:invoice_id>/lines/<int:line_id>/remove", methods=["POST"])
def remove_line(invoice_id, line_id):
    db = get_db()
    db.execute("DELETE FROM invoice_lines WHERE id=? AND invoice_id=?", (line_id, invoice_id))
    db.commit()
    return redirect(url_for("invoices.detail", invoice_id=invoice_id))


@bp.route("/<int:invoice_id>/generate-pay-link", methods=["POST"])
def generate_pay_link(invoice_id):
    db = get_db()
    token = secrets.token_urlsafe(24)
    db.execute("UPDATE invoices SET public_token=? WHERE id=?", (token, invoice_id))
    db.execute("UPDATE invoices SET status='Sent' WHERE id=? AND status='Draft'", (invoice_id,))
    db.commit()
    flash("Pay-now link generated below.", "success")
    return redirect(url_for("invoices.detail", invoice_id=invoice_id))


@bp.route("/<int:invoice_id>/email", methods=["POST"])
def email_to_client(invoice_id):
    # Sandbox has no outbound SMTP/email-API access; this records the
    # reviewed draft.
    # TODO: send here — call your SMTP/email API (Postmark/Resend/SendGrid/etc.)
    # with request.form["subject"] / request.form["body"] and the client's email
    # once deployed. See DEPLOYMENT.md > "Setting up outbound email".
    db = get_db()
    db.execute("UPDATE invoices SET status='Sent' WHERE id=? AND status='Draft'", (invoice_id,))
    db.execute("UPDATE invoices SET notes = COALESCE(notes,'') || '\n[Emailed to client: ' || ? || ']' WHERE id=?",
               (request.form.get("subject", ""), invoice_id))
    db.commit()
    # request.form["body"] holds the reviewed draft body, ready for the real send call above.
    flash("Email marked as sent (wire up real SMTP/email API on deployment).", "success")
    return redirect(url_for("invoices.detail", invoice_id=invoice_id))
