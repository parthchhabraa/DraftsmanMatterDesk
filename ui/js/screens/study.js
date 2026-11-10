import { S, act, api, bar, confirmBox, h, hhmm, hm, led, mins, pick, put, sheet, sk, skLines, toast } from "../core.js";
import { textInput } from "../osk.js";
import { daysPicker, daysText, endOf, lengthText, timePicker } from "../pickers.js";

const pref = JSON.parse(localStorage.getItem("md-study") || "{}");
let subject = pref.subject || null, dur = pref.dur ?? 50, lockin = pref.lockin ?? false;
const save = () => localStorage.setItem("md-study", JSON.stringify({ subject, dur, lockin }));
let tab = "sprint", els, keys, selDay = null, selScore = null;
const TABS = [["sprint", "Sprint"], ["plan", "Plan"], ["insights", "Insights"], ["scores", "Mock scores"]];
const NS = "http://www.w3.org/2000/svg";
const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
const dShort = (iso) => { const [, m, d] = iso.split("-").map(Number); return `${d} ${MONTHS[m - 1]}`; };
function s(tag, attrs = {}, ...kids) {
  const e = document.createElementNS(NS, tag);
  for (const [k, v] of Object.entries(attrs)) if (v != null) e.setAttribute(k, v);
  for (const k of kids) if (k != null) e.append(k);
  return e;
}
const repaint = () => page.update(S.state);

// ================================================================ sprint
function ring(t) {
  const R = 86, C = 100, circ = 2 * Math.PI * R;
  const frac = t ? (t.target_s ? Math.min(1, t.elapsed / t.target_s) : (t.elapsed % 3600) / 3600) : 0;
  const svg = s("svg", { viewBox: "0 0 200 200", class: "sring", role: "img", "aria-label": t ? `${t.subject}, ${hm(t.remaining ?? t.elapsed)}` : "No sprint running" });
  svg.append(s("circle", { cx: C, cy: C, r: R, class: "track" }));
  if (t) svg.append(s("circle", { cx: C, cy: C, r: R, class: `prog${t.paused ? " paused" : ""}`, "stroke-dasharray": `${(frac * circ).toFixed(1)} ${circ.toFixed(1)}`, transform: `rotate(-90 ${C} ${C})` }));
  for (let i = 0; i < 12; i++) {
    const a = (i / 12) * 2 * Math.PI;
    svg.append(s("line", { x1: C + 72 * Math.sin(a), y1: C - 72 * Math.cos(a), x2: C + 76 * Math.sin(a), y2: C - 76 * Math.cos(a), class: "tick" }));
  }
  const big = t ? hm(t.remaining ?? t.elapsed) : dur ? hm(dur * 60) : "Open";
  svg.append(s("text", { x: C, y: 108, class: `t${t ? "" : " idle"}${big.length > 5 ? " long" : ""}`, "text-anchor": "middle" }, big),
    s("text", { x: C, y: 132, class: "m", "text-anchor": "middle" }, t ? (t.paused ? "paused" : t.target_s ? "left" : "elapsed") : "ready"));
  return svg;
}

function sprint(st) {
  const t = st.timer, sd = st.study;
  const now = Date.now() / 1000;
  const planned = (st.plan?.blocks || []).find((b) => b.kind === "study" && b.start <= now && now < b.end);
  const right = [];
  if (t) {
    right.push(h("div.h", t.subject), h("div.dim", `${t.lockin ? "Lock-in on. " : ""}${mins(t.elapsed / 60)} in${t.target_s ? ` of ${mins(t.target_s / 60)}` : ""}`));
  } else if (sd) {
    if (subject && !sd.subjects.includes(subject)) subject = null;
    right.push(h("div.small.faint", "What are you studying?"),
      h("div.subjects", ...sd.subjects.map((x) => h(`button.pad${x === subject ? "" : ".ghost"}`, { onclick: () => { subject = x; save(); repaint(); } }, x))));
    if (planned) right.push(h("button.pad.ghost.planned", { onclick: (e) => act(e.currentTarget, () => api(`/api/plan/${planned.id}/start`, { lockin }), `${planned.label} started`) },
      `Start planned ${planned.label}, ${Math.max(0, Math.floor((planned.end - now) / 60))} min left`));
  }
  if (sd) {
    const max = Math.max(1, ...sd.by_subject.map((x) => x[1]));
    right.push(h("div.rule"), h("div.small.faint", `Today, ${mins(sd.today_min)} of ${mins(sd.goal_min)}`),
      h("div.subjbars", ...(sd.by_subject.length
        ? sd.by_subject.slice(0, 4).map(([n, m]) => h("div.r", h("span.ellip", n), bar((m / max) * 100), h("span.num.dim", mins(m))))
        : [h("div.dim.small", "Nothing logged yet today.")])));
  }
  return h("div.row.stack.grow", h("div.sringwrap", ring(t)), h("div.col.grow", ...right));
}

