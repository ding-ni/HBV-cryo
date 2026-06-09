# -*- coding: utf-8 -*-
from __future__ import annotations

import re
import unicodedata
from pathlib import Path
from typing import Any

import pandas as pd


PROFILE_DAILY = "daily"
PROFILE_HOURLY = "hourly"

OBSERVED_DATE_COLUMN_HINTS = ("date", "datetime", "time", "日期", "时间")
OBSERVED_FLOW_COLUMN_HINTS = (
    "discharge (m3/s)",
    "discharge",
    "flow",
    "streamflow",
    "runoff",
    "q_obs",
    "流量",
    "径流",
    "观测流量",
    "观测径流",
)
FLOW_KEYWORDS = (
    "discharge",
    "flow",
    "streamflow",
    "runoff",
    "qobs",
    "流量",
    "径流",
)

CSV_ENCODINGS = ("utf-8-sig", "utf-8", "gb18030")
EXCEL_SUFFIXES = {".xlsx", ".xls", ".xlsm"}
DEFAULT_MIN_DAILY_HOURS = 18
HYDROLOGICAL_DAY_START_HOUR = 8


def normalize_time_step_hours(value: Any) -> float:
    hours = float(value)
    return 1.0 if hours <= 1.5 else 24.0


def normalize_observed_header(value: Any) -> str:
    text = unicodedata.normalize("NFKC", str(value or "")).strip().lower()
    text = text.replace("（", "(").replace("）", ")")
    text = text.replace("³", "3")
    text = text.replace("^3", "3")
    text = text.replace("m^3", "m3")
    text = re.sub(r"\s+", "", text)
    return text


def strip_flow_unit_suffix(value: Any) -> str:
    text = normalize_observed_header(value)
    text = re.sub(r"\(?m3/s\)?$", "", text)
    text = re.sub(r"\(?m3s-1\)?$", "", text)
    return text.strip("()")


NORMALIZED_DATE_HINTS = tuple(normalize_observed_header(item) for item in OBSERVED_DATE_COLUMN_HINTS)
NORMALIZED_FLOW_HINTS = tuple(normalize_observed_header(item) for item in OBSERVED_FLOW_COLUMN_HINTS)
NORMALIZED_FLOW_BASE_HINTS = tuple(strip_flow_unit_suffix(item) for item in OBSERVED_FLOW_COLUMN_HINTS)
NORMALIZED_FLOW_KEYWORDS = tuple(normalize_observed_header(item) for item in FLOW_KEYWORDS)


def infer_profile_from_hours(step_hours: float | None) -> str:
    return PROFILE_HOURLY if (step_hours is not None and float(step_hours) <= 1.5) else PROFILE_DAILY


def read_observed_table(path_like: str | Path) -> tuple[pd.DataFrame, str]:
    path = Path(path_like)
    suffix = path.suffix.lower()
    if suffix == ".csv":
        last_exc: Exception | None = None
        for encoding in CSV_ENCODINGS:
            try:
                return pd.read_csv(path, encoding=encoding), "csv"
            except UnicodeDecodeError as exc:
                last_exc = exc
        if last_exc is not None:
            raise ValueError(f"无法读取观测径流 CSV 编码：{path}") from last_exc
        return pd.read_csv(path), "csv"
    if suffix in EXCEL_SUFFIXES:
        engine = "xlrd" if suffix == ".xls" else "openpyxl"
        try:
            return pd.read_excel(path, engine=engine), "excel"
        except ImportError as exc:
            raise ValueError(f"当前环境缺少读取 {suffix} 所需依赖：{engine}") from exc
    raise ValueError(f"暂不支持的观测径流文件类型：{suffix or path.suffix}")


