from __future__ import annotations

import ast
import math
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest import mock

import numpy as np
import pandas as pd


STUDIO_DIR = Path(__file__).resolve().parents[1]
if str(STUDIO_DIR) not in sys.path:
    sys.path.insert(0, str(STUDIO_DIR))

import profile_runner as runner  # noqa: E402


class PreservedBoundaryInputContractTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.index = pd.date_range("2025-01-01", "2025-02-28", freq="D")
        self.config = {
            "_config_path": str(self.root / "workspace.json"),
            "项目对象": runner.OBJECT_INTERBASIN,
            "率定模式": "daily",
            "时间步长_小时": 24.0,
            "任务时段模式": "continuous",
            "观测口径模式": "full_year",
            "观测径流_csv": str(self.root / "outlet.csv"),
            "边界条件": {
                "上游边界入流_csv": str(self.root / "boundary.csv"),
                "时间字段": "date",
                "流量字段": "flow",
                "缺失填补": "preserve_missing",
            },
            "时间": {
                "预热开始": "2025-01-01",
                "预热结束": "2025-01-15",
                "率定开始": "2025-01-16",
                "率定结束": "2025-02-15",
                "验证开始": "2025-02-16",
                "验证结束": "2025-02-28",
            },
        }
        self._write_boundary(self.index)
        self._write_observed(self.index)

    def _write_boundary(self, dates: pd.DatetimeIndex, values: np.ndarray | None = None) -> None:
        pd.DataFrame({"date": dates, "flow": values if values is not None else np.arange(len(dates)) + 20.0}).to_csv(
            self.root / "boundary.csv", index=False,
        )

    def _write_observed(self, dates: pd.DatetimeIndex) -> None:
        pd.DataFrame({"date": dates, "flow": np.arange(len(dates)) + 40.0}).to_csv(
            self.root / "outlet.csv", index=False,
        )

    @staticmethod
    def _core_boundary_mask(index: pd.DatetimeIndex, values: np.ndarray, warmup_days: float, step_hours: float) -> tuple[np.ndarray, np.ndarray]:
        source = STUDIO_DIR.parent / "HBV-Cryo" / "率定核心.py"
        selected = {
            "_finite_contiguous_slices", "boundary_routing_warmup_steps",
            "route_boundary_inflow_with_warmup", "_event_time_text",
        }
        tree = ast.parse(source.read_text(encoding="utf-8-sig"))
        functions = [node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name in selected]
        namespace = {
            "np": np, "pd": pd, "ceil": math.ceil, "EPS": 1e-10,
            "TIME_STEP_HOURS": step_hours, "BOUNDARY_ROUTING_WARMUP_DAYS": warmup_days,
            "SIM_DATES": index, "MUSK_DT": step_hours, "BOUNDARY_INFLOW_ENABLED": True,
            "muskingum_route": lambda flow, *_args: flow.copy(),
            "trim_warmup": lambda array: array,
        }
        exec(compile(ast.Module(body=functions, type_ignores=[]), str(source), "exec"), namespace)
        routed, mask, _ = namespace["route_boundary_inflow_with_warmup"](values, 1.0, 0.1)
        return routed, mask

    def test_long_meteorological_warmup_and_incomplete_last_hour_are_allowed_without_changing_dates(self) -> None:
        self.config["时间"] = {
            "预热开始": "2022-01-01", "预热结束": "2025-05-31",
            "率定开始": "2025-06-01", "率定结束": "2025-09-10",
            "验证开始": "2025-09-11", "验证结束": "2025-10-31",
        }
        hours = pd.date_range("2025-05-01 08:00", "2025-10-31 08:00", freq="h")
        self._write_boundary(hours)
        self._write_observed(hours)

        summary = runner.continuous_boundary_evaluation_summary(self.config)
        self.assertEqual(summary["errors"], [])
        self.assertEqual(runner.required_boundary_coverage_error(self.config, "daily"), "")
        self.assertEqual(summary["periods"]["calibration"]["paired_steps"], 102)
        self.assertEqual(summary["periods"]["validation"]["expected_steps"], 51)
        self.assertEqual(summary["periods"]["validation"]["paired_steps"], 50)
        self.assertEqual(summary["periods"]["validation"]["excluded_sample"], ["2025-10-31"])
        self.assertEqual(self.config["时间"]["验证结束"], "2025-10-31")
        index = summary["simulation_index"]
        self.assertFalse(summary["boundary_valid_mask"][index < "2025-05-01"].any())
        self.assertFalse(summary["boundary_evaluable_mask"][index < "2025-05-15"].any())
        self.assertTrue(summary["boundary_evaluable_mask"][index == "2025-05-15"].all())

    def test_missing_day_restarts_warmup_and_gate_matches_core_mask(self) -> None:
        dates = self.index[self.index != pd.Timestamp("2025-01-29")]
        self._write_boundary(dates)

        summary = runner.continuous_boundary_evaluation_summary(self.config)
        index = summary["simulation_index"]
        values, _ = runner.read_boundary_inflow_series(
            self.root / "boundary.csv", index, date_field="date", flow_field="flow",
            gap_fill="preserve_missing", expected_step_hours=24.0,
        )
        routed, core_mask = self._core_boundary_mask(index, values, 14.0, 24.0)
        np.testing.assert_array_equal(summary["boundary_evaluable_mask"], core_mask)
        self.assertTrue(np.isnan(routed[index == "2025-01-29"]).all())
        self.assertFalse(core_mask[(index >= "2025-01-30") & (index <= "2025-02-12")].any())
        self.assertTrue(core_mask[index == "2025-02-13"].all())
        self.assertIn("低于 75%", runner.required_boundary_coverage_error(self.config, "daily"))

    def test_calibration_and_validation_are_checked_separately(self) -> None:
        self._write_boundary(self.index[self.index < pd.Timestamp("2025-02-16")])
        error = runner.required_boundary_coverage_error(self.config, "daily")
        self.assertIn("验证期", error)
        self.assertIn("0/13", error)
        self.assertNotIn("率定期完成", error)

    def test_outlet_observation_gaps_also_reduce_paired_coverage(self) -> None:
        dates = self.index[(self.index < "2025-02-16") | (self.index >= "2025-02-25")]
        self._write_observed(dates)
        error = runner.required_boundary_coverage_error(self.config, "daily")
        self.assertIn("验证期", error)
        self.assertIn("4/13", error)

    def test_insufficient_validation_samples_do_not_pass_with_full_boundary(self) -> None:
        self.config["时间"]["验证开始"] = "2025-02-28"
        error = runner.required_boundary_coverage_error(self.config, "daily")
        self.assertIn("至少需要 2 个", error)

    def test_zero_and_interpolation_cannot_invent_missing_formal_boundary(self) -> None:
        self._write_boundary(self.index[:-1])
        for gap_policy in ("zero", "interpolate", ""):
            with self.subTest(gap_policy=gap_policy):
                self.config["边界条件"]["缺失填补"] = gap_policy
                error = runner.required_boundary_coverage_error(self.config, "daily")
                self.assertIn("禁止零填补或插值", error)
                self.assertIn("2025-02-28", error)

    def test_duplicate_boundary_times_are_still_a_hard_error(self) -> None:
        self._write_boundary(self.index.append(pd.DatetimeIndex([self.index[10]])))
        self.assertIn("重复时间戳", runner.required_boundary_coverage_error(self.config, "daily"))

    def test_negative_boundary_flow_is_still_a_hard_error(self) -> None:
        values = np.full(len(self.index), 20.0)
        values[20] = -1.0
        self._write_boundary(self.index, values)
        self.assertIn("负流量", runner.required_boundary_coverage_error(self.config, "daily"))

    def test_no_actual_boundary_overlap_remains_blocked(self) -> None:
        self._write_boundary(pd.date_range("2020-01-01", "2020-02-01", freq="D"))
        self.assertIn("没有与当前模拟时段重叠", runner.required_boundary_coverage_error(self.config, "daily"))

    def test_actual_zero_boundary_values_are_valid_observations(self) -> None:
        self._write_boundary(self.index, np.zeros(len(self.index)))
        summary = runner.continuous_boundary_evaluation_summary(self.config)
        self.assertEqual(summary["errors"], [])
        self.assertEqual(summary["periods"]["calibration"]["paired_steps"], 31)
        self.assertEqual(summary["periods"]["validation"]["paired_steps"], 13)

    def test_hourly_recovery_uses_ceiling_of_routing_warmup_steps(self) -> None:
        self.config["率定模式"] = "hourly"
        self.config["时间步长_小时"] = 1.0
        self.config["洪水事件率定"] = {"边界汇流预热天数": 0.51}
        self.config["时间"] = {
            "预热开始": "2025-01-01 00:00", "预热结束": "2025-01-01 23:00",
            "率定开始": "2025-01-02 00:00", "率定结束": "2025-01-03",
            "验证开始": "2025-01-04 00:00", "验证结束": "2025-01-05",
        }
        hours = pd.date_range("2025-01-01", "2025-01-05 23:00", freq="h")
        self._write_boundary(hours[hours != pd.Timestamp("2025-01-03 22:00")])
        self._write_observed(hours)
        summary = runner.continuous_boundary_evaluation_summary(self.config)
        values, _ = runner.read_boundary_inflow_series(
            self.root / "boundary.csv", hours, date_field="date", flow_field="flow",
            gap_fill="preserve_missing", expected_step_hours=1.0,
        )
        _, core_mask = self._core_boundary_mask(hours, values, 0.51, 1.0)
        self.assertEqual(summary["routing_warmup_steps"], 13)
        self.assertEqual(summary["periods"]["validation"]["expected_steps"], 48)
        np.testing.assert_array_equal(summary["boundary_evaluable_mask"], core_mask)


