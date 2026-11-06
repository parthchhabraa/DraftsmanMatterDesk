import qrcode from "../../vendor/qrcode.mjs";
import { S, act, api, bytes, confirmBox, h, led, skLines, spark, put } from "../core.js";
import { textInput } from "../osk.js";

let tab = "tailnet", els, keys;
const TABS = [["tailnet", "Tailnet"], ["exit", "Exit node"], ["adguard", "Ad blocking"], ["lan", "Home Wi-Fi"], ["dpn", "Hotspot"]];
const needV2 = (st) => st.brain?.state === "unconfigured" ? "Link the desk to draftsmanbrain first (System, then desk.toml)." : null;

function tailnet(st) {
  const t = st.tailnet;
  if (!t) return needV2(st) ? h("div.empty", needV2(st)) : h("div.col", skLines(5));
  const peers = [...t.peers].sort((a, b) => b.online - a.online || a.name.localeCompare(b.name));
  return h("div.scroll.grow", ...peers.map((p) => h("div.svc", led(p.online ? "ok" : ""),
    h("span.name.ellip", p.name, p.self ? h("span.faint", "  this server") : ""),
    h("span.small.dim", { style: { width: "84px" } }, p.os || ""),
    h("span.small.dim.num", { style: { width: "122px" } }, p.ip),
    h("span.small", { style: { width: "130px", textAlign: "right" } }, p.online ? (p.exit ? h("span.cu", `via brain, ${bytes(p.rx)}`) : bytes(p.rx + p.tx)) : h("span.faint", p.last_seen || "offline")))));
}

function exit(st) {
  const e = st.tailnet?.exit;
  if (!e) return needV2(st) ? h("div.empty", needV2(st)) : h("div.col", skLines(4));
  return h("div.col.grow",
    h("div.row", { style: { alignItems: "center" } },
      h("div.grow", h("div.h", e.advertised ? "draftsmanbrain is offered as an exit node" : "Exit node is off"),
        h("div.dim.small", "Devices that pick draftsmanbrain as their exit node in the Tailscale app get ad blocking and the location below.")),
      h(`button.pad${e.advertised ? ".ghost" : ""}`, { onclick: (ev) => act(ev.currentTarget, () => api("/api/brain/exit", { advertise: !e.advertised })) }, e.advertised ? "Turn off" : "Turn on")),
    h("div.rule"),
    h("div.small.faint", "Traffic leaves from"),
    h("div.subjects", ...e.locations.map((loc) => h(`button.pad${loc === e.location ? "" : ".ghost"}`, {
      onclick: async (ev) => { if (loc !== e.location && await confirmBox(`Route exit traffic through ${loc}?`, "Switch")) act(ev.target, () => api("/api/brain/exit", { location: loc }), `Exit traffic now leaves from ${loc}`); },
    }, loc === "direct" ? "Home connection" : loc))),
    e.locations.length < 2 ? h("div.empty", "Put Proton WireGuard configs in /etc/wireguard/proton on the server to get more locations.") : null);
}

function adguard(st) {
  const a = st.adguard;
  if (!a) return needV2(st) ? h("div.empty", needV2(st)) : h("div.col", skLines(5));
  if (a.error) return h("div.empty", h("b", "AdGuard Home is not answering. "), `${a.error}. Set BRAIN_ADGUARD_URL and login in ~/brain-api/.env on the server.`);
  return h("div.col.grow",
    h("div.metrics", h("div.metric", h("div.n", a.queries.toLocaleString()), h("div.k", "Lookups, 24 h")),
      h("div.metric", h("div.n.cu", a.blocked.toLocaleString()), h("div.k", "Blocked")),
      h("div.metric", h("div.n", a.blocked_pct, h("small", "%")), h("div.k", "Of all lookups")),
      h("div.metric", h("div.n", { class: a.focus ? "warn-t" : "" }, a.focus ? "On" : "Off"), h("div.k", "Lock-in blocking"))),
    a.hourly?.length ? spark([a.hourly]) : null,
    h("div.row.stack.grow", { style: { minHeight: 0 } },
      h("div.col.grow", h("div.small.faint", "Most blocked"), h("div.ro", ...a.top_blocked.slice(0, 4).map(([d, n]) => h("div", h("span.v.ellip", d), h("span.num.dim", n))))),
      h("div.col.grow", h("div.small.faint", "Busiest devices"), h("div.ro", ...a.clients.slice(0, 4).map(([d, n]) => h("div", h("span.v.ellip", d), h("span.num.dim", n)))))));
}

function lan(st) {
  const l = st.lan;
  if (!l) return h("div.col", skLines(5));
  if (!l.nodes.length) return h("div.empty", "No devices seen yet. Try a deep scan.");
  return h("div.scroll.grow", ...l.nodes.map((n) => h("div.svc", led(n.blocked ? "fault" : "ok"),
    h("span.num.small", { style: { width: "118px" } }, n.ip), h("span.name.ellip", n.host || n.vendor),
    h("span.small.dim.ellip", { style: { width: "120px" } }, n.vendor),
    h(`button.pad.small${n.blocked ? "" : ".ghost"}`, {
      onclick: async (e) => { if (n.blocked || await confirmBox(`Cut ${n.host || n.ip} off the Pi's network?`, "Block", { danger: true })) act(e.target, () => api("/api/lan/block", { mac: n.mac, on: !n.blocked })); },
    }, n.blocked ? "Unblock" : "Block"))));
}

