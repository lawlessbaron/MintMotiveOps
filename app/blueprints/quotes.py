from flask import Blueprint, render_template, request, redirect, url_for, flash, current_app
from ..db import get_db, generate_number, document_totals
from .. import email_client

bp = Blueprint("quotes", __name__, url_prefix="/quotes")


@bp.route("/")
def index():
    db = get_db()
    quotes = db.execute(
        "SELECT q.*, c.client_name FROM quotes q JOIN clients c ON c.id=q.client_id ORDER BY q.quote_date DESC"
    ).fetchall()
    totals = {q["id"]: document_totals(db, "quotes", "quote_id", q["id"]) for q in quotes}
    return render_template("quotes/index.html", quotes=quotes, totals=totals)


@bp.route("/new", methods=["GET", "POST"])
def new():
    db = get_db()
    clients = db.execute("SELECT * FROM clients ORDER BY client_name").fetchall()
    if request.method == "POST":
        f = request.form
        number = generate_number("Quote")
        pt = db.execute("SELECT payment_term_id FROM clients WHERE id=?", (f["client_id"],)).fetchone()["payment_term_id"]
        cur = db.execute(
            "INSERT INTO quotes (quote_number, client_id, payment_term_id) VALUES (?,?,?)",
            (number, f["client_id"], pt),
        )
        db.commit()
        return redirect(url_for("quotes.detail", quote_id=cur.lastrowid))
    return render_template("quotes/form.html", clients=clients)


@bp.route("/<int:quote_id>")
def detail(quote_id):
    db = get_db()
    quote = db.execute(
        "SELECT q.*, c.client_name, c.email AS client_email FROM quotes q JOIN clients c ON c.id=q.client_id WHERE q.id=?",
        (quote_id,),
    ).fetchone()
    if quote is None:
        flash("Quote not found.", "error")
        return redirect(url_for("quotes.index"))
    lines = db.execute(
        "SELECT l.*, k.kit_name, p.part_name FROM quote_lines l LEFT JOIN kits k ON k.id=l.kit_id "
        "LEFT JOIN parts p ON p.id=l.part_id WHERE l.quote_id=?", (quote_id,)
    ).fetchall()
    kits = db.execute("SELECT * FROM kits ORDER BY kit_name").fetchall()
    parts = db.execute("SELECT * FROM parts ORDER BY part_name").fetchall()
    countries = db.execute("SELECT * FROM countries WHERE active=1 ORDER BY country_name").fetchall()
    payment_terms = db.execute("SELECT * FROM client_payment_terms WHERE active=1 ORDER BY name").fetchall()
    company = db.execute("SELECT * FROM company_settings WHERE id=1").fetchone()
    totals = document_totals(db, "quotes", "quote_id", quote_id)

    email_tpl = db.execute("SELECT * FROM email_templates WHERE template_name='Quote Sent'").fetchone()
    default_subject = f"Your quote {quote['quote_number']} from {company['company_name'] if company else 'Mint Motive Solutions'}"
    default_body = f"Hi {quote['client_name']},\n\nThanks for your interest — your quote {quote['quote_number']} is ready for review below.\n\nAny questions at all, just reply to this email."
    draft_subject = (email_tpl["subject"] if email_tpl and email_tpl["active"] else default_subject) or default_subject
    draft_body = (email_tpl["body"] if email_tpl and email_tpl["active"] else default_body) or default_body
    draft_subject = draft_subject.replace("{ClientName}", quote["client_name"]).replace("{OrderNumber}", quote["quote_number"])
    draft_body = draft_body.replace("{ClientName}", quote["client_name"]).replace("{OrderNumber}", quote["quote_number"])

    return render_template(
        "quotes/detail.html", doc=quote, lines=lines, kits=kits, parts=parts, countries=countries,
        payment_terms=payment_terms, totals=totals, company=company, doc_type="quote",
        draft_subject=draft_subject, draft_body=draft_body,
    )


