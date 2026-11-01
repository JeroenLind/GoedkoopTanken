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

    def test_release_image_tag_has_no_v(self):
        # Home Assistant haalt ghcr.io/<naam>:<version> op, met version uit config.yaml (bv. 0.0.1, zonder v)
        wf = (ROOT / ".github" / "workflows" / "release.yaml").read_text(encoding="utf-8")
        self.assertIn("${GITHUB_REF_NAME#v}", wf)
        self.assertNotIn("name }}:${{ github.ref_name }}", wf)   # de imagetag is nooit de ruwe tagnaam (met v)
        self.assertIn(":${{ steps.ver.outputs.version }}", wf)

    def test_info_page_has_description_and_existing_screenshots(self):
        import re
        readme = (ROOT / "goedkoop-tanken" / "README.md").read_text(encoding="utf-8")
        self.assertGreater(len(readme), 600)
        shots = re.findall(r"raw\.githubusercontent\.com/[^/]+/[^/]+/main/(docs/screenshots/[\w.-]+)", readme)
        self.assertTrue(shots)
        for rel in shots:
            self.assertTrue((ROOT / rel).exists(), rel)


if __name__ == "__main__":
    unittest.main()
