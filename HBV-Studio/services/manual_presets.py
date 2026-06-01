#!/usr/bin/env python
# -*- coding: utf-8 -*-
from __future__ import annotations

import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

import profile_runner


@dataclass(frozen=True)
class ManualPresetContext:
    global_parameter_library_path: Path
    meteo_key: str
    meteo_precip_mode_key: str
    profile_labels: dict[str, str]
    resolve_path: Callable[..., Path]
    read_runtime_config: Callable[[Path], dict[str, Any]]
    read_json_file: Callable[[Path], dict[str, Any]]
    write_json_file: Callable[[Path, dict[str, Any]], None]
    replace_placeholders: Callable[..., Any]
    remap_legacy_project_path: Callable[[str], Any]
    to_portable_path: Callable[[str], str]
    resolve_source_run_reference: Callable[[Any, Any], str]
    normalize_run_metadata: Callable[..., tuple[dict[str, Any], Path | None]]
    sanitize_param_values: Callable[[dict[str, Any]], dict[str, float]]
    build_forward_runtime_cli_args: Callable[..., Any]
    build_runtime_param_vector: Callable[..., tuple[list[float], dict[str, float], bool]]
    is_studio_editable_metadata: Callable[[dict[str, Any], Path | None], bool]
    run_kind_from_metadata: Callable[[dict[str, Any] | None, bool], str]
    run_kind_label: Callable[[str], str]
    workspace_name_for_summary: Callable[[dict[str, Any], Path | None], str]
    task_time_basis: Callable[..., str]
    normalize_time_step_hours: Callable[[Any], float]
    resolve_profile: Callable[[dict[str, Any], Any], str]
    source_run_metadata_for_preset: Callable[[Any], tuple[dict[str, Any], Path | None, Path | None]] | None = None


def normalize_preset_scope(scope: Any) -> str:
    raw = str(scope or "workspace").strip().lower()
    if raw in {"global", "shared", "公共", "public"}:
        return "global"
    if raw in {"all", "both", "全部"}:
        return "all"
    return "workspace"


def _normalize_manual_preset_source_run(
    source_run_path_raw: Any,
    source_run_name_raw: Any,
    context: ManualPresetContext,
) -> tuple[str, str]:
    source_run_path = str(source_run_path_raw or "").strip()
    source_run_name = str(source_run_name_raw or "").strip()
    if not source_run_path:
        return "", source_run_name
    if not source_run_name:
        try:
            source_run_name = Path(str(context.replace_placeholders(source_run_path))).name
        except Exception:
            source_run_name = Path(source_run_path).name
    resolved_source_run = context.resolve_source_run_reference(source_run_path, source_run_name)
    if resolved_source_run:
        return context.to_portable_path(str(resolved_source_run)), source_run_name
    try:
        fallback = context.remap_legacy_project_path(str(context.replace_placeholders(source_run_path)))
    except Exception:
        fallback = source_run_path
    return context.to_portable_path(str(fallback or source_run_path)), source_run_name


def manual_preset_store_path(config_path_raw: str, context: ManualPresetContext, scope: str = "workspace") -> Path:
    if normalize_preset_scope(scope) == "global":
        return context.global_parameter_library_path
    cfg_path = context.resolve_path(config_path_raw, must_exist=True)
    config = context.read_runtime_config(cfg_path)
    results_root = Path(profile_runner.build_workspace_paths(config)["results_root"])
    return results_root / "manual_calibration_presets.json"


def load_manual_preset_store(config_path_raw: str, context: ManualPresetContext, scope: str = "workspace") -> dict[str, Any]:
    normalized_scope = normalize_preset_scope(scope)
    if normalized_scope == "all":
        raise ValueError("load_manual_preset_store 不支持 scope=all，请使用 list_manual_presets。")
    store_path = manual_preset_store_path(config_path_raw, context, normalized_scope)
    if not store_path.exists():
        return {"presets": [], "scope": normalized_scope}
    data = context.read_json_file(store_path)
    if not isinstance(data, dict):
        return {"presets": [], "scope": normalized_scope}
    presets = data.get("presets", [])
    if not isinstance(presets, list):
        presets = []
    normalized_presets: list[dict[str, Any]] = []
    for item in presets:
        if not isinstance(item, dict):
            continue
        current = dict(item)
        preset_id = str(current.get("parameter_set_id") or current.get("id") or "").strip()
        if preset_id:
            current["parameter_set_id"] = preset_id
        if "parameters" not in current and isinstance(current.get("params"), dict):
            current["parameters"] = dict(current.get("params", {}))
        if not current.get("source_workspace") and isinstance(current.get("context"), dict):
            current["source_workspace"] = str(current["context"].get("workspace_name", "") or "").strip()
        source_run_path, source_run_name = _normalize_manual_preset_source_run(
            current.get("source_run_path"),
            current.get("source_run_name"),
            context,
        )
        if source_run_path:
            current["source_run_path"] = source_run_path
        if source_run_name:
            current["source_run_name"] = source_run_name
        current["scope"] = str(current.get("scope", normalized_scope) or normalized_scope)
        normalized_presets.append(current)
    data["presets"] = normalized_presets
    data["scope"] = normalized_scope
    return data


