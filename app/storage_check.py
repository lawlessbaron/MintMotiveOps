"""Is every piece of data saved somewhere that survives a redeploy?

Ops keeps its records in the database and its uploaded images and documents
in app/static/uploads. On Railway a container's own disk is wiped on every
deploy, so:

  - the database must be Postgres (DATABASE_URL, the Railway Postgres
    service), or a SQLite file on a volume;
  - the uploads folder must be on a volume;
  - SECRET_KEY must be set, because the Stripe and SMTP details saved in
    Integrations are encrypted with it (and it signs logins).

`storage_status()` works that out from plain values so it can be tested
without Flask; `check_on_boot()` refuses to start on Railway when data would
be lost, so a bad deploy fails its health check and Railway keeps the old
one running instead of quietly throwing records away.
"""
import os

DEFAULT_SECRET = "dev-secret-change-me"


def _inside(path, mount):
    path, mount = os.path.realpath(path), os.path.realpath(mount)
    return path == mount or path.startswith(mount.rstrip(os.sep) + os.sep)


def storage_status(env, backend, sqlite_path, uploads_dir):
    """Returns {'host', 'ok', 'problems': [...], 'database', 'uploads', 'secret'}."""
    railway = bool(env.get("RAILWAY_ENVIRONMENT_ID") or env.get("RAILWAY_PROJECT_ID") or env.get("RAILWAY_SERVICE_ID"))
    volume = env.get("RAILWAY_VOLUME_MOUNT_PATH") or ""
    secret = env.get("SECRET_KEY") or ""
    out = {"host": "railway" if railway else "other", "volume": volume or None, "problems": []}

    if backend == "postgres":
        out["database"] = "PostgreSQL (DATABASE_URL)"
        db_ok = True
    else:
        out["database"] = f"SQLite file {sqlite_path}"
        db_ok = (not railway) or bool(volume and _inside(sqlite_path, volume))
        if not db_ok:
            out["problems"].append(
                "The database is a SQLite file inside the container, so every record is wiped at the next deploy. "
                "Add a PostgreSQL service in Railway and set DATABASE_URL=${{Postgres.DATABASE_URL}} on this service."
            )

    out["uploads"] = uploads_dir
    uploads_ok = (not railway) or bool(volume and _inside(uploads_dir, volume))
    if not uploads_ok:
        out["problems"].append(
            f"Uploaded images and documents are saved in {uploads_dir}, which is not on a volume. "
            f"In Railway, right-click the service → Attach volume, and set its mount path to {uploads_dir}."
            if not volume else
            f"The volume is mounted at {volume}, but uploads are saved in {uploads_dir}. Change the volume's mount path to {uploads_dir}."
        )

    secret_ok = bool(secret) and secret != DEFAULT_SECRET
    out["secret"] = "set" if secret_ok else "missing"
    if railway and not secret_ok:
        out["problems"].append(
            "SECRET_KEY is not set. Add a long random SECRET_KEY variable on this service (and keep it: the saved Stripe "
            "and SMTP details are encrypted with it, and changing it signs everyone out)."
        )

    out["database_ok"], out["uploads_ok"], out["secret_ok"] = db_ok, uploads_ok, secret_ok
    out["ok"] = not out["problems"]
    return out


def check_on_boot(app):
    """Log the storage status and refuse to start on Railway if data would be lost.

    ALLOW_EPHEMERAL_STORAGE=1 skips the refusal (for a throwaway preview)."""
    env = os.environ
    status = storage_status(
        env,
        app.config.get("DB_BACKEND"),
        app.config.get("DATABASE"),
        os.path.join(app.static_folder, "uploads"),
    )
    app.config["STORAGE_STATUS"] = status
    for p in status["problems"]:
        app.logger.error("STORAGE: %s", p)
    if status["host"] == "railway" and status["problems"] and env.get("ALLOW_EPHEMERAL_STORAGE") != "1":
        raise RuntimeError(
            "MintMotive Ops will not start on Railway until its data is saved permanently: "
            + " ".join(status["problems"])
            + " (Set ALLOW_EPHEMERAL_STORAGE=1 only for a throwaway preview.)"
        )
    return status
