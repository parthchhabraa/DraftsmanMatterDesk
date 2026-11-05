"""Local network: neighbour map, MAC blocking, and DPN (the Pi as a Wi-Fi hotspot
that routes through WireGuard). Ported from v5 with shell strings replaced by
argument lists, and the hotspot passphrase moved out of the source."""
from __future__ import annotations

import json
import os
import re
import secrets
import socket
import tempfile
import time

import psutil

from .base import Engine

OUI = {
    "B8:27:EB": "Raspberry Pi", "DC:A6:32": "Raspberry Pi", "E4:5F:01": "Raspberry Pi", "D8:3A:DD": "Raspberry Pi",
    "28:CD:C1": "Raspberry Pi", "AC:84:C6": "TP-Link", "50:C7:BF": "TP-Link", "C4:6E:1F": "TP-Link",
    "A4:2B:B0": "TP-Link", "F0:18:98": "Apple", "3C:22:FB": "Apple", "AC:BC:32": "Apple", "40:B0:34": "Apple",
    "00:16:CB": "Apple", "94:B8:6D": "Samsung", "5C:0A:5B": "Samsung", "A0:07:98": "Samsung",
    "F4:F5:D8": "Google", "00:1A:11": "Google", "3C:5A:B4": "Nest", "18:B4:30": "Nest",
}
MAC_RE = re.compile(r"^([0-9a-f]{2}:){5}[0-9a-f]{2}$", re.I)


def vendor(mac: str) -> str:
    v = OUI.get(mac.upper()[:8])
    if v:
        return v
    try:   # locally administered bit = randomised private address (iPhones, Androids)
        return "Private address" if int(mac[1], 16) & 2 else "Unknown"
    except (ValueError, IndexError):
        return "Unknown"


