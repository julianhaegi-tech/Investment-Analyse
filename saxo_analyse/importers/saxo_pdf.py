"""Parser für den Saxo "Portfolio-Bericht" (PDF, SaxoTraderGO > Berichte).

Persönliche Angaben (Name, Adresse) werden bewusst NICHT übernommen.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from .common import DATE_TOKEN_RE, ISIN_RE, parse_date, parse_number

NUM = r"-?[\d,']+(?:\.\d+)?"
PCT = rf"({NUM})\s*%"


def _page_texts(path: str | Path) -> list[dict[str, str]]:
    import pdfplumber

    pages = []
    with pdfplumber.open(str(path)) as pdf:
        for page in pdf.pages:
            full = page.extract_text(x_tolerance=1) or ""
            w = page.width
            right = page.crop((w * 0.29, 0, w, page.height)).extract_text(x_tolerance=1) or ""
            pages.append({"full": full, "right": right})
    return pages


def parse_saxo_pdf(path: str | Path) -> dict[str, Any]:
    return parse_saxo_pages(_page_texts(path))


def parse_saxo_pages(pages: list[dict[str, str]]) -> dict[str, Any]:
    alltext = "\n".join(p["full"] for p in pages)
    if "Saxo" not in alltext and "SAXO" not in alltext:
        raise ValueError("Das PDF sieht nicht nach einem Saxo-Bericht aus.")

    out: dict[str, Any] = {"type": "saxo_portfolio_report", "warnings": []}

    m = re.search(rf"Berichtszeitraum\s*\n?\s*({DATE_TOKEN_RE.pattern})\s*(?:bis|-|to)\s*"
                  rf"({DATE_TOKEN_RE.pattern})", alltext)
    if m:
        dates = DATE_TOKEN_RE.findall(m.group(0))
        out["period_start"] = parse_date("-".join(dates[0]))
        out["period_end"] = parse_date("-".join(dates[1]))
    m = re.search(r"Währung:\s*([A-Z]{3})", alltext)
    out["currency"] = m.group(1) if m else "CHF"
    m = re.search(r"Generiert um:\s*(\S+)", alltext)
    out["generated"] = parse_date(m.group(1)) if m else None

    for p in pages:
        full, right = p["full"], p["right"]
        if "Kontozusammenfassung" in full:
            out["summary"] = _summary(full)
        if "Positionswert" in right and "Kontowert" in right and DATE_TOKEN_RE.search(right):
            vt = _value_table(right)
            if vt:
                out["value_table"] = vt
        if "% Rendite" in right and "Gesamtkosten" in right:
            out.update(_quarterly(right))
        if "G/V-" in full and "Aufschlüsselung" in full:
            out["instrument_pnl"] = _instrument_pnl(right)
        if "Bestände" in full and "ISIN" in full:
            out["holdings"] = _holdings(full)
            mc = re.search(rf"\nBar\s+-\s+({NUM})\s+", full)
            if mc:
                out["cash"] = parse_number(mc.group(1))
        if "Kostenübersicht" in full:
            out["costs"] = _costs(full)

    if not out.get("holdings"):
        out["warnings"].append("Keine Bestände im Bericht gefunden.")
    return out


def _summary(text: str) -> dict[str, Any]:
    amounts = [parse_number(x) for x in re.findall(rf"({NUM})\s*CHF", text)]
    res: dict[str, Any] = {}
    # Reihenfolge im Bericht: Gesamterträge, Nettoeinlagen, Kontowert Ende, Kontowert Start, Änderung
    if len(amounts) >= 4:
        res["total_return"] = amounts[0]
        res["net_deposits"] = amounts[1]
        res["end_value"] = amounts[2]
        res["start_value"] = amounts[3]
    m = re.search(rf"Gesamtrendite\s*\n?\s*{PCT}", text)
    if m:
        res["total_return_pct"] = parse_number(m.group(1))
    return res


def _value_table(text: str) -> list[dict[str, Any]]:
    lines = text.splitlines()
    date_line_idx = next((i for i, l in enumerate(lines) if len(DATE_TOKEN_RE.findall(l)) >= 2), None)
    if date_line_idx is None:
        return []
    dates = [parse_date("-".join(d)) for d in DATE_TOKEN_RE.findall(lines[date_line_idx])]
    n = len(dates)
    row_re = re.compile(rf"((?:\s*{NUM}){{{n}}})\s*$")
    rows = []
    for l in lines[date_line_idx + 1:]:
        m = row_re.search(l)
        if m and len(re.findall(NUM, m.group(1))) == n:
            rows.append([parse_number(x) for x in re.findall(NUM, m.group(1))])
    if len(rows) < 4:
        return []
    cash, accr, pos, acct = rows[:4]
    return [{"date": d, "cash": cash[i], "accruals": accr[i], "positions": pos[i], "account": acct[i]}
            for i, d in enumerate(dates)]


def _quarterly(text: str) -> dict[str, Any]:
    labels = re.findall(r"Q[1-4][ -]\d{4}\*?", text)
    res: dict[str, Any] = {}
    lines = text.splitlines()
    ret = bench = pnl = costs = None
    bench_name = None
    for i, l in enumerate(lines):
        if l.startswith("% Rendite") and re.search(PCT, l):
            ret = [parse_number(x) for x in re.findall(PCT, l)]
        elif l.strip().startswith("Benchmark"):
            vals = re.findall(PCT, l)
            j = i
            if not vals and i + 1 < len(lines):
                j = i + 1
                vals = re.findall(PCT, lines[j])
            bench = [parse_number(x) for x in vals]
            if j + 1 < len(lines) and not re.search(r"\d\s*%", lines[j + 1]):
                bench_name = lines[j + 1].strip()
        elif l.startswith("Gesamt G/V") and re.search(NUM, l[10:]):
            pnl = [parse_number(x) for x in re.findall(NUM, l[10:])]
        elif l.startswith("Gesamtkosten"):
            costs = [parse_number(x) for x in re.findall(NUM, l[12:])]
    q_labels = []
    for lab in labels:
        clean = lab.replace(" ", "-").rstrip("*")
        if clean not in [q["label"] for q in q_labels]:
            q_labels.append({"label": clean, "partial": lab.endswith("*")})
    quarters = []
    for i, q in enumerate(q_labels):
        quarters.append({
            **q,
            "return_pct": ret[i] if ret and i < len(ret) else None,
            "benchmark_pct": bench[i] if bench and i < len(bench) else None,
            "pnl": pnl[i] if pnl and i < len(pnl) else None,
            "costs": costs[i] if costs and i < len(costs) else None,
        })
    res["quarters"] = quarters
    res["benchmark_name"] = bench_name
    if ret and len(ret) == len(q_labels) + 1:
        res["twr_total_pct"] = ret[-1]
    if bench and len(bench) == len(q_labels) + 1:
        res["benchmark_total_pct"] = bench[-1]
    return res


def _instrument_pnl(text: str) -> list[dict[str, Any]]:
    out = []
    started = False
    row = re.compile(rf"^(.+?)\s+({NUM})\s+({NUM})\s+({NUM})\s+(?:{PCT}|-)\s*$")
    for l in text.splitlines():
        if l.startswith("Instrument") and "Rendite" in l:
            started = True
            continue
        if not started:
            continue
        if l.startswith("Gesamt"):
            break
        m = row.match(l.strip())
        if m:
            out.append({"name": m.group(1).strip(), "income": parse_number(m.group(2)),
                        "costs": parse_number(m.group(3)), "pnl": parse_number(m.group(4)),
                        "return_pct": parse_number(m.group(5))})
    return out


def _holdings(text: str) -> list[dict[str, Any]]:
    start = text.find("realisierter G/V")
    start = text.find("\n", text.find("realisierter G/V", start + 1) if start >= 0 else 0)
    section = text[start:]
    end = re.search(r"\nGesamt\s", section)
    if end:
        section = section[: end.start()]
    nums = re.compile(
        rf"\b([A-Z]{{3}})\s+({NUM})\s+({NUM})\s+({NUM})\s+({NUM})\s+{PCT}\s+({NUM})\s+({NUM})\s+{PCT}")
    # Ein Block pro Instrument endet mit "ISIN)" oder mit der Zahlenzeile.
    blocks = re.split(r"(?<=\))\s*\n", section)
    holdings = []
    for b in blocks:
        m = nums.search(b)
        if not m:
            continue
        isin_m = ISIN_RE.search(b)
        name = nums.sub(" ", b)
        name = re.sub(r"\(ISIN:?", " ", name)
        if isin_m:
            name = name.replace(isin_m.group(1), " ")
        name = re.sub(r"[()]", " ", name)
        name = re.sub(r"\s+", " ", name).strip()
        holdings.append({
            "name": name,
            "isin": isin_m.group(1) if isin_m else None,
            "currency": m.group(1),
            "quantity": parse_number(m.group(2)),
            "fx_rate": parse_number(m.group(3)),
            "open_price": parse_number(m.group(4)),
            "current_price": parse_number(m.group(5)),
            "change_pct": parse_number(m.group(6)),
            "unrealized_pnl": parse_number(m.group(7)),
            "market_value": parse_number(m.group(8)),
            "weight_pct": parse_number(m.group(9)),
        })
    for h in holdings:
        # Implizierter Ø-Wechselkurs beim Kauf: Einstandswert CHF / (Menge * Eröffnungskurs)
        if h["quantity"] and h["open_price"] and h["market_value"] is not None and h["unrealized_pnl"] is not None:
            cost_chf = h["market_value"] - h["unrealized_pnl"]
            h["cost_basis"] = round(cost_chf, 2)
            h["implied_fx_at_purchase"] = cost_chf / (h["quantity"] * h["open_price"])
    return holdings


def _costs(text: str) -> dict[str, Any]:
    def grab(label: str) -> float | None:
        m = re.search(rf"{label}\s+({NUM})\s*CHF", text)
        return parse_number(m.group(1)) if m else None

    res = {
        "commission": grab("Provision"),
        "fx_conversion": grab("Währungsumrechnung"),
        "stamp_duty_foreign": grab("Stempelgebühr"),
        "product_costs": grab(r"\* ?Externe Produktkosten"),
        "total": grab("Gesamtkosten in Periode"),
    }
    m = re.findall(rf"Stempelgebühr\s+({NUM})\s*CHF", text)
    if len(m) >= 2:
        res["stamp_duty_foreign"] = parse_number(m[0])
        res["stamp_duty_domestic"] = parse_number(m[1])
    m2 = re.search(rf"Portfolio-\s+({NUM})\s*CHF", text)
    if m2:
        res["avg_exposure"] = parse_number(m2.group(1))
    m = re.search(rf"Kosten als Prozentsatz\s+{PCT}", text)
    if m:
        res["total_pct"] = parse_number(m.group(1))
    return res
