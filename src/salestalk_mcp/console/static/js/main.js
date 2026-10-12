// SalesTalk Console: boots every section. All data comes from /api/* which talks to the SalesTalk
// MCP server over stdio; nothing here touches the database.

import { $, $$, h, icon, fmt, api, callTool, on, countUp, sleep, reduceMotion, argsInline, cleanError, monthName, sqlHtml, setupReveal, setupLoopPausing, watchVisible, toast, esc, refusalLayer } from "./util.js";

/** OK, REFUSED (a safety layer said no) or INVALID (bad input the model can fix). */
function verdict(o) {
  if (o.ok) return { text: "OK", ink: "is-ok", chip: "chip-ok", summary: "" };
  return refusalLayer(o) === "range"
    ? { text: "INVALID", ink: "is-warn", chip: "chip-warn", summary: " is-warn" }
    : { text: "REFUSED", ink: "is-refused", chip: "chip-refused", summary: " is-refused" };
}
import { createConstellation } from "./constellation.js";
import { renderResult } from "./charts.js";
import { renderFrames } from "./frames.js";
import { createFlow } from "./flow.js";
import { createSafety } from "./safety.js";
import { createCta } from "./cta.js";

const state = { tools: [], overview: null, busy: false, activeTool: null, toolStats: {} };

/** Per-tool counters from the calls made on this page (shown on the tool cards). */
function recordCall(o) {
  const st = (state.toolStats[o.tool] ||= { calls: 0, refused: 0, lat: [] });
  st.calls++;
  if (!o.ok) st.refused++;
  st.lat.push({ ms: o.latency_ms, ok: o.ok });
  if (st.lat.length > 10) st.lat.shift();
  renderToolStats(o.tool, true);
}

function renderToolStats(name, ping = false) {
  const card = document.querySelector(`.tcard[data-tool="${name}"]`);
  if (!card) return;
  const box = card.querySelector(".tstats");
  const st = state.toolStats[name];
  if (!st) { box.replaceChildren(h("span", { class: "tstats-text", text: "not called yet" })); return; }
  const max = Math.max(1, ...st.lat.map((l) => l.ms));
  const last = st.lat[st.lat.length - 1];
  box.replaceChildren(
    h("span", { class: "tstats-text", html: `<b>${st.calls}</b> call${st.calls === 1 ? "" : "s"} · last <b>${fmt.ms(last.ms)} ms</b>` }),
    h("span", { class: "tstats-bars", title: "latency of the calls made on this page" }, st.lat.map((l) => h("i", { class: l.ok ? "" : "err", style: { height: `${Math.max(3, (l.ms / max) * 26)}px` } }))),
  );
  if (ping) { card.classList.remove("is-ping"); void card.offsetWidth; card.classList.add("is-ping"); }
}

// ------------------------------------------------------------------ questions (no LLM: each maps to a tool call)

