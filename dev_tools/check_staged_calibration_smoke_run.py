#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Smoke-run staged_calibration_v1 and verify persisted Studio metadata.

This is a development-side engineering fixture.  It uses a tiny synthetic
hydrograph so the staged workflow can execute all three phases quickly without
touching BM-02, translator logic, product objective selectors, or real project
data.
"""

from __future__ import annotations

import csv
import os
import importlib.util
import json
import shutil
import sys
import time
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import numpy as np
import pandas as pd


REPO_ROOT = Path(__file__).resolve().parents[1]
CORE_ROOT = REPO_ROOT / "HBV-Cryo"
STUDIO_ROOT = REPO_ROOT / "HBV-Studio"
SMOKE_ROOT = Path(
    os.environ.get(
        "HBV_STAGED_SMOKE_ROOT",
        str(REPO_ROOT.parent / "memories" / "staged_calibration_smoke"),
    )
).resolve(strict=False)
SMOKE_RUN_DIR = SMOKE_ROOT / "workspace" / "结果" / "日尺度" / "运行记录" / "staged_calibration_v1_smoke_run"

sys.path.insert(0, str(STUDIO_ROOT))
sys.path.insert(0, str(REPO_ROOT / "公共"))


def json_safe(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [json_safe(item) for item in value]
    if isinstance(value, np.ndarray):
        return json_safe(value.tolist())
    if isinstance(value, (np.integer,)):
        return int(value)
    if isinstance(value, (np.floating, float)):
        val = float(value)
        return val if np.isfinite(val) else None
    if isinstance(value, pd.Timestamp):
        return value.strftime("%Y-%m-%d")
    return value


def load_calibration_core() -> Any:
    for path in CORE_ROOT.glob("*.py"):
        text = path.read_text(encoding="utf-8-sig", errors="ignore")
        if "CALIBRATION_WORKFLOW_STAGED" in text and "staged_calibration_phase_definitions" in text:
            spec = importlib.util.spec_from_file_location("hbv_cryo_staged_smoke_core", path)
            if spec is None or spec.loader is None:
                raise RuntimeError(f"无法加载率定核心：{path}")
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            return module
    raise FileNotFoundError("未找到 staged_calibration_v1 率定核心脚本。")


def reset_smoke_root() -> None:
    if SMOKE_ROOT.exists():
        resolved = SMOKE_ROOT.resolve(strict=False)
        workspace_root = REPO_ROOT.parent.resolve(strict=False)
        try:
            resolved.relative_to(workspace_root)
        except ValueError as exc:
            raise RuntimeError(f"拒绝清理仓库工作根之外的 smoke 目录：{resolved}") from exc
        if resolved.name not in {"staged_calibration_smoke", "_staged_calibration_smoke"}:
            raise RuntimeError(f"拒绝清理非预期 smoke 目录：{resolved}")
        shutil.rmtree(resolved)
    (SMOKE_ROOT / "logs").mkdir(parents=True, exist_ok=True)
    (SMOKE_ROOT / "cache").mkdir(parents=True, exist_ok=True)
    SMOKE_RUN_DIR.mkdir(parents=True, exist_ok=True)


def synthetic_series() -> dict[str, Any]:
    dates = pd.date_range("2013-01-01", "2019-12-31", freq="D")
    doy = dates.dayofyear.to_numpy(dtype=np.float64)
    season = np.maximum(0.0, np.sin((doy - 80.0) / 365.0 * 2.0 * np.pi))
    q_rain = 18.0 + 18.0 * season
    q_snow = np.maximum(0.0, 55.0 * np.exp(-((doy - 145.0) / 34.0) ** 2))
    q_ice = np.maximum(0.0, 48.0 * np.exp(-((doy - 235.0) / 45.0) ** 2))
    q_total = q_rain + q_snow + q_ice
    q_obs = q_total.copy()
    return {
        "dates": dates,
        "q_rain": q_rain,
        "q_snow": q_snow,
        "q_ice": q_ice,
        "q_total": q_total,
        "q_obs": q_obs,
    }


def write_simulation_csv(run_dir: Path, series: dict[str, Any]) -> None:
    run_dir.mkdir(parents=True, exist_ok=True)
    with (run_dir / "simulation.csv").open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(
            fh,
            fieldnames=[
                "date",
                "q_sim",
                "q_sim_model",
                "q_local",
                "q_boundary_inflow",
                "q_obs",
                "q_rain",
                "q_snow",
                "q_ice",
                "q_ice_raw",
                "q_ice_reference",
                "q_ice_reference_raw",
            ],
        )
        writer.writeheader()
        for idx, date in enumerate(series["dates"]):
            writer.writerow(
                {
                    "date": pd.Timestamp(date).strftime("%Y-%m-%d"),
                    "q_sim": float(series["q_total"][idx]),
                    "q_sim_model": float(series["q_total"][idx]),
                    "q_local": float(series["q_total"][idx]),
                    "q_boundary_inflow": 0.0,
                    "q_obs": float(series["q_obs"][idx]),
                    "q_rain": float(series["q_rain"][idx]),
                    "q_snow": float(series["q_snow"][idx]),
                    "q_ice": float(series["q_ice"][idx]),
                    "q_ice_raw": float(series["q_ice"][idx]),
                    "q_ice_reference": float(series["q_ice"][idx]),
                    "q_ice_reference_raw": float(series["q_ice"][idx]),
                }
            )


def write_smoke_workspace() -> Path:
    path = SMOKE_ROOT / "staged_smoke_workspace.json"
    config = {
        "_说明": ["staged_calibration_v1 smoke fixture，仅用于开发侧工程链路验收，不作为科学 benchmark。"],
        "项目对象": "full_upstream_basin",
        "率定模式": "daily",
        "目标函数模式": "auto",
        "率定流程": "staged_calibration_v1",
        "运行目录": str((SMOKE_ROOT / "workspace").resolve()),
        "流域名称": "staged_calibration_v1_smoke",
        "流域编号": "staged_smoke",
        "时间步长_小时": 24.0,
        "时间": {
            "预热开始": "2013-01-01",
            "预热结束": "2013-12-31",
            "率定开始": "2014-01-01",
            "率定结束": "2017-12-31",
            "验证开始": "2018-01-01",
            "验证结束": "2019-12-31",
        },
        "气象策略": {"降水源": "custom_tif", "降水来源": "custom_tif"},
    }
    path.write_text(json.dumps(config, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def configure_core_for_smoke(core: Any, series: dict[str, Any]) -> None:
    core.TIME_STEP_HOURS = 24.0
    core.configure_time_step()
    core.CALIBRATION_PROFILE = "daily"
    core.CALIBRATION_PROFILE_LABEL = "staged smoke daily"
    core.OBJECTIVE_MODE_SELECTED = core.OBJECTIVE_FAMILY_DAILY
    core.REQUESTED_OBJECTIVE_MODE = core.OBJECTIVE_FAMILY_DAILY
    core.OBJECTIVE_PROFILE = {"type": core.OBJECTIVE_FAMILY_DAILY, "profile": "daily"}
    core.PARAMETER_PROFILE = None
    core.PROJECT_OBJECT_TYPE = "full_upstream_basin"
    core.BOUNDARY_INFLOW_ENABLED = False
    core.GLACIER_FRAC_WINDOW = [0.02, 0.20]
    core.BASIN_GLACIER_AREA_FRACTION = 0.04
    core.GLACIER_ELEV_STATUS = "missing"
    core.RELIABILITY_FLAG = "degraded_missing_glacier_elev"

    dates = pd.DatetimeIndex(series["dates"])
    calib_mask = (dates >= "2014-01-01") & (dates <= "2017-12-31")
    valid_mask = (dates >= "2018-01-01") & (dates <= "2019-12-31")
    core.SIM_DATES = dates
    core.CALIB_MASK = np.asarray(calib_mask, dtype=np.bool_)
    core.VALID_MASK = np.asarray(valid_mask, dtype=np.bool_)
    core.Q_OBS_FULL = np.asarray(series["q_obs"], dtype=np.float64)
    core.Q_OBS_CALIB = core.Q_OBS_FULL[core.CALIB_MASK]
    core.Q_OBS_VALID = core.Q_OBS_FULL[core.VALID_MASK]
    core.WARMUP_STEPS = 0
    core.CATCHMENT_AREA = 1000.0

    core.LOG_DIR = str(SMOKE_ROOT / "logs")
    core.CACHE_DIR = str(SMOKE_ROOT / "cache")
    core.RUNS_DIR = str(SMOKE_RUN_DIR.parent)
    core.setup_logging()
    core.start_time = time.time()
    core.eval_count = 0
    core.gen_count = 0
    core.best_score = -np.inf
    core.best_objective = np.inf
    core.best_params = None
    core.OPTIMIZATION_STAGE_STATS = {}
    core.STAGED_CALIBRATION_METADATA = {}
    core.CALIBRATION_WORKFLOW_SELECTED = core.CALIBRATION_WORKFLOW_STAGED
    core.args = SimpleNamespace(
        method="mc_only",
        mc_samples=1,
        maxiter=1,
        popsize=1,
        workers=1,
        seed=20260427,
        tol=1e-3,
        polish=False,
        init_params_file="",
        init_bound_shrink=0.0,
        log_every=1,
        prec_source="smoke",
        glacier_mode="inline",
        debug_days=0,
        quick_test=False,
    )

    def smoke_run_simulation(_vector: Any, mode: str | None = None) -> dict[str, Any]:
        q_rain = np.asarray(series["q_rain"], dtype=np.float64)
        q_snow = np.asarray(series["q_snow"], dtype=np.float64)
        q_ice = np.asarray(series["q_ice"], dtype=np.float64)
        q_total = np.asarray(series["q_total"], dtype=np.float64)
        return {
            "date": dates,
            "q_total": q_total,
            "q_local": q_total,
            "q_boundary": np.zeros(len(dates), dtype=np.float64),
            "q_rain": q_rain,
            "q_snow": q_snow,
            "q_ice": q_ice,
            "q_ice_raw": q_ice,
            "q_snow_glacier": q_snow,
            "q_glacier_total": q_snow + q_ice,
            "q_ice_reference": q_ice,
            "q_ice_reference_raw": q_ice,
            "q_obs_obj": core.Q_OBS_FULL,
            "calib_mask": core.CALIB_MASK,
            "project_object_type": "full_upstream_basin",
            "q_score_basis": "q_total",
            "muskingum_coeffs": {"C0": 0.2, "C1": 0.3, "C2": 0.5},
            "glacier_enabled": True,
            "glacier_model_mode": "fractional_subgrid",
            "glacier_area_ratio": 0.04,
            "glacier_mask_exists": True,
            "glacier_fraction_exists": True,
            "glacier_elev_exists": False,
            "glacier_fraction_window": [0.02, 0.20],
            "boundary_enabled": False,
        }

    core.run_simulation = smoke_run_simulation


def run_staged_smoke(core: Any) -> Any:
    base_bounds = core.validate_search_bounds(core.PARAM_BOUNDS)
    init_vector = core.default_test_vector()
    result = core.run_staged_calibration_workflow(base_bounds, init_vector, t_single=0.001, worker_map=None)
    assert getattr(result, "calibration_workflow", "") == core.CALIBRATION_WORKFLOW_STAGED
    return result


def build_metadata(core: Any, result: Any, series: dict[str, Any], workspace_config: Path) -> dict[str, Any]:
    sim = core.run_simulation(result.x)
    q_score, _ = core.scoring_series(sim)
    metrics = core.compute_metrics(q_score)
    objective_value, evaluation = core.compute_objective_terms(metrics, sim)
    workflow = dict(core.STAGED_CALIBRATION_METADATA or {})
    return {
        "run_id": "staged_calibration_v1_smoke_run",
        "run_time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "result_title": "staged_calibration_v1 smoke run",
        "workspace_label": "staged smoke fixture",
        "workspace_config": str(workspace_config.resolve()),
        "project_object_type": "full_upstream_basin",
        "calibration_profile": "daily",
        "rate_mode": "daily",
        "requested_objective_mode": core.OBJECTIVE_FAMILY_DAILY,
        "effective_objective_mode": core.OBJECTIVE_FAMILY_DAILY,
        "recorded_objective_family": core.OBJECTIVE_FAMILY_DAILY,
        "objective_family": core.OBJECTIVE_FAMILY_DAILY,
        "calibration_workflow": workflow.get("calibration_workflow"),
        "calibration_phases": workflow.get("calibration_phases", []),
        "final_selected_phase": workflow.get("final_selected_phase"),
        "final_parameters_from_phase": workflow.get("final_parameters_from_phase"),
        "calibration_workflow_guards": workflow.get("active_objective_guards", []),
        "calibration_workflow_notes": workflow.get("notes", []),
        "time_config": {
            "time_step_hours": 24.0,
            "warmup_start": "2013-01-01",
            "warmup_end": "2013-12-31",
            "calib_start": "2014-01-01",
            "calib_end": "2017-12-31",
            "valid_start": "2018-01-01",
            "valid_end": "2019-12-31",
            "warmup_steps": 0,
        },
        "data_sources": {"runtime_prec_source": "synthetic_smoke", "prec_source": "synthetic_smoke"},
        "optional_modules": {
            "glacier": {
                "enabled": True,
                "model_mode": "fractional_subgrid",
                "mask_exists": True,
                "fraction_exists": True,
                "elev_exists": False,
                "reference_available": True,
            },
            "boundary_inflow": {"enabled": False},
        },
        "basin_info": {"catchment_area_km2": 1000.0, "valid_cells": 9, "glacier_cells": 1},
        "reliability_flag": "degraded_missing_glacier_elev",
        "reliability_notes": ["smoke fixture 缺少 glacier_elev.tif；仅验证工程链路，不作科学解释。"],
        "objective_value": float(objective_value),
        "hard_checks": evaluation.get("hard_checks", {}),
        "objective_terms": evaluation.get("objective_terms", {}),
        "diagnostics": evaluation.get("diagnostics", {}),
        "diagnostic_only_constraints": evaluation.get("diagnostic_only_constraints", {}),
        "evidence_registry": evaluation.get("evidence_registry", {}),
        "metrics": {
            "calibration": {
                "sample_count": int(metrics.get("obs_count_cal", 0)),
                "nse": round(float(metrics.get("nse_cal", np.nan)), 4),
                "kge": round(float(metrics.get("kge_cal", np.nan)), 4),
                "pbias": round(float(metrics.get("pbias_cal", np.nan)), 2),
            },
            "validation": {
                "sample_count": int(metrics.get("obs_count_val", 0)),
                "nse": round(float(metrics.get("nse_val", np.nan)), 4),
                "kge": round(float(metrics.get("kge_val", np.nan)), 4),
                "pbias": round(float(metrics.get("pbias_val", np.nan)), 2),
            },
        },
        "optimization": {
            "method": "staged_smoke_mc_only",
            "mc_samples": 1,
            "maxiter": 1,
            "popsize": 1,
            "workers": 1,
            "objective_value": float(objective_value),
            "objective_mode": core.OBJECTIVE_FAMILY_DAILY,
            "effective_objective_mode": core.OBJECTIVE_FAMILY_DAILY,
            "calibration_workflow": workflow.get("calibration_workflow"),
            "final_selected_phase": workflow.get("final_selected_phase"),
            "stage_stats": core.OPTIMIZATION_STAGE_STATS,
        },
        "parameter_profile": core.current_parameter_profile(),
        "objective_profile": core.current_objective_profile(),
        "optimized_params": {name: round(float(value), 6) for name, value in zip(core.param_names, result.x)},
        "fixed_params": {},
        "smoke_fixture": {
            "enabled": True,
            "scope": "development_regression_only",
            "not_scientific_benchmark": True,
            "not_bm02_tuning": True,
            "series_length": int(len(series["dates"])),
        },
    }


def write_legacy_fixture(run_dir: Path, objective_family: str) -> Path:
    legacy_dir = run_dir.parent / f"legacy_{objective_family}"
    legacy_dir.mkdir(parents=True, exist_ok=True)
    (legacy_dir / "simulation.csv").write_text("date,q_sim,q_obs\n2014-01-01,1.0,1.0\n", encoding="utf-8")
    metadata = {
        "run_id": f"legacy_{objective_family}",
        "run_time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "optimization": {"objective_mode": objective_family, "effective_objective_mode": objective_family},
        "objective": {"type": objective_family},
        "metrics": {"calibration": {"nse": 0.1, "pbias": 5.0}, "validation": {"nse": 0.1, "pbias": 5.0}},
        "objective_terms": {},
        "diagnostics": {},
    }
    (legacy_dir / "metadata.json").write_text(json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8")
    return legacy_dir


def assert_staged_metadata(metadata: dict[str, Any]) -> dict[str, Any]:
    assert metadata.get("calibration_workflow") == "staged_calibration_v1"
    assert metadata.get("objective_family") == "daily_unified_professional_v1"
    phases = list(metadata.get("calibration_phases", []) or [])
    assert len(phases) >= 3
    assert phases[0].get("name") == "hydrologic_skeleton"
    assert phases[1].get("name") == "snow_process"
    assert phases[2].get("name") == "glacier_refinement"
    for phase in phases[:3]:
        assert phase.get("released_parameters"), f"{phase.get('name')} missing released_parameters"
        assert phase.get("locked_parameters") or phase.get("fixed_parameters"), f"{phase.get('name')} missing fixed params"
        assert phase.get("search_stats"), f"{phase.get('name')} missing search_stats"
    assert phases[1].get("seed_from_previous_phase") is True
    assert phases[2].get("seed_from_previous_phase") is True
    assert metadata.get("final_selected_phase") == "glacier_refinement"
    assert metadata.get("final_parameters_from_phase") == "glacier_refinement"
    guards = set(metadata.get("calibration_workflow_guards", []) or [])
    cryo_terms = dict(metadata.get("objective_terms", {}).get("cryo_consistency", {}) or {})
    diagnostics = dict(metadata.get("diagnostics", {}) or {})
    assert "peak_source_guard" in guards or "peak_source_guard" in cryo_terms
    assert "recession_takeover_diagnostic" in guards or "recession_takeover_diagnostic" in diagnostics
    return {
        "phase_names": [item.get("name") for item in phases[:3]],
        "phase_release_counts": {item.get("name"): len(item.get("released_parameters", [])) for item in phases[:3]},
        "phase_fixed_counts": {
            item.get("name"): len(item.get("fixed_parameters") or item.get("locked_parameters") or [])
            for item in phases[:3]
        },
    }


def assert_studio_metadata_compatibility(run_dir: Path, legacy_dirs: list[Path]) -> dict[str, Any]:
    import studio_service  # noqa: E402

    raw = json.loads((run_dir / "metadata.json").read_text(encoding="utf-8"))
    metadata, resolved_config = studio_service.normalize_run_metadata(raw, run_path=run_dir)
    summary = studio_service._build_run_summary(run_dir, metadata, resolved_config)
    assert summary.get("path")
    assert summary.get("objective_family") == "daily_unified_professional_v1"
    assert summary.get("flow_guard_status") == "ok"

    legacy_families: list[str] = []
    for path in legacy_dirs:
        raw_legacy = json.loads((path / "metadata.json").read_text(encoding="utf-8"))
        legacy_meta, legacy_config = studio_service.normalize_run_metadata(raw_legacy, run_path=path)
        legacy_summary = studio_service._build_run_summary(path, legacy_meta, legacy_config)
        family = str(legacy_summary.get("objective_family") or "")
        assert family in {"weighted_daily_universal", "weighted_multi_criteria"}
        legacy_families.append(family)

    return {
        "summary_objective_family": summary.get("objective_family"),
        "studio_compatible": bool(summary.get("studio_compatible")),
        "legacy_families": sorted(legacy_families),
    }


def main() -> None:
    reset_smoke_root()
    workspace_config = write_smoke_workspace()
    series = synthetic_series()
    core = load_calibration_core()
    configure_core_for_smoke(core, series)
    result = run_staged_smoke(core)

    metadata = build_metadata(core, result, series, workspace_config)
    write_simulation_csv(SMOKE_RUN_DIR, series)
    (SMOKE_RUN_DIR / "metadata.json").write_text(
        json.dumps(json_safe(metadata), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    legacy_dirs = [
        write_legacy_fixture(SMOKE_RUN_DIR, "weighted_daily_universal"),
        write_legacy_fixture(SMOKE_RUN_DIR, "weighted_multi_criteria"),
    ]

    persisted = json.loads((SMOKE_RUN_DIR / "metadata.json").read_text(encoding="utf-8"))
    staged_summary = assert_staged_metadata(persisted)
    studio_summary = assert_studio_metadata_compatibility(SMOKE_RUN_DIR, legacy_dirs)

    print(
        json.dumps(
            {
                "smoke_run": {
                    "run_dir": str(SMOKE_RUN_DIR),
                    "metadata_json": str(SMOKE_RUN_DIR / "metadata.json"),
                    "simulation_csv": str(SMOKE_RUN_DIR / "simulation.csv"),
                },
                "staged_metadata": staged_summary,
                "studio_metadata_parser": studio_summary,
                "product_boundary": {
                    "dev_tool_only": True,
                    "not_bm02_tuning": True,
                    "not_scientific_benchmark": True,
                },
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
