#!/usr/bin/env python
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from studio_service import _build_forward_payload_context, _get_or_create_forward_runtime


STORAGE_KEYS = ("sp", "sm", "wc", "uz", "lz")
LOCAL_FLOW_KEYS = ("q_local_raw", "q_local", "q_total")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run dry/wet initial-state sensitivity for a saved HBV-Cryo run.")
    parser.add_argument("--run", required=True, help="Saved run directory containing metadata.json.")
    parser.add_argument("--output", default="", help="Optional output JSON path.")
    parser.add_argument(
        "--proxy-cycles",
        type=int,
        default=0,
        help=(
            "Repeat the available forcing period this many times before the target run. "
            "This is a non-formal spin-up diagnostic and never updates scientific acceptance."
        ),
    )
    return parser.parse_args()


def _finite_stats(values: np.ndarray) -> dict[str, float | None]:
    finite = np.asarray(values, dtype="float64")
    finite = finite[np.isfinite(finite)]
    if finite.size == 0:
        return {"mean": None, "median": None, "p05": None, "p95": None, "max": None}
    return {
        "mean": float(np.mean(finite)),
        "median": float(np.median(finite)),
        "p05": float(np.percentile(finite, 5)),
        "p95": float(np.percentile(finite, 95)),
        "max": float(np.max(finite)),
    }


def summarize_snapshot(arrays: dict[str, np.ndarray], metadata: dict[str, Any]) -> dict[str, Any]:
    branches = list(metadata.get("branches", []) or [])
    combined: dict[str, np.ndarray] = {}
    if branches == ["glacier", "nonglacier"]:
        fraction = np.clip(np.asarray(arrays["glacier_fraction_cells"], dtype="float64"), 0.0, 1.0)
        for key in STORAGE_KEYS:
            combined[key] = (
                fraction * np.asarray(arrays[f"glacier_{key}"], dtype="float64")
                + (1.0 - fraction) * np.asarray(arrays[f"nonglacier_{key}"], dtype="float64")
            )
    elif "main" in branches:
        for key in STORAGE_KEYS:
            combined[key] = np.asarray(arrays[f"main_{key}"], dtype="float64")
    else:
        raise ValueError(f"Unsupported state snapshot branches: {branches}")
    total = np.zeros_like(next(iter(combined.values())), dtype="float64")
    for values in combined.values():
        total += np.where(np.isfinite(values), values, 0.0)
    return {
        "snapshot_time": str(metadata.get("snapshot_time", "")),
        "time_steps": int(metadata.get("time_steps", 0) or 0),
        "branch_mode": str(metadata.get("snapshot_mode", "")),
        "cell_count": int(metadata.get("cell_count", 0) or 0),
        "basin_storage_mm": {key.upper(): _finite_stats(values) for key, values in combined.items()},
        "total_storage_mm": _finite_stats(total),
    }


def _initial_state_vectors(params: dict[str, float]) -> dict[str, list[float]]:
    wet_sp = 50.0
    cwh = max(float(params.get("CWH", 0.05)), 0.0)
    return {
        "dry": [0.0, 0.0, 0.0, 0.0, 0.0],
        "wet": [
            wet_sp,
            0.8 * max(float(params.get("FC", 100.0)), 0.0),
            max(10.0, 0.5 * max(float(params.get("UZL", 0.0)), 0.0)),
            50.0,
            0.5 * cwh * wet_sp,
        ],
    }


def _select_local_flow(simulation: dict[str, Any]) -> tuple[np.ndarray, str]:
    for key in LOCAL_FLOW_KEYS:
        values = simulation.get(key)
        if values is not None:
            return np.asarray(values, dtype="float64"), key
    raise KeyError("Simulation output has no local or total flow series.")


