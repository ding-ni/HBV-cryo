from __future__ import annotations

import sys
import unittest
from pathlib import Path
from typing import Any


STUDIO_DIR = Path(__file__).resolve().parents[1]
if str(STUDIO_DIR) not in sys.path:
    sys.path.insert(0, str(STUDIO_DIR))

from services.observed import ObservedWindowContext, observed_window_messages  # noqa: E402
from services.time_utils import format_timestamp_for_display  # noqa: E402


class ObservedServiceTests(unittest.TestCase):
    def _context(self, *, profile: str = "daily", time_basis: str = "continuous") -> ObservedWindowContext:
        return ObservedWindowContext(
            current_profile=lambda config: profile,
            normalize_time_step_hours=lambda value: 1.0 if float(value) <= 1.5 else 24.0,
            task_time_basis=lambda config, **kwargs: time_basis,
            format_timestamp_for_display=format_timestamp_for_display,
            profile_labels={"daily": "日尺度", "hourly": "小时尺度"},
            profile_daily="daily",
            profile_hourly="hourly",
            time_basis_event_windows="event_windows",
        )

    def test_observed_window_messages_reports_profile_mismatch_and_low_coverage(self) -> None:
        config = {"时间步长_小时": 24, "时间": {}}
        obs_info: dict[str, Any] = {
            "effective_calibration_mode": "hourly",
            "coverage_ratio": 0.7,
            "start": "2020-01-01",
            "end": "2020-12-31",
        }

        issues, warnings = observed_window_messages(config, obs_info, self._context(profile="daily"))

        self.assertEqual(
            issues,
            [
                "观测径流时间步识别为 小时尺度，与当前率定模式不一致。",
                "观测径流在当前模拟时段内覆盖率只有 70.0%，无法支撑稳定率定。",
            ],
        )
        self.assertEqual(warnings, [])

    def test_observed_window_messages_reports_daily_resampling_and_partial_coverage(self) -> None:
        config = {"时间步长_小时": 24, "时间": {}}
        obs_info: dict[str, Any] = {
            "effective_calibration_mode": "daily",
            "resampled_to_daily": True,
            "daily_aggregation": {"valid_days": 365, "insufficient_days": 3},
            "coverage_ratio": 0.9,
            "start": "2020-01-01",
            "end": "2020-12-31",
        }

        issues, warnings = observed_window_messages(config, obs_info, self._context(profile="daily"))

        self.assertEqual(issues, [])
        self.assertEqual(
            warnings,
            [
                "观测径流已从小时尺度按自然日聚合为日平均流量；有效日数 365 天，小时覆盖不足天数 3 天。",
                "观测径流在当前模拟时段内覆盖率只有 90.0%，目标函数会只在部分时间步上计算。",
            ],
        )

    def test_observed_window_messages_checks_continuous_calibration_and_validation_bounds(self) -> None:
        config = {
            "时间步长_小时": 24,
            "时间": {
                "率定开始": "2019-12-31",
                "率定结束": "2020-01-10",
                "验证开始": "2020-12-25",
                "验证结束": "2021-01-02",
            },
        }
        obs_info: dict[str, Any] = {"start": "2020-01-01", "end": "2020-12-31"}

        issues, warnings = observed_window_messages(config, obs_info, self._context(profile="daily"))

        self.assertEqual(
            issues,
            [
                "率定期开始时间早于观测覆盖起点：2019-12-31 < 2020-01-01",
                "验证期结束时间晚于观测覆盖终点：2021-01-02 > 2020-12-31",
            ],
        )
        self.assertEqual(
            warnings,
            [
                "率定期长度只有 11 天，正式率定通常建议至少半年以上。",
                "验证期长度只有 9 天，正式率定通常建议至少半年以上。",
            ],
        )

    def test_observed_window_messages_skips_continuous_bounds_for_event_windows(self) -> None:
        config = {
            "时间步长_小时": 24,
            "时间": {"率定开始": "2019-12-31", "率定结束": "2020-01-02"},
        }
        obs_info: dict[str, Any] = {"coverage_ratio": 0.96, "start": "2020-01-01", "end": "2020-12-31"}

        issues, warnings = observed_window_messages(
            config,
            obs_info,
            self._context(profile="daily", time_basis="event_windows"),
        )

        self.assertEqual(issues, [])
        self.assertEqual(warnings, [])

    def test_observed_window_messages_warns_hourly_short_period(self) -> None:
        config = {
            "时间步长_小时": 1,
            "时间": {"率定开始": "2020-01-02 00:00", "率定结束": "2020-01-03 00:00"},
        }
        obs_info: dict[str, Any] = {
            "effective_calibration_mode": "hourly",
            "start": "2020-01-01 00:00",
            "end": "2020-01-31 23:00",
        }

        issues, warnings = observed_window_messages(config, obs_info, self._context(profile="hourly"))

        self.assertEqual(issues, [])
        self.assertEqual(warnings, ["率定期长度只有 25 小时，小时尺度正式率定通常建议至少 30 天以上。"])


if __name__ == "__main__":
    unittest.main()
