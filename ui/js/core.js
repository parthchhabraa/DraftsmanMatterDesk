// Small runtime shared by every page: DOM helper, live state, API calls, overlays.

export function h(tag, attrs, ...kids) {
  const [name, ...cls] = tag.split(".");
  const el = document.createElement(name || "div");
  if (cls.length) el.className = cls.join(" ");
  if (attrs && (typeof attrs !== "object" || attrs instanceof Node || Array.isArray(attrs))) { kids.unshift(attrs); attrs = null; }
  for (const [k, v] of Object.entries(attrs || {})) {
    if (v == null || v === false) continue;
    if (k.startsWith("on")) el.addEventListener(k.slice(2), v);
    else if (k === "class") el.className += (el.className ? " " : "") + v;
    else if (k === "style" && typeof v === "object") Object.assign(el.style, v);
    else if (k === "html") el.innerHTML = v;
    else el.setAttribute(k, v === true ? "" : v);
  }
  for (const k of kids.flat(Infinity)) if (k != null && k !== false) el.append(k instanceof Node ? k : String(k));
  return el;
}

export const $ = (sel, root = document) => root.querySelector(sel);

// Conditional children are written as `cond ? node : null` everywhere; the DOM would print "null".
for (const m of ["replaceChildren", "append"]) {
  const orig = Element.prototype[m];
  Element.prototype[m] = function (...nodes) { return orig.apply(this, nodes.filter((n) => n != null && n !== false)); };
}

// ---------------------------------------------------------------- live state
export const S = { state: {}, logs: [], connected: false };
const subs = new Set();
export function watch(topics, fn) { const s = { topics: new Set(topics), fn }; subs.add(s); return () => subs.delete(s); }
export function emit(changed) { for (const s of subs) if ([...changed].some((t) => s.topics.has(t) || s.topics.has("*"))) s.fn(S.state, changed); }

// ---------------------------------------------------------------- api
export async function api(path, body, method) {
  const opt = { method: method || (body === undefined ? "GET" : "POST"), headers: {} };
  if (body instanceof FormData) opt.body = body;
  else if (body !== undefined) { opt.body = JSON.stringify(body); opt.headers["content-type"] = "application/json"; }
  const r = await fetch(path, opt);
  const isJson = (r.headers.get("content-type") || "").includes("json");
  const data = isJson ? await r.json() : await r.text();
  if (!r.ok) throw new Error((data && data.error) || `Request failed (${r.status})`);
  return data;
}
// Run an action from a pad: disable it while it runs, toast the error.
export async function act(btn, fn, okText) {
  if (btn) btn.disabled = true;
  try { const out = await fn(); if (okText) toast(okText, "good"); return out; }
  catch (e) { toast(e.message, "danger"); }
  finally { if (btn) btn.disabled = false; }
}

