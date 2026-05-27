import sys
import unittest
from pathlib import Path
from unittest import mock

STUDIO_DIR = Path(__file__).resolve().parents[1]
if str(STUDIO_DIR) not in sys.path:
    sys.path.insert(0, str(STUDIO_DIR))

import launch  # noqa: E402
import studio_service as svc  # noqa: E402


class P1P3RuntimeResilienceTests(unittest.TestCase):
    def test_launcher_marks_existing_service_stale_when_source_is_newer(self) -> None:
        self.assertTrue(
            launch.service_is_stale(
                {"server_started_at": 100.0},
                latest_mtime=105.0,
            )
        )
        self.assertFalse(
            launch.service_is_stale(
                {"server_started_at": 100.0},
                latest_mtime=100.5,
            )
        )

    def test_forecast_worker_keeps_traceback_when_restart_fails(self) -> None:
        task_id = "forecast_failure_smoke"
        with svc.TASK_LOCK:
            svc.TASKS.pop(task_id, None)
            svc.TASKS[task_id] = svc.TaskRecord(
                id=task_id,
                task_type="forecast_restart",
                label="forecast failure smoke",
                command=["forecast_restart"],
                cwd=str(STUDIO_DIR.parent),
            )
        try:
            with mock.patch.object(
                svc,
                "forecast_restart_with_progress",
                side_effect=OSError(22, "Invalid argument"),
            ):
                svc.forecast_restart_worker(task_id, {})
            task = svc.TASKS[task_id]
            self.assertEqual(task.status, "failed")
            self.assertTrue(any("[失败]" in line and "Invalid argument" in line for line in task.output))
            self.assertTrue(any("[诊断]" in line and "OSError" in line for line in task.output))
        finally:
            with svc.TASK_LOCK:
                svc.TASKS.pop(task_id, None)

    def test_health_source_mtime_reports_current_code_surface(self) -> None:
        latest, path = svc.source_files_latest_mtime()
        self.assertGreater(latest, 0)
        self.assertTrue(path.endswith((".py", ".js", ".html", ".css")))


if __name__ == "__main__":
    unittest.main()
