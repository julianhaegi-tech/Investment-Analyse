"""Lokale SQLite-Datenbank im Ordner «Daten» neben der App."""

from __future__ import annotations

import json
import os
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable

DEFAULT_SETTINGS: dict[str, Any] = {
    "benchmarks": [{"symbol": "ACWI", "label": "MSCI ACWI"}, {"symbol": "^SSMI", "label": "SMI"}],
    "tickers": {},        # Instrumentname -> Yahoo-Ticker (manuelle Zuordnung)
    "risk_free_pct": 0.0,
}

SCHEMA = """
CREATE TABLE IF NOT EXISTS report (id INTEGER PRIMARY KEY CHECK (id = 1), imported_at TEXT, filename TEXT, data TEXT);
CREATE TABLE IF NOT EXISTS prices (series TEXT, date TEXT, close REAL, PRIMARY KEY (series, date));
CREATE TABLE IF NOT EXISTS series_meta (series TEXT PRIMARY KEY, currency TEXT, source TEXT, updated TEXT);
CREATE TABLE IF NOT EXISTS exposures (isin TEXT, kind TEXT, name TEXT, weight REAL, source TEXT, as_of TEXT,
                                      PRIMARY KEY (isin, kind, name));
CREATE TABLE IF NOT EXISTS etf_meta (isin TEXT PRIMARY KEY, data TEXT);
CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT);
CREATE TABLE IF NOT EXISTS refresh_log (id INTEGER PRIMARY KEY AUTOINCREMENT, ts TEXT, steps TEXT);
"""


def data_dir() -> Path:
    d = Path(os.environ.get("PORTFOLIO_DATA") or Path(__file__).resolve().parents[2] / "Daten")
    d.mkdir(parents=True, exist_ok=True)
    return d


class Store:
    def __init__(self, path: str | Path | None = None):
        self.path = str(path or data_dir() / "portfolio.db")
        self.db = sqlite3.connect(self.path, check_same_thread=False)
        self.db.executescript(SCHEMA)

    # ---- Bericht
    def save_report(self, data: dict, filename: str) -> None:
        with self.db:
            self.db.execute("INSERT OR REPLACE INTO report VALUES (1, ?, ?, ?)",
                            (datetime.now().isoformat(timespec="seconds"), filename, json.dumps(data)))

    def report(self) -> dict | None:
        row = self.db.execute("SELECT imported_at, filename, data FROM report WHERE id=1").fetchone()
        if not row:
            return None
        return {**json.loads(row[2]), "_imported_at": row[0], "_filename": row[1]}

    # ---- Einstellungen
    def settings(self) -> dict[str, Any]:
        s = json.loads(json.dumps(DEFAULT_SETTINGS))
        for k, v in self.db.execute("SELECT key, value FROM settings"):
            s[k] = json.loads(v)
        return s

    def save_settings(self, **values: Any) -> None:
        with self.db:
            for k, v in values.items():
                self.db.execute("INSERT OR REPLACE INTO settings VALUES (?, ?)", (k, json.dumps(v)))

    # ---- Kurse
    def save_series(self, series: str, points: Iterable[tuple[str, float]], currency: str | None, source: str) -> int:
        pts = [(series, d, float(v)) for d, v in points if v is not None]
        with self.db:
            self.db.executemany("INSERT OR REPLACE INTO prices VALUES (?, ?, ?)", pts)
            self.db.execute("INSERT OR REPLACE INTO series_meta VALUES (?, ?, ?, ?)",
                            (series, currency, source, datetime.now().isoformat(timespec="seconds")))
        return len(pts)

    def series(self, series: str) -> list[tuple[str, float]]:
        return list(self.db.execute("SELECT date, close FROM prices WHERE series=? ORDER BY date", (series,)))

    def series_meta(self, series: str) -> dict | None:
        r = self.db.execute("SELECT currency, source, updated FROM series_meta WHERE series=?", (series,)).fetchone()
        return {"currency": r[0], "source": r[1], "updated": r[2]} if r else None

    # ---- ETF-Zusammensetzung
    def save_exposures(self, isin: str, kind: str, rows: list[tuple[str, float]], source: str) -> None:
        today = datetime.now().date().isoformat()
        with self.db:
            self.db.execute("DELETE FROM exposures WHERE isin=? AND kind=?", (isin, kind))
            self.db.executemany("INSERT OR REPLACE INTO exposures VALUES (?, ?, ?, ?, ?, ?)",
                                [(isin, kind, n, float(w), source, today) for n, w in rows])

    def exposures(self, isin: str) -> dict[str, list[dict]]:
        out: dict[str, list[dict]] = {}
        for kind, name, w, src, asof in self.db.execute(
                "SELECT kind, name, weight, source, as_of FROM exposures WHERE isin=? ORDER BY weight DESC", (isin,)):
            out.setdefault(kind, []).append({"name": name, "weight": w, "source": src, "as_of": asof})
        return out

    def save_etf_meta(self, isin: str, meta: dict) -> None:
        with self.db:
            self.db.execute("INSERT OR REPLACE INTO etf_meta VALUES (?, ?)", (isin, json.dumps(meta)))

    def etf_meta(self, isin: str) -> dict:
        r = self.db.execute("SELECT data FROM etf_meta WHERE isin=?", (isin,)).fetchone()
        return json.loads(r[0]) if r else {}

    # ---- Refresh-Protokoll
    def log_refresh(self, steps: list[dict]) -> None:
        with self.db:
            self.db.execute("INSERT INTO refresh_log (ts, steps) VALUES (?, ?)",
                            (datetime.now().isoformat(timespec="seconds"), json.dumps(steps)))

    def last_refresh(self) -> dict | None:
        r = self.db.execute("SELECT ts, steps FROM refresh_log ORDER BY id DESC LIMIT 1").fetchone()
        return {"ts": r[0], "steps": json.loads(r[1])} if r else None

    def reset(self) -> None:
        with self.db:
            for t in ("report", "prices", "series_meta", "exposures", "etf_meta", "refresh_log"):
                self.db.execute(f"DELETE FROM {t}")
