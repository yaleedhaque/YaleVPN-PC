"""YaleVPN — desktop WireGuard / WARP VPN client for Linux and Windows.

A single Python codebase (stdlib + optional `cryptography`) that manages
WireGuard tunnel profiles and Cloudflare WARP on both platforms:

  * Linux: kernel WireGuard via wg-quick/wg, warp-cli, nftables/iptables
    kill switch, systemd-resolved / resolv.conf DNS.
  * Windows: official WireGuard client automation (wireguard.exe tunnel
    services), netsh firewall kill switch, netsh DNS.

Everything is offline-first: keys are generated on-device, no account, no
cloud control plane. Optional AES-GCM encrypted vault for private keys.
"""

__version__ = "2.0.0"
APP_NAME = "YaleVPN"
APP_LONG = "YaleVPN-PC"