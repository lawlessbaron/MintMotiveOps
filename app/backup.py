"""Full backup and restore: move a whole MintMotive Ops install from one
server to another (Windows box, VPS, Render, Railway...) through the browser,
with no pg_dump, shell access or git needed on either end.

A backup is a single .zip:

    manifest.json          what this is, when, from which backend, row counts
    tables/<table>.json    {"columns": [...], "rows": [[...], ...]}
    uploads/...            every file under app/static/uploads (images, documents)

It is backend-neutral: a backup taken on SQLite restores into Postgres and the
other way round, because every column in both schemas is INTEGER, REAL or
TEXT, and values are coerced to the target column's type on the way in.

Restoring REPLACES the data in every table the backup contains, inside one
transaction: if anything fails, nothing changes. Tables that exist on the
target but not in the backup (newer features) are left alone, and columns
the backup doesn't have take their defaults.

Everything here talks to the raw database connection underneath get_db()'s
wrapper on purpose: the wrapper audit-logs every UPDATE/DELETE, and a restore
would otherwise write thousands of audit rows about itself (into a table it
is in the middle of replacing).
"""
import base64
import hashlib
import hmac
import io
import json
import os
import shutil
import tempfile
import zipfile
from datetime import date, datetime, timezone
from decimal import Decimal

APP_NAME = "MintMotive Ops"
FORMAT = 1

# Short-lived security records that should never travel between servers.
SKIP_TABLES = {"sqlite_sequence", "password_reset_tokens", "login_attempts"}


class BackupError(Exception):
    """A problem worth showing to the person restoring, in plain words."""


# ---------------------------------------------------------------------------
# Raw connection helpers (both backends)

def _raw(db):
    return getattr(db, "_conn", db)


def _q(raw, backend, sql, params=()):
    if backend == "postgres":
        cur = raw.cursor()
        cur.execute(sql.replace("?", "%s"), params)
        return cur
    return raw.execute(sql, params)


def _ident(name):
    if not name.replace("_", "").isalnum():
        raise BackupError(f"Unexpected table or column name: {name!r}")
    return '"' + name + '"'


def list_tables(raw, backend):
    if backend == "postgres":
        rows = _q(raw, backend, "SELECT table_name FROM information_schema.tables "
                                "WHERE table_schema = 'public' AND table_type = 'BASE TABLE'").fetchall()
        names = [r["table_name"] if isinstance(r, dict) else r[0] for r in rows]
    else:
        rows = _q(raw, backend, "SELECT name FROM sqlite_master WHERE type = 'table'").fetchall()
        names = [r[0] for r in rows]
    return sorted(n for n in names if n not in SKIP_TABLES and not n.startswith("sqlite_"))


def _all_tables(raw, backend):
    if backend == "postgres":
        rows = _q(raw, backend, "SELECT table_name FROM information_schema.tables WHERE table_schema = 'public'").fetchall()
        return [r["table_name"] if isinstance(r, dict) else r[0] for r in rows]
    return [r[0] for r in _q(raw, backend, "SELECT name FROM sqlite_master WHERE type = 'table'").fetchall()]


def table_columns(raw, backend, table):
    """[(name, kind)] where kind is 'integer', 'real' or 'text'."""
    def kind(t):
        t = (t or "").lower()
        if "int" in t or t == "serial":
            return "integer"
        if any(k in t for k in ("real", "double", "numeric", "float", "decimal")):
            return "real"
        return "text"
    if backend == "postgres":
        rows = _q(raw, backend, "SELECT column_name, data_type FROM information_schema.columns "
                                "WHERE table_schema = 'public' AND table_name = ? ORDER BY ordinal_position", (table,)).fetchall()
        return [(r["column_name"], kind(r["data_type"])) for r in rows]
    rows = _q(raw, backend, f"PRAGMA table_info({_ident(table)})").fetchall()
    return [(r[1], kind(r[2])) for r in rows]


def foreign_keys(raw, backend, tables):
    """{table: set(tables it references)}, within `tables`."""
    deps = {t: set() for t in tables}
    if backend == "postgres":
        rows = _q(raw, backend,
                  "SELECT tc.table_name AS child, ccu.table_name AS parent "
                  "FROM information_schema.table_constraints tc "
                  "JOIN information_schema.constraint_column_usage ccu "
                  "  ON tc.constraint_name = ccu.constraint_name AND tc.table_schema = ccu.table_schema "
                  "WHERE tc.constraint_type = 'FOREIGN KEY' AND tc.table_schema = 'public'").fetchall()
        for r in rows:
            child, parent = r["child"], r["parent"]
            if child in deps and parent in deps and parent != child:
                deps[child].add(parent)
    else:
        for t in tables:
            for r in _q(raw, backend, f"PRAGMA foreign_key_list({_ident(t)})").fetchall():
                if r[2] in deps and r[2] != t:
                    deps[t].add(r[2])
    return deps


