#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Run a continuous-state HBV forecast from a saved calibration result."""
from __future__ import annotations

import argparse
import json
import shutil
import sys
import time
import uuid
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

import profile_runner
from forward_run import build_legacy_argv, build_param_vector, build_runtime_cli_args, resolve_input_path
from profile_runner import patch_profile_behavior, patch_runtime_environment, resolve_profile


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="HBV-Studio continuous-state forecast runner")
    parser.add_argument("--配置", "--config", dest="config", required=True)
    parser.add_argument("--source-run", dest="source_run", required=True)
    parser.add_argument("--forecast-start", dest="forecast_start", default="")
    parser.add_argument("--forecast-end", dest="forecast_end", required=True)
    parser.add_argument("--forecast-prec-dir", dest="forecast_prec_dir", default="")
    parser.add_argument("--forecast-temp-dir", dest="forecast_temp_dir", default="")
    parser.add_argument("--forecast-evap-dir", dest="forecast_evap_dir", default="")
    parser.add_argument("--率定模式", "--profile", dest="profile", default="")
    parser.add_argument("--目标函数", "--objective-mode", dest="objective_mode", default="")
    parser.add_argument("--降水源", "--prec-source", dest="prec_source", choices=["era5", "mswep", "cmfd", "custom_tif"], default="custom_tif")
    parser.add_argument("--冰川模式", "--glacier-mode", dest="glacier_mode", choices=["inline", "off"], default="inline")
    parser.add_argument("--output-dir", dest="output_dir", default="")
    parser.add_argument("--output-json", dest="output_json", default="")
    return parser.parse_args()


def log_stage(message: str, stage_callback: Any = None) -> None:
    print(f"[阶段] {message}", file=sys.stderr, flush=True)
    if callable(stage_callback):
        stage_callback(message, f"[阶段] {message}")


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def json_default(value: Any) -> Any:
    if isinstance(value, (np.floating, np.integer)):
        return value.item()
    if isinstance(value, np.ndarray):
        return value.tolist()
    if isinstance(value, (pd.Timestamp,)):
        return value.isoformat()
    return str(value)


