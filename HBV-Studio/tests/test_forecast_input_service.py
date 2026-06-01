from __future__ import annotations

import sys
import unittest
import tempfile
from pathlib import Path

import pandas as pd


STUDIO_DIR = Path(__file__).resolve().parents[1]
if str(STUDIO_DIR) not in sys.path:
    sys.path.insert(0, str(STUDIO_DIR))

from services.forecast_input import (  # noqa: E402
    ForecastInputCheckContext,
    ensure_forecast_input_ready,
    forecast_expected_index,
    forecast_input_check,
    forecast_input_dir_summary,
    forecast_output_preview,
    forecast_source_state_time,
)


class ForecastInputServiceTests(unittest.TestCase):
    def _unused_context(self) -> ForecastInputCheckContext:
        def fail(*args, **kwargs):
            raise AssertionError("context should not be used")

        return ForecastInputCheckContext(
            resolve_path=fail,
            read_json_file=fail,
            read_runtime_config=fail,
            build_profile_paths=fail,
            resolve_profile=fail,
            parameter_check_context=fail,
            normalize_time_step_hours=fail,
            is_date_only_string=fail,
            validate_tif_time_series=fail,
            format_time_for_check=fail,
            forecast_parameter_detail_text=fail,
            forecast_station_precip_check=fail,
        )

    def test_forecast_input_check_rejects_missing_source_without_context_io(self) -> None:
        result = forecast_input_check({}, self._unused_context())

        self.assertEqual(result["status"], "fail")
        self.assertEqual(result["headline"], "请先选择预报源结果。")
        self.assertEqual(result["errors"], ["请先选择预报源结果。"])
        self.assertEqual(result["variables"], [])

    def test_ensure_forecast_input_ready_raises_for_failed_check(self) -> None:
        with self.assertRaisesRegex(ValueError, "连续状态预报输入检查未通过：请先选择预报源结果"):
            ensure_forecast_input_ready({}, self._unused_context())

    def test_forecast_source_state_time_prefers_metadata_then_simulation_csv(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            run_dir = Path(tmpdir)
            self.assertEqual(
                forecast_source_state_time(run_dir, {"initial_state": {"state_snapshot_time": "2026-01-02"}}),
                "2026-01-02",
            )

            (run_dir / "simulation.csv").write_text("date,q\n2026-01-01,1\n2026-01-03,2\n", encoding="utf-8")
            self.assertEqual(forecast_source_state_time(run_dir, {}), "2026-01-03")

    def test_forecast_expected_index_expands_date_only_hourly_end(self) -> None:
        index = forecast_expected_index(
            "2026-01-01 00:00",
            "2026-01-01",
            6,
            normalize_time_step_hours=lambda value: float(value),
            is_date_only_string=lambda value: len(str(value)) == 10,
        )

        self.assertEqual(len(index), 4)
        self.assertEqual(str(index[-1]), "2026-01-01 18:00:00")

    def test_forecast_input_dir_summary_builds_coverage_status(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            directory = Path(tmpdir)
            expected_index = pd.date_range("2026-01-01", periods=3, freq="D")

            summary = forecast_input_dir_summary(
                key="prec",
                label="降水",
                raw_path=str(directory),
                step_hours=24,
                expected_index=expected_index,
                resolve_path=lambda raw, **kwargs: Path(str(raw)),
                validate_tif_time_series=lambda *args, **kwargs: {
                    "missing_steps": [expected_index[-1]],
                    "out_of_range_steps": [pd.Timestamp("2026-01-04")],
                    "valid_time_steps": 3,
                    "errors": [],
                    "warnings": ["窗口外文件将不参与本次预报"],
                    "total_files": 4,
                    "timestamps": list(expected_index),
                },
                format_time_for_check=lambda value, step: pd.to_datetime(value).strftime("%Y-%m-%d"),
            )

        self.assertEqual(summary["status"], "warn")
        self.assertEqual(summary["covered_steps"], 2)
        self.assertEqual(summary["missing_steps"], 1)
        self.assertEqual(summary["out_of_window_steps"], 1)
        self.assertIn("2/3", summary["summary"])

    def test_forecast_output_preview_uses_explicit_output_dir(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            source_run = root / "source_run"
            output_dir = root / "manual_forecast"
            source_run.mkdir()

            preview = forecast_output_preview(
                {"output_dir": str(output_dir)},
                source_run,
                resolve_path=lambda raw, **kwargs: Path(str(raw)),
                read_runtime_config=lambda *args, **kwargs: self.fail("config should not be read"),
                build_profile_paths=lambda *args, **kwargs: self.fail("profile paths should not be built"),
                resolve_profile=lambda *args, **kwargs: self.fail("profile should not be resolved"),
            )

            self.assertTrue(preview["explicit"])
            self.assertEqual(preview["result_dir"], str(output_dir.resolve(strict=False)))
            self.assertEqual(preview["result_parent"], str(root.resolve(strict=False)))
            self.assertEqual(preview["archive_root"], str((output_dir / "forecast_inputs").resolve(strict=False)))
            self.assertEqual(
                preview["manifest_path"],
                str((output_dir / "forecast_inputs" / "input_manifest.json").resolve(strict=False)),
            )

    def test_forecast_output_preview_uses_config_runs_dir(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            source_run = root / "source_run"
            config_path = root / "workspace.json"
            runs_dir = root / "runs"
            source_run.mkdir()
            config_path.write_text("{}", encoding="utf-8")

            preview = forecast_output_preview(
                {"config_path": str(config_path), "profile": "daily"},
                source_run,
                resolve_path=lambda raw, **kwargs: Path(str(raw)),
                read_runtime_config=lambda path: {"config_path": str(path)},
                build_profile_paths=lambda config, profile: {"runs_dir": str(runs_dir)},
                resolve_profile=lambda config, requested: requested or "daily",
            )

            self.assertFalse(preview["explicit"])
            self.assertEqual(preview["result_parent"], str(runs_dir.resolve(strict=False)))
            self.assertIn("hbv_forecast_source_run", preview["result_detail"])
            self.assertTrue(preview["archive_detail"].endswith("\\forecast_inputs\\input_manifest.json"))

    def test_forecast_output_preview_falls_back_when_config_unavailable(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            source_run = root / "source_run"
            source_run.mkdir()

            def resolve_path(raw, **kwargs):
                if kwargs.get("must_exist"):
                    raise FileNotFoundError(str(raw))
                return Path(str(raw))

            preview = forecast_output_preview(
                {"config_path": str(root / "missing_workspace.json")},
                source_run,
                resolve_path=resolve_path,
                read_runtime_config=lambda *args, **kwargs: self.fail("config should not be read"),
                build_profile_paths=lambda *args, **kwargs: self.fail("profile paths should not be built"),
                resolve_profile=lambda *args, **kwargs: self.fail("profile should not be resolved"),
            )

            self.assertFalse(preview["explicit"])
            self.assertEqual(preview["result_parent"], str(root.resolve(strict=False)))


if __name__ == "__main__":
    unittest.main()
