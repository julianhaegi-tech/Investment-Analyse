"""SQLite-Speicher. Alle Daten bleiben lokal auf dem PC."""

from __future__ import annotations

import json
import os
import sqlite3
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable

SCHEMA = """
CREATE TABLE IF NOT EXISTS settings (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS instruments (
    isin          TEXT PRIMARY KEY,
    name          TEXT,
    currency      TEXT,
    yahoo_symbol  TEXT,
    meta_json     TEXT
);
CREATE TABLE IF NOT EXISTS trades (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    trade_date  TEXT NOT NULL,
    isin        TEXT NOT NULL,
    name        TEXT,
    side        TEXT NOT NULL CHECK (side IN ('BUY','SELL')),
    quantity    REAL NOT NULL,
    price       REAL NOT NULL,
    currency    TEXT NOT NULL,
    fx_rate     REAL,
    fees_chf    REAL NOT NULL DEFAULT 0,
    amount_chf  REAL,
    source      TEXT,
    note        TEXT,
    estimated   INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS reports (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    imported_at  TEXT NOT NULL,
    period_start TEXT,
    period_end   TEXT,
    data_json    TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS prices (
    series  TEXT NOT NULL,
    date    TEXT NOT NULL,
    close   REAL NOT NULL,
    PRIMARY KEY (series, date)
);
CREATE TABLE IF NOT EXISTS series_meta (
    series    TEXT PRIMARY KEY,
    currency  TEXT,
    source    TEXT,
    label     TEXT,
    updated   TEXT
);
CREATE TABLE IF NOT EXISTS exposures (
    isin    TEXT NOT NULL,
    kind    TEXT NOT NULL,
    name    TEXT NOT NULL,
    weight  REAL NOT NULL,
    as_of   TEXT,
    source  TEXT,
    PRIMARY KEY (isin, kind, name)
);
CREATE TABLE IF NOT EXISTS ledger (
    id           INTEGER PRIMARY KEY CHECK (id = 1),
    imported_at  TEXT NOT NULL,
    data_json    TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS refresh_log (
    id       INTEGER PRIMARY KEY AUTOINCREMENT,
    ts       TEXT NOT NULL,
    ok       INTEGER NOT NULL,
    details  TEXT NOT NULL
);
"""

DEFAULT_SETTINGS: dict[str, Any] = {
    "base_currency": "CHF",
    "risk_free_rate": 0.0,
    "benchmarks": [
        {"symbol": "^SSMI", "label": "SMI"},
        {"symbol": "ACWI", "label": "MSCI ACWI (iShares ACWI)"},
    ],
    "symbol_overrides": {},
    "isin_overrides": {},
}


def default_data_dir() -> Path:
    env = os.environ.get("SAXO_ANALYSE_DATA")
    if env:
        return Path(env)
    if sys.platform.startswith("win"):
        return Path(os.environ.get("APPDATA", Path.home())) / "SaxoAnalyse"
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / "SaxoAnalyse"
    return Path.home() / ".saxo-analyse"


