"use strict";

const $ = (s) => document.querySelector(s);
const css = (v) => getComputedStyle(document.documentElement).getPropertyValue(v).trim();
const SERIES = () => ["--s1", "--s2", "--s3", "--s4", "--s5", "--s6", "--s7", "--s8"].map(css);
let STATE = null;

// ---------- Formatierung (Schweizer Schreibweise) ----------
const nf = (d) => new Intl.NumberFormat("de-CH", { minimumFractionDigits: d, maximumFractionDigits: d });
const fmtCHF = (v, d = 0) => (v == null ? "–" : "CHF " + nf(d).format(v));
const fmtNum = (v, d = 2) => (v == null ? "–" : nf(d).format(v));
const fmtPct = (v, sign = true) => (v == null ? "–" : (sign && v > 0 ? "+" : "") + nf(1).format(v) + " %");
const fmtDate = (s) => (s ? s.split("-").reverse().join(".") : "–");
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

// ---------- API ----------
async function api(path, opts = {}) {
  const r = await fetch(path, opts);
  const j = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error(j.error || r.statusText);
  return j;
}
function toast(msg, ms = 5000) {
  const t = $("#toast");
  t.textContent = msg; t.hidden = false;
  clearTimeout(toast._t); toast._t = setTimeout(() => (t.hidden = true), ms);
}

// ---------- Plotly-Basis ----------
function baseLayout(extra = {}) {
  return Object.assign({
    paper_bgcolor: "rgba(0,0,0,0)", plot_bgcolor: "rgba(0,0,0,0)",
    font: { family: "system-ui, Segoe UI, sans-serif", size: 12, color: css("--text-2") },
    margin: { l: 56, r: 16, t: 8, b: 36 },
    xaxis: { gridcolor: css("--grid"), linecolor: css("--border"), zeroline: false },
    yaxis: { gridcolor: css("--grid"), linecolor: css("--border"), zerolinecolor: css("--border"), separatethousands: true },
    legend: { orientation: "h", y: -0.18, x: 0 },
    hovermode: "x unified",
    hoverlabel: { bgcolor: css("--surface"), bordercolor: css("--border"), font: { color: css("--text") } },
    separators: ".'",
  }, extra);
}
const CFG = { displayModeBar: false, responsive: true, locale: "de-CH" };
function plot(id, data, layout = {}) {
  const el = document.getElementById(id);
  if (!el) return;
  if (!data || !data.length) { el.innerHTML = '<p class="muted">Keine Daten – importieren bzw. aktualisieren.</p>'; return; }
  el.innerHTML = "";
  Plotly.react(el, data, baseLayout(layout), CFG);
}
function hbar(id, rows, valueKey, labelFmt, color) {
  rows = (rows || []).slice(0, 15).reverse();
  plot(id, rows.length ? [{
    type: "bar", orientation: "h", y: rows.map((r) => r.name), x: rows.map((r) => r[valueKey]),
    marker: { color }, text: rows.map((r) => labelFmt(r)), textposition: "outside", cliponaxis: false,
    hovertemplate: "%{y}: %{text}<extra></extra>",
  }] : [], { margin: { l: 170, r: 70, t: 8, b: 30 }, hovermode: "closest", yaxis: { automargin: true }, xaxis: { gridcolor: css("--grid"), ticksuffix: valueKey.endsWith("pct") ? " %" : "" } });
}

// ---------- Rendering ----------
async function load() {
  STATE = await api("/api/state");
  render();
}

