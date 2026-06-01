#!/usr/bin/env python
# -*- coding: utf-8 -*-
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable


@dataclass(frozen=True)
class CalibrationStartContext:
    resolve_path: Callable[..., Path]
    read_runtime_config: Callable[[Path], dict[str, Any]]
    current_profile: Callable[[dict[str, Any]], str]
    resolve_runtime_precip_source: Callable[[dict[str, Any], Any], str]
    validate_workspace_fields: Callable[..., dict[str, Any]]
    config_text_value: Callable[[dict[str, Any], str], str]
    resolve_config_related_path: Callable[[dict[str, Any], Any], Path | None]
    build_profile_paths: Callable[[dict[str, Any], str], dict[str, Any]]
    resolve_legacy_precip_source: Callable[[str], str]
    glacier_formal_requirements: Callable[[dict[str, Any], str], dict[str, Any]]
    resolve_objective_mode: Callable[[dict[str, Any], Any, str], str]
    resolve_param_bounds_profile: Callable[[dict[str, Any], Any, str], str]
    resolve_calibration_workflow: Callable[[dict[str, Any], Any, str], str]
    calibration_workflow_status: Callable[[str], str]
    find_manual_preset: Callable[[str, str], dict[str, Any]]
    build_forward_runtime_cli_args: Callable[..., Any]
    load_legacy_module: Callable[[Any], Any]
    old_script_path: Callable[[dict[str, Any], str, str], Any]
    patch_runtime_environment: Callable[[Any, dict[str, Any], str, Any], Any]
    patch_profile_behavior: Callable[[Any, dict[str, Any], str, str, str], Any]
    build_runtime_param_vector: Callable[[Any, dict[str, Any]], tuple[Any, dict[str, Any], Any]]
    build_python_script_command: Callable[..., list[str]]
    model_runner: Path
    observed_flow_key: str
    calibration_methods: dict[str, str]
    profile_daily: str
    profile_labels: dict[str, str]
    param_bounds_profile_labels: dict[str, str]


@dataclass(frozen=True)
class CalibrationStartPlan:
    label: str
    command: list[str]
    metadata: dict[str, Any]


