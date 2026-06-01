#!/usr/bin/env python
# -*- coding: utf-8 -*-
from __future__ import annotations

import csv
import threading
import time
import traceback
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

DEFAULT_MAX_TASK_OUTPUT = 1200


@dataclass(frozen=True)
class TaskQueryContext:
    tasks: dict[str, Any]
    task_lock: threading.Lock
    snapshot_tasks: Callable[[], list[Any]]
    resolve_any_path: Callable[..., Path]
    task_progress_snapshot: Callable[[Any], dict[str, Any] | None]


@dataclass
class TaskRecord:
    id: str
    task_type: str
    label: str
    command: list[str]
    cwd: str
    status: str = "running"
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)
    return_code: int | None = None
    output: list[str] = field(default_factory=list)
    detected_runs: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)
    max_output_lines: int = DEFAULT_MAX_TASK_OUTPUT

    def append(self, line: str) -> None:
        text = line.rstrip("\n")
        if not text:
            return
        self.output.append(text)
        if len(self.output) > self.max_output_lines:
            self.output = self.output[-self.max_output_lines :]
        self.updated_at = time.time()

    def as_dict(
        self,
        progress_snapshot: Callable[[Any], dict[str, Any] | None] | None = None,
    ) -> dict[str, Any]:
        progress = progress_snapshot(self) if progress_snapshot else None
        return {
            "id": self.id,
            "task_type": self.task_type,
            "label": self.label,
            "command": self.command,
            "cwd": self.cwd,
            "status": self.status,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "return_code": self.return_code,
            "output": self.output[-200:],
            "detected_runs": self.detected_runs,
            "progress": progress,
            "ui_progress": self.metadata.get("ui_progress"),
            "forecast_input_check": self.metadata.get("forecast_input_check"),
            "result": self.metadata.get("result"),
            "config_path": self.metadata.get("config_path"),
            "run_path": self.metadata.get("run_path"),
            "step_id": self.metadata.get("step_id"),
            "step_title": self.metadata.get("step_title"),
            "step_titles": self.metadata.get("step_titles"),
            "profile": self.metadata.get("profile"),
            "calibration_workflow": self.metadata.get("calibration_workflow"),
            "calibration_workflow_status": self.metadata.get("calibration_workflow_status"),
            "runtime_prec_source": self.metadata.get("runtime_prec_source"),
            "objective_mode": self.metadata.get("objective_mode"),
            "glacier_mode": self.metadata.get("glacier_mode"),
            "method": self.metadata.get("method"),
            "quick_test": self.metadata.get("quick_test"),
            "mc_samples": self.metadata.get("mc_samples"),
            "maxiter": self.metadata.get("maxiter"),
            "refine_maxiter": self.metadata.get("refine_maxiter"),
        }


@dataclass(frozen=True)
class TaskCreateContext:
    tasks: dict[str, Any]
    task_lock: threading.Lock
    generate_task_id: Callable[[], str]
    create_task_record: Callable[..., Any]


@dataclass(frozen=True)
class TaskMutationContext:
    tasks: dict[str, Any]
    task_lock: threading.Lock
    now: Callable[[], float]


@dataclass(frozen=True)
class ProcessMonitorContext:
    decode_output_line: Callable[[Any], str]
    add_task_output: Callable[[str, str], None]
    get_task_context: Callable[[str], tuple[str, dict[str, Any]]]
    verify_data_prep_task_output: Callable[[dict[str, Any]], tuple[bool, str]]
    snapshot_run_paths: Callable[[], set[str]]
    pick_latest_run_path: Callable[[list[str]], str]
    build_calibration_task_result: Callable[[str], dict[str, Any] | None]
    finalize_task: Callable[[str, int, list[str], dict[str, Any] | None], None]
    mark_task_exception: Callable[[str, Exception], None]


@dataclass(frozen=True)
class ProcessTaskStartContext:
    popen: Callable[..., Any]
    subprocess_env: Callable[[], dict[str, str]]
    create_registered_task: Callable[..., Any]
    snapshot_run_paths: Callable[[], set[str]]
    start_monitor_thread: Callable[[str, Any, set[str]], None]
    stdout_pipe: Any
    stderr_stdout: Any


@dataclass(frozen=True)
class PythonScriptCommandContext:
    python_exe: str
    run_py_file_role: str
    frozen: bool


def build_python_script_command(
    script: Path | str,
    *args: Any,
    context: PythonScriptCommandContext,
) -> list[str]:
    script_path = str(script)
    tail = [str(arg) for arg in args]
    if context.frozen:
        return [context.python_exe, context.run_py_file_role, script_path, *tail]
    return [context.python_exe, script_path, *tail]


def has_running_tasks(context: TaskQueryContext) -> bool:
    with context.task_lock:
        return any(task.status == "running" for task in context.tasks.values())


