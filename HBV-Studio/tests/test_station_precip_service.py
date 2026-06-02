from __future__ import annotations

import sys
import unittest
from pathlib import Path

import pandas as pd


STUDIO_DIR = Path(__file__).resolve().parents[1]
if str(STUDIO_DIR) not in sys.path:
    sys.path.insert(0, str(STUDIO_DIR))

from services.station_precip import (  # noqa: E402
    format_time_for_check,
    index_display_range,
    max_consecutive_true,
    station_count_text,
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
