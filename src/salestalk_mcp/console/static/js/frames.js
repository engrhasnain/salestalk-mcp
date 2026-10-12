// JSON-RPC frames panel: the exact messages written to the server's stdin (→) and read from its
// stdout (←), syntax coloured and streamed in line by line. Long strings are shortened for
// display only (marked "display only"), with a button to show the full frame.

import { h, icon, esc, fmt, reduceMotion, sleep } from "./util.js";

const LIMIT = 150;

function jsonHtml(value, indent, truncate) {
  const pad = "  ".repeat(indent);
  const pad1 = "  ".repeat(indent + 1);
  if (value === null) return `<span class="j-lit">null</span>`;
  if (typeof value === "boolean") return `<span class="j-lit">${value}</span>`;
  if (typeof value === "number") return `<span class="j-num">${value}</span>`;
  if (typeof value === "string") {
    let s = JSON.stringify(value);
    let more = "";
    if (truncate && s.length > LIMIT) {
      more = ` <span class="j-more">… +${fmt.int(s.length - LIMIT)} chars (display only)</span>`;
      s = `${s.slice(0, LIMIT)}"`;
    }
    return `<span class="j-str">${esc(s)}</span>${more}`;
  }
  if (Array.isArray(value)) {
    if (!value.length) return `<span class="j-punc">[]</span>`;
    const items = value.map((v) => pad1 + jsonHtml(v, indent + 1, truncate));
    return `<span class="j-punc">[</span>\n${items.join(`<span class="j-punc">,</span>\n`)}\n${pad}<span class="j-punc">]</span>`;
  }
  const keys = Object.keys(value);
  if (!keys.length) return `<span class="j-punc">{}</span>`;
  const items = keys.map((k) => `${pad1}<span class="j-key">${esc(JSON.stringify(k))}</span><span class="j-punc">: </span>${jsonHtml(value[k], indent + 1, truncate)}`);
  return `<span class="j-punc">{</span>\n${items.join(`<span class="j-punc">,</span>\n`)}\n${pad}<span class="j-punc">}</span>`;
}

function describe(frame) {
  const m = frame.message || {};
  if (frame.direction === "out") {
    if (m.method) return { what: `${m.method}${m.params?.name ? ` · ${m.params.name}` : ""}`, id: m.id, kind: "request" };
    return { what: "message", id: m.id, kind: "request" };
  }
  if (m.error) return { what: `error ${m.error.code}`, id: m.id, kind: "error" };
  if (m.result) return { what: m.result.isError ? "result · isError: true" : "result", id: m.id, kind: m.result.isError ? "error" : "result" };
  if (m.method) return { what: m.method, id: m.id, kind: "notification" };
  return { what: "message", id: m.id, kind: "result" };
}

async function streamLines(pre, html, perLine) {
  const lines = html.split("\n");
  pre.innerHTML = lines.map((l) => `<span class="line">${l || " "}</span>`).join("");
  const spans = [...pre.children];
  if (reduceMotion) { spans.forEach((s) => s.classList.add("in")); return; }
  const batch = Math.max(1, Math.ceil(spans.length / 40));
  for (let i = 0; i < spans.length; i += batch) {
    for (let j = i; j < Math.min(spans.length, i + batch); j++) spans[j].classList.add("in");
    await sleep(perLine);
  }
}

function frameCard(frame) {
  const info = describe(frame);
  const dirIn = frame.direction === "in";
  const pre = h("pre", { id: `f${Math.random().toString(36).slice(2, 9)}` });
  const toggle = h("button", { class: "frame-head", type: "button", "aria-expanded": "true", "aria-controls": pre.id },
    h("span", { class: "frame-dir", text: dirIn ? "← IN" : "→ OUT" }),
    h("span", { class: "frame-what", text: info.what }),
    h("span", { class: "frame-info", text: `${info.id !== undefined ? `id ${info.id} · ` : ""}${fmt.bytes(frame.bytes)} · +${frame.t_ms.toFixed(1)} ms` }),
    icon("chevron", "ic chev"),
  );
  toggle.addEventListener("click", () => {
    const open = toggle.getAttribute("aria-expanded") === "true";
    toggle.setAttribute("aria-expanded", String(!open));
    pre.hidden = open;
    full.hidden = open || !needsFull;
  });
  const needsFull = JSON.stringify(frame.message).length > 400 && /"[^"]{150,}"/.test(JSON.stringify(frame.message));
  const full = h("button", { class: "frame-full", type: "button", text: "Show the full frame", hidden: !needsFull });
  full.addEventListener("click", () => {
    const showingFull = full.dataset.full === "1";
    full.dataset.full = showingFull ? "0" : "1";
    full.textContent = showingFull ? "Show the full frame" : "Shorten long strings";
    pre.innerHTML = jsonHtml(frame.message, 0, showingFull).split("\n").map((l) => `<span class="line in">${l || " "}</span>`).join("");
  });
  const card = h("div", { class: `frame ${dirIn ? "in-dir" : "out"}${info.kind === "error" ? " is-error" : ""}` }, toggle, pre, full);
  return { card, pre, html: jsonHtml(frame.message, 0, true) };
}

/** Render the frames of one call into the panel, streaming them in order. */
export async function renderFrames(body, frames, { onFrame } = {}) {
  body.replaceChildren();
  if (!frames || !frames.length) {
    body.append(h("p", { class: "frames-empty mono", text: "No frames were captured for this call." }));
    return;
  }
  for (const frame of frames) {
    const { card, pre, html } = frameCard(frame);
    body.append(card);
    requestAnimationFrame(() => card.classList.add("in"));
    if (onFrame) onFrame(frame);
    await streamLines(pre, html, frame.direction === "out" ? 14 : 10);
    await sleep(120);
  }
}
