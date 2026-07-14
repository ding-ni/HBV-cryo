from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

import pandas as pd


STUDIO_DIR = Path(__file__).resolve().parents[1]
if str(STUDIO_DIR) not in sys.path:
    sys.path.insert(0, str(STUDIO_DIR))

from services.meteo_import import (  # noqa: E402
    MeteoImportStartContext,
    MeteoImportWorkerContext,
    meteo_import_start_plan,
    meteo_import_worker_run,
    meteo_import_resampling_name,
    ordered_tif_files_by_timestamp,
    replace_directory_from_stage,
    should_report_file_progress,
    tif_series_digest,
    validate_precipitation_import_metadata,
)


class MeteoImportServiceTests(unittest.TestCase):
    def test_meteo_import_start_plan_builds_task_metadata(self) -> None:
        config = {"profile": "hourly"}
        context = MeteoImportStartContext(
            resolve_path=lambda raw, **kwargs: Path(str(raw)),
            read_runtime_config=lambda path: config,
            current_profile=lambda cfg: str(cfg["profile"]),
            resolve_runtime_precip_source=lambda cfg, source: f"resolved:{source}",
        )

        plan = meteo_import_start_plan(
            {"config_path": "workspace.json", "prec_source": "cmfd"},
            context,
        )

        self.assertEqual(plan.label, "气象栅格导入 | workspace")
        self.assertEqual(plan.command, ["meteo_import"])
        self.assertEqual(plan.metadata["config_path"], str(Path("workspace.json").resolve()))
        self.assertEqual(plan.metadata["profile"], "hourly")
        self.assertEqual(plan.metadata["runtime_prec_source"], "resolved:cmfd")

    def test_meteo_import_start_plan_defaults_precip_source_through_resolver(self) -> None:
        context = MeteoImportStartContext(
            resolve_path=lambda raw, **kwargs: Path(str(raw)),
            read_runtime_config=lambda path: {"profile": "daily"},
            current_profile=lambda cfg: str(cfg["profile"]),
            resolve_runtime_precip_source=lambda cfg, source: "era5" if source is None else str(source),
        )

        plan = meteo_import_start_plan({"config_path": "workspace.json"}, context)

        self.assertEqual(plan.metadata["profile"], "daily")
        self.assertEqual(plan.metadata["runtime_prec_source"], "era5")

    def test_meteo_import_worker_run_records_success_result(self) -> None:
        events: list[tuple] = []

        def perform_meteo_import(payload, *, task_id=None):
            events.append(("perform", payload, task_id))
            return {"prec_count": 3, "state_file": "meteo_state.json"}

        context = MeteoImportWorkerContext(
            perform_meteo_import=perform_meteo_import,
            add_task_exception_output=lambda task_id, exc: events.append(("exception", task_id, str(exc))),
            mark_task_finished=lambda task_id, **kwargs: events.append(("finished", task_id, kwargs)),
        )

        meteo_import_worker_run("task-1", {"config_path": "workspace.json"}, context)

        self.assertIn(("perform", {"config_path": "workspace.json"}, "task-1"), events)
        self.assertIn(
            (
                "finished",
                "task-1",
                {"ok": True, "return_code": 0, "result": {"prec_count": 3, "state_file": "meteo_state.json"}},
            ),
            events,
        )
        self.assertFalse(any(event[0] == "exception" for event in events))

    def test_meteo_import_worker_run_records_failure(self) -> None:
        events: list[tuple] = []

        def perform_meteo_import(payload, *, task_id=None):
            raise RuntimeError("import failed")

        context = MeteoImportWorkerContext(
            perform_meteo_import=perform_meteo_import,
            add_task_exception_output=lambda task_id, exc: events.append(("exception", task_id, str(exc))),
            mark_task_finished=lambda task_id, **kwargs: events.append(("finished", task_id, kwargs)),
        )

        meteo_import_worker_run("task-1", {"config_path": "workspace.json"}, context)

        self.assertIn(("exception", "task-1", "import failed"), events)
        self.assertIn(("finished", "task-1", {"ok": False, "return_code": -1}), events)

    def test_ordered_tif_files_by_timestamp_skips_invalid_names_and_sorts(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            for name in [
                "prec_2026-01-02.tif",
                "prec_2026-01-01.tif",
                "not-a-time.tif",
                "ignore.txt",
            ]:
                (root / name).write_text("", encoding="utf-8")

            ordered = ordered_tif_files_by_timestamp(root)

        self.assertEqual([item[0] for item in ordered], [pd.Timestamp("2026-01-01"), pd.Timestamp("2026-01-02")])
        self.assertEqual([item[1].name for item in ordered], ["prec_2026-01-01.tif", "prec_2026-01-02.tif"])

    def test_replace_directory_from_stage_replaces_existing_target(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            target = root / "target"
            stage = root / "stage"
            target.mkdir()
            stage.mkdir()
            (target / "old.txt").write_text("old", encoding="utf-8")
            (stage / "new.txt").write_text("new", encoding="utf-8")

            replace_directory_from_stage(target, stage)

            self.assertFalse(stage.exists())
            self.assertFalse((target / "old.txt").exists())
            self.assertEqual((target / "new.txt").read_text(encoding="utf-8"), "new")

    def test_should_report_file_progress_uses_small_batch_and_decile_rules(self) -> None:
        self.assertTrue(should_report_file_progress(7, 20))
        self.assertTrue(should_report_file_progress(1, 100))
        self.assertTrue(should_report_file_progress(10, 100))
        self.assertTrue(should_report_file_progress(100, 100))
        self.assertFalse(should_report_file_progress(11, 100))

    def test_meteo_import_resampling_preserves_precipitation_areal_depth(self) -> None:
        self.assertEqual(meteo_import_resampling_name("prec_dir"), "average")
        self.assertEqual(meteo_import_resampling_name("temp_dir"), "bilinear")
        self.assertEqual(meteo_import_resampling_name("evap_dir"), "bilinear")

    def test_daily_precipitation_metadata_has_project_friendly_defaults_and_scales_m_per_day(self) -> None:
        defaults = validate_precipitation_import_metadata({}, time_step_hours=24.0)
        self.assertEqual(defaults["input_unit"], "mm/day")
        self.assertEqual(defaults["day_basis"], "product_calendar_day")
        self.assertEqual(defaults["scale_to_mm"], 1.0)
        metadata = validate_precipitation_import_metadata(
            {"precip_unit": "m/day", "precip_day_basis": "beijing_calendar_day"},
            time_step_hours=24.0,
        )
        self.assertTrue(metadata["required"])
        self.assertEqual(metadata["scale_to_mm"], 1000.0)
        self.assertEqual(metadata["day_basis"], "beijing_calendar_day")

    def test_tif_series_digest_changes_with_file_content(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "P_2025.01.01.tif"
            path.write_bytes(b"one")
            first = tif_series_digest([(pd.Timestamp("2025-01-01"), path)])
            path.write_bytes(b"two")
            second = tif_series_digest([(pd.Timestamp("2025-01-01"), path)])
        self.assertEqual(first["file_count"], 1)
        self.assertNotEqual(first["series_sha256"], second["series_sha256"])


if __name__ == "__main__":
    unittest.main()