function last12FullMonths() {
  const now = new Date();
  const end = new Date(now.getFullYear(), now.getMonth(), 0); // last day of previous month
  const start = new Date(end.getFullYear(), end.getMonth() - 11, 1);
  const iso = (d) => `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
  return `${iso(start)}..${iso(end)}`;
}

const JEDDAH_SQL = `SELECT c.company_name AS customer, c.segment,
       max(o.order_date) AS last_order,
       current_date - max(o.order_date) AS days_silent,
       count(*) AS orders
  FROM customers c
  JOIN cities ci ON ci.city_id = c.city_id
  JOIN orders o  ON o.customer_id = c.customer_id
 WHERE ci.name = 'Jeddah'
 GROUP BY c.customer_id, c.company_name, c.segment
HAVING max(o.order_date) < current_date - 60
 ORDER BY last_order`;

const QUESTIONS = [
  { id: "top", title: "Top 5 customers last month", tool: "query_sales", args: { month: "last_month", limit: 5 }, icon: "users", kind: "TABLE", viz: "rows" },
  { id: "cities", title: "Revenue by city this quarter", tool: "revenue_by_city", args: { range: "this_quarter" }, icon: "pin", kind: "BARS", viz: "bars" },
  { id: "monthly", title: "Monthly revenue, last 12 full months", tool: "revenue_by_city", args: () => ({ range: last12FullMonths(), granularity: "month" }), icon: "line", kind: "LINE", viz: "line" },
  { id: "products", title: "Best sellers, last 30 days", tool: "top_products", args: { range: "last_30_days", limit: 8 }, icon: "package", kind: "BARS", viz: "bars2" },
  { id: "jeddah", title: "Customers in Jeddah who stopped ordering", tool: "run_sql", args: { query: JEDDAH_SQL }, icon: "user-minus", kind: "SQL", viz: "rows2", sql: true },
  { id: "drop", title: "Delete the orders table", tool: "run_sql", args: { query: "DROP TABLE orders" }, icon: "trash", kind: "REFUSED", viz: "wall", danger: true, sql: true },
];

function miniViz(kind) {
  const ns = "http://www.w3.org/2000/svg";
  const svg = document.createElementNS(ns, "svg");
  svg.setAttribute("viewBox", "0 0 64 40");
  const add = (tag, attrs) => { const n = document.createElementNS(ns, tag); for (const [k, v] of Object.entries(attrs)) n.setAttribute(k, v); svg.append(n); return n; };
  if (kind === "bars" || kind === "bars2") {
    const ws = kind === "bars" ? [58, 42, 30, 20] : [60, 50, 38, 30, 22];
    const hgt = 40 / ws.length;
    ws.forEach((w, i) => add("rect", { class: "bar", x: 2, y: i * hgt + 1.5, width: w, height: hgt - 3.5, rx: 2 }));
  } else if (kind === "line") {
    add("path", { class: "ln", d: "M3 30 L13 26 L23 28 L33 18 L43 20 L53 10 L61 12" });
    add("circle", { class: "pt", cx: 61, cy: 12, r: 3 });
  } else if (kind === "rows" || kind === "rows2") {
    [0, 1, 2, 3].forEach((i) => add("rect", { class: `row${i === 0 ? " hi" : ""}`, x: 2, y: 3 + i * 9.5, width: i === 0 ? 60 : 60 - i * 6, height: 5, rx: 2.5 }));
  } else if (kind === "wall") {
    add("rect", { class: "row", x: 2, y: 17, width: 30, height: 6, rx: 3 });
    add("rect", { class: "wall", x: 38, y: 4, width: 7, height: 32, rx: 2 });
    add("path", { d: "M52 14 L60 22 M60 14 L52 22", stroke: "#BE2A2F", "stroke-width": 2.4, "stroke-linecap": "round" });
  }
  return svg;
}

function buildQuestions() {
  const list = $("#questions");
  list.replaceChildren(...QUESTIONS.map((q, i) => {
    const args = typeof q.args === "function" ? q.args() : q.args;
    const btn = h("button", { class: `q${q.danger ? " is-danger" : ""}`, type: "button", "data-reveal": "", style: { "--i": i }, "data-q": q.id },
      h("span", { class: "q-icon" }, icon(q.icon)),
      h("span", { class: "q-text" },
        h("span", { class: "q-title", text: q.title }),
        h("span", { class: "q-call", html: `<b>${q.tool}</b>(${esc(argsInline(args, 26))})` }),
        h("span", { class: "q-kind" }, h("span", { class: `chip ${q.danger ? "chip-down" : "chip-light"}`, text: q.kind })),
      ),
      h("span", { class: "q-viz", "aria-hidden": "true" }, miniViz(q.viz)),
    );
    btn.addEventListener("click", () => runCall({ question: q.title, tool: q.tool, args: typeof q.args === "function" ? q.args() : q.args, card: btn, sql: q.sql }));
    return btn;
  }));
}

// ------------------------------------------------------------------ the console window

const ui = {};

function callHtml(tool, args) {
  const parts = Object.entries(args || {}).map(([k, v]) => {
    let val;
    if (typeof v === "string") {
      const flat = v.replace(/\s+/g, " ").trim();
      val = `<span class="s">${esc(JSON.stringify(flat.length > 70 ? `${flat.slice(0, 68)}…` : flat))}</span>`;
    } else val = `<span class="n">${esc(JSON.stringify(v))}</span>`;
    return `<span class="k">${esc(k)}</span>=${val}`;
  });
  return `<span class="t">${esc(tool)}</span>(${parts.join(", ")})`;
}

async function typeHtml(el, html) {
  if (reduceMotion) { el.innerHTML = html; return; }
  // type the visible characters while keeping the markup intact
  const tmp = document.createElement("div");
  tmp.innerHTML = html;
  const total = tmp.textContent.length;
  const step = Math.max(1, Math.ceil(total / 42));
  for (let n = 0; n <= total; n += step) {
    el.innerHTML = truncateHtml(tmp, n);
    await sleep(16);
  }
  el.innerHTML = html;
}

function truncateHtml(root, n) {
  let left = n;
  const walk = (node) => {
    if (left <= 0) return "";
    if (node.nodeType === 3) { const t = node.textContent.slice(0, left); left -= t.length; return esc(t); }
    const inner = [...node.childNodes].map(walk).join("");
    return node === root ? inner : `<span class="${node.className}">${inner}</span>`;
  };
  return walk(root);
}

function setStatus(text, cls = "") {
  ui.status.className = `chip chip-ink${cls ? ` ${cls}` : ""}`;
  ui.status.textContent = text;
}

async function runCall({ question, tool, args, card = null, sql = false }) {
  if (state.busy) { toast("One call at a time: the current one is still animating."); return; }
  state.busy = true;
  $$(".q").forEach((q) => q.classList.remove("is-active", "is-busy"));
  if (card) card.classList.add("is-active", "is-busy");
  if (window.innerWidth < 980) $("#console").scrollIntoView({ behavior: reduceMotion ? "auto" : "smooth", block: "start" });

  ui.question.textContent = question;
  setStatus("CALLING", "is-busy");
  ui.chip.className = "callchip is-typing";
  ui.metricLatency.textContent = "…";
  ui.metricFrames.textContent = "…";
  ui.metricBytes.textContent = "…";
  ui.framesMeta.textContent = `tools/call ${tool} · waiting`;
  if (sql && args.query) { ui.sqlbox.hidden = false; ui.sqlCode.innerHTML = sqlHtml(args.query); } else ui.sqlbox.hidden = true;
  ui.result.style.opacity = "0.35";

  const pending = callTool(tool, args, "playground").catch((err) => ({ __error: err }));
  await typeHtml(ui.code, callHtml(tool, args));
  const outcome = await pending;
  ui.chip.classList.remove("is-typing");

  if (outcome.__error) {
    setStatus("NO SESSION", "is-refused");
    ui.result.style.opacity = "1";
    ui.result.replaceChildren(h("div", { class: "refusal in" }, h("div", { class: "refusal-side" }, icon("alert")), h("div", { class: "refusal-body" }, h("h3", { text: "The console could not reach the MCP server" }), h("pre", { text: outcome.__error.message }))));
    state.busy = false;
    card?.classList.remove("is-busy");
    return;
  }

  const frames = outcome.frames || [];
  const bytes = frames.reduce((s, f) => s + f.bytes, 0);
  const v = verdict(outcome);
  ui.chip.classList.add(outcome.ok ? "is-ok" : "is-refused");
  setStatus(v.text, v.ink);
  countUp(ui.metricLatency, outcome.latency_ms, { duration: 700, format: (v) => `${fmt.ms(v)} ms` });
  countUp(ui.metricFrames, frames.length, { duration: 500 });
  countUp(ui.metricBytes, bytes, { duration: 800, format: (v) => fmt.bytes(Math.round(v)) });
  ui.framesMeta.textContent = `${frames.length} frames · ${fmt.bytes(bytes)} · ${fmt.ms(outcome.latency_ms)} ms`;
  stripMap.fire(outcome, ui.chip);

  ui.result.style.opacity = "1";
  ui.result.replaceChildren(renderResult(outcome, { width: ui.result.clientWidth - 40 }));
  const framesDone = renderFrames(ui.framesBody, frames);
  await Promise.race([framesDone, sleep(1400)]);
  card?.classList.remove("is-busy");
  state.busy = false;
}

// ------------------------------------------------------------------ any-tool form (from input schemas)

const HINTS = {
  range: ["last_month", "this_month", "this_quarter", "last_quarter", "last_30_days", "last_90_days", "ytd", "last_12_months", "2026-Q3", "2026-01-01..2026-03-31"],
  month: ["last_month", "this_month", "2026-08", "2026-07"],
  city: ["Dubai", "Abu Dhabi", "Riyadh", "Jeddah"],
  granularity: ["total", "month"],
  sort_by: ["revenue", "units"],
  category: ["Dates", "Coffee & Tea", "Spices", "Textiles", "Electronics", "Fragrance"],
  table_name: ["orders", "customers", "products", "order_items", "cities", "v_sales", "dataset_info"],
};

function propType(p) {
  if (p.type) return { type: p.type, nullable: false };
  const types = (p.anyOf || []).map((x) => x.type);
  return { type: types.find((t) => t !== "null") || "string", nullable: types.includes("null") };
}

function buildFields(tool) {
  const fields = $("#fields");
  const props = tool.inputSchema?.properties || {};
  const required = new Set(tool.inputSchema?.required || []);
  const keys = Object.keys(props);
  if (!keys.length) { fields.replaceChildren(h("p", { class: "field-empty", text: "This tool takes no parameters." })); return; }
  fields.replaceChildren(...keys.map((key) => {
    const p = props[key];
    const { type, nullable } = propType(p);
    const id = `f-${tool.name}-${key}`;
    let input;
    if (key === "query") {
      input = h("textarea", { id, name: key, spellcheck: "false", placeholder: "SELECT …" });
      input.value = "SELECT ci.name AS city, count(*) AS customers\n  FROM customers c JOIN cities ci USING (city_id)\n GROUP BY 1 ORDER BY 2 DESC";
    } else {
      input = h("input", { id, name: key, type: type === "integer" ? "number" : "text", inputmode: type === "integer" ? "numeric" : null, min: p.minimum ?? null, max: p.maximum ?? null, placeholder: nullable ? "optional" : "", list: HINTS[key] ? `${id}-list` : null });
      if (p.default !== undefined && p.default !== null) input.value = p.default;
    }
    const range = p.minimum !== undefined || p.maximum !== undefined ? ` ${p.minimum ?? ""}–${p.maximum ?? ""}` : "";
    return h("div", { class: "field" },
      h("label", { class: "field-label", for: id }, h("code", { text: key }), h("span", { class: `field-type${required.has(key) ? " req" : ""}`, text: `${type}${range}${required.has(key) ? " · required" : nullable ? " · optional" : ""}` })),
      p.description ? h("span", { class: "field-help", text: p.description }) : null,
      input,
      HINTS[key] ? h("datalist", { id: `${id}-list` }, HINTS[key].map((v) => h("option", { value: v }))) : null,
    );
  }));
}

function selectTool(name) {
  const tool = state.tools.find((t) => t.name === name);
  if (!tool) return;
  state.activeTool = tool;
  $$(".tool-pick").forEach((b) => b.setAttribute("aria-pressed", String(b.dataset.tool === name)));
  $("#tool-picker-desc").textContent = tool.description.replace(/\s+/g, " ").trim();
  $("#anytool-name").textContent = name;
  buildFields(tool);
}

function buildToolPicker() {
  const picker = $("#tool-picker");
  picker.replaceChildren(...state.tools.map((t) => {
    const b = h("button", { class: "tool-pick", type: "button", "data-tool": t.name, "aria-pressed": "false", text: t.name });
    b.addEventListener("click", () => selectTool(t.name));
    return b;
  }));
  selectTool(state.tools.find((t) => t.name === "top_products") ? "top_products" : state.tools[0]?.name);
  $("#anytool").addEventListener("submit", (e) => {
    e.preventDefault();
    const tool = state.activeTool;
    if (!tool) return;
    const props = tool.inputSchema?.properties || {};
    const args = {};
    for (const key of Object.keys(props)) {
      const el = $(`[name="${key}"]`, $("#fields"));
      if (!el) continue;
      const raw = el.value.trim();
      if (!raw) continue;
      const { type } = propType(props[key]);
      args[key] = type === "integer" ? Number(raw) : raw;
    }
    runCall({ question: `Custom call: ${tool.title || tool.name}`, tool: tool.name, args, sql: tool.name === "run_sql" });
  });
}

// ------------------------------------------------------------------ tools reference (from tools/list)

const TOOL_ICONS = { list_tables: "list", describe_table: "table", query_sales: "users", revenue_by_city: "pin", top_products: "package", run_sql: "terminal" };

function toolGraph(tool) {
  const ns = "http://www.w3.org/2000/svg";
  const svg = document.createElementNS(ns, "svg");
  svg.setAttribute("viewBox", "0 0 360 112");
  svg.setAttribute("preserveAspectRatio", "xMinYMid meet");
  const add = (parent, tag, attrs) => { const n = document.createElementNS(ns, tag); for (const [k, v] of Object.entries(attrs)) n.setAttribute(k, v); parent.append(n); return n; };
  const params = Object.keys(tool.inputSchema?.properties || {});
  const items = params.length ? params : ["no parameters"];
  const cx = 48, cy = 56;
  const paths = [];
  items.forEach((p, i) => {
    const y = items.length === 1 ? cy : 18 + (i * 76) / (items.length - 1);
    const x = 152;
    const d = `M${cx + 22},${cy} C${cx + 56},${cy} ${x - 44},${y} ${x - 6},${y}`;
    paths.push(d);
    add(svg, "path", { d, class: "tg-link" });
    const node = add(svg, "circle", { cx: x, cy: y, r: 5.5, class: "tg-node" });
    node.style.setProperty("--d", `${i * 90}ms`);
    const label = add(svg, "text", { x: x + 13, y: y + 3.6, class: "tg-label" });
    label.textContent = p;
    label.style.setProperty("--d", `${i * 90}ms`);
  });
  add(svg, "circle", { cx, cy, r: 22, class: "tg-core" });
  const g = add(svg, "g", { transform: `translate(${cx - 10}, ${cy - 10}) scale(0.84)` });
  const use = add(g, "use", { href: `#i-${TOOL_ICONS[tool.name] || "terminal"}`, class: "tg-core-ic", fill: "none", "stroke-width": 1.9, "stroke-linecap": "round", "stroke-linejoin": "round", width: 24, height: 24 });
  use.style.stroke = "#8E98FF";
  svg._paths = paths;
  return svg;
}

