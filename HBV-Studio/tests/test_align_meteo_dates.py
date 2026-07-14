from __future__ import annotations

import importlib.util
import json
import tempfile
import unittest
from datetime import datetime
from pathlib import Path

import numpy as np


PROJECT_ROOT = Path(__file__).resolve().parents[2]
SCRIPT_PATH = PROJECT_ROOT / "数据准备" / "08_对齐并裁剪气象数据.py"
SPEC = importlib.util.spec_from_file_location("align_meteo_dates_test", SCRIPT_PATH)
assert SPEC and SPEC.loader
align_meteo = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(align_meteo)


class AlignMeteoDateTests(unittest.TestCase):
    def test_parses_supported_daily_raster_name_styles(self) -> None:
        expected = datetime(2025, 1, 2)

        self.assertEqual(align_meteo.parse_raster_date("2025-01-02_precipitation_amount.tif"), expected)
        self.assertEqual(align_meteo.parse_raster_date("T_2025.01.02.tif"), expected)
        self.assertEqual(align_meteo.parse_raster_date("ET_2025_01_02.tif"), expected)
        self.assertIsNone(align_meteo.parse_raster_date("precipitation_without_date.tif"))

    def test_collects_v2_hyphenated_precipitation_names(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (root / "2025-01-01_precipitation_amount.tif").touch()
            (root / "2025-01-02_precipitation_amount.tif").touch()

            records = align_meteo.collect_files(root, datetime(2025, 1, 1), datetime(2025, 12, 31))

            self.assertEqual([item[0] for item in records], [datetime(2025, 1, 1), datetime(2025, 1, 2)])

    def test_rejects_duplicate_dates_across_name_styles(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (root / "P_2025.01.01.tif").touch()
            (root / "2025-01-01_precipitation_amount.tif").touch()

            with self.assertRaisesRegex(RuntimeError, "重复日期"):
                align_meteo.collect_files(root, datetime(2025, 1, 1), datetime(2025, 12, 31))

    def test_missing_daily_files_fails_before_mask_alignment(self) -> None:
        with self.assertRaisesRegex(FileNotFoundError, "YYYY-MM-DD"):
            align_meteo.require_records([], "降水", Path("empty"))

    def test_processing_window_uses_actual_warmup_and_evaluation_dates(self) -> None:
        start, end = align_meteo.resolve_processing_window(
            {
                "开始年份": 2025,
                "结束年份": 2025,
                "预热开始": "2025-01-01",
                "预热结束": "2025-05-31",
                "率定开始": "2025-06-01",
                "率定结束": "2025-09-10",
                "验证开始": "2025-09-11",
                "验证结束": "2025-10-31",
            }
        )

        self.assertEqual(start, datetime(2025, 1, 1))
        self.assertEqual(end, datetime(2025, 10, 31))

    def test_mask_dates_must_match_but_not_depend_on_precipitation_mask_values(self) -> None:
        basin_mask = np.asarray([[True, True], [False, True]])
        masks = {"2025.01.01": basin_mask.copy()}

        dates = align_meteo.validate_mask_dates(masks, masks.copy(), masks.copy())

        self.assertEqual(dates, ["2025.01.01"])
        with self.assertRaisesRegex(RuntimeError, "日期不一致"):
            align_meteo.validate_mask_dates(masks, {}, masks.copy())

    def test_resampling_uses_area_average_for_precipitation_only(self) -> None:
        self.assertEqual(align_meteo.resampling_for_series("PREC"), align_meteo.Resampling.average)
        self.assertEqual(align_meteo.resampling_for_series("TEMP"), align_meteo.Resampling.bilinear)
        self.assertEqual(align_meteo.resampling_for_series("EVAP"), align_meteo.Resampling.bilinear)

    def test_writes_daily_forcing_manifest_for_aligned_series(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            source_records = {}
            source_dirs = {}
            target_dirs = {}
            for key in ("prec", "temp", "evap"):
                source_dir = root / f"source_{key}"
                target_dir = root / f"target_{key}"
                source_dir.mkdir()
                target_dir.mkdir()
                first = source_dir / f"{key}_2025-01-01.tif"
                second = source_dir / f"{key}_2025-01-02.tif"
                first.write_bytes(f"{key}-first".encode("ascii"))
                second.write_bytes(f"{key}-second".encode("ascii"))
                source_records[key] = [
                    (datetime(2025, 1, 1), first),
                    (datetime(2025, 1, 2), second),
                ]
                source_dirs[key] = source_dir
                target_dirs[key] = target_dir

            manifest_path = root / "daily_forcing_manifest.json"
            align_meteo.write_daily_forcing_manifest(
                manifest_path=manifest_path,
                start_date=datetime(2025, 1, 1),
                end_date=datetime(2025, 1, 2),
                date_count=2,
                source_records=source_records,
                source_dirs=source_dirs,
                target_dirs=target_dirs,
                dem_file=root / "dem.tif",
                dem_profile={"crs": "EPSG:4490", "transform": (1, 0, 90, 0, -1, 30)},
                dem_shape=(2, 3),
            )

            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            self.assertEqual(manifest["schema"], "hbv_cryo_daily_forcing_manifest_v1")
            self.assertEqual(manifest["start_date"], "2025-01-01")
            self.assertEqual(manifest["end_date"], "2025-01-02")
            self.assertEqual(manifest["date_count"], 2)
            self.assertEqual(manifest["precipitation"]["output_unit"], "mm/day")
            self.assertEqual(manifest["precipitation"]["day_basis"], "product_calendar_day")
            self.assertEqual(manifest["source_series"]["prec"]["file_count"], 2)
            self.assertEqual(manifest["grid"]["width"], 3)
            self.assertTrue(manifest["qc"]["active_masks_equal"])


if __name__ == "__main__":
    unittest.main()
