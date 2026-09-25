"""YaleVPN command-line interface.

Cross-platform (Linux + Windows). Everything the GUI does is reachable here,
which also makes automation, cron/task-scheduler and CI integration easy.

Typical flow:  yalevpn add   myprofile.conf + yalevpn up myprofile
              yalevpn warp up   ; yalevpn rotate
"""
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

from . import __version__, APP_LONG
from .backends import killswitch as ks
from .backends import util as butil
from .backends import warp as warp_mod
from .backends import wireguard as wg_mod
from .core import config, profiles, util
from .core.keys import private_to_public, validate_private, new_keypair
from .core.profiles import ProfileStore, Vault, ProfileError

# ------------------------------------------------------------------ store --
_store = ProfileStore()


def _vault_from_env() -> Vault | None:
    import os
    pw = os.environ.get("YALEVPN_VAULT_PASSWORD", "")
    if pw:
        return Vault.from_password(pw)
    return None


def _wireguard_backend() -> wg_mod.WireGuardBackend:
    return wg_mod.WireGuardBackend(util.data_home())


def _warp_backend() -> warp_mod.WarpBackend:
    return warp_mod.WarpBackend(_store)


def _route_iface(backend: str, profile_name: str = "") -> str:
    if backend == "warp":
        return "CloudflareWARP"
    return profile_name or ""


# ------------------------------------------------------------------ core ---
def cmd_status(args) -> int:
    out = []
    out.append(f"{APP_LONG} {__version__} — {util.ts()}")
    out.append(f"platform   : {'windows' if util.is_windows() else 'linux'}")
    avail = butil.available()
    out.append(f"backends   : warp={'yes' if avail['warp'] else 'no'} "
               f"wireguard-linux={'yes' if avail['wireguard_linux'] else 'no'} "
               f"wireguard-win={'yes' if avail['wireguard_windows'] else 'no'}")
    if avail["warp"]:
        st = _warp_backend().status()
        out.append(f"warp       : {'UP' if st['up'] else 'down'}")
        reg = st.get("registration", {})
        if reg.get("account_type"):
            out.append(f"warp acct  : {reg.get('account_type')} id={reg.get('id')}")
        e = st.get("egress", {})
        out.append(f"egress     : v4={e.get('v4') or '-'} v6={e.get('v6') or '-'}")
    ls = _store.list_names()
    out.append(f"profiles   : {len(ls)} — {', '.join(ls) if ls else '(none; use: yalevpn add)'}")
    if ls:
        d = _store.default()
        out.append(f"default    : {d or '(unset)'}")
    k = ks.KillSwitch()
    st = k.status()
    out.append(f"killswitch : {'ON (' + st.get('tool','') + ')' if st['enabled'] else 'off'}")
    try:
        aut = __import__("yalevpn.autostart", fromlist=["status"]).status()
        out.append(f"autostart  : {aut}")
    except Exception:
        pass
    up = config.get_state("active_backend")
    if up:
        out.append(f"session    : {up} since {config.get_state('connected_at')}")
    print("\n".join(out))
    return 0


def _require_default(args) -> str:
    name = getattr(args, "profile", None)
    if not name:
        name = args.target or ""
    if name == "warp":
        return "warp"
    d = name or _store.default()
    if not d:
        raise ProfileError("no default profile — pass a name or set one "
                           "(yalevpn add / yalevpn default)")
    return d


def cmd_up(args) -> int:
    target = _require_default(args)
    if target == "warp":
        st = _warp_backend().up()
        _start_state("warp")
        print(f"warp UP  egress v4={st['egress'].get('v4')} "
              f"v6={st['egress'].get('v6')}")
        return 0
    store = _store
    if store._path(target).exists() or (target in store.list_names()):
        prof = store.load(target)
    else:
        raise ProfileError(f"profile '{target}' not found (yalevpn list)")
    if not prof.private_key:
        raise ProfileError(f"profile '{target}' has no PrivateKey")
    backend = _wireguard_backend()
    st = backend.up(target, profiles.render_conf(prof))
    _start_state("wireguard")
    print(f"{target} UP  egress v4={st['egress'].get('v4')} "
          f"v6={st['egress'].get('v6')}")
    return 0


