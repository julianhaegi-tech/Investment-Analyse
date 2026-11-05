"""Portfolio-Berechnungen: Zeitreihen, Renditen (TWR/IRR), Risiko, Währungs- und Kosteneffekte."""

from __future__ import annotations

import math
from datetime import date
from typing import Any

import numpy as np
import pandas as pd

from .db import Database

BASE = "CHF"


# --------------------------------------------------------------------------- Helpers
def _series(points: list[tuple[str, float]]) -> pd.Series:
    if not points:
        return pd.Series(dtype=float, index=pd.DatetimeIndex([]))
    s = pd.Series({pd.Timestamp(d): v for d, v in points}, dtype=float).sort_index()
    return s[~s.index.duplicated(keep="last")]


def xirr(cashflows: list[tuple[pd.Timestamp, float]]) -> float | None:
    """Geldgewichtete Rendite p.a. (Zahlungen: negativ = Einzahlung, positiv = Wert/Auszahlung)."""
    cfs = [(d, v) for d, v in cashflows if abs(v) > 1e-9]
    if len(cfs) < 2 or not any(v > 0 for _, v in cfs) or not any(v < 0 for _, v in cfs):
        return None
    t0 = min(d for d, _ in cfs)
    yrs = np.array([(d - t0).days / 365.25 for d, _ in cfs])
    vals = np.array([v for _, v in cfs])
    if yrs.max() < 1 / 365:
        return None

    def npv(r: float) -> float:
        return float(np.sum(vals / (1 + r) ** yrs))

    lo, hi = -0.99, 10.0
    f_lo, f_hi = npv(lo), npv(hi)
    if f_lo * f_hi > 0:
        return None
    for _ in range(200):
        mid = (lo + hi) / 2
        f_mid = npv(mid)
        if abs(f_mid) < 1e-7:
            break
        if f_lo * f_mid < 0:
            hi, f_hi = mid, f_mid
        else:
            lo, f_lo = mid, f_mid
    return (lo + hi) / 2


def _r(x: Any, n: int = 2) -> Any:
    if x is None:
        return None
    if isinstance(x, (float, np.floating)):
        if math.isnan(x) or math.isinf(x):
            return None
        return round(float(x), n)
    return x


def _ts(s: pd.Series, n: int = 2) -> dict[str, list]:
    s = s.dropna()
    return {"x": [d.strftime("%Y-%m-%d") for d in s.index], "y": [round(float(v), n) for v in s.values]}


# --------------------------------------------------------------------------- Inputs
class Inputs:
    def __init__(self, db: Database):
        self.db = db
        self.settings = db.get_settings()
        self.report = db.latest_report()
        self.trades = pd.DataFrame(db.trades())
        self.instruments = {i["isin"]: i for i in db.instruments()}
        if not self.trades.empty:
            self.trades["trade_date"] = pd.to_datetime(self.trades["trade_date"])
            self.trades["currency"] = [
                c or (self.instruments.get(i) or {}).get("currency") or BASE
                for c, i in zip(self.trades["currency"], self.trades["isin"])]

    def fx(self, cur: str | None) -> pd.Series:
        if not cur or cur == BASE:
            return pd.Series(dtype=float)
        s = _series(self.db.load_series(f"FX:{cur}{BASE}"))
        # Ergänzen mit Kursen aus Trades / Bericht, falls offline
        extra = {}
        if not self.trades.empty:
            for _, t in self.trades[(self.trades["currency"] == cur) & self.trades["fx_rate"].notna()].iterrows():
                extra[t["trade_date"]] = t["fx_rate"]
        if self.report:
            for h in self.report.get("holdings", []):
                if h.get("currency") == cur and h.get("fx_rate") and self.report.get("period_end"):
                    extra[pd.Timestamp(self.report["period_end"])] = h["fx_rate"]
        for d, v in extra.items():
            if d not in s.index and (s.empty or d > s.index.max() or d < s.index.min()):
                s.loc[d] = v
        return s.sort_index()

    def price(self, isin: str) -> pd.Series:
        s = _series(self.db.load_series(f"PX:{isin}"))
        if s.empty:  # Offline-Fallback: Trade-Kurse + aktueller Kurs aus dem Bericht
            pts = {}
            if not self.trades.empty:
                for _, t in self.trades[self.trades["isin"] == isin].iterrows():
                    pts[t["trade_date"]] = t["price"]
            if self.report:
                for h in self.report.get("holdings", []):
                    if h.get("isin") == isin and h.get("current_price"):
                        pts[pd.Timestamp(self.report["period_end"])] = h["current_price"]
            s = pd.Series(pts, dtype=float).sort_index()
        return s

    def price_source(self, isin: str) -> str:
        m = self.db.series_meta(f"PX:{isin}")
        return m["source"] if m else "offline (Trade-Kurse / Saxo-Bericht)"


