#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Regression checks for staged_calibration_v1 metadata and product boundaries."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[1]
WORKSPACE_ROOT = REPO_ROOT.parent
CORE_ROOT = REPO_ROOT / "HBV-Cryo"
STUDIO_ROOT = REPO_ROOT / "HBV-Studio"
sys.path.insert(0, str(STUDIO_ROOT))
sys.path.insert(0, str(REPO_ROOT / "公共"))


def load_calibration_core() -> Any:
    for path in CORE_ROOT.glob("*.py"):
        text = path.read_text(encoding="utf-8-sig", errors="ignore")
        if "param_names = [" in text and "CALIBRATION_WORKFLOW_STAGED" in text:
            spec = importlib.util.spec_from_file_location("hbv_cryo_calibration_core_for_check", path)
            if spec is None or spec.loader is None:
                raise RuntimeError(f"无法加载率定核心：{path}")
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            return module
    raise FileNotFoundError("未找到包含 staged_calibration_v1 的率定核心脚本。")


def check_staged_metadata_template() -> dict[str, Any]:
    core = load_calibration_core()
    core.configure_time_step()
    seed = core.default_test_vector()
    base_bounds = core.validate_search_bounds(core.PARAM_BOUNDS)
    phase_records: list[dict[str, Any]] = []
    current_seed = seed
    for index, phase in enumerate(core.staged_calibration_phase_definitions(), start=1):
        bounds, fixed_parameters, fixed_values = core.build_staged_phase_bounds(
            base_bounds,
            current_seed,
            phase["released_parameters"],
        )
        assert len(bounds) == len(core.param_names)
        assert phase["released_parameters"], f"phase {phase['name']} missing released parameters"
        assert fixed_parameters, f"phase {phase['name']} missing fixed parameters"
        record = {
            "phase_index": index,
            "name": phase["name"],
            "released_parameters": list(phase["released_parameters"]),
            "locked_parameters": list(fixed_parameters),
            "fixed_parameters": list(fixed_parameters),
            "fixed_parameter_values": dict(fixed_values),
            "seed_from_previous_phase": index > 1,
            "seed_source": "previous_phase_best" if index > 1 else "initial_params_or_default",
            "best_objective": round(0.30 - index * 0.01, 6),
            "score_summary": {"objective_value": round(0.30 - index * 0.01, 6), "nse_cal": 0.70 + index * 0.01},
        }
        phase_records.append(record)
        current_seed = seed

    metadata = core.build_staged_calibration_metadata(phase_records, "glacier_refinement")
    assert metadata["calibration_workflow"] == "staged_calibration_v1"
    assert metadata["objective_family"] == "daily_unified_professional_v1"
    phases = metadata["calibration_phases"]
    assert [item["name"] for item in phases] == ["hydrologic_skeleton", "snow_process", "glacier_refinement"]
    for item in phases:
        assert item["released_parameters"], f"{item['name']} missing released_parameters"
        assert item["fixed_parameters"], f"{item['name']} missing fixed_parameters"
        assert "seed_from_previous_phase" in item, f"{item['name']} missing seed flag"
        assert item["best_objective"] is not None, f"{item['name']} missing best objective"
        assert item["score_summary"], f"{item['name']} missing score_summary"
    assert phases[0]["seed_from_previous_phase"] is False
    assert phases[1]["seed_from_previous_phase"] is True
    assert phases[2]["seed_from_previous_phase"] is True
    assert "flow_guard" in metadata.get("active_objective_guards", [])
    assert "peak_source_guard" in metadata.get("active_objective_guards", [])
    assert "recession_takeover_diagnostic" in metadata.get("active_objective_guards", [])
    return {
        "calibration_workflow": metadata["calibration_workflow"],
        "phase_names": [item["name"] for item in phases],
        "phase_release_counts": {item["name"]: len(item["released_parameters"]) for item in phases},
        "phase_fixed_counts": {item["name"]: len(item["fixed_parameters"]) for item in phases},
    }


