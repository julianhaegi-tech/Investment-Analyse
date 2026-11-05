"""Hilfsfunktionen für Zahlen und Datumsangaben aus Saxo-Exporten."""

from __future__ import annotations

import re
from datetime import date, datetime

MONTHS = {
    "jan": 1, "feb": 2, "mar": 3, "mär": 3, "maer": 3, "apr": 4, "may": 5, "mai": 5, "jun": 6,
    "jul": 7, "aug": 8, "sep": 9, "oct": 10, "okt": 10, "nov": 11, "dec": 12, "dez": 12,
}

ISIN_RE = re.compile(r"\b([A-Z]{2}[A-Z0-9]{9}\d)\b")
DATE_TOKEN_RE = re.compile(r"\b(\d{1,2})[-. ]([A-Za-zäÄ]{3})[a-z]*[-. ](\d{4})\b")


def parse_number(text: str | float | int | None) -> float | None:
    """'31,036.42' / "31'036.42" / '-1,770.62' / '15.6 %' / '1.234,56' -> float."""
    if text is None:
        return None
    if isinstance(text, (int, float)):
        return float(text)
    s = str(text).strip().replace("%", "").replace("−", "-").replace(" ", "")
    s = s.replace("CHF", "").replace("EUR", "").replace("USD", "")
    if s in {"", "-", "–", "—"}:
        return None
    s = s.replace("'", "").replace("’", "")
    if "," in s and "." in s:
        if s.rfind(",") > s.rfind("."):  # 1.234,56 (deutsches Format)
            s = s.replace(".", "").replace(",", ".")
        else:
            s = s.replace(",", "")
    elif "," in s:
        # 1,234 (Tausender) vs 12,5 (Dezimal)
        parts = s.split(",")
        if len(parts) == 2 and len(parts[1]) != 3:
            s = s.replace(",", ".")
        else:
            s = s.replace(",", "")
    try:
        return float(s)
    except ValueError:
        return None


def parse_date(text) -> str | None:
    """Liefert ISO-Datum (YYYY-MM-DD) für viele Saxo-Formate."""
    if text is None:
        return None
    if isinstance(text, datetime):
        return text.date().isoformat()
    if isinstance(text, date):
        return text.isoformat()
    s = str(text).strip()
    if not s or s.lower() == "nan":
        return None
    m = DATE_TOKEN_RE.search(s)
    if m:
        mon = MONTHS.get(m.group(2).lower()[:3])
        if mon:
            return date(int(m.group(3)), mon, int(m.group(1))).isoformat()
    head = s.replace("T", " ").split(" ")[0]
    for fmt in ("%Y-%m-%d", "%d.%m.%Y", "%d/%m/%Y", "%d-%m-%Y", "%d.%m.%y"):
        try:
            return datetime.strptime(head, fmt).date().isoformat()
        except ValueError:
            continue
    try:
        import pandas as pd

        return pd.to_datetime(s, dayfirst=True).date().isoformat()
    except Exception:
        return None
