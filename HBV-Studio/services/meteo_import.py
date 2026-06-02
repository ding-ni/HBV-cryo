#!/usr/bin/env python
# -*- coding: utf-8 -*-
from __future__ import annotations

import shutil
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

import pandas as pd

from services.time_utils import parse_time_from_name


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


def ordered_tif_files_by_timestamp(directory: Path) -> list[tuple[pd.Timestamp, Path]]:
    ordered: list[tuple[pd.Timestamp, Path]] = []
    for tif_path in directory.glob("*.tif"):
        timestamp = parse_time_from_name(tif_path.name)
        if timestamp is not None:
            ordered.append((timestamp, tif_path))
    ordered.sort(key=lambda item: (item[0], item[1].name))
    return ordered


def replace_directory_from_stage(target_dir: Path, stage_dir: Path) -> None:
    backup_dir = target_dir.parent / f".{target_dir.name}__backup_{uuid.uuid4().hex[:8]}"
    had_target = target_dir.exists()
    try:
        if had_target:
            target_dir.replace(backup_dir)
        stage_dir.replace(target_dir)
        if backup_dir.exists():
            shutil.rmtree(backup_dir)
    except Exception:
        if target_dir.exists() and not had_target:
            shutil.rmtree(target_dir)
        if backup_dir.exists() and not target_dir.exists():
            backup_dir.replace(target_dir)
        raise


def should_report_file_progress(index: int, total: int) -> bool:
    if total <= 20:
        return True
    step = max(1, total // 10)
    return index == 1 or index == total or index % step == 0
