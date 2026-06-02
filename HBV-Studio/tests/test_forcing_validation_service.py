from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path
from typing import Any

import pandas as pd


STUDIO_DIR = Path(__file__).resolve().parents[1]
if str(STUDIO_DIR) not in sys.path:
    sys.path.insert(0, str(STUDIO_DIR))

from services.forcing_validation import (  # noqa: E402
    ForcingAlignedStatusContext,
    ForcingInputsReadyContext,
    ForcingPreprocessStatusContext,
    ForcingValidationContext,
    check_aligned_forcing_status,
    check_daily_era5_processed_status,
    check_daily_prec_status,
    check_daily_temp_evap_status,
    check_forcing_inputs_ready,
    check_hourly_prec_status,
    check_hourly_temp_evap_status,
    configured_daily_meteo_sources,
    prefer_raw_or_aligned_group_status,
    validate_forcing_bundle,
)


class ForcingValidationServiceTests(unittest.TestCase):
    def _aligned_context(
        self,
        *,
        scan_results: dict[str, dict[str, Any]] | None = None,
        calls: list[tuple[Any, ...]] | None = None,
    ) -> ForcingAlignedStatusContext:
        results = scan_results or {
            "降水": {"ok": True, "errors": [], "warnings": [], "valid_time_steps": 3},
            "气温": {"ok": True, "errors": [], "warnings": [], "valid_time_steps": 2},
            "蒸散发": {"ok": True, "errors": [], "warnings": [], "valid_time_steps": 1},
        }
        call_log = calls if calls is not None else []

        def build_profile_paths(config: dict[str, Any], profile: str) -> dict[str, Any]:
            call_log.append(("paths", profile))
            return {
                "aligned_temp_dir": "temp_dir",
                "aligned_evap_dir": "evap_dir",
            }

        def effective_precip_paths(config: dict[str, Any], profile: str, **kwargs: Any) -> tuple[Path, Path, str]:
            call_log.append(("precip", profile, kwargs.get("precip_source")))
            return Path("prec_base"), Path("prec_effective"), "era5"

        def validate_tif_time_series(label: str, directory: Path, step_hours: float) -> dict[str, Any]:
            call_log.append(("scan", label, directory, step_hours))
            return results[label]

        return ForcingAlignedStatusContext(
            build_profile_paths=build_profile_paths,
            effective_precip_paths=effective_precip_paths,
            normalize_time_step_hours=lambda value: 24.0,
            validate_tif_time_series=validate_tif_time_series,
        )

    def _context(
        self,
        *,
        time_basis: str = "continuous",
        selected_source: str = "era5",
        grid_error_label: str = "",
    ) -> ForcingValidationContext:
        expected_index = pd.date_range("2021-01-01", periods=2, freq="D")

        def validate_tif_time_series(label: str, directory: Path, step_hours: float, expected: Any, time_basis_label: str) -> dict[str, Any]:
            if label.startswith("降水"):
                return {
                    "label": label,
                    "errors": ["降水缺少 1 个时间步"],
                    "warnings": ["降水有 1 个时间步落在率定时段之外"],
                    "valid_time_steps": 2,
                }
            if label == "气温":
                return {"label": label, "errors": [], "warnings": [], "valid_time_steps": 2}
            return {
                "label": label,
                "errors": [],
                "warnings": ["蒸散发有 1 个时间步落在率定时段之外"],
                "valid_time_steps": 1,
            }

        def validate_tif_grid_alignment(label: str, directory: Path, dem_path: Path) -> dict[str, Any]:
            if label == grid_error_label:
                return {"label": label, "ok": False, "checked_files": 1, "error": f"{label}目录存在与 DEM 网格不一致的 tif：bad.tif"}
            return {"label": label, "ok": True, "checked_files": 1, "error": None}

        return ForcingValidationContext(
            current_profile=lambda config: "daily",
            build_profile_paths=lambda config, profile: {
                "aligned_temp_dir": "temp_dir",
                "aligned_evap_dir": "evap_dir",
                "gis_dir": "gis_dir",
            },
            normalize_time_step_hours=lambda value: 24.0,
            task_time_basis=lambda config, **kwargs: time_basis,
            time_basis_labels={"continuous": "率定时段", "event_windows": "洪水事件窗口"},
            time_basis_event_windows="event_windows",
            build_expected_forcing_index=lambda config, **kwargs: expected_index,
            normalized_flood_events=lambda config, **kwargs: {"events": [{"event_id": "E1"}]},
            effective_precip_paths=lambda config, profile, **kwargs: (Path("prec_base"), Path("prec_dir"), selected_source),
            validate_tif_time_series=validate_tif_time_series,
            workspace_dem_path=lambda gis_dir, **kwargs: Path("dem.tif"),
            configured_dem_kind=lambda config: "1km",
            validate_tif_grid_alignment=validate_tif_grid_alignment,
            event_windows_ui_summary=lambda event_info, step_hours: {"event_count": len(event_info["events"])},
            event_forcing_coverage_summary=lambda event_info, directories, step_hours: {"status": "ok", "event_count": len(event_info["events"])},
        )

    def _inputs_ready_context(
        self,
        base_dir: Path,
        *,
        forcing: dict[str, Any],
        calls: list[tuple[Any, ...]] | None = None,
    ) -> ForcingInputsReadyContext:
        call_log = calls if calls is not None else []
        gis_dir = base_dir / "gis"

        def build_profile_paths(config: dict[str, Any], profile: str) -> dict[str, Any]:
            call_log.append(("paths", profile))
            return {"gis_dir": gis_dir}

        def workspace_dem_path(gis_path: Path, **kwargs: Any) -> Path:
            call_log.append(("dem", gis_path, kwargs.get("prefer")))
            return Path(gis_path) / "dem.tif"

        def resolve_config_related_path(config: dict[str, Any], raw_value: Any) -> Path | None:
            call_log.append(("resolve", raw_value))
            if raw_value in (None, ""):
                return None
            return base_dir / str(raw_value)

        def validate_forcing(config: dict[str, Any], profile: str, **kwargs: Any) -> dict[str, Any]:
            call_log.append(("forcing", profile, kwargs.get("precip_source")))
            return forcing

        return ForcingInputsReadyContext(
            build_profile_paths=build_profile_paths,
            workspace_dem_path=workspace_dem_path,
            configured_dem_kind=lambda config: "1km",
            resolve_config_related_path=resolve_config_related_path,
            validate_forcing_bundle=validate_forcing,
            observed_flow_key="观测径流_csv",
        )

    def _preprocess_context(
        self,
        *,
        precip_source: str = "era5",
        effective_source: str | None = None,
        scan_results: dict[str, dict[str, Any]] | None = None,
        counts: dict[Path, int] | None = None,
        calls: list[tuple[Any, ...]] | None = None,
    ) -> ForcingPreprocessStatusContext:
        call_log = calls if calls is not None else []
        results = scan_results or {}
        count_map = counts or {}

        profile_paths = {
            "raw_temp_daily_dir": "raw_daily_temp",
            "raw_evap_daily_dir": "raw_daily_evap",
            "aligned_temp_dir": "aligned_daily_temp",
            "aligned_evap_dir": "aligned_daily_evap",
            "raw_prec_era5_daily_dir": "raw_daily_era5",
            "raw_prec_cmfd_daily_dir": "raw_daily_cmfd",
            "raw_prec_daily_dir": "raw_daily_default",
            "aligned_prec_era5_base_dir": "aligned_daily_era5",
            "aligned_prec_cmfd_base_dir": "aligned_daily_cmfd",
            "aligned_prec_base_dir": "aligned_daily_default",
            "aligned_prec_custom_base_dir": "aligned_custom",
        }
        hourly_profile_paths = {
            "aligned_temp_dir": "aligned_hourly_temp",
            "aligned_evap_dir": "aligned_hourly_evap",
            "aligned_prec_era5_base_dir": "aligned_hourly_era5",
            "aligned_prec_cmfd_base_dir": "aligned_hourly_cmfd",
            "aligned_prec_base_dir": "aligned_hourly_default",
            "aligned_prec_custom_base_dir": "aligned_hourly_custom",
        }
        workspace_paths = {
            "raw_temp_hourly_dir": "raw_hourly_temp",
            "raw_evap_hourly_dir": "raw_hourly_evap",
            "raw_prec_era5_hourly_dir": "raw_hourly_era5",
            "raw_prec_cmfd_hourly_dir": "raw_hourly_cmfd",
            "raw_prec_hourly_dir": "raw_hourly_default",
        }

        def build_profile_paths(config: dict[str, Any], profile: str) -> dict[str, Any]:
            call_log.append(("profile_paths", profile))
            if profile == "hourly":
                return hourly_profile_paths
            return profile_paths

        def build_workspace_paths(config: dict[str, Any]) -> dict[str, Any]:
            call_log.append(("workspace_paths",))
            return workspace_paths

        def validate_tif_time_series(label: str, directory: Path, step_hours: float) -> dict[str, Any]:
            call_log.append(("scan", label, directory, step_hours))
            return results.get(
                label,
                {
                    "label": label,
                    "ok": False,
                    "errors": [],
                    "warnings": [],
                    "valid_time_steps": 0,
                    "total_files": 0,
                },
            )

        def count_matching(path: Path, pattern: str = "*.tif") -> int:
            call_log.append(("count", path, pattern))
            return count_map.get(path, 0)

        return ForcingPreprocessStatusContext(
            build_workspace_paths=build_workspace_paths,
            build_profile_paths=build_profile_paths,
            resolve_precip_source=lambda config, source: str(source or precip_source),
            effective_precip_source=lambda source: effective_source or source,
            count_matching=count_matching,
            validate_tif_time_series=validate_tif_time_series,
        )

    def test_check_aligned_forcing_status_sums_valid_time_steps(self) -> None:
        calls: list[tuple[Any, ...]] = []
        context = self._aligned_context(calls=calls)

        ready, message, count = check_aligned_forcing_status(
            {"时间步长_小时": 24},
            context,
            profile="daily",
            label="日尺度",
            precip_source="custom_tif",
        )

        self.assertTrue(ready)
        self.assertEqual(message, "日尺度气象驱动有效时间步：6")
        self.assertEqual(count, 6)
        self.assertEqual(calls[0], ("paths", "daily"))
        self.assertEqual(calls[1], ("precip", "daily", "custom_tif"))
        self.assertEqual(calls[2], ("scan", "降水", Path("prec_base"), 24.0))
        self.assertEqual(calls[3], ("scan", "气温", Path("temp_dir"), 24.0))
        self.assertEqual(calls[4], ("scan", "蒸散发", Path("evap_dir"), 24.0))

    def test_check_aligned_forcing_status_reports_first_scan_errors(self) -> None:
        context = self._aligned_context(
            scan_results={
                "降水": {"ok": False, "errors": ["降水缺少 1 个时间步", "降水第二条"], "warnings": [], "valid_time_steps": 1},
                "气温": {"ok": True, "errors": [], "warnings": [], "valid_time_steps": 2},
                "蒸散发": {"ok": False, "errors": ["蒸散发目录为空"], "warnings": [], "valid_time_steps": 0},
            }
        )

        ready, message, count = check_aligned_forcing_status(
            {"时间步长_小时": 24},
            context,
            profile="hourly",
            label="小时尺度",
        )

        self.assertFalse(ready)
        self.assertEqual(message, "降水缺少 1 个时间步；蒸散发目录为空")
        self.assertEqual(count, 3)

    def test_check_forcing_inputs_ready_requires_base_files_and_valid_forcing(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            base_dir = Path(temp_dir)
            gis_dir = base_dir / "gis"
            gis_dir.mkdir()
            for path in [
                gis_dir / "dem.tif",
                gis_dir / "flow_accumulation_masked.tif",
                base_dir / "basin.shp",
                base_dir / "obs.csv",
            ]:
                path.write_text("ok", encoding="utf-8")
            calls: list[tuple[Any, ...]] = []
            context = self._inputs_ready_context(
                base_dir,
                forcing={"ok": True, "errors": [], "total_valid_steps": 5},
                calls=calls,
            )

            ready, message, count = check_forcing_inputs_ready(
                {"流域边界_shp": "basin.shp", "观测径流_csv": "obs.csv"},
                context,
                profile="daily",
                precip_source="custom_tif",
            )

        self.assertTrue(ready)
        self.assertEqual(message, "基础输入齐全；气象驱动有效时间步数：5")
        self.assertEqual(count, 6)
        self.assertEqual(calls[0], ("paths", "daily"))
        self.assertEqual(calls[1], ("dem", gis_dir, "1km"))
        self.assertEqual(calls[-1], ("forcing", "daily", "custom_tif"))

    def test_check_forcing_inputs_ready_reports_missing_base_and_first_forcing_errors(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            base_dir = Path(temp_dir)
            context = self._inputs_ready_context(
                base_dir,
                forcing={
                    "ok": False,
                    "errors": ["气象缺少降水", "气象缺少气温", "气象缺少蒸散发"],
                    "total_valid_steps": 3,
                },
            )

            ready, message, count = check_forcing_inputs_ready(
                {},
                context,
                profile="hourly",
                forcing_label="小时",
            )

        self.assertFalse(ready)
        self.assertEqual(message, "基础输入缺失；小时气象驱动有效时间步数：3；问题：气象缺少降水；气象缺少气温")
        self.assertEqual(count, 3)

    def test_prefer_raw_or_aligned_group_status_prefers_ready_raw_series(self) -> None:
        context = self._preprocess_context(
            scan_results={
                "raw": {"label": "raw", "ok": True, "errors": [], "warnings": [], "valid_time_steps": 4, "total_files": 4},
                "aligned": {"label": "aligned", "ok": True, "errors": [], "warnings": [], "valid_time_steps": 2, "total_files": 2},
            }
        )

        ready, message, count = prefer_raw_or_aligned_group_status(
            [("raw", Path("raw_dir"))],
            [("aligned", Path("aligned_dir"))],
            24.0,
            context,
        )

        self.assertTrue(ready)
        self.assertEqual(message, "raw: 4")
        self.assertEqual(count, 4)

    def test_prefer_raw_or_aligned_group_status_falls_back_to_ready_aligned_series(self) -> None:
        context = self._preprocess_context(
            scan_results={
                "raw": {"label": "raw", "ok": False, "errors": ["raw 缺少时间步"], "warnings": [], "valid_time_steps": 1, "total_files": 1},
                "aligned": {"label": "aligned", "ok": True, "errors": [], "warnings": [], "valid_time_steps": 3, "total_files": 3},
            }
        )

        ready, message, count = prefer_raw_or_aligned_group_status(
            [("raw", Path("raw_dir"))],
            [("aligned", Path("aligned_dir"))],
            24.0,
            context,
        )

        self.assertTrue(ready)
        self.assertEqual(message, "aligned: 3（已导入并完成网格对齐）")
        self.assertEqual(count, 3)

    def test_configured_daily_meteo_sources_uses_defaults_and_legacy_pet_key(self) -> None:
        self.assertEqual(configured_daily_meteo_sources({}), ("era5", "era5_fao56"))
        self.assertEqual(
            configured_daily_meteo_sources({"气象策略": {"温度来源": " CUSTOM_TIF ", "蒸散发来源": " custom_tif "}}),
            ("custom_tif", "custom_tif"),
        )

    def test_check_daily_temp_evap_status_uses_daily_profile_paths(self) -> None:
        context = self._preprocess_context(
            scan_results={
                "日尺度 ERA5 温度中间结果": {
                    "label": "日尺度 ERA5 温度中间结果",
                    "ok": True,
                    "errors": [],
                    "warnings": [],
                    "valid_time_steps": 3,
                    "total_files": 3,
                },
                "日尺度潜在蒸散发中间结果": {
                    "label": "日尺度潜在蒸散发中间结果",
                    "ok": True,
                    "errors": [],
                    "warnings": [],
                    "valid_time_steps": 2,
                    "total_files": 2,
                },
                "工程气温输入": {"label": "工程气温输入", "ok": True, "errors": [], "warnings": [], "valid_time_steps": 1, "total_files": 1},
                "工程潜在蒸散发输入": {"label": "工程潜在蒸散发输入", "ok": True, "errors": [], "warnings": [], "valid_time_steps": 1, "total_files": 1},
            }
        )

        ready, message, count = check_daily_temp_evap_status({}, context, profile="daily")

        self.assertTrue(ready)
        self.assertEqual(message, "日尺度 ERA5 温度中间结果: 3；日尺度潜在蒸散发中间结果: 2")
        self.assertEqual(count, 5)

    def test_check_daily_era5_processed_status_skips_when_temp_and_pet_are_custom_tif(self) -> None:
        context = self._preprocess_context()

        ready, message, count = check_daily_era5_processed_status(
            {"气象策略": {"温度来源": "custom_tif", "潜在蒸散发来源": "custom_tif"}},
            context,
            profile="daily",
        )

        self.assertTrue(ready)
        self.assertEqual(message, "当前方案不需要这一步。")
        self.assertEqual(count, 0)

    def test_check_hourly_temp_evap_status_falls_back_to_aligned_paths(self) -> None:
        calls: list[tuple[Any, ...]] = []
        context = self._preprocess_context(
            scan_results={
                "小时尺度 ERA5 温度中间结果": {
                    "label": "小时尺度 ERA5 温度中间结果",
                    "ok": False,
                    "errors": ["小时气温时间步不连续"],
                    "warnings": [],
                    "valid_time_steps": 1,
                    "total_files": 1,
                },
                "小时尺度潜在蒸散发中间结果": {
                    "label": "小时尺度潜在蒸散发中间结果",
                    "ok": False,
                    "errors": ["小时蒸散发时间步不连续"],
                    "warnings": [],
                    "valid_time_steps": 1,
                    "total_files": 1,
                },
                "工程气温输入": {"label": "工程气温输入", "ok": True, "errors": [], "warnings": [], "valid_time_steps": 4, "total_files": 4},
                "工程潜在蒸散发输入": {
                    "label": "工程潜在蒸散发输入",
                    "ok": True,
                    "errors": [],
                    "warnings": [],
                    "valid_time_steps": 4,
                    "total_files": 4,
                },
            },
            calls=calls,
        )

        ready, message, count = check_hourly_temp_evap_status({}, context, profile="hourly")

        self.assertTrue(ready)
        self.assertEqual(message, "工程气温输入: 4；工程潜在蒸散发输入: 4（已导入并完成网格对齐）")
        self.assertEqual(count, 8)
        self.assertIn(("scan", "小时尺度 ERA5 温度中间结果", Path("raw_hourly_temp"), 1.0), calls)
        self.assertIn(("scan", "工程潜在蒸散发输入", Path("aligned_hourly_evap"), 1.0), calls)

    def test_check_daily_prec_status_handles_custom_tif_without_raw_processing(self) -> None:
        context = self._preprocess_context(
            precip_source="custom_tif",
            counts={Path("aligned_custom"): 2},
        )

        ready, message, count = check_daily_prec_status({}, context, profile="daily")

        self.assertTrue(ready)
        self.assertEqual(message, "当前为本地栅格降水模式，降水已导入工程独立降水目录。")
        self.assertEqual(count, 2)

    def test_check_hourly_prec_status_uses_effective_cmfd_paths(self) -> None:
        calls: list[tuple[Any, ...]] = []
        context = self._preprocess_context(
            precip_source="cmfd",
            effective_source="cmfd",
            scan_results={
                "小时尺度降水中间结果": {
                    "label": "小时尺度降水中间结果",
                    "ok": False,
                    "errors": ["小时降水时间步不连续"],
                    "warnings": [],
                    "valid_time_steps": 1,
                    "total_files": 1,
                },
                "工程降水输入": {
                    "label": "工程降水输入",
                    "ok": True,
                    "errors": [],
                    "warnings": [],
                    "valid_time_steps": 5,
                    "total_files": 5,
                },
            },
            calls=calls,
        )

        ready, message, count = check_hourly_prec_status({}, context, profile="hourly")

        self.assertTrue(ready)
        self.assertEqual(message, "工程降水输入: 5（已导入并完成网格对齐）")
        self.assertEqual(count, 5)
        self.assertIn(("workspace_paths",), calls)
        self.assertIn(("scan", "小时尺度降水中间结果", Path("raw_hourly_cmfd"), 1.0), calls)
        self.assertIn(("scan", "工程降水输入", Path("aligned_hourly_cmfd"), 1.0), calls)

    def test_validate_forcing_bundle_aggregates_directory_and_grid_messages(self) -> None:
        context = self._context(selected_source="custom_tif", grid_error_label="气温")

        result = validate_forcing_bundle({"时间步长_小时": 24}, context, profile="daily", precip_source="custom_tif")

        self.assertFalse(result["ok"])
        self.assertEqual(result["profile"], "daily")
        self.assertEqual(result["time_basis"], "continuous")
        self.assertEqual(result["time_basis_label"], "率定时段")
        self.assertEqual(result["expected_steps"], 2)
        self.assertEqual(result["total_valid_steps"], 5)
        self.assertEqual(result["directories"]["prec"]["label"], "降水（本地栅格）")
        self.assertEqual(result["errors"], ["降水缺少 1 个时间步", "气温目录存在与 DEM 网格不一致的 tif：bad.tif"])
        self.assertEqual(
            result["warnings"],
            ["降水有 1 个时间步落在率定时段之外", "蒸散发有 1 个时间步落在率定时段之外"],
        )
        self.assertIsNone(result["event_windows"])
        self.assertIsNone(result["event_forcing_coverage"])

    def test_validate_forcing_bundle_includes_event_window_summaries(self) -> None:
        context = self._context(time_basis="event_windows")

        result = validate_forcing_bundle({"时间步长_小时": 24}, context)

        self.assertEqual(result["time_basis"], "event_windows")
        self.assertEqual(result["time_basis_label"], "洪水事件窗口")
        self.assertEqual(result["event_windows"], {"event_count": 1})
        self.assertEqual(result["event_forcing_coverage"], {"status": "ok", "event_count": 1})


if __name__ == "__main__":
    unittest.main()
