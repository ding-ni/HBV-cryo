#!/usr/bin/env python
# -*- coding: utf-8 -*-
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

import pandas as pd


@dataclass(frozen=True)
class WizardValidationContext:
    resolve_path: Callable[..., Path]
    read_config: Callable[[Path], dict[str, Any]]
    resolve_precip_source: Callable[..., Any]
    detect_object_type: Callable[[dict[str, Any]], str]
    resolve_config_related_path: Callable[[dict[str, Any], Any], Path | None]
    normalize_time_step_hours: Callable[[Any], float]
    task_time_basis: Callable[..., str]
    normalized_flood_events: Callable[..., dict[str, Any]]
    event_windows_ui_summary: Callable[..., dict[str, Any]]
    time_sequence_messages: Callable[[dict[str, pd.Timestamp], float], list[str]]
    inspect_observed_csv: Callable[..., dict[str, Any]]
    build_expected_observation_index: Callable[..., pd.DatetimeIndex | None]
    observed_window_messages: Callable[..., tuple[list[str], list[str]]]
    event_observation_coverage_summary: Callable[..., dict[str, Any]]
    event_observation_coverage_messages: Callable[..., tuple[list[str], list[str]]]
    inspect_boundary_csv: Callable[..., dict[str, Any]]
    build_expected_boundary_index: Callable[..., pd.DatetimeIndex | None]
    build_expected_forcing_index: Callable[..., pd.DatetimeIndex | None]
    boundary_info_messages: Callable[..., tuple[list[str], list[str]]]
    configured_precip_source: Callable[[dict[str, Any]], str]
    check_clip_dem: Callable[[dict[str, Any]], tuple[bool, str, Any]]
    check_flow_acc: Callable[[dict[str, Any]], tuple[bool, str, Any]]
    check_masked_flow: Callable[[dict[str, Any]], tuple[bool, str, Any]]
    check_elevation_zone: Callable[[dict[str, Any]], tuple[bool, str, Any]]
    find_running_task: Callable[[str, str], Any]
    validate_forcing_bundle: Callable[..., dict[str, Any]]
    current_profile: Callable[[dict[str, Any]], str]
    read_meteo_state: Callable[[dict[str, Any], str | None], dict[str, Any]]
    validate_workspace_fields: Callable[..., dict[str, Any]]
    observed_flow_key: str
    object_interbasin: str
    time_basis_event_windows: str
    meteo_key: str
    meteo_precip_mode_key: str
    meteo_temp_source_key: str
    meteo_pet_source_key: str
    meteo_station_prec_key: str
    meteo_station_meta_key: str
    meteo_custom_prec_dir_key: str
    meteo_custom_temp_dir_key: str
    meteo_custom_pet_dir_key: str


def wizard_step4_meteo_validation(
    config: dict[str, Any],
    context: WizardValidationContext,
) -> tuple[list[str], list[str]]:
    missing: list[str] = []
    warnings: list[str] = []
    meteo = dict(config.get(context.meteo_key, {}))
    precip_mode = str(meteo.get(context.meteo_precip_mode_key, "grid_only")).strip()
    precip_source = context.configured_precip_source(config)
    temp_source = str(meteo.get(context.meteo_temp_source_key, "era5")).strip().lower()
    pet_source = str(meteo.get(context.meteo_pet_source_key, "era5_fao56")).strip().lower()
    station_prec_path = context.resolve_config_related_path(config, meteo.get(context.meteo_station_prec_key))
    station_meta_path = context.resolve_config_related_path(config, meteo.get(context.meteo_station_meta_key))
    custom_prec_path = context.resolve_config_related_path(config, meteo.get(context.meteo_custom_prec_dir_key))
    custom_temp_path = context.resolve_config_related_path(config, meteo.get(context.meteo_custom_temp_dir_key))
    custom_pet_path = context.resolve_config_related_path(config, meteo.get(context.meteo_custom_pet_dir_key))
    if precip_mode in {"grid_plus_station_bias", "thiessen_station_only"}:
        if not meteo.get(context.meteo_station_prec_key):
            missing.append("站点降水 csv")
        elif station_prec_path is None or not station_prec_path.exists():
            missing.append(f"站点降水 csv 文件不存在：{meteo.get(context.meteo_station_prec_key)}")
        if not meteo.get(context.meteo_station_meta_key):
            missing.append("站点信息 csv")
        elif station_meta_path is None or not station_meta_path.exists():
            missing.append(f"站点信息 csv 文件不存在：{meteo.get(context.meteo_station_meta_key)}")
    if precip_source == "custom_tif":
        custom_prec_dir = str(meteo.get(context.meteo_custom_prec_dir_key, "")).strip()
        if not custom_prec_dir:
            missing.append("本地降水栅格目录")
        elif custom_prec_path is None or not custom_prec_path.exists():
            missing.append(f"本地降水栅格目录不存在：{custom_prec_dir}")
    if temp_source == "custom_tif":
        custom_temp_dir = str(meteo.get(context.meteo_custom_temp_dir_key, "")).strip()
        if not custom_temp_dir:
            missing.append("本地气温栅格目录")
        elif custom_temp_path is None or not custom_temp_path.exists():
            missing.append(f"本地气温栅格目录不存在：{custom_temp_dir}")
    if pet_source == "custom_tif":
        custom_pet_dir = str(meteo.get(context.meteo_custom_pet_dir_key, "")).strip()
        if not custom_pet_dir:
            missing.append("本地蒸散发栅格目录")
        elif custom_pet_path is None or not custom_pet_path.exists():
            missing.append(f"本地蒸散发栅格目录不存在：{custom_pet_dir}")
    return missing, warnings


