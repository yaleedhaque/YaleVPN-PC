"""End-to-end CLI smoke tests against an isolated config dir.

Run with:  python3 tests/test_cli.py
"""
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

SRC = Path(__file__).resolve().parent.parent / "src"
ENV = dict(os.environ, PYTHONPATH=str(SRC))


def run_cli(args, cwd=None, env=None):
    e = dict(ENV)
    e.update(env or {})
    return subprocess.run([sys.executable, "-m", "yalevpn", *args],
                          capture_output=True, text=True, timeout=60,
                          cwd=cwd or str(SRC.parent), env=e)


class TestCli(unittest.TestCase):
    def setUp(self):
        self.td = tempfile.mkdtemp()
        # push XDG/HOME into a temp dir so nothing touches the real one
        self.home = tempfile.mkdtemp()
        self.env = {
            "PYTHONPATH": str(SRC),
            "HOME": self.home,
            "XDG_CONFIG_HOME": str(Path(self.home) / ".config"),
            "XDG_STATE_HOME": str(Path(self.home) / ".local" / "state"),
        }

    def test_help(self):
        r = run_cli(["help"], env=self.env)
        self.assertEqual(r.returncode, 0)
        self.assertIn("YaleVPN-PC", r.stdout)

    def test_doctor_with_base_python(self):
        r = run_cli(["doctor"], env=self.env)
        self.assertIn("platform", r.stdout)
        self.assertIn("kernel", r.stdout)

    def test_newkey(self):
        r = run_cli(["newkey"], env=self.env)
        self.assertEqual(r.returncode, 0)
        self.assertIn("PrivateKey", r.stdout)
        self.assertIn("PublicKey", r.stdout)

    def test_profile_add_list_show_export(self):
        conf = Path(self.td) / "t.conf"
        conf.write_text(SAMPLE)
        self.assertEqual(run_cli(["add", str(conf), "--name", "cli_test",
                                  "--default"], env=self.env).returncode, 0)
        r = run_cli(["list"], env=self.env)
        self.assertIn("cli_test", r.stdout)
        r = run_cli(["show", "cli_test"], env=self.env)
        self.assertIn("map.example.com:51820", r.stdout)
        out = Path(self.td) / "exp.conf"
        self.assertEqual(run_cli(["export", "cli_test", str(out)],
                                 env=self.env).returncode, 0)
        self.assertIn("[Interface]", out.read_text())
        self.assertEqual(run_cli(["remove", "cli_test", "-y"],
                                 env=self.env).returncode, 0)
        self.assertNotIn("cli_test", run_cli(["list"], env=self.env).stdout)

    def test_bad_profile_rejected(self):
        conf = Path(self.td) / "bad.conf"
        conf.write_text("[Interface]\nAddress = 1.2.3.4\n")  # no PrivateKey req,
        r = run_cli(["add", str(conf), "--name", "bad"], env=self.env)  # but no Peer
        self.assertEqual(r.returncode, 0)  # wg-quick allows peerless configs


SAMPLE = """[Interface]
PrivateKey = qGBaEatmBCQVymJhUgGicivgAvJJLZFidRGbbAjuZko=
Address = 10.66.66.2/24
DNS = 1.1.1.1, 1.0.0.1
MTU = 1420

[Peer]
PublicKey = bmXOC+F1FxEMF9dyiK2H5/1SUtzH0JuVo51h2wPfgyo=
Endpoint = map.example.com:51820
AllowedIPs = 0.0.0.0/0, ::/0
PersistentKeepalive = 25
"""


if __name__ == "__main__":
    unittest.main(verbosity=2)