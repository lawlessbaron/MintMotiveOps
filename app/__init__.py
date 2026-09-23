import hmac
import os
import secrets
import sqlite3
from flask import Flask, abort, g, session, redirect, url_for, request
from flask.json.provider import DefaultJSONProvider
from werkzeug.middleware.proxy_fix import ProxyFix
from . import db as db_module


class _Row_AwareJSONProvider(DefaultJSONProvider):
    """Lets |tojson (used throughout the admin/quicklinks "pick one from a
    dropdown, edit its real fields" screens) serialize sqlite3.Row objects
    straight out of the database, by treating them like plain dicts."""

    @staticmethod
    def default(o):
        if isinstance(o, sqlite3.Row):
            return dict(o)
        return DefaultJSONProvider.default(o)


def create_app():
    app = Flask(__name__, instance_relative_config=True)
    app.json = _Row_AwareJSONProvider(app)
    # Trust exactly one hop of X-Forwarded-For/-Proto/-Host — the
    # TLS-terminating proxy every real deployment in DEPLOYMENT.md sits
    # behind (Render, Fly, Caddy/Nginx). Without this, request.remote_addr
    # is the proxy's own IP for every visitor alike, which would make
    # login's per-IP rate limiting (see auth.py) useless — one shared
    # bucket for the whole site instead of one per real visitor.
    app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1)
    os.makedirs(app.instance_path, exist_ok=True)
    database_url = os.environ.get("DATABASE_URL")
    app.config.from_mapping(
        SECRET_KEY=os.environ.get("SECRET_KEY", "dev-secret-change-me"),
        DATABASE=os.path.join(app.instance_path, "mintmotive.db"),
        # Set DATABASE_URL (e.g. postgresql://user:pass@host:5432/dbname) to
        # use PostgreSQL instead of the default SQLite file — see
        # POSTGRES_SETUP.md. Nothing else needs to change.
        DATABASE_URL=database_url,
        DB_BACKEND="postgres" if database_url else "sqlite",
        # Documents/CAD/firmware uploads are the biggest legitimate files this
        # app handles; 25MB comfortably covers those while still bounding
        # request size against a disk-fill DoS from unbounded uploads.
        MAX_CONTENT_LENGTH=25 * 1024 * 1024,
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE="Lax",
        # Secure by default (the cookie is dropped on any plain-http visit,
        # which is correct since every real deployment in DEPLOYMENT.md sits
        # behind HTTPS). Piggybacks on the same FLASK_DEBUG=1 flag that
        # already means "this is local dev" (see run.py), rather than adding
        # a second env var nobody would remember to set.
        SESSION_COOKIE_SECURE=os.environ.get("FLASK_DEBUG", "0") != "1",
    )

    db_module.init_db(app)
    app.teardown_appcontext(db_module.close_db)

    # ---- blueprints ----
    from .blueprints import (
        auth, dashboard, clients, parts, suppliers, sourcing, kits, builds,
        sales_orders, purchase_orders, quotes, invoices, admin, documents,
        quicklinks, assets, warehouse, analytics, public, search,
        rmas, batches, workshop, procurement, financial, api,
    )
    app.register_blueprint(auth.bp)
    app.register_blueprint(dashboard.bp)
    app.register_blueprint(clients.bp)
    app.register_blueprint(parts.bp)
    app.register_blueprint(suppliers.bp)
    app.register_blueprint(sourcing.bp)
    app.register_blueprint(kits.bp)
    app.register_blueprint(builds.bp)
    app.register_blueprint(sales_orders.bp)
    app.register_blueprint(purchase_orders.bp)
    app.register_blueprint(quotes.bp)
    app.register_blueprint(invoices.bp)
    app.register_blueprint(admin.bp)
    app.register_blueprint(documents.bp)
    app.register_blueprint(quicklinks.bp)
    app.register_blueprint(assets.bp)
    app.register_blueprint(warehouse.bp)
    app.register_blueprint(analytics.bp)
    app.register_blueprint(public.bp)
    app.register_blueprint(search.bp)
    app.register_blueprint(rmas.bp)
    app.register_blueprint(batches.bp)
    app.register_blueprint(workshop.bp)
    app.register_blueprint(procurement.bp)
    app.register_blueprint(financial.bp)
    app.register_blueprint(api.bp)

    # ---- auth gate: everything except /login, /forgot-password,
    # /reset-password, /public/*, and /api/* (which authenticates the local
    # hardware agent with its own X-API-Key instead of a browser session —
    # see app/blueprints/api.py) requires a session user ----
    @app.before_request
    def require_login():
        open_endpoints = {"auth.login", "auth.forgot_password", "auth.reset_password", "static"}
        if request.endpoint and (
            request.endpoint in open_endpoints
            or request.endpoint.startswith("public.")
            or request.endpoint.startswith("api.")
        ):
            return
        if "user_id" not in session:
            return redirect(url_for("auth.login", next=request.path))

    # ---- role gate: "Owner" vs "Workshop" was previously a cosmetic label
    # only — session["user_role"] was set at login and shown in the topbar,
    # but no route ever checked it, so any authenticated Workshop account
    # had the same access as an Owner to user management, security
    # settings, integrations, and every financial figure in the business.
    # Administration, Financial, and Analytics are now Owner-only by
    # default; everything else operational (orders, builds, inventory,
    # warehouse) stays open to both roles. Analytics has one escape hatch:
    # a per-user can_view_analytics flag (Administration > Security) an
    # Owner can grant to a specific Workshop account without making them a
    # full Owner — see admin.add_user/edit_user. ----
    OWNER_ONLY_BLUEPRINTS = {"admin", "financial"}
    ANALYTICS_BLUEPRINT = "analytics"

    @app.before_request
    def require_owner_role():
        if "user_id" not in session:
            return  # require_login already handles the redirect-to-login case
        role = session.get("user_role")
        bp_name = request.blueprint
        if bp_name in OWNER_ONLY_BLUEPRINTS and role != "Owner":
            abort(403, description="Administration and Financial pages are restricted to Owner accounts.")
        if bp_name == ANALYTICS_BLUEPRINT and role != "Owner" and not session.get("can_view_analytics"):
            abort(
                403,
                description="Analytics & Reports are restricted to Owner accounts, or a Workshop account "
                "an Owner has specifically granted access to (Administration > Security).",
            )

    # ---- CSRF protection: every state-changing browser request must carry
    # the same token stashed in its (signed, httponly) session cookie. The
    # token is injected into every <form> client-side (see base.html) rather
    # than hand-edited into ~100 individual templates. Exempts /api/* (the
    # local hardware agent authenticates with X-API-Key, not a browser
    # session/cookie) and the Stripe webhook (a server-to-server POST from
    # Stripe, verified separately via its own signature, not a browser). ----
    @app.before_request
    def csrf_protect():
        if request.method not in ("POST", "PUT", "PATCH", "DELETE"):
            return
        if request.endpoint and (
            request.endpoint.startswith("api.") or request.endpoint == "public.stripe_webhook"
        ):
            return
        session_token = session.get("csrf_token")
        request_token = request.form.get("csrf_token") or request.headers.get("X-CSRF-Token")
        if not session_token or not request_token or not hmac.compare_digest(session_token, request_token):
            abort(400, description="Your session expired or this form was tampered with — refresh the page and try again.")

    def get_csrf_token():
        if "csrf_token" not in session:
            session["csrf_token"] = secrets.token_hex(32)
        return session["csrf_token"]

    # ---- security headers on every response ----
    @app.after_request
    def set_security_headers(response):
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        response.headers["Permissions-Policy"] = "geolocation=(), microphone=(), camera=(), payment=()"
        # 'unsafe-inline' on script/style is a real gap, not an oversight —
        # this app uses inline <script>/onclick= handlers and an inline
        # <style> block (company-branded theme tokens) throughout, and
        # locking those down needs a template-by-template nonce refactor
        # beyond this pass. Everything else here (no external script/object/
        # frame sources, no framing of this site) still holds.
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; img-src 'self' data:; style-src 'self' 'unsafe-inline'; "
            "script-src 'self' 'unsafe-inline'; font-src 'self'; object-src 'none'; "
            "frame-ancestors 'none'; base-uri 'self'; form-action 'self'"
        )
        if request.is_secure or request.headers.get("X-Forwarded-Proto") == "https":
            response.headers["Strict-Transport-Security"] = "max-age=63072000; includeSubDomains"
        return response

    # ---- inject company settings / theme / CSRF token into every template ----
    @app.context_processor
    def inject_globals():
        from . import db as dbm
        conn = dbm.get_db()
        company = conn.execute("SELECT * FROM company_settings WHERE id = 1").fetchone()
        return {
            "company": company,
            "csrf_token": get_csrf_token,
            "current_user": {
                "name": session.get("user_name"),
                "role": session.get("user_role"),
                "can_view_analytics": bool(session.get("can_view_analytics")),
            } if "user_id" in session else None,
        }

    return app
