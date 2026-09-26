"""Database access layer for MintMotive Ops.

No ORM is used (Prisma/SQLAlchemy aren't installable in the build
environment), just plain SQL with row objects that behave like dicts, plus
a handful of helper functions that implement the real business logic
(numbering, margin defaults, stock reservation, computed totals) so it
lives in one place instead of being copy-pasted into every route.

Two backends are supported, chosen automatically by whether a
DATABASE_URL environment variable is set:

  - SQLite (default) — zero setup, a single file at instance/mintmotive.db.
    This is what local development and WINDOWS_SETUP.md use.
  - PostgreSQL — set DATABASE_URL (e.g. postgresql://user:pass@host:5432/db)
    and the app uses that instead. This is what lets two servers (see
    WINDOWS_SERVER_DEPLOYMENT.md) share one real database instead of each
    keeping an independent SQLite file. See POSTGRES_SETUP.md.

Every route and every helper function below calls `get_db()` and then uses
the sqlite3-style shortcut API (`db.execute(sql, params).fetchone()/.fetchall()`,
`cur.lastrowid`, `db.commit()`) — regardless of which backend is active.
The `PGConnection`/`_PGCursor` wrapper classes exist purely so that same
calling code works unchanged against psycopg2, which doesn't have that
shortcut API natively. If you're adding a new query, just use `?` for
placeholders like everywhere else — it's translated automatically.
"""
import sqlite3
import os
import json
import re
from datetime import datetime, date
from urllib.parse import urlparse, parse_qs
from flask import current_app, g

_LOCAL_PG_HOSTS = {"db", "localhost", "127.0.0.1", "::1", None}


def _pg_connect_kwargs(database_url):
    """Adds sslmode=require automatically for any Postgres host that isn't a
    same-machine/same-Docker-network connection (docker-compose's `db`
    service, or localhost) — every managed Postgres this app documents
    (Render, Fly, POSTGRES_SETUP.md) supports it, and a plaintext
    connection to a real network host would otherwise send every query,
    row, and the connection password itself in the clear. Never overrides
    an sslmode the URL already specifies. Also bounds how long a single
    statement or an idle-in-transaction connection can hold locks, so a
    runaway query or a request that opened a transaction and never
    finished can't starve every other connection indefinitely."""
    kwargs = {"options": "-c statement_timeout=30000 -c idle_in_transaction_session_timeout=30000"}
    parsed = urlparse(database_url)
    query = parse_qs(parsed.query)
    if "sslmode" not in query and parsed.hostname not in _LOCAL_PG_HOSTS:
        # Railway's private network (*.railway.internal) is already an
        # encrypted tunnel between services in one project, so use TLS when
        # the database offers it but don't refuse to connect without it.
        kwargs["sslmode"] = "prefer" if (parsed.hostname or "").endswith(".railway.internal") else "require"
    return kwargs


def now_str():
    """UTC timestamp string in the same format both schemas' CURRENT_TIMESTAMP
    column defaults produce ('YYYY-MM-DD HH:MM:SS'). Use this instead of a
    literal CURRENT_TIMESTAMP inside hand-written UPDATE/INSERT statements —
    Postgres won't implicitly cast a timestamp value to a TEXT column when
    you assign it directly (only SQLite is that permissive), so passing an
    already-formatted string as a normal bound parameter keeps the same SQL
    working on both backends."""
    return datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")


# ---------------------------------------------------------------------------
# Automatic audit logging — every UPDATE/DELETE that goes through either
# backend's connection wrapper below gets an audit_logs row, with NO
# per-call-site opt-in needed anywhere in the app. This is still a
# heuristic, not guaranteed row-level diffing (there's no ORM/ORM-events
# layer to hook that into): table_name comes from matching the SQL text's
# leading "UPDATE <table> SET" / "DELETE FROM <table>", and record_id is
# only filled in for the common, unambiguous "...WHERE id = ?" shape
# (taking the last bound parameter) — every other WHERE shape still gets
# logged (table/action/who/when/the SQL itself in `details`), just with
# record_id left NULL rather than guessed wrong. numbering_sequences is
# excluded (a pure internal counter, incremented on every single numbered
# record and adding pure noise), and audit_logs itself is excluded to
# avoid logging its own inserts.
# ---------------------------------------------------------------------------

_AUDIT_EXCLUDED_TABLES = {"audit_logs", "numbering_sequences"}
_AUDIT_UPDATE_TABLE_RE = re.compile(r"^\s*UPDATE\s+(\w+)\s+SET", re.I)
_AUDIT_DELETE_TABLE_RE = re.compile(r"^\s*DELETE\s+FROM\s+(\w+)", re.I)
_AUDIT_BARE_ID_WHERE_RE = re.compile(r"WHERE\s+id\s*=\s*\?\s*$", re.I)


def _maybe_audit(raw_execute, sql, params, changed_by=None):
    """Called AFTER the real statement has already executed successfully
    (never before — an attempted write that raised should never appear in
    the log as if it happened). raw_execute(sql, params) must run
    straight against the backend's own raw connection/cursor using that
    backend's native placeholder style, bypassing the wrapper's own
    execute() so this can never recurse into itself."""
    stripped = sql.strip()
    m = _AUDIT_UPDATE_TABLE_RE.match(stripped)
    if m:
        action, table_name = "UPDATE", m.group(1)
    else:
        m = _AUDIT_DELETE_TABLE_RE.match(stripped)
        if not m:
            return
        action, table_name = "DELETE", m.group(1)
    if table_name in _AUDIT_EXCLUDED_TABLES:
        return
    record_id = None
    if params and _AUDIT_BARE_ID_WHERE_RE.search(stripped):
        record_id = params[-1]
    if changed_by is None:
        try:
            from flask import session, has_request_context
            if has_request_context():
                changed_by = session.get("user_name")
        except Exception:
            changed_by = None
    try:
        raw_execute(
            "INSERT INTO audit_logs (table_name, record_id, action, changed_by, details) VALUES (?,?,?,?,?)",
            (table_name, record_id, action, changed_by, stripped[:300]),
        )
    except Exception:
        pass  # audit logging is best-effort and must never break a real write


def audit_log_write(db, table_name, record_id, action, changed_by=None, details=None):
    """Manual escape hatch for logging something the automatic hook can't
    see as a single UPDATE/DELETE statement — e.g. a bulk change applied
    across several rows in a loop, where one combined log entry is more
    useful than N automatic ones."""
    db.execute(
        "INSERT INTO audit_logs (table_name, record_id, action, changed_by, details) VALUES (?,?,?,?,?)",
        (table_name, record_id, action, changed_by, details),
    )


