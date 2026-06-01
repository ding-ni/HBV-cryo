from __future__ import annotations

import sys
import unittest
from pathlib import Path


STUDIO_DIR = Path(__file__).resolve().parents[1]
if str(STUDIO_DIR) not in sys.path:
    sys.path.insert(0, str(STUDIO_DIR))

from services.data_prep import (  # noqa: E402
    DataPrepBootstrapContext,
    DataPrepStartContext,
    DataPrepTaskOutputContext,
    data_prep_bootstrap_plan,
    data_prep_start_plan,
    data_prep_step_command,
    data_prep_workflow_decision,
    verify_data_prep_step_output,
    verify_data_prep_task_output,
)


class DataPrepServiceTests(unittest.TestCase):
    def _start_context(
        self,
        *,
        steps: dict[str, dict[str, object]],
        status: list[dict[str, object]] | None = None,
        config: dict[str, object] | None = None,
        cleared: list[dict[str, object]] | None = None,
    ) -> DataPrepStartContext:
        runtime_config = config or {"profile": "daily"}
        return DataPrepStartContext(
            resolve_path=lambda raw, **kwargs: Path(str(raw)),
            read_runtime_config=lambda path: runtime_config,
            task_step_map=lambda profile, cfg: steps,
            current_profile=lambda cfg: str(cfg.get("profile", "daily")),
            resolve_runtime_precip_source=lambda cfg, source: str(source or "era5"),
            resolve_legacy_precip_source=lambda source: f"legacy:{source}",
            data_prep_status=lambda path, source: status if status is not None else [{"id": key, "blocked_by": []} for key in steps],
            build_python_script_command=lambda script, *args: ["python", str(script), *[str(item) for item in args]],
            clear_meteo_state=lambda cfg, *args: (cleared.append(cfg) if cleared is not None else None),
            forcing_pipeline_step_ids=frozenset({"meteo"}),
        )

    def _bootstrap_context(
        self,
        *,
        config: dict[str, object] | None = None,
        glacier_elev: bool = False,
    ) -> DataPrepBootstrapContext:
        runtime_config = config or {"profile": "daily"}
        steps = {
            "clip_dem": {"title": "裁剪 DEM"},
            "flow_acc": {"title": "生成流向与流量累积"},
            "masked_flow": {"title": "生成汇流与流域掩膜"},
            "elevation_zone": {"title": "生成高程分区"},
            "glacier_mask": {"title": "生成冰川掩膜"},
            "glacier_elev": {"title": "生成冰川高程分区"},
        }
        return DataPrepBootstrapContext(
            resolve_path=lambda raw, **kwargs: Path(str(raw)),
            read_runtime_config=lambda path: runtime_config,
            task_step_map=lambda profile, cfg: steps,
            current_profile=lambda cfg: str(cfg.get("profile", "daily")),
            glacier_elev_required=lambda cfg: glacier_elev,
        )

    def test_verify_data_prep_step_output_handles_missing_check_success_and_exception(self) -> None:
        self.assertEqual(verify_data_prep_step_output({}, {}), (True, "该步骤没有产物检查函数。"))

        step = {
            "needs_prec_source": True,
            "check": lambda config, source: (source == "era5", f"source={source}", 2),
        }
        self.assertEqual(verify_data_prep_step_output(step, {}, "era5"), (True, "source=era5"))

        failing_step = {"check": lambda config: (_ for _ in ()).throw(RuntimeError("boom"))}
        ok, message = verify_data_prep_step_output(failing_step, {})
        self.assertFalse(ok)
        self.assertIn("产物检查异常", message)

    def test_verify_data_prep_task_output_resolves_step_and_precip_source(self) -> None:
        calls: list[tuple[dict[str, object], str]] = []

        def check(config: dict[str, object], source: str) -> tuple[bool, str, int]:
            calls.append((config, source))
            return True, "产物已就绪", 1

        config = {"profile": "daily"}
        context = DataPrepTaskOutputContext(
            resolve_path=lambda raw, **kwargs: Path(str(raw)),
            read_runtime_config=lambda path: config,
            task_step_map=lambda profile, cfg: {"meteo": {"id": "meteo", "needs_prec_source": True, "check": check}},
            current_profile=lambda cfg: str(cfg["profile"]),
            resolve_runtime_precip_source=lambda cfg, source: f"resolved:{source}",
        )

        result = verify_data_prep_task_output(
            {"config_path": "workspace.json", "step_id": "meteo", "runtime_prec_source": "era5"},
            context,
        )

        self.assertEqual(result, (True, "产物已就绪"))
        self.assertEqual(calls, [(config, "resolved:era5")])

    def test_verify_data_prep_task_output_handles_missing_unknown_and_prepare_error(self) -> None:
        context = DataPrepTaskOutputContext(
            resolve_path=lambda raw, **kwargs: Path(str(raw)),
            read_runtime_config=lambda path: {},
            task_step_map=lambda profile, cfg: {},
            current_profile=lambda cfg: "daily",
            resolve_runtime_precip_source=lambda cfg, source: "era5",
        )

        self.assertEqual(verify_data_prep_task_output({}, context), (True, "缺少步骤产物检查上下文。"))
        self.assertEqual(
            verify_data_prep_task_output({"config_path": "workspace.json", "step_id": "missing"}, context),
            (True, "未知步骤 missing，跳过产物复核。"),
        )

        error_context = DataPrepTaskOutputContext(
            resolve_path=lambda raw, **kwargs: (_ for _ in ()).throw(FileNotFoundError("missing")),
            read_runtime_config=lambda path: {},
            task_step_map=lambda profile, cfg: {},
            current_profile=lambda cfg: "daily",
            resolve_runtime_precip_source=lambda cfg, source: "era5",
        )
        ok, message = verify_data_prep_task_output(
            {"config_path": "workspace.json", "step_id": "meteo"},
            error_context,
        )
        self.assertFalse(ok)
        self.assertIn("产物检查准备失败", message)

    def test_data_prep_step_command_adds_precip_source_and_overwrite(self) -> None:
        context = self._start_context(
            steps={},
            config={"profile": "daily"},
        )
        command = data_prep_step_command(
            {"script": Path("prep.py"), "needs_prec_source": True, "supports_overwrite": True},
            Path("workspace.json"),
            {"prec_source": "station", "overwrite": True},
            context,
        )

        self.assertEqual(
            command,
            ["python", "prep.py", "--配置", "workspace.json", "--降水源", "legacy:station", "--覆盖"],
        )

    def test_data_prep_start_plan_validates_and_builds_task_metadata(self) -> None:
        cleared: list[dict[str, object]] = []
        steps = {
            "meteo": {
                "id": "meteo",
                "title": "气象数据准备",
                "script": Path("meteo.py"),
                "needs_prec_source": True,
            }
        }
        context = self._start_context(steps=steps, cleared=cleared)

        plan = data_prep_start_plan(
            {"config_path": "workspace.json", "step_id": "meteo", "prec_source": "era5"},
            context,
        )

        self.assertEqual(plan.label, "数据准备 | 气象数据准备 | workspace")
        self.assertEqual(plan.command, ["python", "meteo.py", "--配置", "workspace.json", "--降水源", "era5"])
        self.assertEqual(plan.metadata["step_id"], "meteo")
        self.assertEqual(plan.metadata["step_title"], "气象数据准备")
        self.assertEqual(plan.metadata["runtime_prec_source"], "era5")
        self.assertEqual(plan.metadata["ui_progress"]["label"], "气象数据准备")
        self.assertEqual(len(cleared), 1)

    def test_data_prep_start_plan_rejects_unknown_manual_and_blocked_steps(self) -> None:
        steps = {
            "manual": {"id": "manual", "title": "手动导入", "script": Path("manual.py"), "manual": True},
            "blocked": {"id": "blocked", "title": "被阻塞步骤", "script": Path("blocked.py")},
            "dep": {"id": "dep", "title": "前置步骤", "script": Path("dep.py")},
        }

        with self.assertRaisesRegex(ValueError, "未知的数据准备步骤"):
            data_prep_start_plan({"config_path": "workspace.json", "step_id": "missing"}, self._start_context(steps=steps))
        with self.assertRaisesRegex(ValueError, "手动导入步骤"):
            data_prep_start_plan({"config_path": "workspace.json", "step_id": "manual"}, self._start_context(steps=steps))
        with self.assertRaisesRegex(ValueError, "前置依赖未完成：前置步骤"):
            data_prep_start_plan(
                {"config_path": "workspace.json", "step_id": "blocked"},
                self._start_context(steps=steps, status=[{"id": "blocked", "blocked_by": ["dep"]}]),
            )

    def test_data_prep_bootstrap_plan_builds_base_geography_workflow(self) -> None:
        plan = data_prep_bootstrap_plan(
            {"config_path": "workspace.json"},
            self._bootstrap_context(),
        )

        self.assertEqual(plan.label, "基础地理数据生成 | workspace")
        self.assertEqual(plan.command, ["bootstrap"])
        self.assertEqual(plan.step_ids, ["clip_dem", "flow_acc", "masked_flow", "elevation_zone"])
        self.assertEqual(plan.metadata["profile"], "daily")
        self.assertEqual(plan.metadata["step_titles"], ["裁剪 DEM", "生成流向与流量累积", "生成汇流与流域掩膜", "生成高程分区"])
        self.assertEqual(plan.metadata["ui_progress"], {"stage": "准备执行", "current": 0, "total": 4, "label": "等待前置条件"})

    def test_data_prep_bootstrap_plan_adds_glacier_steps_when_needed(self) -> None:
        plan = data_prep_bootstrap_plan(
            {"config_path": "workspace.json"},
            self._bootstrap_context(config={"profile": "hourly", "冰川边界_shp": "glacier.shp"}, glacier_elev=True),
        )

        self.assertEqual(
            plan.step_ids,
            ["clip_dem", "flow_acc", "masked_flow", "elevation_zone", "glacier_mask", "glacier_elev"],
        )
        self.assertEqual(plan.metadata["profile"], "hourly")
        self.assertEqual(plan.metadata["ui_progress"]["total"], 6)

    def test_data_prep_workflow_decision_marks_skips_ready_and_blocked_steps(self) -> None:
        steps = {
            "already": {"id": "already", "title": "已完成"},
            "manual": {"id": "manual", "title": "手动步骤", "manual": True},
            "ready": {"id": "ready", "title": "可执行", "depends_on": ["already", "manual"]},
            "blocked": {"id": "blocked", "title": "等待依赖", "depends_on": ["missing"]},
        }
        status_map = {"already": {"done": True}}

        decision = data_prep_workflow_decision(
            ["already", "manual", "ready", "blocked"],
            set(),
            steps,
            status_map,
        )

        self.assertEqual(decision.skipped_done, ["already"])
        self.assertEqual(decision.skipped_manual, ["manual"])
        self.assertEqual(decision.ready, ["ready"])
        self.assertEqual(decision.blocked, ["blocked"])
        self.assertEqual(decision.completed_ids, {"already", "manual"})
        self.assertEqual(decision.remaining, ["ready", "blocked"])

    def test_data_prep_workflow_decision_respects_overwrite_for_completed_steps(self) -> None:
        steps = {"already": {"id": "already", "title": "已完成"}}
        decision = data_prep_workflow_decision(
            ["already"],
            set(),
            steps,
            {"already": {"done": True}},
            overwrite=True,
        )

        self.assertEqual(decision.skipped_done, [])
        self.assertEqual(decision.ready, ["already"])
        self.assertEqual(decision.completed_ids, set())
        self.assertEqual(decision.remaining, ["already"])


if __name__ == "__main__":
    unittest.main()
