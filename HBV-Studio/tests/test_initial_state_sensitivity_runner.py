from __future__ import annotations

import sys
import unittest
from pathlib import Path

import numpy as np


STUDIO_DIR = Path(__file__).resolve().parents[1]
if str(STUDIO_DIR) not in sys.path:
    sys.path.insert(0, str(STUDIO_DIR))

from initial_state_sensitivity_runner import (  # noqa: E402
    _select_local_flow,
    build_proxy_forcing_layout,
    build_initial_state_diagnostic,
    summarize_snapshot,
)


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

    def test_initial_state_diagnostic_reports_warnings_without_blocking_modeling(self) -> None:
        metadata = {
            "model_water_balance": {
                "available": True,
                "hydrological_screening": {
                    "formal_interval_acceptance": False,
                    "reasons": ["unresolved_water_source"],
                },
            }
        }
        sensitive = build_initial_state_diagnostic(metadata, {"converged": False})
        self.assertEqual(sensitive["status"], "initial_state_sensitive")
        self.assertIn("unresolved_water_source", sensitive["warnings"])
        self.assertIn("initial_state_sensitivity_detected", sensitive["warnings"])

        metadata["model_water_balance"]["hydrological_screening"] = {
            "formal_interval_acceptance": True,
            "reasons": [],
        }
        converged = build_initial_state_diagnostic(metadata, {"converged": True})
        self.assertEqual(converged["status"], "converged")

    def test_initial_state_diagnostic_labels_repeated_forcing_proxy(self) -> None:
        metadata = {
            "model_water_balance": {
                "available": True,
                "hydrological_screening": {
                    "formal_interval_acceptance": True,
                    "reasons": [],
                },
            }
        }
        result = build_initial_state_diagnostic(
            metadata,
            {"converged": True, "formal_acceptance_eligible": False},
        )
        self.assertTrue(result["repeated_forcing_proxy_used"])
        self.assertIn("repeated_forcing_proxy_used", result["warnings"])

    def test_local_flow_selection_does_not_use_boundary_dominated_total(self) -> None:
        values, basis = _select_local_flow(
            {
                "q_total": np.asarray([100.0, 100.0]),
                "q_local": np.asarray([10.0, 11.0]),
                "q_local_raw": np.asarray([9.0, 10.0]),
            }
        )
        np.testing.assert_allclose(values, [9.0, 10.0])
        self.assertEqual(basis, "q_local_raw")

    def test_proxy_layout_places_target_after_complete_proxy_cycles(self) -> None:
        layout = build_proxy_forcing_layout(total_steps=303, warmup_steps=151, proxy_cycles=3)
        self.assertEqual(layout["combined_steps"], 1212)
        self.assertEqual(layout["target_start_step"], 909)
        self.assertEqual(layout["target_warmup_end_step"], 1060)
        self.assertEqual(layout["target_evaluation_end_step"], 1212)


if __name__ == "__main__":
    unittest.main()
