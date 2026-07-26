from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


STUDIO_DIR = Path(__file__).resolve().parents[1]
if str(STUDIO_DIR) not in sys.path:
    sys.path.insert(0, str(STUDIO_DIR))

import app_bootstrap as bootstrap  # noqa: E402


class UserWorkspaceSeedTests(unittest.TestCase):
    def _seed(self, user_root: Path, gui_root: Path) -> None:
        with (
            patch.object(bootstrap, "should_use_user_data_root", return_value=True),
            patch.object(bootstrap, "user_data_root", return_value=user_root),
            patch.object(bootstrap, "migrate_existing_user_data"),
            patch.object(bootstrap, "installed_mode", return_value=False),
            patch.object(bootstrap, "GUI_ROOT", gui_root),
        ):
            bootstrap.seed_user_data()

    def test_existing_user_workspaces_are_never_overwritten_or_reseeded(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            gui_root = root / "package" / "HBV-Studio"
            source = gui_root / "workspaces"
            target = root / "user" / "workspaces"
            source.mkdir(parents=True)
            target.mkdir(parents=True)
            (source / "deleted.json").write_text('{"source": true}', encoding="utf-8")
            existing = target / "kept.json"
            existing.write_text('{"user": true}', encoding="utf-8")

            self._seed(root / "user", gui_root)

            self.assertEqual(json.loads(existing.read_text(encoding="utf-8")), {"user": True})
            self.assertFalse((target / "deleted.json").exists())
            marker = target / bootstrap.USER_WORKSPACE_SEED_MARKER
            self.assertTrue(marker.exists())

            existing.unlink()
            self._seed(root / "user", gui_root)
            self.assertEqual(list(target.glob("*.json")), [])

    def test_empty_first_run_can_receive_packaged_workspace_once(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            gui_root = root / "package" / "HBV-Studio"
            source = gui_root / "workspaces"
            source.mkdir(parents=True)
            (source / "example.json").write_text('{"流域名称": "example"}', encoding="utf-8")

            self._seed(root / "user", gui_root)

            copied = root / "user" / "workspaces" / "example.json"
            self.assertTrue(copied.exists())
            self.assertEqual(json.loads(copied.read_text(encoding="utf-8"))["流域名称"], "example")
            self.assertTrue((copied.parent / bootstrap.USER_WORKSPACE_SEED_MARKER).exists())

    def test_installed_startup_recovers_wizard_workspace_from_app_directory(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            gui_root = root / "app" / "HBV-Studio"
            misplaced = gui_root / "workspaces" / "区间流域.json"
            misplaced.parent.mkdir(parents=True)
            misplaced.write_text('{"流域名称": "区间流域"}', encoding="utf-8")
            user_root = root / "app" / "用户数据"

            with (
                patch.object(bootstrap, "installed_mode", return_value=True),
                patch.object(bootstrap, "GUI_ROOT", gui_root),
            ):
                bootstrap.migrate_misplaced_installed_workspaces(user_root)

            recovered = user_root / "workspaces" / misplaced.name
            self.assertTrue(recovered.exists())
            self.assertEqual(json.loads(recovered.read_text(encoding="utf-8"))["流域名称"], "区间流域")

            recovered.write_text('{"流域名称": "用户新版"}', encoding="utf-8")
            misplaced.write_text('{"流域名称": "安装目录旧版"}', encoding="utf-8")
            with (
                patch.object(bootstrap, "installed_mode", return_value=True),
                patch.object(bootstrap, "GUI_ROOT", gui_root),
            ):
                bootstrap.migrate_misplaced_installed_workspaces(user_root)
            self.assertEqual(json.loads(recovered.read_text(encoding="utf-8"))["流域名称"], "用户新版")


if __name__ == "__main__":
    unittest.main()
