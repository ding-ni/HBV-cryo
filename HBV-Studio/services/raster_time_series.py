#!/usr/bin/env python
# -*- coding: utf-8 -*-
from __future__ import annotations

import copy
import threading
from pathlib import Path
from typing import Any

import pandas as pd

from services.time_utils import (
    format_timestamp_for_display,
    parse_time_from_name,
    summarize_time_coverage,
    time_step_missing_text,
)


TIF_SCAN_CACHE_LOCK = threading.Lock()
TIF_SCAN_CACHE: dict[str, dict[str, Any]] = {}
GRID_ALIGNMENT_CACHE_LOCK = threading.Lock()
GRID_ALIGNMENT_CACHE: dict[str, dict[str, Any]] = {}
GRID_ALIGNMENT_SAMPLE_LIMIT = 12


def _directory_scan_signature(directory: Path) -> tuple[str, int, int]:
    try:
        resolved = directory.resolve(strict=False)
    except (OSError, ValueError):
        return str(directory), 0, 0
    try:
        stat = resolved.stat()
    except (FileNotFoundError, PermissionError, OSError):
        return str(resolved), 0, 0
    mtime_ns = int(getattr(stat, "st_mtime_ns", int(stat.st_mtime * 1e9)))
    return str(resolved), mtime_ns, int(stat.st_size)


def _file_signature(path: Path) -> tuple[int, int]:
    stat = path.stat()
    return (
        int(getattr(stat, "st_mtime_ns", int(stat.st_mtime * 1e9))),
        int(stat.st_size),
    )


def scan_tif_time_series(directory: Path) -> dict[str, Any]:
    signature = _directory_scan_signature(directory)
    cache_key = signature[0].lower()
    with TIF_SCAN_CACHE_LOCK:
        cached = TIF_SCAN_CACHE.get(cache_key)
        if cached and cached.get("signature") == signature:
            return copy.deepcopy(cached["data"])

    scan_error = ""
    try:
        exists = directory.exists()
    except (OSError, ValueError) as exc:
        exists = False
        scan_error = str(exc)
    try:
        tif_files = sorted(directory.glob("*.tif")) if exists else []
    except (OSError, ValueError) as exc:
        tif_files = []
        scan_error = str(exc)
    invalid_files: list[str] = []
    duplicate_timestamps: dict[pd.Timestamp, list[str]] = {}
    unique_timestamps: dict[pd.Timestamp, str] = {}
    parseable_files = 0

    for tif_path in tif_files:
        timestamp = parse_time_from_name(tif_path.name)
        if timestamp is None:
            invalid_files.append(tif_path.name)
            continue
        parseable_files += 1
        if timestamp in unique_timestamps:
            duplicate_timestamps.setdefault(timestamp, [unique_timestamps[timestamp]]).append(tif_path.name)
        else:
            unique_timestamps[timestamp] = tif_path.name

    timestamps = sorted(unique_timestamps)
    result = {
        "exists": exists,
        "path": str(directory),
        "total_files": len(tif_files),
        "parseable_files": parseable_files,
        "valid_time_steps": len(timestamps),
        "invalid_files": invalid_files,
        "duplicate_timestamps": {ts: duplicate_timestamps[ts] for ts in sorted(duplicate_timestamps)},
        "timestamps": timestamps,
        "scan_error": scan_error,
    }
    with TIF_SCAN_CACHE_LOCK:
        TIF_SCAN_CACHE[cache_key] = {"signature": signature, "data": copy.deepcopy(result)}
    return result


def _time_series_period_summary(
    timestamps: list[pd.Timestamp],
    step_hours: float,
) -> tuple[str, list[pd.Timestamp]]:
    coverage = summarize_time_coverage(timestamps, step_hours)
    return str(coverage["period_summary"]), list(coverage["missing_times"])


def _grid_alignment_signature(directory: Path, dem_path: Path) -> tuple[Any, ...]:
    dir_sig = _directory_scan_signature(directory)
    dem_sig = _file_signature(dem_path) if dem_path.exists() else (0, 0)
    return (dir_sig[0], dir_sig[1], dir_sig[2], str(dem_path.resolve(strict=False)), dem_sig[0], dem_sig[1])


def _sample_tif_files_for_grid_check(files: list[Path], limit: int = GRID_ALIGNMENT_SAMPLE_LIMIT) -> list[Path]:
    if len(files) <= limit:
        return list(files)
    if limit <= 1:
        return [files[0]]
    last_index = len(files) - 1
    indices: list[int] = []
    for pos in range(limit):
        idx = round(pos * last_index / (limit - 1))
        if (not indices) or idx != indices[-1]:
            indices.append(idx)
    return [files[idx] for idx in indices]