class NetworkEngine(Engine):
    name = "network"

    def __init__(self, desk):
        super().__init__(desk)
        n = self.cfg.network
        self.state_path = self.cfg.data_dir / "network.json"
        st = {}
        try:
            st = json.loads(self.state_path.read_text())
        except (OSError, ValueError):
            pass
        self.blocked: set[str] = set(st.get("blocked", []))
        self.passphrase = n.dpn_passphrase or st.get("passphrase") or secrets.token_urlsafe(9)
        self.ssid = st.get("ssid", n.dpn_ssid)
        self.force_vpn = st.get("force_vpn", False)
        self.adblock = st.get("adblock", True)
        self.dpn_on = False
        self._last = None
        self._save()

    def _save(self):
        self.state_path.write_text(json.dumps({"blocked": sorted(self.blocked), "passphrase": self.passphrase,
                                               "ssid": self.ssid, "force_vpn": self.force_vpn, "adblock": self.adblock}))

    def start(self):
        self.publish_dpn()
        self.every(15, self.scan)
        self.every(5, self._dpn_tick)

    # ---------- neighbour map ----------
    def scan(self, deep: bool = False):
        if self.demo:
            nodes = [("192.168.1.1", "a4:2b:b0:11:22:33", "router"), ("192.168.1.7", "f0:18:98:aa:bb:01", "parths-mba"),
                     ("192.168.1.12", "3a:1f:22:90:aa:c1", "iPhone"), ("192.168.1.20", "dc:a6:32:00:11:22", "matterdesk"),
                     ("192.168.1.31", "94:b8:6d:12:34:56", "Unknown"), ("192.168.1.40", "18:b4:30:44:55:66", "nest-mini")]
            self.hub.publish("lan", {"nodes": [{"ip": i, "mac": m, "host": h, "vendor": vendor(m), "blocked": m.upper() in self.blocked}
                                               for i, m, h in nodes], "at": time.time()})
            return
        if deep:
            subnet = self.cfg.network.scan_subnet or f"{self.cfg.network.dpn_subnet}.0/24"
            try:
                self.sh(["nmap", "-sn", subnet], timeout=60)
            except FileNotFoundError:
                self.hub.toast("nmap is not installed: sudo apt install nmap", "warn")
        out = self.sh(["ip", "neigh", "show"]).stdout
        nodes = []
        for line in out.splitlines():
            parts = line.split()
            if "lladdr" not in parts or parts[-1] in ("FAILED", "INCOMPLETE"):
                continue
            ip, mac = parts[0], parts[parts.index("lladdr") + 1]
            if ":" in ip and ip.startswith("fe80"):
                continue
            try:
                host = socket.gethostbyaddr(ip)[0]
            except OSError:
                host = ""
            nodes.append({"ip": ip, "mac": mac, "host": host, "vendor": vendor(mac), "blocked": mac.upper() in self.blocked})
        nodes.sort(key=lambda n: tuple(int(x) if x.isdigit() else 0 for x in n["ip"].split(".")))
        self.hub.publish("lan", {"nodes": nodes, "at": time.time()})

    def block(self, mac: str, on: bool):
        if not MAC_RE.match(mac):
            raise ValueError("bad MAC")
        key = mac.upper()
        if not self.demo:
            rule = ["FORWARD", "-m", "mac", "--mac-source", mac, "-j", "DROP"]
            self.sudo(["iptables", "-I" if on else "-D", *rule])
        (self.blocked.add if on else self.blocked.discard)(key)
        self._save()
        self.hub.note(f"{'Blocked' if on else 'Unblocked'} {mac}")
        self.scan()

    # ---------- DPN hotspot ----------
    def publish_dpn(self, clients=None, rates=(0.0, 0.0), status=None):
        n = self.cfg.network
        self.hub.publish("dpn", {
            "on": self.dpn_on, "status": status or ("routed" if self.dpn_on else "offline"),
            "ssid": self.ssid, "passphrase": self.passphrase,
            "qr": f"WIFI:S:{self.ssid};T:WPA;P:{self.passphrase};;",
            "uplink": n.wg_iface if self.force_vpn else n.wan_iface, "force_vpn": self.force_vpn,
            "adblock": self.adblock, "gateway": f"{n.dpn_subnet}.1",
            "clients": clients or [], "tx": round(rates[0], 1), "rx": round(rates[1], 1),
        })

    def dpn_set(self, on: bool | None = None, force_vpn: bool | None = None, adblock: bool | None = None, ssid: str | None = None):
        if force_vpn is not None:
            self.force_vpn = force_vpn
        if adblock is not None:
            self.adblock = adblock
        if ssid:
            self.ssid = ssid[:32]
        self._save()
        if on is None:
            self.publish_dpn()
            return
        self.publish_dpn(status="starting" if on else "stopping")
        self.spawn(self._dpn_start if on else self._dpn_stop)

    def _write(self, dest: str, text: str):
        with tempfile.NamedTemporaryFile("w", delete=False) as fh:
            fh.write(text)
        self.sudo(["install", "-m", "600", fh.name, dest])
        os.unlink(fh.name)

    def _nat(self, enable: bool):
        n = self.cfg.network
        up = n.wg_iface if self.force_vpn else n.wan_iface
        op = "-A" if enable else "-D"
        self.sudo(["sysctl", "-w", "net.ipv4.ip_forward=1"])
        self.sudo(["iptables", "-t", "nat", op, "POSTROUTING", "-o", up, "-j", "MASQUERADE"])
        self.sudo(["iptables", op, "FORWARD", "-i", n.ap_iface, "-o", up, "-j", "ACCEPT"])
        self.sudo(["iptables", op, "FORWARD", "-i", up, "-o", n.ap_iface, "-m", "state", "--state", "RELATED,ESTABLISHED", "-j", "ACCEPT"])

    def _dpn_start(self):
        n = self.cfg.network
        if self.demo:
            time.sleep(1.2)
            self.dpn_on = True
            self.publish_dpn()
            return
        self._write("/etc/hostapd/hostapd.conf", "\n".join([
            f"interface={n.ap_iface}", "driver=nl80211", f"ssid={self.ssid}", "hw_mode=g", "channel=6",
            "wmm_enabled=1", "auth_algs=1", "wpa=2", f"wpa_passphrase={self.passphrase}",
            "wpa_key_mgmt=WPA-PSK", "rsn_pairwise=CCMP", ""]))
        dns = [f"interface={n.ap_iface}", f"dhcp-range={n.dpn_subnet}.10,{n.dpn_subnet}.100,12h",
               f"dhcp-option=3,{n.dpn_subnet}.1", f"dhcp-option=6,{n.dpn_subnet}.1"]
        if self.adblock:
            dns += [f"address=/{d}/0.0.0.0" for d in ("doubleclick.net", "googlesyndication.com", "googleadservices.com", "app-measurement.com")]
        self._write("/etc/dnsmasq.d/dpn.conf", "\n".join(dns) + "\n")
        self.sudo(["ip", "addr", "flush", "dev", n.ap_iface])
        self.sudo(["ip", "addr", "add", f"{n.dpn_subnet}.1/24", "dev", n.ap_iface])
        self.sudo(["ip", "link", "set", n.ap_iface, "up"])
        self.sudo(["systemctl", "unmask", "hostapd"])
        r1 = self.sudo(["systemctl", "restart", "dnsmasq"])
        r2 = self.sudo(["systemctl", "restart", "hostapd"])
        if self.force_vpn:
            self.sudo(["wg-quick", "up", n.wg_iface])
        if r1.returncode or r2.returncode:
            self.hub.note(f"DPN start failed: {(r1.stderr + r2.stderr).strip()[-200:]}", "error")
            self.publish_dpn(status="error")
            return
        self._nat(True)
        self.dpn_on = True
        self.hub.note("DPN routed")
        self.publish_dpn()

    def _dpn_stop(self):
        if not self.demo:
            self._nat(False)
            self.sudo(["systemctl", "stop", "hostapd", "dnsmasq"])
            if self.force_vpn:
                self.sudo(["wg-quick", "down", self.cfg.network.wg_iface])
        self.dpn_on = False
        self._last = None
        self.hub.note("DPN offline")
        self.publish_dpn()

    def _dpn_tick(self):
        if not self.dpn_on:
            return
        clients = []
        if self.demo:
            clients = [{"mac": "3a:1f:22:90:aa:c1", "ip": f"{self.cfg.network.dpn_subnet}.14", "host": "iPhone"}]
            return self.publish_dpn(clients, (12.0, 88.5))
        try:
            with open("/var/lib/misc/dnsmasq.leases") as fh:
                for line in fh:
                    p = line.split()
                    if len(p) >= 4:
                        clients.append({"mac": p[1], "ip": p[2], "host": p[3] if p[3] != "*" else ""})
        except OSError:
            pass
        c = psutil.net_io_counters(pernic=True).get(self.cfg.network.ap_iface)
        rates = (0.0, 0.0)
        if c:
            now = time.monotonic()
            if self._last:
                tx0, rx0, t0 = self._last
                rates = ((c.bytes_sent - tx0) / 1024 / (now - t0), (c.bytes_recv - rx0) / 1024 / (now - t0))
            self._last = (c.bytes_sent, c.bytes_recv, now)
        self.publish_dpn(clients, rates)
