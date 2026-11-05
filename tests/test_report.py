import pytest

from portfolio.report import num, to_date


def test_number_and_date_formats():
    assert num("31.036,42") == 31036.42
    assert num("2.163") == 2163 and num("2.002") == 2002
    assert num("-3") == -3 and num("15,218") == 15.218 and num("-") is None
    assert to_date("04-Mrz-2026") == "2026-03-04" and to_date("17-Okt-2025") == "2025-10-17"
    assert to_date("24-Jun-2026") == "2026-06-24"


def test_transactions(report):
    tx = report["transactions"]
    assert len(tx) == 21
    assert sum(t["amount_chf"] for t in tx) == pytest.approx(10.60)          # = Barguthaben
    assert sum(t["amount_chf"] for t in tx if t["kind"] == "deposit") == pytest.approx(27622.50)
    assert sum(t["costs_chf"] for t in tx) == pytest.approx(232.65)
    assert sum(t["total_costs_chf"] for t in tx) == pytest.approx(456.39)
    acwi = [t for t in tx if t["instrument"] and "ACWI" in t["instrument"]]
    assert sum(t["qty"] for t in acwi) == 2163


def test_holdings_closed_overview(report):
    (h,) = report["holdings"]
    assert h["isin"] == "IE0000ZVYDH0" and h["symbol"] == "WELA:xetr" and h["qty"] == 2163
    assert h["value_chf"] == pytest.approx(31036.42)
    assert sum(c["realized_chf"] for c in report["closed"]) == pytest.approx(2878.75)
    ov = report["overview"]
    assert ov["account_value"] == pytest.approx(31047.02) and ov["pnl"] == pytest.approx(3424.52)
    assert report["period_start"] == "2025-01-01" and report["period_end"] == "2026-11-04"
