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
    FilesystemPlaceholderContext,
    count_matching,
    ensure_within,
    has_matching,
    is_within_any_root,
    is_within_root,
    normalize_legacy_project_paths,
    placeholder_roots_for_config_path,
    remap_legacy_project_path,
    replace_placeholders,
    resolve_config_related_path,
    resolve_any_path,
    same_path,
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

    def _placeholder_context(self, project_root: Path, gui_root: Path) -> FilesystemPlaceholderContext:
        return FilesystemPlaceholderContext(project_root=project_root, gui_root=gui_root)

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

    def test_placeholder_roots_and_replacement_use_context_roots(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            project_root = Path(temp_dir) / "CurrentProject"
            gui_root = project_root / "HBV-Studio"
            config_path = gui_root / "workspaces" / "demo.json"
            config_path.parent.mkdir(parents=True)
            context = self._placeholder_context(project_root, gui_root)

            detected_project, detected_gui = placeholder_roots_for_config_path(config_path, context)
            payload = replace_placeholders(
                {
                    "workspace": "__GUI_ROOT__/workspaces/demo.json",
                    "items": ["__PROJECT_ROOT__/运行目录/demo"],
                },
                context,
            )

        self.assertEqual(detected_project, project_root.resolve(strict=False))
        self.assertEqual(detected_gui, gui_root.resolve(strict=False))
        self.assertEqual(Path(payload["workspace"]).resolve(strict=False), (gui_root / "workspaces" / "demo.json").resolve(strict=False))
        self.assertEqual(
            [Path(item).resolve(strict=False) for item in payload["items"]],
            [(project_root / "运行目录" / "demo").resolve(strict=False)],
        )

    def test_remap_legacy_project_path_uses_current_project_markers(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            project_root = Path(temp_dir) / "CurrentProject"
            gui_root = project_root / "HBV-Studio"
            context = self._placeholder_context(project_root, gui_root)
            legacy_gui_path = project_root.parent / "legacy" / "HBV-Studio" / "workspaces" / "demo.json"
            legacy_runtime_path = (
                project_root.parent
                / "legacy"
                / project_root.name
                / "运行目录"
                / "demo"
            )

            remapped_gui = remap_legacy_project_path(str(legacy_gui_path), context)
            remapped_runtime = remap_legacy_project_path(str(legacy_runtime_path), context)

        self.assertEqual(remapped_gui, str((gui_root / "workspaces" / "demo.json").resolve(strict=False)))
        self.assertEqual(remapped_runtime, str((project_root / "运行目录" / "demo").resolve(strict=False)))

    def test_remap_legacy_project_path_preserves_new_external_runtime_path(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            project_root = root / "CurrentProject"
            gui_root = project_root / "HBV-Studio"
            context = self._placeholder_context(project_root, gui_root)
            new_runtime_path = root / "HBVStudio" / "用户数据" / "运行目录" / "New"

            remapped = remap_legacy_project_path(str(new_runtime_path), context)

        self.assertEqual(remapped, str(new_runtime_path))

    def test_normalize_legacy_project_paths_only_rewrites_path_like_fields(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            project_root = Path(temp_dir) / "CurrentProject"
            gui_root = project_root / "HBV-Studio"
            context = self._placeholder_context(project_root, gui_root)
            legacy_root = project_root.parent / "legacy" / project_root.name

            normalized = normalize_legacy_project_paths(
                {
                    "运行目录": str(legacy_root / "运行目录" / "demo"),
                    "title": str(legacy_root / "运行目录" / "not_a_path_label"),
                    "nested": [{"dem_tif": str(legacy_root / "HBV-Cryo" / "dem.tif")}],
                },
                context,
            )

        self.assertEqual(normalized["运行目录"], str((project_root / "运行目录" / "demo").resolve(strict=False)))
        self.assertEqual(normalized["title"], str(legacy_root / "运行目录" / "not_a_path_label"))
        self.assertEqual(
            normalized["nested"][0]["dem_tif"],
            str((project_root / "HBV-Cryo" / "dem.tif").resolve(strict=False)),
        )

    def test_count_matching_and_has_matching_use_glob_patterns(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (root / "a.tif").write_text("", encoding="utf-8")
            (root / "b.txt").write_text("", encoding="utf-8")
            (root / "nested").mkdir()
            (root / "nested" / "c.tif").write_text("", encoding="utf-8")

            tif_count = count_matching(root)
            txt_count = count_matching(root, "*.txt")
            has_tif = has_matching(root)
            has_csv = has_matching(root, "*.csv")
            missing_count = count_matching(root / "missing")
            missing_has = has_matching(root / "missing")

        self.assertEqual(tif_count, 1)
        self.assertEqual(txt_count, 1)
        self.assertTrue(has_tif)
        self.assertFalse(has_csv)
        self.assertEqual(missing_count, 0)
        self.assertFalse(missing_has)

    def test_same_path_compares_resolved_paths(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            nested = root / "nested"
            nested.mkdir()

            self.assertTrue(same_path(nested, root / "nested" / ".." / "nested"))
            self.assertFalse(same_path(nested, root / "other"))

    def test_resolve_config_related_path_uses_config_parent_or_default_root(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            config_path = root / "workspaces" / "demo.json"
            config_path.parent.mkdir()
            absolute = root / "absolute.csv"

            relative = resolve_config_related_path({"_config_path": str(config_path)}, "inputs/obs.csv", default_root=root)
            fallback = resolve_config_related_path({}, "inputs/obs.csv", default_root=root)
            resolved_absolute = resolve_config_related_path({}, str(absolute), default_root=root)
            blank = resolve_config_related_path({}, "", default_root=root)

        self.assertEqual(relative, (config_path.parent / "inputs" / "obs.csv").resolve(strict=False))
        self.assertEqual(fallback, (root / "inputs" / "obs.csv").resolve(strict=False))
        self.assertEqual(resolved_absolute, absolute.resolve(strict=False))
        self.assertIsNone(blank)


if __name__ == "__main__":
    unittest.main()
