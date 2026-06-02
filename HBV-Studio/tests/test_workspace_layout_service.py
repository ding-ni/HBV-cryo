from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path


STUDIO_DIR = Path(__file__).resolve().parents[1]
if str(STUDIO_DIR) not in sys.path:
    sys.path.insert(0, str(STUDIO_DIR))

from services.workspace_layout import count_path_entries  # noqa: E402


class WorkspaceLayoutServiceTests(unittest.TestCase):
    def test_count_path_entries_returns_zero_for_missing_directory(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)

            count, truncated = count_path_entries(root / "missing")

        self.assertEqual(count, 0)
        self.assertFalse(truncated)

    def test_count_path_entries_counts_files_by_pattern(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (root / "a.tif").write_text("", encoding="utf-8")
            (root / "b.txt").write_text("", encoding="utf-8")
            (root / "nested").mkdir()
            (root / "nested" / "c.tif").write_text("", encoding="utf-8")

            count, truncated = count_path_entries(root, pattern="*.tif")

        self.assertEqual(count, 1)
        self.assertFalse(truncated)

    def test_count_path_entries_counts_recursive_files_with_limit(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            nested = root / "nested"
            nested.mkdir()
            for index in range(3):
                (nested / f"{index}.tif").write_text("", encoding="utf-8")

            count, truncated = count_path_entries(root, pattern="*.tif", recursive=True, limit=2)

        self.assertEqual(count, 2)
        self.assertTrue(truncated)

    def test_count_path_entries_counts_only_directories(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (root / "dir_a").mkdir()
            (root / "dir_b").mkdir()
            (root / "file.txt").write_text("", encoding="utf-8")

            count, truncated = count_path_entries(root, only_dirs=True)

        self.assertEqual(count, 2)
        self.assertFalse(truncated)


if __name__ == "__main__":
    unittest.main()
