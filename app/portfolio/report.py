"""Import des Saxo «Transaktions- und Saldenbericht» (PDF).

SaxoTraderGO → Konto → Berichte → Transaktions- und Saldenbericht → Zeitraum ab Kontoeröffnung → PDF.

Der Bericht enthält alles Nötige:
  * Kontoübersicht (Einzahlungen, Kosten, realisierte und gesamte G/V, Kontowert)
  * Bestände (inkl. ISIN, Symbol, Menge, Eröffnungs- und aktuellem Kurs)
  * Geschlossene Positionen (realisierte G/V je ETF)
  * Alle Transaktionen (Datum, Menge, Kurs, Wechselkurs, gebuchter Betrag, Kosten)

Persönliche Angaben (Name, Adresse, Kontonummer) werden nicht gespeichert.
"""

from __future__ import annotations

import re
from collections import defaultdict
from datetime import date
from pathlib import Path
from typing import IO, Any

MONTHS = {
    "jan": 1, "feb": 2, "mrz": 3, "mär": 3, "mar": 3, "apr": 4, "mai": 5, "may": 5, "jun": 6,
    "jul": 7, "aug": 8, "sep": 9, "okt": 10, "oct": 10, "nov": 11, "dez": 12, "dec": 12,
}
DATE_RE = re.compile(r"(\d{1,2})[-.\s]([A-Za-zäÄ]{3})[a-zä]*[-.\s](\d{4})")
ISIN_RE = re.compile(r"\b([A-Z]{2}[A-Z0-9]{9}\d)\b")


# --------------------------------------------------------------------------- Zahlen & Daten
def num(text: Any) -> float | None:
    """Schweizer/deutsches Format: '31.036,42' -> 31036.42, '2.163' -> 2163, '-3' -> -3."""
    if text is None:
        return None
    s = str(text).strip().replace("%", "").replace("−", "-").replace(" ", "").replace("'", "")
    if s in {"", "-", "–"}:
        return None
    if "," in s:
        s = s.replace(".", "").replace(",", ".")
    elif re.fullmatch(r"-?\d{1,3}(\.\d{3})+", s):
        s = s.replace(".", "")
    try:
        return float(s)
    except ValueError:
        return None


def to_date(text: Any) -> str | None:
    m = DATE_RE.search(str(text or ""))
    if not m:
        return None
    mon = MONTHS.get(m.group(2).lower()[:3])
    return date(int(m.group(3)), mon, int(m.group(1))).isoformat() if mon else None


# --------------------------------------------------------------------------- PDF -> Tabellen
def extract_tables(source: str | Path | IO[bytes]) -> list[dict[str, Any]]:
    """Liest alle Tabellen des Berichts. Zeilen sind im PDF durch dünne Linien getrennt."""
    import pdfplumber

    out: list[dict[str, Any]] = []
    with pdfplumber.open(source) as pdf:
        for page_no, page in enumerate(pdf.pages, start=1):
            out.extend({**t, "page": page_no} for t in _page_tables(page))
    return out


def _page_tables(page) -> list[dict[str, Any]]:
    seps: dict[float, list[tuple[float, float]]] = defaultdict(list)
    for r in page.rects:
        if r["height"] < 2 and (r["x1"] - r["x0"]) > 15 and r["top"] > 100:
            seps[round(r["top"])].append((r["x0"], r["x1"]))
    if not seps:
        return []
    words = page.extract_words(x_tolerance=1.5)
    groups: list[dict[str, Any]] = []
    for y in sorted(seps):
        cols = sorted(seps[y])
        g = groups[-1] if groups else None
        if g and len(cols) == len(g["cols"]) and abs(cols[0][0] - g["cols"][0][0]) < 3:
            g["ys"].append(y)
        else:
            groups.append({"cols": cols, "ys": [y]})

    def band(cols, y0, y1):
        row = []
        for x0, x1 in cols:
            ws = [w for w in words if y0 < (w["top"] + w["bottom"]) / 2 < y1
                  and x0 - 1 <= (w["x0"] + w["x1"]) / 2 < x1 + 1]
            ws.sort(key=lambda w: (round(w["top"]), w["x0"]))
            row.append(" ".join(w["text"] for w in ws))
        return row

    tables = []
    for g in groups:
        cols, ys = g["cols"], g["ys"]
        header = [re.sub(r"(\w)- (\w)", r"\1\2", re.sub(r"\s+", " ", h)).strip()
                  for h in band(cols, ys[0] - 45, ys[0])]
        rows = [band(cols, a, b) for a, b in zip(ys, ys[1:])]
        tables.append({"header": header, "rows": [r for r in rows if any(c.strip() for c in r)]})
    return tables


