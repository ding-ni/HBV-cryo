from __future__ import annotations

import sys
import unittest
from pathlib import Path


STUDIO_DIR = Path(__file__).resolve().parents[1]
if str(STUDIO_DIR) not in sys.path:
    sys.path.insert(0, str(STUDIO_DIR))

from services.manual_start import ManualStartStartContext, manual_start_start_plan  # noqa: E402


class ManualStartServiceTests(unittest.TestCase):
    def test_manual_start_start_plan_builds_task_metadata(self) -> None:
        forward_context = {
            "config": {"流域名称": "沱沱河"},
            "profile": "daily",
            "prec_source": "era5",
            "objective_mode": "nse",
            "glacier_mode": "formal",
        }
        context = ManualStartStartContext(
            build_workspace_forward_context=lambda payload: forward_context,
        )

        plan = manual_start_start_plan({"config_path": "original.json"}, Path("workspace.json"), context)

        self.assertEqual(plan.label, "手调起点 | 沱沱河")
        self.assertEqual(plan.command, ["manual_start"])
        self.assertEqual(plan.metadata["config_path"], str(Path("workspace.json").resolve()))
        self.assertEqual(plan.metadata["profile"], "daily")
        self.assertEqual(plan.metadata["runtime_prec_source"], "era5")
        self.assertEqual(plan.metadata["objective_mode"], "nse")
        self.assertEqual(plan.metadata["glacier_mode"], "formal")
        self.assertEqual(plan.metadata["ui_progress"], {"stage": "准备启动", "label": "手调起点"})

    def test_manual_start_start_plan_uses_config_stem_when_basin_name_blank(self) -> None:
        forward_context = {
            "config": {"流域名称": "  "},
            "profile": "hourly",
            "prec_source": "cmfd",
            "objective_mode": "auto",
            "glacier_mode": "diagnostic",
        }
        context = ManualStartStartContext(
            build_workspace_forward_context=lambda payload: forward_context,
        )

        plan = manual_start_start_plan({}, Path("workspace.json"), context)

        self.assertEqual(plan.label, "手调起点 | workspace")
        self.assertEqual(plan.metadata["profile"], "hourly")
        self.assertEqual(plan.metadata["runtime_prec_source"], "cmfd")

    def test_manual_start_start_plan_overrides_payload_config_path_for_context(self) -> None:
        seen_payloads: list[dict[str, object]] = []

        def build_context(payload: dict[str, object]) -> dict[str, object]:
            seen_payloads.append(payload)
            return {
                "config": {},
                "profile": "daily",
                "prec_source": "era5",
                "objective_mode": "auto",
                "glacier_mode": "auto",
            }

        context = ManualStartStartContext(build_workspace_forward_context=build_context)
        manual_start_start_plan({"config_path": "stale.json", "other": 1}, Path("workspace.json"), context)

        self.assertEqual(seen_payloads, [{"config_path": "workspace.json", "other": 1}])


if __name__ == "__main__":
    unittest.main()
