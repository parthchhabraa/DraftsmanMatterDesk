import { act, api, bar, glyph, h, hm, pick, sk, toast } from "../core.js";

let els, keys, tick, last, dragging = false;

function progress() {
  const m = last;
  if (!m || !m.duration_ms || !els) return;
  const el = m.progress_ms + (m.state === "playing" ? Date.now() - m.at * 1000 : 0);
  const p = Math.min(m.duration_ms, el);
  els.prog.replaceChildren(bar((p / m.duration_ms) * 100), h("div.row.small.dim", h("span.num", hm(p / 1000)), h("span.grow"), h("span.num", hm(m.duration_ms / 1000))));
}

function volumeSlider(v) {
  const b = bar(v ?? 0);
  const wrap = h("div.slider", { "aria-label": "Volume" }, h("span.small.dim", { style: { width: "64px" } }, "Volume"), b);
  let timer;
  const set = (e) => {
    const r = b.getBoundingClientRect();
    const val = Math.round(Math.max(0, Math.min(1, (e.clientX - r.left) / r.width)) * 100);
    b.firstChild.style.width = `${val}%`;
    clearTimeout(timer); timer = setTimeout(() => api("/api/music/volume", { value: val }).catch((er) => toast(er.message, "danger")), 250);
  };
  wrap.addEventListener("pointerdown", (e) => { dragging = true; wrap.setPointerCapture(e.pointerId); set(e); });
  wrap.addEventListener("pointerup", () => { setTimeout(() => { dragging = false; }, 1500); });
  wrap.addEventListener("pointermove", (e) => { if (e.buttons) set(e); });
  return wrap;
}

export default {
  id: "music", label: "Music", des: "U7", title: "Spotify",
  topics: ["music", "airplay"],
  mount(root, k) {
    keys = k;
    els = { cover: h("div.cover"), info: h("div.col.grow"), prog: h("div"), ctl: h("div.col") };
    root.append(h("div.page.music", els.cover, h("div.col", els.info, els.prog, els.ctl)));
    tick = setInterval(progress, 1000);
  },
  unmount() { clearInterval(tick); },
  update(st) {
    const m = st.music; last = m;
    const ap = st.airplay || {};
    keys.replaceChildren(
      h("div.klabel", "Spotify"),
      h("button.pad.ghost", { disabled: !m?.playlists?.length, onclick: async () => { const p = await pick("Play a playlist", m.playlists); if (p) api("/api/music/playlist", { value: p }); } }, "Playlist"),
      h("button.pad.ghost", { disabled: !m || ["unconfigured", "needs-auth"].includes(m.state), onclick: async (e) => {
        const { devices } = await act(e.currentTarget, () => api("/api/music/devices")) || { devices: [] };
        const d = await pick("Play on", devices, m.device); if (d) api("/api/music/device", { value: d });
      } }, "Output"),
      h("div.spacer"),
      h("div.klabel", "AirPlay"),
      h(`button.pad${ap.state && ap.state !== "off" ? "" : ".ghost"}`, { disabled: !ap.installed, onclick: (e) => act(e.currentTarget, () => api(`/api/airplay/${ap.state === "off" ? "start" : "stop"}`, {})) },
        ap.state === "streaming" ? "Stop mirroring" : ap.state === "waiting" ? "Receiver on" : "Receive AirPlay"),
      ap.state === "streaming" ? h("div.klabel", "Triple-tap the screen to stop") : null);

    if (!m) { els.cover.replaceChildren(); els.info.replaceChildren(sk("line", "80%"), sk("line", "50%")); return; }
    if (["unconfigured", "needs-auth", "error"].includes(m.state)) {
      els.cover.replaceChildren("Spotify");
      els.info.replaceChildren(h("div.empty", m.state === "needs-auth"
        ? [h("b", "One-time login needed. "), "SSH into the Pi and run: python -m desk spotify-auth"]
        : [h("b", "Spotify is not set up. "), "Add your app's client id and secret under [spotify] in config/desk.toml."]));
      els.prog.replaceChildren(); els.ctl.replaceChildren(); return;
    }
    els.cover.style.backgroundImage = m.art ? `url("${m.art}")` : "";
    els.cover.replaceChildren(m.art ? "" : "No art");
    els.info.replaceChildren(...(m.track
      ? [h("div.track", m.track), h("div.dim", m.artist), h("div.small.faint", `${m.album}${m.device ? `, on ${m.device}` : ""}`)]
      : [h("div.track.dim", "Nothing playing"), h("div.small.faint", "Pick a playlist to start")]));
    progress();
    if (dragging) return;
    const c = (action, g, label) => h("button.pad.ghost", { "aria-label": label, onclick: (e) => act(e.currentTarget, () => api(`/api/music/${action}`, {})) }, glyph(g));
    els.ctl.replaceChildren(
      h("div.transport", c("prev", "prev", "Previous"),
        h("button.pad", { "aria-label": "Play or pause", onclick: (e) => act(e.currentTarget, () => api("/api/music/toggle", {})) }, glyph(m.state === "playing" ? "pause" : "play")),
        c("next", "next", "Next")),
      m.volume != null ? volumeSlider(m.volume) : null);
  },
};
