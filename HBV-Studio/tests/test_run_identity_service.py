import sys
import unittest
from pathlib import Path


STUDIO_DIR = Path(__file__).resolve().parents[1]
if str(STUDIO_DIR) not in sys.path:
    sys.path.insert(0, str(STUDIO_DIR))

from services.runs import (  # noqa: E402
    display_run_title,
    has_custom_result_title,
    normalize_result_title,
    run_parameter_context,
    run_kind_from_metadata,
    run_kind_label,
    source_run_meta,
)


class RunIdentityServiceTests(unittest.TestCase):
    def test_run_kind_and_labels_follow_result_metadata(self) -> None:
        self.assertEqual(run_kind_from_metadata({"forecast_result": {"enabled": True}}), "forecast_restart")
        self.assertEqual(run_kind_from_metadata({"manual_result": {"enabled": True}}), "manual_result")
        self.assertEqual(run_kind_from_metadata({"starter_result": {"enabled": True}}), "manual_starter")
        self.assertEqual(run_kind_from_metadata({}, studio_compatible=True), "calibration")
        self.assertEqual(run_kind_from_metadata({}), "legacy")
        self.assertEqual(run_kind_label("manual_result"), "手调结果")
        self.assertEqual(run_kind_label("unknown"), "结果")

    def test_result_titles_distinguish_custom_names_from_system_names(self) -> None:
        run_dir = Path("C:/runs/run_20260602_100000")

        self.assertEqual(normalize_result_title("  我的   结果  "), "我的 结果")
        self.assertFalse(has_custom_result_title(run_dir, "run_20260602_100000"))
        self.assertFalse(has_custom_result_title(run_dir, "手调结果"))
        self.assertTrue(has_custom_result_title(run_dir, "沱沱河一号方案"))

        custom = display_run_title(
            run_dir,
            {"result_title": "沱沱河一号方案", "manual_result": {"enabled": True}, "run_time": "2026-06-02 10:00:00"},
            "沱沱河",
            studio_compatible=True,
        )
        self.assertEqual(custom["display_name"], "沱沱河一号方案")
        self.assertEqual(custom["display_subtitle"], "沱沱河 · 手调结果 · 2026-06-02 10:00:00")
        self.assertTrue(custom["has_custom_title"])
        self.assertEqual(custom["run_type"], "manual_result")

        generated = display_run_title(
            run_dir,
            {"result_title": "手调起点", "starter_result": {"enabled": True}},
            "沱沱河",
            studio_compatible=True,
        )
        self.assertEqual(generated["display_name"], "沱沱河 · 手调起点")
        self.assertEqual(generated["display_subtitle"], "目录名：run_20260602_100000")
        self.assertFalse(generated["has_custom_title"])

    def test_source_run_meta_prefers_replay_then_manual_then_optimization(self) -> None:
        source_path, source_name = source_run_meta(
            {
                "manual_result": {"source_run_path": "C:/runs/manual_source"},
                "optimization": {"source_run_path": "C:/runs/optimization_source"},
                "replay_context": {"source_run_path": "{ROOT}/replay_source"},
            },
            lambda value: str(value).replace("{ROOT}", "D:/resolved"),
        )
        self.assertEqual(source_path, "{ROOT}/replay_source")
        self.assertEqual(source_name, "replay_source")

        explicit_path, explicit_name = source_run_meta({
            "manual_result": {"source_run_path": "C:/runs/manual_source", "source_run_name": "人工命名源结果"},
        })
        self.assertEqual(explicit_path, "C:/runs/manual_source")
        self.assertEqual(explicit_name, "人工命名源结果")

    def test_run_parameter_context_summarizes_source_result_for_forecast(self) -> None:
        run_dir = Path("C:/runs/source_run")
        metadata = {
            "workspace_config": "",
            "calibration_profile": "hourly",
            "effective_objective_mode": "daily_unified_professional_v1",
            "time_config": {"time_step_hours": 1},
            "initial_state": {"state_snapshot_time": "2026-06-02 08:00:00"},
            "data_sources": {
                "configured_precip_source": "era5",
                "prec_source": "cmfd",
                "runtime_prec_source": "custom_tif",
                "station_precip_mode": "station_only",
                "precipitation_mode": "basin_grid",
                "precipitation_strategy": "station_corrected",
                "glacier_mode": "binary_legacy",
            },
            "optional_modules": {"glacier": {"enabled": True}},
            "parameter_profile": {"bounds_profile": "hourly_step"},
            "optimized_params": {"TT": -1.0, "FC": 850.0},
        }

        context = run_parameter_context(
            run_dir,
            metadata,
            Path("C:/workspace/config.json"),
            "沱沱河",
            {"hourly_step": "小时尺度稳定范围"},
        )

        self.assertEqual(context["schema"], "run_parameter_context_v1")
        self.assertEqual(context["source_run_name"], "source_run")
        self.assertEqual(context["source_workspace"], "沱沱河")
        self.assertEqual(context["source_workspace_config"], "C:\\workspace\\config.json")
        self.assertEqual(context["calibration_profile"], "hourly")
        self.assertEqual(context["time_step_hours"], 1)
        self.assertEqual(context["objective_mode"], "daily_unified_professional_v1")
        self.assertEqual(context["prec_source"], "custom_tif")
        self.assertEqual(context["precipitation_strategy"], "station_corrected")
        self.assertEqual(context["glacier_mode"], "binary_legacy")
        self.assertTrue(context["glacier_enabled"])
        self.assertEqual(context["param_bounds_profile"], "hourly_step")
        self.assertEqual(context["param_bounds_profile_label"], "小时尺度稳定范围")
        self.assertEqual(context["state_snapshot_time"], "2026-06-02 08:00:00")
        self.assertEqual(context["parameter_count"], 2)


if __name__ == "__main__":
    unittest.main()