function dpn(st) {
  const d = st.dpn;
  if (!d) return h("div.col", skLines(4));
  let qr = null;
  if (d.on) { const q = qrcode(0, "M"); q.addData(d.qr); q.make(); qr = h("img.qr", { src: q.createDataURL(5, 0), alt: "Scan to join" }); }
  return h("div.row.stack.grow",
    h("div.col.grow",
      h("div.h", { class: d.status === "error" ? "fault-t" : "" }, { routed: "Hotspot is routing", offline: "Hotspot is off", starting: "Starting hotspot", stopping: "Stopping hotspot", error: "Hotspot failed to start" }[d.status] || d.status),
      h("div.ro",
        h("div", h("span.k", "Network"), h("button.v", { onclick: async () => { const v = await textInput("Hotspot name", d.ssid); if (v) api("/api/dpn", { ssid: v }); } }, d.ssid)),
        h("div", h("span.k", "Password"), h("span.v.num", d.passphrase)),
        h("div", h("span.k", "Goes out via"), h("span.v", d.force_vpn ? `WireGuard (${d.uplink})` : `Home Wi-Fi (${d.uplink})`)),
        h("div", h("span.k", "Clients"), h("span.v", d.on ? `${d.clients.length} connected, ${d.rx} KB/s down` : "None"))),
      h("div.small.dim", "Changes to routing or ad blocking apply the next time the hotspot starts.")),
    qr ? h("div.col", { style: { alignItems: "center" } }, qr, h("div.small.dim", "Scan to join")) : null);
}

const RENDER = { tailnet, exit, adguard, lan, dpn };

function paintKeys(st) {
  const d = st.dpn || {};
  const a = st.adguard || {};
  if (keys._sig === JSON.stringify([tab, d.on, d.force_vpn, d.adblock, a.protection, a.focus, a.error])) return;
  keys._sig = JSON.stringify([tab, d.on, d.force_vpn, d.adblock, a.protection, a.focus, a.error]);
  const k = {
    lan: [h("button.pad", { onclick: (e) => act(e.currentTarget, () => api("/api/lan/scan", { deep: true }), "Deep scan started") }, "Deep scan")],
    dpn: [h(`button.pad${d.on ? ".danger" : ""}`, { onclick: (e) => act(e.currentTarget, () => api("/api/dpn", { on: !d.on })) }, d.on ? "Stop hotspot" : "Start hotspot"),
      h(`button.pad${d.force_vpn ? "" : ".ghost"}`, { onclick: () => api("/api/dpn", { force_vpn: !d.force_vpn }) }, d.force_vpn ? "Via WireGuard" : "Via home Wi-Fi"),
      h(`button.pad${d.adblock ? "" : ".ghost"}`, { onclick: () => api("/api/dpn", { adblock: !d.adblock }) }, d.adblock ? "Ad block on" : "Ad block off")],
    adguard: st.adguard && !st.adguard.error ? [
      h(`button.pad${st.adguard.protection ? ".ghost" : ""}`, { onclick: (e) => act(e.currentTarget, () => api("/api/brain/adguard", { enabled: !st.adguard.protection })) }, st.adguard.protection ? "Pause blocking" : "Resume blocking"),
      h(`button.pad${st.adguard.focus ? "" : ".ghost"}`, { onclick: (e) => act(e.currentTarget, () => api("/api/brain/focus", { enabled: !st.adguard.focus })) }, st.adguard.focus ? "Lock-in on" : "Lock-in off"),
      h("div.klabel", "Lock-in blocks social and video apps on every device until you turn it off or a sprint ends.")] : [],
  }[tab] || [];
  keys.replaceChildren(...k);
}

const page = {
  id: "network", label: "Network", des: "U5", title: "Network",
  topics: ["tailnet", "adguard", "lan", "dpn", "brain"],
  mount(root, k, opts) {
    keys = k; if (opts.tab) tab = opts.tab;
    els = { tabs: h("div.tabs"), body: h("div.col.grow") };
    root.append(h("div.page", els.tabs, els.body));
  },
  update(st) {
    put(els.tabs, tab, () => TABS.map(([id, l]) => h(`button.pad${tab === id ? "" : ".ghost"}`, { onclick: () => { tab = id; page.update(S.state); } }, l)));
    const sc = els.body.querySelector(".scroll")?.scrollTop || 0;
    if (put(els.body, [tab, st.tailnet, st.adguard, st.lan, st.dpn, st.brain?.state], () => RENDER[tab](st))) {
      const s2 = els.body.querySelector(".scroll"); if (s2) s2.scrollTop = sc;
    }
    paintKeys(st);
  },
};
export default page;
