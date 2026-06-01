from __future__ import annotations

import sys
import unittest
from pathlib import Path


STUDIO_DIR = Path(__file__).resolve().parents[1]
if str(STUDIO_DIR) not in sys.path:
    sys.path.insert(0, str(STUDIO_DIR))

from services.forward_simulation import ForwardSimulationStartContext, forward_simulation_start_plan  # noqa: E402


class ForwardSimulationServiceTests(unittest.TestCase):
    def test_forward_simulation_start_plan_builds_task_metadata(self) -> None:
        forward_context = {
            "config_path": "workspace.json",
            "run_dir": "runs/source-run",
            "profile": "daily",
            "prec_source": "era5",
            "objective_mode": "nse",
            "glacier_mode": "formal",
        }
        context = ForwardSimulationStartContext(
            build_forward_payload_context=lambda payload: forward_context,
        )

        plan = forward_simulation_start_plan({"run_path": "runs/source-run"}, context)

        self.assertEqual(plan.label, "保存并重算 | source-run")
        self.assertEqual(plan.command, ["forward_sim"])
        self.assertEqual(plan.metadata["config_path"], str(Path("workspace.json").resolve()))
        self.assertEqual(plan.metadata["run_path"], str(Path("runs/source-run").resolve()))
        self.assertEqual(plan.metadata["profile"], "daily")
        self.assertEqual(plan.metadata["runtime_prec_source"], "era5")
        self.assertEqual(plan.metadata["objective_mode"], "nse")
        self.assertEqual(plan.metadata["glacier_mode"], "formal")

    def test_forward_simulation_start_plan_propagates_context_errors(self) -> None:
        context = ForwardSimulationStartContext(
            build_forward_payload_context=lambda payload: (_ for _ in ()).throw(ValueError("缺少源结果")),
        )

        with self.assertRaisesRegex(ValueError, "缺少源结果"):
            forward_simulation_start_plan({}, context)


if __name__ == "__main__":
    unittest.main()
