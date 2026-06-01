#!/usr/bin/env python
# -*- coding: utf-8 -*-
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable


@dataclass(frozen=True)
class ManualStartStartContext:
    build_workspace_forward_context: Callable[[dict[str, Any]], dict[str, Any]]


@dataclass(frozen=True)
class ManualStartStartPlan:
    label: str
    command: list[str]
    metadata: dict[str, Any]


def manual_start_start_plan(
    payload: dict[str, Any],
    config_path: Path,
    context: ManualStartStartContext,
) -> ManualStartStartPlan:
    forward_context = context.build_workspace_forward_context({**payload, "config_path": str(config_path)})
    config = dict(forward_context["config"])
    basin_name = str(config.get("流域名称", config_path.stem)).strip() or config_path.stem
    return ManualStartStartPlan(
        label=f"手调起点 | {basin_name}",
        command=["manual_start"],
        metadata={
            "config_path": str(config_path.resolve()),
            "profile": forward_context["profile"],
            "runtime_prec_source": forward_context["prec_source"],
            "objective_mode": forward_context["objective_mode"],
            "glacier_mode": forward_context["glacier_mode"],
            "ui_progress": {"stage": "准备启动", "label": "手调起点"},
        },
    )
