#!/usr/bin/env python
# -*- coding: utf-8 -*-
from __future__ import annotations

import hashlib
import shutil
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

import pandas as pd

from services.time_utils import parse_time_from_name


DAILY_FORCING_MANIFEST_SCHEMA = "hbv_cryo_daily_forcing_manifest_v1"
DAILY_PRECIP_UNITS = ("mm/day", "m/day")
DEFAULT_DAILY_PRECIP_UNIT = "mm/day"
DEFAULT_DAILY_PRECIP_DAY_BASIS = "product_calendar_day"
DAILY_PRECIP_DAY_BASES = (
    "product_calendar_day",
    "beijing_calendar_day",
    "hydrological_day_08",
)


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


def meteo_import_resampling_name(role: str) -> str:
    """Use area averaging for precipitation depth and bilinear interpolation for state-like fields."""
    return "average" if str(role or "").strip() == "prec_dir" else "bilinear"


def validate_precipitation_import_metadata(
    payload: dict[str, Any],
    *,
    time_step_hours: float,
) -> dict[str, Any]:
    if abs(float(time_step_hours) - 24.0) > 1e-9:
        return {
            "required": False,
            "input_unit": str(payload.get("precip_unit", "") or "").strip().lower(),
            "day_basis": str(payload.get("precip_day_basis", "") or "").strip(),
            "scale_to_mm": 1.0,
        }
    unit = str(payload.get("precip_unit", "") or DEFAULT_DAILY_PRECIP_UNIT).strip().lower()
    day_basis = str(
        payload.get("precip_day_basis", "") or DEFAULT_DAILY_PRECIP_DAY_BASIS
    ).strip()
    if unit not in DAILY_PRECIP_UNITS:
        raise ValueError(f"日尺度降水单位无效，可选值：{', '.join(DAILY_PRECIP_UNITS)}。")
    if day_basis not in DAILY_PRECIP_DAY_BASES:
        raise ValueError(f"日尺度降水日期口径无效，可选值：{', '.join(DAILY_PRECIP_DAY_BASES)}。")
    return {
        "required": True,
        "input_unit": unit,
        "day_basis": day_basis,
        "scale_to_mm": 1000.0 if unit == "m/day" else 1.0,
    }


def tif_series_digest(records: list[tuple[pd.Timestamp, Path]]) -> dict[str, Any]:
    aggregate = hashlib.sha256()
    total_bytes = 0
    for timestamp, path in records:
        file_hash = hashlib.sha256()
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                file_hash.update(chunk)
        size = int(path.stat().st_size)
        total_bytes += size
        token = (
            f"{pd.Timestamp(timestamp).isoformat()}\0{path.name}\0{size}\0{file_hash.hexdigest()}\n"
        ).encode("utf-8")
        aggregate.update(token)
    return {
        "algorithm": "sha256(file_content)+sha256(ordered_series)",
        "series_sha256": aggregate.hexdigest(),
        "file_count": int(len(records)),
        "total_bytes": int(total_bytes),
    }
