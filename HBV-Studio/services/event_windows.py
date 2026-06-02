from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

import pandas as pd

from services.event_config import (
    EVENT_PURPOSE_ALIASES,
    TIME_BASIS_EVENT_WINDOWS,
    TIME_BASIS_FORECAST_WINDOW,
    TIME_BASIS_LABELS,
    event_date_range,
    event_field,
    event_initial_state_policy_summary,
    event_window_index,
    flood_event_raw_config,
    parse_event_timestamp,
    task_time_basis,
    truthy_config,
)
from services.event_io import read_event_table_file
from services.time_utils import is_date_only_string
from services.time_utils import normalize_time_step_hours


@dataclass(frozen=True)
class EventWindowContext:
    resolve_config_related_path: Callable[[dict[str, Any], Any], Path | None]


def _time_config_value(time_cfg: dict[str, Any], *keys: str) -> Any:
    for key in keys:
        value = time_cfg.get(key)
        if value:
            return value
    return None


def _continuous_time_index(
    config: dict[str, Any],
    *,
    start_keys: tuple[str, ...],
    end_keys: tuple[str, ...],
) -> pd.DatetimeIndex | None:
    time_cfg = dict(config.get("\u65f6\u95f4", {}))
    start_raw = _time_config_value(time_cfg, *start_keys)
    end_raw = _time_config_value(time_cfg, *end_keys)
    if not start_raw or not end_raw:
        return None
    step_hours = normalize_time_step_hours(config.get("\u65f6\u95f4\u6b65\u957f_\u5c0f\u65f6", 24.0))
    step = pd.Timedelta(hours=step_hours)
    start_ts = pd.to_datetime(start_raw)
    end_ts = pd.to_datetime(end_raw)
    if step_hours < 24.0 and is_date_only_string(end_raw):
        end_ts = end_ts + pd.Timedelta(days=1) - step
    return pd.date_range(start_ts, end_ts, freq=step)


def build_expected_time_index(config: dict[str, Any]) -> pd.DatetimeIndex | None:
    return _continuous_time_index(
        config,
        start_keys=("\u9884\u70ed\u5f00\u59cb", "\u7387\u5b9a\u5f00\u59cb"),
        end_keys=("\u9a8c\u8bc1\u7ed3\u675f", "\u7387\u5b9a\u7ed3\u675f"),
    )


def build_expected_forcing_index(
    config: dict[str, Any],
    context: EventWindowContext,
    *,
    runtime_context: str = "calibration",
) -> pd.DatetimeIndex | None:
    step_hours = normalize_time_step_hours(config.get("\u65f6\u95f4\u6b65\u957f_\u5c0f\u65f6", 24.0))
    if task_time_basis(config, context=runtime_context) == TIME_BASIS_EVENT_WINDOWS:
        event_info = normalized_flood_events(config, context, step_hours=step_hours)
        index = event_window_index(event_info.get("valid_events", []), "run_start", "run_end", step_hours)
        if len(index) > 0:
            return index
    return build_expected_time_index(config)


def build_expected_observation_index(
    config: dict[str, Any],
    context: EventWindowContext,
    *,
    runtime_context: str = "calibration",
) -> pd.DatetimeIndex | None:
    step_hours = normalize_time_step_hours(config.get("\u65f6\u95f4\u6b65\u957f_\u5c0f\u65f6", 24.0))
    if task_time_basis(config, context=runtime_context) == TIME_BASIS_EVENT_WINDOWS:
        event_info = normalized_flood_events(config, context, step_hours=step_hours)
        index = event_window_index(event_info.get("valid_events", []), "score_start", "score_end", step_hours)
        if len(index) > 0:
            return index
    return _continuous_time_index(
        config,
        start_keys=("\u7387\u5b9a\u5f00\u59cb",),
        end_keys=("\u9a8c\u8bc1\u7ed3\u675f", "\u7387\u5b9a\u7ed3\u675f"),
    )


def _format_time_for_check(value: Any, step_hours: float) -> str:
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