class DailyObjectiveRunnerContractTests(unittest.TestCase):
    def test_formal_precip_check_receives_current_configuration_and_base_inputs(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            corrected = root / "corrected"
            corrected.mkdir()
            (corrected / "precipitation_strategy_summary.json").write_text("{}", encoding="utf-8")
            (corrected / "2025-01-01.tif").write_bytes(b"fixture")
            config = {"气象策略": {"降水方案": "grid_plus_station_bias", "station_correction_algorithm": "monthly_transfer_v3"}}
            paths = {"aligned_prec_effective_dir": corrected, "aligned_prec_effective_base_dir": root / "base"}
            with mock.patch.object(runner, "build_profile_paths", return_value=paths), \
                 mock.patch.object(runner, "daily_forcing_manifest_error", return_value=""), \
                 mock.patch.object(runner, "required_boundary_coverage_error", return_value=""), \
                 mock.patch("services.precip_strategy_status.versioned_precip_summary_error", return_value="") as check:
                runner.validate_profile_input_contracts(config, "daily")
            self.assertIs(check.call_args.kwargs["config"], config)
            self.assertEqual(check.call_args.kwargs["base_dir"], root / "base")

    def test_daily_metadata_matches_calibration_only_core(self) -> None:
        daily = runner.build_weighted_multi_objective_meta("daily")
        self.assertEqual(daily["objective_scoring_policy"], "calibration_only_v1")
        self.assertEqual(daily["optimization_period"], "calibration_period")
        self.assertTrue(daily["validation_diagnostic_only"])
        for key in ("nse_validation", "log_nse_validation", "pbias_validation"):
            self.assertEqual(daily["weights"]["flow"][key], 0.0)
        for key in ("nse_validation_weight", "kge_validation_weight", "pbias_validation_weight"):
            self.assertEqual(daily["weights"]["flow_guard"][key], 0.0)
        self.assertTrue(daily["diagnostic_only_constraints"]["validation_flow_metrics"])
        source = STUDIO_DIR.parent / "HBV-Cryo" / "率定核心.py"
        tree = ast.parse(source.read_text(encoding="utf-8-sig"))
        function = next(node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == "build_daily_unified_objective_meta")
        namespace = {
            "daily_unified_objective": types.SimpleNamespace(OBJECTIVE_SCORING_POLICY="calibration_only_v1"),
            "OBJECTIVE_FAMILY_DAILY": runner.OBJECTIVE_MODE_MULTI,
            "INTERVAL_OBJECTIVE_GUARD_ENABLED": False,
        }
        exec(compile(ast.Module(body=[function], type_ignores=[]), str(source), "exec"), namespace)
        core = namespace["build_daily_unified_objective_meta"]("daily")
        self.assertEqual(daily["weights"], core["weights"])
        self.assertEqual(daily["notes"], core["notes"])

    def test_hourly_legacy_metadata_is_unchanged(self) -> None:
        hourly = runner.build_weighted_multi_objective_meta("hourly")
        self.assertNotIn("objective_scoring_policy", hourly)
        self.assertEqual(hourly["weights"]["flow"]["nse_validation"], 0.35)
        self.assertEqual(hourly["weights"]["flow"]["pbias_validation"], 0.10)

    def test_broken_daily_core_cannot_fall_back_to_legacy_validation_objective(self) -> None:
        module = types.SimpleNamespace(
            np=np, BAD_OBJ=1e9,
            compute_metrics=lambda _q: {"nse_cal": 0.9, "nse_val": 0.9},
            eval_count=0,
            muskingum_is_valid=lambda *_args: True,
            run_simulation=lambda *_args, **_kwargs: {"q_total": np.ones(20)},
        )
        objective, _, _, _ = runner.build_weighted_multi_objective(module, "daily")
        parameters = np.ones(18)
        parameters[10:13] = [0.3, 0.2, 0.1]
        self.assertEqual(objective(parameters), module.BAD_OBJ)
        module.compute_objective_terms = lambda _metrics, _sim: (_ for _ in ()).throw(ValueError("broken core"))
        self.assertEqual(objective(parameters), module.BAD_OBJ)
        module.compute_objective_terms = lambda _metrics, _sim: (0.25, {"nse_cal": 0.9})
        self.assertEqual(objective(parameters), 0.25)


if __name__ == "__main__":
    unittest.main()