def validate_tif_grid_alignment(label: str, directory: Path, dem_path: Path) -> dict[str, Any]:
    import rasterio

    if not directory.exists() or not directory.is_dir():
        return {"label": label, "ok": True, "checked_files": 0, "error": None}
    if not dem_path.exists():
        return {"label": label, "ok": True, "checked_files": 0, "error": None}

    signature = _grid_alignment_signature(directory, dem_path)
    cache_key = str(directory.resolve(strict=False)).lower()
    with GRID_ALIGNMENT_CACHE_LOCK:
        cached = GRID_ALIGNMENT_CACHE.get(cache_key)
        if cached and cached.get("signature") == signature:
            return copy.deepcopy(cached["data"])

    tif_files = sorted(directory.glob("*.tif"))
    if not tif_files:
        result = {"label": label, "ok": True, "checked_files": 0, "error": None}
        with GRID_ALIGNMENT_CACHE_LOCK:
            GRID_ALIGNMENT_CACHE[cache_key] = {"signature": signature, "data": copy.deepcopy(result)}
        return result

    try:
        with rasterio.open(dem_path) as dem:
            dem_meta = {
                "height": dem.height,
                "width": dem.width,
                "crs": dem.crs,
                "transform": dem.transform,
            }
    except Exception as exc:
        result = {"label": label, "ok": False, "checked_files": 0, "error": f"{label}无法读取 DEM 网格：{exc}"}
        with GRID_ALIGNMENT_CACHE_LOCK:
            GRID_ALIGNMENT_CACHE[cache_key] = {"signature": signature, "data": copy.deepcopy(result)}
        return result

    files_to_check = _sample_tif_files_for_grid_check(tif_files)
    checked = 0
    error = None
    for tif_path in files_to_check:
        checked += 1
        try:
            with rasterio.open(tif_path) as src:
                same_grid = (
                    src.height == dem_meta["height"]
                    and src.width == dem_meta["width"]
                    and src.crs == dem_meta["crs"]
                    and src.transform == dem_meta["transform"]
                )
        except Exception as exc:
            error = f"{label}栅格读取失败：{tif_path.name}（{exc}）"
            break
        if not same_grid:
            error = f"{label}目录存在与 DEM 网格不一致的 tif：{tif_path.name}"
            break

    result = {
        "label": label,
        "ok": error is None,
        "checked_files": checked,
        "total_files": len(tif_files),
        "sampled_check": len(files_to_check) < len(tif_files),
        "error": error,
    }
    with GRID_ALIGNMENT_CACHE_LOCK:
        GRID_ALIGNMENT_CACHE[cache_key] = {"signature": signature, "data": copy.deepcopy(result)}
    return result


def validate_tif_time_series(
    label: str,
    directory: Path,
    step_hours: float,
    expected_index: pd.DatetimeIndex | None = None,
    time_basis_label: str = "当前配置时间范围",
) -> dict[str, Any]:
    result = scan_tif_time_series(directory)
    period_summary, internal_missing_steps = _time_series_period_summary(result["timestamps"], step_hours)
    errors: list[str] = []
    warnings: list[str] = []

    if result.get("scan_error"):
        errors.append(f"{label}目录无法读取：{directory}（{result['scan_error']}）")
    elif not result["exists"]:
        errors.append(f"{label}目录不存在：{directory}")
    elif result["total_files"] == 0:
        errors.append(f"{label}目录中没有 .tif 文件：{directory}")

    if result["invalid_files"]:
        sample = "、".join(result["invalid_files"][:3])
        errors.append(f"{label}目录有 {len(result['invalid_files'])} 个 tif 文件名无法解析时间，例如：{sample}")

    if result["duplicate_timestamps"]:
        first_ts, names = next(iter(result["duplicate_timestamps"].items()))
        sample = "、".join(names[:3])
        errors.append(f"{label}目录存在重复时间戳 {format_timestamp_for_display(first_ts, step_hours)}，例如：{sample}")

    if expected_index is None and internal_missing_steps:
        sample = "、".join(format_timestamp_for_display(ts, step_hours) for ts in internal_missing_steps[:3])
        errors.append(
            f"{label}时间序列内部不连续，缺少 {time_step_missing_text(len(internal_missing_steps), step_hours)}，"
            f"例如：{sample}"
        )

    missing_steps: list[pd.Timestamp] = []
    out_of_range_steps: list[pd.Timestamp] = []
    if expected_index is not None:
        expected_list = list(expected_index)
        expected_set = set(expected_list)
        actual_set = set(result["timestamps"])
        missing_steps = [ts for ts in expected_list if ts not in actual_set]
        out_of_range_steps = [ts for ts in result["timestamps"] if ts not in expected_set]
        if missing_steps:
            sample = "、".join(format_timestamp_for_display(ts, step_hours) for ts in missing_steps[:3])
            errors.append(
                f"{label}时间覆盖不完整，缺少 {time_step_missing_text(len(missing_steps), step_hours)}，"
                f"例如：{sample}"
            )
        if out_of_range_steps:
            sample = "、".join(format_timestamp_for_display(ts, step_hours) for ts in out_of_range_steps[:3])
            warnings.append(
                f"{label}有 {time_step_missing_text(len(out_of_range_steps), step_hours)}落在{time_basis_label}之外，"
                f"例如：{sample}"
            )

    result.update(
        {
            "label": label,
            "ok": len(errors) == 0,
            "errors": errors,
            "warnings": warnings,
            "missing_steps": missing_steps,
            "out_of_range_steps": out_of_range_steps,
            "start_time": result["timestamps"][0] if result["timestamps"] else None,
            "end_time": result["timestamps"][-1] if result["timestamps"] else None,
            "internal_missing_steps": internal_missing_steps,
            "period_summary": period_summary,
        }
    )
    return result
