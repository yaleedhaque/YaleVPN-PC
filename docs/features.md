# Feature matrix

Everything is implemented in one Python codebase (`src/yalevpn`) — the same
files run on Linux and Windows. "✔" means implemented; the note column
explains the mechanism or any honest platform caveat.

| Feature | Linux | Windows | Notes / mechanism |
|---|---|---|---|
| WireGuard tunnel (kernel) | ✔ | ✔* | Linux `wg-quick`; Windows via official WireGuard `wireguard.exe` tunnel services |
| WireGuard userspace fallback | ✔ | – | `wireguard-go` when kernel module absent |
| Cloudflare WARP daemon | ✔ | ✔ | `warp-cli` (Windows WARP ships it in recent builds) |
| WARP egress **IP rotation** | ✔ | ✔ | delete + re-register the WARP consumer device; verified before/after |
| WARP-as-WireGuard profile | ✔ | ✔ | `yalevpn warp export` — importable on any platform |
| WARP bootstrap (`wgcf`) | ✔ | ✔ | one-command fresh WARP registration if `wgcf` installed |
| On-device X25519 keygen | ✔ | ✔ | `cryptography`, falls back to `wg` |
| Profile import (file / URL / stdin) | ✔ | ✔ | standard wg-quick `.conf` |
| Profile store (EPM: multiple profiles) | ✔ | ✔ | `~/.config/yalevpn` vs `%APPDATA%\YaleVPN` |
| Default / switch profiles | ✔ | ✔ | `yalevpn default`, mark-default on import |
| Profile edit (DNS/MTU/Addr/Endpoint/…) | ✔ | ✔ | CLI flags |
| Profile export (for phone import) | ✔ | ✔ | `yalevpn export <name>` |
| Optional AES-256-GCM **encrypted vault** | ✔ | ✔ | `YALEVPN_VAULT_PASSWORD` |
| Kill switch (drop non-tunnel outbound) | ✔ | ✔* | nftables/iptables chain on Linux; Adv-Firewall allow-endpoint emulation on Windows *(best-effort documented)* |
| DNS leak protection | ✔ | ✔ | systemd-resolved/resolv.conf on Linux; `netsh` on Windows |
| Leak test | ✔ | ✔ | egress + resolver verification |
| Tunnel statistics | ✔ | ✔ | `wg show transfer`, handshake age, session uptime |
| Auto-connect at logon | ✔ | ✔ | systemd user service vs Task Scheduler |
| Periodic WARP rotation | ✔ | ✔ | systemd timer vs Task Scheduler daily/2h |
| IPv6 awareness | ✔ | ✔ | first-class in status/rotation/leaktest |
| Desktop GUI | ✔ | ✔ | tkinter control panel (`yalevpn gui`) |
| CLI (full parity) | ✔ | ✔ | `/scripts/yalevpn` and `yalevpn.cmd` — automation-friendly |
| Diagnostics | ✔ | ✔ | `yalevpn doctor` (backends, kernel, kill-switch tooling) |
| Zero cloud / zero account | ✔ | ✔ | daemons and keys all local; no control plane |
| Prebuilt binary | – | ✔ | GitHub release `YaleVPN-win64.exe` (PyInstaller) |

`*` — Windows WireGuard requires the free official client installed; the kill
switch there is an honest best-effort emulation (documented in `docs/windows.md`).

## CLI surface

```
yalevpn <command> [args]

TUNNELS      up [profile|warp] · down · status · ip
PROFILES     add <file|url|-> · list · show · edit · remove · export · default · newkey
WARP         warp status|up|down · rotate · warp export · warp bootstrap
PROTECTION   killswitch on|off|status · dns set|restore|status · leaktest
MACHINE      stats · autostart on|off|status · doctor · gui · help
```