from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path
from typing import Any


STUDIO_DIR = Path(__file__).resolve().parents[1]
if str(STUDIO_DIR) not in sys.path:
    sys.path.insert(0, str(STUDIO_DIR))

from services.workspace_staging import (  # noqa: E402
    WorkspaceRuntimeDirsContext,
    WorkspaceStagingContext,
    seed_workspace_runtime_dirs,
    stage_observed_runoff_file,
    stage_vector_shapefile,
)


class WorkspaceStagingServiceTests(unittest.TestCase):
    def _context(self, root: Path) -> WorkspaceStagingContext:
        def build_workspace_paths(config: dict[str, Any]) -> dict[str, Any]:
            return {
                "gis_dir": root / "workspace" / "gis",
                "observed_dir": root / "workspace" / "observed",
            }

        return WorkspaceStagingContext(
            resolve_any_path=lambda raw, **kwargs: Path(str(raw)),
            replace_placeholders=lambda value: value,
            build_workspace_paths=build_workspace_paths,
            workspace_dir=root / "workspaces",
            vector_bundle_suffixes=(".shp", ".dbf", ".prj"),
        )

    def test_stage_vector_shapefile_copies_basin_bundle(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            context = self._context(root)
            source = root / "source" / "basin.shp"
            source.parent.mkdir()
            for suffix in [".shp", ".dbf", ".prj"]:
                source.with_suffix(suffix).write_text(f"content:{suffix}", encoding="utf-8")

            staged = stage_vector_shapefile({"运行目录": str(root / "runtime")}, source, context, role="basin")

            self.assertEqual(staged, (root / "workspace" / "gis" / "basin.shp").resolve(strict=False))
            self.assertEqual(staged.read_text(encoding="utf-8"), "content:.shp")
            self.assertEqual(staged.with_suffix(".dbf").read_text(encoding="utf-8"), "content:.dbf")
            self.assertEqual(staged.with_suffix(".prj").read_text(encoding="utf-8"), "content:.prj")

    def test_stage_vector_shapefile_copies_glacier_bundle_to_role_directory(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            context = self._context(root)
            source = root / "glacier.shp"
            source.write_text("shape", encoding="utf-8")

            staged = stage_vector_shapefile({"运行目录": str(root / "runtime")}, source, context, role="glacier")

            self.assertEqual(staged, (root / "workspace" / "gis" / "glacier_shp" / "glacier.shp").resolve(strict=False))
            self.assertEqual(staged.read_text(encoding="utf-8"), "shape")

    def test_stage_vector_shapefile_rejects_invalid_inputs(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            context = self._context(root)
            source = root / "basin.txt"
            source.write_text("shape", encoding="utf-8")

            with self.assertRaisesRegex(ValueError, "只支持 .shp"):
                stage_vector_shapefile({"运行目录": str(root / "runtime")}, source, context, role="basin")
            with self.assertRaisesRegex(ValueError, "路径不是文件"):
                stage_vector_shapefile({"运行目录": str(root / "runtime")}, root / "missing.shp", context, role="basin")
            source.with_suffix(".shp").write_text("shape", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "缺少运行目录"):
                stage_vector_shapefile({}, source.with_suffix(".shp"), context, role="basin")

    def test_stage_observed_runoff_file_copies_supported_file(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            context = self._context(root)
            source = root / "observed.csv"
            source.write_text("date,q\n2026-01-01,1\n", encoding="utf-8")

            staged = stage_observed_runoff_file({"运行目录": str(root / "runtime")}, source, context)

            self.assertEqual(staged, (root / "workspace" / "observed" / "observed.csv").resolve(strict=False))
            self.assertEqual(staged.read_text(encoding="utf-8"), "date,q\n2026-01-01,1\n")

    def test_stage_observed_runoff_file_rejects_unsupported_suffix_and_missing_runtime(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            context = self._context(root)
            source = root / "observed.txt"
            source.write_text("bad", encoding="utf-8")
            csv_source = source.with_suffix(".csv")
            csv_source.write_text("date,q\n", encoding="utf-8")

            with self.assertRaisesRegex(ValueError, "文件类型不支持"):
                stage_observed_runoff_file({"运行目录": str(root / "runtime")}, source, context)
            with self.assertRaisesRegex(ValueError, "缺少运行目录"):
                stage_observed_runoff_file({}, csv_source, context)

    def test_seed_workspace_runtime_dirs_creates_expected_directories_once(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            created_paths = {
                "workspace_root": root / "workspace",
                "data_root": root / "workspace" / "data",
                "gis_dir": root / "workspace" / "data" / "gis",
                "observed_dir": root / "workspace" / "data" / "observed",
                "raw_root": root / "workspace" / "data" / "raw",
                "aligned_dir": root / "workspace" / "data" / "aligned",
                "aligned_temp_dir": root / "workspace" / "data" / "aligned" / "temp",
                "aligned_evap_dir": root / "workspace" / "data" / "aligned" / "evap",
                "results_root": root / "workspace" / "results",
            }

            context = WorkspaceRuntimeDirsContext(
                current_profile=lambda config: str(config.get("profile", "daily")),
                build_profile_paths=lambda config, profile: created_paths,
                effective_precip_paths=lambda config, profile: (
                    root / "workspace" / "data" / "aligned" / "prec_base",
                    root / "workspace" / "data" / "aligned" / "prec_run",
                    "era5",
                ),
            )

            seed_workspace_runtime_dirs({"运行目录": str(root / "workspace"), "profile": "daily"}, context)

            for path in list(created_paths.values()) + [
                root / "workspace" / "data" / "aligned" / "prec_base",
                root / "workspace" / "data" / "aligned" / "prec_run",
            ]:
                self.assertTrue(path.is_dir(), str(path))

    def test_seed_workspace_runtime_dirs_skips_empty_runtime_root(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            context = WorkspaceRuntimeDirsContext(
                current_profile=lambda config: "daily",
                build_profile_paths=lambda config, profile: {"workspace_root": root / "should-not-exist"},
                effective_precip_paths=lambda config, profile: (root / "base", root / "run", "era5"),
            )

            seed_workspace_runtime_dirs({}, context)

            self.assertFalse((root / "should-not-exist").exists())


if __name__ == "__main__":
    unittest.main()
