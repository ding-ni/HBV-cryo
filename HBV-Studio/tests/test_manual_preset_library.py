import json
import sys
import tempfile
import unittest
from pathlib import Path

STUDIO_DIR = Path(__file__).resolve().parents[1]
if str(STUDIO_DIR) not in sys.path:
    sys.path.insert(0, str(STUDIO_DIR))

import studio_service as svc  # noqa: E402


def _write_workspace_config(root: Path, name: str, *, precipitation_mode: str = "grid_only") -> Path:
    workspace_root = root / name
    workspace_root.mkdir(parents=True, exist_ok=True)
    config_path = workspace_root / "workspace.json"
    config = {
        "流域名称": name,
        "运行目录": str(workspace_root),
        "率定模式": "daily",
        "时间步长_小时": 24,
        "任务时段模式": "continuous",
        "气象策略": {
            "降水来源": "custom_tif",
            "降水方案": precipitation_mode,
        },
        "时间": {
            "预热开始": "2020-01-01",
            "率定开始": "2020-01-02",
            "率定结束": "2020-01-05",
            "验证开始": "2020-01-06",
            "验证结束": "2020-01-08",
        },
    }
    config_path.write_text(json.dumps(config, ensure_ascii=False, indent=2), encoding="utf-8")
    return config_path


def _write_source_run(root: Path, config_path: Path) -> Path:
    run_dir = root / "source_run"
    run_dir.mkdir(parents=True, exist_ok=True)
    metadata = {
        "schema": "hbv_studio_result_v1",
        "run_id": "source_run",
        "run_class": "calibration",
        "workspace_config": str(config_path),
        "calibration_profile": "daily",
        "effective_objective_mode": "daily_unified_professional_v1",
        "optimized_params": {"TT": 0.2, "CFMAX_low": 3.5, "CFMAX_high": 5.2, "FC": 120.0},
        "time_config": {
            "time_step_hours": 24,
            "warmup_start": "2020-01-01",
            "calib_start": "2020-01-02",
            "calib_end": "2020-01-05",
            "valid_start": "2020-01-06",
            "valid_end": "2020-01-08",
        },
        "metrics": {
            "calibration": {"nse": 0.82, "kge": 0.79},
            "validation": {"nse": 0.76, "kge": 0.74},
        },
        "optional_modules": {"glacier": {"enabled": True}},
        "data_sources": {
            "runtime_prec_source": "custom_tif",
            "station_precip_mode": "grid_plus_station_bias",
            "glacier_mode": "inline",
        },
    }
    (run_dir / "metadata.json").write_text(json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8")
    return run_dir


class ManualPresetLibraryTests(unittest.TestCase):
    def test_global_parameter_set_can_be_reused_across_workspaces_with_context(self) -> None:
        old_global_path = svc.GLOBAL_PARAMETER_LIBRARY_PATH
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            svc.GLOBAL_PARAMETER_LIBRARY_PATH = root / "parameter_library" / "global_parameter_sets.json"
            old_build_runtime_cli_args = svc._build_forward_runtime_cli_args
            old_load_legacy_module = svc.profile_runner.load_legacy_module
            svc._build_forward_runtime_cli_args = lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("skip runtime module in unit test"))
            svc.profile_runner.load_legacy_module = lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("skip legacy load in unit test"))
            try:
                config_a = _write_workspace_config(root, "Basin_A", precipitation_mode="grid_plus_station_bias")
                config_b = _write_workspace_config(root, "Basin_B", precipitation_mode="grid_only")
                source_run = _write_source_run(root, config_a)
                source_metadata = json.loads((source_run / "metadata.json").read_text(encoding="utf-8"))
                old_source_run_metadata = svc._source_run_metadata_for_preset
                svc._source_run_metadata_for_preset = lambda raw: (source_metadata, source_run, config_a)

                saved = svc.save_manual_preset(
                    {
                        "config_path": str(config_a),
                        "scope": "global",
                        "run_path": str(source_run),
                        "calibration_profile": "daily",
                        "objective_mode": "daily_unified_professional_v1",
                        "param_bounds_profile": "qtp_alpine_default",
                        "prec_source": "custom_tif",
                        "glacier_mode": "inline",
                        "name": "Tuotuohe calibrated parameter set",
                        "params": {"TT": 0.2, "CFMAX_low": 3.5, "CFMAX_high": 5.2, "FC": 120.0},
                    }
                )
                preset = saved["preset"]
                self.assertEqual(preset["scope"], "global")
                self.assertEqual(preset["source_workspace"], "Basin_A")
                self.assertEqual(preset["context"]["workspace_name"], "Basin_A")
                self.assertEqual(preset["context"]["task_time_basis"], svc.TIME_BASIS_CONTINUOUS)
                self.assertEqual(preset["context"]["precipitation_mode"], "grid_plus_station_bias")
                self.assertEqual(preset["period_summary"]["calibration_start"], "2020-01-02")
                self.assertEqual(preset["metrics"]["validation"]["nse"], 0.76)

                listed = svc.list_manual_presets(str(config_b), calibration_profile="daily", scope="all")
                listed_ids = {item["parameter_set_id"] for item in listed["presets"]}
                self.assertIn(preset["parameter_set_id"], listed_ids)
                self.assertEqual(listed["global_store_path"], str(svc.GLOBAL_PARAMETER_LIBRARY_PATH))

                found = svc.find_manual_preset(str(config_b), preset["parameter_set_id"])
                self.assertEqual(found["scope"], "global")
                self.assertEqual(found["params"]["CFMAX_low"], 3.5)
                self.assertEqual(found["params"]["CFMAX_high"], 5.2)
                self.assertEqual(found["source_workspace_config"], str(config_a))
            finally:
                if "old_source_run_metadata" in locals():
                    svc._source_run_metadata_for_preset = old_source_run_metadata
                svc._build_forward_runtime_cli_args = old_build_runtime_cli_args
                svc.profile_runner.load_legacy_module = old_load_legacy_module
                svc.GLOBAL_PARAMETER_LIBRARY_PATH = old_global_path


if __name__ == "__main__":
    unittest.main()
