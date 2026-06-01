#!/usr/bin/env python
# -*- coding: utf-8 -*-
from __future__ import annotations

import copy
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

import pandas as pd


@dataclass(frozen=True)
class ForecastInputCheckContext:
    resolve_path: Callable[..., Path]
    read_json_file: Callable[[Path], dict[str, Any]]
    read_runtime_config: Callable[[Path], dict[str, Any]]
    build_profile_paths: Callable[[dict[str, Any], str], dict[str, Any]]
    resolve_profile: Callable[[dict[str, Any], str | None], str]
    run_parameter_context: Callable[[Path, dict[str, Any], Path | None], dict[str, Any]]
    profile_labels: dict[str, str]
    objective_label: Callable[[dict[str, Any]], str]
    precip_source_label: Callable[[str], str]
    station_precip_mode_label: Callable[[str], str]
    normalize_time_step_hours: Callable[[Any], float]
    is_date_only_string: Callable[[str], bool]
    validate_tif_time_series: Callable[..., dict[str, Any]]
    format_time_for_check: Callable[[Any, float], str]
    analyze_station_precip_inputs: Callable[..., dict[str, Any]]
    meteo_key: str
    meteo_precip_mode_key: str
    time_basis_forecast_window: str
    time_basis_labels: dict[str, str]


def forecast_source_state_time(source_run: Path, metadata: dict[str, Any]) -> str:
    initial_state = dict(metadata.get("initial_state", {}) or {})
    time_config = dict(metadata.get("time_config", {}) or {})
    state_time = str(
        initial_state.get("state_snapshot_time")
        or time_config.get("forecast_end")
        or time_config.get("valid_end")
        or time_config.get("calib_end")
        or ""
    ).strip()
    if state_time:
        return state_time
    csv_path = source_run / "simulation.csv"
    if csv_path.exists():
        try:
            frame = pd.read_csv(csv_path, usecols=["date"])
            if not frame.empty:
                return str(frame["date"].iloc[-1])
        except Exception:
            pass
    return ""


def forecast_expected_index(
    start_raw: str,
    end_raw: str,
    step_hours: float,
    *,
    normalize_time_step_hours: Callable[[Any], float],
    is_date_only_string: Callable[[str], bool],
) -> pd.DatetimeIndex:
    step = normalize_time_step_hours(step_hours)
    start_ts = pd.to_datetime(start_raw)
    end_ts = pd.to_datetime(end_raw)
    if step < 24.0 and is_date_only_string(end_raw):
        end_ts = end_ts + pd.Timedelta(days=1) - pd.Timedelta(hours=step)
    if end_ts < start_ts:
        return pd.DatetimeIndex([])
    return pd.date_range(start_ts, end_ts, freq=pd.Timedelta(hours=step))


