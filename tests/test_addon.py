"""De add-on-bestanden moeten kloppen (zelfde controle als in CI)."""
import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


class AddonFilesTests(unittest.TestCase):
    def test_check_script_passes(self):
        try:
            import yaml  # noqa: F401
        except ImportError:
            self.skipTest("pyyaml niet geïnstalleerd (alleen nodig voor deze controle)")
        r = subprocess.run([sys.executable, str(ROOT / "scripts" / "check_addon.py")], capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stdout)


if __name__ == "__main__":
    unittest.main()
