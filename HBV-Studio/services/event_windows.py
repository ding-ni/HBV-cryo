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
    event_date_range,
    event_field,
    event_initial_state_policy_summary,
    flood_event_raw_config,
    parse_event_timestamp,
    truthy_config,
)
from services.event_io import read_event_table_file
from services.time_utils import normalize_time_step_hours


@dataclass(frozen=True)
class EventWindowContext:
    resolve_config_related_path: Callable[[dict[str, Any], Any], Path | None]


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
