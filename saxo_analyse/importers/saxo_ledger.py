"""Import des Saxo-Exports «Aggregierte Beträge» (AggregatedAmounts_*.xlsx).

SaxoTraderGO → Konto → Berichte → «Aggregierte Beträge» → Export nach Excel.
Enthält pro Tag und Instrument: Positionswert (Handelswährung und CHF), Netto-G/V, Käufe/Verkäufe
(«Share Amount»), Courtage, Stempelsteuer, Devisenkosten, Produktkosten, Einzahlungen sowie
die tägliche Kontorendite («Performance»). Stückzahlen fehlen – sie werden nicht benötigt.
"""

from __future__ import annotations

import io
import re
from collections import defaultdict
from typing import Any

import pandas as pd

from .common import parse_date

COLS = {
    "date": ["datum", "date"],
    "type": ["betragsartbezeichnung", "amount type name", "amounttypename", "amount type"],
    "symbol": ["instrument-symbol", "instrument symbol", "instrumentsymbol", "symbol"],
    "desc": ["instrumentbeschreibung", "instrument description", "instrumentdescription"],
    "uic": ["vereinheitlichter instrumentencode (uic)", "instrument uic", "uic"],
    "asset": ["assetklasse", "asset type", "assettype"],
    "amount": ["betrag", "amount"],
    "amount_acct": ["betrag in kontowährung", "amount account currency", "amount in account currency",
                    "amountaccountcurrency"],
    "cost_type": ["kostentyp", "cost type"],
}

# Saxo-Börsenkürzel → Yahoo-Suffix und übliche Handelswährung
EXCHANGES = {
    "xetr": (".DE", "EUR"), "xfra": (".F", "EUR"), "xpar": (".PA", "EUR"), "xmil": (".MI", "EUR"),
    "xams": (".AS", "EUR"), "xbru": (".BR", "EUR"), "xmad": (".MC", "EUR"), "xwbo": (".VI", "EUR"),
    "xswx": (".SW", None), "xvtx": (".SW", None), "xlon": (".L", None), "xnas": ("", "USD"),
    "xnys": ("", "USD"), "arcx": ("", "USD"), "bats": ("", "USD"),
}

COST_TYPES = {
    "Commission": "commission",
    "Swiss Stamp Duty Foreign": "stamp_duty",
    "Swiss Stamp Duty Domestic": "stamp_duty",
    "CurrencyConversion": "fx_conversion",
    "External product costs": "product_costs",
}


def _norm(s: Any) -> str:
    return re.sub(r"\s+", " ", str(s).strip().lower())


def _pick(columns: list[str], key: str) -> str | None:
    normed = {_norm(c): c for c in columns}
    for syn in COLS[key]:
        if syn in normed:
            return normed[syn]
    return None


def is_ledger_workbook(content: bytes) -> bool:
    try:
        sheets = pd.read_excel(io.BytesIO(content), sheet_name=None, nrows=2)
    except Exception:  # noqa: BLE001
        return False
    for df in sheets.values():
        cols = [str(c) for c in df.columns]
        if _pick(cols, "type") and _pick(cols, "amount_acct"):
            return True
    return False


def yahoo_symbol(saxo_symbol: str) -> str | None:
    if ":" not in saxo_symbol:
        return None
    tick, ex = saxo_symbol.split(":", 1)
    suffix, _ = EXCHANGES.get(ex.lower(), (None, None))
    if suffix is None:
        return None
    return tick.upper() + suffix


def _guess_currency(saxo_symbol: str, ratio: float | None) -> str:
    ex = saxo_symbol.split(":", 1)[-1].lower() if ":" in saxo_symbol else ""
    if ratio is not None and abs(ratio - 1) < 1e-6:
        return "CHF"
    default = EXCHANGES.get(ex, (None, None))[1]
    if default:
        return default
    if ex == "xlon":
        return "USD" if ratio and ratio < 1 else "GBP"
    return "EUR" if ratio and ratio > 0.86 else "USD"


