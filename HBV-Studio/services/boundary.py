#!/usr/bin/env python
# -*- coding: utf-8 -*-
from __future__ import annotations

import copy
from dataclasses import dataclass
from pathlib import Path
import threading
import time
from typing import Any, Callable

import pandas as pd

from services.time_utils import detect_series_step_hours, format_timestamp_for_display, normalize_time_step_hours


@dataclass(frozen=True)
class BoundaryPreviewContext:
    resolve_path: Callable[..., Path]
    read_config: Callable[[Path], dict[str, Any]]
    build_expected_time_index: Callable[[dict[str, Any]], pd.DatetimeIndex | None]
    normalize_time_step_hours: Callable[[Any], float]
    inspect_boundary_csv: Callable[..., dict[str, Any]]
    is_date_only_string: Callable[[Any], bool]


@dataclass(frozen=True)
class BoundaryInflowInspectContext:
    resolve_path: Callable[..., Path]
    profile_daily: str
    profile_hourly: str


BOUNDARY_CSV_CACHE_LOCK = threading.Lock()
BOUNDARY_CSV_CACHE: dict[str, dict[str, Any]] = {}
MAX_BOUNDARY_CSV_CACHE = 6


def _file_signature(path: Path) -> tuple[int, int]:
    stat = path.stat()
    return (
        int(getattr(stat, "st_mtime_ns", int(stat.st_mtime * 1e9))),
        int(stat.st_size),
    )


def _trim_boundary_csv_cache_locked() -> None:
    while len(BOUNDARY_CSV_CACHE) > MAX_BOUNDARY_CSV_CACHE:
        oldest_key = min(
            BOUNDARY_CSV_CACHE.items(),
            key=lambda item: float(item[1].get("used_at", 0.0)),
        )[0]
        BOUNDARY_CSV_CACHE.pop(oldest_key, None)


def _inspect_boundary_inflow_csv_base(
    csv_path_raw: str,
    context: BoundaryInflowInspectContext,
    *,
    date_field: str = "date",
    flow_field: str = "inflow_m3s",
) -> dict[str, Any]:
    path = context.resolve_path(csv_path_raw, must_exist=True)
    cache_key = f"{path.resolve(strict=False)}|{date_field}|{flow_field}"
    signature = _file_signature(path)
    with BOUNDARY_CSV_CACHE_LOCK:
        cached = BOUNDARY_CSV_CACHE.get(cache_key)
        if cached and cached.get("signature") == signature:
            cached["used_at"] = time.time()
            return copy.deepcopy(cached["data"])

    frame = pd.read_csv(path)
    if date_field not in frame.columns:
        raise ValueError(f"\u627e\u4e0d\u5230\u65f6\u95f4\u5b57\u6bb5 '{date_field}'\uff0c\u53ef\u7528\u5217\uff1a{list(frame.columns)}")
    if flow_field not in frame.columns:
        raise ValueError(f"\u627e\u4e0d\u5230\u6d41\u91cf\u5b57\u6bb5 '{flow_field}'\uff0c\u53ef\u7528\u5217\uff1a{list(frame.columns)}")

    frame = frame.copy()
    frame[date_field] = pd.to_datetime(frame[date_field], errors="coerce")
    frame[flow_field] = pd.to_numeric(frame[flow_field], errors="coerce")
    valid = frame.dropna(subset=[date_field, flow_field]).copy()
    if valid.empty:
        raise ValueError("\u4e0a\u6e38\u8fb9\u754c\u5165\u6d41\u6587\u4ef6\u4e2d\u6ca1\u6709\u53ef\u8bc6\u522b\u7684\u6709\u6548\u65f6\u95f4\u548c\u6d41\u91cf\u8bb0\u5f55\u3002")

    valid.sort_values(date_field, inplace=True)
    duplicate_mask = valid.duplicated(subset=[date_field], keep=False)
    duplicate_timestamps = valid.loc[duplicate_mask, date_field].drop_duplicates().sort_values().tolist()
    actual_index = pd.DatetimeIndex(valid[date_field].drop_duplicates().sort_values().tolist())
    step_hours = detect_series_step_hours(pd.Series(actual_index.tolist()))
    flow_values = valid[flow_field].astype(float)

    preview_rows = []
    for _, row in valid.head(10).iterrows():
        preview_rows.append({date_field: str(row[date_field]), flow_field: float(row[flow_field])})

    base = {
        "columns": list(frame.columns),
        "total_rows": int(len(frame)),
        "valid_rows": int(len(valid)),
        "invalid_rows": int(len(frame) - len(valid)),
        "duplicate_timestamps": [pd.Timestamp(item) for item in duplicate_timestamps],
        "duplicate_count": int(len(duplicate_timestamps)),
        "time_step_hours": step_hours,
        "negative_count": int((flow_values < 0).sum()),
        "zero_count": int((flow_values == 0).sum()),
        "date_range": {
            "start": str(valid[date_field].min()),
            "end": str(valid[date_field].max()),
        },
        "flow_stats": {
            "min": round(float(flow_values.min()), 4),
            "max": round(float(flow_values.max()), 4),
            "mean": round(float(flow_values.mean()), 4),
        },
        "preview": preview_rows,
        "suggested_calibration_mode": context.profile_hourly if step_hours is not None and step_hours <= 1.5 else context.profile_daily,
        "_actual_index": actual_index,
    }
    with BOUNDARY_CSV_CACHE_LOCK:
        BOUNDARY_CSV_CACHE[cache_key] = {"signature": signature, "data": copy.deepcopy(base), "used_at": time.time()}
        _trim_boundary_csv_cache_locked()
    return base


