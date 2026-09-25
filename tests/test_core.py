"""Unit tests for the pure-logic core (no tunnel, no daemon needed).

Run with:  python3 -m pytest tests/ -q     or     python3 tests/test_core.py
"""
import base64
import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from yalevpn.core import keys, profiles  # noqa: E402


class TestKeys(unittest.TestCase):
    def test_new_keypair_roundtrip(self):
        kp = keys.new_keypair()
        self.assertEqual(len(base64.b64decode(kp["private"])), 32)
        self.assertTrue(keys.validate_private(kp["private"]))
        self.assertTrue(keys.validate_public(kp["public"]))
        # public must be derivable from private (crypto inconsistency check)
        pub = keys.private_to_public(kp["private"])
        self.assertEqual(pub, kp["public"])

    def test_generated_keys_are_wireguard_shaped(self):
        kp = keys.new_keypair()
        # base64 -> 32 raw bytes; private keys clamp at use
        self.assertEqual(base64.b64decode(kp["private"], validate=True),
                         bytes(32) and base64.b64decode(kp["private"]))
        self.assertTrue(kp["private"].endswith("="))

    def test_validate_private_rejects_bad(self):
        self.assertFalse(keys.validate_private("not-a-key"))
        self.assertFalse(keys.validate_private(base64.b64encode(b"x" * 10).decode()))

    def test_two_generations_differ(self):
        a = keys.new_keypair()
        b = keys.new_keypair()
        self.assertNotEqual(a["private"], b["private"])


SAMPLE_CONF = """[Interface]
PrivateKey = qGBaEatmBCQVymJhUgGicivgAvJJLZFidRGbbAjuZko=
Address = 10.66.66.2/24
DNS = 1.1.1.1, 1.0.0.1
MTU = 1280

[Peer]
PublicKey = bmXOC+F1FxEMF9dyiK2H5/1SUtzH0JuVo51h2wPfgyo=
PresharedKey = xFXqVQ2zZcVZIUy7qZf6ZhHNMRN87XSkE2qK6PARQns=
Endpoint = 198.41.209.4:2408
AllowedIPs = 0.0.0.0/0, ::/0
PersistentKeepalive = 25
"""


class TestProfiles(unittest.TestCase):
    def test_parse_conf(self):
        p = profiles.parse_conf(SAMPLE_CONF, name="MyVPN")
        self.assertEqual(p.name, "myvpn")
        self.assertEqual(p.iface["PrivateKey"], "qGBaEatmBCQVymJhUgGicivgAvJJLZFidRGbbAjuZko=")
        self.assertEqual(p.iface["MTU"], "1280")
        self.assertEqual(len(p.peers), 1)
        peer = p.peers[0]
        self.assertEqual(peer["Endpoint"], "198.41.209.4:2408")
        self.assertEqual(peer["AllowedIPs"], "0.0.0.0/0, ::/0")

    def test_render_roundtrip(self):
        p = profiles.parse_conf(SAMPLE_CONF, name="x")
        text = profiles.render_conf(p)
        p2 = profiles.parse_conf(text, name="x")
        self.assertEqual(p2.iface, p.iface)
        self.assertEqual(p2.peers, p.peers)

    def test_sanitize_name(self):
        self.assertEqual(profiles.sanitize_name("My VPN!"), "myvpn")
        self.assertEqual(profiles.sanitize_name("a" * 30), "a" * 15)
        # degenerate input falls back to the stable default (never empty)
        self.assertEqual(profiles.sanitize_name("---"), "yalevpn")
        self.assertTrue(profiles.sanitize_name("---").isalnum())

    def test_unique_name(self):
        self.assertEqual(profiles.unique_name("vpn", []), "vpn")
        self.assertEqual(profiles.unique_name("vpn", ["vpn"]), "vpn_2")

    def test_bad_conf_raises(self):
        with self.assertRaises(profiles.ProfileError):
            profiles.parse_conf("[junk]\nno=interface\n")

    def test_store_crud_roundtrip(self):
        with tempfile.TemporaryDirectory() as td:
            store = profiles.ProfileStore(Path(td))
            p = profiles.parse_conf(SAMPLE_CONF, name="test1")
            store.save(p)
            self.assertIn("test1", store.list_names())
            loaded = store.load("test1")
            self.assertEqual(loaded.iface["DNS"], "1.1.1.1, 1.0.0.1")
            store.set_default("test1")
            self.assertEqual(store.default(), "test1")
            store.remove("test1")
            self.assertNotIn("test1", store.list_names())

    def test_vault_roundtrip(self):
        vault = profiles.Vault.from_password("correct horse battery staple")
        self.assertTrue(vault.enabled)
        blob = vault.encrypt_text(SAMPLE_CONF)
        self.assertTrue(blob.startswith("YALEVPN/VAULT/1/"))
        self.assertNotIn("PrivateKey", blob)
        self.assertEqual(vault.decrypt_text(blob), SAMPLE_CONF)
        bad = profiles.Vault.from_password("wrong")
        with self.assertRaises(profiles.ProfileError):
            bad.decrypt_text(blob)


class TestGenerate(unittest.TestCase):
    def test_generate_profile(self):
        kp = keys.new_keypair()
        gen = profiles.generate_profile(
            "myserver",
            private_key=kp["private"],
            endpoint="vpn.example.com:51820",
            peer_pub=kp["public"],
        )
        self.assertEqual(gen.name, "myserver")
        self.assertEqual(gen.peers[0]["Endpoint"], "vpn.example.com:51820")
        self.assertEqual(gen.iface["Address"], "10.0.0.2/24")


if __name__ == "__main__":
    unittest.main(verbosity=2)