function render() {
  const s = STATE;
  $("#empty").hidden = !!(s.has_data || s.report);
  const lr = s.last_refresh;
  $("#refresh-info").textContent = lr ? `Letzter Refresh: ${new Date(lr.ts).toLocaleString("de-CH")}${lr.ok ? "" : " (teilweise fehlgeschlagen)"}` : "Noch nie aktualisiert";
  $("#warnings").innerHTML = (s.warnings || []).map((w) => `<div class="banner">${esc(w)}</div>`).join("") +
    (s.reconciliation || []).filter((r) => !r.ok).map((r) => `<div class="banner">Bestand ${esc(r.name)}: laut Saxo ${fmtNum(r.report_qty, 0)} Stück, aus Transaktionen berechnet ${fmtNum(r.calc_qty, 0)}. Fehlen Trades?</div>`).join("");
  renderKpis(s); renderInsights(s); renderValue(s); renderPerformance(s); renderComposition(s);
  renderPositions(s); renderSaxo(s); renderSettings(s);
}

function kpi(label, value, sub = "", trend = null) {
  const cls = trend == null ? "" : trend >= 0 ? "up" : "down";
  return `<div class="kpi"><div class="label">${label}</div><div class="value ${cls}">${value}</div><div class="sub">${sub}</div></div>`;
}
function renderKpis(s) {
  const k = s.kpis;
  if (!k) { $("#kpis").innerHTML = ""; return; }
  $("#kpis").innerHTML = [
    kpi("Depotwert", fmtCHF(k.value), `Stand ${fmtDate(k.end)}`),
    kpi("Eingezahlt", fmtCHF(k.net_invested), `${k.n_trades} Transaktionen · ${k.n_instruments} ETF(s)` + (k.cash > 1 ? ` · Cash ${fmtCHF(k.cash)}` : "")),
    kpi("Gewinn / Verlust", fmtCHF(k.pnl), fmtPct(k.pnl_pct_on_invested) + " auf Einsatz", k.pnl),
    kpi("Rendite p.a. (IRR)", fmtPct(k.irr_pct), "geldgewichtet, deine Rendite", k.irr_pct),
    kpi("Zeitgewichtet (TWR)", fmtPct(k.twr_pct), k.twr_pa_pct != null ? fmtPct(k.twr_pa_pct) + " p.a." : "seit Start", k.twr_pct),
    kpi("Max. Drawdown", fmtPct(k.max_drawdown_pct), k.max_drawdown_date ? "am " + fmtDate(k.max_drawdown_date) : ""),
    kpi("Währungseffekt", fmtCHF(k.fx_effect), "auf offene Positionen", k.fx_effect),
    kpi("Kosten (Saxo)", fmtCHF(s.report?.costs?.total), s.report?.costs?.total_pct != null ? fmtPct(s.report.costs.total_pct, false) + " des Ø-Kapitals" : "Kostenübersicht im Bericht"),
  ].join("");
}

function renderInsights(s) {
  const list = s.insights || [];
  $("#insights").innerHTML = list.length ? list.map((i) => `<div class="insight ${i.tone}"><b>${esc(i.title)}</b><p>${esc(i.text)}</p></div>`).join("")
    : '<p class="muted">Noch keine Analyse – importiere zuerst Daten.</p>';
}

function renderValue(s) {
  if (!s.has_data) return plot("ch-value", []);
  const [c1, c2] = SERIES();
  const buys = (s.positions || []).flatMap((p) => p.trades.map((t) => ({ ...t, name: p.name })));
  const v = s.series.value;
  const valAt = (d) => { const i = v.x.indexOf(d); return i >= 0 ? v.y[i] : null; };
  plot("ch-value", [
    { x: v.x, y: v.y, name: "Depotwert", type: "scatter", mode: "lines", line: { color: c1, width: 2 }, fill: "tozeroy", fillcolor: c1 + "22", hovertemplate: "%{y:,.0f} CHF" },
    { x: s.series.net_invested.x, y: s.series.net_invested.y, name: "Eingezahlt", type: "scatter", mode: "lines", line: { color: c2, width: 2, shape: "hv" }, hovertemplate: "%{y:,.0f} CHF" },
    { x: buys.map((b) => b.date), y: buys.map((b) => valAt(b.date)), name: "Kauf / Verkauf", mode: "markers", type: "scatter",
      marker: { size: 9, symbol: buys.map((b) => (b.side === "BUY" ? "triangle-up" : "triangle-down")), color: css("--text-2"), line: { color: css("--surface"), width: 2 } },
      text: buys.map((b) => `${b.side === "BUY" ? "Kauf" : "Verkauf"} ${fmtNum(b.quantity, 0)} × ${b.name}`), hovertemplate: "%{text}<extra></extra>" },
  ], { yaxis: { gridcolor: css("--grid"), ticksuffix: "", tickformat: ",.0f" } });
}