def inspect_boundary_inflow_csv(
    csv_path_raw: str,
    context: BoundaryInflowInspectContext,
    *,
    date_field: str = "date",
    flow_field: str = "inflow_m3s",
    expected_index: pd.DatetimeIndex | None = None,
    expected_step_hours: float | None = None,
) -> dict[str, Any]:
    base = _inspect_boundary_inflow_csv_base(
        csv_path_raw,
        context,
        date_field=date_field,
        flow_field=flow_field,
    )
    actual_index = pd.DatetimeIndex(base.pop("_actual_index"))
    expected_steps = None
    missing_steps: list[pd.Timestamp] = []
    out_of_range_steps: list[pd.Timestamp] = []
    coverage_ratio = None
    if expected_index is not None:
        expected_steps = len(expected_index)
        expected_list = list(expected_index)
        expected_set = set(expected_list)
        actual_set = set(actual_index.tolist())
        missing_steps = [ts for ts in expected_list if ts not in actual_set]
        out_of_range_steps = [ts for ts in actual_index.tolist() if ts not in expected_set]
        coverage_ratio = (len(expected_set & actual_set) / len(expected_set)) if expected_set else None

    return {
        **base,
        "expected_time_step_hours": expected_step_hours,
        "expected_steps": expected_steps,
        "missing_steps": missing_steps,
        "out_of_range_steps": out_of_range_steps,
        "coverage_ratio": coverage_ratio,
    }


def boundary_info_messages(
    boundary_info: dict[str, Any],
    step_hours: float,
    gap_fill: str = "zero",
) -> tuple[list[str], list[str]]:
    issues: list[str] = []
    warnings: list[str] = []
    gap_mode = str(gap_fill or "zero").strip().lower()
    detected_step = boundary_info.get("time_step_hours")
    if detected_step is not None and normalize_time_step_hours(detected_step) != step_hours:
        issues.append(
            f"\u4e0a\u6e38\u8fb9\u754c\u5165\u6d41\u65f6\u95f4\u6b65\u8bc6\u522b\u4e3a {int(detected_step)} \u5c0f\u65f6\uff0c\u4e0e\u5f53\u524d\u9879\u76ee\u65f6\u95f4\u6b65\u957f {int(step_hours)} \u5c0f\u65f6\u4e0d\u4e00\u81f4\u3002"
        )
    if boundary_info.get("duplicate_count", 0) > 0:
        sample = "\u3001".join(
            format_timestamp_for_display(ts, step_hours)
            for ts in boundary_info["duplicate_timestamps"][:3]
        )
        issues.append(f"\u4e0a\u6e38\u8fb9\u754c\u5165\u6d41\u5b58\u5728\u91cd\u590d\u65f6\u95f4\u6233 {boundary_info['duplicate_count']} \u4e2a\uff0c\u4f8b\u5982\uff1a{sample}")
    if boundary_info.get("negative_count", 0) > 0:
        issues.append(f"\u4e0a\u6e38\u8fb9\u754c\u5165\u6d41\u5b58\u5728 {boundary_info['negative_count']} \u6761\u8d1f\u6d41\u91cf\u8bb0\u5f55\u3002")
    missing_steps = list(boundary_info.get("missing_steps", []))
    if missing_steps:
        sample = "\u3001".join(format_timestamp_for_display(ts, step_hours) for ts in missing_steps[:3])
        if gap_mode == "interpolate":
            warnings.append(f"\u4e0a\u6e38\u8fb9\u754c\u5165\u6d41\u7f3a\u5c11 {len(missing_steps)} \u4e2a\u65f6\u95f4\u6b65\uff0c\u4f8b\u5982\uff1a{sample}\uff1b\u8fd0\u884c\u65f6\u4f1a\u6309\u7ebf\u6027\u63d2\u503c\u8865\u9f50\u3002")
        elif gap_mode in {"", "zero", "0"}:
            warnings.append(f"\u4e0a\u6e38\u8fb9\u754c\u5165\u6d41\u7f3a\u5c11 {len(missing_steps)} \u4e2a\u65f6\u95f4\u6b65\uff0c\u4f8b\u5982\uff1a{sample}\uff1b\u8fd0\u884c\u65f6\u4f1a\u6309 0 \u586b\u8865\u3002")
        else:
            issues.append(f"\u4e0a\u6e38\u8fb9\u754c\u5165\u6d41\u65f6\u95f4\u8986\u76d6\u4e0d\u5b8c\u6574\uff0c\u7f3a\u5c11 {len(missing_steps)} \u4e2a\u65f6\u95f4\u6b65\uff0c\u4f8b\u5982\uff1a{sample}")
    out_of_range_steps = list(boundary_info.get("out_of_range_steps", []))
    if out_of_range_steps:
        sample = "\u3001".join(format_timestamp_for_display(ts, step_hours) for ts in out_of_range_steps[:3])
        warnings.append(f"\u4e0a\u6e38\u8fb9\u754c\u5165\u6d41\u6709 {len(out_of_range_steps)} \u4e2a\u65f6\u95f4\u6b65\u843d\u5728\u5f53\u524d\u914d\u7f6e\u65f6\u95f4\u8303\u56f4\u4e4b\u5916\uff0c\u4f8b\u5982\uff1a{sample}")
    if boundary_info.get("invalid_rows", 0) > 0:
        warnings.append(f"\u4e0a\u6e38\u8fb9\u754c\u5165\u6d41\u4e2d\u6709 {boundary_info['invalid_rows']} \u884c\u65e0\u6cd5\u89e3\u6790\u65f6\u95f4\u6216\u6d41\u91cf\uff0c\u5df2\u5728\u8bfb\u53d6\u65f6\u5ffd\u7565\u3002")
    zero_count = int(boundary_info.get("zero_count", 0))
    valid_rows = max(1, int(boundary_info.get("valid_rows", 0)))
    if zero_count / valid_rows >= 0.8:
        warnings.append("\u4e0a\u6e38\u8fb9\u754c\u5165\u6d41\u4e2d\u96f6\u503c\u6bd4\u4f8b\u8d85\u8fc7 80%\uff0c\u8bf7\u786e\u8ba4\u7f3a\u6d4b\u503c\u6ca1\u6709\u88ab\u8bef\u5f53\u6210 0\u3002")
    return issues, warnings


