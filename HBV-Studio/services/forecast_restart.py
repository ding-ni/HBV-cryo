#!/usr/bin/env python
# -*- coding: utf-8 -*-
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable


@dataclass(frozen=True)
class ForecastRestartStartContext:
    build_args: Callable[[dict[str, Any]], Any]
    resolve_path: Callable[..., Path]
    ensure_input_ready: Callable[[dict[str, Any]], dict[str, Any]]


@dataclass(frozen=True)
class ForecastRestartStartPlan:
    label: str
    command: list[str]
    metadata: dict[str, Any]
    checked_payload: dict[str, Any]


def forecast_restart_start_plan(
    payload: dict[str, Any],
    context: ForecastRestartStartContext,
) -> ForecastRestartStartPlan:
    args = context.build_args(payload)
    source_run = context.resolve_path(args.source_run, must_exist=True)
    input_check = context.ensure_input_ready(payload)
    config_path = context.resolve_path(args.config, must_exist=True)
    return ForecastRestartStartPlan(
        label=f"连续状态预报 | {source_run.name}",
        command=["forecast_restart"],
        metadata={
            "config_path": str(config_path.resolve(strict=False)),
            "run_path": str(source_run.resolve(strict=False)),
            "forecast_start": args.forecast_start,
            "forecast_end": args.forecast_end,
            "runtime_prec_source": args.prec_source,
            "glacier_mode": args.glacier_mode,
            "forecast_input_check": input_check,
            "ui_progress": {"stage": "准备启动", "label": "连续状态预报"},
        },
        checked_payload={**payload, "_forecast_input_check": input_check},
    )