def build_proxy_forcing_layout(total_steps: int, warmup_steps: int, proxy_cycles: int) -> dict[str, int]:
    total_steps = int(total_steps)
    warmup_steps = int(warmup_steps)
    proxy_cycles = int(proxy_cycles)
    if total_steps <= 0:
        raise ValueError("The available forcing period is empty.")
    if warmup_steps <= 0 or warmup_steps >= total_steps:
        raise ValueError("The proxy diagnostic requires warm-up and evaluation steps in the saved run.")
    if proxy_cycles <= 0:
        raise ValueError("proxy_cycles must be at least 1.")
    target_start = proxy_cycles * total_steps
    return {
        "available_period_steps": total_steps,
        "proxy_cycles": proxy_cycles,
        "combined_steps": (proxy_cycles + 1) * total_steps,
        "target_start_step": target_start,
        "target_warmup_end_step": target_start + warmup_steps,
        "target_evaluation_start_step": target_start + warmup_steps,
        "target_evaluation_end_step": (proxy_cycles + 1) * total_steps,
    }


def _kernel_parameters(module: Any, vector: np.ndarray) -> tuple[np.ndarray, float, float, float]:
    values = module.validate_parameter_vector(vector)
    (
        tt,
        fc,
        beta,
        lp,
        rfcf,
        sfcf,
        cfr,
        cwh,
        cfmax_low,
        cfmax_high,
        k,
        k1,
        k2,
        uzl,
        perc,
        ice_factor,
        _k_musk,
        _x_musk,
    ) = values
    par_base = np.asarray(
        [
            tt,
            rfcf,
            sfcf,
            0.0,
            cwh,
            cfr,
            fc,
            beta,
            module.FIXED["E_CORR"],
            lp,
            module.scale_recession_to_step(k),
            module.scale_recession_to_step(k1),
            module.scale_recession_to_step(k2),
            uzl,
            module.scale_linear_to_step(perc),
        ],
        dtype="float64",
    )
    return (
        par_base,
        float(ice_factor),
        float(module.scale_linear_to_step(cfmax_low)),
        float(module.scale_linear_to_step(cfmax_high)),
    )


def _run_local_forcing(
    module: Any,
    vector: np.ndarray,
    prec_cells: np.ndarray,
    temp_cells: np.ndarray,
    et_cells: np.ndarray,
    ll_temp_cells: np.ndarray,
) -> dict[str, Any]:
    par_base, ice_factor, cfmax_low_step, cfmax_high_step = _kernel_parameters(module, vector)
    glacier_on = bool(module.glacier_feature_enabled())
    fractional = bool(
        glacier_on
        and module.glacier_processing_mode() == "fractional_subgrid"
        and module.GLACIER_FRACTION_CELLS is not None
    )
    if fractional:
        return module.run_fractional_subgrid_simulation_arrays(
            "full",
            par_base,
            ice_factor,
            cfmax_low_step,
            cfmax_high_step,
            prec_cells,
            temp_cells,
            et_cells,
            ll_temp_cells,
        )

    active_cells = np.ones_like(module.ZONE_HIGH_CELLS, dtype=np.bool_)
    glacier_cells = (
        np.ascontiguousarray(module.GLACIER_CELLS, dtype=np.bool_)
        if module.GLACIER_CELLS is not None
        else np.zeros_like(active_cells, dtype=np.bool_)
    )
    return module.unpack_full_kernel_result(
        module.run_all_cells_flat(
            prec_cells,
            temp_cells,
            et_cells,
            ll_temp_cells,
            par_base,
            module.ZONE_HIGH_CELLS,
            module.INIT_ST,
            module.CELL_SCALE,
            glacier_cells,
            glacier_on,
            ice_factor,
            cfmax_low_step,
            cfmax_high_step,
            module.GLACIER_DELTA_T_CELLS,
        )
    )


def _snapshot_for_proxy_inputs(
    module: Any,
    vector: np.ndarray,
    arrays: tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray],
    dates: pd.DatetimeIndex,
    end_step: int,
) -> tuple[dict[str, np.ndarray], dict[str, Any]]:
    original = (
        module.PREC_CELLS,
        module.TEMP_CELLS,
        module.ET_CELLS,
        module.LL_TEMP_CELLS,
        module.SIM_DATES,
    )
    try:
        module.PREC_CELLS, module.TEMP_CELLS, module.ET_CELLS, module.LL_TEMP_CELLS = arrays
        module.SIM_DATES = dates
        return module.compute_state_snapshot(vector, end_step=end_step)
    finally:
        (
            module.PREC_CELLS,
            module.TEMP_CELLS,
            module.ET_CELLS,
            module.LL_TEMP_CELLS,
            module.SIM_DATES,
        ) = original