def event_forcing_coverage_summary(
    event_info: dict[str, Any] | None,
    directories: dict[str, dict[str, Any]],
    step_hours: float,
) -> dict[str, Any] | None:
    if not isinstance(event_info, dict):
        return None
    valid_events = [item for item in list(event_info.get("valid_events", []) or []) if isinstance(item, dict)]
    if not valid_events:
        return {
            "enabled": True,
            "status": "fail",
            "event_count": 0,
            "complete_event_count": 0,
            "events": [],
        }
    label_map = {"prec": "\u964d\u6c34", "temp": "\u6c14\u6e29", "evap": "\u6f5c\u5728\u84b8\u6563\u53d1"}
    timestamp_sets: dict[str, set[pd.Timestamp]] = {}
    for key, item in directories.items():
        timestamp_sets[key] = set(pd.Timestamp(ts) for ts in list(item.get("timestamps", []) or []))

    rows: list[dict[str, Any]] = []
    complete_count = 0
    for event in valid_events:
        run_start = pd.Timestamp(event.get("run_start"))
        run_end = pd.Timestamp(event.get("run_end"))
        run_index = event_date_range(run_start, run_end, step_hours)
        expected_steps = int(len(run_index))
        variables: dict[str, Any] = {}
        event_missing = 0
        for key, label in label_map.items():
            actual = timestamp_sets.get(key, set())
            missing_steps = [ts for ts in run_index if pd.Timestamp(ts) not in actual]
            missing_count = int(len(missing_steps))
            event_missing += missing_count
            variables[key] = {
                "label": label,
                "expected_steps": expected_steps,
                "covered_steps": max(0, expected_steps - missing_count),
                "missing_steps": missing_count,
                "status": "ok" if missing_count == 0 and expected_steps > 0 else "fail",
                "missing_preview": [
                    _format_time_for_check(ts, step_hours)
                    for ts in missing_steps[:3]
                ],
            }
        status = "ok" if event_missing == 0 and expected_steps > 0 else "fail"
        if status == "ok":
            complete_count += 1
        rows.append(
            {
                "event_id": str(event.get("event_id", "") or ""),
                "name": str(event.get("name", "") or event.get("event_id", "") or ""),
                "purpose": str(event.get("purpose", "") or ""),
                "run_start": _format_time_for_check(run_start, step_hours),
                "run_end": _format_time_for_check(run_end, step_hours),
                "expected_steps": expected_steps,
                "status": status,
                "variables": variables,
            }
        )

    return {
        "enabled": True,
        "status": "ok" if complete_count == len(valid_events) else "fail",
        "event_count": len(valid_events),
        "complete_event_count": complete_count,
        "events": rows,
    }


def event_observation_coverage_summary(
    event_info: dict[str, Any] | None,
    observed_series: Any,
    step_hours: float,
) -> dict[str, Any] | None:
    if not isinstance(event_info, dict):
        return None
    valid_events = [item for item in list(event_info.get("valid_events", []) or []) if isinstance(item, dict)]
    if not valid_events:
        return {
            "enabled": True,
            "status": "fail",
            "event_count": 0,
            "complete_event_count": 0,
            "required_event_count": 0,
            "events": [],
        }
    if observed_series is None:
        actual_index = pd.DatetimeIndex([])
    else:
        try:
            actual_index = pd.DatetimeIndex(observed_series.dropna().index)
        except Exception:
            actual_index = pd.DatetimeIndex([])
    actual_set = set(pd.Timestamp(ts) for ts in actual_index.tolist())

    rows: list[dict[str, Any]] = []
    complete_count = 0
    required_count = 0
    required_complete_count = 0
    diagnostic_warn_count = 0
    for event in valid_events:
        score_start = pd.Timestamp(event.get("score_start"))
        score_end = pd.Timestamp(event.get("score_end"))
        score_index = event_date_range(score_start, score_end, step_hours)
        expected_steps = int(len(score_index))
        missing_steps = [ts for ts in score_index if pd.Timestamp(ts) not in actual_set]
        missing_count = int(len(missing_steps))
        covered_steps = max(0, expected_steps - missing_count)
        coverage_ratio = (covered_steps / expected_steps) if expected_steps > 0 else None
        purpose = str(event.get("purpose", "") or "").strip().lower()
        is_required = purpose in {"calibration", "validation", ""}
        if is_required:
            required_count += 1
        if missing_count == 0 and expected_steps > 0:
            status = "ok"
            complete_count += 1
            if is_required:
                required_complete_count += 1
        elif is_required:
            status = "fail"
        else:
            status = "warn"
            diagnostic_warn_count += 1
        rows.append(
            {
                "event_id": str(event.get("event_id", "") or ""),
                "name": str(event.get("name", "") or event.get("event_id", "") or ""),
                "purpose": purpose,
                "score_start": _format_time_for_check(score_start, step_hours),
                "score_end": _format_time_for_check(score_end, step_hours),
                "expected_steps": expected_steps,
                "covered_steps": covered_steps,
                "missing_steps": missing_count,
                "coverage_ratio": coverage_ratio,
                "status": status,
                "missing_preview": [
                    _format_time_for_check(ts, step_hours)
                    for ts in missing_steps[:5]
                ],
            }
        )

    if required_complete_count < required_count:
        status = "fail"
    elif diagnostic_warn_count > 0:
        status = "warn"
    else:
        status = "ok"
    return {
        "enabled": True,
        "status": status,
        "event_count": len(valid_events),
        "complete_event_count": complete_count,
        "required_event_count": required_count,
        "required_complete_event_count": required_complete_count,
        "events": rows,
    }


