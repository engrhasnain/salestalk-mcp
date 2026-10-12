// CTA band: your systems (labelled pills) joined to "Your MCP server" and on to Claude by thin solid
// lines; pulses travel from one system after another, through the server, to Claude.

import { COLORS, rgb, drawNode, drawLink, drawPolyline, drawComet, bezier, seeded, pointerNear, canvasLoop } from "./canvas.js";
import { $$, clamp, reduceMotion } from "./util.js";

export function createCta({ card, canvas, stage }) {
  const systems = $$("[data-sys]", stage);
  const core = stage.querySelector("[data-core]");
  const claude = stage.querySelector("[data-claude]");
  const rand = seeded(99);
  const mesh = Array.from({ length: 54 }, () => ({ x: rand(), y: rand(), a: rand() * 6.28, s: 0.00004 + rand() * 0.00005, r: 0.8 + rand() * 1.5, k: rand() }));
  let anchors = { sys: [], core: null, claude: null };
  let edges = [];
  const comets = [];
  let next = 0;
  let lastFire = 0;

  function center(el) {
    const c = card.getBoundingClientRect();
    const r = el.getBoundingClientRect();
    return { x: r.left - c.left + r.width / 2, y: r.top - c.top + r.height / 2, w: r.width, h: r.height };
  }

  function measure() {
    anchors = { sys: systems.map(center), core: center(core), claude: center(claude) };
    const cc = anchors.core;
    edges = anchors.sys.map((s) => {
      const p0 = { x: s.x, y: s.y };
      const p1 = { x: cc.x - cc.w / 2, y: cc.y };
      const dx = (p1.x - p0.x) * 0.55;
      return bezier(p0, { x: p0.x + dx, y: p0.y }, { x: p1.x - dx, y: p1.y }, p1, 24);
    });
    const cl = anchors.claude;
    edges.claude = [{ x: cc.x + cc.w / 2, y: cc.y }, { x: cl.x - cl.w / 2, y: cl.y }];
  }

  function fire(t) {
    const i = next % systems.length;
    next++;
    const pts = edges[i];
    if (!pts) return;
    comets.push({ pts, t0: t, dur: 1100, color: COLORS.accentHi, onArrive: () => {
      systems[i].classList.add("is-lit");
      setTimeout(() => systems[i].classList.remove("is-lit"), 900);
      comets.push({ pts: edges.claude, t0: performance.now(), dur: 700, color: COLORS.emerald, onArrive: () => {
        claude.classList.add("is-lit");
        setTimeout(() => claude.classList.remove("is-lit"), 700);
      } });
    } });
    systems[i].classList.add("is-lit");
  }

  function draw(ctx, w, h, t, dt, pointer) {
    const box = stage.getBoundingClientRect();
    const c = card.getBoundingClientRect();
    const sx = box.left - c.left;
    const sy = box.top - c.top;
    // drifting mesh behind the right half
    const pts = mesh.map((m) => {
      const a = m.a + (reduceMotion ? 0 : t * m.s);
      return { x: sx + (m.x + Math.cos(a) * 0.03) * box.width, y: sy + (m.y + Math.sin(a) * 0.04) * box.height, m };
    });
    for (let i = 0; i < pts.length; i++) {
      for (let j = i + 1; j < pts.length; j++) {
        const d = Math.hypot(pts[i].x - pts[j].x, pts[i].y - pts[j].y);
        if (d < 90) drawLink(ctx, pts[i], pts[j], rgb("#8E98FF"), (1 - d / 90) * 0.16, 0.7);
      }
    }
    for (const p of pts) {
      const near = pointerNear(p, pointer, 120);
      drawNode(ctx, p.x, p.y, p.m.r * (1 + near), "#8E98FF", 0.35 + 0.3 * p.m.k + near * 0.5, near > 0.2 ? 0.8 : 0);
      if (near > 0.1) drawLink(ctx, p, pointer, rgb("#8E98FF"), near * 0.4, 0.8);
    }
    // the integration lines (solid)
    edges.forEach((e) => drawPolyline(ctx, e, 1, rgb("#6E7BFF"), 0.45, 1.2));
    if (edges.claude) drawPolyline(ctx, edges.claude, 1, rgb("#2FD39A"), 0.45, 1.2);

    if (!reduceMotion && t - lastFire > 1500) { lastFire = t; fire(t); }
    for (let i = comets.length - 1; i >= 0; i--) {
      const cm = comets[i];
      const f = clamp((t - cm.t0) / cm.dur, 0, 1);
      drawPolyline(ctx, cm.pts, f, rgb(cm.color), 0.7 * (1 - f * 0.4), 1.8);
      if (f < 1) drawComet(ctx, cm.pts, f, cm.color, 3.2);
      else { comets.splice(i, 1); cm.onArrive && cm.onArrive(); }
    }
  }

  const loop = canvasLoop(canvas, draw, { onResize: measure });
  window.addEventListener("load", () => { measure(); loop.redraw(); });
  return { measure };
}
