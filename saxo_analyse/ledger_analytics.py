"""Auswertung auf Basis des Saxo-Exports «Aggregierte Beträge».

Saxo liefert Tageswerte (Kontowert, TWR, Positionswerte, G/V inkl. aller Kosten). Diese Zahlen sind
massgebend. Nach dem Exportdatum wird der Bestand mit Marktkursen (Refresh) fortgeschrieben.
"""

from __future__ import annotations

import math
from collections import defaultdict
from typing import Any

import numpy as np
import pandas as pd

from .analytics import BASE, Inputs, _benchmarks, _exposure, _r, _series, _ts, xirr
from .db import Database


def ledger_instruments(db: Database, ledger: dict) -> list[dict[str, Any]]:
    """Ordnet jedem Saxo-Instrument einen Schlüssel (ISIN falls bekannt), Yahoo-Ticker und Währung zu."""
    settings = db.get_settings()
    isin_ov = settings.get("isin_overrides") or {}
    sym_ov = settings.get("symbol_overrides") or {}
    report = db.latest_report() or {}
    by_name = {(h.get("name") or "").lower(): h for h in report.get("holdings", []) if h.get("isin")}
    out = []
    for inst in ledger.get("instruments", []):
        sym = inst["symbol"]
        h = by_name.get((inst.get("name") or "").lower())
        isin = isin_ov.get(sym) or (h or {}).get("isin")
        key = isin or sym
        stored = db.get_instrument(key) or {}
        out.append({
            **inst,
            "key": key, "isin": isin,
            "yahoo_symbol": sym_ov.get(key) or sym_ov.get(sym) or stored.get("yahoo_symbol") or inst.get("yahoo_symbol"),
            "currency": inst.get("currency") or stored.get("currency"),
            "report_qty": (h or {}).get("quantity"),
        })
    return out


