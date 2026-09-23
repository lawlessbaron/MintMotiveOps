from flask import Blueprint, render_template, request, redirect, abort, current_app
from ..db import get_db, document_totals, now_str
from .. import stripe_client

bp = Blueprint("public", __name__, url_prefix="/pay")


@bp.route("/<token>")
def view_invoice(token):
    db = get_db()
    invoice = db.execute(
        "SELECT i.*, c.client_name, c.email AS client_email FROM invoices i JOIN clients c ON c.id=i.client_id "
        "WHERE i.public_token=?", (token,)
    ).fetchone()
    if invoice is None:
        abort(404)
    lines = db.execute(
        "SELECT l.*, k.kit_name, p.part_name FROM invoice_lines l LEFT JOIN kits k ON k.id=l.kit_id "
        "LEFT JOIN parts p ON p.id=l.part_id WHERE l.invoice_id=?", (invoice["id"],)
    ).fetchall()
    company = db.execute("SELECT * FROM company_settings WHERE id=1").fetchone()
    totals = document_totals(db, "invoices", "invoice_id", invoice["id"])
    return render_template(
        "public/invoice.html", doc=invoice, lines=lines, company=company, totals=totals,
        doc_type="invoice", doc_label=("Tax Invoice" if totals["gst_amount"] > 0 else "Invoice"),
        show_abn=totals["gst_amount"] > 0, token=token, stripe_ready=stripe_client.is_configured(),
    )


@bp.route("/<token>/checkout", methods=["POST"])
def checkout(token):
    db = get_db()
    invoice = db.execute("SELECT * FROM invoices WHERE public_token=?", (token,)).fetchone()
    if invoice is None:
        abort(404)
    totals = document_totals(db, "invoices", "invoice_id", invoice["id"])
    amount_cents = int(round(totals["total"] * 100))
    success_url = request.url_root.rstrip("/") + f"/pay/{token}?paid=1"
    cancel_url = request.url_root.rstrip("/") + f"/pay/{token}"
    try:
        session = stripe_client.create_checkout_session(
            invoice, amount_cents, totals["currency"], success_url, cancel_url
        )
        db.execute("UPDATE invoices SET stripe_checkout_session_id=? WHERE id=?", (session["id"], invoice["id"]))
        db.commit()
        return redirect(session["url"])
    except Exception as e:
        current_app.logger.warning(f"Stripe checkout failed: {e}")
        return render_template("public/stripe_unavailable.html", token=token, error=str(e))


@bp.route("/webhook/stripe", methods=["POST"])
def stripe_webhook():
    payload = request.get_data()
    sig_header = request.headers.get("Stripe-Signature")
    secret = stripe_client.webhook_secret()
    if not secret or not stripe_client.verify_webhook_signature(payload, sig_header, secret):
        abort(400)
    import json
    event = json.loads(payload)
    if event.get("type") == "checkout.session.completed":
        session_obj = event["data"]["object"]
        invoice_id = session_obj.get("metadata", {}).get("invoice_id")
        if invoice_id:
            db = get_db()
            db.execute(
                "UPDATE invoices SET status='Paid', paid_at=? WHERE id=?", (now_str(), invoice_id)
            )
            db.commit()
    return {"received": True}
