// Result renderers: every view is built from the tool's structured JSON, and animates in
// (rows slide, bars grow, numbers count up, lines draw). Reduced motion shows the end state.

import { h, icon, fmt, countUp, monthName, reduceMotion, cleanError, refusalLayer, LAYER_NAMES } from "./util.js";

const SERIES_COLORS = ["#4F5BF0", "#11132A", "#9AA2FF", "#7A7FA6"];

function animateIn(nodes, step = 70) {
  nodes.forEach((n, i) => n.style.setProperty("--d", `${reduceMotion ? 0 : i * step}ms`));
  requestAnimationFrame(() => requestAnimationFrame(() => nodes.forEach((n) => n.classList.add("in"))));
}

function kpi(label, value, format = fmt.int, small = "") {
  const b = h("b", { text: "0" });
  countUp(b, value, { format: (v) => format(v) + small });
  return h("div", { class: "r-kpi" }, h("span", { text: label }), b);
}

function changeChip(pct, suffix = "") {
  if (pct === null || pct === undefined) return h("span", { class: "chip chip-line", text: "no comparison" });
  const up = pct >= 0;
  return h("span", { class: `chip ${up ? "chip-up" : "chip-down"}`, text: `${up ? "▲" : "▼"} ${Math.abs(pct).toFixed(1)}%${suffix}` });
}

function head(title, sub, ...right) {
  return h("div", { class: "r-head" }, h("div", {}, h("p", { class: "r-title", text: title }), sub ? h("p", { class: "r-sub", text: sub }) : null), ...right);
}

// ------------------------------------------------------------------ generic table

function isNum(v) { return typeof v === "number"; }

export function table(columns, rows, { rankKey = null, shareKey = null, money = [], strong = [], subs = {}, maxRows = 60 } = {}) {
  const maxShare = shareKey ? Math.max(1e-9, ...rows.map((r) => Number(r[shareKey]) || 0)) : 1;
  const thead = h("thead", {}, h("tr", {}, columns.map((c) => h("th", { class: c.num ? "num" : "", text: c.label }))));
  const trs = rows.slice(0, maxRows).map((r) => h("tr", {}, columns.map((c) => {
    const v = r[c.key];
    if (c.key === rankKey) return h("td", {}, h("span", { class: "rank", text: v }));
    if (c.key === shareKey) {
      const td = h("td", { class: "num" }, h("span", { class: "share" }, h("i", { style: { "--w": `${Math.max(4, ((v || 0) / maxShare) * 100)}%` } }), `${v ?? "–"}%`));
      return td;
    }
    if (v === null || v === undefined) return h("td", { class: "null", text: "null" });
    if (money.includes(c.key) && isNum(v)) {
      const td = h("td", { class: "num", text: "0" });
      countUp(td, v, { format: fmt.aed, duration: 1100 });
      return td;
    }
    if (isNum(v)) return h("td", { class: "num", text: Number.isInteger(v) ? fmt.int(v) : v.toLocaleString("en-US", { maximumFractionDigits: 2 }) });
    const td = h("td", { class: strong.includes(c.key) ? "strong" : "" }, String(typeof v === "object" ? JSON.stringify(v) : v));
    if (subs[c.key]) td.append(h("small", { text: subs[c.key](r) }));
    return td;
  })));
  const tbody = h("tbody", {}, trs);
  const wrap = h("div", { class: "tbl-wrap" }, h("table", { class: "tbl" }, thead, tbody));
  animateIn(trs, 60);
  return wrap;
}

// ------------------------------------------------------------------ bars

export function bars(items, { max } = {}) {
  const top = max || Math.max(1, ...items.map((i) => i.value));
  const rows = items.map((it) => {
    const value = h("span", { class: "bar-value", text: "0" });
    countUp(value, it.value, { format: it.format || fmt.aed, duration: 1200 });
    return h("div", { class: "bar-row" },
      h("div", { class: "bar-label" }, h("b", { text: it.label }), it.sub ? h("span", { text: it.sub }) : null),
      h("div", { class: "bar-track" }, h("span", { class: "bar-fill", style: { "--w": `${Math.max(2, (it.value / top) * 100)}%` } })),
      h("div", { class: "bar-end" }, it.chip || null, value),
    );
  });
  animateIn(rows, 80);
  return h("div", { class: "bars" }, rows);
}

// ------------------------------------------------------------------ line chart (SVG)