def write_manual_preset_store(
    config_path_raw: str,
    data: dict[str, Any],
    context: ManualPresetContext,
    scope: str = "workspace",
) -> Path:
    normalized_scope = normalize_preset_scope(scope)
    if normalized_scope == "all":
        raise ValueError("写入参数集时必须指定 workspace 或 global。")
    store_path = manual_preset_store_path(config_path_raw, context, normalized_scope)
    context.write_json_file(store_path, data)
    return store_path


def list_manual_presets(
    config_path_raw: str,
    context: ManualPresetContext,
    calibration_profile: str | None = None,
    scope: str = "workspace",
) -> dict[str, Any]:
    cfg_path = context.resolve_path(config_path_raw, must_exist=True)
    normalized_scope = normalize_preset_scope(scope)
    if normalized_scope == "all":
        workspace_presets = list_manual_presets(str(cfg_path), context, calibration_profile, scope="workspace")
        global_presets = list_manual_presets(str(cfg_path), context, calibration_profile, scope="global")
        presets = sorted(
            list(workspace_presets.get("presets", [])) + list(global_presets.get("presets", [])),
            key=lambda item: float(item.get("updated_at", 0.0)),
            reverse=True,
        )
        return {
            "config_path": str(cfg_path),
            "scope": "all",
            "store_path": workspace_presets.get("store_path"),
            "global_store_path": global_presets.get("store_path"),
            "calibration_profile": str(calibration_profile or "").strip().lower() or None,
            "presets": presets,
        }
    data = load_manual_preset_store(str(cfg_path), context, normalized_scope)
    profile_filter = str(calibration_profile or "").strip().lower()
    presets = list(data.get("presets", []))
    if profile_filter:
        presets = [
            item for item in presets
            if (not str(item.get("calibration_profile", "")).strip())
            or str(item.get("calibration_profile", "")).strip().lower() == profile_filter
        ]
    presets = sorted(presets, key=lambda item: float(item.get("updated_at", 0.0)), reverse=True)
    return {
        "config_path": str(cfg_path),
        "store_path": str(manual_preset_store_path(str(cfg_path), context, normalized_scope)),
        "scope": normalized_scope,
        "calibration_profile": profile_filter or None,
        "presets": presets,
    }


def _format_epoch_text(value: Any) -> str:
    try:
        return time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(float(value)))
    except Exception:
        return ""


def _source_run_metadata_for_preset(
    source_run_raw: Any,
    context: ManualPresetContext,
) -> tuple[dict[str, Any], Path | None, Path | None]:
    raw = str(source_run_raw or "").strip()
    if not raw:
        return {}, None, None
    try:
        source_name = Path(str(context.replace_placeholders(raw))).name
    except Exception:
        source_name = Path(raw).name
    try:
        resolved = context.resolve_source_run_reference(raw, source_name)
        run_dir = context.resolve_path(resolved, must_exist=False)
    except Exception:
        try:
            run_dir = Path(str(context.replace_placeholders(raw))).expanduser().resolve(strict=False)
        except Exception:
            return {}, None, None
    metadata_path = run_dir / "metadata.json"
    if not metadata_path.exists():
        return {}, run_dir, None
    try:
        metadata, resolved_config = context.normalize_run_metadata(context.read_json_file(metadata_path), run_path=run_dir)
        return metadata, run_dir, resolved_config
    except Exception:
        try:
            return context.read_json_file(metadata_path), run_dir, None
        except Exception:
            return {}, run_dir, None


def _period_value(time_cfg: dict[str, Any], config_time: dict[str, Any], *keys: str) -> str:
    for key in keys:
        value = time_cfg.get(key)
        if value not in (None, ""):
            return str(value)
    for key in keys:
        value = config_time.get(key)
        if value not in (None, ""):
            return str(value)
    return ""