# ---------------------------------------------------------------------------
# PostgreSQL compatibility wrapper — makes a psycopg2 connection look like
# the sqlite3.Connection shortcut API the rest of this file (and every
# blueprint) is written against.
# ---------------------------------------------------------------------------

class _PGCursor:
    """Wraps a psycopg2 cursor with fetchone()/fetchall() plus a
    `.lastrowid` attribute. Postgres has no native lastrowid, so INSERT
    statements that don't already have a RETURNING clause get one appended
    automatically — every table in this schema uses `id` as its primary
    key column name, so this is safe uniformly."""

    def __init__(self, cur, lastrowid=None):
        self._cur = cur
        self.lastrowid = lastrowid

    def fetchone(self):
        return self._cur.fetchone()

    def fetchall(self):
        return self._cur.fetchall()

    @property
    def rowcount(self):
        return self._cur.rowcount


class PGConnection:
    """Thin wrapper so code written against sqlite3.Connection's shortcut
    API (`conn.execute(sql, params)` returning a cursor, plus `.commit()`)
    works unchanged against psycopg2. `?` placeholders are translated to
    `%s` — safe here because every value in this codebase is always passed
    as a bound parameter, never spliced into the SQL text, so a literal
    "?" character never appears inside the SQL string itself."""

    def __init__(self, raw_conn):
        self._conn = raw_conn

    def execute(self, sql, params=()):
        stripped = sql.lstrip()
        is_insert = stripped[:6].upper() == "INSERT"
        pg_sql = sql.replace("?", "%s")
        if is_insert and "RETURNING" not in sql.upper():
            pg_sql = pg_sql.rstrip().rstrip(";") + " RETURNING id"
        cur = self._conn.cursor()
        cur.execute(pg_sql, params)
        lastrowid = None
        if is_insert:
            import psycopg2
            try:
                row = cur.fetchone()
                lastrowid = row["id"] if row else None
            except psycopg2.ProgrammingError:
                lastrowid = None
        _maybe_audit(self._raw_audit_execute, sql, params)
        return _PGCursor(cur, lastrowid=lastrowid)

    def _raw_audit_execute(self, sql, params):
        self._conn.cursor().execute(sql.replace("?", "%s"), params)

    def executemany(self, sql, seq_of_params):
        cur = self._conn.cursor()
        cur.executemany(sql.replace("?", "%s"), seq_of_params)
        return _PGCursor(cur)

    def executescript(self, script_sql):
        cur = self._conn.cursor()
        cur.execute(script_sql)
        return _PGCursor(cur)

    def commit(self):
        self._conn.commit()

    def close(self):
        self._conn.close()


class SQLiteConnection:
    """Wraps a raw sqlite3.Connection purely so every write made through
    it is checked for automatic audit logging (see _maybe_audit) — no
    blueprint anywhere needs to opt in table by table. Every other method
    just forwards straight through to the real connection."""

    def __init__(self, raw_conn):
        self._conn = raw_conn

    def execute(self, sql, params=()):
        cur = self._conn.execute(sql, params)
        _maybe_audit(self._raw_audit_execute, sql, params)
        return cur

    def _raw_audit_execute(self, sql, params):
        self._conn.execute(sql, params)

    def executemany(self, sql, seq_of_params):
        return self._conn.executemany(sql, seq_of_params)

    def executescript(self, script_sql):
        return self._conn.executescript(script_sql)

    def commit(self):
        self._conn.commit()

    def close(self):
        self._conn.close()


def get_db():
    if "db" not in g:
        if current_app.config.get("DB_BACKEND") == "postgres":
            import psycopg2
            import psycopg2.extras
            raw = psycopg2.connect(
                current_app.config["DATABASE_URL"],
                cursor_factory=psycopg2.extras.RealDictCursor,
                **_pg_connect_kwargs(current_app.config["DATABASE_URL"]),
            )
            g.db = PGConnection(raw)
        else:
            raw = sqlite3.connect(
                current_app.config["DATABASE"],
                detect_types=sqlite3.PARSE_DECLTYPES,
            )
            raw.row_factory = sqlite3.Row
            raw.execute("PRAGMA foreign_keys = ON")
            # Same reasoning as init_db's busy_timeout — gunicorn's workers
            # each hold their own connection against the one SQLite file, so
            # two concurrent requests writing at once should wait briefly
            # for each other rather than one throwing "database is locked".
            raw.execute("PRAGMA busy_timeout = 5000")
            g.db = SQLiteConnection(raw)
    return g.db


def close_db(e=None):
    db = g.pop("db", None)
    if db is not None:
        db.close()


# Tables added after an install may already have run its one-time
# schema.sql/schema_postgres.sql apply (see init_db below — that only fires
# against a brand-new, empty database). Anything added here runs on every
# startup, on every existing install too, so a new feature's table shows up
# without anyone needing to run a manual migration.
_MIGRATIONS_SQLITE = """
CREATE TABLE IF NOT EXISTS password_reset_tokens (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    code_hash TEXT NOT NULL,
    expires_at TEXT NOT NULL,
    attempts INTEGER NOT NULL DEFAULT 0,
    used INTEGER NOT NULL DEFAULT 0,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS login_attempts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    email TEXT NOT NULL,
    ip_address TEXT,
    success INTEGER NOT NULL DEFAULT 0,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP
);
-- Generic marker for one-off data corrections (e.g. scripts/*.py fixing
-- something an earlier version of itself got wrong) — insert a row once
-- a fix has run so it never re-applies, without needing a bespoke
-- "already fixed?" heuristic per fix.
CREATE TABLE IF NOT EXISTS applied_data_fixes (
    fix_name TEXT PRIMARY KEY,
    applied_at TEXT DEFAULT CURRENT_TIMESTAMP
);
"""

