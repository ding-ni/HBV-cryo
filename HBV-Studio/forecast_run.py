#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Run a continuous-state HBV forecast from a saved calibration result."""
from __future__ import annotations

import argparse
import json
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


def log_stage(message: str) -> None:
    print(f"[阶段] {message}", file=sys.stderr, flush=True)


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


def time_text(module: Any, value: Any) -> str:
    return module.format_time_value(pd.to_datetime(value))


def infer_forecast_start(module: Any, source_run: Path, metadata: dict[str, Any]) -> str:
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
    next_time = pd.to_datetime(snapshot_time) + module.time_step_timedelta()
    return time_text(module, next_time)


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
    metadata = {
        "schema": "hbv_studio_forecast_result_v1",
        "run_id": output_dir.name,
        "run_time": time.strftime("%Y-%m-%d %H:%M:%S"),
        "result_title": "状态接续预报",
        "run_class": "forecast_restart",
        "forecast_result": {
            "enabled": True,
            "label": "状态接续预报",
            "schema": restart.get("schema", "continuous_state_forecast_v1"),
            "status": restart.get("status", "ok"),
            "source_run_path": str(source_run.resolve(strict=False)),
            "source_run_name": source_run.name,
            "source_snapshot_file": str(snapshot_path.resolve(strict=False)),
            "forecast_state_snapshot_file": forecast_state_file if state_arrays else None,
            "forecast_start": frame["date"].iloc[0] if count else "",
            "forecast_end": frame["date"].iloc[-1] if count else "",
            "time_steps": int(count),
            "routing_state_available": bool(restart.get("routing_state_available")),
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
        "initial_state": {
            "mode": "state_snapshot_restart",
            "hot_start_supported": True,
            "hot_start_enabled": True,
            "source_state_snapshot_file": str(snapshot_path.resolve(strict=False)),
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


def run_forecast(args: argparse.Namespace) -> dict[str, Any]:
    log_stage("读取工作区与源结果")
    config = profile_runner.read_config(args.config)
    config = profile_runner.normalize_legacy_project_paths(config)
    config_path = Path(str(config.get("_config_path", args.config) or args.config)).resolve(strict=False)
    source_run = resolve_input_path(args.source_run, config_path.parent)
    source_metadata = read_json(source_run / "metadata.json")
    snapshot_path = source_snapshot_path(source_run, source_metadata)
    params = params_from_source(source_metadata)

    profile = resolve_profile(config, args.profile or source_metadata.get("calibration_profile") or None)
    objective_mode = profile_runner.resolve_objective_mode(config, args.objective_mode or source_metadata.get("effective_objective_mode"), profile)
    runtime_prec_source = profile_runner.resolve_runtime_precip_source(config, args.prec_source or "custom_tif")
    legacy_precip_source = profile_runner.resolve_legacy_precip_source(runtime_prec_source)
    paths = profile_runner.build_profile_paths(config, profile)
    runtime_prec_dir = str(args.forecast_prec_dir or paths["aligned_prec_custom_dir"])

    log_stage("加载 HBV 核心")
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
    apply_forecast_window(module, forecast_start, args.forecast_end)
    module.PREC_DIR = str(Path(args.forecast_prec_dir or runtime_prec_dir).resolve(strict=False))
    if args.forecast_temp_dir:
        module.TEMP_DIR = str(Path(args.forecast_temp_dir).resolve(strict=False))
    if args.forecast_evap_dir:
        module.EVAP_DIR = str(Path(args.forecast_evap_dir).resolve(strict=False))

    log_stage("加载未来气象与地理数据")
    module.load_all_data(end_date_override=module.SIM_END, skip_obs=True)

    log_stage("读取参数并从状态快照重启")
    param_vector, params_adjusted = build_param_vector(module, params)
    sim = module.run_forecast_from_state(param_vector, snapshot_path=snapshot_path)
    sim["glacier_enabled"] = module.glacier_feature_enabled()

    output_dir = Path(args.output_dir).resolve(strict=False) if args.output_dir else (
        Path(module.RUNS_DIR) / f"hbv_forecast_{source_run.name}_{time.strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:6]}"
    )
    forecast_dirs = {
        "prec": module.PREC_DIR,
        "temp": module.TEMP_DIR,
        "evap": module.EVAP_DIR,
    }
    log_stage("写出预报结果")
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
    )
    result["params_adjusted"] = bool(params_adjusted)
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
