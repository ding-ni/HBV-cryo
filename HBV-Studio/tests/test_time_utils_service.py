from __future__ import annotations

import sys
import unittest
from pathlib import Path

import pandas as pd


STUDIO_DIR = Path(__file__).resolve().parents[1]
if str(STUDIO_DIR) not in sys.path:
    sys.path.insert(0, str(STUDIO_DIR))

from services.time_utils import (  # noqa: E402
    format_timestamp_for_display,
    is_date_only_string,
    normalize_time_step_hours,
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


if __name__ == "__main__":
    unittest.main()
