from __future__ import annotations

import ast
import sys
import unittest
from pathlib import Path
from unittest import mock

import numpy as np
import pandas as pd


STUDIO_DIR = Path(__file__).resolve().parents[1]
if str(STUDIO_DIR) not in sys.path:
    sys.path.insert(0, str(STUDIO_DIR))
import profile_runner as runner  # noqa: E402


CORE_PATH = Path(__file__).resolve().parents[2] / "HBV-Cryo" / "率定核心.py"
CORE_TREE = ast.parse(CORE_PATH.read_text(encoding="utf-8-sig"))
DETECTOR = next(
    node for node in CORE_TREE.body
    if isinstance(node, ast.FunctionDef) and node.name == "detect_obs_eval_mask"
)
DETECTOR_CODE = compile(
    ast.Module(body=[DETECTOR], type_ignores=[]), str(CORE_PATH), "exec",
)


def detect(dates, observations, calibration, validation, *, hours=24.0, mode="full_year"):
    namespace = {
        "np": np,
        "pd": pd,
        "SIM_DATES": dates,
        "Q_OBS_FULL": observations,
        "CALIB_MASK": calibration,
        "VALID_MASK": validation,
        "OBS_MODE_OVERRIDE": mode,
        "TIME_STEP_HOURS": hours,
        "time_step_timedelta": lambda: pd.Timedelta(hours=hours),
    }
    exec(DETECTOR_CODE, namespace)
    return namespace["detect_obs_eval_mask"]()


def period(dates, start, end):
    return np.asarray((dates >= start) & (dates <= end))


