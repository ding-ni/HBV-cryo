import sys
import tempfile
import unittest
from pathlib import Path


STUDIO_DIR = Path(__file__).resolve().parents[1]
if str(STUDIO_DIR) not in sys.path:
    sys.path.insert(0, str(STUDIO_DIR))

from services.run_hydrology import (  # noqa: E402
    RunHydrologyContext,
    build_hydrology_summary,
    ensure_hydrology_diagnostic_report,
    hydrology_diagnostic_report_text,
    metadata_objective_family,
    objective_label_zh,
)


class RunHydrologyServiceTests(unittest.TestCase):
    def context(self) -> RunHydrologyContext:
        return RunHydrologyContext(to_display_path=lambda path: f"display:{Path(path).name}")

    def sample_metadata(self) -> dict:
        return {
            "recorded_objective_family": "daily_unified_professional_v1",
            "run_time": "2026-06-02 10:00:00",
            "metrics": {
                "calibration": {"nse": 0.72, "kge": 0.66, "pbias": -4.2, "rmse": 18.4},
                "validation": {"nse": 0.58, "kge": 0.53, "pbias": 9.1, "rmse": 21.7},
            },
            "diagnostics": {
                "component_fraction_report": {
                    "rain_fraction": 0.60,
                    "snow_fraction": 0.25,
                    "ice_fraction": 0.15,
                    "evaluation_period": "total_runoff_calibration_period",
                }
            },
            "optional_modules": {"glacier": {"enabled": True}},
            "flood_event_evaluation": {
                "enabled": True,
                "status": "pass",
                "valid_event_count": 1,
                "event_count": 1,
                "objective_enabled": True,
                "events": [
                    {
                        "name": "E1",
                        "type": "calibration",
                        "peak_error_percent": -3.2,
                        "peak_time_error_hours": 2,
                        "volume_error_percent": 4.5,
                        "nse": 0.81,
                        "kge": 0.77,
                        "high_flow_weighted_nse": 0.79,
                        "high_flow_kge": 0.74,
                        "recession_slope_error_percent": 5.0,
                    }
                ],
            },
        }

    def test_summary_and_report_text_are_independent_hydrology_logic(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            run_dir = Path(tmp)
            metadata = self.sample_metadata()
            summary = build_hydrology_summary(metadata, run_dir, self.context())
            report = hydrology_diagnostic_report_text(metadata, summary)

        self.assertEqual(metadata_objective_family(metadata), "daily_unified_professional_v1")
        self.assertEqual(objective_label_zh(metadata), "统一日尺度综合水文目标函数")
        self.assertEqual(summary["workflow_label_zh"], "单流程参数率定")
        self.assertEqual(summary["flow_status_zh"], "径流拟合达标")
        self.assertEqual(summary["ice_status_zh"], "降雨 60.0% / 融雪 25.0% / 裸冰 15.0%")
        self.assertIn("## 4. 洪水事件评价", report)
        self.assertIn("| E1 | calibration | -3.20% | 2.0 h | 4.50% | 0.8100 |", report)
        self.assertIn("| 降雨产流 | 60.0% |", report)
        self.assertIn("- 口径：率定期模拟总流量口径", report)

    def test_diagnostic_report_writer_updates_current_and_legacy_files(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            run_dir = Path(tmp)
            metadata = self.sample_metadata()
            legacy = run_dir / "水文诊断摘要.md"
            legacy.write_text("old", encoding="utf-8")

            summary = build_hydrology_summary(metadata, run_dir, self.context())
            updated = ensure_hydrology_diagnostic_report(run_dir, metadata, summary, self.context())

            current = run_dir / "水文过程复核报告.md"
            self.assertEqual(updated["diagnostics_report_status"], "available")
            self.assertTrue(current.exists())
            self.assertIn("# 水文模拟结果说明", current.read_text(encoding="utf-8"))
            self.assertEqual(legacy.read_text(encoding="utf-8"), current.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
