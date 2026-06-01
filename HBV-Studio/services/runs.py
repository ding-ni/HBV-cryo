#!/usr/bin/env python
# -*- coding: utf-8 -*-
from __future__ import annotations

import copy
import csv
import re
import shutil
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

import pandas as pd

from services.run_hydrology import metadata_objective_family, safe_float


RUN_KIND_LABELS = {
    "manual_starter": "手调起点",
    "manual_result": "手调结果",
    "forecast_restart": "连续状态预报",
    "calibration": "正式率定",
    "legacy": "历史结果",
}
SYSTEM_RESULT_TITLES = frozenset({"手调起点", "手调结果"})
RUN_EXPORT_FIELD_LABELS = {
    "q_sim": "模拟总径流(m3/s)",
    "q_sim_model": "模型本地产流(m3/s)",
    "q_boundary_inflow": "边界入流(m3/s)",
    "q_obs": "观测径流(m3/s)",
    "q_rain": "降雨径流(m3/s)",
    "q_snow": "融雪径流(m3/s)",
    "q_ice": "裸冰融化径流(m3/s)",
    "q_ice_raw": "裸冰融化原始分量(m3/s)",
    "q_ice_reference": "冰川参考径流(m3/s)",
    "q_ice_reference_raw": "冰川参考原始融水(m3/s)",
}
DEFAULT_RUN_EXPORT_FIELDS = ("q_sim", "q_obs", "q_rain", "q_snow", "q_ice")


@dataclass(frozen=True)
class RunListContext:
    discover_run_entries: Callable[[], list[tuple[tuple[Any, ...], Path]]]
    summarize_run: Callable[[Path], dict[str, Any]]


@dataclass(frozen=True)
class RunDiscoveryContext:
    project_runtime_dir: Path
    list_workspaces: Callable[[], list[dict[str, Any]]]
    workspace_path_candidates: Callable[..., list[Path]]
    safe_iterdir: Callable[[Path], list[Path]]


@dataclass(frozen=True)
class RunSummaryContext:
    to_display_path: Callable[[Path], str]
    is_studio_editable_metadata: Callable[[dict[str, Any], Path | None], bool]
    build_hydrology_summary: Callable[[dict[str, Any], Path], dict[str, Any]]
    workspace_name_for_summary: Callable[[dict[str, Any], Path | None], str]
    param_bounds_profile_labels: dict[str, str]
    replace_placeholders: Callable[..., Any] | None = None


@dataclass(frozen=True)
class RunWorkspaceNameContext:
    workspace_roots_hint_from_metadata: Callable[[dict[str, Any] | None], tuple[Path | None, Path | None]]
    resolve_workspace_config_reference: Callable[..., Path | None]
    read_runtime_config: Callable[[Path], dict[str, Any]]


@dataclass(frozen=True)
class RunMetadataCompatibilityContext:
    workspace_roots_hint_from_metadata: Callable[[dict[str, Any] | None], tuple[Path | None, Path | None]]
    resolve_workspace_config_reference: Callable[..., Path | None]


@dataclass(frozen=True)
class RunSourceReferenceContext:
    resolve_any_path: Callable[..., Path]
    replace_placeholders: Callable[..., Any]
    discover_runtime_roots: Callable[[], list[Path]]
    iter_run_parent_dirs: Callable[[Path], list[Path]]


@dataclass(frozen=True)
class RunDetailContext:
    resolve_path: Callable[..., Path]
    read_json_file: Callable[[Path], dict[str, Any]]
    normalize_run_metadata: Callable[..., tuple[dict[str, Any], Path | None]]
    run_update_timestamps: Callable[[Path], tuple[float, int]]
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


@dataclass(frozen=True)
class RunMutationContext:
    resolve_path: Callable[..., Path]
    list_runs: Callable[[], list[dict[str, Any]]]
    summarize_run: Callable[[Path], dict[str, Any]]
    read_json_file: Callable[[Path], dict[str, Any]]
    write_json_file: Callable[[Path, dict[str, Any]], None]
    normalize_result_title: Callable[[Any], str]
    invalidate_deleted_run_refs: Callable[[Path], None]


@dataclass(frozen=True)
class RunReplayConfigContext:
    default_initial_state: dict[str, Any]
    resolve_metadata_object_type: Callable[[dict[str, Any]], str]
    metadata_boundary_enabled: Callable[[dict[str, Any]], bool | None]


