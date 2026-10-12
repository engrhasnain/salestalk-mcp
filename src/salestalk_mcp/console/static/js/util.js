// Small shared helpers: DOM, formatting, motion (all motion respects prefers-reduced-motion).

export const reduceMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;

export const $ = (sel, root = document) => root.querySelector(sel);
export const $$ = (sel, root = document) => [...root.querySelectorAll(sel)];

/** Tiny element builder: h("div", {class: "x", text: "hi"}, child, ...). */
export function h(tag, attrs = {}, ...children) {
  const node = document.createElement(tag);
  for (const [key, value] of Object.entries(attrs)) {
    if (value === null || value === undefined || value === false) continue;
    if (key === "class") node.className = value;
    else if (key === "text") node.textContent = value;
    else if (key === "html") node.innerHTML = value;
    else if (key === "style" && typeof value === "object") {
      for (const [prop, v] of Object.entries(value)) {
        if (prop.startsWith("--")) node.style.setProperty(prop, v);
        else node.style[prop] = v;
      }
    }
    else if (key.startsWith("on") && typeof value === "function") node.addEventListener(key.slice(2), value);
    else if (key === "data" && typeof value === "object") Object.entries(value).forEach(([k, v]) => (node.dataset[k] = v));
    else node.setAttribute(key, value === true ? "" : value);
  }
  for (const child of children.flat()) {
    if (child === null || child === undefined || child === false) continue;
    node.append(child instanceof Node ? child : document.createTextNode(String(child)));
  }
  return node;
}

export function icon(name, cls = "ic") {
  const ns = "http://www.w3.org/2000/svg";
  const svg = document.createElementNS(ns, "svg");
  svg.setAttribute("class", cls);
  svg.setAttribute("aria-hidden", "true");
  const use = document.createElementNS(ns, "use");
  use.setAttribute("href", `#i-${name}`);
  svg.append(use);
  return svg;
}

export const esc = (s) => String(s).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]);

export const sleep = (ms) => new Promise((r) => setTimeout(r, reduceMotion ? 0 : ms));
export const clamp = (v, a, b) => Math.max(a, Math.min(b, v));
export const expoOut = (t) => (t >= 1 ? 1 : 1 - Math.pow(2, -10 * t));
export const cubicOut = (t) => 1 - Math.pow(1 - clamp(t, 0, 1), 3);

/** rAF tween; resolves when done. fn(progress 0..1 eased). */
export function tween(duration, fn, ease = expoOut) {
  return new Promise((resolve) => {
    if (reduceMotion || duration <= 0) { fn(1); resolve(); return; }
    const start = performance.now();
    const step = (now) => {
      const t = clamp((now - start) / duration, 0, 1);
      fn(ease(t));
      if (t < 1) requestAnimationFrame(step); else resolve();
    };
    requestAnimationFrame(step);
  });
}

export function countUp(el, to, { duration = 1300, format = fmt.int, from = 0 } = {}) {
  if (to === null || to === undefined || Number.isNaN(Number(to))) { el.textContent = "–"; return Promise.resolve(); }
  return tween(duration, (p) => { el.textContent = format(from + (to - from) * p, p >= 1); });
}

export const fmt = {
  int: (n) => Math.round(n).toLocaleString("en-US"),
  aed: (n) => `AED ${Math.round(n).toLocaleString("en-US")}`,
  compact(n) {
    const a = Math.abs(n);
    if (a >= 1e6) return `${(n / 1e6).toFixed(2)}M`;
    if (a >= 1e4) return `${(n / 1e3).toFixed(0)}K`;
    if (a >= 1e3) return `${(n / 1e3).toFixed(1)}K`;
    return `${Math.round(n)}`;
  },
  aedCompact: (n) => `AED ${fmt.compact(n)}`,
  ms: (n) => (n < 10 ? n.toFixed(1) : Math.round(n).toLocaleString("en-US")),
  bytes: (n) => (n >= 1024 ? `${(n / 1024).toFixed(1)} KB` : `${n} B`),
  pct: (n) => (n === null || n === undefined ? "n/a" : `${n > 0 ? "+" : ""}${n.toFixed(1)}%`),
  time(iso) {
    const d = iso ? new Date(iso) : new Date();
    const p = (v, l = 2) => String(v).padStart(l, "0");
    return `${p(d.getHours())}:${p(d.getMinutes())}:${p(d.getSeconds())}.${p(d.getMilliseconds(), 3)}`;
  },
};

export function monthName(ym, short = false) {
  if (!ym || !/^\d{4}-\d{2}/.test(ym)) return ym || "";
  const [y, m] = ym.split("-").map(Number);
  return new Date(y, m - 1, 1).toLocaleString("en-US", { month: short ? "short" : "long", year: short ? "2-digit" : "numeric" });
}

