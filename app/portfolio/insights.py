"""Kurze, regelbasierte Analyse in Textform."""

from __future__ import annotations

from typing import Any


def chf(x: float | None, dec: int = 0) -> str:
    if x is None:
        return "–"
    return ("-" if x < 0 else "") + "CHF " + f"{abs(x):,.{dec}f}".replace(",", "'")


def pct(x: float | None, sign: bool = True) -> str:
    if x is None:
        return "–"
    return (f"{x:+.1f}" if sign else f"{x:.1f}") + " %"


def fdate(d: Any) -> str:
    s = str(d)[:10]
    return ".".join(reversed(s.split("-"))) if s and s != "None" else "–"


def insights(a: dict[str, Any]) -> list[tuple[str, str, str]]:
    """Liste von (Icon, Titel, Text)."""
    k = a["kpi"]
    out: list[tuple[str, str, str]] = []
    years = k["days"] / 365.25

    out.append(("📈" if k["pnl"] >= 0 else "📉", "Gesamtbild",
                f"In {years:.1f} Jahren hast du {chf(k['deposits'])} eingezahlt. Heute ist das Depot {chf(k['value'])} "
                f"wert. Das sind {chf(k['pnl'])} Gewinn ({pct(k['pnl_pct'])}). Deine persönliche Rendite (IRR) "
                f"liegt bei {pct(k['irr_pct'])} pro Jahr."))

    closed = [p for p in a["positions"] if not p["open"]]
    if closed:
        best = max(closed, key=lambda p: p["realized_chf"])
        worst = min(closed, key=lambda p: p["realized_chf"])
        txt = (f"{len(closed)} ETFs hast du wieder verkauft und dabei {chf(sum(p['realized_chf'] for p in closed))} "
               f"Gewinn realisiert. Am meisten brachte {best['name']} ({chf(best['realized_chf'])}).")
        if worst["realized_chf"] < 0:
            txt += f" Einziger Verlust: {worst['name']} ({chf(worst['realized_chf'])})."
        out.append(("🔁", "Verkaufte ETFs", txt))

    for sw in a["switches"]:
        out.append(("🔀", f"Umschichtung am {fdate(sw['date'])}",
                    f"Verkauft für {chf(sw['sold_chf'])}, gekauft für {chf(sw['bought_chf'])}. "
                    f"Kosten der Umschichtung: {chf(sw['costs'])} "
                    f"({pct(sw['costs'] / max(sw['sold_chf'], 1) * 100, False)} des Betrags)."))

    if k["price_effect"] or k["fx_effect"]:
        out.append(("💱", "Währung",
                    f"Beim aktuellen ETF kommen {chf(k['price_effect'])} aus dem Kursanstieg und "
                    f"{chf(k['fx_effect'])} aus dem Wechselkurs EUR/CHF. "
                    + ("Der stärkere Franken hat also einen Teil des Gewinns weggenommen. " if k["fx_effect"] < 0 else "")
                    + "Weil der ETF weltweit investiert, steckt das eigentliche Währungsrisiko in den Aktien (v. a. USD), "
                      "nicht in der Handelswährung EUR."))

    tc = k["total_costs"]
    if tc:
        ck = a["cost_kinds"]
        top = max(((n, v or 0) for n, v in ck.items()), key=lambda x: x[1])
        out.append(("🧾", "Kosten",
                    f"Insgesamt hast du {chf(tc)} Kosten bezahlt ({pct(tc / max(k['deposits'], 1) * 100, False)} der "
                    f"Einzahlungen). Grösster Posten: {top[0]} ({chf(top[1])}). Jede Umschichtung kostet zweimal "
                    "Courtage, Stempelsteuer und Devisenspread. Seltener wechseln spart am meisten."))

    for b in a["benchmarks"]:
        diff = k["value"] - float(b["value"].iloc[-1])
        out.append(("⚖️", f"Vergleich mit {b['label']}",
                    f"Mit denselben Einzahlungen in {b['label']} (in CHF) hättest du heute {chf(float(b['value'].iloc[-1]))}. "
                    f"Dein Depot liegt {chf(abs(diff))} {'darüber' if diff >= 0 else 'darunter'}."))

    exp = a["exposure"]
    if exp.get("country"):
        c = exp["country"][0]
        ch = next((x for x in exp["country"] if x["name"].lower() in ("schweiz", "switzerland")), None)
        out.append(("🌍", "Länder", f"Grösstes Land ist {c['name']} mit {pct(c['weight'], False)}."
                    + (f" Die Schweiz macht nur {pct(ch['weight'], False)} aus." if ch else "")))
    if exp.get("holding"):
        top10 = sum(h["weight"] for h in exp["holding"][:10])
        h0 = exp["holding"][0]
        out.append(("🏢", "Konzentration", f"Die Top-10-Firmen machen {pct(top10, False)} des ETFs aus. Grösste Position: "
                    f"{h0['name']} ({pct(h0['weight'], False)}, bei dir rund {chf(h0['value_chf'])})."))

    if k.get("max_dd_pct") and a["has_market"]:
        out.append(("🌊", "Schwankungen", f"Der grösste Rückgang vom Höchststand betrug {pct(k['max_dd_pct'])}"
                    + (f" (am {fdate(k['max_dd_date'])})" if k.get("max_dd_date") is not None else "") + "."
                    + (f" Die Schwankung (Volatilität) liegt bei {pct(k['vol_pct'], False)} pro Jahr." if k.get("vol_pct") else "")))
    return out
