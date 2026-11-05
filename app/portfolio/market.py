"""Kostenlose Marktdaten (ohne API-Key) und der «Aktualisieren»-Ablauf.

Kurse:        Yahoo Finance            (Fallback: justETF, für ETFs mit ISIN)
Wechselkurse: EZB über frankfurter.app (Fallback: Yahoo)
Sektoren/Länder/Top-10: justETF-Profilseite (Fallback: Yahoo)
"""

from __future__ import annotations

import re
import time
from datetime import date, datetime, timedelta, timezone
from typing import Any

import requests

from .store import Store

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36"
TIMEOUT = 20
EXCHANGE_SUFFIX = {"xetr": ".DE", "xfra": ".F", "xpar": ".PA", "xmil": ".MI", "xams": ".AS", "xswx": ".SW",
                   "xvtx": ".SW", "xlon": ".L", "xbru": ".BR", "xmad": ".MC", "xwbo": ".VI"}
EXCHANGE_PREF = {"EUR": ["GER", "PAR", "MIL", "AMS", "FRA"], "CHF": ["EBS", "VTX"], "USD": ["NYQ", "PCX", "NMS"]}


def saxo_to_yahoo(symbol: str | None) -> str | None:
    if not symbol or ":" not in symbol:
        return None
    tick, ex = symbol.split(":", 1)
    suffix = EXCHANGE_SUFFIX.get(ex.lower())
    return tick.upper() + suffix if suffix is not None else None