def insert_order(tables, deps):
    """Parents before children. Anything left in a cycle goes last, in name
    order (foreign-key checks are switched off during a restore where the
    database allows it, so a cycle still restores)."""
    order, done = [], set()
    remaining = sorted(tables)
    while remaining:
        ready = [t for t in remaining if deps.get(t, set()) <= done]
        if not ready:
            order.extend(remaining)
            break
        for t in ready:
            order.append(t)
            done.add(t)
        remaining = [t for t in remaining if t not in done]
    return order


def key_check(secret_key):
    """A short fingerprint of SECRET_KEY (never the key itself), so a restore
    can warn when the saved Stripe/SMTP credentials were encrypted with a
    different key and will need re-entering."""
    return hmac.new((secret_key or "").encode(), b"mintmotive-ops-backup", hashlib.sha256).hexdigest()[:16]


def _enc(v):
    if isinstance(v, (bytes, bytearray, memoryview)):
        return {"$b64": base64.b64encode(bytes(v)).decode()}
    if isinstance(v, (datetime, date)):
        return v.isoformat(sep=" ") if isinstance(v, datetime) else v.isoformat()
    if isinstance(v, Decimal):
        return float(v)
    return v


def _dec(v, kind):
    if isinstance(v, dict) and "$b64" in v:
        return base64.b64decode(v["$b64"])
    if v is None:
        return None
    # SQLite lets any value into any column; Postgres doesn't. Coerce to the
    # target column's type so a stray '' or '12' in an INTEGER column restores.
    if kind == "integer":
        if isinstance(v, bool):
            return int(v)
        if isinstance(v, (int, float)):
            return int(v)
        s = str(v).strip()
        if s == "":
            return None
        try:
            return int(float(s))
        except ValueError:
            return None
    if kind == "real":
        if isinstance(v, (int, float)):
            return float(v)
        s = str(v).strip()
        if s == "":
            return None
        try:
            return float(s)
        except ValueError:
            return None
    return v if isinstance(v, str) else str(v)


# ---------------------------------------------------------------------------
# Export

