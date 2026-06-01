import sys
import unittest
from pathlib import Path


STUDIO_DIR = Path(__file__).resolve().parents[1]
if str(STUDIO_DIR) not in sys.path:
    sys.path.insert(0, str(STUDIO_DIR))

from services.data_prep import (  # noqa: E402
    DataPrepTaskOutputContext,
    verify_data_prep_step_output,
    verify_data_prep_task_output,
)


class DataPrepServiceTests(unittest.TestCase):
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


if __name__ == "__main__":
    unittest.main()