class Market:
    def __init__(self, session: requests.Session | None = None):
        self.s = session or requests.Session()
        self.s.headers.update({"User-Agent": UA, "Accept-Language": "de-CH,de;q=0.9,en;q=0.8"})
        self._crumb: str | None = None

    def yahoo_chart(self, symbol: str, start: date) -> tuple[str | None, list[tuple[str, float]]]:
        p1 = int(datetime.combine(start, datetime.min.time(), tzinfo=timezone.utc).timestamp())
        err: Exception | None = None
        for host in ("query1", "query2"):
            try:
                r = self.s.get(f"https://{host}.finance.yahoo.com/v8/finance/chart/{symbol}",
                               params={"period1": p1, "period2": int(time.time()) + 86400, "interval": "1d"},
                               timeout=TIMEOUT)
                r.raise_for_status()
                res = r.json()["chart"]["result"][0]
                cur = res.get("meta", {}).get("currency")
                off = res.get("meta", {}).get("gmtoffset", 0) or 0
                closes = res["indicators"]["quote"][0].get("close") or []
                pts = {datetime.fromtimestamp(t + off, tz=timezone.utc).date().isoformat(): float(c)
                       for t, c in zip(res.get("timestamp") or [], closes) if c is not None}
                if cur == "GBp":
                    cur, pts = "GBP", {d: v / 100 for d, v in pts.items()}
                if not pts:
                    raise ValueError("keine Kurse")
                return cur, sorted(pts.items())
            except Exception as e:  # noqa: BLE001
                err = e
        raise RuntimeError(f"Yahoo {symbol}: {err}")

    def yahoo_search(self, query: str, currency: str | None = None) -> list[str]:
        r = self.s.get("https://query2.finance.yahoo.com/v1/finance/search",
                       params={"q": query, "quotesCount": 10, "newsCount": 0}, timeout=TIMEOUT)
        r.raise_for_status()
        quotes = [q for q in r.json().get("quotes", []) if q.get("symbol") and q.get("quoteType") in ("ETF", "MUTUALFUND", "EQUITY", None)]
        pref = EXCHANGE_PREF.get((currency or "").upper(), [])
        quotes.sort(key=lambda q: pref.index(q.get("exchange")) if q.get("exchange") in pref else 99)
        return [q["symbol"] for q in quotes]

    def justetf_chart(self, isin: str, currency: str, start: date) -> list[tuple[str, float]]:
        r = self.s.get(f"https://www.justetf.com/api/etfs/{isin}/performance-chart",
                       params={"locale": "de", "currency": currency, "valuesType": "MARKET_VALUE",
                               "reduceData": "false", "includeDividends": "false",
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
            raise ValueError("justETF: keine Kurse")
        return pts

    def fx(self, base: str, quote: str, start: date) -> tuple[str, list[tuple[str, float]]]:
        try:
            r = self.s.get(f"https://api.frankfurter.app/{start.isoformat()}..",
                           params={"from": base, "to": quote}, timeout=TIMEOUT)
            r.raise_for_status()
            pts = sorted((d, float(v[quote])) for d, v in r.json().get("rates", {}).items() if quote in v)
            if pts:
                return "EZB (frankfurter.app)", pts
        except Exception:  # noqa: BLE001
            pass
        _, pts = self.yahoo_chart(f"{base}{quote}=X", start)
        return "Yahoo Finance", pts

    def justetf_profile(self, isin: str) -> dict[str, Any]:
        r = self.s.get("https://www.justetf.com/de/etf-profile.html", params={"isin": isin}, timeout=TIMEOUT)
        r.raise_for_status()
        return parse_justetf(r.text)

    def yahoo_holdings(self, symbol: str) -> dict[str, list[tuple[str, float]]]:
        if not self._crumb:
            try:
                self.s.get("https://fc.yahoo.com", timeout=TIMEOUT)
            except requests.RequestException:
                pass
            self._crumb = self.s.get("https://query1.finance.yahoo.com/v1/test/getcrumb", timeout=TIMEOUT).text.strip()
        r = self.s.get(f"https://query2.finance.yahoo.com/v10/finance/quoteSummary/{symbol}",
                       params={"modules": "topHoldings", "crumb": self._crumb}, timeout=TIMEOUT)
        r.raise_for_status()
        th = r.json()["quoteSummary"]["result"][0]["topHoldings"]
        sectors = [(YAHOO_SECTORS.get(k, k), float((v or {}).get("raw", 0)) * 100)
                   for e in th.get("sectorWeightings", []) for k, v in e.items()]
        holds = [(h.get("holdingName") or h.get("symbol"), float(h.get("holdingPercent", {}).get("raw", 0)) * 100)
                 for h in th.get("holdings", [])]
        return {"sector": [s for s in sectors if s[1] > 0], "holding": [h for h in holds if h[1] > 0]}


YAHOO_SECTORS = {"realestate": "Immobilien", "consumer_cyclical": "Zyklischer Konsum", "basic_materials": "Rohstoffe",
                 "consumer_defensive": "Basiskonsum", "technology": "Technologie", "communication_services": "Kommunikation",
                 "financial_services": "Finanzen", "utilities": "Versorger", "industrials": "Industrie",
                 "energy": "Energie", "healthcare": "Gesundheit"}


def _pct(text: str) -> float | None:
    m = re.search(r"(-?\d+(?:[.,]\d+)?)\s*%", text)
    return float(m.group(1).replace(",", ".")) if m else None


def parse_justetf(html: str) -> dict[str, Any]:
    from bs4 import BeautifulSoup

    soup = BeautifulSoup(html, "html.parser")
    out: dict[str, Any] = {"country": [], "sector": [], "holding": [], "meta": {}}
    targets = {"holding": ("top 10 positionen", "top 10 holdings"), "country": ("länder", "countries"),
               "sector": ("sektoren", "sectors")}
    for h in soup.find_all(["h2", "h3", "h4"]):
        title = h.get_text(" ", strip=True).lower()
        for kind, keys in targets.items():
            if out[kind] or not title.startswith(keys):
                continue
            table = h.find_next("table")
            for tr in (table.find_all("tr") if table else []):
                cells = [c.get_text(" ", strip=True) for c in tr.find_all(["td", "th"])]
                if len(cells) >= 2 and (w := _pct(cells[-1])) is not None and not cells[0].lower().startswith(("anzeigen", "show")):
                    out[kind].append((cells[0], w))
    lines = soup.get_text("\n", strip=True).split("\n")
    labels = {"ter": "Gesamtkostenquote (TER)", "fund_size": "Fondsgrösse", "replication": "Replikationsmethode",
              "distribution": "Ertragsverwendung", "index": "Index", "inception": "Auflagedatum"}
    for key, lab in labels.items():
        for i, line in enumerate(lines[:-1]):
            if line in (lab, lab.replace("grösse", "größe")):
                out["meta"][key] = lines[i + 1]
                break
    return out


# --------------------------------------------------------------------------- Aktualisieren
def instrument_list(report: dict) -> list[dict[str, Any]]:
    """Alle ETFs aus dem Bericht mit Währung, ISIN und Saxo-Symbol (falls bekannt)."""
    insts: dict[str, dict[str, Any]] = {}
    for t in report.get("transactions", []):
        if t.get("instrument"):
            insts.setdefault(t["instrument"], {"name": t["instrument"], "currency": t["currency"],
                                               "isin": None, "saxo_symbol": None, "open": False})
    for h in report.get("holdings", []):
        i = insts.setdefault(h["instrument"], {"name": h["instrument"], "currency": h["currency"]})
        i.update({"isin": h.get("isin"), "saxo_symbol": h.get("symbol"), "open": True})
    return list(insts.values())


def refresh(store: Store, market: Market | None = None) -> list[dict[str, Any]]:
    market = market or Market()
    report = store.report()
    steps: list[dict[str, Any]] = []
    if not report:
        return [{"step": "Import", "ok": False, "msg": "Noch kein Bericht importiert."}]
    settings = store.settings()
    start = date.fromisoformat(report["transactions"][0]["date"]) - timedelta(days=10)
    currencies: set[str] = set()
    tickers = dict(settings.get("tickers") or {})

    for inst in instrument_list(report):
        name, cur = inst["name"], inst["currency"]
        if cur != "CHF":
            currencies.add(cur)
        candidates = [c for c in (tickers.get(name), saxo_to_yahoo(inst.get("saxo_symbol"))) if c]
        try:
            candidates += market.yahoo_search(inst.get("isin") or name, cur)
        except Exception as e:  # noqa: BLE001
            steps.append({"step": f"Ticker {name}", "ok": False, "msg": f"Suche fehlgeschlagen: {e}"})
        got = False
        for sym in dict.fromkeys(candidates):
            try:
                ccy, pts = market.yahoo_chart(sym, start)
                if ccy and ccy != cur and sym != tickers.get(name):
                    continue
                store.save_series(f"PX:{name}", pts, ccy or cur, f"Yahoo ({sym})")
                tickers.setdefault(name, sym)
                steps.append({"step": f"Kurse {name}", "ok": True, "msg": f"{len(pts)} Tageskurse ({sym})"})
                got = True
                break
            except Exception:  # noqa: BLE001
                continue
        if not got and inst.get("isin"):
            try:
                pts = market.justetf_chart(inst["isin"], cur, start)
                store.save_series(f"PX:{name}", pts, cur, "justETF")
                steps.append({"step": f"Kurse {name}", "ok": True, "msg": f"{len(pts)} Tageskurse (justETF)"})
                got = True
            except Exception as e:  # noqa: BLE001
                steps.append({"step": f"Kurse {name}", "ok": False, "msg": str(e)})
        elif not got:
            steps.append({"step": f"Kurse {name}", "ok": False,
                          "msg": "Kein Ticker gefunden – unter Einstellungen von Hand eintragen."})

        if inst.get("open") and inst.get("isin"):
            try:
                prof = market.justetf_profile(inst["isin"])
                n = 0
                for kind in ("sector", "country", "holding"):
                    if prof[kind]:
                        store.save_exposures(inst["isin"], kind, prof[kind], "justETF")
                        n += len(prof[kind])
                store.save_etf_meta(inst["isin"], prof["meta"])
                if not n:
                    raise ValueError("keine Daten auf der Seite")
                steps.append({"step": f"Zusammensetzung {name}", "ok": True, "msg": f"{n} Einträge (justETF)"})
            except Exception as e:  # noqa: BLE001
                sym = tickers.get(name)
                try:
                    if not sym:
                        raise ValueError("kein Ticker")
                    yh = market.yahoo_holdings(sym)
                    for kind, rows in yh.items():
                        if rows:
                            store.save_exposures(inst["isin"], kind, rows, "Yahoo")
                    if not any(yh.values()):
                        raise ValueError("leer")
                    steps.append({"step": f"Zusammensetzung {name}", "ok": True, "msg": "Yahoo (justETF nicht erreichbar)"})
                except Exception as e2:  # noqa: BLE001
                    steps.append({"step": f"Zusammensetzung {name}", "ok": False, "msg": f"justETF: {e} · Yahoo: {e2}"})

    for bm in settings.get("benchmarks", []):
        try:
            ccy, pts = market.yahoo_chart(bm["symbol"], start)
            store.save_series(f"BM:{bm['symbol']}", pts, ccy, "Yahoo")
            if ccy and ccy != "CHF":
                currencies.add(ccy)
            steps.append({"step": f"Benchmark {bm['label']}", "ok": True, "msg": f"{len(pts)} Kurse"})
        except Exception as e:  # noqa: BLE001
            steps.append({"step": f"Benchmark {bm['label']}", "ok": False, "msg": str(e)})

    for ccy in sorted(currencies):
        try:
            src, pts = market.fx(ccy, "CHF", start)
            store.save_series(f"FX:{ccy}", pts, "CHF", src)
            steps.append({"step": f"Wechselkurs {ccy}/CHF", "ok": True, "msg": f"{len(pts)} Kurse ({src})"})
        except Exception as e:  # noqa: BLE001
            steps.append({"step": f"Wechselkurs {ccy}/CHF", "ok": False, "msg": str(e)})

    store.save_settings(tickers=tickers)
    store.log_refresh(steps)
    return steps
