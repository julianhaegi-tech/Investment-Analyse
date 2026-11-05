"""Saxo Portfolio – Streamlit-App. Start: SaxoPortfolio.exe (oder `streamlit run app.py`)."""

from __future__ import annotations

import os
import threading
import time

import pandas as pd
import streamlit as st

from portfolio import charts as C
from portfolio.analytics import analyse
from portfolio.insights import chf, fdate, insights, pct
from portfolio.market import instrument_list, refresh
from portfolio.report import parse_report
from portfolio.store import Store, data_dir

st.set_page_config(page_title="Saxo Portfolio", page_icon="📈", layout="wide")
st.markdown("""
<style>
  .block-container {padding-top: 2rem; max-width: 1300px;}
  [data-testid="stMetric"] {background: #fff; border: 1px solid #e7e5df; border-radius: 12px; padding: 14px 16px;}
  [data-testid="stMetricLabel"] p {font-size: 0.85rem; color: #6b7280;}
  [data-testid="stMetricValue"] {font-size: 1.45rem;}
  h1 {font-size: 1.9rem !important;}
  h3 {font-size: 1.1rem !important; font-weight: 600 !important; margin-top: .6rem !important;}
  .muted {color: #6b7280; font-size: 0.9rem;}
  .kpis {display: grid; grid-template-columns: repeat(5, minmax(0, 1fr)); gap: 12px; margin: 6px 0 18px;}
  .kpi {background: #fff; border: 1px solid #e7e5df; border-radius: 14px; padding: 16px 18px;}
  .kpi .l {font-size: .82rem; color: #6b7280;}
  .kpi .v {font-size: 1.6rem; font-weight: 650; color: #111827; margin-top: 2px; font-variant-numeric: tabular-nums;}
  .kpi .s {font-size: .82rem; color: #6b7280; margin-top: 2px;}
  .kpi .s.up {color: #0a7d33;} .kpi .s.down {color: #c43c3c;}
  @media (max-width: 900px) {.kpis {grid-template-columns: repeat(2, minmax(0, 1fr));}}
</style>""", unsafe_allow_html=True)


@st.cache_resource
def get_store() -> Store:
    return Store()


@st.cache_resource
def _autostop() -> bool:
    """Beendet den Server, wenn 10 Minuten lang kein Browser-Tab offen ist (nur beim Start über die .exe)."""
    if os.environ.get("PORTFOLIO_AUTOSTOP") != "1":
        return False

    def watch():
        idle_since = None
        while True:
            time.sleep(30)
            try:
                from streamlit.runtime import get_instance

                n = len(get_instance()._session_mgr.list_active_sessions())
            except Exception:  # noqa: BLE001
                continue
            idle_since = (idle_since or time.time()) if n == 0 else None
            if idle_since and time.time() - idle_since > 600:
                os._exit(0)

    threading.Thread(target=watch, daemon=True).start()
    return True


_autostop()
store = get_store()

# ============================================================================ Seitenleiste
with st.sidebar:
    st.markdown("### 📈 Saxo Portfolio")
    up = st.file_uploader("Transaktions- und Saldenbericht (PDF)", type=["pdf"],
                          help="SaxoTraderGO → Konto → Berichte → «Transaktions- und Saldenbericht», "
                               "Zeitraum ab Kontoeröffnung, als PDF herunterladen.")
    if up is not None and st.session_state.get("imported_id") != up.file_id:
        try:
            rep = parse_report(up)
            store.save_report(rep, up.name)
            st.session_state["imported_id"] = up.file_id
            st.session_state["flash"] = (f"Importiert: {len(rep['transactions'])} Transaktionen "
                                         f"({fdate(rep['period_start'])} – {fdate(rep['period_end'])}).")
            st.rerun()
        except Exception as e:  # noqa: BLE001
            st.error(f"Import fehlgeschlagen: {e}")

    if store.report():
        if st.button("🔄 Kurse aktualisieren", type="primary", width="stretch",
                     help="Lädt Tageskurse, Wechselkurse, Benchmarks und die ETF-Zusammensetzung (gratis, ohne Konto)."):
            with st.status("Lade Marktdaten …", expanded=True) as status:
                steps = refresh(store)
                for s in steps:
                    st.write(("✅ " if s["ok"] else "⚠️ ") + f"**{s['step']}** – {s['msg']}")
                bad = sum(not s["ok"] for s in steps)
                status.update(label="Aktualisiert" if not bad else f"Aktualisiert, {bad} Hinweis(e)",
                              state="complete" if not bad else "error", expanded=bool(bad))
        lr = store.last_refresh()
        st.caption(f"Letzte Aktualisierung: {fdate(lr['ts'])} {lr['ts'][11:16]}" if lr else "Noch nie aktualisiert.")

        with st.expander("⚙️ Einstellungen"):
            s = store.settings()
            rep = store.report()
            st.markdown("**Ticker (Yahoo Finance)** – nur ändern, wenn falsche Kurse geladen werden.")
            df = pd.DataFrame([{"ETF": i["name"], "Ticker": (s["tickers"] or {}).get(i["name"], "")}
                               for i in instrument_list(rep)])
            edited = st.data_editor(df, hide_index=True, width="stretch", disabled=["ETF"], key="tick")
            st.markdown("**Benchmarks**")
            bm_df = pd.DataFrame(s["benchmarks"])
            bm_ed = st.data_editor(bm_df, hide_index=True, num_rows="dynamic", width="stretch",
                                   column_config={"symbol": "Ticker", "label": "Name"}, key="bm")
            if st.button("Speichern", width="stretch"):
                store.save_settings(
                    tickers={r["ETF"]: r["Ticker"].strip() for _, r in edited.iterrows() if str(r["Ticker"]).strip()},
                    benchmarks=[{"symbol": r["symbol"], "label": r["label"] or r["symbol"]}
                                for _, r in bm_ed.iterrows() if str(r.get("symbol") or "").strip()])
                st.success("Gespeichert – jetzt «Kurse aktualisieren».")
            st.caption(f"Daten: {data_dir()}")
            if st.button("Alle Daten löschen", width="stretch"):
                store.reset()
                st.session_state.pop("imported_id", None)
                st.rerun()

