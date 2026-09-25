"""Central helpers for state files, settings and path resolution."""
from __future__ import annotations

import json
from pathlib import Path

from . import util


def state_dir() -> Path:
    return util.data_home() / "state"


def state_file_path(key: str) -> Path:
    d = state_dir()
    d.mkdir(parents=True, exist_ok=True)
    return d / f"{key}.txt"


def set_state(key: str, value: str) -> None:
    state_file_path(key).write_text(value, encoding="utf-8")


def get_state(key: str, default: str = "") -> str:
    p = state_file_path(key)
    if p.exists():
        try:
            return p.read_text(encoding="utf-8").strip()
        except OSError:
            return default
    return default


def clear_state(key: str) -> None:
    p = state_file_path(key)
    if p.exists():
        try:
            p.unlink()
        except OSError:
            pass


def version_banner() -> str:
    from .. import __version__, APP_LONG
    return f"{APP_LONG} v{__version__}"