def event_observation_coverage_messages(coverage: dict[str, Any] | None) -> tuple[list[str], list[str]]:
    issues: list[str] = []
    warnings: list[str] = []
    if not isinstance(coverage, dict) or not coverage.get("enabled"):
        return issues, warnings
    for event in list(coverage.get("events", []) or []):
        if not isinstance(event, dict):
            continue
        status = str(event.get("status", "") or "").lower()
        if status == "ok":
            continue
        name = str(event.get("name") or event.get("event_id") or "\u672a\u547d\u540d\u4e8b\u4ef6")
        missing_steps = int(event.get("missing_steps", 0) or 0)
        expected_steps = int(event.get("expected_steps", 0) or 0)
        preview = "\u3001".join(str(item) for item in list(event.get("missing_preview", []) or [])[:3])
        suffix = f"\uff1b\u4f8b\u5982 {preview}" if preview else ""
        message = f"\u4e8b\u4ef6 {name} \u89c2\u6d4b\u5f84\u6d41\u7f3a\u6d4b {missing_steps}/{expected_steps} \u6b65{suffix}\u3002"
        if status == "fail":
            issues.append(message)
        else:
            warnings.append(message)
    return issues, warnings


def event_windows_ui_summary(event_info: dict[str, Any] | None, step_hours: float) -> dict[str, Any] | None:
    if not isinstance(event_info, dict):
        return None
    events = list(event_info.get("events", []) or [])
    valid_events = list(event_info.get("valid_events", []) or [])

    def convert_event(event: dict[str, Any]) -> dict[str, Any]:
        return {
            "event_id": event.get("event_id", ""),
            "name": event.get("name", "") or event.get("event_id", ""),
            "valid": bool(event.get("valid")),
            "score_start": _format_time_for_check(event.get("score_start"), step_hours),
            "score_end": _format_time_for_check(event.get("score_end"), step_hours),
            "run_start": _format_time_for_check(event.get("run_start"), step_hours),
            "run_end": _format_time_for_check(event.get("run_end"), step_hours),
        }

    return {
        "enabled": bool(event_info.get("enabled")),
        "source_file": str(event_info.get("source_file", "") or ""),
        "event_count": int(event_info.get("event_count", 0) or 0),
        "valid_event_count": int(event_info.get("valid_event_count", 0) or 0),
        "purpose_counts": dict(event_info.get("purpose_counts", {}) or {}),
        "warnings": [str(item) for item in list(event_info.get("warnings", []) or [])],
        "errors": [str(item) for item in list(event_info.get("errors", []) or [])],
        "events": [convert_event(item) for item in events if isinstance(item, dict)],
        "valid_events": [convert_event(item) for item in valid_events if isinstance(item, dict)],
        "time_basis": TIME_BASIS_EVENT_WINDOWS,
        "initial_state_policy": str(event_info.get("initial_state_policy", "event_warmup") or "event_warmup"),
        "initial_state_policy_label": str(event_info.get("initial_state_policy_label", "\u4e8b\u4ef6\u9884\u70ed") or "\u4e8b\u4ef6\u9884\u70ed"),
        "state_continuity_between_events": bool(event_info.get("state_continuity_between_events")),
        "initial_state_note": str(event_info.get("initial_state_note", "") or ""),
        "initial_state_warning": str(event_info.get("initial_state_warning", "") or ""),
    }


