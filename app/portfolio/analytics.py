"""Berechnungen auf Basis des Transaktionsberichts (+ optionale Marktkurse)."""

from __future__ import annotations

import math
from collections import defaultdict
from typing import Any

import numpy as np
import pandas as pd

from .market import instrument_list
from .store import Store


def _s(points: list[tuple[str, float]]) -> pd.Series:
    if not points:
        return pd.Series(dtype=float, index=pd.DatetimeIndex([]))
    s = pd.Series({pd.Timestamp(d): v for d, v in points}, dtype=float).sort_index()
    return s[~s.index.duplicated(keep="last")]


def xirr(flows: list[tuple[pd.Timestamp, float]]) -> float | None:
    flows = [(d, v) for d, v in flows if abs(v) > 1e-9]
    if len(flows) < 2 or not any(v > 0 for _, v in flows) or not any(v < 0 for _, v in flows):
        return None
    t0 = min(d for d, _ in flows)
    yrs = np.array([(d - t0).days / 365.25 for d, _ in flows])
    vals = np.array([v for _, v in flows])
    if yrs.max() <= 0:
        return None
    f = lambda r: float(np.sum(vals / (1 + r) ** yrs))  # noqa: E731
    lo, hi = -0.99, 10.0
    if f(lo) * f(hi) > 0:
        return None
    for _ in range(200):
        mid = (lo + hi) / 2
        if f(lo) * f(mid) <= 0:
            hi = mid
        else:
            lo = mid
    return (lo + hi) / 2


def _daily(series: pd.Series, idx: pd.DatetimeIndex, anchors: dict[pd.Timestamp, float] | None = None,
           interpolate: bool = False) -> pd.Series:
    """Tageswerte auf idx. Fehlende Marktdaten werden mit Ankerpunkten (Trade-Kursen) ergänzt."""
    s = series.copy()
    for d, v in (anchors or {}).items():
        if s.empty or d < s.index.min() or d > s.index.max():
            s.loc[d] = v
    s = s.sort_index()
    s = s[~s.index.duplicated(keep="last")]
    if s.empty:
        return pd.Series(np.nan, index=idx)
    full = s.reindex(s.index.union(idx))
    full = full.interpolate(method="time") if interpolate else full.ffill()
    return full.bfill().reindex(idx)


