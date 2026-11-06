// Home: the day as a dial. Noon at the top, midnight at the bottom.
// Outer band = daylight, copper arcs = study today, inner ring = daily goal, hand = now.
import { act, api, clock, glyph, h, hhmm, mins, put, sk, use12 } from "../core.js";

const go = (id, o) => window.desk.go(id, o);
const NS = "http://www.w3.org/2000/svg";
const DAYS = ["Sunday", "Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday"];
const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
const cpuHist = [];   // brain CPU, kept across page visits
let els, tick, firstDraw = true, last = {};

// ---------------------------------------------------------------- svg helpers
function s(tag, attrs = {}, ...kids) {
  const e = document.createElementNS(NS, tag);
  for (const [k, v] of Object.entries(attrs)) if (v != null) e.setAttribute(k, v);
  for (const k of kids) if (k != null) e.append(k);
  return e;
}
const C = 150;
// fraction of the day (0 = midnight) -> point; noon sits at the top
function pt(frac, r) { const a = (frac * 2 - 1) * Math.PI; return [C + r * Math.sin(a), C - r * Math.cos(a)]; }
function arc(f0, f1, r) {
  if (f1 - f0 >= 0.999) f1 = f0 + 0.999;
  const [x0, y0] = pt(f0, r), [x1, y1] = pt(f1, r);
  return `M${x0.toFixed(2)},${y0.toFixed(2)} A${r},${r} 0 ${f1 - f0 > 0.5 ? 1 : 0} 1 ${x1.toFixed(2)},${y1.toFixed(2)}`;
}
const dayFrac = (d) => (d.getHours() * 3600 + d.getMinutes() * 60 + d.getSeconds()) / 86400;
const fracOf = (hhmmStr) => { const [H, M] = (hhmmStr || "0:0").split(":").map(Number); return (H * 60 + M) / 1440; };
const epochFrac = (t) => dayFrac(new Date(t * 1000));

// ---------------------------------------------------------------- the dial
function dial(st) {
  const now = new Date(), nf = dayFrac(now);
  const w = st.weather, sd = st.study, t = st.timer;
  const svg = s("svg", { viewBox: "0 0 300 300", class: `dial${firstDraw ? " draw" : ""}`, role: "img",
    "aria-label": `Day dial. ${sd ? mins(sd.today_min) + " studied today." : ""}` });

  // day/night band
  svg.append(s("circle", { cx: C, cy: C, r: 142, class: "night" }));
  if (w?.sunrise) svg.append(s("path", { d: arc(fracOf(w.sunrise), fracOf(w.sunset), 142), class: "daylight" }));

  // hour ticks; labels at the four quarters
  for (let hr = 0; hr < 24; hr++) {
    if (hr % 6 === 0) continue;
    const [x0, y0] = pt(hr / 24, 128), [x1, y1] = pt(hr / 24, hr % 3 ? 133 : 135);
    svg.append(s("line", { x1: x0, y1: y0, x2: x1, y2: y1, class: "tick" }));
  }
  const lab = use12() ? ["12a", "6a", "noon", "6p"] : ["00", "06", "12", "18"];
  [0, 6, 12, 18].forEach((hr, i) => {
    const [x, y] = pt(hr / 24, 129);
    svg.append(s("text", { x, y: y + 3.5, class: "hl", "text-anchor": "middle" }, lab[i]));
  });

  // study track, today's sessions, the running sprint
  svg.append(s("circle", { cx: C, cy: C, r: 116, class: "track" }));
  for (const [start, secs] of sd?.today_blocks || []) {
    const f0 = epochFrac(start), f1 = Math.min(f0 + secs / 86400, nf);
    if (f1 > f0) svg.append(s("path", { d: arc(f0, Math.max(f1, f0 + 0.004), 116), class: "block" }));
  }
  if (t?.started) {
    const f0 = epochFrac(t.started);
    svg.append(s("path", { d: arc(f0, Math.max(nf, f0 + 0.003), 116), class: `block live${t.paused ? " paused" : ""}` }));
  }

  // daily goal ring
  const goal = sd ? Math.min(1, (sd.today_min + (t ? t.elapsed / 60 : 0)) / Math.max(1, sd.goal_min)) : 0;
  svg.append(s("circle", { cx: C, cy: C, r: 101, class: "goal-track" }));
  if (goal > 0) svg.append(s("path", { d: arc(0.5, 0.5 + goal * 0.999, 101), class: `goal${goal >= 1 ? " met" : ""}` }));

  // now hand: a trace with a via at the tip
  const [hx0, hy0] = pt(nf, 94), [hx1, hy1] = pt(nf, 148);
  svg.append(s("line", { x1: hx0, y1: hy0, x2: hx1, y2: hy1, class: "hand" }),
    s("circle", { cx: hx1, cy: hy1, r: 4.5, class: "via" }));

  // centre readout
  const c = clock(now);
  const studied = sd ? sd.today_min + (t ? Math.floor(t.elapsed / 60) : 0) : null;
  svg.append(
    s("text", { x: C, y: 146, class: "t", "text-anchor": "middle" }, c.hm, c.ap ? s("tspan", { class: "ap", dx: 4 }, c.ap) : null),
    s("text", { x: C, y: 172, class: "d", "text-anchor": "middle" }, `${DAYS[now.getDay()]} ${now.getDate()} ${MONTHS[now.getMonth()]}`),
    studied != null ? s("text", { x: C, y: 194, class: `g${goal >= 1 ? " met" : ""}`, "text-anchor": "middle" },
      `${mins(studied)} of ${mins(sd.goal_min)}`) : null);
  return svg;
}

