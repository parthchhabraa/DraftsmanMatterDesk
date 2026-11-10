import { S, api, glyph, h, toast } from "../core.js";
import { textInput } from "../osk.js";

let thread = JSON.parse(localStorage.getItem("md-ask") || "[]");
let draft = "", busy = false, rec = null, els, keys;
const store = () => localStorage.setItem("md-ask", JSON.stringify(thread.slice(-30)));

const STARTS = [
  ["Explain", "Explain simply, then give one JEE-style example: "],
  ["Quiz me", "Ask me 5 quick questions, one at a time, on: "],
  ["Check working", "Check my working and point to the first mistake: "],
  ["Plan my day", "I have these tasks and about 6 hours. Order them: "],
];

function paintChat() {
  els.chat.replaceChildren(...(thread.length ? thread.map((m) => m.role === "user"
    ? h("div.msg.me", m.content)
    : h("div.msg.brain", h("div.who", m.model || "brain"), m.content || h("span.caret")))
    : [h("div.empty", "Ask anything. The answer comes from the model running on draftsmanbrain, so it stays in your house. Tap the box to type, or hold the mic.")]));
  els.chat.scrollTop = els.chat.scrollHeight;
}

function paintCompose() {
  els.field.replaceChildren(draft || h("span", "Type a question"));
  els.field.classList.toggle("empty-f", !draft);
  els.send.disabled = busy || !draft.trim();
}

async function send() {
  const q = draft.trim();
  if (!q || busy) return;
  busy = true; draft = "";
  thread.push({ role: "user", content: q });
  const reply = { role: "assistant", content: "" }; thread.push(reply);
  paintChat(); paintCompose();
  try {
    const r = await fetch("/api/ask", { method: "POST", headers: { "content-type": "application/json" },
      body: JSON.stringify({ messages: thread.slice(0, -1).map(({ role, content }) => ({ role, content })) }) });
    if (!r.ok) throw new Error((await r.json().catch(() => ({}))).error || `Ask failed (${r.status})`);
    const reader = r.body.getReader(), dec = new TextDecoder();
    for (;;) {
      const { value, done } = await reader.read();
      if (done) break;
      reply.content += dec.decode(value, { stream: true });
      const last = els.chat.lastElementChild;
      if (last) { last.replaceChildren(h("div.who", "brain"), reply.content); els.chat.scrollTop = els.chat.scrollHeight; }
    }
  } catch (e) {
    reply.content = `Could not reach the brain: ${e.message}`;
    paintChat();
  } finally { busy = false; store(); paintCompose(); }
}

async function edit(prefix = "") {
  const v = await textInput("Ask the brain", prefix || draft, { multiline: true, goLabel: "Done", placeholder: "Type a question" });
  if (v != null) { draft = v; paintCompose(); }
}

async function toggleMic(btn) {
  if (rec) { rec.stop(); return; }
  try {
    const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
    const chunks = [];
    rec = new MediaRecorder(stream);
    rec.ondataavailable = (e) => chunks.push(e.data);
    rec.onstop = async () => {
      stream.getTracks().forEach((t) => t.stop());
      rec = null; btn.classList.remove("on"); btn.replaceChildren(glyph("mic"));
      const fd = new FormData(); fd.append("file", new Blob(chunks, { type: chunks[0]?.type || "audio/webm" }), "ask.webm");
      els.field.replaceChildren(h("span.faint", "Transcribing with Murmur"));
      try { const { text } = await api("/api/dictate", fd); draft = (draft ? draft + " " : "") + text; } catch (e) { toast(e.message, "danger"); }
      paintCompose();
    };
    rec.start(); btn.classList.add("on"); btn.replaceChildren(glyph("stop"));
  } catch (e) { toast(`Microphone: ${e.message}`, "danger"); }
}

export default {
  id: "ask", label: "Ask", des: "U4", title: "Ask the brain",
  topics: ["brain"],
  mount(root, k) {
    keys = k;
    const hasMic = S.state.meta?.murmur && navigator.mediaDevices?.getUserMedia && window.MediaRecorder;
    els = {
      chat: h("div.chat.scroll"),
      field: h("button.field", { onclick: () => edit() }),
      send: h("button.pad", { onclick: send, "aria-label": "Send" }, glyph("send")),
    };
    const mic = hasMic ? h("button.pad.ghost", { "aria-label": "Dictate", onclick: (e) => toggleMic(e.currentTarget) }, glyph("mic")) : null;
    root.append(h("div.page", els.chat, h("div.compose", els.field, mic, els.send)));
    keys.replaceChildren(h("div.klabel", "Start with"),
      ...STARTS.map(([l, p]) => h("button.pad.ghost", { onclick: () => edit(p) }, l)),
      h("div.spacer"),
      h("button.pad.ghost", { onclick: async () => {
        const i = thread.map((m) => m.role).lastIndexOf("assistant");
        if (busy || i < 1 || !thread[i].content) return toast("Ask something first", "warn");
        try { await api("/api/notes", { id: null, body: `${thread[i - 1].content}\n\n${thread[i].content}` }); toast("Saved to Desk, Notes", "good"); } catch (e) { toast(e.message, "danger"); }
      } }, "Save answer"),
      h("button.pad.ghost", { onclick: () => { if (!busy) { thread = []; store(); paintChat(); } } }, "New chat"));
    paintChat(); paintCompose();
  },
  update(st) {
    if (st.brain?.state === "unreachable" && !busy) els.send.disabled = true;
  },
};