function renderPerformance(s) {
  if (!s.has_data) { ["ch-twr", "ch-decomp", "ch-sim", "ch-monthly", "ch-dd"].forEach((id) => plot(id, [])); $("#perf-table").innerHTML = ""; return; }
  const col = SERIES();
  const traces = [{ x: s.series.twr_pct.x, y: s.series.twr_pct.y, name: "Dein Depot", mode: "lines", line: { color: col[0], width: 2 }, hovertemplate: "%{y:.1f} %" }];
  (s.benchmarks || []).forEach((b, i) => traces.push({ x: b.twr_pct.x, y: b.twr_pct.y, name: b.label, mode: "lines", line: { color: col[i + 1], width: 2 }, hovertemplate: "%{y:.1f} %" }));
  plot("ch-twr", traces, { yaxis: { gridcolor: css("--grid"), ticksuffix: " %", zerolinecolor: css("--border") } });

  const k = s.kpis;
  const items = [["Realisiert (verkaufte ETFs)", k.realized_pnl], ["Kursgewinn offene Pos.", k.price_effect], ["Währung offene Pos.", k.fx_effect], ["Total", k.pnl]].reverse();
  plot("ch-decomp", [{
    type: "bar", orientation: "h", y: items.map((i) => i[0]), x: items.map((i) => i[1] ?? 0),
    marker: { color: items.map((i) => ((i[1] ?? 0) >= 0 ? css("--pos") : css("--neg"))) },
    text: items.map((i) => fmtCHF(i[1])), textposition: items.map((i) => ((i[1] ?? 0) < 0 ? "inside" : "outside")), insidetextfont: { color: "#fff" }, cliponaxis: false, hovertemplate: "%{y}: %{text}<extra></extra>",
  }], { hovermode: "closest", margin: { l: 180, r: 70, t: 8, b: 30 }, xaxis: { gridcolor: css("--grid"), tickformat: ",.0f", zerolinecolor: css("--border") }, yaxis: { automargin: true } });

  const sim = [{ x: s.series.value.x, y: s.series.value.y, name: "Dein Depot", mode: "lines", line: { color: col[0], width: 2 }, hovertemplate: "%{y:,.0f} CHF" }];
  (s.benchmarks || []).forEach((b, i) => sim.push({ x: b.sim_value.x, y: b.sim_value.y, name: b.label, mode: "lines", line: { color: col[i + 1], width: 2 }, hovertemplate: "%{y:,.0f} CHF" }));
  plot("ch-sim", s.benchmarks?.length ? sim : [], { yaxis: { gridcolor: css("--grid"), tickformat: ",.0f" } });

  const m = s.monthly || [];
  plot("ch-monthly", [{
    type: "bar", x: m.map((r) => r.month), y: m.map((r) => r.return_pct),
    marker: { color: m.map((r) => (r.return_pct >= 0 ? css("--pos") : css("--neg"))) }, hovertemplate: "%{x}: %{y:.1f} %<extra></extra>",
  }], { hovermode: "closest", yaxis: { gridcolor: css("--grid"), ticksuffix: " %" } });

  plot("ch-dd", [{ x: s.series.drawdown_pct.x, y: s.series.drawdown_pct.y, name: "Drawdown", mode: "lines", fill: "tozeroy", line: { color: css("--neg"), width: 2 }, fillcolor: css("--neg") + "22", hovertemplate: "%{y:.1f} %" }],
    { yaxis: { gridcolor: css("--grid"), ticksuffix: " %" } });

  const rows = [
    ["Zeitraum", `${fmtDate(k.start)} – ${fmtDate(k.end)} (${k.days} Tage)`],
    ["Eingezahlt (Käufe, die nicht aus Verkaufserlösen bezahlt wurden)", fmtCHF(k.invested_total)],
    ["Cash aus Verkäufen (noch nicht reinvestiert)", fmtCHF(k.cash)],
    ["Realisiert / Unrealisiert", `${fmtCHF(k.realized_pnl)} / ${fmtCHF(k.unrealized_pnl)}`],
    ["Volatilität p.a.", fmtPct(k.volatility_pct, false)],
    ["Sharpe-Ratio", k.sharpe != null && k.days >= 180 ? fmtNum(k.sharpe) : "– (zu kurzer Zeitraum)"],
    ["Bester Tag", `${fmtPct(k.best_day_pct)} (${fmtDate(k.best_day)})`],
    ["Schlechtester Tag", `${fmtPct(k.worst_day_pct)} (${fmtDate(k.worst_day)})`],
    ["Positive Tage", fmtPct(k.positive_days_pct, false)],
    ...(s.benchmarks || []).map((b) => [`${b.label} im selben Zeitraum`, fmtPct(b.total_pct)]),
  ];
  $("#perf-table").innerHTML = `<table>${rows.map((r) => `<tr><th>${r[0]}</th><td class="num">${r[1]}</td></tr>`).join("")}</table>`;
}