@bp.route("/<int:quote_id>/email", methods=["POST"])
def email_to_client(quote_id):
    db = get_db()
    quote = db.execute(
        "SELECT q.quote_number, c.email AS client_email FROM quotes q "
        "JOIN clients c ON c.id=q.client_id WHERE q.id=?", (quote_id,),
    ).fetchone()
    subject = request.form.get("subject", "")
    body = request.form.get("body", "")
    sent = False
    if quote and quote["client_email"]:
        try:
            sent = email_client.send_email(quote["client_email"], subject, body)
        except Exception:
            current_app.logger.warning(
                f"Failed to email quote {quote['quote_number']} to {quote['client_email']}",
                exc_info=True,
            )
    db.execute("UPDATE quotes SET status='Sent' WHERE id=? AND status='Draft'", (quote_id,))
    db.execute("UPDATE quotes SET notes = COALESCE(notes,'') || '\n[Emailed to client: ' || ? || ']' WHERE id=?",
               (subject, quote_id))
    db.commit()
    if sent:
        flash(f"Email sent to {quote['client_email']}.", "success")
    elif not (quote and quote["client_email"]):
        flash("Marked as sent, but this client has no email address on file — add one from Clients.", "error")
    else:
        flash("Marked as sent, but the send failed — check SMTP settings in Administration > Integrations.", "error")
    return redirect(url_for("quotes.detail", quote_id=quote_id))


@bp.route("/<int:quote_id>/edit", methods=["POST"])
def edit(quote_id):
    db = get_db()
    f = request.form
    db.execute(
        "UPDATE quotes SET payment_term_id=?, expiry_date=?, status=?, destination_country_id=?, "
        "shipping_duty_terms=?, display_currency=?, exchange_rate=?, estimated_freight=?, estimated_duty=?, notes=? WHERE id=?",
        (f.get("payment_term_id") or None, f.get("expiry_date") or None, f.get("status"),
         f.get("destination_country_id") or None, f.get("shipping_duty_terms"), f.get("display_currency"),
         float(f.get("exchange_rate") or 1), float(f.get("estimated_freight") or 0),
         float(f.get("estimated_duty") or 0), f.get("notes"), quote_id),
    )
    db.commit()
    flash("Quote updated.", "success")
    return redirect(url_for("quotes.detail", quote_id=quote_id))


@bp.route("/<int:quote_id>/lines/add", methods=["POST"])
def add_line(quote_id):
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
        "INSERT INTO quote_lines (quote_id, item_type, kit_id, part_id, description, quantity, unit_price) VALUES (?,?,?,?,?,?,?)",
        (quote_id, item_type, kit_id, part_id, description, int(f.get("quantity", 1)), unit_price),
    )
    db.commit()
    return redirect(url_for("quotes.detail", quote_id=quote_id))


@bp.route("/<int:quote_id>/lines/<int:line_id>/remove", methods=["POST"])
def remove_line(quote_id, line_id):
    db = get_db()
    db.execute("DELETE FROM quote_lines WHERE id=? AND quote_id=?", (line_id, quote_id))
    db.commit()
    return redirect(url_for("quotes.detail", quote_id=quote_id))


@bp.route("/<int:quote_id>/convert-to-invoice", methods=["POST"])
def convert_to_invoice(quote_id):
    db = get_db()
    q = db.execute("SELECT * FROM quotes WHERE id=?", (quote_id,)).fetchone()
    number = generate_number("Invoice")
    cur = db.execute(
        "INSERT INTO invoices (invoice_number, client_id, related_quote_id, payment_term_id, destination_country_id, "
        "shipping_duty_terms, display_currency, exchange_rate, estimated_freight, estimated_duty, notes) "
        "VALUES (?,?,?,?,?,?,?,?,?,?,?)",
        (number, q["client_id"], quote_id, q["payment_term_id"], q["destination_country_id"], q["shipping_duty_terms"],
         q["display_currency"], q["exchange_rate"], q["estimated_freight"], q["estimated_duty"], q["notes"]),
    )
    invoice_id = cur.lastrowid
    for l in db.execute("SELECT * FROM quote_lines WHERE quote_id=?", (quote_id,)).fetchall():
        db.execute(
            "INSERT INTO invoice_lines (invoice_id, item_type, kit_id, part_id, description, quantity, unit_price) "
            "VALUES (?,?,?,?,?,?,?)",
            (invoice_id, l["item_type"], l["kit_id"], l["part_id"], l["description"], l["quantity"], l["unit_price"]),
        )
    db.commit()
    flash("Converted to Invoice.", "success")
    return redirect(url_for("invoices.detail", invoice_id=invoice_id))