def export_backup(db, backend, uploads_dir, secret_key, out):
    """Writes the backup zip to the binary file object `out`. Returns the manifest."""
    raw = _raw(db)
    tables = list_tables(raw, backend)
    counts = {}
    with zipfile.ZipFile(out, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for t in tables:
            cols = [c for c, _ in table_columns(raw, backend, t)]
            if not cols:
                continue
            order = " ORDER BY id" if "id" in cols else ""
            cur = _q(raw, backend, f"SELECT {', '.join(_ident(c) for c in cols)} FROM {_ident(t)}{order}")
            rows = []
            for r in cur.fetchall():
                rows.append([_enc(r[c] if isinstance(r, dict) else r[i]) for i, c in enumerate(cols)])
            counts[t] = len(rows)
            zf.writestr(f"tables/{t}.json", json.dumps({"columns": cols, "rows": rows}, separators=(",", ":")))
        files = 0
        if uploads_dir and os.path.isdir(uploads_dir):
            for root, _dirs, names in os.walk(uploads_dir):
                for name in names:
                    if name == ".gitkeep":
                        continue
                    full = os.path.join(root, name)
                    rel = os.path.relpath(full, uploads_dir).replace(os.sep, "/")
                    zf.write(full, f"uploads/{rel}")
                    files += 1
        manifest = {
            "app": APP_NAME, "format": FORMAT,
            "created_at": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC"),
            "backend": backend, "tables": counts, "files": files,
            "key_check": key_check(secret_key),
        }
        zf.writestr("manifest.json", json.dumps(manifest, indent=2))
    return manifest


# ---------------------------------------------------------------------------
# Restore

def read_manifest(zf):
    try:
        manifest = json.loads(zf.read("manifest.json"))
    except KeyError:
        raise BackupError("This file isn't a MintMotive Ops backup (it has no manifest).")
    except ValueError:
        raise BackupError("The backup's manifest is damaged.")
    if manifest.get("app") != APP_NAME:
        raise BackupError("This file isn't a MintMotive Ops backup.")
    if manifest.get("format") != FORMAT:
        raise BackupError(f"This backup uses format {manifest.get('format')}, which this version can't read. Update this server first.")
    return manifest


def open_backup(fileobj):
    try:
        zf = zipfile.ZipFile(fileobj)
    except zipfile.BadZipFile:
        raise BackupError("That file isn't a backup zip, or it was cut short while uploading.")
    return zf, read_manifest(zf)


def _safe_target(uploads_dir, rel):
    rel = rel.replace("\\", "/")
    if rel.startswith("/") or any(part in ("..", "") for part in rel.split("/")) or ":" in rel.split("/")[0]:
        return None
    target = os.path.realpath(os.path.join(uploads_dir, *rel.split("/")))
    base = os.path.realpath(uploads_dir)
    return target if target.startswith(base + os.sep) else None


def restore_backup(db, backend, fileobj, uploads_dir):
    """Replaces this install's data with the backup's. Returns a summary dict.
    All-or-nothing for the database; uploads are copied in after it commits."""
    zf, manifest = open_backup(fileobj)
    raw = _raw(db)
    target_tables = set(list_tables(raw, backend))
    backup_tables = [t for t in manifest.get("tables", {}) if t in target_tables and t not in SKIP_TABLES]
    if "users" not in backup_tables:
        raise BackupError("This backup has no user accounts in it, so restoring it would lock everyone out. Nothing was changed.")
    order = insert_order(backup_tables, foreign_keys(raw, backend, backup_tables))
    restored, skipped_columns = {}, {}

    try:
        if backend == "postgres":
            raw.commit()
            cur = raw.cursor()
            # Switch foreign-key triggers off for this transaction where the
            # database user is allowed to (Railway's is); otherwise the
            # parents-first order above still gets everything in.
            cur.execute("SAVEPOINT fk_off")
            try:
                cur.execute("SET LOCAL session_replication_role = replica")
            except Exception:
                cur.execute("ROLLBACK TO SAVEPOINT fk_off")
        else:
            raw.commit()
            raw.execute("PRAGMA foreign_keys = OFF")

        for t in reversed(order):
            _q(raw, backend, f"DELETE FROM {_ident(t)}")
        # Reset codes and login attempts belong to the old user ids: drop them.
        existing = set(_all_tables(raw, backend))
        for t in ("password_reset_tokens", "login_attempts"):
            if t in existing:
                _q(raw, backend, f"DELETE FROM {_ident(t)}")

        for t in order:
            data = json.loads(zf.read(f"tables/{t}.json"))
            target_cols = dict(table_columns(raw, backend, t))
            cols = [c for c in data["columns"] if c in target_cols]
            missing = [c for c in data["columns"] if c not in target_cols]
            if missing:
                skipped_columns[t] = missing
            idx = [data["columns"].index(c) for c in cols]
            rows = [tuple(_dec(r[i], target_cols[c]) for i, c in zip(idx, cols)) for r in data["rows"]]
            if rows and cols:
                sql = f"INSERT INTO {_ident(t)} ({', '.join(_ident(c) for c in cols)}) VALUES ({', '.join('?' for _ in cols)})"
                if backend == "postgres":
                    from psycopg2.extras import execute_batch
                    execute_batch(raw.cursor(), sql.replace("?", "%s"), rows, page_size=500)
                else:
                    raw.executemany(sql, rows)
            restored[t] = len(rows)

        if backend == "postgres":
            # Point each id sequence past the restored rows so new records don't collide.
            for t in order:
                cur = raw.cursor()
                cur.execute("SELECT pg_get_serial_sequence(%s, 'id') AS seq", (t,))
                row = cur.fetchone()
                seq = row["seq"] if isinstance(row, dict) else (row[0] if row else None)
                if seq:
                    cur.execute(f"SELECT setval(%s, COALESCE((SELECT MAX(id) FROM {_ident(t)}), 0) + 1, false)", (seq,))
        raw.commit()
    except BackupError:
        raw.rollback()
        raise
    except Exception as e:
        raw.rollback()
        raise BackupError(f"The restore failed and nothing was changed: {e}") from e
    finally:
        if backend != "postgres":
            raw.execute("PRAGMA foreign_keys = ON")

    files = 0
    if uploads_dir:
        os.makedirs(uploads_dir, exist_ok=True)
        for info in zf.infolist():
            if info.is_dir() or not info.filename.startswith("uploads/"):
                continue
            target = _safe_target(uploads_dir, info.filename[len("uploads/"):])
            if not target:
                continue
            os.makedirs(os.path.dirname(target), exist_ok=True)
            with zf.open(info) as src, open(target, "wb") as dst:
                shutil.copyfileobj(src, dst)
            files += 1

    return {"manifest": manifest, "tables": restored, "files": files, "skipped_columns": skipped_columns}


def backup_to_tempfile(db, backend, uploads_dir, secret_key):
    """Builds the zip in a temporary file (backups with many photos can be
    large). Returns (open file positioned at 0, manifest)."""
    tmp = tempfile.TemporaryFile()
    manifest = export_backup(db, backend, uploads_dir, secret_key, tmp)
    tmp.seek(0)
    return tmp, manifest


def backup_filename(company_name=None):
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M")
    return f"mintmotive-ops-backup-{stamp}.zip"


__all__ = ["BackupError", "export_backup", "restore_backup", "open_backup", "backup_to_tempfile", "backup_filename", "key_check"]
