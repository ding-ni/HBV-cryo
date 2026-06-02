from __future__ import annotations

import sys
import unittest
from pathlib import Path

import pandas as pd


STUDIO_DIR = Path(__file__).resolve().parents[1]
if str(STUDIO_DIR) not in sys.path:
    sys.path.insert(0, str(STUDIO_DIR))

from services.time_utils import (  # noqa: E402
    detect_series_step_hours,
    expected_warmup_end,
    format_timestamp_for_display,
    is_date_only_string,
    normalize_time_step_hours,
    parse_time_from_name,
    time_sequence_messages,
)


class TimeUtilsServiceTests(unittest.TestCase):
    def test_normalize_time_step_hours_preserves_existing_hourly_daily_rule(self) -> None:
        self.assertEqual(normalize_time_step_hours(1), 1.0)
        self.assertEqual(normalize_time_step_hours("1.5"), 1.0)
        self.assertEqual(normalize_time_step_hours(24), 24.0)
        self.assertEqual(normalize_time_step_hours("bad-value"), 24.0)
        self.assertEqual(normalize_time_step_hours(None), 24.0)

    def test_is_date_only_string_uses_existing_shape_rule(self) -> None:
        self.assertTrue(is_date_only_string("2026-01-02"))
        self.assertTrue(is_date_only_string(" 2026.01.02 "))
        self.assertFalse(is_date_only_string("2026-01-02 00:00"))
        self.assertFalse(is_date_only_string("2026-01-02T00:00"))
        self.assertFalse(is_date_only_string(""))
        self.assertFalse(is_date_only_string(pd.Timestamp("2026-01-02")))

    def test_format_timestamp_for_display_uses_date_label_for_daily_midnight(self) -> None:
        self.assertEqual(
            format_timestamp_for_display(pd.Timestamp("2026-01-02 00:00"), 24),
            "2026-01-02",
        )
        self.assertEqual(
            format_timestamp_for_display(pd.Timestamp("2026-01-02 00:00"), "bad-value"),
            "2026-01-02",
        )

    def test_format_timestamp_for_display_keeps_time_for_hourly_or_non_midnight(self) -> None:
        self.assertEqual(
            format_timestamp_for_display(pd.Timestamp("2026-01-02 00:00"), 1),
            "2026-01-02 00:00",
        )
        self.assertEqual(
            format_timestamp_for_display(pd.Timestamp("2026-01-02 12:30"), 24),
            "2026-01-02 12:30",
        )

    def test_detect_series_step_hours_uses_median_unique_delta(self) -> None:
        hourly = pd.Series(pd.to_datetime(["2026-01-01 01:00", "2026-01-01 00:00", "2026-01-01 01:00"]))
        daily = pd.Series(pd.to_datetime(["2026-01-01", "2026-01-02", "2026-01-03"]))

        self.assertEqual(detect_series_step_hours(hourly), 1.0)
        self.assertEqual(detect_series_step_hours(daily), 24.0)
        self.assertIsNone(detect_series_step_hours(pd.Series(pd.to_datetime(["2026-01-01"]))))

    def test_parse_time_from_name_supports_existing_tif_filename_shapes(self) -> None:
        self.assertEqual(
            parse_time_from_name("prec_2026.01.02.03.30.tif"),
            pd.Timestamp("2026-01-02 03:30"),
        )
        self.assertEqual(
            parse_time_from_name("temp_2026-01-02T03:00.tif"),
            pd.Timestamp("2026-01-02 03:00"),
        )
        self.assertEqual(parse_time_from_name("2026-01-02.tif"), pd.Timestamp("2026-01-02"))
        self.assertIsNone(parse_time_from_name("no_timestamp_here.tif"))

    def test_expected_warmup_end_uses_normalized_time_step(self) -> None:
        time_values = {"率定开始": pd.Timestamp("2026-01-02 00:00")}

        self.assertEqual(expected_warmup_end(time_values, 24), pd.Timestamp("2026-01-01 00:00"))
        self.assertEqual(expected_warmup_end(time_values, 1), pd.Timestamp("2026-01-01 23:00"))
        self.assertIsNone(expected_warmup_end({}, 24))

    def test_time_sequence_messages_preserves_warmup_and_order_checks(self) -> None:
        valid = {
            "预热开始": pd.Timestamp("2026-01-01"),
            "预热结束": pd.Timestamp("2026-01-02"),
            "率定开始": pd.Timestamp("2026-01-03"),
            "率定结束": pd.Timestamp("2026-01-04"),
            "验证开始": pd.Timestamp("2026-01-05"),
            "验证结束": pd.Timestamp("2026-01-06"),
        }
        bad_order = dict(valid, 率定结束=pd.Timestamp("2026-01-02"))
        bad_warmup = dict(valid, 预热结束=pd.Timestamp("2026-01-01"))

        self.assertEqual(time_sequence_messages(valid, 24), [])
        self.assertIn("时间顺序错误：率定开始 晚于 率定结束", time_sequence_messages(bad_order, 24))
        self.assertEqual(
            time_sequence_messages(bad_warmup, 24),
            ["时间.预热结束 必须紧邻率定开始，当前应为 2026-01-02"],
        )


if __name__ == "__main__":
    unittest.main()