function startSparks(svg) {
  if (reduceMotion || svg._sparks) return;
  const ns = "http://www.w3.org/2000/svg";
  const t0 = svg.getCurrentTime ? svg.getCurrentTime() : 0;
  svg._sparks = svg._paths.map((d, i) => {
    const c = document.createElementNS(ns, "circle");
    c.setAttribute("r", "3");
    c.setAttribute("fill", "#5360F0");
    const m = document.createElementNS(ns, "animateMotion");
    m.setAttribute("path", d);
    m.setAttribute("dur", "1.3s");
    m.setAttribute("begin", `${(t0 + i * 0.16).toFixed(2)}s`);
    m.setAttribute("repeatCount", "indefinite");
    c.append(m);
    svg.append(c);
    return c;
  });
}
function stopSparks(svg) { (svg._sparks || []).forEach((c) => c.remove()); svg._sparks = null; }

function badge(text, cls) { return h("span", { class: `chip ${cls}`, text }); }

function buildToolCards() {
  const wrap = $("#tool-cards");
  wrap.replaceChildren(...state.tools.map((t, i) => {
    const props = t.inputSchema?.properties || {};
    const required = new Set(t.inputSchema?.required || []);
    const a = t.annotations || {};
    const badges = [];
    if (a.readOnlyHint) badges.push(badge("read-only", "chip-up"));
    if (a.idempotentHint) badges.push(badge("idempotent", "chip-light"));
    if (a.destructiveHint === false) badges.push(badge("non-destructive", "chip-line"));
    if (a.openWorldHint === false) badges.push(badge("closed world", "chip-line"));
    const graph = toolGraph(t);
    const params = Object.keys(props).length
      ? Object.entries(props).map(([k, p]) => {
        const { type, nullable } = propType(p);
        const def = p.default !== undefined && p.default !== null ? ` = ${JSON.stringify(p.default)}` : "";
        const range = p.minimum !== undefined ? ` ${p.minimum}–${p.maximum ?? "∞"}` : "";
        return h("li", {}, h("code", { text: k }), h("span", { class: "ptype", text: `${type}${range}${required.has(k) ? " · required" : nullable ? " · optional" : ""}${def}` }), p.description ? h("span", { class: "pdesc", text: p.description }) : null);
      })
      : [h("li", { class: "none", text: "no parameters" })];
    const more = h("button", { class: "btn btn-small btn-outline", type: "button", "aria-expanded": "false" }, h("span", { text: "Details" }));
    const tryIt = h("button", { class: "btn btn-small btn-primary", type: "button" }, h("span", { text: "Try it" }), icon("arrow"));
    const card = h("article", { class: "tcard", "data-reveal": "", "data-tool": t.name, style: { "--i": i % 3 } },
      h("div", { class: "tgraph" }, graph, h("div", { class: "tstats" })),
      h("div", { class: "tcard-body" },
        h("p", { class: "tcard-name", text: t.name }),
        h("h3", { text: t.title || t.name }),
        h("p", { class: "tcard-desc", text: t.description.replace(/\s+/g, " ") }),
        h("div", { class: "badges" }, badges),
        h("ul", { class: "params" }, params),
        h("div", { class: "tcard-actions" }, more, tryIt),
      ),
    );
    card.addEventListener("pointerenter", () => startSparks(graph));
    card.addEventListener("pointerleave", () => { if (!card.classList.contains("is-open")) stopSparks(graph); });
    more.addEventListener("click", () => {
      const open = card.classList.toggle("is-open");
      more.setAttribute("aria-expanded", String(open));
      more.firstChild.textContent = open ? "Less" : "Details";
      open ? startSparks(graph) : stopSparks(graph);
    });
    tryIt.addEventListener("click", () => {
      selectTool(t.name);
      $("#anytool").scrollIntoView({ behavior: reduceMotion ? "auto" : "smooth", block: "center" });
      setTimeout(() => $("#fields input, #fields textarea")?.focus({ preventScroll: true }), reduceMotion ? 0 : 700);
    });
    return card;
  }));
  state.tools.forEach((t) => renderToolStats(t.name));
  setupReveal(wrap);
}

