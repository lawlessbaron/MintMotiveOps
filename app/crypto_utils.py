"""Encrypts secrets (Stripe keys, SMTP password) at rest when they're set
via Administration > Integrations instead of an environment variable.

The encryption key is derived from SECRET_KEY, not stored separately —
this app has no separate secrets manager, and SECRET_KEY is already the
one value every deployment is required to keep safe (it signs every
session cookie). Anyone who has SECRET_KEY can already forge a login
session, so deriving from it adds no new single point of failure — it
just means rotating SECRET_KEY makes previously-encrypted values
undecryptable, which is why the Integrations page always re-checks
decrypt() at read time and treats a failure as "not configured" instead
of crashing, and why rotating SECRET_KEY means re-entering these values.
"""
import base64
import hashlib
import os
from cryptography.fernet import Fernet, InvalidToken


def _fernet():
    secret = os.environ.get("SECRET_KEY", "dev-secret-change-me")
    key = base64.urlsafe_b64encode(hashlib.sha256(secret.encode()).digest())
    return Fernet(key)


def encrypt(plaintext):
    if not plaintext:
        return None
    return _fernet().encrypt(plaintext.encode()).decode()


def decrypt(ciphertext):
    if not ciphertext:
        return None
    try:
        return _fernet().decrypt(ciphertext.encode()).decode()
    except InvalidToken:
        return None
