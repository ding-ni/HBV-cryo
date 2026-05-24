#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Run one HBV forward simulation and export the series as JSON."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

import profile_runner
from profile_runner import patch_profile_behavior, patch_runtime_environment, resolve_profile


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="HBV-Studio forward simulation runner")
    parser.add_argument("--配置", "--config", dest="config", required=True)
    parser.add_argument("--参数文件", "--params-file", dest="params_file", required=True)
    parser.add_argument("--率定模式", "--profile", dest="profile", default="")
    parser.add_argument("--目标函数", "--objective-mode", dest="objective_mode", default="")
    parser.add_argument("--降水源", "--prec-source", dest="prec_source", choices=["mswep", "cmfd", "custom_tif"], default=None)
    parser.add_argument("--prec-dir", dest="prec_dir", default="")
    parser.add_argument("--冰川模式", "--glacier-mode", dest="glacier_mode", choices=["inline", "off"], default="inline")
    parser.add_argument("--output-json", dest="output_json", default="")
    return parser.parse_args()


def log_stage(message: str) -> None:
    print(f"[阶段] {message}", file=sys.stderr, flush=True)


def build_runtime_cli_args(
    config_path: Path,
    profile: str,
    objective_mode: str,
    prec_source: str,
    prec_dir: str,
    glacier_mode: str,
) -> argparse.Namespace:
    cli_args = argparse.Namespace(
        maxiter=1,
        popsize=2,
        seed=42,
        workers=1,
        method="mc_only",
        mc_samples=1,
        init_params_file=None,
        init_bound_shrink=0.0,
        quick_test=False,
        quick_days=30,
    )
    setattr(cli_args, "配置", str(config_path.resolve()))
    setattr(cli_args, "率定模式", profile)
    setattr(cli_args, "目标函数", objective_mode)
    setattr(cli_args, "降水源", prec_source)
    setattr(cli_args, "prec_dir", str(prec_dir or ""))
    setattr(cli_args, "冰川模式", glacier_mode)
    return cli_args


def resolve_input_path(raw_path: str, anchor: Path) -> Path:
    candidate = Path(str(raw_path or "").strip()).expanduser()
    if not candidate.is_absolute():
        candidate = (anchor / candidate).resolve(strict=False)
    else:
        candidate = candidate.resolve(strict=False)
    return candidate


def build_legacy_argv(prec_source: str, glacier_mode: str, prec_dir: str = "") -> list[str]:
    argv = [
        "forward_run.py",
        "--maxiter", "1",
        "--popsize", "2",
        "--seed", "42",
        "--workers", "1",
        "--method", "mc_only",
        "--mc-samples", "1",
        "--prec-source", prec_source,
        "--glacier-mode", glacier_mode,
    ]
    if prec_dir:
        argv.extend(["--prec-dir", prec_dir])
    return argv


def build_result(module: Any, sim: dict[str, Any], metrics: dict[str, Any]) -> dict[str, Any]:
    series_len = min(len(sim["q_total"]), len(module.Q_OBS_FULL))

    def to_series(values: Any) -> list[float | None]:
        if values is None:
            return [None] * series_len
        arr = values[:series_len]
        return [float(item) if module.np.isfinite(item) else None for item in arr]

    if hasattr(module, "format_time_value"):
        dates = [module.format_time_value(item) for item in module.SIM_DATES[:series_len]]
    else:
        dates = [str(item) for item in module.SIM_DATES[:series_len]]

    return {
        "dates": dates,
        "q_sim": to_series(sim["q_total"]),
        "q_obs": to_series(module.Q_OBS_FULL),
        "q_rain": to_series(sim.get("q_rain")),
        "q_snow": to_series(sim.get("q_snow")),
        "q_ice": to_series(sim.get("q_ice")),
        "q_boundary_inflow": to_series(sim.get("q_boundary")),
        "q_ice_reference": to_series(sim.get("q_ice_reference")) if sim.get("q_ice_reference") is not None else [None] * series_len,
        "metrics": {
            "nse_cal": round(float(metrics.get("nse_cal", float("nan"))), 4) if module.np.isfinite(metrics.get("nse_cal", float("nan"))) else None,
            "nse_val": round(float(metrics.get("nse_val", float("nan"))), 4) if module.np.isfinite(metrics.get("nse_val", float("nan"))) else None,
            "kge_cal": round(float(metrics.get("kge_cal", float("nan"))), 4) if module.np.isfinite(metrics.get("kge_cal", float("nan"))) else None,
            "kge_val": round(float(metrics.get("kge_val", float("nan"))), 4) if module.np.isfinite(metrics.get("kge_val", float("nan"))) else None,
            "log_nse_cal": round(float(metrics.get("log_nse_cal", float("nan"))), 4) if module.np.isfinite(metrics.get("log_nse_cal", float("nan"))) else None,
            "log_nse_val": round(float(metrics.get("log_nse_val", float("nan"))), 4) if module.np.isfinite(metrics.get("log_nse_val", float("nan"))) else None,
            "pbias_cal": round(float(metrics.get("pbias_cal", float("nan"))), 2) if module.np.isfinite(metrics.get("pbias_cal", float("nan"))) else None,
            "pbias_val": round(float(metrics.get("pbias_val", float("nan"))), 2) if module.np.isfinite(metrics.get("pbias_val", float("nan"))) else None,
            "rmse_cal": round(float(metrics.get("rmse_cal", float("nan"))), 4) if module.np.isfinite(metrics.get("rmse_cal", float("nan"))) else None,
            "rmse_val": round(float(metrics.get("rmse_val", float("nan"))), 4) if module.np.isfinite(metrics.get("rmse_val", float("nan"))) else None,
        },
        "runtime": {
            "cache_hit": False,
            "glacier_enabled": bool(sim.get("glacier_enabled")),
            "boundary_enabled": bool(sim.get("boundary_enabled")),
            "prec_source": str(getattr(module.args, "prec_source", "") or ""),
            "prec_dir": str(getattr(module.args, "prec_dir", "") or getattr(module, "PREC_DIR", "") or ""),
            "requested_objective_mode": str(getattr(module, "REQUESTED_OBJECTIVE_MODE", "") or ""),
            "objective_mode": str(getattr(module, "OBJECTIVE_MODE_SELECTED", "") or ""),
            "glacier_mode": str(getattr(module.args, "glacier_mode", "") or ""),
        },
    }


