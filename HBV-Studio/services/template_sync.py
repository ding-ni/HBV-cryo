#!/usr/bin/env python
# -*- coding: utf-8 -*-
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable


@dataclass(frozen=True)
class TuotuoheSyncStartContext:
    list_drives: Callable[[], list[str]]
    env_get: Callable[[str, str], str]
    build_python_script_command: Callable[..., list[str]]
    tuotuohe_sync_script: Path
    project_runtime_dir: Path
    gui_root: Path


@dataclass(frozen=True)
class TuotuoheSyncStartPlan:
    label: str
    command: list[str]
    cwd: Path


def _default_tuotuohe_target_root(project_runtime_dir: Path) -> Path:
    return project_runtime_dir / "沱沱河" / "数据"


def tuotuohe_sync_start_plan(
    payload: dict[str, Any],
    context: TuotuoheSyncStartContext,
) -> TuotuoheSyncStartPlan:
    source_root = str(payload.get("source_root", "")).strip()
    if not source_root:
        env_source = str(context.env_get("HBV_TUOTUOHE_SOURCE_ROOT", "")).strip()
        if env_source and Path(env_source).exists():
            source_root = env_source
        else:
            for drive in context.list_drives():
                candidate = Path(drive) / "Hapi" / "data"
                if candidate.exists():
                    source_root = str(candidate.resolve(strict=False))
                    break
    if not source_root:
        raise ValueError("未找到历史数据源目录。请将旧目录放在任一盘符的 Hapi\\data 下，或显式传入 source_root。")

    target_root = str(payload.get("target_root", _default_tuotuohe_target_root(context.project_runtime_dir)))
    command = context.build_python_script_command(context.tuotuohe_sync_script, "--source", source_root, "--target", target_root)
    if bool(payload.get("include_raw", False)):
        command.append("--include-raw")
    return TuotuoheSyncStartPlan(
        label="同步沱沱河模板数据",
        command=command,
        cwd=context.gui_root,
    )
