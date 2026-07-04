# -*- coding: utf-8 -*-
from __future__ import annotations

import re
import unicodedata
import warnings
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd


CSV_ENCODINGS = ("utf-8-sig", "utf-8", "gb18030", "gbk")
EXCEL_SUFFIXES = {".xlsx", ".xls", ".xlsm"}
DEFAULT_MIN_DAILY_HOURS = 18
HYDROLOGICAL_DAY_START_HOUR = 8
MIN_ZERO_FILL_COVERAGE_RATIO = 0.5

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


def _normalize_step_hours(step_hours: Any) -> float:
    value = float(step_hours)
    return 1.0 if value <= 1.5 else 24.0


def _normalize_header(value: Any) -> str:
    text = unicodedata.normalize("NFKC", str(value or "")).strip().lower()
    text = text.replace("（", "(").replace("）", ")")
    text = text.replace("m^3", "m3").replace("^3", "3")
    text = re.sub(r"\s+", "", text)
    return text


NORMALIZED_DATE_HINTS = tuple(_normalize_header(item) for item in DATE_COLUMN_HINTS)
NORMALIZED_FLOW_HINTS = tuple(_normalize_header(item) for item in FLOW_COLUMN_HINTS)
NORMALIZED_FLOW_KEYWORDS = tuple(_normalize_header(item) for item in FLOW_KEYWORDS)


def _detect_series_step_hours(index: Any) -> float | None:
    timestamps = pd.DatetimeIndex(index).sort_values().drop_duplicates()
    if len(timestamps) < 2:
        return None
    diffs = timestamps.to_series().diff().dropna()
    if diffs.empty:
        return None
    median_hours = diffs.median() / pd.Timedelta(hours=1)
    return _normalize_step_hours(median_hours)


def read_boundary_inflow_table(path_like: str | Path) -> tuple[pd.DataFrame, str]:
    path = Path(path_like)
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
            return pd.read_excel(path, engine=engine), "excel"
        except ImportError as exc:
            raise ValueError(f"当前环境缺少读取 {suffix} 所需依赖：{engine}") from exc
    raise ValueError(f"暂不支持的上游边界入流文件类型：{suffix or '(无扩展名)'}")


def detect_time_column(frame: pd.DataFrame, preferred: str | None = None) -> str | None:
    candidates: list[str] = []
    normalized_lookup = {str(col): _normalize_header(col) for col in frame.columns}
    preferred_norm = _normalize_header(preferred) if preferred else ""
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


def detect_flow_column(
    frame: pd.DataFrame,
    *,
    preferred: str | None = None,
    excluded: list[str] | None = None,
) -> str | None:
    excluded_set = {str(item) for item in (excluded or [])}
    threshold = max(1, len(frame) // 3)
    normalized_lookup = {str(col): _normalize_header(col) for col in frame.columns}
    preferred_norm = _normalize_header(preferred) if preferred else ""
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


def _read_grouped_boundary_series(
    path: Path,
    *,
    date_field: str | None,
    flow_field: str | None,
) -> tuple[pd.Series, dict[str, Any]]:
    frame, file_kind = read_boundary_inflow_table(path)
    time_column = detect_time_column(frame, preferred=date_field)
    if time_column is None:
        raise KeyError(f"上游边界入流文件中未能识别时间字段；可用列：{list(frame.columns)}")
    flow_column = detect_flow_column(frame, preferred=flow_field, excluded=[time_column])
    if flow_column is None:
        raise KeyError(f"上游边界入流文件中未能识别流量字段；可用列：{list(frame.columns)}")

    valid = frame[[time_column, flow_column]].copy()
    valid[time_column] = pd.to_datetime(valid[time_column], errors="coerce")
    valid[flow_column] = pd.to_numeric(valid[flow_column], errors="coerce")
    valid = valid.dropna(subset=[time_column, flow_column]).copy()
    if valid.empty:
        raise ValueError("上游边界入流文件中没有可识别的有效时间和流量记录。")
    if (valid[flow_column] < 0).any():
        raise ValueError("上游边界入流文件中存在负流量，请先修正数据。")

    grouped = valid.groupby(time_column, as_index=True)[flow_column].mean().sort_index().astype("float64")
    return grouped, {
        "file_kind": file_kind,
        "date_field": str(time_column),
        "flow_field": str(flow_column),
        "valid_rows": int(len(valid)),
    }


def read_boundary_inflow_series(
    csv_path,
    dates,
    date_field="date",
    flow_field="inflow_m3s",
    gap_fill="zero",
    expected_step_hours=None,
):
    if not csv_path:
        return np.zeros(len(dates), dtype=np.float64), False

    path = Path(csv_path)
    if not path.exists():
        raise FileNotFoundError(f"上游边界入流文件不存在：{path}")

    grouped, _meta = _read_grouped_boundary_series(
        path,
        date_field=date_field,
        flow_field=flow_field,
    )
    detected_step_hours = _detect_series_step_hours(grouped.index)
    effective_series = grouped
    if expected_step_hours is not None and detected_step_hours is not None:
        expected_step = _normalize_step_hours(expected_step_hours)
        if detected_step_hours != expected_step:
            if expected_step >= 24.0 and detected_step_hours <= 1.5:
                effective_series, _aggregation = _aggregate_hourly_series_to_daily(grouped)
            else:
                raise ValueError(
                    f"上游边界入流时间步识别为 {int(detected_step_hours)} 小时，"
                    f"与当前模型时间步长 {int(expected_step)} 小时不一致。"
                )

    target_index = pd.DatetimeIndex(dates)
    series = effective_series.reindex(target_index)
    gap_mode = str(gap_fill).strip().lower()
    original_missing = series.isna()
    original_covered_count = int((~original_missing).sum())
    expected_count = int(len(target_index))
    coverage_ratio = float(original_covered_count / expected_count) if expected_count > 0 else 1.0
    if expected_step_hours is not None and expected_count > 0:
        if original_covered_count == 0:
            raise ValueError(
                "上游边界入流文件没有与当前模拟时段重叠的时间步，"
                "不能在 zero 填补模式下静默按全 0 入流运行。"
            )
        if gap_mode in {"", "zero", "0"} and coverage_ratio < MIN_ZERO_FILL_COVERAGE_RATIO:
            warnings.warn(
                f"上游边界入流与当前模拟时段仅重叠 {coverage_ratio * 100:.1f}% 时间步，"
                "缺失部分将按 0 m3/s 填补；请确认这不是时间范围或时区配置错误。",
                RuntimeWarning,
                stacklevel=2,
            )
    if gap_mode == "interpolate":
        series = series.interpolate(method="linear", limit_direction="both")
    elif gap_mode in {"", "zero", "0"}:
        series = series.fillna(0.0)
    else:
        raise ValueError(f"不支持的上游边界入流缺失填补方式：{gap_fill}")

    if expected_step_hours is not None and series.isna().any():
        missing = target_index[series.isna()]
        sample = "、".join(pd.Timestamp(item).strftime("%Y-%m-%d %H:%M") for item in missing[:3])
        raise ValueError(
            f"上游边界入流时间覆盖不完整，缺少 {int(series.isna().sum())} 个时间步，"
            f"例如：{sample or '请检查原始文件'}"
        )
    series = series.fillna(0.0).astype(float)
    return series.values.astype(np.float64), True
