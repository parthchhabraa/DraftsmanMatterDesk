import { S, act, ago, api, bytes, confirmBox, h, led, level, sheet, skLines, uptime, put } from "../core.js";

let tab = "overview", els, keys;

function metric(k, n, unit, lvl) { return h("div.metric", h("div.n", { class: lvl ? `${lvl}-t` : "" }, n ?? "--", unit ? h("small", unit) : ""), h("div.k", k)); }

function overview(st) {
  const b = st.brain;
  if (!b) return h("div.col", skLines(4));
  if (b.state === "unconfigured") return h("div.empty", h("b", "The desk is not linked to draftsmanbrain yet. "),
    "Run brain/setup.sh on the server, then put its address and token under [brain] in config/desk.toml.");
  const host = b.host || {};
  const down = b.state === "unreachable";
  const svcRow = (name, state, kind) => h("div.svc", led(state === "active" || state === "running" ? "ok" : state === "activating" ? "warn" : "fault"),
    h("span.name.ellip", name), h("span.small.dim", state),
    h("button.pad.ghost.small", {
      onclick: async (e) => { if (await confirmBox(`Restart ${name}?`, "Restart")) act(e.target, () => api(`/api/brain/services/${encodeURIComponent(name)}/restart`, {}), `${name} restarted`); },
    }, "Restart"));
  return h("div.col.grow",
    down ? h("div.fault-t", `Unreachable since ${b.last_ok ? ago(Date.now() / 1000 - b.last_ok) : "start"}. Check the server and Tailscale.`) : null,
    h("div.metrics", metric("CPU", Math.round(host.cpu ?? 0), "%", level(host.cpu, 70, 90)), metric("Memory", Math.round(host.ram ?? 0), "%", level(host.ram, 80, 92)),
      metric("Disk", Math.round(host.disk ?? 0), "%", level(host.disk, 80, 92)), metric("Up", uptime(host.uptime_s))),
    h("div.row.stack.grow", { style: { minHeight: 0 } },
      h("div.col.grow.scroll", h("div.small.faint", "Services"), h("div", ...(b.services || []).map((s) => svcRow(s.name, s.state)))),
      h("div.col.grow.scroll", h("div.small.faint", `Containers (${(b.containers || []).length})`),
        h("div", ...(b.containers || []).map((c) => svcRow(c.name, c.state === "running" ? "running" : c.state))))));
}

function thumb(it) {
  if (it.kind === "image" && !S.state.meta?.demo) return h("div.inbox-thumb", { style: { backgroundImage: `url("/api/inbox/${it.id}/file")` } });
  return h("div.inbox-thumb", { image: "Photo", audio: "Audio", link: "Link", text: "Text", file: "File" }[it.kind] || it.kind);
}

function openItem(it) {
  const body = h("div.col", { style: { maxHeight: "330px" } },
    it.kind === "image" ? h("img", { src: `/api/inbox/${it.id}/file`, style: { maxHeight: "260px", maxWidth: "100%", objectFit: "contain", alignSelf: "flex-start" } }) : null,
    it.kind === "audio" ? h("audio", { controls: true, src: `/api/inbox/${it.id}/file` }) : null,
    it.text ? h("div.scroll", { style: { whiteSpace: "pre-wrap", maxWidth: "70ch" } }, it.text) : it.kind === "audio" ? h("div.dim", "Transcript arrives once Murmur has processed it.") : null,
    h("div.small.dim", `From ${it.source}, ${ago(Date.now() / 1000 - it.at)}${it.size ? `, ${bytes(it.size)}` : ""}`));
  const close = sheet(it.name || it.kind, body, {
    actions: [
      h("button.pad.small", { onclick: (e) => act(e.target, () => api(`/api/inbox/${it.id}/to-mac`, {}), it.text?.startsWith("http") ? "Opened on the Mac" : "On the Mac clipboard") }, "Send to Mac"),
      h("button.pad.danger.small", { onclick: async (e) => { await act(e.target, () => api(`/api/inbox/${it.id}`, undefined, "DELETE")); close(); } }, "Delete"),
    ],
  });
}

function inbox(st) {
  const ib = st.inbox;
  if (st.brain?.state === "unconfigured") return h("div.empty", "The inbox lives on draftsmanbrain. Link the desk to it first.");
  if (!ib) return h("div.col", skLines(4));
  if (!ib.items.length) return h("div.empty", h("b", "Inbox is empty. "), "Penotron photos, Anamnis recordings and anything you share from the iPhone with the Send to Desk shortcut show up here.");
  return h("div.scroll.grow", ...ib.items.map((it) => h("button.li", { onclick: () => openItem(it) }, thumb(it),
    h("div.grow", h("div.ellip", it.text || it.name || it.kind), h("div.small.dim", `${it.source}, ${ago(Date.now() / 1000 - it.at)}`)))));
}

function paintKeys(st) {
  const b = st.brain;
  const targets = b?.wol_targets || [];
  keys.replaceChildren(
    h("div.klabel", "Wake"),
    ...(targets.length ? targets : ["desktop"]).map((t) => h("button.pad", { disabled: !b || b.state === "unconfigured" || b.state === "unreachable",
      onclick: (e) => act(e.currentTarget, () => api(`/api/brain/wol/${t}`, {}), `Wake signal sent to ${t}`) }, `Wake ${t}`)),
    h("div.spacer"),
    b?.ollama ? h("div.klabel", b.ollama.up ? `Ollama up, ${b.ollama.models} models` : "Ollama is down") : null,
    h("button.pad.ghost", { onclick: () => window.desk.go("ask") }, "Ask"));
}

const page = {
  id: "brain", label: "Brain", des: "U3", title: "draftsmanbrain",
  topics: ["brain", "inbox"],
  mount(root, k, opts) {
    keys = k; if (opts.tab) tab = opts.tab;
    els = { tabs: h("div.tabs"), body: h("div.col.grow") };
    root.append(h("div.page", els.tabs, els.body));
  },
  update(st) {
    const n = (st.inbox?.items || []).length;
    put(els.tabs, [tab, n], () => [["overview", "Overview"], ["inbox", `Inbox${n ? ` (${n})` : ""}`]].map(([id, l]) =>
      h(`button.pad${tab === id ? "" : ".ghost"}`, { onclick: () => { tab = id; page.update(S.state); } }, l)));
    const scroll = els.body.querySelector(".scroll")?.scrollTop || 0;
    if (put(els.body, [tab, st.brain?.state, tab === "inbox" ? st.inbox : st.brain], () => (tab === "inbox" ? inbox(st) : overview(st)))) {
      const sc = els.body.querySelector(".scroll"); if (sc) sc.scrollTop = scroll;
    }
    put(keys, [st.brain?.state, st.brain?.wol_targets, st.brain?.ollama], () => { paintKeys(st); return [...keys.childNodes]; });
  },
};
export default page;
