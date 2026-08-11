#!/usr/bin/env python
# -*- coding: utf-8 -*-
from __future__ import annotations

import copy
from dataclasses import dataclass
from pathlib import Path
import re
import threading
import time
from typing import Any, Callable
import unicodedata

import pandas as pd

from services.time_utils import (
    detect_series_step_hours,
    format_timestamp_for_display,
    normalize_time_step_hours,
    summarize_time_coverage,
    time_step_missing_text,
)


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
CSV_ENCODINGS = ("utf-8-sig", "utf-8", "gb18030", "gbk")
EXCEL_SUFFIXES = {".xlsx", ".xls", ".xlsm"}
DEFAULT_MIN_DAILY_HOURS = 18
HYDROLOGICAL_DAY_START_HOUR = 8
DATE_COLUMN_HINTS = ("date", "datetime", "time", "日期", "时间")
FLOW_COLUMN_HINTS = (
    "flow",
    "inflow_m3s",
    "boundary_inflow",
    "q_boundary",
    "q",
    "discharge",
    "streamflow",
    "runoff",
    "流量",
    "径流",
    "入流",
    "上游边界入流",
)
FLOW_KEYWORDS = ("flow", "inflow", "discharge", "streamflow", "runoff", "q", "流量", "径流", "入流")


def _normalize_boundary_header(value: Any) -> str:
    text = unicodedata.normalize("NFKC", str(value or "")).strip().lower()
    text = text.replace("（", "(").replace("）", ")")
    text = text.replace("m^3", "m3").replace("^3", "3")
    text = re.sub(r"\s+", "", text)
    return text


NORMALIZED_DATE_HINTS = tuple(_normalize_boundary_header(item) for item in DATE_COLUMN_HINTS)
NORMALIZED_FLOW_HINTS = tuple(_normalize_boundary_header(item) for item in FLOW_COLUMN_HINTS)
NORMALIZED_FLOW_KEYWORDS = tuple(_normalize_boundary_header(item) for item in FLOW_KEYWORDS)


def read_boundary_inflow_table(path: Path) -> tuple[pd.DataFrame, str]:
    suffix = path.suffix.lower()
    if suffix == ".csv":
        last_exc: Exception | None = None
        for encoding in CSV_ENCODINGS:
            try:
                return pd.read_csv(path, encoding=encoding), "csv"
            except UnicodeDecodeError as exc:
                last_exc = exc
        raise ValueError(f"无法读取上游边界入流 CSV 编码：{path}") from last_exc
    if suffix in EXCEL_SUFFIXES:
        engine = "xlrd" if suffix == ".xls" else "openpyxl"
        try:
            sheets = pd.read_excel(path, engine=engine, sheet_name=None)
        except ImportError as exc:
            raise ValueError(f"当前环境缺少读取 {suffix} 所需依赖：{engine}") from exc
        candidates: list[tuple[int, int, str, pd.DataFrame]] = []
        for order, (sheet_name, frame) in enumerate(sheets.items()):
            if frame is None or frame.empty:
                continue
            time_column = detect_boundary_time_column(frame)
            if time_column is None:
                continue
            try:
                flow_column = detect_boundary_flow_column(frame, excluded=[time_column])
            except ValueError:
                continue
            if flow_column is None:
                continue
            valid_rows = int(
                (
                    pd.to_datetime(frame[time_column], errors="coerce").notna()
                    & pd.to_numeric(frame[flow_column], errors="coerce").notna()
                ).sum()
            )
            if valid_rows:
                candidates.append((valid_rows, -order, str(sheet_name), frame))
        if not candidates:
            raise ValueError(f"未在 Excel 的任何工作表中识别到有效时间列和流量列：{path}")
        _, _, sheet_name, selected = max(candidates, key=lambda item: (item[0], item[1]))
        selected = selected.copy()
        selected.attrs["hbv_sheet_name"] = sheet_name
        return selected, "excel"
    raise ValueError(f"暂不支持的上游边界入流文件类型：{suffix or '(无扩展名)'}")


