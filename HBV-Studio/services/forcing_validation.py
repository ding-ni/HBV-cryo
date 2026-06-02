#!/usr/bin/env python
# -*- coding: utf-8 -*-
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

import pandas as pd


@dataclass(frozen=True)
class ForcingValidationContext:
    current_profile: Callable[[dict[str, Any]], str]
    build_profile_paths: Callable[[dict[str, Any], str], dict[str, Any]]
    normalize_time_step_hours: Callable[[Any], float]
    task_time_basis: Callable[..., str]
    time_basis_labels: dict[str, str]
    time_basis_event_windows: str
    build_expected_forcing_index: Callable[..., pd.DatetimeIndex | None]
    normalized_flood_events: Callable[..., dict[str, Any]]
    effective_precip_paths: Callable[..., tuple[Path, Path, str]]
    validate_tif_time_series: Callable[..., dict[str, Any]]
    workspace_dem_path: Callable[..., Path]
    configured_dem_kind: Callable[[dict[str, Any]], str | None]
    validate_tif_grid_alignment: Callable[..., dict[str, Any]]
    event_windows_ui_summary: Callable[[dict[str, Any] | None, float], dict[str, Any] | None]
    event_forcing_coverage_summary: Callable[..., dict[str, Any] | None]


@dataclass(frozen=True)
class ForcingAlignedStatusContext:
    build_profile_paths: Callable[[dict[str, Any], str], dict[str, Any]]
    effective_precip_paths: Callable[..., tuple[Path, Path, str]]
    normalize_time_step_hours: Callable[[Any], float]
    validate_tif_time_series: Callable[..., dict[str, Any]]


@dataclass(frozen=True)
class ForcingInputsReadyContext:
    build_profile_paths: Callable[[dict[str, Any], str], dict[str, Any]]
    workspace_dem_path: Callable[..., Path]
    configured_dem_kind: Callable[[dict[str, Any]], str | None]
    resolve_config_related_path: Callable[[dict[str, Any], Any], Path | None]
    validate_forcing_bundle: Callable[..., dict[str, Any]]
    observed_flow_key: str


@dataclass(frozen=True)
class ForcingPreprocessStatusContext:
    build_workspace_paths: Callable[[dict[str, Any]], dict[str, Any]]
    build_profile_paths: Callable[[dict[str, Any], str], dict[str, Any]]
    resolve_precip_source: Callable[[dict[str, Any], Any], str]
    effective_precip_source: Callable[[str], str]
    count_matching: Callable[..., int]
    validate_tif_time_series: Callable[..., dict[str, Any]]


def series_group_status(
    entries: list[tuple[str, Path]],
    step_hours: float,
    context: ForcingPreprocessStatusContext,
) -> tuple[bool, str, int, list[dict[str, Any]]]:
    results: list[dict[str, Any]] = []
    total = 0
    for label, directory in entries:
        result = context.validate_tif_time_series(label, directory, step_hours)
        results.append(result)
        total += int(result["valid_time_steps"])
    ready = all(result["ok"] and int(result["valid_time_steps"]) > 0 for result in results)
    if ready:
        message = "；".join(f"{result['label']}: {result['valid_time_steps']}" for result in results)
        return True, message, total, results
    issues = [result["errors"][0] for result in results if result["errors"]]
    if issues:
        return False, "；".join(issues[:2]), total, results
    return False, "未检测到有效 tif 时间序列。", total, results


def prefer_raw_or_aligned_group_status(
    raw_entries: list[tuple[str, Path]],
    aligned_entries: list[tuple[str, Path]],
    step_hours: float,
    context: ForcingPreprocessStatusContext,
) -> tuple[bool, str, int]:
    raw_ok, raw_message, raw_count, raw_results = series_group_status(raw_entries, step_hours, context)
    aligned_ok, aligned_message, aligned_count, aligned_results = series_group_status(aligned_entries, step_hours, context)
    if raw_ok:
        return True, raw_message, raw_count
    if aligned_ok:
        return True, f"{aligned_message}（已导入并完成网格对齐）", aligned_count
    raw_has_files = any(int(result["total_files"]) > 0 for result in raw_results)
    aligned_has_files = any(int(result["total_files"]) > 0 for result in aligned_results)
    if aligned_has_files:
        return False, aligned_message, aligned_count
    if raw_has_files:
        return False, raw_message, raw_count
    return False, raw_message, 0


