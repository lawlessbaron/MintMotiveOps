"""Full backup and restore from the command line — the same files as
Administration > Backup & Move, for when the browser isn't convenient
(very large uploads folders, or a server you can only reach by shell).

    python3 scripts/backup.py export mintmotive-backup.zip
    python3 scripts/backup.py restore mintmotive-backup.zip --yes

Uses the same DATABASE_URL / SQLite file and uploads folder as the app.
Restore replaces all data, all or nothing.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import create_app  # noqa: E402
from app.backup import BackupError, export_backup, restore_backup  # noqa: E402
from app.db import get_db  # noqa: E402


def main(argv):
    if len(argv) < 3 or argv[1] not in ("export", "restore"):
        print(__doc__)
        return 2
    action, path = argv[1], argv[2]
    app = create_app()
    uploads = os.path.join(app.static_folder, "uploads")
    backend = app.config.get("DB_BACKEND")
    with app.app_context():
        db = get_db()
        if action == "export":
            with open(path, "wb") as out:
                m = export_backup(db, backend, uploads, app.config["SECRET_KEY"], out)
            print(f"Wrote {path}: {sum(m['tables'].values())} records in {len(m['tables'])} tables, {m['files']} files.")
            return 0
        if "--yes" not in argv:
            print("Restoring replaces ALL data on this server. Re-run with --yes to go ahead.")
            return 1
        try:
            with open(path, "rb") as f:
                r = restore_backup(db, backend, f, uploads)
        except BackupError as e:
            print(f"Restore failed, nothing changed: {e}")
            return 1
        print(f"Restored {sum(r['tables'].values())} records and {r['files']} files from the backup made {r['manifest'].get('created_at')}.")
        return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