def input_time_basis_ui_summary(
    config: dict[str, Any],
    context: EventWindowContext,
    *,
    time_basis: str,
    step_hours: float,
    event_info: dict[str, Any] | None = None,
    runtime_context: str = "calibration",
) -> dict[str, Any]:
    label = TIME_BASIS_LABELS.get(time_basis, "\u5f53\u524d\u4efb\u52a1\u65f6\u6bb5")

    def index_range(index: pd.DatetimeIndex | None) -> tuple[str, str, int]:
        if index is None or len(index) <= 0:
            return "", "", 0
        return _format_time_for_check(index[0], step_hours), _format_time_for_check(index[-1], step_hours), int(len(index))

    if time_basis == TIME_BASIS_EVENT_WINDOWS:
        info = event_info if isinstance(event_info, dict) else normalized_flood_events(config, context, step_hours=step_hours)
        valid_events = list(info.get("valid_events", []) or [])
        run_index = event_window_index(valid_events, "run_start", "run_end", step_hours)
        start, end, expected_steps = index_range(run_index)
        event_count = int(info.get("event_count", 0) or 0)
        valid_event_count = int(info.get("valid_event_count", 0) or 0)
        status = "fail" if valid_event_count <= 0 else "warn" if info.get("errors") or info.get("warnings") else "ok"
        initial_label = str(info.get("initial_state_policy_label", "\u4e8b\u4ef6\u9884\u70ed") or "\u4e8b\u4ef6\u9884\u70ed")
        initial_note = str(info.get("initial_state_note", "") or "")
        headline = (
            f"\u5f53\u524d\u6309 {valid_event_count} \u573a\u6d2a\u6c34\u4e8b\u4ef6\u68c0\u67e5\uff0c\u4e8b\u4ef6\u4e4b\u95f4\u5141\u8bb8\u8d44\u6599\u95f4\u65ad\u3002"
            if valid_event_count > 0
            else "\u5f53\u524d\u9009\u62e9\u6d2a\u6c34\u4e8b\u4ef6\uff0c\u4f46\u5c1a\u672a\u8bc6\u522b\u5230\u5408\u6cd5\u4e8b\u4ef6\u3002"
        )
        return {
            "time_basis": time_basis,
            "time_basis_label": label,
            "headline": headline,
            "detail": "\u53ea\u68c0\u67e5\u6bcf\u573a\u6d2a\u6c34\u5185\u90e8\u7684\u6c14\u8c61\u4e0e\u6d41\u91cf\u8d44\u6599\u3002"
            + (f" {initial_note}" if initial_note else ""),
            "start": start,
            "end": end,
            "expected_steps": expected_steps,
            "event_count": event_count,
            "valid_event_count": valid_event_count,
            "status": status,
            "items": [
                {"label": "\u8d44\u6599\u53e3\u5f84", "value": label},
                {"label": "\u6709\u6548\u4e8b\u4ef6", "value": f"{valid_event_count}/{event_count} \u573a"},
                {"label": "\u4e8b\u4ef6\u65f6\u6bb5", "value": f"{start} \u81f3 {end}" if start and end else "\u672a\u5f62\u6210\u6709\u6548\u65f6\u6bb5"},
                {"label": "\u521d\u59cb\u6761\u4ef6", "value": initial_label},
            ],
            "initial_state_policy": str(info.get("initial_state_policy", "event_warmup") or "event_warmup"),
            "initial_state_policy_label": initial_label,
            "state_continuity_between_events": bool(info.get("state_continuity_between_events")),
            "initial_state_note": initial_note,
        }

    try:
        expected_index = build_expected_forcing_index(config, context, runtime_context=runtime_context)
    except Exception:
        expected_index = None
    start, end, expected_steps = index_range(expected_index)
    status = "ok" if expected_steps else "warn"
    if time_basis == TIME_BASIS_FORECAST_WINDOW:
        headline = (
            f"\u5f53\u524d\u6309\u8fde\u7eed\u72b6\u6001\u9884\u62a5\u7a97\u53e3\u68c0\u67e5\uff1a{start} \u81f3 {end}\u3002"
            if start and end
            else "\u5f53\u524d\u6309\u8fde\u7eed\u72b6\u6001\u9884\u62a5\u7a97\u53e3\u68c0\u67e5\uff0c\u4f46\u9884\u62a5\u8d77\u6b62\u65f6\u95f4\u5c1a\u672a\u5b8c\u6574\u914d\u7f6e\u3002"
        )
        detail = "\u9884\u62a5\u7a97\u53e3\u5185\u964d\u6c34\u3001\u6c14\u6e29\u548c\u6f5c\u5728\u84b8\u6563\u53d1\u5fc5\u987b\u8fde\u7eed\uff1b\u591a\u4f59\u6c14\u8c61\u6587\u4ef6\u4e0d\u4f5c\u4e3a\u672c\u6b21\u9884\u62a5\u4f9d\u636e\u3002"
    else:
        headline = (
            f"\u5f53\u524d\u6309\u8fde\u7eed\u65f6\u6bb5\u68c0\u67e5\uff1a{start} \u81f3 {end}\u3002"
            if start and end
            else "\u5f53\u524d\u6309\u8fde\u7eed\u65f6\u6bb5\u68c0\u67e5\uff0c\u4f46\u9884\u70ed\u3001\u7387\u5b9a\u6216\u9a8c\u8bc1\u65f6\u95f4\u5c1a\u672a\u5b8c\u6574\u914d\u7f6e\u3002"
        )
        detail = "\u8fde\u7eed\u6a21\u62df\u8981\u6c42\u76ee\u6807\u65f6\u95f4\u8f74\u5185\u964d\u6c34\u3001\u6c14\u6e29\u3001\u6f5c\u5728\u84b8\u6563\u53d1\u548c\u5fc5\u8981\u89c2\u6d4b\u8d44\u6599\u8fde\u7eed\u8986\u76d6\u3002"
    return {
        "time_basis": time_basis,
        "time_basis_label": label,
        "headline": headline,
        "detail": detail,
        "start": start,
        "end": end,
        "expected_steps": expected_steps,
        "status": status,
        "items": [
            {"label": "\u8d44\u6599\u53e3\u5f84", "value": label},
            {"label": "\u68c0\u67e5\u8303\u56f4", "value": f"{start} \u81f3 {end}" if start and end else "\u672a\u5b8c\u6574\u914d\u7f6e"},
            {"label": "\u76ee\u6807\u65f6\u95f4\u6b65", "value": str(expected_steps) if expected_steps else "\u672a\u5f62\u6210"},
            {"label": "\u65f6\u95f4\u6b65\u957f", "value": f"{step_hours:g} \u5c0f\u65f6"},
        ],
    }