@dataclass(frozen=True)
class RunCalibrationTaskContext:
    resolve_path: Callable[..., Path]
    read_json_file: Callable[[Path], dict[str, Any]]
    normalize_run_metadata: Callable[..., tuple[dict[str, Any], Path | None]]
    run_update_timestamps: Callable[[Path], tuple[float, int]]
    build_run_summary: Callable[..., dict[str, Any]]
    is_studio_editable_metadata: Callable[[dict[str, Any], Path | None], bool]


_RUN_LIST_CACHE_LOCK = threading.Lock()
_RUN_LIST_CACHE_SIGNATURE: tuple[tuple[Any, ...], ...] | None = None
_RUN_LIST_CACHE_ITEMS: list[dict[str, Any]] = []


def discover_runtime_roots(context: RunDiscoveryContext) -> list[Path]:
    roots: list[Path] = []
    if context.project_runtime_dir.exists():
        roots.append(context.project_runtime_dir.resolve())
    for workspace in context.list_workspaces():
        runtime_root = workspace.get("workspace_root")
        if runtime_root:
            try:
                path = Path(runtime_root).resolve()
                if path.exists():
                    roots.append(path)
            except Exception:
                pass
    unique: list[Path] = []
    seen: set[str] = set()
    for root in roots:
        key = str(root).lower()
        if key not in seen:
            seen.add(key)
            unique.append(root)
    return unique


def iter_run_parent_dirs(root_dir: Path, context: RunDiscoveryContext) -> list[Path]:
    workspace_dirs: list[Path] = []
    direct_results_roots = [
        path for path in context.workspace_path_candidates(root_dir, ("结果",), ("results",))
        if path.exists()
    ]
    if direct_results_roots:
        workspace_dirs.append(root_dir.resolve())
    for child in context.safe_iterdir(root_dir):
        try:
            if not child.is_dir():
                continue
            child_results_roots = [
                path for path in context.workspace_path_candidates(child, ("结果",), ("results",))
                if path.exists()
            ]
            if not child_results_roots:
                continue
            workspace_dirs.append(child.resolve())
        except (PermissionError, OSError):
            continue

    parents: list[Path] = []
    for workspace_dir in workspace_dirs:
        results_roots = [
            path for path in context.workspace_path_candidates(workspace_dir, ("结果",), ("results",))
            if path.exists()
        ]
        for results_root in results_roots:
            direct_runs_dirs = [
                path for path in context.workspace_path_candidates(results_root, ("运行记录",), ("runs",))
                if path.exists()
            ]
            for direct_runs_dir in direct_runs_dirs:
                parents.append(direct_runs_dir.resolve())
            for child in context.safe_iterdir(results_root):
                try:
                    if not child.is_dir():
                        continue
                except (PermissionError, OSError):
                    continue
                for candidate in context.workspace_path_candidates(child, ("运行记录",), ("runs",)):
                    try:
                        if candidate.exists() and candidate.is_dir():
                            parents.append(candidate.resolve())
                    except (PermissionError, OSError):
                        continue
    unique: list[Path] = []
    seen: set[str] = set()
    for parent in parents:
        key = str(parent).lower()
        if key in seen:
            continue
        seen.add(key)
        unique.append(parent)
    return unique


def discover_run_entries(context: RunDiscoveryContext) -> list[tuple[tuple[Any, ...], Path]]:
    entries: list[tuple[tuple[Any, ...], Path]] = []
    seen: set[str] = set()
    for root_dir in discover_runtime_roots(context):
        for runs_dir in iter_run_parent_dirs(root_dir, context):
            for candidate in context.safe_iterdir(runs_dir):
                try:
                    if not candidate.is_dir():
                        continue
                    metadata_path = candidate / "metadata.json"
                    simulation_path = candidate / "simulation.csv"
                    if not metadata_path.exists() or not simulation_path.exists():
                        continue
                    resolved = candidate.resolve()
                    key = str(resolved).lower()
                    if key in seen:
                        continue
                    seen.add(key)
                    run_stat = resolved.stat()
                    metadata_stat = metadata_path.stat()
                    simulation_stat = simulation_path.stat()
                except (FileNotFoundError, PermissionError, OSError):
                    continue
                entries.append(
                    (
                        (
                            key,
                            int(getattr(run_stat, "st_mtime_ns", int(run_stat.st_mtime * 1e9))),
                            int(getattr(metadata_stat, "st_mtime_ns", int(metadata_stat.st_mtime * 1e9))),
                            int(getattr(simulation_stat, "st_mtime_ns", int(simulation_stat.st_mtime * 1e9))),
                            int(simulation_stat.st_size),
                        ),
                        resolved,
                    )
                )
    entries.sort(key=lambda item: item[0][0])
    return entries


