"""Shared small helpers used by backends."""

from __future__ import annotations

from ..core import util


def has_warp() -> bool:
    return util.have("warp-cli")


def has_wireguard_linux() -> bool:
    return util.have("wg-quick") and util.have("wg")


def has_windows_wireguard() -> bool:
    if not util.is_windows():
        return False
    import shutil
    from pathlib import Path
    if shutil.which("wireguard.exe"):
        return True
    for cand in (
        r"C:\Program Files\WireGuard\wireguard.exe",
        r"C:\Program Files (x86)\WireGuard\wireguard.exe",
    ):
        if Path(cand).exists():
            return True
    return False


def executable(name: str) -> str:
    """Find a binary, covering the official install path on Windows."""
    import shutil
    from pathlib import Path
    exe = shutil.which(name)
    if exe:
        return exe
    if util.is_windows():
        for cand in (
            rf"C:\Program Files\WireGuard\{name}",
            rf"C:\Program Files (x86)\WireGuard\{name}",
        ):
            if Path(cand).exists():
                return cand
    raise RuntimeError(f"{name} not found on PATH")


def available() -> dict:
    info = {"platform": ("windows" if util.is_windows() else
                         ("macos" if util.is_mac() else "linux"))}
    if util.is_linux():
        import platform
        info["kernel"] = platform.release()
    info["warp"] = has_warp()
    info["wireguard_linux"] = has_wireguard_linux()
    info["wireguard_go"] = util.have("wireguard-go")
    info["wireguard_windows"] = has_windows_wireguard()
    info["nft"] = util.have("nft")
    info["iptables"] = util.have("iptables")
    info["ip6tables"] = util.have("ip6tables")
    info["resolvectl"] = util.have("resolvectl")
    info["resolvconf"] = util.have("resolvconf")
    info["cryptography"] = has_cryptography()
    info["wgcf"] = util.have("wgcf")
    return info


def has_cryptography() -> bool:
    try:
        import cryptography  # noqa: F401
        return True
    except Exception:
        return False


def tunnel_state(interface: str) -> dict:
    """Gateway used by both backends to normalize a status report."""
    return {"interface": interface, "up": False, "egress": util.egress_ips()}