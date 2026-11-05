"""Import von Trade-Listen (Saxo "Trades"/"Transaktionen"-Export als Excel/CSV oder eigene CSV).

Die Spalten werden tolerant über deutsche und englische Synonyme erkannt.
"""

from __future__ import annotations

import io
import re
from pathlib import Path
from typing import Any

import pandas as pd

from .common import ISIN_RE, parse_date, parse_number

SYNONYMS: dict[str, list[str]] = {
    "date": ["trade date", "handelsdatum", "tradedatum", "ausführungsdatum", "abschlussdatum",
             "trade time", "execution time", "datum", "date", "buchungsdatum", "valutadatum", "value date"],
    "isin": ["instrument isin", "isin"],
    "name": ["instrument description", "instrumentenbeschreibung", "instrument", "beschreibung",
             "produkt", "name", "security", "wertpapier"],
    "symbol": ["instrument symbol", "symbol", "ticker"],
    "side": ["buy/sell", "kauf/verkauf", "kaufen/verkaufen", "b/s", "direction", "richtung", "side",
             "event", "aktion", "art", "typ", "type"],
    "quantity": ["traded amount", "amount", "quantity", "menge", "anzahl", "stück", "stueck", "units",
                 "volumen", "betrag (menge)"],
    "price": ["trade price", "price", "kurs", "preis", "ausführungskurs", "ausfuehrungskurs"],
    "currency": ["instrument currency", "instrumentwährung", "instrumentenwährung", "currency",
                 "währung", "waehrung", "ccy"],
    "fx_rate": ["conversion rate", "umrechnungskurs", "fx rate", "wechselkurs", "fx_rate"],
    "amount_chf": ["booked amount", "gebuchter betrag", "booked amount account currency",
                   "betrag in kontowährung", "amount_chf", "total cost", "gesamtbetrag"],
    "fees_chf": ["commission", "provision", "fees", "gebühren", "gebuehren", "kosten", "fees_chf"],
}

BUY_WORDS = ("buy", "kauf", "bought", "gekauft", "long")
SELL_WORDS = ("sell", "verkauf", "sold", "verkauft", "short")


def _norm(s: Any) -> str:
    return re.sub(r"\s+", " ", str(s).strip().lower())


def _read_table(content: bytes, filename: str) -> pd.DataFrame:
    name = filename.lower()
    if name.endswith((".xlsx", ".xlsm", ".xls")):
        sheets = pd.read_excel(io.BytesIO(content), sheet_name=None, header=None, dtype=object)
        # Das Blatt mit den meisten erkannten Spalten gewinnt
        best, best_score = None, -1
        for df in sheets.values():
            hdr, score = _find_header(df)
            if score > best_score:
                best, best_score = (df, hdr), score
        df, hdr = best
    else:
        text = content.decode("utf-8-sig", errors="replace")
        sep = max([";", ",", "\t"], key=lambda s: text.split("\n", 1)[0].count(s))
        df = pd.read_csv(io.StringIO(text), sep=sep, header=None, dtype=object)
        hdr, _ = _find_header(df)
    df.columns = [str(c) for c in df.iloc[hdr].tolist()]
    return df.iloc[hdr + 1:].reset_index(drop=True)


def _find_header(df: pd.DataFrame) -> tuple[int, int]:
    best_row, best_score = 0, -1
    for i in range(min(len(df), 30)):
        cells = [_norm(c) for c in df.iloc[i].tolist() if pd.notna(c)]
        score = sum(1 for key in ("date", "quantity", "price", "side", "isin", "name")
                    if any(c in SYNONYMS[key] for c in cells))
        if score > best_score:
            best_row, best_score = i, score
    return best_row, best_score


def _map_columns(columns: list[str]) -> dict[str, str]:
    mapping: dict[str, str] = {}
    normed = {c: _norm(c) for c in columns}
    for key, syns in SYNONYMS.items():
        for syn in syns:  # Reihenfolge = Priorität
            hit = next((c for c, n in normed.items() if n == syn and c not in mapping.values()), None)
            if hit:
                mapping[key] = hit
                break
    return mapping


def parse_trades_file(content: bytes, filename: str) -> dict[str, Any]:
    df = _read_table(content, filename)
    mapping = _map_columns(list(df.columns))
    missing = [k for k in ("date", "quantity", "price") if k not in mapping]
    if missing:
        raise ValueError(
            "Konnte die Spalten nicht erkennen: " + ", ".join(missing)
            + f". Gefundene Spalten: {', '.join(map(str, df.columns))}")

    trades, warnings = [], []
    for idx, row in df.iterrows():
        d = parse_date(row.get(mapping["date"]))
        qty = parse_number(row.get(mapping["quantity"]))
        price = parse_number(row.get(mapping["price"]))
        if not d or qty is None or price is None or qty == 0:
            continue
        name = str(row.get(mapping.get("name", ""), "") or "").strip()
        isin = None
        if "isin" in mapping and pd.notna(row.get(mapping["isin"])):
            isin = str(row.get(mapping["isin"])).strip().upper()
        if not isin:
            m = ISIN_RE.search(" ".join(str(v) for v in row.tolist()))
            isin = m.group(1) if m else None
        if not isin:
            warnings.append(f"Zeile {idx + 1}: keine ISIN gefunden – übersprungen ({name}).")
            continue
        side_raw = _norm(row.get(mapping["side"])) if "side" in mapping else ""
        if any(w in side_raw for w in SELL_WORDS):
            side = "SELL"
        elif any(w in side_raw for w in BUY_WORDS):
            side = "BUY"
        else:
            side = "SELL" if qty < 0 else "BUY"
        currency = str(row.get(mapping["currency"])).strip().upper() if "currency" in mapping else ""
        if not re.fullmatch(r"[A-Z]{3}", currency or ""):
            currency = ""
        fx = parse_number(row.get(mapping["fx_rate"])) if "fx_rate" in mapping else None
        amount = parse_number(row.get(mapping["amount_chf"])) if "amount_chf" in mapping else None
        fees = parse_number(row.get(mapping["fees_chf"])) if "fees_chf" in mapping else None
        trades.append({
            "trade_date": d, "isin": isin, "name": name or None, "side": side,
            "quantity": abs(qty), "price": abs(price), "currency": currency or None,
            "fx_rate": fx if fx and fx > 0 else None,
            "amount_chf": abs(amount) if amount else None,
            "fees_chf": abs(fees) if fees else 0.0,
            "source": f"import:{Path(filename).name}",
        })
    return {"type": "trades", "trades": trades, "warnings": warnings, "mapping": mapping}
