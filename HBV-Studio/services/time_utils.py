from __future__ import annotations

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
