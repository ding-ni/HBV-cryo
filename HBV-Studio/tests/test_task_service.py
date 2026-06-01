from __future__ import annotations

import contextlib
import io
import os
import sys
import tempfile
import threading
import unittest
from pathlib import Path


STUDIO_DIR = Path(__file__).resolve().parents[1]
if str(STUDIO_DIR) not in sys.path:
    sys.path.insert(0, str(STUDIO_DIR))

from services.tasks import (  # noqa: E402
    ProcessMonitorContext,
    ProcessTaskStartContext,
    PythonScriptCommandContext,
    TaskCreateContext,
    TaskMutationContext,
    TaskQueryContext,
    TaskRecord,
    append_task_exception_output,
    append_task_output,
    build_python_script_command,
    call_with_output_capture,
    create_registered_task,
    list_tasks,
    mark_task_finished,
    monitor_process_task,
    set_task_detected_runs,
    start_process_task,
    task_progress_snapshot,
    update_task_metadata,
)


class FakeTask:
    def __init__(self) -> None:
        self.output: list[str] = []
        self.metadata: dict[str, object] = {}
        self.updated_at = 0.0
        self.status = "running"
        self.return_code: int | None = None
        self.detected_runs: list[str] = []

    def append(self, line: str) -> None:
        self.output.append(line)


class FakeRecord:
    def __init__(self, **kwargs) -> None:
        self.__dict__.update(kwargs)


