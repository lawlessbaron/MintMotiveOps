# Deploying MintMotive Ops

This is a real, self-contained Flask app with a SQLite database file — there's no build step, no Node, no separate database server to provision. That makes it simple to deploy, but it does mean the one thing you must get right is **persistent storage for the database file**, since a few popular hosts wipe local disk on every deploy.

## What you're deploying

- **App**: `app/` (Flask, Python 3.11+) — entry point is `run.py`, WSGI target is `app:create_app()` (a factory, so most WSGI servers need `--factory` or an explicit `wsgi.py` — see below).
- **Database**: SQLite file at `instance/mintmotive.db`, created automatically from `schema.sql` the first time the app runs against a fresh `instance/` folder.
- **Uploads**: product/kit/build images and documents saved under `app/static/uploads/` — these need the same persistent-disk treatment as the database.

## Recommended host: Render.com

Render's free/starter web services support a persistent disk, which is exactly what a SQLite app needs.

1. Push this project to a GitHub/GitLab repo.
2. In Render: **New > Web Service**, connect the repo.
3. Runtime: Python 3. Build command: `pip install -r requirements.txt`. Start command: `gunicorn wsgi:app`.
4. Add a **Disk**: mount path `/opt/render/project/src/instance` (or wherever your working directory resolves to), 1 GB is plenty to start. This is what stops your database and uploads from disappearing on every deploy.
5. Environment variables (Render dashboard > Environment):
   - `SECRET_KEY` — any long random string (`python3 -c "import secrets; print(secrets.token_hex(32))"`)
   - `STRIPE_SECRET_KEY` — from your Stripe dashboard (see below)
   - `STRIPE_WEBHOOK_SECRET` — from your Stripe webhook setup (see below)
6. Deploy. Then, **once**, open a Render shell (or a one-off job) and run:
   ```
   python3 seed.py you@yourdomain.com "Your Name"
   ```
   This creates the Company Settings row (with your brand colors already applied), all numbering sequences, starter reference lists, and your Owner login — it prints a temporary password once. Change it immediately from Administration > Security.

### Alternatives

- **Fly.io** — similar shape: attach a [Fly Volume](https://fly.io/docs/reference/volumes/) at the `instance/` path, set the same env vars as secrets (`fly secrets set ...`), deploy with a simple Dockerfile (`pip install -r requirements.txt`, `CMD gunicorn wsgi:app`).
- **PythonAnywhere** — good if you'd rather not touch Docker/CLI deploys. It gives you a real persistent filesystem by default (no extra disk config needed), and has a first-class "WSGI configuration file" step where you point it at `wsgi.py`.
- **Railway** — works, but double-check the volume is actually mounted at your `instance/` path before relying on it; Railway's default filesystem is ephemeral like Render's.

Avoid host types that don't offer any persistent volume at all (e.g. typical serverless/Lambda-style deploys) — every deploy or cold start would reset your database to empty.

## `wsgi.py` (add this file at deploy time)

Most WSGI servers expect a module-level `app` object, but this project uses an app *factory* (`create_app()`) so tests can spin up isolated instances. Add a two-line `wsgi.py` next to `run.py`:

```python
from app import create_app
app = create_app()
```

Then your start command is simply `gunicorn wsgi:app`.

## Setting up Stripe (the "email an invoice with a Pay Now link" feature)

The invoicing module is fully built and code-complete for Stripe Checkout — it just needs real credentials once you're deployed somewhere with outbound internet access (this development sandbox intentionally has none, which is why it couldn't be tested live end-to-end here — everything up to the actual Stripe API call has been verified against the Stripe API's documented request/response shapes).

1. Create a Stripe account at https://dashboard.stripe.com if you don't have one.
2. Dashboard > Developers > API keys — copy the **Secret key** (starts `sk_live_...` or `sk_test_...` while testing). Set it as `STRIPE_SECRET_KEY`.
3. Dashboard > Developers > Webhooks > Add endpoint. URL: `https://yourdomain.com/pay/webhook/stripe`. Event to send: `checkout.session.completed`. Copy the **Signing secret** it gives you and set it as `STRIPE_WEBHOOK_SECRET`.
4. Test with Stripe's test card `4242 4242 4242 4242`, any future expiry/CVC, before switching to live keys.
5. Once live keys are in place: Invoices > (open an invoice) > **Generate Pay Link** produces a real `https://yourdomain.com/pay/<token>` URL. Email it to the client (the in-app "Email to Client" button drafts the message; wiring real outbound email is the one remaining manual step — see below), they review the branded invoice and pay by card, and the webhook marks it Paid automatically.

## Setting up outbound email (quotes/invoices/build-complete notifications)

The app builds every outgoing email as a real, editable draft (subject + body, pulled from your Email Templates in Administration > Company) but this sandbox has no outbound SMTP/email-API access, so sending is currently marked as a recorded action rather than an actual network call. To make sending real, the cleanest option is a transactional email API (Postmark, Resend, SendGrid, or plain SMTP via your own mail provider) — add its API key as another environment variable and replace the `# TODO: send here` marker in `app/blueprints/invoices.py` (`email_to_client`) and `app/blueprints/builds.py` (`send_completion_email`) with that provider's send call. Both functions already have the finished subject/body and recipient ready to go.

## Connecting Shopify

Administration > Integrations has a working "Test Sync" button that, once deployed with internet access, is where a real Shopify Admin API call (Products/Customers/Orders) gets wired in — right now it honestly reports that this sandbox can't reach Shopify's API rather than faking a result. Add a Shopify custom app API key as `SHOPIFY_API_KEY`/`SHOPIFY_STORE_DOMAIN` env vars and implement the sync in `app/blueprints/admin.py` (`test_sync`) when you're ready.

## Growing beyond SQLite

SQLite comfortably handles a single-warehouse operation like this at real production traffic levels (it's used in production by much bigger apps than this). If you want a separately-hosted database instead — for multiple servers sharing one database, managed backups, or read replicas — this is already built in and ready to use: see `POSTGRES_SETUP.md`. Set a `DATABASE_URL` environment variable pointing at a Postgres instance (Render/Railway/Fly/Neon/Azure Database for PostgreSQL all offer one) and the app uses it automatically instead of the SQLite file — no code changes needed, and `migrate_sqlite_to_postgres.py` brings across any data you've already entered.

## Backups

Until you're on a managed database, back up `instance/mintmotive.db` regularly — it's a single file, so `cp instance/mintmotive.db backups/mintmotive-$(date +%F).db` (cron it, or use your host's disk-snapshot feature if it has one) is a complete backup of every record in the system.
