from __future__ import annotations

import sys
import unittest
from pathlib import Path


STUDIO_DIR = Path(__file__).resolve().parents[1]
if str(STUDIO_DIR) not in sys.path:
    sys.path.insert(0, str(STUDIO_DIR))

from services.meteo_import import (  # noqa: E402
    MeteoImportStartContext,
    MeteoImportWorkerContext,
    meteo_import_start_plan,
    meteo_import_worker_run,
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


if __name__ == "__main__":
    unittest.main()
