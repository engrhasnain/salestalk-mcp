// "How one question flows": Claude → MCP (stdio) → SalesTalk tools → range parser / SQL guard →
// DB layer → PostgreSQL, drawn as cards joined by thin solid lines. Every call made on the page
// replays here: a glowing pulse goes out with the request and comes back with the response; a
// refused call stops (in red) at the layer that refused it.

import { rgb, drawNode, drawLink, drawRing, drawPolyline, drawComet, bezier, pathLength, seeded, pointerNear, canvasLoop } from "./canvas.js";
import { $, $$, h, icon, fmt, argsInline, refusalLayer, cleanError, reduceMotion, clamp, watchVisible, sleep } from "./util.js";

const EDGES = [["client", "mcp"], ["mcp", "server"], ["server", "range"], ["server", "guard"], ["server", "db"], ["range", "db"], ["guard", "db"], ["db", "pg"]];
const LABEL = { client: "Claude", mcp: "MCP", server: "tools", range: "range parser", guard: "SQL guard", db: "DB layer", pg: "PostgreSQL" };
const C = { line: rgb("#B9BCE0"), lit: rgb("#5360F0"), back: rgb("#0E9F6E"), red: rgb("#E5484D"), amber: rgb("#D98A0B"), mesh: rgb("#9AA0D8") };

