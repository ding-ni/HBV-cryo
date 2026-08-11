from __future__ import annotations

import importlib.util
import json
import tempfile
import unittest
from pathlib import Path

import numpy as np
import pandas as pd


CORE_PATH = Path(__file__).resolve().parents[2] / "HBV-Cryo" / "率定核心.py"
SPEC = importlib.util.spec_from_file_location("hbv_core_invariant_test", CORE_PATH)
assert SPEC is not None and SPEC.loader is not None
CORE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(CORE)


class HbvCoreInvariantTests(unittest.TestCase):
    def test_independent_event_positions_do_not_double_count_repeated_timestamps(self) -> None:
        dates_one = pd.date_range("2025-06-01", periods=8, freq="1h")
        dates = pd.DatetimeIndex(list(dates_one) + list(dates_one))
        obs = np.asarray([1, 2, 4, 8, 6, 4, 2, 1] * 2, dtype=float)
        sim = obs.copy()
        previous = (
            CORE.EVENT_RUNTIME_ENABLED,
            CORE.EVENT_RUNTIME_MODE,
            CORE.EVENT_RUNTIME_WINDOWS,
            CORE.TIME_STEP_HOURS,
        )
        try:
            CORE.EVENT_RUNTIME_ENABLED = True
            CORE.EVENT_RUNTIME_MODE = "independent_event_windows"
            CORE.EVENT_RUNTIME_WINDOWS = [
                {"event_id": "E1", "start_idx": 0, "end_idx": 7},
                {"event_id": "E2", "start_idx": 8, "end_idx": 15},
            ]
            CORE.TIME_STEP_HOURS = 1.0
            metrics = CORE.compute_single_flood_event_metrics(
                dates,
                obs,
                sim,
                {"event_id": "E1", "score_start": dates_one[0], "score_end": dates_one[-1]},
                CORE.normalize_flood_event_weights(),
                6.0,
            )
        finally:
            (
                CORE.EVENT_RUNTIME_ENABLED,
                CORE.EVENT_RUNTIME_MODE,
                CORE.EVENT_RUNTIME_WINDOWS,
                CORE.TIME_STEP_HOURS,
            ) = previous

        self.assertTrue(metrics["valid"])
        self.assertEqual(metrics["total_steps"], 8)
        self.assertEqual(metrics["duration_hours"], 8.0)

    def test_event_with_internal_non_evaluable_outlet_step_is_invalid(self) -> None:
        dates = pd.date_range("2025-06-01", periods=8, freq="1h")
        obs = np.asarray([1, 2, 4, 8, 6, 4, 2, 1], dtype=float)
        sim = obs.copy()
        sim[5] = np.nan
        previous_step = CORE.TIME_STEP_HOURS
        try:
            CORE.TIME_STEP_HOURS = 1.0
            metrics = CORE.compute_single_flood_event_metrics(
                dates,
                obs,
                sim,
                {"event_id": "E1", "score_start": dates[0], "score_end": dates[-1]},
                CORE.normalize_flood_event_weights(),
                6.0,
            )
        finally:
            CORE.TIME_STEP_HOURS = previous_step

        self.assertFalse(metrics["valid"])
        self.assertEqual(metrics["status"], "incomplete_event_data")
        self.assertEqual(metrics["non_evaluable_simulation_steps"], 1)

    def test_boundary_routing_requires_new_warmup_after_each_missing_period(self) -> None:
        boundary = np.r_[np.ones(30), [np.nan], np.ones(30)]
        previous = (
            CORE.BOUNDARY_INFLOW_ENABLED,
            CORE.BOUNDARY_ROUTING_WARMUP_DAYS,
            CORE.TIME_STEP_HOURS,
            CORE.SIM_DATES,
        )
        try:
            CORE.BOUNDARY_INFLOW_ENABLED = True
            CORE.BOUNDARY_ROUTING_WARMUP_DAYS = 1.0
            CORE.TIME_STEP_HOURS = 1.0
            CORE.SIM_DATES = pd.date_range("2025-01-01", periods=len(boundary), freq="1h")
            routed, evaluable, periods = CORE.route_boundary_inflow_with_warmup(boundary, 1.0, 0.2)
        finally:
            (
                CORE.BOUNDARY_INFLOW_ENABLED,
                CORE.BOUNDARY_ROUTING_WARMUP_DAYS,
                CORE.TIME_STEP_HOURS,
                CORE.SIM_DATES,
            ) = previous

        self.assertTrue(np.isnan(routed[30]))
        self.assertFalse(evaluable[:24].any())
        self.assertTrue(evaluable[24:30].all())
        self.assertFalse(evaluable[31:55].any())
        self.assertTrue(evaluable[55:].all())
        self.assertEqual(len(periods), 2)

    def test_initial_parameter_loader_accepts_studio_txt_and_metadata_json(self) -> None:
        values = {name: float(index + 1) for index, name in enumerate(CORE.param_names)}
        values.update({"K": 0.4, "K1": 0.2, "K2": 0.05, "K_MUSK": 1.0, "X_MUSK": 0.2})
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            text_path = root / "parameters.txt"
            text_path.write_text(
                "HBV-Cryo calibration\n\n" + "\n".join(f"{name} = {value}" for name, value in values.items()),
                encoding="utf-8",
            )
            json_path = root / "metadata.json"
            json_path.write_text(json.dumps({"optimized_params": values}), encoding="utf-8")
            from_text = CORE.load_initial_param_vector(text_path)
            from_json = CORE.load_initial_param_vector(json_path)
        np.testing.assert_allclose(from_text, from_json)
        self.assertEqual(len(from_text), len(CORE.param_names))

    def test_upper_zone_limit_preserves_raw_q0_q1_ratio(self) -> None:
        q0, q1 = CORE.limit_upper_zone_outflows(8.0, 4.0, 6.0)
        self.assertAlmostEqual(q0, 4.0)
        self.assertAlmostEqual(q1, 2.0)
        self.assertAlmostEqual(q0 / q1, 2.0)
        self.assertEqual(CORE.limit_upper_zone_outflows(1.0, 2.0, 5.0), (1.0, 2.0))

    def test_mixed_wc_withdrawal_is_proportional_and_conservative(self) -> None:
        remaining_r, remaining_s, remaining_i, out_r, out_s, out_i = CORE.withdraw_mixed_water_sources(
            2.0, 3.0, 5.0, 4.0,
        )
        np.testing.assert_allclose([out_r, out_s, out_i], [0.8, 1.2, 2.0], rtol=0, atol=1e-12)
        self.assertAlmostEqual(remaining_r + remaining_s + remaining_i, 6.0)
        self.assertAlmostEqual(out_r + out_s + out_i, 4.0)

    def test_full_and_fast_ice_kernels_share_source_accounting(self) -> None:
        parameters = np.asarray(
            [0.0, 1.0, 1.0, 3.0, 0.1, 0.05, 100.0, 1.0, 0.0, 0.8, 0.5, 0.1, 0.05, 1.0, 0.2],
            dtype="float64",
        )
        precipitation = np.asarray([[10.0, 0.0, 5.0, 0.0]], dtype="float32")
        temperature = np.asarray([[-5.0, 5.0, 5.0, 2.0]], dtype="float32")
        zeros = np.zeros_like(precipitation)
        zone_high = np.asarray([True])
        glacier = np.asarray([True])
        scale = np.asarray([1.0])
        delta_t = np.zeros(1, dtype="float32")
        initial = np.asarray([0.0, 5.0, 0.0, 0.0, 0.0])

        full_result = CORE.run_all_cells_flat(
            precipitation, temperature, zeros, zeros, parameters, zone_high, initial,
            scale, glacier, True, 1.5, 3.0, 4.0, delta_t,
        )
        full = full_result[:4]
        fast = CORE.run_all_cells_total_ice_flat(
            precipitation, temperature, zeros, zeros, parameters, zone_high, initial,
            scale, glacier, True, 1.5, 3.0, 4.0, delta_t,
        )

        np.testing.assert_allclose(full[0], full[1] + full[2] + full[3], rtol=0, atol=1e-10)
        np.testing.assert_allclose(full[0], fast[0], rtol=0, atol=1e-10)
        np.testing.assert_allclose(full[3], fast[1], rtol=0, atol=1e-10)

    def test_soil_storage_excess_is_routed_and_full_kernel_closes(self) -> None:
        initial_recharge = (9.0 / 10.0) ** 4.0 * 100.0
        sm, recharge, excess = CORE.route_soil_storage_excess(
            9.0, 100.0, initial_recharge, 0.0, 10.0,
        )
        self.assertAlmostEqual(sm, 10.0)
        self.assertAlmostEqual(recharge, 99.0)
        self.assertGreater(excess, 0.0)

        parameters = np.asarray(
            [0.0, 1.0, 1.0, 3.0, 0.1, 0.05, 10.0, 4.0, 0.0, 0.8, 0.5, 0.1, 0.05, 1.0, 0.2],
            dtype="float64",
        )
        precipitation = np.asarray([[100.0, 0.0, 0.0]], dtype="float32")
        temperature = np.asarray([[5.0, 5.0, 5.0]], dtype="float32")
        zeros = np.zeros_like(precipitation)
        result = CORE.run_all_cells_flat(
            precipitation,
            temperature,
            zeros,
            zeros,
            parameters,
            np.asarray([False]),
            np.asarray([0.0, 9.0, 0.0, 0.0, 0.0]),
            np.asarray([1.0]),
            np.asarray([False]),
            False,
            1.5,
            3.0,
            4.0,
            np.zeros(1, dtype="float32"),
        )
        np.testing.assert_allclose(result[0], result[1] + result[2] + result[3], rtol=0, atol=1e-9)
        np.testing.assert_allclose(result[7], 0.0, rtol=0, atol=1e-9)
        self.assertLessEqual(result[-1], 1e-9)

    def test_v1_snapshot_wc_loads_conservatively_as_legacy_snow_source(self) -> None:
        values = np.asarray([1.0, 2.0], dtype="float32")
        snapshot = {
            "main_sp": values,
            "main_sm": values,
            "main_wc": values,
            "main_uz_r": values,
            "main_uz_s": values,
            "main_uz_i": values,
            "main_lz_r": values,
            "main_lz_s": values,
            "main_lz_i": values,
        }
        states = CORE._snapshot_branch_tuple(snapshot, "main_")
        self.assertEqual(len(states), 12)
        np.testing.assert_allclose(states[3], 0.0)
        np.testing.assert_allclose(states[4], values)
        np.testing.assert_allclose(states[5], 0.0)

    def test_interbasin_residual_diagnostic_uses_routed_boundary_and_local_flow(self) -> None:
        diagnostics = CORE.compute_interbasin_residual_diagnostics(
            np.asarray(["2025-06-01", "2025-06-02", "2025-06-03"], dtype="datetime64[D]"),
            np.asarray([10.0, 12.0, 14.0]),
            np.asarray([4.0, 4.0, 4.0]),
            np.asarray([6.0, 8.0, 10.0]),
            step_hours=24.0,
        )
        self.assertTrue(diagnostics["available"])
        self.assertEqual(diagnostics["negative_residual_steps"], 0)
        self.assertAlmostEqual(diagnostics["comparison"]["nse"], 1.0)
        self.assertAlmostEqual(CORE.interval_objective_guard_penalty(diagnostics), 0.0)

        unreliable = CORE.compute_interbasin_residual_diagnostics(
            None,
            np.asarray([1.0, 1.0, 1.0]),
            np.asarray([2.0, 2.0, 2.0]),
            np.asarray([0.0, 0.0, 0.0]),
            step_hours=24.0,
        )
        self.assertGreater(unreliable["negative_residual_volume_ratio"], 0.10)
        self.assertIsNone(CORE.interval_objective_guard_penalty(unreliable))


if __name__ == "__main__":
    unittest.main()
