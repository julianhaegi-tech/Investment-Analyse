"""Flask-Server (nur lokal auf 127.0.0.1) + JSON-API für die Oberfläche."""

from __future__ import annotations

import os
import threading
from pathlib import Path

from flask import Flask, jsonify, request, send_from_directory

from . import __version__
from .analytics import compute, estimate_trade_from_report
from .db import Database
from .importers.saxo_ledger import is_ledger_workbook, parse_ledger
from .importers.saxo_pdf import parse_saxo_pdf
from .importers.saxo_trades import parse_trades_file
from .insights import build_insights
from .refresh import refresh_all

STATIC = Path(__file__).parent / "static"


def create_app(db: Database | None = None) -> Flask:
    app = Flask(__name__, static_folder=None)
    app.config["MAX_CONTENT_LENGTH"] = 30 * 1024 * 1024
    app.db = db or Database()
    lock = threading.Lock()

    @app.get("/")
    def index():
        return send_from_directory(STATIC, "index.html")

    @app.get("/static/<path:name>")
    def static_files(name: str):
        return send_from_directory(STATIC, name)

    @app.get("/api/state")
    def state():
        with lock:
            s = compute(app.db)
        s["insights"] = build_insights(s)
        s["version"] = __version__
        s["data_path"] = app.db.path
        return jsonify(s)

    @app.post("/api/refresh")
    def refresh():
        with lock:
            return jsonify(refresh_all(app.db))

    @app.post("/api/import")
    def import_file():
        f = request.files.get("file")
        if not f or not f.filename:
            return jsonify({"error": "Keine Datei erhalten."}), 400
        content = f.read()
        name = f.filename
        try:
            with lock:
                if name.lower().endswith(".pdf"):
                    return jsonify(_import_report(app.db, content))
                if name.lower().endswith((".xlsx", ".xls", ".xlsm")) and is_ledger_workbook(content):
                    return jsonify(_import_ledger(app.db, content))
                return jsonify(_import_trades(app.db, content, name))
        except Exception as e:  # noqa: BLE001
            return jsonify({"error": str(e)}), 400

    @app.post("/api/trades")
    def add_trade():
        t = _clean_trade(request.get_json(force=True))
        with lock:
            app.db.upsert_instrument(t["isin"], t.get("name"), t.get("currency"))
            tid = app.db.add_trade({**t, "source": "manuell"})
        return jsonify({"id": tid})

    @app.put("/api/trades/<int:tid>")
    def update_trade(tid: int):
        t = _clean_trade(request.get_json(force=True), partial=True)
        with lock:
            app.db.update_trade(tid, {**t, "estimated": 0})
        return jsonify({"ok": True})

    @app.delete("/api/trades/<int:tid>")
    def delete_trade(tid: int):
        with lock:
            app.db.delete_trade(tid)
        return jsonify({"ok": True})

    @app.post("/api/settings")
    def settings():
        with lock:
            app.db.set_settings(request.get_json(force=True))
        return jsonify(app.db.get_settings())

    @app.post("/api/reset")
    def reset():
        with lock:
            app.db.reset()
        return jsonify({"ok": True})

    @app.post("/api/shutdown")
    def shutdown():
        threading.Timer(0.3, lambda: os._exit(0)).start()
        return jsonify({"ok": True})

    return app


def _clean_trade(d: dict, partial: bool = False) -> dict:
    out = {}
    for k in ("trade_date", "isin", "name", "side", "currency", "note"):
        if k in d and d[k] not in (None, ""):
            out[k] = str(d[k]).strip()
    for k in ("quantity", "price", "fx_rate", "fees_chf", "amount_chf"):
        if k in d:
            out[k] = float(d[k]) if d[k] not in (None, "") else None
    if "isin" in out:
        out["isin"] = out["isin"].upper()
    if "currency" in out:
        out["currency"] = out["currency"].upper()
    if "side" in out:
        out["side"] = "SELL" if out["side"].upper().startswith(("S", "V")) else "BUY"
    if not partial:
        for k in ("trade_date", "isin", "side", "quantity", "price", "currency"):
            if out.get(k) in (None, ""):
                raise ValueError(f"Feld fehlt: {k}")
    if out.get("fees_chf") is None and not partial:
        out["fees_chf"] = 0.0
    return out


def _import_report(db: Database, content: bytes) -> dict:
    import tempfile

    with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp:
        tmp.write(content)
        tmp_path = tmp.name
    try:
        rep = parse_saxo_pdf(tmp_path)
    finally:
        os.unlink(tmp_path)
    db.add_report(rep)
    created = []
    existing = {t["isin"] for t in db.trades()}
    if db.ledger():  # Saxo-Tagesdaten vorhanden – keine Schätzung nötig
        existing |= {h.get("isin") for h in rep.get("holdings", [])}
    for h in rep.get("holdings", []):
        if not h.get("isin"):
            continue
        db.upsert_instrument(h["isin"], h.get("name"), h.get("currency"))
        if h["isin"] not in existing:
            db.add_trade(estimate_trade_from_report(rep, h))
            created.append(h["name"])
    return {"type": "report", "period": [rep.get("period_start"), rep.get("period_end")],
            "holdings": len(rep.get("holdings", [])), "estimated_trades": created,
            "warnings": rep.get("warnings", [])}


def _import_ledger(db: Database, content: bytes) -> dict:
    led = parse_ledger(content)
    db.set_ledger(led)
    db.delete_all_estimated_trades()
    return {"type": "ledger", "period": [led["period_start"], led["period_end"]],
            "instruments": [i["name"] for i in led["instruments"]],
            "trades": sum(1 for m in led["movements"] if m["kind"] == "trade"),
            "deposits": round(sum(d["amount_chf"] for d in led["deposits"]), 2)}


def _import_trades(db: Database, content: bytes, name: str) -> dict:
    res = parse_trades_file(content, name)
    added = skipped = 0
    for isin in {t["isin"] for t in res["trades"]}:
        db.delete_estimated_trades(isin)  # echte Trades ersetzen Schätzungen
    for t in res["trades"]:
        inst = db.get_instrument(t["isin"]) or {}
        t["currency"] = t.get("currency") or inst.get("currency") or "CHF"
        db.upsert_instrument(t["isin"], t.get("name") or inst.get("name"), t["currency"])
        if db.trade_exists(t):
            skipped += 1
            continue
        db.add_trade(t)
        added += 1
    return {"type": "trades", "added": added, "skipped_duplicates": skipped,
            "warnings": res["warnings"], "columns": res["mapping"]}
