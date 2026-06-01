from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace


STUDIO_DIR = Path(__file__).resolve().parents[1]
if str(STUDIO_DIR) not in sys.path:
    sys.path.insert(0, str(STUDIO_DIR))

from services.forecast_restart import ForecastRestartStartContext, forecast_restart_args, forecast_restart_start_plan  # noqa: E402


class ForecastRestartServiceTests(unittest.TestCase):
    def test_forecast_restart_args_builds_namespace_from_payload_aliases(self) -> None:
        input_check = {"status": "ok"}
        args = forecast_restart_args(
            {
                "config": "workspace.json",
                "run_path": "runs/source",
                "forecast_start": "2026-07-01",
                "forecast_end": "2026-07-10",
                "prec_dir": "prec",
                "temp_dir": "temp",
                "evap_dir": "evap",
                "calibration_mode": "daily",
                "objective_mode": "daily_unified_professional_v1",
                "_forecast_input_check": input_check,
            },
            resolve_path=lambda *args, **kwargs: self.fail("resolve_path should not be used"),
            read_json_file=lambda *args, **kwargs: self.fail("read_json_file should not be used"),
        )

        self.assertEqual(args.config, "workspace.json")
        self.assertEqual(args.source_run, "runs/source")
        self.assertEqual(args.forecast_start, "2026-07-01")
        self.assertEqual(args.forecast_end, "2026-07-10")
        self.assertEqual(args.forecast_prec_dir, "prec")
        self.assertEqual(args.forecast_temp_dir, "temp")
        self.assertEqual(args.forecast_evap_dir, "evap")
        self.assertEqual(args.profile, "daily")
        self.assertEqual(args.objective_mode, "daily_unified_professional_v1")
        self.assertEqual(args.prec_source, "custom_tif")
        self.assertEqual(args.glacier_mode, "inline")
        self.assertEqual(args.forecast_input_check, input_check)
        self.assertEqual(args.output_json, "")

    def test_forecast_restart_args_uses_source_metadata_config_when_missing(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            source_run = root / "source"
            source_run.mkdir()
            config_path = root / "workspace.json"
            (source_run / "metadata.json").write_text(
                json.dumps({"workspace_config": str(config_path)}, ensure_ascii=False),
                encoding="utf-8",
            )

            args = forecast_restart_args(
                {"source_run": str(source_run), "forecast_end": "2026-07-10"},
                resolve_path=lambda raw, **kwargs: Path(str(raw)),
                read_json_file=lambda path: json.loads(path.read_text(encoding="utf-8")),
            )

            self.assertEqual(args.config, str(config_path))
            self.assertEqual(args.source_run, str(source_run))

    def test_forecast_restart_args_requires_forecast_end(self) -> None:
        with self.assertRaisesRegex(ValueError, "forecast_end"):
            forecast_restart_args(
                {"config_path": "workspace.json", "source_run": "runs/source"},
                resolve_path=lambda *args, **kwargs: self.fail("resolve_path should not be used"),
                read_json_file=lambda *args, **kwargs: self.fail("read_json_file should not be used"),
            )

    def test_forecast_restart_start_plan_builds_metadata_and_checked_payload(self) -> None:
        args = SimpleNamespace(
            source_run="runs/source",
            config="workspace.json",
            forecast_start="2026-07-01",
            forecast_end="2026-07-10",
            prec_source="era5",
            glacier_mode="auto",
        )
        input_check = {"status": "ok", "errors": []}
        context = ForecastRestartStartContext(
            build_args=lambda payload: args,
            resolve_path=lambda raw, **kwargs: Path(str(raw)),
            ensure_input_ready=lambda payload: input_check,
        )
        payload = {"config_path": "workspace.json", "source_run": "runs/source"}

        plan = forecast_restart_start_plan(payload, context)

        self.assertEqual(plan.label, "连续状态预报 | source")
        self.assertEqual(plan.command, ["forecast_restart"])
        self.assertEqual(plan.metadata["config_path"], str(Path("workspace.json").resolve(strict=False)))
        self.assertEqual(plan.metadata["run_path"], str(Path("runs/source").resolve(strict=False)))
        self.assertEqual(plan.metadata["forecast_start"], "2026-07-01")
        self.assertEqual(plan.metadata["forecast_end"], "2026-07-10")
        self.assertEqual(plan.metadata["runtime_prec_source"], "era5")
        self.assertEqual(plan.metadata["glacier_mode"], "auto")
        self.assertEqual(plan.metadata["forecast_input_check"], input_check)
        self.assertEqual(plan.metadata["ui_progress"], {"stage": "准备启动", "label": "连续状态预报"})
        self.assertIs(plan.checked_payload["_forecast_input_check"], input_check)
        self.assertEqual(payload, {"config_path": "workspace.json", "source_run": "runs/source"})

    def test_forecast_restart_start_plan_propagates_input_check_failure(self) -> None:
        args = SimpleNamespace(
            source_run="runs/source",
            config="workspace.json",
            forecast_start="2026-07-01",
            forecast_end="2026-07-10",
            prec_source="era5",
            glacier_mode="auto",
        )
        context = ForecastRestartStartContext(
            build_args=lambda payload: args,
            resolve_path=lambda raw, **kwargs: Path(str(raw)),
            ensure_input_ready=lambda payload: (_ for _ in ()).throw(ValueError("连续状态预报输入检查未通过")),
        )

        with self.assertRaisesRegex(ValueError, "连续状态预报输入检查未通过"):
            forecast_restart_start_plan({"config_path": "workspace.json"}, context)


if __name__ == "__main__":
    unittest.main()
