from __future__ import annotations

import ast
import copy
import sys
import unittest
from pathlib import Path

import numpy as np
import pandas as pd


CORE_DIR = Path(__file__).resolve().parents[2] / "HBV-Cryo"
if str(CORE_DIR) not in sys.path:
    sys.path.insert(0, str(CORE_DIR))

import daily_unified_objective as objective  # noqa: E402


def build_bundle(*, seasonal_only: bool = False) -> dict:
    if seasonal_only:
        dates = pd.date_range("2022-01-01", "2025-10-31", freq="D")
        calib_mask = np.asarray((dates >= "2025-06-01") & (dates <= "2025-09-10"))
        valid_mask = np.asarray(dates >= "2025-09-11")
    else:
        dates = pd.date_range("2020-01-01", "2023-12-31", freq="D")
        calib_mask = np.asarray((dates.year == 2021) | (dates.year == 2022))
        valid_mask = np.asarray(dates.year == 2023)
    doy = dates.dayofyear.to_numpy(dtype=np.float64)
    q_rain = 7.0 + 17.0 * np.exp(-((doy - 190.0) / 60.0) ** 2)
    q_snow = 4.0 * np.exp(-((doy - 135.0) / 35.0) ** 2)
    q_ice = 2.0 * np.exp(-((doy - 240.0) / 40.0) ** 2)
    q_boundary = 3.0 + 0.4 * np.sin(doy * 2.0 * np.pi / 365.25)
    q_local = q_rain + q_snow + q_ice
    q_total = q_local + q_boundary
    obs = q_total * (1.0 + 0.05 * np.cos(doy * 2.0 * np.pi / 365.25))
    obs[~(calib_mask | valid_mask)] = np.nan
    return {
        "date": dates,
        "q_total": q_total,
        "q_local": q_local,
        "q_boundary": q_boundary,
        "q_rain": q_rain,
        "q_snow": q_snow,
        "q_ice": q_ice,
        "q_ice_raw": q_ice.copy(),
        "q_snow_glacier": q_snow * 0.5,
        "q_glacier_total": q_ice + q_snow * 0.5,
        "q_obs": obs.copy(),
        "q_obs_obj": obs,
        "calib_mask": calib_mask,
        "valid_mask": valid_mask,
        "project_object_type": "interbasin_with_boundary",
        "q_score_basis": "q_total",
        "muskingum_coeffs": {"C0": 0.2, "C1": 0.3, "C2": 0.5},
        "glacier_enabled": True,
        "glacier_model_mode": "fractional_subgrid",
        "glacier_area_ratio": 0.03,
        "glacier_mask_exists": True,
        "glacier_fraction_exists": True,
        "glacier_elev_exists": True,
        "glacier_fraction_window": [0.02, 0.20],
    }


def measure_metrics(bundle: dict) -> dict:
    metrics = {}
    for suffix, mask_key in (("cal", "calib_mask"), ("val", "valid_mask")):
        obs = bundle["q_obs_obj"][bundle[mask_key]]
        sim = bundle["q_total"][bundle[mask_key]]
        common = np.isfinite(obs) & np.isfinite(sim)
        obs, sim = obs[common], sim[common]
        metrics[f"obs_count_{suffix}"] = len(obs)
        if len(obs) < 2:
            for name in ("nse", "log_nse", "kge", "pbias"):
                metrics[f"{name}_{suffix}"] = float("nan")
            continue
        metrics[f"nse_{suffix}"] = 1.0 - np.sum((sim - obs) ** 2) / np.sum((obs - np.mean(obs)) ** 2)
        log_obs, log_sim = np.log1p(obs), np.log1p(sim)
        metrics[f"log_nse_{suffix}"] = 1.0 - np.sum((log_sim - log_obs) ** 2) / np.sum((log_obs - np.mean(log_obs)) ** 2)
        r = np.corrcoef(obs, sim)[0, 1]
        alpha = np.std(sim) / np.std(obs)
        beta = np.mean(sim) / np.mean(obs)
        metrics[f"kge_{suffix}"] = 1.0 - np.sqrt((r - 1.0) ** 2 + (alpha - 1.0) ** 2 + (beta - 1.0) ** 2)
        metrics[f"pbias_{suffix}"] = 100.0 * np.sum(sim - obs) / np.sum(obs)
    return metrics


