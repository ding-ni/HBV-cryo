from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path
from typing import Any


STUDIO_DIR = Path(__file__).resolve().parents[1]
if str(STUDIO_DIR) not in sys.path:
    sys.path.insert(0, str(STUDIO_DIR))

from services.filesystem import (  # noqa: E402
    FilesystemPathContext,
    ensure_within,
    is_within_any_root,
    is_within_root,
    resolve_any_path,
    to_display_path,
)


class FilesystemServiceTests(unittest.TestCase):
    def _context(self, project_root: Path, gui_root: Path) -> FilesystemPathContext:
        def replace_placeholders(value: Any, **kwargs: Any) -> Any:
            if not isinstance(value, str):
                return value
            return (
                value
                .replace("__PROJECT_ROOT__", str(project_root))
                .replace("__GUI_ROOT__", str(gui_root))
            )

        return FilesystemPathContext(
            gui_root=gui_root,
            project_root=project_root,
            replace_placeholders=replace_placeholders,
            remap_legacy_project_path=lambda value, **kwargs: value,
        )

    def test_resolve_any_path_expands_placeholders_and_relative_paths(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            project_root = Path(temp_dir)
            gui_root = project_root / "HBV-Studio"
            gui_root.mkdir()
            context = self._context(project_root, gui_root)

            project_path = resolve_any_path("__PROJECT_ROOT__/运行目录/demo", context)
            relative_path = resolve_any_path("workspaces/demo.json", context)

        self.assertEqual(project_path, (project_root / "运行目录" / "demo").resolve(strict=False))
        self.assertEqual(relative_path, (gui_root / "workspaces" / "demo.json").resolve(strict=False))

    def test_resolve_any_path_requires_existing_path_when_requested(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            project_root = Path(temp_dir)
            gui_root = project_root / "HBV-Studio"
            gui_root.mkdir()
            existing = gui_root / "workspaces"
            existing.mkdir()
            context = self._context(project_root, gui_root)

            self.assertEqual(resolve_any_path("workspaces", context, must_exist=True), existing.resolve(strict=False))
            with self.assertRaises(FileNotFoundError):
                resolve_any_path("missing", context, must_exist=True)
            with self.assertRaisesRegex(ValueError, "缺少路径参数"):
                resolve_any_path("", context)

    def test_root_checks_and_display_paths_use_resolved_paths(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            gui_root = root / "HBV-Studio"
            workspace = gui_root / "workspaces" / "demo.json"
            workspace.parent.mkdir(parents=True)
            workspace.write_text("{}", encoding="utf-8")
            outside = root.parent / "outside-demo.json"

            self.assertEqual(ensure_within(gui_root, workspace), workspace.resolve(strict=False))
            self.assertTrue(is_within_root(gui_root, workspace))
            self.assertTrue(is_within_any_root(workspace, (gui_root, root / "other")))
            self.assertFalse(is_within_root(gui_root, outside))
            self.assertEqual(to_display_path(workspace, (gui_root, root)), "workspaces/demo.json")
            with self.assertRaisesRegex(ValueError, "路径超出允许范围"):
                ensure_within(gui_root, outside)


if __name__ == "__main__":
    unittest.main()
