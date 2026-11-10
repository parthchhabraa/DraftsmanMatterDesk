// Touch pickers for time of day, weekdays and lengths. No typing needed.
import { h, hhmm, pad2, sheet, use12 } from "./core.js";

export const WD = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];   // matches the server: Monday = 0

export function daysText(days) {
  if (!days || !days.length) return "Every day";
  if (days.length === 7) return "Every day";
  const s = [...days].sort((a, b) => a - b);
  if (s.join() === "0,1,2,3,4") return "Weekdays";
  if (s.join() === "0,1,2,3,4,5") return "Mon to Sat";
  if (s.join() === "5,6") return "Weekends";
  return s.map((d) => WD[d]).join(", ");
}
export function lengthText(m) { return m < 60 ? `${m} min` : m % 60 ? `${Math.floor(m / 60)} h ${m % 60} min` : `${m / 60} h`; }
export const endOf = (start, minutes) => { const [H, M] = start.split(":").map(Number); const t = (H * 60 + M + minutes) % 1440; return `${pad2(Math.floor(t / 60))}:${pad2(t % 60)}`; };

// resolves "HH:MM" (24 h) or null
export function timePicker(title, initial = "17:00") {
  return new Promise((resolve) => {
    let [H, M] = initial.split(":").map(Number);
    let done = false;
    const finish = (v) => { if (done) return; done = true; close(); resolve(v); };
    const show = h("div.tp-show");
    const paint = () => show.replaceChildren(hhmm(`${pad2(H)}:${pad2(M)}`));
    const step = (label, fn) => h("button.pad.ghost.tp-step", { onpointerdown: (e) => { e.preventDefault(); fn(); paint(); } }, label);
    const body = h("div.tp",
      show,
      h("div.tp-row",
        h("div.tp-col", h("div.small.faint", "Hour"), h("div.row", step("−", () => { H = (H + 23) % 24; }), step("+", () => { H = (H + 1) % 24; }))),
        h("div.tp-col", h("div.small.faint", "Minute"), h("div.row", step("−5", () => { M = (Math.ceil(M / 5) * 5 + 55) % 60; }), step("+5", () => { M = (Math.floor(M / 5) * 5 + 5) % 60; }),
          step("+1", () => { M = (M + 1) % 60; }))),
        use12() ? h("div.tp-col", h("div.small.faint", "Half"), h("div.row", step("am / pm", () => { H = (H + 12) % 24; }))) : null),
      h("button.pad.wide", { onclick: () => finish(`${pad2(H)}:${pad2(M)}`) }, "Set time"));
    paint();
    var close = sheet(title, body, { onClose: () => finish(null) });
  });
}

// resolves a sorted array of weekday numbers ([] = every day) or null
export function daysPicker(title, initial = []) {
  return new Promise((resolve) => {
    const sel = new Set(initial);
    let done = false;
    const finish = (v) => { if (done) return; done = true; close(); resolve(v); };
    const row = h("div.tp-days");
    const paint = () => row.replaceChildren(...WD.map((d, i) => h(`button.pad${sel.has(i) ? "" : ".ghost"}`, {
      "aria-pressed": String(sel.has(i)), onclick: () => { sel.has(i) ? sel.delete(i) : sel.add(i); paint(); } }, d)));
    const preset = (label, days) => h("button.pad.ghost.small", { onclick: () => { sel.clear(); days.forEach((d) => sel.add(d)); paint(); } }, label);
    paint();
    var close = sheet(title, h("div.col", row,
      h("div.row", preset("Every day", []), preset("Mon to Sat", [0, 1, 2, 3, 4, 5]), preset("Weekdays", [0, 1, 2, 3, 4]), preset("Weekends", [5, 6])),
      h("div.small.dim", "No day selected means every day."),
      h("button.pad.wide", { onclick: () => finish(sel.size === 7 ? [] : [...sel].sort((a, b) => a - b)) }, "Done")), { onClose: () => finish(null) });
  });
}
