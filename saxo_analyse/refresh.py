"""Refresh-Button: holt Kurse, Wechselkurse, Benchmarks und ETF-Zusammensetzung neu."""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any

from .db import Database
from .market import MarketData

BASE = "CHF"


def _start_date(db: Database) -> date:
    dates = [t["trade_date"] for t in db.trades()]
    rep = db.latest_report()
    if rep and rep.get("period_start"):
        dates.append(rep["period_start"])
    if not dates:
        return date.today() - timedelta(days=730)
    return date.fromisoformat(min(dates)) - timedelta(days=10)


def refresh_all(db: Database, md: MarketData | None = None) -> dict[str, Any]:
    md = md or MarketData()
    settings = db.get_settings()
    start = _start_date(db)
    steps: list[dict[str, Any]] = []

    def step(name: str, ok: bool, msg: str) -> None:
        steps.append({"step": name, "ok": ok, "message": msg})

    instruments: dict[str, dict] = {}
    for t in db.trades():
        instruments.setdefault(t["isin"], {"isin": t["isin"], "name": t.get("name"),
                                           "currency": t.get("currency")})
    for isin, inst in list(instruments.items()):
        stored = db.get_instrument(isin) or {}
        inst["currency"] = stored.get("currency") or inst.get("currency")
        inst["name"] = stored.get("name") or inst.get("name")
        inst["yahoo_symbol"] = stored.get("yahoo_symbol")

    currencies: set[str] = set()
    overrides = settings.get("symbol_overrides") or {}

    for isin, inst in instruments.items():
        cur = inst.get("currency")
        label = inst.get("name") or isin
        # --- Kurse
        got = False
        candidates: list[str] = []
        if overrides.get(isin):
            candidates.append(overrides[isin])
        if inst.get("yahoo_symbol"):
            candidates.append(inst["yahoo_symbol"])
        try:
            candidates += md.resolve_symbol(isin, cur)
        except Exception as e:  # noqa: BLE001
            step(f"Ticker-Suche {label}", False, f"Yahoo-Suche fehlgeschlagen: {e}")
        for sym in dict.fromkeys(candidates):
            try:
                ccy, pts = md.yahoo_chart(sym, start)
                if cur and ccy and ccy.upper() != cur.upper() and sym != overrides.get(isin):
                    continue  # andere Börse/Währung – nächsten Kandidaten versuchen
                db.save_series(f"PX:{isin}", pts, ccy or cur, f"Yahoo Finance ({sym})", label)
                db.upsert_instrument(isin, inst.get("name"), cur or ccy, sym)
                cur = cur or ccy
                step(f"Kurse {label}", True, f"{len(pts)} Tageskurse via Yahoo ({sym}, {ccy})")
                got = True
                break
            except Exception:  # noqa: BLE001
                continue
        if not got and cur:
            try:
                pts = md.justetf_chart(isin, cur, start)
                db.save_series(f"PX:{isin}", pts, cur, "justETF", label)
                step(f"Kurse {label}", True, f"{len(pts)} Tageskurse via justETF ({cur})")
                got = True
            except Exception as e:  # noqa: BLE001
                step(f"Kurse {label}", False, f"Keine Kurse (Yahoo & justETF): {e}")
        elif not got:
            step(f"Kurse {label}", False, "Keine Kurse gefunden und Währung unbekannt.")
        if cur and cur != BASE:
            currencies.add(cur)

        # --- Zusammensetzung (nur für ETFs relevant, schadet sonst nicht)
        today = date.today().isoformat()
        try:
            prof = md.justetf_profile(isin)
            n = 0
            for kind in ("sector", "country", "holding"):
                if prof.get(kind):
                    db.save_exposures(isin, kind, prof[kind], today, "justETF")
                    n += len(prof[kind])
            if prof.get("meta"):
                db.upsert_instrument(isin, inst.get("name"), cur, None, {"justetf": prof["meta"]})
            if n == 0:
                raise ValueError("Seite ohne Sektor-/Länderdaten")
            step(f"Zusammensetzung {label}", True, f"{n} Einträge via justETF")
        except Exception as e:  # noqa: BLE001
            sym = (db.get_instrument(isin) or {}).get("yahoo_symbol")
            try:
                if not sym:
                    raise ValueError("kein Yahoo-Ticker")
                yh = md.yahoo_holdings(sym)
                for kind, rows in yh.items():
                    if rows:
                        db.save_exposures(isin, kind, rows, today, "Yahoo Finance")
                if not any(yh.values()):
                    raise ValueError("leer")
                step(f"Zusammensetzung {label}", True, "via Yahoo Finance (justETF nicht erreichbar)")
            except Exception as e2:  # noqa: BLE001
                step(f"Zusammensetzung {label}", False, f"justETF: {e}; Yahoo: {e2}")

    # --- Benchmarks
    for bm in settings.get("benchmarks", []):
        sym = bm.get("symbol")
        if not sym:
            continue
        try:
            ccy, pts = md.yahoo_chart(sym, start)
            db.save_series(f"BM:{sym}", pts, ccy, f"Yahoo Finance ({sym})", bm.get("label"))
            if ccy and ccy != BASE:
                currencies.add(ccy)
            step(f"Benchmark {bm.get('label') or sym}", True, f"{len(pts)} Kurse ({ccy})")
        except Exception as e:  # noqa: BLE001
            step(f"Benchmark {bm.get('label') or sym}", False, str(e))

    # --- Wechselkurse
    for ccy in sorted(currencies):
        try:
            src, pts = md.fx_series(ccy, BASE, start)
            db.save_series(f"FX:{ccy}{BASE}", pts, BASE, src, f"{ccy}/{BASE}")
            step(f"Wechselkurs {ccy}/{BASE}", True, f"{len(pts)} Kurse via {src}")
        except Exception as e:  # noqa: BLE001
            step(f"Wechselkurs {ccy}/{BASE}", False, str(e))

    if not instruments:
        step("Instrumente", False, "Noch keine Transaktionen importiert.")
    ok = bool(steps) and all(s["ok"] for s in steps if s["step"].startswith(("Kurse", "Wechselkurs")))
    db.log_refresh(ok, steps)
    return {"ok": ok, "steps": steps}
