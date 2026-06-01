#!/usr/bin/env python
# -*- coding: utf-8 -*-
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable


@dataclass(frozen=True)
class ForwardSimulationStartContext:
    build_forward_payload_context: Callable[[dict[str, Any]], dict[str, Any]]


@dataclass(frozen=True)
class ForwardSimulationStartPlan:
    label: str
    command: list[str]
    metadata: dict[str, Any]


def forward_simulation_start_plan(
    payload: dict[str, Any],
    context: ForwardSimulationStartContext,
) -> ForwardSimulationStartPlan:
    forward_context = context.build_forward_payload_context(payload)
    run_path = Path(forward_context["run_dir"])
    return ForwardSimulationStartPlan(
        label=f"保存并重算 | {run_path.name}",
        command=["forward_sim"],
        metadata={
            "config_path": str(Path(forward_context["config_path"]).resolve()),
            "run_path": str(run_path.resolve()),
            "profile": forward_context["profile"],
            "runtime_prec_source": forward_context["prec_source"],
            "objective_mode": forward_context["objective_mode"],
            "glacier_mode": forward_context["glacier_mode"],
        },
    )
