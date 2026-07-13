from __future__ import annotations

import sys
import unittest
from pathlib import Path

import numpy as np


STUDIO_DIR = Path(__file__).resolve().parents[1]
if str(STUDIO_DIR) not in sys.path:
    sys.path.insert(0, str(STUDIO_DIR))

from initial_state_sensitivity_runner import build_scientific_acceptance, summarize_snapshot  # noqa: E402


class InitialStateSensitivityRunnerTests(unittest.TestCase):
    def test_summarize_snapshot_combines_fractional_branches(self) -> None:
        arrays = {"glacier_fraction_cells": np.asarray([0.25, 0.75])}
        for key in ("sp", "sm", "wc", "uz", "lz"):
            arrays[f"glacier_{key}"] = np.asarray([4.0, 8.0])
            arrays[f"nonglacier_{key}"] = np.asarray([0.0, 4.0])

        summary = summarize_snapshot(
            arrays,
            {
                "branches": ["glacier", "nonglacier"],
                "snapshot_time": "2025-05-31",
                "time_steps": 151,
                "snapshot_mode": "fractional_subgrid",
                "cell_count": 2,
            },
        )

        self.assertAlmostEqual(summary["basin_storage_mm"]["SP"]["mean"], 4.0)
        self.assertAlmostEqual(summary["total_storage_mm"]["mean"], 20.0)
        self.assertEqual(summary["snapshot_time"], "2025-05-31")

    def test_scientific_acceptance_requires_water_and_initial_state_gates(self) -> None:
        metadata = {
            "model_water_balance": {
                "available": True,
                "hydrological_screening": {
                    "formal_interval_acceptance": False,
                    "reasons": ["unresolved_water_source"],
                },
            }
        }
        blocked = build_scientific_acceptance(metadata, {"converged": False})
        self.assertFalse(blocked["formal_result_accepted"])
        self.assertIn("unresolved_water_source", blocked["blockers"])
        self.assertIn("initial_state_sensitivity_not_converged", blocked["blockers"])

        metadata["model_water_balance"]["hydrological_screening"] = {
            "formal_interval_acceptance": True,
            "reasons": [],
        }
        accepted = build_scientific_acceptance(metadata, {"converged": True})
        self.assertTrue(accepted["formal_result_accepted"])
        self.assertEqual(accepted["status"], "accepted")


if __name__ == "__main__":
    unittest.main()
