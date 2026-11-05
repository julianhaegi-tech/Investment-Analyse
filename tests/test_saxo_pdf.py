import json
from pathlib import Path

import pytest

from saxo_analyse.importers.saxo_pdf import parse_saxo_pages

FIX = Path(__file__).parent / "fixtures" / "saxo_report_pages.json"


@pytest.fixture(scope="module")
def report():
    return parse_saxo_pages(json.loads(FIX.read_text(encoding="utf-8")))


def test_period_and_summary(report):
    assert report["period_start"] == "2025-02-12"
    assert report["period_end"] == "2026-11-04"
    assert report["summary"]["net_deposits"] == 27622.50
    assert report["summary"]["end_value"] == 31047.02
    assert report["summary"]["total_return_pct"] == 15.63


def test_holding(report):
    (h,) = report["holdings"]
    assert h["isin"] == "IE0000ZVYDH0"
    assert h["name"] == "Amundi MSCI ACWI SRI PAB UCITS USD ETF"
    assert h["currency"] == "EUR" and h["quantity"] == 2163
    assert h["open_price"] == pytest.approx(15.21779)
    assert h["cost_basis"] == pytest.approx(30416.97)
    # Einstand CHF = Menge * Ø-Kurs * impliziter FX
    assert h["quantity"] * h["open_price"] * h["implied_fx_at_purchase"] == pytest.approx(30416.97)


def test_quarters_and_instruments(report):
    labels = [q["label"] for q in report["quarters"]]
    assert labels == ["Q4-2025", "Q1-2026", "Q2-2026", "Q3-2026", "Q4-2026"]
    assert report["quarters"][2]["return_pct"] == 19.9
    assert report["quarters"][1]["pnl"] == -1770.62
    assert report["benchmark_name"] == "Switzerland 20"
    names = [i["name"] for i in report["instrument_pnl"]]
    assert len(names) == 5 and "UBS Gold ETF" in names
    assert sum(i["pnl"] for i in report["instrument_pnl"]) == pytest.approx(3424.52)


def test_value_table_and_costs(report):
    vt = report["value_table"]
    assert [r["account"] for r in vt][-1] == 31047.02
    assert all(abs(r["cash"] + r["positions"] + r["accruals"] - r["account"]) < 0.02 for r in vt)
    c = report["costs"]
    assert c["total"] == 509.68 and c["fx_conversion"] == 223.92
    assert c["stamp_duty_foreign"] == 134.32 and c["stamp_duty_domestic"] == 1.5