function sprintKeys(st) {
  const t = st.timer;
  if (t) return [
    h("div.klabel", "Sprint"),
    h("button.pad", { onclick: (e) => act(e.currentTarget, () => api("/api/study/pause", {})) }, t.paused ? "Resume" : "Pause"),
    h("button.pad.ghost", { onclick: (e) => act(e.currentTarget, () => api("/api/study/stop", {})) }, "End and log"),
    h("div.spacer"),
    t.lockin ? h("div.klabel", "Lock-in is blocking distractions on every device") : null];
  const durs = [[25, "25 min"], [50, "50 min"], [90, "90 min"], [0, "Open"]];
  return [
    h("div.klabel", "Length"),
    ...durs.map(([v, l]) => h(`button.pad${dur === v ? "" : ".ghost"}`, { onclick: () => { dur = v; save(); repaint(); } }, l)),
    h("div.spacer"),
    h(`button.pad${lockin ? "" : ".ghost"}`, { onclick: () => { lockin = !lockin; save(); repaint(); }, "aria-pressed": String(lockin) }, lockin ? "Lock-in on" : "Lock-in off"),
    h("button.pad", { disabled: !subject, onclick: (e) => act(e.currentTarget, () => api("/api/study/start", { subject, target_min: dur || null, lockin })) }, "Start")];
}

// ================================================================ plan
const LENGTHS = [30, 45, 60, 90, 120, 150, 180, 240, 300, 360, 390, 420];

function editBlock(b0) {
  const b = { kind: "study", subject: null, label: "", start: "17:00", minutes: 60, days: [], ...b0 };
  const body = h("div.col");
  const rowBtn = (k, v, fn) => h("div", h("span.k", k), h("button.v", { onclick: async () => { await fn(); paint(); } }, v, h("span.faint", "  change")));
  const paint = () => body.replaceChildren(
    h("div.ro",
      b.kind === "study"
        ? rowBtn("Subject", b.subject || "Choose", async () => { const v = await pick("Subject", S.state.study?.subjects || []); if (v) { b.subject = v; b.label = v; } })
        : rowBtn("Name", b.label || "Name it", async () => { const v = await textInput("What is this block?", b.label, { placeholder: "School", goLabel: "Done" }); if (v != null) b.label = v.trim(); }),
      rowBtn("Starts", hhmm(b.start), async () => { const v = await timePicker("Starts at", b.start); if (v) b.start = v; }),
      rowBtn("Length", `${lengthText(b.minutes)}, ends ${hhmm(endOf(b.start, b.minutes))}`, async () => { const v = await pick("Length", LENGTHS.map((m) => [m, lengthText(m)]), b.minutes); if (v) b.minutes = v; }),
      rowBtn("Repeats", daysText(b.days), async () => { const v = await daysPicker("Which days?", b.days); if (v) b.days = v; })),
    h("div.row",
      b.id ? h("button.pad.danger", { onclick: async () => { await api(`/api/plan/${b.id}`, undefined, "DELETE"); close(); } }, "Delete") : null,
      h("button.pad.grow", { onclick: async (e) => {
        if (b.kind === "study" && !b.subject) return toast("Choose a subject first", "warn");
        if (b.kind === "fixed" && !b.label) return toast("Name the block first", "warn");
        if (await act(e.currentTarget, () => api("/api/plan", { block: b }))) close();
      } }, "Save block")));
  paint();
  const close = sheet(b.id ? "Edit block" : b.kind === "study" ? "New study block" : "New fixed block", body);
}

