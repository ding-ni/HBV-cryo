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

from services.runs import (  # noqa: E402
    RunCalibrationTaskContext,
    RunDiscoveryContext,
    RunReplayConfigContext,
    RunSummaryContext,
    apply_run_replay_config_overrides,
    build_run_summary,
    build_calibration_task_result,
    capture_forward_observation_state,
    default_run_export_fields,
    discover_run_entries,
    discover_runtime_roots,
    display_run_title,
    has_custom_result_title,
    iter_run_parent_dirs,
    load_run_series_map,
    metadata_initial_state_override,
    normalize_result_title,
    pick_latest_run_path,
    read_sampled_csv_rows,
    restore_forward_boundary_series,
    restore_forward_observation_state,
    restore_forward_observed_series,
    run_parameter_context,
    run_kind_from_metadata,
    run_kind_label,
    run_update_timestamps,
    snapshot_run_paths,
    source_run_meta,
)


class RunIdentityServiceTests(unittest.TestCase):
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
