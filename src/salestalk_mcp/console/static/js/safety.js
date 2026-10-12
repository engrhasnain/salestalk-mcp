// "Try to break it": attack cards send real run_sql calls; the safety stack shows which layer
// refused each one (judged from the server's own error text) with a pulse travelling down a solid
// line and a red ripple on the layer that stopped it.

import { $, $$, h, icon, fmt, tween, sleep, reduceMotion, cleanError, refusalLayer, LAYER_NAMES, sqlHtml, callTool, toast } from "./util.js";

const ORDER = ["entry", "guard", "cap", "session", "prepared", "role", "timeout", "pg"];
const LAYER_FOR = { guard: "guard", role: "role", session: "session", prepared: "prepared", timeout: "timeout", range: "entry", connect: "session", pg: "pg" };

export const ATTACKS = [
  { id: "delete", title: "Delete every order", icon: "trash", sql: "DELETE FROM orders", expect: "expect: refused" },
  { id: "drop", title: "Drop the orders table", icon: "x", sql: "DROP TABLE orders", expect: "expect: refused" },
  { id: "stacked", title: "Smuggle a second statement", icon: "split", sql: "SELECT 1; DROP TABLE orders", expect: "expect: refused" },
  { id: "sleep", title: "Stall the database for 10 s", icon: "hourglass", sql: "SELECT pg_sleep(10)", expect: "expect: refused" },
  { id: "into", title: "Copy orders into a new table", icon: "copy", sql: "SELECT * INTO orders_copy FROM orders", expect: "expect: refused" },
  { id: "authid", title: "Read the password hashes", icon: "key", sql: "SELECT rolname, rolpassword FROM pg_authid", expect: "a valid SELECT: what stops it?" },
  { id: "dump", title: "Dump every order line", icon: "rows", sql: "SELECT * FROM order_items", expect: "a valid SELECT: what comes back?", cap: true },
];