def fx_on(fx: pd.Series, d: pd.Timestamp) -> float:
    if fx.empty:
        return 1.0
    prior = fx[:d]
    return float(prior.iloc[-1] if not prior.empty else fx.iloc[0])


# --------------------------------------------------------------------------- Core
def compute(db: Database) -> dict[str, Any]:
    inp = Inputs(db)
    state: dict[str, Any] = {
        "settings": inp.settings,
        "report": inp.report,
        "last_refresh": db.last_refresh(),
        "trades": [_trade_out(t) for t in db.trades()],
        "instruments": list(inp.instruments.values()),
        "has_data": False,
        "warnings": [],
    }
    ledger = db.ledger()
    if ledger:
        from .ledger_analytics import compute_ledger

        if any(not t.get("estimated") for t in db.trades()):
            state["warnings"].append(
                "Es ist ein Saxo-Export «Aggregierte Beträge» importiert. Er ist massgebend; manuell erfasste "
                "Transaktionen werden in der Auswertung nicht berücksichtigt.")
        return compute_ledger(db, ledger, state)

    if inp.trades.empty:
        if inp.report:
            state["warnings"].append(
                "Keine Transaktionen vorhanden. Importiere den Saxo-Trade-Export oder erfasse Käufe manuell.")
        return state

    tr = inp.trades
    if tr["estimated"].astype(bool).any():
        state["warnings"].append(
            "Mindestens ein Kauf ist aus dem Saxo-Bericht geschätzt (Datum unbekannt). "
            "Für eine exakte Historie den Trade-Export importieren oder das Datum anpassen.")

    start = tr["trade_date"].min().normalize()
    isins = list(dict.fromkeys(tr["isin"]))
    price_series = {i: inp.price(i) for i in isins}
    last_dates = [s.index.max() for s in price_series.values() if not s.empty]
    end = max(last_dates + [tr["trade_date"].max()])
    idx = pd.bdate_range(start, end)
    idx = idx.union(pd.DatetimeIndex(tr["trade_date"].dt.normalize().unique()))

    cur_of = {i: (tr[tr["isin"] == i]["currency"].iloc[0]) for i in isins}
    fx_cache = {c: inp.fx(c) for c in set(cur_of.values())}

    def fx_daily(cur: str) -> pd.Series:
        fx = fx_cache[cur]
        if fx.empty:
            return pd.Series(1.0, index=idx)
        return fx.reindex(fx.index.union(idx)).sort_index().ffill().bfill().reindex(idx)

    values = pd.DataFrame(0.0, index=idx, columns=isins)
    inflow = pd.Series(0.0, index=idx)   # externe Einzahlungen (CHF)
    outflow = pd.Series(0.0, index=idx)  # externe Auszahlungen (CHF) – unbekannt, daher 0
    events: list[tuple[pd.Timestamp, int, float]] = []  # (Datum, 0=Verkauf/1=Kauf, Betrag CHF)
    fees_total = 0.0
    positions: list[dict[str, Any]] = []
    cashflows: list[tuple[pd.Timestamp, float]] = []

    for isin in isins:
        t_i = tr[tr["isin"] == isin].sort_values(["trade_date", "id"])
        cur = cur_of[isin]
        fxd = fx_daily(cur)
        px = price_series[isin]
        pxd = px.reindex(px.index.union(idx)).sort_index().ffill().reindex(idx) if not px.empty \
            else pd.Series(np.nan, index=idx)
        qty = pd.Series(0.0, index=idx)

        # Durchschnittskosten-Methode
        held = cost_ccy = cost_chf = 0.0
        realized = fees = bought_chf = 0.0
        first_buy = last_trade = None
        trade_points = []
        for _, t in t_i.iterrows():
            d = t["trade_date"].normalize()
            fx_t = t["fx_rate"] if pd.notna(t["fx_rate"]) and t["fx_rate"] else (
                1.0 if cur == BASE else fx_on(fx_cache[cur], d))
            gross_chf = t["quantity"] * t["price"] * fx_t
            fee = float(t["fees_chf"] or 0)
            fees += fee
            sign = 1 if t["side"] == "BUY" else -1
            qty.loc[d:] += sign * t["quantity"]
            if pd.isna(pxd.loc[d]):
                pxd.loc[d] = t["price"]
            if t["side"] == "BUY":
                total = float(t["amount_chf"]) if pd.notna(t["amount_chf"]) and t["amount_chf"] else gross_chf + fee
                events.append((d, 1, total))
                held += t["quantity"]
                cost_ccy += t["quantity"] * t["price"]
                cost_chf += total
                bought_chf += total
                first_buy = first_buy or d
            else:
                proceeds = float(t["amount_chf"]) if pd.notna(t["amount_chf"]) and t["amount_chf"] else gross_chf - fee
                events.append((d, 0, proceeds))
                q = min(t["quantity"], held) if held > 0 else 0
                avg_chf = cost_chf / held if held else 0
                avg_ccy = cost_ccy / held if held else 0
                realized += proceeds - q * avg_chf
                held -= q
                cost_chf -= q * avg_chf
                cost_ccy -= q * avg_ccy
            last_trade = d
            trade_points.append({"date": d.strftime("%Y-%m-%d"), "side": t["side"],
                                 "quantity": t["quantity"], "price": t["price"],
                                 "value_chf": round(gross_chf, 2)})
        pxd = pxd.ffill().bfill()
        values[isin] = qty * pxd * fxd
        fees_total += fees
        inst = inp.instruments.get(isin, {})
        names = t_i["name"].dropna()
        name = inst.get("name") or (names.iloc[0] if len(names) else isin)
        p_now, fx_now = float(pxd.iloc[-1]), float(fxd.iloc[-1])
        mv = held * p_now * fx_now
        pos = {
            "isin": isin, "name": inst.get("name") or name, "currency": cur,
            "quantity": round(held, 6), "price": _r(p_now, 4), "fx": _r(fx_now, 5),
            "market_value": _r(mv), "cost_basis": _r(cost_chf), "realized_pnl": _r(realized),
            "unrealized_pnl": _r(mv - cost_chf) if held > 1e-9 else 0.0,
            "fees": _r(fees), "bought_chf": _r(bought_chf),
            "first_buy": first_buy.strftime("%Y-%m-%d") if first_buy is not None else None,
            "last_trade": last_trade.strftime("%Y-%m-%d") if last_trade is not None else None,
            "open": held > 1e-9, "trades": trade_points,
            "price_source": inp.price_source(isin), "symbol": inst.get("yahoo_symbol"),
            "price_series": _ts(px[px.index >= start - pd.Timedelta(days=30)], 4) if not px.empty else None,
        }
        pos["total_pnl"] = _r((pos["realized_pnl"] or 0) + (pos["unrealized_pnl"] or 0))
        if held > 1e-9 and cost_ccy > 0:
            avg_price = cost_ccy / held
            avg_fx = cost_chf / cost_ccy if cost_ccy else 1.0  # inkl. Gebühren
            pos["avg_price"] = _r(avg_price, 5)
            pos["avg_fx"] = _r(avg_fx, 5)
            pos["price_effect"] = _r(held * (p_now - avg_price) * avg_fx)
            pos["fx_effect"] = _r(held * p_now * (fx_now - avg_fx))
            pos["price_change_pct"] = _r((p_now / avg_price - 1) * 100)
        positions.append(pos)

    # Verkaufserlöse bleiben als Cash im Konto und finanzieren spätere Käufe (ETF-Wechsel).
    # Nur der Teil eines Kaufs, der nicht durch Cash gedeckt ist, gilt als neue Einzahlung.
    cash_delta = pd.Series(0.0, index=idx)
    bal = 0.0
    for d, kind, amt in sorted(events, key=lambda e: (e[0], e[1])):
        if kind == 0:
            bal += amt
            cash_delta.loc[d] += amt
        else:
            use = min(bal, amt)
            bal -= use
            cash_delta.loc[d] -= use
            if amt - use > 1e-9:
                inflow.loc[d] += amt - use
                cashflows.append((d, -(amt - use)))
    cash = cash_delta.cumsum()
    total_value = values.sum(axis=1) + cash
    net_invested = (inflow - outflow).cumsum()
    pnl = total_value + outflow.cumsum() - inflow.cumsum()

    # Zeitgewichtete Rendite (TWR): Tagesrenditen bereinigt um Käufe/Verkäufe
    prev = total_value.shift(1)
    daily = (total_value + outflow - inflow) / prev - 1
    daily[(prev <= 1e-6) | prev.isna()] = 0.0
    daily = daily.replace([np.inf, -np.inf], 0).fillna(0)
    twr_index = (1 + daily).cumprod()
    days = max((idx[-1] - idx[0]).days, 1)
    twr_total = twr_index.iloc[-1] - 1
    twr_pa = (1 + twr_total) ** (365.25 / days) - 1 if days >= 365 else None

    irr_flows = cashflows + [(idx[-1], float(total_value.iloc[-1]))]
    irr = xirr(irr_flows)

    active = daily[total_value.shift(1) > 1e-6]
    vol = float(active.std() * math.sqrt(252)) if len(active) > 20 else None
    dd = twr_index / twr_index.cummax() - 1
    max_dd = float(dd.min())
    max_dd_date = dd.idxmin()
    rf = float(inp.settings.get("risk_free_rate") or 0) / 100
    ann_ret = (1 + twr_total) ** (365.25 / days) - 1
    sharpe = (ann_ret - rf) / vol if vol else None

    monthly = twr_index.resample("ME").last().pct_change()
    first_m = twr_index.resample("ME").last()
    if not first_m.empty:
        monthly.iloc[0] = first_m.iloc[0] - 1
    monthly_out = [{"month": d.strftime("%Y-%m"), "return_pct": _r(v * 100)} for d, v in monthly.items()
                   if pd.notna(v)]

    total_in = float(inflow.sum())
    total_out = float(outflow.sum())
    cur_val = float(total_value.iloc[-1])
    total_pnl = cur_val + total_out - total_in

    kpis = {
        "value": _r(cur_val), "invested_total": _r(total_in), "withdrawn_total": _r(total_out),
        "net_invested": _r(total_in - total_out), "pnl": _r(total_pnl),
        "pnl_pct_on_invested": _r(total_pnl / (total_in - total_out) * 100) if total_in - total_out > 0 else None,
        "twr_pct": _r(twr_total * 100), "twr_pa_pct": _r(twr_pa * 100) if twr_pa is not None else None,
        "irr_pct": _r(irr * 100) if irr is not None else None,
        "volatility_pct": _r(vol * 100) if vol else None, "max_drawdown_pct": _r(max_dd * 100),
        "max_drawdown_date": max_dd_date.strftime("%Y-%m-%d") if max_dd < 0 else None,
        "sharpe": _r(sharpe), "fees_recorded": _r(fees_total),
        "start": idx[0].strftime("%Y-%m-%d"), "end": idx[-1].strftime("%Y-%m-%d"), "days": days,
        "best_day_pct": _r(active.max() * 100) if len(active) else None,
        "worst_day_pct": _r(active.min() * 100) if len(active) else None,
        "best_day": active.idxmax().strftime("%Y-%m-%d") if len(active) else None,
        "worst_day": active.idxmin().strftime("%Y-%m-%d") if len(active) else None,
        "positive_days_pct": _r((active > 0).mean() * 100) if len(active) else None,
        "n_trades": int(len(tr)), "n_instruments": len(isins),
        "n_open": sum(1 for p in positions if p["open"]),
        "cash": _r(float(cash.iloc[-1])),
    }
    open_pos = [p for p in positions if p["open"]]
    kpis["price_effect"] = _r(sum(p.get("price_effect") or 0 for p in open_pos))
    kpis["fx_effect"] = _r(sum(p.get("fx_effect") or 0 for p in open_pos))
    kpis["realized_pnl"] = _r(sum(p["realized_pnl"] or 0 for p in positions))
    kpis["unrealized_pnl"] = _r(sum(p["unrealized_pnl"] or 0 for p in open_pos))

    state.update({
        "has_data": True,
        "kpis": kpis,
        "positions": positions,
        "series": {
            "value": _ts(total_value), "net_invested": _ts(net_invested), "pnl": _ts(pnl),
            "twr_pct": _ts((twr_index - 1) * 100), "drawdown_pct": _ts(dd * 100),
            "by_instrument": {i: _ts(values[i].where(values[i].abs() > 0.005)) for i in isins},
        },
        "monthly": monthly_out,
        "benchmarks": _benchmarks(inp, idx, inflow, outflow, twr_index),
        "exposure": _exposure(db, open_pos),
    })
    state["reconciliation"] = _reconcile(inp, positions)
    return state


