"""Plotly-Grafiken mit einheitlichem, ruhigem Stil."""

from __future__ import annotations

import re
from typing import Any

import pandas as pd
import plotly.graph_objects as go

BLUE, ORANGE, AQUA, YELLOW, MAGENTA, GREEN, VIOLET, RED = (
    "#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4", "#008300", "#6250d6", "#e34948")
SERIES = [BLUE, ORANGE, AQUA, YELLOW, MAGENTA, GREEN, VIOLET, RED]
POS, NEG, INK, MUTED, GRID = BLUE, RED, "#1f2937", "#6b7280", "#eceae4"


def short(name: str) -> str:
    s = name.replace("Clmt", "Climate").replace("Algnd", "Aligned")
    s = re.sub(r"\b(UCITS|ETF|Paris Aligned|MSCI)\b", "", s)
    return re.sub(r"\s+", " ", s).strip()


def color_map(names: list[str]) -> dict[str, str]:
    return {n: SERIES[i % len(SERIES)] for i, n in enumerate(names)}


def chf(v: float) -> str:
    return f"CHF {v:,.0f}".replace(",", "'")


def _layout(fig: go.Figure, height: int = 360, **kw: Any) -> go.Figure:
    opts = dict(
        height=height, margin=dict(l=8, r=8, t=8, b=8), paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)", font=dict(family="Inter, Segoe UI, sans-serif", size=13, color=INK),
        hovermode="x unified", separators=".'", legend=dict(orientation="h", y=1.02, yanchor="bottom", x=0, title=None),
        hoverlabel=dict(bgcolor="white", font_size=13))
    fig.update_layout(**{**opts, **kw})
    fig.update_xaxes(showgrid=False, linecolor=GRID, ticks="", title=None)
    fig.update_yaxes(gridcolor=GRID, zeroline=False, title=None, tickformat=",.0f")
    return fig


def value_chart(a: dict) -> go.Figure:
    d = a["daily"]
    fig = go.Figure()
    fig.add_scatter(x=d.index, y=d["Depotwert"], name="Depotwert", mode="lines", line=dict(color=BLUE, width=2.5),
                    fill="tozeroy", fillcolor="rgba(42,120,214,0.10)", hovertemplate="%{y:,.0f} CHF")
    fig.add_scatter(x=d.index, y=d["Einzahlungen"], name="Einzahlungen", mode="lines",
                    line=dict(color=ORANGE, width=2, shape="hv"), hovertemplate="%{y:,.0f} CHF")
    tx = [t for t in a["report"]["transactions"] if t["kind"] in ("buy", "sell")]
    days: dict[str, list[str]] = {}
    for t in tx:
        days.setdefault(t["date"], []).append(("Kauf " if t["kind"] == "buy" else "Verkauf ") + short(t["instrument"]))
    xs = [pd.Timestamp(x) for x in days]
    fig.add_scatter(x=xs, y=[d["Depotwert"].get(x) for x in xs], name="Käufe / Verkäufe", mode="markers",
                    marker=dict(size=9, color="white", line=dict(color=INK, width=1.5)),
                    text=["<br>".join(sorted(set(v))) for v in days.values()], hovertemplate="%{text}<extra></extra>")
    return _layout(fig, 380)


