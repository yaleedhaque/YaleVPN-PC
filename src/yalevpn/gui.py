"""YaleVPN desktop control panel (tkinter — ships with Python everywhere).

Threading model: all tunnel/network work happens on a worker thread so the
UI stays responsive even when a wg-quick/nft call blocks. A poll timer
refreshes status ~ every 2s.

The GUI is intentionally small: full feature surface stays in the CLI, so
automation and remote/headless use never depends on a display.
"""
from __future__ import annotations

import queue
import threading
import time

from . import __version__, APP_LONG
from .backends import util as butil
from .core import config, util
from .core.profiles import ProfileStore, ProfileError
from .core.keys import new_keypair


class _Worker:
    def __init__(self):
        self.q: queue.Queue = queue.Queue()

    def submit(self, fn, on_ok=None, on_err=None):
        def _run():
            try:
                result = fn()
                self.q.put(("ok", on_ok, result))
            except Exception as e:  # noqa: BLE001
                self.q.put(("err", on_err, str(e)))

        threading.Thread(target=_run, daemon=True).start()

    def drain(self, app):
        try:
            while True:
                kind, cb, payload = self.q.get_nowait()
                if kind == "ok":
                    if cb:
                        cb(payload)
                else:
                    if app:
                        app.toast(payload if cb is None else str(payload))
        except queue.Empty:
            pass


