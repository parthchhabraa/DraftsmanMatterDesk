import { S, act, api, confirmBox, h, put, sheet, skLines } from "../core.js";
import { KIOSK, textInput } from "../osk.js";

let els, keys;
const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
const when = (t) => { if (!t) return ""; const d = new Date(t * 1000); return `${d.getDate()} ${MONTHS[d.getMonth()]}`; };
const slug = (url) => url.split("/").pop();

export async function openArtifact(a) {
  if (!KIOSK) { window.open(a.url, "_blank", "noopener"); return; }
  if (!S.state.viewer?.available) {
    await confirmBox("The desk can't open pages yet. Restart the kiosk once (System, Power, Restart the desk app) after updating.", "OK");
    return;
  }
  act(null, () => api("/api/viewer/open", { url: a.url }));
}

function manage(a) {
  const close = sheet(a.title || slug(a.url), h("div.col",
    h("div.small.dim", a.url),
    h("div.small.dim", `Added ${when(a.added)}${a.opened ? `, last opened ${when(a.opened)}` : ""}${a.source && a.source !== "desk" ? `, from ${a.source}` : ""}`)), {
    actions: [
      h("button.pad.small", { onclick: () => { close(); openArtifact(a); } }, "Open"),
      h("button.pad.ghost.small", { onclick: async () => { const t = await textInput("Name on the shelf", a.title || "", { goLabel: "Save" }); if (t != null) { api(`/api/artifacts/${a.id}/rename`, { title: t }); close(); } } }, "Rename"),
      h("button.pad.danger.small", { onclick: async () => { if (await confirmBox(`Take "${a.title || slug(a.url)}" off the shelf? The artifact itself stays on Claude.`, "Remove", { danger: true })) { api(`/api/artifacts/${a.id}`, undefined, "DELETE"); close(); } } }, "Remove"),
    ],
  });
}

function shelf(list) {
  if (!list.length) return h("div.empty", h("b", "Nothing on the shelf yet. "),
    "Share a claude.ai artifact link to the desk from your iPhone (Send to Desk), or tap Add link. Pages you make with Claude then open here full screen.");
  return h("div.scroll.grow", ...list.map((a) => h("div.li",
    h("button.grow", { style: { textAlign: "left", minWidth: 0 }, onclick: () => openArtifact(a) },
      h("div.ellip", a.title || h("span.dim", `Artifact ${slug(a.url)}`)),
      h("div.small.dim", a.opened ? `Opened ${when(a.opened)}` : `Added ${when(a.added)}`)),
    h("button.pad.ghost.small", { "aria-label": `Options for ${a.title || "artifact"}`, onclick: () => manage(a) }, "More"))));
}

const page = {
  id: "claude", label: "Claude", des: "U10", title: "Claude artifacts",
  topics: ["desk", "viewer"],
  mount(root, k) {
    keys = k;
    els = { body: h("div.col.grow") };
    root.append(h("div.page", els.body));
    keys.replaceChildren(
      h("button.pad", { onclick: async () => {
        const url = await textInput("Artifact link", "https://claude.ai/artifact/", { goLabel: "Add" });
        if (url && url.trim().length > 30) act(null, () => api("/api/artifacts", { url: url.trim() }), "Added to the shelf");
      } }, "Add link"),
      h("div.spacer"),
      h("div.klabel", KIOSK ? "Pages open full screen. Tap Back to desk, or triple-tap, to return." : "Pages open in a new tab."));
  },
  update(st) {
    const list = st.desk?.artifacts;
    const sc = els.body.querySelector(".scroll")?.scrollTop || 0;
    if (put(els.body, list || "sk", () => (list ? shelf(list) : h("div.col", skLines(5))))) {
      const s2 = els.body.querySelector(".scroll"); if (s2) s2.scrollTop = sc;
    }
  },
};
export default page;