// ---------------------------------------------------------------- formatting
export const pad2 = (n) => String(n).padStart(2, "0");
export const use12 = () => { try { return localStorage.getItem("md-clock") !== "24"; } catch { return true; } };
// {hm: "3:25", ap: "pm"} or {hm: "15:25", ap: ""}
export function clock(d = new Date()) {
  const H = d.getHours(), M = pad2(d.getMinutes());
  if (!use12()) return { hm: `${pad2(H)}:${M}`, ap: "" };
  return { hm: `${H % 12 || 12}:${M}`, ap: H < 12 ? "am" : "pm" };
}
export const clockText = (d) => { const c = clock(d); return c.ap ? `${c.hm} ${c.ap}` : c.hm; };
// "17:41" or "17:41:05" from the server -> "5:41 pm"
export function hhmm(s) {
  if (!s || !use12()) return s || "";
  const [H, M, S] = s.split(":").map(Number);
  return `${H % 12 || 12}:${pad2(M)}${S != null && !isNaN(S) ? ":" + pad2(S) : ""} ${H < 12 ? "am" : "pm"}`;
}
export function hm(sec) { sec = Math.max(0, Math.round(sec)); const h = Math.floor(sec / 3600), m = Math.floor(sec % 3600 / 60), s = sec % 60; return h ? `${h}:${pad2(m)}:${pad2(s)}` : `${pad2(m)}:${pad2(s)}`; }
export function mins(m) { m = Math.round(m || 0); return m >= 60 ? `${Math.floor(m / 60)}h ${pad2(m % 60)}m` : `${m}m`; }
export function ago(s) { if (s == null) return "never"; if (s < 90) return "just now"; if (s < 3600) return `${Math.round(s / 60)} min ago`; if (s < 86400) return `${Math.round(s / 3600)} h ago`; return `${Math.round(s / 86400)} d ago`; }
export function uptime(s) { s = s || 0; const d = Math.floor(s / 86400), h = Math.floor(s % 86400 / 3600); return d ? `${d}d ${h}h` : `${h}h ${Math.floor(s % 3600 / 60)}m`; }
export function bytes(n) { n = n || 0; for (const u of ["B", "KB", "MB", "GB", "TB"]) { if (n < 1024) return `${n < 10 && u !== "B" ? n.toFixed(1) : Math.round(n)} ${u}`; n /= 1024; } return `${Math.round(n)} PB`; }
export const level = (v, warn, bad) => (v >= bad ? "fault" : v >= warn ? "warn" : "ok");

export function led(state, extra = "") { return h("i.led", { class: `${state || ""} ${extra}`.trim(), "aria-hidden": "true" }); }
export function bar(pct, cls = "") { const b = h("div.bar", { class: cls }, h("i")); b.firstChild.style.width = `${Math.max(0, Math.min(100, pct || 0))}%`; return b; }
export function sk(kind = "line", w) { const e = h("div.sk", { class: kind }); if (w) e.style.width = w; return e; }
export function skLines(n = 3) { return Array.from({ length: n }, (_, i) => sk("line", `${90 - i * 17}%`)); }

export function spark(series, { w = 300, hgt = 48, colors = ["var(--copper)"] } = {}) {
  const ns = "http://www.w3.org/2000/svg";
  const svg = document.createElementNS(ns, "svg");
  svg.setAttribute("viewBox", `0 0 ${w} ${hgt}`); svg.setAttribute("preserveAspectRatio", "none"); svg.classList.add("spark");
  const max = Math.max(1, ...series.flat());
  series.forEach((s, i) => {
    if (!s.length) return;
    const step = w / Math.max(1, s.length - 1);
    const d = s.map((v, j) => `${j ? "L" : "M"}${(j * step).toFixed(1)},${(hgt - 2 - (v / max) * (hgt - 4)).toFixed(1)}`).join("");
    const p = document.createElementNS(ns, "path"); p.setAttribute("d", d); p.style.stroke = colors[i % colors.length];
    svg.append(p);
  });
  return svg;
}

const GLYPHS = {
  play: "M5 3l13 7-13 7z", pause: "M4 3h4v14H4zM12 3h4v14h-4z", next: "M3 3l10 7-10 7zM14 3h3v14h-3z",
  prev: "M17 3L7 10l10 7zM3 3h3v14H3z", mic: "M10 2a3 3 0 0 1 3 3v5a3 3 0 0 1-6 0V5a3 3 0 0 1 3-3zM5 9h2a3 3 0 0 0 6 0h2a5 5 0 0 1-4 4.9V17h3v2H6v-2h3v-3.1A5 5 0 0 1 5 9z",
  stop: "M4 4h12v12H4z", send: "M2 3l16 7-16 7 2-7z",
};
export function glyph(name) {
  const ns = "http://www.w3.org/2000/svg";
  const svg = document.createElementNS(ns, "svg"); svg.setAttribute("viewBox", "0 0 20 20"); svg.classList.add("glyph"); svg.setAttribute("aria-hidden", "true");
  const p = document.createElementNS(ns, "path"); p.setAttribute("d", GLYPHS[name]); svg.append(p); return svg;
}