_MIGRATIONS_POSTGRES = """
CREATE TABLE IF NOT EXISTS password_reset_tokens (
    id SERIAL PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    code_hash TEXT NOT NULL,
    expires_at TEXT NOT NULL,
    attempts INTEGER NOT NULL DEFAULT 0,
    used INTEGER NOT NULL DEFAULT 0,
    created_at TEXT DEFAULT to_char(CURRENT_TIMESTAMP, 'YYYY-MM-DD HH24:MI:SS')
);
CREATE TABLE IF NOT EXISTS login_attempts (
    id SERIAL PRIMARY KEY,
    email TEXT NOT NULL,
    ip_address TEXT,
    success INTEGER NOT NULL DEFAULT 0,
    created_at TEXT DEFAULT to_char(CURRENT_TIMESTAMP, 'YYYY-MM-DD HH24:MI:SS')
);
CREATE TABLE IF NOT EXISTS applied_data_fixes (
    fix_name TEXT PRIMARY KEY,
    applied_at TEXT DEFAULT to_char(CURRENT_TIMESTAMP, 'YYYY-MM-DD HH24:MI:SS')
);
ALTER TABLE users ADD COLUMN IF NOT EXISTS can_view_analytics INTEGER NOT NULL DEFAULT 0;
ALTER TABLE users ADD COLUMN IF NOT EXISTS spending_limit REAL;
ALTER TABLE users ADD COLUMN IF NOT EXISTS hidden_analytics_widgets TEXT;
ALTER TABLE purchase_orders ADD COLUMN IF NOT EXISTS requested_by INTEGER REFERENCES users(id) ON DELETE SET NULL;
ALTER TABLE purchase_orders ADD COLUMN IF NOT EXISTS approval_status TEXT NOT NULL DEFAULT 'Not Required';
ALTER TABLE purchase_orders ADD COLUMN IF NOT EXISTS approved_by INTEGER REFERENCES users(id) ON DELETE SET NULL;
ALTER TABLE purchase_orders ADD COLUMN IF NOT EXISTS approved_at TEXT;
ALTER TABLE purchase_orders ADD COLUMN IF NOT EXISTS approval_notes TEXT;
ALTER TABLE company_settings ADD COLUMN IF NOT EXISTS stripe_secret_key_encrypted TEXT;
ALTER TABLE company_settings ADD COLUMN IF NOT EXISTS stripe_webhook_secret_encrypted TEXT;
ALTER TABLE company_settings ADD COLUMN IF NOT EXISTS smtp_host TEXT;
ALTER TABLE company_settings ADD COLUMN IF NOT EXISTS smtp_port INTEGER;
ALTER TABLE company_settings ADD COLUMN IF NOT EXISTS smtp_user TEXT;
ALTER TABLE company_settings ADD COLUMN IF NOT EXISTS smtp_password_encrypted TEXT;
ALTER TABLE company_settings ADD COLUMN IF NOT EXISTS smtp_from TEXT;
ALTER TABLE company_settings ADD COLUMN IF NOT EXISTS tagline TEXT;
ALTER TABLE company_settings ADD COLUMN IF NOT EXISTS show_company_name INTEGER NOT NULL DEFAULT 1;
ALTER TABLE company_settings ADD COLUMN IF NOT EXISTS show_tagline INTEGER NOT NULL DEFAULT 1;
ALTER TABLE company_settings ADD COLUMN IF NOT EXISTS favicon_path TEXT;
ALTER TABLE company_settings ADD COLUMN IF NOT EXISTS quote_stale_days INTEGER NOT NULL DEFAULT 7;
ALTER TABLE company_settings ADD COLUMN IF NOT EXISTS review_request_days INTEGER NOT NULL DEFAULT 7;
ALTER TABLE company_settings ADD COLUMN IF NOT EXISTS tasks_api_key TEXT;
ALTER TABLE builds ADD COLUMN IF NOT EXISTS review_request_sent_at TEXT;
"""


def _ensure_column_sqlite(conn, table, column, coltype_sql):
    """SQLite's ADD COLUMN IF NOT EXISTS needs 3.35+ (2021) — check via
    PRAGMA table_info instead so this self-heal works on any version."""
    cols = [row[1] for row in conn.execute(f"PRAGMA table_info({table})").fetchall()]
    if column not in cols:
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {coltype_sql}")


def init_db(app):
    if app.config.get("DB_BACKEND") == "postgres":
        return _init_db_postgres(app)

    db_path = app.config["DATABASE"]
    schema_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "schema.sql")
    fresh = not os.path.exists(db_path)
    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA foreign_keys = ON")
    # Gunicorn runs multiple worker processes, each calling init_db() once
    # at startup against the same SQLite file. Without a busy_timeout, two
    # workers' self-heal ALTER TABLE calls landing at the same moment fail
    # immediately with "database is locked" instead of one just waiting a
    # few hundred ms for the other — an unhandled exception here crashes
    # that worker's boot, which is exactly the kind of thing that shows up
    # as a 502 (Render's proxy can't reach a process that never came up).
    conn.execute("PRAGMA busy_timeout = 5000")
    if fresh:
        with open(schema_path) as f:
            conn.executescript(f.read())
    conn.executescript(_MIGRATIONS_SQLITE)
    _ensure_column_sqlite(conn, "users", "can_view_analytics", "INTEGER NOT NULL DEFAULT 0")
    _ensure_column_sqlite(conn, "users", "spending_limit", "REAL")
    _ensure_column_sqlite(conn, "users", "hidden_analytics_widgets", "TEXT")
    _ensure_column_sqlite(conn, "purchase_orders", "requested_by", "INTEGER REFERENCES users(id) ON DELETE SET NULL")
    _ensure_column_sqlite(conn, "purchase_orders", "approval_status", "TEXT NOT NULL DEFAULT 'Not Required'")
    _ensure_column_sqlite(conn, "purchase_orders", "approved_by", "INTEGER REFERENCES users(id) ON DELETE SET NULL")
    _ensure_column_sqlite(conn, "purchase_orders", "approved_at", "TEXT")
    _ensure_column_sqlite(conn, "purchase_orders", "approval_notes", "TEXT")
    _ensure_column_sqlite(conn, "company_settings", "stripe_secret_key_encrypted", "TEXT")
    _ensure_column_sqlite(conn, "company_settings", "stripe_webhook_secret_encrypted", "TEXT")
    _ensure_column_sqlite(conn, "company_settings", "smtp_host", "TEXT")
    _ensure_column_sqlite(conn, "company_settings", "smtp_port", "INTEGER")
    _ensure_column_sqlite(conn, "company_settings", "smtp_user", "TEXT")
    _ensure_column_sqlite(conn, "company_settings", "smtp_password_encrypted", "TEXT")
    _ensure_column_sqlite(conn, "company_settings", "smtp_from", "TEXT")
    _ensure_column_sqlite(conn, "company_settings", "tagline", "TEXT")
    _ensure_column_sqlite(conn, "company_settings", "show_company_name", "INTEGER NOT NULL DEFAULT 1")
    _ensure_column_sqlite(conn, "company_settings", "show_tagline", "INTEGER NOT NULL DEFAULT 1")
    _ensure_column_sqlite(conn, "company_settings", "favicon_path", "TEXT")
    _ensure_column_sqlite(conn, "company_settings", "quote_stale_days", "INTEGER NOT NULL DEFAULT 7")
    _ensure_column_sqlite(conn, "company_settings", "review_request_days", "INTEGER NOT NULL DEFAULT 7")
    _ensure_column_sqlite(conn, "company_settings", "tasks_api_key", "TEXT")
    _ensure_column_sqlite(conn, "builds", "review_request_sent_at", "TEXT")
    conn.commit()
    conn.close()
    return fresh


