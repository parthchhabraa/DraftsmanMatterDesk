import { S, act, api, bar, confirmBox, h, hhmm, hm, led, sheet, skLines, put } from "../core.js";
import { textInput } from "../osk.js";
import { daysPicker, daysText, timePicker } from "../pickers.js";

let tab = "tasks", els, keys, secTick;
let cardSubject = null, cardIdx = 0, showBack = false;
const TABS = [["tasks", "Tasks"], ["notes", "Notes"], ["cards", "Flashcards"], ["countdowns", "Countdowns"], ["alarms", "Alarms"]];
const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
const fmtDate = (iso) => { const [y, m, d] = iso.split("-").map(Number); return `${d} ${MONTHS[m - 1]} ${y}`; };

function tasks(d) {
  if (!d.tasks.length) return h("div.empty", "No tasks. Add what has to get done today.");
  const open = d.tasks.filter((t) => !t.done), done = d.tasks.filter((t) => t.done);
  return h("div.scroll.grow", ...[...open, ...done].map((t) => h("div.task", { class: t.done ? "done" : "" },
    h("button.tick", { "aria-label": t.done ? "Mark not done" : "Mark done", onclick: () => api(`/api/tasks/${t.id}/toggle`, {}) }, h("i")),
    h("button.txt", { onclick: async () => { if (await confirmBox(`Delete "${t.text}"?`, "Delete", { danger: true })) api(`/api/tasks/${t.id}`, undefined, "DELETE"); } },
      h("div", t.text), t.subject ? h("div.tag", t.subject) : null))));
}

async function editNote(n) {
  const body = await textInput(n ? "Edit note" : "New note", n?.body || "", { multiline: true, goLabel: "Save" });
  if (body == null) return;
  if (!body.trim() && n) return api(`/api/notes/${n.id}`, undefined, "DELETE");
  if (body.trim()) await act(null, () => api("/api/notes", { id: n?.id || null, body }));
}

function notes(d) {
  if (!d.notes.length) return h("div.empty", "No notes yet. Jot a formula, a doubt for class, anything.");
  return h("div.scroll.grow", ...d.notes.map((n) => {
    const [first, ...rest] = n.body.split("\n");
    return h("button.li", { onclick: () => {
      const close = sheet(first.slice(0, 40) || "Note", h("div.scroll", { style: { whiteSpace: "pre-wrap", maxHeight: "300px", maxWidth: "70ch" } }, n.body), {
        actions: [h("button.pad.small", { onclick: () => { close(); editNote(n); } }, "Edit"),
          h("button.pad.danger.small", { onclick: async () => { await api(`/api/notes/${n.id}`, undefined, "DELETE"); close(); } }, "Delete")],
      });
    } }, h("div.grow", h("div.ellip", first), h("div.small.dim.ellip", rest.join(" ") || "")));
  }));
}

function cards(d) {
  const subjects = [...new Set(d.cards.map((c) => c.subject))];
  if (!subjects.length) return h("div.empty", "No flashcards. Add one with a question on the front and the answer on the back.");
  if (!subjects.includes(cardSubject)) cardSubject = subjects[0];
  const now = Date.now() / 1000;
  const deck = d.cards.filter((c) => c.subject === cardSubject).sort((a, b) => (a.due || 0) - (b.due || 0));
  const dueCount = deck.filter((c) => (c.due || 0) <= now).length;
  cardIdx %= deck.length;
  const c = deck[cardIdx];
  const next = () => { cardIdx++; showBack = false; page.update(S.state); };
  return h("div.col.grow",
    h("div.subjects", ...subjects.map((s) => h(`button.pad${s === cardSubject ? "" : ".ghost"}`, { onclick: () => { cardSubject = s; cardIdx = 0; showBack = false; page.update(S.state); } }, s))),
    h("button.flash", { class: showBack ? "back" : "", onclick: () => { showBack = !showBack; page.update(S.state); } },
      h("div.side", `${showBack ? "Answer" : "Question"}, card ${cardIdx + 1} of ${deck.length}, ${dueCount} due`), h("div.face", showBack ? c.back : c.front)),
    h("div.row", showBack
      ? [h("button.pad.ghost.grow", { onclick: () => { api(`/api/cards/${c.id}/grade`, { knew: false }); next(); } }, "Missed it"),
        h("button.pad.grow", { onclick: () => { api(`/api/cards/${c.id}/grade`, { knew: true }); next(); } }, "Knew it")]
      : [h("button.pad.ghost.grow", { onclick: next }, "Skip"), h("button.pad.grow", { onclick: () => { showBack = true; page.update(S.state); } }, "Show answer")]));
}

