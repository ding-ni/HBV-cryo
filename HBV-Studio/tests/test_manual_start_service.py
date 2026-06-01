from __future__ import annotations

import sys
import unittest
from pathlib import Path


STUDIO_DIR = Path(__file__).resolve().parents[1]
if str(STUDIO_DIR) not in sys.path:
    sys.path.insert(0, str(STUDIO_DIR))

from services.manual_start import (  # noqa: E402
    ManualStartStartContext,
    ManualStartWorkerContext,
    manual_start_start_plan,
    manual_start_worker_run,
)


class ManualStartServiceTests(unittest.TestCase):
    def test_manual_start_start_plan_builds_task_metadata(self) -> None:
        forward_context = {
            "config": {"流域名称": "沱沱河"},
            "profile": "daily",
            "prec_source": "era5",
            "objective_mode": "nse",
            "glacier_mode": "formal",
        }
        context = ManualStartStartContext(
            build_workspace_forward_context=lambda payload: forward_context,
        )

        plan = manual_start_start_plan({"config_path": "original.json"}, Path("workspace.json"), context)

        self.assertEqual(plan.label, "手调起点 | 沱沱河")
        self.assertEqual(plan.command, ["manual_start"])
        self.assertEqual(plan.metadata["config_path"], str(Path("workspace.json").resolve()))
        self.assertEqual(plan.metadata["profile"], "daily")
        self.assertEqual(plan.metadata["runtime_prec_source"], "era5")
        self.assertEqual(plan.metadata["objective_mode"], "nse")
        self.assertEqual(plan.metadata["glacier_mode"], "formal")
        self.assertEqual(plan.metadata["ui_progress"], {"stage": "准备启动", "label": "手调起点"})

    def test_manual_start_start_plan_uses_config_stem_when_basin_name_blank(self) -> None:
        forward_context = {
            "config": {"流域名称": "  "},
            "profile": "hourly",
            "prec_source": "cmfd",
            "objective_mode": "auto",
            "glacier_mode": "diagnostic",
        }
        context = ManualStartStartContext(
            build_workspace_forward_context=lambda payload: forward_context,
        )

        plan = manual_start_start_plan({}, Path("workspace.json"), context)

        self.assertEqual(plan.label, "手调起点 | workspace")
        self.assertEqual(plan.metadata["profile"], "hourly")
        self.assertEqual(plan.metadata["runtime_prec_source"], "cmfd")

    def test_manual_start_start_plan_overrides_payload_config_path_for_context(self) -> None:
        seen_payloads: list[dict[str, object]] = []

        def build_context(payload: dict[str, object]) -> dict[str, object]:
            seen_payloads.append(payload)
            return {
                "config": {},
                "profile": "daily",
                "prec_source": "era5",
                "objective_mode": "auto",
                "glacier_mode": "auto",
            }

        context = ManualStartStartContext(build_workspace_forward_context=build_context)
        manual_start_start_plan({"config_path": "stale.json", "other": 1}, Path("workspace.json"), context)

        self.assertEqual(seen_payloads, [{"config_path": "workspace.json", "other": 1}])

    def test_manual_start_worker_run_records_success_outputs_and_detected_run(self) -> None:
        events: list[tuple] = []

        def create_manual_start_result(payload, *, stage_callback=None, output_callback=None):
            events.append(("payload", payload))
            stage_callback("写出手调起点结果", "正在写出")
            output_callback("模型输出")
            return {"run_path": "runs/manual"}

        context = ManualStartWorkerContext(
            create_manual_start_result=create_manual_start_result,
            set_task_metadata=lambda task_id, **kwargs: events.append(("metadata", task_id, kwargs)),
            add_task_output=lambda task_id, message: events.append(("output", task_id, message)),
            add_task_exception_output=lambda task_id, exc: events.append(("exception", task_id, str(exc))),
            mark_task_finished=lambda task_id, **kwargs: events.append(("finished", task_id, kwargs)),
            set_detected_runs=lambda task_id, runs: events.append(("detected", task_id, runs)),
        )

        manual_start_worker_run("task-1", {"config_path": "workspace.json"}, context)

        self.assertIn(("output", "task-1", "[阶段] 准备生成手调起点"), events)
        self.assertIn(("output", "task-1", "正在写出"), events)
        self.assertIn(("output", "task-1", "模型输出"), events)
        self.assertIn(("metadata", "task-1", {"run_path": "runs/manual"}), events)
        self.assertIn(("detected", "task-1", ["runs/manual"]), events)
        self.assertIn(("finished", "task-1", {"ok": True, "return_code": 0, "result": {"run_path": "runs/manual"}}), events)

    def test_manual_start_worker_run_records_failure_after_last_stage(self) -> None:
        events: list[tuple] = []

        def create_manual_start_result(payload, *, stage_callback=None, output_callback=None):
            stage_callback("写出手调起点结果", "正在写出")
            raise RuntimeError("manual failed")

        context = ManualStartWorkerContext(
            create_manual_start_result=create_manual_start_result,
            set_task_metadata=lambda task_id, **kwargs: events.append(("metadata", task_id, kwargs)),
            add_task_output=lambda task_id, message: events.append(("output", task_id, message)),
            add_task_exception_output=lambda task_id, exc: events.append(("exception", task_id, str(exc))),
            mark_task_finished=lambda task_id, **kwargs: events.append(("finished", task_id, kwargs)),
            set_detected_runs=lambda task_id, runs: events.append(("detected", task_id, runs)),
        )

        manual_start_worker_run("task-1", {"config_path": "workspace.json"}, context)

        self.assertIn(("metadata", "task-1", {"ui_progress": {"stage": "写出手调起点结果", "label": "手调起点"}}), events)
        self.assertIn(("exception", "task-1", "manual failed"), events)
        self.assertIn(("finished", "task-1", {"ok": False, "return_code": -1}), events)
        self.assertFalse(any(event[0] == "detected" for event in events))


if __name__ == "__main__":
    unittest.main()
