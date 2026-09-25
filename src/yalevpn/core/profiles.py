"""WireGuard profile model, wg-quick parse/render, on-disk store.

Profiles are standard wg-quick .conf files (the same format the official
apps on Windows and Android, and wg-quick on Linux, all consume). We keep
them as plaintext files plus a tiny settings.json index; optional encrypted
vault keeps private keys safe at rest (AES-256-GCM).
"""
from __future__ import annotations

import configparser
import json
import re
from dataclasses import dataclass, field
from pathlib import Path

from . import util

_INTERFACE_KEY = "interface"
_PEER_KEY = "peer"
_NAME_RE = re.compile(r"[^a-z0-9_]")

DEFAULT_MTU = "1420"
DEFAULT_DNS = "1.1.1.1, 1.0.0.1"


@dataclass
class Profile:
    name: str
    iface: dict = field(default_factory=dict)
    peers: list = field(default_factory=list)

    @property
    def private_key(self) -> str:
        return self.iface.get("PrivateKey", "")

    @property
    def is_default(self) -> bool:
        return False


class ProfileError(RuntimeError):
    pass


def sanitize_name(name: str) -> str:
    """Linux wg-quick interfaces: [a-z0-9_]{1,15}."""
    n = _NAME_RE.sub("", (name or "").lower())
    n = n.strip("_")
    if not n:
        n = "yalevpn"
    if len(n) > 15:
        n = n[:15].rstrip("_")
    return n


def unique_name(name: str, existing: list) -> str:
    n = sanitize_name(name)
    if n not in existing:
        return n
    i = 2
    while f"{n[:13]}_{i}" in existing and i < 100:
        i += 1
    return f"{n[:13]}_{i}"


def _cp() -> configparser.ConfigParser:
    cp = configparser.ConfigParser(delimiters=("=",), allow_no_value=True)
    cp.optionxform = str  # preserve AllowedIPs/PresharedKey case
    return cp


def parse_conf(text: str, name: str = "") -> Profile:
    cp = _cp()
    try:
        cp.read_string(text)
    except configparser.Error as e:
        raise ProfileError(f"invalid wg config: {e}") from e
    iface = dict(cp["Interface"]) if cp.has_section("Interface") else {}
    # wg-quick allows a single [Peer]; be permissive about [Peer], [PeerN].
    peers = []
    if cp.has_section("Peer"):
        peers.append(dict(cp["Peer"]))
    i = 1
    while cp.has_section(f"Peer{i}"):
        peers.append(dict(cp[f"Peer{i}"]))
        i += 1
    if not iface:
        raise ProfileError("config has no [Interface] section")
    nm = name or iface.get("Name") or ""
    return Profile(name=sanitize_name(nm), iface=iface, peers=peers)


def render_conf(profile: Profile) -> str:
    out = ["[Interface]"]
    for k, v in profile.iface.items():
        if k.startswith("X-"):
            continue
        out.append(f"{k} = {v}" if v is not None else k)
    for peer in profile.peers:
        out.append("\n[Peer]")
        for k, v in peer.items():
            out.append(f"{k} = {v}" if v is not None else k)
    return "\n".join(out) + "\n"


def generate_profile(name: str, private_key: str, public_key: str = "",
                     address: str = "10.0.0.2/24", dns: str = DEFAULT_DNS,
                     mtu: str = "", endpoint: str = "",
                     allowed_ips: str = "0.0.0.0/0, ::/0",
                     peer_pub: str = "", preshared: str = "",
                     keepalive: str = "25") -> Profile:
    iface = {"PrivateKey": private_key, "Address": address}
    if dns:
        iface["DNS"] = dns
    if mtu:
        iface["MTU"] = mtu
    peers = []
    if peer_pub:
        p = {"PublicKey": peer_pub}
        if preshared:
            p["PresharedKey"] = preshared
        if endpoint:
            p["Endpoint"] = endpoint
        if allowed_ips:
            p["AllowedIPs"] = allowed_ips
        if keepalive:
            p["PersistentKeepalive"] = keepalive
        peers.append(p)
    return Profile(name=sanitize_name(name), iface=iface, peers=peers)


