"""Minimal Stripe REST client using plain HTTPS (the `stripe` Python SDK
isn't installable in the build sandbox — this sandbox also can't reach
api.stripe.com to test it live). Uses only `requests` and the stdlib `hmac`
module, both already installed, and talks to Stripe's plain REST API
directly, which needs no SDK. This becomes live the moment a real
STRIPE_SECRET_KEY is set — either as an environment variable (checked
first) or via Administration > Integrations (encrypted at rest, see
app/crypto_utils.py) — nothing else needs to change.
"""
import os
import hmac
import hashlib
import time
import requests

STRIPE_API_BASE = "https://api.stripe.com/v1"


def _company_settings():
    from .db import get_db
    return get_db().execute("SELECT * FROM company_settings WHERE id=1").fetchone()


def _secret_key():
    env_val = os.environ.get("STRIPE_SECRET_KEY")
    if env_val:
        return env_val
    from . import crypto_utils
    row = _company_settings()
    return crypto_utils.decrypt(row["stripe_secret_key_encrypted"]) if row else None


def webhook_secret():
    env_val = os.environ.get("STRIPE_WEBHOOK_SECRET")
    if env_val:
        return env_val
    from . import crypto_utils
    row = _company_settings()
    return crypto_utils.decrypt(row["stripe_webhook_secret_encrypted"]) if row else None


def is_configured():
    return bool(_secret_key())


def create_checkout_session(invoice, amount_cents, currency, success_url, cancel_url):
    """Creates a Stripe Checkout Session for a single line-item payment of
    the invoice total. Returns the session's hosted `url` to redirect the
    client to, or raises on error."""
    key = _secret_key()
    if not key:
        raise RuntimeError("STRIPE_SECRET_KEY is not set — add it in your deployment environment.")
    data = {
        "mode": "payment",
        "success_url": success_url,
        "cancel_url": cancel_url,
        "line_items[0][price_data][currency]": currency.lower(),
        "line_items[0][price_data][product_data][name]": f"Invoice {invoice['invoice_number']}",
        "line_items[0][price_data][unit_amount]": str(amount_cents),
        "line_items[0][quantity]": "1",
        "metadata[invoice_id]": str(invoice["id"]),
        "metadata[invoice_number]": invoice["invoice_number"],
    }
    resp = requests.post(
        f"{STRIPE_API_BASE}/checkout/sessions",
        data=data,
        auth=(key, ""),
        timeout=15,
    )
    resp.raise_for_status()
    return resp.json()


def verify_webhook_signature(payload_body, sig_header, endpoint_secret, tolerance=300):
    """Verifies a Stripe webhook signature per Stripe's documented scheme
    (t=timestamp,v1=signature) without needing the stripe SDK."""
    if not sig_header:
        return False
    parts = dict(p.split("=", 1) for p in sig_header.split(",") if "=" in p)
    timestamp = parts.get("t")
    signature = parts.get("v1")
    if not timestamp or not signature:
        return False
    if abs(time.time() - int(timestamp)) > tolerance:
        return False
    signed_payload = f"{timestamp}.{payload_body.decode() if isinstance(payload_body, bytes) else payload_body}"
    expected = hmac.new(endpoint_secret.encode(), signed_payload.encode(), hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, signature)