if msg := st.session_state.pop("flash", None):
    st.toast(msg, icon="✅")

a = analyse(store)

# ============================================================================ Startseite ohne Daten
if not a:
    st.title("Willkommen 👋")
    st.markdown("""
Diese App analysiert dein Saxo-Depot – lokal auf deinem PC.

1. In **SaxoTraderGO** → *Konto* → *Berichte* → **Transaktions- und Saldenbericht** öffnen.
2. Zeitraum **ab Kontoeröffnung bis heute** wählen und als **PDF** herunterladen.
3. Die Datei links bei **Import** hineinziehen.
4. Optional: **Kurse aktualisieren** für tagesgenaue Verläufe, Benchmarks und Sektoren.
""")
    st.stop()

k = a["kpi"]
rep = a["report"]

# ============================================================================ Kopf & Kennzahlen
st.title("Mein Saxo-Depot")
st.markdown(f"<span class='muted'>Stand {fdate(k['end'])} · Import: {rep.get('_filename', '')} "
            f"({fdate(rep.get('period_start'))} – {fdate(rep.get('period_end'))})</span>", unsafe_allow_html=True)
if not a["has_market"]:
    st.info("Die Verläufe basieren auf den Kursen aus dem Saxo-Bericht (zwischen den Käufen geschätzt). "
            "Für tagesgenaue Kurse, Benchmarks und Sektoren links auf **Kurse aktualisieren** klicken.", icon="ℹ️")

def kpi(label: str, value: str, sub: str = "", tone: str = "") -> str:
    return f"<div class='kpi'><div class='l'>{label}</div><div class='v'>{value}</div><div class='s {tone}'>{sub}</div></div>"


tone = "up" if k["pnl"] >= 0 else "down"
st.markdown("<div class='kpis'>" + "".join([
    kpi("Depotwert", chf(k["value"]), f"Cash {chf(k['cash'])}"),
    kpi("Eingezahlt", chf(k["deposits"]), f"{k['n_trades']} Käufe/Verkäufe"),
    kpi("Gewinn", chf(k["pnl"]), pct(k["pnl_pct"]) + " auf Einzahlungen", tone),
    kpi("Rendite pro Jahr", pct(k["irr_pct"]), "geldgewichtet (IRR)", "up" if (k["irr_pct"] or 0) >= 0 else "down"),
    kpi("Kosten total", chf(k["total_costs"]), pct(k["total_costs"] / max(k["deposits"], 1) * 100, False) + " der Einzahlungen"),
]) + "</div>", unsafe_allow_html=True)

tabs = st.tabs(["Übersicht", "Performance", "ETFs", "Kosten", "Zusammensetzung", "Transaktionen"])

# ---------------------------------------------------------------------------- Übersicht
with tabs[0]:
    st.subheader("Depotwert und Einzahlungen")
    st.plotly_chart(C.value_chart(a), width="stretch", config={"displayModeBar": False})
    st.subheader("Woher der Gewinn kommt")
    st.plotly_chart(C.pnl_waterfall(a), width="stretch", config={"displayModeBar": False})
    st.subheader("Analyse")
    cards = insights(a)
    cols = st.columns(3, gap="medium")
    for i, (icon, title, text) in enumerate(cards):
        with cols[i % 3].container(border=True):
            st.markdown(f"**{icon} {title}**")
            st.markdown(f"<span style='font-size:0.93rem'>{text}</span>", unsafe_allow_html=True)

