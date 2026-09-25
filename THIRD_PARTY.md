# Third-party components

YaleVPN-PC is MIT-licensed (see `LICENSE`). It integrates with the following
external, independently-licensed components by invoking their command-line
interfaces (never linking or copying their code):

| Component | Use | License | Source |
|---|---|---|---|
| **WireGuard** (`wg`, `wg-quick`) | Linux kernel tunnels | GPL-2.0 / MIT (tools) | https://www.wireguard.com |
| **WireGuard for Windows** (`wireguard.exe`) | Windows tunnel services | GPL-2.0 | https://git.zx2c4.com/wireguard-windows |
| **wireguard-go** | Linux userspace fallback | MIT | https://git.zx2c4.com/wireguard-go |
| **Cloudflare WARP** (`warp-cli`) | WARP daemon control | proprietary (free client) | https://developers.cloudflare.com/warp-client |
| **wgcf** (optional) | WARP WireGuard profile generation | MIT | https://github.com/ViRb3/wgcf |
| **cryptography** (optional) | on-device X25519 keys + AES-GCM vault | Apache-2.0 / BSD-3-Clause | https://github.com/pyca/cryptography |
| **PyInstaller** (build only) | Windows .exe packaging | GPL-2.0 (with exception) | https://www.pyinstaller.org |

Interoperability only: YaleVPN-PC consumes the documented command-line /
wire-format interfaces of these tools and is network-wire-compatible with the
WireGuard protocol. It contains no code from the GPL components.

Reuse policy: MIT-licenced dependencies are used with attribution above; GPL
components are used only as external executables ("clean room" usage), never
copied or linked into this repository.