def forecast_input_dir_summary(
    *,
    key: str,
    label: str,
    raw_path: str,
    step_hours: float,
    expected_index: pd.DatetimeIndex | None,
    resolve_path: Callable[..., Path],
    validate_tif_time_series: Callable[..., dict[str, Any]],
    format_time_for_check: Callable[[Any, float], str],
) -> dict[str, Any]:
    raw_text = str(raw_path or "").strip()
    if not raw_text:
        return {
            "key": key,
            "label": label,
            "path": "",
            "status": "fail",
            "summary": f"请选择预报{label}栅格目录。",
            "errors": [f"请选择预报{label}栅格目录。"],
            "warnings": [],
            "total_files": 0,
            "valid_time_steps": 0,
            "expected_steps": int(len(expected_index)) if expected_index is not None else 0,
            "covered_steps": 0,
            "missing_steps": 0,
            "out_of_window_steps": 0,
        }
    try:
        directory = resolve_path(raw_text, must_exist=False)
    except (OSError, ValueError) as exc:
        message = f"预报{label}目录路径无效：{exc}"
        return {
            "key": key,
            "label": label,
            "path": raw_text,
            "status": "fail",
            "summary": message,
            "errors": [message],
            "warnings": [],
            "total_files": 0,
            "valid_time_steps": 0,
            "expected_steps": int(len(expected_index)) if expected_index is not None else 0,
            "covered_steps": 0,
            "missing_steps": int(len(expected_index)) if expected_index is not None else 0,
            "out_of_window_steps": 0,
        }
    check = validate_tif_time_series(label, directory, step_hours, expected_index, "预报窗口")
    expected_steps = int(len(expected_index)) if expected_index is not None else 0
    missing_count = int(len(check.get("missing_steps", []) or []))
    out_count = int(len(check.get("out_of_range_steps", []) or []))
    valid_steps = int(check.get("valid_time_steps", 0) or 0)
    covered_steps = max(0, expected_steps - missing_count) if expected_steps else valid_steps
    errors = [str(item) for item in list(check.get("errors", []) or [])]
    warnings = [str(item) for item in list(check.get("warnings", []) or [])]
    if errors:
        status = "fail"
    elif warnings or expected_steps <= 0:
        status = "warn"
    else:
        status = "ok"
    if expected_steps > 0:
        summary = f"{covered_steps}/{expected_steps} 个预报时步可用"
        if out_count:
            summary += f"，另有 {out_count} 个窗口外文件将不参与本次预报"
    else:
        summary = f"识别到 {valid_steps} 个有效时间步，填写预报时段后可核对覆盖"
    timestamps = list(check.get("timestamps", []) or [])
    return {
        "key": key,
        "label": label,
        "path": str(directory.resolve(strict=False)),
        "status": status,
        "summary": summary,
        "errors": errors,
        "warnings": warnings,
        "total_files": int(check.get("total_files", 0) or 0),
        "valid_time_steps": valid_steps,
        "expected_steps": expected_steps,
        "covered_steps": covered_steps,
        "missing_steps": missing_count,
        "out_of_window_steps": out_count,
        "first_time": format_time_for_check(timestamps[0], step_hours) if timestamps else "",
        "last_time": format_time_for_check(timestamps[-1], step_hours) if timestamps else "",
    }


def forecast_output_preview(
    payload: dict[str, Any],
    source_run: Path,
    *,
    profile_hint: str = "",
    resolve_path: Callable[..., Path],
    read_runtime_config: Callable[[Path], dict[str, Any]],
    build_profile_paths: Callable[[dict[str, Any], str], dict[str, Any]],
    resolve_profile: Callable[[dict[str, Any], str | None], str],
) -> dict[str, Any]:
    source_name = source_run.name or "source_result"
    name_pattern = f"hbv_forecast_{source_name}_运行时间_编号"
    output_dir_raw = str(payload.get("output_dir", "") or "").strip()
    if output_dir_raw:
        output_dir = resolve_path(output_dir_raw, must_exist=False)
        archive_root = output_dir / "forecast_inputs"
        manifest_path = archive_root / "input_manifest.json"
        return {
            "explicit": True,
            "result_parent": str(output_dir.parent.resolve(strict=False)),
            "result_dir": str(output_dir.resolve(strict=False)),
            "result_name_pattern": output_dir.name,
            "result_label": "指定结果目录",
            "result_detail": str(output_dir.resolve(strict=False)),
            "archive_label": "指定目录下的 forecast_inputs",
            "archive_root": str(archive_root.resolve(strict=False)),
            "manifest_path": str(manifest_path.resolve(strict=False)),
            "archive_detail": str(manifest_path.resolve(strict=False)),
        }

    result_parent = source_run.parent
    config_path_raw = str(payload.get("config_path", "") or "").strip()
    if config_path_raw:
        try:
            cfg_path = resolve_path(config_path_raw, must_exist=True)
            config = read_runtime_config(cfg_path)
            requested_profile = str(
                payload.get("profile")
                or payload.get("calibration_mode")
                or profile_hint
                or ""
            ).strip() or None
            active_profile = resolve_profile(config, requested_profile)
            result_parent = Path(build_profile_paths(config, active_profile)["runs_dir"]).resolve(strict=False)
        except Exception:
            result_parent = source_run.parent
    result_detail = str((result_parent / name_pattern).resolve(strict=False))
    return {
        "explicit": False,
        "result_parent": str(result_parent.resolve(strict=False)),
        "result_dir": "",
        "result_name_pattern": name_pattern,
        "result_label": "运行时新建预报结果目录",
        "result_detail": result_detail,
        "archive_label": "结果目录下的 forecast_inputs",
        "archive_root": "",
        "manifest_path": "结果目录/forecast_inputs/input_manifest.json",
        "archive_detail": f"{result_detail}\\forecast_inputs\\input_manifest.json",
    }


