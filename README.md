# MintMotive Ops

A real, self-hosted business operations system for Mint Motive Solutions — inventory, suppliers/sourcing, kits & builds (with automatic stock reservation), sales orders, clients, quotes/invoices (GST-aware, with a Stripe "email a Pay Now link" flow like MYOB/Xero), purchase orders with partial receiving, warehouse/assets, documents, quick links & label URLs, analytics/CSV reports, and full admin control over every reference list, numbering sequence, and brand color.

Built as plain Flask + Jinja — no Node, no build step, no low-code platform. Uses SQLite by default (zero setup, a single file) with optional PostgreSQL support if you want a separately-hosted database (see `POSTGRES_SETUP.md`) — same app, same code, just set a `DATABASE_URL` environment variable. Every screen is server-rendered; the whole UI is themed live from 18 color values you control in Administration > Appearance (see `app/templates/base.html` / `app/static/css/app.css`).

## Running it locally

```
pip install -r requirements.txt
python3 seed.py you@yourdomain.com "Your Name"   # first run only — creates your login + starter data
python3 run.py
```

Then open http://127.0.0.1:5000 and log in with the email/password `seed.py` printed.

## Project layout

- `schema.sql` — the entire database schema (one file, ~40 tables), self-documenting with comments. Used for the default SQLite backend.
- `schema_postgres.sql` — the same schema, in PostgreSQL dialect, used automatically instead when `DATABASE_URL` is set. Keep both in sync if you add or change tables.
- `app/db.py` — every piece of real business logic lives here: pricing formulas, numbering sequences, GST/document totals, the build stock-reservation lifecycle, purchase-order receiving/status transitions. Routes call these functions rather than re-implementing the rules. Also where the SQLite/Postgres backend switch lives.
- `migrate_sqlite_to_postgres.py` — one-time script to copy existing SQLite data across if you switch backends after already using the app (see `POSTGRES_SETUP.md`).
- `app/blueprints/` — one file per module (clients, parts, kits, builds, sales_orders, purchase_orders, quotes, invoices, admin, documents, quicklinks, assets, warehouse, analytics, search, public, auth, dashboard).
- `app/templates/` — one folder per module, mirroring the blueprints.
- `app/stripe_client.py` — a hand-rolled Stripe REST client (Checkout Sessions + webhook signature verification) using only `requests`/stdlib, so it needs no SDK install.
- `seed.py` — idempotent first-run setup (company settings, numbering, reference lists, email templates, your Owner login).
- `run.py` / `requirements.txt` — dev entry point and pinned dependencies.
- `functional_test.py` / `smoke_test.py` — end-to-end tests that exercise every module through the real Flask test client (create a supplier → part → kit/BOM → client → sales order → PO with partial receiving → quote → convert to invoice → generate pay link → build lifecycle with stock reservation → warehouse/documents/quick links/assets → every Administration tab). Run with `python3 functional_test.py <your-password>` after seeding.

## Deploying

**Railway**: see "Railway (recommended)" at the top of `DEPLOYMENT.md` (its own project, Railway Postgres, a volume for uploads).

See `DEPLOYMENT.md` — covers hosting (Render/Fly/PythonAnywhere, with persistent-disk notes since this uses SQLite), wiring up real Stripe keys, outbound email, and the Shopify integration.

Running your own Windows server (Azure VM, rented VPS, etc.) instead? See
`WINDOWS_SERVER_DEPLOYMENT.md` — covers Waitress (the Windows-compatible
production server, used automatically via `serve.py`), keeping it running
permanently with Task Scheduler, exposing it over HTTPS with a subdomain +
Caddy without touching your main domain's DNS, and the primary/cold-standby
setup if you're running two servers.

Running two (or more) servers that should share one database instead of
each keeping its own SQLite file? See `POSTGRES_SETUP.md`.