# --------------------------------------------------------------------------- Tabellen -> Modell
def _norm(h: str) -> str:
    return re.sub(r"[^a-zäöü/]", "", h.lower())


def _find(tables: list[dict], *must: str) -> list[dict]:
    res = []
    for t in tables:
        hdr = " ".join(_norm(h) for h in t["header"])
        if all(_norm(m) in hdr for m in must):
            res.append(t)
    return res


def _rows_as_dicts(table: dict, keys: dict[str, str]) -> list[dict[str, str]]:
    """keys: Zielname -> Teilstring des (normalisierten) Spaltentitels."""
    idx = {}
    normed = [_norm(h) for h in table["header"]]
    for key, part in keys.items():
        p = _norm(part)
        idx[key] = next((i for i, h in enumerate(normed) if p in h), None)
    out = []
    for r in table["rows"]:
        out.append({k: (r[i] if i is not None and i < len(r) else "") for k, i in idx.items()})
    return out


def parse_tables(tables: list[dict[str, Any]], meta: dict[str, Any] | None = None) -> dict[str, Any]:
    meta = meta or {}
    rep: dict[str, Any] = {"source": "saxo_transaction_balance", **meta}

    # --- Transaktionen
    tx_keys = {"date": "Trade-Datum", "valuta": "Valuta", "trade_id": "Trade-ID", "product": "Produkt",
               "instrument": "Instrument", "currency": "Instrumentenwährung", "event": "Ereignistyp",
               "open_close": "Eröffnung/Schluss", "qty": "Menge", "price": "Kurs", "fx": "Umrechnungskurs",
               "realized": "RealisierteG/V", "amount": "GebuchterBetrag", "costs": "GebuchteKosten",
               "total_costs": "Gesamtkosten"}
    txs = []
    for t in _find(tables, "Trade-Datum", "Ereignistyp"):
        for r in _rows_as_dicts(t, tx_keys):
            d = to_date(r["date"])
            if not d:
                continue  # Summenzeile «Gesamt»
            event = r["event"].strip()
            kind = ("deposit" if "einlage" in event.lower() else
                    "withdrawal" if "auszahlung" in event.lower() or "entnahme" in event.lower() else
                    "buy" if event.lower().startswith("kauf") else
                    "sell" if event.lower().startswith("verkauf") else "other")
            qty = num(r["qty"])
            txs.append({
                "date": d, "valuta": to_date(r["valuta"]), "trade_id": r["trade_id"].strip() if r["trade_id"].strip() not in ("", "-") else None,
                "kind": kind, "instrument": r["instrument"].strip() or None,
                "currency": r["currency"].strip() or "CHF", "event": event,
                "qty": abs(qty) if qty is not None else None,
                "price": num(r["price"]), "fx": num(r["fx"]) or 1.0,
                "realized": num(r["realized"]), "amount_chf": num(r["amount"]) or 0.0,
                "costs_chf": -(num(r["costs"]) or 0.0), "total_costs_chf": -(num(r["total_costs"]) or 0.0),
            })
    # Duplikate (Seitenumbrüche) entfernen, chronologisch sortieren
    seen, uniq = set(), []
    for tx in txs:
        key = (tx["date"], tx["trade_id"], tx["kind"], tx["amount_chf"])
        if key not in seen:
            seen.add(key)
            uniq.append(tx)
    rep["transactions"] = sorted(uniq, key=lambda t: (t["date"], {"deposit": 0, "buy": 1, "sell": 2}.get(t["kind"], 3)))

    # --- Bestände
    hold = []
    for t in _find(tables, "Symbol", "Marktwert"):
        for r in _rows_as_dicts(t, {"instrument": "Instrument", "symbol": "Symbol", "currency": "Instrumentenwä",
                                     "opened": "Datum der Eröffnung", "qty": "Menge", "fx": "Umrechnungskurs",
                                     "open_price": "Eröffnungspreis", "price": "Aktueller Preis",
                                     "pnl": "G/V", "value": "Marktwert"}):
            if r["instrument"].strip().lower().startswith("gesamt"):
                continue
            m = ISIN_RE.search(r["instrument"])
            name = re.sub(r"\(ISIN:?\s*[A-Z0-9]*\)?", "", r["instrument"]).strip()
            hold.append({"instrument": name, "isin": m.group(1) if m else None, "symbol": r["symbol"].strip(),
                         "currency": r["currency"].strip(), "opened": to_date(r["opened"]), "qty": num(r["qty"]),
                         "fx": num(r["fx"]), "open_price": num(r["open_price"]), "price": num(r["price"]),
                         "pnl_chf": num(r["pnl"]), "value_chf": num(r["value"])})
    rep["holdings"] = hold

    # --- Geschlossene Positionen
    closed = []
    for t in _find(tables, "geschlossene", "Realisierte"):
        for r in _rows_as_dicts(t, {"instrument": "Instrument", "opened": "Datum der Eröffnung",
                                     "closed": "Schließungsdatum", "qty": "Menge", "open_price": "Eröffnungskurs",
                                     "close_price": "Schließungskurs", "open_amount": "GebuchterBetragEröffnung",
                                     "close_amount": "Schließunggebuchter", "realized": "RealisierteG/V"}):
            if r["instrument"].strip().lower().startswith("gesamt") or not to_date(r["closed"]):
                continue
            closed.append({"instrument": r["instrument"].strip(), "opened": to_date(r["opened"]),
                           "closed": to_date(r["closed"]), "qty": num(r["qty"]), "open_price": num(r["open_price"]),
                           "close_price": num(r["close_price"]), "open_amount_chf": num(r["open_amount"]),
                           "close_amount_chf": num(r["close_amount"]), "realized_chf": num(r["realized"])})
    rep["closed"] = closed

    # --- Kontoübersicht
    ov: dict[str, Any] = {}
    for t in _find(tables, "Barguthaben", "Kontowert"):
        hdr = [_norm(h) for h in t["header"]]
        tot = next((r for r in t["rows"] if r and r[0].strip().lower().startswith("gesamt")), None)
        if tot:
            kw = [i for i, h in enumerate(hdr) if h == "kontowert"]
            bar = [i for i, h in enumerate(hdr) if h == "barguthaben"]
            pos = [i for i, h in enumerate(hdr) if "positionen" in h]
            if kw:
                ov["account_value"] = num(tot[kw[-1]])
            if bar:
                ov["cash"] = num(tot[bar[-1]])
            if pos:
                ov["positions_value"] = num(tot[pos[-1]])
    for t in _find(tables, "Kosten", "RealisierteG/V"):
        if _find([t], "Trade-Datum"):
            continue
        d = _rows_as_dicts(t, {"transfers": "Wertpapierübertrag", "income": "Einnahmen", "costs": "Kosten",
                               "realized": "RealisierteG/V", "change": "ÄnderungdesKontowerts"})
        tot = next((r for r, raw in zip(d, t["rows"]) if raw and raw[0].strip().lower().startswith("gesamt")), None)
        if tot:
            ov.update({"transfers": num(tot["transfers"]), "income": num(tot["income"]),
                       "costs": -(num(tot["costs"]) or 0.0), "realized": num(tot["realized"])})
            # letzte Spalte = G/V gesamt
            raw = next(raw for raw in t["rows"] if raw[0].strip().lower().startswith("gesamt"))
            ov["pnl"] = num(raw[-1])
    rep["overview"] = ov

    # --- Buchungen (Kostenarten)
    book = {}
    for t in _find(tables, "Produkt", "Debit", "Kredit"):
        for r in _rows_as_dicts(t, {"type": "Typ", "total": "Gesamt"}):
            if r["type"].strip() and r["type"].strip() != "-":
                book[r["type"].strip()] = num(r["total"])
    rep["bookings"] = book

    if not rep["transactions"]:
        raise ValueError("Im PDF wurden keine Transaktionen gefunden. Ist es der «Transaktions- und Saldenbericht»?")
    rep["period_start"] = meta.get("period_start") or rep["transactions"][0]["date"]
    rep["period_end"] = meta.get("period_end") or rep["transactions"][-1]["date"]
    return rep


def _meta_from_text(text: str) -> dict[str, Any]:
    meta: dict[str, Any] = {}
    m = re.search(r"Berichtszeitraum:?\s*(\d{1,2}-\w{3}-\d{4})\s*(?:-|bis|an)\s*(\d{1,2}-\w{3}-\d{4})", text)
    if m:
        meta["period_start"], meta["period_end"] = to_date(m.group(1)), to_date(m.group(2))
    m = re.search(r"Währung:\s*([A-Z]{3})", text)
    meta["currency"] = m.group(1) if m else "CHF"
    return meta


def parse_report(source: str | Path | IO[bytes]) -> dict[str, Any]:
    import pdfplumber

    with pdfplumber.open(source) as pdf:
        first = "\n".join((p.extract_text() or "") for p in pdf.pages[:2])
    if "Transaktions" not in first and "Transaction" not in first:
        raise ValueError("Das ist kein Saxo «Transaktions- und Saldenbericht».")
    if hasattr(source, "seek"):
        source.seek(0)
    return parse_tables(extract_tables(source), _meta_from_text(first))