def _init_db_postgres(app):
    import psycopg2
    schema_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "schema_postgres.sql")
    conn = psycopg2.connect(app.config["DATABASE_URL"], **_pg_connect_kwargs(app.config["DATABASE_URL"]))
    cur = conn.cursor()
    cur.execute(
        "SELECT EXISTS (SELECT 1 FROM information_schema.tables WHERE table_name = 'company_settings')"
    )
    fresh = not cur.fetchone()[0]
    if fresh:
        with open(schema_path) as f:
            cur.execute(f.read())
    cur.execute(_MIGRATIONS_POSTGRES)
    conn.commit()
    cur.close()
    conn.close()
    return fresh


def query(sql, args=(), one=False):
    db = get_db()
    cur = db.execute(sql, args)
    rows = cur.fetchall()
    return (rows[0] if rows else None) if one else rows


def execute(sql, args=()):
    db = get_db()
    cur = db.execute(sql, args)
    db.commit()
    return cur.lastrowid


def executemany(sql, seq_of_args):
    db = get_db()
    db.executemany(sql, seq_of_args)
    db.commit()


# ---------------------------------------------------------------------------
# Numbering sequences — drives "auto-generate" on every numbered entity
# ---------------------------------------------------------------------------

def generate_number(entity_name):
    """Reads that entity's Prefix + Next Number + Padding Length, builds the
    number, saves the increment, and returns the finished string. Each
    entity's row is independent, so fixing one never depends on another."""
    db = get_db()
    row = db.execute(
        "SELECT * FROM numbering_sequences WHERE entity_name = ?", (entity_name,)
    ).fetchone()
    if row is None:
        # Self-heal: create a sane default sequence if it's missing.
        db.execute(
            "INSERT INTO numbering_sequences (entity_name, prefix, next_number, padding_length) "
            "VALUES (?, ?, 1, 6)",
            (entity_name, entity_name[:3].upper() + "-"),
        )
        db.commit()
        row = db.execute(
            "SELECT * FROM numbering_sequences WHERE entity_name = ?", (entity_name,)
        ).fetchone()
    number = f"{row['prefix']}{str(row['next_number']).zfill(row['padding_length'])}"
    db.execute(
        "UPDATE numbering_sequences SET next_number = next_number + 1 WHERE id = ?",
        (row["id"],),
    )
    db.commit()
    return number


# ---------------------------------------------------------------------------
# Pricing — Part/Kit margin defaults (Category first, Company fallback)
# ---------------------------------------------------------------------------

def default_margin_for_part(category_id):
    db = get_db()
    if category_id:
        row = db.execute(
            "SELECT default_margin_pct FROM part_categories WHERE id = ?", (category_id,)
        ).fetchone()
        if row and row["default_margin_pct"] is not None:
            return row["default_margin_pct"]
    company = db.execute("SELECT default_margin_pct FROM company_settings WHERE id = 1").fetchone()
    return company["default_margin_pct"] if company else 0


def default_margin_for_kit(category_id):
    db = get_db()
    if category_id:
        row = db.execute(
            "SELECT default_margin_pct FROM kit_categories WHERE id = ?", (category_id,)
        ).fetchone()
        if row and row["default_margin_pct"] is not None:
            return row["default_margin_pct"]
    company = db.execute("SELECT default_margin_pct FROM company_settings WHERE id = 1").fetchone()
    return company["default_margin_pct"] if company else 0


def default_payment_term(kind):
    """kind is 'client' or 'supplier' — returns Company Settings' default id."""
    db = get_db()
    col = "default_client_payment_term_id" if kind == "client" else "default_supplier_payment_term_id"
    row = db.execute(f"SELECT {col} AS pt FROM company_settings WHERE id = 1").fetchone()
    return row["pt"] if row else None


def spending_approval_needed(db, user_id, amount):
    """True if this user's spending limit requires Owner approval before
    the given $ amount can actually be committed (see
    purchase_orders.update_status). A NULL/unset limit means unlimited —
    every Owner, and any Workshop account an Owner hasn't restricted from
    Administration > Security."""
    if not amount or not user_id:
        return False
    user = db.execute("SELECT role, spending_limit FROM users WHERE id=?", (user_id,)).fetchone()
    if user is None or user["role"] == "Owner" or user["spending_limit"] is None:
        return False
    return amount > user["spending_limit"]


def purchase_order_total(db, po_id):
    return db.execute(
        "SELECT COALESCE(SUM(quantity_ordered * unit_cost), 0) t FROM purchase_order_lines "
        "WHERE purchase_order_id=?", (po_id,)
    ).fetchone()["t"]


# ---------------------------------------------------------------------------
# Computed fields (kept in Python since generated columns referencing other
# tables aren't portable across SQLite/Postgres — these are the single
# source of truth so no screen ever needs to duplicate the formula)
# ---------------------------------------------------------------------------

def part_sell_price(unit_cost, margin_pct):
    return round((unit_cost or 0) * (1 + (margin_pct or 0) / 100), 2)


def part_available_qty(on_hand, reserved):
    return (on_hand or 0) - (reserved or 0)


def kit_total_part_cost(db, kit_id, _visited=None):
    """Sums a kit's BOM cost. A BOM line is either a raw Part (its
    unit_cost) or another Kit acting as a sub-assembly (that kit's own
    total cost, computed recursively) — this is what makes multi-level
    BOMs work: a "final" kit can consume sub-assembly kits, which can
    themselves consume parts or further sub-assemblies.

    _visited guards against a cycle ever reaching here (add_bom_line/
    kit_bom_would_cycle should prevent one from being created in the first
    place, but this is the safety net that stops a runaway recursion if
    one somehow exists in the data)."""
    if _visited is None:
        _visited = set()
    if kit_id in _visited:
        return 0
    _visited = _visited | {kit_id}

    lines = db.execute(
        "SELECT part_id, component_kit_id, quantity_required FROM kit_parts WHERE kit_id = ?",
        (kit_id,),
    ).fetchall()
    total = 0.0
    for line in lines:
        qty = line["quantity_required"] or 0
        if line["part_id"] is not None:
            part = db.execute("SELECT unit_cost FROM parts WHERE id = ?", (line["part_id"],)).fetchone()
            total += qty * (part["unit_cost"] if part else 0)
        elif line["component_kit_id"] is not None:
            total += qty * kit_total_part_cost(db, line["component_kit_id"], _visited)
    return round(total, 2)


