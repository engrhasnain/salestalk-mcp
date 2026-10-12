// Canvas-2D helpers for the constellation style: glowing nodes, thin SOLID links whose alpha fades
// with distance, comets (a bright node with a short fading tail) travelling along solid paths,
// ripples, a DPR-aware loop that pauses off-screen and draws one still frame under reduced motion.

import { reduceMotion } from "./util.js";

export const COLORS = {
  accent: "#6E7BFF",
  accentHi: "#8E98FF",
  lavender: "#C9CCF5",
  white: "#FFFFFF",
  emerald: "#2FD39A",
  red: "#F2555A",
  amber: "#F5A524",
  ink: "#0C0E1A",
};

export function rgb(hex) {
  const n = parseInt(hex.slice(1), 16);
  return `${(n >> 16) & 255},${(n >> 8) & 255},${n & 255}`;
}

const sprites = new Map();
/** A soft radial glow rendered once per colour (cheaper than shadowBlur on every frame). */
function glowSprite(color) {
  let s = sprites.get(color);
  if (s) return s;
  s = document.createElement("canvas");
  s.width = s.height = 64;
  const g = s.getContext("2d");
  const c = rgb(color);
  const grad = g.createRadialGradient(32, 32, 0, 32, 32, 32);
  grad.addColorStop(0, `rgba(${c},0.95)`);
  grad.addColorStop(0.22, `rgba(${c},0.5)`);
  grad.addColorStop(0.55, `rgba(${c},0.13)`);
  grad.addColorStop(1, `rgba(${c},0)`);
  g.fillStyle = grad;
  g.fillRect(0, 0, 64, 64);
  sprites.set(color, s);
  return s;
}

/** Glowing node: a small halo (only on nodes) + crisp solid core. */
export function drawNode(ctx, x, y, r, color, alpha = 1, glow = 1) {
  if (glow > 0) {
    const g = r * 4.2 * glow;
    ctx.globalAlpha = Math.min(1, alpha * (0.32 + 0.38 * glow));
    ctx.drawImage(glowSprite(color), x - g, y - g, g * 2, g * 2);
  }
  ctx.globalAlpha = alpha;
  ctx.fillStyle = color;
  ctx.beginPath();
  ctx.arc(x, y, r, 0, Math.PI * 2);
  ctx.fill();
  ctx.globalAlpha = 1;
}

export function drawLink(ctx, a, b, rgbStr, alpha, width = 1) {
  if (alpha <= 0.004) return;
  ctx.strokeStyle = `rgba(${rgbStr},${alpha})`;
  ctx.lineWidth = width;
  ctx.beginPath();
  ctx.moveTo(a.x, a.y);
  ctx.lineTo(b.x, b.y);
  ctx.stroke();
}

export function drawRing(ctx, x, y, r, rgbStr, alpha, width = 1.2) {
  if (alpha <= 0.004 || r <= 0) return;
  ctx.strokeStyle = `rgba(${rgbStr},${alpha})`;
  ctx.lineWidth = width;
  ctx.beginPath();
  ctx.arc(x, y, r, 0, Math.PI * 2);
  ctx.stroke();
}

function lengths(points) {
  const segs = [];
  let total = 0;
  for (let i = 1; i < points.length; i++) {
    const l = Math.hypot(points[i].x - points[i - 1].x, points[i].y - points[i - 1].y);
    segs.push(l);
    total += l;
  }
  return { segs, total };
}

export function pathLength(points) { return lengths(points).total; }

/** Point at fraction f (0..1) along a polyline, by length. */
export function pointAlong(points, f) {
  if (points.length === 1) return points[0];
  const { segs, total } = lengths(points);
  let d = Math.max(0, Math.min(1, f)) * total;
  for (let i = 0; i < segs.length; i++) {
    if (d <= segs[i] || i === segs.length - 1) {
      const k = segs[i] ? Math.min(1, d / segs[i]) : 0;
      return { x: points[i].x + (points[i + 1].x - points[i].x) * k, y: points[i].y + (points[i + 1].y - points[i].y) * k };
    }
    d -= segs[i];
  }
  return points[points.length - 1];
}

/** Draws the part of a polyline between fractions f0 and f1 as one solid stroke. */
export function drawPolyline(ctx, points, f1, rgbStr, alpha, width = 1.4, f0 = 0) {
  if (points.length < 2 || f1 <= f0 || alpha <= 0.004) return;
  const { segs, total } = lengths(points);
  const a = Math.max(0, f0) * total;
  const b = Math.min(1, f1) * total;
  ctx.strokeStyle = `rgba(${rgbStr},${alpha})`;
  ctx.lineWidth = width;
  ctx.lineCap = "round";
  ctx.lineJoin = "round";
  ctx.beginPath();
  let walked = 0;
  let started = false;
  for (let i = 0; i < segs.length; i++) {
    const s0 = walked;
    const s1 = walked + segs[i];
    walked = s1;
    if (s1 < a || s0 > b) continue;
    const p = points[i];
    const q = points[i + 1];
    const k0 = segs[i] ? Math.max(0, (a - s0) / segs[i]) : 0;
    const k1 = segs[i] ? Math.min(1, (b - s0) / segs[i]) : 1;
    const x0 = p.x + (q.x - p.x) * k0;
    const y0 = p.y + (q.y - p.y) * k0;
    if (!started) { ctx.moveTo(x0, y0); started = true; }
    ctx.lineTo(p.x + (q.x - p.x) * k1, p.y + (q.y - p.y) * k1);
  }
  ctx.stroke();
}

