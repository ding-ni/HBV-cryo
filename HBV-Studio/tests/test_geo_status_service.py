from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path
from typing import Any


STUDIO_DIR = Path(__file__).resolve().parents[1]
if str(STUDIO_DIR) not in sys.path:
    sys.path.insert(0, str(STUDIO_DIR))

from services.geo_status import (  # noqa: E402
    GeoStatusContext,
    check_clip_dem,
    check_elevation_zone,
    check_flow_acc,
    check_masked_flow,
)


class GeoStatusServiceTests(unittest.TestCase):
    def _context(self, gis_dir: Path, calls: list[tuple[Any, ...]] | None = None) -> GeoStatusContext:
        call_log = calls if calls is not None else []

        def current_profile(config: dict[str, Any]) -> str:
            call_log.append(("profile",))
            return "daily"

        def build_profile_paths(config: dict[str, Any], profile: str) -> dict[str, Any]:
            call_log.append(("paths", profile))
            return {"gis_dir": gis_dir}

        def workspace_dem_path(raw_gis_dir: Path, **kwargs: Any) -> Path:
            call_log.append(("dem", raw_gis_dir, kwargs.get("prefer")))
            return Path(raw_gis_dir) / "dem.tif"

        return GeoStatusContext(
            current_profile=current_profile,
            build_profile_paths=build_profile_paths,
            workspace_dem_path=workspace_dem_path,
            configured_dem_kind=lambda config: "1km",
        )

    def test_check_clip_dem_reports_dem_generation_status(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            gis_dir = Path(temp_dir)
            (gis_dir / "dem.tif").write_text("ok", encoding="utf-8")
            calls: list[tuple[Any, ...]] = []

            ready, message, count = check_clip_dem({}, self._context(gis_dir, calls))

        self.assertTrue(ready)
        self.assertEqual(message, "已生成 DEM")
        self.assertEqual(count, 1)
        self.assertEqual(calls, [("profile",), ("paths", "daily"), ("dem", gis_dir, "1km")])

    def test_check_flow_acc_and_masked_flow_report_missing_and_existing_files(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            gis_dir = Path(temp_dir)
            context = self._context(gis_dir)
            (gis_dir / "flow_accumulation_masked.tif").write_text("ok", encoding="utf-8")

            flow_ready, flow_message, flow_count = check_flow_acc({}, context)
            masked_ready, masked_message, masked_count = check_masked_flow({}, context)

        self.assertFalse(flow_ready)
        self.assertEqual(flow_message, "尚未生成")
        self.assertEqual(flow_count, 0)
        self.assertTrue(masked_ready)
        self.assertEqual(masked_message, "已生成流域掩膜")
        self.assertEqual(masked_count, 1)

    def test_check_elevation_zone_accepts_low_or_mid_plus_high(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            gis_dir = Path(temp_dir)
            context = self._context(gis_dir)
            (gis_dir / "elevation_zone_mid.tif").write_text("ok", encoding="utf-8")
            (gis_dir / "elevation_zone_high.tif").write_text("ok", encoding="utf-8")

            ready, message, count = check_elevation_zone({}, context)

        self.assertTrue(ready)
        self.assertEqual(message, "高程分区文件 2/2")
        self.assertEqual(count, 2)

    def test_check_elevation_zone_reports_partial_count(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            gis_dir = Path(temp_dir)
            context = self._context(gis_dir)
            (gis_dir / "elevation_zone_low.tif").write_text("ok", encoding="utf-8")

            ready, message, count = check_elevation_zone({}, context)

        self.assertFalse(ready)
        self.assertEqual(message, "高程分区文件 1/2")
        self.assertEqual(count, 1)


if __name__ == "__main__":
    unittest.main()