class ObservedMaskValidationIsolationTests(unittest.TestCase):
    def test_validation_nan_cannot_exclude_calibration_samples_in_shared_year(self):
        dates = pd.date_range("2020-01-01", "2023-12-31", freq="D")
        calibration = period(dates, "2021-04-01", "2022-09-10")
        validation = period(dates, "2022-09-11", "2023-12-31")
        observations = np.full(len(dates), 20.0)
        observations[dates.year == 2020] = np.nan
        before, before_mode = detect(dates, observations, calibration, validation)
        changed = observations.copy()
        changed[period(dates, "2022-09-11", "2022-09-30")] = np.nan
        after, after_mode = detect(dates, changed, calibration, validation)

        np.testing.assert_array_equal(observations[calibration], changed[calibration])
        np.testing.assert_array_equal(before[calibration], after[calibration])
        self.assertEqual(int(np.sum(before & calibration)), 528)
        self.assertEqual(int(np.sum(after & calibration)), 528)
        self.assertEqual(before_mode, "full_year_with_period_fallback")
        self.assertEqual(after_mode, before_mode)

    def test_validation_fallback_cannot_restore_an_incomplete_calibration_year(self):
        dates = pd.date_range("2020-01-01", "2023-12-31", freq="D")
        calibration = np.asarray(np.isin(dates.year, [2021, 2022]))
        validation = np.asarray(dates.year == 2023)
        observations = np.full(len(dates), 20.0)
        observations[dates == "2021-07-01"] = np.nan
        before, before_mode = detect(dates, observations, calibration, validation)
        changed = observations.copy()
        changed[validation] = np.nan
        after, after_mode = detect(dates, changed, calibration, validation)

        np.testing.assert_array_equal(before[calibration], after[calibration])
        self.assertEqual(int(np.sum(after & calibration)), 365)
        self.assertFalse(np.any(after[dates.year == 2021]))
        self.assertEqual(before_mode, "full_year")
        self.assertEqual(after_mode, "full_year_with_period_fallback")

    def test_validation_fallback_cannot_change_complete_calibration_year_selection(self):
        dates = pd.date_range("2020-01-01", "2023-12-31", freq="D")
        calibration = period(dates, "2021-01-01", "2022-09-10")
        validation = period(dates, "2022-09-11", "2023-12-31")
        observations = np.full(len(dates), 20.0)
        before, _ = detect(dates, observations, calibration, validation)
        changed = observations.copy()
        changed[validation] = np.nan
        after, mode = detect(dates, changed, calibration, validation)

        np.testing.assert_array_equal(before[calibration], after[calibration])
        self.assertEqual(int(np.sum(after & calibration)), 365)
        self.assertEqual(int(np.sum(after & validation)), int(np.sum(validation)))
        self.assertEqual(mode, "full_year_with_period_fallback")

    def test_complete_multiyear_data_keeps_complete_calendar_years(self):
        dates = pd.date_range("2020-07-01", "2024-03-31", freq="D")
        calibration = np.asarray(np.isin(dates.year, [2021, 2022]))
        validation = np.asarray(dates.year == 2023)
        observations = np.full(len(dates), 20.0)
        mask, mode = detect(dates, observations, calibration, validation)

        np.testing.assert_array_equal(mask, np.isin(dates.year, [2021, 2022, 2023]))
        self.assertEqual(int(np.sum(mask & calibration)), 730)
        self.assertEqual(int(np.sum(mask & validation)), 365)
        self.assertEqual(mode, "full_year")

    def test_partial_scoring_years_are_not_reported_as_complete_years(self):
        dates = pd.date_range("2020-01-01", "2023-12-31", freq="D")
        calibration = period(dates, "2020-06-01", "2022-09-10")
        validation = period(dates, "2022-09-11", "2023-12-31")
        mask, mode = detect(dates, np.full(len(dates), 20.0), calibration, validation)

        np.testing.assert_array_equal(mask & calibration, dates.year == 2021)
        np.testing.assert_array_equal(mask & validation, dates.year == 2023)
        self.assertEqual(mode, "full_year")

    def test_calibration_gaps_do_not_change_validation_year_selection(self):
        dates = pd.date_range("2020-01-01", "2023-12-31", freq="D")
        calibration = np.asarray(np.isin(dates.year, [2021, 2022]))
        validation = np.asarray(dates.year == 2023)
        observations = np.full(len(dates), 20.0)
        before, _ = detect(dates, observations, calibration, validation)
        changed = observations.copy()
        changed[dates == "2021-05-17"] = np.nan
        after, mode = detect(dates, changed, calibration, validation)

        np.testing.assert_array_equal(before[validation], after[validation])
        self.assertEqual(int(np.sum(after & calibration)), 365)
        self.assertEqual(mode, "full_year")

    def test_current_long_warmup_seasonal_workspace_retains_all_steps(self):
        dates = pd.date_range("2022-01-01", "2025-10-31", freq="D")
        calibration = period(dates, "2025-06-01", "2025-09-10")
        validation = period(dates, "2025-09-11", "2025-10-31")
        observations = np.full(len(dates), np.nan)
        observations[period(dates, "2025-05-01", "2025-10-31")] = 20.0
        original = observations.copy()
        before, mode = detect(dates, observations, calibration, validation)
        changed = observations.copy()
        changed[validation] = np.nan
        after, changed_mode = detect(dates, changed, calibration, validation)

        np.testing.assert_array_equal(observations, original)
        np.testing.assert_array_equal(before, np.ones(1400, dtype=bool))
        np.testing.assert_array_equal(after, before)
        self.assertEqual(int(np.sum(before & calibration)), 102)
        self.assertEqual(int(np.sum(before & validation)), 51)
        self.assertEqual(mode, "all_valid")
        self.assertEqual(changed_mode, mode)

    def test_seasonal_observations_fallback_without_filling_winter_gaps(self):
        dates = pd.date_range("2020-01-01", "2023-12-31", freq="D")
        calibration = np.asarray(np.isin(dates.year, [2021, 2022]))
        validation = np.asarray(dates.year == 2023)
        observations = np.where((dates.month >= 5) & (dates.month <= 10), 20.0, np.nan)
        original_missing = ~np.isfinite(observations)
        mask, mode = detect(dates, observations, calibration, validation)

        self.assertTrue(np.all(mask))
        np.testing.assert_array_equal(~np.isfinite(observations), original_missing)
        self.assertFalse(np.any(np.isfinite(observations[dates.month == 1])))
        self.assertEqual(mode, "all_valid")

    def test_hourly_leap_year_and_validation_fallback_are_isolated(self):
        dates = pd.date_range("2019-01-01", "2022-12-31 23:00", freq="h")
        calibration = period(dates, "2020-01-01", "2021-09-10 23:00")
        validation = period(dates, "2021-09-11", "2022-12-31 23:00")
        observations = np.full(len(dates), 20.0)
        before, before_mode = detect(dates, observations, calibration, validation, hours=1.0)
        changed = observations.copy()
        changed[dates == "2022-06-01 08:00"] = np.nan
        after, after_mode = detect(dates, changed, calibration, validation, hours=1.0)

        np.testing.assert_array_equal(before[calibration], after[calibration])
        np.testing.assert_array_equal(after & calibration, dates.year == 2020)
        self.assertEqual(int(np.sum(after & calibration)), 366 * 24)
        self.assertEqual(before_mode, "full_year")
        self.assertEqual(after_mode, "full_year_with_period_fallback")

    def test_hourly_seasonal_windows_retain_short_window_fallback(self):
        dates = pd.date_range("2022-01-01", "2025-10-31 23:00", freq="h")
        calibration = period(dates, "2025-06-01", "2025-09-10 23:00")
        validation = period(dates, "2025-09-11", "2025-10-31 23:00")
        observations = np.full(len(dates), np.nan)
        observations[period(dates, "2025-05-01", "2025-10-31 23:00")] = 20.0
        mask, mode = detect(dates, observations, calibration, validation, hours=1.0)

        self.assertTrue(np.all(mask))
        self.assertEqual(int(np.sum(mask & calibration)), 102 * 24)
        self.assertEqual(int(np.sum(mask & validation)), 51 * 24)
        self.assertEqual(mode, "all_valid")

    def test_legacy_overlap_cannot_let_validation_fallback_restore_calibration_samples(self):
        dates = pd.date_range("2020-01-01", "2023-12-31", freq="D")
        calibration = np.asarray(np.isin(dates.year, [2021, 2022]))
        validation = np.asarray(dates.year == 2021)
        observations = np.full(len(dates), 20.0)
        observations[dates == "2021-07-01"] = np.nan
        mask, mode = detect(dates, observations, calibration, validation)

        self.assertFalse(np.any(mask & validation))
        self.assertEqual(int(np.sum(mask & calibration)), 365)
        self.assertEqual(mode, "full_year_with_period_fallback")

    def test_no_scoring_periods_preserve_complete_observed_year_filter(self):
        dates = pd.date_range("2020-09-01", "2023-03-31", freq="D")
        observations = np.full(len(dates), 20.0)
        observations[dates == "2022-06-01"] = np.nan
        mask, mode = detect(dates, observations, None, None)

        np.testing.assert_array_equal(mask, dates.year == 2021)
        self.assertEqual(mode, "full_year")

    def test_explicit_modes_and_empty_input_preserve_existing_behavior(self):
        dates = pd.date_range("2025-05-01", "2025-10-31", freq="D")
        observations = np.full(len(dates), np.nan)
        for mode in ("all", "all_valid", "full_period", "available_only", "legacy_mode"):
            with self.subTest(mode=mode):
                mask, applied = detect(dates, observations, None, None, mode=mode)
                self.assertTrue(np.all(mask))
                self.assertEqual(applied, mode)
        for dates in (None, pd.DatetimeIndex([])):
            with self.subTest(dates=dates):
                mask, mode = detect(dates, None, None, None)
                self.assertEqual(mask.shape, (0,))
                self.assertEqual(mode, "full_year")