function renderComposition(s) {
  const e = s.exposure || {};
  const [c1, c2, c3] = SERIES();
  hbar("ch-sector", e.sector, "weight_pct", (r) => fmtPct(r.weight_pct, false), c1);
  hbar("ch-country", e.country, "weight_pct", (r) => fmtPct(r.weight_pct, false), c3);
  hbar("ch-holding", e.holding, "value_chf", (r) => `${fmtCHF(r.value_chf)} · ${fmtPct(r.weight_pct, false)}`, c2);
  const src = (e.meta?.sources || []).map((x) => `${x.kind}: ${x.source} (${fmtDate(x.as_of)})`);
  $("#exp-source").textContent = src.length ? "Quelle: " + [...new Set(src)].join(" · ") + ". Gewichtet nach deinen offenen Positionen." : "Noch keine Zusammensetzung geladen – «Aktualisieren» klicken.";
  const metas = (s.instruments || []).filter((i) => i.meta?.justetf);
  $("#etf-meta").innerHTML = metas.length ? `<table><tr><th>ETF</th><th>TER</th><th>Fondsgrösse</th><th>Replikation</th><th>Ertrag</th><th>Index</th></tr>${metas.map((i) => {
    const m = i.meta.justetf;
    return `<tr><td>${esc(i.name)}<br><span class="muted">${esc(i.isin)}</span></td><td>${esc(m.ter || "–")}</td><td>${esc(m.fund_size || "–")}</td><td>${esc(m.replication || "–")}</td><td>${esc(m.distribution || "–")}</td><td>${esc(m.index || "–")}</td></tr>`;
  }).join("")}</table>` : '<p class="muted">Eckdaten werden beim Refresh von justETF geladen.</p>';
}