def check_daily_prec_status(
    config: dict[str, Any],
    context: ForcingPreprocessStatusContext,
    *,
    profile: str,
    precip_source: Any = None,
) -> tuple[bool, str, int]:
    paths = context.build_profile_paths(config, profile)
    source_key = context.resolve_precip_source(config, precip_source)
    if source_key == "custom_tif":
        aligned = Path(paths["aligned_prec_custom_base_dir"])
        count = context.count_matching(aligned)
        if count > 0:
            return True, "当前为本地栅格降水模式，降水已导入工程独立降水目录。", count
        return True, "当前为本地栅格降水模式，不需要执行原始降水预处理。", 0
    source = context.effective_precip_source(source_key)
    if source == "era5":
        target = paths["raw_prec_era5_daily_dir"]
        aligned = paths["aligned_prec_era5_base_dir"]
    elif source == "cmfd":
        target = paths["raw_prec_cmfd_daily_dir"]
        aligned = paths["aligned_prec_cmfd_base_dir"]
    else:
        target = paths["raw_prec_daily_dir"]
        aligned = paths["aligned_prec_base_dir"]
    return prefer_raw_or_aligned_group_status(
        [("日尺度降水中间结果", Path(target))],
        [("工程降水输入", Path(aligned))],
        24.0,
        context,
    )


def check_hourly_prec_status(
    config: dict[str, Any],
    context: ForcingPreprocessStatusContext,
    *,
    profile: str,
    precip_source: Any = None,
) -> tuple[bool, str, int]:
    paths = context.build_workspace_paths(config)
    profile_paths = context.build_profile_paths(config, profile)
    source_key = context.resolve_precip_source(config, precip_source)
    if source_key == "custom_tif":
        aligned = Path(profile_paths["aligned_prec_custom_base_dir"])
        count = context.count_matching(aligned)
        if count > 0:
            return True, "当前为本地栅格降水模式，小时降水已导入工程独立降水目录。", count
        return True, "当前为本地栅格降水模式，不需要执行原始小时降水标准化。", 0
    source = context.effective_precip_source(source_key)
    if source == "era5":
        target = paths["raw_prec_era5_hourly_dir"]
        aligned = profile_paths["aligned_prec_era5_base_dir"]
    elif source == "cmfd":
        target = paths["raw_prec_cmfd_hourly_dir"]
        aligned = profile_paths["aligned_prec_cmfd_base_dir"]
    else:
        target = paths["raw_prec_hourly_dir"]
        aligned = profile_paths["aligned_prec_base_dir"]
    return prefer_raw_or_aligned_group_status(
        [("小时尺度降水中间结果", Path(target))],
        [("工程降水输入", Path(aligned))],
        1.0,
        context,
    )


def check_aligned_forcing_status(
    config: dict[str, Any],
    context: ForcingAlignedStatusContext,
    *,
    profile: str,
    label: str,
    precip_source: Any = None,
) -> tuple[bool, str, int]:
    paths = context.build_profile_paths(config, profile)
    precip_dir, _, _ = context.effective_precip_paths(config, profile, precip_source=precip_source)
    step_hours = context.normalize_time_step_hours(config.get("时间步长_小时", 24.0))
    scans = [
        context.validate_tif_time_series("降水", precip_dir, step_hours),
        context.validate_tif_time_series("气温", Path(paths["aligned_temp_dir"]), step_hours),
        context.validate_tif_time_series("蒸散发", Path(paths["aligned_evap_dir"]), step_hours),
    ]
    count = sum(int(item["valid_time_steps"]) for item in scans)
    ready = all(item["ok"] for item in scans)
    message = "；".join(item["errors"][0] for item in scans if item["errors"]) or f"{label}气象驱动有效时间步：{count}"
    return ready, message, count


