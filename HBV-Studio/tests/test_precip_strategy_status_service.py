from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path
from typing import Any


STUDIO_DIR = Path(__file__).resolve().parents[1]
if str(STUDIO_DIR) not in sys.path:
    sys.path.insert(0, str(STUDIO_DIR))

from services.precip_strategy_status import (  # noqa: E402
    PrecipStrategyStatusContext,
    check_precip_strategy_outputs,
)


class PrecipStrategyStatusServiceTests(unittest.TestCase):
    def _context(
        self,
        root: Path,
        *,
        selected_source: str = "era5",
        read_json_raises: bool = False,
    ) -> PrecipStrategyStatusContext:
        base_dir = root / "base"
        corrected_dir = root / "corrected"
        base_dir.mkdir()
        corrected_dir.mkdir()

        def count_matching(path: Any) -> int:
            return len(list(Path(path).glob("*.tif")))

        def read_json_file(path: Path) -> dict[str, Any]:
            if read_json_raises:
                raise ValueError("bad json")
            return json.loads(path.read_text(encoding="utf-8"))

        return PrecipStrategyStatusContext(
            meteo_key="气象策略",
            meteo_precip_mode_key="降水方案",
            current_profile=lambda config: "daily",
            effective_precip_paths=lambda config, profile, **kwargs: (base_dir, corrected_dir, selected_source),
            count_matching=count_matching,
            read_json_file=read_json_file,
        )

    def test_grid_only_reports_baseline_output_count(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            context = self._context(root)
            (root / "base" / "prec_2021.01.01.tif").write_bytes(b"")

            ok, message, count = check_precip_strategy_outputs({"气象策略": {"降水方案": "grid_only"}}, context)

        self.assertTrue(ok)
        self.assertEqual(message, "当前为格点基线方案，不需要额外订正。")
        self.assertEqual(count, 1)

    def test_grid_only_custom_tif_uses_local_raster_label(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            context = self._context(root, selected_source="custom_tif")

            ok, message, count = check_precip_strategy_outputs({"气象策略": {"降水方案": "grid_only"}}, context)

        self.assertFalse(ok)
        self.assertEqual(message, "当前为本地栅格基线方案，不需要额外订正。")
        self.assertEqual(count, 0)

    def test_station_bias_summary_builds_detailed_message(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            context = self._context(root)
            corrected = root / "corrected"
            (corrected / "prec_2021.01.01.tif").write_bytes(b"")
            (corrected / "precipitation_strategy_summary.json").write_text(
                json.dumps(
                    {
                        "time_basis_label": "洪水事件窗口",
                        "selected_steps": 10,
                        "written_files": 8,
                        "zero_available_station_steps": 2,
                        "skipped_out_of_scope_steps": 3,
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )

            ok, message, count = check_precip_strategy_outputs(
                {"气象策略": {"降水方案": "grid_plus_station_bias"}},
                context,
            )

        self.assertTrue(ok)
        self.assertEqual(
            message,
            "站点订正降水文件数：1；资料口径：洪水事件窗口；参与时段：8/10；无可用站点时段：2；已忽略口径外时段：3",
        )
        self.assertEqual(count, 1)

    def test_thiessen_summary_read_error_falls_back_to_count_message(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            context = self._context(root, read_json_raises=True)
            corrected = root / "corrected"
            (corrected / "prec_2021.01.01.tif").write_bytes(b"")
            (corrected / "precipitation_strategy_summary.json").write_text("{bad", encoding="utf-8")

            ok, message, count = check_precip_strategy_outputs(
                {"气象策略": {"降水方案": "thiessen_station_only"}},
                context,
            )

        self.assertTrue(ok)
        self.assertEqual(message, "泰森插值降水文件数：1")
        self.assertEqual(count, 1)

    def test_station_bias_summary_includes_hydrological_diagnostics(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            context = self._context(root)
            corrected = root / "corrected"
            (corrected / "prec_2021.01.01.tif").write_bytes(b"")
            (corrected / "precipitation_strategy_summary.json").write_text(
                json.dumps(
                    {
                        "time_basis_label": "连续时段",
                        "selected_steps": 1,
                        "written_files": 1,
                        "hydrological_diagnostics": {
                            "station_day_samples_available": 24,
                            "station_day_samples_total": 25,
                            "station_day_missing_rate_percent": 4.0,
                            "station_point_before": {"sample_count": 24, "mae_mm": 3.5, "pbias_percent": -20.0},
                            "station_point_after": {"sample_count": 24, "mae_mm": 1.2, "pbias_percent": -5.0},
                            "basin_precip_total_before_mm": 100.0,
                            "basin_precip_total_after_mm": 120.0,
                            "basin_precip_total_change_percent": 20.0,
                            "correction_factor_mean": 1.2,
                            "ratio_clip_step_count": 1,
                            "grid_missed_precip_repair_step_count": 0,
                            "hydrological_time_basis_note": "小时站点降水已按水文日 08:00-次日08:00 累计为日降水。",
                        },
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )

            ok, message, count = check_precip_strategy_outputs(
                {"气象策略": {"降水方案": "grid_plus_station_bias"}},
                context,
            )

        self.assertTrue(ok)
        self.assertEqual(count, 1)
        self.assertIn("站点日样本：24/25，缺测率 4.0%", message)
        self.assertIn("站点处MAE：3.50 mm→1.20 mm；PBIAS：-20.0%→-5.0%", message)
        self.assertIn("流域面降水总量：100.0 mm→120.0 mm（20.0%）", message)
        self.assertIn("时间口径：小时站点降水已按水文日 08:00-次日08:00 累计为日降水。", message)


if __name__ == "__main__":
    unittest.main()