def pnl_waterfall(a: dict) -> go.Figure:
    k = a["kpi"]
    # Positive Beiträge zuerst, damit negative Balken nie über die Null-Linie in die Beschriftung ragen
    closed = sorted(((short(p["name"]), p["realized_chf"]) for p in a["positions"] if not p["open"]), key=lambda x: -x[1])
    items = [(f"{n} (verkauft)", v) for n, v in closed if v >= 0] + [("Kursgewinn aktueller ETF", k["price_effect"])]
    items += [(f"{n} (verkauft)", v) for n, v in closed if v < 0]
    items += [("Währung aktueller ETF", k["fx_effect"]), ("Kaufkosten aktueller ETF", k["buy_costs_open"])]
    fig = go.Figure(go.Waterfall(
        orientation="h", y=[i[0] for i in items] + ["Gewinn total"], x=[i[1] for i in items] + [k["pnl"]],
        measure=["relative"] * len(items) + ["total"], text=[chf(v) for _, v in items] + [chf(k["pnl"])],
        textposition="outside", cliponaxis=False, connector=dict(line=dict(color=GRID)),
        increasing=dict(marker=dict(color=POS)), decreasing=dict(marker=dict(color=NEG)),
        totals=dict(marker=dict(color=INK)), hovertemplate="%{y}: %{text}<extra></extra>"))
    fig = _layout(fig, 60 + 40 * (len(items) + 1), hovermode="closest", showlegend=False)
    fig.update_yaxes(autorange="reversed", gridcolor="rgba(0,0,0,0)", tickformat=None)
    fig.update_xaxes(showgrid=True, gridcolor=GRID, tickformat=",.0f", tickangle=0, nticks=6)
    fig.update_layout(margin=dict(l=8, r=90, t=8, b=8))
    return fig


def twr_chart(a: dict) -> go.Figure:
    fig = go.Figure()
    fig.add_scatter(x=a["twr"].index, y=a["twr"] * 100, name="Dein Depot", line=dict(color=BLUE, width=2.5),
                    hovertemplate="%{y:.1f} %")
    for i, b in enumerate(a["benchmarks"]):
        fig.add_scatter(x=b["twr"].index, y=b["twr"] * 100, name=b["label"], line=dict(color=SERIES[i + 1], width=2),
                        hovertemplate="%{y:.1f} %")
    fig = _layout(fig, 360)
    fig.update_yaxes(ticksuffix=" %", tickformat=".0f", zeroline=True, zerolinecolor="#cfccc4")
    return fig


def bench_value_chart(a: dict) -> go.Figure:
    fig = go.Figure()
    fig.add_scatter(x=a["daily"].index, y=a["daily"]["Depotwert"], name="Dein Depot", line=dict(color=BLUE, width=2.5),
                    hovertemplate="%{y:,.0f} CHF")
    for i, b in enumerate(a["benchmarks"]):
        fig.add_scatter(x=b["value"].index, y=b["value"], name=b["label"], line=dict(color=SERIES[i + 1], width=2),
                        hovertemplate="%{y:,.0f} CHF")
    return _layout(fig, 320)


def monthly_chart(a: dict) -> go.Figure:
    m = a["monthly"] * 100
    fig = go.Figure(go.Bar(x=m.index.strftime("%b %y"), y=m.values, marker_color=[POS if v >= 0 else NEG for v in m.values],
                           hovertemplate="%{x}: %{y:.1f} %<extra></extra>"))
    fig = _layout(fig, 300, hovermode="closest", showlegend=False)
    fig.update_yaxes(ticksuffix=" %", tickformat=".0f")
    fig.update_xaxes(tickangle=0, nticks=7)
    return fig


def drawdown_chart(a: dict) -> go.Figure:
    dd = a["drawdown"] * 100
    fig = go.Figure(go.Scatter(x=dd.index, y=dd, fill="tozeroy", line=dict(color=NEG, width=1.5),
                               fillcolor="rgba(227,73,72,0.12)", hovertemplate="%{y:.1f} %", name="Drawdown"))
    fig = _layout(fig, 300, showlegend=False)
    fig.update_yaxes(ticksuffix=" %", tickformat=".0f")
    return fig


