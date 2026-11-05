"""Gratis-Marktdaten. Jede Quelle hat einen Fallback.

* Kurse:          Yahoo Finance (ohne Key)  ->  justETF-Chart-API
* Wechselkurse:   Yahoo Finance (EURCHF=X)  ->  Frankfurter (EZB-Referenzkurse)
* Zusammensetzung (Sektoren/Länder/Top-Positionen):
                  justETF-Profilseite       ->  Yahoo Finance (topHoldings)
"""

from __future__ import annotations

import re
import time
from datetime import date, datetime, timedelta, timezone
from typing import Any

import requests

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) "
      "Chrome/126.0 Safari/537.36")
TIMEOUT = 20

# Bevorzugte Yahoo-Börsen je Handelswährung
EXCHANGE_PREF = {
    "EUR": ["GER", "XETRA", "PAR", "AMS", "MIL", "FRA", "STU", "MUN"],
    "CHF": ["EBS", "VTX"],
    "USD": ["NMS", "NYQ", "PCX", "NGM", "LSE"],
    "GBP": ["LSE"],
}


class MarketData:
    def __init__(self, session: requests.Session | None = None):
        self.s = session or requests.Session()
        self.s.headers.update({"User-Agent": UA, "Accept": "*/*", "Accept-Language": "de-CH,de;q=0.9,en;q=0.8"})
        self._crumb: str | None = None

    # ------------------------------------------------------------------ Yahoo
    def yahoo_search(self, query: str) -> list[dict]:
        r = self.s.get("https://query2.finance.yahoo.com/v1/finance/search",
                       params={"q": query, "quotesCount": 15, "newsCount": 0}, timeout=TIMEOUT)
        r.raise_for_status()
        return [q for q in r.json().get("quotes", []) if q.get("symbol")]

    def yahoo_chart(self, symbol: str, start: date) -> tuple[str | None, list[tuple[str, float]]]:
        p1 = int(datetime.combine(start, datetime.min.time(), tzinfo=timezone.utc).timestamp())
        p2 = int(time.time()) + 86400
        last_err: Exception | None = None
        for host in ("query1", "query2"):
            try:
                r = self.s.get(f"https://{host}.finance.yahoo.com/v8/finance/chart/{symbol}",
                               params={"period1": p1, "period2": p2, "interval": "1d",
                                       "includeAdjustedClose": "true"}, timeout=TIMEOUT)
                r.raise_for_status()
                res = r.json()["chart"]["result"][0]
                cur = res.get("meta", {}).get("currency")
                ts = res.get("timestamp") or []
                closes = res["indicators"]["quote"][0].get("close") or []
                tz_off = res.get("meta", {}).get("gmtoffset", 0) or 0
                pts = []
                for t, c in zip(ts, closes):
                    if c is None:
                        continue
                    d = datetime.fromtimestamp(t + tz_off, tz=timezone.utc).date().isoformat()
                    pts.append((d, float(c)))
                if cur == "GBp":  # Pence -> Pfund
                    cur, pts = "GBP", [(d, v / 100) for d, v in pts]
                if not pts:
                    raise ValueError(f"Keine Kursdaten für {symbol}")
                return cur, _dedupe(pts)
            except Exception as e:  # noqa: BLE001
                last_err = e
        raise RuntimeError(f"Yahoo-Chart {symbol}: {last_err}")

    def resolve_symbol(self, isin: str, currency: str | None) -> list[str]:
        """Kandidaten-Ticker für eine ISIN, sortiert nach passender Börse."""
        quotes = self.yahoo_search(isin)
        pref = EXCHANGE_PREF.get((currency or "").upper(), [])

        def rank(q: dict) -> int:
            ex = (q.get("exchange") or "").upper()
            return pref.index(ex) if ex in pref else len(pref) + 1

        return [q["symbol"] for q in sorted(quotes, key=rank)]

    def _yahoo_crumb(self) -> str:
        if self._crumb:
            return self._crumb
        try:
            self.s.get("https://fc.yahoo.com", timeout=TIMEOUT)
        except requests.RequestException:
            pass
        r = self.s.get("https://query1.finance.yahoo.com/v1/test/getcrumb", timeout=TIMEOUT)
        r.raise_for_status()
        self._crumb = r.text.strip()
        return self._crumb

    def yahoo_holdings(self, symbol: str) -> dict[str, list[tuple[str, float]]]:
        crumb = self._yahoo_crumb()
        r = self.s.get(f"https://query2.finance.yahoo.com/v10/finance/quoteSummary/{symbol}",
                       params={"modules": "topHoldings", "crumb": crumb}, timeout=TIMEOUT)
        r.raise_for_status()
        th = r.json()["quoteSummary"]["result"][0]["topHoldings"]
        sectors = []
        for entry in th.get("sectorWeightings", []):
            for k, v in entry.items():
                w = v.get("raw") if isinstance(v, dict) else v
                if w:
                    sectors.append((YAHOO_SECTORS.get(k, k), float(w) * 100))
        holdings = []
        for h in th.get("holdings", []):
            w = h.get("holdingPercent", {})
            w = w.get("raw") if isinstance(w, dict) else w
            if w:
                holdings.append((h.get("holdingName") or h.get("symbol"), float(w) * 100))
        return {"sector": sectors, "holding": holdings}

    # ---------------------------------------------------------------- justETF
    def justetf_chart(self, isin: str, currency: str, start: date) -> list[tuple[str, float]]:
        r = self.s.get(
            f"https://www.justetf.com/api/etfs/{isin}/performance-chart",
            params={"locale": "de", "currency": currency, "valuesType": "MARKET_VALUE",
                    "reduceData": "false", "includeDividends": "false", "features": "DIVIDENDS",
                    "dateFrom": start.isoformat(), "dateTo": date.today().isoformat()},
            headers={"Accept": "application/json"}, timeout=TIMEOUT)
        r.raise_for_status()
        pts = []
        for p in r.json().get("series", []):
            v = p.get("value")
            v = v.get("raw") if isinstance(v, dict) else v
            if v is not None and p.get("date"):
                pts.append((p["date"][:10], float(v)))
        if not pts:
            raise ValueError("justETF lieferte keine Kurse")
        return _dedupe(pts)

    def justetf_profile(self, isin: str) -> dict[str, Any]:
        r = self.s.get("https://www.justetf.com/de/etf-profile.html", params={"isin": isin},
                       timeout=TIMEOUT)
        r.raise_for_status()
        return parse_justetf_profile(r.text)

    # --------------------------------------------------------------------- FX
    def fx_series(self, base: str, quote: str, start: date) -> tuple[str, list[tuple[str, float]]]:
        try:
            _, pts = self.yahoo_chart(f"{base}{quote}=X", start)
            return "yahoo", pts
        except Exception:  # noqa: BLE001
            pass
        r = self.s.get(f"https://api.frankfurter.app/{start.isoformat()}..",
                       params={"from": base, "to": quote}, timeout=TIMEOUT)
        r.raise_for_status()
        rates = r.json().get("rates", {})
        pts = sorted((d, float(v[quote])) for d, v in rates.items() if quote in v)
        if not pts:
            raise ValueError(f"Keine Wechselkurse {base}/{quote}")
        return "frankfurter (EZB)", pts


