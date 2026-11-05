from datetime import date

from saxo_analyse.market import MarketData, parse_justetf_profile


class Resp:
    def __init__(self, payload=None, text=""):
        self._p, self.text = payload, text

    def raise_for_status(self):
        pass

    def json(self):
        return self._p


class Session:
    def __init__(self, routes):
        self.routes, self.headers = routes, {}

    def get(self, url, **kw):
        for key, resp in self.routes.items():
            if key in url:
                return resp
        raise RuntimeError("blocked " + url)


def test_yahoo_chart_and_search():
    chart = {"chart": {"result": [{"meta": {"currency": "EUR", "gmtoffset": 3600},
                                   "timestamp": [1767254400, 1767340800, 1767427200],
                                   "indicators": {"quote": [{"close": [15.1, None, 15.3]}]}}]}}
    search = {"quotes": [{"symbol": "X.L", "exchange": "LSE"}, {"symbol": "X.DE", "exchange": "GER"}]}
    md = MarketData(Session({"/chart/": Resp(chart), "/search": Resp(search)}))
    cur, pts = md.yahoo_chart("X.DE", date(2026, 1, 1))
    assert cur == "EUR" and [v for _, v in pts] == [15.1, 15.3]
    assert md.resolve_symbol("IE0000ZVYDH0", "EUR")[0] == "X.DE"


def test_fx_falls_back_to_frankfurter():
    fr = {"rates": {"2026-01-02": {"CHF": 0.93}, "2026-01-05": {"CHF": 0.931}}}
    md = MarketData(Session({"frankfurter": Resp(fr)}))
    src, pts = md.fx_series("EUR", "CHF", date(2026, 1, 1))
    assert "frankfurter" in src and pts[-1] == ("2026-01-05", 0.931)


def test_justetf_chart():
    js = {"series": [{"date": "2026-01-02", "value": {"raw": 15.0}}, {"date": "2026-01-05", "value": 15.2}]}
    md = MarketData(Session({"performance-chart": Resp(js)}))
    assert md.justetf_chart("IE0000ZVYDH0", "EUR", date(2026, 1, 1)) == [("2026-01-02", 15.0), ("2026-01-05", 15.2)]


def test_justetf_profile_parser():
    html = """<html><body><h1>Amundi MSCI ACWI SRI PAB</h1>
    <table><tr><td>Gesamtkostenquote (TER)</td><td>0,18% p.a.</td></tr></table>
    <div>Gesamtkostenquote (TER)</div><div>0,18% p.a.</div>
    <h3>Top 10 Positionen</h3><table><tr><td>NVIDIA Corp.</td><td>5,12%</td></tr><tr><td>Microsoft</td><td>4,50%</td></tr></table>
    <h3>Länder</h3><table><tr><td>USA</td><td>62,10%</td></tr><tr><td>Japan</td><td>6,00%</td></tr><tr><td>Anzeigen mehr</td><td></td></tr></table>
    <h3>Sektoren</h3><table><tr><td>Technologie</td><td>27,30%</td></tr></table></body></html>"""
    p = parse_justetf_profile(html)
    assert p["holding"][0] == ("NVIDIA Corp.", 5.12)
    assert p["country"] == [("USA", 62.1), ("Japan", 6.0)]
    assert p["sector"] == [("Technologie", 27.3)]
    assert p["meta"]["ter_pct"] == 0.18
