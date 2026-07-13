#!/usr/bin/env python
# -*- coding: utf-8 -*-
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable


@dataclass(frozen=True)
class WorkspaceCompletenessContext:
    resolve_any_path: Callable[..., Path]
    read_runtime_config: Callable[[Path], dict[str, Any]]
    resolve_precip_source: Callable[[dict[str, Any], Any], str]
    detect_object_type: Callable[[dict[str, Any]], str]
    wizard_validate_step: Callable[..., dict[str, Any]]
    current_profile: Callable[[dict[str, Any]], str]
    build_profile_paths: Callable[[dict[str, Any], str], dict[str, Any]]
    workspace_dem_path: Callable[..., Path]
    configured_dem_kind: Callable[[dict[str, Any]], str | None]
    effective_precip_paths: Callable[..., tuple[str, str, str]]
    has_matching: Callable[[Path], bool]
    validate_workspace_fields: Callable[..., dict[str, Any]]
    object_interbasin: str


def _all_steps_for_object(object_type: str, context: WorkspaceCompletenessContext) -> list[int]:
    return [1, 2, 3, 4, 5, 6, 7] if object_type == context.object_interbasin else [1, 2, 4, 5, 6, 7]


def quick_workspace_completeness(
    config_path_raw: str,
    context: WorkspaceCompletenessContext,
    precip_source: Any = None,
) -> dict[str, Any]:
    """Return a lightweight workflow summary for dashboards and lists."""
    try:
        cfg_path = context.resolve_any_path(config_path_raw, must_exist=True)
        config = context.read_runtime_config(cfg_path)
    except Exception:
        return {"steps_completed": [], "steps_remaining": [1, 2, 3, 4, 5, 6, 7], "ready_for_calibration": False}

    runtime_prec_source = context.resolve_precip_source(config, precip_source)
    object_type = context.detect_object_type(config)
    all_steps = _all_steps_for_object(object_type, context)
    completed: list[int] = []
    for step in [s for s in all_steps if s in {1, 2, 3, 4}]:
        result = context.wizard_validate_step(str(cfg_path), step, precip_source=runtime_prec_source)
        if result["valid"]:
            completed.append(step)

    profile = context.current_profile(config)
    paths = context.build_profile_paths(config, profile)
    gis_dir = Path(paths["gis_dir"])
    dem_ready = context.workspace_dem_path(gis_dir, prefer=context.configured_dem_kind(config)).exists()
    flow_ready = (gis_dir / "flow_accumulation_masked.tif").exists()
    zone_low_ready = (gis_dir / "elevation_zone_low.tif").exists() or (gis_dir / "elevation_zone_mid.tif").exists()
    zone_high_ready = (gis_dir / "elevation_zone_high.tif").exists()
    if dem_ready and flow_ready and zone_low_ready and zone_high_ready:
        completed.append(5)

    _, precip_dir, _ = context.effective_precip_paths(config, profile, precip_source=runtime_prec_source)
    temp_dir = Path(paths["aligned_temp_dir"])
    evap_dir = Path(paths["aligned_evap_dir"])
    if context.has_matching(Path(precip_dir)) and context.has_matching(temp_dir) and context.has_matching(evap_dir):
        completed.append(6)

    completed = sorted(set(completed))
    remaining = [s for s in all_steps if s not in completed]
    pending_validation = 7 in all_steps and set(all_steps) - {7} <= set(completed)
    ready = False
    validation_missing: list[str] = []
    validation_warnings: list[str] = []
    next_step: int | None = remaining[0] if remaining else None
    if pending_validation:
        # Dashboard/list summaries must stay cheap. Full forcing, boundary, and
        # scientific validation remains mandatory when step 7 is opened or a
        # calibration is started; a quick summary never claims that gate passed.
        next_step = 7

    return {
        "steps_completed": completed,
        "steps_remaining": sorted(remaining),
        "all_steps": all_steps,
        "completed_count": len(completed),
        "total_steps": len(all_steps),
        "completion_ratio": (len(completed) / len(all_steps)) if all_steps else 0.0,
        "next_step": next_step,
        "ready_for_calibration": ready,
        "pending_validation": pending_validation,
        "missing": validation_missing if next_step == 7 else [],
        "warnings": validation_warnings if next_step == 7 else [],
        "object_type": object_type,
        "profile": profile,
    }


def workspace_completeness(
    config_path_raw: str,
    context: WorkspaceCompletenessContext,
    *,
    quick: bool = False,
    precip_source: Any = None,
) -> dict[str, Any]:
    """Return which wizard steps are completed for a workspace."""
    if quick:
        return quick_workspace_completeness(config_path_raw, context, precip_source=precip_source)
    try:
        cfg_path = context.resolve_any_path(config_path_raw, must_exist=True)
        config = context.read_runtime_config(cfg_path)
    except Exception:
        return {"steps_completed": [], "steps_remaining": [1, 2, 3, 4, 5, 6, 7], "ready_for_calibration": False}

    object_type = context.detect_object_type(config)
    all_steps = _all_steps_for_object(object_type, context)
    completed: list[int] = []
    for step in all_steps:
        result = context.wizard_validate_step(str(cfg_path), step, precip_source=precip_source)
        if result["valid"]:
            completed.append(step)
    remaining = [s for s in all_steps if s not in completed]

    profile = context.current_profile(config)
    calib_validation = context.validate_workspace_fields(str(cfg_path), stage="calibration", precip_source=precip_source)
    ready = calib_validation["valid"]
    next_step: int | None = remaining[0] if remaining else None

    return {
        "steps_completed": sorted(completed),
        "steps_remaining": sorted(remaining),
        "all_steps": all_steps,
        "completed_count": len(completed),
        "total_steps": len(all_steps),
        "completion_ratio": (len(completed) / len(all_steps)) if all_steps else 0.0,
        "next_step": next_step,
        "ready_for_calibration": ready,
        "pending_validation": False,
        "missing": calib_validation.get("missing", []),
        "warnings": calib_validation.get("warnings", []),
        "object_type": object_type,
        "profile": profile,
    }


def workspace_workflow_summary(
    config_path_raw: str,
    context: WorkspaceCompletenessContext,
    *,
    quick: bool = False,
    precip_source: Any = None,
) -> dict[str, Any]:
    comp = workspace_completeness(config_path_raw, context, quick=quick, precip_source=precip_source)
    return {
        "completed_count": int(comp.get("completed_count", 0)),
        "total_steps": int(comp.get("total_steps", 0)),
        "completion_ratio": float(comp.get("completion_ratio", 0.0)),
        "next_step": comp.get("next_step"),
        "ready_for_calibration": bool(comp.get("ready_for_calibration", False)),
        "pending_validation": bool(comp.get("pending_validation", False)),
        "missing_count": len(comp.get("missing", [])),
        "warning_count": len(comp.get("warnings", [])),
        "steps_remaining": list(comp.get("steps_remaining", [])),
    }