YAHOO_SECTORS = {
    "realestate": "Immobilien", "consumer_cyclical": "Zyklische Konsumgüter",
    "basic_materials": "Grundstoffe", "consumer_defensive": "Basiskonsumgüter",
    "technology": "Technologie", "communication_services": "Kommunikation",
    "financial_services": "Finanzen", "utilities": "Versorger", "industrials": "Industrie",
    "energy": "Energie", "healthcare": "Gesundheit",
}


def _dedupe(pts: list[tuple[str, float]]) -> list[tuple[str, float]]:
    d: dict[str, float] = {}
    for k, v in pts:
        d[k] = v
    return sorted(d.items())


def _pct(text: str) -> float | None:
    m = re.search(r"(-?\d+(?:[.,]\d+)?)\s*%", text)
    return float(m.group(1).replace(",", ".")) if m else None


def parse_justetf_profile(html: str) -> dict[str, Any]:
    """Liest Länder, Sektoren, Top-10 und Eckdaten aus einer justETF-Profilseite.

    Bewusst heuristisch: gesucht wird die erste Tabelle nach einer passenden Überschrift.
    """
    from bs4 import BeautifulSoup

    soup = BeautifulSoup(html, "html.parser")
    out: dict[str, Any] = {"country": [], "sector": [], "holding": [], "meta": {}}

    targets = {
        "holding": ("top 10 positionen", "top 10 holdings", "top-10"),
        "country": ("länder", "countries"),
        "sector": ("sektoren", "sectors", "branchen"),
    }
    for heading in soup.find_all(["h2", "h3", "h4"]):
        title = heading.get_text(" ", strip=True).lower()
        for kind, keys in targets.items():
            if out[kind] or not any(title.startswith(k) for k in keys):
                continue
            table = heading.find_next("table")
            if table is None:
                continue
            rows = []
            for tr in table.find_all("tr"):
                cells = [c.get_text(" ", strip=True) for c in tr.find_all(["td", "th"])]
                if len(cells) < 2:
                    continue
                w = _pct(cells[-1])
                name = cells[0].strip()
                if w is not None and name and not name.lower().startswith(("anzeigen", "show")):
                    rows.append((name, w))
            out[kind] = rows

    # Eckdaten (TER, Fondsgrösse, Replikation, Ertragsverwendung, Fondswährung)
    text = soup.get_text("\n", strip=True)
    lines = text.split("\n")
    labels = {
        "ter": ("Gesamtkostenquote (TER)", "Total expense ratio"),
        "fund_size": ("Fondsgrösse", "Fondsgröße", "Fund size"),
        "replication": ("Replikationsmethode", "Replication"),
        "distribution": ("Ertragsverwendung", "Distribution policy"),
        "fund_currency": ("Fondswährung", "Fund currency"),
        "inception": ("Auflagedatum", "Inception"),
        "index": ("Index",),
        "holdings_count": ("Anzahl Positionen", "Holdings"),
    }
    for key, labs in labels.items():
        for i, l in enumerate(lines[:-1]):
            if l in labs:
                out["meta"][key] = lines[i + 1]
                break
    if "ter" in out["meta"]:
        out["meta"]["ter_pct"] = _pct(out["meta"]["ter"])
    h1 = soup.find("h1")
    if h1:
        out["meta"]["name"] = h1.get_text(" ", strip=True)
    return out