function plan(st) {
  const all = st.desk?.plan;
  if (!all) return h("div.col", skLines(4));
  if (!all.length) return h("div.empty", h("b", "No plan yet. "),
    "Add your fixed blocks (school, coaching) and the study blocks you want to hit. They show on the home dial, and the desk nudges you when one starts.");
  const today = new Map((st.plan?.blocks || []).map((b) => [b.id, b]));
  const now = Date.now() / 1000;
  return h("div.scroll.grow", ...all.map((b) => {
    const t = today.get(b.id), live = t && t.start <= now && now < t.end, past = t && t.end <= now;
    return h("button.li.planrow", { class: !t ? "off" : "", onclick: () => editBlock(b) },
      led(live ? "ok blink" : t && !past ? "warn" : ""),
      h("span.num.ptime", `${hhmm(b.start)} to ${hhmm(endOf(b.start, b.minutes))}`),
      h("div.grow", { style: { minWidth: 0 } }, h("div.ellip", b.label), h("div.small.dim", `${b.kind === "fixed" ? "Fixed" : "Study"}, ${lengthText(b.minutes)}, ${daysText(b.days).toLowerCase()}`)),
      h("span.small.dim", live ? "now" : !t ? "not today" : past ? "done" : "today"));
  }));
}

// ================================================================ insights
function daysChart(sd) {
  const d = sd.days14, W = 520, H = 132, base = H - 20, top = 12;
  const max = Math.max(sd.goal_min, ...d.map((x) => x.min), 60);
  const bw = W / d.length;
  if (selDay == null || selDay >= d.length) selDay = d.length - 1;
  const svg = s("svg", { viewBox: `0 0 ${W} ${H}`, class: "chart", role: "img", "aria-label": `Study minutes for the last 14 days. Average ${mins(sd.avg7)} a day.` });
  const gy = base - (sd.goal_min / max) * (base - top);
  svg.append(s("line", { x1: 0, x2: W, y1: base, y2: base, class: "axis" }),
    s("line", { x1: 0, x2: W, y1: gy, y2: gy, class: "goal-line" }),
    s("text", { x: W - 2, y: gy - 4, class: "lbl", "text-anchor": "end" }, `goal ${mins(sd.goal_min)}`));
  d.forEach((x, i) => {
    const bh = x.min ? Math.max(3, (x.min / max) * (base - top)) : 0;
    const g = s("g", { class: `col${i === selDay ? " sel" : ""}${x.min >= sd.goal_min ? " met" : ""}` });
    g.append(s("rect", { x: i * bw, y: 0, width: bw, height: H, class: "hit" }),   // hit target wider than the mark
      s("rect", { x: i * bw + 5, y: base - bh, width: bw - 10, height: bh, rx: 2, class: "b" }),
      s("text", { x: i * bw + bw / 2, y: H - 5, class: "lbl", "text-anchor": "middle" }, i === d.length - 1 ? "today" : x.wd.slice(0, 2)));
    g.addEventListener("pointerdown", () => { selDay = i; repaint(); });
    svg.append(g);
  });
  return svg;
}

function heat(cells) {
  const today = cells.length - 1;
  const lv = (m) => (m <= 0 ? "" : m < 60 ? "l1" : m < 150 ? "l2" : m < 270 ? "l3" : "l4");
  const start = new Date(); start.setDate(start.getDate() - today);
  const padCount = (start.getDay() + 6) % 7;
  return h("div.heat", ...Array.from({ length: padCount }, () => h("i", { style: { visibility: "hidden" } })),
    ...cells.map((m, i) => h("i", { class: `${lv(m)} ${i === today ? "today" : ""}` })));
}