# ---------------------------------------------------------------------------- Performance
with tabs[1]:
    if not a["has_market"]:
        st.info("Für Benchmark-Vergleich, Monatsrenditen und Schwankungen zuerst **Kurse aktualisieren**.", icon="ℹ️")
    st.subheader("Rendite im Vergleich (zeitgewichtet, in CHF)")
    st.plotly_chart(C.twr_chart(a), width="stretch", config={"displayModeBar": False})
    if a["benchmarks"]:
        st.subheader("Gleiche Einzahlungen im Benchmark")
        st.plotly_chart(C.bench_value_chart(a), width="stretch", config={"displayModeBar": False})
    if a["has_market"]:
        l, r = st.columns(2, gap="large")
        with l:
            st.subheader("Monatsrenditen")
            st.plotly_chart(C.monthly_chart(a), width="stretch", config={"displayModeBar": False})
        with r:
            st.subheader("Rückgang vom Höchststand")
            st.plotly_chart(C.drawdown_chart(a), width="stretch", config={"displayModeBar": False})
    rows = [("Zeitgewichtete Rendite", pct(k["twr_pct"])), ("… pro Jahr", pct(k["twr_pa_pct"])),
            ("Geldgewichtete Rendite (IRR) pro Jahr", pct(k["irr_pct"])),
            ("Grösster Rückgang", pct(k["max_dd_pct"]) if a["has_market"] else "–"),
            ("Volatilität pro Jahr", pct(k["vol_pct"], False)),
            ("Sharpe-Ratio", f"{k['sharpe']:.2f}" if k.get("sharpe") is not None else "–")]
    rows += [(f"{b['label']} im selben Zeitraum", pct(b["total_pct"])) for b in a["benchmarks"]]
    st.dataframe(pd.DataFrame(rows, columns=["Kennzahl", "Wert"]), hide_index=True, width="stretch")

# ---------------------------------------------------------------------------- ETFs
with tabs[2]:
    st.subheader("Wann du welchen ETF gehalten hast")
    st.plotly_chart(C.timeline(a), width="stretch", config={"displayModeBar": False})
    st.subheader("Alle ETFs")
    tbl = pd.DataFrame([{
        "ETF": C.short(p["name"]),
        "Gehalten": f"{fdate(p['first_buy'])} – {'heute' if p['open'] else fdate(p['last_trade'])}",
        "Investiert": p["bought_chf"], "Erlös / Wert heute": p["value_chf"] if p["open"] else p["sold_chf"],
        "Gewinn": p["pnl_chf"], "Rendite": p["return_pct"], "Kosten": p["total_costs_chf"],
    } for p in a["positions"]])
    money = st.column_config.NumberColumn(format="CHF %.0f")
    st.dataframe(tbl, hide_index=True, width="stretch", column_config={
        "Investiert": money, "Erlös / Wert heute": money, "Gewinn": money, "Kosten": money,
        "Rendite": st.column_config.NumberColumn(format="%.1f %%")})
    st.subheader("Wert je ETF über die Zeit")
    st.plotly_chart(C.stack_chart(a), width="stretch", config={"displayModeBar": False})
    st.subheader("Kursverlauf mit deinen Käufen und Verkäufen")
    sel = st.selectbox("ETF", [p["name"] for p in a["positions"]], format_func=C.short, label_visibility="collapsed")
    has_px = a["price_series"].get(sel) is not None and not a["price_series"][sel].empty
    n_days = len({t["date"] for t in rep["transactions"] if t.get("instrument") == sel})
    if has_px or n_days > 1:
        st.plotly_chart(C.price_chart(a, sel), width="stretch", config={"displayModeBar": False})
    if not has_px:
        st.caption("Ohne Marktkurse sind nur deine Kauf- und Verkaufskurse bekannt – für den vollen Kursverlauf "
                   "links auf «Kurse aktualisieren» klicken.")

