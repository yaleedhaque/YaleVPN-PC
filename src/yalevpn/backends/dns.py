"""DNS leak protection.

Linux  : prefer systemd-resolved (`resolvectl dns <iface> 1.1.1.1 1.0.0.1`,
         then revert on down). Fallback: back up /etc/resolv.conf and write
         the tunnel's DNS servers (restored on down).
Windows: set static DNS on the active WireGuard adapter via `netsh`.
Soften the claim: on both platforms, WireGuard/WARP configs already carry
their own DNS — this module only hardens the physical adapter so queries
can't leak before the tunnel is up.
"""
from __future__ import annotations

import shutil
from pathlib import Path

from ..core import util


def _active_physical_linux() -> str:
    """First physical UP interface (tunnel interfaces are excluded)."""
    out = util.run_out(["ip", "-o", "-4", "addr", "show", "up", "up", "scope",
                        "global"])
    for line in out.splitlines():
        parts = line.split()
        if not parts:
            continue
        iface = parts[1]
        if iface == "lo" or iface.startswith(("Cloudflare", "wg", "tun",
                                              "warp", "utun")):
            continue
        return iface
    return ""


class DNS:
    def __init__(self, servers: list | None = None, iface: str = ""):
        self.servers = servers or ["1.1.1.1", "1.0.0.1"]
        self.iface = iface

    def status(self) -> dict:
        if util.is_windows():
            return self._status_windows()
        return self._status_linux()

    # -- linux -------------------------------------------------------------
    def _status_linux(self) -> dict:
        if not self.iface:
            self.iface = _active_physical_linux() or "lo"
        if util.have("resolvectl"):
            out = util.run_out(["resolvectl", "dns", self.iface])
            return {"iface": self.iface, "servers": out.strip(),
                    "tool": "resolvectl", "linux": True}
        if (Path("/etc/resolv.conf").exists()
                and not Path("/etc/resolv.conf").read_text(
                    encoding="utf-8", errors="replace").strip()):
            return {"iface": self.iface, "servers": "(empty)",
                    "tool": "resolv.conf", "linux": True}
        return {"iface": self.iface, "servers": "(managed elsewhere)",
                "tool": "resolv.conf", "linux": True}

    def set(self) -> dict:
        if util.is_windows():
            return self._set_windows()
        return self._set_linux()

    def unset(self) -> dict:
        if util.is_windows():
            return self._unset_windows()
        return self._unset_linux()

    def _set_linux(self) -> dict:
        util.need_root("setting DNS")
        if not self.iface:
            self.iface = _active_physical_linux()
        if not self.iface:
            raise RuntimeError("no physical interface found to pin DNS on")
        if util.have("resolvectl"):
            util.sudo(["resolvectl", "dns", self.iface, *self.servers])
            util.sudo(["resolvectl", "domain", self.iface, ""])
            return {"iface": self.iface, "servers": self.servers,
                    "tool": "resolvectl"}
        # /etc/resolv.conf fallback with atomic backup
        rc = Path("/etc/resolv.conf")
        backup = util.data_home() / "resolv.conf.bak"
        if rc.exists() and not backup.exists():
            backup.write_bytes(rc.read_bytes())
        body = "# managed by yalevpn\n" + "\n".join(
            f"nameserver {s}" for s in self.servers) + "\n"
        rc.write_text(body, encoding="utf-8")
        return {"iface": self.iface, "servers": self.servers,
                "tool": "resolv.conf"}

    def _unset_linux(self) -> dict:
        util.need_root("restoring DNS")
        if util.have("resolvectl"):
            for name in (self.iface,) if self.iface else ():
                util.sudo(["resolvectl", "revert", name])
            return {"iface": self.iface, "servers": "(reverted)",
                    "tool": "resolvectl"}
        backup = util.data_home() / "resolv.conf.bak"
        if backup.exists():
            Path("/etc/resolv.conf").write_bytes(backup.read_bytes())
            backup.unlink()
        return {"iface": self.iface, "servers": "(restored)",
                "tool": "resolv.conf"}

    # -- windows -----------------------------------------------------------
    def _windows_adapter(self) -> str:
        out = util.run_out(["powershell", "-NoProfile", "-Command",
                            "(Get-NetAdapter | Where-Object "
                            "{$_.Status -eq 'Up' -and $_.Name -notmatch "
                            "'.*WireGuard.*'} | Select-Object -First 1).Name"])
        return out.strip()

    def _status_windows(self) -> dict:
        adapter = self._windows_adapter()
        if not adapter:
            return {"iface": "?", "servers": "(unknown)", "tool": "netsh",
                    "windows": True}
        out = util.run_out(["netsh", "interface", "ipv4", "sh", "dnsservers",
                            f"name={adapter}"])
        return {"iface": adapter, "servers": out.strip(), "tool": "netsh",
                "windows": True}

    def _set_windows(self) -> dict:
        util.need_root("setting DNS")
        adapter = self._windows_adapter()
        if not adapter:
            raise RuntimeError("no active adapter found")
        for s in self.servers:
            util.run(["netsh", "interface", "ipv4", "set", "dnsservers",
                      f"name={adapter}", "static", s])
        return {"iface": adapter, "servers": self.servers, "tool": "netsh",
                "windows": True}

    def _unset_windows(self) -> dict:
        util.need_root("restoring DNS")
        adapter = self._windows_adapter()
        if adapter:
            util.run(["netsh", "interface", "ipv4", "set", "dnsservers",
                      f"name={adapter}", "dhcp"])
        return {"iface": adapter or "", "servers": "(dhcp)",
                "tool": "netsh", "windows": True}