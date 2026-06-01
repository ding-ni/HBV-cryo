#!/usr/bin/env python
# -*- coding: utf-8 -*-
from __future__ import annotations

import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable


@dataclass(frozen=True)
class RunListContext:
    discover_run_entries: Callable[[], list[tuple[tuple[Any, ...], Path]]]
    summarize_run: Callable[[Path], dict[str, Any]]


@dataclass(frozen=True)
class RunDetailContext:
    resolve_path: Callable[..., Path]
    read_json_file: Callable[[Path], dict[str, Any]]
    normalize_run_metadata: Callable[..., tuple[dict[str, Any], Path | None]]
    run_update_timestamps: Callable[[Path], tuple[float, int]]
    read_sampled_csv_rows: Callable[[Path], tuple[list[dict[str, str]], int]]
    safe_float: Callable[[Any], float | None]
    build_hydrology_summary: Callable[[dict[str, Any], Path], dict[str, Any]]
    ensure_hydrology_diagnostic_report: Callable[[Path, dict[str, Any], dict[str, Any]], dict[str, Any]]
    build_run_summary: Callable[..., dict[str, Any]]
    is_studio_editable_metadata: Callable[[dict[str, Any], Path | None], bool]


_RUN_LIST_CACHE_LOCK = threading.Lock()
_RUN_LIST_CACHE_SIGNATURE: tuple[tuple[Any, ...], ...] | None = None
_RUN_LIST_CACHE_ITEMS: list[dict[str, Any]] = []


def list_runs(context: RunListContext) -> list[dict[str, Any]]:
    global _RUN_LIST_CACHE_SIGNATURE, _RUN_LIST_CACHE_ITEMS
    entries = context.discover_run_entries()
    signature = tuple(item[0] for item in entries)
    with _RUN_LIST_CACHE_LOCK:
        if signature == _RUN_LIST_CACHE_SIGNATURE:
            return [dict(item) for item in _RUN_LIST_CACHE_ITEMS]

    items = sorted(
        [context.summarize_run(path) for _, path in entries],
        key=lambda item: item["updated_at"],
        reverse=True,
    )
    with _RUN_LIST_CACHE_LOCK:
        _RUN_LIST_CACHE_SIGNATURE = signature
        _RUN_LIST_CACHE_ITEMS = [dict(item) for item in items]
    return items


def load_run_detail(run_path: str, context: RunDetailContext) -> dict[str, Any]:
    run_dir = context.resolve_path(run_path, must_exist=True)
    simulation_path = run_dir / "simulation.csv"
    metadata_path = run_dir / "metadata.json"
    if not simulation_path.exists() or not metadata_path.exists():
        raise FileNotFoundError("结果目录缺少 simulation.csv 或 metadata.json。")
    metadata, resolved_config = context.normalize_run_metadata(context.read_json_file(metadata_path), run_path=run_dir)
    updated_at, updated_at_ns = context.run_update_timestamps(run_dir)
    sampled, total_rows = context.read_sampled_csv_rows(simulation_path)
    fields = [
        "q_sim",
        "q_sim_model",
        "q_boundary_inflow",
        "q_obs",
        "q_rain",
        "q_snow",
        "q_ice",
        "q_ice_raw",
        "q_ice_reference",
        "q_ice_reference_raw",
    ]
    series = {field: [] for field in fields}
    dates: list[str] = []
    residuals: list[float | None] = []
    for row in sampled:
        dates.append(row.get("date", ""))
        q_sim = context.safe_float(row.get("q_sim"))
        q_obs = context.safe_float(row.get("q_obs"))
        residuals.append((q_sim - q_obs) if (q_sim is not None and q_obs is not None) else None)
        for field in fields:
            series[field].append(context.safe_float(row.get(field)))
    time_cfg = dict(metadata.get("time_config", {}) or {})
    actual_start = dates[0] if dates else ""
    actual_end = dates[-1] if dates else ""
    warmup_start = str(time_cfg.get("warmup_start", "") or "")
    warmup_covered = bool(actual_start and (not warmup_start or str(actual_start).strip() == warmup_start.strip()))
    hydrology_summary = context.ensure_hydrology_diagnostic_report(
        run_dir,
        metadata,
        context.build_hydrology_summary(metadata, run_dir),
    )
    metadata["hydrology_summary"] = hydrology_summary
    run_summary = context.build_run_summary(
        run_dir,
        metadata,
        resolved_config,
        updated_at=updated_at,
        updated_at_ns=updated_at_ns,
    )
    run_summary["hydrology_summary"] = hydrology_summary
    return {
        "run": run_summary,
        "metadata": metadata,
        "hydrology_summary": hydrology_summary,
        "series": {"dates": dates, "residuals": residuals, **series},
        "series_range": {
            "actual_start": actual_start,
            "actual_end": actual_end,
            "warmup_start": warmup_start,
            "warmup_end": str(time_cfg.get("warmup_end", "") or ""),
            "warmup_covered": warmup_covered,
        },
        "sampling": {"sampled_points": len(sampled), "total_points": total_rows},
        "parameters": [{"name": key, "value": value} for key, value in metadata.get("optimized_params", {}).items()],
        "studio_compatible": context.is_studio_editable_metadata(metadata, resolved_config),
    }