function renderPositions(s) {
  const pos = s.positions || [];
  const col = SERIES();
  plot("ch-stack", pos.map((p, i) => {
    const ser = s.series.by_instrument[p.isin];
    return { x: ser.x, y: ser.y, name: p.name, stackgroup: "one", mode: "lines", line: { width: 1, color: col[i % 8] }, hovertemplate: "%{y:,.0f} CHF" };
  }), { yaxis: { gridcolor: css("--grid"), tickformat: ",.0f" } });

  const sel = $("#px-select");
  const prev = sel.value;
  sel.innerHTML = pos.map((p) => `<option value="${esc(p.isin)}">${esc(p.name)}${p.open ? "" : " (verkauft)"}</option>`).join("");
  if (prev && pos.some((p) => p.isin === prev)) sel.value = prev;
  renderPrice();

  $("#pos-table").innerHTML = pos.length ? `<div class="table-wrap"><table><tr><th>ETF</th><th>Status</th><th class="num">Stück</th><th class="num">Ø-Kurs</th><th class="num">Kurs</th><th class="num">Wert CHF</th><th class="num">Unrealisiert</th><th class="num">Realisiert</th><th class="num">Total G/V</th><th>Kursquelle</th></tr>
    ${pos.map((p) => `<tr><td>${esc(p.name)}<br><span class="muted">${esc(p.isin)} · ${esc(p.currency)}</span></td>
      <td><span class="tag">${p.open ? "offen" : "verkauft"}</span></td><td class="num">${fmtNum(p.quantity, 0)}</td>
      <td class="num">${p.avg_price ? fmtNum(p.avg_price, 3) : "–"}</td><td class="num">${fmtNum(p.price, 3)}</td>
      <td class="num">${fmtCHF(p.market_value)}</td><td class="num">${fmtCHF(p.unrealized_pnl)}</td><td class="num">${fmtCHF(p.realized_pnl)}</td>
      <td class="num"><b>${fmtCHF(p.total_pnl)}</b></td><td class="muted">${esc(p.price_source)}</td></tr>`).join("")}</table></div>` : "";

  const tr = s.trades || [];
  $("#trade-table").innerHTML = tr.length ? `<div class="table-wrap"><table><tr><th>Datum</th><th>ETF</th><th>Art</th><th class="num">Stück</th><th class="num">Kurs</th><th>Whg.</th><th class="num">FX→CHF</th><th class="num">Gebühren</th><th class="num">Betrag CHF</th><th></th></tr>
    ${tr.map((t) => `<tr class="${t.estimated ? "est" : ""}" data-id="${t.id}">
      <td><input type="date" value="${t.trade_date}" data-f="trade_date"></td>
      <td>${esc(t.name || t.isin)}${t.estimated ? ' <span class="tag warn">geschätzt</span>' : ""}<br><span class="muted">${esc(t.isin)}</span></td>
      <td>${t.side === "BUY" ? "Kauf" : "Verkauf"}</td>
      <td class="num"><input type="number" step="any" value="${t.quantity}" data-f="quantity"></td>
      <td class="num"><input type="number" step="any" value="${t.price}" data-f="price"></td>
      <td>${esc(t.currency)}</td>
      <td class="num">${t.fx_rate ? fmtNum(t.fx_rate, 4) : "auto"}</td>
      <td class="num"><input type="number" step="any" value="${t.fees_chf ?? 0}" data-f="fees_chf"></td>
      <td class="num">${t.amount_chf ? fmtNum(t.amount_chf, 2) : "–"}</td>
      <td><button class="icon" data-del="${t.id}" title="Löschen">✕</button></td></tr>`).join("")}</table></div>` : '<p class="muted">Noch keine Transaktionen.</p>';
}

function renderPrice() {
  const p = (STATE.positions || []).find((x) => x.isin === $("#px-select").value);
  if (!p || !p.price_series) return plot("ch-price", []);
  const [c1] = SERIES();
  const t = p.trades;
  plot("ch-price", [
    { x: p.price_series.x, y: p.price_series.y, name: `Kurs (${p.currency})`, mode: "lines", line: { color: c1, width: 2 }, hovertemplate: "%{y:.3f} " + p.currency },
    { x: t.map((x) => x.date), y: t.map((x) => x.price), mode: "markers", name: "Trades",
      marker: { size: 13, symbol: t.map((x) => (x.side === "BUY" ? "triangle-up" : "triangle-down")), color: t.map((x) => (x.side === "BUY" ? css("--good") : css("--bad"))), line: { color: css("--surface"), width: 2 } },
      text: t.map((x) => `${x.side === "BUY" ? "Kauf" : "Verkauf"} ${fmtNum(x.quantity, 0)} @ ${fmtNum(x.price, 3)} (${fmtCHF(x.value_chf)})`), hovertemplate: "%{text}<extra></extra>" },
  ], { yaxis: { gridcolor: css("--grid") } });
}

