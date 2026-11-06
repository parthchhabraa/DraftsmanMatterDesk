import { S, act, api, confirmBox, h, led, level, pick, skLines, spark, toast, uptime, watch, put } from "../core.js";
import { textInput } from "../osk.js";

let tab = "pi", els, keys, wifi = null, unwatch, results = {};
const TABS = [["pi", "This Pi"], ["wifi", "Wi-Fi"], ["tests", "Checks"], ["logs", "Log"]];

function pi(st) {
  const p = st.pi;
  if (!p) return h("div.col", skLines(4));
  const m = (k, n, unit, lvl) => h("div.metric", h("div.n", { class: lvl ? `${lvl}-t` : "" }, n, h("small", unit)), h("div.k", k));
  return h("div.col.grow",
    h("div.metrics", m("CPU", p.cpu, "%", level(p.cpu, 70, 90)), m("Memory", p.ram, "%", level(p.ram, 80, 92)),
      m("Temperature", Math.round(p.temp), "°C", level(p.temp, 70, 80)), m("Disk", p.disk, "%", level(p.disk, 80, 92))),
    h("div.col", { style: { gap: "4px" } }, h("div.small.faint", "Network, last 30 s: up in copper, down in silk"),
      spark([p.net.map((x) => x[0]), p.net.map((x) => x[1])], { colors: ["var(--copper)", "var(--silk-dim)"] })),
    h("div.ro",
      h("div", h("span.k", "Up for"), h("span.v", uptime(p.uptime_s))),
      h("div", h("span.k", "Screen"), h("span.v", p.sleep_in == null ? `Kept on by ${p.wake_lock.join(" and ") || "standby"}` : `Sleeps in ${Math.ceil(p.sleep_in / 60)} min if untouched`)),
      h("div", h("span.k", "Software"), h("span.v", `MatterDesk ${st.meta?.version || ""}${st.meta?.demo ? ", demo data" : ""}`))));
}

function wifiTab() {
  if (!wifi) return h("div.col", skLines(4));
  if (!wifi.length) return h("div.empty", "No networks found. Move closer to the router and scan again.");
  return h("div.scroll.grow", ...wifi.map((n) => h("button.li", {
    onclick: async () => {
      if (n.active) return;
      const pw = n.secure ? await textInput(`Password for ${n.ssid}`, "", { secret: true, goLabel: "Join" }) : "";
      if (pw == null) return;
      const r = await act(null, () => api("/api/wifi", { ssid: n.ssid, password: pw }));
      if (r) toast(r.ok ? `Joined ${n.ssid}` : r.message, r.ok ? "good" : "danger");
    },
  }, led(n.active ? "ok" : ""), h("div.grow", n.ssid), h("span.small.dim", `${n.signal}%${n.secure ? "" : ", open"}`))));
}

function tests() {
  const run = (id) => async (e) => { results[id] = await act(e.currentTarget, () => api(`/api/diag/${id}`)); page.update(S.state, new Set(["*"])); };
  const row = (id, label) => h("div.svc", led(results[id] ? (results[id].ok ? "ok" : "fault") : ""), h("span.name", label),
    h("span.small.dim.ellip", { style: { maxWidth: "280px" } }, results[id]?.detail || ""), h("button.pad.ghost.small", { onclick: run(id) }, "Run"));
  return h("div.col.grow",
    h("div", row("network", "Internet"), row("brain", "draftsmanbrain"), row("github", "GitHub updates"), row("thermal", "Temperature and throttling")),
    h("div.row", h("button.pad.ghost.grow", { onclick: touchTest }, "Touch test"), h("button.pad.ghost.grow", { onclick: displayTest }, "Display test")));
}

function touchTest() {
  const c = h("canvas", { width: innerWidth, height: innerHeight, style: { position: "fixed", inset: 0, zIndex: 99, background: "var(--mask-deep)", touchAction: "none" } });
  const g = c.getContext("2d"); g.fillStyle = getComputedStyle(document.documentElement).getPropertyValue("--copper");
  g.font = "16px B612"; g.fillText("Draw anywhere. Hold the top-left corner to leave.", 20, 30);
  c.onpointermove = (e) => { if (e.buttons) { g.fillRect(e.clientX - 3, e.clientY - 3, 6, 6); } };
  let t; c.onpointerdown = (e) => { if (e.clientX < 80 && e.clientY < 80) t = setTimeout(() => c.remove(), 700); };
  c.onpointerup = () => clearTimeout(t);
  document.body.append(c);
}
function displayTest() {
  const colors = ["#ff0000", "#00ff00", "#0000ff", "#ffffff", "#000000"];
  const d = h("div", { style: { position: "fixed", inset: 0, zIndex: 99 } }); document.body.append(d);
  colors.forEach((c, i) => setTimeout(() => (d.style.background = c), i * 900));
  setTimeout(() => d.remove(), colors.length * 900);
}