// ------------------------------------------------------------------ hero feed

function summarize(o) {
  if (!o.ok) return cleanError(o.error);
  const r = o.result || {};
  try {
    switch (o.tool) {
      case "query_sales": return `${monthName(r.month)} · ${fmt.aedCompact(r.summary.revenue)} from ${fmt.int(r.summary.orders)} orders · ${fmt.pct(r.previous_period.revenue_change_pct)} vs previous month`;
      case "revenue_by_city": return `${r.cities.slice(0, 3).map((c) => `${c.city} ${fmt.aedCompact(c.revenue)}`).join(" · ")}${r.monthly ? ` · ${r.monthly.length} monthly points` : ""}`;
      case "top_products": return r.products.length ? `#1 ${r.products[0].product} · ${fmt.aedCompact(r.products[0].revenue)} · ${r.products[0].gross_margin_pct}% margin` : "no sales in range";
      case "list_tables": return `${r.table_count} tables and views: ${r.tables.map((t) => t.name).slice(0, 5).join(", ")}…`;
      case "describe_table": return `${r.name}: ${r.columns.length} columns, ${r.sample_rows.length} sample rows`;
      case "run_sql":
        if (o.key === "stats" && r.rows?.[0]) { const s = r.rows[0]; return `${fmt.int(s.customers)} customers · ${fmt.int(s.products)} products · ${fmt.int(s.orders)} orders`; }
        if (o.key === "customers") return `${fmt.int(r.row_count)} customers with revenue: the nodes on this map`;
        return `${fmt.int(r.row_count)} row${r.row_count === 1 ? "" : "s"}${r.truncated ? " (row cap hit)" : ""} in ${r.elapsed_ms} ms`;
      default: return "done";
    }
  } catch { return "done"; }
}