export function lines(months, series, { partialLast = false, partialFirst = false, width = 720 } = {}) {
  const W = Math.round(Math.max(340, Math.min(760, width)));
  const narrow = W < 520;
  const H = narrow ? 250 : 300, L = narrow ? 44 : 64, R = narrow ? 96 : 118, T = 16, B = 34;
  const ns = "http://www.w3.org/2000/svg";
  const el = (tag, attrs = {}) => { const n = document.createElementNS(ns, tag); for (const [k, v] of Object.entries(attrs)) n.setAttribute(k, v); return n; };
  const maxV = Math.max(1, ...series.flatMap((s) => s.values));
  const niceMax = Math.ceil(maxV / 2e5) * 2e5;
  const x = (i) => L + (i / Math.max(1, months.length - 1)) * (W - L - R);
  const y = (v) => T + (1 - v / niceMax) * (H - T - B);
  const svg = el("svg", { viewBox: `0 0 ${W} ${H}`, role: "img", "aria-label": "Monthly revenue by city" });
  const uid = `clip${Math.random().toString(36).slice(2, 8)}`;
  const defs = el("defs");
  const clip = el("clipPath", { id: uid, class: "lc-clip" });
  const clipRect = el("rect", { x: 0, y: 0, width: reduceMotion ? W : 0, height: H });
  clip.append(clipRect);
  defs.append(clip);
  svg.append(defs);

  const grid = el("g", { class: "lc-grid" });
  const axis = el("g", { class: "lc-axis" });
  for (let k = 0; k <= 4; k++) {
    const v = (niceMax / 4) * k;
    grid.append(el("line", { x1: L, x2: W - R + 8, y1: y(v), y2: y(v) }));
    const tx = el("text", { x: L - 10, y: y(v) + 3.5, "text-anchor": "end" });
    tx.textContent = fmt.compact(v);
    axis.append(tx);
  }
  months.forEach((m, i) => {
    if (months.length > 8 && i % (narrow ? 3 : 2) !== 0 && i !== months.length - 1) return;
    const tx = el("text", { x: x(i), y: H - 10, "text-anchor": "middle" });
    tx.textContent = monthName(m, true) + ((partialLast && i === months.length - 1) || (partialFirst && i === 0) ? "*" : "");
    axis.append(tx);
  });
  svg.append(grid, axis);

  const plot = el("g", { "clip-path": `url(#${uid})` });
  series.forEach((s, si) => {
    const d = s.values.map((v, i) => `${i ? "L" : "M"}${x(i).toFixed(1)},${y(v).toFixed(1)}`).join(" ");
    plot.append(el("path", { d, class: "lc-line", stroke: s.color || SERIES_COLORS[si % 4] }));
  });
  svg.append(plot);
  const dots = el("g");
  series.forEach((s, si) => s.values.forEach((v, i) => {
    const c = el("circle", { cx: x(i), cy: y(v), r: i === s.values.length - 1 ? 4.5 : 3, class: "lc-dot", fill: s.color || SERIES_COLORS[si % 4] });
    c.style.setProperty("--d", `${reduceMotion ? 0 : 200 + i * 90}ms`);
    dots.append(c);
  }));
  svg.append(dots);
  // direct labels at the line ends (no legend to decode)
  const ends = series.map((s, si) => ({ s, si, y: y(s.values[s.values.length - 1]) })).sort((a, b) => a.y - b.y);
  for (let i = 1; i < ends.length; i++) if (ends[i].y - ends[i - 1].y < 26) ends[i].y = ends[i - 1].y + 26;
  const labels = el("g");
  ends.forEach(({ s, si, y: ly }) => {
    const t = el("text", { x: W - R + 16, y: ly + 4, class: "lc-end", fill: s.color || SERIES_COLORS[si % 4] });
    t.textContent = s.name;
    const sp = el("tspan", { x: W - R + 16, dy: 13, fill: "#5F6288" });
    sp.textContent = fmt.aedCompact(s.values.reduce((a, b) => a + b, 0));
    t.append(sp);
    labels.append(t);
  });
  svg.append(labels);

  // hover crosshair
  const hover = el("g", { class: "lc-hover", opacity: 0 });
  const vline = el("line", { y1: T, y2: H - B });
  hover.append(vline);
  svg.append(hover);
  const tip = h("div", { class: "lc-tip" });
  const box = h("div", { class: "linechart" }, svg, tip);
  svg.addEventListener("pointermove", (e) => {
    const r = svg.getBoundingClientRect();
    const px = ((e.clientX - r.left) / r.width) * W;
    const i = Math.max(0, Math.min(months.length - 1, Math.round(((px - L) / (W - L - R)) * (months.length - 1))));
    vline.setAttribute("x1", x(i)); vline.setAttribute("x2", x(i));
    hover.setAttribute("opacity", 1);
    tip.innerHTML = `<b>${monthName(months[i])}${(partialLast && i === months.length - 1) || (partialFirst && i === 0) ? " (partial)" : ""}</b>` +
      series.map((s, si) => `<div><i style="background:${s.color || SERIES_COLORS[si % 4]}"></i>${s.name} ${fmt.aed(s.values[i])}</div>`).join("");
    const left = (x(i) / W) * r.width;
    tip.style.transform = `translate(${left > r.width * 0.6 ? left - 200 : left + 14}px, 8px)`;
    tip.classList.add("is-on");
  });
  svg.addEventListener("pointerleave", () => { hover.setAttribute("opacity", 0); tip.classList.remove("is-on"); });

  requestAnimationFrame(() => requestAnimationFrame(() => {
    box.classList.add("in");
    if (!reduceMotion) clipRect.setAttribute("width", W);
  }));
  // CSS transition on the clip rect width draws the solid lines left to right
  clipRect.style.transition = reduceMotion ? "none" : "width 1.6s cubic-bezier(.16,1,.3,1)";
  return box;
}

