#!/usr/bin/env python
# -*- coding: utf-8 -*-
from __future__ import annotations

import re
import shutil
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

import pandas as pd

from services.run_hydrology import metadata_objective_family


RUN_KIND_LABELS = {
    "manual_starter": "手调起点",
    "manual_result": "手调结果",
    "forecast_restart": "连续状态预报",
    "calibration": "正式率定",
    "legacy": "历史结果",
}
SYSTEM_RESULT_TITLES = frozenset({"手调起点", "手调结果"})


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


@dataclass(frozen=True)
class RunMutationContext:
    resolve_path: Callable[..., Path]
    list_runs: Callable[[], list[dict[str, Any]]]
    summarize_run: Callable[[Path], dict[str, Any]]
    read_json_file: Callable[[Path], dict[str, Any]]
    write_json_file: Callable[[Path, dict[str, Any]], None]
    normalize_result_title: Callable[[Any], str]
    invalidate_deleted_run_refs: Callable[[Path], None]


_RUN_LIST_CACHE_LOCK = threading.Lock()
_RUN_LIST_CACHE_SIGNATURE: tuple[tuple[Any, ...], ...] | None = None
_RUN_LIST_CACHE_ITEMS: list[dict[str, Any]] = []


def run_kind_from_metadata(metadata: dict[str, Any] | None, studio_compatible: bool = False) -> str:
    meta = dict(metadata or {})
    forecast_result = dict(meta.get("forecast_result", {}) or {})
    manual_result = dict(meta.get("manual_result", {}) or {})
    starter_result = dict(meta.get("starter_result", {}) or {})
    if bool(forecast_result.get("enabled")) or str(meta.get("run_class", "") or "") == "forecast_restart":
        return "forecast_restart"
    if bool(manual_result.get("enabled")):
        return "manual_result"
    if bool(starter_result.get("enabled")):
        return "manual_starter"
    if studio_compatible:
        return "calibration"
    return "legacy"


def run_kind_label(kind: str) -> str:
    return RUN_KIND_LABELS.get(kind, "结果")


def normalize_result_title(value: Any) -> str:
    text = re.sub(r"\s+", " ", str(value or "").strip())
    return text.strip()


def has_custom_result_title(run_dir: Path, title: str) -> bool:
    normalized = normalize_result_title(title)
    if not normalized:
        return False
    if normalized.lower() == run_dir.name.lower():
        return False
    if normalized in SYSTEM_RESULT_TITLES:
        return False
    return True


def run_time_label(raw_value: Any, updated_at: float | None = None) -> str:
    text = str(raw_value or "").strip()
    if text:
        return text
    if updated_at:
        try:
            return time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(float(updated_at)))
        except Exception:
            return ""
    return ""


def source_run_meta(metadata: dict[str, Any], replace_placeholders: Callable[..., Any] | None = None) -> tuple[str, str]:
    manual_result = dict(metadata.get("manual_result", {}) or {})
    optimization = dict(metadata.get("optimization", {}) or {})
    replay_context = dict(metadata.get("replay_context", {}) or {})
    source_path = str(
        replay_context.get("source_run_path")
        or manual_result.get("source_run_path")
        or optimization.get("source_run_path")
        or ""
    ).strip()
    source_name = str(
        replay_context.get("source_run_name")
        or manual_result.get("source_run_name")
        or optimization.get("source_run_name")
        or ""
    ).strip()
    if not source_name and source_path:
        try:
            resolved = replace_placeholders(source_path) if replace_placeholders else source_path
            source_name = Path(str(resolved)).name
        except Exception:
            source_name = Path(source_path).name
    return source_path, source_name


def display_run_title(
    run_dir: Path,
    metadata: dict[str, Any],
    workspace_name: str,
    studio_compatible: bool,
    updated_at: float | None = None,
) -> dict[str, Any]:
    raw_title = normalize_result_title(metadata.get("result_title", ""))
    run_kind = run_kind_from_metadata(metadata, studio_compatible)
    kind_label = run_kind_label(run_kind)
    time_text = run_time_label(metadata.get("run_time"), updated_at)
    has_custom_title = has_custom_result_title(run_dir, raw_title)
    if has_custom_title:
        display_name = raw_title
        subtitle_parts = [workspace_name, kind_label, time_text]
    else:
        display_name = " · ".join(part for part in (workspace_name, kind_label, time_text) if part)
        subtitle_parts = []
    display_name = display_name or raw_title or run_dir.name
    subtitle = " · ".join(part for part in subtitle_parts if part)
    if not subtitle and display_name != run_dir.name:
        subtitle = f"目录名：{run_dir.name}"
    return {
        "name": raw_title or run_dir.name,
        "raw_title": raw_title,
        "display_name": display_name,
        "display_subtitle": subtitle,
        "has_custom_title": has_custom_title,
        "run_type": run_kind,
        "run_type_label": kind_label,
        "workspace_name": workspace_name,
        "run_time_label": time_text,
    }


