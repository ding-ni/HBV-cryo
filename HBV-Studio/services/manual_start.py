#!/usr/bin/env python
# -*- coding: utf-8 -*-
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable


@dataclass(frozen=True)
class ManualStartStartContext:
    build_workspace_forward_context: Callable[[dict[str, Any]], dict[str, Any]]


@dataclass(frozen=True)
class ManualStartWorkerContext:
    create_manual_start_result: Callable[..., dict[str, Any]]
    set_task_metadata: Callable[..., None]
    add_task_output: Callable[[str, str], None]
    add_task_exception_output: Callable[[str, Exception], None]
    mark_task_finished: Callable[..., None]
    set_detected_runs: Callable[[str, list[str]], None]


@dataclass(frozen=True)
class ManualStartStartPlan:
    label: str
    command: list[str]
    metadata: dict[str, Any]


def manual_start_start_plan(
    payload: dict[str, Any],
    config_path: Path,
    context: ManualStartStartContext,
) -> ManualStartStartPlan:
    forward_context = context.build_workspace_forward_context({**payload, "config_path": str(config_path)})
    config = dict(forward_context["config"])
    basin_name = str(config.get("流域名称", config_path.stem)).strip() or config_path.stem
    return ManualStartStartPlan(
        label=f"手调起点 | {basin_name}",
        command=["manual_start"],
        metadata={
            "config_path": str(config_path.resolve()),
            "profile": forward_context["profile"],
            "runtime_prec_source": forward_context["prec_source"],
            "objective_mode": forward_context["objective_mode"],
            "glacier_mode": forward_context["glacier_mode"],
            "ui_progress": {"stage": "准备启动", "label": "手调起点"},
        },
    )


def manual_start_worker_run(
    task_id: str,
    payload: dict[str, Any],
    context: ManualStartWorkerContext,
) -> None:
    last_stage = ""

    def report(stage: str, message: str | None = None) -> None:
        nonlocal last_stage
        last_stage = stage
        context.set_task_metadata(task_id, ui_progress={"stage": stage, "label": "手调起点"})
        if message:
            context.add_task_output(task_id, message)

    try:
        report("准备启动", "[阶段] 准备生成手调起点")
        result = context.create_manual_start_result(
            payload,
            stage_callback=report,
            output_callback=lambda line: context.add_task_output(task_id, line),
        )
        context.set_task_metadata(task_id, run_path=result["run_path"])
        context.set_detected_runs(task_id, [result["run_path"]])
        context.mark_task_finished(task_id, ok=True, return_code=0, result=result)
    except Exception as exc:
        if last_stage:
            context.set_task_metadata(task_id, ui_progress={"stage": last_stage, "label": "手调起点"})
        context.add_task_exception_output(task_id, exc)
        context.mark_task_finished(task_id, ok=False, return_code=-1)