def analyse(store: Store) -> dict[str, Any] | None:
    rep = store.report()
    if not rep:
        return None
    settings = store.settings()
    txs = rep["transactions"]
    insts = {i["name"]: i for i in instrument_list(rep)}
    holdings = {h["instrument"]: h for h in rep.get("holdings", [])}
    end_report = pd.Timestamp(rep.get("period_end") or txs[-1]["date"])

    # ------------------------------------------------------------------ Positionen (Durchschnittskosten)
    pos: dict[str, dict[str, Any]] = {}
    for t in txs:
        if t["kind"] not in ("buy", "sell"):
            continue
        p = pos.setdefault(t["instrument"], {
            "name": t["instrument"], "currency": t["currency"], "qty": 0.0, "cost_chf": 0.0, "cost_ccy": 0.0,
            "bought_chf": 0.0, "sold_chf": 0.0, "realized_chf": 0.0, "costs_chf": 0.0, "total_costs_chf": 0.0,
            "periods": [], "trades": [], "_open_since": None})
        p["costs_chf"] += t["costs_chf"]
        p["total_costs_chf"] += t["total_costs_chf"]
        p["trades"].append(t)
        if t["kind"] == "buy":
            if p["qty"] <= 1e-9:
                p["_open_since"] = t["date"]
            p["qty"] += t["qty"]
            p["cost_chf"] += -t["amount_chf"]
            p["cost_ccy"] += t["qty"] * t["price"]
            p["bought_chf"] += -t["amount_chf"]
        else:
            q = min(t["qty"], p["qty"])
            avg_chf = p["cost_chf"] / p["qty"] if p["qty"] else 0
            avg_ccy = p["cost_ccy"] / p["qty"] if p["qty"] else 0
            p["realized_chf"] += t["amount_chf"] - q * avg_chf
            p["sold_chf"] += t["amount_chf"]
            p["qty"] -= q
            p["cost_chf"] -= q * avg_chf
            p["cost_ccy"] -= q * avg_ccy
            if p["qty"] <= 1e-9:
                p["periods"].append((p["_open_since"], t["date"]))
                p["qty"] = p["cost_chf"] = p["cost_ccy"] = 0.0
    for p in pos.values():
        if p["qty"] > 1e-9:
            p["periods"].append((p["_open_since"], None))

    # ------------------------------------------------------------------ Tagesreihen
    price_series = {n: _s(store.series(f"PX:{n}")) for n in pos}
    has_market = all(not s.empty for n, s in price_series.items())
    last_dates = [s.index.max() for s in price_series.values() if not s.empty]
    end = max([end_report] + last_dates)
    start = pd.Timestamp(txs[0]["date"])
    idx = pd.bdate_range(start, end).union(pd.DatetimeIndex(sorted({pd.Timestamp(t["date"]) for t in txs})))

    fx_cache: dict[str, pd.Series] = {}

    def fx_daily(cur: str) -> pd.Series:
        if cur == "CHF":
            return pd.Series(1.0, index=idx)
        if cur not in fx_cache:
            anchors = {pd.Timestamp(t["date"]): t["fx"] for t in txs if t["currency"] == cur and t.get("fx")}
            for h in holdings.values():  # exakter Kurs aus Marktwert (im Bericht ist FX auf 4 Stellen gerundet)
                if h["currency"] == cur and h.get("qty") and h.get("price") and h.get("value_chf"):
                    anchors[end_report] = h["value_chf"] / (h["qty"] * h["price"])
            market_fx = _s(store.series(f"FX:{cur}"))
            fx_cache[cur] = _daily(market_fx, idx, anchors, interpolate=market_fx.empty)
        return fx_cache[cur]

    values = pd.DataFrame(0.0, index=idx, columns=list(pos))
    for name, p in pos.items():
        qty = pd.Series(0.0, index=idx)
        for t in p["trades"]:
            qty.loc[pd.Timestamp(t["date"]):] += t["qty"] if t["kind"] == "buy" else -t["qty"]
        anchors = {pd.Timestamp(t["date"]): t["price"] for t in p["trades"]}
        if name in holdings and holdings[name].get("price"):
            anchors[end_report] = holdings[name]["price"]
        px = _daily(price_series[name], idx, anchors, interpolate=price_series[name].empty)
        values[name] = (qty.clip(lower=0) * px * fx_daily(p["currency"])).fillna(0.0)
        p["price_now"] = float(px.iloc[-1])
        p["fx_now"] = float(fx_daily(p["currency"]).iloc[-1])

    flows = pd.Series(0.0, index=idx)
    cash = pd.Series(0.0, index=idx)
    for t in txs:
        d = pd.Timestamp(t["date"])
        cash.loc[d] += t["amount_chf"]
        if t["kind"] in ("deposit", "withdrawal"):
            flows.loc[d] += t["amount_chf"]
    cash = cash.cumsum()
    deposits = flows.cumsum()
    total = values.sum(axis=1) + cash

    # Einzahlungen zählen ab Tagesbeginn (werden am selben Tag investiert): r = V_t / (V_t-1 + Einzahlung_t) - 1
    prev = total.shift(1).fillna(0.0)
    base = prev + flows
    r = (total / base - 1).where(base > 1e-6, 0.0).replace([np.inf, -np.inf], 0.0).fillna(0.0)
    twr = (1 + r).cumprod()
    dd = twr / twr.cummax() - 1

    # ------------------------------------------------------------------ Positionen fertigstellen
    positions = []
    for name, p in pos.items():
        info = insts.get(name, {})
        open_ = p["qty"] > 1e-9
        value = float(values[name].iloc[-1]) if open_ else 0.0
        unreal = value - p["cost_chf"] if open_ else 0.0
        row = {
            "name": name, "isin": info.get("isin"), "currency": p["currency"], "open": open_,
            "qty": p["qty"], "value_chf": value, "bought_chf": p["bought_chf"], "sold_chf": p["sold_chf"],
            "realized_chf": p["realized_chf"], "unrealized_chf": unreal, "pnl_chf": p["realized_chf"] + unreal,
            "costs_chf": p["costs_chf"], "total_costs_chf": p["total_costs_chf"], "periods": p["periods"],
            "first_buy": p["trades"][0]["date"], "last_trade": p["trades"][-1]["date"],
            "price_now": p["price_now"], "fx_now": p["fx_now"],
        }
        held_days = sum(((pd.Timestamp(b) if b else end) - pd.Timestamp(a)).days for a, b in p["periods"])
        row["held_days"] = held_days
        row["return_pct"] = row["pnl_chf"] / p["bought_chf"] * 100 if p["bought_chf"] else None
        if open_ and p["cost_ccy"] > 0:
            avg_price = p["cost_ccy"] / p["qty"]
            buys = [t for t in p["trades"] if t["kind"] == "buy"]
            avg_fx = sum(t["qty"] * t["price"] * t["fx"] for t in buys) / sum(t["qty"] * t["price"] for t in buys)
            row.update({
                "avg_price": avg_price, "avg_fx": avg_fx,
                "price_effect": p["qty"] * (p["price_now"] - avg_price) * avg_fx,
                "fx_effect": p["qty"] * p["price_now"] * (p["fx_now"] - avg_fx),
            })
            row["buy_costs"] = unreal - row["price_effect"] - row["fx_effect"]
        positions.append(row)
    positions.sort(key=lambda r: (not r["open"], r["first_buy"]))

    # ------------------------------------------------------------------ Kennzahlen
    days = max((idx[-1] - idx[0]).days, 1)
    value_now = float(total.iloc[-1])
    dep = float(deposits.iloc[-1])
    irr = xirr([(d, -v) for d, v in flows.items() if v] + [(idx[-1], value_now)])
    active = r[base > 1e-6].iloc[1:]
    vol = float(active.std() * math.sqrt(252)) if has_market and len(active) > 20 else None
    twr_total = float(twr.iloc[-1] - 1)
    ann = (1 + twr_total) ** (365.25 / days) - 1
    rf = float(settings.get("risk_free_pct") or 0) / 100
    open_pos = [p for p in positions if p["open"]]
    kpi = {
        "value": value_now, "deposits": dep, "pnl": value_now - dep,
        "pnl_pct": (value_now - dep) / dep * 100 if dep else None,
        "realized": sum(p["realized_chf"] for p in positions),
        "unrealized": sum(p["unrealized_chf"] for p in open_pos),
        "price_effect": sum(p.get("price_effect", 0) for p in open_pos),
        "fx_effect": sum(p.get("fx_effect", 0) for p in open_pos),
        "buy_costs_open": sum(p.get("buy_costs", 0) for p in open_pos),
        "costs": sum(p["costs_chf"] for p in positions),
        "total_costs": sum(p["total_costs_chf"] for p in positions),
        "cash": float(cash.iloc[-1]), "irr_pct": irr * 100 if irr is not None else None,
        "twr_pct": twr_total * 100, "twr_pa_pct": ann * 100 if days >= 365 else None,
        "max_dd_pct": float(dd.min()) * 100, "max_dd_date": dd.idxmin() if dd.min() < 0 else None,
        "vol_pct": vol * 100 if vol else None, "sharpe": (ann - rf) / vol if vol else None,
        "start": idx[0], "end": idx[-1], "days": days, "n_trades": sum(1 for t in txs if t["kind"] in ("buy", "sell")),
    }

    monthly = twr.resample("ME").last()
    monthly_ret = monthly.pct_change()
    if len(monthly):
        monthly_ret.iloc[0] = monthly.iloc[0] - 1

    # ------------------------------------------------------------------ Benchmarks (gleiche Einzahlungen)
    benchmarks = []
    for bm in settings.get("benchmarks", []):
        s = _s(store.series(f"BM:{bm['symbol']}"))
        if s.empty:
            continue
        cur = (store.series_meta(f"BM:{bm['symbol']}") or {}).get("currency") or "CHF"
        s = _daily(s, idx) * (fx_daily(cur) if cur != "CHF" else 1.0)
        units = (flows / s).cumsum()
        benchmarks.append({"label": bm["label"], "twr": s / s.iloc[0] - 1, "value": units * s,
                           "total_pct": float(s.iloc[-1] / s.iloc[0] - 1) * 100})

    # ------------------------------------------------------------------ Umschichtungen & Kosten
    by_day: dict[str, dict[str, Any]] = defaultdict(lambda: {"sold": [], "bought": [], "sold_chf": 0.0,
                                                             "bought_chf": 0.0, "costs": 0.0})
    for t in txs:
        if t["kind"] in ("buy", "sell"):
            d = by_day[t["date"]]
            if t["kind"] == "sell":
                d["sold"].append(t["instrument"])
                d["sold_chf"] += t["amount_chf"]
            else:
                d["bought"].append(t["instrument"])
                d["bought_chf"] += -t["amount_chf"]
            d["costs"] += t["total_costs_chf"]
    switches = [{"date": d, **v, "sold": sorted(set(v["sold"])), "bought": sorted(set(v["bought"]))}
                for d, v in sorted(by_day.items()) if v["sold"] and v["bought"]]

    book = rep.get("bookings") or {}
    commission = -sum(v for k, v in book.items() if "provision" in k.lower())
    stamp = -sum(v for k, v in book.items() if "stempel" in k.lower())
    cost_kinds = {"Courtage": commission or None, "Stempelsteuer": stamp or None,
                  "Devisen & übrige": kpi["total_costs"] - kpi["costs"]}

    # ------------------------------------------------------------------ Zusammensetzung (offene ETFs)
    exposure: dict[str, list[dict]] = {}
    total_open = sum(p["value_chf"] for p in open_pos) or 1.0
    sources = set()
    for p in open_pos:
        if not p.get("isin"):
            continue
        for kind, rows in store.exposures(p["isin"]).items():
            agg = {e["name"]: e for e in exposure.get(kind, [])}
            for e in rows:
                w = e["weight"] * p["value_chf"] / total_open
                agg.setdefault(e["name"], {"name": e["name"], "weight": 0.0})["weight"] += w
                sources.add(f"{e['source']} ({e['as_of']})")
            exposure[kind] = sorted(agg.values(), key=lambda x: -x["weight"])
    for rows in exposure.values():
        for e in rows:
            e["value_chf"] = e["weight"] / 100 * total_open

    return {
        "report": rep, "settings": settings, "positions": positions, "kpi": kpi, "has_market": has_market,
        "daily": pd.DataFrame({"Depotwert": total, "Einzahlungen": deposits, "Cash": cash}),
        "values": values, "twr": twr - 1, "drawdown": dd, "monthly": monthly_ret.dropna(),
        "benchmarks": benchmarks, "switches": switches, "cost_kinds": cost_kinds,
        "exposure": exposure, "exposure_sources": sorted(sources),
        "etf_meta": {p["isin"]: store.etf_meta(p["isin"]) for p in open_pos if p.get("isin")},
        "price_series": price_series, "last_refresh": store.last_refresh(),
    }
