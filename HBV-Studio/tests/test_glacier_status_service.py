from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path
from typing import Any


STUDIO_DIR = Path(__file__).resolve().parents[1]
if str(STUDIO_DIR) not in sys.path:
    sys.path.insert(0, str(STUDIO_DIR))

from services.glacier_status import (  # noqa: E402
    GlacierStatusContext,
    check_glacier_elev,
    check_glacier_mask,
    glacier_elev_required,
    glacier_formal_requirements,
)


class GlacierStatusServiceTests(unittest.TestCase):
    def _context(
        self,
        root: Path,
        *,
        reference_count: int = 0,
        dem_kind: str = "1km",
        objective_mode: str = "multi",
    ) -> GlacierStatusContext:
        gis_dir = root / "gis"
        melt_dir = root / "melt"
        gis_dir.mkdir(parents=True, exist_ok=True)
        melt_dir.mkdir(parents=True, exist_ok=True)

        def read_json_file(path: Path) -> dict[str, Any]:
            return json.loads(path.read_text(encoding="utf-8"))

        return GlacierStatusContext(
            current_profile=lambda config: "daily",
            build_profile_paths=lambda config, profile: {
                "gis_dir": str(gis_dir),
                "glacier_melt_dir": str(melt_dir),
            },
            read_json_file=read_json_file,
            count_matching=lambda path: reference_count,
            workspace_dem_path=lambda gis_path, **kwargs: Path(gis_path) / "dem.tif",
            configured_dem_kind=lambda config: dem_kind,
            infer_dem_kind_from_raster=lambda path: dem_kind,
            resolve_objective_mode=lambda config, value, profile: objective_mode,
            objective_mode_multi="multi",
            objective_mode_flood_event="flood_event",
        )

    def test_check_glacier_mask_reports_disabled_without_glacier_shape(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            context = self._context(Path(temp_dir))

            ok, message, count = check_glacier_mask({}, context)

        self.assertTrue(ok)
        self.assertEqual(message, "未启用（未提供冰川边界 shp）")
        self.assertEqual(count, 0)

    def test_check_glacier_mask_uses_fractional_summary_message(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            context = self._context(root)
            gis_dir = root / "gis"
            (gis_dir / "glacier_mask.tif").write_text("", encoding="utf-8")
            (gis_dir / "glacier_mask_summary.json").write_text(
                json.dumps({"glacier_mode": "fractional_subgrid", "message": "分数栅格已生成"}, ensure_ascii=False),
                encoding="utf-8",
            )

            ok, message, count = check_glacier_mask({"冰川边界_shp": "glacier.shp"}, context)

        self.assertTrue(ok)
        self.assertEqual(message, "分数栅格已生成")
        self.assertEqual(count, 1)

    def test_check_glacier_elev_reports_ok_summary_with_weighted_mean(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            context = self._context(root)
            gis_dir = root / "gis"
            (gis_dir / "glacier_elev.tif").write_text("", encoding="utf-8")
            (gis_dir / "glacier_elev_summary.json").write_text(
                json.dumps(
                    {
                        "status": "ok",
                        "glacier_pixels_with_elev": 12,
                        "glacier_pixels_without_elev": 2,
                        "area_weighted_elev_mean": 4321.4,
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )

            ok, message, count = check_glacier_elev({"冰川边界_shp": "glacier.shp"}, context)

        self.assertTrue(ok)
        self.assertEqual(message, "已生成（冰川像元 12 个有高程，2 个缺失，面积加权均值 4321 m）")
        self.assertEqual(count, 12)

    def test_glacier_formal_requirements_keeps_compatibility_fields_and_notes(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            context = self._context(root, reference_count=3, dem_kind="0.1deg", objective_mode="flood_event")
            (root / "gis" / "dem.tif").write_text("", encoding="utf-8")

            result = glacier_formal_requirements(
                {"冰川边界_shp": "glacier.shp", "DEM_tif": "dem_0p1.tif"},
                context,
                "daily",
            )

        self.assertTrue(result["enabled"])
        self.assertEqual(result["objective_mode"], "flood_event")
        self.assertTrue(result["objective_is_event"])
        self.assertFalse(result["objective_is_multi"])
        self.assertEqual(result["reference_count"], 3)
        self.assertTrue(result["reference_ready"])
        self.assertEqual(result["dem_kind"], "0.1deg")
        self.assertTrue(result["glacier_elev_required"])
        self.assertFalse(result["glacier_elev_ready"])
        self.assertEqual(result["glacier_elev_message"], "未执行")
        self.assertTrue(result["formal_preconditions_ready"])
        self.assertEqual(result["blocking_reasons"], [])
        self.assertEqual(len(result["diagnostic_notes"]), 2)

    def test_glacier_elev_required_skips_1km_or_missing_glacier_shape(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            context = self._context(root, dem_kind="1km")

            self.assertFalse(glacier_elev_required({}, context))
            self.assertFalse(glacier_elev_required({"冰川边界_shp": "glacier.shp", "DEM_tif": "dem_1km.tif"}, context))


if __name__ == "__main__":
    unittest.main()
