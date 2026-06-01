import sys
import unittest
from pathlib import Path

STUDIO_DIR = Path(__file__).resolve().parents[1]
if str(STUDIO_DIR) not in sys.path:
    sys.path.insert(0, str(STUDIO_DIR))

from services.app_lifecycle import AppLifecycleContext, app_quit, app_window_unload  # noqa: E402


class AppLifecycleServiceTests(unittest.TestCase):
    def test_window_unload_marks_activity_and_accepts(self) -> None:
        calls = []
        context = AppLifecycleContext(
            mark_activity=lambda **kwargs: calls.append(kwargs),
            has_running_tasks=lambda: False,
        )

        result = app_window_unload(context)

        self.assertTrue(result.ok)
        self.assertEqual(result.status, 200)
        self.assertEqual(result.data, {"accepted": True})
        self.assertEqual(calls, [{"unload": True}])

    def test_quit_rejects_when_tasks_are_running(self) -> None:
        context = AppLifecycleContext(
            mark_activity=lambda **kwargs: None,
            has_running_tasks=lambda: True,
        )

        result = app_quit(context)

        self.assertFalse(result.ok)
        self.assertEqual(result.status, 409)
        self.assertEqual(result.data, {"accepted": False})
        self.assertIn("运行中的任务", result.error)
        self.assertFalse(result.shutdown_message)

    def test_quit_accepts_and_requests_shutdown_when_idle(self) -> None:
        context = AppLifecycleContext(
            mark_activity=lambda **kwargs: None,
            has_running_tasks=lambda: False,
        )

        result = app_quit(context)

        self.assertTrue(result.ok)
        self.assertEqual(result.status, 200)
        self.assertEqual(result.data, {"accepted": True})
        self.assertIn("正在关闭本地服务", result.shutdown_message)
        self.assertEqual(result.shutdown_delay_sec, 0.2)


if __name__ == "__main__":
    unittest.main()
