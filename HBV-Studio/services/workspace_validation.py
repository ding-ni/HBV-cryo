#!/usr/bin/env python
# -*- coding: utf-8 -*-
from __future__ import annotations

import copy
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

import pandas as pd


@dataclass(frozen=True)
class WorkspaceValidationContext:
    resolve_path: Callable[..., Path]
    read_config: Callable[[Path], dict[str, Any]]
    find_running_task: Callable[[str, str], Any]
    current_profile: Callable[[dict[str, Any]], str]
    detect_object_type: Callable[[dict[str, Any]], str]
    build_profile_paths: Callable[[dict[str, Any], str], dict[str, Any]]
    normalize_time_step_hours: Callable[[Any], float]
    task_time_basis: Callable[..., str]
    normalized_flood_events: Callable[..., dict[str, Any]]
    workspace_dem_path: Callable[..., Path]
    configured_dem_kind: Callable[[dict[str, Any]], str | None]
    resolve_config_related_path: Callable[[dict[str, Any], Any], Path | None]
    time_sequence_messages: Callable[[dict[str, pd.Timestamp], float], list[str]]
    inspect_observed_csv: Callable[..., dict[str, Any]]
    build_expected_observation_index: Callable[..., pd.DatetimeIndex | None]
    observed_window_messages: Callable[..., tuple[list[str], list[str]]]
    event_observation_coverage_summary: Callable[..., dict[str, Any]]
    event_observation_coverage_messages: Callable[..., tuple[list[str], list[str]]]
    format_timestamp_for_display: Callable[[pd.Timestamp, float], str]
    inspect_boundary_csv: Callable[..., dict[str, Any]]
    build_expected_forcing_index: Callable[..., pd.DatetimeIndex | None]
    boundary_info_messages: Callable[..., tuple[list[str], list[str]]]
    resolve_precip_source: Callable[..., str]
    analyze_station_precip_inputs: Callable[..., dict[str, Any]]
    validate_forcing_bundle: Callable[..., dict[str, Any]]
    glacier_formal_requirements: Callable[..., dict[str, Any]]
    input_time_basis_ui_summary: Callable[..., dict[str, Any]]
    event_windows_ui_summary: Callable[..., dict[str, Any]]
    default_init_state: dict[str, Any]
    observed_flow_key: str
    profile_daily: str
    profile_hourly: str
    profile_labels: dict[str, str]
    default_min_daily_hours: int
    object_interbasin: str
    object_full_upstream: str
    object_labels: dict[str, str]
    time_basis_event_windows: str
    time_basis_labels: dict[str, str]
    meteo_key: str
    meteo_precip_mode_key: str
    meteo_pet_source_key: str


def _config_text_value(config: dict[str, Any], key: str) -> str:
    if not isinstance(config, dict):
        return ""
    value = config[key] if key in config else ""
    if value is None:
        return ""
    return str(value).strip()


def _append_unique_message(items: list[str], text: str) -> None:
    if text and text not in items:
        items.append(text)