function insights(st) {
  const sd = st.study;
  if (!sd?.days14) return h("div.col", sk("block"));
  const chart = daysChart(sd), x = sd.days14[selDay];
  const max = Math.max(1, ...sd.split30.map((r) => r[1])), total = sd.split30.reduce((a, r) => a + r[1], 0);
  const stat = (n, k) => h("div.metric", h("div.n", n), h("div.k", k));
  return h("div.col",
    h("div.metrics", stat(mins(sd.avg7), "Daily average, last 7 days"), stat(mins(sd.week_min), "This week"), stat(`${sd.streak}`, "Day streak"), stat(mins(sd.best14), "Best day in 14")),
    h("div.col", { style: { gap: "4px" } },
      h("div.small.spread", { style: { gap: "10px" } }, h("span.dim", selDay === sd.days14.length - 1 ? "Today" : `${x.wd} ${dShort(x.date)}`), h("b", mins(x.min)), x.min >= sd.goal_min ? h("span.ok-t", "goal met") : null,
        h("span.faint", "Tap a bar to read it")), chart),
    h("div.row.stack",
      h("div.col.grow", h("div.small.faint", `Last 30 days by subject, ${mins(total)} in all`),
        h("div.subjbars", ...(sd.split30.length ? sd.split30.slice(0, 6).map(([n, m]) => h("div.r", h("span.ellip", n), bar((m / max) * 100), h("span.num.dim", mins(m))))
          : [h("div.dim.small", "No sessions in the last 30 days.")]))),
      h("div.col", { style: { flex: "none" } }, h("div.small.faint", "Last 20 weeks"), heat(sd.heat))));
}

// ================================================================ mock scores
function scoreChart(list, target) {
  const W = 520, H = 170, L = 8, R = 78, T = 14, B = 22;
  const vals = list.map((x) => x.score);
  const lo = Math.min(target, ...vals) - 15, hi = Math.max(target, ...vals) + 15;
  const X = (i) => (list.length === 1 ? (W - R + L) / 2 : L + 14 + (i / (list.length - 1)) * (W - R - L - 28));
  const Y = (v) => T + (1 - (v - lo) / (hi - lo)) * (H - T - B);
  if (selScore == null || selScore >= list.length) selScore = list.length - 1;
  const svg = s("svg", { viewBox: `0 0 ${W} ${H}`, class: "chart", role: "img", "aria-label": `Mock scores, latest ${vals[vals.length - 1]}, target ${target}.` });
  svg.append(s("line", { x1: L, x2: W - R, y1: H - B, y2: H - B, class: "axis" }),
    s("line", { x1: L, x2: W - R, y1: Y(target), y2: Y(target), class: "goal-line" }),
    s("text", { x: W - R + 6, y: Y(target) + 4, class: "lbl" }, `target ${target}`));
  if (list.length > 1) svg.append(s("path", { d: list.map((x, i) => `${i ? "L" : "M"}${X(i).toFixed(1)},${Y(x.score).toFixed(1)}`).join(""), class: "ln" }));
  list.forEach((x, i) => {
    const g = s("g", { class: `pt${i === selScore ? " sel" : ""}${x.score >= target ? " met" : ""}` });
    g.append(s("rect", { x: X(i) - 20, y: 0, width: 40, height: H, class: "hit" }), s("circle", { cx: X(i), cy: Y(x.score), r: 5.5, class: "dot" }));
    if (i === selScore) g.append(s("text", { x: X(i), y: Y(x.score) - 11, class: "val", "text-anchor": "middle" }, x.score));
    g.addEventListener("pointerdown", () => { selScore = i; repaint(); });
    svg.append(g);
  });
  svg.append(s("text", { x: X(0), y: H - 6, class: "lbl", "text-anchor": "middle" }, dShort(list[0].date)));
  if (list.length > 1) svg.append(s("text", { x: X(list.length - 1), y: H - 6, class: "lbl", "text-anchor": "middle" }, dShort(list[list.length - 1].date)));
  return svg;
}