export function createFlow({ card, canvas, grid, onIdle }) {
  const nodes = Object.fromEntries($$("[data-node]", grid).map((el) => [el.dataset.node, el]));
  for (const el of Object.values(nodes)) {
    const st = el.querySelector(".fnode-state");
    st.append(icon("check", "st-ok"), icon("x", "st-no"));
    const sub = el.querySelector(".mono");
    sub.dataset.default = sub.textContent;
  }
  const setSub = (k, text) => {
    const sub = nodes[k]?.querySelector(".mono");
    if (sub && text) { sub.textContent = text; sub.classList.add("is-live"); }
  };
  function details(o) {
    const r = o.result || {};
    const frames = o.frames || [];
    const out = frames.find((f) => f.direction === "out");
    const inn = frames.find((f) => f.direction === "in");
    const count = o.frames_count ?? frames.length;
    const bytes = o.bytes ?? frames.reduce((s, f) => s + f.bytes, 0);
    const rows = r.top_customers?.length ?? r.cities?.length ?? r.products?.length ?? r.tables?.length ?? r.columns?.length ?? r.row_count;
    const period = r.period || r.range;
    return {
      client: `${o.tool}()`,
      mcp: out && inn ? `→ ${fmt.bytes(out.bytes)} · ← ${fmt.bytes(inn.bytes)}` : count ? `${count} frames · ${fmt.bytes(bytes)}` : "tools/call",
      server: o.tool,
      range: period ? `${period.start} → ${period.end}` : null,
      guard: o.ok ? "passed: one SELECT" : null,
      db: r.elapsed_ms !== undefined ? `${r.elapsed_ms} ms · rolled back` : "READ ONLY · rolled back",
      pg: o.ok ? `${rows ?? 0} ${o.tool === "revenue_by_city" ? "cities" : "rows"} back` : cleanError(o.error).slice(0, 42),
    };
  }
  let geo = {}; // edge key -> polyline points
  let boxes = {};
  const comets = [];
  const ripples = [];
  const litEdges = new Map(); // key -> {rgb, t}
  const rand = seeded(42);
  const mesh = Array.from({ length: 46 }, () => ({ x: rand(), y: rand(), vx: (rand() - 0.5) * 0.00003, vy: (rand() - 0.5) * 0.00003, r: 1 + rand() * 1.6, ph: rand() * 6.28 }));
  let playing = false;
  let queued = null;
  let visible = false;
  let lastPlay = -1e9;
  const history = [];
  let historyIndex = 0;

  const els = { label: $("#flow-label"), code: $("#flow-code"), path: $("#flow-path"), latency: $("#flow-latency"), replay: $("#flow-replay") };

  function measure() {
    const c = card.getBoundingClientRect();
    boxes = {};
    for (const [k, el] of Object.entries(nodes)) {
      const r = el.getBoundingClientRect();
      boxes[k] = { l: r.left - c.left, t: r.top - c.top, r: r.right - c.left, b: r.bottom - c.top, cx: r.left - c.left + r.width / 2, cy: r.top - c.top + r.height / 2 };
    }
    geo = {};
    const maxRight = Math.max(...Object.values(boxes).map((b) => b.r));
    for (const [a, b] of EDGES) {
      const A = boxes[a];
      const B = boxes[b];
      if (!A || !B) continue;
      let pts;
      if (B.l >= A.r - 4) {
        const p0 = { x: A.r, y: A.cy };
        const p1 = { x: B.l, y: B.cy };
        const dx = (p1.x - p0.x) * 0.5;
        pts = bezier(p0, { x: p0.x + dx, y: p0.y }, { x: p1.x - dx, y: p1.y }, p1);
      } else if (a === "server" && b === "db") {
        // stacked layout: route around the range/guard pair along the right edge
        const x = Math.min(maxRight + 10, c.width - 6);
        const p0 = { x: A.r, y: A.cy };
        const p1 = { x: B.r, y: B.cy };
        pts = bezier(p0, { x, y: p0.y }, { x, y: p1.y }, p1);
      } else {
        const p0 = { x: A.cx, y: A.b };
        const p1 = { x: B.cx, y: B.t };
        const dy = (p1.y - p0.y) * 0.5;
        pts = bezier(p0, { x: p0.x, y: p0.y + dy }, { x: p1.x, y: p1.y - dy }, p1);
      }
      geo[`${a}-${b}`] = pts;
    }
  }

  function edgePoints(a, b) {
    if (geo[`${a}-${b}`]) return geo[`${a}-${b}`];
    if (geo[`${b}-${a}`]) return [...geo[`${b}-${a}`]].reverse();
    return null;
  }

  function draw(ctx, w, hgt, t, dt, pointer) {
    // ambient mesh: slowly drifting nodes with solid links that fade with distance
    const pts = mesh.map((m) => {
      if (!reduceMotion) {
        m.x += m.vx * dt; m.y += m.vy * dt;
        if (m.x < 0 || m.x > 1) m.vx *= -1;
        if (m.y < 0 || m.y > 1) m.vy *= -1;
      }
      return { x: m.x * w, y: m.y * hgt, m };
    });
    for (let i = 0; i < pts.length; i++) {
      for (let j = i + 1; j < pts.length; j++) {
        const d = Math.hypot(pts[i].x - pts[j].x, pts[i].y - pts[j].y);
        if (d < 120) drawLink(ctx, pts[i], pts[j], C.mesh, (1 - d / 120) * 0.16, 0.8);
      }
    }
    for (const p of pts) {
      const near = pointerNear(p, pointer, 130);
      drawNode(ctx, p.x, p.y, p.m.r * (1 + near), "#9AA0D8", 0.45 + near * 0.5 + 0.1 * Math.sin(t * 0.002 + p.m.ph), near > 0.2 ? 0.8 : 0);
      if (near > 0.1) drawLink(ctx, p, pointer, C.mesh, near * 0.35, 0.8);
    }

    // edges: always solid; lit ones glow with the call's colour and fade out
    for (const [key, ptsE] of Object.entries(geo)) {
      drawPolyline(ctx, ptsE, 1, C.line, 0.9, 1.4);
      const lit = litEdges.get(key);
      if (lit) {
        const age = t - lit.t;
        const a = lit.hold ? 1 : clamp(1 - (age - 1400) / 900, 0, 1);
        drawPolyline(ctx, ptsE, 1, lit.rgb, 0.8 * a, 2.2);
        if (a <= 0) litEdges.delete(key);
      }
    }

    for (let i = comets.length - 1; i >= 0; i--) {
      const cm = comets[i];
      const f = clamp((t - cm.t0) / cm.dur, 0, 1);
      if (t < cm.t0) continue;
      drawPolyline(ctx, cm.pts, f, cm.rgb, 0.95, 2.4);
      if (f < 1) drawComet(ctx, cm.pts, f, cm.color, 4);
      else { comets.splice(i, 1); cm.resolve(); }
    }

    for (let i = ripples.length - 1; i >= 0; i--) {
      const rp = ripples[i];
      const el = t - rp.t0;
      for (let k = 0; k < 4; k++) {
        const e = clamp((el - k * 220) / 1000, 0, 1);
        if (e > 0 && e < 1) drawRing(ctx, rp.x, rp.y, rp.r + e * 60, rp.rgb, (1 - e) * 0.85, 2);
      }
      if (el > 1800) ripples.splice(i, 1);
    }
  }

  const loop = canvasLoop(canvas, draw, { onResize: measure });
  window.addEventListener("load", () => { measure(); loop.redraw(); });

  function travel(a, b, color, rgbStr) {
    const pts = edgePoints(a, b);
    if (!pts) return Promise.resolve();
    const key = geo[`${a}-${b}`] ? `${a}-${b}` : `${b}-${a}`;
    return new Promise((resolve) => {
      const done = () => { litEdges.set(key, { rgb: rgbStr, t: performance.now() }); resolve(); };
      if (reduceMotion) { done(); return; }
      comets.push({ pts, t0: performance.now(), dur: clamp(pathLength(pts) / 0.55, 260, 700), color, rgb: rgbStr, resolve: done });
    });
  }

  function ripple(node, rgbStr) {
    const b = boxes[node];
    if (!b || reduceMotion) return;
    ripples.push({ x: b.cx, y: b.cy, r: Math.min(b.r - b.l, b.b - b.t) / 2, rgb: rgbStr, t0: performance.now() });
  }

  function plan(outcome) {
    const tool = outcome.tool;
    const check = tool === "run_sql" ? "guard" : ["query_sales", "revenue_by_city", "top_products"].includes(tool) ? "range" : null;
    const fwd = ["client", "mcp", "server", ...(check ? [check] : []), "db", "pg"];
    const back = ["pg", "db", "server", "mcp", "client"];
    if (outcome.ok) return { fwd, back, stop: null, check };
    const layer = refusalLayer(outcome);
    if (layer === "guard") return { fwd: ["client", "mcp", "server", "guard"], back: ["guard", "server", "mcp", "client"], stop: "guard", state: "is-refused", check };
    if (layer === "range") {
      const at = check || "server";
      return { fwd: fwd.slice(0, fwd.indexOf(at) + 1), back: at === "server" ? ["server", "mcp", "client"] : [at, "server", "mcp", "client"], stop: at, state: "is-warn", check };
    }
    if (layer === "connect") return { fwd: fwd.slice(0, fwd.indexOf("db") + 1), back: ["db", "server", "mcp", "client"], stop: "db", state: "is-refused", check };
    return { fwd, back, stop: "pg", state: "is-refused", check };
  }

  function reset() {
    Object.values(nodes).forEach((n) => {
      n.classList.remove("is-lit", "is-passed", "is-back", "is-refused", "is-warn", "is-dim");
      const sub = n.querySelector(".mono");
      sub.textContent = sub.dataset.default;
      sub.classList.remove("is-live");
    });
    litEdges.clear();
  }

  function setBar(outcome, live) {
    els.label.textContent = live ? "Live call" : "Replaying";
    els.code.textContent = `${outcome.tool}(${argsInline(outcome.arguments, 48)})`;
    els.code.title = `${outcome.tool}(${argsInline(outcome.arguments)})`;
    const p = plan(outcome);
    const keys = [...new Set([...p.fwd])];
    els.path.replaceChildren(...keys.map((k) => h("li", { "data-k": k, text: LABEL[k] })));
    els.latency.textContent = "";
  }

  async function play(outcome, live = false) {
    if (playing) { queued = { outcome, live }; return; }
    playing = true;
    lastPlay = performance.now();
    measure();
    reset();
    setBar(outcome, live);
    const p = plan(outcome);
    const info = details(outcome);
    const pathLi = (k) => els.path.querySelector(`[data-k="${k}"]`);
    // dim the branch this call does not use
    for (const k of ["range", "guard"]) if (p.check !== k) nodes[k].classList.add("is-dim");
    if (!p.check) { nodes.range.classList.add("is-dim"); nodes.guard.classList.add("is-dim"); }

    nodes[p.fwd[0]].classList.add("is-lit");
    setSub(p.fwd[0], info.client);
    pathLi(p.fwd[0])?.classList.add("is-on");
    for (let i = 1; i < p.fwd.length; i++) {
      const a = p.fwd[i - 1];
      const b = p.fwd[i];
      const isStop = b === p.stop;
      const stopRgb = p.state === "is-warn" ? C.amber : C.red;
      await travel(a, b, isStop ? (p.state === "is-warn" ? "#D98A0B" : "#E5484D") : "#5360F0", isStop ? stopRgb : C.lit);
      nodes[a].classList.remove("is-lit");
      nodes[a].classList.add("is-passed");
      if (isStop) {
        nodes[b].classList.add(p.state);
        setSub(b, p.state === "is-warn" ? "invalid input" : b === "guard" ? "refused" : "refused here");
        pathLi(b)?.classList.add(p.state === "is-warn" ? "is-warn" : "is-refused");
        ripple(b, stopRgb);
        await sleep(650);
      } else {
        nodes[b].classList.add("is-lit");
        pathLi(b)?.classList.add("is-on");
        setSub(b, info[b]);
      }
    }
    if (!p.stop) { ripple("pg", C.lit); await sleep(220); }
    // the response travels back
    const backRgb = p.stop ? (p.state === "is-warn" ? C.amber : C.red) : C.back;
    const backColor = p.stop ? (p.state === "is-warn" ? "#D98A0B" : "#E5484D") : "#0E9F6E";
    for (let i = 1; i < p.back.length; i++) {
      const a = p.back[i - 1];
      const b = p.back[i];
      await travel(a, b, backColor, backRgb);
      if (a !== p.stop) { nodes[a].classList.remove("is-lit"); nodes[a].classList.add("is-passed", "is-back"); }
    }
    nodes.client.classList.remove("is-lit");
    nodes.client.classList.add("is-passed", "is-back");
    setSub("client", `${fmt.ms(outcome.latency_ms)} ms round trip`);
    const frames = outcome.frames_count ?? (outcome.frames || []).length;
    const bytes = outcome.bytes ?? (outcome.frames || []).reduce((s, f) => s + f.bytes, 0);
    els.latency.textContent = `${fmt.ms(outcome.latency_ms)} ms${frames ? ` · ${frames} frames · ${fmt.bytes(bytes)}` : ""}`;
    loop.redraw();
    await sleep(1600);
    playing = false;
    lastPlay = performance.now();
    if (queued) { const q = queued; queued = null; play(q.outcome, q.live); }
  }

  function remember(outcome) {
    history.push(outcome);
    if (history.length > 10) history.shift();
    historyIndex = history.length - 1;
  }

  /** A call just happened somewhere on the page. */
  function push(outcome) {
    remember(outcome);
    if (visible) play(outcome, true); else queued = { outcome, live: true };
  }

  function seed(outcomes) {
    outcomes.forEach(remember);
    historyIndex = 0;
  }

  watchVisible(card, (v) => {
    visible = v;
    if (v) {
      measure();
      if (queued && !playing) { const q = queued; queued = null; play(q.outcome, q.live); }
      else if (!playing && history.length && performance.now() - lastPlay > 3000) play(history[historyIndex], false);
    }
  }, "-15% 0px");

  // keep it alive: when idle, replay the calls made on this page, one after another
  setInterval(() => {
    if (!visible || playing || !history.length || reduceMotion) return;
    if (performance.now() - lastPlay < 5200) return;
    historyIndex = (historyIndex + 1) % history.length;
    play(history[historyIndex], false);
    if (onIdle) onIdle();
  }, 900);

  els.replay.addEventListener("click", () => { if (history.length) play(history[historyIndex], false); });

  return { push, seed, play };
}
