import { S, act, api, confirmBox, h, sheet, skLines, put } from "../core.js";
import { textInput } from "../osk.js";

let tab = "tasks", els, keys;
let cardSubject = null, cardIdx = 0, showBack = false;
const TABS = [["tasks", "Tasks"], ["notes", "Notes"], ["cards", "Flashcards"], ["countdowns", "Countdowns"]];
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

const RENDER = { tasks, notes, cards, countdowns };

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
  }[tab];
  keys.replaceChildren(...k);
}

const page = {
  id: "desk", label: "Desk", des: "U8", title: "Desk",
  topics: ["desk"],
  mount(root, k, opts) {
    keys = k; if (opts.tab) tab = opts.tab;
    els = { tabs: h("div.tabs"), body: h("div.col.grow") };
    root.append(h("div.page", els.tabs, els.body));
  },
  update(st) {
    put(els.tabs, tab, () => TABS.map(([id, l]) => h(`button.pad${tab === id ? "" : ".ghost"}`, { onclick: () => { tab = id; showBack = false; page.update(S.state); } }, l)));
    const sc = els.body.querySelector(".scroll")?.scrollTop || 0;
    if (put(els.body, [tab, st.desk, cardSubject, cardIdx, showBack], () => st.desk ? RENDER[tab](st.desk) : h("div.col", skLines(4)))) {
      const s2 = els.body.querySelector(".scroll"); if (s2) s2.scrollTop = sc;
    }
    paintKeys();
  },
};
export default page;
