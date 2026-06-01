#!/usr/bin/env python
# -*- coding: utf-8 -*-
from __future__ import annotations

import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable


@dataclass(frozen=True)
class TaskQueryContext:
    tasks: dict[str, Any]
    task_lock: threading.Lock
    snapshot_tasks: Callable[[], list[Any]]
    resolve_any_path: Callable[..., Path]


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


def has_running_tasks(context: TaskQueryContext) -> bool:
    with context.task_lock:
        return any(task.status == "running" for task in context.tasks.values())


def list_tasks(context: TaskQueryContext) -> list[dict[str, Any]]:
    items = [task.as_dict() for task in context.snapshot_tasks()]
    return sorted(items, key=lambda item: item["updated_at"], reverse=True)


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
