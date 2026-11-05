"""Baut dist/SaxoPortfolio.zip:  SaxoPortfolio/ ├ SaxoPortfolio.exe ├ app/ └ LIESMICH.txt

Die .exe ist ein kleiner C-Starter, kompiliert mit Zig (pip install ziglang) – funktioniert auch unter Linux/macOS.
Aufruf:  python tools/build_package.py
"""

from __future__ import annotations

import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TOOLS = ROOT / "tools"
DIST = ROOT / "dist"
PKG = DIST / "SaxoPortfolio"

README = """SAXO PORTFOLIO – lokale Analyse deines Saxo-Depots
====================================================

Starten
-------
Doppelklick auf  SaxoPortfolio.exe
Die App öffnet sich im Browser (http://localhost:8790). Kein Konsolenfenster.
Beim allerersten Start werden einmalig die nötigen Python-Pakete installiert (1–2 Minuten).

Voraussetzung: Python 3.11 oder neuer (python.org) – ist bei dir schon für «Finanzen» installiert.

Daten importieren
-----------------
SaxoTraderGO → Konto → Berichte → «Transaktions- und Saldenbericht»
→ Zeitraum ab Kontoeröffnung bis heute → PDF herunterladen
→ in der App links bei «Import» hineinziehen. Fertig.

Optional: «Kurse aktualisieren» lädt Tageskurse, Benchmarks (MSCI ACWI, SMI) und
Sektoren/Länder deines ETFs aus kostenlosen Quellen (Yahoo Finance, justETF, EZB).

Ordner
------
SaxoPortfolio.exe   Starter
app\\                Programm (nicht verändern)
Daten\\              wird beim ersten Start angelegt: Datenbank und Logdateien
                    (bei Problemen: Daten\\server.log und Daten\\start.log)

Beenden
-------
Browser-Tab schliessen – die App beendet sich nach 10 Minuten von selbst.
"""


def build_exe(out: Path) -> None:
    cmd = [sys.executable, "-m", "ziglang", "cc", "-target", "x86_64-windows-gnu", "-O2", "-municode",
           "-Wl,--subsystem,windows", str(TOOLS / "launcher.c"), str(TOOLS / "icon.rc"), "-o", str(out)]
    subprocess.run(cmd, check=True, cwd=TOOLS)
    for junk in out.parent.glob("SaxoPortfolio.pdb"):
        junk.unlink()


def main() -> None:
    shutil.rmtree(DIST, ignore_errors=True)
    PKG.mkdir(parents=True)
    build_exe(PKG / "SaxoPortfolio.exe")
    shutil.copytree(ROOT / "app", PKG / "app", ignore=shutil.ignore_patterns("__pycache__", "*.pyc", "Daten"))
    (PKG / "LIESMICH.txt").write_text(README.replace("\n", "\r\n"), encoding="utf-8-sig")
    zpath = DIST / "SaxoPortfolio.zip"
    with zipfile.ZipFile(zpath, "w", zipfile.ZIP_DEFLATED) as z:
        for f in sorted(PKG.rglob("*")):
            z.write(f, f.relative_to(DIST))
    print(zpath, zpath.stat().st_size // 1024, "KB")


if __name__ == "__main__":
    main()
