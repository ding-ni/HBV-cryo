from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path
from typing import Any


STUDIO_DIR = Path(__file__).resolve().parents[1]
if str(STUDIO_DIR) not in sys.path:
    sys.path.insert(0, str(STUDIO_DIR))

from services.workspace_catalog import (  # noqa: E402
    WorkspaceCatalogContext,
    build_empty_workspace,
    detect_object_type,
    detect_profile_from_payload,
    runtime_root_for_workspace,
    slugify_workspace_name,
    suggest_time_windows,
)


class WorkspaceCatalogServiceTests(unittest.TestCase):
    def _context(self, root: Path) -> WorkspaceCatalogContext:
        def no_config(path: Path) -> dict[str, Any]:
            return {}

        glacier = root / "glacier.shp"
        glacier.write_text("", encoding="utf-8")
        dem = root / "dem.tif"
        dem.write_text("", encoding="utf-8")
        return WorkspaceCatalogContext(
            template_dir=root / "templates",
            workspace_dir=root / "workspaces",
            project_runtime_dir=root / "runtime",
            default_workspace_path=root / "workspaces" / "default.json",
            builtin_glacier_shp=glacier,
            builtin_dem=dem,
            profile_daily="daily",
            profile_hourly="hourly",
            time_basis_continuous="continuous",
            object_regression="regression_validation",
            object_interbasin="interbasin_with_boundary",
            object_full_upstream="full_upstream_basin",
            observed_flow_key="observed",
            meteo_key="气象策略",
            meteo_precip_source_key="降水来源",
            meteo_precip_source_legacy_key="降水源",
            read_json_file=no_config,
            read_runtime_config=no_config,
            replace_placeholders=lambda value: value,
            resolve_any_path=lambda raw, **kwargs: Path(raw),
            resolve_profile=lambda config, fallback=None: fallback or "daily",
            normalize_config_before_save=lambda config, path: config,
            default_initial_state={"SP": 0.0, "SM": 10.0},
            write_json_file=lambda path, data: None,
            to_display_path=lambda path: str(path),
            workspace_workflow_summary=lambda *args, **kwargs: {},
            normalize_time_step_hours=lambda value: float(value),
            ensure_within=lambda root, candidate: candidate,
            inspect_observed_csv=lambda *args, **kwargs: {},
            fill_bbox_from_shp=lambda path: {"北": 1, "西": 2, "南": 0, "东": 3},
            suggest_cfmax_threshold=lambda basin, dem: {"suggested_threshold_m": 5000.0},
            stage_vector_shapefile=lambda config, source, **kwargs: Path(source),
            stage_observed_runoff_file=lambda config, source, **kwargs: Path(source),
        )

    def test_slugify_workspace_name_normalizes_invalid_and_reserved_names(self) -> None:
        self.assertEqual(slugify_workspace_name("  通天河 / 上游  "), "通天河_上游")
        self.assertEqual(slugify_workspace_name("CON"), "CON_53ae")
        self.assertEqual(slugify_workspace_name(""), "新工作区")

    def test_runtime_root_for_workspace_uses_slugified_name(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)

            runtime_root = runtime_root_for_workspace("通天河 / 上游", root / "runtime")

        self.assertEqual(runtime_root, root / "runtime" / "通天河_上游")

    def test_build_empty_workspace_uses_catalog_context_defaults(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            context = self._context(root)

            config = build_empty_workspace("通天河", "hourly", context)

        self.assertEqual(config["项目对象"], "full_upstream_basin")
        self.assertEqual(config["率定模式"], "hourly")
        self.assertEqual(config["任务时段模式"], "continuous")
        self.assertEqual(config["运行目录"], str(root / "runtime" / "通天河"))
        self.assertEqual(config["流域编号"], "通天河")
        self.assertEqual(config["DEM_tif"], str((root / "dem.tif").resolve()))
        self.assertEqual(config["observed"], "")
        self.assertEqual(config["时间步长_小时"], 1.0)
        self.assertEqual(config["初始状态"], {"SP": 0.0, "SM": 10.0})
        self.assertEqual(config["气象策略"]["降水来源"], "era5")

    def test_detect_profile_from_payload_prefers_explicit_mode_then_step_hours(self) -> None:
        self.assertEqual(detect_profile_from_payload({"率定模式": "hourly", "时间步长_小时": 24}), "hourly")
        self.assertEqual(detect_profile_from_payload({"时间步长_小时": 1.5}), "hourly")
        self.assertEqual(detect_profile_from_payload({"时间步长_小时": 2}), "daily")
        self.assertEqual(detect_profile_from_payload({"时间步长_小时": "bad"}), "daily")

    def test_detect_object_type_prefers_explicit_mode_then_boundary_file(self) -> None:
        self.assertEqual(detect_object_type({"项目对象": "regression_validation"}), "regression_validation")
        self.assertEqual(
            detect_object_type({"边界条件": {"上游边界入流_csv": "boundary.csv"}}),
            "interbasin_with_boundary",
        )
        self.assertEqual(detect_object_type({}), "full_upstream_basin")

    def test_suggest_time_windows_splits_full_daily_years(self) -> None:
        windows = suggest_time_windows("2001-01-01", "2012-12-31", "daily")

        self.assertEqual(
            windows,
            {
                "预热开始": "2001-01-01",
                "预热结束": "2002-12-31",
                "率定开始": "2003-01-01",
                "率定结束": "2009-12-31",
                "验证开始": "2010-01-01",
                "验证结束": "2012-12-31",
            },
        )

    def test_suggest_time_windows_uses_hourly_format_and_short_period_fallback(self) -> None:
        windows = suggest_time_windows("2026-06-01 08:00", "2026-06-03 20:00", "hourly")

        self.assertEqual(windows["预热开始"], "2026-06-01 08:00")
        self.assertEqual(windows["预热结束"], "2026-06-01 08:00")
        self.assertEqual(windows["率定开始"], "2026-06-02 08:00")
        self.assertEqual(windows["验证结束"], "2026-06-03 20:00")

    def test_suggest_time_windows_handles_reversed_period_without_invalid_split(self) -> None:
        windows = suggest_time_windows("2026-06-03", "2026-06-01", "daily")

        self.assertEqual(windows["预热开始"], "2026-06-03")
        self.assertEqual(windows["预热结束"], "2026-06-03")
        self.assertEqual(windows["率定结束"], "2026-06-01")
        self.assertEqual(windows["验证结束"], "2026-06-01")


if __name__ == "__main__":
    unittest.main()