def iter_run_dirs(context: RunDiscoveryContext) -> list[Path]:
    return [path for _, path in discover_run_entries(context)]


def snapshot_run_paths(list_runs: Callable[[], list[dict[str, Any]]]) -> set[str]:
    return {item["path"] for item in list_runs()}


def run_update_timestamps(run_dir: Path) -> tuple[float, int]:
    stat = run_dir.stat()
    updated_at = stat.st_mtime
    updated_at_ns = int(getattr(stat, "st_mtime_ns", int(updated_at * 1e9)))
    for candidate in (run_dir / "metadata.json", run_dir / "simulation.csv"):
        try:
            candidate_stat = candidate.stat()
            updated_at = max(updated_at, candidate_stat.st_mtime)
            updated_at_ns = max(
                updated_at_ns,
                int(getattr(candidate_stat, "st_mtime_ns", int(candidate_stat.st_mtime * 1e9))),
            )
        except (FileNotFoundError, PermissionError, OSError):
            pass
    return updated_at, updated_at_ns


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


def run_boundary_enabled(metadata: dict[str, Any] | None) -> bool:
    meta = dict(metadata or {})
    optional_modules = dict(meta.get("optional_modules", {}) or {})
    boundary_meta = dict(meta.get("boundary_condition", {}) or {})
    return bool(
        meta.get("project_object_type") == "interbasin_with_boundary"
        or dict(optional_modules.get("boundary_inflow", {}) or {}).get("enabled")
        or boundary_meta.get("enabled")
        or boundary_meta.get("boundary_inflow_file")
    )


def default_run_export_fields(metadata: dict[str, Any] | None) -> list[str]:
    fields = list(DEFAULT_RUN_EXPORT_FIELDS)
    if run_boundary_enabled(metadata):
        fields.append("q_boundary_inflow")
    return fields


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


def resolve_source_run_reference(
    source_run_path_raw: Any,
    source_run_name_raw: Any,
    context: RunSourceReferenceContext,
) -> str:
    source_run_path = str(source_run_path_raw or "").strip()
    source_run_name = str(source_run_name_raw or "").strip()
    if not source_run_path:
        return ""

    def is_run_dir(candidate: Path) -> bool:
        return (candidate / "metadata.json").exists() and (candidate / "simulation.csv").exists()

    def is_workspace_dir(candidate: Path) -> bool:
        return any((candidate / item).exists() for item in ("\u7ed3\u679c", "results"))

    try:
        base_path = context.resolve_any_path(source_run_path, must_exist=False)
    except Exception:
        return source_run_path

    candidates: list[Path] = [base_path]
    search_names: list[str] = []
    for name in (
        source_run_name,
        Path(str(context.replace_placeholders(source_run_path))).name,
        base_path.name,
    ):
        cleaned = str(name or "").strip()
        if cleaned and cleaned not in search_names:
            search_names.append(cleaned)
    if source_run_name:
        candidates.append(base_path / source_run_name)
        for parts in (
            ("\u7ed3\u679c", "\u65e5\u5c3a\u5ea6", "\u8fd0\u884c\u8bb0\u5f55"),
            ("\u7ed3\u679c", "\u5c0f\u65f6\u5c3a\u5ea6", "\u8fd0\u884c\u8bb0\u5f55"),
            ("results", "daily", "runs"),
            ("results", "hourly", "runs"),
        ):
            candidates.append(base_path.joinpath(*parts, source_run_name))

    for candidate in candidates:
        if is_run_dir(candidate):
            return str(candidate.resolve(strict=False))

    try:
        runtime_roots = context.discover_runtime_roots()
    except Exception:
        runtime_roots = []

    for name in search_names:
        for root_dir in runtime_roots:
            root = Path(root_dir).resolve(strict=False)
            if root.name == name and (is_workspace_dir(root) or is_run_dir(root)):
                return str(root)
            candidate = (root / name).resolve(strict=False)
            if is_workspace_dir(candidate) or is_run_dir(candidate):
                return str(candidate)
        for root_dir in runtime_roots:
            for parent in context.iter_run_parent_dirs(Path(root_dir)):
                candidate = (parent / name).resolve(strict=False)
                if is_run_dir(candidate):
                    return str(candidate)

    return str(base_path.resolve(strict=False))


