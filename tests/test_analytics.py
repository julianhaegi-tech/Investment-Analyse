import json
from pathlib import Path

import pandas as pd
import pytest

from saxo_analyse.analytics import compute, estimate_trade_from_report, xirr
from saxo_analyse.app import create_app
from saxo_analyse.importers.saxo_pdf import parse_saxo_pages
from saxo_analyse.insights import build_insights
from saxo_analyse.refresh import refresh_all


def add(db, d, isin, side, q, p, fees=0.0, name=None):
    db.upsert_instrument(isin, name or isin, "EUR")
    db.add_trade({"trade_date": d, "isin": isin, "name": name, "side": side, "quantity": q, "price": p,
                  "currency": "EUR", "fees_chf": fees, "source": "test"})


def test_xirr_simple():
    r = xirr([(pd.Timestamp("2025-01-01"), -1000), (pd.Timestamp("2026-01-01"), 1100)])
    assert r == pytest.approx(0.1, abs=1e-3)


def test_etf_switch_scenario(db, market):
    # ETF A kaufen, später verkaufen, Erlös in ETF B umschichten
    add(db, "2025-10-01", "IE000AAAAAA1", "BUY", 500, 10.0, fees=10, name="ETF A")
    add(db, "2026-05-04", "IE000AAAAAA1", "SELL", 500, 11.5, fees=10, name="ETF A")
    add(db, "2026-05-05", "IE000BBBBBB2", "BUY", 300, 20.0, fees=10, name="ETF B")
    res = refresh_all(db, market)
    assert res["ok"], res
    s = compute(db)
    k = s["kpis"]
    a = next(p for p in s["positions"] if p["isin"] == "IE000AAAAAA1")
    b = next(p for p in s["positions"] if p["isin"] == "IE000BBBBBB2")
    assert not a["open"] and b["open"]
    # A: Einstand 500*10*0.95+10 = 4760, Erlös 500*11.5*0.95-10 = 5452.5
    assert a["realized_pnl"] == pytest.approx(5452.5 - 4760, abs=0.01)
    # B: Wert 300*20*0.95 = 5700, Einstand 5710
    assert b["market_value"] == pytest.approx(5700)
    assert b["unrealized_pnl"] == pytest.approx(-10)
    assert k["pnl"] == pytest.approx(692.5 - 10, abs=0.05)
    assert k["n_open"] == 1 and k["irr_pct"] is not None
    # Wechsel A -> B wird aus dem Verkaufserlös bezahlt: nur die Differenz ist neue Einzahlung
    assert k["net_invested"] == pytest.approx(4760 + (5710 - 5452.5), abs=0.01)
    assert min(s["series"]["value"]["y"]) > 4000  # kein Einbruch auf 0 zwischen Verkauf und Kauf
    assert len(s["benchmarks"]) == 2
    # USD-Benchmark wird in CHF umgerechnet (100 USD * 0.80)
    acwi = next(x for x in s["benchmarks"] if x["symbol"] == "ACWI")
    assert acwi["total_pct"] == pytest.approx(0, abs=1e-6)
    assert s["exposure"]["sector"][0]["name"] == "Technologie"
    assert s["exposure"]["holding"][0]["value_chf"] == pytest.approx(5700 * 0.05)
    titles = [i["title"] for i in build_insights(s)]
    assert "Gesamtbild" in titles and "Frühere ETFs" in titles


def test_twr_ignores_deposits(db, market):
    # Konstanter Kurs: Nachkäufe dürfen keine Rendite erzeugen
    add(db, "2025-10-01", "IE000BBBBBB2", "BUY", 100, 20.0)
    add(db, "2026-02-02", "IE000BBBBBB2", "BUY", 200, 20.0)
    refresh_all(db, market)
    s = compute(db)
    assert s["kpis"]["twr_pct"] == pytest.approx(0, abs=1e-6)
    assert s["kpis"]["pnl"] == pytest.approx(0, abs=1e-6)


def test_offline_fallback_and_estimate(db):
    rep = parse_saxo_pages(json.loads(
        (Path(__file__).parent / "fixtures" / "saxo_report_pages.json").read_text(encoding="utf-8")))
    db.add_report(rep)
    h = rep["holdings"][0]
    est = estimate_trade_from_report(rep, h)
    assert est["trade_date"] == "2026-06-30" and est["estimated"]
    db.add_trade(est)
    s = compute(db)  # ohne Refresh: Kurs aus Bericht
    assert s["kpis"]["value"] == pytest.approx(31036.42, abs=1)
    assert s["kpis"]["pnl"] == pytest.approx(619.45, abs=1)
    assert s["kpis"]["price_effect"] + s["kpis"]["fx_effect"] == pytest.approx(619.45, abs=1)
    assert any("geschätzt" in w for w in s["warnings"])


def test_refresh_falls_back_to_justetf(db):
    from tests.conftest import FakeMarket
    add(db, "2025-10-01", "IE000AAAAAA1", "BUY", 10, 10.0)
    res = refresh_all(db, FakeMarket(fail_yahoo=True))
    assert any(st["step"].startswith("Kurse") and st["ok"] and "justETF" in st["message"]
               for st in res["steps"])


def test_api_roundtrip(db, market, tmp_path):
    app = create_app(db)
    c = app.test_client()
    r = c.post("/api/trades", json={"trade_date": "2025-10-01", "isin": "ie000bbbbbb2", "side": "Kauf",
                                    "quantity": "10", "price": "20", "currency": "eur"})
    assert r.status_code == 200
    s = c.get("/api/state").get_json()
    assert s["has_data"] and s["trades"][0]["isin"] == "IE000BBBBBB2"
    tid = s["trades"][0]["id"]
    c.put(f"/api/trades/{tid}", json={"quantity": "12"})
    assert c.get("/api/state").get_json()["trades"][0]["quantity"] == 12
    assert c.get("/").status_code == 200
