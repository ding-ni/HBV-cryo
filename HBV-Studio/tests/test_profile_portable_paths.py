from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

STUDIO_DIR = Path(__file__).resolve().parents[1]
if str(STUDIO_DIR) not in sys.path:
    sys.path.insert(0, str(STUDIO_DIR))

import profile_runner


class ProfilePortablePathsTests(unittest.TestCase):
    def test_startup_normalization_preserves_values_and_is_idempotent(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            app_root = Path(temp_dir).resolve()
            gui_root = app_root / "HBV-Studio"
            gui_root.mkdir()
            original_cwd = Path.cwd()
            try:
                os.chdir(app_root)
                with patch.object(profile_runner, "APP_ROOT", app_root), patch.object(profile_runner, "GUI_ROOT", gui_root):
                    payload = {
                        "algorithm": "monthly_transfer_v3",
                        "quality": "passed",
                        "relative_path": "data/forcing.json",
                        "placeholder": "__PROJECT_ROOT__/data/forcing.json",
                        "empty": "",
                        "fingerprint": "a" * 64,
                        "nested": [str(gui_root / "workspaces" / "demo.json"), str(app_root / "data" / "forcing.json"), 1, True, None],
                    }
                    expected = dict(payload)
                    expected["nested"] = ["__GUI_ROOT__/workspaces/demo.json", "__PROJECT_ROOT__/data/forcing.json", 1, True, None]
                    once = profile_runner.portableize_value_paths(payload)
                    self.assertEqual(once, expected)
                    self.assertEqual(profile_runner.portableize_value_paths(once), expected)
            finally:
                os.chdir(original_cwd)

    def test_external_absolute_path_is_preserved(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir).resolve()
            app_root = root / "install"
            external = str(root / "station.csv")
            with patch.object(profile_runner, "APP_ROOT", app_root), patch.object(profile_runner, "GUI_ROOT", app_root / "HBV-Studio"):
                self.assertEqual(profile_runner.to_portable_path(external), external)


if __name__ == "__main__":
    unittest.main()
