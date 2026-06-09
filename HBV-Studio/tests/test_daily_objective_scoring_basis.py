from __future__ import annotations

import sys
import unittest
from pathlib import Path

import numpy as np


CORE_DIR = Path(__file__).resolve().parents[2] / "HBV-Cryo"
if str(CORE_DIR) not in sys.path:
    sys.path.insert(0, str(CORE_DIR))

import daily_unified_objective as objective  # noqa: E402


class DailyObjectiveScoringBasisTests(unittest.TestCase):
    def test_interbasin_with_boundary_scores_total_outlet_flow(self) -> None:
        bundle = {
            "q_total": np.asarray([11.0, 22.0], dtype="float64"),
            "q_local": np.asarray([1.0, 2.0], dtype="float64"),
        }

        series, key, label = objective._select_q_score_base(bundle, "interbasin_with_boundary")

        self.assertEqual(key, "q_total")
        self.assertEqual(label, "total_runoff_calibration_period")
        np.testing.assert_allclose(series, bundle["q_total"])


if __name__ == "__main__":
    unittest.main()