// ---------------------------------------------------------------- side panels
function hourly(w) {
  const hrs = w.hours || [];
  if (!hrs.length) return null;
  const lo = Math.min(...hrs.map((x) => x.t)) - 2, hi = Math.max(...hrs.map((x) => x.t)) + 1;
  const W = 150, H = 34, bw = W / hrs.length;
  const svg = s("svg", { viewBox: `0 0 ${W} ${H + 14}`, class: "hourly", "aria-hidden": "true" });
  hrs.forEach((x, i) => {
    const bh = Math.max(3, ((x.t - lo) / Math.max(1, hi - lo)) * H);
    svg.append(s("rect", { x: i * bw + 5, y: H - bh, width: bw - 10, height: bh, class: "hb" }),
      s("text", { x: i * bw + bw / 2, y: H + 12, "text-anchor": "middle", class: "hh" }, use12() ? `${(+x.h % 12) || 12}${+x.h < 12 ? "a" : "p"}` : x.h));
  });
  return svg;
}

function battery(label, d) {
  if (!d || d.battery == null) return h("div.cell.off", h("span.cl", label), h("div.cv", h("div.bat", h("i")), h("span.faint", "--")));
  const lvl = d.stale ? "stale" : d.charging ? "ok" : d.battery <= 20 ? "fault" : d.battery <= 40 ? "warn" : "";
  const b = h("div.bat", { class: lvl }, h("i"));
  b.firstChild.style.width = `${d.battery}%`;
  return h("div.cell", h("span.cl", label), h("div.cv", b, h("span.num", { class: d.stale ? "faint" : "" }, `${d.battery}%${d.charging ? "+" : ""}`)));
}

function spark(vals) {
  const W = 92, H = 26;
  const svg = s("svg", { viewBox: `0 0 ${W} ${H}`, class: "cpu", "aria-hidden": "true" });
  if (vals.length > 1) {
    const step = W / (vals.length - 1);
    svg.append(s("path", { d: vals.map((v, i) => `${i ? "L" : "M"}${(i * step).toFixed(1)},${(H - 1 - (v / 100) * (H - 2)).toFixed(1)}`).join("") }));
  }
  return svg;
}

const row = (label, body, onclick) => h("div.hrow", { role: "button", tabindex: 0, onclick }, h("span.k", label), h("div.grow.hbody", body));
const stop = (fn) => (e) => { e.stopPropagation(); fn(e); };

