"""Startpunkt: startet den lokalen Server und öffnet die App im Browser."""

from __future__ import annotations

import socket
import sys
import threading
import webbrowser


def free_port(preferred: int = 8765) -> int:
    for port in (preferred, 0):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            try:
                s.bind(("127.0.0.1", port))
                return s.getsockname()[1]
            except OSError:
                continue
    raise RuntimeError("Kein freier Port gefunden")


def main() -> None:
    from saxo_analyse.app import create_app

    port = free_port()
    url = f"http://127.0.0.1:{port}/"
    app = create_app()
    print("Saxo Portfolio Analyse läuft unter", url)
    print("Daten:", app.db.path)
    print("Zum Beenden dieses Fenster schliessen oder in der App auf «Beenden» klicken.")
    # Entwickler-Hinweise von Flask im Konsolenfenster ausblenden
    import logging

    import flask.cli

    flask.cli.show_server_banner = lambda *a, **k: None
    logging.getLogger("werkzeug").setLevel(logging.WARNING)
    if "--no-browser" not in sys.argv:
        threading.Timer(1.0, lambda: webbrowser.open(url)).start()
    app.run(host="127.0.0.1", port=port, debug=False, use_reloader=False)


if __name__ == "__main__":
    main()
