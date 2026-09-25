# YaleVPN on Linux

The client is a single Python package — no build step, no cloud. It drives
three backends on Linux:

| Backend | Tool | Role |
|---|---|---|
| WireGuard (kernel) | `wg` + `wg-quick` | fast kernel-mode tunnels |
| WireGuard (userspace) | `wireguard-go` | fallback when the kernel module is missing |
| Cloudflare WARP | `warp-cli` | WARP consumer tunnel + egress-IP rotation |

## Install

```bash
curl -sO https://raw.githubusercontent.com/yaleedhaque/YaleVPN-PC/master/install.sh
bash install.sh
```

or copy the project and run `install.sh` directly. It installs into
`~/.local/bin` (no root needed). Optionally install `wireguard-tools`
(kernel tunnels) and `cloudflare-warp` (WARP + rotation):

```bash
sudo apt install wireguard-tools     # wg, wg-quick          (recommended)
sudo apt install cloudflare-warp     # warp-cli               (recommended)
sudo apt install nftables iptables   # kill switch            (recommended)
pip install --user cryptography      # software keygen/vault  (optional)
```

Verify:

```bash
yalevpn doctor
```

## Import a WireGuard profile

Any standard `wg-quick` `.conf` works — from your own server, a provider, or
a generated WARP profile:

```bash
yalevpn add ~/Downloads/myserver.conf --default
yalevpn list
yalevpn up myserver
```

You can also paste a profile directly ([Interface] … [Peer]) or fetch one:

```bash
yalevpn add https://vpn.example.com/wireguard/my.conf
yalevpn add - < myserver.conf
```

## Connect

```bash
yalevpn up myserver      # kernel WireGuard
yalevpn up warp          # Cloudflare WARP daemon
yalevpn down
yalevpn status           # full machine state + egress IPs
yalevpn ip               # current IPv4/IPv6
```

## WARP IP rotation

Cloudflare WARP assigns its egress IP from a shared pool. Re-registering the
consumer device yields a fresh egress on demand (verified before/after):

```bash
yalevpn rotate                     # manual
yalevpn autostart on --target warp # also enables the 2h systemd timer
```

Requires a Free WARP registration (it is the default `warp-cli` registration).

## Leak protection

```bash
yalevpn killswitch on    # nftables/iptables: drop all non-tunnel outbound
yalevpn killswitch off
yalevpn dns set          # pin 1.1.1.1 / 1.0.0.1 via systemd-resolved
yalevpn dns restore
yalevpn leaktest         # confirm the egress + resolver are through the tunnel
```

The kill switch builds a dedicated `YALEVPN` nftables chain that accepts only
established/related traffic, the tunnel interface, loopback and DNS, and drops
everything else. It is removed cleanly on `off`.

## Statistics & diagnostics

```bash
yalevpn stats            # transfer, handshake age, session uptime
yalevpn doctor           # environment drill-down + readiness score
yalevpn gui              # desktop control panel (tkinter)
```

## GUI

`yalevpn gui` launches the desktop panel: profile table, Connect /
Disconnect, Import, WARP IP rotation, kill-switch toggle, on-device key
generation and live egress readout (refreshes every 3s).

## Auto-connect at logon

```bash
yalevpn autostart on --target warp    # systemd user units
yalevpn autostart off
yalevpn autostart status
```

Equivalent systemd units ship in `systemd/` for manual use:

```bash
mkdir -p ~/.config/systemd/user
cp systemd/yalevpn-*.{service,timer} ~/.config/systemd/user/ 2>/dev/null
systemctl --user daemon-reload
systemctl --user enable --now yalevpn-autostart.service yalevpn-rotate.timer
```

## Uninstall

```bash
rm ~/.local/bin/yalevpn ~/.local/bin/yalevpn-pc
rm -rf ~/.local/share/yalevpn ~/.config/yalevpn ~/.local/state/yalevpn
```

## Notes

- Profiles live in `~/.config/yalevpn/profiles/` (0600). Optional AES-GCM
  encryption via `YALEVPN_VAULT_PASSWORD` (see `yalevpn.conf` peak at
  `core/profiles.py`).
- All key pairs are generated on-device (`yalevpn newkey`) and never leave
  the machine.
- Logs: `~/.local/state/yalevpn/yalevpn.log`.