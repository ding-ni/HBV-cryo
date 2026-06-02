from __future__ import annotations

from typing import Any

import pandas as pd

from services.time_utils import is_date_only_string


TIME_BASIS_CONTINUOUS = "continuous"
TIME_BASIS_EVENT_WINDOWS = "event_windows"
TIME_BASIS_FORECAST_WINDOW = "forecast_window"
TIME_BASIS_LABELS = {
    TIME_BASIS_CONTINUOUS: "\u8fde\u7eed\u65f6\u6bb5",
    TIME_BASIS_EVENT_WINDOWS: "\u6d2a\u6c34\u4e8b\u4ef6\u7a97\u53e3",
    TIME_BASIS_FORECAST_WINDOW: "\u9884\u62a5\u7a97\u53e3",
}

EVENT_PURPOSE_ALIASES = {
    "calibration": "calibration",
    "calib": "calibration",
    "train": "calibration",
    "training": "calibration",
    "\u7387\u5b9a": "calibration",
    "\u8bad\u7ec3": "calibration",
    "validation": "validation",
    "valid": "validation",
    "val": "validation",
    "verify": "validation",
    "\u9a8c\u8bc1": "validation",
    "diagnostic": "diagnostic",
    "diag": "diagnostic",
    "\u8bca\u65ad": "diagnostic",
    "\u590d\u6838": "diagnostic",
}

EVENT_INITIAL_STATE_POLICY_ALIASES = {
    "event_warmup": "event_warmup",
    "event-preheat": "event_warmup",
    "event_preheat": "event_warmup",
    "independent_warmup": "event_warmup",
    "warmup_each_event": "event_warmup",
    "warmup": "event_warmup",
    "\u4e8b\u4ef6\u9884\u70ed": "event_warmup",
    "\u9010\u573a\u9884\u70ed": "event_warmup",
    "fixed_initial": "fixed_initial",
    "fixed": "fixed_initial",
    "default_initial": "fixed_initial",
    "constant": "fixed_initial",
    "\u56fa\u5b9a\u521d\u503c": "fixed_initial",
    "\u56fa\u5b9a\u521d\u59cb\u72b6\u6001": "fixed_initial",
    "\u9ed8\u8ba4\u521d\u503c": "fixed_initial",
    "source_state": "source_state",
    "restart_state": "source_state",
    "snapshot": "source_state",
    "hot_start": "source_state",
    "\u6765\u6e90\u72b6\u6001": "source_state",
    "\u72b6\u6001\u5feb\u7167": "source_state",
    "\u8d77\u62a5\u72b6\u6001": "source_state",
    "continuous_state": "continuous_state",
    "continuous": "continuous_state",
    "carryover": "continuous_state",
    "carry_over": "continuous_state",
    "\u8fde\u7eed\u72b6\u6001": "continuous_state",
    "\u4e8b\u4ef6\u95f4\u8fde\u7eed": "continuous_state",
}