class Database:
    def __init__(self, path: Path | str | None = None):
        if path is None:
            d = default_data_dir()
            d.mkdir(parents=True, exist_ok=True)
            path = d / "portfolio.db"
        self.path = str(path)
        self.conn = sqlite3.connect(self.path, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self.conn.executescript(SCHEMA)
        self.conn.commit()

    # ---------- Einstellungen ----------
    def get_settings(self) -> dict[str, Any]:
        out = json.loads(json.dumps(DEFAULT_SETTINGS))
        for row in self.conn.execute("SELECT key, value FROM settings"):
            out[row["key"]] = json.loads(row["value"])
        return out

    def set_settings(self, values: dict[str, Any]) -> None:
        with self.conn:
            for k, v in values.items():
                if k not in DEFAULT_SETTINGS:
                    continue
                self.conn.execute(
                    "INSERT INTO settings(key, value) VALUES(?, ?) "
                    "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                    (k, json.dumps(v)),
                )

    # ---------- Instrumente ----------
    def upsert_instrument(self, isin: str, name: str | None = None, currency: str | None = None,
                          yahoo_symbol: str | None = None, meta: dict | None = None) -> None:
        cur = self.get_instrument(isin) or {}
        merged_meta = {**(cur.get("meta") or {}), **(meta or {})}
        with self.conn:
            self.conn.execute(
                "INSERT INTO instruments(isin, name, currency, yahoo_symbol, meta_json) VALUES(?,?,?,?,?) "
                "ON CONFLICT(isin) DO UPDATE SET name=excluded.name, currency=excluded.currency, "
                "yahoo_symbol=excluded.yahoo_symbol, meta_json=excluded.meta_json",
                (isin, name or cur.get("name"), currency or cur.get("currency"),
                 yahoo_symbol or cur.get("yahoo_symbol"), json.dumps(merged_meta)),
            )

    def get_instrument(self, isin: str) -> dict | None:
        row = self.conn.execute("SELECT * FROM instruments WHERE isin=?", (isin,)).fetchone()
        return _instrument(row) if row else None

    def instruments(self) -> list[dict]:
        return [_instrument(r) for r in self.conn.execute("SELECT * FROM instruments ORDER BY name")]

    # ---------- Trades ----------
    def trades(self) -> list[dict]:
        return [dict(r) for r in self.conn.execute("SELECT * FROM trades ORDER BY trade_date, id")]

    def add_trade(self, t: dict) -> int:
        cols = ["trade_date", "isin", "name", "side", "quantity", "price", "currency", "fx_rate",
                "fees_chf", "amount_chf", "source", "note", "estimated"]
        vals = [t.get(c) for c in cols]
        vals[cols.index("fees_chf")] = t.get("fees_chf") or 0.0
        vals[cols.index("estimated")] = 1 if t.get("estimated") else 0
        with self.conn:
            cur = self.conn.execute(
                f"INSERT INTO trades({','.join(cols)}) VALUES({','.join('?' * len(cols))})", vals)
        return int(cur.lastrowid)

    def trade_exists(self, t: dict) -> bool:
        row = self.conn.execute(
            "SELECT 1 FROM trades WHERE trade_date=? AND isin=? AND side=? AND abs(quantity-?)<1e-9 "
            "AND abs(price-?)<1e-9", (t["trade_date"], t["isin"], t["side"], t["quantity"], t["price"]),
        ).fetchone()
        return row is not None

    def update_trade(self, trade_id: int, t: dict) -> None:
        allowed = ["trade_date", "isin", "name", "side", "quantity", "price", "currency", "fx_rate",
                   "fees_chf", "amount_chf", "note", "estimated"]
        sets = [(k, t[k]) for k in allowed if k in t]
        if not sets:
            return
        with self.conn:
            self.conn.execute(
                f"UPDATE trades SET {', '.join(k + '=?' for k, _ in sets)} WHERE id=?",
                [v for _, v in sets] + [trade_id])

    def delete_trade(self, trade_id: int) -> None:
        with self.conn:
            self.conn.execute("DELETE FROM trades WHERE id=?", (trade_id,))

    def delete_estimated_trades(self, isin: str) -> None:
        with self.conn:
            self.conn.execute("DELETE FROM trades WHERE isin=? AND estimated=1", (isin,))

    # ---------- Saxo-Berichte ----------
    def add_report(self, data: dict) -> int:
        with self.conn:
            cur = self.conn.execute(
                "INSERT INTO reports(imported_at, period_start, period_end, data_json) VALUES(?,?,?,?)",
                (datetime.now().isoformat(timespec="seconds"), data.get("period_start"),
                 data.get("period_end"), json.dumps(data)))
        return int(cur.lastrowid)

    def latest_report(self) -> dict | None:
        row = self.conn.execute(
            "SELECT * FROM reports ORDER BY period_end DESC, id DESC LIMIT 1").fetchone()
        if not row:
            return None
        data = json.loads(row["data_json"])
        data["_imported_at"] = row["imported_at"]
        return data

    # ---------- Saxo «Aggregierte Beträge» ----------
    def set_ledger(self, data: dict) -> None:
        with self.conn:
            self.conn.execute(
                "INSERT INTO ledger(id, imported_at, data_json) VALUES(1, ?, ?) "
                "ON CONFLICT(id) DO UPDATE SET imported_at=excluded.imported_at, data_json=excluded.data_json",
                (datetime.now().isoformat(timespec="seconds"), json.dumps(data)))

    def ledger(self) -> dict | None:
        row = self.conn.execute("SELECT * FROM ledger WHERE id=1").fetchone()
        if not row:
            return None
        data = json.loads(row["data_json"])
        data["_imported_at"] = row["imported_at"]
        return data

    def delete_all_estimated_trades(self) -> None:
        with self.conn:
            self.conn.execute("DELETE FROM trades WHERE estimated=1")

    # ---------- Kurse ----------
    def save_series(self, series: str, points: Iterable[tuple[str, float]], currency: str | None,
                    source: str, label: str | None = None) -> int:
        pts = [(series, d, float(v)) for d, v in points if v is not None]
        with self.conn:
            self.conn.executemany(
                "INSERT INTO prices(series, date, close) VALUES(?,?,?) "
                "ON CONFLICT(series, date) DO UPDATE SET close=excluded.close", pts)
            self.conn.execute(
                "INSERT INTO series_meta(series, currency, source, label, updated) VALUES(?,?,?,?,?) "
                "ON CONFLICT(series) DO UPDATE SET currency=excluded.currency, source=excluded.source, "
                "label=COALESCE(excluded.label, series_meta.label), updated=excluded.updated",
                (series, currency, source, label, datetime.now().isoformat(timespec="seconds")))
        return len(pts)

    def load_series(self, series: str) -> list[tuple[str, float]]:
        return [(r["date"], r["close"]) for r in self.conn.execute(
            "SELECT date, close FROM prices WHERE series=? ORDER BY date", (series,))]

    def series_meta(self, series: str) -> dict | None:
        row = self.conn.execute("SELECT * FROM series_meta WHERE series=?", (series,)).fetchone()
        return dict(row) if row else None

    # ---------- Zusammensetzung (Sektoren, Länder, Positionen) ----------
    def save_exposures(self, isin: str, kind: str, rows: list[tuple[str, float]], as_of: str,
                       source: str) -> None:
        with self.conn:
            self.conn.execute("DELETE FROM exposures WHERE isin=? AND kind=?", (isin, kind))
            self.conn.executemany(
                "INSERT OR REPLACE INTO exposures(isin, kind, name, weight, as_of, source) "
                "VALUES(?,?,?,?,?,?)", [(isin, kind, n, float(w), as_of, source) for n, w in rows])

    def exposures(self, isin: str) -> dict[str, list[dict]]:
        out: dict[str, list[dict]] = {}
        for r in self.conn.execute(
                "SELECT * FROM exposures WHERE isin=? ORDER BY kind, weight DESC", (isin,)):
            out.setdefault(r["kind"], []).append(dict(r))
        return out

    # ---------- Refresh-Log ----------
    def log_refresh(self, ok: bool, details: Any) -> None:
        with self.conn:
            self.conn.execute("INSERT INTO refresh_log(ts, ok, details) VALUES(?,?,?)",
                              (datetime.now().isoformat(timespec="seconds"), 1 if ok else 0,
                               json.dumps(details)))

    def last_refresh(self) -> dict | None:
        row = self.conn.execute("SELECT * FROM refresh_log ORDER BY id DESC LIMIT 1").fetchone()
        if not row:
            return None
        return {"ts": row["ts"], "ok": bool(row["ok"]), "details": json.loads(row["details"])}

    def reset(self) -> None:
        with self.conn:
            for t in ["instruments", "trades", "reports", "prices", "series_meta", "exposures",
                      "refresh_log", "ledger"]:
                self.conn.execute(f"DELETE FROM {t}")


def _instrument(row: sqlite3.Row) -> dict:
    d = dict(row)
    d["meta"] = json.loads(d.pop("meta_json") or "{}")
    return d