def normalized_flood_events(
    config: dict[str, Any],
    context: EventWindowContext,
    *,
    step_hours: float | None = None,
) -> dict[str, Any]:
    step = normalize_time_step_hours(step_hours if step_hours is not None else config.get("\u65f6\u95f4\u6b65\u957f_\u5c0f\u65f6", 24.0))
    cfg = flood_event_raw_config(config)
    raw_events = cfg.get("\u4e8b\u4ef6\u8868", cfg.get("events", []))
    warnings: list[str] = []
    errors: list[str] = []
    initial_state = event_initial_state_policy_summary(
        cfg.get(
            "\u521d\u59cb\u6761\u4ef6\u7b56\u7565",
            cfg.get("initial_state_policy", cfg.get("event_initial_state_policy", "event_warmup")),
        )
    )
    if initial_state.get("warning"):
        warnings.append(str(initial_state["warning"]))
    event_file_raw = str(cfg.get("\u4e8b\u4ef6\u8868\u8def\u5f84", cfg.get("events_file", cfg.get("event_file", ""))) or "").strip()
    event_file = context.resolve_config_related_path(config, event_file_raw) if event_file_raw else None
    if event_file_raw:
        if event_file is None or not event_file.exists():
            errors.append(f"\u6d2a\u6c34\u4e8b\u4ef6\u8868\u6587\u4ef6\u4e0d\u5b58\u5728\uff1a{event_file_raw}")
            raw_events = []
        else:
            try:
                raw_events = read_event_table_file(event_file)
            except Exception as exc:
                errors.append(f"\u6d2a\u6c34\u4e8b\u4ef6\u8868\u8bfb\u53d6\u5931\u8d25\uff1a{exc}")
                raw_events = []
    if isinstance(raw_events, dict):
        raw_events = raw_events.get("events", raw_events.get("\u4e8b\u4ef6\u8868", []))
    if not isinstance(raw_events, list):
        raw_events = []

    events: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    for index, raw_event in enumerate(raw_events, start=1):
        if not isinstance(raw_event, dict):
            warnings.append(f"\u7b2c {index} \u6761\u4e8b\u4ef6\u4e0d\u662f\u5bf9\u8c61\uff0c\u5df2\u8df3\u8fc7\u3002")
            continue
        event = dict(raw_event)
        token = json.dumps(event, ensure_ascii=False, sort_keys=True, default=str).encode("utf-8")
        event_id_raw = str(event_field(event, "event_id", "id", "\u7f16\u53f7", "\u6d2a\u6c34\u7f16\u53f7", "\u4e8b\u4ef6\u7f16\u53f7") or "").strip()
        event_id = event_id_raw
        name = str(event_field(event, "name", "\u540d\u79f0", "\u4e8b\u4ef6\u540d\u79f0", "\u6d2a\u6c34\u540d\u79f0") or "").strip()
        if not event_id:
            event_id = name or f"event_{hashlib.sha1(token).hexdigest()[:8]}"
            warnings.append(f"\u7b2c {index} \u6761\u4e8b\u4ef6\u672a\u586b\u5199 event_id\uff0c\u5df2\u4e34\u65f6\u4f7f\u7528 {event_id}\uff1b\u6b63\u5f0f\u5de5\u7a0b\u5efa\u8bae\u586b\u5199\u552f\u4e00\u4e8b\u4ef6\u7f16\u53f7\u3002")
        purpose_raw = str(event_field(event, "purpose", "\u7528\u9014", "\u7c7b\u578b", "type") or "calibration").strip()
        purpose = EVENT_PURPOSE_ALIASES.get(purpose_raw.lower(), purpose_raw.lower() or "calibration")
        if purpose not in {"calibration", "validation", "diagnostic"}:
            warnings.append(f"\u4e8b\u4ef6 {event_id} \u7684\u7528\u9014 {purpose_raw} \u672a\u8bc6\u522b\uff0c\u6309 diagnostic \u5904\u7406\u3002")
            purpose = "diagnostic"
        if event_id in seen_ids:
            errors.append(f"\u6d2a\u6c34\u4e8b\u4ef6\u7f16\u53f7\u91cd\u590d\uff1a{event_id}")
        seen_ids.add(event_id)
        score_start_raw = event_field(event, "score_start", "\u8bc4\u5206\u5f00\u59cb", "\u4e8b\u4ef6\u5f00\u59cb", "\u6d2a\u6c34\u5f00\u59cb", "\u5f00\u59cb\u65f6\u95f4", "\u8d77\u59cb\u65f6\u95f4", "start")
        score_end_raw = event_field(event, "score_end", "\u8bc4\u5206\u7ed3\u675f", "\u4e8b\u4ef6\u7ed3\u675f", "\u6d2a\u6c34\u7ed3\u675f", "\u7ed3\u675f\u65f6\u95f4", "\u7ec8\u6b62\u65f6\u95f4", "end")
        run_start_raw = event_field(event, "run_start", "\u8fd0\u884c\u5f00\u59cb", "\u9884\u70ed\u5f00\u59cb", "warmup_start") or score_start_raw
        run_end_value = event_field(event, "run_end", "\u8fd0\u884c\u7ed3\u675f", "\u9000\u6c34\u7ed3\u675f")
        if run_end_value in (None, ""):
            run_end_raw = score_end_raw
        else:
            run_end_raw = run_end_value
        event_errors: list[str] = []
        time_steps_run = 0
        time_steps_score = 0
        try:
            run_start = parse_event_timestamp(run_start_raw, end=False, step_hours=step)
            score_start = parse_event_timestamp(score_start_raw, end=False, step_hours=step)
            score_end = parse_event_timestamp(score_end_raw, end=True, step_hours=step)
            run_end = parse_event_timestamp(run_end_raw, end=True, step_hours=step)
        except Exception as exc:
            run_start = score_start = score_end = run_end = None
            event_errors.append(f"\u4e8b\u4ef6\u65f6\u95f4\u65e0\u6cd5\u89e3\u6790\uff1a{exc}")
        if run_start is None or score_start is None or score_end is None or run_end is None:
            event_errors.append("\u4e8b\u4ef6\u7f3a\u5c11\u5f00\u59cb\u65f6\u95f4\u6216\u7ed3\u675f\u65f6\u95f4\u3002")
        elif not (run_start <= score_start <= score_end <= run_end):
            event_errors.append("\u4e8b\u4ef6\u65f6\u95f4\u987a\u5e8f\u4e0d\u6b63\u786e\uff1a\u8fd0\u884c\u5f00\u59cb\u5e94\u4e0d\u665a\u4e8e\u5f00\u59cb\u65f6\u95f4\uff0c\u7ed3\u675f\u65f6\u95f4\u5e94\u4e0d\u665a\u4e8e\u8fd0\u884c\u7ed3\u675f\u3002")
        else:
            time_steps_run = int(len(event_date_range(run_start, run_end, step)))
            time_steps_score = int(len(event_date_range(score_start, score_end, step)))
            min_score_steps = 3 if step >= 24.0 else 6
            if time_steps_score < min_score_steps:
                unit = "\u5929" if step >= 24.0 else "\u5c0f\u65f6"
                event_errors.append(f"\u4e8b\u4ef6\u65f6\u6bb5\u8fc7\u77ed\uff1a\u5f53\u524d {time_steps_score} \u6b65\uff0c\u81f3\u5c11\u9700\u8981 {min_score_steps} \u6b65\uff08{unit}\u5c3a\u5ea6\uff09\u3002")
        if event_errors:
            errors.extend(f"{event_id}: {item}" for item in event_errors)
        events.append(
            {
                "event_id": event_id,
                "name": name or event_id,
                "purpose": purpose,
                "run_start": run_start,
                "score_start": score_start,
                "score_end": score_end,
                "run_end": run_end,
                "raw": event,
                "valid": not event_errors,
                "time_steps_run": time_steps_run,
                "time_steps_score": time_steps_score,
            }
        )

    valid_events = sorted(
        [event for event in events if event.get("valid")],
        key=lambda item: (pd.Timestamp(item["run_start"]), str(item.get("event_id", ""))),
    )
    for left, right in zip(valid_events, valid_events[1:]):
        if left["run_end"] >= right["run_start"]:
            warnings.append(f"\u4e8b\u4ef6\u65f6\u6bb5\u53ef\u80fd\u91cd\u53e0\uff1a{left['event_id']} \u4e0e {right['event_id']}\u3002")
    purpose_counts = {
        "calibration": sum(1 for event in valid_events if event.get("purpose") == "calibration"),
        "validation": sum(1 for event in valid_events if event.get("purpose") == "validation"),
        "diagnostic": sum(1 for event in valid_events if event.get("purpose") == "diagnostic"),
    }
    return {
        "enabled": truthy_config(cfg.get("\u542f\u7528", cfg.get("enabled")), default=bool(events)),
        "source_file": str(event_file.resolve(strict=False)) if event_file is not None and event_file.exists() else "",
        "events": events,
        "valid_events": valid_events,
        "event_count": len(events),
        "valid_event_count": len(valid_events),
        "purpose_counts": purpose_counts,
        "warnings": warnings,
        "errors": errors,
        "time_basis": TIME_BASIS_EVENT_WINDOWS,
        "initial_state_policy": initial_state.get("policy", "event_warmup"),
        "initial_state_policy_label": initial_state.get("label", "\u4e8b\u4ef6\u9884\u70ed"),
        "state_continuity_between_events": bool(initial_state.get("state_continuity_between_events")),
        "initial_state_note": initial_state.get("note", ""),
        "initial_state_warning": initial_state.get("warning", ""),
    }
