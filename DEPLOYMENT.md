# Deploying MintMotive Ops

This app runs against either SQLite (a single file, zero setup) or real PostgreSQL — same code, same features, no business logic changes either way (see `POSTGRES_SETUP.md`). **This deployment uses Postgres**, running on the same server as the app itself: see "Single-VPS deploy" below, which is the primary path for this project. The SQLite instructions further down still work and are kept for reference (e.g. quick local testing).

## What you're deploying

- **App**: `app/` (Flask, Python 3.11+) — entry point is `run.py`, WSGI target is `app:create_app()` (a factory, so most WSGI servers need `--factory` or an explicit `wsgi.py` — see below).
- **Database**: PostgreSQL, schema auto-applied from `schema_postgres.sql` the first time the app connects to an empty database. Runs as a sibling Docker container on the same VPS as the app — see below.
- **Uploads**: product/kit/build images and documents saved under `app/static/uploads/` — persisted via a Docker volume in the single-VPS path (or a persistent disk on PaaS hosts).

## Single-VPS deploy: app + Postgres, same server, zero network hop

If you want a real Postgres database instead of the SQLite file, but don't
want it split onto a separate managed service, this is the setup: one VPS
(DigitalOcean/Hetzner/Linode/a rented box — anything that gives you root
and Docker), running the Flask app and Postgres as two containers on that
one machine's private Docker network. They never leave the box to talk to
each other — no internet hop, no separate server to keep in sync, and
Postgres isn't reachable from outside at all (see `docker-compose.yml`,
which deliberately has no `ports:` entry for the `db` service).

This repo already has everything needed for this path: `Dockerfile`,
`docker-compose.yml`, `.env.example`, and `Caddyfile.example`.

1. **Get a VPS.** A $6-12/month droplet (1-2 GB RAM) is plenty for this
   app's traffic. Point a DNS A record at its IP (e.g.
   `ops.yourdomain.com.au`).
2. **Install Docker** on it: `curl -fsSL https://get.docker.com | sh`
   (works on any fresh Ubuntu/Debian box).
3. **Get the code onto the server**: `git clone` this repo (or `git pull`
   if you set it up once already).
4. **Configure secrets**: `cp .env.example .env`, then edit `.env` and
   fill in `POSTGRES_PASSWORD` and `SECRET_KEY` (the file tells you how to
   generate a good one).
5. **Start it**: `docker compose up -d --build`. This builds the app
   image, starts Postgres, waits for Postgres to report healthy, then
   starts the app — `schema_postgres.sql` is applied automatically the
   first time the app connects to an empty database.
6. **Seed your first login** (once): `docker compose exec web python3
   seed.py you@yourdomain.com.au "Your Name"` — prints a temporary
   password, change it immediately from Administration > Security.
7. **Put HTTPS in front of it.** Easiest option is Caddy, which handles
   Let's Encrypt certificates automatically with zero manual renewal:
   ```
   sudo apt install -y debian-keyring debian-archive-keyring apt-transport-https
   curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/gpg.key' | sudo gpg --dearmor -o /usr/share/keyrings/caddy-stable-archive-keyring.gpg
   curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/debian.deb.txt' | sudo tee /etc/apt/sources.list.d/caddy-stable.list
   sudo apt update && sudo apt install caddy
   ```
   Then `cp Caddyfile.example Caddyfile`, edit in your real domain, copy
   it to `/etc/caddy/Caddyfile`, and `sudo systemctl restart caddy`. Caddy
   listens on 80/443 and reverse-proxies to the app container on 8000.
8. **Updates from then on**: `git pull && docker compose up -d --build`
   — Postgres data and uploaded files live in named Docker volumes
   (`pgdata`, `uploads`), so rebuilding the app container never touches
   them.
9. **Backups**: `docker compose exec db pg_dump -U mintmotive_app
   mintmotive | gzip > backup-$(date +%F).sql.gz` (cron it). Restoring is
   `gunzip -c backup-2026-09-22.sql.gz | docker compose exec -T db psql -U
   mintmotive_app mintmotive`.

If you're bringing across data you already entered into a SQLite copy
while testing, run `python3 migrate_sqlite_to_postgres.py` once, pointed
at this server's Postgres — see `POSTGRES_SETUP.md` for the exact steps.

## SQLite path (reference — not what this deployment uses)

The instructions below describe deploying the SQLite-backed version instead. Kept for reference in case you ever want a simpler single-file setup (e.g. for local testing or a low-traffic instance).

### Recommended host: Render.com

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

## SQLite backups (only relevant if you're on the SQLite path above)

Back up `instance/mintmotive.db` regularly — it's a single file, so `cp instance/mintmotive.db backups/mintmotive-$(date +%F).db` (cron it, or use your host's disk-snapshot feature if it has one) is a complete backup of every record in the system. If you're on the Postgres/single-VPS path instead, use the `pg_dump` backup command in that section above.