function logs() {
  if (!S.logs.length) return h("div.empty", "Nothing logged yet.");
  return h("div.scroll.grow", ...S.logs.slice(0, 150).map((l) => h("div.svc", led(l.level === "error" ? "fault" : l.level === "warn" ? "warn" : ""),
    h("span.num.small.dim", { style: { width: "70px" } }, l.ts), h("span.name", { style: { whiteSpace: "normal" } }, l.msg))));
}

async function scanWifi() { wifi = null; page.update(S.state, new Set(["*"])); try { wifi = (await api("/api/wifi")).networks; } catch (e) { wifi = []; toast(e.message, "danger"); } page.update(S.state, new Set(["*"])); }

function paintKeys() {
  const theme = localStorage.getItem("md-theme") || "auto";
  keys.replaceChildren(
    tab === "wifi" ? h("button.pad", { onclick: scanWifi }, "Scan again") : null,
    h("button.pad.ghost", { onclick: () => api("/api/display/sleep", {}) }, "Sleep screen"),
    h("button.pad.ghost", { onclick: async () => {
      const t = await pick("Screen colours", [["auto", "Follow the clock"], ["day", "Day"], ["night", "Night"]], theme);
      if (!t) return; t === "auto" ? localStorage.removeItem("md-theme") : localStorage.setItem("md-theme", t);
      document.documentElement.dataset.theme = t === "night" || (t === "auto" && (new Date().getHours() >= 19 || new Date().getHours() < 7)) ? "night" : "";
      paintKeys();
    } }, `Colours: ${theme}`),
    h("button.pad.ghost", { onclick: async () => { if (await confirmBox("Download and install the latest MatterDesk from GitHub?", "Update")) api("/api/ota", {}); } }, "Update"),
    h("div.spacer"),
    h("button.pad.danger", { onclick: async () => {
      const a = await pick("Power", [["restart-desk", "Restart the desk app"], ["reboot", "Restart the Pi"], ["poweroff", "Shut down the Pi"]]);
      if (a && (a === "restart-desk" || await confirmBox(a === "reboot" ? "Restart the Pi now?" : "Shut down the Pi? You will need to unplug it to start again.", a === "reboot" ? "Restart" : "Shut down", { danger: true }))) api(`/api/power/${a}`, {});
    } }, "Power"));
}

const page = {
  id: "system", label: "System", des: "U9", title: "System",
  topics: ["pi", "meta", "brain"],
  mount(root, k, opts) {
    keys = k; if (opts.tab) tab = opts.tab;
    els = { tabs: h("div.tabs"), body: h("div.col.grow") };
    root.append(h("div.page", els.tabs, els.body));
    unwatch = watch(["logs"], () => tab === "logs" && page.update(S.state, new Set(["logs"])));
    if (tab === "wifi") scanWifi();
  },
  unmount() { unwatch && unwatch(); },
  update(st, changed) {
    if (changed && !changed.has("*") && tab !== "pi" && !changed.has("logs")) return;   // 1 s telemetry only matters on This Pi
    put(els.tabs, tab, () => TABS.map(([id, l]) => h(`button.pad${tab === id ? "" : ".ghost"}`, { onclick: () => { tab = id; if (id === "wifi" && !wifi) scanWifi(); page.update(S.state, new Set(["*"])); } }, l)));
    const sc = els.body.querySelector(".scroll")?.scrollTop || 0;
    if (put(els.body, [tab, st.pi, st.meta, wifi, results, S.logs.length], () => ({ pi: () => pi(st), wifi: wifiTab, tests, logs })[tab]())) {
      const s2 = els.body.querySelector(".scroll"); if (s2) s2.scrollTop = sc;
    }
    if (keys._tab !== tab) { keys._tab = tab; paintKeys(); }
  },
};
export default page;