def cmd_down(args) -> int:
    target = getattr(args, "profile", "") or getattr(args, "target", "")
    backend_kind = config.get_state("active_backend")
    if backend_kind == "warp" or (target == "warp" and not backend_kind):
        st = _warp_backend().down()
        config.clear_state("active_backend")
        config.clear_state("connected_at")
        print("warp DOWN")
        return 0
    # wireguard: down the session (or named) interface
    iface = target or _store.last_profile() or _store.default()
    if iface:
        try:
            backend = _wireguard_backend()
            backend.down(iface)
            config.clear_state("active_backend")
            config.clear_state("connected_at")
            print(f"{iface} DOWN")
        except Exception as e:
            print(f"down failed: {e}")
            return 1
    return 0


def _start_state(backend: str) -> None:
    config.set_state("active_backend", backend)
    config.set_state("connected_at", util.now())


def cmd_rotate(args) -> int:
    quiet = getattr(args, "quiet", False)
    backend = _warp_backend()
    try:
        r = backend.rotate(attempts=getattr(args, "attempts", 3), quiet=quiet)
    except Exception as e:
        if not quiet:
            print(f"rotate failed: {e}")
        return 1
    if not quiet:
        print(f"before: v4={r['before'].get('v4')} v6={r['before'].get('v6')}")
        print(f"after : v4={r['after'].get('v4')} v6={r['after'].get('v6')}")
        if r["rotated"]:
            print(f"ROTATED attempt={r['attempt']}")
        else:
            print("WEAK — egress unchanged (shared Cloudflare WARP pool)")
    return 0 if r["rotated"] else 1


def cmd_warp(args) -> int:
    act = args.warp_action
    if act == "status":
        st = _warp_backend().status()
        print(f"state      : {'UP' if st['up'] else 'down'}")
        for k, v in st.get("registration", {}).items():
            print(f"{k:12}: {v}")
        e = st.get("egress", {})
        print(f"{'egress':12}: v4={e.get('v4') or '-'} v6={e.get('v6') or '-'}")
        return 0
    if act == "up":
        return cmd_up(argparse.Namespace(profile="warp", target="warp"))
    if act == "down":
        return cmd_down(argparse.Namespace(profile="warp", target="warp"))
    if act == "rotate":
        return cmd_rotate(argparse.Namespace(quiet=args.quiet,
                                             attempts=args.attempts))
    if act == "bootstrap":
        prof = warp_mod.WarpBackend.bootstrap_with_wgcf(
            name=args.profile or "warp")
        _store.save(prof)
        print(f"WARP profile '{prof.name}' created on-device (wgcf).")
        print(f"Connect with: yalevpn up {prof.name}")
        return 0
    if act == "export":
        prof = _warp_backend().warp_profile(name="warp")
        path = args.path or str(util.config_home() / "profiles" / "warp-wireguard.conf")
        prof.name = "warp"
        Path(path).write_text(profiles.render_conf(prof), encoding="utf-8")
        try:
            Path(path).chmod(0o600)
        except Exception:
            pass
        print(f"WARP WireGuard profile written: {path}")
        print("This file imports into the Windows / Android / macOS WireGuard apps.")
        return 0
    raise SystemExit("unknown warp action")


# ------------------------------------------------------------- profiles -----
def cmd_add(args) -> int:
    src = args.source
    name = args.name or ""
    text = ""
    if src == "-":
        text = sys.stdin.read()
    elif src.startswith("http://") or src.startswith("https://"):
        text = util.http_get(src, timeout=20)
        if not text:
            print(f"failed to fetch {src}", file=sys.stderr)
            return 1
    else:
        p = Path(src)
        if not p.exists():
            print(f"no such file: {src}", file=sys.stderr)
            return 1
        text = p.read_text(encoding="utf-8")
    if not text.strip():
        print("empty config", file=sys.stderr)
        return 1
    try:
        prof = profiles.parse_conf(text, name=name or Path(src).stem)
    except ProfileError as e:
        print(f"bad config: {e}", file=sys.stderr)
        return 1
    prof.name = profiles.unique_name(
        prof.name or "wg", _store.list_names() + ["warp"])
    if prof.name == "warp":
        prof.name = "warp-wg"
    _store.save(prof)
    if args.make_default:
        _store.set_default(prof.name)
    print(f"added profile '{prof.name}'"
          + (" (default)" if args.make_default else ""))
    print(f"peers  : {len(prof.peers)}")
    print(f"dns    : {prof.iface.get('DNS', '-')}")
    print(f"connect: yalevpn up {prof.name}")
    return 0


