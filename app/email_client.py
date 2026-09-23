"""Minimal SMTP email client using stdlib smtplib — no extra dependency
needed. Used for password-reset codes (see app/blueprints/auth.py).
Configure via environment variables (SMTP_HOST, SMTP_PORT, SMTP_USER,
SMTP_PASSWORD, SMTP_FROM) on your deployment host; this becomes live the
moment those are set, exactly like STRIPE_SECRET_KEY in stripe_client.py —
nothing else needs to change.
"""
import os
import smtplib
import ssl
from email.message import EmailMessage


def is_configured():
    return bool(
        os.environ.get("SMTP_HOST") and os.environ.get("SMTP_USER") and os.environ.get("SMTP_PASSWORD")
    )


def send_email(to_address, subject, body):
    """Sends a plain-text email. Returns True if it was handed off to the
    SMTP server, False if SMTP isn't configured. Callers should show the
    same message to the user either way (see auth.forgot_password) so this
    never reveals whether a given email address has an account."""
    if not is_configured():
        return False
    host = os.environ["SMTP_HOST"]
    port = int(os.environ.get("SMTP_PORT", 587))
    user = os.environ["SMTP_USER"]
    password = os.environ["SMTP_PASSWORD"]
    from_addr = os.environ.get("SMTP_FROM", user)

    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = from_addr
    msg["To"] = to_address
    msg.set_content(body)

    context = ssl.create_default_context()
    if port == 465:
        with smtplib.SMTP_SSL(host, port, context=context, timeout=15) as server:
            server.login(user, password)
            server.send_message(msg)
    else:
        with smtplib.SMTP(host, port, timeout=15) as server:
            server.starttls(context=context)
            server.login(user, password)
            server.send_message(msg)
    return True