def boundary_preview(
    csv_path_raw: str,
    date_field: str,
    flow_field: str,
    context: BoundaryPreviewContext,
    *,
    config_path_raw: str = "",
    expected_start: str = "",
    expected_end: str = "",
    expected_step_hours: float | None = None,
) -> dict[str, Any]:
    """Preview the first rows and stats of a boundary inflow CSV."""
    expected_index = None
    expected_step = expected_step_hours
    if config_path_raw:
        cfg_path = context.resolve_path(config_path_raw, must_exist=True)
        config = context.read_config(cfg_path)
        expected_index = context.build_expected_time_index(config)
        expected_step = context.normalize_time_step_hours(config.get("时间步长_小时", 24.0))
    elif expected_start and expected_end and expected_step_hours is not None:
        try:
            step = pd.Timedelta(hours=float(expected_step_hours))
            end_ts = pd.to_datetime(expected_end)
            if float(expected_step_hours) < 24.0 and context.is_date_only_string(expected_end):
                end_ts = end_ts + pd.Timedelta(days=1) - step
            expected_index = pd.date_range(
                start=pd.to_datetime(expected_start),
                end=end_ts,
                freq=step,
            )
            expected_step = context.normalize_time_step_hours(expected_step_hours)
        except Exception:
            expected_index = None
    data = context.inspect_boundary_csv(
        csv_path_raw,
        date_field=date_field,
        flow_field=flow_field,
        expected_index=expected_index,
        expected_step_hours=expected_step,
    )
    return {
        "columns": data["columns"],
        "total_rows": data["total_rows"],
        "valid_rows": data["valid_rows"],
        "invalid_rows": data["invalid_rows"],
        "duplicate_count": data["duplicate_count"],
        "time_step_hours": data["time_step_hours"],
        "expected_time_step_hours": data["expected_time_step_hours"],
        "suggested_calibration_mode": data.get("suggested_calibration_mode"),
        "negative_count": data["negative_count"],
        "zero_count": data["zero_count"],
        "coverage_ratio": data.get("coverage_ratio"),
        "expected_steps": data.get("expected_steps"),
        "missing_count": len(data.get("missing_steps", [])),
        "out_of_range_count": len(data.get("out_of_range_steps", [])),
        "date_range": data["date_range"],
        "flow_stats": data["flow_stats"],
        "preview": data["preview"],
    }
