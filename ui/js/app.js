import { $, S, api, emit, h, hm, led, pad2, toast, watch } from "./core.js";
import { KIOSK } from "./osk.js";
import home from "./screens/home.js";
import study from "./screens/study.js";
import brain from "./screens/brain.js";
import ask from "./screens/ask.js";
import network from "./screens/network.js";
import devices from "./screens/devices.js";
import music from "./screens/music.js";
import desk from "./screens/desk.js";
import system from "./screens/system.js";

const PAGES = [home, study, brain, ask, network, devices, music, desk, system];
const pageEl = $("#page"), keysEl = $("#keys"), railEl = $("#rail"), stripEl = $("#strip"), board = $("#board");
let current = null;
let lastTouch = Date.now();

// ---------------------------------------------------------------- navigation
export function go(id, opts) {
  const p = PAGES.find((x) => x.id === id) || home;
  if (current && current.unmount) current.unmount();
  current = p;
  pageEl.replaceChildren(); keysEl.replaceChildren();
  delete keysEl._sig; delete keysEl._tab;
  p.mount(pageEl, keysEl, opts || {});
  p.update && p.update(S.state, new Set(["*", ...Object.keys(S.state)]));
  for (const b of railEl.children) {
    if (b.dataset.id === id) b.setAttribute("aria-current", "page"); else b.removeAttribute("aria-current");
  }
  paintStrip();
  if (!KIOSK) history.replaceState(null, "", `#${id}`);
}
window.desk = { go };

function buildRail() {
  railEl.replaceChildren(...PAGES.map((p) => h("button.rk", { "data-id": p.id, onclick: () => go(p.id) }, p.label, h("i.led", { "data-led": p.id }))));
}
function railLeds() {
  const st = S.state;
  const set = (id, cls) => { const e = railEl.querySelector(`[data-led="${id}"]`); if (e) e.className = `led ${cls}`; };
  const b = st.brain?.state;
  set("brain", b === "online" ? "ok" : b === "degraded" ? "warn" : b === "unreachable" ? "fault" : "");
  set("study", st.timer ? (st.timer.paused ? "warn" : "ok blink") : "");
  set("music", st.music?.state === "playing" ? "ok" : "");
  const devs = Object.values(st.devices || {});
  set("devices", devs.some((d) => !d.stale && d.battery != null && d.battery <= 20 && !d.charging) ? "warn" : "");
  set("network", st.dpn?.on ? "ok" : st.adguard?.focus ? "warn" : "");
  set("system", st.pi?.panic ? "fault blink" : (st.pi?.temp || 0) > 75 ? "warn" : "");
  for (const e of railEl.querySelectorAll(".led")) e.style.visibility = e.className.trim() === "led" ? "hidden" : "visible";
}

// ---------------------------------------------------------------- status strip
function paintStrip() {
  const st = S.state, now = new Date();
  const items = [h("span.page-id", h("span.des", current?.des || ""), current?.title || current?.label || "")];
  items.push(h("span.grow"));
  if (st.timer) items.push(h("span.si", led(st.timer.paused ? "warn" : "ok"), `${st.timer.subject} ${hm(st.timer.remaining ?? st.timer.elapsed)}`));
  if (st.brain && st.brain.state !== "unconfigured") items.push(h("span.si", led({ online: "ok", degraded: "warn", unreachable: "fault" }[st.brain.state]), "Brain"));
  const mac = st.devices?.mac;
  if (mac && !mac.stale && mac.battery != null) items.push(h("span.si.opt", `Mac ${mac.battery}%${mac.charging ? " charging" : ""}`));
  if (st.pi && st.pi.temp > 0) items.push(h("span.si.opt", { class: st.pi.temp > 75 ? "warn-t" : "" }, `Pi ${Math.round(st.pi.temp)}°`));
  items.push(h("span.si.clock", `${pad2(now.getHours())}:${pad2(now.getMinutes())}`));
  stripEl.replaceChildren(...items);
}

// ---------------------------------------------------------------- theme
function applyTheme() {
  const m = S.state.meta || {};
  let t = m.theme || "auto";
  if (t === "auto") { const hr = new Date().getHours(); t = hr >= (m.night_from ?? 19) || hr < (m.day_from ?? 7) ? "night" : "day"; }
  if (localStorage.getItem("md-theme")) t = localStorage.getItem("md-theme");
  document.documentElement.dataset.theme = t === "night" ? "night" : "";
}

// ---------------------------------------------------------------- standby (Pi only)
let standbyTimer;
function standby(asleep) {
  const el = $("#standby");
  if (!KIOSK) return;
  el.hidden = !asleep;
  clearInterval(standbyTimer);
  if (!asleep) return;
  const t = el.firstElementChild;
  const move = () => {
    const d = new Date(); t.textContent = `${pad2(d.getHours())}:${pad2(d.getMinutes())}`;
    t.style.left = `${40 + Math.random() * (innerWidth - 220)}px`; t.style.top = `${30 + Math.random() * (innerHeight - 100)}px`;
  };
  move(); standbyTimer = setInterval(move, 8000);
}
$("#standby").addEventListener("pointerdown", () => api("/api/display/wake", {}).catch(() => {}));

