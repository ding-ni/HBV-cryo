from __future__ import annotations

import copy
import json
import unittest

import numpy as np
import pandas as pd

from test_daily_objective_validation_isolation import build_bundle, evaluate, objective


class DailyObjectiveWinterAvailabilityTests(unittest.TestCase):
    def test_summer_calibration_reports_winter_unchecked_without_changing_score(self) -> None:
        result = evaluate(build_bundle(seasonal_only=True))
        item = result["objective_terms"]["cryo_consistency"]["winter_ice_ratio"]
        self.assertFalse(item["active"])
        self.assertEqual(item["status"], "skipped_insufficient_data")
        self.assertEqual(item["sample_count"], 0)
        self.assertIsNone(item["value_sim"])
        self.assertIsNone(item["winter_ice_ratio_djf"])
        self.assertEqual(item["penalty"], 0.0)
        for report in (result["diagnostics"]["cryo_timing_report"], result["hard_checks"]["details"]):
            self.assertEqual(report["winter_sample_count"], 0)
            self.assertFalse(report["winter_ice_check_active"])
            self.assertEqual(report["winter_ice_check_status"], "skipped_insufficient_data")
            self.assertIsNone(report["winter_ice_ratio_djf"])
            self.assertIsNone(report["winter_ice_mean_m3s"])
            self.assertIsNone(json.loads(json.dumps(report))["winter_ice_ratio_djf"])
        self.assertEqual(result["hard_checks"]["status"], "pass")
        # Captured before this diagnostic-only change on the same seasonal fixture.
        self.assertAlmostEqual(result["objective_value"], 0.20493874199936546, places=14)

    def test_winter_simulation_outside_calibration_does_not_activate_check(self) -> None:
        bundle = build_bundle(seasonal_only=True)
        baseline = evaluate(bundle)
        changed = copy.deepcopy(bundle)
        winter = np.isin(bundle["date"].month, [12, 1, 2])
        changed["q_ice"][winter] = 5000.0
        changed["q_ice_raw"] = changed["q_ice"].copy()
        changed["q_glacier_total"] = changed["q_ice"] + changed["q_snow_glacier"]
        changed["q_local"] = changed["q_rain"] + changed["q_snow"] + changed["q_ice"]
        changed["q_total"] = changed["q_local"] + changed["q_boundary"]
        result = evaluate(changed)
        self.assertEqual(result["objective_value"], baseline["objective_value"])
        self.assertEqual(result["objective_terms"]["cryo_consistency"]["winter_ice_ratio"],
                         baseline["objective_terms"]["cryo_consistency"]["winter_ice_ratio"])
        self.assertEqual(result["hard_checks"], baseline["hard_checks"])

    def test_full_year_calibration_retains_winter_values_and_score(self) -> None:
        result = evaluate(build_bundle())
        item = result["objective_terms"]["cryo_consistency"]["winter_ice_ratio"]
        self.assertTrue(item["active"])
        self.assertEqual(item["status"], "ok")
        self.assertEqual(item["sample_count"], 180)
        self.assertEqual(result["hard_checks"]["details"]["winter_sample_count"], 180)
        self.assertAlmostEqual(item["value_sim"], 6.421385237320211e-05, places=16)
        self.assertAlmostEqual(result["diagnostics"]["cryo_timing_report"]["winter_ice_mean_m3s"],
                               0.0006498225898638509, places=16)
        # Captured before this diagnostic-only change on the full-year fixture.
        self.assertAlmostEqual(result["objective_value"], 0.017887334809704884, places=14)

    def test_available_winter_with_zero_ice_is_measured_zero(self) -> None:
        dates = pd.date_range("2025-01-01", "2025-01-31", freq="D")
        zeros = np.zeros(len(dates))
        _, terms, report = objective._compute_cryo_terms(
            dates, zeros, zeros, zeros, np.full(len(dates), 10.0), np.ones(len(dates), dtype=bool),
        )
        item = terms["winter_ice_ratio"]
        self.assertTrue(item["active"])
        self.assertEqual(item["status"], "ok")
        self.assertEqual(item["sample_count"], 31)
        self.assertEqual(item["value_sim"], 0.0)
        self.assertEqual(report["winter_ice_mean_m3s"], 0.0)

    def test_available_winter_keeps_soft_penalty_and_hard_limit(self) -> None:
        dates = pd.date_range("2025-01-01", "2025-01-31", freq="D")
        zeros = np.zeros(len(dates))
        penalty, terms, _ = objective._compute_cryo_terms(
            dates, np.ones(len(dates)), zeros, zeros,
            np.full(len(dates), 10.0), np.ones(len(dates), dtype=bool),
        )
        self.assertAlmostEqual(penalty, 0.10)
        self.assertAlmostEqual(terms["winter_ice_ratio"]["value_sim"], 0.10)
        bundle = build_bundle()
        winter = bundle["calib_mask"] & np.isin(bundle["date"].month, [12, 1, 2])
        bundle["q_ice"][winter] = 10.0
        bundle["q_ice_raw"] = bundle["q_ice"].copy()
        bundle["q_local"] = bundle["q_rain"] + bundle["q_snow"] + bundle["q_ice"]
        bundle["q_total"] = bundle["q_local"] + bundle["q_boundary"]
        result = evaluate(bundle)
        self.assertEqual(result["hard_checks"]["failed_code"], "H007_WINTER_ICE_LEAKAGE_HARD")
        self.assertEqual(result["hard_checks"]["details"]["winter_sample_count"], 180)
        self.assertEqual(result["objective_value"], 9999.0)


if __name__ == "__main__":
    unittest.main()