def forecast_parameter_check_context(
    payload: dict[str, Any],
    source_run: Path,
    metadata: dict[str, Any],
    *,
    resolve_path: Callable[..., Path],
    run_parameter_context: Callable[[Path, dict[str, Any], Path | None], dict[str, Any]],
) -> dict[str, Any]:
    config_path_raw = str(
        payload.get("config_path")
        or payload.get("config")
        or metadata.get("workspace_config")
        or ""
    ).strip()
    resolved_config: Path | None = None
    if config_path_raw:
        try:
            resolved_config = resolve_path(config_path_raw, must_exist=True)
        except Exception:
            resolved_config = None
    return run_parameter_context(source_run, metadata, resolved_config)


def forecast_parameter_detail_text(
    context: dict[str, Any],
    *,
    profile_labels: dict[str, str],
    objective_label: Callable[[dict[str, Any]], str],
    precip_source_label: Callable[[str], str],
    station_precip_mode_label: Callable[[str], str],
) -> str:
    parts: list[str] = []
    workspace = str(context.get("source_workspace", "") or "").strip()
    profile = str(context.get("calibration_profile", "") or "").strip()
    objective = str(context.get("objective_mode", "") or "").strip()
    prec_source = str(context.get("prec_source", "") or "").strip()
    precipitation = str(context.get("precipitation_strategy", "") or context.get("precipitation_mode", "") or "").strip()
    if workspace:
        parts.append(f"来源工作区：{workspace}")
    if profile:
        parts.append(f"计算尺度：{profile_labels.get(profile, profile)}")
    if objective:
        parts.append(f"率定目标：{objective_label({'effective_objective_mode': objective})}")
    if prec_source:
        parts.append(f"降水驱动：{precip_source_label(prec_source)}")
    if precipitation:
        parts.append(f"降水方案：{station_precip_mode_label(precipitation)}")
    return "；".join(parts)


def forecast_station_precip_check(
    payload: dict[str, Any],
    metadata: dict[str, Any],
    forecast_start: str,
    forecast_end: str,
    step_hours: float,
    *,
    resolve_path: Callable[..., Path],
    read_runtime_config: Callable[[Path], dict[str, Any]],
    analyze_station_precip_inputs: Callable[..., dict[str, Any]],
    meteo_key: str,
    meteo_precip_mode_key: str,
    time_basis_forecast_window: str,
    time_basis_labels: dict[str, str],
) -> dict[str, Any] | None:
    if not forecast_start or not forecast_end:
        return None
    config_path_raw = str(
        payload.get("config_path")
        or payload.get("config")
        or metadata.get("workspace_config")
        or ""
    ).strip()
    if not config_path_raw:
        return None
    try:
        cfg_path = resolve_path(config_path_raw, must_exist=True)
        config = read_runtime_config(cfg_path)
    except Exception:
        return None
    meteo = dict(config.get(meteo_key, {}) or {})
    precip_mode = str(meteo.get(meteo_precip_mode_key, "grid_only") or "grid_only").strip()
    if precip_mode not in {"grid_plus_station_bias", "thiessen_station_only"}:
        return None
    forecast_config = copy.deepcopy(config)
    forecast_config["任务时段模式"] = time_basis_forecast_window
    forecast_config["时间步长_小时"] = step_hours
    time_cfg = dict(forecast_config.get("时间", {}) or {})
    time_cfg.update(
        {
            "预热开始": forecast_start,
            "率定开始": forecast_start,
            "率定结束": forecast_end,
            "验证开始": forecast_start,
            "验证结束": forecast_end,
        }
    )
    forecast_config["时间"] = time_cfg
    try:
        return analyze_station_precip_inputs(
            forecast_config,
            step_hours=step_hours,
            context="forecast",
        )
    except Exception as exc:
        return {
            "enabled": True,
            "mode": precip_mode,
            "status": "warn",
            "summary": f"预报窗口站点降水资料检查失败：{exc}",
            "items": [{"label": "检查状态", "value": str(exc), "status": "warn"}],
            "warnings": [f"预报窗口站点降水资料检查失败：{exc}"],
            "missing": [],
            "matched_station_count": 0,
            "time_basis": time_basis_forecast_window,
            "time_basis_label": time_basis_labels[time_basis_forecast_window],
        }