def _runoff_depth_mm(module: Any, values: np.ndarray) -> float:
    q = np.asarray(values, dtype="float64")
    finite = np.isfinite(q)
    if not np.any(finite):
        return 0.0
    area_km2 = float(module.CATCHMENT_AREA)
    if area_km2 <= 0.0:
        raise ValueError("Catchment area must be positive for runoff-depth conversion.")
    step_seconds = float(module.TIME_STEP_HOURS) * 3600.0
    return float(np.sum(q[finite]) * step_seconds / (area_km2 * 1000.0))


def build_initial_state_diagnostic(metadata: dict[str, Any], sensitivity: dict[str, Any]) -> dict[str, Any]:
    water_balance = dict(metadata.get("model_water_balance", {}) or {})
    water_screening = dict(water_balance.get("hydrological_screening", {}) or {})
    converged = bool(sensitivity.get("converged", False))
    uses_repeated_forcing = not bool(sensitivity.get("formal_acceptance_eligible", True))
    warnings = list(water_screening.get("reasons", []) or [])
    if not water_balance.get("available"):
        warnings.append("model_water_balance_pending_or_unavailable")
    if not converged:
        warnings.append("initial_state_sensitivity_detected")
    if uses_repeated_forcing:
        warnings.append("repeated_forcing_proxy_used")
    warnings = list(dict.fromkeys(str(item) for item in warnings if str(item).strip()))
    return {
        "status": "converged" if converged else "initial_state_sensitive",
        "converged": converged,
        "model_water_balance_available": bool(water_balance.get("available")),
        "repeated_forcing_proxy_used": uses_repeated_forcing,
        "warnings": warnings,
        "notes": [
            "Initial-state sensitivity is an engineering diagnostic, not a model-run gate.",
            "Within-year warm-up is valid when it covers the available pre-evaluation period; extend it only when the application requires lower initial-state sensitivity.",
        ],
    }