def detect_boundary_time_column(frame: pd.DataFrame, preferred: str | None = None) -> str | None:
    candidates: list[str] = []
    normalized_lookup = {str(col): _normalize_boundary_header(col) for col in frame.columns}
    preferred_norm = _normalize_boundary_header(preferred) if preferred else ""
    if preferred:
        if preferred in frame.columns:
            candidates.append(str(preferred))
        else:
            for column, normalized in normalized_lookup.items():
                if normalized == preferred_norm:
                    candidates.append(column)
                    break
    for hint in NORMALIZED_DATE_HINTS:
        for column, normalized in normalized_lookup.items():
            if normalized == hint and column not in candidates:
                candidates.append(column)
    candidates.extend([str(col) for col in frame.columns if str(col) not in candidates])

    threshold = max(1, len(frame) // 3)
    for column in candidates:
        parsed = pd.to_datetime(frame[column], errors="coerce")
        if parsed.notna().sum() >= threshold:
            return column
    return None


def _numeric_candidate_count(series: pd.Series) -> int:
    return int(pd.to_numeric(series, errors="coerce").notna().sum())


def detect_boundary_flow_column(
    frame: pd.DataFrame,
    *,
    preferred: str | None = None,
    excluded: list[str] | None = None,
) -> str | None:
    excluded_set = {str(item) for item in (excluded or [])}
    threshold = max(1, len(frame) // 3)
    normalized_lookup = {str(col): _normalize_boundary_header(col) for col in frame.columns}
    preferred_norm = _normalize_boundary_header(preferred) if preferred else ""
    if preferred:
        preferred_candidates = []
        if preferred in frame.columns:
            preferred_candidates.append(str(preferred))
        preferred_candidates.extend(
            column for column, normalized in normalized_lookup.items()
            if normalized == preferred_norm and column not in preferred_candidates
        )
        for column in preferred_candidates:
            if column not in excluded_set and _numeric_candidate_count(frame[column]) >= threshold:
                return column

    exact_candidates: list[tuple[int, str]] = []
    keyword_candidates: list[str] = []
    numeric_candidates: list[str] = []
    for order, column in enumerate(frame.columns):
        column_name = str(column)
        if column_name in excluded_set:
            continue
        numeric_count = _numeric_candidate_count(frame[column_name])
        if numeric_count < threshold:
            continue
        numeric_candidates.append(column_name)
        normalized = normalized_lookup[column_name]
        if normalized in NORMALIZED_FLOW_HINTS:
            exact_candidates.append((NORMALIZED_FLOW_HINTS.index(normalized) * 1000 + order, column_name))
            continue
        if any(keyword in normalized for keyword in NORMALIZED_FLOW_KEYWORDS):
            keyword_candidates.append(column_name)

    if exact_candidates:
        exact_candidates.sort(key=lambda item: item[0])
        return exact_candidates[0][1]
    if len(keyword_candidates) == 1:
        return keyword_candidates[0]
    if len(keyword_candidates) > 1:
        raise ValueError("未能自动判定流量列，存在多个候选流量列：" + "、".join(keyword_candidates[:6]))
    if len(numeric_candidates) == 1:
        return numeric_candidates[0]
    if len(numeric_candidates) > 1:
        raise ValueError("未能自动判定流量列，存在多个数值列：" + "、".join(numeric_candidates[:6]))
    return None


def aggregate_hourly_boundary_to_daily(
    grouped: pd.Series,
    *,
    min_daily_hours: int = DEFAULT_MIN_DAILY_HOURS,
    day_start_hour: int = HYDROLOGICAL_DAY_START_HOUR,
) -> tuple[pd.Series, dict[str, Any]]:
    if grouped.empty:
        return grouped.astype("float64"), {
            "enabled": True,
            "min_hours_per_day": int(min_daily_hours),
            "day_start_hour": int(day_start_hour),
            "day_label": "start",
            "valid_days": 0,
            "insufficient_days": 0,
            "hourly_rows": 0,
        }
    hydrological_day = (pd.DatetimeIndex(grouped.index) - pd.Timedelta(hours=int(day_start_hour))).normalize()
    daily_frame = grouped.groupby(hydrological_day).agg(["mean", "count"])
    daily_series = daily_frame["mean"].where(daily_frame["count"] >= int(min_daily_hours))
    return daily_series.astype("float64"), {
        "enabled": True,
        "min_hours_per_day": int(min_daily_hours),
        "day_start_hour": int(day_start_hour),
        "day_label": "start",
        "valid_days": int(daily_series.notna().sum()),
        "insufficient_days": int((daily_frame["count"] < int(min_daily_hours)).sum()),
        "hourly_rows": int(len(grouped)),
    }


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
    flow_field: str = "flow",
) -> dict[str, Any]:
    path = context.resolve_path(csv_path_raw, must_exist=True)
    cache_key = f"{path.resolve(strict=False)}|{date_field}|{flow_field}"
    signature = _file_signature(path)
    with BOUNDARY_CSV_CACHE_LOCK:
        cached = BOUNDARY_CSV_CACHE.get(cache_key)
        if cached and cached.get("signature") == signature:
            cached["used_at"] = time.time()
            return copy.deepcopy(cached["data"])

    frame, file_kind = read_boundary_inflow_table(path)
    actual_date_field = detect_boundary_time_column(frame, preferred=date_field)
    if actual_date_field is None:
        raise ValueError(f"找不到时间字段 '{date_field}'，也未能自动识别时间列；可用列：{list(frame.columns)}")
    actual_flow_field = detect_boundary_flow_column(frame, preferred=flow_field, excluded=[actual_date_field])
    if actual_flow_field is None:
        raise ValueError(f"找不到流量字段 '{flow_field}'，也未能自动识别流量列；可用列：{list(frame.columns)}")

    frame = frame.copy()
    frame[actual_date_field] = pd.to_datetime(frame[actual_date_field], errors="coerce")
    frame[actual_flow_field] = pd.to_numeric(frame[actual_flow_field], errors="coerce")
    valid = frame.dropna(subset=[actual_date_field, actual_flow_field]).copy()
    if valid.empty:
        raise ValueError("\u4e0a\u6e38\u8fb9\u754c\u5165\u6d41\u6587\u4ef6\u4e2d\u6ca1\u6709\u53ef\u8bc6\u522b\u7684\u6709\u6548\u65f6\u95f4\u548c\u6d41\u91cf\u8bb0\u5f55\u3002")

    valid.sort_values(actual_date_field, inplace=True)
    duplicate_mask = valid.duplicated(subset=[actual_date_field], keep=False)
    duplicate_timestamps = valid.loc[duplicate_mask, actual_date_field].drop_duplicates().sort_values().tolist()
    grouped_series = valid.groupby(actual_date_field, as_index=True)[actual_flow_field].mean().sort_index().astype("float64")
    actual_index = pd.DatetimeIndex(grouped_series.dropna().index)
    step_hours = detect_series_step_hours(pd.Series(actual_index.tolist()))
    flow_values = valid[actual_flow_field].astype(float)

    preview_rows = []
    for _, row in valid.head(10).iterrows():
        preview_rows.append({actual_date_field: str(row[actual_date_field]), actual_flow_field: float(row[actual_flow_field])})

    base = {
        "columns": list(frame.columns),
        "file_kind": file_kind,
        "sheet_name": frame.attrs.get("hbv_sheet_name"),
        "date_field": str(actual_date_field),
        "flow_field": str(actual_flow_field),
        "total_rows": int(len(frame)),
        "valid_rows": int(len(valid)),
        "invalid_rows": int(len(frame) - len(valid)),
        "duplicate_timestamps": [pd.Timestamp(item) for item in duplicate_timestamps],
        "duplicate_count": int(len(duplicate_timestamps)),
        "time_step_hours": step_hours,
        "source_time_step_hours": step_hours,
        "effective_time_step_hours": step_hours,
        "resampled_to_daily": False,
        "daily_aggregation": None,
        "negative_count": int((flow_values < 0).sum()),
        "zero_count": int((flow_values == 0).sum()),
        "date_range": {
            "start": str(valid[actual_date_field].min()),
            "end": str(valid[actual_date_field].max()),
        },
        "flow_stats": {
            "min": round(float(flow_values.min()), 4),
            "max": round(float(flow_values.max()), 4),
            "mean": round(float(flow_values.mean()), 4),
        },
        "preview": preview_rows,
        "suggested_calibration_mode": context.profile_hourly if step_hours is not None and step_hours <= 1.5 else context.profile_daily,
        "_actual_index": actual_index,
        "_grouped_series": grouped_series,
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
    flow_field: str = "flow",
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
    grouped_series = base.pop("_grouped_series", None)
    source_step_hours = base.get("source_time_step_hours")
    normalized_expected_step = normalize_time_step_hours(expected_step_hours) if expected_step_hours is not None else None
    if normalized_expected_step is None and expected_index is not None:
        normalized_expected_step = detect_series_step_hours(pd.Series(pd.DatetimeIndex(expected_index).tolist()))
    if (
        grouped_series is not None
        and normalized_expected_step is not None
        and source_step_hours is not None
        and normalize_time_step_hours(source_step_hours) != normalized_expected_step
        and normalized_expected_step >= 24.0
        and normalize_time_step_hours(source_step_hours) <= 1.5
    ):
        effective_series, aggregation_meta = aggregate_hourly_boundary_to_daily(grouped_series)
        actual_index = pd.DatetimeIndex(effective_series.dropna().index)
        base["time_step_hours"] = 24.0
        base["effective_time_step_hours"] = 24.0
        base["resampled_to_daily"] = True
        base["daily_aggregation"] = aggregation_meta
        base["suggested_calibration_mode"] = context.profile_daily
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

    coverage = summarize_time_coverage(actual_index, normalized_expected_step or source_step_hours or 24.0)

    return {
        **base,
        "expected_time_step_hours": expected_step_hours if expected_step_hours is not None else normalized_expected_step,
        "expected_steps": expected_steps,
        "missing_steps": missing_steps,
        "out_of_range_steps": out_of_range_steps,
        "coverage_ratio": coverage_ratio,
        "period_summary": coverage["period_summary"],
    }


def boundary_info_messages(
    boundary_info: dict[str, Any],
    step_hours: float,
    gap_fill: str = "preserve_missing",
) -> tuple[list[str], list[str]]:
    issues: list[str] = []
    warnings: list[str] = []
    gap_mode = str(gap_fill or "preserve_missing").strip().lower()
    detected_step = boundary_info.get("time_step_hours")
    if detected_step is not None and normalize_time_step_hours(detected_step) != step_hours:
        issues.append(
            f"\u4e0a\u6e38\u8fb9\u754c\u5165\u6d41\u65f6\u95f4\u6b65\u8bc6\u522b\u4e3a {int(detected_step)} \u5c0f\u65f6\uff0c\u4e0e\u5f53\u524d\u9879\u76ee\u65f6\u95f4\u6b65\u957f {int(step_hours)} \u5c0f\u65f6\u4e0d\u4e00\u81f4\u3002"
        )
    if boundary_info.get("resampled_to_daily"):
        aggregation = dict(boundary_info.get("daily_aggregation") or {})
        start_hour = int(aggregation.get("day_start_hour", HYDROLOGICAL_DAY_START_HOUR) or HYDROLOGICAL_DAY_START_HOUR)
        warnings.append(
            f"上游边界入流已从小时尺度按水文日（{start_hour:02d}:00 至次日 {start_hour:02d}:00）"
            f"聚合为日平均流量；有效日数 {int(aggregation.get('valid_days', 0) or 0)} 天，"
            f"小时覆盖不足天数 {int(aggregation.get('insufficient_days', 0) or 0)} 天。"
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
        missing_text = time_step_missing_text(len(missing_steps), step_hours)
        if gap_mode == "interpolate":
            warnings.append(f"上游边界入流缺少 {missing_text}，例如：{sample}；运行时会按线性插值补齐。")
        elif gap_mode in {"", "zero", "0"}:
            warnings.append(f"上游边界入流缺少 {missing_text}，例如：{sample}；运行时会按 0 填补。")
        else:
            issues.append(f"上游边界入流时间覆盖不完整，缺少 {missing_text}，例如：{sample}")
    out_of_range_steps = list(boundary_info.get("out_of_range_steps", []))
    if out_of_range_steps:
        sample = "\u3001".join(format_timestamp_for_display(ts, step_hours) for ts in out_of_range_steps[:3])
        warnings.append(
            f"上游边界入流有 {time_step_missing_text(len(out_of_range_steps), step_hours)}落在当前配置时间范围之外，"
            f"例如：{sample}"
        )
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
        "file_kind": data.get("file_kind"),
        "sheet_name": data.get("sheet_name"),
        "date_field": data.get("date_field"),
        "flow_field": data.get("flow_field"),
        "total_rows": data["total_rows"],
        "valid_rows": data["valid_rows"],
        "invalid_rows": data["invalid_rows"],
        "duplicate_count": data["duplicate_count"],
        "time_step_hours": data["time_step_hours"],
        "source_time_step_hours": data.get("source_time_step_hours"),
        "effective_time_step_hours": data.get("effective_time_step_hours"),
        "expected_time_step_hours": data["expected_time_step_hours"],
        "resampled_to_daily": data.get("resampled_to_daily", False),
        "daily_aggregation": data.get("daily_aggregation"),
        "suggested_calibration_mode": data.get("suggested_calibration_mode"),
        "negative_count": data["negative_count"],
        "zero_count": data["zero_count"],
        "coverage_ratio": data.get("coverage_ratio"),
        "period_summary": data.get("period_summary"),
        "expected_steps": data.get("expected_steps"),
        "missing_count": len(data.get("missing_steps", [])),
        "out_of_range_count": len(data.get("out_of_range_steps", [])),
        "date_range": data["date_range"],
        "flow_stats": data["flow_stats"],
        "preview": data["preview"],
    }