def run_parameter_context(
    run_dir: Path,
    metadata: dict[str, Any],
    resolved_config: Path | None,
    workspace_name: str = "",
    param_bounds_profile_labels: dict[str, str] | None = None,
) -> dict[str, Any]:
    data_sources = dict(metadata.get("data_sources", {}) or {})
    time_config = dict(metadata.get("time_config", {}) or {})
    initial_state = dict(metadata.get("initial_state", {}) or {})
    parameter_profile = dict(metadata.get("parameter_profile", {}) or {})
    optimized_params = metadata.get("optimized_params", {})
    bounds_profile = str(
        metadata.get("param_bounds_profile")
        or parameter_profile.get("bounds_profile")
        or ""
    ).strip()
    bounds_labels = dict(param_bounds_profile_labels or {})
    bounds_label = str(
        metadata.get("param_bounds_profile_label")
        or parameter_profile.get("bounds_profile_label")
        or bounds_labels.get(bounds_profile, "")
        or ""
    ).strip()
    workspace_config = str(metadata.get("workspace_config", "") or (resolved_config or "")).strip()
    return {
        "schema": "run_parameter_context_v1",
        "parameter_source": "source_result",
        "parameter_source_label": "源结果参数",
        "source_run_path": str(run_dir.resolve(strict=False)),
        "source_run_name": run_dir.name,
        "source_workspace": str(workspace_name or "").strip(),
        "source_workspace_config": workspace_config,
        "calibration_profile": str(metadata.get("calibration_profile") or "").strip(),
        "time_step_hours": time_config.get("time_step_hours"),
        "objective_mode": metadata_objective_family(metadata),
        "prec_source": str(
            data_sources.get("runtime_prec_source")
            or data_sources.get("prec_source")
            or data_sources.get("configured_precip_source")
            or ""
        ).strip(),
        "precipitation_strategy": str(
            data_sources.get("precipitation_strategy")
            or data_sources.get("precipitation_mode")
            or data_sources.get("station_precip_mode")
            or ""
        ).strip(),
        "glacier_mode": str(data_sources.get("glacier_mode", "") or "").strip(),
        "glacier_enabled": bool(metadata.get("optional_modules", {}).get("glacier", {}).get("enabled")),
        "param_bounds_profile": bounds_profile,
        "param_bounds_profile_label": bounds_label,
        "state_snapshot_time": str(initial_state.get("state_snapshot_time", "") or "").strip(),
        "parameter_count": int(len(optimized_params)) if isinstance(optimized_params, dict) else 0,
    }


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


def _managed_run_paths(context: RunMutationContext) -> set[Path]:
    return {
        Path(str(item["path"])).resolve(strict=False)
        for item in context.list_runs()
    }


def delete_run(run_path_raw: str, context: RunMutationContext) -> dict[str, Any]:
    run_dir = context.resolve_path(run_path_raw, must_exist=True)
    metadata_path = run_dir / "metadata.json"
    simulation_path = run_dir / "simulation.csv"
    if not run_dir.is_dir() or not metadata_path.exists() or not simulation_path.exists():
        raise ValueError("目标目录不是可识别的结果目录。")
    if run_dir.resolve(strict=False) not in _managed_run_paths(context):
        raise ValueError("该结果目录不在当前工程可管理范围内。")
    name = context.summarize_run(run_dir).get("name") or run_dir.name
    shutil.rmtree(run_dir)
    context.invalidate_deleted_run_refs(run_dir)
    return {"deleted": True, "name": name, "path": str(run_dir.resolve(strict=False))}


def rename_run(payload: dict[str, Any], context: RunMutationContext) -> dict[str, Any]:
    run_path_raw = str(payload.get("path", "")).strip()
    if not run_path_raw:
        raise ValueError("缺少结果路径。")
    run_dir = context.resolve_path(run_path_raw, must_exist=True)
    metadata_path = run_dir / "metadata.json"
    simulation_path = run_dir / "simulation.csv"
    if not run_dir.is_dir() or not metadata_path.exists() or not simulation_path.exists():
        raise ValueError("目标目录不是可识别的结果目录。")
    if run_dir.resolve(strict=False) not in _managed_run_paths(context):
        raise ValueError("该结果目录不在当前工程可管理范围内。")
    new_title = context.normalize_result_title(payload.get("title", ""))
    if len(new_title) > 60:
        raise ValueError("结果标题请控制在 60 个字符以内。")
    metadata = context.read_json_file(metadata_path)
    if new_title:
        metadata["result_title"] = new_title
    else:
        metadata.pop("result_title", None)
    context.write_json_file(metadata_path, metadata)
    updated = context.summarize_run(run_dir)
    return {
        "renamed": True,
        "path": str(run_dir.resolve(strict=False)),
        "title": new_title,
        "auto_named": not bool(new_title),
        "run": updated,
    }
