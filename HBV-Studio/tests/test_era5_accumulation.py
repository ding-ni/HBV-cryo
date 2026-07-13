from __future__ import annotations

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

from era5_accumulation import (  # noqa: E402
    append_following_midnight,
    daily_totals_from_following_midnight,
    find_boundary_file,
)


class Era5AccumulationTests(unittest.TestCase):
    def test_cross_year_last_day_uses_following_midnight(self) -> None:
        current_times = pd.date_range("2024-12-30", "2024-12-31 18:00", freq="6h")
        current = xr.DataArray(
            np.arange(len(current_times), dtype="float64"),
            dims=("valid_time",),
            coords={"valid_time": current_times},
        )
        boundary = xr.DataArray(
            np.asarray([99.0]),
            dims=("valid_time",),
            coords={"valid_time": [pd.Timestamp("2025-01-01 00:00")]},
        )

        combined = append_following_midnight(
            current,
            boundary,
            boundary_time="2025-01-01 00:00",
        )
        daily = daily_totals_from_following_midnight(
            combined,
            start_date="2024-12-30",
            end_date="2024-12-31",
        )

        self.assertEqual(pd.DatetimeIndex(daily.time.values).tolist(), [
            pd.Timestamp("2024-12-30"),
            pd.Timestamp("2024-12-31"),
        ])
        np.testing.assert_allclose(daily.values, [4.0, 99.0])

    def test_missing_following_midnight_is_rejected(self) -> None:
        times = pd.date_range("2024-12-30", "2024-12-31 18:00", freq="6h")
        values = xr.DataArray(
            np.arange(len(times), dtype="float64"),
            dims=("time",),
            coords={"time": times},
        )

        with self.assertRaisesRegex(ValueError, "following 00:00 sample"):
            daily_totals_from_following_midnight(
                values,
                start_date="2024-12-30",
                end_date="2024-12-31",
            )

    def test_boundary_append_requires_exactly_one_target_sample(self) -> None:
        current = xr.DataArray(
            np.asarray([1.0]),
            dims=("time",),
            coords={"time": [pd.Timestamp("2024-12-31 18:00")]},
        )
        wrong_boundary = xr.DataArray(
            np.asarray([2.0]),
            dims=("time",),
            coords={"time": [pd.Timestamp("2025-01-01 06:00")]},
        )

        with self.assertRaisesRegex(ValueError, "exactly one"):
            append_following_midnight(
                current,
                wrong_boundary,
                boundary_time="2025-01-01 00:00",
            )

    def test_boundary_file_prefers_full_next_year_then_boundary_file(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            boundary = root / "era5_tp_boundary_2025.nc"
            boundary.write_bytes(b"boundary")
            self.assertEqual(find_boundary_file(root, "era5_tp", 2024), boundary)

            full_year = root / "era5_tp_2025.nc"
            full_year.write_bytes(b"full")
            self.assertEqual(find_boundary_file(root, "era5_tp", 2024), full_year)


if __name__ == "__main__":
    unittest.main()
