from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock


STUDIO_DIR = Path(__file__).resolve().parents[1]
if str(STUDIO_DIR) not in sys.path:
    sys.path.insert(0, str(STUDIO_DIR))

import launch  # noqa: E402
from services.system_status import HealthContext, health_payload, source_files_latest_mtime  # noqa: E402


class InstalledSourceStalenessTests(unittest.TestCase):
    @staticmethod
    def _touch(root: Path, relative: str, timestamp: float) -> Path:
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"test")
        os.utime(path, (timestamp, timestamp))
        return path

    def test_new_adjacent_bytecode_makes_existing_service_stale(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            self._touch(root, "launch.pyc", 90.0)
            self._touch(root, "profile_runner.py", 90.0)
            expected = self._touch(root, "profile_runner.pyc", 120.0)
            with mock.patch.object(launch, "__file__", str(root / "launch.pyc")):
                latest, filename = launch.latest_source_mtime()
            self.assertEqual((latest, filename), (120.0, str(expected)))
            self.assertTrue(launch.service_is_stale({"server_started_at": 100.0}, latest))
            context = HealthContext(root, "test", 100.0)
            self.assertEqual(source_files_latest_mtime(context), (120.0, str(expected)))
            with mock.patch("services.project_license.license_payload", return_value={"ok": True}):
                self.assertTrue(health_payload(context)["source_stale"])

    def test_service_bytecode_is_detected_without_python_sources(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            self._touch(root, "launch.pyc", 90.0)
            expected = self._touch(root, "services/workspace_completeness.pyc", 130.0)
            with mock.patch.object(launch, "__file__", str(root / "launch.pyc")):
                self.assertEqual(launch.latest_source_mtime(), (130.0, str(expected)))
            self.assertEqual(source_files_latest_mtime(HealthContext(root, "test", 100.0)), (130.0, str(expected)))

    def test_old_bytecode_and_automatic_import_caches_do_not_make_service_stale(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            expected = self._touch(root, "launch.pyc", 90.0)
            self._touch(root, "services/system_status.pyc", 80.0)
            self._touch(root, "__pycache__/launch.cpython-311.pyc", 130.0)
            self._touch(root, "services/__pycache__/system_status.cpython-311.pyc", 140.0)
            with mock.patch.object(launch, "__file__", str(root / "launch.pyc")):
                latest, filename = launch.latest_source_mtime()
            self.assertEqual((latest, filename), (90.0, str(expected)))
            self.assertFalse(launch.service_is_stale({"server_started_at": 100.0}, latest))
            context = HealthContext(root, "test", 100.0)
            self.assertEqual(source_files_latest_mtime(context), (90.0, str(expected)))
            with mock.patch("services.project_license.license_payload", return_value={"ok": True}):
                self.assertFalse(health_payload(context)["source_stale"])


if __name__ == "__main__":
    unittest.main()
