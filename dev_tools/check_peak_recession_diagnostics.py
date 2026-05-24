#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Lightweight regression checks for unified-objective cryosphere diagnostics."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd


REPO_ROOT = Path(__file__).resolve().parents[1]
WORKSPACE_ROOT = REPO_ROOT.parent
sys.path.insert(0, str(REPO_ROOT / "HBV-Cryo"))
sys.path.insert(0, str(REPO_ROOT / "HBV-Studio"))
sys.path.insert(0, str(REPO_ROOT / "公共"))

import daily_unified_objective  # noqa: E402


REQUIRED_OBJECTIVE_KEYS = (
    "flow_guard",
    "secondary_terms",
)
REQUIRED_CRYO_KEYS = (
    "ice_dominance_guard",
    "peak_source_guard",
    "recession_takeover_diagnostic",
)
REQUIRED_DIAGNOSTICS = (
    "glacier_fraction_report",
    "peak_source_report",
    "recession_takeover_diagnostic",
)


def build_synthetic_bundle() -> tuple[dict[str, object], dict[str, float]]:
    dates = pd.date_range("2013-01-01", "2019-12-31", freq="D")
    doy = dates.dayofyear.to_numpy(dtype=np.float64)
    season = np.maximum(0.0, np.sin((doy - 90.0) / 365.0 * 2.0 * np.pi))
    q_rain = 20.0 + 20.0 * season
    q_snow = np.maximum(0.0, 80.0 * np.exp(-((doy - 145.0) / 35.0) ** 2))
    q_ice = np.maximum(0.0, 90.0 * np.exp(-((doy - 235.0) / 45.0) ** 2))
    q_total = q_rain + q_snow + q_ice
    bundle: dict[str, object] = {
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
        "q_obs_obj": q_total * 0.98,
        "calib_mask": np.ones(len(dates), dtype=bool),
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
    }
    metrics = {
        "nse_cal": 0.82,
        "nse_val": 0.78,
        "kge_cal": 0.80,
        "kge_val": 0.76,
        "log_nse_cal": 0.80,
        "log_nse_val": 0.75,
        "pbias_cal": 2.0,
        "pbias_val": 3.0,
    }
    return bundle, metrics


def check_synthetic_objective() -> dict[str, object]:
    bundle, metrics = build_synthetic_bundle()
    evaluation = daily_unified_objective.evaluate_daily_unified_objective(bundle, metrics, bad_obj=9999.0)
    assert evaluation.get("objective_family") == daily_unified_objective.OBJECTIVE_FAMILY
    assert evaluation.get("hard_checks", {}).get("status") == "pass"
    objective_terms = evaluation.get("objective_terms", {})
    for key in REQUIRED_OBJECTIVE_KEYS:
        assert key in objective_terms, f"missing objective_terms.{key}"
    cryo_terms = objective_terms.get("cryo_consistency", {})
    for key in REQUIRED_CRYO_KEYS:
        assert key in cryo_terms, f"missing objective_terms.cryo_consistency.{key}"
    diagnostics = evaluation.get("diagnostics", {})
    for key in REQUIRED_DIAGNOSTICS:
        assert key in diagnostics, f"missing diagnostics.{key}"
    return {
        "objective_family": evaluation.get("objective_family"),
        "flow_guard": objective_terms.get("flow_guard", {}).get("status"),
        "secondary_terms": objective_terms.get("secondary_terms", {}).get("status"),
        "ice_dominance_guard": cryo_terms.get("ice_dominance_guard", {}).get("status"),
        "peak_source_guard": cryo_terms.get("peak_source_guard", {}).get("status"),
        "recession_takeover_diagnostic": diagnostics.get("recession_takeover_diagnostic", {}).get("status"),
    }


def check_legacy_demo_metadata(limit: int = 5) -> dict[str, object]:
    demo_root = WORKSPACE_ROOT / "HBVStudio_Demo"
    if not demo_root.exists():
        return {"checked": 0, "skipped": "HBVStudio_Demo not found"}

    import studio_service  # noqa: E402

    checked = 0
    objective_families: set[str] = set()
    for metadata_path in sorted(demo_root.rglob("metadata.json")):
        run_dir = metadata_path.parent
        if not (run_dir / "simulation.csv").exists():
            continue
        raw = json.loads(metadata_path.read_text(encoding="utf-8"))
        metadata, resolved_config = studio_service.normalize_run_metadata(raw, run_path=run_dir)
        summary = studio_service._build_run_summary(run_dir, metadata, resolved_config)
        objective_family = str(summary.get("objective_family") or "").strip()
        if objective_family:
            objective_families.add(objective_family)
        diagnostics = metadata.get("diagnostics", {}) or {}
        # Legacy metadata may not have the new fields; compatibility means summary/detail loading does not raise.
        assert "peak_source_report" not in diagnostics or isinstance(diagnostics.get("peak_source_report"), dict)
        assert summary.get("path"), "run summary missing path"
        checked += 1
        if checked >= limit:
            break
    return {"checked": checked, "objective_families": sorted(objective_families)}


def main() -> None:
    result = {
        "synthetic_objective": check_synthetic_objective(),
        "legacy_demo_metadata": check_legacy_demo_metadata(),
    }
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
