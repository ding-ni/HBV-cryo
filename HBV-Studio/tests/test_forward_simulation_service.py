from __future__ import annotations

import sys
import unittest
from pathlib import Path


STUDIO_DIR = Path(__file__).resolve().parents[1]
if str(STUDIO_DIR) not in sys.path:
    sys.path.insert(0, str(STUDIO_DIR))

from services.forward_simulation import (  # noqa: E402
    ForwardSimulationStartContext,
    ForwardSimulationWorkerContext,
    forward_simulation_start_plan,
    forward_simulation_worker_run,
)


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


    def test_forward_simulation_worker_run_records_success_outputs_and_detected_run(self) -> None:
        events: list[tuple] = []

        def run_forward_simulation(payload, *, stage_callback=None, output_callback=None):
            events.append(("payload", payload))
            stage_callback("执行前向模拟", "正在计算")
            output_callback("模型输出")
            return {"run_path": "runs/forward"}

        context = ForwardSimulationWorkerContext(
            run_forward_simulation=run_forward_simulation,
            set_task_metadata=lambda task_id, **kwargs: events.append(("metadata", task_id, kwargs)),
            add_task_output=lambda task_id, message: events.append(("output", task_id, message)),
            add_task_exception_output=lambda task_id, exc: events.append(("exception", task_id, str(exc))),
            mark_task_finished=lambda task_id, **kwargs: events.append(("finished", task_id, kwargs)),
            set_detected_runs=lambda task_id, runs: events.append(("detected", task_id, runs)),
        )

        forward_simulation_worker_run("task-1", {"run_path": "runs/source"}, context)

        self.assertIn(("output", "task-1", "[阶段] 准备启动"), events)
        self.assertIn(("output", "task-1", "正在计算"), events)
        self.assertIn(("output", "task-1", "模型输出"), events)
        self.assertIn(("metadata", "task-1", {"run_path": "runs/forward"}), events)
        self.assertIn(("detected", "task-1", ["runs/forward"]), events)
        self.assertIn(("finished", "task-1", {"ok": True, "return_code": 0, "result": {"run_path": "runs/forward"}}), events)

    def test_forward_simulation_worker_run_records_failure_after_last_stage(self) -> None:
        events: list[tuple] = []

        def run_forward_simulation(payload, *, stage_callback=None, output_callback=None):
            stage_callback("执行前向模拟", "正在计算")
            raise RuntimeError("forward failed")

        context = ForwardSimulationWorkerContext(
            run_forward_simulation=run_forward_simulation,
            set_task_metadata=lambda task_id, **kwargs: events.append(("metadata", task_id, kwargs)),
            add_task_output=lambda task_id, message: events.append(("output", task_id, message)),
            add_task_exception_output=lambda task_id, exc: events.append(("exception", task_id, str(exc))),
            mark_task_finished=lambda task_id, **kwargs: events.append(("finished", task_id, kwargs)),
            set_detected_runs=lambda task_id, runs: events.append(("detected", task_id, runs)),
        )

        forward_simulation_worker_run("task-1", {"run_path": "runs/source"}, context)

        self.assertIn(("metadata", "task-1", {"ui_progress": {"stage": "执行前向模拟", "label": "保存并重算"}}), events)
        self.assertIn(("exception", "task-1", "forward failed"), events)
        self.assertIn(("finished", "task-1", {"ok": False, "return_code": -1}), events)
        self.assertFalse(any(event[0] == "detected" for event in events))


if __name__ == "__main__":
    unittest.main()
