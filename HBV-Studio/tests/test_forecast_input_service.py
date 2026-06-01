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
    forecast_parameter_check_context,
    forecast_parameter_detail_text,
    forecast_station_precip_check,
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
            run_parameter_context=fail,
            profile_labels={},
            objective_label=fail,
            precip_source_label=fail,
            station_precip_mode_label=fail,
            normalize_time_step_hours=fail,
            is_date_only_string=fail,
            validate_tif_time_series=fail,
            format_time_for_check=fail,
            analyze_station_precip_inputs=fail,
            meteo_key="meteo",
            meteo_precip_mode_key="precip_mode",
            time_basis_forecast_window="forecast_window",
            time_basis_labels={"forecast_window": "预报窗口"},
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

    def test_forecast_parameter_check_context_prefers_payload_config_path(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            source_run = root / "source_run"
            payload_config = root / "payload_workspace.json"
            metadata_config = root / "metadata_workspace.json"
            source_run.mkdir()
            payload_config.write_text("{}", encoding="utf-8")
            metadata_config.write_text("{}", encoding="utf-8")

            captured: dict[str, object] = {}
            expected = {"ok": True}

            def run_parameter_context(run, metadata, config):
                captured["run"] = run
                captured["metadata"] = metadata
                captured["config"] = config
                return expected

            result = forecast_parameter_check_context(
                {"config_path": str(payload_config)},
                source_run,
                {"workspace_config": str(metadata_config)},
                resolve_path=lambda raw, **kwargs: Path(str(raw)),
                run_parameter_context=run_parameter_context,
            )

            self.assertIs(result, expected)
            self.assertEqual(captured["run"], source_run)
            self.assertEqual(captured["metadata"], {"workspace_config": str(metadata_config)})
            self.assertEqual(captured["config"], payload_config)

    def test_forecast_parameter_check_context_uses_none_when_config_cannot_resolve(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            source_run = root / "source_run"
            source_run.mkdir()

            def resolve_path(raw, **kwargs):
                raise FileNotFoundError(str(raw))

            result = forecast_parameter_check_context(
                {},
                source_run,
                {"workspace_config": str(root / "missing_workspace.json")},
                resolve_path=resolve_path,
                run_parameter_context=lambda run, metadata, config: {"config": config},
            )

            self.assertIsNone(result["config"])

    def test_forecast_parameter_detail_text_formats_available_context(self) -> None:
        detail = forecast_parameter_detail_text(
            {
                "source_workspace": "Basin_A",
                "calibration_profile": "daily",
                "objective_mode": "daily_unified_professional_v1",
                "prec_source": "custom_tif",
                "precipitation_strategy": "grid_plus_station_bias",
            },
            profile_labels={"daily": "日尺度"},
            objective_label=lambda metadata: "统一专业目标",
            precip_source_label=lambda source: "本地栅格",
            station_precip_mode_label=lambda mode: "站点订正",
        )

        self.assertEqual(
            detail,
            "来源工作区：Basin_A；计算尺度：日尺度；率定目标：统一专业目标；降水驱动：本地栅格；降水方案：站点订正",
        )

    def test_forecast_parameter_detail_text_skips_blank_fields_and_keeps_unknown_profile(self) -> None:
        detail = forecast_parameter_detail_text(
            {
                "source_workspace": "",
                "calibration_profile": "event",
                "objective_mode": "",
                "prec_source": "",
                "precipitation_mode": "thiessen_station_only",
            },
            profile_labels={},
            objective_label=lambda metadata: self.fail("objective label should not be used"),
            precip_source_label=lambda source: self.fail("precip source label should not be used"),
            station_precip_mode_label=lambda mode: "泰森站点降水",
        )

        self.assertEqual(detail, "计算尺度：event；降水方案：泰森站点降水")

    def test_forecast_station_precip_check_skips_grid_only_mode(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            config_path = Path(tmpdir) / "workspace.json"
            config_path.write_text("{}", encoding="utf-8")

            result = forecast_station_precip_check(
                {"config_path": str(config_path)},
                {},
                "2026-01-01",
                "2026-01-03",
                24,
                resolve_path=lambda raw, **kwargs: Path(str(raw)),
                read_runtime_config=lambda path: {"meteo": {"precip_mode": "grid_only"}},
                analyze_station_precip_inputs=lambda *args, **kwargs: self.fail("analysis should be skipped"),
                meteo_key="meteo",
                meteo_precip_mode_key="precip_mode",
                time_basis_forecast_window="forecast_window",
                time_basis_labels={"forecast_window": "预报窗口"},
            )

            self.assertIsNone(result)

    def test_forecast_station_precip_check_builds_forecast_window_config(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            config_path = Path(tmpdir) / "workspace.json"
            config_path.write_text("{}", encoding="utf-8")
            config = {
                "meteo": {"precip_mode": "grid_plus_station_bias"},
                "时间": {"预热开始": "old", "率定结束": "old"},
            }
            captured: dict[str, object] = {}

            def analyze(forecast_config, **kwargs):
                captured["config"] = forecast_config
                captured["kwargs"] = kwargs
                return {"status": "ok", "items": []}

            result = forecast_station_precip_check(
                {"config_path": str(config_path)},
                {},
                "2026-01-01",
                "2026-01-03",
                6,
                resolve_path=lambda raw, **kwargs: Path(str(raw)),
                read_runtime_config=lambda path: config,
                analyze_station_precip_inputs=analyze,
                meteo_key="meteo",
                meteo_precip_mode_key="precip_mode",
                time_basis_forecast_window="forecast_window",
                time_basis_labels={"forecast_window": "预报窗口"},
            )

            self.assertEqual(result["status"], "ok")
            self.assertEqual(config["时间"]["预热开始"], "old")
            forecast_config = captured["config"]
            self.assertEqual(forecast_config["任务时段模式"], "forecast_window")
            self.assertEqual(forecast_config["时间步长_小时"], 6)
            self.assertEqual(forecast_config["时间"]["预热开始"], "2026-01-01")
            self.assertEqual(forecast_config["时间"]["率定开始"], "2026-01-01")
            self.assertEqual(forecast_config["时间"]["率定结束"], "2026-01-03")
            self.assertEqual(forecast_config["时间"]["验证开始"], "2026-01-01")
            self.assertEqual(forecast_config["时间"]["验证结束"], "2026-01-03")
            self.assertEqual(captured["kwargs"], {"step_hours": 6, "context": "forecast"})

    def test_forecast_station_precip_check_warns_when_analysis_fails(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            config_path = Path(tmpdir) / "workspace.json"
            config_path.write_text("{}", encoding="utf-8")

            def analyze(*args, **kwargs):
                raise RuntimeError("station data unavailable")

            result = forecast_station_precip_check(
                {"config_path": str(config_path)},
                {},
                "2026-01-01",
                "2026-01-03",
                24,
                resolve_path=lambda raw, **kwargs: Path(str(raw)),
                read_runtime_config=lambda path: {"meteo": {"precip_mode": "thiessen_station_only"}},
                analyze_station_precip_inputs=analyze,
                meteo_key="meteo",
                meteo_precip_mode_key="precip_mode",
                time_basis_forecast_window="forecast_window",
                time_basis_labels={"forecast_window": "预报窗口"},
            )

            self.assertEqual(result["status"], "warn")
            self.assertEqual(result["mode"], "thiessen_station_only")
            self.assertEqual(result["time_basis"], "forecast_window")
            self.assertEqual(result["time_basis_label"], "预报窗口")
            self.assertTrue(any("station data unavailable" in item for item in result["warnings"]))


if __name__ == "__main__":
    unittest.main()