def cmd_newkey(args) -> int:
    try:
        kp = new_keypair()
    except Exception as e:
        print(f"keygen failed: {e}", file=sys.stderr)
        return 1
    print(f"PrivateKey = {kp['private']}")
    print(f"PublicKey  = {kp['public']}")
    print("# keep the private key secret — it never leaves this machine.")
    return 0


def cmd_list(args) -> int:
    names = _store.list_names()
    if not names:
        print("no profiles yet — yalevpn add <file.conf> [name]")
        return 0
    d = _store.default()
    for n in names:
        prof = None
        try:
            prof = _store.load(n)
        except Exception:
            pass
        ep = "?"
        dns = prof.iface.get("DNS", "-") if prof else "-"
        peers = len(prof.peers) if prof else 0
        if prof and prof.peers:
            ep = prof.peers[0].get("Endpoint", "-") or "-"
        print(f"{'*' if n == d else ' '} {n:16} peer={peers} "
              f"endpoint={ep} dns={dns}")
    print("\n* = default")
    return 0


def cmd_show(args) -> int:
    try:
        prof = _store.load(args.profile)
    except ProfileError as e:
        print(str(e), file=sys.stderr)
        return 1
    print(f"name      : {prof.name}")
    for k, v in prof.iface.items():
        if k.lower() == "privatekey":
            v = "🔒 (hidden; yalevpn export to view)"
        print(f"{k:12}: {v}")
    for i, peer in enumerate(prof.peers, 1):
        print(f"--- Peer {i} ---")
        for k, v in peer.items():
            print(f"{k:12}: {v}")
    return 0


def cmd_remove(args) -> int:
    name = args.profile
    if args.yes or util.is_root():
        _store.remove(name)
        print(f"removed '{name}'")
    else:
        ans = input(f"remove profile '{name}'? [y/N] ")
        if ans.lower() in ("y", "yes"):
            _store.remove(name)
            print(f"removed '{name}'")
        else:
            print("aborted")
    return 0


def cmd_edit(args) -> int:
    name = args.profile
    try:
        prof = _store.load(name)
    except ProfileError as e:
        print(str(e), file=sys.stderr)
        return 1
    changes = {}
    if args.private_key:
        changes["PrivateKey"] = args.private_key
    if args.address is not None:
        changes["Address"] = args.address
    if args.dns is not None:
        changes["DNS"] = args.dns
    if args.mtu is not None:
        changes["MTU"] = args.mtu
    if args.endpoint:
        if not prof.peers:
            prof.peers.append({})
        prof.peers[0]["Endpoint"] = args.endpoint
    if args.allowed_ips:
        if not prof.peers:
            prof.peers.append({})
        prof.peers[0]["AllowedIPs"] = args.allowed_ips
    if args.keepalive:
        if not prof.peers:
            prof.peers.append({})
        prof.peers[0]["PersistentKeepalive"] = args.keepalive
    prof.iface.update(changes)
    _store.save(prof)
    print(f"updated '{name}'")
    return 0


def cmd_default(args) -> int:
    if args.profile == "warp":
        _store.update_settings(default_profile=None)
        print("default: warp")
        return 0
    _store.set_default(args.profile)
    print(f"default profile: {args.profile}")
    return 0


def cmd_export(args) -> int:
    prof = _store.load(args.profile)
    path = args.path or str(Path.cwd() / f"{prof.name}.conf")
    Path(path).write_text(profiles.render_conf(prof), encoding="utf-8")
    try:
        Path(path).chmod(0o600)
    except Exception:
        pass
    print(f"exported '{prof.name}' -> {path}")
    return 0


def cmd_import(args) -> int:
    return cmd_add(args)


