"""Local/dev entry point. In production, run with a real WSGI server instead
(gunicorn, waitress, etc. — see DEPLOYMENT.md)."""
import os
from app import create_app

app = create_app()

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=os.environ.get("FLASK_DEBUG", "0") == "1")
