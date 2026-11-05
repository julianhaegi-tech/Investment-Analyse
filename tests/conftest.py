import sys
from datetime import date, timedelta
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from saxo_analyse.db import Database  # noqa: E402


def bdays(start: date, end: date):
    d = start
    while d <= end:
        if d.weekday() < 5:
            yield d
        d += timedelta(days=1)


class FakeMarket:
    """Deterministische Marktdaten ohne Netzwerk."""

    def __init__(self, fail_yahoo=False):
        self.fail_yahoo = fail_yahoo

    def resolve_symbol(self, isin, currency):
        if self.fail_yahoo:
            raise RuntimeError("offline")
        return {"IE000AAAAAA1": ["AAA.DE"], "IE000BBBBBB2": ["BBB.DE"]}.get(isin, [])

    def yahoo_chart(self, symbol, start):
        if self.fail_yahoo:
            raise RuntimeError("offline")
        end = date(2026, 11, 4)
        days = list(bdays(date(2025, 9, 1), end))
        if symbol == "AAA.DE":  # steigt linear 10 -> 12
            return "EUR", [(d.isoformat(), 10 + 2 * i / (len(days) - 1)) for i, d in enumerate(days)]
        if symbol == "BBB.DE":  # konstant 20
            return "EUR", [(d.isoformat(), 20.0) for d in days]
        if symbol == "^SSMI":
            return "CHF", [(d.isoformat(), 12000 + i) for i, d in enumerate(days)]
        if symbol == "ACWI":
            return "USD", [(d.isoformat(), 100.0) for d in days]
        raise RuntimeError("unknown " + symbol)

    def justetf_chart(self, isin, currency, start):
        return [("2025-10-01", 10.0), ("2026-11-04", 12.0)]

    def justetf_profile(self, isin):
        return {"sector": [("Technologie", 30.0), ("Finanzen", 20.0)],
                "country": [("USA", 60.0), ("Japan", 6.0), ("Schweiz", 2.5)],
                "holding": [("NVIDIA", 5.0), ("Microsoft", 4.0)],
                "meta": {"ter": "0,18% p.a.", "ter_pct": 0.18}}

    def yahoo_holdings(self, symbol):
        return {"sector": [], "holding": []}

    def fx_series(self, base, quote, start):
        days = list(bdays(date(2025, 9, 1), date(2026, 11, 4)))
        rate = {"EUR": 0.95, "USD": 0.80}[base]
        return "fake", [(d.isoformat(), rate) for d in days]


@pytest.fixture
def db(tmp_path):
    return Database(tmp_path / "test.db")


@pytest.fixture
def market():
    return FakeMarket()