function panels(st) {
  const out = {};
  const cds = (st.desk?.countdowns || []).filter((c) => c.days >= 0);
  out.next = row("Next", cds.length
    ? [h("div.big", h("span.num", cds[0].days === 0 ? "Today" : cds[0].days), cds[0].days ? h("small", " days") : null),
      h("div.sub.ellip", cds[0].label, cds[1] ? h("span.faint", `, then ${cds[1].label} in ${cds[1].days}`) : null)]
    : h("div.sub", "Add an exam date to count down to it"), () => go("desk", { tab: "countdowns" }));

  const open = (st.desk?.tasks || []).filter((x) => !x.done);
  out.task = row("To do", open.length
    ? h("div.taskline", h("button.tick", { "aria-label": "Mark done", onclick: stop(() => api(`/api/tasks/${open[0].id}/toggle`, {})) }, h("i")),
      h("div.grow", { style: { minWidth: 0 } }, h("div.ellip", open[0].text), h("div.sub", open.length > 1 ? `${open.length - 1} more after this` : "Last one")))
    : h("div.sub", "Nothing left. Add tasks in Desk"), () => go("desk", { tab: "tasks" }));

  const m = st.music;
  const playing = m && m.track;
  out.music = row("Music", playing
    ? h("div.music-line",
      h("div.art", { style: { backgroundImage: m.art ? `url("${m.art}")` : "" } }),
      h("div.grow", { style: { minWidth: 0 } }, h("div.ellip", m.track), h("div.sub.ellip", m.artist), h("div.prog", h("i.mprog"))),
      h("button.pp", { "aria-label": m.state === "playing" ? "Pause" : "Play", onclick: stop((e) => act(e.currentTarget, () => api("/api/music/toggle", {}))) },
        glyph(m.state === "playing" ? "pause" : "play")))
    : h("div.sub", !m ? "" : m.state === "needs-auth" ? "Spotify needs a one-time login" : m.state === "unconfigured" ? "Spotify not set up" : "Nothing playing"), () => go("music"));

  const b = st.brain;
  let brainBody;
  if (!b) brainBody = sk("line", "60%");
  else if (b.state === "unconfigured") brainBody = h("div.sub", "Link the brain in desk.toml");
  else if (b.state === "unreachable") brainBody = [h("div.fault-t", "Unreachable"), h("div.sub", "Server off or Tailscale down")];
  else {
    const units = [...(b.services || []).map((x) => x.state === "active"), ...(b.containers || []).map((x) => x.state === "running")];
    const inbox = (st.inbox?.items || []).filter((i) => Date.now() / 1000 - i.at < 86400).length;
    brainBody = h("div.brain-line",
      h("div.grow", h("div.leds", units.map((ok) => h("i.led", { class: ok ? "ok" : "fault" }))),
        h("div.sub", `${units.filter(Boolean).length} of ${units.length} up${inbox ? `, ${inbox} new in inbox` : ""}`)),
      h("div.cpuwrap", spark(cpuHist), h("div.sub.num", `CPU ${Math.round(b.host?.cpu ?? 0)}%`)));
  }
  out.brain = row("Brain", brainBody, () => go("brain"));

  const d = st.devices || {};
  out.devs = row("Power", h("div.cells", battery("Mac", d.mac), battery("iPhone", d.iphone), battery("iPad", d.ipad)), () => go("devices"));
  return out;
}

function musicProgress() {
  const m = last.music, bar = els?.right.querySelector(".mprog");
  if (!m || !bar || !m.duration_ms) return;
  const el = m.progress_ms + (m.state === "playing" ? Date.now() - m.at * 1000 : 0);
  bar.style.width = `${Math.min(100, (el / m.duration_ms) * 100)}%`;
}

export default {
  id: "home", label: "Home", des: "U1", title: "Desk",
  topics: ["weather", "study", "timer", "desk", "music", "brain", "devices", "inbox"],
  mount(root) {
    els = { dial: h("div.dialwrap"), wx: h("div.wxrow"), actions: h("div.actions"), right: h("div.hright") };
    root.append(h("div.page.home2", h("div.hleft", els.dial, els.wx, els.actions), els.right));
    firstDraw = !matchMedia("(prefers-reduced-motion: reduce)").matches;
    tick = setInterval(() => { this.paintDial(last); musicProgress(); }, 1000);
  },
  unmount() { clearInterval(tick); firstDraw = true; },
  paintDial(st) {
    const t = st.timer, minute = Math.floor(Date.now() / 60000);
    // repaint each minute, and every second while a sprint is running
    if (put(els.dial, [minute, t?.started, t?.paused, t ? Math.floor(t.elapsed / 30) : 0, st.study?.today_blocks, st.study?.goal_min, st.weather?.sunrise, use12()], () => dial(st))) {
      if (firstDraw) setTimeout(() => { firstDraw = false; els.dial.querySelector(".dial")?.classList.remove("draw"); }, 1400);
    }
  },
  update(st, changed) {
    last = st;
    if (changed?.has("brain") || changed?.has("*")) {
      const v = st.brain?.host?.cpu;
      if (v != null && (changed.has("brain"))) { cpuHist.push(v); if (cpuHist.length > 40) cpuHist.shift(); }
    }
    this.paintDial(st);

    const w = st.weather;
    put(els.wx, [w, use12()], () => w
      ? [h("div.wxnow", h("div.wt", `${w.temp}°`), h("div", { style: { minWidth: 0 } }, h("div.ellip", w.desc), h("div.sub.ellip", `Sunset ${hhmm(w.sunset)}`))), hourly(w)]
      : [sk("line", "80%")]);

    const t = st.timer;
    put(els.actions, [!!t, t?.subject], () => [
      h("button.pad", { onclick: () => go("study") }, t ? `${t.subject} running` : "Start a sprint"),
      h("button.pad.ghost", { onclick: () => go("ask") }, "Ask the brain")]);

    const p = panels(st);
    const m = st.music;
    put(els.right, [st.desk?.countdowns, st.desk?.tasks?.filter((x) => !x.done).length, st.desk?.tasks?.find((x) => !x.done)?.id,
      m?.track, m?.state, m?.art, st.brain?.state, st.brain?.services, st.brain?.containers?.map((c) => c.state), Math.round(st.brain?.host?.cpu ?? -1),
      st.inbox?.items?.length, st.devices], () => [p.next, p.task, p.music, p.brain, p.devs]);
    musicProgress();
  },
};
