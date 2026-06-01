#!/usr/bin/env python
# -*- coding: utf-8 -*-
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable


@dataclass(frozen=True)
class DashboardContext:
    list_templates: Callable[[], list[dict[str, Any]]]
    list_workspaces: Callable[[], list[dict[str, Any]]]
    list_runs: Callable[[], list[dict[str, Any]]]
    list_tasks: Callable[[], list[dict[str, Any]]]
    project_root: Path
    gui_root: Path
    builtin_dem: Path
    builtin_dem_1km: Path
    builtin_dem_0p1: Path
    project_runtime_dir: Path


def dashboard_payload(context: DashboardContext) -> dict[str, Any]:
    templates = context.list_templates()
    workspaces = context.list_workspaces()
    runs = context.list_runs()
    tasks = context.list_tasks()
    return {
        "project": {
            "project_root": str(context.project_root),
            "gui_root": str(context.gui_root),
            "builtin_dem": str(context.builtin_dem.resolve()),
            "builtin_dems": {
                "1km": str(context.builtin_dem_1km.resolve()),
                "0p1deg": str(context.builtin_dem_0p1.resolve()),
            },
            "runtime_root": str(context.project_runtime_dir.resolve()),
        },
        "counts": {
            "templates": len(templates),
            "workspaces": len(workspaces),
            "runs": len(runs),
            "tasks": len(tasks),
        },
        "templates": templates,
        "workspaces": workspaces,
        "runs": runs,
        "tasks": tasks,
    }