# ---------------------------------------------------------------------------- Kosten
with tabs[3]:
    ck = a["cost_kinds"]
    m = st.columns(4)
    m[0].metric("Kosten total", chf(k["total_costs"], 2))
    m[1].metric("Courtage", chf(ck.get("Courtage"), 2))
    m[2].metric("Stempelsteuer", chf(ck.get("Stempelsteuer"), 2))
    m[3].metric("Devisen & übrige", chf(ck.get("Devisen & übrige"), 2),
                help="Differenz zwischen «Gesamtkosten» und gebuchten Kosten laut Saxo – v. a. Devisenumrechnung.")
    l, r = st.columns(2, gap="large")
    with l:
        st.subheader("Kosten je ETF")
        st.plotly_chart(C.hbar([(C.short(p["name"]), p["total_costs_chf"]) for p in
                                sorted(a["positions"], key=lambda p: -p["total_costs_chf"])], C.ORANGE),
                        width="stretch", config={"displayModeBar": False})
    with r:
        st.subheader("Kosten je Umschichtung")
        if a["switches"]:
            st.plotly_chart(C.hbar([(fdate(s["date"]), s["costs"]) for s in a["switches"]], C.ORANGE),
                            width="stretch", config={"displayModeBar": False})
        else:
            st.caption("Keine Umschichtungen.")
    st.subheader("Kosten je Transaktion")
    tx = [t for t in rep["transactions"] if t["kind"] in ("buy", "sell")]
    st.dataframe(pd.DataFrame([{
        "Datum": pd.Timestamp(t["date"]), "ETF": C.short(t["instrument"]), "Art": "Kauf" if t["kind"] == "buy" else "Verkauf",
        "Betrag": abs(t["amount_chf"]), "Gebuchte Kosten": t["costs_chf"], "Gesamtkosten": t["total_costs_chf"],
        "in %": t["total_costs_chf"] / max(abs(t["amount_chf"]), 1) * 100} for t in reversed(tx)]),
        hide_index=True, width="stretch", column_config={
            "Datum": st.column_config.DateColumn(format="DD.MM.YYYY"), "Betrag": st.column_config.NumberColumn(format="CHF %.2f"),
            "Gebuchte Kosten": st.column_config.NumberColumn(format="CHF %.2f"),
            "Gesamtkosten": st.column_config.NumberColumn(format="CHF %.2f"), "in %": st.column_config.NumberColumn(format="%.2f %%")})

# ---------------------------------------------------------------------------- Zusammensetzung
with tabs[4]:
    exp = a["exposure"]
    if not exp:
        st.info("Sektoren, Länder und Top-Positionen werden mit **Kurse aktualisieren** geladen (Quelle: justETF).", icon="ℹ️")
    else:
        st.caption("Gewichtet nach deinen aktuellen ETFs · Quelle: " + ", ".join(a["exposure_sources"]))
        l, r = st.columns(2, gap="large")
        with l:
            st.subheader("Sektoren")
            st.plotly_chart(C.hbar([(e["name"], e["weight"]) for e in exp.get("sector", [])[:12]], C.BLUE,
                                   fmt=lambda v: f"{v:.1f} %"), width="stretch", config={"displayModeBar": False})
        with r:
            st.subheader("Länder")
            st.plotly_chart(C.hbar([(e["name"], e["weight"]) for e in exp.get("country", [])[:12]], C.AQUA,
                                   fmt=lambda v: f"{v:.1f} %"), width="stretch", config={"displayModeBar": False})
        if exp.get("holding"):
            st.subheader("Top-Positionen – dein Anteil in CHF")
            st.plotly_chart(C.hbar([(e["name"], e["value_chf"]) for e in exp["holding"][:10]], C.VIOLET),
                            width="stretch", config={"displayModeBar": False})
        for isin, meta in a["etf_meta"].items():
            if meta:
                st.caption(" · ".join(f"{k_}: {v}" for k_, v in meta.items()))

# ---------------------------------------------------------------------------- Transaktionen
with tabs[5]:
    kinds = {"buy": "Kauf", "sell": "Verkauf", "deposit": "Einzahlung", "withdrawal": "Auszahlung", "other": "Andere"}
    st.dataframe(pd.DataFrame([{
        "Datum": pd.Timestamp(t["date"]), "Art": kinds[t["kind"]], "ETF": t["instrument"] or "",
        "Stück": t["qty"], "Kurs": t["price"] if t["kind"] in ("buy", "sell") else None, "Whg.": t["currency"],
        "FX": t["fx"], "Betrag CHF": t["amount_chf"], "Kosten": t["total_costs_chf"] or None,
        "Realisiert": t["realized"]} for t in reversed(rep["transactions"])]),
        hide_index=True, width="stretch", height=560, column_config={
            "Datum": st.column_config.DateColumn(format="DD.MM.YYYY"),
            "Stück": st.column_config.NumberColumn(format="%.0f"), "Kurs": st.column_config.NumberColumn(format="%.3f"),
            "FX": st.column_config.NumberColumn(format="%.4f"), "Betrag CHF": st.column_config.NumberColumn(format="%.2f"),
            "Kosten": st.column_config.NumberColumn(format="%.2f"), "Realisiert": st.column_config.NumberColumn(format="%.2f")})