async function editCountdown(c) {
  const label = await textInput(c ? "Rename" : "What are you counting down to?", c?.label || "", { placeholder: "JEE Main S1", goLabel: "Next" });
  if (!label) return;
  const date = await textInput(`Date for ${label}`, c?.date || "", { placeholder: "2027-01-22", goLabel: "Save" });
  if (!date) return;
  await act(null, () => api("/api/countdowns", { id: c?.id || null, label, date: date.trim() }));
}

function countdowns(d) {
  if (!d.countdowns.length) return h("div.empty", "Add JEE Main, boards, UCAS: anything with a date.");
  return h("div.scroll.grow", ...d.countdowns.map((c) => h("button.cd.li", { onclick: async () => {
    const close = sheet(c.label, h("div.dim", fmtDate(c.date)), { actions: [
      h("button.pad.small", { onclick: () => { close(); editCountdown(c); } }, "Edit"),
      h("button.pad.danger.small", { onclick: async () => { await api(`/api/countdowns/${c.id}`, undefined, "DELETE"); close(); } }, "Delete")] });
  } }, h("span.days", { class: c.days < 0 ? "past" : "" }, c.days < 0 ? "done" : c.days),
    h("div.grow", h("div.h", c.label), h("div.small.dim", c.days === 0 ? "Today" : `${c.days < 0 ? "Was" : "days to"} ${fmtDate(c.date)}`)))));
}

function editAlarm(a0) {
  const a = { time: "06:00", label: "Alarm", days: [], enabled: true, ...a0 };
  const body = h("div.col");
  const rowBtn = (k, v, fn) => h("div", h("span.k", k), h("button.v", { onclick: async () => { await fn(); paint(); } }, v, h("span.faint", "  change")));
  const paint = () => body.replaceChildren(
    h("div.ro",
      rowBtn("Time", hhmm(a.time), async () => { const v = await timePicker("Alarm time", a.time); if (v) a.time = v; }),
      rowBtn("Label", a.label, async () => { const v = await textInput("Alarm label", a.label, { goLabel: "Done" }); if (v?.trim()) a.label = v.trim(); }),
      rowBtn("Repeats", a.days.length ? daysText(a.days) : "Once", async () => { const v = await daysPicker("Ring on which days?", a.days); if (v) a.days = v; })),
    h("div.small.dim", "With no day selected the alarm rings once and switches itself off."),
    h("div.row",
      a.id ? h("button.pad.danger", { onclick: async () => { await api(`/api/alarms/${a.id}`, undefined, "DELETE"); close(); } }, "Delete") : null,
      h("button.pad.grow", { onclick: async (e) => { if (await act(e.currentTarget, () => api("/api/alarms", { alarm: { ...a, enabled: true } }))) close(); } }, "Save alarm")));
  paint();
  const close = sheet(a.id ? "Edit alarm" : "New alarm", body);
}

function alarms(d) {
  const timers = S.state.timers || [], now = Date.now() / 1000;
  const parts = [];
  if (timers.length) parts.push(h("div.small.faint", "Running timers"), ...timers.map((t) => h("div.svc",
    led("warn blink"), h("span.name.ellip", t.label), h("div", { style: { width: "150px" } }, bar(100 - ((t.ends - now) / Math.max(1, t.total)) * 100, "warn")),
    h("span.num", { style: { width: "64px", textAlign: "right" } }, hm(Math.max(0, t.ends - now))),
    h("button.pad.ghost.small", { onclick: () => api(`/api/timers/${t.id}`, undefined, "DELETE") }, "Cancel"))));
  if (!d.alarms.length && !timers.length) parts.push(h("div.empty", h("b", "No alarms or timers. "), "Set a wake-up alarm, or start a quick timer from the keys on the right. Both ring here and notify your Mac."));
  if (d.alarms.length) parts.push(h("div.small.faint", "Alarms"), ...d.alarms.map((a) => h("div.svc.alarmrow", { class: a.enabled ? "" : "off" },
    h("button.name", { style: { textAlign: "left" }, onclick: () => editAlarm(a) }, h("span.atime", hhmm(a.time)), h("span.dim", `  ${a.label}, ${a.days.length ? daysText(a.days).toLowerCase() : "once"}`)),
    h(`button.pad.small${a.enabled ? "" : ".ghost"}`, { "aria-pressed": String(a.enabled), onclick: () => api(`/api/alarms/${a.id}/toggle`, {}) }, a.enabled ? "On" : "Off"))));
  return h("div.scroll.grow", ...parts);
}