def _benchmarks(inp: Inputs, idx: pd.DatetimeIndex, inflow: pd.Series, outflow: pd.Series,
                twr_index: pd.Series) -> list[dict[str, Any]]:
    out = []
    for bm in inp.settings.get("benchmarks", []):
        sym = bm["symbol"]
        s = _series(inp.db.load_series(f"BM:{sym}"))
        if s.empty:
            continue
        meta = inp.db.series_meta(f"BM:{sym}") or {}
        cur = meta.get("currency") or BASE
        fx = inp.fx(cur) if cur != BASE else pd.Series(dtype=float)
        s = s.reindex(s.index.union(idx)).sort_index().ffill().reindex(idx).bfill()
        if not fx.empty:
            fxd = fx.reindex(fx.index.union(idx)).sort_index().ffill().bfill().reindex(idx)
            s = s * fxd
        if s.isna().all():
            continue
        # gleiche Zahlungen in den Benchmark investieren (Was-wäre-wenn)
        units = (inflow / s - outflow / s).cumsum()
        sim_value = units * s
        bench_index = s / s.iloc[0]
        out.append({
            "symbol": sym, "label": bm.get("label") or sym, "currency": cur,
            "twr_pct": _ts((bench_index - 1) * 100),
            "total_pct": _r((bench_index.iloc[-1] - 1) * 100),
            "sim_value": _ts(sim_value), "sim_final": _r(float(sim_value.iloc[-1])),
        })
    return out