def list_tasks(context: TaskQueryContext) -> list[dict[str, Any]]:
    items = [task.as_dict(context.task_progress_snapshot) for task in context.snapshot_tasks()]
    return sorted(items, key=lambda item: item["updated_at"], reverse=True)


def _safe_float(value: Any) -> float | None:
    if value in (None, "", "nan", "NaN"):
        return None
    try:
        out = float(value)
    except Exception:
        return None
    if out != out:
        return None
    return out


def _latest_progress_row(path: Path) -> dict[str, str] | None:
    try:
        with path.open("r", encoding="utf-8-sig", newline="") as handle:
            rows = list(csv.DictReader(handle))
    except Exception:
        return None
    return rows[-1] if rows else None


def _progress_history_rows(path: Path, limit: int = 160) -> list[dict[str, float | int | None]]:
    try:
        with path.open("r", encoding="utf-8-sig", newline="") as handle:
            rows = list(csv.DictReader(handle))
    except Exception:
        return []
    history: list[dict[str, float | int | None]] = []
    for row in rows[-limit:]:
        history.append(
            {
                "gen": int(float(row.get("gen", 0) or 0)),
                "nse_cal": _safe_float(row.get("nse_cal")),
                "nse_val": _safe_float(row.get("nse_val")),
                "obj": _safe_float(row.get("obj")),
                "elapsed_sec": _safe_float(row.get("elapsed_sec")),
            }
        )
    return history


def _progress_stage_name(path: Path) -> str:
    stem = path.stem.lower()
    if "refine" in stem:
        return "refine"
    if "mc" in stem:
        return "mc"
    return "global"


def _progress_stage_maxiter(task: TaskRecord, stage: str) -> int:
    if stage == "refine":
        return int(task.metadata.get("refine_maxiter", 0) or 0)
    if stage == "mc":
        return int(task.metadata.get("mc_samples", 0) or 0)
    if str(task.metadata.get("method", "")).strip().lower() == "mc_only":
        return int(task.metadata.get("mc_samples", 0) or 0)
    return int(task.metadata.get("maxiter", 0) or 0)


def task_progress_snapshot(task: TaskRecord) -> dict[str, Any] | None:
    logs_dir_raw = str(task.metadata.get("logs_dir", "")).strip()
    if task.task_type != "calibration" or not logs_dir_raw:
        return None
    logs_dir = Path(logs_dir_raw)
    if not logs_dir.exists():
        return None
    candidates = [path for path in logs_dir.glob("progress*.csv") if path.stat().st_mtime >= task.created_at - 5]
    if not candidates:
        return None
    candidate_rows: list[tuple[Path, dict[str, str]]] = []
    for candidate in candidates:
        candidate_last = _latest_progress_row(candidate)
        if candidate_last:
            candidate_rows.append((candidate, candidate_last))
    if not candidate_rows:
        return None
    latest, last_row = max(candidate_rows, key=lambda item: item[0].stat().st_mtime)
    stage = _progress_stage_name(latest)
    maxiter = _progress_stage_maxiter(task, stage)
    gen = int(float(last_row.get("gen", 0) or 0))
    elapsed_sec = float(last_row.get("elapsed_sec", 0.0) or 0.0)
    eta_sec = None
    if maxiter > 0 and gen > 0 and gen <= maxiter and elapsed_sec > 0:
        eta_sec = max(0.0, elapsed_sec / gen * (maxiter - gen))
    stage_snapshots: dict[str, Any] = {}
    for candidate, candidate_last in sorted(candidate_rows, key=lambda item: item[0].stat().st_mtime):
        candidate_stage = _progress_stage_name(candidate)
        candidate_gen = int(float(candidate_last.get("gen", 0) or 0))
        candidate_elapsed = float(candidate_last.get("elapsed_sec", 0.0) or 0.0)
        candidate_maxiter = _progress_stage_maxiter(task, candidate_stage)
        candidate_eta = None
        if candidate_maxiter > 0 and candidate_gen > 0 and candidate_gen <= candidate_maxiter and candidate_elapsed > 0:
            candidate_eta = max(0.0, candidate_elapsed / candidate_gen * (candidate_maxiter - candidate_gen))
        stage_snapshots[candidate_stage] = {
            "file": str(candidate),
            "stage": candidate_stage,
            "gen": candidate_gen,
            "maxiter": candidate_maxiter or None,
            "nse_cal": _safe_float(candidate_last.get("nse_cal")),
            "nse_val": _safe_float(candidate_last.get("nse_val")),
            "obj": _safe_float(candidate_last.get("obj")),
            "convergence": _safe_float(candidate_last.get("convergence")),
            "elapsed_sec": candidate_elapsed,
            "eta_sec": candidate_eta,
            "timestamp": candidate_last.get("timestamp"),
            "history": _progress_history_rows(candidate),
        }
    return {
        "file": str(latest),
        "stage": stage,
        "gen": gen,
        "maxiter": maxiter or None,
        "nse_cal": _safe_float(last_row.get("nse_cal")),
        "nse_val": _safe_float(last_row.get("nse_val")),
        "obj": _safe_float(last_row.get("obj")),
        "convergence": _safe_float(last_row.get("convergence")),
        "elapsed_sec": elapsed_sec,
        "eta_sec": eta_sec,
        "timestamp": last_row.get("timestamp"),
        "history": _progress_history_rows(latest),
        "stages": stage_snapshots,
    }