# ---------------------------------------------------------- privileges ------
def cmd_killswitch(args) -> int:
    k = ks.KillSwitch()
    act = args.action
    try:
        if act == "on":
            tun = _tun_ifaces(args)
            endpoints = _endpoints(args)
            k.tun = tun
            k.endpoints = endpoints
            r = k.on()
            print(f"kill switch ON via {r.get('tool')} (drop non-tunnel outbound)")
        elif act == "off":
            r = k.off()
            print(f"kill switch off")
        else:
            r = k.status()
            state = "ON" if r.get("enabled") else "off"
            print(f"kill switch: {state} (tool={r.get('tool')})")
    except Exception as e:
        print(f"killswitch: {e}", file=sys.stderr)
        return 1
    return 0


def _tun_ifaces(args):
    # attempt to introspect active tunnel interface (best effort)
    up = config.get_state("active_backend")
    if up == "warp":
        return "CloudflareWARP"
    if up == "wireguard":
        name = _store.last_profile()
        if name:
            return name
    return getattr(args, "iface", "") or "CloudflareWARP"


def _endpoints(args):
    eps = []
    try:
        for name in _store.list_names():
            prof = _store.load(name)
            for peer in prof.peers:
                if peer.get("Endpoint"):
                    eps.append(peer["Endpoint"])
    except Exception:
        pass
    return eps


def cmd_dns(args) -> int:
    from .backends.dns import DNS
    d = DNS(servers=args.servers)
    act = args.action

    def _iface():
        return _tun_ifaces(argparse.Namespace())

    d.iface = _iface()
    try:
        if act == "set":
            r = d.set()
            print(f"DNS pinned {','.join(d.servers)} on {r.get('iface')} "
                  f"({r.get('tool')})")
        elif act == "restore" or act == "unset":
            r = d.unset()
            print(f"DNS restored on {r.get('iface') or 'auto'}")
        else:
            r = d.status()
            srv = r.get("servers") or "?"
            print(f"resolver: {r.get('tool')} iface={r.get('iface')} "
                  f"servers={srv}")
    except Exception as e:
        print(f"dns: {e}", file=sys.stderr)
        return 1
    return 0


def cmd_leaktest(args) -> int:
    from .stats import leak_test
    r = leak_test()
    print(f"egress v4 : {r.get('actual_v4') or '-'}")
    print(f"egress v6 : {r.get('actual_v6') or '-'}")
    if r.get("cdn_loc"):
        print(f"cdn loc   : {r['cdn_loc']}")
    print(f"conclusion: {r.get('conclusion')}")
    if r.get("resolver_notes"):
        print(" --- resolver ---")
        for ln in r["resolver_notes"]:
            print(f"  {ln}")
    return 0


def cmd_stats(args) -> int:
    from .stats import active_stats, session_uptime
    up = config.get_state("active_backend")
    if not up:
        print("no active tunnel")
        return 0
    iface = "" if up == "warp" else _store.last_profile() or ""
    st = active_stats(up, iface)
    print(f"session   : {up} uptime={session_uptime() or '-'}")
    for k, v in st.items():
        print(f"{k:15}: {v}")
    return 0


def cmd_doctor(args) -> int:
    avail = butil.available()
    ok = 0
    total = 4
    print(f"{APP_LONG} {__version__} doctor")
    print(f"platform : {avail['platform']}" +
          (f" kernel={avail.get('kernel')}" if avail.get("kernel") else ""))
    rows = [
        ("warp-cli (WARP daemon)", avail["warp"], "recommended"),
        ("wg + wg-quick (kernel WG)" if "windows" not in avail["platform"]
         else "WireGuard client (wireguard.exe)", avail.get(
            "wireguard_windows") or avail.get("wireguard_linux"), "recommended"),
        ("cryptography (keygen/vault)", avail.get("cryptography"), "optional"),
        ("nft/iptables (kill switch)", avail.get("nft") or avail.get("iptables"),
         "recommended on Linux"),
    ]
    for label, present, note in rows:
        mark = "✔" if present else "–"
        print(f"  {mark} {label:35} [{note}]")
        if present:
            ok += 1
    total = len(rows)
    egress = util.egress_ips()
    print(f"egress   : v4={egress['v4'] or '-'} v6={egress['v6'] or '-'}")
    score = f"{ok}/{total}"
    print(f"ready    : {score}")
    print("hint     : install wireguard-tools + cloudflare-warp for the full suite")
    return 0 if ok >= 3 else (0 if ok == total else 1)