def _exposure(db: Database, open_pos: list[dict]) -> dict[str, Any]:
    total = sum(p["market_value"] or 0 for p in open_pos)
    agg: dict[str, dict[str, float]] = {"sector": {}, "country": {}, "holding": {}}
    meta: dict[str, Any] = {"sources": [], "missing": []}
    for p in open_pos:
        ex = db.exposures(p["isin"])
        w_pos = (p["market_value"] or 0) / total if total else 0
        if not ex:
            meta["missing"].append(p["name"])
            continue
        for kind, rows in ex.items():
            for r in rows:
                agg.setdefault(kind, {})
                agg[kind][r["name"]] = agg[kind].get(r["name"], 0) + r["weight"] * w_pos
            meta["sources"].append({"isin": p["isin"], "kind": kind, "source": rows[0]["source"],
                                    "as_of": rows[0]["as_of"]})
    res: dict[str, Any] = {"meta": meta}
    for kind, d in agg.items():
        rows = sorted(d.items(), key=lambda kv: -kv[1])
        res[kind] = [{"name": n, "weight_pct": _r(w), "value_chf": _r(w / 100 * total)} for n, w in rows]
    return res


def _reconcile(inp: Inputs, positions: list[dict]) -> list[dict]:
    """Vergleicht die aus Trades berechneten Bestände mit dem Saxo-Bericht."""
    if not inp.report:
        return []
    out = []
    by_isin = {p["isin"]: p for p in positions}
    for h in inp.report.get("holdings", []):
        p = by_isin.get(h.get("isin"))
        q_calc = p["quantity"] if p else 0
        out.append({"isin": h.get("isin"), "name": h.get("name"), "report_qty": h.get("quantity"),
                    "calc_qty": q_calc, "ok": abs((h.get("quantity") or 0) - q_calc) < 1e-6})
    return out


def _trade_out(t: dict) -> dict:
    return {**t, "estimated": bool(t.get("estimated"))}


def estimate_trade_from_report(report: dict, holding: dict) -> dict:
    """Erzeugt einen geschätzten Kauf aus einer Bestandsposition des Saxo-Berichts.

    Datum: erster Stichtag, an dem der Positionswert ~90 % des heutigen Einstandswerts erreichte.
    """
    cost = holding.get("cost_basis") or (holding["quantity"] * holding["open_price"])
    guess = report.get("period_start") or date.today().isoformat()
    for row in report.get("value_table", []):
        if (row.get("positions") or 0) >= 0.9 * cost:
            guess = row["date"]
            break
    return {
        "trade_date": guess, "isin": holding["isin"], "name": holding.get("name"), "side": "BUY",
        "quantity": holding["quantity"], "price": holding["open_price"],
        "currency": holding.get("currency"), "fx_rate": holding.get("implied_fx_at_purchase"),
        "fees_chf": 0.0, "amount_chf": cost, "source": "saxo_report_estimate",
        "note": "Aus Saxo-Bericht geschätzt (Ø-Kurs, Datum unbekannt) – bitte prüfen",
        "estimated": True,
    }
