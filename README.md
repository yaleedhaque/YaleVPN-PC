# YaleVPN-PC

Desktop companion to [YaleVPN](https://github.com/yaleedhaque/YaleVPN) (Android). A WireGuard/WARP
client for Linux **plus automatic public-IP rotation** — a fresh Cloudflare WARP egress on demand,
so per-IP rate limits/buckets reset without touching your ISP connection.

## What it does

- **Tunnel control** — `up` / `down` / `status` on the Cloudflare WARP consumer tunnel (`warp-cli`).
- **IP rotation** — `rotate` deletes and re-registers the WARP consumer device, yielding a new
  egress IP (v4 within Cloudflare's `104.28.x` pool, v6 `2a09:bacX:…`), verified before/after.
- **Periodic rotation** — systemd user timer (`yalevpn-pc-rotate.timer`, every 2 h, `Persistent=true`).
- **Profile export** — emits the same WARP WireGuard profile the Android app imports, so the
  **Windows WireGuard client** gets the identical tunnel (`export windows` / `export linux`).

## Install

```bash
# Linux (this repo's script)
install -Dm755 scripts/yalevpn-pc ~/.local/bin/yalevpn-pc

# systemd timer (optional, periodic rotation)
mkdir -p ~/.config/systemd/user
cp systemd/yalevpn-pc-rotate.* ~/.config/systemd/user/
systemctl --user daemon-reload
systemctl --user enable --now yalevpn-pc-rotate.timer
```

Requires `warp-cli` (Cloudflare WARP) for the tunnel/rotation and `curl` for IP probing.
`export linux` additionally needs `wireguard-tools` (`apt install wireguard-tools`).

## Usage

```
yalevpn-pc status                 # WARP state + current egress IPs + timer
yalevpn-pc rotate                 # re-register -> fresh egress IP (retries x3)
yalevpn-pc rotate --quiet         # no stdout (used by the timer)
yalevpn-pc timer on|off|status
yalevpn-pc export windows [path]  # Windows WireGuard .conf
yalevpn-pc export linux  [path]   # wg-quick .conf
yalevpn-pc conf                   # print profile
```

## Rotation — how it actually behaves

Cloudflare WARP consumer egress is a **shared** pool. Empirical behaviour observed on this machine:

| field | before | after rotate |
|-------|--------|--------------|
| IPv4  | `104.28.208.84` | `104.28.208.81` / `104.28.240.85` |
| IPv6  | `2a09:bac5:4a9:250f::3b1:1` | `2a09:bac1:b40:80::3b1:6` |

Re-registration reliably changes the **IPv6** egress and moves the **IPv4** within the `104.28.x`
range. Because the pool is shared, a freshly registered IP can still already be exhausted by other
WARP users — if you need a guaranteed private bucket, tether through a phone's mobile data instead.

## Windows

See [`docs/windows-wireguard.md`](docs/windows-wireguard.md). Generate the profile with
`yalevpn-pc export windows`, then import the `.conf` into the official WireGuard for Windows client.

> `config/*.conf` contains your private key and is **git-ignored** — never commit it.

## License

MIT — Md. Yaleed Haque.