def _parameter_period_summary(
    config: dict[str, Any],
    metadata: dict[str, Any],
    context: ManualPresetContext,
) -> dict[str, Any]:
    time_cfg = dict(metadata.get("time_config", {}) or {})
    config_time = dict(config.get("时间", {}) or {})
    step_hours = (
        time_cfg.get("time_step_hours")
        or time_cfg.get("时间步长_小时")
        or config.get("时间步长_小时")
        or 24.0
    )
    return {
        "warmup_start": _period_value(time_cfg, config_time, "warmup_start", "预热开始"),
        "warmup_end": _period_value(time_cfg, config_time, "warmup_end", "预热结束"),
        "calibration_start": _period_value(time_cfg, config_time, "calib_start", "calibration_start", "率定开始"),
        "calibration_end": _period_value(time_cfg, config_time, "calib_end", "calibration_end", "率定结束"),
        "validation_start": _period_value(time_cfg, config_time, "valid_start", "validation_start", "验证开始"),
        "validation_end": _period_value(time_cfg, config_time, "valid_end", "validation_end", "验证结束"),
        "time_step_hours": context.normalize_time_step_hours(step_hours),
    }


def _parameter_metric_summary(metadata: dict[str, Any]) -> dict[str, Any]:
    metrics = dict(metadata.get("metrics", {}) or {})
    summary: dict[str, Any] = {}
    for period in ("calibration", "validation"):
        item = metrics.get(period)
        if not isinstance(item, dict):
            continue
        summary[period] = {
            key: item.get(key)
            for key in ("nse", "kge", "pbias", "rmse", "r2")
            if item.get(key) is not None
        }
    return summary


def save_manual_preset(payload: dict[str, Any], context: ManualPresetContext) -> dict[str, Any]:
    config_path_raw = str(payload.get("config_path", "")).strip()
    if not config_path_raw:
        raise ValueError("缺少 config_path。")
    name = str(payload.get("name", "")).strip()
    if not name:
        raise ValueError("缺少参数集名称。")
    config_path = context.resolve_path(config_path_raw, must_exist=True)
    config = context.read_runtime_config(config_path)
    scope = normalize_preset_scope(payload.get("scope", "workspace"))
    if scope == "all":
        scope = "workspace"
    calibration_profile = context.resolve_profile(config, str(payload.get("calibration_profile", "")).strip().lower() or None)
    raw_params = dict(payload.get("params", {}))
    params = context.sanitize_param_values(raw_params)
    params_adjusted = False
    objective_mode = profile_runner.resolve_objective_mode(config, payload.get("objective_mode", None), calibration_profile)
    param_bounds_profile = profile_runner.resolve_param_bounds_profile(
        config,
        payload.get("param_bounds_profile", None),
        calibration_profile,
    )
    runtime_prec_source = profile_runner.resolve_runtime_precip_source(config, payload.get("prec_source", None))
    glacier_mode = str(payload.get("glacier_mode", "inline")).strip().lower() or "inline"
    try:
        cli_args = context.build_forward_runtime_cli_args(
            config_path,
            calibration_profile,
            prec_source=runtime_prec_source,
            glacier_mode=glacier_mode,
            objective_mode=objective_mode,
        )
        module = profile_runner.load_legacy_module(profile_runner.old_script_path(config, "model", "calibrate_hbv_cryo.py"))
        profile_runner.patch_runtime_environment(module, config, calibration_profile, cli_args)
        profile_runner.patch_profile_behavior(module, config, calibration_profile, objective_mode, param_bounds_profile)
        configure_time_step = getattr(module, "configure_time_step", None)
        if callable(configure_time_step):
            configure_time_step()
        _, params, params_adjusted = context.build_runtime_param_vector(module, raw_params)
    except Exception:
        params_adjusted = False
    now = time.time()
    data = load_manual_preset_store(config_path_raw, context, scope)
    presets = list(data.get("presets", []))
    source_run_path, source_run_name = _normalize_manual_preset_source_run(payload.get("run_path", ""), "", context)
    if context.source_run_metadata_for_preset is not None:
        source_metadata, source_run_dir, source_resolved_config = context.source_run_metadata_for_preset(payload.get("run_path", ""))
    else:
        source_metadata, source_run_dir, source_resolved_config = _source_run_metadata_for_preset(payload.get("run_path", ""), context)
    existing = next(
        (
            item for item in presets
            if str(item.get("name", "")).strip() == name
            and str(item.get("calibration_profile", "")).strip().lower() == calibration_profile
            and str(item.get("scope", scope)).strip().lower() == scope
        ),
        None,
    )
    if existing is None:
        existing = {"id": uuid.uuid4().hex[:10], "created_at": now}
        presets.append(existing)
    created_at = float(existing.get("created_at", now) or now)
    parameter_set_id = str(existing.get("parameter_set_id") or existing.get("id") or uuid.uuid4().hex[:10]).strip()
    existing["id"] = str(existing.get("id") or parameter_set_id)
    source_run_type = ""
    source_run_type_label = ""
    if source_metadata:
        try:
            source_studio_compatible = context.is_studio_editable_metadata(source_metadata, source_resolved_config)
        except Exception:
            source_studio_compatible = False
        source_run_type = context.run_kind_from_metadata(source_metadata, source_studio_compatible)
        source_run_type_label = context.run_kind_label(source_run_type)
    meteo_cfg = dict(config.get(context.meteo_key, {}) or {})
    source_workspace = (
        context.workspace_name_for_summary(source_metadata, source_resolved_config)
        if source_metadata
        else str(config.get("流域名称", "") or Path(config_path).stem)
    )
    if not source_workspace:
        source_workspace = str(config.get("流域名称", "") or Path(config_path).stem)
    source_workspace_config_raw = source_metadata.get("workspace_config") if source_metadata else ""
    source_workspace_config = str(source_workspace_config_raw or config_path.resolve(strict=False))
    source_run_id = str(source_metadata.get("run_id") or (source_run_dir.name if source_run_dir is not None else source_run_name) or "").strip()
    glacier_enabled = dict(dict(source_metadata.get("optional_modules", {}) or {}).get("glacier", {}) or {}).get("enabled")
    if glacier_enabled is None:
        glacier_enabled = glacier_mode != "off"
    existing.update(
        {
            "parameter_set_id": parameter_set_id,
            "name": name,
            "scope": scope,
            "params": params,
            "parameters": params,
            "calibration_profile": calibration_profile,
            "params_adjusted": bool(params_adjusted),
            "objective_mode": objective_mode,
            "param_bounds_profile": param_bounds_profile,
            "param_bounds_profile_label": profile_runner.PARAM_BOUNDS_PROFILE_LABELS.get(
                param_bounds_profile,
                param_bounds_profile,
            ),
            "prec_source": runtime_prec_source,
            "glacier_mode": glacier_mode,
            "created_at": created_at,
            "created_at_text": _format_epoch_text(created_at),
            "updated_at": now,
            "updated_at_text": _format_epoch_text(now),
            "source_run_path": source_run_path,
            "source_run_name": source_run_name,
            "source_workspace": source_workspace,
            "source_workspace_config": source_workspace_config,
            "source_run_id": source_run_id,
            "source_run_type": source_run_type,
            "source_run_type_label": source_run_type_label,
            "time_step": context.profile_labels.get(calibration_profile, calibration_profile),
            "time_step_hours": context.normalize_time_step_hours(config.get("时间步长_小时", 24.0)),
            "meteo_source": runtime_prec_source,
            "precipitation_strategy": str(meteo_cfg.get(context.meteo_precip_mode_key, "grid_only")),
            "glacier_enabled": bool(glacier_enabled),
            "period_summary": _parameter_period_summary(config, source_metadata, context),
            "metrics": _parameter_metric_summary(source_metadata),
            "notes": str(payload.get("notes", "")).strip(),
            "context": {
                "workspace_name": str(config.get("流域名称", "") or Path(config_path).stem),
                "workspace_config": str(config_path.resolve(strict=False)),
                "time_step_hours": context.normalize_time_step_hours(config.get("时间步长_小时", 24.0)),
                "task_time_basis": context.task_time_basis(config, context="calibration"),
                "precipitation_mode": str(dict(config.get(context.meteo_key, {}) or {}).get(context.meteo_precip_mode_key, "grid_only")),
            },
        }
    )
    data["presets"] = presets
    store_path = write_manual_preset_store(config_path_raw, data, context, scope)
    return {"saved": True, "preset": existing, "store_path": str(store_path)}


