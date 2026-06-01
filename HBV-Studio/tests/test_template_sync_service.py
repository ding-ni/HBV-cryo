from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path


STUDIO_DIR = Path(__file__).resolve().parents[1]
if str(STUDIO_DIR) not in sys.path:
    sys.path.insert(0, str(STUDIO_DIR))

from services.template_sync import TuotuoheSyncStartContext, tuotuohe_sync_start_plan  # noqa: E402


class TemplateSyncServiceTests(unittest.TestCase):
    def _context(
        self,
        root: Path,
        *,
        env_source: str = "",
        drives: list[str] | None = None,
    ) -> TuotuoheSyncStartContext:
        return TuotuoheSyncStartContext(
            list_drives=lambda: drives or [],
            env_get=lambda key, default="": env_source if key == "HBV_TUOTUOHE_SOURCE_ROOT" else default,
            build_python_script_command=lambda script, *args: ["python", str(script), *[str(item) for item in args]],
            tuotuohe_sync_script=Path("sync.py"),
            project_runtime_dir=root / "runtime",
            gui_root=root / "gui",
        )

    def test_tuotuohe_sync_start_plan_uses_explicit_source_and_include_raw(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            plan = tuotuohe_sync_start_plan(
                {"source_root": "D:/legacy/data", "target_root": "D:/target", "include_raw": True},
                self._context(root),
            )

        self.assertEqual(plan.label, "同步沱沱河模板数据")
        self.assertEqual(
            plan.command,
            ["python", "sync.py", "--source", "D:/legacy/data", "--target", "D:/target", "--include-raw"],
        )
        self.assertEqual(plan.cwd, root / "gui")

    def test_tuotuohe_sync_start_plan_uses_existing_env_source(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            env_source = root / "env_data"
            env_source.mkdir()
            plan = tuotuohe_sync_start_plan({}, self._context(root, env_source=str(env_source)))

        self.assertEqual(plan.command[:5], ["python", "sync.py", "--source", str(env_source), "--target"])
        self.assertEqual(plan.command[5], str(root / "runtime" / "沱沱河" / "数据"))

    def test_tuotuohe_sync_start_plan_falls_back_to_drive_hapi_data(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            drive = root / "drive"
            source = drive / "Hapi" / "data"
            source.mkdir(parents=True)
            plan = tuotuohe_sync_start_plan({}, self._context(root, drives=[str(drive)]))

        self.assertEqual(plan.command[3], str(source.resolve(strict=False)))

    def test_tuotuohe_sync_start_plan_rejects_missing_source(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            with self.assertRaisesRegex(ValueError, "未找到历史数据源目录"):
                tuotuohe_sync_start_plan({}, self._context(Path(tmpdir)))


if __name__ == "__main__":
    unittest.main()