def evaluate(bundle: dict, metrics: dict | None = None) -> dict:
    return objective.evaluate_daily_unified_objective(
        bundle, measure_metrics(bundle) if metrics is None else metrics, bad_obj=9999.0,
    )


class DailyObjectiveValidationIsolationTests(unittest.TestCase):
    def assert_optimization_equal(self, before: dict, after: dict) -> None:
        self.assertEqual(before["objective_value"], after["objective_value"])
        self.assertEqual(before["hard_checks"], after["hard_checks"])
        for name in ("flow", "flow_guard"):
            self.assertEqual(before["objective_terms"][name]["penalty"], after["objective_terms"][name]["penalty"])
        for name in ("seasonality", "process_signatures", "cryo_consistency", "external_evidence", "secondary_terms"):
            self.assertEqual(before["objective_terms"][name], after["objective_terms"][name])

    def test_changed_validation_and_warmup_observations_do_not_change_any_optimization_terms(self) -> None:
        bundle = build_bundle()
        baseline = evaluate(bundle)
        self.assertEqual(baseline["hard_checks"]["status"], "pass")
        self.assertTrue(baseline["objective_terms"]["seasonality"]["active"])
        self.assertTrue(baseline["objective_terms"]["process_signatures"]["swr"]["active"])
        self.assertTrue(baseline["objective_terms"]["process_signatures"]["peak_timing"]["active"])
        valid_mask = bundle["valid_mask"]
        for replacement in (
            bundle["q_obs_obj"][valid_mask] * 25.0,
            bundle["q_obs_obj"][valid_mask][::-1],
            np.full(np.sum(valid_mask), np.nan),
        ):
            with self.subTest(replacement=replacement[:2]):
                changed = copy.deepcopy(bundle)
                changed["q_obs_obj"][valid_mask] = replacement
                changed["q_obs_obj"][~(bundle["calib_mask"] | valid_mask)] = 1e8
                changed["q_obs"] = changed["q_obs_obj"].copy()
                result = evaluate(changed)
                self.assert_optimization_equal(baseline, result)
                self.assertTrue(result["validation_diagnostic_only"])
                self.assertEqual(result["objective_scoring_policy"], "calibration_only_v1")

    def test_long_warmup_with_only_summer_calibration_is_independent_of_validation_sample_count(self) -> None:
        bundle = build_bundle(seasonal_only=True)
        self.assertEqual(int(np.sum(bundle["calib_mask"])), 102)
        self.assertEqual(int(np.sum(bundle["valid_mask"])), 51)
        baseline = evaluate(bundle)
        self.assertEqual(baseline["hard_checks"]["status"], "pass")
        self.assertFalse(baseline["objective_terms"]["seasonality"]["active"])
        changed = copy.deepcopy(bundle)
        changed["q_obs_obj"][bundle["valid_mask"]] = np.nan
        self.assertEqual(measure_metrics(changed)["obs_count_val"], 0)
        self.assert_optimization_equal(baseline, evaluate(changed))

    def test_arbitrary_validation_metrics_cannot_add_flow_or_guard_penalty(self) -> None:
        metrics = measure_metrics(build_bundle())
        baseline_flow, _ = objective._compute_flow_terms(metrics)
        baseline_guard, _ = objective._compute_flow_guard_terms(metrics)
        for value in (1.0, -100.0, -1e300, float("nan"), float("inf"), None):
            for count in (0, 29, 30, 51, 10000):
                with self.subTest(value=value, count=count):
                    changed = dict(metrics, nse_val=value, log_nse_val=value, kge_val=value, pbias_val=value, obs_count_val=count)
                    flow, flow_term = objective._compute_flow_terms(changed)
                    guard, guard_term = objective._compute_flow_guard_terms(changed)
                    self.assertEqual(flow, baseline_flow)
                    self.assertEqual(guard, baseline_guard)
                    for key in ("nse_val", "lognse_val", "pbias_val"):
                        self.assertEqual(flow_term["weight_config"][key], 0.0)
                    for key in ("nse_val", "kge_val", "pbias_val"):
                        check = guard_term["checks"][key]
                        self.assertFalse(check["active"])
                        self.assertTrue(check["diagnostic_only"])
                        self.assertEqual(check["penalty"], 0.0)
                        self.assertEqual(check["weight"], 0.0)
        changed = dict(metrics, nse_cal=0.2, kge_cal=0.35, pbias_cal=40.0)
        self.assertGreater(objective._compute_flow_terms(changed)[0], baseline_flow)
        self.assertGreater(objective._compute_flow_guard_terms(changed)[0], baseline_guard)

    def test_candidate_order_stays_fixed_when_validation_observations_favor_the_other_candidate(self) -> None:
        candidate_a = build_bundle()
        candidate_b = copy.deepcopy(candidate_a)
        for key in ("q_rain", "q_snow", "q_ice", "q_ice_raw", "q_snow_glacier", "q_glacier_total", "q_local"):
            candidate_b[key] *= 0.75
        candidate_b["q_total"] = candidate_b["q_local"] + candidate_b["q_boundary"]
        scores = []
        validation_preferences = []
        for favored in (candidate_a, candidate_b):
            evaluated = []
            for candidate in (candidate_a, candidate_b):
                changed = copy.deepcopy(candidate)
                changed["q_obs_obj"][candidate_a["valid_mask"]] = favored["q_total"][candidate_a["valid_mask"]]
                evaluated.append(evaluate(changed))
            self.assertLess(evaluated[0]["objective_value"], evaluated[1]["objective_value"])
            scores.append(tuple(item["objective_value"] for item in evaluated))
            validation_preferences.append(evaluated[0]["nse_val"] > evaluated[1]["nse_val"])
        self.assertEqual(scores[0], scores[1])
        self.assertEqual(validation_preferences, [True, False])

    def test_good_validation_cannot_rescue_an_invalid_calibration_score(self) -> None:
        bundle = build_bundle()
        metrics = measure_metrics(bundle)
        for nse_val in (1.0, -100.0):
            result = evaluate(bundle, dict(metrics, nse_cal=np.nan, nse_val=nse_val))
            self.assertEqual(result["objective_value"], 9999.0)
            self.assertEqual(result["nse_val"], nse_val)
            self.assertEqual(result["objective_terms"]["flow"]["nse_val"], nse_val)

    def test_core_metadata_records_the_actual_calibration_only_weights(self) -> None:
        core_path = CORE_DIR / "率定核心.py"
        parsed = ast.parse(core_path.read_text(encoding="utf-8"))
        function = next(node for node in parsed.body if isinstance(node, ast.FunctionDef) and node.name == "build_daily_unified_objective_meta")
        namespace = {
            "daily_unified_objective": objective,
            "OBJECTIVE_FAMILY_DAILY": objective.OBJECTIVE_FAMILY,
            "INTERVAL_OBJECTIVE_GUARD_ENABLED": False,
            "current_calibration_profile": lambda: "daily",
        }
        exec(compile(ast.Module(body=[function], type_ignores=[]), str(core_path), "exec"), namespace)
        metadata = namespace["build_daily_unified_objective_meta"]("daily")
        evaluation = evaluate(build_bundle())
        self.assertEqual(metadata["objective_scoring_policy"], evaluation["objective_scoring_policy"])
        self.assertTrue(metadata["validation_diagnostic_only"])
        self.assertTrue(metadata["diagnostic_only_constraints"]["validation_flow_metrics"])
        self.assertEqual(metadata["optimization_period"], "calibration_period")
        flow_weights = metadata["weights"]["flow"]
        actual_weights = evaluation["objective_terms"]["flow"]["weight_config"]
        for recorded, actual in (("nse", "nse"), ("log_nse", "lognse"), ("pbias", "pbias")):
            for period, suffix in (("calibration", "cal"), ("validation", "val")):
                self.assertEqual(flow_weights[f"{recorded}_{period}"], actual_weights[f"{actual}_{suffix}"])
        for name in ("nse", "kge", "pbias"):
            for period, suffix in (("calibration", "cal"), ("validation", "val")):
                self.assertEqual(metadata["weights"]["flow_guard"][f"{name}_{period}_weight"], objective.FLOW_GUARD_CONFIG[f"{name}_{suffix}"]["weight"])


if __name__ == "__main__":
    unittest.main()
