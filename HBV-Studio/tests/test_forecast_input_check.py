import json
import sys
import tempfile
import unittest
from pathlib import Path
from typing import Optional

STUDIO_DIR = Path(__file__).resolve().parents[1]
if str(STUDIO_DIR) not in sys.path:
    sys.path.insert(0, str(STUDIO_DIR))

import studio_service as svc  # noqa: E402


def _write_workspace_config(root: Path, name: str = "Basin_A") -> Path:
    workspace_root = root / name
    workspace_root.mkdir(parents=True, exist_ok=True)
    config_path = workspace_root / "workspace.json"
    config = {
        "流域名称": name,
        "运行目录": str(workspace_root),
        "率定模式": "daily",
        "时间步长_小时": 24,
        "气象策略": {
            "降水来源": "custom_tif",
            "降水方案": "grid_only",
        },
        "时间": {
            "预热开始": "2025-01-01",
            "率定开始": "2025-01-01",
            "率定结束": "2025-01-03",
            "验证开始": "2025-01-01",
            "验证结束": "2025-01-03",
        },
    }
    config_path.write_text(json.dumps(config, ensure_ascii=False, indent=2), encoding="utf-8")
    return config_path


def _write_source_run(root: Path, config_path: Path, *, params: bool = True, state: bool = True) -> Path:
    run_dir = root / "source_run"
    run_dir.mkdir(parents=True, exist_ok=True)
    if state:
        (run_dir / "state_snapshot.npz").write_bytes(b"snapshot placeholder")
    metadata = {
        "schema": "hbv_studio_result_v1",
        "run_id": "source_run",
        "run_class": "calibration",
        "workspace_config": str(config_path),
        "calibration_profile": "daily",
        "effective_objective_mode": "daily_unified_professional_v1",
        "optimized_params": {"TT": 0.1, "FC": 100.0} if params else {},
        "time_config": {
            "time_step_hours": 24,
            "calib_start": "2025-01-01",
            "calib_end": "2025-01-03",
        },
        "initial_state": {
            "state_snapshot_file": "state_snapshot.npz",
            "state_snapshot_time": "2025-01-03",
            "state_snapshot_available": state,
        },
        "optional_modules": {"glacier": {"enabled": True}},
        "data_sources": {
            "runtime_prec_source": "custom_tif",
            "station_precip_mode": "grid_only",
            "glacier_mode": "inline",
        },
    }
    (run_dir / "metadata.json").write_text(json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8")
    return run_dir


def _write_forecast_tifs(root: Path, key: str, dates: list[str]) -> Path:
    directory = root / key
    directory.mkdir(parents=True, exist_ok=True)
    for date in dates:
        (directory / f"{key}_{date}.tif").write_bytes(b"")
    return directory


def _forecast_payload(root: Path, config_path: Path, source_run: Path, dates: Optional[list[str]] = None) -> dict:
    dates = dates or ["2025-01-04", "2025-01-05", "2025-01-06"]
    return {
        "config_path": str(config_path),
        "source_run": str(source_run),
        "forecast_start": "2025-01-04",
        "forecast_end": "2025-01-06",
        "forecast_prec_dir": str(_write_forecast_tifs(root, "prec", dates)),
        "forecast_temp_dir": str(_write_forecast_tifs(root, "temp", dates)),
        "forecast_evap_dir": str(_write_forecast_tifs(root, "evap", dates)),
    }


class ForecastInputCheckTests(unittest.TestCase):
    def test_complete_forecast_window_reports_source_state_parameters_and_output_paths(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            config_path = _write_workspace_config(root)
            source_run = _write_source_run(root, config_path)

            check = svc.forecast_input_check(_forecast_payload(root, config_path, source_run))

            self.assertEqual(check["status"], "ok")
            self.assertEqual(check["source"]["source_state_time"], "2025-01-03")
            self.assertEqual(check["source"]["expected_forecast_start"], "2025-01-04")
            self.assertEqual(check["source"]["parameter_count"], 2)
            self.assertEqual(check["window"]["forecast_start"], "2025-01-04")
            self.assertEqual(check["window"]["expected_steps"], 3)
            self.assertIn("source_run", check["output"]["result_detail"])
            self.assertIn("forecast_inputs", check["output"]["archive_detail"])
            self.assertEqual(check["parameter_context"]["parameter_source"], "source_result")
            self.assertEqual(check["parameter_context"]["source_workspace"], "Basin_A")
            self.assertTrue(any(item["label"] == "参数来源" and item["status"] == "ok" for item in check["items"]))

    def test_out_of_window_forecast_files_warn_without_blocking_restart(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            config_path = _write_workspace_config(root)
            source_run = _write_source_run(root, config_path)
            dates = ["2025-01-04", "2025-01-05", "2025-01-06", "2025-01-07"]

            check = svc.forecast_input_check(_forecast_payload(root, config_path, source_run, dates=dates))

            self.assertEqual(check["status"], "warn")
            self.assertEqual(check["errors"], [])
            self.assertTrue(any("窗口外文件将不参与本次预报" in item["summary"] for item in check["variables"]))
            self.assertTrue(any(item["out_of_window_steps"] == 1 for item in check["variables"]))
            ready = svc.ensure_forecast_input_ready(_forecast_payload(root, config_path, source_run, dates=dates))
            self.assertEqual(ready["status"], "warn")

    def test_missing_parameters_or_source_state_blocks_forecast_start(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            config_path = _write_workspace_config(root)
            source_run = _write_source_run(root, config_path, params=False, state=False)

            check = svc.forecast_input_check(_forecast_payload(root, config_path, source_run))

            self.assertEqual(check["status"], "fail")
            self.assertTrue(any("缺少率定参数" in item for item in check["errors"]))
            self.assertTrue(any("缺少可用于起报的保存状态" in item for item in check["errors"]))
            with self.assertRaisesRegex(ValueError, "连续状态预报输入检查未通过"):
                svc.ensure_forecast_input_ready(_forecast_payload(root, config_path, source_run))

    def test_forecast_start_must_follow_source_state_by_one_time_step(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            config_path = _write_workspace_config(root)
            source_run = _write_source_run(root, config_path)
            payload = _forecast_payload(root, config_path, source_run)
            payload["forecast_start"] = "2025-01-05"

            check = svc.forecast_input_check(payload)

            self.assertEqual(check["status"], "fail")
            self.assertTrue(any("起报时间必须紧接源结果保存状态" in item for item in check["errors"]))


if __name__ == "__main__":
    unittest.main()