def kit_bom_would_cycle(db, kit_id, proposed_component_kit_id):
    """True if adding proposed_component_kit_id as a BOM component of
    kit_id would create a cycle — i.e. kit_id appears anywhere in
    proposed_component_kit_id's own BOM tree (directly or through further
    sub-assembly levels). Call this before inserting a component_kit_id
    line; the direct self-reference case (a kit including itself) is
    already blocked by a CHECK constraint in the schema."""
    if proposed_component_kit_id == kit_id:
        return True
    stack = [proposed_component_kit_id]
    seen = set()
    while stack:
        current = stack.pop()
        if current in seen:
            continue
        seen.add(current)
        sub_kit_ids = db.execute(
            "SELECT component_kit_id FROM kit_parts WHERE kit_id = ? AND component_kit_id IS NOT NULL",
            (current,),
        ).fetchall()
        for row in sub_kit_ids:
            child = row["component_kit_id"]
            if child == kit_id:
                return True
            stack.append(child)
    return False


def kit_sell_price(db, kit_id, margin_pct, freight_included, freight_allowance):
    total_cost = kit_total_part_cost(db, kit_id)
    base = total_cost + (freight_allowance or 0) if freight_included else total_cost
    return round(base * (1 + (margin_pct or 0) / 100), 2)


def line_total(quantity, unit_price):
    return round((quantity or 0) * (unit_price or 0), 2)


def document_totals(db, table, id_field, doc_id, gst_rate=None):
    """Shared Subtotal/GST/Total calculation for Quotes and Invoices."""
    lines_table = {"quotes": "quote_lines", "invoices": "invoice_lines"}[table]
    fk = {"quotes": "quote_id", "invoices": "invoice_id"}[table]
    row = db.execute(
        f"SELECT COALESCE(SUM(quantity * unit_price), 0) AS subtotal FROM {lines_table} WHERE {fk} = ?",
        (doc_id,),
    ).fetchone()
    subtotal = round(row["subtotal"], 2)
    doc = db.execute(f"SELECT * FROM {table} WHERE id = ?", (doc_id,)).fetchone()
    freight = doc["estimated_freight"] or 0
    duty = doc["estimated_duty"] or 0
    currency = doc["display_currency"]
    exchange_rate = doc["exchange_rate"] or 1
    if gst_rate is None:
        company = db.execute("SELECT default_gst_rate_pct FROM company_settings WHERE id = 1").fetchone()
        gst_rate = company["default_gst_rate_pct"] if company else 0
    gst_amount = round(subtotal * (gst_rate / 100), 2) if currency == "AUD" else 0
    total = round((subtotal + freight + duty + gst_amount) * exchange_rate, 2)
    return {
        "subtotal": subtotal,
        "gst_amount": gst_amount,
        "freight": freight,
        "duty": duty,
        "total": total,
        "currency": currency,
    }


# ---------------------------------------------------------------------------
# Stock reservation lifecycle (Builds)
# ---------------------------------------------------------------------------

IN_PROGRESS_STATUSES = {"Printing", "Assembly", "QC"}
FINISHED_STATUSES = {"Shipped", "Complete"}


def apply_build_status_change(db, build_id, new_status):
    """Reserve stock when a build starts, consume it when it finishes,
    release the reservation (never touching on-hand stock) if it's
    cancelled or bounced back to Queued before finishing."""
    build = db.execute("SELECT * FROM builds WHERE id = ?", (build_id,)).fetchone()
    if build is None:
        return
    # Effective BOM = the Kit's normal kit_parts, with any Build-level CPQ
    # overrides (build_bom_overrides) substituted in — only raw Part lines
    # carry a stock count in this schema (a sub-assembly Kit consumed here
    # gets built/tracked via its own Build), so only those are reserved.
    bom = [
        line for line in build_effective_bom(db, build_id)
        if line["part_id"] is not None
    ]

    already_reserved = bool(build["stock_reserved"])
    already_consumed = bool(build["stock_consumed"])

    if new_status in IN_PROGRESS_STATUSES and not already_reserved:
        for line in bom:
            db.execute(
                "UPDATE parts SET quantity_reserved = quantity_reserved + ? WHERE id = ?",
                (line["quantity_required"], line["part_id"]),
            )
        db.execute("UPDATE builds SET stock_reserved = 1 WHERE id = ?", (build_id,))

    elif new_status in FINISHED_STATUSES and not already_consumed:
        for line in bom:
            db.execute(
                "UPDATE parts SET quantity_on_hand = quantity_on_hand - ?, "
                "quantity_reserved = quantity_reserved - ? WHERE id = ?",
                (line["quantity_required"], line["quantity_required"], line["part_id"]),
            )
        db.execute("UPDATE builds SET stock_consumed = 1, stock_reserved = 1 WHERE id = ?", (build_id,))

    elif new_status in ("Queued", "Cancelled") and already_reserved and not already_consumed:
        for line in bom:
            db.execute(
                "UPDATE parts SET quantity_reserved = quantity_reserved - ? WHERE id = ?",
                (line["quantity_required"], line["part_id"]),
            )
        db.execute("UPDATE builds SET stock_reserved = 0 WHERE id = ?", (build_id,))

    db.execute("UPDATE builds SET status = ? WHERE id = ?", (new_status, build_id))
    db.commit()


# ---------------------------------------------------------------------------
# Purchase order receiving — auto status transitions
# ---------------------------------------------------------------------------

def recompute_po_status(db, po_id):
    lines = db.execute(
        "SELECT quantity_ordered, quantity_received FROM purchase_order_lines WHERE purchase_order_id = ?",
        (po_id,),
    ).fetchall()
    if not lines:
        return
    total_ordered = sum(l["quantity_ordered"] for l in lines)
    total_received = sum(l["quantity_received"] for l in lines)
    po = db.execute("SELECT status FROM purchase_orders WHERE id = ?", (po_id,)).fetchone()
    if po["status"] in ("Draft", "Cancelled"):
        return  # don't auto-advance a PO that hasn't been sent, or was cancelled
    if total_received <= 0:
        new_status = po["status"] if po["status"] not in ("Partially Received", "Received") else "Confirmed"
    elif total_received < total_ordered:
        new_status = "Partially Received"
    else:
        new_status = "Received"
    db.execute("UPDATE purchase_orders SET status = ? WHERE id = ?", (new_status, po_id))
    if new_status == "Received":
        db.execute(
            "UPDATE purchase_orders SET closed_date = ? WHERE id = ? AND closed_date IS NULL",
            (datetime.utcnow().date().isoformat(), po_id),
        )
    db.commit()


