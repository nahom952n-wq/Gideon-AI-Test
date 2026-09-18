"""
ScholarMind AI — Application Entry Point.

Run with: python run.py
"""

import os
from app import create_app

app = create_app()

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    debug = os.environ.get("FLASK_ENV", "development") == "development"
    # Bind to loopback by default because this entry point is intended for
    # local use. Set HOST explicitly when a network-accessible server is needed.
    host = os.environ.get("HOST", "127.0.0.1")
    app.run(host=host, port=port, debug=debug, use_reloader=False)
