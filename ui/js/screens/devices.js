import { act, ago, api, bar, h, led, uptime } from "../core.js";
import { textInput } from "../osk.js";

let els, keys;

function battery(d) {
  if (d.battery == null) return h("div.dim", "No battery reading");
  const lvl = d.charging ? "ok" : d.battery <= 20 ? "fault" : d.battery <= 40 ? "warn" : "";
  return h("div.col", { style: { gap: "6px" } },
    h("div.metric", h("div.n", d.battery, h("small", `%${d.charging ? " charging" : ""}`))), bar(d.battery, lvl));
}

function card(name, d, extra) {
  if (!d) return h("div.fp.grow", h("span.ref", name), h("div.dim", "No reports yet."));
  return h("div.fp.grow", { class: d.stale ? "faint" : "" }, h("span.ref", d.name || name),
    h("div.col", battery(d), h("div.ro",
      ...extra(d),
      h("div", h("span.k", "Last seen"), h("span.v", { class: d.stale ? "warn-t" : "" }, led(d.stale ? "warn" : "ok"), ` ${ago(d.ago_s)}`)))));
}

export default {
  id: "devices", label: "Devices", des: "U6", title: "Mac, iPhone, iPad",
  topics: ["devices"],
  mount(root, k) {
    keys = k;
    els = { body: h("div.row.stack.grow") };
    root.append(h("div.page", els.body));
    const send = (cmd, arg, ok) => (e) => act(e.currentTarget, () => api(`/api/devices/mac/${cmd}`, { arg }), ok);
    keys.replaceChildren(
      h("div.klabel", "Mac"),
      h("button.pad", { onclick: send("lock", null, "Mac locked") }, "Lock"),
      h("button.pad.ghost", { onclick: send("sleep_display", null, "Mac display off") }, "Display off"),
      h("button.pad.ghost", { onclick: async (e) => { const t = await textInput("Put on the Mac clipboard", "", { multiline: true, goLabel: "Send" }); if (t) send("clipboard", t, "On the Mac clipboard")(e); } }, "Send text"),
      h("button.pad.ghost", { onclick: async (e) => { const t = await textInput("Show on the Mac", "", { goLabel: "Send" }); if (t) send("notify", t, "Sent")(e); } }, "Notify"),
      h("button.pad.ghost", { onclick: send("caffeinate", 3600, "Mac stays awake for an hour") }, "Keep awake"));
  },
  update(st) {
    const d = st.devices || {};
    if (!Object.keys(d).length) {
      els.body.replaceChildren(h("div.empty", h("b", "No devices have reported yet. "),
        "Install the Mac agent from companions/mac, and add the iPhone shortcuts from companions/iphone. Both need the device key from desk.toml."));
      return;
    }
    const mac = d.mac;
    els.body.replaceChildren(
      card("Mac", mac, (m) => [
        h("div", h("span.k", "In front"), h("span.v.ellip", m.locked ? "Locked" : m.app || "--")),
        h("div", h("span.k", "Load"), h("span.v.spread", h("span", `CPU ${m.cpu ?? "--"}%`), h("span", `RAM ${m.ram ?? "--"}%`))),
        m.uptime_s ? h("div", h("span.k", "Up"), h("span.v", uptime(m.uptime_s))) : null,
        m.agent === false ? h("div", h("span.v.warn-t", "Agent not running, commands will wait")) : null]),
      h("div.col.grow",
        card("iPhone", d.iphone, (p) => [h("div", h("span.k", "Focus"), h("span.v", p.focus || "None"))]),
        card("iPad", d.ipad, () => [])));
    for (const b of keys.querySelectorAll(".pad")) b.disabled = !mac || mac.stale;
  },
};