def first_existing_path(candidates: list[Path]) -> Path | None:
    seen: set[str] = set()
    fallback: Path | None = None
    for candidate in candidates:
        resolved = Path(candidate).resolve(strict=False)
        key = str(resolved).lower()
        if key in seen:
            continue
        seen.add(key)
        if fallback is None:
            fallback = resolved
        if resolved.exists():
            return resolved
    return fallback


def has_parameter_bounds(metadata: dict[str, Any]) -> bool:
    profile = metadata.get("parameter_profile")
    if not isinstance(profile, dict):
        return False
    bounds = profile.get("bounds")
    if not isinstance(bounds, dict) or not bounds:
        return False
    for value in bounds.values():
        if isinstance(value, (list, tuple)) and len(value) >= 2:
            return True
    return False


def is_studio_editable_metadata(
    metadata: dict[str, Any],
    resolved_config: Path | None = None,
    context: RunMetadataCompatibilityContext | None = None,
) -> bool:
    config_path = resolved_config
    if config_path is None and context is not None:
        hint_project_root, hint_gui_root = context.workspace_roots_hint_from_metadata(metadata)
        config_path = context.resolve_workspace_config_reference(
            str(metadata.get("workspace_config", "") or ""),
            project_root=hint_project_root,
            gui_root=hint_gui_root,
        )
    return bool(config_path and has_parameter_bounds(metadata))


def workspace_name_for_summary(
    metadata: dict[str, Any],
    resolved_config: Path | None = None,
    context: RunWorkspaceNameContext | None = None,
) -> str:
    value = str(metadata.get("workspace_label", "") or "").strip()
    if value:
        return value
    config_path = resolved_config
    if config_path is None and context is not None:
        hint_project_root, hint_gui_root = context.workspace_roots_hint_from_metadata(metadata)
        config_path = context.resolve_workspace_config_reference(
            str(metadata.get("workspace_config", "") or ""),
            project_root=hint_project_root,
            gui_root=hint_gui_root,
        )
    if config_path is not None:
        if context is None:
            return config_path.stem
        try:
            config = context.read_runtime_config(config_path)
            value = str(config.get("\u6d41\u57df\u540d\u79f0", config_path.stem)).strip()
            if value:
                return value
        except Exception:
            return config_path.stem
    raw = str(metadata.get("workspace_config", "") or "").strip()
    if raw:
        try:
            return Path(raw).stem
        except Exception:
            return raw
    return ""


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