def check_legacy_metadata_compatibility(limit: int = 5) -> dict[str, Any]:
    demo_root = WORKSPACE_ROOT / "HBVStudio_Demo"
    import studio_service  # noqa: E402

    synthetic_multi = {
        "run_id": "synthetic_weighted_multi_criteria",
        "run_time": "2026-04-27 00:00:00",
        "optimization": {"objective_mode": "weighted_multi_criteria"},
        "metrics": {"calibration": {"nse": 0.1, "pbias": 5.0}, "validation": {"nse": 0.1, "pbias": 5.0}},
        "objective_terms": {},
        "diagnostics": {},
    }
    synthetic_run_path = REPO_ROOT
    synthetic_metadata, synthetic_config = studio_service.normalize_run_metadata(synthetic_multi, run_path=synthetic_run_path)
    synthetic_summary = studio_service._build_run_summary(
        synthetic_run_path,
        synthetic_metadata,
        synthetic_config,
    )
    assert synthetic_summary.get("objective_family") == "weighted_multi_criteria"

    if not demo_root.exists():
        return {"checked": 0, "synthetic_weighted_multi_criteria": True, "skipped": "HBVStudio_Demo not found"}

    checked = 0
    objective_families: set[str] = set()
    for metadata_path in sorted(demo_root.rglob("metadata.json")):
        run_dir = metadata_path.parent
        if not (run_dir / "simulation.csv").exists():
            continue
        raw = json.loads(metadata_path.read_text(encoding="utf-8"))
        metadata, resolved_config = studio_service.normalize_run_metadata(raw, run_path=run_dir)
        summary = studio_service._build_run_summary(run_dir, metadata, resolved_config)
        family = str(summary.get("objective_family") or "").strip()
        if family:
            objective_families.add(family)
        assert summary.get("path"), "run summary missing path"
        assert family in {"weighted_daily_universal", "weighted_multi_criteria", "daily_unified_professional_v1", ""}
        checked += 1
        if checked >= limit:
            break
    return {
        "checked": checked,
        "objective_families": sorted(objective_families),
        "synthetic_weighted_multi_criteria": True,
    }


def check_product_boundary() -> dict[str, Any]:
    index_html = (STUDIO_ROOT / "web" / "index.html").read_text(encoding="utf-8-sig")
    app_js = (STUDIO_ROOT / "web" / "app.js").read_text(encoding="utf-8-sig")
    marker = 'id="task-objective-mode"'
    start = index_html.index(marker)
    end = index_html.index("</select>", start)
    objective_block = index_html[start:end]
    assert objective_block.count("<option") == 1
    assert 'value="daily_unified_professional_v1"' in objective_block
    forbidden = [
        "bm02_final_micro_tuning",
        "bm02_local_signature_search",
        "bm02_peak_source_and_targeted_search",
        "benchmark_acceptance_runner",
        "check_staged_calibration_smoke_run",
        "check_staged_calibration_metadata",
        "check_peak_recession_diagnostics",
        "studio_ui_acceptance",
        "scientific benchmark",
        "frozen PASS",
    ]
    web_text = index_html + "\n" + app_js
    hits = [item for item in forbidden if item in web_text]
    assert not hits, f"product web exposes forbidden internals: {hits}"

    product_suffixes = {".py", ".js", ".html", ".css", ".json"}
    hardcoded_path_markers = [
        "memories\\studio_acceptance",
        "memories/studio_acceptance",
        "memories\\staged_calibration_smoke",
        "memories/staged_calibration_smoke",
    ]
    hardcoded_hits: list[str] = []
    for root in (STUDIO_ROOT, CORE_ROOT):
        for path in root.rglob("*"):
            if not path.is_file() or path.suffix.lower() not in product_suffixes:
                continue
            text = path.read_text(encoding="utf-8-sig", errors="ignore")
            for marker in hardcoded_path_markers:
                if marker in text:
                    hardcoded_hits.append(str(path.relative_to(REPO_ROOT)))
                    break
    assert not hardcoded_hits, f"product code contains acceptance temp paths: {hardcoded_hits}"

    return {
        "objective_selector_options": 1,
        "bm02_scripts_exposed": False,
        "dev_tools_exposed_in_web": False,
        "hardcoded_acceptance_paths": False,
    }


def check_profile_runner_workflow_resolution() -> dict[str, Any]:
    import profile_runner  # noqa: E402

    workflow_key = "\u7387\u5b9a\u6d41\u7a0b"
    assert profile_runner.resolve_calibration_workflow({}, None, "daily") == "single_pass"
    assert profile_runner.resolve_calibration_workflow({}, None, "hourly") == "single_pass"
    assert profile_runner.resolve_calibration_workflow({workflow_key: "single_pass"}, None, "daily") == "single_pass"
    assert (
        profile_runner.resolve_calibration_workflow({workflow_key: "staged_calibration_v1"}, None, "daily")
        == "staged_calibration_v1"
    )
    assert profile_runner.calibration_workflow_status("single_pass") == "default_production"
    assert profile_runner.calibration_workflow_status("staged_calibration_v1") == "experimental"
    return {"daily_default": "single_pass", "hourly_default": "single_pass", "staged_status": "experimental"}


def main() -> None:
    result = {
        "staged_metadata": check_staged_metadata_template(),
        "workflow_resolution": check_profile_runner_workflow_resolution(),
        "legacy_metadata": check_legacy_metadata_compatibility(),
        "product_boundary": check_product_boundary(),
    }
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