def update_run_metadata(run_path: Path, sensitivity: dict[str, Any]) -> dict[str, Any]:
    metadata_path = run_path / "metadata.json"
    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    metadata["initial_state_sensitivity"] = {
        "schema": str(sensitivity.get("schema", "")),
        "output_file": "initial_state_sensitivity.json",
        "converged": bool(sensitivity.get("converged", False)),
        "flow_converged": bool(sensitivity.get("flow_converged", False)),
        "storage_converged": bool(sensitivity.get("storage_converged", False)),
        "last_14_step_flow_relative_difference_percent": (
            sensitivity.get("warmup_last_14_steps_flow", {}).get("relative_difference_percent")
        ),
        "warmup_end_total_storage_relative_difference_percent": sensitivity.get(
            "warmup_end_total_storage_relative_difference_percent"
        ),
    }
    diagnostic = build_initial_state_diagnostic(metadata, sensitivity)
    metadata["initial_state_sensitivity"]["diagnostic_status"] = diagnostic["status"]
    metadata["engineering_diagnostics"] = dict(metadata.get("engineering_diagnostics", {}) or {})
    metadata["engineering_diagnostics"]["initial_state"] = diagnostic
    metadata.pop("scientific_acceptance", None)
    temporary = metadata_path.with_suffix(".json.tmp")
    temporary.write_text(json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(metadata_path)
    return diagnostic


def run_sensitivity(run_path: Path) -> dict[str, Any]:
    metadata_path = run_path / "metadata.json"
    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    params = {str(key): float(value) for key, value in dict(metadata.get("optimized_params", {}) or {}).items()}
    if not params:
        raise ValueError(f"Saved run has no optimized_params: {run_path}")
    context = _build_forward_payload_context(
        {"run_path": str(run_path.resolve()), "params": params, "save_run": False}
    )
    entry, cache_hit = _get_or_create_forward_runtime(context)
    module = entry.module
    vector = np.asarray([params[name] for name in module.param_names], dtype="float64")
    warmup_steps = int(module.WARMUP_STEPS or 0)
    if warmup_steps <= 0:
        raise ValueError("The saved run has no continuous warm-up period.")

    original_init = np.asarray(module.INIT_ST, dtype="float64").copy()
    cases: dict[str, Any] = {}
    flow_series: dict[str, np.ndarray] = {}
    flow_basis = ""
    try:
        for name, init_state in _initial_state_vectors(params).items():
            module.INIT_ST = np.asarray(init_state, dtype="float64")
            simulation = module.run_simulation(vector)
            snapshot_arrays, snapshot_meta = module.compute_state_snapshot(vector, end_step=warmup_steps)
            q_local, selected_basis = _select_local_flow(simulation)
            flow_series[name] = q_local
            flow_basis = selected_basis
            cases[name] = {
                "initial_state": {
                    key: float(value)
                    for key, value in zip(("SP", "SM", "UZ", "LZ", "WC"), init_state)
                },
                "warmup_end_state": summarize_snapshot(snapshot_arrays, snapshot_meta),
            }
    finally:
        module.INIT_ST = original_init

    compare_start = max(0, warmup_steps - 14)
    dry_flow = flow_series["dry"][compare_start:warmup_steps]
    wet_flow = flow_series["wet"][compare_start:warmup_steps]
    finite = np.isfinite(dry_flow) & np.isfinite(wet_flow)
    differences = np.abs(dry_flow[finite] - wet_flow[finite])
    flow_scale = float(np.mean((np.abs(dry_flow[finite]) + np.abs(wet_flow[finite])) / 2.0)) if np.any(finite) else 0.0
    mean_abs_flow_difference = float(np.mean(differences)) if differences.size else None
    flow_difference_percent = (
        float(mean_abs_flow_difference / flow_scale * 100.0)
        if mean_abs_flow_difference is not None and flow_scale > 1e-12 else None
    )

    dry_total = cases["dry"]["warmup_end_state"]["total_storage_mm"]["mean"]
    wet_total = cases["wet"]["warmup_end_state"]["total_storage_mm"]["mean"]
    storage_scale = (abs(float(dry_total)) + abs(float(wet_total))) / 2.0 if dry_total is not None and wet_total is not None else 0.0
    storage_difference_percent = (
        abs(float(wet_total) - float(dry_total)) / storage_scale * 100.0
        if storage_scale > 1e-12 else None
    )
    flow_converged = flow_difference_percent is not None and flow_difference_percent <= 5.0
    storage_converged = storage_difference_percent is not None and storage_difference_percent <= 10.0
    recommended_years = 3 if storage_difference_percent is not None and storage_difference_percent > 20.0 else 2
    return {
        "schema": "hbv_cryo_initial_state_sensitivity_v1",
        "run_path": str(run_path.resolve()),
        "workspace_config": str(context["config_path"]),
        "cache_hit": bool(cache_hit),
        "formal_acceptance_eligible": True,
        "flow_comparison_basis": flow_basis,
        "warmup_steps": int(warmup_steps),
        "warmup_start": str(module.WARMUP_START),
        "warmup_end": str(module.WARMUP_END),
        "cases": cases,
        "warmup_last_14_steps_flow": {
            "sample_count": int(np.count_nonzero(finite)),
            "dry_mean_m3s": float(np.mean(dry_flow[finite])) if np.any(finite) else None,
            "wet_mean_m3s": float(np.mean(wet_flow[finite])) if np.any(finite) else None,
            "mean_absolute_difference_m3s": mean_abs_flow_difference,
            "max_absolute_difference_m3s": float(np.max(differences)) if differences.size else None,
            "relative_difference_percent": flow_difference_percent,
        },
        "warmup_end_total_storage_relative_difference_percent": storage_difference_percent,
        "convergence_thresholds": {
            "last_14_step_flow_relative_difference_percent_max": 5.0,
            "warmup_end_total_storage_relative_difference_percent_max": 10.0,
        },
        "flow_converged": bool(flow_converged),
        "storage_converged": bool(storage_converged),
        "converged": bool(flow_converged and storage_converged),
        "interpretation": (
            "A failed threshold marks residual initial-state uncertainty; calibration scores must not hide it."
        ),
        "recommended_remedy": {
            "minimum_continuous_warmup_years": int(recommended_years),
            "preferred_forcing": "consistent earlier P/T/PET; ERA5-Land may be used for state spin-up with an explicit bias-transition manifest",
            "fallback_when_earlier_forcing_is_unavailable": "retain dry/wet initial-state ensemble and report its prediction range",
            "prohibited_shortcut": "do not tune hydrological or glacier parameters to erase initial-state sensitivity",
        },
    }


def run_repeated_forcing_proxy(run_path: Path, proxy_cycles: int) -> dict[str, Any]:
    metadata_path = run_path / "metadata.json"
    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    params = {str(key): float(value) for key, value in dict(metadata.get("optimized_params", {}) or {}).items()}
    if not params:
        raise ValueError(f"Saved run has no optimized_params: {run_path}")
    context = _build_forward_payload_context(
        {"run_path": str(run_path.resolve()), "params": params, "save_run": False}
    )
    entry, cache_hit = _get_or_create_forward_runtime(context)
    module = entry.module
    vector = np.asarray([params[name] for name in module.param_names], dtype="float64")
    layout = build_proxy_forcing_layout(
        int(module.PREC_CELLS.shape[1]),
        int(module.WARMUP_STEPS or 0),
        int(proxy_cycles),
    )
    repeats = int(proxy_cycles) + 1
    combined = tuple(
        np.ascontiguousarray(np.tile(np.asarray(values), (1, repeats)))
        for values in (module.PREC_CELLS, module.TEMP_CELLS, module.ET_CELLS, module.LL_TEMP_CELLS)
    )
    original_dates = pd.DatetimeIndex(module.SIM_DATES)
    combined_dates = pd.DatetimeIndex(np.tile(original_dates.to_numpy(), repeats))
    warmup_end_step = int(layout["target_warmup_end_step"])
    evaluation_slice = slice(
        int(layout["target_evaluation_start_step"]),
        int(layout["target_evaluation_end_step"]),
    )

    original_init = np.asarray(module.INIT_ST, dtype="float64").copy()
    cases: dict[str, Any] = {}
    flow_series: dict[str, np.ndarray] = {}
    try:
        for name, init_state in _initial_state_vectors(params).items():
            module.INIT_ST = np.asarray(init_state, dtype="float64")
            simulation = _run_local_forcing(module, vector, *combined)
            snapshot_arrays, snapshot_meta = _snapshot_for_proxy_inputs(
                module,
                vector,
                combined,
                combined_dates,
                warmup_end_step,
            )
            q_local = np.asarray(simulation["q_total"], dtype="float64")
            flow_series[name] = q_local
            cases[name] = {
                "initial_state": {
                    key: float(value)
                    for key, value in zip(("SP", "SM", "UZ", "LZ", "WC"), init_state)
                },
                "target_warmup_end_state": summarize_snapshot(snapshot_arrays, snapshot_meta),
                "target_evaluation_runoff_mm": {
                    "total": _runoff_depth_mm(module, q_local[evaluation_slice]),
                    "rain": _runoff_depth_mm(module, np.asarray(simulation["q_rain"])[evaluation_slice]),
                    "snow": _runoff_depth_mm(module, np.asarray(simulation["q_snow"])[evaluation_slice]),
                    "ice": _runoff_depth_mm(module, np.asarray(simulation["q_ice"])[evaluation_slice]),
                },
            }
    finally:
        module.INIT_ST = original_init

    compare_start = max(0, warmup_end_step - 14)
    dry_flow = flow_series["dry"][compare_start:warmup_end_step]
    wet_flow = flow_series["wet"][compare_start:warmup_end_step]
    finite = np.isfinite(dry_flow) & np.isfinite(wet_flow)
    differences = np.abs(dry_flow[finite] - wet_flow[finite])
    flow_scale = float(np.mean((np.abs(dry_flow[finite]) + np.abs(wet_flow[finite])) / 2.0)) if np.any(finite) else 0.0
    mean_abs_flow_difference = float(np.mean(differences)) if differences.size else None
    flow_difference_percent = (
        float(mean_abs_flow_difference / flow_scale * 100.0)
        if mean_abs_flow_difference is not None and flow_scale > 1e-12 else None
    )
    dry_total = cases["dry"]["target_warmup_end_state"]["total_storage_mm"]["mean"]
    wet_total = cases["wet"]["target_warmup_end_state"]["total_storage_mm"]["mean"]
    storage_scale = (abs(float(dry_total)) + abs(float(wet_total))) / 2.0 if dry_total is not None and wet_total is not None else 0.0
    storage_difference_percent = (
        abs(float(wet_total) - float(dry_total)) / storage_scale * 100.0
        if storage_scale > 1e-12 else None
    )
    flow_converged = flow_difference_percent is not None and flow_difference_percent <= 5.0
    storage_converged = storage_difference_percent is not None and storage_difference_percent <= 10.0
    current_evaluation = dict(metadata.get("model_water_balance", {}).get("windows", {}).get("evaluation", {}) or {})
    return {
        "schema": "hbv_cryo_repeated_forcing_spinup_proxy_v1",
        "run_path": str(run_path.resolve()),
        "workspace_config": str(context["config_path"]),
        "cache_hit": bool(cache_hit),
        "formal_acceptance_eligible": False,
        "forcing_identity": {
            "mode": "repeated_available_period_proxy",
            "proxy_cycles_before_target": int(proxy_cycles),
            "available_period_start": str(original_dates[0]),
            "available_period_end": str(original_dates[-1]),
            "available_period_steps": int(len(original_dates)),
            "contains_repeated_target_year_weather": True,
            "contains_continuous_historical_weather": False,
        },
        "layout": layout,
        "cases": cases,
        "target_warmup_last_14_steps_local_flow": {
            "sample_count": int(np.count_nonzero(finite)),
            "dry_mean_m3s": float(np.mean(dry_flow[finite])) if np.any(finite) else None,
            "wet_mean_m3s": float(np.mean(wet_flow[finite])) if np.any(finite) else None,
            "mean_absolute_difference_m3s": mean_abs_flow_difference,
            "max_absolute_difference_m3s": float(np.max(differences)) if differences.size else None,
            "relative_difference_percent": flow_difference_percent,
        },
        "target_warmup_end_total_storage_relative_difference_percent": storage_difference_percent,
        "convergence_thresholds": {
            "last_14_step_local_flow_relative_difference_percent_max": 5.0,
            "warmup_end_total_storage_relative_difference_percent_max": 10.0,
        },
        "flow_converged": bool(flow_converged),
        "storage_converged": bool(storage_converged),
        "converged": bool(flow_converged and storage_converged),
        "current_saved_run_evaluation_local_runoff_raw_mm": current_evaluation.get("local_runoff_raw_mm"),
        "interpretation": (
            "This proxy isolates whether longer state cycling can remove initial-condition dependence. "
            "It reuses target-period weather and cannot replace continuous historical forcing."
        ),
        "required_next_step": (
            "Build a continuous ERA5-Land historical spin-up with an explicit precipitation-bias transition manifest, "
            "then recalibrate the target period."
        ),
    }


def main() -> None:
    args = parse_args()
    run_path = Path(args.run).resolve(strict=True)
    if int(args.proxy_cycles) > 0:
        result = run_repeated_forcing_proxy(run_path, int(args.proxy_cycles))
        output_path = (
            Path(args.output).resolve(strict=False)
            if args.output
            else run_path / "initial_state_spinup_proxy.json"
        )
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
        print(
            json.dumps(
                {
                    "output": str(output_path),
                    "converged": result["converged"],
                    "formal_acceptance_eligible": False,
                },
                ensure_ascii=False,
            )
        )
        return
    result = run_sensitivity(run_path)
    output_path = Path(args.output).resolve(strict=False) if args.output else run_path / "initial_state_sensitivity.json"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    diagnostic = update_run_metadata(run_path, result)
    print(
        json.dumps(
            {
                "output": str(output_path),
                "converged": result["converged"],
                "diagnostic_status": diagnostic["status"],
            },
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