class ProfileStore:
    def __init__(self, base: Path | None = None, vault: "Vault | None" = None):
        self.base = base or (util.config_home() / "profiles")
        self.vault = vault
        self.base.mkdir(parents=True, exist_ok=True)

    def settings_path(self) -> Path:
        return self.base.parent / "settings.json"

    def _load_settings(self) -> dict:
        p = self.settings_path()
        if p.exists():
            try:
                return json.loads(p.read_text(encoding="utf-8"))
            except Exception:
                return {}
        return {}

    def _save_settings(self, s: dict) -> None:
        self.settings_path().write_text(
            json.dumps(s, indent=2, sort_keys=True), encoding="utf-8")

    # -- profile CRUD ------------------------------------------------------
    def _path(self, name: str) -> Path:
        return self.base / f"{sanitize_name(name)}.conf"

    def list_names(self) -> list:
        return sorted(p.stem for p in self.base.glob("*.conf"))

    def load(self, name: str) -> Profile:
        p = self._path(name)
        if not p.exists():
            raise ProfileError(f"profile '{name}' not found")
        text = p.read_text(encoding="utf-8")
        if self.vault and text.startswith("YALEVPN/VAULT"):
            text = self.vault.decrypt_text(text)
        return parse_conf(text, name=name)

    def save(self, profile: Profile) -> Path:
        name = sanitize_name(profile.name)
        p = self._path(name)
        text = render_conf(profile)
        if self.vault and self.vault.enabled:
            p.write_text(self.vault.encrypt_text(text), encoding="utf-8")
        else:
            p.write_text(text, encoding="utf-8")
        try:
            p.chmod(0o600)
        except Exception:
            pass
        return p

    def remove(self, name: str) -> None:
        p = self._path(name)
        if p.exists():
            p.unlink()

    def rename(self, old: str, new: str) -> Profile:
        p = self._path(old)
        if not p.exists():
            raise ProfileError(f"profile '{old}' not found")
        profile = self.load(old)
        profile.name = sanitize_name(new)
        self.save(profile)
        self.remove(old)
        return profile

    def default(self) -> str | None:
        s = self._load_settings()
        d = s.get("default_profile")
        if d and (self.base / f"{d}.conf").exists():
            return d
        names = self.list_names()
        return names[0] if names else None

    def set_default(self, name: str) -> None:
        s = self._load_settings()
        s["default_profile"] = sanitize_name(name)
        self._save_settings(s)

    def last_profile(self) -> str | None:
        s = self._load_settings()
        return s.get("last_profile")

    def set_last(self, name: str) -> None:
        s = self._load_settings()
        s["last_profile"] = sanitize_name(name)
        self._save_settings(s)

    def settings(self) -> dict:
        return self._load_settings()

    def update_settings(self, **kw) -> None:
        s = self._load_settings()
        s.update(kw)
        self._save_settings(s)


# ------------------------------------------------------------------ vault --
class Vault:
    """Optional AES-256-GCM encrypted store for profile configs.

    Only used when a master password is set. Store this program's own
    password with the OS credential helpers when possible (keyring), else
    fall back to an env var `YALEVPN_VAULT_KEY` or interactive prompt.
    """

    def __init__(self, key: bytes | None = None):
        self.key = key
        self.enabled = key is not None

    @classmethod
    def from_password(cls, password: str) -> "Vault":
        try:
            from cryptography.hazmat.primitives.kdf.scrypt import Scrypt
            kdf = Scrypt(salt=b"yalevpn-vault-v1", length=32, n=2**14,
                         r=8, p=1)
            key = kdf.derive(password.encode("utf-8"))
            return cls(key=key)
        except Exception:
            return cls(key=password.encode("utf-8")[:32].ljust(32, b"\0"))

    def encrypt_text(self, text: str) -> str:
        if not self.key:
            return text
        from cryptography.hazmat.primitives.ciphers.aead import AESGCM
        nonce = __import__("os").urandom(12)
        body = AESGCM(self.key).encrypt(nonce, text.encode("utf-8"), None)
        import base64
        return "YALEVPN/VAULT/1/" + base64.b64encode(nonce + body).decode()

    def decrypt_text(self, blob: str) -> str:
        import base64
        from cryptography.hazmat.primitives.ciphers.aead import AESGCM
        raw = base64.b64decode(blob.split("/", 3)[3])
        nonce, body = raw[:12], raw[12:]
        try:
            return AESGCM(self.key).decrypt(nonce, body, None).decode("utf-8")
        except Exception as e:
            raise ProfileError(f"vault decrypt failed (wrong password?): {e}")


def env_or_prompt(key: str) -> str:
    import os
    v = os.environ.get(key, "").strip()
    if v:
        return v
    try:
        import getpass
        return getpass.getpass(f"{key}: ").strip()
    except Exception:
        return ""