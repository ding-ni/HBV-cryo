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


@dataclass(frozen=True)
class DataPrepTaskOutputContext:
    resolve_path: Callable[..., Path]
    read_runtime_config: Callable[[Path], dict[str, Any]]
    task_step_map: Callable[[str, dict[str, Any]], dict[str, dict[str, Any]]]
    current_profile: Callable[[dict[str, Any]], str]
    resolve_runtime_precip_source: Callable[[dict[str, Any], Any], str]


@dataclass(frozen=True)
class DataPrepStartContext:
    resolve_path: Callable[..., Path]
    read_runtime_config: Callable[[Path], dict[str, Any]]
    task_step_map: Callable[[str, dict[str, Any]], dict[str, dict[str, Any]]]
    current_profile: Callable[[dict[str, Any]], str]
    resolve_runtime_precip_source: Callable[[dict[str, Any], Any], str]
    resolve_legacy_precip_source: Callable[[str], str]
    data_prep_status: Callable[[str, Any], list[dict[str, Any]]]
    build_python_script_command: Callable[..., list[str]]
    clear_meteo_state: Callable[..., None]
    forcing_pipeline_step_ids: frozenset[str]


@dataclass(frozen=True)
class DataPrepStartPlan:
    label: str
    command: list[str]
    metadata: dict[str, Any]


@dataclass(frozen=True)
class DataPrepWorkflowDecision:
    ready: list[str]
    skipped_done: list[str]
    skipped_manual: list[str]
    blocked: list[str]
    completed_ids: set[str]
    remaining: list[str]


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


def verify_data_prep_step_output(
    step: dict[str, Any],
    config: dict[str, Any],
    runtime_prec_source: Any = None,
) -> tuple[bool, str]:
    check = step.get("check")
    if not callable(check):
        return True, "该步骤没有产物检查函数。"
    try:
        if step.get("needs_prec_source"):
            done, message, _ = check(config, runtime_prec_source)
        else:
            done, message, _ = check(config)
    except Exception as exc:
        return False, f"产物检查异常：{exc}"
    return bool(done), str(message or "")


def verify_data_prep_task_output(
    metadata: dict[str, Any],
    context: DataPrepTaskOutputContext,
) -> tuple[bool, str]:
    config_path_raw = str(metadata.get("config_path", "")).strip()
    step_id = str(metadata.get("step_id", "")).strip()
    if not config_path_raw or not step_id:
        return True, "缺少步骤产物检查上下文。"
    try:
        config_path = context.resolve_path(config_path_raw, must_exist=True)
        config = context.read_runtime_config(config_path)
        steps = context.task_step_map(context.current_profile(config), config)
        step = steps.get(step_id)
        if step is None:
            return True, f"未知步骤 {step_id}，跳过产物复核。"
        runtime_prec_source = context.resolve_runtime_precip_source(
            config,
            metadata.get("runtime_prec_source", None),
        )
        return verify_data_prep_step_output(step, config, runtime_prec_source)
    except Exception as exc:
        return False, f"产物检查准备失败：{exc}"


def data_prep_step_command(
    step: dict[str, Any],
    config_path: Path,
    payload: dict[str, Any],
    context: DataPrepStartContext,
) -> list[str]:
    command = context.build_python_script_command(step["script"], "--配置", str(config_path))
    if step.get("needs_prec_source"):
        config = context.read_runtime_config(config_path)
        runtime_prec_source = context.resolve_runtime_precip_source(config, payload.get("prec_source", None))
        command.extend(
            [
                "--降水源",
                runtime_prec_source
                if runtime_prec_source in {"era5", "custom_tif"}
                else context.resolve_legacy_precip_source(runtime_prec_source),
            ]
        )
    if step.get("supports_overwrite") and bool(payload.get("overwrite", False)):
        command.append("--覆盖")
    return command


def data_prep_start_plan(payload: dict[str, Any], context: DataPrepStartContext) -> DataPrepStartPlan:
    config_path = context.resolve_path(str(payload.get("config_path", "")), must_exist=True)
    config = context.read_runtime_config(config_path)
    runtime_prec_source = context.resolve_runtime_precip_source(config, payload.get("prec_source", None))
    profile = context.current_profile(config)
    steps = context.task_step_map(profile, config)
    step_id = str(payload.get("step_id", "")).strip()
    if step_id not in steps:
        raise ValueError(f"未知的数据准备步骤：{step_id}")
    step = steps[step_id]
    if step.get("manual"):
        raise ValueError("这个步骤是手动导入步骤，不支持直接启动脚本。")

    status_map = {item["id"]: item for item in context.data_prep_status(str(config_path), runtime_prec_source)}
    blocked_by = list(status_map.get(step_id, {}).get("blocked_by", []) or [])
    if blocked_by:
        titles = [steps[item]["title"] for item in blocked_by if item in steps]
        raise ValueError(f"步骤前置依赖未完成：{', '.join(titles)}")
    if step_id in context.forcing_pipeline_step_ids:
        context.clear_meteo_state(config)

    metadata = {
        "config_path": str(config_path.resolve()),
        "profile": profile,
        "runtime_prec_source": runtime_prec_source,
        "step_id": step_id,
        "step_title": step["title"],
        "step_titles": [step["title"]],
        "ui_progress": {"stage": "执行脚本", "current": 0, "total": 1, "label": step["title"]},
    }
    return DataPrepStartPlan(
        label=f"数据准备 | {step['title']} | {config_path.stem}",
        command=data_prep_step_command(step, config_path, payload, context),
        metadata=metadata,
    )


def data_prep_workflow_decision(
    remaining: list[str],
    completed_ids: set[str],
    steps: dict[str, dict[str, Any]],
    status_map: dict[str, dict[str, Any]],
    *,
    overwrite: bool = False,
) -> DataPrepWorkflowDecision:
    completed = set(completed_ids)
    ready: list[str] = []
    skipped_done: list[str] = []
    skipped_manual: list[str] = []
    blocked: list[str] = []

    for sid in remaining:
        step = steps[sid]
        if status_map.get(sid, {}).get("done") and not overwrite:
            skipped_done.append(sid)
            completed.add(sid)
            continue
        deps = step.get("depends_on", [])
        unmet = [dep for dep in deps if dep not in completed]
        if unmet:
            blocked.append(sid)
        elif step.get("manual"):
            skipped_manual.append(sid)
            completed.add(sid)
        else:
            ready.append(sid)

    return DataPrepWorkflowDecision(
        ready=ready,
        skipped_done=skipped_done,
        skipped_manual=skipped_manual,
        blocked=blocked,
        completed_ids=completed,
        remaining=[sid for sid in remaining if sid not in completed],
    )
