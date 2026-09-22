"""One-time (idempotent) seed script — populates the reference data and the
first Owner login the app needs to be usable at all. Safe to re-run: every
insert checks for existing data first, so it never duplicates rows or
overwrites anything you've since edited in Administration.

Usage:  python3 seed.py
"""
import secrets
import string
import sys
from werkzeug.security import generate_password_hash

from app import create_app
from app.db import get_db

NUMBERING_DEFAULTS = [
    ("Part", "PART-", 6),
    ("Supplier", "SUP-", 4),
    ("Kit", "KIT-", 4),
    ("Sales Order", "SO-", 6),
    ("Purchase Order", "PO-", 6),
    ("Quote", "QT-", 6),
    ("Invoice", "INV-", 6),
    ("Build", "BLD-", 6),
    ("Serial", "MM-BB-", 4),
    ("ECO", "ECO-", 4),
    ("RMA", "RMA-", 4),
    ("Batch Run", "BATCH-", 4),
]

REF_LIST_DEFAULTS = {
    "part_categories": ["Electronics", "Hardware", "3D Printed", "Fasteners"],
    "kit_categories": ["Sim Racing Rigs", "Button Boxes", "Wheel Stands"],
    "asset_types": ["3D Printer", "Tool", "Computer", "Other Equipment"],
    "document_types": ["Invoice", "Packing Slip", "CAD Drawing", "Customs Declaration", "Warranty"],
    "supplier_payment_terms": ["Net 30", "Net 14", "Prepaid", "COD"],
    "client_payment_terms": ["Due on Receipt", "Net 14", "Net 30"],
    "order_sources": ["Shopify", "Direct / Word of Mouth", "Trade Show", "Referral"],
}

EMAIL_TEMPLATES = [
    ("Quote Sent", "Your quote {OrderNumber} from Mint Motive Solutions",
     "Hi {ClientName},\n\nThanks for your interest — your quote {OrderNumber} is attached/linked below for review.\n\nAny questions at all, just reply to this email.\n\nCheers,\nMintMotive"),
    ("Invoice Sent", "Invoice {OrderNumber} from Mint Motive Solutions",
     "Hi {ClientName},\n\nYour invoice {OrderNumber} is ready — you can review and pay securely using the link below.\n\nThanks for your business!\n\nMintMotive"),
    ("Invoice Payment Reminder", "Reminder: Invoice {OrderNumber} is due",
     "Hi {ClientName},\n\nJust a friendly reminder that invoice {OrderNumber} is coming up for payment. You can pay securely using the link below.\n\nMintMotive"),
    ("Build Complete", "Your {KitName} build is complete!",
     "Hi {ClientName},\n\nGreat news — your {KitName} build ({BuildNumber}) is complete and about to ship. We'll send tracking details shortly.\n\nMintMotive"),
]


def _gen_password(length=14):
    alphabet = string.ascii_letters + string.digits
    return "".join(secrets.choice(alphabet) for _ in range(length))


def seed(owner_email, owner_name="Reece"):
    app = create_app()
    with app.app_context():
        db = get_db()

        # --- Company settings singleton row (every other column has a DB default) ---
        if db.execute("SELECT 1 FROM company_settings WHERE id=1").fetchone() is None:
            db.execute(
                "INSERT INTO company_settings (id, company_name) VALUES (1, 'Mint Motive Solutions')"
            )
            print("✓ Company settings row created (brand colors + defaults applied).")
        else:
            print("· Company settings already present — left untouched.")

        # --- Numbering sequences ---
        for entity, prefix, padding in NUMBERING_DEFAULTS:
            if db.execute("SELECT 1 FROM numbering_sequences WHERE entity_name=?", (entity,)).fetchone() is None:
                db.execute(
                    "INSERT INTO numbering_sequences (entity_name, prefix, next_number, padding_length) VALUES (?,?,1,?)",
                    (entity, prefix, padding),
                )
        print("✓ Numbering sequences seeded (Part/Supplier/Kit/Sales Order/Purchase Order/Quote/Invoice/Build).")

        # --- Simple reference lists ---
        for table, names in REF_LIST_DEFAULTS.items():
            existing = db.execute(f"SELECT COUNT(*) c FROM {table}").fetchone()["c"]
            if existing == 0:
                for name in names:
                    db.execute(f"INSERT INTO {table} (name) VALUES (?)", (name,))
        print("✓ Reference lists seeded (categories, payment terms, order sources, etc.).")

        # --- Countries (at least Australia, since GST/duty logic assumes it) ---
        if db.execute("SELECT 1 FROM countries WHERE country_name='Australia'").fetchone() is None:
            db.execute(
                "INSERT INTO countries (country_name, iso_code, default_import_duty_rate_pct, gst_tax_note) "
                "VALUES ('Australia', 'AU', 0, 'GST applies at the company default rate')"
            )
        print("✓ Australia seeded as a default country for Duties & Shipping.")

        # --- Integrations ---
        for name in ("Shopify", "Stripe"):
            if db.execute("SELECT 1 FROM integration_settings WHERE integration_name=?", (name,)).fetchone() is None:
                db.execute("INSERT INTO integration_settings (integration_name, status) VALUES (?, 'Inactive')", (name,))
        print("✓ Integrations rows seeded (Shopify, Stripe — connect them from Administration > Integrations).")

        # --- Email templates ---
        if db.execute("SELECT COUNT(*) c FROM email_templates").fetchone()["c"] == 0:
            for name, subject, body in EMAIL_TEMPLATES:
                db.execute(
                    "INSERT INTO email_templates (template_name, subject, body, active) VALUES (?,?,?,1)",
                    (name, subject, body),
                )
        print("✓ Email templates seeded (Quote Sent, Invoice Sent, Payment Reminder, Build Complete).")

        # --- Owner user ---
        existing_user = db.execute("SELECT 1 FROM users WHERE lower(email)=?", (owner_email.lower(),)).fetchone()
        password = None
        if existing_user is None:
            password = _gen_password()
            db.execute(
                "INSERT INTO users (name, email, password_hash, role) VALUES (?,?,?,'Owner')",
                (owner_name, owner_email, generate_password_hash(password)),
            )
            print(f"✓ Owner account created for {owner_email}.")
        else:
            print(f"· A user with email {owner_email} already exists — left untouched.")

        db.commit()

        if password:
            print("\n" + "=" * 60)
            print(" YOUR LOGIN")
            print("=" * 60)
            print(f" Email:    {owner_email}")
            print(f" Password: {password}")
            print(" (change this from Administration > Security after first login)")
            print("=" * 60 + "\n")


if __name__ == "__main__":
    email = sys.argv[1] if len(sys.argv) > 1 else "reece@mintmotive.com.au"
    name = sys.argv[2] if len(sys.argv) > 2 else "Reece"
    seed(email, name)
