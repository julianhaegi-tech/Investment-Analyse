"""Startpunkt: startet die App im Hintergrund (ohne Konsolenfenster) und öffnet sie im Browser.

- Läuft die App schon, wird nur der Browser geöffnet (keine zweite Instanz).
- Die App beendet sich selbst, wenn kein Browser-Tab mehr offen ist (oder per «Beenden»).
- Fehler und Refresh-Ergebnisse landen in einer Logdatei im Datenordner.
"""

from __future__ import annotations

import json
import logging
import os
import socket
import sys
import threading
import time
import urllib.request
import webbrowser

APP_ID = "saxo-portfolio-analyse"
PORT = 8765


def _quiet_stdio() -> None:
    # Ohne Konsole (PyInstaller --windowed) sind stdout/stderr None -> Schreibzugriffe abfangen
    if sys.stdout is None:
        sys.stdout = open(os.devnull, "w")  # noqa: SIM115
    if sys.stderr is None:
        sys.stderr = open(os.devnull, "w")  # noqa: SIM115


def _already_running(port: int) -> bool:
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/ping", timeout=1.5) as r:
            return json.loads(r.read().decode()).get("app") == APP_ID
    except Exception:  # noqa: BLE001
        return False


def _port_free(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        try:
            s.bind(("127.0.0.1", port))
            return True
        except OSError:
            return False


def _any_free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _setup_logging(data_dir: str) -> str:
    log_path = os.path.join(data_dir, "app.log")
    logging.basicConfig(
        filename=log_path, level=logging.INFO, encoding="utf-8",
        format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    logging.getLogger("werkzeug").setLevel(logging.WARNING)
    return log_path


def main() -> None:
    _quiet_stdio()
    open_browser = "--no-browser" not in sys.argv

    if _already_running(PORT):
        if open_browser:
            webbrowser.open(f"http://127.0.0.1:{PORT}/")
        return

    from saxo_analyse.app import create_app
    from saxo_analyse.db import default_data_dir

    data_dir = default_data_dir()
    data_dir.mkdir(parents=True, exist_ok=True)
    log_path = _setup_logging(str(data_dir))

    port = PORT if _port_free(PORT) else _any_free_port()
    url = f"http://127.0.0.1:{port}/"
    app = create_app(idle_shutdown=open_browser)
    logging.info("Start %s, Daten: %s, Log: %s", url, app.db.path, log_path)

    import flask.cli

    flask.cli.show_server_banner = lambda *a, **k: None
    if open_browser:
        threading.Timer(0.8, lambda: webbrowser.open(url)).start()
    try:
        app.run(host="127.0.0.1", port=port, debug=False, use_reloader=False, threaded=True)
    except Exception:  # noqa: BLE001
        logging.exception("Server-Fehler")
        time.sleep(0.5)
        raise


if __name__ == "__main__":
    main()