/** A bright node travelling along a path with a short fading tail of smaller nodes (no dashes). */
export function drawComet(ctx, points, f, color, size = 3.2) {
  for (let k = 4; k >= 1; k--) {
    const ff = f - k * 0.03;
    if (ff < 0) continue;
    const p = pointAlong(points, ff);
    drawNode(ctx, p.x, p.y, size * (1 - k * 0.15), color, 0.55 - k * 0.11, 0.5);
  }
  const head = pointAlong(points, f);
  drawNode(ctx, head.x, head.y, size, color, 1, 2.2);
  drawNode(ctx, head.x, head.y, size * 0.45, COLORS.white, 1, 0);
  return head;
}

/** Sample a cubic bezier into a polyline. */
export function bezier(p0, c1, c2, p1, n = 28) {
  const pts = [];
  for (let i = 0; i <= n; i++) {
    const t = i / n;
    const u = 1 - t;
    pts.push({
      x: u * u * u * p0.x + 3 * u * u * t * c1.x + 3 * u * t * t * c2.x + t * t * t * p1.x,
      y: u * u * u * p0.y + 3 * u * u * t * c1.y + 3 * u * t * t * c2.y + t * t * t * p1.y,
    });
  }
  return pts;
}

/** Deterministic random numbers, so layouts are stable between reloads. */
export function seeded(seed) {
  let a = seed >>> 0;
  return () => {
    a = (a + 0x6d2b79f5) >>> 0;
    let t = a;
    t = Math.imul(t ^ (t >>> 15), t | 1);
    t ^= t + Math.imul(t ^ (t >>> 7), t | 61);
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

export function pointerNear(p, pointer, radius = 120) {
  if (!pointer) return 0;
  const d = Math.hypot(p.x - pointer.x, p.y - pointer.y);
  return d < radius ? 1 - d / radius : 0;
}

/**
 * Runs draw(ctx, w, h, t, dt, pointer) on a DPR-aware canvas: resizes with its box, pauses
 * off-screen, tracks the pointer relative to the canvas, and under reduced motion draws still
 * frames only (call api.redraw() after data changes).
 */
export function canvasLoop(canvas, draw, { onResize } = {}) {
  const ctx = canvas.getContext("2d");
  const dpr = Math.min(window.devicePixelRatio || 1, 2);
  let w = 0;
  let h = 0;
  let raf = 0;
  let running = false;
  let visible = false;
  let last = performance.now();
  const client = { x: -9999, y: -9999, on: false };

  const resize = () => {
    const r = canvas.getBoundingClientRect();
    w = r.width;
    h = r.height;
    canvas.width = Math.max(1, Math.round(w * dpr));
    canvas.height = Math.max(1, Math.round(h * dpr));
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    if (onResize) onResize(w, h);
  };
  const pointer = () => {
    if (!client.on) return null;
    const r = canvas.getBoundingClientRect();
    const p = { x: client.x - r.left, y: client.y - r.top };
    return p.x < -40 || p.y < -40 || p.x > w + 40 || p.y > h + 40 ? null : p;
  };
  const frame = (t) => {
    const dt = Math.min(48, t - last);
    last = t;
    ctx.clearRect(0, 0, w, h);
    draw(ctx, w, h, t, dt, pointer());
  };
  const loop = (t) => {
    frame(t);
    if (running) raf = requestAnimationFrame(loop);
  };
  const start = () => {
    if (running || reduceMotion) return;
    running = true;
    last = performance.now();
    raf = requestAnimationFrame(loop);
  };
  const stop = () => { running = false; cancelAnimationFrame(raf); };

  resize();
  frame(performance.now());
  const io = new IntersectionObserver(([e]) => { visible = e.isIntersecting; visible ? start() : stop(); }, { rootMargin: "80px 0px" });
  io.observe(canvas);
  const ro = new ResizeObserver(() => { resize(); if (!running) frame(performance.now()); });
  ro.observe(canvas);
  window.addEventListener("pointermove", (e) => { client.x = e.clientX; client.y = e.clientY; client.on = e.pointerType !== "touch"; }, { passive: true });
  document.addEventListener("pointerleave", () => (client.on = false));

  return {
    redraw: () => frame(performance.now()),
    get visible() { return visible; },
    get size() { return { w, h }; },
    resize,
  };
}