EVENT_INITIAL_STATE_POLICY_SUMMARIES = {
    "event_warmup": {
        "label": "\u4e8b\u4ef6\u9884\u70ed",
        "state_continuity_between_events": False,
        "note": "\u6bcf\u573a\u6d2a\u6c34\u72ec\u7acb\u786e\u5b9a\u521d\u59cb\u72b6\u6001\uff0c\u4e8b\u4ef6\u4e4b\u95f4\u4e0d\u4f20\u9012\u72b6\u6001\u3002",
        "warning": "",
    },
    "fixed_initial": {
        "label": "\u56fa\u5b9a\u521d\u503c",
        "state_continuity_between_events": False,
        "note": "\u6bcf\u573a\u4e8b\u4ef6\u4f7f\u7528\u9ed8\u8ba4\u6216\u6307\u5b9a\u521d\u59cb\u72b6\u6001\uff0c\u4e8b\u4ef6\u4e4b\u95f4\u4e0d\u4f20\u9012\u72b6\u6001\u3002",
        "warning": "\u56fa\u5b9a\u521d\u503c\u5bf9\u524d\u671f\u542b\u6c34\u91cf\u3001\u79ef\u96ea\u548c\u6c47\u6d41\u8bb0\u5fc6\u7684\u4e0d\u786e\u5b9a\u6027\u8f83\u9ad8\uff0c\u5b9c\u4ec5\u7528\u4e8e\u8d44\u6599\u6781\u77ed\u7684\u6b21\u6d2a\u590d\u6838\u3002",
    },
    "source_state": {
        "label": "\u6765\u6e90\u72b6\u6001",
        "state_continuity_between_events": False,
        "note": "\u6bcf\u573a\u6d2a\u6c34\u4f7f\u7528\u5916\u90e8\u8fde\u7eed\u6a21\u62df\u72b6\u6001\u4f5c\u4e3a\u521d\u503c\u3002",
        "warning": "",
    },
    "continuous_state": {
        "label": "\u8fde\u7eed\u72b6\u6001",
        "state_continuity_between_events": True,
        "note": "\u4e8b\u4ef6\u95f4\u6309\u8fde\u7eed\u8fc7\u7a0b\u4f20\u9012\u72b6\u6001\uff0c\u8981\u6c42\u4e8b\u4ef6\u4e4b\u95f4\u5f3a\u8feb\u8d44\u6599\u8fde\u7eed\u3002",
        "warning": "\u8fde\u7eed\u72b6\u6001\u7b56\u7565\u4e0d\u9002\u5408\u4e8b\u4ef6\u4e4b\u95f4\u5b58\u5728\u8d44\u6599\u7f3a\u53e3\u7684\u4e8b\u4ef6\u7a97\u53e3\u96c6\u5408\u3002",
    },
}


def truthy_config(value: Any, default: bool = False) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return default
    raw = str(value).strip().lower()
    if raw in {"1", "true", "yes", "y", "on", "\u542f\u7528", "\u662f"}:
        return True
    if raw in {"0", "false", "no", "n", "off", "\u7981\u7528", "\u5426"}:
        return False
    return default


def flood_event_raw_config(config: dict[str, Any]) -> dict[str, Any]:
    raw = config.get("\u6d2a\u6c34\u4e8b\u4ef6\u7387\u5b9a", {})
    if isinstance(raw, list):
        return {"\u542f\u7528": bool(raw), "\u4e8b\u4ef6\u8868": raw}
    if isinstance(raw, dict):
        cfg = dict(raw)
    else:
        cfg = {}
    event_mode = config.get("\u4e8b\u4ef6\u8d44\u6599\u6a21\u5f0f", {})
    if isinstance(event_mode, dict):
        for key, value in event_mode.items():
            cfg.setdefault(key, value)
    for key in ("\u4e8b\u4ef6\u8868", "events"):
        if key in config and key not in cfg:
            cfg[key] = config.get(key)
    return cfg


def normalize_event_initial_state_policy(value: Any) -> str:
    raw = str(value or "event_warmup").strip()
    if not raw:
        return "event_warmup"
    key = raw.lower()
    return EVENT_INITIAL_STATE_POLICY_ALIASES.get(key, EVENT_INITIAL_STATE_POLICY_ALIASES.get(raw, key))


def event_initial_state_policy_summary(value: Any) -> dict[str, Any]:
    policy = normalize_event_initial_state_policy(value)
    summary = dict(EVENT_INITIAL_STATE_POLICY_SUMMARIES.get(policy, {}))
    if not summary:
        summary = {
            "label": str(value or policy or "\u672a\u8bb0\u5f55"),
            "state_continuity_between_events": False,
            "note": "\u6309\u914d\u7f6e\u7684\u4e8b\u4ef6\u521d\u59cb\u6761\u4ef6\u7b56\u7565\u5904\u7406\u3002",
            "warning": "",
        }
    summary["policy"] = policy
    return summary