function renderSaxo(s) {
  const r = s.report;
  if (!r) { ["ch-q-ret", "ch-q-pnl", "ch-inst", "ch-costs", "ch-acct"].forEach((id) => plot(id, [])); $("#saxo-period").textContent = "Kein Saxo-Bericht importiert."; return; }
  $("#saxo-period").textContent = `Berichtszeitraum ${fmtDate(r.period_start)} – ${fmtDate(r.period_end)} · Gesamtrendite laut Saxo ${fmtPct(r.summary?.total_return_pct)} · Nettoeinlagen ${fmtCHF(r.summary?.net_deposits, 2)} · Gesamterträge ${fmtCHF(r.summary?.total_return, 2)}`;
  const q = r.quarters || [];
  const [c1, c2] = SERIES();
  const lab = q.map((x) => x.label + (x.partial ? "*" : ""));
  plot("ch-q-ret", [
    { type: "bar", x: lab, y: q.map((x) => x.return_pct), name: "Depot", marker: { color: c1 }, hovertemplate: "%{y:.1f} %" },
    { type: "bar", x: lab, y: q.map((x) => x.benchmark_pct), name: r.benchmark_name || "Benchmark", marker: { color: c2 }, hovertemplate: "%{y:.1f} %" },
  ], { barmode: "group", bargap: 0.3, bargroupgap: 0.08, yaxis: { gridcolor: css("--grid"), ticksuffix: " %" } });
  plot("ch-q-pnl", [
    { type: "bar", x: lab, y: q.map((x) => x.pnl), name: "G/V", marker: { color: q.map((x) => (x.pnl >= 0 ? css("--pos") : css("--neg"))) }, hovertemplate: "%{y:,.0f} CHF" },
    { type: "scatter", mode: "lines+markers", x: lab, y: q.map((x) => -x.costs), name: "Kosten", line: { color: css("--text-2"), width: 2, dash: "dot" }, marker: { size: 8 }, hovertemplate: "%{y:,.0f} CHF" },
  ], { yaxis: { gridcolor: css("--grid"), tickformat: ",.0f" } });
  const inst = r.instrument_pnl || [];
  plot("ch-inst", [{
    type: "bar", orientation: "h", y: inst.map((x) => x.name), x: inst.map((x) => x.pnl),
    marker: { color: inst.map((x) => (x.pnl >= 0 ? css("--pos") : css("--neg"))) },
    text: inst.map((x) => `${fmtCHF(x.pnl)} (${fmtPct(x.return_pct)})`), textposition: inst.map((x) => (x.pnl < 0 ? "inside" : "outside")), insidetextfont: { color: "#fff" }, cliponaxis: false,
    customdata: inst.map((x) => fmtCHF(x.costs, 2)), hovertemplate: "%{y}<br>G/V %{text}<br>Kosten %{customdata}<extra></extra>",
  }], { hovermode: "closest", margin: { l: 230, r: 110, t: 8, b: 30 }, xaxis: { gridcolor: css("--grid"), tickformat: ",.0f", zerolinecolor: css("--border") }, yaxis: { automargin: true, autorange: "reversed" } });
  const c = r.costs || {};
  const items = [["Devisenumrechnung", c.fx_conversion], ["Courtage", c.commission], ["Stempelsteuer Ausland", c.stamp_duty_foreign], ["Stempelsteuer Inland", c.stamp_duty_domestic], ["Produktkosten (TER)", c.product_costs]].filter((x) => x[1]);
  hbar("ch-costs", items.map(([name, v]) => ({ name, v })).sort((a, b) => b.v - a.v), "v", (x) => fmtCHF(x.v, 2), c1);
  const vt = (r.value_table || []).filter((x) => x.account > 0);
  plot("ch-acct", [
    { x: vt.map((x) => x.date), y: vt.map((x) => x.account), name: "Kontowert", mode: "lines+markers", line: { color: c1, width: 2 }, marker: { size: 8 }, hovertemplate: "%{y:,.2f} CHF" },
  ], { yaxis: { gridcolor: css("--grid"), tickformat: ",.0f" } });
}