// ------------------------------------------------------------------ refusal

export function refusal(outcome) {
  const layer = refusalLayer(outcome);
  const warn = layer === "range";
  const title = warn ? "Rejected: invalid input" : `Refused by the ${LAYER_NAMES[layer] || "server"}`;
  const note = layer === "guard"
    ? "The SQL guard stopped it before anything was sent to PostgreSQL. And the database role can't write anyway."
    : layer === "range"
      ? "The tool checked its inputs and explained the problem, so Claude can retry with valid values."
      : layer === "connect"
        ? "The server could not reach the database. Start PostgreSQL and try again."
        : "It passed the guard, and the database itself refused it: the role is read-only.";
  const card = h("div", { class: `refusal${warn ? " is-warn" : ""}` },
    h("div", { class: "refusal-side" }, icon(warn ? "alert" : "shield-x")),
    h("div", { class: "refusal-body" },
      h("h3", { text: title }),
      h("pre", { text: cleanError(outcome.error) }),
      h("p", { text: note }),
    ),
  );
  requestAnimationFrame(() => requestAnimationFrame(() => card.classList.add("in")));
  return card;
}

// ------------------------------------------------------------------ per-tool views

export function renderResult(outcome, { width = 720 } = {}) {
  if (!outcome.ok) return refusal(outcome);
  const r = outcome.result || {};
  const box = h("div", { class: "r" });
  const wrap = { append: (...nodes) => box.append(...nodes.filter((n) => n !== null && n !== undefined && n !== false)) };
  switch (outcome.tool) {
    case "query_sales": {
      const prev = r.previous_period || {};
      wrap.append(
        head(`${monthName(r.month)}${r.city ? ` · ${r.city}` : ""}`, `${r.period?.start} to ${r.period?.end} · revenue in AED`,
          h("div", { class: "r-kpis" }, kpi("Revenue", r.summary?.revenue, fmt.aed), kpi("Orders", r.summary?.orders), kpi("Avg order", r.summary?.avg_order_value, fmt.aed))),
        h("div", { style: { display: "flex", gap: "8px", alignItems: "center", margin: "-4px 0 16px", flexWrap: "wrap" } },
          changeChip(prev.revenue_change_pct, ` vs ${monthName(prev.label?.slice(0, 7))}`),
          h("span", { class: "chip chip-line", text: `${r.summary?.active_customers ?? "–"} active customers` })),
        table(
          [{ key: "rank", label: "#" }, { key: "customer", label: "Customer" }, { key: "city", label: "City" }, { key: "orders", label: "Orders", num: true }, { key: "revenue", label: "Revenue", num: true }, { key: "share_of_revenue_pct", label: "Share", num: true }],
          r.top_customers || [],
          { rankKey: "rank", shareKey: "share_of_revenue_pct", money: ["revenue"], strong: ["customer"], subs: { customer: (row) => `${row.segment} · last order ${row.last_order_date}` } },
        ),
      );
      break;
    }
    case "revenue_by_city": {
      if (r.monthly) {
        const months = r.monthly.map((m) => m.month);
        const cities = (r.cities || []).map((c) => c.city);
        const [, , sd] = (r.range?.start || "0-0-1").split("-").map(Number);
        const [ey, em, ed] = (r.range?.end || "0-0-1").split("-").map(Number);
        const partialFirst = sd > 1;
        const partialLast = ed < new Date(ey, em, 0).getDate();
        wrap.append(
          head("Monthly revenue by city", `${r.range?.start} to ${r.range?.end} · ${months.length} months`, h("div", { class: "r-kpis" }, kpi("Total", r.total_revenue, fmt.aed), kpi("Cities", cities.length))),
          lines(months, cities.map((c, i) => ({ name: c, values: r.monthly.map((m) => m[c] || 0), color: SERIES_COLORS[i % 4] })), { partialLast, partialFirst, width }),
          partialLast || partialFirst ? h("p", { class: "r-foot", text: `* partial month: the range ${partialFirst ? "starts" : "ends"}${partialFirst && partialLast ? " and ends" : ""} mid-month.` }) : null,
        );
      } else {
        wrap.append(
          head(`Revenue by city · ${(r.range?.label || "").replace(/_/g, " ")}`, `${r.range?.start} to ${r.range?.end} · compared with ${r.previous_period?.start} to ${r.previous_period?.end}`,
            h("div", { class: "r-kpis" }, kpi("Total", r.total_revenue, fmt.aed))),
          bars((r.cities || []).map((c) => ({ label: c.city, sub: `${fmt.int(c.orders)} orders · ${c.customers} customers · ${c.share_pct ?? "–"}% share`, value: c.revenue, chip: changeChip(c.change_pct) }))),
        );
      }
      break;
    }
    case "top_products": {
      wrap.append(
        head(`Best sellers · ${(r.range?.label || "").replace(/_/g, " ")}`, `${r.range?.start} to ${r.range?.end} · ranked by ${r.sort_by}${r.category ? ` · ${r.category}` : ""}${r.city ? ` · ${r.city}` : ""}`,
          h("div", { class: "r-kpis" }, kpi("In scope", r.total_revenue_in_scope, fmt.aed))),
        bars((r.products || []).map((p) => ({
          label: p.product, sub: `${p.category} · ${fmt.int(p.units)} units · ${p.orders} orders`,
          value: r.sort_by === "units" ? p.units : p.revenue, format: r.sort_by === "units" ? (v) => `${fmt.int(v)} u` : fmt.aed,
          chip: h("span", { class: "chip chip-light", text: `${p.gross_margin_pct ?? "–"}% margin` }),
        }))),
      );
      break;
    }
    case "run_sql": {
      const cols = (r.columns || []).map((c) => ({ key: c, label: c.replace(/_/g, " "), num: (r.rows || []).some((row) => typeof row[c] === "number") }));
      wrap.append(
        head(`${fmt.int(r.row_count)} row${r.row_count === 1 ? "" : "s"}${r.truncated ? ` (capped at ${r.row_limit})` : ""}`, `executed in ${r.elapsed_ms} ms · read-only transaction · row cap ${r.row_limit}`,
          r.truncated ? h("span", { class: "chip chip-amber", text: "row cap hit" }) : h("span", { class: "chip chip-up", text: "read-only" })),
        cols.length ? table(cols, r.rows || [], { money: cols.filter((c) => /revenue|amount|total/.test(c.key)).map((c) => c.key), strong: [cols[0]?.key] }) : h("p", { class: "r-sub", text: "No columns returned." }),
        (r.rows || []).length > 60 ? h("p", { class: "r-foot", text: `Showing 60 of ${r.row_count} rows here; the full result is in the response frame.` }) : null,
      );
      break;
    }
    case "list_tables": {
      wrap.append(
        head(`${r.table_count} tables and views`, `schema ${r.schema} · approx rows from planner statistics`),
        table([{ key: "name", label: "Name" }, { key: "kind", label: "Kind" }, { key: "approx_rows", label: "Rows", num: true }, { key: "column_count", label: "Cols", num: true }], r.tables || [], { strong: ["name"], subs: { name: (row) => row.description || "" } }),
      );
      break;
    }
    case "describe_table": {
      wrap.append(
        head(`${r.name} (${r.kind})`, `${(r.columns || []).length} columns · ${r.primary_key || "no primary key"} · ${(r.sample_rows || []).length} sample rows`),
        table([{ key: "name", label: "Column" }, { key: "type", label: "Type" }, { key: "nullable", label: "Null" }], (r.columns || []).map((c) => ({ ...c, nullable: c.nullable ? "yes" : "no" })), { strong: ["name"], subs: { name: (row) => row.description || "" } }),
      );
      break;
    }
    default:
      wrap.append(h("pre", { class: "sql", text: JSON.stringify(r, null, 2) }));
  }
  return box;
}

