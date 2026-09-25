"""Kill switch — fail-closed leak protection while a tunnel is up.

Linux  : dedicated nftables/iptables chain ``YALEVPN`` on OUTPUT that
          drops everything except: established/related connections, traffic
          toward configured DNS servers (UDP/TCP 53), the tunneled
          interface, and loopback. Applied with real root powers; removed
          cleanly on ``off``.
Windows: an Advanced Firewall rule set (``YaleVPN Kill Switch``) that
          blocks all outbound traffic except toward the WireGuard endpoint
          and DNS — forcing non-tunneled apps into the tunnel.

Never modifies NAT/POSTROUTING. Idempotent on/off.
"""
from __future__ import annotations

import re
import shutil

from ..core import util

CHAIN = "YALEVPN"


class KillSwitch:
    def __init__(self, tun_interface: str = "", dns_servers: list | None = None,
                 endpoints: list | None = None):
        self.tun = tun_interface or "CloudflareWARP"
        self.dns = dns_servers or ["1.1.1.1", "1.0.0.1"]
        self.endpoints = endpoints or []

    # -- linux -------------------------------------------------------------
    def linux_status(self) -> dict:
        if util.have("nft"):
            out = util.sudo(["nft", "list", "table", "ip", "filter"])
            low = out.lower()
            enabled = (f"chain {CHAIN}".lower() in low) and (
                "hook output" in low or "jump" in low)
            return {"enabled": bool(enabled), "area": "OUTPUT", "tool": "nft"}
        if util.have("iptables"):
            out = util.sudo(["iptables", "-S"])
            active = f"-A OUTPUT -j {CHAIN}" in out or \
                f"-I OUTPUT -j {CHAIN}" in out or \
                f"-A OUTPUT -j {CHAIN.lower()}" in out.lower()
            return {"enabled": bool(active), "area": "OUTPUT", "tool": "iptables"}
        return {"enabled": False, "area": "-", "tool": "missing"}

    def linux_on(self) -> dict:
        util.need_root("enabling the nftables/iptables kill switch")
        if util.have("nft"):
            self._nft_on()
        elif util.have("iptables"):
            self._ipt_on()
        else:
            raise RuntimeError("neither nft nor iptables installed "
                               "(apt install nftables iptables)")
        return self.linux_status()

    def linux_off(self) -> dict:
        util.need_root("disabling the kill switch")
        if util.have("nft"):
            out = util.sudo(["nft", "list", "table", "ip", "filter"])
            if f"chain {CHAIN}".lower() in out.lower():
                util.sudo(["nft", "delete", "chain", "ip", "filter", CHAIN])
        if util.have("iptables"):
            for ipt in ("iptables", "ip6tables"):
                if not util.have(ipt):
                    continue
                util.sudo([ipt, "-D", "OUTPUT", "-j", CHAIN])
                if f"Chain {CHAIN}".lower() in util.sudo([ipt, "-S"]).lower():
                    util.sudo([ipt, "-F", CHAIN])
                    util.sudo([ipt, "-X", CHAIN])
        return self.linux_status()

    def _nft_rules(self) -> str:
        rules = [f"chain {CHAIN} {{",
                 "  type filter hook output priority 100; policy drop;"]
        for dns in self.dns:
            rules.append(f"  ip daddr {dns} udp dport 53 accept")
            rules.append(f"  ip daddr {dns} tcp dport 53 accept")
        rules.append("  ct state established,related accept")
        rules.append("  meta oifname lo accept")
        rules.append(f"  oifname {self.tun} accept")
        if self.endpoints:
            for ip in {_host_of(ep) for ep in self.endpoints if _host_of(ep)}:
                rules.append(f"  ip daddr {ip} accept")
        rules.append("  counter drop")
        rules.append("}")
        return "\n".join(rules)

    def _nft_on(self) -> None:
        cur = util.sudo(["nft", "list", "table", "ip", "filter"])
        if f"chain {CHAIN}" in cur.lower():
            util.sudo(["nft", "delete", "chain", "ip", "filter", CHAIN])
        script = f"table ip filter {{\n{self._nft_rules()}\n}}"
        _, script_path = _write_temp(script)
        try:
            util.sudo(["nft", "-f", script_path])
        finally:
            _rm_temp(script_path)

    def _ipt_on(self) -> None:
        for ipt in ("iptables", "ip6tables"):
            if not util.have(ipt):
                continue
            util.sudo([ipt, "-N", CHAIN])
            util.sudo([ipt, "-F", CHAIN])
            for dns in self.dns:
                util.sudo([ipt, "-A", CHAIN, "-d", dns, "-p", "udp",
                           "--dport", "53", "-j", "ACCEPT"])
                util.sudo([ipt, "-A", CHAIN, "-d", dns, "-p", "tcp",
                           "--dport", "53", "-j", "ACCEPT"])
            util.sudo([ipt, "-A", CHAIN, "-m", "conntrack", "--ctstate",
                       "ESTABLISHED,RELATED", "-j", "ACCEPT"])
            util.sudo([ipt, "-A", CHAIN, "-i", "lo", "-j", "ACCEPT"])
            util.sudo([ipt, "-A", CHAIN, "-o", self.tun, "-j", "ACCEPT"])
            for ep in self.endpoints:
                ip = _host_of(ep)
                if ip:
                    util.sudo([ipt, "-A", CHAIN, "-d", ip, "-j", "ACCEPT"])
            util.sudo([ipt, "-A", CHAIN, "-j", "DROP"])
            util.sudo([ipt, "-I", "OUTPUT", "1", "-j", CHAIN])

    # -- windows -----------------------------------------------------------
    def windows_on(self) -> dict:
        util.need_root("creating the Victoria firewall kill-switch rules")
        util.run(["netsh", "advfirewall", "reset", "outbound"])
        # block branch established traffic is controlled by per-rule action.
        util.run(["netsh", "advfirewall", "firewall", "delete", "rule",
                  "name=YaleVPN Kill Switch"])
        util.run(["netsh", "advfirewall", "firewall", "add", "rule",
                  "name=YaleVPN Kill Switch", "dir=out",
                  "action=block", "enable=yes",
                  "profile=any", "protocol=any"])
        for ep in self.endpoints:
            ip = _host_of(ep)
            if not ip:
                continue
            util.run(["netsh", "advfirewall", "firewall", "add", "rule",
                      "name=YaleVPN Allow Tunnel", "dir=out",
                      "action=allow", "enable=yes",
                      "profile=any", "protocol=any", f"remoteip={ip}"])
        for dns in self.dns:
            util.run(["netsh", "advfirewall", "firewall", "add", "rule",
                      "name=YaleVPN Allow DNS", "dir=out",
                      "action=allow", "enable=yes",
                      "profile=any", "protocol=udp",
                      f"remoteip={dns}:53"])
        return {"enabled": True, "area": "all-profiles", "tool": "netsh"}

    def windows_off(self) -> dict:
        util.need_root("removing the YaleVPN firewall rules")
        util.run(["netsh", "advfirewall", "firewall", "delete", "rule",
                  "name=YaleVPN Kill Switch"])
        util.run(["netsh", "advfirewall", "firewall", "delete", "rule",
                  "name=YaleVPN Allow Tunnel"])
        util.run(["netsh", "advfirewall", "firewall", "delete", "rule",
                  "name=YaleVPN Allow DNS"])
        return {"enabled": False, "area": "-", "tool": "netsh"}

    # -- dispatch ----------------------------------------------------------
    def on(self) -> dict:
        return self.windows_on() if util.is_windows() else self.linux_on()

    def off(self) -> dict:
        return self.windows_off() if util.is_windows() else self.linux_off()

    def status(self) -> dict:
        return self.windows_status() if util.is_windows() else self.linux_status()

    def windows_status(self) -> dict:
        out = util.run_out(["netsh", "advfirewall", "firewall", "show", "rule",
                            "name=YaleVPN Kill Switch"])
        return {"enabled": bool(re.search(r"Enabled:\s*Yes", out)),
                "area": "all-profiles", "tool": "netsh"}


def _host_of(endpoint: str) -> str:
    ep = re.sub(r"[\[\]]", "", endpoint or "")
    ip = ep.split(":")[0]
    if ip and " " not in ip:
        return ip
    return ""


def _write_temp(text: str):
    import tempfile
    f = tempfile.NamedTemporaryFile("w", suffix=".nft", delete=False,
                                    encoding="utf-8")
    f.write(text)
    f.close()
    return True, f.name


def _rm_temp(path: str):
    import os
    try:
        os.unlink(path)
    except OSError:
        pass