def timeline(a: dict) -> go.Figure:
    pos = sorted(a["positions"], key=lambda p: p["first_buy"])
    cmap = color_map([p["name"] for p in pos])
    end = a["kpi"]["end"]
    fig = go.Figure()
    for p in pos:
        for s, e in p["periods"]:
            s_ts, e_ts = pd.Timestamp(s), pd.Timestamp(e) if e else end
            fig.add_trace(go.Bar(
                y=[short(p["name"])], x=[(e_ts - s_ts).days * 86400000], base=[s_ts], orientation="h",
                marker=dict(color=cmap[p["name"]], line=dict(width=0)), showlegend=False,
                hovertemplate=f"{short(p['name'])}<br>{s_ts:%d.%m.%Y} – {e_ts:%d.%m.%Y}<br>G/V {chf(p['pnl_chf'])}<extra></extra>"))
    fig = _layout(fig, 60 + 46 * len(pos), hovermode="closest", bargap=0.35)
    fig.update_xaxes(type="date", showgrid=True, gridcolor=GRID)
    fig.update_yaxes(autorange="reversed", gridcolor="rgba(0,0,0,0)", tickformat=None)
    return fig


def stack_chart(a: dict) -> go.Figure:
    v = a["values"]
    names = sorted(v.columns, key=lambda n: next(p["first_buy"] for p in a["positions"] if p["name"] == n))
    cmap = color_map(names)
    fig = go.Figure()
    for n in names:
        s = v[n].where(v[n] > 0.5)
        fig.add_scatter(x=s.index, y=s, name=short(n), stackgroup="one", mode="lines",
                        line=dict(width=0.5, color=cmap[n]), hovertemplate="%{y:,.0f} CHF")
    return _layout(fig, 360)


def hbar(rows: list[tuple[str, float]], color: str = BLUE, fmt=chf, height: int | None = None) -> go.Figure:
    rows = [r for r in rows if r[1] is not None]
    fig = go.Figure(go.Bar(
        y=[r[0] for r in rows], x=[r[1] for r in rows], orientation="h",
        marker_color=[color if r[1] >= 0 else NEG for r in rows], text=[fmt(r[1]) for r in rows],
        textposition="outside", cliponaxis=False, hovertemplate="%{y}: %{text}<extra></extra>"))
    fig = _layout(fig, height or (40 + 38 * len(rows)), hovermode="closest", showlegend=False, bargap=0.3)
    fig.update_yaxes(autorange="reversed", gridcolor="rgba(0,0,0,0)", tickformat=None)
    fig.update_xaxes(showgrid=True, gridcolor=GRID, tickformat=",.0f", zeroline=True, zerolinecolor="#cfccc4",
                     tickangle=0, nticks=5)
    fig.update_layout(margin=dict(l=8, r=80, t=8, b=8))
    return fig


def price_chart(a: dict, name: str) -> go.Figure | None:
    px = a["price_series"].get(name)
    pos = next(p for p in a["positions"] if p["name"] == name)
    trades = [t for t in a["report"]["transactions"] if t.get("instrument") == name]
    fig = go.Figure()
    if px is not None and not px.empty:
        start = pd.Timestamp(trades[0]["date"]) - pd.Timedelta(days=30)
        px = px[px.index >= start]
        fig.add_scatter(x=px.index, y=px, name=f"Kurs ({pos['currency']})", line=dict(color=BLUE, width=2),
                        hovertemplate="%{y:.2f} " + pos["currency"])
    for kind, sym, col, lab in (("buy", "triangle-up", AQUA, "Kauf"), ("sell", "triangle-down", RED, "Verkauf")):
        tt = [t for t in trades if t["kind"] == kind]
        if tt:
            fig.add_scatter(x=[pd.Timestamp(t["date"]) for t in tt], y=[t["price"] for t in tt], mode="markers", name=lab,
                            marker=dict(symbol=sym, size=13, color=col, line=dict(color="white", width=1.5)),
                            text=[f"{lab} {t['qty']:,.0f} × {t['price']:.2f} ({chf(abs(t['amount_chf']))})".replace(",", "'") for t in tt],
                            hovertemplate="%{text}<extra></extra>")
    fig = _layout(fig, 340)
    fig.update_yaxes(tickformat=",.2f")
    return fig
