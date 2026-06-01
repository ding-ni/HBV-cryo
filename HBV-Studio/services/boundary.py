#!/usr/bin/env python
# -*- coding: utf-8 -*-
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

import pandas as pd


@dataclass(frozen=True)
class BoundaryPreviewContext:
    resolve_path: Callable[..., Path]
    read_config: Callable[[Path], dict[str, Any]]
    build_expected_time_index: Callable[[dict[str, Any]], pd.DatetimeIndex | None]
    normalize_time_step_hours: Callable[[Any], float]
    inspect_boundary_csv: Callable[..., dict[str, Any]]
    is_date_only_string: Callable[[Any], bool]


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