function scores(st) {
  const list = st.desk?.scores, sd = st.study;
  if (!list || !sd) return h("div.col", skLines(4));
  const target = sd.score_target;
  if (!list.length) return h("div.empty", h("b", "No mock scores yet. "), `Add each test you sit. The desk plots them against your target of ${target}.`);
  const chart = scoreChart(list, target), cur = list[selScore];
  const last = list[list.length - 1], best = Math.max(...list.map((x) => x.score));
  const gap = target - last.score;
  const stat = (n, k, cls) => h("div.metric", h("div.n", { class: cls }, n), h("div.k", k));
  return h("div.col",
    h("div.metrics", stat(last.score, "Latest"), stat(best, "Best"), stat(gap > 0 ? gap : `+${-gap}`, gap > 0 ? `Marks to ${target}` : "Above target", gap > 0 ? "" : "ok-t"),
      stat(list.length > 1 ? `${last.score - list[list.length - 2].score >= 0 ? "+" : ""}${Math.round((last.score - list[list.length - 2].score) * 10) / 10}` : "--", "Since last test")),
    chart,
    h("div.row", { style: { alignItems: "center" } },
      h("div.grow.spread", { style: { gap: "10px" } }, h("b", cur.name), h("span.dim", `${dShort(cur.date)}, ${cur.score} of ${cur.out_of}`)),
      h("button.pad.danger.small", { onclick: async () => { if (await confirmBox(`Remove ${cur.name} (${cur.score})?`, "Remove", { danger: true })) { selScore = null; api(`/api/scores/${cur.id}`, undefined, "DELETE"); } } }, "Remove")));
}

async function addScore() {
  const sd = S.state.study;
  const name = await textInput("Which test?", "", { placeholder: "AITS 5", goLabel: "Next" });
  if (!name?.trim()) return;
  const raw = await textInput(`Score in ${name.trim()} (out of ${sd?.score_out_of ?? 300})`, "", { placeholder: "132", goLabel: "Save" });
  if (raw == null) return;
  const score = Number(raw.replace(/[^0-9.\-]/g, ""));
  if (!raw.trim() || Number.isNaN(score)) return toast("That is not a number", "warn");
  selScore = null;
  act(null, () => api("/api/scores", { name: name.trim(), score }), "Score added");
}

// ================================================================ page
const RENDER = { sprint, plan, insights, scores };
function tabKeys(st) {
  if (tab === "sprint") return sprintKeys(st);
  if (tab === "plan") return [
    h("button.pad", { onclick: () => editBlock({ kind: "study" }) }, "Add study block"),
    h("button.pad.ghost", { onclick: () => editBlock({ kind: "fixed", start: "07:30", minutes: 390, days: [0, 1, 2, 3, 4, 5] }) }, "Add fixed block"),
    h("div.spacer"), h("div.klabel", "Fixed blocks are school or coaching. Study blocks can be started in one tap when their time comes.")];
  if (tab === "scores") return [h("button.pad", { onclick: addScore }, "Add score"), h("div.spacer"),
    h("div.klabel", `Target ${st.study?.score_target ?? 150}. Change it in desk.toml.`)];
  return [h("div.klabel", "Copper bars are days under your goal. Green bars met it.")];
}

const page = {
  id: "study", label: "Study", des: "U2", title: "Study",
  topics: ["timer", "study", "plan", "desk"],
  mount(root, k, opts) {
    keys = k; if (opts.tab) tab = opts.tab;
    els = { tabs: h("div.tabs"), body: h("div.col.grow") };
    root.append(h("div.page", els.tabs, els.body));
  },
  update(st) {
    const t = st.timer;
    put(els.tabs, tab, () => TABS.map(([id, l]) => h(`button.pad${tab === id ? "" : ".ghost"}`, { onclick: () => { tab = id; repaint(); } }, l)));
    const sig = {
      sprint: [t, st.study?.by_subject, st.study?.subjects, subject, dur, Math.floor(Date.now() / 60000), st.plan?.blocks],
      plan: [st.desk?.plan, st.plan?.blocks, Math.floor(Date.now() / 60000)],
      insights: [st.study?.days14, st.study?.split30, selDay],
      scores: [st.desk?.scores, st.study?.score_target, selScore],
    }[tab];
    const sc = els.body.querySelector(".scroll")?.scrollTop || 0;
    if (put(els.body, [tab, sig], () => RENDER[tab](st))) { const s2 = els.body.querySelector(".scroll"); if (s2) s2.scrollTop = sc; }
    put(keys, [tab, !!t, t?.paused, t?.lockin, dur, lockin, subject, st.study?.score_target], () => tabKeys(st));
  },
};
export default page;