def clean_for_json(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(k): clean_for_json(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [clean_for_json(v) for v in value]
    if isinstance(value, (np.floating, float)):
        number = float(value)
        return number if np.isfinite(number) else None
    if isinstance(value, (np.integer, int)):
        return int(value)
    if isinstance(value, np.ndarray):
        return clean_for_json(value.tolist())
    return value


def source_snapshot_path(source_run: Path, metadata: dict[str, Any]) -> Path:
    initial_state = dict(metadata.get("initial_state", {}) or {})
    snapshot_file = str(initial_state.get("state_snapshot_file", "") or "").strip() or "state_snapshot.npz"
    candidate = source_run / snapshot_file
    if not candidate.exists():
        raise FileNotFoundError("源结果目录缺少状态快照 state_snapshot.npz，请先用新版率定或手调结果生成状态。")
    return candidate


def params_from_source(metadata: dict[str, Any]) -> dict[str, Any]:
    params = dict(metadata.get("optimized_params", {}) or {})
    if params:
        return params
    raise ValueError("源结果缺少 optimized_params，不能进行不重新率定的预报运行。")


def build_source_parameter_summary(
    source_run: Path,
    source_metadata: dict[str, Any],
    params: dict[str, Any],
    profile: str,
    objective_mode: str,
) -> dict[str, Any]:
    data_sources = dict(source_metadata.get("data_sources", {}) or {})
    time_config = dict(source_metadata.get("time_config", {}) or {})
    initial_state = dict(source_metadata.get("initial_state", {}) or {})
    optimization = dict(source_metadata.get("optimization", {}) or {})
    return {
        "schema": "forecast_source_parameter_summary_v1",
        "parameter_source": "source_result",
        "parameter_source_label": "源结果参数",
        "source_run_path": str(source_run.resolve(strict=False)),
        "source_run_name": source_run.name,
        "source_run_title": str(source_metadata.get("result_title", "") or "").strip(),
        "source_run_class": str(source_metadata.get("run_class", "") or "").strip(),
        "source_run_time": str(source_metadata.get("run_time", "") or "").strip(),
        "parameter_count": int(len(params)),
        "calibration_profile": str(profile or source_metadata.get("calibration_profile") or "").strip(),
        "objective_mode": str(
            objective_mode
            or source_metadata.get("effective_objective_mode")
            or optimization.get("effective_objective_mode")
            or optimization.get("objective_mode")
            or ""
        ).strip(),
        "state_snapshot_time": str(initial_state.get("state_snapshot_time", "") or "").strip(),
        "time_step_hours": time_config.get("time_step_hours"),
        "prec_source": str(
            data_sources.get("runtime_prec_source")
            or data_sources.get("prec_source")
            or data_sources.get("configured_precip_source")
            or ""
        ).strip(),
        "glacier_mode": str(data_sources.get("glacier_mode", "") or "").strip(),
    }


def time_text(module: Any, value: Any) -> str:
    return module.format_time_value(pd.to_datetime(value))


def infer_forecast_start(module: Any, source_run: Path, metadata: dict[str, Any]) -> str:
    snapshot_time = source_state_time(source_run, metadata)
    next_time = pd.to_datetime(snapshot_time) + module.time_step_timedelta()
    return time_text(module, next_time)


def source_state_time(source_run: Path, metadata: dict[str, Any]) -> str:
    initial_state = dict(metadata.get("initial_state", {}) or {})
    snapshot_time = str(initial_state.get("state_snapshot_time", "") or "").strip()
    if not snapshot_time:
        csv_path = source_run / "simulation.csv"
        if csv_path.exists():
            frame = pd.read_csv(csv_path, usecols=["date"])
            if not frame.empty:
                snapshot_time = str(frame["date"].iloc[-1])
    if not snapshot_time:
        raise ValueError("无法从源结果推断状态日期，请显式提供 forecast_start。")
    return snapshot_time


def validate_forecast_window(
    module: Any,
    source_run: Path,
    metadata: dict[str, Any],
    forecast_start: str,
    forecast_end: str,
) -> dict[str, Any]:
    source_time = source_state_time(source_run, metadata)
    expected_start = time_text(module, pd.to_datetime(source_time) + module.time_step_timedelta())
    start_text = time_text(module, forecast_start)
    end_text = time_text(module, forecast_end)
    if pd.Timestamp(start_text) != pd.Timestamp(expected_start):
        raise ValueError(
            "连续状态预报起报时间必须紧接源状态快照："
            f"源状态时刻为 {time_text(module, source_time)}，当前应从 {expected_start} 起报。"
            f"如果需要从 {start_text} 起报，请先补充源状态后至该时刻前的历史气象强迫，"
            "完成状态滚动更新后再启动预报。"
        )
    if pd.Timestamp(end_text) < pd.Timestamp(start_text):
        raise ValueError(f"预报结束时间不能早于起报时间：{start_text} 至 {end_text}")
    return {
        "strict_continuity": True,
        "source_state_time": time_text(module, source_time),
        "expected_forecast_start": expected_start,
        "requested_forecast_start": start_text,
        "forecast_start": start_text,
        "forecast_end": end_text,
        "time_step_hours": float(module.TIME_STEP_HOURS),
        "gap_steps": 0,
    }


def apply_forecast_window(module: Any, forecast_start: str, forecast_end: str) -> None:
    start_text = time_text(module, forecast_start)
    end_text = time_text(module, forecast_end)
    module.WARMUP_START = start_text
    module.WARMUP_END = ""
    module.CALIB_START = start_text
    module.CALIB_END = end_text
    module.VALID_START = start_text
    module.VALID_END = end_text
    module.SIM_START = start_text
    module.SIM_END = end_text


def forecast_time_index(module: Any, forecast_start: str, forecast_end: str) -> pd.DatetimeIndex:
    dates = module.build_time_index(time_text(module, forecast_start), time_text(module, forecast_end))
    return pd.DatetimeIndex(dates)


def archive_forecast_inputs(
    module: Any,
    output_dir: Path,
    source_dirs: dict[str, str],
    forecast_start: str,
    forecast_end: str,
) -> dict[str, Any]:
    expected_index = forecast_time_index(module, forecast_start, forecast_end)
    expected_set = set(expected_index)
    archive_root = output_dir / "forecast_inputs"
    archive_root.mkdir(parents=True, exist_ok=True)
    manifest: dict[str, Any] = {
        "schema": "forecast_input_manifest_v1",
        "forecast_start": time_text(module, forecast_start),
        "forecast_end": time_text(module, forecast_end),
        "expected_steps": int(len(expected_index)),
        "created_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "variables": {},
    }
    archived_dirs: dict[str, str] = {}
    label_map = {"prec": "降水", "temp": "气温", "evap": "潜在蒸散发"}
    for key, label in label_map.items():
        src_dir = Path(str(source_dirs.get(key, "") or "")).resolve(strict=False)
        if not src_dir.exists():
            raise FileNotFoundError(f"预报{label}目录不存在：{src_dir}")
        tif_files = sorted(src_dir.glob("*.tif"))
        if not tif_files:
            raise FileNotFoundError(f"预报{label}目录中没有 .tif 文件：{src_dir}")
        time_to_file: dict[pd.Timestamp, Path] = {}
        invalid_files: list[str] = []
        duplicate_times: dict[str, list[str]] = {}
        for tif_path in tif_files:
            timestamp = module.parse_time_from_name(str(tif_path))
            if timestamp is None:
                invalid_files.append(tif_path.name)
                continue
            timestamp = pd.Timestamp(timestamp)
            if timestamp in time_to_file:
                duplicate_times.setdefault(module.format_time_value(timestamp), [time_to_file[timestamp].name]).append(tif_path.name)
            else:
                time_to_file[timestamp] = tif_path
        if invalid_files:
            raise ValueError(f"预报{label}目录存在无法解析时间的文件，例如：{'、'.join(invalid_files[:3])}")
        if duplicate_times:
            first_time, names = next(iter(duplicate_times.items()))
            raise ValueError(f"预报{label}目录存在重复时间 {first_time}，例如：{'、'.join(names[:3])}")
        missing = [timestamp for timestamp in expected_index if timestamp not in time_to_file]
        if missing:
            sample = "、".join(module.format_time_value(item) for item in missing[:3])
            raise ValueError(f"预报{label}目录缺少 {len(missing)} 个时间步，例如：{sample}")
        out_of_window = [timestamp for timestamp in time_to_file if timestamp not in expected_set]
        target_dir = archive_root / key
        if target_dir.exists():
            shutil.rmtree(target_dir)
        target_dir.mkdir(parents=True, exist_ok=True)
        copied_files: list[str] = []
        for timestamp in expected_index:
            src_file = time_to_file[pd.Timestamp(timestamp)]
            target_file = target_dir / src_file.name
            shutil.copy2(src_file, target_file)
            copied_files.append(target_file.name)
        archived_dirs[key] = str(target_dir.resolve(strict=False))
        manifest["variables"][key] = {
            "label": label,
            "source_dir": str(src_dir),
            "archive_dir": archived_dirs[key],
            "expected_steps": int(len(expected_index)),
            "archived_files": int(len(copied_files)),
            "out_of_window_files": int(len(out_of_window)),
            "first_time": module.format_time_value(expected_index[0]) if len(expected_index) else "",
            "last_time": module.format_time_value(expected_index[-1]) if len(expected_index) else "",
            "files": copied_files,
        }
    manifest_path = archive_root / "input_manifest.json"
    manifest_path.write_text(json.dumps(clean_for_json(manifest), ensure_ascii=False, indent=2, default=json_default), encoding="utf-8")
    return {
        "enabled": True,
        "archive_root": str(archive_root.resolve(strict=False)),
        "manifest_path": str(manifest_path.resolve(strict=False)),
        "manifest": manifest,
        "archived_dirs": archived_dirs,
    }


def series_values(values: Any, count: int) -> list[float | None]:
    if values is None:
        return [None] * count
    arr = np.asarray(values, dtype=np.float64)[:count]
    return [float(v) if np.isfinite(v) else None for v in arr]


def write_forecast_outputs(
    module: Any,
    output_dir: Path,
    sim: dict[str, Any],
    *,
    source_run: Path,
    snapshot_path: Path,
    params: dict[str, Any],
    config_path: Path,
    profile: str,
    objective_mode: str,
    forecast_dirs: dict[str, str],
    input_archive: dict[str, Any] | None = None,
    source_state_summary: dict[str, Any] | None = None,
    source_parameter_summary: dict[str, Any] | None = None,
) -> dict[str, Any]:
    output_dir.mkdir(parents=True, exist_ok=True)
    raw_dates = sim.get("date")
    if raw_dates is None:
        raw_dates = module.SIM_DATES
    dates = pd.DatetimeIndex(raw_dates)
    count = len(dates)
    q_obs = sim.get("q_obs")
    if q_obs is None or len(q_obs) != count:
        q_obs = np.full(count, np.nan, dtype=np.float64)
    frame = pd.DataFrame(
        {
            "date": [module.format_time_value(item) for item in dates],
            "q_forecast": series_values(sim.get("q_forecast", sim.get("q_total")), count),
            "q_sim": series_values(sim.get("q_total"), count),
            "q_sim_model": series_values(sim.get("q_local"), count),
            "q_boundary_inflow": series_values(sim.get("q_boundary"), count),
            "q_obs": series_values(q_obs, count),
            "q_rain": series_values(sim.get("q_rain"), count),
            "q_snow": series_values(sim.get("q_snow"), count),
            "q_ice": series_values(sim.get("q_ice"), count),
            "q_ice_raw": series_values(sim.get("q_ice_raw"), count),
            "q_ice_reference": [None] * count,
            "q_ice_reference_raw": [None] * count,
        }
    )
    frame.to_csv(output_dir / "forecast.csv", index=False, encoding="utf-8-sig")
    frame.to_csv(output_dir / "simulation.csv", index=False, encoding="utf-8-sig")

    state_arrays = dict(sim.get("forecast_state_snapshot_arrays", {}) or {})
    forecast_state_file = "forecast_state_snapshot.npz"
    if state_arrays:
        np.savez_compressed(output_dir / forecast_state_file, **state_arrays)

    restart = dict(sim.get("forecast_restart", {}) or {})
    source_initial = dict(read_json(source_run / "metadata.json").get("initial_state", {}) or {})
    source_state_time = str(source_initial.get("state_snapshot_time", "") or "").strip()
    source_state_summary = dict(source_state_summary or {})
    source_parameter_summary = dict(source_parameter_summary or {})
    metadata = {
        "schema": "hbv_studio_forecast_result_v1",
        "run_id": output_dir.name,
        "run_time": time.strftime("%Y-%m-%d %H:%M:%S"),
        "result_title": "连续状态预报",
        "run_class": "forecast_restart",
        "forecast_result": {
            "enabled": True,
            "label": "连续状态预报",
            "schema": restart.get("schema", "continuous_state_forecast_v1"),
            "status": restart.get("status", "ok"),
            "source_run_path": str(source_run.resolve(strict=False)),
            "source_run_name": source_run.name,
            "source_snapshot_file": str(snapshot_path.resolve(strict=False)),
            "source_state_time": source_state_time,
            "source_state_summary": clean_for_json(source_state_summary),
            "source_parameter_summary": clean_for_json(source_parameter_summary),
            "forecast_state_snapshot_file": forecast_state_file if state_arrays else None,
            "forecast_start": frame["date"].iloc[0] if count else "",
            "forecast_end": frame["date"].iloc[-1] if count else "",
            "time_steps": int(count),
            "routing_state_available": bool(restart.get("routing_state_available")),
            "forecast_input_archive": clean_for_json(input_archive or {}),
        },
        "workspace_config": str(config_path.resolve(strict=False)),
        "calibration_profile": profile,
        "rate_mode": profile,
        "effective_objective_mode": objective_mode,
        "optimized_params": clean_for_json(params),
        "metrics": {
            "calibration": {},
            "validation": {},
        },
        "time_config": {
            "time_step_hours": float(module.TIME_STEP_HOURS),
            "forecast_start": frame["date"].iloc[0] if count else "",
            "forecast_end": frame["date"].iloc[-1] if count else "",
            "warmup_steps": 0,
        },
        "source_state_summary": clean_for_json(source_state_summary),
        "source_parameter_summary": clean_for_json(source_parameter_summary),
        "initial_state": {
            "mode": "state_snapshot_restart",
            "hot_start_supported": True,
            "hot_start_enabled": True,
            "source_state_snapshot_file": str(snapshot_path.resolve(strict=False)),
            "source_state_snapshot_time": source_state_time,
            "state_snapshot_available": bool(state_arrays),
            "state_snapshot_file": forecast_state_file if state_arrays else None,
            "state_snapshot_schema": "per_cell_branch_states_v1",
            "state_snapshot_time": frame["date"].iloc[-1] if count else "",
            "state_snapshot_routing_state": bool(state_arrays),
            "notes": [
                "本结果从上一轮结果的 SP/SM/WC/UZ/LZ 与水源分支状态继续运行。",
                "预报运行不重新率定参数，只读取源结果参数、状态快照和未来气象输入。",
            ],
        },
        "data_sources": {
            "prec_source": "forecast_custom",
            "forecast_prec_dir": forecast_dirs.get("prec", ""),
            "forecast_temp_dir": forecast_dirs.get("temp", ""),
            "forecast_evap_dir": forecast_dirs.get("evap", ""),
            "forecast_input_archive": clean_for_json(input_archive or {}),
            "glacier_mode": str(getattr(module.args, "glacier_mode", "") or ""),
        },
        "optional_modules": {
            "glacier": {"enabled": bool(sim.get("glacier_enabled", False))},
            "boundary_inflow": {"enabled": bool(np.any(np.asarray(sim.get("q_boundary_raw", []), dtype=np.float64)))},
        },
    }
    metadata_path = output_dir / "metadata.json"
    metadata_path.write_text(json.dumps(clean_for_json(metadata), ensure_ascii=False, indent=2, default=json_default), encoding="utf-8")
    return {
        "run_path": str(output_dir.resolve(strict=False)),
        "forecast_csv": str((output_dir / "forecast.csv").resolve(strict=False)),
        "metadata": metadata,
    }


def run_forecast(args: argparse.Namespace, stage_callback: Any = None) -> dict[str, Any]:
    log_stage("读取工作区与源结果", stage_callback)
    config = profile_runner.read_config(args.config)
    config = profile_runner.normalize_legacy_project_paths(config)
    config_path = Path(str(config.get("_config_path", args.config) or args.config)).resolve(strict=False)
    source_run = resolve_input_path(args.source_run, config_path.parent)
    source_metadata = read_json(source_run / "metadata.json")
    log_stage("读取源状态快照", stage_callback)
    snapshot_path = source_snapshot_path(source_run, source_metadata)
    log_stage("读取源结果参数", stage_callback)
    params = params_from_source(source_metadata)

    profile = resolve_profile(config, args.profile or source_metadata.get("calibration_profile") or None)
    objective_mode = profile_runner.resolve_objective_mode(config, args.objective_mode or source_metadata.get("effective_objective_mode"), profile)
    runtime_prec_source = profile_runner.resolve_runtime_precip_source(config, args.prec_source or "custom_tif")
    legacy_precip_source = profile_runner.resolve_legacy_precip_source(runtime_prec_source)
    paths = profile_runner.build_profile_paths(config, profile)
    runtime_prec_dir = str(args.forecast_prec_dir or paths["aligned_prec_custom_dir"])

    log_stage("加载 HBV 核心", stage_callback)
    module = profile_runner.load_legacy_module(profile_runner.old_script_path(config, "model", "calibrate_hbv_cryo.py"))
    cli_args = build_runtime_cli_args(config_path, profile, objective_mode, runtime_prec_source, runtime_prec_dir, args.glacier_mode)
    patch_runtime_environment(module, config, profile, cli_args)
    patch_profile_behavior(module, config, profile, objective_mode)
    with profile_runner.temporary_argv(build_legacy_argv(legacy_precip_source, args.glacier_mode, runtime_prec_dir)):
        module.args = module.parse_args()
    module.args.prec_source = runtime_prec_source
    module.args.prec_dir = runtime_prec_dir
    module.configure_time_step()

    forecast_start = args.forecast_start or infer_forecast_start(module, source_run, source_metadata)
    log_stage("检查预报时段与源状态连续性", stage_callback)
    source_state_summary = validate_forecast_window(
        module,
        source_run,
        source_metadata,
        forecast_start,
        args.forecast_end,
    )
    forecast_start = str(source_state_summary["forecast_start"])
    forecast_end = str(source_state_summary["forecast_end"])
    source_parameter_summary = build_source_parameter_summary(
        source_run,
        source_metadata,
        params,
        profile,
        objective_mode,
    )
    apply_forecast_window(module, forecast_start, forecast_end)
    output_dir = Path(args.output_dir).resolve(strict=False) if args.output_dir else (
        Path(module.RUNS_DIR) / f"hbv_forecast_{source_run.name}_{time.strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:6]}"
    )
    source_forecast_dirs = {
        "prec": str(Path(args.forecast_prec_dir or runtime_prec_dir).resolve(strict=False)),
        "temp": str(Path(args.forecast_temp_dir or paths["aligned_temp_dir"]).resolve(strict=False)),
        "evap": str(Path(args.forecast_evap_dir or paths["aligned_evap_dir"]).resolve(strict=False)),
    }
    log_stage("检查预报气象时间覆盖", stage_callback)
    input_archive = archive_forecast_inputs(
        module,
        output_dir,
        source_forecast_dirs,
        forecast_start,
        forecast_end,
    )
    log_stage("归档预报气象输入", stage_callback)
    archived_dirs = dict(input_archive.get("archived_dirs", {}) or {})
    module.PREC_DIR = archived_dirs.get("prec", source_forecast_dirs["prec"])
    module.TEMP_DIR = archived_dirs.get("temp", source_forecast_dirs["temp"])
    module.EVAP_DIR = archived_dirs.get("evap", source_forecast_dirs["evap"])

    log_stage("加载未来气象与地理数据", stage_callback)
    module.load_all_data(end_date_override=module.SIM_END, skip_obs=True)

    log_stage("整理参数与源状态快照", stage_callback)
    param_vector, params_adjusted = build_param_vector(module, params)
    log_stage("执行连续状态预报", stage_callback)
    sim = module.run_forecast_from_state(param_vector, snapshot_path=snapshot_path)
    sim["glacier_enabled"] = module.glacier_feature_enabled()

    forecast_dirs = {
        "prec": module.PREC_DIR,
        "temp": module.TEMP_DIR,
        "evap": module.EVAP_DIR,
    }
    log_stage("写出预报结果", stage_callback)
    result = write_forecast_outputs(
        module,
        output_dir,
        sim,
        source_run=source_run,
        snapshot_path=snapshot_path,
        params=params,
        config_path=config_path,
        profile=profile,
        objective_mode=objective_mode,
        forecast_dirs=forecast_dirs,
        input_archive=input_archive,
        source_state_summary=source_state_summary,
        source_parameter_summary=source_parameter_summary,
    )
    log_stage("生成预报元数据", stage_callback)
    result["params_adjusted"] = bool(params_adjusted)
    log_stage("预报完成", stage_callback)
    return result


def main() -> None:
    args = parse_args()
    result = run_forecast(args)
    payload = json.dumps(clean_for_json(result), ensure_ascii=False, default=json_default)
    if args.output_json:
        Path(args.output_json).write_text(payload, encoding="utf-8")
    else:
        sys.stdout.write(payload)


if __name__ == "__main__":
    main()