export function createSafety({ attacksEl, stackEl, stats }) {
  const layers = Object.fromEntries($$(".layer", stackEl).map((li) => [li.dataset.layer, li]));
  const line = $(".stack-line", stackEl);
  const fill = $(".stack-fill", stackEl);
  const dot = $(".stack-head-dot", stackEl);
  const status = $("#stack-status");
  const verdict = $("#verdict");
  const vTitle = $("#verdict-title");
  const vText = $("#verdict-text");
  let geo = { top: 0, height: 1, ys: {} };
  let busy = false;
  let headY = 0;

  function measure() {
    const s = stackEl.getBoundingClientRect();
    const ys = {};
    let x = 0;
    for (const k of ORDER) {
      const node = $(".layer-node", layers[k]).getBoundingClientRect();
      ys[k] = node.top - s.top + node.height / 2;
      x = node.left - s.left + node.width / 2;
    }
    geo = { top: ys.entry, height: ys.pg - ys.entry, ys };
    line.style.top = `${geo.top}px`;
    line.style.height = `${geo.height}px`;
    line.style.left = `${x - 1}px`;
  }
  new ResizeObserver(measure).observe(stackEl);
  window.addEventListener("load", measure);

  function setHead(y) {
    headY = y;
    const p = Math.max(0, Math.min(1, (y - geo.top) / geo.height));
    fill.style.transform = `scaleY(${p})`;
    dot.style.transform = `translateY(${y - geo.top}px)`;
  }

  async function moveTo(layerKey, ms = 240) {
    const from = headY;
    const to = geo.ys[layerKey];
    const dist = Math.abs(to - from);
    await tween(Math.max(160, Math.min(ms * 2.2, dist * 3.2)), (p) => setHead(from + (to - from) * p));
  }

  function reset() {
    Object.values(layers).forEach((li) => li.classList.remove("is-pass", "is-refused", "is-warn", "is-skip"));
    line.classList.remove("is-refused");
    verdict.className = "verdict";
    measure();
    setHead(geo.top);
    dot.style.opacity = reduceMotion ? "0" : "1";
  }

  async function typeInto(el, text) {
    if (reduceMotion) { el.textContent = text; return; }
    el.textContent = "";
    const step = Math.max(1, Math.ceil(text.length / 60));
    for (let i = 0; i <= text.length; i += step) { el.textContent = text.slice(0, i); await sleep(12); }
    el.textContent = text;
  }

  /** Animate one run_sql outcome through the stack. */
  async function show(outcome) {
    reset();
    status.className = "chip chip-ink is-busy";
    status.textContent = "CHECKING";
    vTitle.textContent = `run_sql · ${fmt.ms(outcome.latency_ms)} ms round trip`;
    vText.textContent = "";
    layers.entry.classList.add("is-pass");
    let stop = null;
    let warnCap = false;
    if (!outcome.ok) stop = LAYER_FOR[refusalLayer(outcome)] || "pg";
    else if (outcome.result?.truncated) warnCap = true;

    const path = stop ? ORDER.slice(1, ORDER.indexOf(stop) + 1) : ORDER.slice(1);
    for (const k of path) {
      await moveTo(k);
      if (k === stop) {
        layers[k].classList.add("is-refused");
        line.classList.add("is-refused");
        break;
      }
      layers[k].classList.add("is-pass");
    }
    if (stop) {
      ORDER.slice(ORDER.indexOf(stop) + 1).forEach((k) => layers[k].classList.add("is-skip"));
      const layerName = LAYER_NAMES[refusalLayer(outcome)] || "server";
      status.className = "chip chip-ink is-refused";
      status.textContent = "REFUSED";
      verdict.classList.add("is-refused");
      vTitle.textContent = `Refused by the ${layerName} · ${fmt.ms(outcome.latency_ms)} ms`;
      await typeInto(vText, cleanError(outcome.error));
    } else if (warnCap) {
      await sleep(200);
      await moveTo("cap", 320);
      layers.cap.classList.remove("is-pass");
      layers.cap.classList.add("is-warn");
      status.className = "chip chip-ink is-warn";
      status.textContent = "CAPPED";
      verdict.classList.add("is-warn");
      const total = stats?.order_lines;
      vTitle.textContent = `Row cap · ${outcome.result.row_count} rows returned${total ? ` of ${fmt.int(total)}` : ""}`;
      await typeInto(vText, `truncated: true. The query ran read-only, and only the first ${outcome.result.row_limit} rows came back (the cap holds even if the query has its own huge LIMIT).`);
    } else {
      status.className = "chip chip-ink is-ok";
      status.textContent = "ALLOWED";
      verdict.classList.add("is-ok");
      vTitle.textContent = `Allowed · ${outcome.result?.row_count ?? 0} rows · ${fmt.ms(outcome.latency_ms)} ms`;
      await typeInto(vText, "A plain read-only SELECT: it passed every layer and ran inside a read-only transaction that was rolled back.");
    }
    dot.style.opacity = "0";
    return { stop, warnCap };
  }

  function attackCard(a) {
    const result = h("span", { class: "attack-result", text: a.expect });
    const run = h("button", { class: "attack-run", type: "button" }, icon("play"), h("span", { text: "Run it" }));
    let sqlEl;
    if (a.custom) {
      sqlEl = h("textarea", { "aria-label": "Your SQL", spellcheck: "false" });
      sqlEl.value = a.sql;
    } else {
      sqlEl = h("pre", { class: "attack-sql", html: sqlHtml(a.sql) });
    }
    const card = h("article", { class: `attack${a.cap ? " is-cap" : ""}${a.custom ? " is-custom" : ""}`, "data-reveal": "" },
      h("div", { class: "attack-top" }, h("span", { class: "attack-icon" }, icon(a.icon)), h("div", {}, h("h3", { text: a.title }), h("p", { class: "attack-expect", text: a.custom ? "any SQL you like" : "run_sql(query=…)" }))),
      sqlEl,
      h("div", { class: "attack-foot" }, result, run),
    );
    run.addEventListener("click", async () => {
      if (busy) return;
      const sql = a.custom ? sqlEl.value.trim() : a.sql;
      if (!sql) { toast("Type a query first."); return; }
      busy = true;
      run.disabled = true;
      card.classList.remove("is-done-refused", "is-done-cap", "is-done-ok");
      result.textContent = "calling run_sql over MCP…";
      if (window.innerWidth < 980) stackEl.scrollIntoView({ behavior: reduceMotion ? "auto" : "smooth", block: "start" });
      try {
        const outcome = await callTool("run_sql", { query: sql }, "break");
        const { stop, warnCap } = await show(outcome);
        result.replaceChildren(
          stop ? h("span", { class: "chip chip-refused", text: "REFUSED" }) : warnCap ? h("span", { class: "chip chip-warn", text: "CAPPED" }) : h("span", { class: "chip chip-ok", text: "ALLOWED" }),
          h("span", { text: stop ? LAYER_NAMES[refusalLayer(outcome)] : warnCap ? `${outcome.result.row_count} rows max` : `${outcome.result?.row_count ?? 0} rows` }),
        );
        card.classList.add(stop ? "is-done-refused" : warnCap ? "is-done-cap" : "is-done-ok");
      } catch (err) {
        result.textContent = err.message;
      } finally {
        busy = false;
        run.disabled = false;
      }
    });
    return card;
  }

  const custom = { id: "custom", title: "Write your own", icon: "pencil", sql: "SELECT segment, count(*) AS customers\n  FROM customers GROUP BY 1 ORDER BY 2 DESC", custom: true };
  attacksEl.replaceChildren(...ATTACKS.map(attackCard), attackCard(custom));
  reset();
  return { show, measure, setStats(s) { stats = s; } };
}