const RENDER = { tasks, notes, cards, countdowns, alarms };

function paintKeys() {
  const k = {
    tasks: [h("button.pad", { onclick: async () => { const t = await textInput("New task", "", { goLabel: "Add" }); if (t?.trim()) act(null, () => api("/api/tasks", { text: t })); } }, "Add task"),
      h("button.pad.ghost", { onclick: () => api("/api/tasks/clear-done", {}) }, "Clear done")],
    notes: [h("button.pad", { onclick: () => editNote(null) }, "New note")],
    cards: [h("button.pad", { onclick: async () => {
      const subj = await textInput("Subject", cardSubject || "", { goLabel: "Next" }); if (!subj) return;
      const front = await textInput("Front: the question", "", { multiline: true, goLabel: "Next" }); if (!front) return;
      const back = await textInput("Back: the answer", "", { multiline: true, goLabel: "Save" }); if (!back) return;
      cardSubject = subj; act(null, () => api("/api/cards", { subject: subj, front, back }), "Card added");
    } }, "Add card")],
    countdowns: [h("button.pad", { onclick: () => editCountdown(null) }, "Add date")],
    alarms: [h("button.pad", { onclick: () => editAlarm({}) }, "Add alarm"),
      h("div.klabel", "Quick timer"),
      ...[5, 10, 25].map((m) => h("button.pad.ghost", { onclick: (e) => act(e.currentTarget, () => api("/api/timers", { minutes: m, label: `${m} min timer` }), `${m} min timer started`) }, `${m} min`)),
      h("button.pad.ghost", { onclick: async () => {
        const raw = await textInput("Timer length in minutes", "", { placeholder: "15", goLabel: "Next" }); const m = Number(raw);
        if (!raw || !(m > 0)) return;
        const label = await textInput("What is it for?", "", { placeholder: "Tea", goLabel: "Start" });
        act(null, () => api("/api/timers", { minutes: m, label: label || "" }), "Timer started");
      } }, "Custom")],
  }[tab];
  keys.replaceChildren(...k);
}

const page = {
  id: "desk", label: "Desk", des: "U8", title: "Desk",
  topics: ["desk", "timers"],
  unmount() { clearInterval(secTick); },
  mount(root, k, opts) {
    keys = k; if (opts.tab) tab = opts.tab;
    secTick = setInterval(() => { if (tab === "alarms" && S.state.timers?.length) page.update(S.state); }, 1000);
    els = { tabs: h("div.tabs"), body: h("div.col.grow") };
    root.append(h("div.page", els.tabs, els.body));
  },
  update(st) {
    put(els.tabs, tab, () => TABS.map(([id, l]) => h(`button.pad${tab === id ? "" : ".ghost"}`, { onclick: () => { tab = id; showBack = false; page.update(S.state); } }, l)));
    const sc = els.body.querySelector(".scroll")?.scrollTop || 0;
    if (put(els.body, [tab, st.desk, cardSubject, cardIdx, showBack, tab === "alarms" ? [st.timers, st.timers?.length ? Math.floor(Date.now() / 1000) : 0] : 0], () => st.desk ? RENDER[tab](st.desk) : h("div.col", skLines(4)))) {
      const s2 = els.body.querySelector(".scroll"); if (s2) s2.scrollTop = sc;
    }
    if (keys._tab !== tab) { keys._tab = tab; paintKeys(); }
  },
};
export default page;
