"""Starter für Saxo Portfolio (wird von SaxoPortfolio.exe aufgerufen, ohne Konsolenfenster).

Ordnerstruktur:  SaxoPortfolio.exe · app\\ (Programm) · Daten\\ (Datenbank, Logs)
1. Läuft die App schon? -> nur Browser öffnen.
2. Erster Start: fehlende Pakete einmalig installieren (1–2 Minuten).
3. Streamlit-Server im Hintergrund starten und Browser öffnen.
Die App beendet sich selbst, wenn 10 Minuten lang kein Browser-Tab offen ist.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
import urllib.request
import webbrowser
from pathlib import Path

APP = Path(__file__).resolve().parent
BASE = Path(sys.argv[1]).resolve() if len(sys.argv) > 1 and Path(sys.argv[1]).is_dir() else APP.parent
DATA = BASE / "Daten"
PORTS = range(8790, 8800)          # Finanzen.exe nutzt 8765–8784
WIN = sys.platform.startswith("win")
NO_WINDOW = 0x08000000 if WIN else 0
TITLE = "Saxo Portfolio"


def msg(text: str, error: bool = False) -> None:
    if WIN:
        import ctypes

        ctypes.windll.user32.MessageBoxW(None, text, TITLE, 0x10 if error else 0x40)
    else:
        print(("FEHLER: " if error else "") + text)


def log(text: str) -> None:
    with open(DATA / "start.log", "a", encoding="utf-8") as f:
        f.write(time.strftime("%Y-%m-%d %H:%M:%S ") + text + "\n")


def console_python() -> str:
    exe = Path(sys.executable)
    if exe.name.lower() == "pythonw.exe" and (exe.parent / "python.exe").exists():
        return str(exe.parent / "python.exe")
    return str(exe)


def healthy(port: int) -> bool:
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/_stcore/health", timeout=1.5) as r:
            return r.read().decode().strip() == "ok"
    except Exception:  # noqa: BLE001
        return False


def port_free(port: int) -> bool:
    import socket

    with socket.socket() as s:
        try:
            s.bind(("127.0.0.1", port))
            return True
        except OSError:
            return False


def deps_ok(py: str) -> bool:
    r = subprocess.run([py, "-c", "import streamlit, plotly, pdfplumber, bs4, pandas, requests"],
                       capture_output=True, creationflags=NO_WINDOW)
    return r.returncode == 0


def install(py: str) -> bool:
    msg("Erster Start: Die benötigten Pakete werden jetzt installiert (einmalig, ca. 1–2 Minuten).\n\n"
        "Bitte auf OK klicken und kurz warten – der Browser öffnet sich danach automatisch.")
    req = str(APP / "requirements.txt")
    with open(DATA / "install.log", "w", encoding="utf-8") as f:
        for extra in ([], ["--user"]):
            r = subprocess.run([py, "-m", "pip", "install", "--disable-pip-version-check", "-r", req, *extra],
                               stdout=f, stderr=subprocess.STDOUT, creationflags=NO_WINDOW)
            if r.returncode == 0 and deps_ok(py):
                return True
    return False


def main() -> None:
    DATA.mkdir(parents=True, exist_ok=True)
    state_file = DATA / "server.json"
    if state_file.exists():
        try:
            port = json.loads(state_file.read_text())["port"]
            if healthy(port):
                webbrowser.open(f"http://localhost:{port}/")
                return
        except Exception:  # noqa: BLE001
            pass

    py = console_python()
    log(f"Start mit {py}")
    if not deps_ok(py) and not install(py):
        msg(f"Die Pakete konnten nicht installiert werden.\nDetails: {DATA / 'install.log'}", error=True)
        return

    port = next((p for p in PORTS if port_free(p)), None)
    if port is None:
        msg("Alle Ports 8790–8799 sind belegt. Bitte andere Programme schliessen.", error=True)
        return
    env = {**os.environ, "PORTFOLIO_DATA": str(DATA), "PORTFOLIO_AUTOSTOP": "1"}
    with open(DATA / "server.log", "w", encoding="utf-8") as out:
        proc = subprocess.Popen(
            [py, "-m", "streamlit", "run", str(APP / "app.py"), "--server.port", str(port),
             "--server.address", "127.0.0.1", "--server.headless", "true", "--browser.gatherUsageStats", "false"],
            cwd=str(APP), env=env, stdout=out, stderr=subprocess.STDOUT, creationflags=NO_WINDOW)
    for _ in range(180):
        if healthy(port):
            state_file.write_text(json.dumps({"port": port, "pid": proc.pid}))
            log(f"Server läuft auf Port {port}")
            webbrowser.open(f"http://localhost:{port}/")
            return
        if proc.poll() is not None:
            break
        time.sleep(0.5)
    tail = (DATA / "server.log").read_text(encoding="utf-8", errors="replace")[-800:]
    log("Server-Start fehlgeschlagen")
    msg(f"Der Server konnte nicht gestartet werden.\n\n{tail}\n\nDetails: {DATA / 'server.log'}", error=True)


if __name__ == "__main__":
    try:
        main()
    except Exception as e:  # noqa: BLE001
        DATA.mkdir(parents=True, exist_ok=True)
        log(f"Fehler: {e!r}")
        msg(f"Unerwarteter Fehler: {e}", error=True)