def build_run_summary(
    run_dir: Path,
    metadata: dict[str, Any] | None = None,
    resolved_config: Path | None = None,
    *,
    updated_at: float,
    updated_at_ns: int,
    context: RunSummaryContext,
) -> dict[str, Any]:
    summary = {
        "name": run_dir.name,
        "raw_title": "",
        "display_name": run_dir.name,
        "display_subtitle": "",
        "has_custom_title": False,
        "path": str(run_dir.resolve()),
        "display_path": context.to_display_path(run_dir),
        "updated_at": updated_at,
        "updated_at_ns": int(updated_at_ns),
        "run_time": None,
        "run_id": None,
        "nse_cal": None,
        "nse_val": None,
        "pbias_cal": None,
        "pbias_val": None,
        "glacier_enabled": None,
        "boundary_enabled": None,
        "time_step_hours": None,
        "time_config": {},
        "calibration_profile": None,
        "object_type": None,
        "workspace_config": "",
        "workspace_display_path": "",
        "workspace_name": "",
        "studio_compatible": False,
        "run_origin": "legacy",
        "run_type": "legacy",
        "run_type_label": RUN_KIND_LABELS["legacy"],
        "run_time_label": "",
        "source_run_path": "",
        "source_run_name": "",
        "recorded_objective_family": "",
        "objective_family": "",
        "effective_objective_mode": "",
        "flow_guard_status": "",
        "hydrology_summary": {},
        "optimized_params_available": False,
        "optimized_param_count": 0,
        "state_snapshot_available": False,
        "state_snapshot_time": "",
        "source_state_snapshot_time": "",
        "source_state_summary": {},
        "source_parameter_summary": {},
        "parameter_context": {},
        "forecast_input_archive": {},
        "forecast_source_ready": False,
    }
    if metadata is None:
        return summary

    summary["run_time"] = metadata.get("run_time")
    summary["run_id"] = metadata.get("run_id")
    summary["nse_cal"] = metadata.get("metrics", {}).get("calibration", {}).get("nse")
    summary["nse_val"] = metadata.get("metrics", {}).get("validation", {}).get("nse")
    summary["pbias_cal"] = metadata.get("metrics", {}).get("calibration", {}).get("pbias")
    summary["pbias_val"] = metadata.get("metrics", {}).get("validation", {}).get("pbias")
    summary["glacier_enabled"] = metadata.get("optional_modules", {}).get("glacier", {}).get("enabled")
    summary["boundary_enabled"] = metadata.get("optional_modules", {}).get("boundary_inflow", {}).get("enabled")
    summary["time_step_hours"] = metadata.get("time_config", {}).get("time_step_hours")
    summary["time_config"] = dict(metadata.get("time_config", {}) or {})
    summary["calibration_profile"] = metadata.get("calibration_profile")
    summary["object_type"] = metadata.get("project_object_type")
    workspace_config = str(metadata.get("workspace_config", "") or "").strip()
    summary["workspace_config"] = workspace_config
    if workspace_config:
        try:
            summary["workspace_display_path"] = context.to_display_path(Path(workspace_config))
        except Exception:
            summary["workspace_display_path"] = workspace_config

    studio_compatible = context.is_studio_editable_metadata(metadata, resolved_config)
    summary["studio_compatible"] = studio_compatible
    summary["run_origin"] = "studio" if studio_compatible else "legacy"
    summary["recorded_objective_family"] = str(metadata.get("recorded_objective_family") or "").strip()
    summary["objective_family"] = metadata_objective_family(metadata)
    summary["effective_objective_mode"] = str(
        metadata.get("effective_objective_mode")
        or metadata.get("optimization", {}).get("effective_objective_mode")
        or ""
    ).strip()
    summary["flow_guard_status"] = str(
        metadata.get("objective_terms", {}).get("flow_guard", {}).get("status", "")
        or ""
    ).strip()
    summary["hydrology_summary"] = context.build_hydrology_summary(metadata, run_dir)

    initial_state = dict(metadata.get("initial_state", {}) or {})
    forecast_result = dict(metadata.get("forecast_result", {}) or {})
    snapshot_file = str(initial_state.get("state_snapshot_file", "") or "").strip()
    snapshot_path = run_dir / snapshot_file if snapshot_file else run_dir / "state_snapshot.npz"
    optimized_params = metadata.get("optimized_params", {})
    summary["optimized_params_available"] = bool(isinstance(optimized_params, dict) and optimized_params)
    summary["optimized_param_count"] = int(len(optimized_params)) if isinstance(optimized_params, dict) else 0
    summary["state_snapshot_available"] = bool(snapshot_path.exists() or initial_state.get("state_snapshot_available"))
    summary["state_snapshot_time"] = str(initial_state.get("state_snapshot_time", "") or "").strip()
    summary["source_state_snapshot_time"] = str(
        initial_state.get("source_state_snapshot_time")
        or forecast_result.get("source_state_time")
        or ""
    ).strip()
    summary["source_state_summary"] = dict(
        forecast_result.get("source_state_summary")
        or metadata.get("source_state_summary")
        or {}
    )
    summary["source_parameter_summary"] = dict(
        forecast_result.get("source_parameter_summary")
        or metadata.get("source_parameter_summary")
        or {}
    )
    summary["forecast_input_archive"] = dict(
        forecast_result.get("forecast_input_archive")
        or dict(metadata.get("data_sources", {}) or {}).get("forecast_input_archive")
        or {}
    )

    workspace_name = context.workspace_name_for_summary(metadata, resolved_config)
    summary["parameter_context"] = run_parameter_context(
        run_dir,
        metadata,
        resolved_config,
        workspace_name,
        context.param_bounds_profile_labels,
    )
    summary["forecast_source_ready"] = bool(summary["optimized_params_available"] and summary["state_snapshot_available"])
    summary.update(display_run_title(run_dir, metadata, workspace_name, studio_compatible, updated_at=updated_at))
    source_path, source_name = source_run_meta(metadata, context.replace_placeholders)
    summary["source_run_path"] = source_path
    summary["source_run_name"] = source_name
    return summary