function rowsOf(o) {
  const r = o.result || {};
  if (!o.ok) return null;
  return r.top_customers?.length ?? r.cities?.length ?? r.products?.length ?? r.tables?.length ?? r.columns?.length ?? r.row_count ?? null;
}

function createFeed(heroMap) {
  const body = $("#feed-body");
  const dashes = $("#feed-dashes");
  const count = $("#feed-count");
  const feedEl = $("#feed");
  const items = [];
  let index = -1;
  let timer = 0;
  let visible = true;
  let paused = false;
  const DUR = 3600;

  function render(o) {
    const v = verdict(o);
    const rows = rowsOf(o);
    return h("div", { class: "feed-item is-entering" },
      h("div", { class: "feed-meta" },
        h("span", { class: `chip ${v.chip}`, text: v.text }),
        h("span", { text: `${fmt.time(o.called_at)} · ${fmt.ms(o.latency_ms)} ms${rows !== null ? ` · ${rows} row${rows === 1 ? "" : "s"}` : ""}` })),
      h("p", { class: "feed-tool", text: o.tool }),
      h("p", { class: "feed-args", text: argsInline(o.arguments, 40) || "no arguments" }),
      h("p", { class: `feed-summary${v.summary}`, text: summarize(o) }),
    );
  }

  function drawDashes() {
    const shown = items.slice(-10);
    const offset = items.length - shown.length;
    dashes.replaceChildren(...shown.map((o, k) => {
      const i = k + offset;
      const b = h("button", { class: `feed-dash${i === index ? " is-active" : ""}${i < index ? " is-done" : ""}${o.ok ? "" : " is-refused"}`, type: "button", "aria-current": i === index ? "true" : null, "aria-label": `${o.tool} call ${i + 1}`, style: { "--dur": `${DUR}ms` } }, h("i"));
      b.addEventListener("click", () => show(i, true));
      return b;
    }));
    count.textContent = `${String(index + 1).padStart(2, "0")}/${String(items.length).padStart(2, "0")}`;
  }

  async function show(i, fromUser = false) {
    if (!items.length) return;
    index = (i + items.length) % items.length;
    const o = items[index];
    const old = body.querySelector(".feed-item:not(.is-leaving)");
    const next = render(o);
    body.append(next);
    if (old) { old.classList.add("is-leaving"); setTimeout(() => old.remove(), 600); }
    requestAnimationFrame(() => requestAnimationFrame(() => next.classList.remove("is-entering")));
    drawDashes();
    heroMap.fire(o, feedEl);
    schedule(fromUser ? DUR * 1.6 : DUR);
  }

  function schedule(ms) {
    clearTimeout(timer);
    if (reduceMotion) return;
    timer = setTimeout(() => {
      if (!visible || paused || document.hidden) { schedule(800); return; }
      show(index + 1);
    }, ms);
  }

  feedEl.addEventListener("pointerenter", () => { paused = true; dashes.querySelector(".is-active")?.classList.add("is-paused"); });
  feedEl.addEventListener("pointerleave", () => { paused = false; dashes.querySelector(".is-active")?.classList.remove("is-paused"); });
  watchVisible($("#hero"), (v) => (visible = v), "0px");

  return {
    load(calls) { items.push(...calls); show(0); },
    push(o) { items.push(o); if (items.length > 24) items.splice(0, items.length - 24); index = Math.min(index, items.length - 1); if (visible) show(items.length - 1); else drawDashes(); },
    error(message) {
      body.replaceChildren(h("div", { class: "feed-item" },
        h("div", { class: "feed-meta" }, h("span", { class: "chip chip-refused", text: "NO DATA" })),
        h("p", { class: "feed-tool", text: "MCP session" }),
        h("p", { class: "feed-summary is-refused", text: message })));
    },
  };
}