def run_gui() -> None:
    try:
        import tkinter as tk
        from tkinter import ttk, filedialog, messagebox
    except Exception as e:  # pragma: no cover
        raise RuntimeError(f"tkinter not available: {e}") from e

    store = ProfileStore()

    class App:
        def __init__(self):
            self.root = tk.Tk()
            self.root.title(f"{APP_LONG} {__version__}")
            self.root.geometry("760x560")
            self.root.minsize(680, 480)
            self.worker = _Worker()
            self.bg = "#11151c"
            self.fg = "#e8ecf3"
            self.accent = "#e8b33c"  # gold
            self.green = "#4ade80"
            self.red = "#f87171"
            self._build()
            self.root.protocol("WM_DELETE_WINDOW", self.root.destroy)

        # ---- ui ----------------------------------------------------------
        def _build(self):
            self.root.configure(bg=self.bg)
            style = ttk.Style()
            try:
                style.theme_use("clam")
            except Exception:
                pass
            style.configure("Treeview", background="#1a2028",
                            fieldbackground="#1a2028", foreground=self.fg,
                            rowheight=26)
            style.configure("Treeview.Heading", background="#222a35",
                            foreground=self.fg, font=("", 9, "bold"))
            style.map("Treeview", background=[("selected", "#2b3a52")])

            head = tk.Frame(self.root, bg=self.bg)
            head.pack(fill="x", padx=14, pady=(12, 4))
            tk.Label(head, text="YaleVPN", bg=self.bg, fg=self.accent,
                     font=("", 16, "bold")).pack(side="left")
            self.lbl_state = tk.Label(head, text="…", bg=self.bg, fg=self.fg,
                                      font=("", 11, "bold"))
            self.lbl_state.pack(side="right")
            self.lbl_egress = tk.Label(head, text="", bg=self.bg,
                                       fg="#9aa7b5", font=("", 9))
            self.lbl_egress.pack(side="right", padx=10)

            info = tk.Frame(self.root, bg=self.bg)
            info.pack(fill="x", padx=14, pady=2)
            self.lbl_sub = tk.Label(info, text="profiles", bg=self.bg,
                                    fg="#9aa7b5")
            self.lbl_sub.pack(side="left")

            # profiles tree
            frame = tk.Frame(self.root, bg=self.bg)
            frame.pack(fill="both", expand=True, padx=14, pady=6)
            cols = ("name", "kind", "endpoint", "dns")
            self.tree = ttk.Treeview(frame, columns=cols, show="headings",
                                     selectmode="browse")
            widths = {"name": 140, "kind": 70, "endpoint": 300, "dns": 180}
            labels = {"name": "Profile", "kind": "Type", "endpoint": "Endpoint",
                      "dns": "DNS"}
            for c in cols:
                self.tree.heading(c, text=labels[c])
                self.tree.column(c, width=widths[c], anchor="w")
            ys = ttk.Scrollbar(frame, command=self.tree.yview)
            self.tree.configure(yscrollcommand=ys.set)
            self.tree.pack(side="left", fill="both", expand=True)
            ys.pack(side="right", fill="y")
            self.tree.bind("<Double-1>", lambda e: self.on_connect())

            # buttons
            btns = tk.Frame(self.root, bg=self.bg)
            btns.pack(fill="x", padx=14, pady=(0, 10))
            self._btn(btns, "Connect", self.green, self.on_connect)
            self._btn(btns, "Disconnect", self.red, self.on_disconnect)
            self._btn(btns, "Import…", "#3b82f6", self.on_import)
            self._btn(btns, "Rotate IP", "#a78bfa", self.on_rotate)
            self._btn(btns, "Kill switch", self.accent,
                      self.on_killswitch, toggle=True)
            self._btn(btns, "New keys", "#64748b", self.on_newkeys)
            self._btn(btns, "Refresh", "#475569", self.refresh)
            self.lbl_log = tk.Label(self.root, text="", bg=self.bg,
                                    fg="#9aa7b5", anchor="w", justify="left",
                                    font=("", 8))
            self.lbl_log.pack(fill="x", padx=14, pady=(0, 10))

        @staticmethod
        def _btn(parent, label, color, cb, toggle=False):
            def _go():
                if toggle and hasattr(cb, "__self__") and cb.__self__ == self:
                    pass
                cb()

            b = tk.Button(parent, text=label, bg="#1e2733", fg=color,
                          activebackground="#2b3a52", activeforeground=color,
                          relief="flat", bd=0, padx=12, pady=6,
                          font=("", 9, "bold"), cursor="hand2",
                          command=_go)
            b.pack(side="left", padx=(0, 8))
            b.bind("<Enter>", lambda e: b.configure(bg="#263244"))
            b.bind("<Leave>", lambda e: b.configure(bg="#1e2733"))
            return b

        # ---- workers -----------------------------------------------------
        def refresh(self):
            self.worker.submit(self._status_snapshot, self._apply_status)

        def _status_snapshot(self):
            avail = butil.available()
            out = {"avail": avail}
            if avail.get("warp"):
                from .backends.warp import WarpBackend
                out["warp"] = WarpBackend(store).status()
            e = util.egress_ips()
            out["egress"] = e
            out["active"] = config.get_state("active_backend")
            return out

        def _apply_status(self, s):
            self.tree.delete(*self.tree.get_children())
            d = store.default()
            for name in store.list_names():
                try:
                    prof = store.load(name)
                except Exception:
                    continue
                ep = prof.peers[0].get("Endpoint", "-") if prof.peers else "-"
                vid = "wg" if prof.iface.get("PrivateKey") else "?"
                self.tree.insert("", "end", iid=name, values=(
                    ("* " if name == d else "") + name, vid, ep,
                    prof.iface.get("DNS", "-")))
            warp = s.get("warp")
            if warp and warp.get("up"):
                self.tree.insert("", "end", iid="warp", values=(
                    ("* " if d in (None, "", "warp") else "") + "warp",
                    "warp", "engage.cloudflareclient.com:2408", "1.1.1.1, 1.0.0.1"))
            # status line
            e = s.get("egress", {})
            self.lbl_egress.config(
                text=f"v4 {e.get('v4') or '–'}  v6 {e.get('v6') or '–'}")
            if warp and warp.get("up"):
                self.lbl_state.config(text="▲ WARP CONNECTED", fg=self.green)
            elif s.get("active") == "wireguard":
                self.lbl_state.config(text="▲ TUNNEL UP", fg=self.green)
            else:
                self.lbl_state.config(text="▽ NO TUNNEL", fg=self.red)

        def toast(self, msg):
            self.lbl_log.config(text=msg)
            self.root.after(5000, lambda: self.lbl_log.config(text=""))

        # ---- actions -----------------------------------------------------
        def on_connect(self):
            sel = self.tree.selection()
            name = sel[0] if sel else store.default() or "warp"

            def _do():
                from .cli import cmd_up
                import argparse
                return cmd_up(argparse.Namespace(profile=name, target=name))

            def _ok(res):
                self.refresh()
                self.toast(f"connected: {name}")

            self.worker.submit(_do, _ok)

        def on_disconnect(self):
            def _do():
                from .cli import cmd_down
                import argparse
                return cmd_down(argparse.Namespace(profile="", target=""))

            def _ok(_):
                self.refresh()
                self.toast("disconnected")

            self.worker.submit(_do, _ok)

        def on_import(self):
            path = filedialog.askopenfilename(
                title="Import a WireGuard config",
                filetypes=[("WireGuard config", "*.conf"), ("All files", "*")])
            if not path:
                return

            def _do():
                from .cli import cmd_add
                import argparse
                return cmd_add(argparse.Namespace(
                    source=path, name="", make_default=False))

            def _ok(msg):
                self.refresh()
                self.toast(msg)

            self.worker.submit(_do, _ok)

        def on_rotate(self):
            def _do():
                from .cli import cmd_rotate
                import argparse
                return cmd_rotate(argparse.Namespace(quiet=True, attempts=3))

            def _ok(res):
                self.refresh()
                self.toast("WARP egress IP rotated")

            self.worker.submit(_do, _ok)

        def on_killswitch(self):
            def _do():
                from .cli import cmd_killswitch
                import argparse
                cur = ks_state()
                act = "off" if cur else "on"
                return cmd_killswitch(argparse.Namespace(
                    action=act, iface=""))

            def _ok(_):
                self.refresh()
                self.toast("kill switch toggled")

            self.worker.submit(_do, _ok)

        def on_newkeys(self):
            def _do():
                return new_keypair()

            def _ok(kp):
                from tkinter import messagebox
                messagebox.showinfo(
                    "YaleVPN keys (on-device)",
                    f"PrivateKey = {kp['private']}\n\n"
                    f"PublicKey  = {kp['public']}\n\n"
                    "Keep the private key secret — it never leaves this "
                    "machine. Paste the PublicKey into your WireGuard server "
                    "config to authorize this device.")
                self.refresh()

            self.worker.submit(_do, _ok)

        def poll(self):
            self.worker.drain(self)
            self.refresh()
            self.root.after(3000, self.poll)

    def ks_state():
        from .backends.killswitch import KillSwitch
        return bool(KillSwitch().status().get("enabled"))

    app = App()
    app.poll()
    app.root.mainloop()