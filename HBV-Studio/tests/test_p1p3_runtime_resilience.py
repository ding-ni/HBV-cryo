import sys
import tempfile
import threading
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

    def test_get_api_route_registry_is_complete_and_resolvable(self) -> None:
        expected_routes = {
            "/api/health",
            "/api/dashboard",
            "/api/templates",
            "/api/workspaces",
            "/api/configs",
            "/api/workspace",
            "/api/config",
            "/api/runs",
            "/api/run",
            "/api/tasks",
            "/api/cdsapi/status",
            "/api/fs/list",
            "/api/obs-info",
            "/api/suggest/bbox",
            "/api/suggest/cfmax-threshold",
            "/api/geo/overview",
            "/api/data-prep/steps",
            "/api/data-prep/status",
            "/api/config/validate",
            "/api/wizard/validate-step",
            "/api/boundary-preview",
            "/api/workspace/completeness",
            "/api/workspace/detailed-check",
            "/api/workspace/layout",
            "/api/workspace/advice",
            "/api/manual-presets",
        }
        self.assertEqual(set(svc.StudioHandler.GET_ROUTE_HANDLERS), expected_routes)
        for handler_name in svc.StudioHandler.GET_ROUTE_HANDLERS.values():
            self.assertTrue(hasattr(svc.StudioHandler, handler_name), handler_name)
        self.assertEqual(
            svc.StudioHandler.GET_ROUTE_HANDLERS["/api/workspaces"],
            svc.StudioHandler.GET_ROUTE_HANDLERS["/api/configs"],
        )
        self.assertEqual(
            svc.StudioHandler.GET_ROUTE_HANDLERS["/api/workspace"],
            svc.StudioHandler.GET_ROUTE_HANDLERS["/api/config"],
        )

    def test_post_api_route_registry_is_complete_and_resolvable(self) -> None:
        expected_routes = {
            "/api/workspace/save",
            "/api/config/save",
            "/api/template/instantiate",
            "/api/import-workspace",
            "/api/auto-config",
            "/api/bootstrap/start",
            "/api/data-prep/start",
            "/api/calibration/start",
            "/api/self-check/start",
            "/api/template/sync-tuotuohe",
            "/api/wizard/save-step",
            "/api/gis/import",
            "/api/meteo/import/start",
            "/api/meteo/import",
            "/api/simulate/forward/start",
            "/api/simulate/forward",
            "/api/forecast/restart/start",
            "/api/forecast/restart",
            "/api/forecast/input-check",
            "/api/manual-start/start",
            "/api/manual-preset/save",
            "/api/manual-preset/delete",
            "/api/run/export-excel",
            "/api/run/rename",
            "/api/run/delete",
            "/api/workspace/delete",
            "/api/fs/open-path",
            "/api/app/window-unload",
            "/api/app/quit",
        }
        self.assertEqual(set(svc.StudioHandler.POST_ROUTE_HANDLERS), expected_routes)
        for handler_name in svc.StudioHandler.POST_ROUTE_HANDLERS.values():
            self.assertTrue(hasattr(svc.StudioHandler, handler_name), handler_name)
        self.assertEqual(
            svc.StudioHandler.POST_ROUTE_HANDLERS["/api/workspace/save"],
            svc.StudioHandler.POST_ROUTE_HANDLERS["/api/config/save"],
        )
        self.assertEqual(
            svc.StudioHandler.POST_ROUTE_HANDLERS["/api/import-workspace"],
            svc.StudioHandler.POST_ROUTE_HANDLERS["/api/auto-config"],
        )

    def test_workspace_writability_probe_is_concurrency_safe(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp)
            barrier = threading.Barrier(8)
            results: list[bool] = []
            lock = threading.Lock()

            def worker() -> None:
                barrier.wait()
                local = [svc.profile_runner._dir_is_writable(target) for _ in range(20)]
                with lock:
                    results.extend(local)

            threads = [threading.Thread(target=worker) for _ in range(8)]
            for thread in threads:
                thread.start()
            for thread in threads:
                thread.join()

            self.assertEqual(len(results), 160)
            self.assertTrue(all(results))
            self.assertFalse(list(target.glob(".__codex_write_probe__*")))


if __name__ == "__main__":
    unittest.main()
