"""Regelbasierte Text-Analyse aus den berechneten Kennzahlen (keine KI, keine Kosten)."""

from __future__ import annotations

from typing import Any


def chf(x: float | None) -> str:
    if x is None:
        return "–"
    s = f"{abs(x):,.0f}".replace(",", "'")
    return f"{'-' if x < 0 else ''}CHF {s}"


def fdate(d: str | None) -> str:
    return ".".join(reversed(d.split("-"))) if d else "–"


def pct(x: float | None, sign: bool = True) -> str:
    if x is None:
        return "–"
    return f"{x:+.1f} %" if sign else f"{x:.1f} %"


def build_insights(state: dict[str, Any]) -> list[dict[str, str]]:
    out: list[dict[str, str]] = []
    rep = state.get("report") or {}

    def add(title: str, text: str, tone: str = "neutral") -> None:
        out.append({"title": title, "text": text, "tone": tone})

    k = state.get("kpis")
    if k:
        years = k["days"] / 365.25
        tone = "good" if (k["pnl"] or 0) >= 0 else "bad"
        txt = (f"Seit dem ersten Kauf am {fdate(k['start'])} ({years:.1f} Jahre) hast du "
               f"{chf(k['net_invested'])} eingezahlt (Umschichtungen zwischen ETFs nicht doppelt gezählt). Heute ist das Depot {chf(k['value'])} wert, "
               f"das ergibt {chf(k['pnl'])} Gewinn bzw. Verlust ({pct(k['pnl_pct_on_invested'])} auf das investierte Kapital).")
        if k.get("irr_pct") is not None:
            txt += (f" Die geldgewichtete Rendite (IRR) beträgt {pct(k['irr_pct'])} pro Jahr. Sie berücksichtigt, "
                    f"wann wie viel Geld investiert war.")
        add("Gesamtbild", txt, tone)

        if k.get("irr_pct") is not None and k.get("twr_pa_pct") is not None:
            diff = k["irr_pct"] - k["twr_pa_pct"]
            if abs(diff) > 1:
                add("Timing deiner Einzahlungen",
                    f"Die zeitgewichtete Rendite (TWR, misst nur das Produkt) liegt bei {pct(k['twr_pa_pct'])} p.a., "
                    f"deine persönliche Rendite (IRR) bei {pct(k['irr_pct'])} p.a. "
                    + ("Dein Einstiegs-Timing hat also geholfen." if diff > 0 else
                       "Grössere Beträge kamen eher vor schwächeren Phasen. Das Timing hat Rendite gekostet."),
                    "good" if diff > 0 else "warn")

        bms = state.get("benchmarks") or []
        for b in bms:
            if b.get("sim_final") is None:
                continue
            delta = (k["value"] or 0) - b["sim_final"]
            add(f"Vergleich mit {b['label']}",
                f"Hättest du dieselben Beträge an denselben Tagen in {b['label']} (in CHF gerechnet) investiert, "
                f"wäre das heute {chf(b['sim_final'])} wert. Dein Depot liegt damit {chf(abs(delta))} "
                f"{'darüber' if delta >= 0 else 'darunter'}.",
                "good" if delta >= 0 else "warn")

        if k.get("fx_effect") is not None and k.get("price_effect") is not None and (k["fx_effect"] or k["price_effect"]):
            fx_e, px_e = k["fx_effect"], k["price_effect"]
            add("Währungseffekt",
                f"Auf den offenen Positionen stammen {chf(px_e)} aus der Kursentwicklung und {chf(fx_e)} aus dem Wechselkurs. "
                + ("Der stärkere Franken hat einen Teil des Gewinns aufgefressen. " if fx_e < 0 else
                   "Der Wechselkurs hat zusätzlich geholfen. ")
                + "Wichtig: Die Handelswährung (z. B. EUR) ist nicht das eigentliche Risiko. Ein globaler ETF hält "
                  "überwiegend US-Dollar-Aktien. Das Währungsrisiko gegenüber dem CHF steckt in den Firmen selbst.",
                "warn" if fx_e < 0 else "good")

        if k.get("max_drawdown_pct") is not None and k["max_drawdown_pct"] < -1:
            add("Risiko",
                f"Der grösste zwischenzeitliche Rückgang betrug {pct(k['max_drawdown_pct'])} "
                f"(Tiefpunkt am {fdate(k['max_drawdown_date'])})."
                + (f" Die annualisierte Schwankung (Volatilität) liegt bei {pct(k['volatility_pct'], False)}."
                   if k.get("volatility_pct") else "")
                + (f" Sharpe-Ratio: {k['sharpe']:.2f}." if k.get("sharpe") is not None and k["days"] >= 180 else ""),
                "neutral")

        closed = [p for p in state.get("positions", []) if not p["open"]]
        if closed:
            best = max(closed, key=lambda p: p["realized_pnl"] or 0)
            add("Frühere ETFs",
                f"Du hast {len(closed)} ETF(s) wieder verkauft. Realisiert insgesamt: {chf(sum(p['realized_pnl'] or 0 for p in closed))}. "
                f"Den grössten Beitrag lieferte {best['name']} mit {chf(best['realized_pnl'])}. "
                "Jeder Wechsel kostete Courtage, Stempelsteuer und Devisenspread, siehe Kosten.",
                "neutral")

    for sw in state.get("switches") or []:
        add(f"Umschichtung am {fdate(sw['date'])}",
            f"Verkauft für {chf(sw['sold'])}: {', '.join(sw['sells'])}. Gekauft für {chf(sw['bought'])}: "
            f"{', '.join(sw['buys'])}. Kosten der Umschichtung (Courtage, Stempelsteuer, Devisen, beide Seiten): "
            f"{chf(sw['costs'])}, also {pct(sw['cost_pct'], False)} des umgeschichteten Betrags.",
            "warn" if (sw.get("cost_pct") or 0) > 0.5 else "neutral")

    costs = rep.get("costs") or {}
    lc = state.get("ledger_costs")
    if lc and lc.get("total"):
        costs = {"total": lc["total"], "total_pct": lc.get("total_pct"), "fx_conversion": lc.get("fx_conversion"),
                 "commission": lc.get("commission"), "stamp_duty_foreign": lc.get("stamp_duty"),
                 "product_costs": lc.get("product_costs")}
        n_sw = sum(1 for t in state.get("ledger_trades", []))
        if n_sw:
            costs["_trades"] = n_sw
    if costs.get("total"):
        parts = sorted([("Devisenumrechnung", costs.get("fx_conversion")), ("Courtage", costs.get("commission")),
                        ("Stempelsteuer", (costs.get("stamp_duty_foreign") or 0) + (costs.get("stamp_duty_domestic") or 0)),
                        ("Produktkosten (TER)", costs.get("product_costs"))], key=lambda kv: -(kv[1] or 0))
        top = parts[0]
        txt = (f"Laut Saxo hast du im Zeitraum {chf(costs['total'])} Kosten bezahlt"
               + (f" (bei {costs['_trades']} Käufen/Verkäufen)" if costs.get("_trades") else "") + ", "
               f"{pct(costs.get('total_pct'), False)} des durchschnittlich investierten Kapitals. "
               f"Grösster Posten: {top[0]} ({chf(top[1])}).")
        if top[0] == "Devisenumrechnung":
            txt += (" Tipp: Wenn ein ETF auch in CHF (z. B. an der SIX) gehandelt wird, entfällt beim Kauf "
                    "die Saxo-Devisengebühr. Die Stempelsteuer bleibt gleich.")
        add("Kosten", txt, "warn" if (costs.get("total_pct") or 0) > 1 else "neutral")

    exp = state.get("exposure") or {}
    countries = exp.get("country") or []
    sectors = exp.get("sector") or []
    holdings = exp.get("holding") or []
    if countries:
        us = next((c for c in countries if c["name"].lower() in ("usa", "vereinigte staaten", "united states")), None)
        ch = next((c for c in countries if c["name"].lower() in ("schweiz", "switzerland")), None)
        txt = f"Grösstes Land: {countries[0]['name']} mit {pct(countries[0]['weight_pct'], False)}."
        if us and us is not countries[0]:
            txt += f" USA: {pct(us['weight_pct'], False)}."
        if ch:
            txt += f" Die Schweiz macht nur {pct(ch['weight_pct'], False)} aus (Home Bias: keiner)."
        add("Länder", txt, "neutral")
    if sectors:
        top2 = sectors[:2]
        add("Sektoren",
            f"Die zwei grössten Sektoren sind {top2[0]['name']} ({pct(top2[0]['weight_pct'], False)})"
            + (f" und {top2[1]['name']} ({pct(top2[1]['weight_pct'], False)})." if len(top2) > 1 else ".")
            + " SRI- und Paris-Aligned-Indizes schliessen fossile Energie und kontroverse Branchen weitgehend aus. "
              "Das verschiebt Gewichte zu Technologie, Gesundheit und Finanzen.",
            "neutral")
    if holdings:
        top10 = sum(h["weight_pct"] or 0 for h in holdings[:10])
        add("Konzentration",
            f"Die Top-{min(10, len(holdings))} Positionen machen {pct(top10, False)} des ETFs aus. "
            f"Grösste Einzelposition: {holdings[0]['name']} ({pct(holdings[0]['weight_pct'], False)}, "
            f"bei dir ≈ {chf(holdings[0]['value_chf'])}).",
            "warn" if top10 > 30 else "neutral")
    if (exp.get("meta") or {}).get("missing"):
        add("Fehlende Daten", "Für " + ", ".join(exp["meta"]["missing"]) +
            " konnte die Zusammensetzung noch nicht geladen werden. Klicke auf «Aktualisieren».", "warn")

    if rep.get("twr_total_pct") is not None and rep.get("benchmark_total_pct") is not None:
        d = rep["twr_total_pct"] - rep["benchmark_total_pct"]
        add("Saxo-Bericht",
            f"Saxo weist eine zeitgewichtete Rendite von {pct(rep['twr_total_pct'])} aus. Der Saxo-Benchmark "
            f"«{rep.get('benchmark_name') or 'Benchmark'}» kam auf {pct(rep['benchmark_total_pct'])} "
            f"({'+' if d >= 0 else ''}{d:.1f} Prozentpunkte). Der SMI ist für ein Weltportfolio allerdings kein fairer Vergleich. "
            "Aussagekräftiger ist ein MSCI ACWI in CHF.",
            "neutral")
    return out
