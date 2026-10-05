from __future__ import annotations

import hashlib
import json
import sys
import tempfile
import unittest
from pathlib import Path

import numpy as np
import pandas as pd
import xarray as xr


PROJECT_ROOT = Path(__file__).resolve().parents[2]
PUBLIC_DIR = PROJECT_ROOT / "公共"
if str(PUBLIC_DIR) not in sys.path:
    sys.path.insert(0, str(PUBLIC_DIR))

from era5_quality import Era5QualityError, audit_era5_dataarray  # noqa: E402
from era5_ssrd_repair import repair_ssrd_single_point  # noqa: E402


def make_grid(values: np.ndarray, times: pd.DatetimeIndex) -> xr.DataArray:
    return xr.DataArray(
        values,
        dims=("time", "latitude", "longitude"),
        coords={
            "time": times,
            "latitude": [29.5, 29.6, 29.7],
            "longitude": [92.1, 92.2, 92.3],
        },
        name="ssrd",
    )


class Era5QualityTests(unittest.TestCase):
    def test_valid_data_passes_and_records_source_hash(self) -> None:
        times = pd.date_range("2025-01-01", periods=3, freq="h")
        values = np.ones((3, 3, 3), dtype="float64")
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            source = root / "source.nc"
            source.write_bytes(b"quality-audit-fixture")
            report_path = root / "quality.json"
            report = audit_era5_dataarray(
                make_grid(values, times),
                variable="ssrd",
                source_paths=[source],
                report_path=report_path,
            )

            self.assertEqual(report["status"], "passed")
            self.assertEqual(report["missing"]["count"], 0)
            self.assertEqual(
                report["source_files"][0]["sha256"],
                hashlib.sha256(source.read_bytes()).hexdigest(),
            )
            self.assertEqual(json.loads(report_path.read_text(encoding="utf-8"))["schema"], "hbv_era5_quality_report_v1")

    def test_nan_inf_and_fill_value_are_blocked_and_reported(self) -> None:
        times = pd.date_range("2025-01-01", periods=3, freq="h")
        values = np.ones((3, 3, 3), dtype="float64")
        values[0, 0, 0] = np.nan
        values[1, 0, 1] = np.inf
        values[2, 0, 2] = -9999.0
        arr = make_grid(values, times)
        arr.attrs["_FillValue"] = -9999.0

        with tempfile.TemporaryDirectory() as temp_dir:
            report_path = Path(temp_dir) / "quality.json"
            with self.assertRaises(Era5QualityError) as context:
                audit_era5_dataarray(arr, variable="ssrd", report_path=report_path)
            self.assertIn("缺测", str(context.exception))
            report = json.loads(report_path.read_text(encoding="utf-8"))
            self.assertEqual(report["status"], "failed")
            self.assertEqual(report["missing"]["count"], 3)

    def test_duplicate_time_and_internal_gap_are_blocked(self) -> None:
        times = pd.DatetimeIndex(
            ["2025-01-01 00:00", "2025-01-01 01:00", "2025-01-01 01:00", "2025-01-01 03:00"]
        )
        with self.assertRaises(Era5QualityError) as context:
            audit_era5_dataarray(make_grid(np.ones((4, 3, 3)), times), variable="t2m")
        self.assertIn("重复", str(context.exception))
        self.assertTrue(any("重复" in item for item in context.exception.report["errors"]))

        times_with_gap = pd.date_range("2025-01-01", periods=4, freq="h").delete(2)
        with self.assertRaises(Era5QualityError) as context:
            audit_era5_dataarray(make_grid(np.ones((3, 3, 3)), times_with_gap), variable="t2m")
        self.assertIn("内部缺口", str(context.exception))

    def test_missing_coordinates_and_required_time_are_blocked(self) -> None:
        times = pd.date_range("2025-01-01", periods=2, freq="h")
        arr = xr.DataArray(
            np.ones((2, 2, 2)),
            dims=("time", "y", "x"),
            coords={"time": times, "y": [29.5, 29.6], "x": [92.1, 92.2]},
        )
        with self.assertRaises(Era5QualityError) as context:
            audit_era5_dataarray(
                arr,
                variable="tp",
                required_times=["2025-01-01 02:00"],
            )
        self.assertIn("缺少longitude坐标", str(context.exception))
        self.assertIn("required_time_missing", context.exception.report)

    def test_whitelisted_ssrd_gap_is_repaired_before_audit(self) -> None:
        times = pd.date_range("2023-01-28 00:00", periods=3, freq="h")
        values = np.full((3, 3, 3), 100.0, dtype="float64")
        values[1, 1, 1] = np.nan
        values[1, 0, 0] = 10.0
        values[1, 0, 2] = 20.0
        values[1, 2, 0] = 30.0
        values[1, 2, 2] = 40.0
        repaired = repair_ssrd_single_point(make_grid(values, times))
        self.assertAlmostEqual(float(repaired.isel(time=1, latitude=1, longitude=1)), 25.0)
        report = audit_era5_dataarray(repaired, variable="ssrd")
        self.assertEqual(report["status"], "passed")
        self.assertEqual(report["missing"]["count"], 0)

    def test_unknown_ssrd_gap_is_not_silently_repaired(self) -> None:
        times = pd.date_range("2025-01-01", periods=3, freq="h")
        values = np.ones((3, 3, 3), dtype="float64")
        values[1, 0, 0] = np.nan
        with tempfile.TemporaryDirectory() as temp_dir:
            report_path = Path(temp_dir) / "unknown_ssrd_quality.json"
            with self.assertRaises(Era5QualityError):
                audit_era5_dataarray(
                    make_grid(values, times),
                    variable="ssrd",
                    report_path=report_path,
                )
            report = json.loads(report_path.read_text(encoding="utf-8"))
            self.assertEqual(report["missing"]["count"], 1)
            self.assertEqual(report["status"], "failed")


if __name__ == "__main__":
    unittest.main()