def compute_ledger(db: Database, ledger: dict, state: dict[str, Any]) -> dict[str, Any]:
    inp = Inputs(db)
    insts = ledger_instruments(db, ledger)
    by_sym = {i["symbol"]: i for i in insts}

    acc = pd.DataFrame(ledger["account"])
    acc["date"] = pd.to_datetime(acc["date"])
    acc = acc.drop_duplicates("date", keep="last").set_index("date").sort_index()
    end_l = acc.index[-1]

    daily = pd.DataFrame(ledger["inst_daily"])
    daily["date"] = pd.to_datetime(daily["date"])
    vchf = daily.pivot_table(index="date", columns="symbol", values="value_chf", aggfunc="last").reindex(acc.index).fillna(0.0)
    vccy = daily.pivot_table(index="date", columns="symbol", values="value_ccy", aggfunc="last").reindex(acc.index).fillna(0.0)
    pnl_chf = daily.pivot_table(index="date", columns="symbol", values="pnl_chf", aggfunc="sum").reindex(acc.index).fillna(0.0)

    # ---------------- Fortschreibung nach dem Exportdatum
    ext_values: dict[str, pd.Series] = {}
    open_syms = [s for s in vchf.columns if vchf[s].iloc[-1] > 0.5]
    ext_idx = None
    px_cache: dict[str, pd.Series] = {}
    for sym in vchf.columns:
        info = by_sym.get(sym, {})
        px = _series(db.load_series(f"PX:{info.get('key', sym)}"))
        px_cache[sym] = px
    for sym in open_syms:
        info = by_sym.get(sym, {})
        px = px_cache[sym]
        if px.empty or px.index.max() <= end_l:
            continue
        cur = (db.series_meta(f"PX:{info['key']}") or {}).get("currency") or info.get("currency")
        fx = inp.fx(cur) if cur and cur != BASE else pd.Series(dtype=float)
        later = px[px.index > end_l]
        p_l = px[:end_l]
        if p_l.empty:
            continue
        p_l = float(p_l.iloc[-1])
        if fx.empty:
            factor = later / p_l
        else:
            fx_d = fx.reindex(fx.index.union(later.index).union([end_l])).sort_index().ffill().bfill()
            factor = (later * fx_d.reindex(later.index)) / (p_l * float(fx_d.loc[end_l]))
        ext_values[sym] = factor * float(vchf[sym].iloc[-1])
        ext_idx = later.index if ext_idx is None else ext_idx.union(later.index)

    cash_last = acc["cash"].dropna().iloc[-1] if "cash" in acc and acc["cash"].notna().any() else \
        float(acc["value"].iloc[-1] - vchf.iloc[-1].sum())
    if ext_idx is not None and len(ext_idx):
        ext = pd.DataFrame(index=ext_idx)
        for sym in open_syms:
            s = ext_values.get(sym)
            ext[sym] = s.reindex(ext_idx).ffill() if s is not None else float(vchf[sym].iloc[-1])
        ext = ext.ffill().fillna(0.0)
        vchf = pd.concat([vchf, ext.reindex(columns=vchf.columns).fillna(0.0)])
        ext_total = ext.sum(axis=1) + cash_last
        value = pd.concat([acc["value"], ext_total])
        transfers = pd.concat([acc["transfers_cum"], pd.Series(acc["transfers_cum"].iloc[-1], index=ext_idx)])
    else:
        value = acc["value"].copy()
        transfers = acc["transfers_cum"].copy()

    # ---------------- Rendite
    if acc["twr_pct"].notna().all():
        twr_index = 1 + acc["twr_pct"] / 100
    else:
        inflow = acc["transfers_cum"].diff().fillna(acc["transfers_cum"].iloc[0])
        prev = acc["value"].shift(1)
        r = ((acc["value"] - inflow) / prev - 1).where(prev > 0, 0.0).fillna(0.0)
        twr_index = (1 + r).cumprod()
    if len(value) > len(acc):
        twr_index = pd.concat([twr_index, twr_index.iloc[-1] * value[value.index > end_l] / value.loc[end_l]])
    daily_ret = twr_index.pct_change()
    daily_ret.iloc[0] = twr_index.iloc[0] - 1
    idx = value.index
    days = max((idx[-1] - idx[0]).days, 1)
    twr_total = float(twr_index.iloc[-1] - 1)
    twr_pa = (1 + twr_total) ** (365.25 / days) - 1 if days >= 365 else None

    inflow_s = transfers.diff().fillna(transfers.iloc[0])
    flows = [(d, -float(v)) for d, v in inflow_s.items() if abs(v) > 1e-9]
    irr = xirr(flows + [(idx[-1], float(value.iloc[-1]))])

    active = daily_ret[value.shift(1) > 1e-6]
    vol = float(active.std() * math.sqrt(252)) if len(active) > 20 else None
    dd = twr_index / twr_index.cummax() - 1
    max_dd = float(dd.min())
    rf = float(inp.settings.get("risk_free_rate") or 0) / 100
    ann = (1 + twr_total) ** (365.25 / days) - 1
    sharpe = (ann - rf) / vol if vol else None
    me = twr_index.resample("ME").last()
    monthly = me.pct_change()
    if len(me):
        monthly.iloc[0] = me.iloc[0] - 1

    # ---------------- Positionen
    moves = defaultdict(list)
    for m in ledger.get("movements", []):
        moves[m["symbol"]].append(m)
    positions, ledger_trades = [], []
    cost_tot: dict[str, float] = defaultdict(float)
    cost_by_inst = []
    for sym in vchf.columns:
        info = by_sym.get(sym, {"symbol": sym, "name": sym, "key": sym})
        mv = moves.get(sym, [])
        costs = defaultdict(float)
        fees_by_date: dict[str, float] = defaultdict(float)
        for m in mv:
            if m["kind"] != "trade":
                costs[m["kind"]] += -m["amount_chf"]
                cost_tot[m["kind"]] += -m["amount_chf"]
                if m["kind"] in ("commission", "stamp_duty"):
                    fees_by_date[m["date"]] += -m["amount_chf"]
        cost_ccy = cost_chf = 0.0
        bought = sold = 0.0
        trades = []
        px = px_cache.get(sym, pd.Series(dtype=float))
        for m in [x for x in mv if x["kind"] == "trade"]:
            d = pd.Timestamp(m["date"])
            a_ccy, a_chf = -m["amount_ccy"], -m["amount_chf"]
            fx_t = a_chf / a_ccy if a_ccy else None
            if a_chf > 0:  # Kauf
                side = "BUY"
                bought += a_chf
                cost_ccy += a_ccy
                cost_chf += a_chf
            else:
                side = "SELL"
                sold += -a_chf
                prev = vccy[sym][vccy.index < d]
                prev_val = float(prev.iloc[-1]) if len(prev) else 0.0
                frac = min(1.0, (-a_ccy) / prev_val) if prev_val > 0 else 1.0
                after = vchf[sym][vchf.index >= d]
                if len(after) and float(after.iloc[-1]) < 0.5 and float(after.iloc[min(1, len(after) - 1)]) < 0.5:
                    frac = 1.0
                cost_ccy *= (1 - frac)
                cost_chf *= (1 - frac)
            pxd = px[:d]
            trades.append({"date": m["date"], "side": side, "amount_ccy": _r(abs(a_ccy)), "value_chf": _r(abs(a_chf)),
                           "fees_chf": _r(fees_by_date.get(m["date"], 0.0)), "fx": _r(fx_t, 5) if fx_t else None,
                           "price": _r(float(pxd.iloc[-1]), 4) if len(pxd) else None, "quantity": None})
            ledger_trades.append({"trade_date": m["date"], "name": info.get("name"), "isin": info.get("isin") or sym,
                                  "symbol": sym, "side": side, "amount_ccy": _r(abs(a_ccy)), "currency": info.get("currency"),
                                  "amount_chf": _r(abs(a_chf)), "fees_chf": _r(fees_by_date.get(m["date"], 0.0)),
                                  "fx_rate": _r(fx_t, 5) if fx_t else None})
        mval = float(vchf[sym].iloc[-1])
        is_open = mval > 0.5
        ext_gain = mval - float(vchf[sym].loc[end_l]) if is_open else 0.0
        total_pnl = float(pnl_chf[sym].sum()) + ext_gain if sym in pnl_chf else ext_gain
        v_ccy_l = float(vccy[sym].iloc[-1]) if sym in vccy else 0.0
        pos: dict[str, Any] = {
            "isin": info.get("key", sym), "real_isin": info.get("isin"), "symbol": info.get("yahoo_symbol"),
            "saxo_symbol": sym, "name": info.get("name"), "currency": info.get("currency"), "open": is_open,
            "market_value": _r(mval), "bought_chf": _r(bought), "sold_chf": _r(sold),
            "fees": _r(costs["commission"] + costs["stamp_duty"]), "fx_costs": _r(costs["fx_conversion"]),
            "product_costs": _r(costs["product_costs"]), "total_pnl": _r(total_pnl),
            "return_pct": _r(total_pnl / bought * 100) if bought else None,
            "first_buy": next((t["date"] for t in trades if t["side"] == "BUY"), None),
            "last_trade": trades[-1]["date"] if trades else None, "trades": trades,
            "price_source": inp.price_source(info.get("key", sym)) if not px.empty else "Saxo-Export (Positionswerte)",
            "price_series": _ts(px[px.index >= idx[0] - pd.Timedelta(days=30)], 4) if not px.empty else None,
            "quantity": None, "price": None,
        }
        if is_open:
            # G/V laut Saxo = unrealisiert − Courtage/Stempel (+ Gewinne aus Teilverkäufen)
            fees_open = costs["commission"] + costs["stamp_duty"]
            pos["unrealized_pnl"] = _r(mval - cost_chf)
            pos["realized_pnl"] = _r(total_pnl - (mval - cost_chf) + fees_open)
            pos["open_fees"] = _r(fees_open)
            pos["cost_basis"] = _r(cost_chf)
            p_l = px[:end_l]
            if info.get("report_qty"):
                pos["quantity"] = info["report_qty"]
            elif len(p_l) and float(p_l.iloc[-1]) > 0:
                pos["quantity"] = round(v_ccy_l / float(p_l.iloc[-1]), 2)
            if len(px):
                pos["price"] = _r(float(px.iloc[-1]), 4)
            if cost_ccy > 0 and v_ccy_l > 0:
                ext_factor = mval / float(vchf[sym].loc[end_l]) if float(vchf[sym].loc[end_l]) else 1.0
                fx_l = float(vchf[sym].loc[end_l]) / v_ccy_l
                avg_fx = cost_chf / cost_ccy
                # Marktwert in Handelswährung (fortgeschrieben) und aktueller FX
                v_ccy_now = v_ccy_l * ext_factor  # Näherung: Fortschreibung vollständig dem Kurs zugeordnet
                pos["avg_fx"] = _r(avg_fx, 5)
                pos["fx"] = _r(fx_l, 5)
                pos["price_effect"] = _r((v_ccy_now - cost_ccy) * avg_fx)
                pos["fx_effect"] = _r(mval - cost_chf - (v_ccy_now - cost_ccy) * avg_fx)
                pos["price_change_pct"] = _r((v_ccy_l / cost_ccy - 1) * 100)
                if pos["quantity"]:
                    pos["avg_price"] = _r(cost_ccy / pos["quantity"], 5)
        else:
            pos["unrealized_pnl"] = 0.0
            pos["realized_pnl"] = _r(total_pnl)
        positions.append(pos)
        cost_by_inst.append({"name": info.get("name"), **{k: _r(v) for k, v in costs.items()}})

    positions.sort(key=lambda p: (not p["open"], p["first_buy"] or ""))
    open_pos = [p for p in positions if p["open"]]
    cur_val = float(value.iloc[-1])
    invested = float(transfers.iloc[-1])
    total_pnl = cur_val - invested
    best = active.idxmax() if len(active) else None
    worst = active.idxmin() if len(active) else None
    kpis = {
        "value": _r(cur_val), "invested_total": _r(invested), "withdrawn_total": 0.0,
        "net_invested": _r(invested), "pnl": _r(total_pnl),
        "pnl_pct_on_invested": _r(total_pnl / invested * 100) if invested > 0 else None,
        "twr_pct": _r(twr_total * 100), "twr_pa_pct": _r(twr_pa * 100) if twr_pa is not None else None,
        "irr_pct": _r(irr * 100) if irr is not None else None,
        "volatility_pct": _r(vol * 100) if vol else None, "max_drawdown_pct": _r(max_dd * 100),
        "max_drawdown_date": dd.idxmin().strftime("%Y-%m-%d") if max_dd < 0 else None,
        "sharpe": _r(sharpe), "fees_recorded": _r(cost_tot["commission"] + cost_tot["stamp_duty"]),
        "start": idx[0].strftime("%Y-%m-%d"), "end": idx[-1].strftime("%Y-%m-%d"), "days": days,
        "best_day_pct": _r(float(active.max()) * 100) if len(active) else None,
        "worst_day_pct": _r(float(active.min()) * 100) if len(active) else None,
        "best_day": best.strftime("%Y-%m-%d") if best is not None else None,
        "worst_day": worst.strftime("%Y-%m-%d") if worst is not None else None,
        "positive_days_pct": _r(float((active > 0).mean()) * 100) if len(active) else None,
        "n_trades": len(ledger_trades), "n_instruments": len(positions), "n_open": len(open_pos),
        "cash": _r(float(cash_last)),
        "price_effect": _r(sum(p.get("price_effect") or 0 for p in open_pos)),
        "fx_effect": _r(sum(p.get("fx_effect") or 0 for p in open_pos)),
        "realized_pnl": _r(sum(p["realized_pnl"] or 0 for p in positions)),
        "open_fees": _r(sum(p.get("open_fees") or 0 for p in open_pos)),
        "unrealized_pnl": _r(sum(p["unrealized_pnl"] or 0 for p in open_pos)),
        "ledger_end": end_l.strftime("%Y-%m-%d"),
        "extended": bool(ext_idx is not None and len(ext_idx)),
    }
    costs_total = {k: _r(v) for k, v in cost_tot.items()}
    costs_total["total"] = _r(sum(cost_tot.values()))
    costs_total["total_pct"] = _r(sum(cost_tot.values()) / float(acc["value"][acc["value"] > 0].mean()) * 100) \
        if (acc["value"] > 0).any() else None

    # Umschichtungen: Tage mit Verkäufen und Käufen
    by_day: dict[str, dict[str, Any]] = defaultdict(lambda: {"buys": [], "sells": [], "costs": 0.0, "bought": 0.0, "sold": 0.0})
    for m in ledger.get("movements", []):
        day = by_day[m["date"]]
        name = by_sym.get(m["symbol"], {}).get("name", m["symbol"])
        if m["kind"] == "trade":
            if m["amount_chf"] < 0:
                day["buys"].append(name)
                day["bought"] += -m["amount_chf"]
            else:
                day["sells"].append(name)
                day["sold"] += m["amount_chf"]
        elif m["kind"] in ("commission", "stamp_duty", "fx_conversion"):
            day["costs"] += -m["amount_chf"]
    switches = [{"date": d, "buys": v["buys"], "sells": v["sells"], "costs": _r(v["costs"]),
                 "sold": _r(v["sold"]), "bought": _r(v["bought"]),
                 "cost_pct": _r(v["costs"] / v["sold"] * 100) if v["sold"] else None}
                for d, v in sorted(by_day.items()) if v["buys"] and v["sells"]]

    # Inflow-Reihe für Benchmark-Simulation (gleiche Einzahlungen)
    inflow_full = inflow_s.reindex(idx).fillna(0.0)
    state.update({
        "has_data": True, "mode": "saxo_ledger", "kpis": kpis, "positions": positions,
        "series": {
            "value": _ts(value), "net_invested": _ts(transfers), "pnl": _ts(value - transfers),
            "twr_pct": _ts((twr_index - 1) * 100), "drawdown_pct": _ts(dd * 100),
            "by_instrument": {p["isin"]: _ts(vchf[p["saxo_symbol"]].where(vchf[p["saxo_symbol"]] > 0.5))
                              for p in positions},
        },
        "monthly": [{"month": d.strftime("%Y-%m"), "return_pct": _r(v * 100)} for d, v in monthly.items() if pd.notna(v)],
        "benchmarks": _benchmarks(inp, idx, inflow_full, pd.Series(0.0, index=idx), twr_index),
        "exposure": _exposure(db, open_pos),
        "ledger_trades": ledger_trades,
        "ledger_costs": {**costs_total, "by_instrument": cost_by_inst},
        "switches": switches,
        "ledger_info": {"period_start": ledger.get("period_start"), "period_end": ledger.get("period_end"),
                        "imported_at": ledger.get("_imported_at")},
        "reconciliation": [],
    })
    if not kpis["extended"]:
        state["warnings"].append(
            f"Werte bis {end_l.strftime('%d.%m.%Y')} stammen aus dem Saxo-Export. Mit «Aktualisieren» wird der "
            "aktuelle Bestand mit Marktkursen bis heute fortgeschrieben.")
    return state
