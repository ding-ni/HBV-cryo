from __future__ import annotations

from pathlib import Path
from typing import Any

import pandas as pd

from services.event_config import TIME_BASIS_EVENT_WINDOWS, TIME_BASIS_FORECAST_WINDOW


def detect_table_column(columns: list[str], candidates: list[str]) -> str | None:
    lowered = {str(col).strip().lower(): str(col) for col in columns}
    for candidate in candidates:
        found = lowered.get(candidate.lower())
        if found is not None:
            return found
    return None


def detect_table_time_column(frame: pd.DataFrame) -> str | None:
    for column in frame.columns:
        parsed = pd.to_datetime(frame[column], errors="coerce")
        if int(parsed.notna().sum()) >= max(1, len(frame) // 3):
            return str(column)
    return None


def read_station_csv(path: Path) -> pd.DataFrame:
    last_error: Exception | None = None
    for encoding in ("utf-8-sig", "utf-8", "gbk"):
        try:
            return pd.read_csv(path, encoding=encoding)
        except UnicodeDecodeError as exc:
            last_error = exc
    if last_error is not None:
        raise last_error
    return pd.read_csv(path)


def load_station_precip_table(path: Path) -> tuple[pd.DataFrame, str, str | None]:
    frame = read_station_csv(path)
    if frame.empty:
        raise ValueError("\u7ad9\u70b9\u964d\u6c34 csv \u4e3a\u7a7a\u3002")
    time_col = detect_table_time_column(frame)
    if not time_col:
        raise ValueError("\u7ad9\u70b9\u964d\u6c34 csv \u672a\u8bc6\u522b\u5230\u65f6\u95f4\u5217\u3002")

    columns = [str(col) for col in frame.columns]
    id_col = detect_table_column(columns, ["station_id", "station", "id", "name", "\u7ad9\u70b9", "\u7ad9\u53f7"])
    value_col = detect_table_column(columns, ["precip", "prec", "ppt", "rain", "value", "\u964d\u6c34", "\u964d\u6c34\u91cf"])
    if id_col and value_col and id_col != time_col and value_col != time_col:
        data = frame[[time_col, id_col, value_col]].copy()
        data.columns = ["time", "station_id", "value"]
        data["time"] = pd.to_datetime(data["time"], errors="coerce")
        data["station_id"] = data["station_id"].astype(str).str.strip()
        data["value"] = pd.to_numeric(data["value"], errors="coerce")
        wide = data.pivot_table(index="time", columns="station_id", values="value", aggfunc="mean")
        wide.columns = [str(col).strip() for col in wide.columns]
        return wide.sort_index(), "\u957f\u8868", time_col

    wide = frame.copy()
    wide[time_col] = pd.to_datetime(wide[time_col], errors="coerce")
    wide = wide.dropna(subset=[time_col]).set_index(time_col).sort_index()
    wide.columns = [str(col).strip() for col in wide.columns]
    for column in list(wide.columns):
        wide[column] = pd.to_numeric(wide[column], errors="coerce")
    return wide, "\u5bbd\u8868", time_col


def load_station_metadata_table(path: Path) -> tuple[pd.DataFrame, dict[str, str | None]]:
    frame = read_station_csv(path)
    if frame.empty:
        raise ValueError("\u7ad9\u70b9\u4fe1\u606f csv \u4e3a\u7a7a\u3002")
    columns = [str(col) for col in frame.columns]
    id_col = detect_table_column(columns, ["station_id", "station", "id", "name", "\u7ad9\u70b9", "\u7ad9\u53f7"])
    lon_col = detect_table_column(columns, ["lon", "longitude", "x", "\u7ecf\u5ea6"])
    lat_col = detect_table_column(columns, ["lat", "latitude", "y", "\u7eac\u5ea6"])
    if not id_col:
        raise ValueError("\u7ad9\u70b9\u4fe1\u606f csv \u672a\u8bc6\u522b\u5230\u7ad9\u53f7\u5b57\u6bb5\u3002")
    out = frame.copy()
    out["_station_id"] = out[id_col].astype(str).str.strip()
    return out, {"id": id_col, "lon": lon_col, "lat": lat_col}


def format_time_for_check(value: Any, step_hours: float) -> str:
    if value in (None, ""):
        return ""
    try:
        ts = pd.to_datetime(value)
    except Exception:
        return "\u672a\u8bc6\u522b"
    if pd.isna(ts):
        return ""
    if abs(float(step_hours) - 24.0) < 1e-9 and ts.hour == 0 and ts.minute == 0 and ts.second == 0:
        return ts.strftime("%Y-%m-%d")
    return ts.strftime("%Y-%m-%d %H:%M")


def station_precip_mode_label(mode: str) -> str:
    return {
        "grid_plus_station_bias": "\u683c\u70b9 + \u7ad9\u70b9\u504f\u5dee\u8ba2\u6b63",
        "thiessen_station_only": "\u7eaf\u7ad9\u70b9\u6cf0\u68ee\u5206\u914d",
    }.get(str(mode or "").strip(), "\u7ad9\u70b9\u964d\u6c34\u65b9\u6848")


def index_display_range(index: pd.DatetimeIndex | None, step_hours: float) -> tuple[str, str, int]:
    if index is None or len(index) <= 0:
        return "", "", 0
    return (
        format_time_for_check(index[0], step_hours),
        format_time_for_check(index[-1], step_hours),
        int(len(index)),
    )


def max_consecutive_true(values: Any) -> int:
    longest = 0
    current = 0
    for value in list(values):
        if bool(value):
            current += 1
            longest = max(longest, current)
        else:
            current = 0
    return int(longest)


def station_count_text(min_count: int | None, mean_count: float | None) -> str:
    if min_count is None:
        return "\u672a\u5f62\u6210"
    if mean_count is None:
        return str(int(min_count))
    return f"\u6700\u5c11 {int(min_count)}\uff0c\u5e73\u5747 {mean_count:.1f}"


def station_precip_task_context_summary(
    *,
    mode: str,
    context: str,
    time_basis: str,
    time_basis_label: str,
    step_hours: float,
    expected_index: pd.DatetimeIndex | None,
    expected_count: int,
    covered_count: int,
    coverage_ratio: float | None,
    zero_available_steps: int,
    max_consecutive_zero_steps: int = 0,
    min_available_station_count: int | None = None,
    mean_available_station_count: float | None = None,
    station_start: Any = None,
    station_end: Any = None,
    event_info: dict[str, Any] | None = None,
    event_coverage: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    start, end, expected_steps = index_display_range(expected_index, step_hours)
    station_start_text = format_time_for_check(station_start, step_hours)
    station_end_text = format_time_for_check(station_end, step_hours)
    coverage_text = (
        f"{covered_count}/{expected_count} \u6b65\uff08{coverage_ratio * 100:.1f}%\uff09"
        if coverage_ratio is not None and expected_count > 0
        else "\u672a\u5f62\u6210\u53ef\u6838\u5bf9\u65f6\u6bb5"
    )
    events = list(event_coverage or [])
    event_ok_count = sum(1 for item in events if str(item.get("status", "") or "") == "ok")
    event_count = int(len(events))
    event_valid_count = int((event_info or {}).get("valid_event_count", event_count) or 0)
    if time_basis == TIME_BASIS_EVENT_WINDOWS and event_valid_count <= 0:
        status = "fail"
    elif expected_count <= 0:
        status = "warn"
    elif coverage_ratio is None or covered_count <= 0:
        status = "fail"
    elif coverage_ratio >= 0.99 and zero_available_steps == 0 and all(str(item.get("status", "")) == "ok" for item in events):
        status = "ok"
    elif mode == "thiessen_station_only" and zero_available_steps > 0:
        status = "fail"
    else:
        status = "warn"

    count_text = station_count_text(min_available_station_count, mean_available_station_count)
    if time_basis == TIME_BASIS_EVENT_WINDOWS:
        headline = (
            f"\u5f53\u524d\u6309 {event_valid_count} \u573a\u6d2a\u6c34\u4e8b\u4ef6\u8fd0\u884c\u7a97\u53e3\u6838\u5bf9\u7ad9\u70b9\u964d\u6c34\uff0c\u4e8b\u4ef6\u4e4b\u95f4\u5141\u8bb8\u8d44\u6599\u95f4\u65ad\u3002"
            if event_valid_count > 0
            else "\u5f53\u524d\u9009\u62e9\u6d2a\u6c34\u4e8b\u4ef6\u7a97\u53e3\uff0c\u4f46\u5c1a\u672a\u5f62\u6210\u53ef\u6838\u5bf9\u7684\u6709\u6548\u4e8b\u4ef6\u3002"
        )
        detail = (
            "\u7ad9\u70b9\u964d\u6c34\u5b8c\u6574\u6027\u53ea\u5728\u4e8b\u4ef6\u8fd0\u884c\u7a97\u53e3\u5185\u8bc4\u4ef7\uff1b\u4e8b\u4ef6\u5185\u90e8\u82e5\u51fa\u73b0\u65e0\u53ef\u7528\u7ad9\u70b9\u65f6\u95f4\u6b65\uff0c"
            "\u7eaf\u7ad9\u70b9\u6cf0\u68ee\u5206\u914d\u4e0d\u80fd\u76f4\u63a5\u8fd0\u884c\uff0c\u683c\u70b9\u8ba2\u6b63\u4e5f\u5e94\u4f5c\u4e3a\u98ce\u9669\u5904\u7406\u3002"
        )
        scope_value = f"{start} \u81f3 {end}" if start and end else "\u672a\u5f62\u6210\u4e8b\u4ef6\u8fd0\u884c\u7a97\u53e3"
        items = [
            {"label": "\u68c0\u67e5\u53e3\u5f84", "value": time_basis_label, "status": "ok" if event_valid_count > 0 else "fail"},
            {"label": "\u4e8b\u4ef6\u8986\u76d6", "value": f"{event_ok_count}/{event_count} \u573a\u5b8c\u6574" if event_count else "\u672a\u5f62\u6210", "status": "ok" if event_count and event_ok_count == event_count else "fail" if event_valid_count <= 0 else "warn"},
            {"label": "\u8fd0\u884c\u7a97\u53e3\u5e76\u96c6", "value": scope_value, "status": "ok" if expected_steps else "warn"},
            {"label": "\u8986\u76d6\u6b65\u6570", "value": coverage_text, "status": "ok" if coverage_ratio is not None and coverage_ratio >= 0.99 else "warn" if covered_count > 0 else "fail"},
            {"label": "\u53ef\u7528\u7ad9\u70b9", "value": count_text, "status": "ok" if min_available_station_count and min_available_station_count > 0 else "fail" if mode == "thiessen_station_only" else "warn"},
            {"label": "\u65e0\u7ad9\u70b9\u65f6\u95f4\u6b65", "value": str(zero_available_steps), "status": "ok" if zero_available_steps == 0 else "fail" if mode == "thiessen_station_only" else "warn"},
            {"label": "\u6700\u5927\u8fde\u7eed\u65e0\u7ad9\u70b9", "value": f"{max_consecutive_zero_steps} \u6b65", "status": "ok" if max_consecutive_zero_steps == 0 else "fail" if mode == "thiessen_station_only" else "warn"},
        ]
    elif time_basis == TIME_BASIS_FORECAST_WINDOW or context == "forecast":
        headline = (
            f"\u5f53\u524d\u6309\u8fde\u7eed\u72b6\u6001\u9884\u62a5\u7a97\u53e3\u6838\u5bf9\u7ad9\u70b9\u964d\u6c34\uff1a{start} \u81f3 {end}\u3002"
            if start and end
            else "\u5f53\u524d\u6309\u8fde\u7eed\u72b6\u6001\u9884\u62a5\u7a97\u53e3\u6838\u5bf9\u7ad9\u70b9\u964d\u6c34\uff0c\u4f46\u9884\u62a5\u8d77\u6b62\u65f6\u95f4\u5c1a\u672a\u5b8c\u6574\u914d\u7f6e\u3002"
        )
        detail = (
            "\u9884\u62a5\u8fd0\u884c\u4e3b\u7ebf\u8bfb\u53d6\u5df2\u7ecf\u5236\u5907\u597d\u7684\u964d\u6c34\u6805\u683c\uff1b\u5982\u679c\u672a\u6765\u964d\u6c34\u6765\u81ea\u7ad9\u70b9\u8d44\u6599\uff0c\u5e94\u5148\u5728\u6c14\u8c61\u51c6\u5907\u6d41\u7a0b\u4e2d\u5b8c\u6210\u8ba2\u6b63\u6216\u6cf0\u68ee\u5236\u56fe\uff0c"
            "\u518d\u5c06\u751f\u6210\u7684\u9884\u62a5\u7a97\u53e3\u6805\u683c\u4ea4\u7ed9\u8fde\u7eed\u72b6\u6001\u9884\u62a5\u3002"
        )
        items = [
            {"label": "\u68c0\u67e5\u53e3\u5f84", "value": time_basis_label, "status": "ok" if expected_steps else "warn"},
            {"label": "\u9884\u62a5\u7a97\u53e3", "value": f"{start} \u81f3 {end}" if start and end else "\u672a\u5b8c\u6574\u914d\u7f6e", "status": "ok" if expected_steps else "warn"},
            {"label": "\u8986\u76d6\u6b65\u6570", "value": coverage_text, "status": "ok" if coverage_ratio is not None and coverage_ratio >= 0.99 else "warn" if covered_count > 0 else "fail"},
            {"label": "\u53ef\u7528\u7ad9\u70b9", "value": count_text, "status": "ok" if min_available_station_count and min_available_station_count > 0 else "warn"},
            {"label": "\u6700\u5927\u8fde\u7eed\u65e0\u7ad9\u70b9", "value": f"{max_consecutive_zero_steps} \u6b65", "status": "ok" if max_consecutive_zero_steps == 0 else "warn"},
            {"label": "\u964d\u6c34\u5904\u7406", "value": "\u9884\u62a5\u9875\u4f7f\u7528\u76ee\u6807\u6805\u683c\uff0c\u7ad9\u70b9\u96e8\u91cf\u5148\u5728\u6c14\u8c61\u51c6\u5907\u4e2d\u5236\u56fe", "status": "ok"},
        ]
    else:
        headline = (
            f"\u5f53\u524d\u6309\u8fde\u7eed\u65f6\u6bb5\u6838\u5bf9\u7ad9\u70b9\u964d\u6c34\uff1a{start} \u81f3 {end}\u3002"
            if start and end
            else "\u5f53\u524d\u6309\u8fde\u7eed\u65f6\u6bb5\u6838\u5bf9\u7ad9\u70b9\u964d\u6c34\uff0c\u4f46\u9884\u70ed\u3001\u7387\u5b9a\u6216\u9a8c\u8bc1\u65f6\u95f4\u5c1a\u672a\u5b8c\u6574\u914d\u7f6e\u3002"
        )
        detail = (
            "\u8fde\u7eed\u6a21\u62df\u8981\u6c42\u76ee\u6807\u65f6\u95f4\u8f74\u5185\u7ad9\u70b9\u964d\u6c34\u8fde\u7eed\u53c2\u4e0e\uff1b\u4e2d\u95f4\u7f3a\u53e3\u4f1a\u5f71\u54cd\u571f\u58e4\u542b\u6c34\u91cf\u3001\u79ef\u96ea\u3001\u6c34\u5e93\u72b6\u6001\u548c\u6c47\u6d41\u8bb0\u5fc6\u3002"
        )
        items = [
            {"label": "\u68c0\u67e5\u53e3\u5f84", "value": time_basis_label, "status": "ok" if expected_steps else "warn"},
            {"label": "\u8fde\u7eed\u65f6\u6bb5", "value": f"{start} \u81f3 {end}" if start and end else "\u672a\u5b8c\u6574\u914d\u7f6e", "status": "ok" if expected_steps else "warn"},
            {"label": "\u8986\u76d6\u6b65\u6570", "value": coverage_text, "status": "ok" if coverage_ratio is not None and coverage_ratio >= 0.99 else "warn" if covered_count > 0 else "fail"},
            {"label": "\u53ef\u7528\u7ad9\u70b9", "value": count_text, "status": "ok" if min_available_station_count and min_available_station_count > 0 else "fail" if mode == "thiessen_station_only" else "warn"},
            {"label": "\u65e0\u7ad9\u70b9\u65f6\u95f4\u6b65", "value": str(zero_available_steps), "status": "ok" if zero_available_steps == 0 else "fail" if mode == "thiessen_station_only" else "warn"},
            {"label": "\u6700\u5927\u8fde\u7eed\u65e0\u7ad9\u70b9", "value": f"{max_consecutive_zero_steps} \u6b65", "status": "ok" if max_consecutive_zero_steps == 0 else "fail" if mode == "thiessen_station_only" else "warn"},
        ]

    return {
        "schema": "station_precip_task_context_v1",
        "context": context,
        "mode": mode,
        "mode_label": station_precip_mode_label(mode),
        "time_basis": time_basis,
        "time_basis_label": time_basis_label,
        "headline": headline,
        "detail": detail,
        "status": status,
        "start": start,
        "end": end,
        "expected_steps": int(expected_steps),
        "covered_steps": int(covered_count),
        "coverage_ratio": coverage_ratio,
        "zero_available_steps": int(zero_available_steps),
        "max_consecutive_zero_steps": int(max_consecutive_zero_steps),
        "min_available_station_count": min_available_station_count,
        "mean_available_station_count": mean_available_station_count,
        "station_time_range": {
            "start": station_start_text,
            "end": station_end_text,
        },
        "event_count": event_count,
        "event_ok_count": int(event_ok_count),
        "items": items,
    }