function renderSettings(s) {
  const st = s.settings;
  $("#rf").value = st.risk_free_rate ?? 0;
  $("#data-path").textContent = "Datenbank: " + s.data_path;
  $("#bm-list").innerHTML = (st.benchmarks || []).map((b, i) => `<div class="row" data-i="${i}"><input data-k="symbol" value="${esc(b.symbol)}" placeholder="Ticker"><input data-k="label" value="${esc(b.label)}" placeholder="Name"><button class="icon btn ghost" data-bmdel="${i}">✕</button></div>`).join("");
  const isins = [...new Set((s.trades || []).map((t) => t.isin))];
  const ov = st.symbol_overrides || {};
  $("#sym-list").innerHTML = isins.map((i) => {
    const inst = (s.instruments || []).find((x) => x.isin === i);
    return `<label>${esc(inst?.name || i)} <span class="muted">(${esc(i)}, aktuell: ${esc(inst?.yahoo_symbol || "–")})</span><input data-isin="${esc(i)}" value="${esc(ov[i] || "")}" placeholder="automatisch"></label>`;
  }).join("") || '<p class="muted">Noch keine ETFs.</p>';
  const lr = s.last_refresh;
  $("#refresh-log").innerHTML = lr ? `<ul class="steps">${lr.details.map((d) => `<li class="${d.ok ? "ok" : "fail"}"><b>${esc(d.step)}:</b> ${esc(d.message)}</li>`).join("")}</ul>` : '<p class="muted">Noch kein Refresh.</p>';
}

function collectSettings() {
  const benchmarks = [...document.querySelectorAll("#bm-list .row")].map((r) => ({
    symbol: r.querySelector('[data-k="symbol"]').value.trim(), label: r.querySelector('[data-k="label"]').value.trim(),
  })).filter((b) => b.symbol);
  const symbol_overrides = {};
  document.querySelectorAll("#sym-list input").forEach((i) => { if (i.value.trim()) symbol_overrides[i.dataset.isin] = i.value.trim(); });
  return { benchmarks, symbol_overrides, risk_free_rate: parseFloat($("#rf").value) || 0 };
}

// ---------- Events ----------
document.querySelectorAll(".tabs button").forEach((b) => b.addEventListener("click", () => {
  document.querySelectorAll(".tabs button").forEach((x) => x.classList.toggle("active", x === b));
  document.querySelectorAll(".tab-panel").forEach((p) => p.classList.toggle("active", p.dataset.panel === b.dataset.tab));
  try { localStorage.setItem("tab", b.dataset.tab); } catch (e) { /* egal */ }
  document.querySelectorAll(`[data-panel="${b.dataset.tab}"] .chart`).forEach((c) => c.data && Plotly.Plots.resize(c));
}));

$("#btn-refresh").addEventListener("click", async (ev) => {
  const btn = ev.currentTarget;
  btn.disabled = true; btn.textContent = "Lade Daten …";
  try {
    const r = await api("/api/refresh", { method: "POST" });
    const fails = r.steps.filter((s) => !s.ok);
    toast(fails.length ? `Aktualisiert, ${fails.length} Problem(e):\n` + fails.map((f) => `• ${f.step}: ${f.message}`).join("\n") : "Alles aktualisiert ✓", fails.length ? 12000 : 4000);
    await load();
  } catch (e) { toast("Fehler: " + e.message); }
  btn.disabled = false; btn.textContent = "Aktualisieren";
});