def cmd_autostart(args) -> int:
    from . import autostart
    act = args.action
    target = args.target or "warp"
    try:
        if act == "on":
            r = autostart.install(target)
            print(f"autostart enabled for '{target}': {r}")
        elif act == "off":
            r = autostart.remove()
            print(f"autostart off: {r}")
        else:
            r = autostart.status()
            print(f"autostart : {r.get('autostart')}")
            print(f"rotate    : {r.get('rotate_timer')}")
    except Exception as e:
        print(f"autostart: {e}", file=sys.stderr)
        return 1
    return 0


# ------------------------------------------------------------------- gui ---
def cmd_gui(args) -> int:
    try:
        from .gui import run_gui
        run_gui()
        return 0
    except Exception as e:
        print(f"gui unavailable: {e}", file=sys.stderr)
        return 1


def cmd_help(args) -> int:
    print(_help_text())
    return 0


def _help_text() -> str:
    return f"""{APP_LONG} v{__version__} — WireGuard + WARP desktop VPN (Linux & Windows)

USAGE
  yalevpn <command> [args]

TUNNELS
  up [profile]       bring tunnel up (profile name, default, or 'warp')
  down               take the active tunnel down
  status             full machine status (backends, profiles, egress)
  ip                 show egress IPv4/IPv6

PROFILES (WireGuard)
  add <file|url|->   import a wg-quick config   [--name X] [--default]
  list / show <name> inspect stored profiles
  edit <name> ...    change DNS/MTU/Address/Endpoint/AllowedIPs/keepalive
  remove <name>      delete a profile
  export <name>      write the profile back out (e.g. for phone import)
  default <name>     set the default profile
  newkey             generate an on-device Curve25519 keypair

WARP (Cloudflare)
  warp status|up|down
  rotate [--attempts N] [--quiet]   re-register WARP -> fresh egress IP
  warp export [path]  write a WARP WireGuard profile (works on Windows)
  warp bootstrap [--profile name]   build a fresh WARP profile via 'wgcf'

PROTECTION & MACHINE
  killswitch on|off|status
  dns set|restore|status [servers...]
  leaktest           verify DNS/IP through the tunnel
  stats              transfer + handshake + session uptime
  autostart on|off   [--target profile|warp]   systemd / Task Scheduler
  doctor             diagnose the environment
  gui                launch the desktop control panel
  help
"""
    print(_help_text())
    return 0


