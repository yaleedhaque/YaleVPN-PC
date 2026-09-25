"""WireGuard key generation.

WireGuard keys are Curve25519 (X25519) keys: a 32-byte random scalar (the
private key) and its X25519 public key, both base64-encoded. Keys are
generated ON-DEVICE — nothing leaves the machine.

Priority for generation:
  1. cryptography (pure software, cross-platform, packaged into the Windows
     exe) — preferred.
  2. system `wg genkey` / `wg pubkey` (wireguard-tools).

Both produce byte-identical, interoperable WireGuard keys.
"""
from __future__ import annotations

import base64
import re

from . import util

_B64 = re.compile(r"^[A-Za-z0-9+/]{43}=$")


class KeyError_(RuntimeError):
    pass


def new_keypair() -> dict:
    """Return {'private': b64priv, 'public': b64pub}. On-device generation."""
    try:
        from cryptography.hazmat.primitives.asymmetric.x25519 import (
            X25519PrivateKey,
        )
        from cryptography.hazmat.primitives.serialization import (
            Encoding,
            NoEncryption,
            PrivateFormat,
            PublicFormat,
        )
        sk = X25519PrivateKey.generate()
        priv = sk.private_bytes(Encoding.Raw, PrivateFormat.Raw, NoEncryption())
        pub = sk.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)
        return {
            "private": base64.b64encode(priv).decode(),
            "public": base64.b64encode(pub).decode(),
        }
    except Exception:
        if not util.have("wg"):
            raise KeyError_(
                "key generation needs either the 'cryptography' pip package "
                "(pip install cryptography) or wireguard-tools ('wg')."
            )
        p = util.run(["wg", "genkey"], timeout=20)
        if p.returncode != 0:
            raise KeyError_("wg genkey failed")
        priv_b64 = p.stdout.strip()
        pub = util.run(["wg", "pubkey"], input_text=priv_b64, timeout=20)
        if pub.returncode != 0 or not pub.stdout.strip():
            raise KeyError_("wg pubkey failed")
        return {"private": priv_b64, "public": pub.stdout.strip()}


def _random_priv() -> bytes:
    import os
    priv = os.urandom(32)
    # RFC 7748 clamping so even a raw random scalar is a valid WG private key.
    priv = bytearray(priv)
    priv[0] &= 248
    priv[31] &= 127
    priv[31] |= 64
    return bytes(priv)


def private_to_public(priv_b64: str) -> str:
    try:
        from cryptography.hazmat.primitives.asymmetric.x25519 import (
            X25519PrivateKey,
        )
        from cryptography.hazmat.primitives.serialization import (
            Encoding,
            NoEncryption,
            PrivateFormat,
            PublicFormat,
        )
        raw = base64.b64decode(priv_b64)
        sk = X25519PrivateKey.from_private_bytes(raw)
        pub = sk.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)
        return base64.b64encode(pub).decode()
    except Exception:
        p = util.run(["wg", "pubkey"], input_text=priv_b64, timeout=20)
        if p.returncode != 0 or not p.stdout:
            raise KeyError_("cannot derive public key")
        return p.stdout.strip()


def validate_private(priv_b64: str) -> bool:
    try:
        raw = base64.b64decode(priv_b64, validate=True)
    except Exception:
        return False
    return len(raw) == 32


def validate_public(pub_b64: str) -> bool:
    return bool(_B64.match(pub_b64 or ""))