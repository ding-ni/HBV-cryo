#!/usr/bin/env python
# -*- coding: utf-8 -*-
from __future__ import annotations

import argparse
import importlib.util
import sys
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[1]
STUDIO_SERVICE_PATH = PROJECT_ROOT / "HBV-Studio" / "studio_service.py"


def _load_studio_service() -> Any:
    spec = importlib.util.spec_from_file_location("hbvstudio_studio_service_dev", STUDIO_SERVICE_PATH)
    if spec is None or spec.loader is None:
        raise ImportError(f"Cannot load studio_service.py from {STUDIO_SERVICE_PATH}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


svc = _load_studio_service()


def build_internal_replay_diff_report(
    source_run_path_raw: str,
    replay_run_path_raw: str,
    *,
    output_path_raw: str | None = None,
) -> dict[str, Any]:
    source_run = svc.resolve_any_path(source_run_path_raw, must_exist=True)
    replay_run = svc.resolve_any_path(replay_run_path_raw, must_exist=True)
    source_metadata = svc.read_json_file(source_run / "metadata.json")
    replay_metadata = svc.read_json_file(replay_run / "metadata.json")
    _, resolved_source_config = svc.normalize_run_metadata(source_metadata, run_path=source_run)
    _, resolved_replay_config = svc.normalize_run_metadata(replay_metadata, run_path=replay_run)

    source_time = dict(source_metadata.get("time_config", {}) or {})
    replay_time = dict(replay_metadata.get("time_config", {}) or {})
    source_optional = dict(source_metadata.get("optional_modules", {}) or {})
    replay_optional = dict(replay_metadata.get("optional_modules", {}) or {})
    source_glacier = dict(source_optional.get("glacier", {}) or {})
    replay_glacier = dict(replay_optional.get("glacier", {}) or {})

    source_metrics = svc._read_run_metrics_snapshot(source_run)
    replay_metrics = svc._read_run_metrics_snapshot(replay_run)
    process_terms = dict((replay_metadata.get("objective_terms", {}) or {}).get("process_signatures", {}) or {})
    replay_signatures = {
        "peak_timing_error_days": svc.safe_float(dict(process_terms.get("peak_timing", {}) or {}).get("peak_timing_error_days")),
        "peak_magnitude_log_error": svc.safe_float(dict(process_terms.get("peak_magnitude_bias", {}) or {}).get("peak_magnitude_log_error")),
        "recession_slope_log_error": svc.safe_float(dict(process_terms.get("recession_slope", {}) or {}).get("recession_slope_log_error")),
    }
    cryo_report = dict((replay_metadata.get("diagnostics", {}) or {}).get("cryo_timing_report", {}) or {})
    replay_cryo = {
        "snow_to_ice_centroid_lag_days": svc.safe_float(cryo_report.get("lag_days")),
    }

    source_csv = svc._run_csv_date_bounds(source_run)
    replay_csv = svc._run_csv_date_bounds(replay_run)
    source_preview = svc._run_csv_preview(source_run)
    replay_preview = svc._run_csv_preview(replay_run)

    classification = {
        "metadata_structure_fixed": bool(
            not source_metadata.get("objective_family")
            and replay_metadata.get("objective_family") == "daily_unified_professional_v1"
            and dict(replay_metadata.get("hard_checks", {}) or {}).get("status") == "pass"
        ),
        "workspace_resolution_drift": bool(
            str(source_metadata.get("workspace_config", "") or "").strip().startswith("__GUI_ROOT__/")
            and resolved_source_config is not None
            and "HBV-cryo\\HBV-Studio\\workspaces" in str(resolved_source_config)
        ),
        "time_window_changed": bool(
            source_csv.get("first_date") != replay_csv.get("first_date")
            or source_csv.get("last_date") != replay_csv.get("last_date")
            or source_csv.get("row_count") != replay_csv.get("row_count")
            or str(source_time.get("calib_start", "") or "") != str(replay_time.get("calib_start", "") or "")
        ),
        "glacier_chain_changed": bool(
            bool(source_glacier.get("enabled")) != bool(replay_glacier.get("enabled"))
        ),
    }

    if classification["time_window_changed"] or classification["glacier_chain_changed"] or classification["workspace_resolution_drift"]:
        overall_judgement = "同参数前向输出已变"
    elif classification["metadata_structure_fixed"]:
        overall_judgement = "旧 metadata 缺失已修复，但过程门槛仍未通过"
    else:
        overall_judgement = "评分口径漂移待进一步核对"

    attributions = {
        "NSE_cal": "前向输出变化" if abs((replay_metrics["nse_cal"] or 0.0) - (source_metrics["nse_cal"] or 0.0)) > 1e-6 else "基本一致",
        "NSE_val": "前向输出变化" if abs((replay_metrics["nse_val"] or 0.0) - (source_metrics["nse_val"] or 0.0)) > 1e-6 else "基本一致",
        "KGE_val": "前向输出变化" if abs((replay_metrics["kge_val"] or 0.0) - (source_metrics["kge_val"] or 0.0)) > 1e-6 else "基本一致",
        "PBIAS_val": "前向输出变化" if abs((replay_metrics["pbias_val"] or 0.0) - (source_metrics["pbias_val"] or 0.0)) > 1e-6 else "基本一致",
        "peak_timing_error_days": "过程线建立在当前回放 hydrograph 上计算；旧参考 run 无同字段",
        "peak_magnitude_log_error": "过程线建立在当前回放 hydrograph 上计算；旧参考 run 无同字段",
        "recession_slope_log_error": "过程线建立在当前回放 hydrograph 上计算；旧参考 run 无同字段",
        "snow_to_ice_centroid_lag_days": "cryo_timing 建立在当前回放 hydrograph 上计算；旧参考 run 无同字段",
    }

    report = {
        "source_run_path": str(source_run.resolve(strict=False)),
        "replay_run_path": str(replay_run.resolve(strict=False)),
        "source_workspace_config_raw": source_metadata.get("workspace_config"),
        "source_workspace_config_resolved_now": str(resolved_source_config) if resolved_source_config is not None else None,
        "replay_workspace_config_raw": replay_metadata.get("workspace_config"),
        "replay_workspace_config_resolved_now": str(resolved_replay_config) if resolved_replay_config is not None else None,
        "source_time_config": source_time,
        "replay_time_config": replay_time,
        "source_csv_window": source_csv,
        "replay_csv_window": replay_csv,
        "source_csv_preview": source_preview,
        "replay_csv_preview": replay_preview,
        "flow_compare": {
            "source_reference_metrics": source_metrics,
            "replay_metrics": replay_metrics,
            "delta": {
                key: (
                    None
                    if source_metrics.get(key) is None or replay_metrics.get(key) is None
                    else float(replay_metrics[key] - source_metrics[key])
                )
                for key in ("nse_cal", "nse_val", "kge_val", "pbias_val")
            },
        },
        "process_signature_compare": {
            "source_reference_metrics": {
                "peak_timing_error_days": None,
                "peak_magnitude_log_error": None,
                "recession_slope_log_error": None,
            },
            "replay_metrics": replay_signatures,
        },
        "cryo_compare": {
            "source_reference_metrics": {
                "snow_to_ice_centroid_lag_days": None,
            },
            "replay_metrics": replay_cryo,
        },
        "classification": {
            **classification,
            "overall_judgement": overall_judgement,
        },
        "attribution": attributions,
    }

    if output_path_raw:
        output_path = svc.resolve_any_path(output_path_raw, must_exist=False)
    else:
        output_path = (PROJECT_ROOT / "dev_tools" / "internal_replay_diff_report.json").resolve(strict=False)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(svc.json_dumps_safe(report, indent=2), encoding="utf-8")
    report["report_path"] = str(output_path)
    return report


def build_process_signature_alignment_report(
    run_path_raw: str,
    *,
    output_path_raw: str | None = None,
) -> dict[str, Any]:
    run_path = svc.resolve_any_path(run_path_raw, must_exist=True)
    metadata = svc.read_json_file(run_path / "metadata.json")
    simulation_path = run_path / "simulation.csv"
    if not simulation_path.exists():
        raise FileNotFoundError("结果目录缺少 simulation.csv。")

    cryo_root = (PROJECT_ROOT / "HBV-Cryo").resolve(strict=False)
    cryo_root_str = str(cryo_root)
    if cryo_root_str not in sys.path:
        sys.path.insert(0, cryo_root_str)
    import daily_unified_objective  # type: ignore

    frame = svc.pd.read_csv(simulation_path)
    if "date" not in frame.columns or "q_obs" not in frame.columns or "q_sim" not in frame.columns:
        raise ValueError("simulation.csv 缺少过程签名诊断所需字段。")
    dates = svc.pd.DatetimeIndex(svc.pd.to_datetime(frame["date"]))
    q_obs = svc.pd.to_numeric(frame["q_obs"], errors="coerce").to_numpy(dtype=float)
    q_sim = svc.pd.to_numeric(frame["q_sim"], errors="coerce").to_numpy(dtype=float)

    time_config = dict(metadata.get("time_config", {}) or {})
    calib_start = svc.pd.Timestamp(str(time_config.get("calib_start", "") or "1900-01-01"))
    calib_end = svc.pd.Timestamp(str(time_config.get("calib_end", "") or "1900-01-01"))
    calib_mask = svc.np.asarray((dates >= calib_start) & (dates <= calib_end), dtype=bool)
    process_terms = dict((metadata.get("objective_terms", {}) or {}).get("process_signatures", {}) or {})
    alignment = daily_unified_objective.build_process_signature_alignment_debug_report(
        dates,
        q_obs,
        q_sim,
        calib_mask,
        existing_terms=process_terms,
    )

    report = {
        "run_path": str(run_path.resolve(strict=False)),
        "workspace_config": metadata.get("workspace_config"),
        "objective_family": metadata.get("objective_family"),
        "project_object_type": metadata.get("project_object_type"),
        "time_config": time_config,
        "signature_alignment": alignment,
    }
    if output_path_raw:
        output_path = svc.resolve_any_path(output_path_raw, must_exist=False)
    else:
        output_path = (PROJECT_ROOT / "dev_tools" / "process_signature_alignment_report.json").resolve(strict=False)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(svc.json_dumps_safe(report, indent=2), encoding="utf-8")
    report["report_path"] = str(output_path)
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description="Build development-only HBVStudio validation reports.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    replay = subparsers.add_parser("replay-diff")
    replay.add_argument("source_run")
    replay.add_argument("replay_run")
    replay.add_argument("--output")

    signature = subparsers.add_parser("signature-alignment")
    signature.add_argument("run")
    signature.add_argument("--output")

    args = parser.parse_args()
    if args.command == "replay-diff":
        report = build_internal_replay_diff_report(args.source_run, args.replay_run, output_path_raw=args.output)
    else:
        report = build_process_signature_alignment_report(args.run, output_path_raw=args.output)
    print(svc.json_dumps_safe(report, indent=2))


if __name__ == "__main__":
    main()
