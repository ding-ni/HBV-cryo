from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace


STUDIO_DIR = Path(__file__).resolve().parents[1]
if str(STUDIO_DIR) not in sys.path:
    sys.path.insert(0, str(STUDIO_DIR))

from services.workspace_detailed_check import build_reasonableness_checks  # noqa: E402


class WorkspaceDetailedCheckServiceTests(unittest.TestCase):
    def _context(self) -> SimpleNamespace:
        return SimpleNamespace(
            current_profile=lambda config: str(config.get("profile", "daily")),
            profile_daily="daily",
            resolve_objective_mode=lambda config, run, profile: str(config.get("objective_mode", "multi")),
            objective_mode_multi="multi",
            build_profile_paths=lambda config, profile: {"glacier_melt_dir": Path("missing-glacier-reference")},
            count_matching=lambda path, pattern="*.tif": 0,
            read_json_file=lambda path: {},
        )

    def _forcing(self, root: Path) -> dict[str, object]:
        return {
            "directories": {
                "prec": {"path": str(root / "prec")},
                "temp": {"path": str(root / "temp")},
                "evap": {"path": str(root / "evap")},
            }
        }

    def test_reasonableness_checks_warn_when_daily_rasters_are_unavailable(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            checks = build_reasonableness_checks(
                {"profile": "daily", "冰川边界_shp": ""},
                self._forcing(Path(temp_dir)),
                self._context(),
                dem_stats={
                    "valid_pixels": 20,
                    "min": 3000,
                    "max": 6100,
                    "median": 4500,
                    "resolution_text": "0.010000 x 0.010000",
                },
            )

        self.assertEqual([item["title"] for item in checks[:3]], ["降水合理性检查", "气温合理性检查", "潜在蒸散发合理性检查"])
        self.assertTrue(all(item["status"] == "warn" for item in checks[:3]))
        dem = next(item for item in checks if item["title"] == "DEM 合理性检查")
        self.assertEqual(dem["status"], "ok")
        glacier = next(item for item in checks if item["title"] == "冰川合理性检查")
        self.assertEqual(glacier["summary"], "当前未启用冰川输入。")

    def test_reasonableness_checks_fail_when_configured_glacier_mask_is_missing(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            checks = build_reasonableness_checks(
                {"profile": "daily", "冰川边界_shp": "glacier.shp"},
                self._forcing(Path(temp_dir)),
                self._context(),
                dem_stats={"valid_pixels": 100, "min": 3000, "max": 6000, "median": 4500},
                glacier_mask_summary={"glacier_mode": "binary_legacy", "glacier_pixels": 12},
                glacier_mask_exists=False,
                gis_dir=Path(temp_dir),
            )

        glacier = next(item for item in checks if item["title"] == "冰川合理性检查")
        self.assertEqual(glacier["status"], "fail")
        self.assertIn("还没有生成冰川掩膜", glacier["summary"])
        mask_item = next(item for item in glacier["items"] if item["label"] == "掩膜状态")
        self.assertEqual(mask_item["status"], "fail")


if __name__ == "__main__":
    unittest.main()
