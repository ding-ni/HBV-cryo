from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

import pandas as pd


STUDIO_DIR = Path(__file__).resolve().parents[1]
if str(STUDIO_DIR) not in sys.path:
    sys.path.insert(0, str(STUDIO_DIR))

from services.station_precip import (  # noqa: E402
    format_time_for_check,
    index_display_range,
    load_station_metadata_table,
    load_station_precip_table,
    max_consecutive_true,
    station_count_text,
    station_precip_event_coverage_summary,
    station_precip_expected_coverage,
    station_precip_id_match_summary,
    station_precip_mode_label,
    station_precip_task_context_summary,
)


class StationPrecipServiceTests(unittest.TestCase):
    def test_labels_time_formatting_and_counts(self) -> None:
        self.assertEqual(station_precip_mode_label("grid_plus_station_bias"), "\u683c\u70b9 + \u7ad9\u70b9\u504f\u5dee\u8ba2\u6b63")
        self.assertEqual(station_precip_mode_label("thiessen_station_only"), "\u7eaf\u7ad9\u70b9\u6cf0\u68ee\u5206\u914d")
        self.assertEqual(station_precip_mode_label("unknown"), "\u7ad9\u70b9\u964d\u6c34\u65b9\u6848")
        self.assertEqual(format_time_for_check("2026-01-01", 24), "2026-01-01")
        self.assertEqual(format_time_for_check("2026-01-01 06:00", 1), "2026-01-01 06:00")
        self.assertEqual(format_time_for_check("bad-time", 24), "\u672a\u8bc6\u522b")
        self.assertEqual(station_count_text(None, None), "\u672a\u5f62\u6210")
        self.assertEqual(station_count_text(2, None), "2")
        self.assertEqual(station_count_text(1, 1.5), "\u6700\u5c11 1\uff0c\u5e73\u5747 1.5")
        self.assertEqual(max_consecutive_true([False, True, True, False, True, True, True]), 3)

        start, end, count = index_display_range(pd.date_range("2026-01-01", periods=3, freq="1D"), 24)
        self.assertEqual((start, end, count), ("2026-01-01", "2026-01-03", 3))

    def test_load_station_precip_table_reads_wide_format(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "station_precip.csv"
            pd.DataFrame(
                [
                    {"time": "2026-01-02", "S2": "4.2", "S1": "5.1"},
                    {"time": "2026-01-01", "S2": "4.0", "S1": "5.0"},
                ]
            ).to_csv(path, index=False, encoding="utf-8-sig")

            table, table_format, time_col = load_station_precip_table(path)

        self.assertEqual(table_format, "\u5bbd\u8868")
        self.assertEqual(time_col, "time")
        self.assertEqual(list(table.columns), ["S2", "S1"])
        self.assertEqual(list(table.index), [pd.Timestamp("2026-01-01"), pd.Timestamp("2026-01-02")])
        self.assertEqual(float(table.loc[pd.Timestamp("2026-01-01"), "S1"]), 5.0)

    def test_load_station_precip_table_pivots_long_format(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "station_precip_long.csv"
            pd.DataFrame(
                [
                    {"time": "2026-01-01", "station_id": "S1", "precip": 5.0},
                    {"time": "2026-01-01", "station_id": "S2", "precip": 4.0},
                    {"time": "2026-01-02", "station_id": "S1", "precip": 5.2},
                ]
            ).to_csv(path, index=False, encoding="utf-8")

            table, table_format, time_col = load_station_precip_table(path)

        self.assertEqual(table_format, "\u957f\u8868")
        self.assertEqual(time_col, "time")
        self.assertEqual(list(table.columns), ["S1", "S2"])
        self.assertEqual(float(table.loc[pd.Timestamp("2026-01-01"), "S2"]), 4.0)
        self.assertTrue(pd.isna(table.loc[pd.Timestamp("2026-01-02"), "S2"]))

    def test_load_station_metadata_table_normalizes_station_id(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "station_meta.csv"
            pd.DataFrame(
                [
                    {"station_id": " S1 ", "lon": 92.1, "lat": 34.1},
                    {"station_id": "S2", "lon": 92.2, "lat": 34.2},
                ]
            ).to_csv(path, index=False, encoding="utf-8-sig")

            table, columns = load_station_metadata_table(path)

        self.assertEqual(columns, {"id": "station_id", "lon": "lon", "lat": "lat"})
        self.assertEqual(table["_station_id"].tolist(), ["S1", "S2"])

    def test_station_precip_id_match_summary_reports_mismatch_and_coordinate_risk(self) -> None:
        station_series = pd.DataFrame(
            {"S1": [1.0], "S3": [2.0]},
            index=pd.date_range("2026-01-01", periods=1, freq="1D"),
        )
        station_meta = pd.DataFrame({"_station_id": ["S1", "S2"]})

        summary = station_precip_id_match_summary(
            station_series,
            station_meta,
            {"id": "station_id", "lon": "lon", "lat": None},
        )

        self.assertEqual(summary["matched_ids"], ["S1"])
        self.assertEqual(summary["missing_in_precip"], ["S2"])
        self.assertEqual(summary["missing_in_meta"], ["S3"])
        self.assertEqual(summary["station_count"], 2)
        self.assertEqual(summary["precip_station_count"], 2)
        self.assertEqual(summary["missing"], [])
        self.assertEqual(len(summary["warnings"]), 3)
        self.assertIn("\u6ca1\u6709\u5bf9\u5e94\u5217", summary["warnings"][0])
        self.assertIn("\u6ca1\u6709\u5bf9\u5e94\u7ad9\u70b9\u4fe1\u606f", summary["warnings"][1])
        self.assertIn("\u7ecf\u7eac\u5ea6", summary["warnings"][2])

    def test_station_precip_expected_coverage_warns_when_target_window_is_partial(self) -> None:
        matched_series = pd.DataFrame(
            {
                "S1": [1.0, None, 3.0],
                "S2": [None, None, 4.0],
            },
            index=pd.date_range("2026-01-01", periods=3, freq="1D"),
        )
        expected_index = pd.date_range("2026-01-01", periods=4, freq="1D")

        coverage = station_precip_expected_coverage(
            matched_series,
            expected_index,
            mode="grid_plus_station_bias",
            time_basis_label="\u8fde\u7eed\u65f6\u6bb5",
        )

        self.assertEqual(coverage["expected_count"], 4)
        self.assertEqual(coverage["covered_count"], 2)
        self.assertEqual(coverage["coverage_ratio"], 0.5)
        self.assertEqual(coverage["zero_available_steps"], 2)
        self.assertEqual(coverage["max_consecutive_zero_steps"], 1)
        self.assertEqual(coverage["min_available_station_count"], 0)
        self.assertEqual(coverage["mean_available_station_count"], 0.75)
        self.assertEqual(coverage["missing"], [])
        self.assertIn("\u8986\u76d6\u4e0d\u8db3", coverage["warnings"][0])
        self.assertEqual(list(coverage["quality_series"].index), list(expected_index))

    def test_station_precip_expected_coverage_fails_station_only_when_target_window_is_partial(self) -> None:
        matched_series = pd.DataFrame(
            {"S1": [1.0, None]},
            index=pd.date_range("2026-01-01", periods=2, freq="1D"),
        )

        coverage = station_precip_expected_coverage(
            matched_series,
            pd.date_range("2026-01-01", periods=2, freq="1D"),
            mode="thiessen_station_only",
            time_basis_label="\u8fde\u7eed\u65f6\u6bb5",
        )

        self.assertEqual(coverage["warnings"], [])
        self.assertIn("\u8986\u76d6\u4e0d\u8db3", coverage["missing"][0])

    def test_station_precip_event_coverage_summary_warns_for_bias_mode_gaps(self) -> None:
        matched_series = pd.DataFrame(
            {"S1": [1.0, None, 3.0]},
            index=pd.date_range("2026-06-01", periods=3, freq="1D"),
        )
        event_info = {
            "valid_events": [
                {
                    "event_id": "E01",
                    "name": "\u5165\u6c5b\u6d2a\u6c34",
                    "purpose": "calibration",
                    "run_start": pd.Timestamp("2026-06-01"),
                    "run_end": pd.Timestamp("2026-06-03"),
                }
            ]
        }

        summary = station_precip_event_coverage_summary(
            matched_series,
            event_info,
            step_hours=24,
            mode="grid_plus_station_bias",
        )

        self.assertEqual(summary["missing"], [])
        self.assertIn("E01", summary["warnings"][0])
        event = summary["event_coverage"][0]
        self.assertEqual(event["event_id"], "E01")
        self.assertEqual(event["run_start"], "2026-06-01")
        self.assertEqual(event["run_end"], "2026-06-03")
        self.assertEqual(event["expected_steps"], 3)
        self.assertEqual(event["covered_steps"], 2)
        self.assertEqual(event["coverage_ratio"], 2 / 3)
        self.assertEqual(event["zero_available_steps"], 1)
        self.assertEqual(event["max_consecutive_zero_steps"], 1)
        self.assertEqual(event["available_station_min"], 0)
        self.assertEqual(event["available_station_mean"], 2 / 3)
        self.assertEqual(event["status"], "warn")

    def test_station_precip_event_coverage_summary_fails_station_only_gaps(self) -> None:
        matched_series = pd.DataFrame(
            {"S1": [1.0, None]},
            index=pd.date_range("2026-06-01", periods=2, freq="1D"),
        )
        event_info = {
            "valid_events": [
                {
                    "event_id": "E02",
                    "name": "\u65e0\u96e8\u6d2a\u6c34",
                    "purpose": "validation",
                    "run_start": pd.Timestamp("2026-06-01"),
                    "run_end": pd.Timestamp("2026-06-02"),
                }
            ]
        }

        summary = station_precip_event_coverage_summary(
            matched_series,
            event_info,
            step_hours=24,
            mode="thiessen_station_only",
        )

        self.assertEqual(summary["warnings"], [])
        self.assertIn("E02", summary["missing"][0])
        self.assertEqual(summary["event_coverage"][0]["status"], "fail")

    def test_continuous_station_only_summary_fails_when_no_station_steps_exist(self) -> None:
        summary = station_precip_task_context_summary(
            mode="thiessen_station_only",
            context="calibration",
            time_basis="continuous",
            time_basis_label="\u8fde\u7eed\u65f6\u6bb5",
            step_hours=24,
            expected_index=pd.date_range("2026-01-01", periods=3, freq="1D"),
            expected_count=3,
            covered_count=2,
            coverage_ratio=2 / 3,
            zero_available_steps=1,
            max_consecutive_zero_steps=1,
            min_available_station_count=1,
            mean_available_station_count=1.5,
            station_start="2026-01-01",
            station_end="2026-01-03",
        )

        self.assertEqual(summary["status"], "fail")
        self.assertEqual(summary["mode_label"], "\u7eaf\u7ad9\u70b9\u6cf0\u68ee\u5206\u914d")
        self.assertEqual(summary["start"], "2026-01-01")
        self.assertEqual(summary["end"], "2026-01-03")
        self.assertEqual(summary["station_time_range"], {"start": "2026-01-01", "end": "2026-01-03"})
        self.assertEqual(summary["items"][3]["value"], "\u6700\u5c11 1\uff0c\u5e73\u5747 1.5")

    def test_event_window_summary_uses_event_coverage(self) -> None:
        summary = station_precip_task_context_summary(
            mode="thiessen_station_only",
            context="calibration",
            time_basis="event_windows",
            time_basis_label="\u6d2a\u6c34\u4e8b\u4ef6\u7a97\u53e3",
            step_hours=24,
            expected_index=pd.date_range("2026-06-01", periods=5, freq="1D"),
            expected_count=5,
            covered_count=5,
            coverage_ratio=1.0,
            zero_available_steps=0,
            max_consecutive_zero_steps=0,
            min_available_station_count=2,
            mean_available_station_count=2.0,
            event_info={"valid_event_count": 1},
            event_coverage=[{"status": "ok"}],
        )

        self.assertEqual(summary["status"], "ok")
        self.assertEqual(summary["event_count"], 1)
        self.assertEqual(summary["event_ok_count"], 1)
        self.assertIn("1 \u573a\u6d2a\u6c34\u4e8b\u4ef6", summary["headline"])
        self.assertEqual(summary["items"][1]["value"], "1/1 \u573a\u5b8c\u6574")

    def test_forecast_summary_uses_forecast_wording(self) -> None:
        summary = station_precip_task_context_summary(
            mode="grid_plus_station_bias",
            context="forecast",
            time_basis="forecast_window",
            time_basis_label="\u9884\u62a5\u7a97\u53e3",
            step_hours=24,
            expected_index=pd.date_range("2026-08-01", periods=2, freq="1D"),
            expected_count=2,
            covered_count=2,
            coverage_ratio=1.0,
            zero_available_steps=0,
            min_available_station_count=1,
            mean_available_station_count=1.0,
        )

        self.assertEqual(summary["status"], "ok")
        self.assertIn("\u8fde\u7eed\u72b6\u6001\u9884\u62a5\u7a97\u53e3", summary["headline"])
        self.assertEqual(summary["items"][-1]["label"], "\u964d\u6c34\u5904\u7406")


if __name__ == "__main__":
    unittest.main()
