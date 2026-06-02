from __future__ import annotations

import sys
import unittest
from pathlib import Path
from typing import Any

import pandas as pd


STUDIO_DIR = Path(__file__).resolve().parents[1]
if str(STUDIO_DIR) not in sys.path:
    sys.path.insert(0, str(STUDIO_DIR))

from services.forcing_validation import (  # noqa: E402
    ForcingAlignedStatusContext,
    ForcingValidationContext,
    check_aligned_forcing_status,
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
