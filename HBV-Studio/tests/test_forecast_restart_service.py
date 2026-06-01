from __future__ import annotations

import sys
import unittest
from pathlib import Path
from types import SimpleNamespace


STUDIO_DIR = Path(__file__).resolve().parents[1]
if str(STUDIO_DIR) not in sys.path:
    sys.path.insert(0, str(STUDIO_DIR))

from services.forecast_restart import ForecastRestartStartContext, forecast_restart_start_plan  # noqa: E402


class ForecastRestartServiceTests(unittest.TestCase):
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
