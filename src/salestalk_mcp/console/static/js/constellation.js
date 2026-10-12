// The data constellation: built from REAL tool results. The four cities are hubs sized by revenue,
// every customer orbits its city hub (sized by revenue), joined by thin solid links. When a tool
// runs, a glowing pulse travels from the source (feed card or tool-call chip) through the server's
// check (range parser / SQL guard) into the hubs and customers the result talks about.

import { COLORS, rgb, drawNode, drawLink, drawRing, drawPolyline, drawComet, pathLength, seeded, pointerNear, canvasLoop } from "./canvas.js";
import { h, fmt, reduceMotion, refusalLayer, LAYER_NAMES, clamp } from "./util.js";

const LINK = rgb("#AEB5FF");
const SPOKE = rgb("#8E98FF");
const LANE = rgb("#6E7BFF");
const RED = rgb(COLORS.red);
const AMBER = rgb(COLORS.amber);
const ACC = rgb(COLORS.accent);

// Stage-relative layouts (fractions of the stage box). West to east: KSA, then the UAE.
const LAYOUTS = {
  hero: {
    hubs: { Jeddah: [0.15, 0.50], Riyadh: [0.40, 0.21], "Abu Dhabi": [0.60, 0.48], Dubai: [0.86, 0.20] },
    gates: { range: [0.07, 0.75], guard: [0.19, 0.9] },
    scale: 0.2,
  },
  heroNarrow: {
    hubs: { Jeddah: [0.2, 0.62], Riyadh: [0.36, 0.24], "Abu Dhabi": [0.66, 0.66], Dubai: [0.8, 0.26] },
    gates: { range: [0.4, 0.95], guard: [0.62, 0.95] },
    scale: 0.26,
  },
  strip: {
    hubs: { Jeddah: [0.2, 0.64], Riyadh: [0.42, 0.3], "Abu Dhabi": [0.64, 0.68], Dubai: [0.86, 0.33] },
    gates: { range: [0.08, 0.3], guard: [0.08, 0.72] },
    scale: 0.25,
  },
  stripNarrow: {
    hubs: { Jeddah: [0.17, 0.64], Riyadh: [0.4, 0.4], "Abu Dhabi": [0.63, 0.76], Dubai: [0.84, 0.44] },
    gates: { range: [0.24, 0.09], guard: [0.64, 0.09] },
    scale: 0.24,
  },
};
const TILT = { Jeddah: -0.35, Riyadh: 0.25, "Abu Dhabi": -0.2, Dubai: 0.3 };
const GATE_LABEL = { range: "range parser", guard: "SQL guard" };

