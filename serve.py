"""Production entry point for Windows servers (Azure VM, rented VPS, or any
other Windows Server box) — uses Waitress, a pure-Python WSGI server that
runs natively on Windows (gunicorn does not: it depends on os.fork/fcntl,
which are Unix-only).

On Linux hosts, prefer gunicorn instead:
    gunicorn -w 4 -b 0.0.0.0:8000 run:app

Usage on Windows (from inside the activated venv):
    python serve.py

Reads the same PORT env var as run.py (defaults to 8000 here, since 5000
is commonly reserved on Windows by an OS-level service). Always runs with
debug/reloader off — this is the production path.
"""
import os
from waitress import serve

from app import create_app

app = create_app()

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8000))
    threads = int(os.environ.get("WEB_THREADS", 4))
    print(f"MintMotive Ops serving on http://0.0.0.0:{port} (Waitress, {threads} threads)")
    serve(app, host="0.0.0.0", port=port, threads=threads)
