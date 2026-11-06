import { S, act, api, bar, h, hm, mins, put, sk } from "../core.js";

const pref = JSON.parse(localStorage.getItem("md-study") || "{}");
let subject = pref.subject || null, dur = pref.dur ?? 50, lockin = pref.lockin ?? false;
const save = () => localStorage.setItem("md-study", JSON.stringify({ subject, dur, lockin }));
let els, keys;

function heat(cells) {
  const today = cells.length - 1;
  const lv = (m) => (m <= 0 ? "" : m < 60 ? "l1" : m < 150 ? "l2" : m < 270 ? "l3" : "l4");
  // first column starts on the weekday 139 days ago; pad so rows are weekdays
  const start = new Date(); start.setDate(start.getDate() - today);
  const padCount = (start.getDay() + 6) % 7;
  return h("div.heat", { title: "Last 20 weeks" }, ...Array.from({ length: padCount }, () => h("i", { style: { visibility: "hidden" } })),
    ...cells.map((m, i) => h("i", { class: `${lv(m)} ${i === today ? "today" : ""}`, title: `${m} min` })));
}

function paintKeys(st) {
  const t = st.timer;
  put(keys, [!!t, t?.paused, t?.lockin, dur, lockin, subject], () => t ? keysRunning(t) : keysIdle());
}
function keysRunning(t) {
  {
    return [
      h("div.klabel", "Sprint"),
      h("button.pad", { onclick: (e) => act(e.currentTarget, () => api("/api/study/pause", {})) }, t.paused ? "Resume" : "Pause"),
      h("button.pad.ghost", { onclick: (e) => act(e.currentTarget, () => api("/api/study/stop", {})) }, "End and log"),
      h("div.spacer"),
      t.lockin ? h("div.klabel", "Lock-in is blocking distractions on every device") : null];
  }
}
function keysIdle() {
  const durs = [[25, "25 min"], [50, "50 min"], [90, "90 min"], [0, "Open"]];
  return [
    h("div.klabel", "Length"),
    ...durs.map(([v, l]) => h(`button.pad${dur === v ? "" : ".ghost"}`, { onclick: () => { dur = v; save(); paintKeys(S.state); } }, l)),
    h("div.spacer"),
    h(`button.pad${lockin ? "" : ".ghost"}`, { onclick: () => { lockin = !lockin; save(); paintKeys(S.state); }, "aria-pressed": String(lockin) }, lockin ? "Lock-in on" : "Lock-in off"),
    h("button.pad", { disabled: !subject, onclick: (e) => act(e.currentTarget, () => api("/api/study/start", { subject, target_min: dur || null, lockin })) }, "Start")];
}

const page = {
  id: "study", label: "Study", des: "U2", title: "Study",
  topics: ["timer", "study", "adguard"],
  mount(root, k) {
    keys = k;
    els = { face: h("div.timer-face"), setup: h("div.col"), stats: h("div.row.stack") };
    root.append(h("div.page", els.face, els.setup, h("div.rule"), els.stats));
  },
  update(st) {
    const t = st.timer, s = st.study;
    if (t) {
      const left = t.remaining ?? t.elapsed;
      els.face.replaceChildren(h("div.t", hm(left)),
        h("div.meta", `${t.subject}${t.lockin ? ", lock-in" : ""}${t.paused ? ", paused" : ""}${t.target_s ? `, ${mins(t.elapsed / 60)} in` : ", open sprint"}`),
        t.target_s ? bar((t.elapsed / t.target_s) * 100, t.paused ? "warn" : "") : null);
    } else {
      els.face.replaceChildren(h("div.t.idle", dur ? hm(dur * 60) : "00:00"), h("div.meta", subject ? `${subject}, ready` : "Pick what you are studying"));
    }
    if (!t && s) {
      if (subject && !s.subjects.includes(subject)) subject = null;
      put(els.setup, [s.subjects, subject], () => h("div.subjects", ...s.subjects.map((x) =>
        h(`button.pad${x === subject ? "" : ".ghost"}`, { onclick: () => { subject = x; save(); page.update(S.state); } }, x))));
    } else put(els.setup, "none", () => []);

    if (s) {
      put(els.stats, s, () => [
        h("div.col", { style: { flex: "none" } }, heat(s.heat), h("div.row.small.dim", { style: { gap: "18px" } }, h("span", `${s.streak} day streak`), h("span", `${mins(s.week_min)} this week`))),
        h("div.col.grow", h("div.subjbars", ...(s.by_subject.length
          ? s.by_subject.slice(0, 5).map(([n, m]) => h("div.r", h("span.ellip", n), bar((m / Math.max(...s.by_subject.map((x) => x[1]))) * 100), h("span.num.dim", mins(m))))
          : [h("div.empty", "Nothing logged today yet. Pick a subject and start.")])))]);
    } else put(els.stats, "sk", () => sk("block"));
    paintKeys(st);
  },
};
export default page;
