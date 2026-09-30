from __future__ import annotations

import importlib.util
import io
import json
import tempfile
import time
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

import numpy as np
import pandas as pd


CORE_PATH = Path(__file__).resolve().parents[2] / "HBV-Cryo" / "率定核心.py"
SPEC = importlib.util.spec_from_file_location("hbv_core_full_period_test", CORE_PATH)
assert SPEC is not None and SPEC.loader is not None
CORE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(CORE)


class RunFullPeriodOutputTests(unittest.TestCase):
    def test_fractions_share_outlet_and_observation_pairs(self) -> None:
        arrays = [
            np.asarray([10.0, np.nan, 20.0, 30.0]),
            np.asarray([4.0, 1000.0, 8.0, 6000.0]),
            np.asarray([6.0, np.nan, 12.0, 24.0]),
            np.asarray([2.0, 800.0, 4.0, 3000.0]),
            np.asarray([1.0, 100.0, 2.0, 1000.0]),
            np.asarray([1.0, 100.0, 2.0, 2000.0]),
            np.asarray([11.0, 2.0, 22.0, np.nan]),
        ]
        before = [values.copy() for values in arrays]
        fractions = CORE.compute_flow_component_fractions(*arrays)

        self.assertEqual(fractions["sample_count"], 2)
        self.assertAlmostEqual(fractions["boundary_inflow_fraction"], 0.6)
        self.assertAlmostEqual(fractions["local_runoff_fraction"], 0.4)
        self.assertAlmostEqual(fractions["rain_fraction"], 0.2)
        self.assertAlmostEqual(fractions["snow_fraction"], 0.1)
        self.assertAlmostEqual(fractions["ice_fraction"], 0.1)
        self.assertAlmostEqual(fractions["local_rain_fraction"], 0.5)
        self.assertAlmostEqual(fractions["local_snow_fraction"], 0.25)
        self.assertAlmostEqual(fractions["local_ice_fraction"], 0.25)
        for old, current in zip(before, arrays):
            np.testing.assert_array_equal(current, old)

    def test_complete_series_keeps_component_fractions(self) -> None:
        total = np.asarray([10.0, 20.0, 30.0])
        local = total * 0.4
        fractions = CORE.compute_flow_component_fractions(
            total, local, total - local, local * 0.5, local * 0.3, local * 0.2, total,
        )
        self.assertEqual(fractions["sample_count"], 3)
        self.assertAlmostEqual(fractions["boundary_inflow_fraction"], 0.6)
        self.assertAlmostEqual(fractions["local_runoff_fraction"], 0.4)
        self.assertAlmostEqual(fractions["local_snow_fraction"], 0.3)
        self.assertAlmostEqual(fractions["local_ice_fraction"], 0.2)

    def test_no_valid_pairs_or_no_water_do_not_claim_zero_contribution(self) -> None:
        for total, observations in (
            (np.asarray([np.nan, np.nan]), np.asarray([1.0, 2.0])),
            (np.asarray([0.0, 0.0]), np.asarray([0.0, 0.0])),
        ):
            with self.subTest(total=total):
                zero = np.zeros(2)
                fractions = CORE.compute_flow_component_fractions(total, zero, zero, zero, zero, zero, observations)
                cleaned = CORE._json_safe_value(fractions)
                for name in ("boundary_inflow_fraction", "local_runoff_fraction", "local_snow_fraction", "local_ice_fraction"):
                    self.assertIsNone(cleaned[name])

    def test_save_results_retains_daily_and_hourly_warmup_and_missing_boundary(self) -> None:
        for step_hours in (24.0, 1.0):
            with self.subTest(step_hours=step_hours), tempfile.TemporaryDirectory(prefix="hbv_full_period_") as temp_dir:
                root = Path(temp_dir)
                dates = pd.date_range("2025-06-01", periods=10, freq=pd.Timedelta(hours=step_hours))
                rain = np.arange(1.0, 11.0)
                rain[6] = 1000.0  # No observed outlet: excluded from every fraction.
                rain[8] = 2000.0  # No boundary: local state/output still exists.
                snow, ice = rain * 0.4, rain * 0.2
                local = rain + snow + ice
                boundary = np.full(10, 100.0)
                boundary[:3] = np.nan
                boundary[8] = np.nan
                total = local + boundary
                observed = total * 0.98
                observed[6] = np.nan
                calibration = np.asarray([False] * 3 + [True] * 3 + [False] * 4)
                validation = np.asarray([False] * 6 + [True] * 4)
                simulation = {
                    "q_total": total,
                    "q_local": local,
                    "q_boundary": boundary,
                    "q_rain": rain,
                    "q_snow": snow,
                    "q_ice": ice,
                    "q_ice_raw": ice.copy(),
                    "q_ice_reference": None,
                    "q_ice_reference_raw": None,
                    "glacier_enabled": True,
                    "boundary_enabled": True,
                    "boundary_evaluable_mask": np.isfinite(boundary),
                    "outlet_evaluable_mask": np.isfinite(total),
                }
                result = SimpleNamespace(x=np.ones(len(CORE.param_names)), nfev=1, nit=0)
                globals_and_dependencies = {
                    "args": SimpleNamespace(prec_source="era5", glacier_mode="inline", workers=1),
                    "start_time": time.time(),
                    "RUN_ID": "full_period_fixture",
                    "RUNS_DIR": str(root / "runs"),
                    "SIM_DATES": dates,
                    "WARMUP_STEPS": 3,
                    "WARMUP_START": str(dates[0]),
                    "WARMUP_END": str(dates[2]),
                    "CALIB_START": str(dates[3]),
                    "CALIB_END": str(dates[5]),
                    "VALID_START": str(dates[6]),
                    "VALID_END": str(dates[-1]),
                    "TIME_STEP_HOURS": step_hours,
                    "CALIB_MASK": calibration,
                    "VALID_MASK": validation,
                    "Q_OBS_FULL": observed,
                    "Q_OBS_OBJ": observed.copy(),
                    "Q_OBS_CALIB": observed[calibration],
                    "Q_OBS_VALID": observed[validation],
                    "BOUNDARY_INFLOW_ENABLED": True,
                    "PROJECT_OBJECT_TYPE": "interbasin_with_boundary",
                    "VALID_CELLS": np.asarray([[0, 0]]),
                    "CATCHMENT_AREA": 1.0,
                    "ZONE_LOW": np.asarray([[True]]),
                    "ZONE_HIGH": np.asarray([[False]]),
                    "GLACIER_MASK": np.asarray([[True]]),
                    "GLACIER_FRACTION": np.asarray([[0.1]]),
                    "run_simulation": mock.Mock(return_value=simulation),
                    "compute_objective_terms": mock.Mock(return_value=(0.0, {})),
                    "compute_model_water_balance_diagnostics": mock.Mock(return_value={"available": False}),
                    "compute_glacier_physical_checks": mock.Mock(return_value={"available": False}),
                    "compute_state_snapshot": mock.Mock(side_effect=RuntimeError("fixture has no spatial model state")),
                }
                for name in ("PREC_DIR", "TEMP_DIR", "EVAP_DIR", "GLACIER_MELT_DIR", "GLACIER_MASK_PATH", "GLACIER_FRACTION_PATH", "GLACIER_ELEV_PATH", "OBS_FILE"):
                    globals_and_dependencies[name] = str(root / "input" / name)

                with mock.patch.multiple(CORE, **globals_and_dependencies), redirect_stdout(io.StringIO()):
                    expected_metrics = CORE.compute_metrics(total)
                    CORE.save_results(result)
                globals_and_dependencies["run_simulation"].assert_called_once_with(result.x)
                run_dir = root / "runs" / "hbv_cryo_era5_inline_full_period_fixture"
                frame = pd.read_csv(run_dir / "simulation.csv")
                interval_frame = pd.read_csv(run_dir / "interbasin_residual_diagnostics.csv")
                metadata = json.loads((run_dir / "metadata.json").read_text(encoding="utf-8"))

                self.assertEqual(len(frame), 10)
                self.assertEqual(len(interval_frame), 10)
                np.testing.assert_array_equal(pd.to_datetime(frame["date"]), dates)
                self.assertTrue(frame.loc[:2, "q_sim"].isna().all())
                self.assertTrue(frame.loc[:2, "q_boundary_inflow"].isna().all())
                np.testing.assert_allclose(frame["q_local"], local)
                np.testing.assert_allclose(frame["q_rain"], rain)
                self.assertTrue(pd.isna(frame.loc[8, "q_sim"]))
                self.assertEqual(frame.loc[8, "q_local"], local[8])
                self.assertEqual(metadata["time_config"]["warmup_steps"], 3)
                for label, suffix, mask in (("calibration", "cal", calibration), ("validation", "val", validation)):
                    metrics = metadata["metrics"][label]
                    common = mask & np.isfinite(total) & np.isfinite(observed)
                    self.assertEqual(metrics["sample_count"], expected_metrics[f"obs_count_{suffix}"])
                    self.assertEqual(metrics["fraction_sample_count"], int(np.sum(common)))
                    self.assertEqual(metrics["fraction_sample_count"], metrics["sample_count"])
                    self.assertEqual(metrics["nse"], round(expected_metrics[f"nse_{suffix}"], 4))
                    self.assertEqual(metrics["local_runoff_fraction"], round(float(np.sum(local[common]) / np.sum(total[common])), 4))
                    self.assertAlmostEqual(metrics["boundary_inflow_fraction"] + metrics["local_runoff_fraction"], 1.0, places=4)
                    self.assertAlmostEqual(metrics["local_rain_fraction"] + metrics["local_snow_fraction"] + metrics["local_ice_fraction"], 1.0, places=4)


if __name__ == "__main__":
    unittest.main()