def build_param_vector(module: Any, params: dict[str, Any]) -> tuple[list[float], bool]:
    defaults: list[float] = []
    default_builder = getattr(module, "default_test_vector", None)
    if callable(default_builder):
        try:
            defaults = [float(v) for v in list(default_builder())]
        except Exception:
            defaults = []

    vector: list[float] = []
    for idx, name in enumerate(module.param_names):
        if name in params:
            value = float(params[name])
        elif idx < len(defaults):
            value = float(defaults[idx])
        else:
            value = 0.0
        vector.append(float(value))

    adjusted = False
    sanitizer = getattr(module, "sanitize_initial_param_vector", None)
    if callable(sanitizer):
        sanitized = [float(v) for v in list(sanitizer(vector))]
        adjusted = any(abs(float(a) - float(b)) > 1e-10 for a, b in zip(vector, sanitized))
        vector = sanitized
    return vector, adjusted


def main() -> None:
    args = parse_args()

    log_stage("读取工作区配置")
    config = profile_runner.read_config(args.config)
    config = profile_runner.normalize_legacy_project_paths(config)
    config_path = Path(str(config.get("_config_path", args.config) or args.config)).resolve(strict=False)
    profile = resolve_profile(config, args.profile or None)
    requested_objective_mode = profile_runner.normalize_objective_mode(args.objective_mode or None)
    objective_mode = profile_runner.resolve_objective_mode(config, args.objective_mode or None, profile)
    runtime_precip_source = profile_runner.resolve_runtime_precip_source(config, args.prec_source)
    legacy_precip_source = profile_runner.resolve_legacy_precip_source(runtime_precip_source)
    paths = profile_runner.build_profile_paths(config, profile)

    log_stage("读取参数文件")
    params_path = resolve_input_path(args.params_file, config_path.parent)
    params = json.loads(params_path.read_text(encoding="utf-8"))

    log_stage("加载 HBV 核心")
    module = profile_runner.load_legacy_module(profile_runner.old_script_path(config, "model", "calibrate_hbv_cryo.py"))

    runtime_prec_dir = str(args.prec_dir or (paths["aligned_prec_custom_dir"] if runtime_precip_source == "custom_tif" else ""))
    cli_args = build_runtime_cli_args(config_path, profile, objective_mode, runtime_precip_source, runtime_prec_dir, args.glacier_mode)
    patch_runtime_environment(module, config, profile, cli_args)
    patch_profile_behavior(module, config, profile, objective_mode)
    module.REQUESTED_OBJECTIVE_MODE = requested_objective_mode
    base_parse_args = module.parse_args

    def parse_args_with_runtime_source() -> argparse.Namespace:
        parsed = base_parse_args()
        parsed.prec_source = runtime_precip_source
        parsed.prec_dir = runtime_prec_dir
        return parsed

    module.parse_args = parse_args_with_runtime_source

    with profile_runner.temporary_argv(build_legacy_argv(legacy_precip_source, args.glacier_mode, runtime_prec_dir)):
        module.args = module.parse_args()
    module.configure_time_step()

    log_stage("加载气象与地理数据")
    module.load_all_data()

    log_stage("执行前向模拟")
    param_vector, params_adjusted = build_param_vector(module, params)
    sim = module.run_simulation(param_vector)

    log_stage("计算指标")
    metrics = module.compute_metrics(sim["q_total"])
    result = build_result(module, sim, metrics)
    result["runtime"]["params_adjusted"] = bool(params_adjusted)

    payload = json.dumps(result, ensure_ascii=False)
    log_stage("输出结果")
    if args.output_json:
        Path(args.output_json).write_text(payload, encoding="utf-8")
    else:
        sys.stdout.write(payload)


if __name__ == "__main__":
    main()
