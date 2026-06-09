from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

import pandas as pd


STUDIO_DIR = Path(__file__).resolve().parents[1]
REPO_DIR = STUDIO_DIR.parent
COMMON_DIR = REPO_DIR / "公共"
if str(STUDIO_DIR) not in sys.path:
    sys.path.insert(0, str(STUDIO_DIR))
if str(COMMON_DIR) not in sys.path:
    sys.path.insert(0, str(COMMON_DIR))

from services.boundary import (  # noqa: E402
    BoundaryInflowInspectContext,
    boundary_info_messages,
    inspect_boundary_inflow_csv,
)
from 上游边界入流 import read_boundary_inflow_series  # noqa: E402


class BoundaryServiceTests(unittest.TestCase):
    def test_inspect_boundary_inflow_csv_reports_stats_and_coverage(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            path = root / "boundary.csv"
            pd.DataFrame(
                [
                    {"date": "2026-01-01", "inflow_m3s": 10.0},
                    {"date": "2026-01-01", "inflow_m3s": 12.0},
                    {"date": "2026-01-03", "inflow_m3s": -1.0},
                    {"date": "bad-time", "inflow_m3s": 5.0},
                    {"date": "2026-01-04", "inflow_m3s": 0.0},
                ]
            ).to_csv(path, index=False, encoding="utf-8-sig")
            context = BoundaryInflowInspectContext(
                resolve_path=lambda raw, must_exist=True: Path(raw),
                profile_daily="daily",
                profile_hourly="hourly",
            )

            result = inspect_boundary_inflow_csv(
                str(path),
                context,
                expected_index=pd.date_range("2026-01-01", periods=4, freq="1D"),
                expected_step_hours=24,
            )

        self.assertEqual(result["total_rows"], 5)
        self.assertEqual(result["valid_rows"], 4)
        self.assertEqual(result["invalid_rows"], 1)
        self.assertEqual(result["duplicate_count"], 1)
        self.assertEqual(result["negative_count"], 1)
        self.assertEqual(result["zero_count"], 1)
        self.assertEqual(result["time_step_hours"], 24.0)
        self.assertEqual(result["expected_steps"], 4)
        self.assertEqual(result["coverage_ratio"], 0.75)
        self.assertEqual(result["suggested_calibration_mode"], "daily")
        self.assertEqual(result["flow_stats"]["min"], -1.0)
        self.assertEqual(result["flow_stats"]["max"], 12.0)
        self.assertEqual([str(ts.date()) for ts in result["missing_steps"]], ["2026-01-02"])
        self.assertEqual(result["out_of_range_steps"], [])

    def test_boundary_info_messages_classifies_issues_and_gap_fill(self) -> None:
        info = {
            "time_step_hours": 1.0,
            "duplicate_count": 1,
            "duplicate_timestamps": [pd.Timestamp("2026-01-01")],
            "negative_count": 2,
            "missing_steps": [pd.Timestamp("2026-01-02")],
            "out_of_range_steps": [pd.Timestamp("2026-01-05")],
            "invalid_rows": 1,
            "zero_count": 9,
            "valid_rows": 10,
        }

        issues, warnings = boundary_info_messages(info, 24.0, gap_fill="interpolate")

        self.assertEqual(len(issues), 3)
        self.assertIn("\u65f6\u95f4\u6b65\u8bc6\u522b\u4e3a 1 \u5c0f\u65f6", issues[0])
        self.assertIn("\u91cd\u590d\u65f6\u95f4\u6233", issues[1])
        self.assertIn("\u8d1f\u6d41\u91cf", issues[2])
        self.assertEqual(len(warnings), 4)
        self.assertIn("\u7ebf\u6027\u63d2\u503c", warnings[0])
        self.assertIn("\u65f6\u95f4\u8303\u56f4\u4e4b\u5916", warnings[1])
        self.assertIn("\u65e0\u6cd5\u89e3\u6790", warnings[2])
        self.assertIn("80%", warnings[3])

    def test_inspect_boundary_inflow_csv_reads_gb18030_and_autodetects_flow(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            path = root / "boundary_gbk.csv"
            pd.DataFrame(
                [
                    {"时间": "2026-01-01", "流量": 10.0},
                    {"时间": "2026-01-02", "流量": 12.0},
                ]
            ).to_csv(path, index=False, encoding="gb18030")
            context = BoundaryInflowInspectContext(
                resolve_path=lambda raw, must_exist=True: Path(raw),
                profile_daily="daily",
                profile_hourly="hourly",
            )

            result = inspect_boundary_inflow_csv(
                str(path),
                context,
                date_field="date",
                flow_field="inflow_m3s",
                expected_index=pd.date_range("2026-01-01", periods=2, freq="1D"),
                expected_step_hours=24,
            )

        self.assertEqual(result["date_field"], "时间")
        self.assertEqual(result["flow_field"], "流量")
        self.assertEqual(result["coverage_ratio"], 1.0)
        self.assertEqual(result["time_step_hours"], 24.0)

    def test_boundary_hourly_series_is_aggregated_to_daily_for_daily_target(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            path = root / "boundary_hourly.csv"
            hours = pd.date_range("2026-01-01 08:00", periods=48, freq="1h")
            values = [1.0] * 24 + [3.0] * 24
            pd.DataFrame({"date": hours, "flow": values}).to_csv(path, index=False, encoding="utf-8-sig")

            series, enabled = read_boundary_inflow_series(
                str(path),
                pd.date_range("2026-01-01", periods=2, freq="1D"),
                date_field="date",
                flow_field="inflow_m3s",
                expected_step_hours=24,
            )

        self.assertTrue(enabled)
        self.assertEqual(series.tolist(), [1.0, 3.0])

    def test_boundary_xlsx_is_supported_by_preview_and_runtime(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            path = root / "boundary.xlsx"
            pd.DataFrame(
                [
                    {"date": "2026-01-01", "flow": 11.0},
                    {"date": "2026-01-02", "flow": 12.5},
                ]
            ).to_excel(path, index=False)
            context = BoundaryInflowInspectContext(
                resolve_path=lambda raw, must_exist=True: Path(raw),
                profile_daily="daily",
                profile_hourly="hourly",
            )

            preview = inspect_boundary_inflow_csv(
                str(path),
                context,
                expected_index=pd.date_range("2026-01-01", periods=2, freq="1D"),
                expected_step_hours=24,
            )
            series, enabled = read_boundary_inflow_series(
                str(path),
                pd.date_range("2026-01-01", periods=2, freq="1D"),
                date_field="date",
                flow_field="flow",
                expected_step_hours=24,
            )

        self.assertEqual(preview["file_kind"], "excel")
        self.assertEqual(preview["coverage_ratio"], 1.0)
        self.assertTrue(enabled)
        self.assertEqual(series.tolist(), [11.0, 12.5])

    def test_inspect_boundary_hourly_file_reports_daily_resampling(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            path = root / "boundary_hourly.csv"
            hours = pd.date_range("2026-01-01 08:00", periods=48, freq="1h")
            pd.DataFrame({"date": hours, "flow": range(48)}).to_csv(path, index=False, encoding="utf-8-sig")
            context = BoundaryInflowInspectContext(
                resolve_path=lambda raw, must_exist=True: Path(raw),
                profile_daily="daily",
                profile_hourly="hourly",
            )

            result = inspect_boundary_inflow_csv(
                str(path),
                context,
                expected_index=pd.date_range("2026-01-01", periods=2, freq="1D"),
                expected_step_hours=24,
            )

        self.assertTrue(result["resampled_to_daily"])
        self.assertEqual(result["source_time_step_hours"], 1.0)
        self.assertEqual(result["time_step_hours"], 24.0)
        self.assertEqual(result["daily_aggregation"]["valid_days"], 2)
        self.assertEqual(result["daily_aggregation"]["day_start_hour"], 8)
        self.assertEqual(result["coverage_ratio"], 1.0)


if __name__ == "__main__":
    unittest.main()
