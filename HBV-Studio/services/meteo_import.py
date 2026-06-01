#!/usr/bin/env python
# -*- coding: utf-8 -*-
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable


@dataclass(frozen=True)
class MeteoImportStartContext:
    resolve_path: Callable[..., Path]
    read_runtime_config: Callable[[Path], dict[str, Any]]
    current_profile: Callable[[dict[str, Any]], str]
    resolve_runtime_precip_source: Callable[[dict[str, Any], Any], str]


@dataclass(frozen=True)
class MeteoImportWorkerContext:
    perform_meteo_import: Callable[..., dict[str, Any]]
    add_task_exception_output: Callable[[str, Exception], None]
    mark_task_finished: Callable[..., None]


@dataclass(frozen=True)
class MeteoImportStartPlan:
    label: str
    command: list[str]
    metadata: dict[str, Any]


def meteo_import_start_plan(payload: dict[str, Any], context: MeteoImportStartContext) -> MeteoImportStartPlan:
    config_path = context.resolve_path(str(payload.get("config_path", "")), must_exist=True)
    config = context.read_runtime_config(config_path)
    runtime_prec_source = context.resolve_runtime_precip_source(config, payload.get("prec_source", None))
    return MeteoImportStartPlan(
        label=f"气象栅格导入 | {config_path.stem}",
        command=["meteo_import"],
        metadata={
            "config_path": str(config_path.resolve()),
            "profile": context.current_profile(config),
            "runtime_prec_source": runtime_prec_source,
        },
    )


def meteo_import_worker_run(
    task_id: str,
    payload: dict[str, Any],
    context: MeteoImportWorkerContext,
) -> None:
    try:
        result = context.perform_meteo_import(payload, task_id=task_id)
        context.mark_task_finished(task_id, ok=True, return_code=0, result=result)
    except Exception as exc:
        context.add_task_exception_output(task_id, exc)
        context.mark_task_finished(task_id, ok=False, return_code=-1)
