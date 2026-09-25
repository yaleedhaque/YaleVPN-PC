# YaleVPN on Windows

The client is Python 3.9+ only — no MSI, no account, no cloud. It drives the
**official WireGuard client for Windows** (which ships `wireguard.exe` tunnel
services) and — if you install it — Cloudflare WARP.

## 1. Prerequisites

| Item | Why | Install |
|---|---|---|
| Python 3.9+ | the client itself | https://www.python.org/downloads/ (tick **Add python.exe to PATH**) |
| WireGuard (official) | Windows tunnel backend | https://www.wireguard.com/install/ |
| Cloudflare WARP (optional) | WARP mode + rotation | https://developers.cloudflare.com/warp-client/setup/windows/ |

## 2. Install

**Elevated** PowerShell (right-click → Run as administrator):

```powershell
powershell -ExecutionPolicy Bypass -File install.ps1
```

`install.ps1` copies the client to `%LocalAppData%\Programs\YaleVPN`, adds
`yalevpn.cmd` to `%SystemRoot%` and PATH, installs `cryptography`, and builds a
self-contained `yalevpn.exe` with PyInstaller when possible (skip with
`-SkipTools`).

Prebuilt binaries are attached to every GitHub **Release** — download
`YaleVPN-win64.exe` and run `yalevpn` from the extracted folder.

## 3. Import a WireGuard profile

```cmd
yalevpn add %USERPROFILE%\Downloads\mirchi.conf --default
yalevpn list
yalevpn up mirchi
```

The **WARP WireGuard profile** also works directly on Windows. Export one from
any Linux WARP machine (or use `yalevpn warp export`):

```cmd
yalevpn add warp-wireguard.conf
yalevpn up warp-wireguard
```

## 4. Usage cheat-sheet

| Command | What it does |
|---|---|
| `yalevpn status` | machine + tunnel + egress |
| `yalevpn up <name>` / `yalevpn down` | connect / disconnect |
| `yalevpn rotate` | fresh WARP egress IP (needs warp-cli) |
| `yalevpn killswitch on` | Advanced-Firewall outbound block (allow tunnel + DNS) |
| `yalevpn dns set` | pin DNS on the physical adapter via `netsh` |
| `yalevpn autostart on --target warp` | Task Scheduler at logon (+2h rotation task) |
| `yalevpn gui` | desktop control panel |
| `yalevpn doctor` | pre-flight diagnostics |

## 5. How the WireGuard backend works on Windows

The official WireGuard client exposes an automation interface used by the
backend:

```
wireguard.exe /installtunnelservice  <absolute path to .conf>   # create tunnel service
wireguard.exe /uninstalltunnelservice <tunnel name>             # remove it
sc query WireGuardTunnel$<name>                                  # status (RUNNING/STOPPED)
wireguard.exe /showconf <name>                                   # current config
```

`yalevpn up` writes the profile to
`%LocalAppData%\YaleVPN\interfaces\<name>.conf`, then installs the tunnel as a
Windows service. `yalevpn down` uninstalls it. Each tunnel is a hardened,
built-in WireGuard Windows service with the dynamic firewall ("tunnel" binding)
WireGuard manages automatically.

## 6. Kill switch on Windows

Windows has no per-app routing kill switch. The backend emulates one with the
Advanced Firewall:

- adds a **YaleVPN Kill Switch** outbound **block-all** rule,
- then allows the WireGuard **endpoint** IPs and DNS,
- removes both on `off` (or a failed tunnel).

Everything non-tunneled is forced through the tunnel while it is active. This
requires elevation and is documented honestly: unlike the nftables version on
Linux it is a *best-effort* enforcement layer, not kernel routing table
manipulation.

## 7. Enabling WARP properly on Windows

Two options:

1. **Install the Cloudflare WARP client.** Newer builds expose `warp-cli` on
   PATH; the `warp` backend then works identically to Linux, including
   `yalevpn rotate`.
2. **WARP-as-WireGuard (works with only the WireGuard backend).** Use a valid
   WARP WireGuard `.conf` (exported via `yalevpn warp export` on a Linux box,
   or generated once with `wgcf`) and import it like any profile. Handshakes
   against Cloudflare's `engage.cloudflareclient.com:2408` work through the
   official Windows WireGuard client.

## 8. Uninstall

```cmd
yalevpn autostart off
schtasks /delete /tn "YaleVPN Autostart" /f
schtasks /delete /tn "YaleVPN Rotate" /f
rmdir /s /q %LocalAppData%\Programs\YaleVPN
del %SystemRoot%\yalevpn.cmd
```

## Notes

- Every privileged op auto-detects elevation and fails with a clear message
  when rights are missing.
- Profiles live in `%APPDATA%\YaleVPN\profiles`; logs in
  `%LOCALAPPDATA%\YaleVPN\yalevpn.log`.
- `cryptography` is bundled in the Release exe and in `install.ps1` — software
  X25519 keygen works without WireGuard installed.