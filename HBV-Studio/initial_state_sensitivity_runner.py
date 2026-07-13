#!/usr/bin/env python
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import numpy as np

from studio_service import _build_forward_payload_context, _get_or_create_forward_runtime


STORAGE_KEYS = ("sp", "sm", "wc", "uz", "lz")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run dry/wet initial-state sensitivity for a saved HBV-Cryo run.")
    parser.add_argument("--run", required=True, help="Saved run directory containing metadata.json.")
    parser.add_argument("--output", default="", help="Optional output JSON path.")
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


def build_scientific_acceptance(metadata: dict[str, Any], sensitivity: dict[str, Any]) -> dict[str, Any]:
    water_balance = dict(metadata.get("model_water_balance", {}) or {})
    water_screening = dict(water_balance.get("hydrological_screening", {}) or {})
    water_accepted = bool(water_screening.get("formal_interval_acceptance", False))
    initial_state_accepted = bool(sensitivity.get("converged", False))
    blockers = list(water_screening.get("reasons", []) or [])
    if not water_balance.get("available"):
        blockers.append("model_water_balance_pending_or_unavailable")
    if not initial_state_accepted:
        blockers.append("initial_state_sensitivity_not_converged")
    blockers = list(dict.fromkeys(str(item) for item in blockers if str(item).strip()))
    accepted = bool(water_accepted and initial_state_accepted and not blockers)
    return {
        "status": "accepted" if accepted else "blocked_by_scientific_qc",
        "formal_result_accepted": accepted,
        "model_water_balance_accepted": water_accepted,
        "initial_state_sensitivity_accepted": initial_state_accepted,
        "blockers": blockers,
        "notes": [
            "Outlet NSE/KGE cannot override interval water-availability or warm-up convergence gates.",
            "A blocked result remains usable for internal diagnosis, not formal interval validation.",
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
    metadata["scientific_acceptance"] = build_scientific_acceptance(metadata, sensitivity)
    temporary = metadata_path.with_suffix(".json.tmp")
    temporary.write_text(json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(metadata_path)
    return metadata["scientific_acceptance"]


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
    try:
        for name, init_state in _initial_state_vectors(params).items():
            module.INIT_ST = np.asarray(init_state, dtype="float64")
            simulation = module.run_simulation(vector)
            snapshot_arrays, snapshot_meta = module.compute_state_snapshot(vector, end_step=warmup_steps)
            q_total = np.asarray(simulation["q_total"], dtype="float64")
            flow_series[name] = q_total
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


def main() -> None:
    args = parse_args()
    run_path = Path(args.run).resolve(strict=True)
    result = run_sensitivity(run_path)
    output_path = Path(args.output).resolve(strict=False) if args.output else run_path / "initial_state_sensitivity.json"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    acceptance = update_run_metadata(run_path, result)
    print(
        json.dumps(
            {
                "output": str(output_path),
                "converged": result["converged"],
                "formal_result_accepted": acceptance["formal_result_accepted"],
            },
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
