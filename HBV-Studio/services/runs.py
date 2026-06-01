#!/usr/bin/env python
# -*- coding: utf-8 -*-
from __future__ import annotations

import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

import pandas as pd


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


@dataclass(frozen=True)
class RunExportContext:
    resolve_path: Callable[..., Path]
    read_json_file: Callable[[Path], dict[str, Any]]
    normalize_time_step_hours: Callable[[Any], float]
    is_date_only_string: Callable[[Any], bool]
    format_timestamp_for_display: Callable[[pd.Timestamp, float], str]
    slugify_workspace_name: Callable[[str], str]
    to_display_path: Callable[[Path], str]
    default_export_fields: Callable[[dict[str, Any] | None], list[str]]
    export_field_labels: dict[str, str]


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


def _run_export_time_label(timestamp: pd.Timestamp, step_hours: float, context: RunExportContext) -> str:
    return context.format_timestamp_for_display(timestamp, step_hours).replace(":", "-").replace(" ", "_")


def export_run_excel(payload: dict[str, Any], context: RunExportContext) -> dict[str, Any]:
    run_dir = context.resolve_path(str(payload.get("path", "")), must_exist=True)
    simulation_path = run_dir / "simulation.csv"
    metadata_path = run_dir / "metadata.json"
    if not simulation_path.exists():
        raise FileNotFoundError("结果目录缺少 simulation.csv。")
    metadata = context.read_json_file(metadata_path) if metadata_path.exists() else {}
    time_cfg = dict(metadata.get("time_config", {}) or {})
    step_hours = context.normalize_time_step_hours(time_cfg.get("time_step_hours", 24.0))

    selected_fields = [
        field
        for field in [str(item).strip() for item in list(payload.get("fields", []) or [])]
        if field
    ] or context.default_export_fields(metadata)
    invalid_fields = [field for field in selected_fields if field not in context.export_field_labels]
    if invalid_fields:
        raise ValueError("存在不支持的导出字段：" + "、".join(invalid_fields[:6]))

    frame = pd.read_csv(simulation_path)
    if "date" not in frame.columns:
        raise ValueError("simulation.csv 缺少 date 列。")
    frame["date"] = pd.to_datetime(frame["date"], errors="coerce")
    frame = frame.dropna(subset=["date"]).copy()
    if frame.empty:
        raise ValueError("当前结果没有可导出的有效时间记录。")

    start_raw = str(payload.get("start_date", "")).strip()
    end_raw = str(payload.get("end_date", "")).strip()
    start_ts = pd.to_datetime(start_raw) if start_raw else pd.Timestamp(frame["date"].min())
    end_ts = pd.to_datetime(end_raw) if end_raw else pd.Timestamp(frame["date"].max())
    if step_hours < 24.0 and context.is_date_only_string(end_raw):
        end_ts = end_ts + pd.Timedelta(days=1) - pd.Timedelta(hours=step_hours)
    if end_ts < start_ts:
        raise ValueError("导出结束时间不能早于开始时间。")

    actual_start = pd.Timestamp(frame["date"].min())
    actual_end = pd.Timestamp(frame["date"].max())
    warmup_start_raw = str(time_cfg.get("warmup_start", "") or "").strip()
    warmup_start_ts = pd.to_datetime(warmup_start_raw) if warmup_start_raw else None
    if warmup_start_ts is not None and actual_start > warmup_start_ts and start_ts < actual_start:
        raise ValueError(
            "当前结果文件只保存了率定后时段，未包含预热段。"
            "请用新版程序重新生成结果后，再导出包含预热期的全时段数据。"
        )

    filtered = frame.loc[(frame["date"] >= start_ts) & (frame["date"] <= end_ts)].copy()
    if filtered.empty:
        raise ValueError("当前时间范围内没有可导出的结果记录。")

    export_frame = pd.DataFrame()
    export_frame["日期"] = filtered["date"].dt.strftime("%Y-%m-%d" if step_hours >= 24.0 else "%Y-%m-%d %H:%M")
    for field in selected_fields:
        export_frame[context.export_field_labels[field]] = filtered[field] if field in filtered.columns else pd.NA

    export_dir = run_dir / "导出"
    export_dir.mkdir(parents=True, exist_ok=True)
    run_title = str(metadata.get("result_title", "")).strip() or run_dir.name
    file_name = (
        f"{context.slugify_workspace_name(run_title)}"
        f"_导出_{_run_export_time_label(start_ts, step_hours, context)}"
        f"_{_run_export_time_label(end_ts, step_hours, context)}.xlsx"
    )
    export_path = export_dir / file_name
    try:
        with pd.ExcelWriter(export_path, engine="xlsxwriter") as writer:
            export_frame.to_excel(writer, sheet_name="结果数据", index=False)
            worksheet = writer.sheets["结果数据"]
            worksheet.freeze_panes(1, 1)
            worksheet.set_column(0, 0, 18)
            worksheet.set_column(1, len(export_frame.columns), 18)
    except ImportError:
        with pd.ExcelWriter(export_path, engine="openpyxl") as writer:
            export_frame.to_excel(writer, sheet_name="结果数据", index=False)

    return {
        "path": str(export_path.resolve(strict=False)),
        "display_path": context.to_display_path(export_path),
        "row_count": int(len(export_frame)),
        "fields": list(selected_fields),
        "labels": [context.export_field_labels[field] for field in selected_fields],
        "start": export_frame.iloc[0, 0],
        "end": export_frame.iloc[-1, 0],
    }