// ---------------------------------------------------------------- OTA overlay
function ota(o) {
  let el = $(".ota");
  if (!o) { el && el.remove(); return; }
  if (!el) { el = h("div.ota"); document.body.append(el); }
  const b = h("div.bar", h("i")); b.firstChild.style.width = `${o.pct}%`;
  el.replaceChildren(h("div.wordmark", "MATTERDESK"), h("div", o.error ? h("span.fault-t", o.label) : o.label), b,
    o.error ? h("div.dim.small", { style: { maxWidth: "50ch", textAlign: "center" } }, o.error) : null,
    o.error ? h("button.pad.ghost", { onclick: () => el.remove() }, "Back to desk") : null);
}

// ---------------------------------------------------------------- live connection
let ws, retry = 0, offlineTimer;
function connect() {
  ws = new WebSocket(`${location.protocol === "https:" ? "wss" : "ws"}://${location.host}/ws`);
  ws.onmessage = (ev) => {
    const m = JSON.parse(ev.data);
    if (m.snapshot) {
      S.state = m.snapshot; S.logs = m.logs || []; S.connected = true; retry = 0;
      clearTimeout(offlineTimer); $(".offline-banner")?.remove();
      applyTheme(); standby(S.state.display?.asleep);
      if (!current) go((!KIOSK && location.hash.slice(1)) || "home"); else go(current.id);
      railLeds(); bootDone();
      return;
    }
    if (m.t) {
      S.state[m.t] = m.d;
      if (m.t === "display") standby(m.d?.asleep);
      if (m.t === "ota") ota(m.d);
      if (m.t === "meta") applyTheme();
      if (["brain", "timer", "devices", "pi", "music", "dpn", "adguard"].includes(m.t)) { railLeds(); paintStrip(); }
      if (current?.topics?.includes(m.t) || current?.topics?.includes("*")) current.update(S.state, new Set([m.t]));
      emit(new Set([m.t]));
    } else if (m.e === "toast") toast(m.d.text, m.d.level);
    else if (m.e === "log") { S.logs.unshift(m.d); S.logs.length = Math.min(S.logs.length, 300); emit(new Set(["logs"])); }
  };
  ws.onclose = (ev) => {
    S.connected = false;
    if (ev.code === 4401) { document.body.replaceChildren(h("div.empty", { style: { padding: "40px" } }, "Open the desk with ?key=… once on this device.")); return; }
    offlineTimer = setTimeout(() => { if (!S.connected && !$(".offline-banner")) document.body.append(h("div.offline-banner", "Desk service is restarting. Reconnecting.")); }, 2500);
    setTimeout(connect, Math.min(8000, 500 * 2 ** retry++));
  };
}

// any touch keeps the screen awake (throttled)
let lastPing = 0;
document.addEventListener("pointerdown", () => {
  lastTouch = Date.now();
  closeFocusView();
  if (Date.now() - lastPing > 4000 && ws?.readyState === 1) { ws.send("activity"); lastPing = Date.now(); }
}, { capture: true });

// ---------------------------------------------------------------- focus view during a sprint
let focusEl = null, focusUnwatch = null;
function closeFocusView() { if (focusEl) { focusEl.remove(); focusEl = null; focusUnwatch && focusUnwatch(); } }
function openFocusView() {
  const inner = h("div.inner"); focusEl = h("div.focusview", inner); document.body.append(focusEl);
  let n = 0;
  const paint = () => {
    const t = S.state.timer; if (!t) return closeFocusView();
    inner.replaceChildren(h("div.t", hm(t.remaining ?? t.elapsed)), h("div.s", t.lockin ? h("span.lk", "Lock-in  ") : "", t.subject, t.paused ? "  paused" : ""));
    if (n++ % 20 === 0) inner.style.transform = `translate(${(Math.random() - .5) * 220}px, ${(Math.random() - .5) * 120}px)`;
  };
  paint(); focusUnwatch = watch(["timer"], paint);
}
setInterval(() => {
  if (KIOSK && !focusEl && S.state.timer && !S.state.timer.paused && current?.id === "study" && Date.now() - lastTouch > 15000 && !$("#layer").children.length) openFocusView();
}, 1000);

// ---------------------------------------------------------------- boot
let booted = false;
function bootDone() {
  if (booted) return; booted = true;
  const mark = $(".bootmark");
  setTimeout(() => {
    mark && (mark.style.opacity = "0");
    board.classList.remove("booting"); board.classList.add("boot");
    setTimeout(() => mark && mark.remove(), 320);
  }, KIOSK ? 700 : 150);
}
document.body.append(h("div.bootmark", h("div.wordmark", "MATTERDESK"), h("div.credit", "a parthchhabra production")));

buildRail();
setInterval(() => { paintStrip(); applyTheme(); }, 15000);
connect();