def task_time_basis(config: dict[str, Any], *, context: str = "calibration") -> str:
    if context == "forecast":
        return TIME_BASIS_FORECAST_WINDOW
    raw = str(
        config.get("\u4efb\u52a1\u65f6\u6bb5\u6a21\u5f0f")
        or config.get("time_basis")
        or config.get("\u8d44\u6599\u65f6\u6bb5\u6a21\u5f0f")
        or ""
    ).strip().lower()
    if raw in {"event", "events", "event_window", "event_windows", "flood_event", "\u6d2a\u6c34\u4e8b\u4ef6", "\u4e8b\u4ef6\u7a97\u53e3", "\u4e8b\u4ef6\u8d44\u6599"}:
        return TIME_BASIS_EVENT_WINDOWS
    if raw in {"forecast", "forecast_window", "\u9884\u62a5", "\u9884\u62a5\u7a97\u53e3"}:
        return TIME_BASIS_FORECAST_WINDOW
    event_cfg = flood_event_raw_config(config)
    event_mode = config.get("\u4e8b\u4ef6\u8d44\u6599\u6a21\u5f0f", {})
    event_enabled = truthy_config(event_cfg.get("\u542f\u7528", event_cfg.get("enabled")), default=False)
    event_data_enabled = truthy_config(
        event_cfg.get("\u4e8b\u4ef6\u7a97\u53e3\u8d44\u6599", event_cfg.get("event_windows_enabled")),
        default=False,
    )
    if isinstance(event_mode, dict):
        event_data_enabled = truthy_config(
            event_mode.get("\u542f\u7528", event_mode.get("enabled")),
            default=event_data_enabled,
        )
    has_events = bool(
        event_cfg.get("\u4e8b\u4ef6\u8868")
        or event_cfg.get("events")
        or event_cfg.get("\u4e8b\u4ef6\u8868\u8def\u5f84")
        or event_cfg.get("events_file")
    )
    if event_enabled and (event_data_enabled or raw in {"event_segments", "\u4e8b\u4ef6\u8d44\u6599\u6a21\u5f0f"}):
        return TIME_BASIS_EVENT_WINDOWS
    if raw in {"continuous", "full", "\u8fde\u7eed", "\u8fde\u7eed\u65f6\u6bb5", ""}:
        return TIME_BASIS_CONTINUOUS
    return TIME_BASIS_EVENT_WINDOWS if event_data_enabled and has_events else TIME_BASIS_CONTINUOUS


def event_field(event: dict[str, Any], *names: str) -> Any:
    for name in names:
        if name in event and event.get(name) not in (None, ""):
            return event.get(name)
    lower_map = {str(key).strip().lower(): value for key, value in event.items()}
    for name in names:
        value = lower_map.get(str(name).strip().lower())
        if value not in (None, ""):
            return value
    return None


def parse_event_timestamp(value: Any, *, end: bool, step_hours: float) -> pd.Timestamp | None:
    if value in (None, ""):
        return None
    ts = pd.to_datetime(value)
    if end and step_hours < 24.0 and is_date_only_string(value):
        ts = ts + pd.Timedelta(days=1) - pd.Timedelta(hours=step_hours)
    return pd.Timestamp(ts)


def event_date_range(start: pd.Timestamp, end: pd.Timestamp, step_hours: float) -> pd.DatetimeIndex:
    if end < start:
        return pd.DatetimeIndex([])
    return pd.date_range(start, end, freq=pd.Timedelta(hours=step_hours))


def event_window_index(events: list[dict[str, Any]], start_key: str, end_key: str, step_hours: float) -> pd.DatetimeIndex:
    values: list[pd.Timestamp] = []
    for event in events:
        start = event.get(start_key)
        end = event.get(end_key)
        if start is None or end is None or end < start:
            continue
        values.extend(list(event_date_range(pd.Timestamp(start), pd.Timestamp(end), step_hours)))
    if not values:
        return pd.DatetimeIndex([])
    return pd.DatetimeIndex(sorted(set(pd.Timestamp(item) for item in values)))