def receive_po_line(db, line_id, quantity_received_delta):
    line = db.execute("SELECT * FROM purchase_order_lines WHERE id = ?", (line_id,)).fetchone()
    old_received = line["quantity_received"]
    new_received = min(old_received + quantity_received_delta, line["quantity_ordered"])
    new_received = max(new_received, 0)
    actual_delta = new_received - old_received
    db.execute(
        "UPDATE purchase_order_lines SET quantity_received = ? WHERE id = ?", (new_received, line_id)
    )
    db.execute(
        "UPDATE parts SET quantity_on_hand = quantity_on_hand + ? WHERE id = ?",
        (quantity_received_delta, line["part_id"]),
    )
    if actual_delta > 0:
        # Auto-file an itemized expense for this receipt — the real GST-Paid
        # source for the BAS Generator. unit_cost is treated as GST-inclusive
        # (matching the old estimate's assumption), so the GST component is
        # the receipt value / 11. Guarded by actual_delta > 0 so a receive
        # call that can't add stock (already fully received, or a 0/negative
        # delta) never files a zero-value duplicate line.
        po = db.execute(
            "SELECT po_number, supplier_id FROM purchase_orders WHERE id = ?",
            (line["purchase_order_id"],),
        ).fetchone()
        part = db.execute("SELECT part_name FROM parts WHERE id = ?", (line["part_id"],)).fetchone()
        line_value = round(actual_delta * line["unit_cost"], 2)
        gst_amount = round(line_value / 11, 2)
        amount_ex_gst = round(line_value - gst_amount, 2)
        db.execute(
            "INSERT INTO expenses (category, description, supplier_id, amount_ex_gst, gst_amount, "
            "source, related_purchase_order_id) VALUES (?,?,?,?,?,?,?)",
            (
                "Stock Purchases",
                f"PO {po['po_number']} receipt: {part['part_name']} x{actual_delta}",
                po["supplier_id"],
                amount_ex_gst,
                gst_amount,
                "Purchase Order",
                line["purchase_order_id"],
            ),
        )
    db.commit()
    recompute_po_status(db, line["purchase_order_id"])


# ---------------------------------------------------------------------------
# Build-level BOM overrides (CPQ) — resolves a Build's EFFECTIVE BOM, i.e.
# the Kit's normal kit_parts list with any build_bom_overrides substitutions
# applied. Stock reservation/consumption and true-COGS calculations both
# read this instead of raw kit_parts, so a per-client component swap on one
# physical unit actually reserves/consumes the right stock.
# ---------------------------------------------------------------------------

def build_effective_bom(db, build_id):
    build = db.execute("SELECT kit_id FROM builds WHERE id = ?", (build_id,)).fetchone()
    if build is None:
        return []
    base_lines = db.execute(
        "SELECT id, part_id, component_kit_id, quantity_required FROM kit_parts WHERE kit_id = ?",
        (build["kit_id"],),
    ).fetchall()
    overrides = db.execute(
        "SELECT * FROM build_bom_overrides WHERE build_id = ?", (build_id,)
    ).fetchall()
    overridden_kit_part_ids = {o["original_kit_part_id"] for o in overrides if o["original_kit_part_id"]}
    effective = []
    for line in base_lines:
        if line["id"] in overridden_kit_part_ids:
            continue
        effective.append({
            "part_id": line["part_id"],
            "component_kit_id": line["component_kit_id"],
            "quantity_required": line["quantity_required"],
        })
    for o in overrides:
        effective.append({
            "part_id": o["substitute_part_id"],
            "component_kit_id": o["substitute_component_kit_id"],
            "quantity_required": o["quantity_required"],
        })
    return effective


# ---------------------------------------------------------------------------
# Engineering Change Orders — every approved BOM edit gets a numbered ECO
# with a full JSON snapshot of the BOM as it stood at that moment, so past
# revisions are always reconstructable even though kit_parts itself only
# ever holds the CURRENT BOM.
# ---------------------------------------------------------------------------

def snapshot_kit_bom(db, kit_id):
    lines = db.execute(
        "SELECT kp.part_id, kp.component_kit_id, kp.quantity_required, "
        "p.part_name AS part_name, p.part_number AS part_number, k.kit_name AS component_kit_name "
        "FROM kit_parts kp LEFT JOIN parts p ON p.id = kp.part_id "
        "LEFT JOIN kits k ON k.id = kp.component_kit_id WHERE kp.kit_id = ?",
        (kit_id,),
    ).fetchall()
    return json.dumps([dict(l) for l in lines])


def record_kit_eco(db, kit_id, description, status="Approved"):
    """Call right after a BOM edit — snapshots the kit's now-current BOM
    and files it as a new numbered ECO documenting that change."""
    snapshot = snapshot_kit_bom(db, kit_id)
    eco_number = generate_number("ECO")
    db.execute(
        "INSERT INTO kit_ecos (kit_id, eco_number, description, bom_snapshot, status) VALUES (?,?,?,?,?)",
        (kit_id, eco_number, description, snapshot, status),
    )
    db.commit()
    return eco_number


# ---------------------------------------------------------------------------
# RMAs — teardown a returned Build's components back into inventory
# ---------------------------------------------------------------------------

def process_rma_teardown(db, rma_id):
    """Applies every teardown line's disposition. Restock adds the
    quantity back onto parts.quantity_on_hand; a Restock line against a
    component_kit_id (a sub-assembly) is recorded but moves no stock
    number, since sub-assemblies don't carry their own stock count in this
    schema. Scrap moves nothing. Marks the RMA 'Teardown Complete'."""
    lines = db.execute("SELECT * FROM rma_teardown_lines WHERE rma_id = ?", (rma_id,)).fetchall()
    for line in lines:
        if line["disposition"] == "Restock" and line["part_id"] is not None:
            db.execute(
                "UPDATE parts SET quantity_on_hand = quantity_on_hand + ? WHERE id = ?",
                (line["quantity"], line["part_id"]),
            )
    db.execute("UPDATE rmas SET status = 'Teardown Complete' WHERE id = ?", (rma_id,))
    db.commit()


# ---------------------------------------------------------------------------
# Routings & Operations — real labor time -> true COGS
# ---------------------------------------------------------------------------