// ------------------------------------------------------------------ header

function setupHeader() {
  const header = $(".site-header");
  const bar = $(".progress span");
  const links = $$(".nav a");
  const update = () => {
    const y = window.scrollY;
    const max = document.documentElement.scrollHeight - window.innerHeight;
    header.classList.toggle("is-solid", y > 12);
    bar.style.transform = `scaleX(${max > 0 ? Math.min(1, y / max) : 0})`;
  };
  window.addEventListener("scroll", update, { passive: true });
  update();
  const io = new IntersectionObserver((entries) => {
    for (const e of entries) if (e.isIntersecting) links.forEach((a) => a.classList.toggle("is-active", a.getAttribute("href") === `#${e.target.id}`));
  }, { rootMargin: "-45% 0px -50% 0px" });
  ["playground", "flow", "break", "tools"].forEach((id) => io.observe(document.getElementById(id)));
}

function setSession(session, toolsCount) {
  const conn = $("#conn");
  if (session?.connected) {
    conn.dataset.state = "up";
    $(".conn-text", conn).textContent = `MCP connected · stdio · ${toolsCount} tools`;
  } else {
    conn.dataset.state = "down";
    $(".conn-text", conn).textContent = "MCP not connected";
  }
  if (!session) return;
  $("#sess-server").textContent = session.server?.name ? `${session.server.name} ${session.server.version || ""}` : "–";
  $("#sess-protocol").textContent = session.protocol_version || "–";
  $("#sess-transport").textContent = `${session.transport} · ${session.mode}`;
  $("#sess-frames").textContent = fmt.int(session.frames_seen || 0);
  $("#footer-session").textContent = `MCP ${session.protocol_version || ""} · stdio · ${session.server?.name || "salestalk"} ${session.server?.version || ""}`;
  $("#feed-state").textContent = session.protocol_version ? `stdio · MCP ${session.protocol_version}` : "stdio · connected";
}