def find_manual_preset(config_path_raw: str, preset_id: str, context: ManualPresetContext) -> dict[str, Any]:
    for scope in ("workspace", "global"):
        data = load_manual_preset_store(config_path_raw, context, scope)
        for item in data.get("presets", []):
            if str(item.get("id", "")).strip() == preset_id or str(item.get("parameter_set_id", "")).strip() == preset_id:
                item = dict(item)
                item["scope"] = str(item.get("scope", scope) or scope)
                return item
    raise FileNotFoundError(f"未找到参数集：{preset_id}")


def delete_manual_preset(payload: dict[str, Any], context: ManualPresetContext) -> dict[str, Any]:
    config_path_raw = str(payload.get("config_path", "")).strip()
    preset_id = str(payload.get("preset_id", "")).strip()
    if not config_path_raw or not preset_id:
        raise ValueError("缺少 config_path 或 preset_id。")
    scope = normalize_preset_scope(payload.get("scope", "workspace"))
    if scope == "all":
        existing = find_manual_preset(config_path_raw, preset_id, context)
        scope = normalize_preset_scope(existing.get("scope", "workspace"))
    data = load_manual_preset_store(config_path_raw, context, scope)
    presets = [item for item in data.get("presets", []) if str(item.get("id", "")).strip() != preset_id]
    data["presets"] = presets
    store_path = write_manual_preset_store(config_path_raw, data, context, scope)
    return {"deleted": True, "preset_id": preset_id, "store_path": str(store_path)}
