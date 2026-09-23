"""Minimal SMTP email client using stdlib smtplib — no extra dependency
needed. Used for password-reset codes (see app/blueprints/auth.py) and PO
approval notifications (see app/blueprints/purchase_orders.py). Configure
via environment variables (SMTP_HOST, SMTP_PORT, SMTP_USER, SMTP_PASSWORD,
SMTP_FROM) on your deployment host, checked first — or via Administration
> Integrations (encrypted at rest for the password, see
app/crypto_utils.py), checked as a fallback. This becomes live the moment
either is set — nothing else needs to change.
"""
import os
import smtplib
import ssl
from email.message import EmailMessage


def _company_settings():
    from .db import get_db
    return get_db().execute("SELECT * FROM company_settings WHERE id=1").fetchone()


def _config():
    """Resolves host/port/user/password/from from env vars first, then the
    database. Env and DB values are never mixed field-by-field — if
    SMTP_HOST is set as an env var, the whole config comes from env vars,
    so a partially-set env doesn't silently pick up a DB password (or vice
    versa)."""
    if os.environ.get("SMTP_HOST"):
        return {
            "host": os.environ.get("SMTP_HOST"),
            "port": int(os.environ.get("SMTP_PORT", 587)),
            "user": os.environ.get("SMTP_USER"),
            "password": os.environ.get("SMTP_PASSWORD"),
            "from_addr": os.environ.get("SMTP_FROM") or os.environ.get("SMTP_USER"),
        }
    from . import crypto_utils
    row = _company_settings()
    if row and row["smtp_host"]:
        return {
            "host": row["smtp_host"],
            "port": row["smtp_port"] or 587,
            "user": row["smtp_user"],
            "password": crypto_utils.decrypt(row["smtp_password_encrypted"]),
            "from_addr": row["smtp_from"] or row["smtp_user"],
        }
    return None


def is_configured():
    cfg = _config()
    return bool(cfg and cfg["host"] and cfg["user"] and cfg["password"])


def send_email(to_address, subject, body):
    """Sends a plain-text email. Returns True if it was handed off to the
    SMTP server, False if SMTP isn't configured. Callers should show the
    same message to the user either way (see auth.forgot_password) so this
    never reveals whether a given email address has an account."""
    cfg = _config()
    if not cfg or not cfg["host"] or not cfg["user"] or not cfg["password"]:
        return False

    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = cfg["from_addr"]
    msg["To"] = to_address
    msg.set_content(body)

    context = ssl.create_default_context()
    if cfg["port"] == 465:
        with smtplib.SMTP_SSL(cfg["host"], cfg["port"], context=context, timeout=15) as server:
            server.login(cfg["user"], cfg["password"])
            server.send_message(msg)
    else:
        with smtplib.SMTP(cfg["host"], cfg["port"], timeout=15) as server:
            server.starttls(context=context)
            server.login(cfg["user"], cfg["password"])
            server.send_message(msg)
    return True