def build_engineering_focus_checks(
    config: dict[str, Any],
    context: WorkspaceValidationContext,
    *,
    profile: str,
    object_type: str,
    step_hours: float,
    obs_info: dict[str, Any] | None = None,
    boundary_info: dict[str, Any] | None = None,
    forcing: dict[str, Any] | None = None,
    station_precip_info: dict[str, Any] | None = None,
    boundary_csv: str = "",
) -> list[dict[str, Any]]:
    checks: list[dict[str, Any]] = []

    if profile == context.profile_daily:
        observed_profile = (
            obs_info.get("effective_calibration_mode")
            or obs_info.get("suggested_calibration_mode")
            if obs_info else None
        )
        resampled_to_daily = bool(obs_info.get("resampled_to_daily")) if obs_info else False
        forcing_ok = bool(forcing.get("ok")) if forcing is not None else None
        expected_steps = int(forcing.get("expected_steps") or 0) if forcing is not None and forcing.get("expected_steps") is not None else None
        time_basis_label = str(forcing.get("time_basis_label", "连续时段") if forcing else "连续时段")
        if step_hours != 24.0:
            status = "fail"
            summary = "当前设置为日尺度，但项目时间步长不是 24 小时。"
        elif observed_profile and observed_profile != context.profile_daily:
            status = "fail"
            summary = "观测径流识别为小时尺度，和当前日尺度项目不一致。"
        elif resampled_to_daily:
            status = "ok"
            summary = "观测径流原始时步为小时尺度，已按水文日（08:00 至次日 08:00）聚合为日平均流量后用于日尺度项目。"
        elif forcing is not None and not forcing_ok:
            status = "warn"
            summary = f"日尺度主流程已选定，但气象驱动在{time_basis_label}内的覆盖或文件命名仍有问题。"
        else:
            status = "ok"
            summary = f"日尺度主流程基本合理，重点继续检查{time_basis_label}和气象驱动完整性。"
        items = [
            {"label": "项目时间步长", "value": f"{int(step_hours)} 小时", "status": "ok" if step_hours == 24.0 else "fail"},
            {
                "label": "观测径流识别模式",
                "value": context.profile_labels.get(observed_profile, "尚未识别") if observed_profile else "尚未识别",
                "status": "ok" if observed_profile in {None, context.profile_daily} else "fail",
            },
        ]
        if resampled_to_daily:
            aggregation = dict(obs_info.get("daily_aggregation") or {})
            start_hour = int(aggregation.get("day_start_hour", 8) or 8)
            items.append(
                {
                    "label": "小时观测转日尺度",
                    "value": (
                        f"已按水文日 {start_hour:02d}:00 聚合（日均；至少 {aggregation.get('min_hours_per_day', context.default_min_daily_hours)} 小时/天）"
                    ),
                    "status": "ok",
                }
            )
        if expected_steps is not None:
            items.append(
                {
                    "label": "期望时间步数",
                    "value": str(expected_steps),
                    "status": "ok" if forcing_ok is not False else "warn",
                }
            )
        if forcing is not None:
            items.append(
                {
                    "label": "气象驱动状态",
                    "value": f"已覆盖{time_basis_label}" if forcing_ok else "仍有覆盖或命名问题",
                    "status": "ok" if forcing_ok else "warn",
                }
            )
            items.append({"label": "资料口径", "value": time_basis_label, "status": "ok"})
            event_windows = dict(forcing.get("event_windows") or {})
            if event_windows:
                items.append(
                    {
                        "label": "洪水事件",
                        "value": f"{int(event_windows.get('valid_event_count', 0) or 0)}/{int(event_windows.get('event_count', 0) or 0)} 场有效",
                        "status": "ok" if int(event_windows.get("valid_event_count", 0) or 0) > 0 else "fail",
                    }
                )
        checks.append(
            {
                "id": "daily_profile",
                "title": "日尺度专项检查",
                "summary": summary,
                "status": status,
                "target_step": 2 if any(item["status"] == "fail" for item in items[:2]) else 6,
                "items": items,
            }
        )

    if object_type == context.object_interbasin or boundary_csv:
        if object_type != context.object_interbasin and boundary_csv:
            checks.append(
                {
                    "id": "boundary_inflow",
                    "title": "上游边界入流专项检查",
                    "summary": "当前项目不是区间流域，但配置了上游边界入流，请确认对象类型是否正确。",
                    "status": "warn",
                    "target_step": 3,
                    "items": [
                        {"label": "项目对象", "value": context.object_labels.get(object_type, object_type), "status": "warn"},
                        {"label": "边界入流文件", "value": "已配置" if boundary_csv else "未配置", "status": "warn" if boundary_csv else "ok"},
                    ],
                }
            )
        elif not boundary_csv:
            checks.append(
                {
                    "id": "boundary_inflow",
                    "title": "上游边界入流专项检查",
                    "summary": "区间流域必须提供上游边界入流文件。",
                    "status": "fail",
                    "target_step": 3,
                    "items": [
                        {"label": "边界入流文件", "value": "缺失", "status": "fail"},
                    ],
                }
            )
        elif boundary_info is not None:
            coverage_ratio = boundary_info.get("coverage_ratio")
            duplicate_count = int(boundary_info.get("duplicate_count", 0) or 0)
            negative_count = int(boundary_info.get("negative_count", 0) or 0)
            out_of_range_count = len(boundary_info.get("out_of_range_steps", []) or [])
            zero_ratio = int(boundary_info.get("zero_count", 0) or 0) / max(1, int(boundary_info.get("valid_rows", 0) or 0))
            detected_step = context.normalize_time_step_hours(boundary_info.get("time_step_hours"))
            step_match = detected_step == step_hours if boundary_info.get("time_step_hours") is not None else None
            if duplicate_count > 0 or negative_count > 0 or step_match is False or (coverage_ratio is not None and coverage_ratio < 0.99):
                status = "fail"
                summary = "边界入流仍有关键问题，正式率定前需要先修正时间步长、覆盖率或异常值。"
            elif zero_ratio >= 0.8 or int(boundary_info.get("invalid_rows", 0) or 0) > 0 or out_of_range_count > 0:
                status = "warn"
                summary = "边界入流可以继续核查，但仍有高零值比例或范围外记录等风险。"
            else:
                status = "ok"
                summary = "边界入流时间步和覆盖范围基本合理，可进入后续调试或率定。"
            checks.append(
                {
                    "id": "boundary_inflow",
                    "title": "上游边界入流专项检查",
                    "summary": summary,
                    "status": status,
                    "target_step": 3,
                    "items": [
                        {"label": "识别时间步长", "value": f"{int(detected_step)} 小时" if detected_step is not None else "未识别", "status": "ok" if step_match in {True, None} else "fail"},
                        {
                            "label": "覆盖率",
                            "value": (f"{coverage_ratio * 100:.1f}%" if coverage_ratio is not None else "未与当前时段对比"),
                            "status": "ok" if coverage_ratio is None or coverage_ratio >= 0.99 else "fail",
                        },
                        {
                            "label": "重复时间戳",
                            "value": str(duplicate_count),
                            "status": "ok" if duplicate_count == 0 else "fail",
                        },
                        {
                            "label": "负流量记录",
                            "value": str(negative_count),
                            "status": "ok" if negative_count == 0 else "fail",
                        },
                        {
                            "label": "零值比例",
                            "value": f"{zero_ratio * 100:.1f}%",
                            "status": "warn" if zero_ratio >= 0.8 else "ok",
                        },
                    ],
                }
            )
    if station_precip_info and station_precip_info.get("enabled"):
        event_coverage = list(station_precip_info.get("event_coverage", []) or [])
        event_ok_count = sum(1 for item in event_coverage if str(item.get("status", "") or "") == "ok")
        checks.append(
            {
                "id": "station_precip",
                "title": "站点降水专项检查",
                "summary": str(station_precip_info.get("summary", "")),
                "status": str(station_precip_info.get("status", "warn") or "warn"),
                "target_step": 4,
                "items": list(station_precip_info.get("items", []) or []),
                "task_context": dict(station_precip_info.get("task_context", {}) or {}),
                "event_coverage": event_coverage,
                "event_coverage_summary": {
                    "enabled": bool(event_coverage),
                    "ok_count": int(event_ok_count),
                    "event_count": int(len(event_coverage)),
                },
            }
        )
    return checks


