import { bar, clock as now12, h, hhmm, mins, sk, led } from "../core.js";

const DAYS = ["Sunday", "Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday"];
const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
const go = (id, o) => window.desk.go(id, o);

let els, clockTimer;

function clock() {
  const d = new Date();
  const c = now12(d), [hh, mm] = c.hm.split(":");
  els.time.replaceChildren(hh, h("span.colon", ":"), mm, c.ap ? h("span.ampm", c.ap) : null);
  els.date.textContent = `${DAYS[d.getDay()]} ${d.getDate()} ${MONTHS[d.getMonth()]}`;
}

export default {
  id: "home", label: "Home", des: "U1", title: "Desk",
  topics: ["weather", "study", "timer", "desk", "music", "brain", "devices", "inbox"],
  mount(root) {
    els = {
      time: h("div.time"), date: h("div.date"), wx: h("div.wx"), agenda: h("div.agenda"), goal: h("div.goal"), actions: h("div.actions"),
      next: h("button.li"), music: h("button.li"), brain: h("button.li"), devs: h("button.li"), inbox: h("button.li"),
    };
    els.next.onclick = () => go("desk", { tab: "countdowns" });
    els.music.onclick = () => go("music");
    els.brain.onclick = () => go("brain");
    els.devs.onclick = () => go("devices");
    els.inbox.onclick = () => go("brain", { tab: "inbox" });
    root.append(h("div.page.home",
      h("div.left", els.time, els.date, els.wx, els.agenda, els.goal, els.actions),
      h("div.right", els.next, els.brain, els.music, els.devs, els.inbox)));
    clock(); clockTimer = setInterval(clock, 1000);
  },
  unmount() { clearInterval(clockTimer); },
  update(st) {
    const w = st.weather;
    els.wx.replaceChildren(...(w ? [h("b", `${w.temp}°`), ` ${w.desc}, sunset ${hhmm(w.sunset)}`] : [sk("line", "70%")]));

    const open = (st.desk?.tasks || []).filter((x) => !x.done);
    els.agenda.replaceChildren(...open.slice(0, 3).map((x) => h("button.ag", { onclick: () => go("desk", { tab: "tasks" }) }, h("i"), h("span.ellip", x.text))),
      open.length > 3 ? h("div.faint.small", `and ${open.length - 3} more`) : null);

    const s = st.study, t = st.timer;
    if (s) {
      const pct = Math.min(100, (s.today_min / Math.max(1, s.goal_min)) * 100);
      els.goal.replaceChildren(h("div.lbl", h("span", `${mins(s.today_min)} studied today`), h("span.dim", `goal ${mins(s.goal_min)}`)),
        bar(pct, pct >= 100 ? "ok" : ""));
    } else els.goal.replaceChildren(sk("line"), sk("line", "100%"));
    els.actions.replaceChildren(
      h("button.pad", { onclick: () => go("study") }, t ? `${t.subject} running` : "Start a sprint"),
      h("button.pad.ghost", { onclick: () => go("ask") }, "Ask the brain"));

    const cd = (st.desk?.countdowns || []).find((c) => c.days >= 0);
    els.next.replaceChildren(h("span.k", "Next"), cd
      ? h("div.grow", h("div.big", cd.days === 0 ? "Today" : `${cd.days} days`), h("div.sub.ellip", cd.label))
      : h("div.grow.sub", "Add an exam date in Desk to count down to it"));

    const m = st.music;
    els.music.replaceChildren(h("span.k", "Music"), ...(m && m.track
      ? [h("div.art", { style: { backgroundImage: m.art ? `url("${m.art}")` : "" } }),
        h("div.grow", h("div.ellip", m.track), h("div.sub.ellip", `${m.artist}${m.state === "paused" ? ", paused" : ""}`))]
      : [h("div.grow.sub", !m ? "" : m.state === "needs-auth" ? "Spotify needs a one-time login" : m.state === "unconfigured" ? "Spotify not set up" : "Nothing playing")]));

    const b = st.brain;
    let brainBody;
    if (!b) brainBody = h("div.grow", sk("line", "60%"));
    else if (b.state === "unconfigured") brainBody = h("div.grow.sub", "Add the brain address in desk.toml");
    else if (b.state === "unreachable") brainBody = h("div.grow", h("div", led("fault"), " Unreachable"), h("div.sub", "Server off or Tailscale down"));
    else {
      const all = [...(b.services || []), ...(b.containers || []).map((c) => ({ state: c.state === "running" ? "active" : c.state }))];
      const up = all.filter((x) => x.state === "active").length;
      brainBody = h("div.grow", h("div", led(b.state === "online" ? "ok" : "warn"), ` ${up} of ${all.length} running`),
        h("div.sub.spread", h("span", `CPU ${Math.round(b.host?.cpu ?? 0)}%`), h("span", `RAM ${Math.round(b.host?.ram ?? 0)}%`)));
    }
    els.brain.replaceChildren(h("span.k", "Brain"), brainBody);

    const d = st.devices || {};
    const fmt = (k, label) => d[k] && d[k].battery != null && !d[k].stale ? `${label} ${d[k].battery}%${d[k].charging ? "+" : ""}` : null;
    const parts = [fmt("mac", "Mac"), fmt("iphone", "iPhone"), fmt("ipad", "iPad")].filter(Boolean);
    els.devs.replaceChildren(h("span.k", "Devices"), h("div.grow", parts.length ? h("div.spread", parts.map((x) => h("span", x))) : h("div.sub", "No reports yet. Set up the Mac agent and iPhone shortcut")));

    const items = st.inbox?.items || [];
    const fresh = items.filter((i) => Date.now() / 1000 - i.at < 86400);
    els.inbox.replaceChildren(h("span.k", "Inbox"), h("div.grow",
      fresh.length ? [h("div", `${fresh.length} new today`), h("div.sub.ellip", `Latest from ${items[0].source}: ${items[0].text || items[0].name || items[0].kind}`)]
        : h("div.sub", items.length ? "Nothing new today" : "Photos from Penotron and Anamnis recordings land here")));
  },
};