def check_forcing_inputs_ready(
    config: dict[str, Any],
    context: ForcingInputsReadyContext,
    *,
    profile: str,
    forcing_label: str = "",
    precip_source: Any = None,
) -> tuple[bool, str, int]:
    paths = context.build_profile_paths(config, profile)
    required = [
        context.workspace_dem_path(paths["gis_dir"], prefer=context.configured_dem_kind(config)),
        Path(paths["gis_dir"]) / "flow_accumulation_masked.tif",
    ]
    basin_path = context.resolve_config_related_path(config, config.get("流域边界_shp"))
    obs_path = context.resolve_config_related_path(config, config.get(context.observed_flow_key))
    if basin_path is not None:
        required.append(basin_path)
    if obs_path is not None:
        required.append(obs_path)
    base_ready = all(Path(item).exists() for item in required)
    if basin_path is None or obs_path is None:
        base_ready = False

    forcing = context.validate_forcing_bundle(config, profile, precip_source=precip_source)
    message = f"基础输入{'齐全' if base_ready else '缺失'}；{forcing_label}气象驱动有效时间步数：{forcing['total_valid_steps']}"
    if forcing["errors"]:
        message += f"；问题：{'；'.join(forcing['errors'][:2])}"
    return base_ready and forcing["ok"], message, int(forcing["total_valid_steps"]) + int(base_ready)


def validate_forcing_bundle(
    config: dict[str, Any],
    context: ForcingValidationContext,
    profile: str | None = None,
    precip_source: Any = None,
) -> dict[str, Any]:
    active_profile = profile or context.current_profile(config)
    paths = context.build_profile_paths(config, active_profile)
    step_hours = context.normalize_time_step_hours(config.get("时间步长_小时", 24.0))
    time_basis = context.task_time_basis(config, context="calibration")
    time_basis_label = context.time_basis_labels.get(time_basis, "当前任务时段")
    expected_index = context.build_expected_forcing_index(config, context="calibration")
    event_info = (
        context.normalized_flood_events(config, step_hours=step_hours)
        if time_basis == context.time_basis_event_windows
        else None
    )
    _, precip_dir, selected_source = context.effective_precip_paths(
        config,
        active_profile,
        precip_source=precip_source,
    )
    precip_label = "降水（本地栅格）" if selected_source == "custom_tif" else "降水"
    directories = {
        "prec": context.validate_tif_time_series(precip_label, Path(precip_dir), step_hours, expected_index, time_basis_label),
        "temp": context.validate_tif_time_series("气温", Path(paths["aligned_temp_dir"]), step_hours, expected_index, time_basis_label),
        "evap": context.validate_tif_time_series("蒸散发", Path(paths["aligned_evap_dir"]), step_hours, expected_index, time_basis_label),
    }
    errors: list[str] = []
    warnings: list[str] = []
    for item in directories.values():
        errors.extend(item["errors"])
        warnings.extend(item["warnings"])
    dem_path = context.workspace_dem_path(paths["gis_dir"], prefer=context.configured_dem_kind(config))
    grid_checks = {
        "prec": context.validate_tif_grid_alignment(precip_label, Path(precip_dir), dem_path),
        "temp": context.validate_tif_grid_alignment("气温", Path(paths["aligned_temp_dir"]), dem_path),
        "evap": context.validate_tif_grid_alignment("蒸散发", Path(paths["aligned_evap_dir"]), dem_path),
    }
    for item in grid_checks.values():
        if not item.get("ok") and item.get("error"):
            errors.append(str(item["error"]))
    return {
        "ok": len(errors) == 0,
        "errors": errors,
        "warnings": warnings,
        "expected_steps": len(expected_index) if expected_index is not None else None,
        "directories": directories,
        "grid_checks": grid_checks,
        "total_valid_steps": sum(int(item["valid_time_steps"]) for item in directories.values()),
        "profile": active_profile,
        "time_basis": time_basis,
        "time_basis_label": time_basis_label,
        "event_windows": context.event_windows_ui_summary(event_info, step_hours) if event_info is not None else None,
        "event_forcing_coverage": (
            context.event_forcing_coverage_summary(event_info, directories, step_hours)
            if event_info is not None
            else None
        ),
    }
