from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

import pandas as pd


STUDIO_DIR = Path(__file__).resolve().parents[1]
if str(STUDIO_DIR) not in sys.path:
    sys.path.insert(0, str(STUDIO_DIR))

from services.raster_time_series import (  # noqa: E402
    scan_tif_time_series,
    validate_tif_grid_alignment,
    validate_tif_time_series,
)


class RasterTimeSeriesServiceTests(unittest.TestCase):
    def test_scan_tif_time_series_counts_invalid_and_duplicate_names(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            data_dir = root / "prec"
            data_dir.mkdir()
            for name in [
                "prec_2021.01.01.tif",
                "duplicate_2021.01.01.tif",
                "prec_2021.01.03.tif",
                "bad_name.tif",
            ]:
                (data_dir / name).write_bytes(b"")

            result = scan_tif_time_series(data_dir)

        self.assertTrue(result["exists"])
        self.assertEqual(result["total_files"], 4)
        self.assertEqual(result["parseable_files"], 3)
        self.assertEqual(result["valid_time_steps"], 2)
        self.assertEqual(result["invalid_files"], ["bad_name.tif"])
        self.assertIn(pd.Timestamp("2021-01-01"), result["duplicate_timestamps"])

    def test_validate_tif_time_series_reports_missing_duplicate_invalid_and_out_of_range(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            data_dir = root / "temp"
            data_dir.mkdir()
            for name in [
                "temp_2021.01.01.tif",
                "same_2021.01.01.tif",
                "temp_2021.01.03.tif",
                "bad_name.tif",
            ]:
                (data_dir / name).write_bytes(b"")
            expected = pd.date_range("2021-01-01", "2021-01-02", freq="D")

            result = validate_tif_time_series("气温", data_dir, 24, expected, "率定窗口")

        self.assertFalse(result["ok"])
        self.assertEqual(result["missing_steps"], [pd.Timestamp("2021-01-02")])
        self.assertEqual(result["out_of_range_steps"], [pd.Timestamp("2021-01-03")])
        self.assertEqual(len(result["errors"]), 3)
        self.assertEqual(len(result["warnings"]), 1)
        self.assertIn("无法解析时间", result["errors"][0])
        self.assertIn("重复时间戳", result["errors"][1])
        self.assertIn("缺少 1 日", result["errors"][2])
        self.assertIn("落在率定窗口之外", result["warnings"][0])

    def test_validate_tif_time_series_reports_missing_directory(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            missing_dir = Path(temp_dir) / "missing"

            result = validate_tif_time_series("降水", missing_dir, 24)

        self.assertFalse(result["ok"])
        self.assertEqual(result["total_files"], 0)
        self.assertIn("目录不存在", result["errors"][0])

    def test_period_summary_uses_hydrological_daily_and_hourly_units(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            daily_dir = root / "daily"
            hourly_dir = root / "hourly"
            daily_dir.mkdir()
            hourly_dir.mkdir()
            for name in ("P_2025.01.01.tif", "P_2025.01.02.tif", "P_2025.01.03.tif"):
                (daily_dir / name).write_bytes(b"")
            for name in (
                "P_2025.01.01.08.tif",
                "P_2025.01.01.09.tif",
                "P_2025.01.01.10.tif",
            ):
                (hourly_dir / name).write_bytes(b"")

            daily = validate_tif_time_series("降水", daily_dir, 24)
            hourly = validate_tif_time_series("降水", hourly_dir, 1)

        self.assertEqual(daily["period_summary"], "2025-01-01 至 2025-01-03，共 3 日，逐日连续无缺测")
        self.assertEqual(
            hourly["period_summary"],
            "2025-01-01 08:00 至 2025-01-01 10:00，共 3 小时，逐小时连续无缺测",
        )

    def test_hourly_internal_gap_names_missing_hour(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            hourly_dir = Path(temp_dir)
            (hourly_dir / "P_2025.01.01.08.tif").write_bytes(b"")
            (hourly_dir / "P_2025.01.01.10.tif").write_bytes(b"")

            result = validate_tif_time_series("降水", hourly_dir, 1)

        self.assertFalse(result["ok"])
        self.assertEqual(result["period_summary"], "2025-01-01 08:00 至 2025-01-01 10:00，共 2 小时，内部缺少 1 小时")
        self.assertIn("缺少 1 小时，例如：2025-01-01 09:00", result["errors"][0])

    def test_validate_tif_grid_alignment_skips_missing_dem_or_directory(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            data_dir = root / "prec"
            data_dir.mkdir()
            (data_dir / "prec_2021.01.01.tif").write_bytes(b"")

            missing_dem = validate_tif_grid_alignment("降水", data_dir, root / "missing_dem.tif")
            missing_dir = validate_tif_grid_alignment("降水", root / "missing_dir", root / "missing_dem.tif")

        self.assertTrue(missing_dem["ok"])
        self.assertEqual(missing_dem["checked_files"], 0)
        self.assertIsNone(missing_dem["error"])
        self.assertTrue(missing_dir["ok"])
        self.assertEqual(missing_dir["checked_files"], 0)
        self.assertIsNone(missing_dir["error"])


if __name__ == "__main__":
    unittest.main()
