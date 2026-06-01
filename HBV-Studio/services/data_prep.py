#!/usr/bin/env python
# -*- coding: utf-8 -*-
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable


@dataclass(frozen=True)
class DataPrepContext:
    load_workspace_config: Callable[[str], tuple[Path, dict[str, Any]]]
    current_profile: Callable[[dict[str, Any]], str]
    data_prep_steps: Callable[[str], list[dict[str, Any]]]
    resolve_data_prep_step: Callable[[dict[str, Any], dict[str, Any] | None], dict[str, Any]]
    resolve_precip_source: Callable[[dict[str, Any], Any], str]
    find_running_task: Callable[[str, str], Any]
    profile_daily: str


def data_prep_steps_payload(config_path_raw: str, context: DataPrepContext) -> list[dict[str, Any]]:
    profile = context.profile_daily
    config = None
    if config_path_raw:
        _, config = context.load_workspace_config(config_path_raw)
        profile = context.current_profile(config)
    return [
        {
            "id": step["id"],
            "title": step["title"],
            "description": step["description"],
            "depends_on": step.get("depends_on", []),
            "optional": bool(step.get("optional", False)),
            "manual": bool(step.get("manual", False)),
            "needs_prec_source": bool(step.get("needs_prec_source", False)),
            "supports_overwrite": bool(step.get("supports_overwrite", False)),
        }
        for step in (
            context.resolve_data_prep_step(item, config)
            for item in context.data_prep_steps(profile)
        )
    ]


def data_prep_status(
    config_path_raw: str,
    context: DataPrepContext,
    precip_source: Any = None,
) -> list[dict[str, Any]]:
    cfg_path, config = context.load_workspace_config(config_path_raw)
    runtime_prec_source = context.resolve_precip_source(config, precip_source)
    steps = [
        context.resolve_data_prep_step(step, config)
        for step in context.data_prep_steps(context.current_profile(config))
    ]
    active_task = context.find_running_task("data_prep", str(cfg_path))
    active_step_id = str(active_task.metadata.get("step_id", "")).strip() if active_task is not None else ""
    active_progress = dict(active_task.metadata.get("ui_progress") or {}) if active_task is not None else {}
    done_set: set[str] = set()
    results: list[dict[str, Any]] = []
    for step in steps:
        if step.get("needs_prec_source"):
            done, message, count = step["check"](config, runtime_prec_source)
        else:
            done, message, count = step["check"](config)
        is_running = active_step_id == step["id"]
        if is_running:
            stage_label = str(active_progress.get("stage", "正在执行")).strip() or "正在执行"
            label = str(active_progress.get("label", step["title"])).strip() or step["title"]
            current = int(active_progress.get("current", 0) or 0)
            total = int(active_progress.get("total", 0) or 0)
            message = f"{stage_label}：{label}" + (f"（{current}/{total}）" if total > 0 else "") + "。"
        blocked_by = [dep for dep in step.get("depends_on", []) if dep not in done_set]
        if done:
            done_set.add(step["id"])
        results.append(
            {
                "id": step["id"],
                "title": step["title"],
                "description": step["description"],
                "done": done,
                "message": message,
                "file_count": count,
                "depends_on": step.get("depends_on", []),
                "blocked_by": blocked_by,
                "deps_met": not blocked_by,
                "optional": bool(step.get("optional", False)),
                "manual": bool(step.get("manual", False)),
                "supports_overwrite": bool(step.get("supports_overwrite", False)),
                "needs_prec_source": bool(step.get("needs_prec_source", False)),
                "running": is_running,
                "script": str(step["script"].resolve()) if step.get("script") else "",
            }
        )
    return results
