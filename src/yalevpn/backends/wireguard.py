"""WireGuard backend.

Linux   : kernel tunnel via wg-quick / wg (wireguard-tools). The config
          file name determines the interface: ``<data>/interfaces/<name>.conf``.
          Falls back to `wireguard-go` when the kernel module is missing.
Windows : the official WireGuard client's automation interface:
            * install  -> ``wireguard.exe /installtunnelservice <conf>``
                           (creates the ``WireGuardTunnel$<name>`` service)
            * uninstall-> ``wireguard.exe /uninstalltunnelservice <name>``
            * status   -> ``sc query WireGuardTunnel$<name>``
          Requires the free official WireGuard client for Windows
          (https://www.wireguard.com/install/). Elevation required.
"""
from __future__ import annotations

import shutil
from pathlib import Path

from ..core import util
from . import _wireguard_util as wgutil


class WireGuardBackend:
    kind = "wireguard"

    def __init__(self, data_dir: Path):
        self.data = data_dir

    # -- path helpers ------------------------------------------------------
    def conf_path(self, name: str) -> Path:
        d = self.data / "interfaces"
        d.mkdir(parents=True, exist_ok=True)
        return d / f"{name}.conf"

    # -- availability ------------------------------------------------------
    def available(self) -> bool:
        if util.is_windows():
            return wgutil.executable("wireguard.exe") is not None
        return wgutil.executable("wg-quick") is not None or util.have("wireguard-go")

    # -- api ---------------------------------------------------------------
    def up(self, name: str, conf_text: str | None = None) -> dict:
        name = wgutil.sanitize(name)
        util.log("info", f"wg up {name}")
        if util.is_windows():
            return self._up_windows(name, conf_text)
        return self._up_linux(name, conf_text)

    def down(self, name: str) -> dict:
        name = wgutil.sanitize(name)
        util.log("info", f"wg down {name}")
        if util.is_windows():
            return self._down_windows(name)
        return self._down_linux(name)

    def status(self, name: str) -> dict:
        name = wgutil.sanitize(name)
        st = {"kind": "wireguard", "interface": name, "up": None}
        try:
            if util.is_windows():
                st = self._status_windows(name)
            else:
                st = self._status_linux(name)
        finally:
            st.setdefault("egress", util.egress_ips())
        return st

    # -- linux -------------------------------------------------------------
    def _up_linux(self, name, conf_text) -> dict:
        path = self.conf_path(name)
        if conf_text is not None:
            path.write_text(conf_text, encoding="utf-8")
            try:
                path.chmod(0o600)
            except Exception:
                pass
        cmd = wgutil.executable("wg-quick")
        p = util.run([cmd, "up", str(path)], timeout=40)
        if p.returncode != 0:
            util.log("error", f"wg-quick up failed: {p.stderr}")
            raise RuntimeError(f"wg-quick up failed: {p.stderr.strip() or p.stdout.strip()}")
        util.log("info", f"wg-quick up {name} ok")
        return self.status(name)

    def _down_linux(self, name) -> dict:
        path = self.conf_path(name)
        cmd = wgutil.executable("wg-quick")
        p = util.run([cmd, "down", str(path)], timeout=40)
        if p.returncode != 0:
            util.log("error", f"wg-quick down failed: {p.stderr}")
            raise RuntimeError(f"wg-quick down failed: {p.stderr.strip() or p.stdout.strip()}")
        return self.status(name)

    def _status_linux(self, name) -> dict:
        wg = wgutil.executable("wg")
        p = util.sudo([wg, "show", name])
        up = ("interface:" in p) or ("public key:" in p)
        st = {"kind": "wireguard", "interface": name, "up": False}
        if up and p:
            st["up"] = True
            st["detail"] = p
            conf = self._linux_conf(name)
            st["endpoint"] = conf.get("endpoint")
        return st

    def _linux_conf(self, name) -> dict:
        conf = {}
        wg = wgutil.executable("wg")
        out = util.sudo([wg, "show", name, "endpoint"])
        for line in out.splitlines():
            parts = line.split()
            if len(parts) >= 3 and parts[0].startswith("peer") and parts[1] == "endpoint":
                conf["endpoint"] = parts[2]
                break
        return conf

    # -- windows -----------------------------------------------------------
    def _wireguard_exe(self) -> str:
        exe = shutil.which("wireguard.exe") or None
        if exe:
            return exe
        for cand in (r"C:\Program Files\WireGuard\wireguard.exe",
                     r"C:\Program Files (x86)\WireGuard\wireguard.exe"):
            if Path(cand).exists():
                return cand
        raise RuntimeError(
            "the official WireGuard client for Windows is required — "
            "install it from https://www.wireguard.com/install/")

    def _up_windows(self, name, conf_text) -> dict:
        util.need_root("installing the WireGuard tunnel service")
        exe = self._wireguard_exe()
        path = self.conf_path(name)
        if conf_text is not None:
            path.write_text(conf_text, encoding="utf-8")
        # installtunnelservice requires the fully-qualified conf path
        p = util.run([exe, "/installtunnelservice", str(path)], timeout=60)
        if p.returncode != 0:
            util.log("error", f"wireguard /installtunnelservice failed: {p.stdout or p.stderr}")
            raise RuntimeError(
                f"wireguard install service failed: "
                f"{(p.stderr or p.stdout or '').strip()}")
        util.log("info", f"wireguard tunnel service installed: {name}")
        return self.status(name)

    def _down_windows(self, name) -> dict:
        util.need_root("removing the WireGuard tunnel service")
        exe = self._wireguard_exe()
        p = util.run([exe, "/uninstalltunnelservice", name], timeout=60)
        if p.returncode != 0:
            util.log("error", f"wireguard /uninstalltunnelservice failed: {p.stdout or p.stderr}")
            # service may already be gone — not fatal
        return self.status(name)

    def _status_windows(self, name) -> dict:
        svc = f"WireGuardTunnel${name}"
        q = util.run(["sc", "query", svc], timeout=20)
        up = "RUNNING" in (q.stdout or "")
        st = {"kind": "wireguard", "interface": name, "up": up}
        if up:
            exe = self._wireguard_exe()
            s = util.run([exe, "/showconf", name], timeout=20)
            st["detail"] = (s.stdout or "").strip()
        return st