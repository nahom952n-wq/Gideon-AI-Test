"""Windows desktop shell for the local ScholarMind AI companion."""

from __future__ import annotations

import os
import socket
import threading
import time
import webbrowser

import pystray
import webview
from PIL import Image, ImageDraw
from werkzeug.serving import BaseWSGIServer, make_server

HOST = os.environ.get("HOST", "127.0.0.1")
PORT = int(os.environ.get("PORT", "5000"))
TELEGRAM_URL = os.environ.get("TELEGRAM_WEB_URL", "http://localhost:1234")
WINDOW_TITLE = "ScholarMind AI"


def _wait_for_server(timeout: float = 15.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
            probe.settimeout(0.25)
            try:
                probe.connect((HOST, PORT))
                return
            except OSError:
                time.sleep(0.05)
    raise RuntimeError(f"ScholarMind AI server did not start on {HOST}:{PORT}")


def _create_icon() -> Image.Image:
    image = Image.new("RGBA", (64, 64), "#172033")
    draw = ImageDraw.Draw(image)
    draw.rounded_rectangle((8, 8, 56, 56), radius=12, fill="#4f8cff")
    draw.text((20, 18), "S", fill="white")
    return image


def main() -> None:
    os.environ.setdefault("FLASK_ENV", "production")
    server_ready = threading.Event()
    server_holder: dict[str, BaseWSGIServer] = {}
    app_holder: dict[str, object] = {}
    startup_error: list[BaseException] = []

    def run_server() -> None:
        try:
            from app import create_app
            app = create_app("production")
            app_holder["app"] = app
            server = make_server(HOST, PORT, app)
            server_holder["server"] = server
            server_ready.set()
            server.serve_forever()
        except BaseException as exc:
            startup_error.append(exc)
            server_ready.set()

    server_thread = threading.Thread(target=run_server, daemon=True, name="scholarmind-server")
    server_thread.start()
    server_ready.wait()
    if startup_error:
        raise startup_error[0]
    _wait_for_server()

    window = webview.create_window(
        WINDOW_TITLE,
        f"http://{HOST}:{PORT}/dashboard",
        width=1280,
        height=800,
    )
    tray = pystray.Icon("scholarmind", _create_icon(), "ScholarMind AI")

    def open_dashboard(_icon, _item) -> None:
        window.show()

    def open_telegram(_icon, _item) -> None:
        webbrowser.open(TELEGRAM_URL)

    def run_enrichment(_icon, _item) -> None:
        def process() -> None:
            app = app_holder.get("app")
            if app is None:
                return
            from app.services.enrichment_service import EnrichmentService
            with app.app_context():
                EnrichmentService().process_pending()
        threading.Thread(target=process, daemon=True, name="scholarmind-enrichment").start()

    def exit_application(_icon, _item) -> None:
        tray.stop()
        server = server_holder.get("server")
        if server:
            server.shutdown()
        window.destroy()

    def minimize_to_tray() -> bool:
        window.hide()
        return False

    window.events.closing += minimize_to_tray
    tray.menu = pystray.Menu(
        pystray.MenuItem("Open ScholarMind Dashboard", open_dashboard),
        pystray.MenuItem("Open Telegram Web", open_telegram),
        pystray.MenuItem("Run AI Enrichment", run_enrichment),
        pystray.MenuItem("Exit", exit_application),
    )

    def start_tray() -> None:
        tray.run()

    threading.Thread(target=start_tray, daemon=True, name="scholarmind-tray").start()
    webview.start()
    exit_application(tray, None)


if __name__ == "__main__":
    main()