// ------------------------------------------------------------------ boot

let stripMap;

async function boot() {
  document.documentElement.classList.remove("no-js");
  Object.assign(ui, {
    question: $("#console-question"), status: $("#console-status"), chip: $("#callchip"), code: $("#callchip-code"),
    metricLatency: $("#metric-latency"), metricFrames: $("#metric-frames"), metricBytes: $("#metric-bytes"),
    sqlbox: $("#sqlbox"), sqlCode: $("#sqlbox-code"), result: $("#result"), framesBody: $("#frames-body"), framesMeta: $("#frames-meta"),
  });
  setupHeader();
  setupLoopPausing();

  const heroMap = createConstellation({ canvas: $("#hero-canvas"), overlay: $("#hero-overlay"), stage: $("#hero-map"), layout: "hero", wide: 560, maxTags: 3 });
  stripMap = createConstellation({ canvas: $("#strip-canvas"), overlay: $("#strip-overlay"), stage: $("#strip-map"), layout: "strip", wide: 420, maxTags: 4 });
  heroMap.setData({});
  stripMap.setData({});
  const feed = createFeed(heroMap);
  const flow = createFlow({ card: $("#flow-card"), canvas: $("#flow-canvas"), grid: $("#flow-grid") });
  const safety = createSafety({ attacksEl: $("#attacks"), stackEl: $("#stack"), stats: null });
  createCta({ card: $("#cta"), canvas: $("#cta-canvas"), stage: $("#cta-stage") });
  buildQuestions();
  setupReveal();

  $("#frames-toggle").addEventListener("click", (e) => {
    const btn = e.currentTarget;
    const open = btn.getAttribute("aria-expanded") === "true";
    btn.setAttribute("aria-expanded", String(!open));
    $("#frames-body").hidden = open;
  });

  // every call anywhere on the page: the hero feed, the flow diagram and the session counters react
  on("call", ({ outcome }) => {
    recordCall(outcome);
    feed.push(outcome);
    flow.push(outcome);
    api("/api/health").then((s) => setSession(s, state.tools.length)).catch(() => {});
  });

  try {
    const res = await api("/api/tools");
    state.tools = res.tools;
    setSession(res.session, res.tools.length);
    buildToolPicker();
    buildToolCards();
  } catch (err) {
    setSession(null, 0);
    $("#conn").dataset.state = "down";
    toast(`MCP session not available: ${err.message}`, 8000);
  }

  try {
    const ov = await api("/api/overview");
    state.overview = ov;
    const d = ov.data;
    if (d.stats) {
      for (const el of $$("[data-stat]")) countUp(el, d.stats[el.dataset.stat], { duration: 1400 });
      safety.setStats(d.stats);
    }
    heroMap.setData({ cities: d.cities, customers: d.customers });
    stripMap.setData({ cities: d.cities, customers: d.customers });
    $("#map-customers").textContent = fmt.int(d.customers.length || 0);
    feed.load(ov.calls);
    flow.seed(ov.calls);
    ov.calls.forEach((c) => recordCall(c));
    setSession(ov.session, state.tools.length);
  } catch (err) {
    feed.error(err.message);
  }
}

boot();
