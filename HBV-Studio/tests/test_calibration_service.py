from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path
from typing import Any


STUDIO_DIR = Path(__file__).resolve().parents[1]
if str(STUDIO_DIR) not in sys.path:
    sys.path.insert(0, str(STUDIO_DIR))

from services.calibration import CalibrationStartContext, calibration_start_plan  # noqa: E402


class CalibrationServiceTests(unittest.TestCase):
    def _context(
        self,
        root: Path,
        *,
        config: dict[str, Any] | None = None,
        validation: dict[str, Any] | None = None,
        runtime_prec_source: str = "era5",
    ) -> CalibrationStartContext:
        cfg = config or {"profile": "daily"}
        validation_result = validation or {"valid": True, "missing": []}

        return CalibrationStartContext(
            resolve_path=lambda raw, **kwargs: Path(str(raw)),
            read_runtime_config=lambda path: cfg,
            current_profile=lambda current_config: str(current_config.get("profile", "daily")),
            resolve_runtime_precip_source=lambda current_config, source: runtime_prec_source,
            validate_workspace_fields=lambda *args, **kwargs: validation_result,
            config_text_value=lambda current_config, key: str(current_config.get(key, "")),
            resolve_config_related_path=lambda current_config, raw: Path(str(raw)),
            build_profile_paths=lambda current_config, profile: {
                "logs_dir": root / "logs",
                "cache_dir": root / "cache",
                "aligned_prec_custom_dir": root / "custom_prec",
            },
            resolve_legacy_precip_source=lambda source: f"legacy:{source}",
            glacier_formal_requirements=lambda current_config, profile: {"ok": True},
            resolve_objective_mode=lambda current_config, value, profile: str(value or "nse"),
            resolve_param_bounds_profile=lambda current_config, value, profile: str(value or "professional"),
            resolve_calibration_workflow=lambda current_config, value, profile: str(value or "staged"),
            calibration_workflow_status=lambda workflow: f"status:{workflow}",
            find_manual_preset=lambda config_path, preset_id: {},
            build_forward_runtime_cli_args=lambda *args, **kwargs: object(),
            load_legacy_module=lambda script_path: object(),
            old_script_path=lambda current_config, group, name: Path(name),
            patch_runtime_environment=lambda *args, **kwargs: None,
            patch_profile_behavior=lambda *args, **kwargs: None,
            build_runtime_param_vector=lambda module, params: (None, params, None),
            build_python_script_command=lambda script, *args: ["python", str(script), *[str(item) for item in args]],
            model_runner=Path("runner.py"),
            observed_flow_key="观测径流_csv",
            calibration_methods={"de": "Differential Evolution", "mc_screen_de": "Monte Carlo + DE"},
            profile_daily="daily",
            profile_labels={"daily": "日尺度", "hourly": "小时尺度"},
            param_bounds_profile_labels={"professional": "专业参数范围"},
        )

    def test_calibration_start_plan_builds_command_and_metadata(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            obs = root / "observed.csv"
            obs.write_text("date,q\n2026-01-01,1\n", encoding="utf-8")
            context = self._context(root, config={"profile": "daily", "观测径流_csv": str(obs)})

            plan = calibration_start_plan(
                {
                    "config_path": "workspace.json",
                    "calibration_mode": "daily",
                    "prec_source": "era5",
                    "method": "de",
                    "workers": 3,
                    "maxiter": 40,
                    "popsize": 7,
                    "seed": 9,
                    "mc_samples": 120,
                    "objective_mode": "nse",
                    "param_bounds_profile": "professional",
                    "calibration_workflow": "staged",
                    "glacier_mode": "inline",
                    "refine_enabled": True,
                    "refine_maxiter": 4,
                },
                context,
            )

        self.assertEqual(plan.label, "率定任务 | workspace | 日尺度")
        self.assertEqual(plan.command[:4], ["python", "runner.py", "--配置", "workspace.json"])
        self.assertIn("--目标函数", plan.command)
        self.assertIn("nse", plan.command)
        self.assertIn("--param-bounds-profile", plan.command)
        self.assertIn("professional", plan.command)
        self.assertIn("--降水源", plan.command)
        self.assertIn("era5", plan.command)
        self.assertIn("--refine-maxiter", plan.command)
        self.assertIn("4", plan.command)
        self.assertEqual(plan.metadata["profile"], "daily")
        self.assertEqual(plan.metadata["method"], "de")
        self.assertEqual(plan.metadata["maxiter"], 40)
        self.assertEqual(plan.metadata["mc_samples"], 120)
        self.assertEqual(plan.metadata["runtime_prec_source"], "era5")
        self.assertTrue(plan.metadata["refine_enabled"])
        self.assertEqual(plan.metadata["refine_maxiter"], 4)
        self.assertFalse(plan.metadata["quick_test"])
        self.assertEqual(plan.metadata["calibration_workflow_status"], "status:staged")

    def test_calibration_start_plan_uses_custom_precip_directory(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            obs = root / "observed.csv"
            obs.write_text("date,q\n2026-01-01,1\n", encoding="utf-8")
            context = self._context(
                root,
                config={"profile": "daily", "观测径流_csv": str(obs)},
                runtime_prec_source="custom_tif",
            )

            plan = calibration_start_plan({"config_path": "workspace.json"}, context)

        self.assertIn("--降水源", plan.command)
        self.assertIn("custom_tif", plan.command)
        self.assertIn("--prec-dir", plan.command)
        self.assertIn(str(Path(tmpdir) / "custom_prec"), plan.command)
        self.assertEqual(plan.metadata["runtime_prec_source"], "custom_tif")

    def test_calibration_start_plan_rejects_validation_failure(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            context = self._context(
                Path(tmpdir),
                validation={"valid": False, "missing": ["观测径流_csv", "气象驱动"]},
            )

            with self.assertRaisesRegex(ValueError, "输入检查未通过，无法启动率定"):
                calibration_start_plan({"config_path": "workspace.json"}, context)

    def test_calibration_start_plan_quick_test_disables_debug_and_refine(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            context = self._context(Path(tmpdir), config={"profile": "daily"})

            plan = calibration_start_plan(
                {
                    "config_path": "workspace.json",
                    "quick_test": True,
                    "debug_days": 10,
                    "refine_enabled": True,
                    "refine_maxiter": 8,
                    "quick_days": 12,
                },
                context,
            )

        self.assertEqual(plan.label, "输入预核算 | workspace | 日尺度")
        self.assertNotIn("--debug-days", plan.command)
        self.assertIn("--refine-maxiter", plan.command)
        self.assertIn("0", plan.command)
        self.assertIn("--quick-test", plan.command)
        self.assertIn("--quick-days", plan.command)
        self.assertIn("12", plan.command)
        self.assertEqual(plan.metadata["debug_days"], 0)
        self.assertFalse(plan.metadata["refine_enabled"])
        self.assertEqual(plan.metadata["refine_maxiter"], 0)
        self.assertTrue(plan.metadata["quick_test"])


if __name__ == "__main__":
    unittest.main()
