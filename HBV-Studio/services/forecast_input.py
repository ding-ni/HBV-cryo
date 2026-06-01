#!/usr/bin/env python
# -*- coding: utf-8 -*-
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

import pandas as pd


@dataclass(frozen=True)
class ForecastInputCheckContext:
    resolve_path: Callable[..., Path]
    read_json_file: Callable[[Path], dict[str, Any]]
    parameter_check_context: Callable[[dict[str, Any], Path, dict[str, Any]], dict[str, Any]]
    normalize_time_step_hours: Callable[[Any], float]
    is_date_only_string: Callable[[str], bool]
    validate_tif_time_series: Callable[..., dict[str, Any]]
    format_time_for_check: Callable[[Any, float], str]
    forecast_output_preview: Callable[..., dict[str, Any]]
    forecast_parameter_detail_text: Callable[[dict[str, Any]], str]
    forecast_station_precip_check: Callable[[dict[str, Any], dict[str, Any], str, str, float], dict[str, Any] | None]


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
    parameter_context = context.parameter_check_context(payload, source_run, metadata)
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
    output_preview = context.forecast_output_preview(
        payload,
        source_run,
        profile_hint=str(metadata.get("calibration_profile", "") or ""),
    )
    output_status = "ok" if expected_steps > 0 else "warn"
    parameter_detail = context.forecast_parameter_detail_text(parameter_context)
    station_precip_check = context.forecast_station_precip_check(
        payload,
        metadata,
        forecast_start,
        forecast_end,
        step_hours,
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
