import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

import numpy as np


STUDIO_DIR = Path(__file__).resolve().parents[1]
if str(STUDIO_DIR) not in sys.path:
    sys.path.insert(0, str(STUDIO_DIR))

import profile_runner  # noqa: E402

from services.runs import (  # noqa: E402
    RunCalibrationTaskContext,
    RunDiscoveryContext,
    RunMetadataCompatibilityContext,
    RunMetadataObjectTypeContext,
    RunReplayConfigContext,
    RunSourceReferenceContext,
    RunSummaryContext,
    RunWorkspaceNameContext,
    apply_run_replay_config_overrides,
    build_run_summary,
    build_calibration_task_result,
    capture_forward_observation_state,
    default_run_export_fields,
    discover_run_entries,
    discover_runtime_roots,
    display_run_title,
    finalize_run_metadata_sections,
    first_existing_path,
    has_parameter_bounds,
    has_custom_result_title,
    apply_effective_objective_mode,
    infer_effective_objective_mode,
    is_studio_editable_metadata,
    iter_run_parent_dirs,
    load_run_series_map,
    metadata_boundary_enabled,
    metadata_initial_state_override,
    normalize_metadata_object_type,
    normalize_optimization_metadata,
    normalize_result_title,
    optimization_stage_counter,
    infer_selected_result_stage,
    pick_latest_run_path,
    prepare_run_metadata_sections,
    read_sampled_csv_rows,
    read_run_metrics_snapshot,
    recorded_objective_family,
    restore_forward_boundary_series,
    restore_forward_observation_state,
    restore_forward_observed_series,
    resolve_metadata_object_type,
    resolve_run_objective_metadata,
    resolve_run_workspace_config,
    resolve_source_run_reference,
    rebase_run_data_cache_paths,
    run_precip_dir_candidates,
    run_csv_date_bounds,
    run_csv_preview,
    run_parameter_context,
    run_kind_from_metadata,
    run_kind_label,
    run_update_timestamps,
    snapshot_run_paths,
    source_run_meta,
    synthesized_objective_profile,
    synthesized_parameter_profile,
    sync_objective_profile_metadata,
    sync_run_boundary_condition_path,
    sync_run_config_profile_metadata,
    sync_run_data_source_paths,
    sync_source_run_reference,
    workspace_name_for_summary,
)


