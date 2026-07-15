from __future__ import annotations

import sys
import tempfile
import unittest
import warnings
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

    def test_boundary_zero_fill_rejects_no_overlap(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            path = root / "boundary.csv"
            pd.DataFrame({"date": ["2026-01-01"], "flow": [10.0]}).to_csv(path, index=False, encoding="utf-8-sig")

            with self.assertRaisesRegex(ValueError, "没有与当前模拟时段重叠"):
                read_boundary_inflow_series(
                    str(path),
                    pd.date_range("2026-02-01", periods=3, freq="1D"),
                    date_field="date",
                    flow_field="flow",
                    gap_fill="zero",
                    expected_step_hours=24,
                )

    def test_boundary_zero_fill_allows_explicit_early_diagnostic_subwindow(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            path = root / "boundary.csv"
            pd.DataFrame({"date": ["2026-05-01"], "flow": [10.0]}).to_csv(path, index=False, encoding="utf-8-sig")

            with warnings.catch_warnings(record=True) as caught:
                warnings.simplefilter("always")
                series, enabled = read_boundary_inflow_series(
                    str(path),
                    pd.date_range("2026-01-01", periods=3, freq="1D"),
                    date_field="date",
                    flow_field="flow",
                    gap_fill="zero",
                    expected_step_hours=24,
                    allow_no_overlap=True,
                )

        self.assertTrue(enabled)
        self.assertEqual(series.tolist(), [0.0, 0.0, 0.0])
        self.assertTrue(any("诊断子窗口" in str(item.message) for item in caught))

    def test_boundary_zero_fill_warns_on_low_overlap(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            path = root / "boundary.csv"
            pd.DataFrame({"date": ["2026-01-01"], "flow": [10.0]}).to_csv(path, index=False, encoding="utf-8-sig")

            with warnings.catch_warnings(record=True) as caught:
                warnings.simplefilter("always")
                series, enabled = read_boundary_inflow_series(
                    str(path),
                    pd.date_range("2026-01-01", periods=4, freq="1D"),
                    date_field="date",
                    flow_field="flow",
                    gap_fill="zero",
                    expected_step_hours=24,
                )

        self.assertTrue(enabled)
        self.assertEqual(series.tolist(), [10.0, 0.0, 0.0, 0.0])
        self.assertTrue(any("内仅覆盖" in str(item.message) for item in caught))

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

    def test_boundary_excel_selects_the_sheet_with_valid_time_and_flow(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "boundary_multi_sheet.xlsx"
            with pd.ExcelWriter(path, engine="openpyxl") as writer:
                pd.DataFrame({"说明": ["项目资料", "非数据页"]}).to_excel(
                    writer, sheet_name="说明", index=False
                )
                pd.DataFrame(
                    {
                        "监测时间": pd.date_range("2026-05-01 08:00", periods=24, freq="1h"),
                        "上游流量(m^3/s)": range(24),
                    }
                ).to_excel(writer, sheet_name="小时流量", index=False)
            context = BoundaryInflowInspectContext(
                resolve_path=lambda raw, must_exist=True: Path(raw),
                profile_daily="daily",
                profile_hourly="hourly",
            )

            preview = inspect_boundary_inflow_csv(str(path), context, date_field="", flow_field="")
            series, enabled = read_boundary_inflow_series(
                str(path),
                pd.date_range("2026-05-01 08:00", periods=24, freq="1h"),
                date_field="",
                flow_field="",
                expected_step_hours=1,
            )

        self.assertEqual(preview["sheet_name"], "小时流量")
        self.assertEqual(preview["date_field"], "监测时间")
        self.assertEqual(preview["flow_field"], "上游流量(m^3/s)")
        self.assertTrue(enabled)
        self.assertEqual(series.tolist(), list(range(24)))

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
