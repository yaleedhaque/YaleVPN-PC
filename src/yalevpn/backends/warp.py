"""Cloudflare WARP backend (warp-cli daemon, Linux primarily).

Also wires up `wgcf`-based WARP-profile bootstrapping and exporting a
plain WARP WireGuard profile for use by any platform (including Windows),
mirroring the YaleVPN Android app's WARP import flow.

Rotation: WARP hands out a fresh consumer egress IP when the device
registration is deleted and re-created. Success is verified by comparing
egress IPv4/IPv6 before/after.
"""
from __future__ import annotations

import re
from pathlib import Path

from ..core import profiles, util

WARP_IFACE = "CloudflareWARP"
MEMORY_VAULT = Path.home() / ".config/opencode/shared/memory.md"


class WarpBackend:
    kind = "warp"

    def __init__(self, store: profiles.ProfileStore | None = None):
        self.store = store or profiles.ProfileStore()

    @staticmethod
    def available() -> bool:
        return util.have("warp-cli")

    def _warp(self):
        if not util.have("warp-cli"):
            raise RuntimeError("warp-cli not found (install cloudflare-warp)")
        return "warp-cli"

    # -- daemon state ------------------------------------------------------
    def status(self) -> dict:
        st = {"kind": "warp", "interface": WARP_IFACE, "up": False}
        if not self.available():
            st["error"] = "warp-cli not installed"
            return st
        raw = util.run_out([self._warp(), "status"])
        m = re.search(r"Status update:\s*(\w+)", raw)
        st["detail"] = raw.strip()
        st["up"] = bool(m and m.group(1).lower() == "connected")
        st["registration"] = self.registration()
        st["egress"] = util.egress_ips()
        return st

    def registration(self) -> dict:
        raw = util.run_out([self._warp(), "registration", "show"])
        out = {}
        for k in ("Account type", "ID", "Device ID", "Public key", "Account ID",
                  "License", "Model", "Name"):
            m = re.search(rf"^{re.escape(k)}:\s*(.+)", raw, re.M)
            if m:
                out[k.lower().replace(" ", "_")] = m.group(1).strip()
        return out

    def up(self) -> dict:
        util.log("info", "warp up")
        util.run([self._warp(), "connect"], timeout=20)
        util.run(["sleep", "2"])
        return self.status()

    def down(self) -> dict:
        util.log("info", "warp down")
        util.run([self._warp(), "disconnect"], timeout=20)
        util.run(["sleep", "2"])
        return self.status()

    # -- rotation ----------------------------------------------------------
    def rotate(self, attempts: int = 3, quiet: bool = False) -> dict:
        w = self._warp()
        acct = self._registration_account(w)
        if not acct.startswith("Free"):
            raise RuntimeError(
                f"refusing to rotate: registration is '{acct}' (not Free)")
        before = util.egress_ips()
        util.log("info", f"warp rotate before v4={before['v4']} v6={before['v6']}")
        last = before
        for attempt in range(1, attempts + 1):
            util.run([w, "disconnect"], timeout=20)
            util.run([w, "registration", "delete"], timeout=20)
            util.run([w, "registration", "new"], timeout=30)
            util.run([w, "connect"], timeout=30)
            util.run(["sleep", "5"])
            after = util.egress_ips()
            if after["v4"] != before["v4"] or after["v6"] != before["v6"]:
                util.log("info",
                         f"warp rotate OK attempt={attempt} v4={after['v4']} "
                         f"v6={after['v6']}")
                return {"rotated": True, "attempt": attempt,
                        "before": before, "after": after}
            last = after
        util.log("warning", f"warp rotate WEAK: egress unchanged after "
                            f"{attempts} attempts (shared WARP pool)")
        return {"rotated": False, "attempt": attempts,
                "before": before, "after": last}

    def _registration_account(self, w: str) -> str:
        raw = ""
        for _ in range(6):
            raw = util.run_out([w, "registration", "show"])
            m = re.search(r"Account type:\s*(\S+)", raw)
            if m:
                return m.group(1)
            util.run(["sleep", "1"])
        m = re.search(r"Account type:\s*(\S+)", raw)
        return m.group(1) if m else "unknown"

    # -- profile export / bootstrap ---------------------------------------
    @staticmethod
    def warp_profile_fields() -> tuple[str, str]:
        """Return (private_key, public_key) for the WARP WireGuard profile.

        Retrieved from (in order): env YALEVPN_WARP_PRIVATE_KEY,
        YALEVPN_WARP_PUBLIC_KEY; else the remembered vault line in
        ~/.config/opencode/shared/memory.md (legacy YaleVPN-PC mirror).
        """
        import os
        pk = os.environ.get("YALEVPN_WARP_PRIVATE_KEY", "")
        pub = os.environ.get("YALEVPN_WARP_PUBLIC_KEY", "")
        if pk and pub:
            return pk, pub
        for src in (MEMORY_VAULT,
                    Path.home() / ".config/opencode/shared/memory-full.md"):
            if not src.exists():
                continue
            try:
                lines = src.read_text(encoding="utf-8").splitlines()
            except OSError:
                continue
            try:
                line = next(l for l in lines if "yalevpn-warp-account" in l)
                fields = line.split("**")[-1].strip().lstrip("*: ").split("|")
                for f in fields:
                    if f.startswith("private_key="):
                        pk = f.split("=", 1)[1].strip()
                    elif f.startswith("peer_pub="):
                        pub = f.split("=", 1)[1].strip()
                break
            except (StopIteration, IndexError):
                continue
        if not pk or not pub:
            raise RuntimeError(
                "WARP WireGuard keys not configured. Export keys from the "
                "Cloudflare WARP client / a WARP profile, then set "
                "YALEVPN_WARP_PRIVATE_KEY and YALEVPN_WARP_PUBLIC_KEY, or "
                "run 'yalevpn warp bootstrap' with wgcf installed.")
        return pk, pub

    def warp_profile(self, name: str = "warp") -> profiles.Profile:
        pk, _pub = self.warp_profile_fields()
        raw = util.run_out(["warp-cli", "registration", "show"])
        pp = re.search(r"Public key:\s*(\S+)", raw)
        peer = pp.group(1) if pp else ""
        ep = (os_env("YALEVPN_WARP_ENDPOINT") or
              "engage.cloudflareclient.com:2408")
        p = profiles.generate_profile(
            name=name, private_key=pk, peer_pub=peer or "x", endpoint=ep,
            address="172.16.0.2/32",
            dns=profiles.DEFAULT_DNS, mtu="1280",
            allowed_ips="0.0.0.0/0, ::/0", keepalive="25")
        if not peer:
            p.iface["X-WarpPeerPub"] = "unset"
        return p

    @staticmethod
    def bootstrap_with_wgcf(name: str = "warp") -> profiles.Profile:
        """Generate a fresh WARP WireGuard profile using `wgcf` (the clean
        open-source WARP registration tool). Requires network once; the
        resulting profile then lives on-device like any other."""
        if not util.have("wgcf"):
            raise RuntimeError("'wgcf' not found — install from "
                               "https://github.com/ViRb3/wgcf")
        util.log("info", "wgcf bootstrap: registering a fresh WARP device")
        out_dir = util.data_home() / "wgcf"
        out_dir.mkdir(parents=True, exist_ok=True)
        util.run(["wgcf", "register", "--accept-tos", "-d", out_dir], timeout=120)
        ing = out_dir / "wgcf-account.toml"
        util.run(["wgcf", "generate", "-a", str(ing), "-o", str(out_dir)],
                 timeout=60)
        conf = out_dir / "wgcf-profile.conf"
        text = conf.read_text(encoding="utf-8") if conf.exists() else ""
        if not text:
            raise RuntimeError("wgcf did not produce a profile")
        profile = profiles.parse_conf(text, name=name)
        profile.name = profiles.sanitize_name(name)
        return profile
    # -- end --------------------------------------------------------------


def os_env(k: str) -> str:
    import os
    return os.environ.get(k, "")