export function createConstellation({ canvas, overlay, stage, layout = "hero", wide = 720, maxTags = 5 }) {
  const rand = seeded(layout === "hero" ? 20261011 : 7);
  let hubs = [];
  let customers = [];
  const gates = ["range", "guard"].map((key) => ({ key, x: 0, y: 0, flash: -1e9, state: null, pill: null }));
  const comets = [];
  const ripples = [];
  let stageBox = { x: 0, y: 0, w: 100, h: 100 };
  let now = performance.now();
  let lastTraffic = 0;
  let hovered = null;

  // ------------------------------------------------------------ overlay (HTML labels)
  const tip = h("div", { class: "node-tip" });
  const tagPool = Array.from({ length: 6 }, () => h("div", { class: "node-tag" }));
  const tags = []; // {el, target(), until}
  overlay.append(tip, ...tagPool);
  for (const g of gates) {
    g.pill = h("span", { class: "gate-pill", text: GATE_LABEL[g.key] });
    overlay.append(g.pill);
  }

  function layoutFor(w) {
    if (layout === "hero") return w < wide ? LAYOUTS.heroNarrow : LAYOUTS.hero;
    return w < wide ? LAYOUTS.stripNarrow : LAYOUTS.strip;
  }

  function measure() {
    const c = canvas.getBoundingClientRect();
    const s = stage.getBoundingClientRect();
    stageBox = { x: s.left - c.left, y: s.top - c.top, w: Math.max(40, s.width), h: Math.max(40, s.height) };
    const L = layoutFor(stageBox.w);
    const base = Math.min(stageBox.w, stageBox.h * 1.25);
    const maxRev = Math.max(1, ...hubs.map((hb) => hb.revenue));
    for (const hb of hubs) {
      const [fx, fy] = L.hubs[hb.city] || [0.5, 0.5];
      hb.x = stageBox.x + fx * stageBox.w;
      hb.y = stageBox.y + fy * stageBox.h;
      const k = Math.sqrt(hb.revenue / maxRev);
      hb.r = 6 + 7 * k;
      hb.R = base * L.scale * (0.62 + 0.38 * k);
    }
    for (const g of gates) {
      const [fx, fy] = L.gates[g.key];
      g.x = stageBox.x + fx * stageBox.w;
      g.y = stageBox.y + fy * stageBox.h;
    }
  }

  function setData({ cities = [], customers: list = [] }) {
    const byCity = new Map();
    const fallback = ["Dubai", "Riyadh", "Abu Dhabi", "Jeddah"].map((city) => ({ city, revenue: 1 }));
    hubs = (cities.length ? cities : fallback).map((c) => ({
      city: c.city, revenue: Number(c.revenue) || 1, share: c.share_pct, x: 0, y: 0, r: 8, R: 60,
      flash: -1e9, flashColor: COLORS.accent, pill: null, pillText: cities.length ? fmt.aedCompact(c.revenue) : "loading",
      override: null,
    }));
    overlay.querySelectorAll(".hub-pill").forEach((el) => el.remove());
    for (const hb of hubs) {
      hb.pill = h("span", { class: "hub-pill" }, h("span", { text: hb.city }), h("b", { text: hb.pillText }));
      overlay.append(hb.pill);
      byCity.set(hb.city, hb);
    }
    const maxRev = Math.max(1, ...list.map((c) => Number(c.revenue) || 0));
    const groups = new Map();
    for (const c of list) {
      if (!byCity.has(c.city)) continue;
      if (!groups.has(c.city)) groups.set(c.city, []);
      groups.get(c.city).push(c);
    }
    customers = [];
    for (const [city, group] of groups) {
      group.sort((a, b) => (b.revenue || 0) - (a.revenue || 0));
      const n = group.length;
      group.forEach((c, i) => {
        const rev = Number(c.revenue) || 0;
        const k = Math.sqrt(rev / maxRev);
        customers.push({
          ...c,
          hub: byCity.get(city),
          rank: i,
          top: i < 8,
          orbit: 0.3 + 0.7 * Math.pow((i + 1) / n, 0.62) + (rand() - 0.5) * 0.08,
          squash: 0.58 + rand() * 0.1,
          angle0: i * 2.39996 + rand() * 0.6,
          speed: (0.000055 + rand() * 0.00003) * (city === "Riyadh" || city === "Dubai" ? 1 : -1),
          size: 1.05 + 3.4 * k,
          tw: rand() * Math.PI * 2,
          flash: -1e9,
          x: 0, y: 0,
        });
      });
    }
    measure();
    loop.redraw();
  }

  function positions(t) {
    const tt = reduceMotion ? 0 : t;
    for (const c of customers) {
      const hb = c.hub;
      const a = c.angle0 + tt * c.speed / Math.sqrt(c.orbit);
      const rx = hb.R * c.orbit * 1.35;
      const ry = rx * c.squash;
      const tilt = TILT[hb.city] || 0;
      const ca = Math.cos(a) * rx;
      const sa = Math.sin(a) * ry;
      c.x = hb.x + ca * Math.cos(tilt) - sa * Math.sin(tilt);
      c.y = hb.y + ca * Math.sin(tilt) + sa * Math.cos(tilt);
    }
  }

  // ------------------------------------------------------------ drawing

  function draw(ctx, w, hgt, t, dt, pointer) {
    now = t;
    positions(t);
    const lanes = [];
    for (let i = 0; i < hubs.length; i++) for (let j = i + 1; j < hubs.length; j++) lanes.push([hubs[i], hubs[j]]);

    // trade lanes between cities (solid)
    for (const [a, b] of lanes) drawLink(ctx, a, b, LANE, 0.2, 1);

    // ambient traffic: a small pulse along a lane every couple of seconds
    if (!reduceMotion && hubs.length > 1 && t - lastTraffic > 2300) {
      lastTraffic = t;
      const [a, b] = lanes[Math.floor(Math.random() * lanes.length)];
      const [from, to] = Math.random() < 0.5 ? [a, b] : [b, a];
      addComet([() => from, () => to], { color: COLORS.accentHi, size: 2.2, trail: 0.22, onArrive: () => ripple(() => to, COLORS.accentHi, 0.5) });
    }

    // customer mesh: solid links that fade with distance
    const D = layout === "hero" ? 34 : 30;
    for (let i = 0; i < customers.length; i++) {
      const a = customers[i];
      for (let j = i + 1; j < customers.length; j++) {
        const b = customers[j];
        const dx = a.x - b.x;
        if (dx > D || dx < -D) continue;
        const dy = a.y - b.y;
        if (dy > D || dy < -D) continue;
        const d = Math.hypot(dx, dy);
        if (d < D) drawLink(ctx, a, b, LINK, (1 - d / D) * 0.24, 0.7);
      }
    }
    // spokes from the biggest customers to their hub
    for (const c of customers) if (c.top) drawLink(ctx, c, c.hub, SPOKE, 0.16, 0.8);

    // comets (request pulses) with their solid lit path
    for (let i = comets.length - 1; i >= 0; i--) {
      const cm = comets[i];
      const el = t - cm.t0;
      if (el < 0) continue;
      const pts = cm.path.map((fn) => fn());
      const f = clamp(el / cm.dur, 0, 1);
      const fade = cm.arrivedAt ? clamp(1 - (t - cm.arrivedAt) / 700, 0, 1) : 1;
      drawPolyline(ctx, pts, f, cm.rgb, cm.trail * fade, cm.width);
      if (f < 1) drawComet(ctx, pts, f, cm.color, cm.size);
      else if (!cm.arrivedAt) { cm.arrivedAt = t; cm.onArrive && cm.onArrive(); }
      if (cm.arrivedAt && fade <= 0) comets.splice(i, 1);
    }

    // customers
    for (const c of customers) {
      const fl = clamp(1 - (t - c.flash) / 2200, 0, 1);
      const near = pointerNear(c, pointer, 120);
      const tw = reduceMotion ? 0.8 : 0.72 + 0.28 * Math.sin(t * 0.0016 + c.tw);
      const base = c.top ? 0.92 : 0.36 + 0.4 * (c.size / 4.5);
      const alpha = Math.min(1, base * tw + near * 0.5 + fl);
      const r = c.size * (1 + near * 0.7 + fl * 1.3);
      const color = fl > 0.05 ? (fl > 0.6 ? COLORS.white : COLORS.accentHi) : c.top ? "#B7BDFF" : COLORS.lavender;
      drawNode(ctx, c.x, c.y, r, color, alpha, fl > 0 || near > 0.3 ? 0.5 + fl * 0.9 + near * 0.5 : c.top ? 0.35 : 0);
      if (fl > 0) drawRing(ctx, c.x, c.y, r + 4 + (1 - fl) * 18, ACC, fl * 0.7, 1.2);
      if (near > 0.08) drawLink(ctx, c, pointer, LINK, near * 0.5, 0.8);
    }

    // hubs
    for (const hb of hubs) {
      const fl = clamp(1 - (t - hb.flash) / 1800, 0, 1);
      const near = pointerNear(hb, pointer, 150);
      const breathe = reduceMotion ? 0 : Math.sin(t * 0.0018 + hb.x) * 1.2;
      drawRing(ctx, hb.x, hb.y, hb.r + 9 + breathe, ACC, 0.35 + near * 0.3, 1);
      if (fl > 0) {
        drawRing(ctx, hb.x, hb.y, hb.r + 10 + (1 - fl) * 46, rgb(hb.flashColor), fl * 0.85, 1.6);
        drawRing(ctx, hb.x, hb.y, hb.r + 6 + (1 - fl) * 24, rgb(hb.flashColor), fl * 0.6, 1.2);
      }
      drawNode(ctx, hb.x, hb.y, hb.r * (1 + fl * 0.25), fl > 0.2 ? hb.flashColor : COLORS.accent, 1, 0.55 + fl * 0.55 + near * 0.4);
      drawNode(ctx, hb.x, hb.y, hb.r * 0.38, COLORS.white, 1, 0);
      if (near > 0.1) drawLink(ctx, hb, pointer, LANE, near * 0.55, 1);
    }

    // gates (the server's checks)
    for (const g of gates) {
      const fl = clamp(1 - (t - g.flash) / 2400, 0, 1);
      const col = g.state === "refused" ? COLORS.red : g.state === "warn" ? COLORS.amber : COLORS.accentHi;
      drawRing(ctx, g.x, g.y, 7, rgb(col), 0.55 + fl * 0.45, 1.2);
      drawNode(ctx, g.x, g.y, 3.2 + fl * 1.6, fl > 0.05 ? col : "#7D85D6", 1, fl > 0.05 ? 1.2 + fl : 0.4);
      if (fl <= 0 && g.state) { g.state = null; g.pill.classList.remove("is-refused", "is-warn", "is-lit"); }
    }

    // ripples
    for (let i = ripples.length - 1; i >= 0; i--) {
      const rp = ripples[i];
      const p = rp.at();
      const el = t - rp.t0;
      for (let k = 0; k < rp.rings; k++) {
        const e = clamp((el - k * 200) / rp.dur, 0, 1);
        if (e > 0 && e < 1) drawRing(ctx, p.x, p.y, 6 + e * rp.size, rgb(rp.color), (1 - e) * 0.9 * rp.strength, 1.6);
      }
      if (el > rp.dur + rp.rings * 200) ripples.splice(i, 1);
    }

    updateOverlay(pointer);
  }

  function updateOverlay(pointer) {
    const CW = canvas.clientWidth;
    for (const hb of hubs) {
      if (!hb.pill) continue;
      const pw = hb.pill.offsetWidth;
      hb.pillX = clamp(hb.x, Math.max(pw / 2 + 6, stageBox.x + pw / 2 + 4), CW - pw / 2 - 6);
      hb.pill.style.transform = `translate(${hb.pillX}px, ${hb.y - hb.r - 26}px) translate(-50%, -50%)`;
    }
    for (const g of gates) {
      const pw = g.pill.offsetWidth;
      g.pill.style.transform = `translate(${clamp(g.x, pw / 2 + 4, CW - pw / 2 - 4)}px, ${g.y + 19}px) translate(-50%, -50%)`;
    }
    for (let i = tags.length - 1; i >= 0; i--) {
      if (now > tags[i].until) { tags[i].el.classList.remove("is-on"); tags.splice(i, 1); }
    }
    // place tags above their node; nudge any that would overlap a label already placed
    const W = canvas.clientWidth;
    const placed = [];
    for (const hb of hubs) if (hb.pill) placed.push({ x: hb.pillX ?? hb.x, y: hb.y - hb.r - 26, w: hb.pill.offsetWidth, h: hb.pill.offsetHeight });
    for (const g of gates) placed.push({ x: g.x, y: g.y + 19, w: g.pill.offsetWidth, h: g.pill.offsetHeight });
    const ordered = tags.map((tg) => ({ tg, p: tg.target(), w: tg.el.offsetWidth || 160, hh: tg.el.offsetHeight || 24 }))
      .sort((a, b) => b.p.y - a.p.y);
    for (const it of ordered) {
      const x = clamp(it.p.x, it.w / 2 + 8, W - it.w / 2 - 8);
      const hits = (y) => placed.find((q) => Math.abs(q.x - x) < (q.w + it.w) / 2 + 6 && Math.abs(q.y - y) < (q.h + it.hh) / 2 + 4);
      const minY = stageBox.y + it.hh / 2 + 6;
      let cy = it.p.y - (it.tg.offset || 0) - 12 - it.hh / 2; // the tag sits above its node
      for (let n = 0, hit = hits(cy); hit && n < 10; n++, hit = hits(cy)) cy = hit.y - (hit.h + it.hh) / 2 - 5;
      if (cy < minY) {
        // no room above: hang it below the node instead
        cy = it.p.y + 14 + it.hh / 2;
        for (let n = 0, hit = hits(cy); hit && n < 10; n++, hit = hits(cy)) cy = hit.y + (hit.h + it.hh) / 2 + 5;
      }
      placed.push({ x, y: cy, w: it.w, h: it.hh });
      it.tg.el.style.left = `${x}px`;
      it.tg.el.style.top = `${cy + 12 + it.hh / 2}px`;
    }
    // hover tooltip (customers and hubs)
    let best = null;
    if (pointer) {
      let bd = 16;
      for (const c of customers) {
        const d = Math.hypot(c.x - pointer.x, c.y - pointer.y);
        if (d < bd) { bd = d; best = c; }
      }
      for (const hb of hubs) if (Math.hypot(hb.x - pointer.x, hb.y - pointer.y) < hb.r + 8) best = hb;
    }
    if (best !== hovered) {
      hovered = best;
      if (best) {
        const isHub = !best.hub;
        tip.replaceChildren(
          h("strong", { text: isHub ? best.city : best.name }),
          isHub
            ? h("span", { text: `${fmt.aed(best.revenue)} · ${best.share ?? "–"}% of revenue` })
            : h("span", { text: `${best.city} · ${best.segment || "customer"}` }),
          isHub ? h("span", { text: "last 12 months, revenue_by_city" }) : h("span", { text: `${fmt.aed(best.revenue)} · ${best.orders} orders` }),
        );
      }
      tip.classList.toggle("is-on", !!best);
    }
    if (best) tip.style.transform = `translate(${best.x + 14}px, ${best.y}px) translate(0, -50%)`;
  }

  // ------------------------------------------------------------ effects

  function addComet(path, { delay = 0, color = COLORS.accent, size = 3.2, trail = 0.55, width = 1.4, speed = 0.7, onArrive } = {}) {
    const pts = path.map((fn) => fn());
    const len = pathLength(pts);
    const cm = { path, t0: performance.now() + delay, dur: clamp(len / speed, 520, 1500), color, rgb: rgb(color), size, trail, width, onArrive, arrivedAt: 0 };
    if (reduceMotion) { setTimeout(() => onArrive && onArrive(), 0); return; }
    comets.push(cm);
  }

  function ripple(at, color, strength = 1, size = 42, rings = 3) {
    if (reduceMotion) return;
    ripples.push({ at, t0: performance.now(), color, strength, size, rings, dur: 900 });
  }

  function showTag(target, html, ms = 2800, { refused = false, warn = false, offset = 0 } = {}) {
    const el = tagPool.find((t) => !tags.some((x) => x.el === t)) || tagPool[0];
    const existing = tags.findIndex((x) => x.el === el);
    if (existing >= 0) tags.splice(existing, 1);
    el.innerHTML = html;
    el.classList.toggle("is-refused", refused);
    el.classList.toggle("is-warn", warn);
    el.classList.add("is-on");
    tags.push({ el, target, until: performance.now() + ms, offset });
  }

  const at = (obj) => () => obj;
  const fixed = (p) => () => p;

  function sourcePoint(source) {
    const c = canvas.getBoundingClientRect();
    if (!source) return { x: stageBox.x + stageBox.w * 0.5, y: stageBox.y + stageBox.h };
    const r = source.getBoundingClientRect ? source.getBoundingClientRect() : source;
    if (layout === "hero" && stageBox.w >= wide) return { x: r.left - c.left + 2, y: r.top - c.top + r.height * 0.32 };
    if (layout === "hero") return { x: r.left - c.left + r.width * 0.5, y: r.top - c.top };
    if (stageBox.w >= wide) return { x: r.right - c.left - 4, y: r.top - c.top + r.height / 2 };
    return { x: r.left - c.left + r.width / 2, y: r.bottom - c.top };
  }

  const findHub = (city) => hubs.find((hb) => hb.city === city);
  const findCustomer = (name, city) => customers.find((c) => c.name === name && (!city || c.city === city));

  /** React to one tool call outcome. source: element (or rect) the pulse starts from. */
  function fire(outcome, source) {
    measure();
    const src = sourcePoint(source);
    const tool = outcome.tool;
    const res = outcome.result || {};
    const gateKey = tool === "run_sql" ? "guard" : ["query_sales", "revenue_by_city", "top_products"].includes(tool) ? "range" : null;
    const gate = gates.find((g) => g.key === gateKey);
    const viaGate = gate ? [fixed(src), at(gate)] : [fixed(src)];

    if (!outcome.ok) {
      const layer = refusalLayer(outcome);
      const stopAtGate = gate && (layer === "guard" || layer === "range");
      const color = layer === "range" ? COLORS.amber : COLORS.red;
      const label = layer === "range" ? "<i>INVALID</i>input" : `<i>REFUSED</i>${LAYER_NAMES[layer] || "server"}`;
      const tagOpts = { refused: layer !== "range", warn: layer === "range" };
      if (stopAtGate || !gate) {
        const target = gate || { x: src.x, y: src.y - 40 };
        addComet([fixed(src), at(target)], {
          color, trail: 0.6,
          onArrive: () => {
            if (gate) {
              gate.flash = performance.now(); gate.state = layer === "range" ? "warn" : "refused";
              gate.pill.classList.add(layer === "range" ? "is-warn" : "is-refused");
            }
            ripple(at(target), color, 1, 58, 4);
            showTag(at(target), label, 3200, { ...tagOpts, offset: 8 });
            loop.redraw();
          },
        });
      } else {
        // passed the guard, refused deeper (e.g. by the read-only role)
        const mid = { x: (gate.x + (hubs[1]?.x ?? gate.x)) / 2, y: (gate.y + (hubs[1]?.y ?? gate.y)) / 2 };
        addComet([fixed(src), at(gate), fixed(mid)], {
          color: COLORS.red,
          onArrive: () => { ripple(fixed(mid), COLORS.red, 1, 58, 4); showTag(fixed(mid), label, 3200, { refused: true }); },
        });
        gate.flash = performance.now(); gate.pill.classList.add("is-lit"); gate.state = "lit";
      }
      return;
    }

    if (gate) {
      gate.flash = performance.now(); gate.state = "lit"; gate.pill.classList.add("is-lit");
    }
    const targets = [];
    if (tool === "query_sales") {
      for (const c of res.top_customers || []) {
        const hb = findHub(c.city);
        const node = findCustomer(c.customer, c.city);
        if (hb) targets.push({ hub: hb, node, html: `<i>#${c.rank}</i>${escapeHtml(c.customer)}<b>${fmt.aed(c.revenue)}</b>` });
      }
    } else if (tool === "revenue_by_city") {
      for (const c of [...(res.cities || [])].sort((a, b) => b.revenue - a.revenue)) {
        const hb = findHub(c.city);
        if (hb) targets.push({ hub: hb, hubText: fmt.aedCompact(c.revenue) });
      }
    } else if (tool === "top_products") {
      const list = res.city ? hubs.filter((hb) => hb.city === res.city) : [...hubs].sort((a, b) => b.revenue - a.revenue);
      list.forEach((hb) => targets.push({ hub: hb }));
    } else if (tool === "run_sql") {
      const rows = res.rows || [];
      const nameKey = (res.columns || []).find((k) => ["customer", "company_name", "name"].includes(k));
      if (nameKey) {
        rows.slice(0, 24).forEach((r, i) => {
          const node = findCustomer(r[nameKey], r.city);
          if (!node) return;
          const extra = r.days_silent !== undefined ? `${r.days_silent} days silent` : r.revenue !== undefined ? fmt.aed(r.revenue) : "";
          targets.push({ hub: node.hub, node, html: i < 5 ? `${escapeHtml(r[nameKey])}<b>${extra}</b>` : null });
        });
      }
      if (!targets.length && (res.columns || []).includes("city")) {
        const seen = new Set();
        rows.forEach((r) => { const hb = findHub(r.city); if (hb && !seen.has(hb)) { seen.add(hb); targets.push({ hub: hb }); } });
      }
      if (!targets.length) hubs.forEach((hb) => targets.push({ hub: hb, soft: true }));
    } else {
      hubs.forEach((hb) => targets.push({ hub: hb, soft: true }));
    }

    const stagger = targets.length > 8 ? 70 : 170;
    let tagCount = 0;
    targets.forEach((tg, i) => {
      const path = [...viaGate, at(tg.hub)];
      if (tg.node) path.push(at(tg.node));
      const showThisTag = tg.html && tagCount < (stageBox.w < wide ? Math.min(3, maxTags) : maxTags);
      if (showThisTag) tagCount++;
      addComet(path, {
        delay: i * stagger,
        size: tg.soft ? 2.6 : 3.2,
        onArrive: () => {
          const tNow = performance.now();
          tg.hub.flash = tNow; tg.hub.flashColor = COLORS.accent;
          if (tg.node) tg.node.flash = tNow;
          if (tg.hubText) {
            tg.hub.pill.classList.add("is-lit");
            tg.hub.pill.querySelector("b").textContent = tg.hubText;
            clearTimeout(tg.hub._t);
            tg.hub._t = setTimeout(() => { tg.hub.pill.classList.remove("is-lit"); tg.hub.pill.querySelector("b").textContent = tg.hub.pillText; }, 3400);
          }
          if (showThisTag) showTag(at(tg.node || tg.hub), tg.html, 3000 + (5 - i) * 120);
          ripple(at(tg.node || tg.hub), COLORS.accentHi, tg.soft ? 0.5 : 0.8, tg.node ? 24 : 40, 2);
          if (reduceMotion) { loop.redraw(); setTimeout(() => loop.redraw(), 2600); }
        },
      });
    });
  }

  function escapeHtml(s) { return String(s).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]); }

  const loop = canvasLoop(canvas, draw, { onResize: () => measure() });
  window.addEventListener("load", () => { measure(); loop.redraw(); });

  return { setData, fire, redraw: () => loop.redraw(), get customerCount() { return customers.length; } };
}