def wizard_validate_step(
    config_path_raw: str,
    step: int,
    context: WizardValidationContext,
    precip_source: Any = None,
) -> dict[str, Any]:
    """Validate only the fields relevant to a single wizard step."""
    missing: list[str] = []
    warnings: list[str] = []
    try:
        cfg_path = context.resolve_path(config_path_raw, must_exist=True)
        config = context.read_config(cfg_path)
    except Exception as exc:
        return {"step": step, "valid": False, "missing": [str(exc)], "warnings": []}
    runtime_prec_source = context.resolve_precip_source(config, precip_source)
    event_windows: dict[str, Any] | None = None
    event_observation_coverage: dict[str, Any] | None = None

    if step == 1:
        if not config.get("流域名称"):
            missing.append("流域名称")
        if not config.get("运行目录"):
            missing.append("运行目录")
    elif step == 2:
        if not config.get("流域边界_shp"):
            missing.append("流域边界 shp")
        else:
            basin_path = context.resolve_config_related_path(config, config.get("流域边界_shp"))
            if basin_path is None or not basin_path.exists():
                missing.append(f"流域边界 shp 文件不存在：{config['流域边界_shp']}")
        if not config.get(context.observed_flow_key):
            missing.append("观测径流文件")
        else:
            obs_file = context.resolve_config_related_path(config, config.get(context.observed_flow_key))
            if obs_file is None or not obs_file.exists():
                missing.append(f"观测径流文件不存在：{config[context.observed_flow_key]}")
        step_hours = context.normalize_time_step_hours(config.get("时间步长_小时", 24.0))
        time_basis = context.task_time_basis(config, context="calibration")
        if time_basis == context.time_basis_event_windows:
            event_info = context.normalized_flood_events(config, step_hours=step_hours)
            event_windows = context.event_windows_ui_summary(event_info, step_hours)
            for item in list(event_info.get("errors", []) or []):
                missing.append(str(item))
            for item in list(event_info.get("warnings", []) or []):
                warnings.append(str(item))
            if not event_info.get("valid_event_count"):
                missing.append("场次洪水窗口模式需要至少一场合法场次洪水。")
            else:
                counts = dict(event_info.get("purpose_counts", {}) or {})
                warnings.append(
                    "当前按场次洪水窗口组织资料："
                    f"{int(event_info.get('valid_event_count', 0) or 0)} 场有效，"
                    f"率定 {int(counts.get('calibration', 0) or 0)}、"
                    f"验证 {int(counts.get('validation', 0) or 0)}、"
                    f"诊断 {int(counts.get('diagnostic', 0) or 0)}。"
                )
        else:
            time_cfg = config.get("时间", {})
            for key in ("预热开始", "率定开始", "率定结束", "验证结束"):
                if not time_cfg.get(key):
                    missing.append(f"时间.{key}")
            time_values: dict[str, pd.Timestamp] = {}
            for key in ("预热开始", "预热结束", "率定开始", "率定结束", "验证开始", "验证结束"):
                value = time_cfg.get(key)
                if not value:
                    continue
                try:
                    time_values[key] = pd.to_datetime(value)
                except Exception:
                    missing.append(f"时间.{key} 无法解析：{value}")
            missing.extend(context.time_sequence_messages(time_values, step_hours))
        obs_path = str(config.get(context.observed_flow_key, "")).strip()
        obs_file = context.resolve_config_related_path(config, obs_path)
        if obs_path and obs_file is not None and obs_file.exists():
            try:
                obs_info = context.inspect_observed_csv(
                    str(obs_file),
                    expected_index=context.build_expected_observation_index(config, context="calibration"),
                    target_step_hours=context.normalize_time_step_hours(config.get("时间步长_小时", 24.0)),
                    return_series=time_basis == context.time_basis_event_windows,
                )
                observed_series = obs_info.pop("series", None)
                obs_missing, obs_warnings = context.observed_window_messages(config, obs_info)
                missing.extend(obs_missing)
                warnings.extend(obs_warnings)
                if time_basis == context.time_basis_event_windows:
                    event_info = context.normalized_flood_events(config, step_hours=step_hours)
                    event_observation_coverage = context.event_observation_coverage_summary(
                        event_info,
                        observed_series,
                        step_hours,
                    )
                    event_obs_missing, event_obs_warnings = context.event_observation_coverage_messages(
                        event_observation_coverage
                    )
                    missing.extend(event_obs_missing)
                    warnings.extend(event_obs_warnings)
            except Exception as exc:
                warnings.append(f"观测径流检查失败：{exc}")
    elif step == 3:
        object_type = context.detect_object_type(config)
        if object_type == context.object_interbasin:
            boundary = dict(config.get("边界条件", {}))
            csv_path = str(boundary.get("上游边界入流_csv", "")).strip()
            if not csv_path:
                missing.append("上游边界入流 csv")
            else:
                boundary_file = context.resolve_config_related_path(config, csv_path)
                if boundary_file is None or not boundary_file.exists():
                    missing.append(f"上游边界入流文件不存在：{csv_path}")
                    boundary_file = None
                if boundary_file is None:
                    return {"step": step, "valid": False, "missing": missing, "warnings": warnings}
                try:
                    step_hours = context.normalize_time_step_hours(config.get("时间步长_小时", 24.0))
                    boundary_info = context.inspect_boundary_csv(
                        str(boundary_file),
                        date_field=str(boundary.get("时间字段", "date")).strip() or "date",
                        flow_field=str(boundary.get("流量字段", "inflow_m3s")).strip() or "inflow_m3s",
                        expected_index=context.build_expected_boundary_index(config, context="calibration"),
                        expected_step_hours=step_hours,
                    )
                    boundary_missing, boundary_warnings = context.boundary_info_messages(
                        boundary_info,
                        step_hours,
                        gap_fill=str(boundary.get("缺失填补", "preserve_missing")),
                    )
                    missing.extend(boundary_missing)
                    warnings.extend(boundary_warnings)
                except Exception as exc:
                    missing.append(f"上游边界入流检查失败：{exc}")
        else:
            boundary_csv = str(dict(config.get("边界条件", {})).get("上游边界入流_csv", "")).strip()
            if boundary_csv:
                warnings.append("当前项目不是区间流域，但配置了上游边界入流；请确认对象类型是否正确。")
    elif step == 4:
        step_missing, step_warnings = wizard_step4_meteo_validation(config, context)
        missing.extend(step_missing)
        warnings.extend(step_warnings)
    elif step == 5:
        gis_checks = [
            ("DEM 裁剪", context.check_clip_dem(config)),
            ("流向与流量累积", context.check_flow_acc(config)),
            ("汇流与流域掩膜", context.check_masked_flow(config)),
            ("高程分区", context.check_elevation_zone(config)),
        ]
        for label, (done, message, _) in gis_checks:
            if not done:
                missing.append(f"{label}未完成：{message}")
    elif step == 6:
        active_meteo_import = context.find_running_task("meteo_import", str(cfg_path))
        if active_meteo_import is not None:
            progress = dict(active_meteo_import.metadata.get("ui_progress") or {})
            stage_label = str(progress.get("stage", "气象栅格导入")).strip() or "气象栅格导入"
            current = int(progress.get("current", 0) or 0)
            total = int(progress.get("total", 0) or 0)
            suffix = f" 当前进度 {current}/{total}。" if total > 0 else "。"
            missing.append(f"{stage_label}仍在进行，请等待完成后再检查第 6 步。{suffix}")
            return {"step": step, "valid": False, "missing": missing, "warnings": warnings}
        forcing = context.validate_forcing_bundle(config, context.current_profile(config), precip_source=runtime_prec_source)
        if runtime_prec_source == "custom_tif" and (not forcing["ok"]) and (
            not context.read_meteo_state(config, context.current_profile(config))
        ):
            warnings.append("当前为本地栅格降水模式；如尚未完成气象栅格导入，请优先使用本步“验证并导入”。")
        missing.extend(forcing["errors"])
        warnings.extend(forcing["warnings"])
    elif step == 7:
        validation = context.validate_workspace_fields(str(cfg_path), stage="calibration", precip_source=runtime_prec_source)
        missing.extend(validation["missing"])
        warnings.extend(validation["warnings"])

    result = {"step": step, "valid": len(missing) == 0, "missing": missing, "warnings": warnings}
    if event_windows is not None:
        result["event_windows"] = event_windows
    if event_observation_coverage is not None:
        result["event_observation_coverage"] = event_observation_coverage
    return result
