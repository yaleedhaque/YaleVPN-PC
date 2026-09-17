# Windows WireGuard setup — YaleVPN-PC

The Android YaleVPN app and this desktop tool share the same WARP account, so the Windows client
gets the identical tunnel.

## 1. Generate the profile (on the Linux machine)

```bash
yalevpn-pc export windows
# -> /mnt/windows_d/OpenCode Projects/PC Apps/YaleVPN-PC/config/yalevpn-windows.conf
```

The file is mode `600` and git-ignored (it holds the WireGuard private key).

## 2. Install WireGuard for Windows

Download from <https://www.wireguard.com/install/> and run the installer.

## 3. Import the tunnel

1. Open **WireGuard**.
2. Click **Add Tunnel → Import tunnel(s) from file…**
3. Pick `yalevpn-windows.conf` (from `D:\OpenCode Projects\PC Apps\YaleVPN-PC\config\`).
4. Click **Activate**.

Verify: open <https://www.cloudflare.com/cdn-cgi/trace> — you should see `warp=on` and an IP in
Cloudflare's ranges.

## 4. Rotating on Windows

The `.conf` is a static WARP identity. To rotate, re-export a new profile from Linux
(`yalevpn-pc rotate` then `yalevpn-pc export windows`) and re-import it, **or** delete the tunnel in
the Windows client and import the freshly exported file. Windows has no equivalent of the Linux
`warp-cli` re-registration, so rotation stays driven from the Linux side.

## Profile contents

```
[Interface]
PrivateKey  = <your WARP private key>
Address     = 172.16.0.2/32
DNS         = 1.1.1.1, 1.0.0.1
MTU         = 1280

[Peer]
PublicKey          = bmXOC+F1FxEMF9dyiK2H5/1SUtzH0JuVo51h2wPfgyo=
AllowedIPs         = 0.0.0.0/0, ::/0
Endpoint           = engage.cloudflareclient.com:2408
PersistentKeepalive = 25
```
