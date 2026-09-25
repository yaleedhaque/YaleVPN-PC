"""Auto-start / scheduled rotation.

Linux : systemd user units — `yalevpn-autostart.service` brings the default
        profile (or warp) up for this user at login; `yalevpn-rotate.timer`
        re-rotates a WARP egress IP on a schedule.
Windows: Task Scheduler `schtasks /create ... /sc onlogon` to connect at
        logon, and a second task for periodic WARP rotation.
"""
from __future__ import annotations

from pathlib import Path

from .core import util

UNITS_DIR = Path.home() / ".config/systemd/user"


class AutoStart:
    def __init__(self, binary: str | None = None, target: str | None = None,
                 kind: str = "warp"):
        self.binary = binary or _resolve_binary()
        self.target = target or "warp"  # profile name or 'warp'
        self.kind = "warp" if target == "warp" else "wireguard"

    # -- binary ------------------------------------------------------------
    def _exe(self) -> str:
        return self.binary or _resolve_binary()


def _resolve_binary() -> str:
    import shutil
    exe = shutil.which("yalevpn")
    if exe:
        return exe
    if util.is_windows():
        p = Path.home() / ".yalevpn" / "yalevpn.exe"
        if p.exists():
            return str(p)
    p = Path.home() / ".local" / "bin" / "yalevpn"
    if p.exists():
        return str(p)
    return "yalevpn"


def install_linux(target: str) -> dict:
    exe = _resolve_binary()
    units = UNITS_DIR
    units.mkdir(parents=True, exist_ok=True)
    svc = units / "yalevpn-autostart.service"
    svc.write_text(f"""[Unit]
Description=YaleVPN autostart ({target})
After=network-online.target
Wants=network-online.target

[Service]
Type=oneshot
RemainAfterExit=yes
ExecStart={exe} up {target}
ExecStop={exe} down
Nice=10
Restart=on-failure
RestartSec=15

[Install]
WantedBy=default.target
""")
    timer = units / "yalevpn-rotate.timer"
    timer_svc = units / "yalevpn-rotate.service"
    if target == "warp":
        timer_svc.write_text(f"""[Unit]
Description=YaleVPN WARP IP rotation

[Service]
Type=oneshot
ExecStart={exe} rotate --quiet
TimeoutStartSec=180
Nice=10
Restart=on-failure
RestartSec=90
""")
        timer.write_text(f"""[Unit]
Description=Rotate the YaleVPN WARP egress IP every two hours

[Timer]
OnCalendar=*-*-* 0/2:00:00
Persistent=true

[Install]
WantedBy=timers.target
""")
    util.run(["systemctl", "--user", "daemon-reload"])
    util.run(["systemctl", "--user", "enable", "--now",
              "yalevpn-autostart.service"], timeout=30)
    if target == "warp":
        util.run(["systemctl", "--user", "enable", "--now",
                  "yalevpn-rotate.timer"], timeout=30)
    return status_linux()


def remove_linux() -> dict:
    for name in ("yalevpn-autostart.service",
                 "yalevpn-rotate.service", "yalevpn-rotate.timer"):
        util.run(["systemctl", "--user", "disable", "--now", name], timeout=30)
        p = UNITS_DIR / name
        if p.exists():
            p.unlink()
    util.run(["systemctl", "--user", "daemon-reload"])
    return status_linux()


def status_linux() -> dict:
    autostart = util.run_out(["systemctl", "--user", "is-active",
                              "yalevpn-autostart.service"])
    enabled = util.run_out(["systemctl", "--user", "is-enabled",
                            "yalevpn-autostart.service", "--quiet"])
    timer_state = util.run_out(["systemctl", "--user", "is-active",
                                "yalevpn-rotate.timer"])
    state = "off"
    if autostart in ("active", "activating"):
        state = "active"
    elif enabled.startswith("enabled"):
        state = "enabled"
    return {"autostart": state,
            "rotate_timer": timer_state == "active"}


# ---------------------------------------------------------------- windows --
def install_windows(target: str) -> dict:
    util.need_root("creating scheduled tasks")
    exe = _resolve_binary()
    py = _resolve_python()
    cmdline = f'"{py}" -m yalevpn up {target}' if py else f'"{exe}" up {target}'
    util.run(["schtasks", "/create", "/tn", "YaleVPN Autostart", "/tr",
              cmdline, "/sc", "onlogon", "/rl", "highest", "/f"])
    if target == "warp":
        util.run(["schtasks", "/create", "/tn", "YaleVPN Rotate", "/tr",
                  f'"{exe}" rotate --quiet', "/sc", "daily", "/mo", "2",
                  "/rl", "highest", "/f"])
    return status_windows()


def remove_windows() -> dict:
    util.need_root("deleting scheduled tasks")
    for name in ("YaleVPN Autostart", "YaleVPN Rotate"):
        util.run(["schtasks", "/delete", "/tn", name, "/f"])
    return status_windows()


def status_windows() -> dict:
    return {"autostart": util.run_out(
        ["schtasks", "/query", "/tn", "YaleVPN Autostart"]).strip() != "",
        "rotate_timer": bool(util.run_out(
            ["schtasks", "/query", "/tn", "YaleVPN Rotate"]).strip())}


def _resolve_python() -> str:
    import shutil, sys
    return shutil.which("python") or sys.executable or ""


def install(target: str) -> dict:
    return install_windows(target) if util.is_windows() else install_linux(target)


def remove() -> dict:
    return remove_windows() if util.is_windows() else remove_linux()


def status() -> dict:
    return status_windows() if util.is_windows() else status_linux()