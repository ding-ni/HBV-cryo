from __future__ import annotations

import sys
import unittest
from pathlib import Path


STUDIO_DIR = Path(__file__).resolve().parents[1]
if str(STUDIO_DIR) not in sys.path:
    sys.path.insert(0, str(STUDIO_DIR))

from services.tasks import ProcessMonitorContext, monitor_process_task  # noqa: E402


class TaskServiceTests(unittest.TestCase):
    def _context(
        self,
        *,
        events: list[tuple],
        task_type: str = "",
        task_metadata: dict[str, object] | None = None,
        verify_result: tuple[bool, str] = (True, "ok"),
        current_runs: set[str] | None = None,
        latest_run: str = "",
        calibration_result: dict[str, object] | None = None,
        decode_output_line=None,
    ) -> ProcessMonitorContext:
        return ProcessMonitorContext(
            decode_output_line=decode_output_line
            or (lambda raw: raw.decode("utf-8").rstrip("\r\n") if isinstance(raw, bytes) else str(raw)),
            add_task_output=lambda task_id, message: events.append(("output", task_id, message)),
            get_task_context=lambda task_id: (task_type, dict(task_metadata or {})),
            verify_data_prep_task_output=lambda metadata: verify_result,
            snapshot_run_paths=lambda: set(current_runs or set()),
            pick_latest_run_path=lambda runs: events.append(("pick", runs)) or latest_run,
            build_calibration_task_result=lambda run_path: events.append(("calibration", run_path)) or calibration_result,
            finalize_task=lambda task_id, return_code, detected_runs, result: events.append(
                ("finalize", task_id, return_code, detected_runs, result)
            ),
            mark_task_exception=lambda task_id, exc: events.append(("exception", task_id, str(exc))),
        )

    def test_monitor_process_task_records_calibration_result_for_new_run(self) -> None:
        events: list[tuple] = []

        class FakeProcess:
            stdout = [b"hello\n"]

            def wait(self) -> int:
                return 0

        context = self._context(
            events=events,
            task_type="calibration",
            current_runs={"runs/old", "runs/new-b", "runs/new-a"},
            latest_run="runs/new-b",
            calibration_result={"run_path": "runs/new-b", "nse": 0.8},
        )

        monitor_process_task("task-1", FakeProcess(), {"runs/old"}, context)

        self.assertIn(("output", "task-1", "hello"), events)
        self.assertIn(("pick", ["runs/new-a", "runs/new-b"]), events)
        self.assertIn(("calibration", "runs/new-b"), events)
        self.assertIn(
            ("finalize", "task-1", 0, ["runs/new-a", "runs/new-b"], {"run_path": "runs/new-b", "nse": 0.8}),
            events,
        )

    def test_monitor_process_task_marks_data_prep_failed_when_output_check_fails(self) -> None:
        events: list[tuple] = []

        class FakeProcess:
            stdout: list[bytes] = []

            def wait(self) -> int:
                return 0

        context = self._context(
            events=events,
            task_type="data_prep",
            task_metadata={"step_id": "meteo"},
            verify_result=(False, "缺少降水文件"),
            current_runs={"runs/new"},
        )

        monitor_process_task("task-1", FakeProcess(), set(), context)

        self.assertIn(("output", "task-1", "[失败] 产物检查未通过：缺少降水文件"), events)
        self.assertIn(("pick", []), events)
        self.assertIn(("finalize", "task-1", 1, [], None), events)
        self.assertFalse(any(event[0] == "calibration" for event in events))

    def test_monitor_process_task_preserves_nonzero_return_code(self) -> None:
        events: list[tuple] = []

        class FakeProcess:
            stdout: list[bytes] = []

            def wait(self) -> int:
                return 2

        monitor_process_task("task-1", FakeProcess(), set(), self._context(events=events, current_runs={"runs/new"}))

        self.assertIn(("pick", []), events)
        self.assertIn(("finalize", "task-1", 2, [], None), events)

    def test_monitor_process_task_marks_exception_when_output_decode_fails(self) -> None:
        events: list[tuple] = []

        class FakeProcess:
            stdout = [b"bad\n"]

            def wait(self) -> int:
                return 0

        context = self._context(
            events=events,
            decode_output_line=lambda raw: (_ for _ in ()).throw(RuntimeError("decode failed")),
        )

        monitor_process_task("task-1", FakeProcess(), set(), context)

        self.assertIn(("exception", "task-1", "decode failed"), events)
        self.assertFalse(any(event[0] == "finalize" for event in events))


if __name__ == "__main__":
    unittest.main()
