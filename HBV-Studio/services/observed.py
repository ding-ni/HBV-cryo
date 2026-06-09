#!/usr/bin/env python
# -*- coding: utf-8 -*-
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

import pandas as pd


@dataclass(frozen=True)
class ObservedInfoContext:
    inspect_observed_csv: Callable[..., dict[str, Any]]


@dataclass(frozen=True)
class ObservedWindowContext:
    current_profile: Callable[[dict[str, Any]], str]
    normalize_time_step_hours: Callable[[Any], float]
    task_time_basis: Callable[..., str]
    format_timestamp_for_display: Callable[[pd.Timestamp, float], str]
    profile_labels: dict[str, str]
    profile_daily: str
    profile_hourly: str
    time_basis_event_windows: str


def observed_info(
    csv_path: str,
    context: ObservedInfoContext,
    *,
    date_field: str | None = None,
    target_step_hours: float | None = None,
) -> dict[str, Any]:
    return context.inspect_observed_csv(
        csv_path,
        date_field=date_field,
        target_step_hours=target_step_hours,
    )


def observed_window_messages(
    config: dict[str, Any],
    obs_info: dict[str, Any],
    context: ObservedWindowContext,
) -> tuple[list[str], list[str]]:
    issues: list[str] = []
    warnings: list[str] = []
    profile = context.current_profile(config)
    step_hours = context.normalize_time_step_hours(config.get("时间步长_小时", 24.0))
    effective_profile = str(
        obs_info.get("effective_calibration_mode")
        or obs_info.get("suggested_calibration_mode")
        or ""
    ).strip().lower()
    if effective_profile and effective_profile != profile:
        issues.append(f"观测径流时间步识别为 {context.profile_labels[effective_profile]}，与当前率定模式不一致。")
    elif profile == context.profile_daily and bool(obs_info.get("resampled_to_daily")):
        aggregation = dict(obs_info.get("daily_aggregation") or {})
        valid_days = int(aggregation.get("valid_days", 0) or 0)
        insufficient_days = int(aggregation.get("insufficient_days", 0) or 0)
        start_hour = int(aggregation.get("day_start_hour", 8) or 8)
        warnings.append(
            f"观测径流已从小时尺度按水文日（{start_hour:02d}:00 至次日 {start_hour:02d}:00）"
            f"聚合为日平均流量；有效日数 {valid_days} 天，小时覆盖不足天数 {insufficient_days} 天。"
        )
    coverage_ratio = obs_info.get("coverage_ratio")
    if coverage_ratio is not None:
        coverage_ratio = float(coverage_ratio)
        if coverage_ratio < 0.75:
            issues.append(f"观测径流在当前模拟时段内覆盖率只有 {coverage_ratio * 100:.1f}%，无法支撑稳定率定。")
        elif coverage_ratio < 0.95:
            warnings.append(f"观测径流在当前模拟时段内覆盖率只有 {coverage_ratio * 100:.1f}%，目标函数会只在部分时间步上计算。")

    if context.task_time_basis(config, context="calibration") == context.time_basis_event_windows:
        return issues, warnings

    obs_start = pd.to_datetime(obs_info.get("start"))
    obs_end = pd.to_datetime(obs_info.get("end"))
    time_cfg = dict(config.get("时间", {}))
    parsed: dict[str, pd.Timestamp] = {}
    for key in ("率定开始", "率定结束", "验证开始", "验证结束"):
        value = time_cfg.get(key)
        if not value:
            continue
        try:
            parsed[key] = pd.to_datetime(value)
        except Exception:
            continue

    for start_key, end_key, label in (("率定开始", "率定结束", "率定期"), ("验证开始", "验证结束", "验证期")):
        start_ts = parsed.get(start_key)
        end_ts = parsed.get(end_key)
        if start_ts is None or end_ts is None:
            continue
        if start_ts < obs_start:
            issues.append(
                f"{label}开始时间早于观测覆盖起点："
                f"{context.format_timestamp_for_display(start_ts, step_hours)} < "
                f"{context.format_timestamp_for_display(obs_start, step_hours)}"
            )
        if end_ts > obs_end:
            issues.append(
                f"{label}结束时间晚于观测覆盖终点："
                f"{context.format_timestamp_for_display(end_ts, step_hours)} > "
                f"{context.format_timestamp_for_display(obs_end, step_hours)}"
            )
        steps = int(((end_ts - start_ts) / pd.Timedelta(hours=step_hours)) + 1)
        if profile == context.profile_daily and steps < 180:
            warnings.append(f"{label}长度只有 {steps} 天，正式率定通常建议至少半年以上。")
        if profile == context.profile_hourly and steps < 24 * 30:
            warnings.append(f"{label}长度只有 {steps} 小时，小时尺度正式率定通常建议至少 30 天以上。")
    return issues, warnings