def forecast_input_check(payload: dict[str, Any], context: ForecastInputCheckContext) -> dict[str, Any]:
    source_run_raw = str(payload.get("source_run", payload.get("run_path", "")) or "").strip()
    if not source_run_raw:
        return {
            "status": "fail",
            "headline": "请先选择预报源结果。",
            "errors": ["请先选择预报源结果。"],
            "warnings": [],
            "items": [],
            "variables": [],
        }
    source_run = context.resolve_path(source_run_raw, must_exist=True)
    metadata = context.read_json_file(source_run / "metadata.json")
    initial_state = dict(metadata.get("initial_state", {}) or {})
    time_config = dict(metadata.get("time_config", {}) or {})
    params = dict(metadata.get("optimized_params", {}) or {})
    parameter_context = forecast_parameter_check_context(
        payload,
        source_run,
        metadata,
        resolve_path=context.resolve_path,
        run_parameter_context=context.run_parameter_context,
    )
    step_hours = context.normalize_time_step_hours(time_config.get("time_step_hours", payload.get("time_step_hours", 24.0)))
    source_state_time = forecast_source_state_time(source_run, metadata)
    errors: list[str] = []
    warnings: list[str] = []
    if not params:
        errors.append("源结果缺少率定参数，不能作为连续状态预报起点。")
    snapshot_file = str(initial_state.get("state_snapshot_file", "") or "").strip() or "state_snapshot.npz"
    snapshot_path = source_run / snapshot_file
    state_available = bool(snapshot_path.exists() or initial_state.get("state_snapshot_available"))
    if not state_available:
        errors.append("源结果缺少可用于起报的保存状态。")
    expected_start = ""
    if source_state_time:
        expected_start = context.format_time_for_check(pd.to_datetime(source_state_time) + pd.Timedelta(hours=step_hours), step_hours)
    else:
        errors.append("源结果未记录状态时刻，不能推断预报起报时间。")
    requested_start_raw = str(payload.get("forecast_start", "") or "").strip()
    forecast_start = requested_start_raw or expected_start
    forecast_end = str(payload.get("forecast_end", "") or "").strip()
    expected_index: pd.DatetimeIndex | None = None
    if not forecast_end:
        warnings.append("尚未填写预报结束时间。")
    if forecast_start and forecast_end:
        try:
            expected_index = forecast_expected_index(
                forecast_start,
                forecast_end,
                step_hours,
                normalize_time_step_hours=context.normalize_time_step_hours,
                is_date_only_string=context.is_date_only_string,
            )
            if expected_index.empty:
                errors.append("预报结束时间不能早于起报时间。")
            elif requested_start_raw and expected_start and pd.Timestamp(pd.to_datetime(forecast_start)) != pd.Timestamp(pd.to_datetime(expected_start)):
                errors.append(f"起报时间必须紧接源结果保存状态，当前应从 {expected_start} 起报。")
        except Exception as exc:
            errors.append(f"预报时段无法解析：{exc}")
    variables = [
        forecast_input_dir_summary(
            key="prec",
            label="降水",
            raw_path=str(payload.get("forecast_prec_dir", payload.get("prec_dir", "")) or ""),
            step_hours=step_hours,
            expected_index=expected_index,
            resolve_path=context.resolve_path,
            validate_tif_time_series=context.validate_tif_time_series,
            format_time_for_check=context.format_time_for_check,
        ),
        forecast_input_dir_summary(
            key="temp",
            label="气温",
            raw_path=str(payload.get("forecast_temp_dir", payload.get("temp_dir", "")) or ""),
            step_hours=step_hours,
            expected_index=expected_index,
            resolve_path=context.resolve_path,
            validate_tif_time_series=context.validate_tif_time_series,
            format_time_for_check=context.format_time_for_check,
        ),
        forecast_input_dir_summary(
            key="evap",
            label="潜在蒸散发",
            raw_path=str(payload.get("forecast_evap_dir", payload.get("evap_dir", "")) or ""),
            step_hours=step_hours,
            expected_index=expected_index,
            resolve_path=context.resolve_path,
            validate_tif_time_series=context.validate_tif_time_series,
            format_time_for_check=context.format_time_for_check,
        ),
    ]
    for item in variables:
        errors.extend(str(msg) for msg in list(item.get("errors", []) or []))
        warnings.extend(str(msg) for msg in list(item.get("warnings", []) or []))
    expected_steps = int(len(expected_index)) if expected_index is not None else 0
    status = "fail" if errors else "warn" if warnings or expected_steps <= 0 else "ok"
    coverage_complete = not errors and expected_steps > 0
    headline = (
        f"预报气象覆盖完整：{forecast_start} 至 {forecast_end}，共 {expected_steps} 个时间步。"
        if coverage_complete
        else "预报气象输入仍需核对。"
    )
    output_preview = forecast_output_preview(
        payload,
        source_run,
        profile_hint=str(metadata.get("calibration_profile", "") or ""),
        resolve_path=context.resolve_path,
        read_runtime_config=context.read_runtime_config,
        build_profile_paths=context.build_profile_paths,
        resolve_profile=context.resolve_profile,
    )
    output_status = "ok" if expected_steps > 0 else "warn"
    parameter_detail = forecast_parameter_detail_text(
        parameter_context,
        profile_labels=context.profile_labels,
        objective_label=context.objective_label,
        precip_source_label=context.precip_source_label,
        station_precip_mode_label=context.station_precip_mode_label,
    )
    station_precip_check = forecast_station_precip_check(
        payload,
        metadata,
        forecast_start,
        forecast_end,
        step_hours,
        resolve_path=context.resolve_path,
        read_runtime_config=context.read_runtime_config,
        analyze_station_precip_inputs=context.analyze_station_precip_inputs,
        meteo_key=context.meteo_key,
        meteo_precip_mode_key=context.meteo_precip_mode_key,
        time_basis_forecast_window=context.time_basis_forecast_window,
        time_basis_labels=context.time_basis_labels,
    )
    return {
        "status": status,
        "headline": headline,
        "errors": sorted(set(errors)),
        "warnings": sorted(set(warnings)),
        "source": {
            "source_run": str(source_run.resolve(strict=False)),
            "source_run_name": source_run.name,
            "parameter_count": int(len(params)),
            "state_available": state_available,
            "source_state_time": context.format_time_for_check(source_state_time, step_hours),
            "expected_forecast_start": expected_start,
            "parameter_context": parameter_context,
            "source_parameter_summary": dict(metadata.get("source_parameter_summary") or {}),
        },
        "parameter_context": parameter_context,
        "window": {
            "forecast_start": forecast_start,
            "forecast_end": forecast_end,
            "time_step_hours": float(step_hours),
            "expected_steps": expected_steps,
        },
        "output": output_preview,
        "variables": variables,
        "station_precip": station_precip_check,
        "items": [
            {"label": "源结果", "value": source_run.name, "status": "ok"},
            {"label": "起报状态", "value": context.format_time_for_check(source_state_time, step_hours) or "未记录", "status": "ok" if source_state_time and state_available else "fail"},
            {"label": "建议起报", "value": expected_start or "未形成", "status": "ok" if expected_start else "fail"},
            {"label": "预报时段", "value": f"{forecast_start} 至 {forecast_end}" if forecast_start and forecast_end else "未完整填写", "status": "ok" if expected_steps > 0 else "warn"},
            {"label": "参数来源", "value": f"源结果参数（{len(params)} 项）" if params else "缺少参数", "detail": parameter_detail, "status": "ok" if params else "fail"},
            {"label": "归档方式", "value": "运行时仅归档预报窗口内 P/T/PET 栅格", "status": "ok" if expected_steps > 0 else "warn"},
            {"label": "结果输出", "value": output_preview["result_label"], "detail": output_preview["result_detail"], "status": output_status},
            {"label": "输入清单", "value": output_preview["archive_label"], "detail": output_preview["archive_detail"], "status": output_status},
        ],
    }


def ensure_forecast_input_ready(payload: dict[str, Any], context: ForecastInputCheckContext) -> dict[str, Any]:
    check = forecast_input_check(payload, context)
    if str(check.get("status", "")).lower() == "fail":
        issues = [str(item) for item in list(check.get("errors", []) or []) if str(item).strip()]
        message = "；".join(issues[:3]) if issues else "预报气象输入检查未通过。"
        raise ValueError(f"连续状态预报输入检查未通过：{message}")
    return check
