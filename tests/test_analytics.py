import pytest

from portfolio.analytics import analyse, xirr
from portfolio.insights import insights
from portfolio.market import Market, refresh, saxo_to_yahoo


def test_matches_saxo_without_market_data(store):
    a = analyse(store)
    k = a["kpi"]
    assert k["value"] == pytest.approx(31047.02, abs=0.02)
    assert k["deposits"] == pytest.approx(27622.50)
    assert k["pnl"] == pytest.approx(3424.52, abs=0.02)
    assert k["realized"] == pytest.approx(2878.75, abs=0.01)
    assert k["unrealized"] == pytest.approx(545.77, abs=0.02)
    assert k["price_effect"] + k["fx_effect"] + k["buy_costs_open"] == pytest.approx(545.77, abs=0.05)
    assert k["total_costs"] == pytest.approx(456.39)
    assert not a["has_market"]
    names = {p["name"]: p for p in a["positions"]}
    assert names["UBS Gold ETF"]["realized_chf"] == pytest.approx(-91.44)
    assert not names["Amundi MSCI EM SRI Climate Paris Aligned UCITS ETF"]["open"]
    assert [s["date"] for s in a["switches"]] == ["2026-01-21", "2026-06-24"]
    assert -10 < a["twr"].min() * 100 < 0          # keine Ausreisser durch Einzahlungen
    assert any(t == "Gesamtbild" for _, t, _ in insights(a))


def test_xirr():
    import pandas as pd
    assert xirr([(pd.Timestamp("2025-01-01"), -100), (pd.Timestamp("2026-01-01"), 110)]) == pytest.approx(0.1, abs=1e-3)


def test_saxo_symbols():
    assert saxo_to_yahoo("WELA:xetr") == "WELA.DE" and saxo_to_yahoo("AUUSIC:xswx") == "AUUSIC.SW"


class Fake(Market):
    def __init__(self):
        super().__init__()

    def yahoo_search(self, q, cur=None):
        raise RuntimeError("offline")

    def yahoo_chart(self, s, start):
        if s == "WELA.DE":
            return "EUR", [("2026-06-24", 15.2), ("2026-11-04", 15.676), ("2026-11-05", 16.0)]
        raise RuntimeError("nicht gefunden")

    def justetf_chart(self, isin, cur, start):
        raise RuntimeError("offline")

    def justetf_profile(self, isin):
        return {"sector": [("Technologie", 25.0)], "country": [("USA", 60.0)], "holding": [("NVIDIA", 5.0)], "meta": {}}

    def fx(self, b, q, start):
        return "test", [("2026-06-24", 0.924), ("2026-11-05", 0.9153)]


def test_refresh_partial_failure_still_analyses(store):
    steps = refresh(store, Fake())
    assert any(s["ok"] and "WELA.DE" in s["msg"] for s in steps)
    assert any(not s["ok"] for s in steps)      # andere ETFs ohne Ticker -> Hinweis statt Absturz
    a = analyse(store)
    assert a["kpi"]["value"] > 31047               # bis 05.11. fortgeschrieben
    assert a["exposure"]["country"][0]["name"] == "USA"