def validate_workspace_fields(
    config_path_raw: str,
    context: WorkspaceValidationContext,
    *,
    stage: str = "calibration",
    precip_source: Any = None,
    config_override: dict[str, Any] | None = None,
) -> dict[str, Any]:
    missing: list[str] = []
    warnings: list[str] = []
    try:
        cfg_path = context.resolve_path(config_path_raw, must_exist=True)
        config = copy.deepcopy(config_override) if config_override is not None else context.read_config(cfg_path)
    except Exception as exc:
        return {"valid": False, "missing": [f"配置文件无法读取：{exc}"], "warnings": []}

    active_meteo_import = context.find_running_task("meteo_import", str(cfg_path))
    if active_meteo_import is not None:
        progress = dict(active_meteo_import.metadata.get("ui_progress") or {})
        stage_label = str(progress.get("stage", "气象栅格导入任务")).strip() or "气象栅格导入任务"
        warnings.append(f"{stage_label}仍在进行，检查结果会随导入进度变化。")
        if stage in {"calibration", "forward"}:
            missing.append("气象栅格导入任务仍在运行，请等待完成后再进行输入检查或启动率定。")
            return {
                "valid": False,
                "missing": missing,
                "warnings": warnings,
                "profile": context.current_profile(config),
                "object_type": context.detect_object_type(config),
                "stage": stage,
            }

    profile = context.current_profile(config)
    object_type = context.detect_object_type(config)
    paths = context.build_profile_paths(config, profile)
    step_hours = context.normalize_time_step_hours(config.get("时间步长_小时", 24.0))
    time_basis = context.task_time_basis(config, context="calibration")
    event_window_info = (
        context.normalized_flood_events(config, step_hours=step_hours)
        if time_basis == context.time_basis_event_windows
        else None
    )
    runtime_stage = str(stage or "calibration").strip().lower() or "calibration"
    require_observed_flow = runtime_stage != "quick_test"
    obs_info: dict[str, Any] | None = None
    event_observation_coverage: dict[str, Any] | None = None
    boundary_info: dict[str, Any] | None = None
    forcing: dict[str, Any] | None = None
    station_precip_info: dict[str, Any] | None = None
    for repair_key, label in (("流域边界_shp", "流域边界"), ("冰川边界_shp", "冰川边界"), (context.observed_flow_key, "观测径流")):
        repair_info = dict(config.get("_path_repairs", {})).get(repair_key)
        if isinstance(repair_info, dict) and repair_info.get("recovered_from"):
            warnings.append(
                f"{label}已自动恢复到当前工作区：{repair_info.get('resolved_path', '')}（来源 {repair_info.get('recovered_from', '')}）"
            )
    if not config.get("运行目录"):
        missing.append("运行目录")
    basin_path_raw = str(config.get("流域边界_shp", "")).strip()
    basin_path = context.resolve_config_related_path(config, basin_path_raw)
    runtime_gis_ready = all(
        file_path.exists()
        for file_path in (
            context.workspace_dem_path(paths["gis_dir"], prefer=context.configured_dem_kind(config)),
            Path(paths["gis_dir"]) / "flow_accumulation_masked.tif",
        )
    )
    if runtime_stage == "calibration":
        if not basin_path_raw:
            if runtime_gis_ready:
                warnings.append("原始流域边界 shp 未配置，但当前工作区已具备运行时 GIS 数据，可继续率定。")
            else:
                missing.append("流域边界_shp")
        elif basin_path is None or not basin_path.exists():
            if runtime_gis_ready:
                warnings.append(f"原始流域边界文件不存在：{basin_path_raw}；当前工作区已具备运行时 GIS 数据，可继续率定。")
            else:
                missing.append(f"流域边界文件不存在：{basin_path_raw}")
    obs_path = _config_text_value(config, context.observed_flow_key)
    obs_file = context.resolve_config_related_path(config, obs_path)
    if require_observed_flow:
        if not obs_path:
            _append_unique_message(missing, context.observed_flow_key)
        elif obs_file is None or not obs_file.exists():
            _append_unique_message(missing, f"观测径流文件不存在：{obs_path}")
    elif not obs_path:
        warnings.append("输入预核算未配置观测径流文件；本次只检查运行资料可用性，不计算观测指标。")
    elif obs_file is None or not obs_file.exists():
        warnings.append(f"输入预核算未找到观测径流文件：{obs_path}；本次只检查运行资料可用性，不计算观测指标。")
    if profile == context.profile_daily and step_hours != 24.0:
        missing.append("率定模式=日尺度 但 时间步长_小时 不是 24")
    if profile == context.profile_hourly and step_hours != 1.0:
        missing.append("率定模式=小时尺度 但 时间步长_小时 不是 1")

    time_cfg = config.get("时间", {})
    if time_basis == context.time_basis_event_windows:
        warnings.append("当前工作区采用洪水事件资料口径，输入检查按每场洪水时段核验。")
    else:
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
    if event_window_info is not None:
        for item in list(event_window_info.get("errors", []) or []):
            missing.append(str(item))
        for item in list(event_window_info.get("warnings", []) or []):
            warnings.append(str(item))
        if not event_window_info.get("valid_event_count"):
            missing.append("事件资料模式已启用，但没有可用的洪水事件窗口。")
        else:
            counts = dict(event_window_info.get("purpose_counts", {}) or {})
            warnings.append(
                "当前按洪水事件窗口检查资料："
                f"{int(event_window_info.get('valid_event_count', 0) or 0)} 场有效，"
                f"率定 {int(counts.get('calibration', 0) or 0)}、"
                f"验证 {int(counts.get('validation', 0) or 0)}、"
                f"诊断 {int(counts.get('diagnostic', 0) or 0)}。"
            )

    init_state = dict(config.get("初始状态", {}) or {})
    for key, default_value in context.default_init_state.items():
        raw_value = init_state.get(key, default_value)
        try:
            value = float(raw_value)
        except Exception:
            missing.append(f"初始状态.{key} 不是有效数字：{raw_value}")
            continue
        if value < 0:
            missing.append(f"初始状态.{key} 不能为负值：{raw_value}")

    bbox = config.get("范围_bbox", {})
    if not all(bbox.get(dim) is not None for dim in ("北", "西", "南", "东")):
        warnings.append("范围_bbox 未完整填写，保存时可由 shp 自动生成。")

    if obs_path and obs_file is not None and obs_file.exists():
        try:
            obs_info = context.inspect_observed_csv(
                str(obs_file),
                expected_index=context.build_expected_observation_index(config, context="calibration"),
                target_step_hours=step_hours,
                return_series=time_basis == context.time_basis_event_windows,
            )
            observed_series = obs_info.pop("series", None)
            obs_missing, obs_warnings = context.observed_window_messages(config, obs_info)
            if require_observed_flow:
                missing.extend(obs_missing)
            else:
                warnings.extend(obs_missing)
            warnings.extend(obs_warnings)
            if event_window_info is not None:
                event_observation_coverage = context.event_observation_coverage_summary(
                    event_window_info,
                    observed_series,
                    step_hours,
                )
                event_obs_missing, event_obs_warnings = context.event_observation_coverage_messages(event_observation_coverage)
                if require_observed_flow:
                    missing.extend(event_obs_missing)
                else:
                    warnings.extend(event_obs_missing)
                warnings.extend(event_obs_warnings)
            duplicate_count = int(obs_info.get("duplicate_count", 0) or 0)
            if duplicate_count > 0:
                sample = "、".join(
                    context.format_timestamp_for_display(item, step_hours)
                    for item in list(obs_info.get("duplicate_timestamps", []))[:3]
                )
                warnings.append(
                    f"观测径流存在 {duplicate_count} 个重复时间戳，运行时会按同一时刻求平均，例如：{sample or '请检查原始 CSV'}"
                )
        except Exception as exc:
            missing.append(f"观测径流检查失败：{exc}")

    boundary_cfg = dict(config.get("边界条件", {}))
    boundary_csv = str(boundary_cfg.get("上游边界入流_csv", "")).strip()
    boundary_file = context.resolve_config_related_path(config, boundary_csv)
    boundary_date_field = str(boundary_cfg.get("时间字段", "date")).strip() or "date"
    boundary_flow_field = str(boundary_cfg.get("流量字段", "inflow_m3s")).strip() or "inflow_m3s"
    if runtime_stage in {"calibration", "forward"} and object_type == context.object_interbasin:
        if not boundary_csv:
            missing.append("项目对象=区间流域时必须提供 上游边界入流_csv。")
        elif boundary_file is None or not boundary_file.exists():
            missing.append(f"上游边界入流文件不存在：{boundary_csv}")
        else:
            try:
                boundary_info = context.inspect_boundary_csv(
                    str(boundary_file),
                    date_field=boundary_date_field,
                    flow_field=boundary_flow_field,
                    expected_index=context.build_expected_forcing_index(config, context="calibration"),
                    expected_step_hours=step_hours,
                )
                boundary_missing, boundary_warnings = context.boundary_info_messages(
                    boundary_info,
                    step_hours,
                    gap_fill=str(boundary_cfg.get("缺失填补", "zero")),
                )
                missing.extend(boundary_missing)
                warnings.extend(boundary_warnings)
            except Exception as exc:
                missing.append(f"上游边界入流检查失败：{exc}")
    elif runtime_stage == "calibration" and object_type == context.object_full_upstream and boundary_csv:
        warnings.append("完整上游流域通常不需要上游边界入流；如确需使用，请确认对象类型是否正确。")

    meteo = dict(config.get(context.meteo_key, {}))
    precip_mode = str(meteo.get(context.meteo_precip_mode_key, "grid_only")).strip()
    precip_source_ui = context.resolve_precip_source(config, precip_source)
    if runtime_stage == "calibration" and precip_mode in {"grid_plus_station_bias", "thiessen_station_only"}:
        station_precip_info = context.analyze_station_precip_inputs(config, step_hours=step_hours)
        for item in list(station_precip_info.get("missing", []) or []):
            if item not in missing:
                missing.append(str(item))
        for item in list(station_precip_info.get("warnings", []) or []):
            if item not in warnings:
                warnings.append(str(item))
    if precip_mode == "thiessen_station_only":
        warnings.append("纯泰森方案建议只作为快速基线，不建议直接作为最终方案。")
    if precip_source_ui == "custom_tif":
        warnings.append("降水来源为“本地栅格目录”时，请在第 6 步使用“验证并导入”；系统会写入工程独立降水目录，运行时直接读取。")
    pet_source = str(meteo.get(context.meteo_pet_source_key, "era5_fao56")).strip().lower()
    if runtime_stage == "calibration" and pet_source == "era5_direct":
        missing.append("潜在蒸散发来源“era5_direct”尚未接通，请改用 era5_fao56 或“本地栅格目录”。")

    if runtime_stage in {"calibration", "forward"}:
        for file_path in (
            context.workspace_dem_path(paths["gis_dir"], prefer=context.configured_dem_kind(config)),
            Path(paths["gis_dir"]) / "flow_accumulation_masked.tif",
        ):
            if not file_path.exists():
                missing.append(f"缺少输入文件：{file_path}")

        forcing = context.validate_forcing_bundle(config, profile, precip_source=precip_source_ui)
        missing.extend(forcing["errors"])
        warnings.extend(forcing["warnings"])

    glacier_requirements = context.glacier_formal_requirements(config, profile)
    if glacier_requirements["enabled"]:
        for note in glacier_requirements.get("diagnostic_notes", []):
            warnings.append(note)

    if require_observed_flow:
        obs_path = _config_text_value(config, context.observed_flow_key)
        if not obs_path:
            _append_unique_message(missing, context.observed_flow_key)
        elif obs_file is None or not obs_file.exists():
            _append_unique_message(missing, f"观测径流文件不存在：{obs_path}")

    focus_checks = build_engineering_focus_checks(
        config,
        context,
        profile=profile,
        object_type=object_type,
        step_hours=step_hours,
        obs_info=obs_info,
        boundary_info=boundary_info,
        forcing=forcing,
        station_precip_info=station_precip_info,
        boundary_csv=boundary_csv,
    )

    return {
        "valid": len(missing) == 0,
        "missing": missing,
        "warnings": warnings,
        "profile": profile,
        "object_type": object_type,
        "stage": stage,
        "focus_checks": focus_checks,
        "input_time_summary": context.input_time_basis_ui_summary(
            config,
            time_basis=time_basis,
            step_hours=step_hours,
            event_info=event_window_info,
            context="calibration",
        ),
        "time_basis": time_basis,
        "time_basis_label": context.time_basis_labels.get(time_basis, "当前任务时段"),
        "event_windows": context.event_windows_ui_summary(event_window_info, step_hours) if event_window_info is not None else None,
        "event_forcing_coverage": dict(forcing.get("event_forcing_coverage") or {}) if forcing else None,
        "event_observation_coverage": event_observation_coverage,
    }
