#!/usr/bin/env python
# -*- coding: utf-8 -*-
from __future__ import annotations

import argparse
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


def forecast_restart_args(
    payload: dict[str, Any],
    *,
    resolve_path: Callable[..., Path],
    read_json_file: Callable[[Path], dict[str, Any]],
) -> argparse.Namespace:
    config_path = str(payload.get("config_path", payload.get("config", "")) or "").strip()
    source_run = str(payload.get("source_run", payload.get("run_path", "")) or "").strip()
    if not config_path:
        run_path = resolve_path(source_run, must_exist=True)
        metadata = read_json_file(run_path / "metadata.json")
        config_path = str(metadata.get("workspace_config", "") or "").strip()
    if not config_path:
        raise ValueError("缺少工作区配置路径。")
    if not source_run:
        raise ValueError("缺少源结果目录。")
    forecast_end = str(payload.get("forecast_end", "") or "").strip()
    if not forecast_end:
        raise ValueError("缺少预报结束时间 forecast_end。")
    return argparse.Namespace(
        config=config_path,
        source_run=source_run,
        forecast_start=str(payload.get("forecast_start", "") or "").strip(),
        forecast_end=forecast_end,
        forecast_prec_dir=str(payload.get("forecast_prec_dir", payload.get("prec_dir", "")) or "").strip(),
        forecast_temp_dir=str(payload.get("forecast_temp_dir", payload.get("temp_dir", "")) or "").strip(),
        forecast_evap_dir=str(payload.get("forecast_evap_dir", payload.get("evap_dir", "")) or "").strip(),
        profile=str(payload.get("profile", payload.get("calibration_mode", "")) or "").strip(),
        objective_mode=str(payload.get("objective_mode", "") or "").strip(),
        prec_source=str(payload.get("prec_source", "custom_tif") or "custom_tif").strip(),
        glacier_mode=str(payload.get("glacier_mode", "inline") or "inline").strip(),
        output_dir=str(payload.get("output_dir", "") or "").strip(),
        forecast_input_check=dict(payload.get("_forecast_input_check") or payload.get("forecast_input_check") or {}),
        output_json="",
    )


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