def find_running_task(task_type: str, config_path_raw: str, context: TaskQueryContext) -> Any | None:
    try:
        cfg_path = context.resolve_any_path(config_path_raw, must_exist=False).resolve(strict=False)
    except Exception:
        return None
    with context.task_lock:
        for task in context.tasks.values():
            if task.task_type != task_type or task.status != "running":
                continue
            task_cfg = str(task.metadata.get("config_path", "")).strip()
            if not task_cfg:
                continue
            try:
                if Path(task_cfg).resolve(strict=False) == cfg_path:
                    return task
            except Exception:
                continue
    return None


def create_registered_task(
    task_type: str,
    label: str,
    command: list[str],
    cwd: Path,
    context: TaskCreateContext,
    *,
    metadata: dict[str, Any] | None = None,
) -> Any:
    task_id = context.generate_task_id()
    record = context.create_task_record(
        id=task_id,
        task_type=task_type,
        label=label,
        command=command,
        cwd=str(cwd),
        metadata=metadata or {},
    )
    with context.task_lock:
        context.tasks[task_id] = record
    return record


def start_process_task(
    task_type: str,
    label: str,
    command: list[str],
    cwd: Path,
    context: ProcessTaskStartContext,
    *,
    metadata: dict[str, Any] | None = None,
) -> Any:
    process = context.popen(
        command,
        cwd=str(cwd),
        stdout=context.stdout_pipe,
        stderr=context.stderr_stdout,
        bufsize=0,
        env=context.subprocess_env(),
    )
    record = context.create_registered_task(task_type, label, command, cwd, metadata=metadata)
    context.start_monitor_thread(record.id, process, context.snapshot_run_paths())
    return record


def append_task_output(task_id: str, line: str, context: TaskMutationContext) -> None:
    with context.task_lock:
        task = context.tasks.get(task_id)
        if task is not None:
            task.append(line)


def append_task_exception_output(
    task_id: str,
    exc: BaseException,
    context: TaskMutationContext,
    *,
    prefix: str = "[失败]",
) -> None:
    append_task_output(task_id, f"{prefix} {exc}", context)
    trace_lines = traceback.format_exception(type(exc), exc, exc.__traceback__)
    for line in "".join(trace_lines).strip().splitlines()[-12:]:
        append_task_output(task_id, f"[诊断] {line}", context)


def update_task_metadata(task_id: str, context: TaskMutationContext, **items: Any) -> None:
    with context.task_lock:
        task = context.tasks.get(task_id)
        if task is None:
            return
        task.metadata.update(items)
        task.updated_at = context.now()


def mark_task_finished(
    task_id: str,
    context: TaskMutationContext,
    *,
    ok: bool,
    return_code: int,
    result: dict[str, Any] | None = None,
) -> None:
    with context.task_lock:
        task = context.tasks.get(task_id)
        if task is None:
            return
        task.status = "completed" if ok else "failed"
        task.return_code = return_code
        if result is not None:
            task.metadata["result"] = result
        task.updated_at = context.now()


def set_task_detected_runs(task_id: str, detected_runs: list[str], context: TaskMutationContext) -> None:
    with context.task_lock:
        task = context.tasks.get(task_id)
        if task is not None:
            task.detected_runs = detected_runs


def monitor_process_task(
    task_id: str,
    process: Any,
    previous_runs: set[str],
    context: ProcessMonitorContext,
) -> None:
    try:
        if process.stdout is not None:
            for raw_line in process.stdout:
                context.add_task_output(task_id, context.decode_output_line(raw_line))
        return_code = process.wait()
        task_type = ""
        if return_code == 0:
            task_type, task_metadata = context.get_task_context(task_id)
            if task_type == "data_prep":
                output_ok, output_message = context.verify_data_prep_task_output(task_metadata)
                if not output_ok:
                    context.add_task_output(task_id, f"[失败] 产物检查未通过：{output_message}")
                    return_code = 1
        detected_runs = sorted(context.snapshot_run_paths() - previous_runs) if return_code == 0 else []
        latest_run_path = context.pick_latest_run_path(detected_runs)
        calibration_result = None
        if return_code == 0 and task_type == "calibration" and latest_run_path:
            calibration_result = context.build_calibration_task_result(latest_run_path)
        context.finalize_task(task_id, return_code, detected_runs, calibration_result)
    except Exception as exc:
        context.mark_task_exception(task_id, exc)