def calibration_start_plan(payload: dict[str, Any], context: CalibrationStartContext) -> CalibrationStartPlan:
    config_path = context.resolve_path(str(payload.get("config_path", "")), must_exist=True)
    config = context.read_runtime_config(config_path)
    profile = str(payload.get("calibration_mode", "")).strip().lower() or context.current_profile(config)
    runtime_prec_source = context.resolve_runtime_precip_source(config, payload.get("prec_source", None))
    quick_test = bool(payload.get("quick_test", False))
    validation_stage = "quick_test" if quick_test else "calibration"
    validation = context.validate_workspace_fields(
        str(config_path),
        stage=validation_stage,
        precip_source=runtime_prec_source,
    )
    if not validation["valid"]:
        task_label = "输入预核算" if quick_test else "率定"
        raise ValueError(f"输入检查未通过，无法启动{task_label}：\n- " + "\n- ".join(validation["missing"][:8]))
    if not quick_test:
        obs_path = context.config_text_value(config, context.observed_flow_key)
        if not obs_path:
            raise ValueError(f"输入检查未通过，无法启动率定：\n- {context.observed_flow_key}")
        obs_file = context.resolve_config_related_path(config, obs_path)
        if obs_file is None or not obs_file.exists():
            raise ValueError(f"输入检查未通过，无法启动率定：\n- 观测径流文件不存在：{obs_path}")

    paths = context.build_profile_paths(config, profile)
    maxiter = int(payload.get("maxiter", 24))
    workers = int(payload.get("workers", 4))
    legacy_prec_source = context.resolve_legacy_precip_source(runtime_prec_source)
    context.glacier_formal_requirements(config, profile)
    objective_mode = context.resolve_objective_mode(config, payload.get("objective_mode", None), profile)
    param_bounds_profile = context.resolve_param_bounds_profile(
        config,
        payload.get("param_bounds_profile", None),
        profile,
    )
    calibration_workflow = context.resolve_calibration_workflow(
        config,
        payload.get("calibration_workflow", None),
        profile,
    )
    calibration_workflow_status = context.calibration_workflow_status(calibration_workflow)
    method = str(payload.get("method", "de")).strip().lower() or "de"
    if method not in context.calibration_methods:
        raise ValueError(f"未知率定方法：{method}")

    mc_samples = int(payload.get("mc_samples", 300))
    init_bound_shrink = max(0.0, float(payload.get("init_bound_shrink", 0.0) or 0.0))
    debug_days = max(0, int(payload.get("debug_days", 0) or 0))
    if quick_test:
        debug_days = 0
    refine_enabled_payload = bool(payload.get("refine_enabled", False))
    refine_maxiter_payload = max(0, int(payload.get("refine_maxiter", 0) or 0))
    if quick_test or method not in {"de", "mc_screen_de"}:
        refine_cli_value = 0
        refine_metadata_value = 0
    elif refine_enabled_payload and refine_maxiter_payload > 0:
        refine_cli_value = refine_maxiter_payload
        refine_metadata_value = refine_maxiter_payload
    elif refine_enabled_payload:
        refine_cli_value = -1
        refine_metadata_value = min(20, max(6, int(round(maxiter * 0.25))))
    else:
        refine_cli_value = 0
        refine_metadata_value = 0

    init_params_file = ""
    preset_id = str(payload.get("init_preset_id", "")).strip()
    if preset_id:
        preset = context.find_manual_preset(str(config_path), preset_id)
        preset_profile = str(preset.get("calibration_profile", "")).strip().lower()
        if preset_profile and preset_profile != profile:
            raise ValueError(
                f"所选手调参数集属于 {context.profile_labels.get(preset_profile, preset_profile)}，"
                f"与当前率定模式 {context.profile_labels.get(profile, profile)} 不一致。"
            )
        paths["cache_dir"].mkdir(parents=True, exist_ok=True)
        init_file = Path(paths["cache_dir"]) / f"init_params_{preset_id}.json"
        preset_params = dict(preset.get("params", {}))
        cli_args = context.build_forward_runtime_cli_args(
            config_path,
            profile,
            prec_source=runtime_prec_source,
            glacier_mode=str(payload.get("glacier_mode", "inline")).strip().lower() or "inline",
            objective_mode=objective_mode,
        )
        module = context.load_legacy_module(context.old_script_path(config, "model", "calibrate_hbv_cryo.py"))
        context.patch_runtime_environment(module, config, profile, cli_args)
        context.patch_profile_behavior(module, config, profile, objective_mode, param_bounds_profile)
        configure_time_step = getattr(module, "configure_time_step", None)
        if callable(configure_time_step):
            configure_time_step()
        _, complete_params, _ = context.build_runtime_param_vector(module, preset_params)
        init_file.write_text(json.dumps(complete_params, ensure_ascii=False, indent=2), encoding="utf-8")
        init_params_file = str(init_file)

    command = context.build_python_script_command(
        context.model_runner,
        "--配置", str(config_path),
        "--率定模式", profile,
        "--method", method,
        "--workers", str(workers),
        "--maxiter", str(maxiter),
        "--popsize", str(int(payload.get("popsize", 6))),
        "--seed", str(int(payload.get("seed", 42))),
        "--mc-samples", str(mc_samples),
        "--目标函数", objective_mode,
        "--calibration-workflow", calibration_workflow,
        "--冰川模式", str(payload.get("glacier_mode", "inline")),
    )
    if profile == context.profile_daily:
        command.extend(["--param-bounds-profile", param_bounds_profile])
    if runtime_prec_source == "custom_tif":
        command.extend(["--降水源", "custom_tif", "--prec-dir", str(paths["aligned_prec_custom_dir"])])
    elif runtime_prec_source == "era5":
        command.extend(["--降水源", "era5"])
    else:
        command.extend(["--降水源", legacy_prec_source])
    if init_params_file:
        command.extend(["--init-params-file", init_params_file, "--init-bound-shrink", str(init_bound_shrink)])
    if debug_days > 0:
        command.extend(["--debug-days", str(debug_days)])
    if refine_cli_value != -1:
        command.extend(["--refine-maxiter", str(refine_cli_value)])
    if quick_test:
        command.extend(["--quick-test", "--quick-days", str(int(payload.get("quick_days", 30)))])

    task_name = "输入预核算" if quick_test else ("快速试算" if debug_days > 0 else "率定任务")
    label = f"{task_name} | {config_path.stem} | {context.profile_labels.get(profile, profile)}"
    metadata = {
        "config_path": str(config_path),
        "logs_dir": str(paths["logs_dir"]),
        "profile": profile,
        "objective_mode": objective_mode,
        "param_bounds_profile": param_bounds_profile,
        "param_bounds_profile_label": context.param_bounds_profile_labels.get(
            param_bounds_profile,
            param_bounds_profile,
        ),
        "calibration_workflow": calibration_workflow,
        "calibration_workflow_status": calibration_workflow_status,
        "method": method,
        "maxiter": maxiter,
        "mc_samples": mc_samples,
        "debug_days": debug_days,
        "init_preset_id": preset_id,
        "init_bound_shrink": init_bound_shrink,
        "runtime_prec_source": runtime_prec_source,
        "refine_enabled": refine_enabled_payload and refine_metadata_value > 0,
        "refine_maxiter": refine_metadata_value,
        "quick_test": quick_test,
        "ui_progress": {
            "stage": "启动率定任务",
            "label": "正在加载模型、驱动和目标函数",
        },
    }
    return CalibrationStartPlan(label=label, command=command, metadata=metadata)