class TaskServiceTests(unittest.TestCase):
    def _create_context(self, tasks: dict[str, FakeRecord]) -> TaskCreateContext:
        return TaskCreateContext(
            tasks=tasks,
            task_lock=threading.Lock(),
            generate_task_id=lambda: "task-1",
            create_task_record=lambda **kwargs: FakeRecord(**kwargs),
        )

    def _mutation_context(self, tasks: dict[str, FakeTask], *, now: float = 123.0) -> TaskMutationContext:
        return TaskMutationContext(
            tasks=tasks,
            task_lock=threading.Lock(),
            now=lambda: now,
        )

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

    def test_create_registered_task_builds_and_stores_record(self) -> None:
        tasks: dict[str, FakeRecord] = {}
        metadata = {"ui_progress": {"stage": "准备"}}

        record = create_registered_task(
            "forward_sim",
            "保存并重算",
            ["forward_sim"],
            Path("project-root"),
            self._create_context(tasks),
            metadata=metadata,
        )

        self.assertIs(tasks["task-1"], record)
        self.assertEqual(record.id, "task-1")
        self.assertEqual(record.task_type, "forward_sim")
        self.assertEqual(record.label, "保存并重算")
        self.assertEqual(record.command, ["forward_sim"])
        self.assertEqual(record.cwd, "project-root")
        self.assertIs(record.metadata, metadata)

    def test_create_registered_task_defaults_metadata(self) -> None:
        tasks: dict[str, FakeRecord] = {}

        record = create_registered_task("sync", "同步", ["sync"], Path("project-root"), self._create_context(tasks))

        self.assertEqual(record.metadata, {})
        self.assertIs(tasks["task-1"], record)

    def test_task_record_append_trims_output_and_as_dict_uses_progress_callback(self) -> None:
        task = TaskRecord(
            id="task-1",
            task_type="calibration",
            label="Calibration",
            command=["calibrate"],
            cwd="project-root",
            metadata={
                "ui_progress": {"stage": "running"},
                "config_path": "workspace.json",
                "method": "de",
                "maxiter": 20,
            },
            max_output_lines=3,
        )

        task.append("line-1\n")
        task.append("")
        task.append("line-2")
        task.append("line-3")
        task.append("line-4")
        payload = task.as_dict(lambda current: {"task_id": current.id, "gen": 2})

        self.assertEqual(task.output, ["line-2", "line-3", "line-4"])
        self.assertEqual(payload["id"], "task-1")
        self.assertEqual(payload["task_type"], "calibration")
        self.assertEqual(payload["output"], ["line-2", "line-3", "line-4"])
        self.assertEqual(payload["progress"], {"task_id": "task-1", "gen": 2})
        self.assertEqual(payload["ui_progress"], {"stage": "running"})
        self.assertEqual(payload["config_path"], "workspace.json")
        self.assertEqual(payload["method"], "de")
        self.assertEqual(payload["maxiter"], 20)

    def test_list_tasks_sorts_snapshots_and_injects_progress_snapshot(self) -> None:
        older = TaskRecord(
            id="older",
            task_type="sync",
            label="Older",
            command=["sync"],
            cwd="root",
            updated_at=1.0,
        )
        newer = TaskRecord(
            id="newer",
            task_type="calibration",
            label="Newer",
            command=["calibrate"],
            cwd="root",
            updated_at=2.0,
        )
        context = TaskQueryContext(
            tasks={older.id: older, newer.id: newer},
            task_lock=threading.Lock(),
            snapshot_tasks=lambda: [older, newer],
            resolve_any_path=lambda value, **kwargs: Path(value),
            task_progress_snapshot=lambda task: {"id": task.id} if task.task_type == "calibration" else None,
        )

        payload = list_tasks(context)

        self.assertEqual([item["id"] for item in payload], ["newer", "older"])
        self.assertEqual(payload[0]["progress"], {"id": "newer"})
        self.assertIsNone(payload[1]["progress"])

    def test_task_progress_snapshot_reads_latest_stage_and_history(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            logs_dir = Path(tmp)
            mc_file = logs_dir / "progress_mc.csv"
            refine_file = logs_dir / "progress_refine.csv"
            mc_file.write_text(
                "gen,nse_cal,nse_val,obj,convergence,elapsed_sec,timestamp\n"
                "1,0.30,0.20,5.0,0.9,10,t1\n"
                "2,0.40,0.30,4.0,0.8,20,t2\n",
                encoding="utf-8",
            )
            refine_file.write_text(
                "gen,nse_cal,nse_val,obj,convergence,elapsed_sec,timestamp\n"
                "3,0.70,0.60,2.0,0.3,30,t3\n",
                encoding="utf-8",
            )
            os.utime(mc_file, (100.0, 100.0))
            os.utime(refine_file, (110.0, 110.0))
            task = TaskRecord(
                id="task-1",
                task_type="calibration",
                label="Calibration",
                command=["calibrate"],
                cwd="root",
                created_at=0.0,
                metadata={
                    "logs_dir": str(logs_dir),
                    "mc_samples": 10,
                    "maxiter": 20,
                    "refine_maxiter": 5,
                },
            )

            payload = task_progress_snapshot(task)

        self.assertIsNotNone(payload)
        assert payload is not None
        self.assertEqual(payload["stage"], "refine")
        self.assertEqual(payload["gen"], 3)
        self.assertEqual(payload["maxiter"], 5)
        self.assertEqual(payload["nse_cal"], 0.70)
        self.assertEqual(payload["eta_sec"], 20.0)
        self.assertEqual(payload["history"], [{"gen": 3, "nse_cal": 0.70, "nse_val": 0.60, "obj": 2.0, "elapsed_sec": 30.0}])
        self.assertEqual(payload["stages"]["mc"]["stage"], "mc")
        self.assertEqual(payload["stages"]["mc"]["maxiter"], 10)
        self.assertEqual(payload["stages"]["mc"]["history"][-1]["gen"], 2)
        self.assertEqual(payload["stages"]["refine"]["timestamp"], "t3")

    def test_task_progress_snapshot_ignores_non_calibration_tasks(self) -> None:
        task = TaskRecord(
            id="task-1",
            task_type="sync",
            label="Sync",
            command=["sync"],
            cwd="root",
            metadata={"logs_dir": "missing"},
        )

        self.assertIsNone(task_progress_snapshot(task))

    def test_call_with_output_capture_relays_stdout_stderr_and_partial_lines(self) -> None:
        events: list[str] = []

        def emit_output(left: int, right: int) -> int:
            print("stdout line")
            print("stderr line", file=sys.stderr)
            print("partial", end="")
            return left + right

        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            result = call_with_output_capture(events.append, emit_output, 2, 3)

        self.assertEqual(result, 5)
        self.assertEqual(events, ["stdout line", "stderr line", "partial"])

    def test_call_with_output_capture_flushes_partial_output_on_exception(self) -> None:
        events: list[str] = []

        def fail_after_partial_output() -> None:
            print("before failure", end="")
            raise RuntimeError("boom")

        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            with self.assertRaisesRegex(RuntimeError, "boom"):
                call_with_output_capture(events.append, fail_after_partial_output)

        self.assertEqual(events, ["before failure"])

    def test_call_with_output_capture_skips_relay_when_callback_is_none(self) -> None:
        result = call_with_output_capture(None, lambda value: value + 1, 4)

        self.assertEqual(result, 5)

    def test_build_python_script_command_uses_script_path_when_not_frozen(self) -> None:
        command = build_python_script_command(
            Path("scripts") / "run.py",
            "--count",
            3,
            context=PythonScriptCommandContext(
                python_exe="python.exe",
                run_py_file_role="__run_py_file__",
                frozen=False,
            ),
        )

        self.assertEqual(command, ["python.exe", str(Path("scripts") / "run.py"), "--count", "3"])

    def test_build_python_script_command_uses_bootstrap_role_when_frozen(self) -> None:
        command = build_python_script_command(
            "scripts/run.py",
            "--flag",
            context=PythonScriptCommandContext(
                python_exe="HBVStudio.exe",
                run_py_file_role="__run_py_file__",
                frozen=True,
            ),
        )

        self.assertEqual(command, ["HBVStudio.exe", "__run_py_file__", "scripts/run.py", "--flag"])

    def test_start_process_task_launches_registers_and_starts_monitor(self) -> None:
        events: list[tuple] = []
        process = object()
        metadata = {"step_id": "calibration"}

        def subprocess_env() -> dict[str, str]:
            events.append(("env",))
            return {"PYTHONUNBUFFERED": "1"}

        def popen(command, **kwargs):
            events.append(("popen", command, kwargs))
            return process

        def create_task(task_type, label, command, cwd, *, metadata=None):
            events.append(("register", task_type, label, command, cwd, metadata))
            return FakeRecord(id="task-42")

        context = ProcessTaskStartContext(
            popen=popen,
            subprocess_env=subprocess_env,
            create_registered_task=create_task,
            snapshot_run_paths=lambda: events.append(("snapshot",)) or {"runs/old"},
            start_monitor_thread=lambda task_id, process_arg, previous_runs: events.append(
                ("monitor", task_id, process_arg, previous_runs)
            ),
            stdout_pipe="PIPE",
            stderr_stdout="STDOUT",
        )

        record = start_process_task(
            "calibration",
            "Calibration",
            ["python", "runner.py"],
            Path("project-root"),
            context,
            metadata=metadata,
        )

        self.assertEqual(record.id, "task-42")
        self.assertEqual(events[0], ("env",))
        self.assertEqual(events[1][0], "popen")
        self.assertEqual(events[1][1], ["python", "runner.py"])
        self.assertEqual(
            events[1][2],
            {
                "cwd": "project-root",
                "stdout": "PIPE",
                "stderr": "STDOUT",
                "bufsize": 0,
                "env": {"PYTHONUNBUFFERED": "1"},
            },
        )
        self.assertEqual(
            events[2],
            ("register", "calibration", "Calibration", ["python", "runner.py"], Path("project-root"), metadata),
        )
        self.assertEqual(events[3], ("snapshot",))
        self.assertEqual(events[4], ("monitor", "task-42", process, {"runs/old"}))

    def test_start_process_task_propagates_popen_failure_without_registration(self) -> None:
        events: list[tuple] = []

        def subprocess_env() -> dict[str, str]:
            events.append(("env",))
            return {}

        def popen(command, **kwargs):
            events.append(("popen", command, kwargs))
            raise RuntimeError("launch failed")

        context = ProcessTaskStartContext(
            popen=popen,
            subprocess_env=subprocess_env,
            create_registered_task=lambda *args, **kwargs: events.append(("register", args, kwargs)),
            snapshot_run_paths=lambda: events.append(("snapshot",)) or set(),
            start_monitor_thread=lambda *args: events.append(("monitor", args)),
            stdout_pipe="PIPE",
            stderr_stdout="STDOUT",
        )

        with self.assertRaisesRegex(RuntimeError, "launch failed"):
            start_process_task("sync", "Sync", ["sync"], Path("project-root"), context)

        self.assertEqual([event[0] for event in events], ["env", "popen"])

    def test_task_mutation_helpers_update_task_state(self) -> None:
        task = FakeTask()
        context = self._mutation_context({"task-1": task}, now=456.0)

        append_task_output("task-1", "line", context)
        update_task_metadata("task-1", context, ui_progress={"stage": "运行中"})
        set_task_detected_runs("task-1", ["runs/a"], context)
        mark_task_finished("task-1", context, ok=True, return_code=0, result={"run_path": "runs/a"})

        self.assertEqual(task.output, ["line"])
        self.assertEqual(task.metadata["ui_progress"], {"stage": "运行中"})
        self.assertEqual(task.metadata["result"], {"run_path": "runs/a"})
        self.assertEqual(task.detected_runs, ["runs/a"])
        self.assertEqual(task.status, "completed")
        self.assertEqual(task.return_code, 0)
        self.assertEqual(task.updated_at, 456.0)

    def test_task_mutation_helpers_ignore_missing_task(self) -> None:
        context = self._mutation_context({})

        append_task_output("missing", "line", context)
        update_task_metadata("missing", context, value=1)
        set_task_detected_runs("missing", ["runs/a"], context)
        mark_task_finished("missing", context, ok=False, return_code=-1)

        self.assertEqual(context.tasks, {})

    def test_append_task_exception_output_adds_prefix_and_diagnostics(self) -> None:
        task = FakeTask()
        context = self._mutation_context({"task-1": task})

        try:
            raise RuntimeError("boom")
        except RuntimeError as exc:
            append_task_exception_output("task-1", exc, context, prefix="[错误]")

        self.assertEqual(task.output[0], "[错误] boom")
        self.assertTrue(any(line.startswith("[诊断]") and "RuntimeError: boom" in line for line in task.output))

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