def parse_ledger(content: bytes) -> dict[str, Any]:
    sheets = pd.read_excel(io.BytesIO(content), sheet_name=None)
    main = perf = None
    for name, df in sheets.items():
        cols = [str(c) for c in df.columns]
        if _pick(cols, "type") and _pick(cols, "amount_acct"):
            if main is None or len(df) > len(main):
                main = df
        if any("AccountValueTimeSeries" in c for c in cols):
            perf = df
    if main is None:
        raise ValueError("Keine Tabelle «Aggregierte Beträge» gefunden.")

    cols = [str(c) for c in main.columns]
    c = {k: _pick(cols, k) for k in COLS}
    for k in ("date", "type", "amount", "amount_acct"):
        if not c[k]:
            raise ValueError(f"Spalte für «{k}» fehlt im Export.")

    instruments: dict[str, dict[str, Any]] = {}
    daily: dict[tuple[str, str], dict[str, float]] = defaultdict(dict)
    cash_daily: dict[str, float] = {}
    movements: list[dict[str, Any]] = []
    deposits: list[dict[str, Any]] = []
    fx_ratios: dict[str, list[float]] = defaultdict(list)

    for _, r in main.iterrows():
        d = parse_date(r[c["date"]])
        t = str(r[c["type"]]).strip()
        if not d or t in ("nan", ""):
            continue
        amt = float(r[c["amount"]]) if pd.notna(r[c["amount"]]) else 0.0
        amt_chf = float(r[c["amount_acct"]]) if pd.notna(r[c["amount_acct"]]) else 0.0
        sym = str(r[c["symbol"]]).strip() if c["symbol"] and pd.notna(r[c["symbol"]]) else ""
        desc = str(r[c["desc"]]).strip() if c["desc"] and pd.notna(r[c["desc"]]) else ""
        asset = str(r[c["asset"]]).strip().lower() if c["asset"] and pd.notna(r[c["asset"]]) else ""

        if t == "Cash" and not sym:
            cash_daily[d] = amt_chf
            continue
        if t == "Cash Amount" or asset == "cash":
            deposits.append({"date": d, "amount_chf": amt_chf, "description": desc})
            continue
        if not sym:
            continue
        inst = instruments.setdefault(sym, {
            "symbol": sym, "name": desc or sym,
            "uic": str(r[c["uic"]]) if c["uic"] and pd.notna(r[c["uic"]]) else None,
            "yahoo_symbol": yahoo_symbol(sym),
        })
        if not inst.get("name"):
            inst["name"] = desc
        if t == "Position Values":
            daily[(d, sym)]["value_ccy"] = amt
            daily[(d, sym)]["value_chf"] = amt_chf
            if amt:
                fx_ratios[sym].append(amt_chf / amt)
        elif t == "Net P/L":
            daily[(d, sym)]["pnl_chf"] = amt_chf
            daily[(d, sym)]["pnl_ccy"] = amt
        elif t == "Share Amount":
            movements.append({"date": d, "symbol": sym, "kind": "trade", "amount_ccy": amt, "amount_chf": amt_chf})
            if amt:
                fx_ratios[sym].append(amt_chf / amt)
        elif t in COST_TYPES:
            movements.append({"date": d, "symbol": sym, "kind": COST_TYPES[t], "amount_ccy": amt,
                              "amount_chf": amt_chf, "label": t})

    for sym, inst in instruments.items():
        ratios = sorted(fx_ratios.get(sym, []))
        med = ratios[len(ratios) // 2] if ratios else None
        inst["currency"] = _guess_currency(sym, med)

    account = []
    if perf is not None:
        for _, r in perf.iterrows():
            d = parse_date(r.get("Datum", r.get("Date")))
            if not d:
                continue
            account.append({
                "date": d,
                "value": float(r["AccountValueTimeSeries"]),
                "twr_pct": float(r["AccumulatedTimeWeightedTimeSeries"]),
                "transfers_cum": float(r.get("CashTransferTimeSeries", 0) or 0)
                + float(r.get("SecurityTransferTimeSeries", 0) or 0),
                "cash": cash_daily.get(d),
            })
    else:  # ohne Performance-Blatt: Kontowert aus Positionen + Cash rekonstruieren
        dates = sorted({d for d, _ in daily} | set(cash_daily))
        cum = 0.0
        dep_by_date: dict[str, float] = defaultdict(float)
        for x in deposits:
            dep_by_date[x["date"]] += x["amount_chf"]
        for d in dates:
            cum += dep_by_date.get(d, 0.0)
            val = sum(v.get("value_chf", 0.0) for (dd, _), v in daily.items() if dd == d)
            account.append({"date": d, "value": val + cash_daily.get(d, 0.0), "twr_pct": None,
                            "transfers_cum": cum, "cash": cash_daily.get(d)})

    inst_daily = [{"date": d, "symbol": s, **v} for (d, s), v in sorted(daily.items())]
    account.sort(key=lambda x: x["date"])
    if not account:
        raise ValueError("Export enthält keine Tageswerte.")
    return {
        "type": "saxo_ledger",
        "period_start": account[0]["date"], "period_end": account[-1]["date"],
        "instruments": list(instruments.values()),
        "account": account, "inst_daily": inst_daily,
        "movements": sorted(movements, key=lambda m: (m["date"], m["symbol"])),
        "deposits": deposits,
    }
