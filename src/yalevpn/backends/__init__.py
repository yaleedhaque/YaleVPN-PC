"""Tunnel backends.

A backend knows how to bring a tunnel up/down and report status on the
current platform. We support:

  * ``wireguard`` — kernel WireGuard via wg-quick/wg on Linux, or the
    official WireGuard Windows client (wireguard.exe tunnel services) on
    Windows. A `wireguard-go` userspace fallback is used on Linux when the
    kernel module is unavailable.
  * ``warp`` — the Cloudflare WARP daemon via the warp-cli controller,
    including public-IP rotation.
"""
from .util import has_wireguard_linux, has_windows_wireguard, has_warp, available  # noqa: F401