$("#file-input").addEventListener("change", async (ev) => {
  const f = ev.target.files[0];
  if (!f) return;
  const fd = new FormData(); fd.append("file", f);
  try {
    const r = await api("/api/import", { method: "POST", body: fd });
    if (r.type === "report") toast(`Saxo-Bericht importiert (${fmtDate(r.period[0])} – ${fmtDate(r.period[1])}).` + (r.estimated_trades.length ? `\nGeschätzter Kauf angelegt für: ${r.estimated_trades.join(", ")}. Für exakte Daten den Trade-Export importieren.` : ""), 9000);
    else toast(`${r.added} Transaktionen importiert, ${r.skipped_duplicates} Duplikate übersprungen.` + (r.warnings.length ? "\n" + r.warnings.slice(0, 5).join("\n") : ""), 9000);
    await load();
  } catch (e) { toast("Import fehlgeschlagen: " + e.message, 12000); }
  ev.target.value = "";
});

$("#px-select").addEventListener("change", renderPrice);

$("#trade-table").addEventListener("change", async (ev) => {
  const inp = ev.target.closest("input[data-f]");
  if (!inp) return;
  const id = inp.closest("tr").dataset.id;
  try { await api(`/api/trades/${id}`, { method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ [inp.dataset.f]: inp.value }) }); await load(); }
  catch (e) { toast("Fehler: " + e.message); }
});
$("#trade-table").addEventListener("click", async (ev) => {
  const b = ev.target.closest("[data-del]");
  if (!b || !confirm("Transaktion löschen?")) return;
  await api(`/api/trades/${b.dataset.del}`, { method: "DELETE" }); await load();
});
$("#trade-form").addEventListener("submit", async (ev) => {
  ev.preventDefault();
  const data = Object.fromEntries(new FormData(ev.target).entries());
  try { await api("/api/trades", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(data) }); ev.target.reset(); toast("Gespeichert. Tipp: «Aktualisieren» lädt Kurse für neue ETFs."); await load(); }
  catch (e) { toast("Fehler: " + e.message); }
});

$("#bm-add").addEventListener("click", () => { STATE.settings.benchmarks = [...collectSettings().benchmarks, { symbol: "", label: "" }]; renderSettings(STATE); });
$("#bm-list").addEventListener("click", (ev) => {
  const b = ev.target.closest("[data-bmdel]"); if (!b) return;
  const bms = collectSettings().benchmarks; bms.splice(+b.dataset.bmdel, 1); STATE.settings.benchmarks = bms; renderSettings(STATE);
});
$("#save-settings").addEventListener("click", async () => {
  await api("/api/settings", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(collectSettings()) });
  toast("Gespeichert. Klicke auf «Aktualisieren», um neue Benchmarks/Ticker zu laden."); await load();
});
$("#btn-reset").addEventListener("click", async () => {
  if (!confirm("Wirklich alle importierten Daten löschen?")) return;
  await api("/api/reset", { method: "POST" }); await load();
});
$("#btn-quit").addEventListener("click", async () => {
  if (!confirm("App beenden?")) return;
  await api("/api/shutdown", { method: "POST" }).catch(() => {});
  document.body.innerHTML = '<main><div class="panel"><h2>App beendet</h2><p>Du kannst dieses Fenster schliessen.</p></div></main>';
});
window.matchMedia("(prefers-color-scheme: dark)").addEventListener("change", () => STATE && render());

try { const t = localStorage.getItem("tab"); if (t) document.querySelector(`.tabs [data-tab="${t}"]`)?.click(); } catch (e) { /* egal */ }
load().catch((e) => toast("Fehler beim Laden: " + e.message));
