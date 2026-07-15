from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import pandas as pd


def normalize_time_step_hours(value: Any) -> float:
    try:
        numeric = float(value)
    except Exception:
        numeric = 24.0
    return 1.0 if numeric <= 1.5 else 24.0


def is_date_only_string(value: Any) -> bool:
    if not isinstance(value, str):
        return False
    text = value.strip()
    return bool(text) and (" " not in text) and ("T" not in text) and len(text) <= 10


def format_timestamp_for_display(timestamp: pd.Timestamp, step_hours: float) -> str:
    ts = pd.Timestamp(timestamp)
    if normalize_time_step_hours(step_hours) >= 24.0 and ts.hour == 0 and ts.minute == 0 and ts.second == 0:
        return ts.strftime("%Y-%m-%d")
    return ts.strftime("%Y-%m-%d %H:%M")


def time_step_count_text(count: int, step_hours: float) -> str:
    """Describe a hydrological series length in calendar units, not implementation steps."""
    numeric_count = int(count)
    step = float(step_hours)
    if abs(step - 1.0) <= 1e-9:
        return f"{numeric_count} 小时"
    if abs(step - 24.0) <= 1e-9:
        return f"{numeric_count} 日"
    return f"{numeric_count} 个 {step:g} 小时时段"


def time_step_missing_text(count: int, step_hours: float) -> str:
    step = float(step_hours)
    if abs(step - 1.0) <= 1e-9:
        return f"{int(count)} 小时"
    if abs(step - 24.0) <= 1e-9:
        return f"{int(count)} 日"
    return f"{int(count)} 个时段"


def summarize_time_coverage(timestamps: Any, step_hours: float) -> dict[str, Any]:
    """Return a user-facing start/end/continuity summary for a dated series."""
    ordered = sorted({pd.Timestamp(item) for item in timestamps if pd.notna(item)})
    if not ordered:
        return {
            "start_time": None,
            "end_time": None,
            "count": 0,
            "missing_times": [],
            "continuous": False,
            "period_summary": "未识别到有效时间范围",
        }
    step = float(step_hours)
    start = ordered[0]
    end = ordered[-1]
    expected = pd.date_range(start=start, end=end, freq=pd.Timedelta(hours=step))
    actual = set(ordered)
    missing = [pd.Timestamp(item) for item in expected if pd.Timestamp(item) not in actual]
    if not missing:
        continuity = "逐小时连续无缺测" if abs(step - 1.0) <= 1e-9 else (
            "逐日连续无缺测" if abs(step - 24.0) <= 1e-9 else "时序连续无缺测"
        )
    else:
        continuity = f"内部缺少 {time_step_missing_text(len(missing), step)}"
    return {
        "start_time": start,
        "end_time": end,
        "count": len(ordered),
        "missing_times": missing,
        "continuous": not missing,
        "period_summary": (
            f"{format_timestamp_for_display(start, step)} 至 "
            f"{format_timestamp_for_display(end, step)}，共 {time_step_count_text(len(ordered), step)}，{continuity}"
        ),
    }


def detect_series_step_hours(timestamps: pd.Series) -> float | None:
    diffs = timestamps.sort_values().drop_duplicates().diff().dropna()
    if diffs.empty:
        return None
    median_hours = diffs.median() / pd.Timedelta(hours=1)
    if median_hours <= 1.5:
        return 1.0
    return 24.0


DATE_PATTERNS = [
    ("%Y.%m.%d.%H.%M", [r"\d{4}\.\d{2}\.\d{2}\.\d{2}\.\d{2}"]),
    ("%Y.%m.%d.%H", [r"\d{4}\.\d{2}\.\d{2}\.\d{2}"]),
    ("%Y-%m-%d %H:%M", [r"\d{4}-\d{2}-\d{2} \d{2}:\d{2}"]),
    ("%Y-%m-%dT%H:%M", [r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}"]),
    ("%Y.%m.%d", [r"\d{4}\.\d{2}\.\d{2}"]),
    ("%Y-%m-%d", [r"\d{4}-\d{2}-\d{2}"]),
]


def parse_time_from_name(name: str) -> pd.Timestamp | None:
    stem = Path(name).stem
    for fmt, patterns in DATE_PATTERNS:
        for pattern in patterns:
            match = re.search(pattern, stem)
            if match:
                try:
                    return pd.to_datetime(match.group(0), format=fmt)
                except Exception:
                    pass
    try:
        return pd.to_datetime(stem)
    except Exception:
        return None


def expected_warmup_end(time_values: dict[str, pd.Timestamp], step_hours: float) -> pd.Timestamp | None:
    calib_start = time_values.get("率定开始")
    if calib_start is None:
        return None
    return calib_start - pd.Timedelta(hours=normalize_time_step_hours(step_hours))


def time_sequence_messages(time_values: dict[str, pd.Timestamp], step_hours: float) -> list[str]:
    messages: list[str] = []
    ordered_pairs = [
        ("预热开始", "预热结束"),
        ("预热结束", "率定开始"),
        ("率定开始", "率定结束"),
        ("率定结束", "验证开始"),
        ("验证开始", "验证结束"),
    ]
    for left, right in ordered_pairs:
        if left in time_values and right in time_values and time_values[left] > time_values[right]:
            messages.append(f"时间顺序错误：{left} 晚于 {right}")

    warmup_start = time_values.get("预热开始")
    configured_warmup_end = time_values.get("预热结束")
    expected_end = expected_warmup_end(time_values, step_hours)
    if warmup_start is not None and expected_end is not None:
        if warmup_start > expected_end:
            messages.append(
                "预热期至少需要覆盖率定开始前 "
                + ("1 小时。" if abs(float(step_hours) - 1.0) <= 1e-9 else "1 日。")
            )
        elif configured_warmup_end is not None and configured_warmup_end != expected_end:
            expected_label = format_timestamp_for_display(expected_end, step_hours)
            messages.append(f"时间.预热结束 必须紧邻率定开始，当前应为 {expected_label}")
    return messages