def detect_time_column(frame: pd.DataFrame, preferred: str | None = None) -> str | None:
    candidates: list[str] = []
    normalized_lookup = {str(col): normalize_observed_header(col) for col in frame.columns}
    if preferred and preferred in frame.columns:
        candidates.append(preferred)
    for preferred_name in NORMALIZED_DATE_HINTS:
        for column, normalized in normalized_lookup.items():
            if normalized == preferred_name and column not in candidates:
                candidates.append(column)
    candidates.extend([str(col) for col in frame.columns if str(col) not in candidates])
    threshold = max(1, len(frame) // 3)
    for column in candidates:
        parsed = pd.to_datetime(frame[column], errors="coerce")
        if parsed.notna().sum() >= threshold:
            return column
    return None


def detect_series_step_hours(index_like: Any) -> float | None:
    timestamps = pd.DatetimeIndex(index_like).sort_values().drop_duplicates()
    if len(timestamps) < 2:
        return None
    diffs = timestamps.to_series().diff().dropna()
    if diffs.empty:
        return None
    median_hours = diffs.median() / pd.Timedelta(hours=1)
    return normalize_time_step_hours(median_hours)


def _numeric_candidate_count(series: pd.Series) -> int:
    numeric = pd.to_numeric(series, errors="coerce")
    return int(numeric.notna().sum())


def detect_observed_flow_column(frame: pd.DataFrame, *, excluded: list[str] | None = None) -> str | None:
    excluded_set = {str(item) for item in (excluded or [])}
    threshold = max(1, len(frame) // 3)
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
        normalized = normalize_observed_header(column_name)
        base_name = strip_flow_unit_suffix(column_name)
        matched_rank = None
        for idx, hint in enumerate(NORMALIZED_FLOW_HINTS):
            if normalized == hint:
                matched_rank = idx
                break
        if matched_rank is None:
            for idx, hint in enumerate(NORMALIZED_FLOW_BASE_HINTS):
                if base_name == hint:
                    matched_rank = idx
                    break
        if matched_rank is not None:
            exact_candidates.append((matched_rank * 1000 + order, column_name))
            continue
        if any(keyword in normalized or keyword in base_name for keyword in NORMALIZED_FLOW_KEYWORDS):
            keyword_candidates.append(column_name)

    if exact_candidates:
        exact_candidates.sort(key=lambda item: item[0])
        return exact_candidates[0][1]
    if len(keyword_candidates) == 1:
        return keyword_candidates[0]
    if len(keyword_candidates) > 1:
        raise ValueError(
            "未能自动判定流量列，存在多个候选流量列："
            + "、".join(keyword_candidates[:6])
        )
    if len(numeric_candidates) == 1:
        return numeric_candidates[0]
    if len(numeric_candidates) > 1:
        raise ValueError(
            "未能自动判定流量列，存在多个数值列："
            + "、".join(numeric_candidates[:6])
        )
    return None


def _aggregate_hourly_series_to_daily(
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


def inspect_observed_discharge(
    path_like: str | Path,
    *,
    date_field: str | None = None,
    expected_index: pd.DatetimeIndex | None = None,
    target_step_hours: float | None = None,
    allow_hourly_to_daily: bool = True,
    min_daily_hours: int = DEFAULT_MIN_DAILY_HOURS,
    return_series: bool = False,
) -> dict[str, Any]:
    path = Path(path_like).expanduser().resolve(strict=False)
    frame, file_kind = read_observed_table(path)
    time_column = detect_time_column(frame, preferred=date_field)
    if time_column is None:
        raise ValueError("未能在观测径流文件中识别时间列。")
    flow_column = detect_observed_flow_column(frame, excluded=[time_column])
    if flow_column is None:
        raise ValueError("未能在观测径流文件中识别流量列。")

    valid = frame[[time_column, flow_column]].copy()
    valid[time_column] = pd.to_datetime(valid[time_column], errors="coerce")
    valid[flow_column] = pd.to_numeric(valid[flow_column], errors="coerce")
    valid = valid.dropna(subset=[time_column, flow_column]).copy()
    if valid.empty:
        raise ValueError("观测径流文件中没有可识别的有效时间和流量记录。")

    valid.sort_values(time_column, inplace=True)
    duplicate_mask = valid.duplicated(subset=[time_column], keep=False)
    duplicate_timestamps = valid.loc[duplicate_mask, time_column].drop_duplicates().sort_values().tolist()
    grouped = valid.groupby(time_column, as_index=True)[flow_column].mean().sort_index().astype("float64")
    detected_step_hours = detect_series_step_hours(grouped.index) or 24.0
    effective_series = grouped
    effective_step_hours = detected_step_hours
    resampled_to_daily = False
    aggregation_meta: dict[str, Any] | None = None

    normalized_target = None
    if target_step_hours is not None:
        normalized_target = normalize_time_step_hours(target_step_hours)
    elif expected_index is not None:
        normalized_target = detect_series_step_hours(expected_index) or 24.0

    if normalized_target is not None and detected_step_hours != normalized_target:
        if normalized_target >= 24.0 and detected_step_hours <= 1.5 and allow_hourly_to_daily:
            effective_series, aggregation_meta = _aggregate_hourly_series_to_daily(
                grouped,
                min_daily_hours=min_daily_hours,
            )
            effective_step_hours = 24.0
            resampled_to_daily = True
        else:
            raise ValueError(
                f"观测径流时间步识别为 {int(detected_step_hours)} 小时，与当前项目时间步长 {int(normalized_target)} 小时不一致。"
            )

    expected_set: set[pd.Timestamp] | None = None
    actual_index = pd.DatetimeIndex(effective_series.dropna().index)
    coverage_ratio = None
    missing_steps: list[pd.Timestamp] = []
    out_of_range_steps: list[pd.Timestamp] = []
    matched_steps = int(actual_index.size)
    if expected_index is not None:
        expected_list = list(pd.DatetimeIndex(expected_index))
        expected_set = set(expected_list)
        actual_set = set(actual_index.tolist())
        missing_steps = [ts for ts in expected_list if ts not in actual_set]
        out_of_range_steps = [ts for ts in actual_index.tolist() if ts not in expected_set]
        coverage_ratio = (len(expected_set & actual_set) / len(expected_set)) if expected_set else None
        if expected_set:
            matched_steps = int(len(expected_set & actual_set))

    result: dict[str, Any] = {
        "path": str(path),
        "file_kind": file_kind,
        "date_field": str(time_column),
        "flow_field": str(flow_column),
        "row_count": int(len(frame)),
        "valid_rows": int(len(valid)),
        "invalid_rows": int(len(frame) - len(valid)),
        "duplicate_count": int(len(duplicate_timestamps)),
        "duplicate_timestamps": [str(pd.Timestamp(item)) for item in duplicate_timestamps],
        "start": valid[time_column].iloc[0].strftime("%Y-%m-%d %H:%M"),
        "end": valid[time_column].iloc[-1].strftime("%Y-%m-%d %H:%M"),
        "suggested_time_step_hours": float(detected_step_hours),
        "suggested_calibration_mode": infer_profile_from_hours(detected_step_hours),
        "effective_time_step_hours": float(effective_step_hours),
        "effective_calibration_mode": infer_profile_from_hours(effective_step_hours),
        "target_time_step_hours": float(normalized_target) if normalized_target is not None else None,
        "resampled_to_daily": bool(resampled_to_daily),
        "matched_steps": matched_steps,
        "coverage_ratio": coverage_ratio,
        "missing_steps_count": len(missing_steps),
        "missing_steps_sample": [str(pd.Timestamp(item)) for item in missing_steps[:3]],
        "out_of_range_steps_count": len(out_of_range_steps),
        "out_of_range_steps_sample": [str(pd.Timestamp(item)) for item in out_of_range_steps[:3]],
        "daily_aggregation": aggregation_meta,
    }
    if return_series:
        result["series"] = effective_series
    return result
