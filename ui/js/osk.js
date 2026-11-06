// Text entry. On the Pi (no keyboard) it opens a full on-screen keyboard;
// on a phone or Mac it uses the device's own keyboard.
import { h, sheet } from "./core.js";

export const KIOSK = ["127.0.0.1", "localhost"].includes(location.hostname) && !matchMedia("(pointer: fine)").matches
  || new URLSearchParams(location.search).has("kiosk");

const ROWS = {
  abc: ["1234567890", "qwertyuiop", "asdfghjkl'", "zxcvbnm,.?"],
  sym: ["1234567890", "+-=×÷/()^√", "@#&%_:;\"!*", "<>[]{}°πτ²"],
};

export function textInput(title, initial = "", { placeholder = "", secret = false, multiline = false, goLabel = "Done" } = {}) {
  return new Promise((resolve) => {
    let value = initial || "";
    let settled = false;
    const finish = (v) => { if (settled) return; settled = true; close(); resolve(v); };

    if (!KIOSK) {
      const field = h(multiline ? "textarea.field" : "input.field", { placeholder, type: secret ? "password" : "text", rows: multiline ? 5 : null });
      field.value = value;
      field.style.maxHeight = "none";
      field.addEventListener("keydown", (e) => { if (e.key === "Enter" && (!multiline || e.metaKey || e.ctrlKey)) { e.preventDefault(); finish(field.value); } });
      var close = sheet(title, h("div.col", field, h("button.pad", { onclick: () => finish(field.value) }, goLabel)), { onClose: () => finish(null) });
      setTimeout(() => field.focus(), 50);
      return;
    }

    let shift = false, mode = "abc";
    const shown = h("div.field.live");
    const paint = () => {
      const txt = secret ? "•".repeat(value.length) : value;
      shown.replaceChildren(txt || h("span.faint", placeholder), h("span.caret"));
      shown.scrollTop = shown.scrollHeight;
    };
    const keyboard = h("div.osk");
    const press = (k) => {
      if (k === "⌫") value = value.slice(0, -1);
      else if (k === "space") value += " ";
      else if (k === "enter") value += "\n";
      else { value += shift ? k.toUpperCase() : k; if (shift) { shift = false; build(); } }
      paint();
    };
    let holdTimer;
    const key = (label, cls, fn) => h(`button${cls ? "." + cls : ""}`, {
      onpointerdown: (e) => { e.preventDefault(); fn(); if (label === "⌫") holdTimer = setInterval(fn, 90); },
      onpointerup: () => clearInterval(holdTimer), onpointerleave: () => clearInterval(holdTimer),
    }, label);
    function build() {
      keyboard.replaceChildren(
        ...ROWS[mode].map((row, i) => h("div.r", ...(i === 3 && mode === "abc" ? [key("shift", "mod w15" + (shift ? " on" : ""), () => { shift = !shift; build(); })] : []),
          ...[...row].map((c) => key(shift ? c.toUpperCase() : c, "", () => press(c))),
          ...(i === 3 ? [key("⌫", "mod w15", () => press("⌫"))] : []))),
        h("div.r",
          key(mode === "abc" ? "#+=" : "abc", "mod w15", () => { mode = mode === "abc" ? "sym" : "abc"; build(); }),
          key("space", "w5", () => press("space")),
          ...(multiline ? [key("return", "mod w15", () => press("enter"))] : []),
          key(goLabel, "go w2", () => finish(value))));
    }
    build(); paint();
    var close = sheet(title, h("div.col", shown, keyboard), { onClose: () => finish(null) });
  });
}