// ---------------------------------------------------------------- sound
// Short synthesised tones, no audio files. Off switch lives in System.
let actx;
export const soundOn = () => { try { return localStorage.getItem("md-sound") !== "off"; } catch { return true; } };
const TONES = {
  chime: [[660, 0, 0.18], [880, 0.16, 0.32]],
  done: [[523, 0, 0.16], [659, 0.15, 0.16], [784, 0.3, 0.45]],
  alarm: [[880, 0, 0.13], [880, 0.2, 0.13], [880, 0.4, 0.13], [1175, 0.6, 0.32]],
};
export function sound(kind = "chime") {
  if (!soundOn()) return;
  try {
    actx = actx || new (window.AudioContext || window.webkitAudioContext)();
    if (actx.state === "suspended") actx.resume();
    const t0 = actx.currentTime + 0.02;
    for (const [freq, at, len] of TONES[kind] || TONES.chime) {
      const o = actx.createOscillator(), g = actx.createGain();
      o.type = "triangle"; o.frequency.value = freq;
      g.gain.setValueAtTime(0.0001, t0 + at);
      g.gain.exponentialRampToValueAtTime(0.28, t0 + at + 0.015);
      g.gain.exponentialRampToValueAtTime(0.0001, t0 + at + len);
      o.connect(g).connect(actx.destination); o.start(t0 + at); o.stop(t0 + at + len + 0.02);
    }
  } catch { /* no audio device: the screen still shows it */ }
}

// ---------------------------------------------------------------- overlays
const layer = () => document.getElementById("layer");

export function toast(text, levelName = "info") {
  const map = { good: "ok", warn: "warn", danger: "fault", info: "" };
  const t = h("div.toast", led(map[levelName] ?? ""), h("span", text));
  document.getElementById("toasts").append(t);
  setTimeout(() => t.remove(), levelName === "danger" ? 6000 : 3500);
}

export function sheet(title, body, { actions = [], onClose } = {}) {
  const close = () => { bg.remove(); onClose && onClose(); };
  const head = h("div.title", h("div.h", title), ...actions, h("button.pad.ghost.small", { onclick: close }, "Close"));
  const bg = h("div.sheet-bg", { onclick: (e) => e.target === bg && close() }, h("div.sheet", head, body));
  layer().append(bg);
  return close;
}

export function confirmBox(question, yesLabel, { danger = false } = {}) {
  return new Promise((res) => {
    const done = (v) => { bg.remove(); res(v); };
    const bg = h("div.sheet-bg.dialog-bg", h("div.sheet.dialog",
      h("div.h", question),
      h("div.row", h("button.pad.ghost.grow", { onclick: () => done(false) }, "Cancel"),
        h(`button.pad.grow${danger ? ".danger" : ""}`, { onclick: () => done(true) }, yesLabel))));
    layer().append(bg);
  });
}

export function pick(title, options, current) {
  return new Promise((res) => {
    // Resolve BEFORE closing: closing fires onClose, which would settle the promise with null first.
    const close = sheet(title, h("div.picks", options.map((o) => {
      const [value, label] = Array.isArray(o) ? o : [o, o];
      return h(`button.pad${value === current ? "" : ".ghost"}`, { onclick: () => { res(value); close(); } }, label);
    })), { onClose: () => res(null) });
  });
}

// Re-render a region only when its inputs changed. A node swapped out between
// touch-down and touch-up loses the tap, so hot regions must stay put.
export function put(el, sig, build) {
  const s = typeof sig === "string" ? sig : JSON.stringify(sig);
  if (el._sig === s) return false;
  el._sig = s;
  const out = build();
  el.replaceChildren(...(Array.isArray(out) ? out : [out]).filter((x) => x != null));
  return true;
}