def build_labor_cost(db, build_id):
    rate_row = db.execute("SELECT labor_rate_per_hour FROM company_settings WHERE id = 1").fetchone()
    rate = (rate_row["labor_rate_per_hour"] if rate_row else 0) or 0
    minutes_row = db.execute(
        "SELECT COALESCE(SUM(actual_minutes), 0) AS m FROM build_step_logs WHERE build_id = ?",
        (build_id,),
    ).fetchone()
    total_minutes = minutes_row["m"] or 0
    return round((total_minutes / 60.0) * rate, 2)


def build_true_cogs(db, build_id):
    """Part cost, from the Build's effective (override-aware) BOM, plus
    labor cost from logged routing-step time — the fullest COGS figure the
    app can produce for one physical unit."""
    part_cost = 0.0
    for line in build_effective_bom(db, build_id):
        qty = line["quantity_required"] or 0
        if line["part_id"] is not None:
            p = db.execute("SELECT unit_cost FROM parts WHERE id = ?", (line["part_id"],)).fetchone()
            part_cost += qty * (p["unit_cost"] if p else 0)
        elif line["component_kit_id"] is not None:
            part_cost += qty * kit_total_part_cost(db, line["component_kit_id"])
    return round(part_cost + build_labor_cost(db, build_id), 2)


# ---------------------------------------------------------------------------
# Batch Production Runs — Gridfinity-aware pick list.
# A location can record which named baseplate it's a cell of, and its
# (grid_x, grid_y) coordinate within that baseplate. Parts stored in a
# Gridfinity bin get walked in serpentine order (row-major, alternating
# direction each row) — the shortest real walk of a baseplate's cells — and
# grouped baseplate by baseplate. Parts in a location with no grid
# coordinates (a shelf, a workstation) fall back to a plain
# location-name/part-name grouping, listed after the gridded baseplates.
# ---------------------------------------------------------------------------

def batch_pick_list(db, batch_id):
    batch = db.execute("SELECT * FROM batch_runs WHERE id = ?", (batch_id,)).fetchone()
    if batch is None:
        return []
    needed = {}

    def _walk(kit_id, multiplier):
        lines = db.execute(
            "SELECT part_id, component_kit_id, quantity_required FROM kit_parts WHERE kit_id = ?",
            (kit_id,),
        ).fetchall()
        for line in lines:
            qty = (line["quantity_required"] or 0) * multiplier
            if line["part_id"] is not None:
                needed[line["part_id"]] = needed.get(line["part_id"], 0) + qty
            elif line["component_kit_id"] is not None:
                _walk(line["component_kit_id"], qty)

    _walk(batch["kit_id"], batch["quantity"])
    rows = []
    for part_id, qty in needed.items():
        p = db.execute(
            "SELECT p.*, l.name AS bin_location_name, l.baseplate_name, l.grid_x, l.grid_y FROM parts p "
            "LEFT JOIN locations l ON l.id = p.bin_location_id WHERE p.id = ?",
            (part_id,),
        ).fetchone()
        if p:
            rows.append({
                "part_id": part_id,
                "part_name": p["part_name"],
                "part_number": p["part_number"],
                "bin_location_name": p["bin_location_name"] or "Unassigned",
                "baseplate_name": p["baseplate_name"],
                "grid_x": p["grid_x"],
                "grid_y": p["grid_y"],
                "quantity_needed": qty,
                "quantity_on_hand": p["quantity_on_hand"],
            })

    def _sort_key(r):
        if r["baseplate_name"]:
            x, y = r["grid_x"] or 0, r["grid_y"] or 0
            # Serpentine walk: even rows left-to-right, odd rows right-to-left.
            effective_x = x if (y % 2 == 0) else -x
            return (0, r["baseplate_name"], y, effective_x)
        return (1, r["bin_location_name"], r["part_name"])

    rows.sort(key=_sort_key)
    for i, r in enumerate(rows, start=1):
        r["pick_order"] = i
    return rows


def batch_pick_list_grid_maps(db, rows):
    """Builds a visual per-baseplate grid map for the pick list: every
    physical cell that exists in each referenced baseplate (queried fresh
    from locations), with the cells this batch needs marked with their part
    and walk order, and every other cell in the baseplate shown blank so the
    picker can see where those needed bins actually sit."""
    baseplate_names = sorted({r["baseplate_name"] for r in rows if r["baseplate_name"]})
    if not baseplate_names:
        return []
    maps = []
    for name in baseplate_names:
        cells = db.execute(
            "SELECT grid_x, grid_y FROM locations WHERE baseplate_name = ?", (name,)
        ).fetchall()
        max_x = max((c["grid_x"] or 0) for c in cells) if cells else 0
        max_y = max((c["grid_y"] or 0) for c in cells) if cells else 0
        needed_by_xy = {(r["grid_x"] or 0, r["grid_y"] or 0): r for r in rows if r["baseplate_name"] == name}
        grid_rows = []
        for y in range(0, max_y + 1):
            row_cells = []
            for x in range(0, max_x + 1):
                match = needed_by_xy.get((x, y))
                if match:
                    row_cells.append({
                        "x": x, "y": y, "needed": True,
                        "part_name": match["part_name"], "part_number": match["part_number"],
                        "quantity_needed": match["quantity_needed"], "pick_order": match["pick_order"],
                    })
                else:
                    row_cells.append({"x": x, "y": y, "needed": False})
            grid_rows.append(row_cells)
        maps.append({"baseplate_name": name, "grid_rows": grid_rows})
    return maps


# ---------------------------------------------------------------------------
# Auto-Procurement Queue — reorder-threshold scan, supplier
# blackout-calendar aware
# ---------------------------------------------------------------------------

def procurement_suggestions(db):
    today = date.today().isoformat()
    parts = db.execute(
        "SELECT * FROM parts WHERE quantity_on_hand - quantity_reserved <= reorder_threshold "
        "AND preferred_supplier_id IS NOT NULL ORDER BY preferred_supplier_id"
    ).fetchall()
    blackout_supplier_ids = {
        row["supplier_id"] for row in db.execute(
            "SELECT supplier_id FROM supplier_blackout_periods WHERE ? BETWEEN start_date AND end_date",
            (today,),
        ).fetchall()
    }
    by_supplier = {}
    for p in parts:
        sid = p["preferred_supplier_id"]
        if sid not in by_supplier:
            supplier = db.execute("SELECT supplier_name FROM suppliers WHERE id = ?", (sid,)).fetchone()
            by_supplier[sid] = {
                "supplier_id": sid,
                "supplier_name": supplier["supplier_name"] if supplier else "Unknown",
                "in_blackout": sid in blackout_supplier_ids,
                "parts": [],
            }
        available = part_available_qty(p["quantity_on_hand"], p["quantity_reserved"])
        suggested_qty = max((p["reorder_threshold"] or 0) * 2 - available, 1)
        by_supplier[sid]["parts"].append({
            "part_id": p["id"],
            "part_name": p["part_name"],
            "part_number": p["part_number"],
            "available_qty": available,
            "reorder_threshold": p["reorder_threshold"],
            "suggested_qty": suggested_qty,
            "unit_cost": p["unit_cost"],
        })
    return list(by_supplier.values())


