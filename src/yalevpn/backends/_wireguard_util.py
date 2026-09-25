"""Internal helpers shared by WireGuard backends (kept separate from the
public `core.util` namespace to avoid import cycles)."""
from __future__ import annotations

import shutil
from pathlib import Path

from ..core import util


def executable(name: str) -> str:
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


def sanitize(name: str) -> str:
    import re
    n = re.sub(r"[^a-z0-9_]", "", (name or "").lower()) or "yalevpn"
    return n[:15].rstrip("_") or "yalevpn"