class ObservedMaskPreflightConsistencyTests(unittest.TestCase):
    def preflight(self, dates, observations, calibration, validation, *, hours=24.0, boundary=None):
        frequency = pd.Timedelta(hours=hours)
        calibration_dates = dates[calibration]
        validation_dates = dates[validation]

        def label(value):
            return value.strftime("%Y-%m-%d" if hours == 24.0 else "%Y-%m-%d %H:%M")

        config = {
            "_config_path": str(STUDIO_DIR / "tests" / "observation-mask-workspace.json"),
            "项目对象": runner.OBJECT_INTERBASIN,
            "率定模式": "daily" if hours == 24.0 else "hourly",
            "时间步长_小时": hours,
            "任务时段模式": "continuous",
            "观测口径模式": "full_year",
            "观测径流_csv": "outlet.csv",
            "边界条件": {
                "上游边界入流_csv": "boundary.csv",
                "时间字段": "date",
                "流量字段": "flow",
                "缺失填补": "preserve_missing",
            },
            "时间": {
                "预热开始": label(dates[0]),
                "预热结束": label(calibration_dates[0] - frequency),
                "率定开始": label(calibration_dates[0]),
                "率定结束": label(calibration_dates[-1]),
                "验证开始": label(validation_dates[0]),
                "验证结束": label(validation_dates[-1]),
            },
        }
        values = np.full(len(dates), 10.0) if boundary is None else boundary
        with (
            mock.patch.object(runner, "inspect_boundary_inflow_csv", return_value={}),
            mock.patch.object(runner, "read_boundary_inflow_series", return_value=(values, True)),
            mock.patch.object(runner, "inspect_observed_discharge", return_value={"series": pd.Series(observations, index=dates)}),
        ):
            summary = runner.continuous_boundary_evaluation_summary(config)
        core_mask, _ = detect(dates, observations, calibration, validation, hours=hours)
        np.testing.assert_array_equal(summary["simulation_index"], dates)
        np.testing.assert_array_equal(
            summary["paired_evaluation_mask"],
            core_mask & summary["boundary_evaluable_mask"] & np.isfinite(observations),
        )
        return summary

    def test_daily_preflight_and_core_match_after_role_specific_fallback(self):
        dates = pd.date_range("2020-01-01", "2023-12-31", freq="D")
        for calibration_end in ("2022-09-10", "2022-12-31"):
            calibration = period(dates, "2021-01-01", calibration_end)
            validation = period(dates, str((dates[calibration][-1] + pd.Timedelta(days=1)).date()), "2023-12-31")
            observations = np.full(len(dates), 20.0)
            observations[dates == "2021-07-01"] = np.nan
            before = self.preflight(dates, observations, calibration, validation)
            changed = observations.copy()
            changed[validation] = np.nan
            after = self.preflight(dates, changed, calibration, validation)
            with self.subTest(calibration_end=calibration_end):
                self.assertEqual(before["periods"]["calibration"], after["periods"]["calibration"])

    def test_hourly_preflight_and_core_match_with_leap_year_and_missing_validation_hour(self):
        dates = pd.date_range("2019-01-01", "2022-12-31 23:00", freq="h")
        calibration = period(dates, "2020-01-01", "2021-09-10 23:00")
        validation = period(dates, "2021-09-11", "2022-12-31 23:00")
        observations = np.full(len(dates), 20.0)
        before = self.preflight(dates, observations, calibration, validation, hours=1.0)
        changed = observations.copy()
        changed[dates == "2022-06-01 08:00"] = np.nan
        after = self.preflight(dates, changed, calibration, validation, hours=1.0)

        self.assertEqual(before["periods"]["calibration"], after["periods"]["calibration"])
        self.assertEqual(after["periods"]["calibration"]["paired_steps"], 366 * 24)

    def test_current_workspace_preflight_still_uses_102_and_50_actual_pairs(self):
        dates = pd.date_range("2022-01-01", "2025-10-31", freq="D")
        calibration = period(dates, "2025-06-01", "2025-09-10")
        validation = period(dates, "2025-09-11", "2025-10-31")
        observations = np.full(len(dates), np.nan)
        observations[period(dates, "2025-05-01", "2025-10-31")] = 20.0
        boundary = np.full(len(dates), np.nan)
        boundary[period(dates, "2025-05-01", "2025-10-30")] = 10.0
        summary = self.preflight(dates, observations, calibration, validation, boundary=boundary)

        self.assertEqual(summary["errors"], [])
        self.assertEqual(summary["periods"]["calibration"]["paired_steps"], 102)
        self.assertEqual(summary["periods"]["validation"]["paired_steps"], 50)
        self.assertEqual(summary["periods"]["validation"]["excluded_sample"], ["2025-10-31"])


if __name__ == "__main__":
    unittest.main()
