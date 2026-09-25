"""Paths, platform detection, subprocess helpers, logging, egress probing.

Everything here is pure stdlib so the client runs anywhere Python 3.9+ does.
"""
from __future__ import annotations

import logging
import os
import shutil
import subprocess
import sys
import time
import urllib.request
from datetime import datetime
from pathlib import Path

APP_NAME = "yalevpn"

LOG: logging.Logger | None = None


def is_windows() -> bool:
    return os.name == "nt"


def is_linux() -> bool:
    return os.name == "posix" and not sys.platform.startswith("darwin")


def is_mac() -> bool:
    return sys.platform.startswith("darwin")


def is_root() -> bool:
    if is_windows():
        try:
            import ctypes
            return bool(ctypes.windll.shell32.IsUserAnAdmin())
        except Exception:
            return False
    return os.geteuid() == 0


def config_home() -> Path:
    if is_windows():
        base = os.environ.get("APPDATA") or (Path.home() / "AppData" / "Roaming")
        return Path(base) / "YaleVPN"
    return Path.home() / ".config" / "yalevpn"


def log_home() -> Path:
    if is_windows():
        return Path(os.environ.get("LOCALAPPDATA") or Path.home() / "AppData") / "YaleVPN"
    return Path.home() / ".local" / "state" / "yalevpn"


def data_home() -> Path:
    if is_windows():
        base = os.environ.get("LOCALAPPDATA") or Path.home() / "AppData" / "Local"
        return Path(base) / "YaleVPN"
    # FHS-compliant var location; falls back to config dir on minimal systems.
    var = Path(os.environ.get("XDG_STATE_HOME") or Path.home() / ".local" / "state")
    return var / "yalevpn"


def ensure_dirs() -> None:
    for d in (config_home() / "profiles", config_home() / "vault",
              data_home(), log_home()):
        d.mkdir(parents=True, exist_ok=True)


def logger() -> logging.Logger:
    global LOG
    if LOG is not None:
        return LOG
    LOG = logging.getLogger(APP_NAME)
    LOG.setLevel(logging.INFO)
    if not LOG.handlers:
        _fmt = logging.Formatter("%(asctime)s %(levelname)s %(message)s")
        sh = logging.StreamHandler()
        sh.setFormatter(_fmt)
        LOG.addHandler(sh)
        fh = logging.FileHandler(log_home() / "yalevpn.log", encoding="utf-8")
        fh.setFormatter(_fmt)
        LOG.addHandler(fh)
    return LOG


def log(level: str, msg: str) -> None:
    getattr(logger(), level.lower())(msg)


def have(name: str) -> bool:
    return shutil.which(name) is not None


def which(name: str) -> str | None:
    return shutil.which(name)


def _creationflags() -> int:
    if is_windows():
        return getattr(subprocess, "CREATE_NO_WINDOW", 0) | 0x08000000
    return 0


def run(cmd, check: bool = False, timeout: int = 120, env=None,
        input_text: str | None = None) -> subprocess.CompletedProcess:
    """Run a commandlist safely. Returns CompletedProcess (never raises
    unless check=True)."""
    if isinstance(cmd, str):
        cmd = cmd.split()
    proc = subprocess.run(
        cmd,
        input=input_text,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=timeout,
        env=env,
        creationflags=_creationflags(),
    )
    if check:
        proc.check_returncode()
    return proc


def run_out(cmd, timeout: int = 120) -> str:
    """Run and return combined stdout. Empty string on any failure."""
    try:
        p = run(cmd, timeout=timeout)
        out = (p.stdout or "") + (p.stderr or "")
        return out.strip()
    except Exception:
        return ""


def need_root(explain: str):
    """Raise RuntimeError if not root/administrator. Auto-sudo on Linux."""
    if is_root():
        return
    if is_windows():
        raise RuntimeError(
            "administrator rights required — run this from an elevated "
            "terminal (right-click -> Run as administrator)" + (f" ({explain})" if explain else "")
        )
    # Linux: passwordless sudo is common; instruct otherwise.
    if not have("sudo"):
        raise RuntimeError(f"root required ({explain}). Run with sudo.")
    try:
        p = run(["sudo", "-n", "true"])
        if p.returncode != 0:
            raise RuntimeError(f"root required ({explain}). Re-run with sudo.")
    except Exception as e:  # sudo missing
        raise RuntimeError(f"root required ({explain}). Re-run with sudo.") from e


def sudo(cmd) -> str:
    """Run a privileged command (auto-prefixed with sudo on Linux)."""
    if is_windows():
        return run_out(cmd)
    if is_root():
        return run_out(cmd)
    return run_out(["sudo", "-n", *cmd])


def http_get(url: str, timeout: int = 8) -> str:
    try:
        req = urllib.request.Request(url, headers={"User-Agent": APP_NAME})
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.read().decode("utf-8", "replace").strip()
    except Exception:
        return ""


def _curl_family(family: str) -> str:
    """Use curl with an explicit IP family so the probe cannot slip to the
    other address family (urllib would happily use IPv6 for the v4 probe)."""
    if have("curl"):
        try:
            p = subprocess.run(
                ["curl", "-s", "--max-time", "8", f"-{family}",
                 "https://api64.ipify.org"],
                stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                timeout=12, creationflags=_creationflags(),
            )
            out = (p.stdout or b"").decode("utf-8", "replace").strip()
            if out and (":" in out) == (family == "6"):
                return out
        except Exception:
            pass
    return ""


def egress_v4() -> str:
    if is_windows():
        s = _curl_family("4")
        if s:
            return s
    for url in ("https://api.ipify.org", "https://api64.ipify.org"):
        s = http_get(url)
        if s and ":" not in s:  # IPv4 literal
            return s
        s = ""
    return s


def egress_v6() -> str:
    if is_windows():
        s = _curl_family("6")
        if s:
            return s
    for url in ("https://api6.ipify.org", "https://api64.ipify.org"):
        s = http_get(url)
        if s and ":" in s:
            return s
        s = ""
    return s


def egress_ips() -> dict:
    return {"v4": egress_v4(), "v6": egress_v6()}


def now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def interface_exists(name: str) -> bool:
    if not name:
        return False
    if is_windows():
        return f"WireGuardTunnel${name}" in run_out(
            ["sc", "query", f"WireGuardTunnel${name}"]
        ).lower() or run_out(["sc", "query", f"WireGuardTunnel${name}"]).startswith("SERVICE_NAME")
    p = run(["ip", "link", "show", name])
    return p.returncode == 0


def ts() -> str:
    return time.strftime("%Y-%m-%d %H:%M:%S")