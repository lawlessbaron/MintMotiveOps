"""One-time migration: copy everything out of your existing SQLite database
(instance/mintmotive.db) into a PostgreSQL database, so you don't lose the
suppliers/parts/clients/orders/etc. you've already entered when switching
backends.

When to use this: you've been running the app on SQLite (the default) and
now want to move to Postgres — most likely so two servers (see
WINDOWS_SERVER_DEPLOYMENT.md) can share one real database instead of each
keeping an independent file. If you're starting completely fresh on
Postgres with no existing data, you don't need this at all — just run
`python seed.py you@yourdomain.com "Your Name"` against it instead.

Usage:
    set DATABASE_URL=postgresql://user:pass@host:5432/dbname   (Windows: use `set`, not `export`)
    python migrate_sqlite_to_postgres.py [path-to-sqlite-file]

If you don't pass a path, it looks for instance/mintmotive.db (the default
location). Safe to re-run against an empty Postgres database; it refuses to
run against one that already has data, so it can't silently double-insert
or clobber anything — wipe the target database first if you really want to
start over.
"""
import os
import sys
import sqlite3

import psycopg2
import psycopg2.extras

from app import create_app
from app.db import init_db as app_init_db

# Same order the tables are created in (schema_postgres.sql) — inserting in
# this order means every foreign key a row points at is already present.
TABLE_ORDER = [
    "numbering_sequences", "integration_settings", "email_templates",
    "part_categories", "kit_categories", "asset_types", "document_types",
    "supplier_payment_terms", "client_payment_terms", "company_settings",
    "order_sources", "locations", "countries", "harmonised_codes",
    "customs_agents", "shipping_carriers", "shipping_rates", "sticker_templates",
    "suppliers", "parts", "part_suppliers", "sourcing_prospects",
    "kits", "kit_parts", "assets",
    "clients", "client_addresses", "client_contacts",
    "sales_orders", "sales_order_lines",
    "purchase_orders", "purchase_order_lines",
    "quotes", "quote_lines",
    "invoices", "invoice_lines",
    "builds", "documents", "quick_links", "users",
]


def main():
    database_url = os.environ.get("DATABASE_URL")
    if not database_url:
        print("ERROR: set the DATABASE_URL environment variable to your Postgres connection string first.")
        sys.exit(1)

    sqlite_path = sys.argv[1] if len(sys.argv) > 1 else os.path.join("instance", "mintmotive.db")
    if not os.path.exists(sqlite_path):
        print(f"ERROR: no SQLite database found at {sqlite_path}")
        sys.exit(1)

    # Make sure the Postgres schema exists (creates it fresh if this is a
    # brand-new database; does nothing if the tables are already there).
    app = create_app()
    with app.app_context():
        app_init_db(app)

    pg = psycopg2.connect(database_url)
    pg_cur = pg.cursor()

    pg_cur.execute("SELECT COUNT(*) FROM users")
    if pg_cur.fetchone()[0] > 0:
        print("ERROR: the Postgres database already has data in it (users table is non-empty).")
        print("Refusing to migrate on top of existing data — this is a one-time, empty-target operation.")
        print("If you really want to start over, drop and recreate the Postgres database first.")
        sys.exit(1)

    sconn = sqlite3.connect(sqlite_path)
    sconn.row_factory = sqlite3.Row

    total_rows = 0
    for table in TABLE_ORDER:
        rows = sconn.execute(f"SELECT * FROM {table}").fetchall()
        if not rows:
            continue
        columns = rows[0].keys()
        col_list = ", ".join(columns)
        placeholders = ", ".join(["%s"] * len(columns))
        values = [tuple(row[c] for c in columns) for row in rows]
        psycopg2.extras.execute_batch(
            pg_cur, f"INSERT INTO {table} ({col_list}) VALUES ({placeholders})", values
        )
        # Postgres's auto-increment sequence doesn't know about the explicit
        # ids we just inserted — bump it past the highest one so the next
        # real INSERT (with no id given) doesn't collide.
        pg_cur.execute(
            f"SELECT setval(pg_get_serial_sequence('{table}', 'id'), COALESCE((SELECT MAX(id) FROM {table}), 1))"
        )
        print(f"  {table}: {len(rows)} rows")
        total_rows += len(rows)

    pg.commit()
    sconn.close()
    pg_cur.close()
    pg.close()
    print(f"\nDone — {total_rows} total rows copied into Postgres.")
    print("Point DATABASE_URL at this Postgres database going forward and you're set.")


if __name__ == "__main__":
    main()
