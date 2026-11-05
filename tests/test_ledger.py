"""Saxo-Export «Aggregierte Beträge» – synthetische Daten (keine echten Kontodaten)."""

import io

import pandas as pd
import pytest

from saxo_analyse.analytics import compute
from saxo_analyse.app import _import_ledger, create_app
from saxo_analyse.importers.saxo_ledger import is_ledger_workbook, parse_ledger, yahoo_symbol
from saxo_analyse.insights import build_insights

HDR = ["Datum", "Buchungskonto", "Kontowährung", "Kundenwährung", "Betragsartbezeichnung",
       "Auswirkung auf Saldo", "Assetklasse", "Vereinheitlichter Instrumentencode (UIC)",
       "Instrument-Symbol", "Instrumentbeschreibung", "Betrag", "Betrag in Kontowährung"]


def row(d, typ, sym, name, amt, chf, asset="Etf"):
    return [d, "00000/000000", "CHF", "CHF", typ, "No", asset, 1, sym, name, amt, chf]


def build_workbook() -> bytes:
    """ETF A (EUR, Paris) 3 Tage, dann Wechsel in ETF B (EUR, Xetra)."""
    A, B = ("AAA:xpar", "ETF A"), ("BBB:xetr", "ETF B")
    rows = [
        row("01-10-2025", "Cash Amount", "CASHDEPWI", "Deposits", 1000, 1000, asset="Cash"),
        row("01-10-2025", "Share Amount", *A, -1000, -950),
        row("01-10-2025", "Commission", *A, -5, -4.75),
        row("01-10-2025", "Position Values", *A, 1000, 950),
        row("01-10-2025", "Net P/L", *A, -5, -4.75),
        row("01-10-2025", "Cash", "", "", 45.25, 45.25, asset=None),
        row("02-10-2025", "Position Values", *A, 1100, 1045),
        row("02-10-2025", "Net P/L", *A, 100, 95),
        row("02-10-2025", "Cash", "", "", 45.25, 45.25, asset=None),
        # Wechsel: A verkaufen (1045 CHF), B kaufen (1040 CHF)
        row("03-10-2025", "Share Amount", *A, 1100, 1045),
        row("03-10-2025", "Commission", *A, -5, -4.75),
        row("03-10-2025", "Net P/L", *A, -5, -4.75),
        row("03-10-2025", "Share Amount", *B, -1094.74, -1040),
        row("03-10-2025", "Swiss Stamp Duty Foreign", *B, -1.6, -1.52),
        row("03-10-2025", "CurrencyConversion", *B, 0, -2.0),
        row("03-10-2025", "Position Values", *B, 1094.74, 1040),
        row("03-10-2025", "Net P/L", *B, -1.6, -1.52),
        row("03-10-2025", "Cash", "", "", 43.98, 43.98, asset=None),
    ]
    main = pd.DataFrame(rows, columns=HDR)
    perf = pd.DataFrame({
        "Datum": ["01-10-2025", "02-10-2025", "03-10-2025"],
        "AccumulatedTimeWeightedTimeSeries": [-0.475, 9.0, 8.5],
        "AccountValueTimeSeries": [995.25, 1090.25, 1083.98],
        "SecurityTransferTimeSeries": [0, 0, 0],
        "CashTransferTimeSeries": [1000, 1000, 1000],
        "% daily returns": [0, 0.0954, -0.0058],
    })
    buf = io.BytesIO()
    with pd.ExcelWriter(buf) as xw:
        main.to_excel(xw, sheet_name="Aggregierte Beträge", index=False)
        perf.to_excel(xw, sheet_name="Performance", index=False)
    return buf.getvalue()


def test_detect_and_parse():
    wb = build_workbook()
    assert is_ledger_workbook(wb)
    led = parse_ledger(wb)
    assert led["period_start"] == "2025-10-01" and led["period_end"] == "2025-10-03"
    assert {i["symbol"] for i in led["instruments"]} == {"AAA:xpar", "BBB:xetr"}
    assert sum(d["amount_chf"] for d in led["deposits"]) == 1000
    assert yahoo_symbol("WELA:xetr") == "WELA.DE" and yahoo_symbol("SUSW:xswx") == "SUSW.SW"
    assert next(i for i in led["instruments"] if i["symbol"] == "AAA:xpar")["currency"] == "EUR"


def test_ledger_analysis(db):
    _import_ledger(db, build_workbook())
    s = compute(db)
    k = s["kpis"]
    assert s["mode"] == "saxo_ledger"
    assert k["value"] == pytest.approx(1083.98) and k["net_invested"] == 1000
    assert k["pnl"] == pytest.approx(83.98)
    assert k["twr_pct"] == pytest.approx(8.5)
    a = next(p for p in s["positions"] if p["saxo_symbol"] == "AAA:xpar")
    b = next(p for p in s["positions"] if p["saxo_symbol"] == "BBB:xetr")
    assert not a["open"] and a["total_pnl"] == pytest.approx(85.5)       # Summe Net P/L
    assert b["open"] and b["market_value"] == pytest.approx(1040)
    assert b["unrealized_pnl"] == pytest.approx(0) and b["open_fees"] == pytest.approx(1.52)
    assert s["ledger_costs"]["commission"] == pytest.approx(9.5)
    assert s["ledger_costs"]["fx_conversion"] == pytest.approx(2.0)
    (sw,) = s["switches"]
    assert sw["sold"] == pytest.approx(1045) and sw["bought"] == pytest.approx(1040)
    titles = [i["title"] for i in build_insights(s)]
    assert any(t.startswith("Umschichtung") for t in titles)


def test_extension_with_market_prices(db):
    _import_ledger(db, build_workbook())
    db.save_series("PX:BBB:xetr", [("2025-10-03", 10.0), ("2025-10-06", 11.0)], "EUR", "test")
    db.save_series("FX:EURCHF", [("2025-10-03", 0.95), ("2025-10-06", 0.95)], "CHF", "test")
    s = compute(db)
    # Bestand B (1040 CHF) +10 % -> 1144, Cash 43.98 bleibt
    assert s["kpis"]["value"] == pytest.approx(1144 + 43.98)
    assert s["kpis"]["extended"] is True


def test_import_endpoint_routes_ledger(db):
    c = create_app(db).test_client()
    r = c.post("/api/import", data={"file": (io.BytesIO(build_workbook()), "AggregatedAmounts_x.xlsx")})
    assert r.get_json()["type"] == "ledger"
    assert c.get("/api/state").get_json()["has_data"]