def read_sampled_csv_rows(path: Path, max_points: int = 900) -> tuple[list[dict[str, str]], int]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        total_rows = max(sum(1 for _ in handle) - 1, 0)
    if total_rows <= 0:
        return [], 0

    stride = 1 if total_rows <= max_points else max(1, total_rows // max_points)
    sampled: list[dict[str, str]] = []
    last_row: dict[str, str] | None = None
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        for idx, row in enumerate(reader):
            last_row = row
            if stride == 1 or idx % stride == 0:
                sampled.append(row)
    if last_row is not None and (not sampled or sampled[-1] != last_row):
        sampled.append(last_row)
    return sampled, total_rows


def load_run_series_map(run_path: Path, field: str) -> dict[str, float | None]:
    simulation_path = run_path / "simulation.csv"
    if not simulation_path.exists():
        return {}
    values: dict[str, float | None] = {}
    with simulation_path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        for row in reader:
            date_text = str(row.get("date", "")).strip()
            if not date_text:
                continue
            values[date_text] = safe_float(row.get(field))
    return values


def run_csv_preview(run_path: Path, *, limit: int = 3) -> dict[str, Any]:
    csv_path = run_path / "simulation.csv"
    if not csv_path.exists():
        return {"columns": [], "rows": []}
    with csv_path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        rows: list[dict[str, Any]] = []
        for idx, row in enumerate(reader):
            if idx >= max(int(limit), 0):
                break
            rows.append(dict(row))
        return {"columns": list(reader.fieldnames or []), "rows": rows}


def run_csv_date_bounds(run_path: Path) -> dict[str, Any]:
    csv_path = run_path / "simulation.csv"
    if not csv_path.exists():
        return {"first_date": None, "last_date": None, "row_count": 0}
    first_date = None
    last_date = None
    row_count = 0
    with csv_path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        for row in reader:
            row_count += 1
            current = str(row.get("date", "") or "").strip() or None
            if first_date is None:
                first_date = current
            last_date = current
    return {"first_date": first_date, "last_date": last_date, "row_count": row_count}


def read_run_metrics_snapshot(
    run_path: Path,
    read_json_file: Callable[[Path], dict[str, Any]],
) -> dict[str, Any]:
    metadata = read_json_file(run_path / "metadata.json")
    metrics = dict(metadata.get("metrics", {}) or {})
    calibration = dict(metrics.get("calibration", {}) or {})
    validation = dict(metrics.get("validation", {}) or {})
    return {
        "nse_cal": safe_float(calibration.get("nse")),
        "nse_val": safe_float(validation.get("nse")),
        "kge_val": safe_float(validation.get("kge")),
        "pbias_val": safe_float(validation.get("pbias")),
    }


def metadata_initial_state_override(
    metadata: dict[str, Any],
    default_initial_state: dict[str, Any],
) -> dict[str, float] | None:
    initial_state = dict(metadata.get("initial_state", {}) or {})
    raw_vector = initial_state.get("vector", None)
    if not isinstance(raw_vector, dict):
        return None

    override: dict[str, float] = {}
    for key in default_initial_state.keys():
        if key not in raw_vector:
            continue
        raw_value = raw_vector.get(key)
        try:
            value = float(raw_value)
        except Exception as exc:
            raise ValueError(f"结果 metadata 中的 initial_state.{key} 不是有效数字：{raw_value}") from exc
        if value < 0:
            raise ValueError(f"结果 metadata 中的 initial_state.{key} 不能为负值：{raw_value}")
        override[key] = value
    return override or None


def apply_run_replay_config_overrides(
    config: dict[str, Any],
    metadata: dict[str, Any],
    context: RunReplayConfigContext,
) -> dict[str, Any]:
    patched = copy.deepcopy(config)
    time_meta = dict(metadata.get("time_config", {}) or {})
    if time_meta:
        time_cfg = dict(patched.get("时间", {}) or {})
        key_map = {
            "warmup_start": "预热开始",
            "warmup_end": "预热结束",
            "calib_start": "率定开始",
            "calib_end": "率定结束",
            "valid_start": "验证开始",
            "valid_end": "验证结束",
        }
        for src_key, dst_key in key_map.items():
            value = time_meta.get(src_key, None)
            if value:
                time_cfg[dst_key] = str(value)
        starts = [pd.to_datetime(value) for value in [time_cfg.get("预热开始"), time_cfg.get("率定开始")] if value]
        ends = [pd.to_datetime(value) for value in [time_cfg.get("验证结束"), time_cfg.get("率定结束")] if value]
        if starts:
            time_cfg["开始年份"] = int(min(starts).year)
        if ends:
            time_cfg["结束年份"] = int(max(ends).year)
        patched["时间"] = time_cfg
        if time_meta.get("time_step_hours", None) is not None:
            patched["时间步长_小时"] = float(time_meta["time_step_hours"])

    resolved_object_type = context.resolve_metadata_object_type(metadata)
    if resolved_object_type:
        patched["项目对象"] = resolved_object_type

    objective_meta = dict(metadata.get("objective", {}) or {})
    obs_mode = str(objective_meta.get("obs_mode", "") or "").strip()
    if obs_mode:
        patched["观测口径模式"] = obs_mode
    cfmax_threshold = objective_meta.get("cfmax_zone_threshold_m", None)
    if cfmax_threshold not in (None, ""):
        try:
            patched["CFMAX分区阈值_m"] = float(cfmax_threshold)
        except Exception as exc:
            raise ValueError(f"结果 metadata 中的 cfmax_zone_threshold_m 不是有效数字：{cfmax_threshold}") from exc

    initial_state_override = metadata_initial_state_override(metadata, context.default_initial_state)
    if initial_state_override is not None:
        init_state = dict(patched.get("初始状态", {}) or {})
        for key, default_value in context.default_initial_state.items():
            init_state.setdefault(key, default_value)
        init_state.update(initial_state_override)
        patched["初始状态"] = init_state

    boundary_meta = dict(metadata.get("boundary_condition", {}) or {})
    optional_modules = dict(metadata.get("optional_modules", {}) or {})
    boundary_module = dict(optional_modules.get("boundary_inflow", {}) or {})
    boundary_file = str(
        boundary_meta.get("boundary_inflow_file")
        or boundary_module.get("file")
        or ""
    ).strip()
    boundary_enabled = context.metadata_boundary_enabled(metadata)
    boundary_cfg = dict(patched.get("边界条件", {}) or {})
    boundary_cfg["时间字段"] = str(boundary_meta.get("date_field", boundary_cfg.get("时间字段", "date")) or "date")
    boundary_cfg["流量字段"] = str(boundary_meta.get("flow_field", boundary_cfg.get("流量字段", "inflow_m3s")) or "inflow_m3s")
    gap_fill = boundary_meta.get("gap_fill", boundary_cfg.get("缺失填补", "zero"))
    boundary_cfg["缺失填补"] = str(gap_fill or "zero")
    if boundary_enabled is False:
        boundary_cfg["上游边界入流_csv"] = ""
    elif boundary_file:
        boundary_cfg["上游边界入流_csv"] = boundary_file
    if boundary_cfg:
        patched["边界条件"] = boundary_cfg

    return patched


def restore_forward_observed_series(module: Any, source_obs_series: dict[str, float | None]) -> bool:
    if not source_obs_series or not hasattr(module, "SIM_DATES") or not hasattr(module, "np"):
        return False
    np_mod = module.np

    restored_values: list[float] = []
    matched = 0
    for item in module.SIM_DATES:
        key = module.format_time_value(item) if hasattr(module, "format_time_value") else str(item)
        value = source_obs_series.get(key, None)
        if value is None:
            restored_values.append(float("nan"))
        else:
            restored_values.append(float(value))
            matched += 1
    restored = np_mod.asarray(restored_values, dtype=np_mod.float64)
    if matched <= 0 or not np_mod.isfinite(restored).any():
        return False

    module.Q_OBS_FULL = restored
    module.Q_OBS_OBJ = restored.copy()
    calib_mask = getattr(module, "CALIB_MASK", None)
    valid_mask = getattr(module, "VALID_MASK", None)
    module.Q_OBS_CALIB = module.Q_OBS_OBJ[calib_mask] if calib_mask is not None else module.Q_OBS_OBJ.copy()
    module.Q_OBS_VALID = module.Q_OBS_OBJ[valid_mask] if valid_mask is not None else np_mod.asarray([], dtype=np_mod.float64)
    if hasattr(module, "OBS_MODE_APPLIED"):
        module.OBS_MODE_APPLIED = "run_replay_fallback"
    return True


def capture_forward_observation_state(module: Any) -> dict[str, Any]:
    np_mod = getattr(module, "np", None)
    state: dict[str, Any] = {
        "obs_mode_applied": getattr(module, "OBS_MODE_APPLIED", None),
    }
    for name in ("Q_OBS_FULL", "Q_OBS_OBJ", "Q_OBS_CALIB", "Q_OBS_VALID"):
        value = getattr(module, name, None)
        if value is None:
            state[name] = None
        elif np_mod is not None:
            state[name] = np_mod.asarray(value, dtype=np_mod.float64).copy()
        else:
            try:
                state[name] = value.copy()
            except Exception:
                state[name] = value
    return state


def restore_forward_observation_state(module: Any, state: dict[str, Any] | None) -> None:
    if not isinstance(state, dict):
        return
    np_mod = getattr(module, "np", None)
    for name in ("Q_OBS_FULL", "Q_OBS_OBJ", "Q_OBS_CALIB", "Q_OBS_VALID"):
        value = state.get(name, None)
        if value is None:
            setattr(module, name, None)
        elif np_mod is not None:
            setattr(module, name, np_mod.asarray(value, dtype=np_mod.float64).copy())
        else:
            try:
                setattr(module, name, value.copy())
            except Exception:
                setattr(module, name, value)
    if "obs_mode_applied" in state:
        setattr(module, "OBS_MODE_APPLIED", state.get("obs_mode_applied"))


def restore_forward_boundary_series(
    module: Any,
    sim: dict[str, Any],
    source_boundary_series: dict[str, float | None],
) -> bool:
    if not source_boundary_series or not hasattr(module, "SIM_DATES") or not hasattr(module, "np"):
        return False
    q_total = sim.get("q_total")
    if q_total is None:
        return False
    series_len = len(q_total)
    sim_dates = module.SIM_DATES[:series_len]
    restored_values: list[float] = []
    matched = 0
    for item in sim_dates:
        key = module.format_time_value(item) if hasattr(module, "format_time_value") else str(item)
        if key not in source_boundary_series:
            return False
        value = source_boundary_series.get(key, 0.0)
        restored_values.append(0.0 if value is None else float(value))
        matched += 1
    if matched != series_len:
        return False

    np_mod = module.np
    boundary_routed = np_mod.asarray(restored_values, dtype=np_mod.float64)
    local_source = sim.get("q_local")
    if local_source is None:
        local_source = q_total
    local_routed = np_mod.asarray(local_source, dtype=np_mod.float64)
    if len(local_routed) != series_len:
        local_routed = np_mod.asarray(q_total, dtype=np_mod.float64)
    sim["q_local"] = local_routed.copy()
    sim["q_boundary"] = boundary_routed
    sim["q_total"] = local_routed + boundary_routed
    sim["boundary_enabled"] = True
    sim["boundary_replay_fixed"] = True
    return True


def pick_latest_run_path(run_paths: list[str]) -> str:
    def sort_key(value: str) -> tuple[float, str]:
        try:
            path = Path(value)
            return (path.stat().st_mtime, str(path))
        except Exception:
            return (0.0, str(value))

    return max(run_paths, key=sort_key) if run_paths else ""


def build_calibration_task_result(run_path: str, context: RunCalibrationTaskContext) -> dict[str, Any] | None:
    try:
        run_dir = context.resolve_path(run_path, must_exist=True)
        metadata_path = run_dir / "metadata.json"
        if not metadata_path.exists():
            return None
        metadata, resolved_config = context.normalize_run_metadata(context.read_json_file(metadata_path), run_path=run_dir)
        updated_at, updated_at_ns = context.run_update_timestamps(run_dir)
        summary = context.build_run_summary(
            run_dir,
            metadata,
            resolved_config,
            updated_at=updated_at,
            updated_at_ns=updated_at_ns,
        )
    except Exception:
        return None

    optimization = dict(metadata.get("optimization", {}) or {})
    calibration = dict(metadata.get("metrics", {}).get("calibration", {}) or {})
    validation = dict(metadata.get("metrics", {}).get("validation", {}) or {})
    return {
        "run_path": str(run_dir.resolve()),
        "run_name": str(summary.get("display_name", "") or summary.get("name", "") or run_dir.name),
        "workspace_config": str(metadata.get("workspace_config", "") or ""),
        "calibration_profile": metadata.get("calibration_profile"),
        "requested_objective_mode": metadata.get("requested_objective_mode") or optimization.get("requested_objective_mode"),
        "effective_objective_mode": metadata.get("effective_objective_mode") or optimization.get("effective_objective_mode"),
        "metrics": {
            "nse_cal": calibration.get("nse"),
            "nse_val": validation.get("nse"),
            "kge_cal": calibration.get("kge"),
            "kge_val": validation.get("kge"),
            "pbias_cal": calibration.get("pbias"),
            "pbias_val": validation.get("pbias"),
        },
        "optimization": optimization,
        "studio_compatible": context.is_studio_editable_metadata(metadata, resolved_config),
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
    sampled, total_rows = read_sampled_csv_rows(simulation_path)
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
    ] or default_run_export_fields(metadata)
    invalid_fields = [field for field in selected_fields if field not in RUN_EXPORT_FIELD_LABELS]
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
        export_frame[RUN_EXPORT_FIELD_LABELS[field]] = filtered[field] if field in filtered.columns else pd.NA

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
        "labels": [RUN_EXPORT_FIELD_LABELS[field] for field in selected_fields],
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
