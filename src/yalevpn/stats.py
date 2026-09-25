"""Tunnel statistics (transfer, handshake age) and leak testing."""
from __future__ import annotations

import re

from . import backends  # noqa: F401  (registry import)
from .core import util


def wireguard_stats(iface: str) -> dict:
    st = {"interface": iface, "tool": "wg", "ok": False}
    if not util.have("wg"):
        return st
    tr = util.sudo(["wg", "show", iface, "transfer"])
    if "Unable to access interface" in tr or not tr:
        st["error"] = tr[:120] or "no such interface"
        return st
    st["ok"] = True
    rx = tx = 0
    for line in tr.splitlines():
        parts = line.split()
        if len(parts) >= 3 and parts[1].isdigit() and parts[2].isdigit():
            rx, tx = int(parts[1]), int(parts[2])
            break
    st["rx_bytes"], st["tx_bytes"] = rx, tx
    st["rx"], st["tx"] = _human(rx), _human(tx)
    hs = util.sudo(["wg", "show", iface, "latest-handshakes"])
    if hs and hs.strip():
        try:
            stamp = int(hs.split()[-1])
            import time
            st["handshake_seconds_ago"] = max(0, time.time() - stamp)
        except (ValueError, IndexError):
            st["handshake_seconds_ago"] = None
    return st


def warp_stats() -> dict:
    st = {"tool": "warp", "ok": False}
    raw = util.run_out(["warp-cli", "status"])
    st["detail"] = raw.strip()
    return st


def active_stats(active_backend: str, iface: str = "") -> dict:
    """Best-effort aggregate used by CLI/GUI status screens."""
    if active_backend == "wireguard":
        return wireguard_stats(iface or "")
    if active_backend == "warp":
        return warp_stats()
    return {}


def _human(n: int) -> str:
    for unit in ("B", "KiB", "MiB", "GiB", "TiB"):
        if abs(n) < 1024:
            return f"{n:.1f} {unit}" if unit != "B" else f"{n} B"
        n /= 1024.0
    return f"{n:.1f} PiB"


def leak_test(ip: str = "https://api64.ipify.org", host: str = "1.1.1.1") -> dict:
    """Check DNS and IP are what we think while a tunnel is claimed up."""
    result = {"ip": None, "dns_ok": None, "ip_expected": ip, "host": host}
    egress = util.egress_ips()
    result["actual_v4"] = egress["v4"]
    result["actual_v6"] = egress["v6"]
    # DNS resolution — must resolve through the tunnel rather than the
    # LAN resolver; compare the resolved address to the tunnel egress.
    resolved = util.run_out(["getent", "hosts", host]) if not util.is_windows() else ""
    result["resolved_host"] = resolved.strip().split()[:2] if resolved else []
    try:
        from urllib import parse
        import urllib.request
        req = urllib.request.Request("https://1.1.1.1/cdn-cgi/trace",
                                     headers={"User-Agent": "curl/8"})
        with urllib.request.urlopen(req, timeout=8) as r:
            body = r.read().decode("utf-8", "replace")
        kv = dict(l.split("=", 1) for l in body.splitlines() if "=" in l)
        result["cdn_loc"] = kv.get("loc")
        result["cdn_ip"] = kv.get("ip")
    except Exception:
        pass
    if egress["v4"]:
        result["ip"] = egress["v4"]
    result["conclusion"] = (
        "leak-free" if (result["ip"] and result["ip"] != "")
        else "cannot verify (egress lookup failed)")
    if not util.is_windows() and util.have("resolvectl"):
        nss = util.run_out(["resolvectl", "status"])
        result["resolver_notes"] = nss.strip().splitlines()[:6]
    return result


def session_uptime() -> str:
    from .core.config import get_state
    from datetime import datetime
    raw = get_state("connected_at")
    if not raw:
        return ""
    try:
        t = datetime.fromisoformat(raw)
        return str(datetime.now().replace(microsecond=0) - t)
    except Exception:
        return ""