# ---------------------------------------------------------------------------
# Landed Cost distribution — spreads a PO's actual freight/duty across its
# received lines and folds it into each part's moving-average unit_cost.
# ---------------------------------------------------------------------------

def apply_landed_cost(db, po_id):
    """Weighted moving-average costing: stock already on the shelf keeps
    its old cost basis, only the newly-received units carry the allocated
    landed extra — not a last-cost overwrite of the whole part."""
    po = db.execute("SELECT * FROM purchase_orders WHERE id = ?", (po_id,)).fetchone()
    if po is None or po["landed_cost_applied"]:
        return False
    lines = db.execute(
        "SELECT * FROM purchase_order_lines WHERE purchase_order_id = ? AND quantity_received > 0",
        (po_id,),
    ).fetchall()
    if not lines:
        return False
    total_value = sum((l["unit_cost"] or 0) * l["quantity_received"] for l in lines)
    extra_total = (po["actual_freight_paid"] or 0) + (po["actual_duty_paid"] or 0)
    if total_value <= 0 or extra_total <= 0:
        db.execute("UPDATE purchase_orders SET landed_cost_applied = 1 WHERE id = ?", (po_id,))
        db.commit()
        return False
    for line in lines:
        line_value = (line["unit_cost"] or 0) * line["quantity_received"]
        share = (line_value / total_value) * extra_total
        landed_unit_cost = line["unit_cost"] + (share / line["quantity_received"])
        part = db.execute("SELECT * FROM parts WHERE id = ?", (line["part_id"],)).fetchone()
        if part is None:
            continue
        prior_qty = max((part["quantity_on_hand"] or 0) - line["quantity_received"], 0)
        prior_cost_basis = prior_qty * (part["unit_cost"] or 0)
        new_cost_basis = prior_cost_basis + (landed_unit_cost * line["quantity_received"])
        new_total_qty = prior_qty + line["quantity_received"]
        new_avg_cost = round(new_cost_basis / new_total_qty, 4) if new_total_qty > 0 else round(landed_unit_cost, 4)
        db.execute("UPDATE parts SET unit_cost = ? WHERE id = ?", (new_avg_cost, line["part_id"]))
    db.execute("UPDATE purchase_orders SET landed_cost_applied = 1 WHERE id = ?", (po_id,))
    db.commit()
    return True


# ---------------------------------------------------------------------------
# Supplier Reliability — average days late per supplier
# ---------------------------------------------------------------------------

def supplier_reliability_stats(db):
    pos = db.execute(
        "SELECT supplier_id, expected_delivery_date, received_date FROM purchase_orders "
        "WHERE expected_delivery_date IS NOT NULL AND received_date IS NOT NULL"
    ).fetchall()
    by_supplier = {}
    for po in pos:
        try:
            exp = date.fromisoformat(po["expected_delivery_date"][:10])
            rec = date.fromisoformat(po["received_date"][:10])
        except (ValueError, TypeError):
            continue
        by_supplier.setdefault(po["supplier_id"], []).append((rec - exp).days)
    results = []
    for sid, days_list in by_supplier.items():
        supplier = db.execute("SELECT supplier_name FROM suppliers WHERE id = ?", (sid,)).fetchone()
        results.append({
            "supplier_id": sid,
            "supplier_name": supplier["supplier_name"] if supplier else "Unknown",
            "avg_days_late": round(sum(days_list) / len(days_list), 1),
            "po_count": len(days_list),
        })
    results.sort(key=lambda r: -r["avg_days_late"])
    return results


# ---------------------------------------------------------------------------
# BAS generator (GST collected vs. GST paid, both sourced from real ledgers)
# and CapEx break-even calculator
# ---------------------------------------------------------------------------

def generate_bas_report(db, period_start, period_end):
    """gst_collected comes from paid/sent invoice lines in the period.
    gst_paid_estimated is now summed straight from the expenses ledger —
    itemized PO-receipt lines (auto-filed by receive_po_line) plus whatever
    other business expenses (rent, software, freight, tools, etc.) have been
    entered for the period. It's still called an "estimate" because it can
    only be as complete as the expenses ledger is kept — anything not
    entered there won't show up here. Check with your bookkeeper/accountant
    before lodging."""
    invoices = db.execute(
        "SELECT id FROM invoices WHERE invoice_date >= ? AND invoice_date <= ? AND status != 'Cancelled'",
        (period_start, period_end + " 23:59:59"),
    ).fetchall()
    gst_collected = 0.0
    for inv in invoices:
        totals = document_totals(db, "invoices", "id", inv["id"])
        gst_collected += totals["gst_amount"]
    gst_collected = round(gst_collected, 2)

    expenses_row = db.execute(
        "SELECT COALESCE(SUM(gst_amount), 0) AS v FROM expenses "
        "WHERE expense_date >= ? AND expense_date <= ?",
        (period_start, period_end + " 23:59:59"),
    ).fetchone()
    gst_paid_estimated = round(expenses_row["v"] or 0, 2)
    net_gst_payable = round(gst_collected - gst_paid_estimated, 2)
    db.execute(
        "INSERT INTO bas_reports (period_start, period_end, gst_collected, gst_paid_estimated, net_gst_payable) "
        "VALUES (?,?,?,?,?)",
        (period_start, period_end, gst_collected, gst_paid_estimated, net_gst_payable),
    )
    db.commit()
    return {
        "period_start": period_start,
        "period_end": period_end,
        "gst_collected": gst_collected,
        "gst_paid_estimated": gst_paid_estimated,
        "net_gst_payable": net_gst_payable,
    }


def capex_breakeven_months(equipment_cost, monthly_revenue_increase, monthly_cost_increase):
    net_monthly = (monthly_revenue_increase or 0) - (monthly_cost_increase or 0)
    if net_monthly <= 0:
        return None  # never breaks even at this rate
    return round((equipment_cost or 0) / net_monthly, 1)