/** month="last_month", limit=5 (strings quoted, like the README and the demo GIF). */
export function argsInline(args, maxLen = 0) {
  const parts = Object.entries(args || {}).map(([k, v]) => {
    let s = typeof v === "string" ? JSON.stringify(v.replace(/\s+/g, " ").trim()) : JSON.stringify(v);
    if (maxLen && s.length > maxLen) s = `${s.slice(0, maxLen - 2)}…"`;
    return `${k}=${s}`;
  });
  return parts.join(", ");
}

export const cleanError = (text) => String(text || "").replace(/^Error executing tool [\w-]+:\s*/, "").trim();

/** Which safety layer produced an error, judged only from the server's own error text. */
export function refusalLayer(outcome) {
  const err = cleanError(outcome.error || "");
  if (/Only SELECT|Only a single statement|forbidden keyword|Row-locking|is not allowed in read-only|Empty query|too long|NUL byte|Unterminated/i.test(err)) return "guard";
  if (/read-only role|permission denied/i.test(err)) return "role";
  if (/connection is read-only|read-only transaction/i.test(err)) return "session";
  if (/multiple commands|prepared statement/i.test(err)) return "prepared";
  if (/statement timeout|Query cancelled/i.test(err)) return "timeout";
  if (/Unknown range|Unknown month|range|granularity|sort_by|Unknown city|Unknown category|validation error|Input should/i.test(err)) return "range";
  if (/Cannot connect/i.test(err)) return "connect";
  return "pg";
}

export const LAYER_NAMES = {
  guard: "SQL guard",
  role: "read-only role",
  session: "read-only transaction",
  prepared: "one-statement rule",
  timeout: "statement timeout",
  range: "input validation",
  connect: "database connection",
  pg: "PostgreSQL",
};

/** Highlight SQL keywords and strings for display. */
export function sqlHtml(sql, kwClass = "kw") {
  const kw = /\b(SELECT|FROM|WHERE|JOIN|LEFT|ON|AND|OR|NOT|IN|GROUP|BY|ORDER|HAVING|AS|LIMIT|DELETE|DROP|TABLE|INTO|INSERT|UPDATE|WITH|COUNT|SUM|MAX|MIN|ROUND|COALESCE|CURRENT_DATE|DESC|ASC|USING|DISTINCT|CASE|WHEN|THEN|ELSE|END)\b/gi;
  return esc(sql)
    .replace(/'([^']*)'/g, `<span class="str">'$1'</span>`)
    .replace(kw, (m) => `<span class="${kwClass}">${m}</span>`);
}

// ------------------------------------------------------------------ event bus + API

const bus = new EventTarget();
export const emit = (name, detail) => bus.dispatchEvent(new CustomEvent(name, { detail }));
export const on = (name, fn) => bus.addEventListener(name, (e) => fn(e.detail));

export async function api(path, options = {}) {
  const res = await fetch(path, { headers: { "Content-Type": "application/json" }, ...options });
  let body = null;
  try { body = await res.json(); } catch { /* not JSON */ }
  if (!res.ok) {
    const err = new Error((body && body.error) || `${res.status} ${res.statusText}`);
    err.status = res.status;
    err.body = body;
    throw err;
  }
  return body;
}

/** POST /api/call and broadcast the outcome so every visual on the page can replay it. */
export async function callTool(name, args, origin = "page") {
  const outcome = await api("/api/call", { method: "POST", body: JSON.stringify({ name, arguments: args }) });
  emit("call", { outcome, origin });
  return outcome;
}

// ------------------------------------------------------------------ visibility helpers

/** Calls onChange(true/false) as the element enters/leaves the viewport (with a margin). */
export function watchVisible(el, onChange, margin = "120px 0px") {
  const io = new IntersectionObserver(([e]) => onChange(e.isIntersecting), { rootMargin: margin });
  io.observe(el);
  return () => io.disconnect();
}

/** Staggered entrance for [data-reveal] elements (call again for elements added later). */
let revealIO = null;
export function setupReveal(root = document) {
  const items = $$("[data-reveal]:not(.is-in)", root);
  if (reduceMotion) { items.forEach((el) => el.classList.add("is-in")); return; }
  if (!revealIO) {
    revealIO = new IntersectionObserver((entries) => {
      for (const e of entries) {
        if (e.isIntersecting) { e.target.classList.add("is-in"); revealIO.unobserve(e.target); }
      }
    }, { rootMargin: "0px 0px -6% 0px", threshold: 0.01 });
  }
  items.forEach((el) => revealIO.observe(el));
}

/** Pause CSS loops in sections that are off-screen. */
export function setupLoopPausing() {
  $$("[data-loop]").forEach((section) => watchVisible(section, (v) => section.classList.toggle("is-offscreen", !v), "60px 0px"));
}

export function toast(message, ms = 3800) {
  const t = $("#toast");
  t.textContent = message;
  t.hidden = false;
  clearTimeout(toast._t);
  toast._t = setTimeout(() => (t.hidden = true), ms);
}