# ----------------------------------------------------------------- parser ---
def _make_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="yalevpn", description="WireGuard + WARP desktop VPN client")
    p.add_argument("--version", action="version",
                   version=f"{APP_LONG} {__version__}")
    sub = p.add_subparsers(dest="command")

    sp = sub.add_parser("status", help="machine status")
    sp.set_defaults(fn=cmd_status)

    p1 = sub.add_parser("ip", help="egress IPs")
    p1.set_defaults(fn=_cmd_ip)

    pu = sub.add_parser("up", help="bring a tunnel up")
    pu.add_argument("profile", nargs="?", default="", help="profile or warp")
    pu.add_argument("--target", default="")
    pu.set_defaults(fn=cmd_up)

    pd = sub.add_parser("down", help="take the tunnel down")
    pd.add_argument("profile", nargs="?", default="")
    pd.set_defaults(fn=cmd_down)

    pr = sub.add_parser("rotate", help="rotate the WARP egress IP")
    pr.add_argument("--attempts", type=int, default=3)
    pr.add_argument("--quiet", action="store_true")
    pr.set_defaults(fn=cmd_rotate)

    pw = sub.add_parser("warp", help="Cloudflare WARP control")
    pw.add_argument("warp_action", choices=["status", "up", "down", "rotate",
                                            "bootstrap", "export"])
    pw.add_argument("--profile", default="warp")
    pw.add_argument("--attempts", type=int, default=3)
    pw.add_argument("--quiet", action="store_true")
    pw.add_argument("path", nargs="?")
    pw.set_defaults(fn=cmd_warp)

    pa = sub.add_parser("add", help="import a WireGuard profile")
    pa.add_argument("source", help="file path, URL, or '-' for stdin")
    pa.add_argument("--name", default="")
    pa.add_argument("--default", action="store_true", dest="make_default")
    pa.set_defaults(fn=cmd_add)

    pl = sub.add_parser("list", help="list profiles")
    pl.set_defaults(fn=cmd_list)

    ps = sub.add_parser("show", help="show a profile")
    ps.add_argument("profile")
    ps.set_defaults(fn=cmd_show)

    pre = sub.add_parser("remove", help="delete a profile")
    pre.add_argument("profile")
    pre.add_argument("-y", "--yes", action="store_true")
    pre.set_defaults(fn=cmd_remove)

    pe = sub.add_parser("edit", help="edit a profile")
    pe.add_argument("profile")
    pe.add_argument("--privkey", dest="private_key")
    pe.add_argument("--address")
    pe.add_argument("--dns")
    pe.add_argument("--mtu")
    pe.add_argument("--endpoint")
    pe.add_argument("--allowed-ips", dest="allowed_ips")
    pe.add_argument("--keepalive")
    pe.set_defaults(fn=cmd_edit)

    pg = sub.add_parser("default", help="set the default profile")
    pg.add_argument("profile")
    pg.set_defaults(fn=cmd_default)

    pex = sub.add_parser("export", help="export a profile")
    pex.add_argument("profile")
    pex.add_argument("path", nargs="?", default="")
    pex.set_defaults(fn=cmd_export)

    pn = sub.add_parser("newkey", help="generate a keypair")
    pn.set_defaults(fn=cmd_newkey)

    pk = sub.add_parser("killswitch", help="leak protection")
    pk.add_argument("action", choices=["on", "off", "status"], default="status",
                    nargs="?")
    pk.add_argument("--iface", default="")
    pk.set_defaults(fn=cmd_killswitch)

    pdn = sub.add_parser("dns", help="DNS leak protection")
    pdn.add_argument("action", choices=["set", "restore", "status"],
                     default="status", nargs="?")
    pdn.add_argument("servers", nargs="*", default=["1.1.1.1", "1.0.0.1"])
    pdn.set_defaults(fn=cmd_dns)

    plt = sub.add_parser("leaktest", help="DNS/IP leak check")
    plt.set_defaults(fn=cmd_leaktest)

    pst = sub.add_parser("stats", help="tunnel statistics")
    pst.set_defaults(fn=cmd_stats)

    paut = sub.add_parser("autostart", help="auto-connect at boot")
    paut.add_argument("action", choices=["on", "off", "status"],
                      default="status", nargs="?")
    paut.add_argument("--target", default="warp")
    paut.set_defaults(fn=cmd_autostart)

    pdoc = sub.add_parser("doctor", help="diagnose the environment")
    pdoc.set_defaults(fn=cmd_doctor)

    pgui = sub.add_parser("gui", help="launch the desktop control panel")
    pgui.set_defaults(fn=cmd_gui)

    ph = sub.add_parser("help")
    ph.set_defaults(fn=cmd_help)
    return p


def _cmd_ip(args) -> int:
    from .core import util
    e = util.egress_ips()
    print(f"v4={e['v4'] or '-'} v6={e['v6'] or '-'}")
    return 0


def main(argv=None) -> int:
    argv = argv if argv is not None else sys.argv[1:]
    if not argv or argv[0] in ("-h", "--help", "help"):
        print(_help_text())
        return 0
    p = _make_parser()
    try:
        args = p.parse_args(argv)
    except SystemExit as e:
        return e.code if isinstance(e.code, int) else 1
    if not hasattr(args, "fn"):
        print(_help_text())
        return 0
    try:
        return args.fn(args)
    except ProfileError as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    except RuntimeError as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("\ninterrupted")
        return 130


if __name__ == "__main__":
    raise SystemExit(main())