class RunIdentityServiceTests(unittest.TestCase):
    def _metadata_object_type_context(self, detect=None) -> RunMetadataObjectTypeContext:
        return RunMetadataObjectTypeContext(detect_object_type=detect or (lambda config: ""))

    def _source_reference_context(
        self,
        *,
        resolve=None,
        replace=None,
        roots=None,
        parents=None,
    ) -> RunSourceReferenceContext:
        return RunSourceReferenceContext(
            resolve_any_path=resolve or (lambda raw, **kwargs: Path(raw)),
            replace_placeholders=replace or (lambda value, **kwargs: value),
            discover_runtime_roots=roots or (lambda: []),
            iter_run_parent_dirs=parents or (lambda root: []),
        )

    def _metadata_compatibility_context(self, *, hints=None, resolve=None) -> RunMetadataCompatibilityContext:
        return RunMetadataCompatibilityContext(
            workspace_roots_hint_from_metadata=hints or (lambda metadata: (None, None)),
            resolve_workspace_config_reference=resolve or (lambda raw, **kwargs: None),
        )

    def _workspace_name_context(self, *, hints=None, resolve=None, read_config=None) -> RunWorkspaceNameContext:
        return RunWorkspaceNameContext(
            workspace_roots_hint_from_metadata=hints or (lambda metadata: (None, None)),
            resolve_workspace_config_reference=resolve or (lambda raw, **kwargs: None),
            read_runtime_config=read_config or (lambda path: {}),
        )

    def test_run_kind_and_labels_follow_result_metadata(self) -> None:
        self.assertEqual(run_kind_from_metadata({"forecast_result": {"enabled": True}}), "forecast_restart")
        self.assertEqual(run_kind_from_metadata({"manual_result": {"enabled": True}}), "manual_result")
        self.assertEqual(run_kind_from_metadata({"starter_result": {"enabled": True}}), "manual_starter")
        self.assertEqual(run_kind_from_metadata({}, studio_compatible=True), "calibration")
        self.assertEqual(run_kind_from_metadata({}), "legacy")
        self.assertEqual(run_kind_label("manual_result"), "手调结果")
        self.assertEqual(run_kind_label("unknown"), "结果")

    def test_run_discovery_finds_runtime_workspace_and_complete_runs(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            runtime_root = root / "runtime"
            workspace_root = runtime_root / "workspace_a"
            direct_run = workspace_root / "results" / "runs" / "run_a"
            nested_run = workspace_root / "results" / "nested" / "runs" / "run_b"
            incomplete_run = workspace_root / "results" / "runs" / "missing_simulation"
            for run_dir in (direct_run, nested_run):
                run_dir.mkdir(parents=True)
                (run_dir / "metadata.json").write_text("{}", encoding="utf-8")
                (run_dir / "simulation.csv").write_text("date,q_sim\n2026-06-01,1\n", encoding="utf-8")
            incomplete_run.mkdir(parents=True)
            (incomplete_run / "metadata.json").write_text("{}", encoding="utf-8")

            def workspace_path_candidates(base: Path, zh_names: tuple[str, ...], en_names: tuple[str, ...]) -> list[Path]:
                return [Path(base) / name for name in (*zh_names, *en_names)]

            def safe_iterdir(path: Path) -> list[Path]:
                try:
                    return sorted(Path(path).iterdir(), key=lambda item: item.name)
                except (OSError, FileNotFoundError):
                    return []

            context = RunDiscoveryContext(
                project_runtime_dir=runtime_root,
                list_workspaces=lambda: [
                    {"workspace_root": str(workspace_root)},
                    {"workspace_root": str(workspace_root)},
                    {"workspace_root": str(root / "missing")},
                ],
                workspace_path_candidates=workspace_path_candidates,
                safe_iterdir=safe_iterdir,
            )

            roots = discover_runtime_roots(context)
            parents = iter_run_parent_dirs(workspace_root, context)
            entries = discover_run_entries(context)

        self.assertEqual(roots, [runtime_root.resolve(), workspace_root.resolve()])
        self.assertEqual({path.name for path in parents}, {"runs"})
        self.assertEqual({path.parent.name for path in parents}, {"results", "nested"})
        self.assertEqual({path.name for _, path in entries}, {"run_a", "run_b"})
        self.assertNotIn("missing_simulation", {path.name for _, path in entries})
        self.assertTrue(all(len(signature) == 5 for signature, _ in entries))

    def test_snapshot_run_paths_collects_list_run_paths(self) -> None:
        self.assertEqual(
            snapshot_run_paths(lambda: [{"path": "runs/a"}, {"path": "runs/b"}]),
            {"runs/a", "runs/b"},
        )

    def test_run_update_timestamps_uses_newest_run_file_timestamp(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            run_dir = Path(tmp) / "run"
            run_dir.mkdir()
            metadata_path = run_dir / "metadata.json"
            simulation_path = run_dir / "simulation.csv"
            metadata_path.write_text("{}", encoding="utf-8")
            simulation_path.write_text("date,q_sim\n2026-06-01,1\n", encoding="utf-8")
            os.utime(run_dir, ns=(1_000_000_000, 1_000_000_000))
            os.utime(metadata_path, ns=(2_000_000_000, 2_000_000_000))
            os.utime(simulation_path, ns=(3_000_000_000, 3_000_000_000))

            updated_at, updated_at_ns = run_update_timestamps(run_dir)

        self.assertEqual(updated_at, 3.0)
        self.assertEqual(updated_at_ns, 3_000_000_000)

    def test_result_titles_distinguish_custom_names_from_system_names(self) -> None:
        run_dir = Path("C:/runs/run_20260602_100000")

        self.assertEqual(normalize_result_title("  我的   结果  "), "我的 结果")
        self.assertFalse(has_custom_result_title(run_dir, "run_20260602_100000"))
        self.assertFalse(has_custom_result_title(run_dir, "手调结果"))
        self.assertTrue(has_custom_result_title(run_dir, "沱沱河一号方案"))

        custom = display_run_title(
            run_dir,
            {"result_title": "沱沱河一号方案", "manual_result": {"enabled": True}, "run_time": "2026-06-02 10:00:00"},
            "沱沱河",
            studio_compatible=True,
        )
        self.assertEqual(custom["display_name"], "沱沱河一号方案")
        self.assertEqual(custom["display_subtitle"], "沱沱河 · 手调结果 · 2026-06-02 10:00:00")
        self.assertTrue(custom["has_custom_title"])
        self.assertEqual(custom["run_type"], "manual_result")

        generated = display_run_title(
            run_dir,
            {"result_title": "手调起点", "starter_result": {"enabled": True}},
            "沱沱河",
            studio_compatible=True,
        )
        self.assertEqual(generated["display_name"], "沱沱河 · 手调起点")
        self.assertEqual(generated["display_subtitle"], "目录名：run_20260602_100000")
        self.assertFalse(generated["has_custom_title"])

    def test_source_run_meta_prefers_replay_then_manual_then_optimization(self) -> None:
        source_path, source_name = source_run_meta(
            {
                "manual_result": {"source_run_path": "C:/runs/manual_source"},
                "optimization": {"source_run_path": "C:/runs/optimization_source"},
                "replay_context": {"source_run_path": "{ROOT}/replay_source"},
            },
            lambda value: str(value).replace("{ROOT}", "D:/resolved"),
        )
        self.assertEqual(source_path, "{ROOT}/replay_source")
        self.assertEqual(source_name, "replay_source")

        explicit_path, explicit_name = source_run_meta({
            "manual_result": {"source_run_path": "C:/runs/manual_source", "source_run_name": "人工命名源结果"},
        })
        self.assertEqual(explicit_path, "C:/runs/manual_source")
        self.assertEqual(explicit_name, "人工命名源结果")

    def test_resolve_source_run_reference_returns_direct_run_dir(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            run_dir = Path(temp_dir) / "run_a"
            run_dir.mkdir()
            (run_dir / "metadata.json").write_text("{}", encoding="utf-8")
            (run_dir / "simulation.csv").write_text("date,q_sim\n2026-06-01,1\n", encoding="utf-8")

            resolved = resolve_source_run_reference(str(run_dir), "", self._source_reference_context())

        self.assertEqual(resolved, str(run_dir.resolve(strict=False)))

    def test_resolve_source_run_reference_finds_named_run_under_workspace(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace_dir = Path(temp_dir) / "workspace"
            run_dir = workspace_dir / "results" / "daily" / "runs" / "run_named"
            run_dir.mkdir(parents=True)
            (run_dir / "metadata.json").write_text("{}", encoding="utf-8")
            (run_dir / "simulation.csv").write_text("date,q_sim\n2026-06-01,1\n", encoding="utf-8")

            resolved = resolve_source_run_reference(
                str(workspace_dir),
                "run_named",
                self._source_reference_context(),
            )

        self.assertEqual(resolved, str(run_dir.resolve(strict=False)))

    def test_resolve_source_run_reference_searches_runtime_parent_dirs(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir) / "runtime_workspace"
            parent = root / "results" / "hourly" / "runs"
            run_dir = parent / "run_from_root"
            run_dir.mkdir(parents=True)
            (run_dir / "metadata.json").write_text("{}", encoding="utf-8")
            (run_dir / "simulation.csv").write_text("date,q_sim\n2026-06-01,1\n", encoding="utf-8")
            context = self._source_reference_context(
                roots=lambda: [root],
                parents=lambda runtime_root: [parent],
            )

            resolved = resolve_source_run_reference("old/path/run_from_root", "", context)

        self.assertEqual(resolved, str(run_dir.resolve(strict=False)))

    def test_resolve_source_run_reference_returns_raw_path_when_resolution_fails(self) -> None:
        def fail_resolve(*args, **kwargs):
            raise ValueError("bad path")

        resolved = resolve_source_run_reference("bad/raw/path", "run_name", self._source_reference_context(resolve=fail_resolve))

        self.assertEqual(resolved, "bad/raw/path")

    def test_first_existing_path_prefers_existing_unique_candidate(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            missing = root / "missing"
            existing = root / "existing"
            existing.mkdir()

            resolved = first_existing_path([missing, missing, existing])

        self.assertEqual(resolved, existing.resolve(strict=False))

    def test_first_existing_path_falls_back_to_first_unique_candidate(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            first = root / "first_missing"
            second = root / "second_missing"

            resolved = first_existing_path([first, first, second])

        self.assertEqual(resolved, first.resolve(strict=False))
        self.assertIsNone(first_existing_path([]))

    def test_metadata_object_type_rules_normalize_explicit_values(self) -> None:
        self.assertEqual(normalize_metadata_object_type("regression_test"), "regression_validation")
        self.assertEqual(normalize_metadata_object_type(" interbasin_with_boundary "), "interbasin_with_boundary")
        self.assertEqual(normalize_metadata_object_type("full_upstream_basin"), "full_upstream_basin")
        self.assertEqual(normalize_metadata_object_type("unknown"), "")

    def test_metadata_boundary_enabled_prefers_boolean_flags_then_files(self) -> None:
        self.assertTrue(metadata_boundary_enabled({"optional_modules": {"boundary_inflow": {"enabled": True}}}))
        self.assertFalse(metadata_boundary_enabled({"boundary_condition": {"enabled": False, "boundary_inflow_file": "b.csv"}}))
        self.assertTrue(metadata_boundary_enabled({"optional_modules": {"boundary_inflow": {"file": "b.csv"}}}))
        self.assertIsNone(metadata_boundary_enabled({}))

    def test_resolve_metadata_object_type_uses_metadata_boundary_and_config(self) -> None:
        self.assertEqual(
            resolve_metadata_object_type({"project_object_type": "regression_test"}),
            "regression_validation",
        )
        self.assertEqual(
            resolve_metadata_object_type({"boundary_condition": {"boundary_inflow_file": "b.csv"}}),
            "interbasin_with_boundary",
        )
        self.assertEqual(
            resolve_metadata_object_type({"optional_modules": {"boundary_inflow": {"enabled": False}}}),
            "full_upstream_basin",
        )
        self.assertEqual(
            resolve_metadata_object_type(
                {},
                {"dummy": True},
                self._metadata_object_type_context(lambda config: "full_upstream_basin"),
            ),
            "full_upstream_basin",
        )

    def test_optimization_stage_counter_clamps_invalid_values(self) -> None:
        self.assertEqual(optimization_stage_counter("5"), 5)
        self.assertEqual(optimization_stage_counter("-2"), 0)
        self.assertEqual(optimization_stage_counter("bad"), 0)
        self.assertEqual(optimization_stage_counter(None), 0)

    def test_infer_selected_result_stage_uses_explicit_stage_stats_and_labels(self) -> None:
        self.assertEqual(infer_selected_result_stage({"selected_result_stage": "global"}, {}), "global")
        self.assertEqual(infer_selected_result_stage({}, {"refine": {"selected": True}}), "refine")
        self.assertEqual(infer_selected_result_stage({"selected_result_label": "\u5feb\u901f\u7b5b\u9009\u7ed3\u679c"}, {}), "mc")
        self.assertEqual(infer_selected_result_stage({"selected_result_label": "\u5dee\u5206\u8fdb\u5316\u7ed3\u679c"}, {}), "global")

    def test_normalize_optimization_metadata_marks_skipped_refine_and_totals(self) -> None:
        normalized = normalize_optimization_metadata(
            {
                "method": "mc_screen_de",
                "stage_stats": {
                    "mc": {"nit": 12},
                    "global": {"nfev": 30, "nit": 5, "selected": True},
                    "refine": {"skipped_reason": "flat objective"},
                },
            },
            effective_objective_mode="daily_unified_professional_v1",
            fallback_total_evaluations=18,
        )

        self.assertEqual(normalized["selected_result_stage"], "global")
        self.assertEqual(normalized["selected_result_label"], "\u7cbe\u7ec6\u641c\u7d22\u7ed3\u679c")
        self.assertEqual(normalized["method_label"], "\u5feb\u901f\u7b5b\u9009 + \u7cbe\u7ec6\u641c\u7d22\uff08\u5c40\u90e8\u7cbe\u4fee\u5df2\u8df3\u8fc7\uff09")
        self.assertEqual(normalized["selected_stage_evaluations"], 30)
        self.assertEqual(normalized["selected_stage_generations"], 5)
        self.assertEqual(normalized["total_evaluations"], 30)
        self.assertEqual(normalized["total_generations"], 5)
        self.assertEqual(normalized["total_progress_points"], 12)
        self.assertEqual(normalized["effective_objective_mode"], "daily_unified_professional_v1")
        self.assertTrue(normalized["stage_stats"]["mc"]["requested"])
        self.assertTrue(normalized["stage_stats"]["mc"]["executed"])
        self.assertTrue(normalized["stage_stats"]["global"]["selected"])
        self.assertTrue(normalized["stage_stats"]["refine"]["requested"])
        self.assertFalse(normalized["stage_stats"]["refine"]["executed"])

    def test_run_parameter_context_summarizes_source_result_for_forecast(self) -> None:
        run_dir = Path("C:/runs/source_run")
        metadata = {
            "workspace_config": "",
            "calibration_profile": "hourly",
            "effective_objective_mode": "daily_unified_professional_v1",
            "time_config": {"time_step_hours": 1},
            "initial_state": {"state_snapshot_time": "2026-06-02 08:00:00"},
            "data_sources": {
                "configured_precip_source": "era5",
                "prec_source": "cmfd",
                "runtime_prec_source": "custom_tif",
                "station_precip_mode": "station_only",
                "precipitation_mode": "basin_grid",
                "precipitation_strategy": "station_corrected",
                "glacier_mode": "binary_legacy",
            },
            "optional_modules": {"glacier": {"enabled": True}},
            "parameter_profile": {"bounds_profile": "hourly_step"},
            "optimized_params": {"TT": -1.0, "FC": 850.0},
        }

        context = run_parameter_context(
            run_dir,
            metadata,
            Path("C:/workspace/config.json"),
            "沱沱河",
            {"hourly_step": "小时尺度稳定范围"},
        )

        self.assertEqual(context["schema"], "run_parameter_context_v1")
        self.assertEqual(context["source_run_name"], "source_run")
        self.assertEqual(context["source_workspace"], "沱沱河")
        self.assertEqual(context["source_workspace_config"], "C:\\workspace\\config.json")
        self.assertEqual(context["calibration_profile"], "hourly")
        self.assertEqual(context["time_step_hours"], 1)
        self.assertEqual(context["objective_mode"], "daily_unified_professional_v1")
        self.assertEqual(context["prec_source"], "custom_tif")
        self.assertEqual(context["precipitation_strategy"], "station_corrected")
        self.assertEqual(context["glacier_mode"], "binary_legacy")
        self.assertTrue(context["glacier_enabled"])
        self.assertEqual(context["param_bounds_profile"], "hourly_step")
        self.assertEqual(context["param_bounds_profile_label"], "小时尺度稳定范围")
        self.assertEqual(context["state_snapshot_time"], "2026-06-02 08:00:00")
        self.assertEqual(context["parameter_count"], 2)

    def test_has_parameter_bounds_requires_two_value_bounds(self) -> None:
        self.assertFalse(has_parameter_bounds({}))
        self.assertFalse(has_parameter_bounds({"parameter_profile": {"bounds": {}}}))
        self.assertFalse(has_parameter_bounds({"parameter_profile": {"bounds": {"TT": [0]}}}))
        self.assertTrue(has_parameter_bounds({"parameter_profile": {"bounds": {"TT": [-2.0, 2.0]}}}))
        self.assertTrue(has_parameter_bounds({"parameter_profile": {"bounds": {"FC": (100.0, 1000.0)}}}))

    def test_synthesized_parameter_profile_uses_hourly_objective_notes_and_bounds(self) -> None:
        profile = synthesized_parameter_profile(profile_runner.PROFILE_HOURLY, profile_runner.OBJECTIVE_MODE_MULTI)

        self.assertEqual(profile["name"], profile_runner.PROFILE_HOURLY)
        self.assertEqual(profile["label"], profile_runner.PROFILE_LABELS[profile_runner.PROFILE_HOURLY])
        self.assertEqual(profile["bounds_profile"], profile_runner.PARAM_BOUNDS_PROFILE_HOURLY)
        self.assertEqual(profile["notes"][0], "\u5c0f\u65f6\u5c3a\u5ea6\u5f53\u524d\u542f\u7528\u7efc\u5408\u6c34\u6587\u8bc4\u4ef7\u53e3\u5f84\u3002")
        self.assertIn("K_MUSK", profile["bounds"])
        self.assertGreaterEqual(len(profile["bounds"]["K_MUSK"]), 2)

    def test_synthesized_parameter_profile_uses_daily_qtp_bounds(self) -> None:
        profile = synthesized_parameter_profile(profile_runner.PROFILE_DAILY, profile_runner.OBJECTIVE_MODE_MULTI)

        self.assertEqual(profile["name"], profile_runner.PROFILE_DAILY)
        self.assertEqual(profile["bounds_profile"], profile_runner.DEFAULT_DAILY_PARAM_BOUNDS_PROFILE)
        self.assertEqual(
            profile["bounds_profile_label"],
            profile_runner.PARAM_BOUNDS_PROFILE_LABELS[profile_runner.DEFAULT_DAILY_PARAM_BOUNDS_PROFILE],
        )
        self.assertTrue(profile["label"].startswith(profile_runner.PROFILE_LABELS[profile_runner.PROFILE_DAILY]))
        self.assertIn("CFMAX_low", profile["bounds"])

    def test_synthesized_objective_profile_preserves_recorded_fields_but_sets_type(self) -> None:
        profile = synthesized_objective_profile(
            profile_runner.PROFILE_DAILY,
            profile_runner.OBJECTIVE_MODE_MULTI,
            {
                "label": "\u5df2\u8bb0\u5f55\u76ee\u6807",
                "summary": "\u5386\u53f2\u8bf4\u660e",
                "weights": {"nse": 0.7, "pbias": 0.3},
                "notes": ["\u5df2\u8bb0\u5f55\u5907\u6ce8"],
            },
        )

        self.assertEqual(profile["type"], profile_runner.OBJECTIVE_MODE_MULTI)
        self.assertEqual(profile["label"], "\u5df2\u8bb0\u5f55\u76ee\u6807")
        self.assertEqual(profile["summary"], "\u5386\u53f2\u8bf4\u660e")
        self.assertEqual(profile["weights"], {"nse": 0.7, "pbias": 0.3})
        self.assertEqual(profile["notes"], ["\u5df2\u8bb0\u5f55\u5907\u6ce8"])

    def test_recorded_objective_family_uses_existing_metadata_priority(self) -> None:
        self.assertEqual(
            recorded_objective_family(
                {
                    "objective_family": "flood_event_calibration_v1",
                    "effective_objective_mode": profile_runner.OBJECTIVE_MODE_MULTI,
                    "objective_profile": {"type": profile_runner.OBJECTIVE_MODE_SINGLE},
                },
                {"objective_mode": "ignored"},
            ),
            "flood_event_calibration_v1",
        )
        self.assertEqual(
            recorded_objective_family(
                {"objective_profile": {"type": profile_runner.OBJECTIVE_MODE_SINGLE}},
                {},
            ),
            profile_runner.OBJECTIVE_MODE_SINGLE,
        )

    def test_prepare_run_metadata_sections_copies_sections_and_records_objective_family(self) -> None:
        metadata = {
            "data_sources": {"runtime_prec_source": "era5"},
            "boundary_condition": {"enabled": True},
            "optimization": {"effective_objective_mode": profile_runner.OBJECTIVE_MODE_MULTI},
            "manual_result": {"source_run_name": "manual"},
            "replay_context": {"source_run_path": "raw/path"},
            "data_cache": {"paths": {"simulation_csv": "C:/run/sim.csv"}, "version": 1},
        }

        sections = prepare_run_metadata_sections(metadata)

        self.assertEqual(metadata["recorded_objective_family"], profile_runner.OBJECTIVE_MODE_MULTI)
        self.assertEqual(sections.effective_objective_mode, profile_runner.OBJECTIVE_MODE_MULTI)
        self.assertEqual(sections.data_sources, {"runtime_prec_source": "era5"})
        self.assertIsNot(sections.data_sources, metadata["data_sources"])
        self.assertEqual(sections.boundary_condition, {"enabled": True})
        self.assertEqual(sections.manual_result, {"source_run_name": "manual"})
        self.assertEqual(sections.replay_context, {"source_run_path": "raw/path"})
        self.assertEqual(sections.cache, {"paths": {"simulation_csv": "C:/run/sim.csv"}, "version": 1})
        self.assertIsNot(sections.cache["paths"], metadata["data_cache"]["paths"])

    def test_prepare_run_metadata_sections_prefers_metadata_effective_mode(self) -> None:
        metadata = {
            "effective_objective_mode": profile_runner.OBJECTIVE_MODE_SINGLE.upper(),
            "optimization": {"effective_objective_mode": profile_runner.OBJECTIVE_MODE_MULTI},
        }

        sections = prepare_run_metadata_sections(metadata)

        self.assertEqual(sections.effective_objective_mode, profile_runner.OBJECTIVE_MODE_SINGLE)
        self.assertEqual(metadata["recorded_objective_family"], profile_runner.OBJECTIVE_MODE_SINGLE)

    def test_sync_objective_profile_metadata_copies_contract_fields(self) -> None:
        metadata = {
            "objective": {"label": "\u539f\u6807\u7b7e"},
            "objective_profile": {
                "type": profile_runner.OBJECTIVE_MODE_MULTI,
                "summary": "\u7efc\u5408\u8bf4\u660e",
                "formula": "NSE + PBIAS",
                "weights": {"nse": 0.8},
                "diagnostic_only_constraints": ["winter_ice"],
            },
        }

        sync_objective_profile_metadata(metadata)

        self.assertEqual(metadata["objective"]["label"], "\u539f\u6807\u7b7e")
        self.assertEqual(metadata["objective"]["type"], profile_runner.OBJECTIVE_MODE_MULTI)
        self.assertEqual(metadata["objective"]["summary"], "\u7efc\u5408\u8bf4\u660e")
        self.assertEqual(metadata["objective"]["formula"], "NSE + PBIAS")
        self.assertEqual(metadata["objective"]["weights"], {"nse": 0.8})
        self.assertEqual(metadata["objective"]["diagnostic_only_constraints"], ["winter_ice"])

    def test_sync_run_config_profile_metadata_fills_missing_profiles_and_preserves_existing_rate(self) -> None:
        metadata = {
            "rate_mode": "hourly",
            "objective": {"label": "\u5386\u53f2\u76ee\u6807"},
        }
        optimization = {}

        effective = sync_run_config_profile_metadata(
            metadata,
            optimization,
            profile=profile_runner.PROFILE_DAILY,
            objective_mode=profile_runner.OBJECTIVE_MODE_MULTI,
            workspace_label="\u6c71\u5730\u6d41\u57df",
            resolved_object_type="full_upstream_basin",
        )

        self.assertEqual(effective, profile_runner.OBJECTIVE_MODE_MULTI)
        self.assertEqual(metadata["calibration_profile"], profile_runner.PROFILE_DAILY)
        self.assertEqual(metadata["rate_mode"], "hourly")
        self.assertEqual(metadata["project_object_type"], "full_upstream_basin")
        self.assertEqual(metadata["workspace_label"], "\u6c71\u5730\u6d41\u57df")
        self.assertIn("bounds", metadata["parameter_profile"])
        self.assertEqual(metadata["objective_profile"]["type"], profile_runner.OBJECTIVE_MODE_MULTI)
        self.assertEqual(metadata["objective"]["type"], profile_runner.OBJECTIVE_MODE_MULTI)
        self.assertEqual(metadata["objective"]["label"], "\u5386\u53f2\u76ee\u6807")
        self.assertEqual(optimization["effective_objective_mode"], profile_runner.OBJECTIVE_MODE_MULTI)

    def test_sync_run_config_profile_metadata_keeps_existing_profile_payloads(self) -> None:
        parameter_profile = {"bounds": {"TT": [-2.0, 2.0]}}
        objective_profile = {"type": profile_runner.OBJECTIVE_MODE_SINGLE, "summary": "\u65e7\u6458\u8981"}
        metadata = {
            "calibration_profile": "hourly",
            "parameter_profile": parameter_profile,
            "objective_profile": objective_profile,
        }
        optimization = {}

        effective = sync_run_config_profile_metadata(
            metadata,
            optimization,
            profile=profile_runner.PROFILE_DAILY,
            objective_mode="",
            workspace_label="  \u73b0\u6709\u6d41\u57df  ",
        )

        self.assertEqual(effective, "")
        self.assertIs(metadata["parameter_profile"], parameter_profile)
        self.assertIs(metadata["objective_profile"], objective_profile)
        self.assertEqual(metadata["calibration_profile"], "hourly")
        self.assertEqual(metadata["rate_mode"], profile_runner.PROFILE_DAILY)
        self.assertEqual(metadata["workspace_label"], "\u73b0\u6709\u6d41\u57df")
        self.assertEqual(metadata["objective"]["type"], profile_runner.OBJECTIVE_MODE_SINGLE)
        self.assertNotIn("effective_objective_mode", optimization)

    def test_effective_objective_mode_helpers_normalize_and_apply_to_metadata(self) -> None:
        metadata = {
            "\u76ee\u6807\u51fd\u6570\u6a21\u5f0f": "nse",
            "objective_profile": {"type": ""},
            "objective": {},
        }
        optimization = {}

        mode = infer_effective_objective_mode(metadata, optimization)
        apply_effective_objective_mode(metadata, optimization, mode)

        self.assertEqual(mode, profile_runner.OBJECTIVE_MODE_SINGLE)
        self.assertEqual(metadata["effective_objective_mode"], profile_runner.OBJECTIVE_MODE_SINGLE)
        self.assertEqual(metadata["objective_profile"]["type"], profile_runner.OBJECTIVE_MODE_SINGLE)
        self.assertEqual(metadata["objective"]["type"], profile_runner.OBJECTIVE_MODE_SINGLE)
        self.assertEqual(optimization["effective_objective_mode"], profile_runner.OBJECTIVE_MODE_SINGLE)

    def test_resolve_run_objective_metadata_syncs_profile_and_object_type(self) -> None:
        metadata = {
            "objective": {"label": "\u65e7\u76ee\u6807"},
            "objective_profile": {
                "type": profile_runner.OBJECTIVE_MODE_MULTI,
                "summary": "\u7efc\u5408\u76ee\u6807",
                "weights": {"nse": 0.7, "pbias": 0.3},
            },
        }
        optimization = {}

        mode = resolve_run_objective_metadata(
            metadata,
            optimization,
            resolved_object_type="interbasin_with_boundary",
        )

        self.assertEqual(mode, profile_runner.OBJECTIVE_MODE_MULTI)
        self.assertEqual(metadata["project_object_type"], "interbasin_with_boundary")
        self.assertEqual(metadata["objective"]["label"], "\u65e7\u76ee\u6807")
        self.assertEqual(metadata["objective"]["type"], profile_runner.OBJECTIVE_MODE_MULTI)
        self.assertEqual(metadata["objective"]["summary"], "\u7efc\u5408\u76ee\u6807")
        self.assertEqual(metadata["objective"]["weights"], {"nse": 0.7, "pbias": 0.3})
        self.assertNotIn("effective_objective_mode", optimization)

    def test_resolve_run_objective_metadata_preserves_explicit_effective_mode(self) -> None:
        metadata = {
            "objective_profile": {"type": profile_runner.OBJECTIVE_MODE_MULTI},
            "objective": {},
        }
        optimization = {"objective_mode": profile_runner.OBJECTIVE_MODE_MULTI}

        mode = resolve_run_objective_metadata(
            metadata,
            optimization,
            effective_objective_mode=profile_runner.OBJECTIVE_MODE_SINGLE.upper(),
        )

        self.assertEqual(mode, profile_runner.OBJECTIVE_MODE_SINGLE)
        self.assertEqual(metadata["objective"]["type"], profile_runner.OBJECTIVE_MODE_MULTI)
        self.assertNotIn("effective_objective_mode", optimization)

    def test_sync_source_run_reference_updates_all_present_metadata_sections(self) -> None:
        replay_context = {}
        manual_result = {"source_run_path": "manual/raw", "source_run_name": "manual-run"}
        optimization = {"source_run_name": "opt-run"}

        source_run_path = sync_source_run_reference(
            replay_context,
            manual_result,
            optimization,
            lambda raw, name: f"C:/resolved/{name or Path(str(raw)).name}",
        )

        self.assertEqual(source_run_path, "C:/resolved/manual-run")
        self.assertEqual(replay_context["source_run_path"], "C:/resolved/manual-run")
        self.assertEqual(manual_result["source_run_path"], "C:/resolved/manual-run")
        self.assertEqual(optimization["source_run_path"], "C:/resolved/manual-run")

    def test_finalize_run_metadata_sections_writes_run_sections_and_normalizes_optimization(self) -> None:
        metadata = {"evaluations": 3, "objective_profile": {}, "objective": {}}
        data_sources = {"runtime_prec_source": "era5", "prec_dir": "C:/prec"}
        boundary_condition = {"enabled": True, "path": "C:/boundary.csv"}
        replay_context = {}
        manual_result = {"source_run_path": "manual/raw", "source_run_name": "manual-run"}
        optimization = {
            "method": "mc_only",
            "selected_result_stage": "mc",
            "source_run_name": "opt-run",
            "stage_stats": {"mc": {"nfev": 5, "nit": 2}},
        }
        cache = {"simulation": {"csv": "C:/run/simulation.csv"}}

        finalize_run_metadata_sections(
            metadata,
            data_sources=data_sources,
            boundary_condition=boundary_condition,
            replay_context=replay_context,
            manual_result=manual_result,
            optimization=optimization,
            cache=cache,
            effective_objective_mode=profile_runner.OBJECTIVE_MODE_SINGLE,
            resolve_source_run_reference=lambda raw, name: f"C:/resolved/{name or Path(str(raw)).name}",
        )

        self.assertIs(metadata["data_sources"], data_sources)
        self.assertIs(metadata["boundary_condition"], boundary_condition)
        self.assertEqual(metadata["replay_context"]["source_run_path"], "C:/resolved/manual-run")
        self.assertEqual(metadata["manual_result"]["source_run_path"], "C:/resolved/manual-run")
        self.assertEqual(metadata["objective_profile"]["type"], profile_runner.OBJECTIVE_MODE_SINGLE)
        self.assertEqual(metadata["objective"]["type"], profile_runner.OBJECTIVE_MODE_SINGLE)
        self.assertEqual(metadata["effective_objective_mode"], profile_runner.OBJECTIVE_MODE_SINGLE)
        self.assertEqual(metadata["optimization"]["source_run_path"], "C:/resolved/manual-run")
        self.assertEqual(metadata["optimization"]["effective_objective_mode"], profile_runner.OBJECTIVE_MODE_SINGLE)
        self.assertEqual(metadata["optimization"]["total_evaluations"], 5)
        self.assertEqual(metadata["evaluations"], 5)
        self.assertIs(metadata["data_cache"], cache)

    def test_finalize_run_metadata_sections_skips_empty_optional_sections(self) -> None:
        metadata = {}

        finalize_run_metadata_sections(
            metadata,
            data_sources={},
            boundary_condition={},
            replay_context={},
            manual_result={},
            optimization={},
            cache={},
            effective_objective_mode="",
            resolve_source_run_reference=lambda raw, name: "",
        )

        self.assertEqual(metadata, {})

    def test_run_precip_dir_candidates_follow_source_specific_order(self) -> None:
        paths = {
            "aligned_prec_era5_dir": "C:/era5/current",
            "aligned_prec_era5_base_dir": "C:/era5/base",
            "aligned_prec_custom_dir": "C:/custom/current",
            "aligned_prec_custom_base_dir": "C:/custom/base",
            "aligned_prec_cmfd_dir": "C:/cmfd/current",
            "aligned_prec_cmfd_base_dir": "C:/cmfd/base",
            "aligned_prec_dir": "C:/default/current",
            "aligned_prec_base_dir": "C:/default/base",
        }

        candidates = run_precip_dir_candidates(
            paths,
            "custom_tif",
            "relative/prec",
            "C:/effective/prec",
            lambda raw, **kwargs: Path("D:/resolved") / raw,
        )

        self.assertEqual([str(path).replace("\\", "/") for path in candidates], [
            "C:/custom/current",
            "C:/custom/base",
            "D:/resolved/relative/prec",
            "C:/effective/prec",
        ])

    def test_sync_run_data_source_paths_sets_configured_paths_and_optional_glacier_files(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            gis_dir = root / "gis"
            glacier_melt_dir = root / "glacier_melt"
            gis_dir.mkdir()
            glacier_melt_dir.mkdir()
            (gis_dir / "glacier_mask.tif").write_text("mask", encoding="utf-8")
            obs_path = root / "obs.csv"
            obs_path.write_text("date,q\n2026-06-01,1\n", encoding="utf-8")
            data_sources = {"glacier_melt_dir": "legacy", "glacier_mask": "legacy-mask"}
            paths = {
                "aligned_temp_dir": root / "temp",
                "aligned_evap_dir": root / "evap",
                "glacier_melt_dir": glacier_melt_dir,
                "gis_dir": gis_dir,
            }

            sync_run_data_source_paths(
                data_sources,
                paths,
                "cmfd",
                "era5",
                root / "prec",
                obs_path,
            )

            self.assertEqual(data_sources["prec_dir"], str(root / "prec"))
            self.assertEqual(data_sources["temp_dir"], str((root / "temp").resolve(strict=False)))
            self.assertEqual(data_sources["evap_dir"], str((root / "evap").resolve(strict=False)))
            self.assertEqual(data_sources["glacier_melt_dir"], str(glacier_melt_dir.resolve(strict=False)))
            self.assertEqual(data_sources["glacier_mask"], str((gis_dir / "glacier_mask.tif").resolve(strict=False)))
            self.assertEqual(data_sources["obs_file"], str(obs_path.resolve(strict=False)))
            self.assertEqual(data_sources["prec_source"], "cmfd")
            self.assertEqual(data_sources["configured_precip_source"], "era5")
            self.assertEqual(data_sources["runtime_prec_source"], "cmfd")

    def test_sync_run_boundary_condition_path_prefers_existing_candidate(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            raw_path = root / "raw.csv"
            config_path = root / "config.csv"
            config_path.write_text("date,q\n2026-06-01,1\n", encoding="utf-8")
            boundary_condition = {}
            optional_modules = {"boundary_inflow": {"file": str(raw_path)}}

            sync_run_boundary_condition_path(
                boundary_condition,
                optional_modules,
                config_path,
                lambda raw, **kwargs: Path(raw),
                first_existing_path,
            )

            self.assertEqual(boundary_condition["boundary_inflow_file"], str(config_path.resolve(strict=False)))

    def test_rebase_run_data_cache_paths_uses_current_source_dirs_and_cache_dir(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            paths = {
                "cache_dir": root / "cache",
                "aligned_temp_dir": root / "temp",
                "aligned_evap_dir": root / "evap",
            }
            data_sources = {"prec_dir": str(root / "prec")}
            cache = {
                "prec": {"cache_path": "old/prec.nc"},
                "temp": {"cache_path": "old/temp.nc", "source_dir": "old-temp"},
                "evap": {},
                "other": "keep",
            }

            rebase_run_data_cache_paths(cache, paths, data_sources)

            self.assertEqual(cache["prec"]["source_dir"], str((root / "prec").resolve(strict=False)))
            self.assertEqual(cache["prec"]["cache_path"], str((root / "cache" / "prec.nc").resolve(strict=False)))
            self.assertEqual(cache["temp"]["source_dir"], str((root / "temp").resolve(strict=False)))
            self.assertEqual(cache["temp"]["cache_path"], str((root / "cache" / "temp.nc").resolve(strict=False)))
            self.assertEqual(cache["evap"]["source_dir"], str((root / "evap").resolve(strict=False)))
            self.assertEqual(cache["other"], "keep")

    def test_is_studio_editable_metadata_requires_config_and_parameter_bounds(self) -> None:
        metadata = {"parameter_profile": {"bounds": {"TT": [-2.0, 2.0]}}}

        self.assertTrue(is_studio_editable_metadata(metadata, Path("C:/workspace/config.json")))
        self.assertFalse(is_studio_editable_metadata({}, Path("C:/workspace/config.json")))
        self.assertFalse(is_studio_editable_metadata(metadata, None, self._metadata_compatibility_context()))

    def test_is_studio_editable_metadata_resolves_config_with_metadata_hints(self) -> None:
        observed = {}

        def hints(metadata):
            observed["metadata"] = metadata
            return Path("C:/project"), Path("C:/gui")

        def resolve(raw, **kwargs):
            observed["raw"] = raw
            observed["kwargs"] = kwargs
            return Path("D:/resolved/config.json")

        context = self._metadata_compatibility_context(hints=hints, resolve=resolve)
        metadata = {
            "workspace_config": "relative/config.json",
            "parameter_profile": {"bounds": {"TT": [-2.0, 2.0]}},
        }

        self.assertTrue(is_studio_editable_metadata(metadata, context=context))
        self.assertIs(observed["metadata"], metadata)
        self.assertEqual(observed["raw"], "relative/config.json")
        self.assertEqual(observed["kwargs"]["project_root"], Path("C:/project"))
        self.assertEqual(observed["kwargs"]["gui_root"], Path("C:/gui"))

    def test_resolve_run_workspace_config_updates_resolved_metadata_path(self) -> None:
        observed = {}

        def hints(metadata):
            observed["metadata"] = metadata
            return Path("C:/project"), Path("C:/gui")

        def resolve(raw, **kwargs):
            observed["raw"] = raw
            observed["kwargs"] = kwargs
            return Path("D:/resolved/config.json")

        context = self._metadata_compatibility_context(hints=hints, resolve=resolve)
        metadata = {"workspace_config": "relative/config.json"}

        result = resolve_run_workspace_config(metadata, run_path=Path("C:/runs/run-001"), context=context)

        self.assertEqual(result, Path("D:/resolved/config.json"))
        self.assertEqual(metadata["workspace_config"], str(Path("D:/resolved/config.json")))
        self.assertIs(observed["metadata"], metadata)
        self.assertEqual(observed["raw"], "relative/config.json")
        self.assertEqual(observed["kwargs"]["run_path"], Path("C:/runs/run-001"))
        self.assertEqual(observed["kwargs"]["project_root"], Path("C:/project"))
        self.assertEqual(observed["kwargs"]["gui_root"], Path("C:/gui"))

    def test_resolve_run_workspace_config_keeps_raw_metadata_when_unresolved(self) -> None:
        context = self._metadata_compatibility_context(
            hints=lambda metadata: (None, None),
            resolve=lambda raw, **kwargs: None,
        )
        metadata = {"workspace_config": "missing/config.json"}

        result = resolve_run_workspace_config(metadata, context=context)

        self.assertIsNone(result)
        self.assertEqual(metadata["workspace_config"], "missing/config.json")

    def test_workspace_name_for_summary_prefers_workspace_label(self) -> None:
        def fail_resolve(*args, **kwargs):
            self.fail("workspace_config should not be resolved when label is present")

        def fail_read(path):
            self.fail("config should not be read when label is present")

        context = self._workspace_name_context(resolve=fail_resolve, read_config=fail_read)

        name = workspace_name_for_summary(
            {"workspace_label": "  Basin Label  ", "workspace_config": "C:/workspace/config.json"},
            context=context,
        )

        self.assertEqual(name, "Basin Label")

    def test_workspace_name_for_summary_reads_resolved_config_name(self) -> None:
        config_path = Path("C:/workspace/config_alpha.json")
        read_paths = []
        context = self._workspace_name_context(
            read_config=lambda path: read_paths.append(path) or {"\u6d41\u57df\u540d\u79f0": "Config Basin"},
        )

        name = workspace_name_for_summary({"workspace_config": "ignored"}, config_path, context)

        self.assertEqual(name, "Config Basin")
        self.assertEqual(read_paths, [config_path])

    def test_workspace_name_for_summary_falls_back_to_config_stem_when_read_fails(self) -> None:
        def fail_read(path):
            raise RuntimeError("cannot read config")

        context = self._workspace_name_context(read_config=fail_read)

        name = workspace_name_for_summary(
            {"workspace_config": "ignored"},
            Path("C:/workspace/config_beta.json"),
            context,
        )

        self.assertEqual(name, "config_beta")

    def test_workspace_name_for_summary_resolves_metadata_config_with_hints(self) -> None:
        observed = {}

        def hints(metadata):
            observed["metadata"] = metadata
            return Path("C:/project"), Path("C:/gui")

        def resolve(raw, **kwargs):
            observed["raw"] = raw
            observed["kwargs"] = kwargs
            return Path("D:/resolved/config_gamma.json")

        context = self._workspace_name_context(hints=hints, resolve=resolve)
        metadata = {"workspace_config": "relative/config_gamma.json"}

        name = workspace_name_for_summary(metadata, context=context)

        self.assertEqual(name, "config_gamma")
        self.assertIs(observed["metadata"], metadata)
        self.assertEqual(observed["raw"], "relative/config_gamma.json")
        self.assertEqual(observed["kwargs"]["project_root"], Path("C:/project"))
        self.assertEqual(observed["kwargs"]["gui_root"], Path("C:/gui"))

    def test_workspace_name_for_summary_falls_back_to_raw_config_stem(self) -> None:
        context = self._workspace_name_context()

        name = workspace_name_for_summary({"workspace_config": "C:/workspace/raw_delta.json"}, context=context)

        self.assertEqual(name, "raw_delta")

    def test_build_run_summary_keeps_result_api_fields(self) -> None:
        run_dir = Path("C:/runs/source_run")
        metadata = {
            "result_title": "手调起点",
            "run_id": "run-1",
            "run_time": "2026-06-02 10:00:00",
            "workspace_config": "C:/workspace/config.json",
            "calibration_profile": "daily",
            "project_object_type": "full_upstream_basin",
            "recorded_objective_family": "daily_unified_professional_v1",
            "metrics": {
                "calibration": {"nse": 0.76, "pbias": -2.4},
                "validation": {"nse": 0.61, "pbias": 7.3},
            },
            "optional_modules": {
                "glacier": {"enabled": True},
                "boundary_inflow": {"enabled": False},
            },
            "time_config": {"time_step_hours": 24},
            "initial_state": {"state_snapshot_available": True, "state_snapshot_time": "2026-06-02 00:00:00"},
            "forecast_result": {
                "source_state_time": "2026-06-01 00:00:00",
                "source_state_summary": {"source": "state"},
                "source_parameter_summary": {"parameter_count": 2},
                "forecast_input_archive": {"variable_count": 3},
            },
            "starter_result": {"enabled": True},
            "manual_result": {"source_run_path": "{ROOT}/manual_source"},
            "optimized_params": {"TT": -1.0, "FC": 850.0},
        }
        context = RunSummaryContext(
            to_display_path=lambda path: f"display:{Path(path).name}",
            is_studio_editable_metadata=lambda meta, resolved: True,
            build_hydrology_summary=lambda meta, path: {"flow_status_zh": "径流拟合达标"},
            workspace_name_for_summary=lambda meta, resolved: "沱沱河",
            param_bounds_profile_labels={},
            replace_placeholders=lambda value: str(value).replace("{ROOT}", "D:/resolved"),
        )

        summary = build_run_summary(
            run_dir,
            metadata,
            Path("C:/workspace/config.json"),
            updated_at=123.0,
            updated_at_ns=123000,
            context=context,
        )

        self.assertEqual(summary["path"], str(run_dir.resolve()))
        self.assertEqual(summary["display_path"], "display:source_run")
        self.assertEqual(summary["run_id"], "run-1")
        self.assertEqual(summary["nse_cal"], 0.76)
        self.assertEqual(summary["pbias_val"], 7.3)
        self.assertTrue(summary["glacier_enabled"])
        self.assertFalse(summary["boundary_enabled"])
        self.assertEqual(summary["workspace_display_path"], "display:config.json")
        self.assertTrue(summary["studio_compatible"])
        self.assertEqual(summary["run_origin"], "studio")
        self.assertEqual(summary["objective_family"], "daily_unified_professional_v1")
        self.assertEqual(summary["hydrology_summary"]["flow_status_zh"], "径流拟合达标")
        self.assertTrue(summary["optimized_params_available"])
        self.assertEqual(summary["optimized_param_count"], 2)
        self.assertTrue(summary["state_snapshot_available"])
        self.assertEqual(summary["state_snapshot_time"], "2026-06-02 00:00:00")
        self.assertEqual(summary["source_state_snapshot_time"], "2026-06-01 00:00:00")
        self.assertEqual(summary["source_state_summary"], {"source": "state"})
        self.assertEqual(summary["source_parameter_summary"], {"parameter_count": 2})
        self.assertEqual(summary["forecast_input_archive"], {"variable_count": 3})
        self.assertTrue(summary["forecast_source_ready"])
        self.assertEqual(summary["display_name"], "沱沱河 · 手调起点 · 2026-06-02 10:00:00")
        self.assertEqual(summary["display_subtitle"], "目录名：source_run")
        self.assertEqual(summary["run_type"], "manual_starter")
        self.assertEqual(summary["source_run_name"], "manual_source")
        self.assertEqual(summary["parameter_context"]["source_workspace"], "沱沱河")

    def test_default_run_export_fields_include_boundary_when_configured(self) -> None:
        self.assertEqual(default_run_export_fields({}), ["q_sim", "q_obs", "q_rain", "q_snow", "q_ice"])

        boundary_cases = [
            {"project_object_type": "interbasin_with_boundary"},
            {"optional_modules": {"boundary_inflow": {"enabled": True}}},
            {"boundary_condition": {"enabled": True}},
            {"boundary_condition": {"boundary_inflow_file": "boundary.csv"}},
        ]
        for metadata in boundary_cases:
            with self.subTest(metadata=metadata):
                self.assertEqual(
                    default_run_export_fields(metadata),
                    ["q_sim", "q_obs", "q_rain", "q_snow", "q_ice", "q_boundary_inflow"],
                )

    def test_read_sampled_csv_rows_preserves_total_and_last_row(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            csv_path = Path(temp_dir) / "simulation.csv"
            rows = ["date,q_sim,q_obs"]
            rows.extend(f"2026-06-{day:02d},{day},{day + 0.5}" for day in range(1, 12))
            csv_path.write_text("\n".join(rows), encoding="utf-8")

            sampled, total_rows = read_sampled_csv_rows(csv_path, max_points=3)

        self.assertEqual(total_rows, 11)
        self.assertEqual(sampled[0]["date"], "2026-06-01")
        self.assertEqual(sampled[-1]["date"], "2026-06-11")
        self.assertLess(len(sampled), total_rows)

    def test_run_csv_preview_reads_columns_and_limited_rows(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            run_path = Path(temp_dir)
            (run_path / "simulation.csv").write_text(
                "\n".join(
                    [
                        "date,q_sim,q_obs",
                        "2026-06-01,1.0,1.5",
                        "2026-06-02,2.0,2.5",
                        "2026-06-03,3.0,3.5",
                    ]
                ),
                encoding="utf-8",
            )

            preview = run_csv_preview(run_path, limit=2)
            empty_preview = run_csv_preview(run_path / "missing", limit=2)
            zero_preview = run_csv_preview(run_path, limit=0)

        self.assertEqual(preview["columns"], ["date", "q_sim", "q_obs"])
        self.assertEqual([row["date"] for row in preview["rows"]], ["2026-06-01", "2026-06-02"])
        self.assertEqual(empty_preview, {"columns": [], "rows": []})
        self.assertEqual(zero_preview["rows"], [])

    def test_run_csv_date_bounds_reads_first_last_and_count(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            run_path = Path(temp_dir)
            (run_path / "simulation.csv").write_text(
                "\n".join(
                    [
                        "date,q_sim",
                        "2026-06-01,1.0",
                        "2026-06-02,2.0",
                        ",3.0",
                    ]
                ),
                encoding="utf-8",
            )

            bounds = run_csv_date_bounds(run_path)
            missing_bounds = run_csv_date_bounds(run_path / "missing")

        self.assertEqual(bounds, {"first_date": "2026-06-01", "last_date": None, "row_count": 3})
        self.assertEqual(missing_bounds, {"first_date": None, "last_date": None, "row_count": 0})

    def test_read_run_metrics_snapshot_converts_metric_values(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            run_path = Path(temp_dir)
            metadata_path = run_path / "metadata.json"
            metadata_path.write_text(
                json.dumps(
                    {
                        "metrics": {
                            "calibration": {"nse": "0.81"},
                            "validation": {"nse": "0.73", "kge": "bad", "pbias": "-3.5"},
                        }
                    }
                ),
                encoding="utf-8",
            )

            snapshot = read_run_metrics_snapshot(
                run_path,
                lambda path: json.loads(path.read_text(encoding="utf-8")),
            )

        self.assertEqual(snapshot["nse_cal"], 0.81)
        self.assertEqual(snapshot["nse_val"], 0.73)
        self.assertIsNone(snapshot["kge_val"])
        self.assertEqual(snapshot["pbias_val"], -3.5)

    def test_load_run_series_map_reads_requested_field_by_date(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            run_path = Path(temp_dir)
            csv_path = run_path / "simulation.csv"
            csv_path.write_text(
                "\n".join(
                    [
                        "date,q_obs,q_boundary_inflow",
                        "2026-06-01,12.5,3.1",
                        ",99,8",
                        "2026-06-02,bad,4.2",
                    ]
                ),
                encoding="utf-8",
            )

            observed = load_run_series_map(run_path, "q_obs")
            missing = load_run_series_map(run_path / "missing", "q_obs")

        self.assertEqual(observed, {"2026-06-01": 12.5, "2026-06-02": None})
        self.assertEqual(missing, {})

    def test_apply_run_replay_config_overrides_replays_metadata_contracts(self) -> None:
        config = {
            "时间": {"预热开始": "2020-01-01", "率定开始": "2020-02-01"},
            "初始状态": {"UZ": 1.0},
            "边界条件": {"上游边界入流_csv": "old.csv"},
        }
        metadata = {
            "time_config": {
                "warmup_start": "2026-01-01",
                "calib_start": "2026-02-01",
                "valid_end": "2026-12-31",
                "time_step_hours": 6,
            },
            "objective": {"obs_mode": "daily_mean", "cfmax_zone_threshold_m": "4800"},
            "initial_state": {"vector": {"SM": "2.5"}},
            "boundary_condition": {
                "date_field": "time",
                "flow_field": "inflow",
                "gap_fill": "nearest",
                "boundary_inflow_file": "boundary.csv",
            },
        }
        context = RunReplayConfigContext(
            default_initial_state={"SM": 0.0, "UZ": 0.0},
            resolve_metadata_object_type=lambda meta: "interbasin_with_boundary",
            metadata_boundary_enabled=lambda meta: True,
        )

        patched = apply_run_replay_config_overrides(config, metadata, context)

        self.assertEqual(config["时间"]["预热开始"], "2020-01-01")
        self.assertEqual(patched["时间"]["预热开始"], "2026-01-01")
        self.assertEqual(patched["时间"]["率定开始"], "2026-02-01")
        self.assertEqual(patched["时间"]["验证结束"], "2026-12-31")
        self.assertEqual(patched["时间"]["开始年份"], 2026)
        self.assertEqual(patched["时间"]["结束年份"], 2026)
        self.assertEqual(patched["时间步长_小时"], 6.0)
        self.assertEqual(patched["项目对象"], "interbasin_with_boundary")
        self.assertEqual(patched["观测口径模式"], "daily_mean")
        self.assertEqual(patched["CFMAX分区阈值_m"], 4800.0)
        self.assertEqual(patched["初始状态"], {"UZ": 1.0, "SM": 2.5})
        self.assertEqual(
            patched["边界条件"],
            {
                "上游边界入流_csv": "boundary.csv",
                "时间字段": "time",
                "流量字段": "inflow",
                "缺失填补": "nearest",
            },
        )

    def test_apply_run_replay_config_overrides_clears_disabled_boundary(self) -> None:
        context = RunReplayConfigContext(
            default_initial_state={},
            resolve_metadata_object_type=lambda meta: "full_upstream_basin",
            metadata_boundary_enabled=lambda meta: False,
        )

        patched = apply_run_replay_config_overrides(
            {"边界条件": {"上游边界入流_csv": "old.csv"}},
            {"boundary_condition": {"date_field": "date"}},
            context,
        )

        self.assertEqual(patched["项目对象"], "full_upstream_basin")
        self.assertEqual(patched["边界条件"]["上游边界入流_csv"], "")
        self.assertEqual(patched["边界条件"]["时间字段"], "date")
        self.assertEqual(patched["边界条件"]["流量字段"], "inflow_m3s")
        self.assertEqual(patched["边界条件"]["缺失填补"], "zero")

    def test_metadata_initial_state_override_rejects_invalid_values(self) -> None:
        self.assertEqual(
            metadata_initial_state_override({"initial_state": {"vector": {"SM": "1.25"}}}, {"SM": 0.0}),
            {"SM": 1.25},
        )
        with self.assertRaisesRegex(ValueError, "不是有效数字"):
            metadata_initial_state_override({"initial_state": {"vector": {"SM": "bad"}}}, {"SM": 0.0})
        with self.assertRaisesRegex(ValueError, "不能为负值"):
            metadata_initial_state_override({"initial_state": {"vector": {"SM": "-1"}}}, {"SM": 0.0})

    def test_restore_forward_observed_series_updates_objective_arrays(self) -> None:
        module = SimpleNamespace(
            np=np,
            SIM_DATES=["2026-06-01", "2026-06-02", "2026-06-03"],
            CALIB_MASK=np.asarray([True, False, True]),
            VALID_MASK=np.asarray([False, True, False]),
            OBS_MODE_APPLIED="original",
            format_time_value=lambda value: value,
        )

        restored = restore_forward_observed_series(
            module,
            {"2026-06-01": 1.0, "2026-06-03": 3.0},
        )

        self.assertTrue(restored)
        np.testing.assert_allclose(module.Q_OBS_FULL, np.asarray([1.0, np.nan, 3.0]), equal_nan=True)
        np.testing.assert_allclose(module.Q_OBS_CALIB, np.asarray([1.0, 3.0]))
        np.testing.assert_allclose(module.Q_OBS_VALID, np.asarray([np.nan]), equal_nan=True)
        self.assertEqual(module.OBS_MODE_APPLIED, "run_replay_fallback")
        self.assertFalse(restore_forward_observed_series(module, {}))

    def test_forward_observation_state_round_trips_numpy_arrays(self) -> None:
        module = SimpleNamespace(
            np=np,
            OBS_MODE_APPLIED="original",
            Q_OBS_FULL=np.asarray([1.0, 2.0]),
            Q_OBS_OBJ=np.asarray([3.0, 4.0]),
            Q_OBS_CALIB=np.asarray([1.0]),
            Q_OBS_VALID=np.asarray([2.0]),
        )

        state = capture_forward_observation_state(module)
        module.Q_OBS_FULL[0] = 99.0
        module.Q_OBS_FULL = None
        module.Q_OBS_OBJ = None
        module.Q_OBS_CALIB = None
        module.Q_OBS_VALID = None
        module.OBS_MODE_APPLIED = "changed"

        restore_forward_observation_state(module, state)

        np.testing.assert_allclose(module.Q_OBS_FULL, np.asarray([1.0, 2.0]))
        np.testing.assert_allclose(module.Q_OBS_OBJ, np.asarray([3.0, 4.0]))
        np.testing.assert_allclose(module.Q_OBS_CALIB, np.asarray([1.0]))
        np.testing.assert_allclose(module.Q_OBS_VALID, np.asarray([2.0]))
        self.assertEqual(module.OBS_MODE_APPLIED, "original")

    def test_restore_forward_boundary_series_rebuilds_total_flow(self) -> None:
        module = SimpleNamespace(
            np=np,
            SIM_DATES=["2026-06-01", "2026-06-02", "2026-06-03"],
            format_time_value=lambda value: value,
        )
        sim = {
            "q_total": np.asarray([10.0, 20.0]),
            "q_local": np.asarray([7.0, 17.0]),
        }

        restored = restore_forward_boundary_series(
            module,
            sim,
            {"2026-06-01": 3.0, "2026-06-02": None},
        )

        self.assertTrue(restored)
        np.testing.assert_allclose(sim["q_local"], np.asarray([7.0, 17.0]))
        np.testing.assert_allclose(sim["q_boundary"], np.asarray([3.0, 0.0]))
        np.testing.assert_allclose(sim["q_total"], np.asarray([10.0, 17.0]))
        self.assertTrue(sim["boundary_enabled"])
        self.assertTrue(sim["boundary_replay_fixed"])
        self.assertFalse(restore_forward_boundary_series(module, {"q_total": np.asarray([1.0])}, {}))
        self.assertFalse(
            restore_forward_boundary_series(module, {"q_total": np.asarray([1.0])}, {"2026-06-02": 1.0})
        )

    def test_pick_latest_run_path_uses_mtime_then_path_for_tie_break(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            first = Path(temp_dir) / "run_a"
            second = Path(temp_dir) / "run_b"
            first.mkdir()
            second.mkdir()
            first_time = 1_800_000_000
            second_time = 1_800_000_010
            first.touch()
            second.touch()
            os.utime(first, (first_time, first_time))
            os.utime(second, (second_time, second_time))

            latest = pick_latest_run_path([str(first), str(second)])

        self.assertEqual(Path(latest).name, "run_b")
        self.assertEqual(pick_latest_run_path([]), "")
        self.assertEqual(pick_latest_run_path(["Z:/missing_a", "Z:/missing_b"]), "Z:/missing_b")

    def test_build_calibration_task_result_summarizes_run_metadata(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            run_dir = Path(temp_dir) / "run_1"
            run_dir.mkdir()
            metadata = {
                "workspace_config": "C:/workspace/config.json",
                "calibration_profile": "daily",
                "requested_objective_mode": "auto",
                "optimization": {
                    "requested_objective_mode": "de",
                    "effective_objective_mode": "daily_unified_professional_v1",
                },
                "metrics": {
                    "calibration": {"nse": 0.82, "kge": 0.76, "pbias": -1.5},
                    "validation": {"nse": 0.71, "kge": 0.68, "pbias": 2.3},
                },
            }
            (run_dir / "metadata.json").write_text(json.dumps(metadata), encoding="utf-8")
            context = RunCalibrationTaskContext(
                resolve_path=lambda raw, **kwargs: Path(raw).resolve(strict=bool(kwargs.get("must_exist"))),
                read_json_file=lambda path: json.loads(Path(path).read_text(encoding="utf-8")),
                normalize_run_metadata=lambda meta, **kwargs: (dict(meta), Path("C:/workspace/config.json")),
                run_update_timestamps=lambda path: (123.0, 123000),
                build_run_summary=lambda path, meta, resolved, **kwargs: {"display_name": "沱沱河率定结果"},
                is_studio_editable_metadata=lambda meta, resolved: True,
            )

            result = build_calibration_task_result(str(run_dir), context)

        self.assertIsNotNone(result)
        assert result is not None
        self.assertEqual(Path(result["run_path"]).name, "run_1")
        self.assertEqual(result["run_name"], "沱沱河率定结果")
        self.assertEqual(result["workspace_config"], "C:/workspace/config.json")
        self.assertEqual(result["calibration_profile"], "daily")
        self.assertEqual(result["requested_objective_mode"], "auto")
        self.assertEqual(result["effective_objective_mode"], "daily_unified_professional_v1")
        self.assertEqual(result["metrics"]["nse_cal"], 0.82)
        self.assertEqual(result["metrics"]["nse_val"], 0.71)
        self.assertEqual(result["metrics"]["kge_cal"], 0.76)
        self.assertEqual(result["metrics"]["kge_val"], 0.68)
        self.assertEqual(result["metrics"]["pbias_cal"], -1.5)
        self.assertEqual(result["metrics"]["pbias_val"], 2.3)
        self.assertTrue(result["studio_compatible"])

    def test_build_calibration_task_result_returns_none_for_missing_metadata(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            run_dir = Path(temp_dir) / "run_missing_metadata"
            run_dir.mkdir()
            context = RunCalibrationTaskContext(
                resolve_path=lambda raw, **kwargs: Path(raw).resolve(strict=bool(kwargs.get("must_exist"))),
                read_json_file=lambda path: {},
                normalize_run_metadata=lambda meta, **kwargs: (dict(meta), None),
                run_update_timestamps=lambda path: (0.0, 0),
                build_run_summary=lambda path, meta, resolved, **kwargs: {},
                is_studio_editable_metadata=lambda meta, resolved: False,
            )

            result = build_calibration_task_result(str(run_dir), context)

        self.assertIsNone(result)


if __name__ == "__main__":
    unittest.main()
