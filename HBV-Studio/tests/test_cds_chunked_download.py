# -*- coding: utf-8 -*-
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import numpy as np
import xarray as xr


class CdsChunkedDownloadTests(unittest.TestCase):
    def test_month_chunks(self) -> None:
        from cds_chunked_download import month_chunks

        self.assertEqual(month_chunks(1), [[m] for m in range(1, 13)])
        self.assertEqual(month_chunks(2)[0], [1, 2])
        self.assertEqual(month_chunks(12), [list(range(1, 13))])

    def test_is_cds_size_error(self) -> None:
        from cds_chunked_download import format_cds_size_error, is_cds_size_error

        self.assertTrue(is_cds_size_error("cost limits exceeded"))
        self.assertTrue(is_cds_size_error("Your request is too large"))
        self.assertFalse(is_cds_size_error("network timeout"))
        text = format_cds_size_error("cost limits exceeded")
        self.assertIn("too large", text.lower())
        self.assertIn("提示", text)

    def test_merge_netcdf_files_sorts_and_dedups(self) -> None:
        from cds_chunked_download import merge_netcdf_files

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            times_a = np.array(["2025-01-01T00", "2025-01-01T01"], dtype="datetime64[h]")
            times_b = np.array(["2025-01-01T01", "2025-01-01T02"], dtype="datetime64[h]")
            for name, times, values in [
                ("a.nc", times_a, [1.0, 2.0]),
                ("b.nc", times_b, [2.0, 3.0]),
            ]:
                ds = xr.Dataset(
                    {"tp": (("valid_time", "latitude", "longitude"), np.asarray(values)[:, None, None])},
                    coords={
                        "valid_time": times,
                        "latitude": [30.0],
                        "longitude": [90.0],
                    },
                )
                ds.to_netcdf(root / name)
            out = root / "era5_tp_hourly_2025.nc"
            merge_netcdf_files([root / "a.nc", root / "b.nc"], out)
            with xr.open_dataset(out) as merged:
                self.assertEqual(merged.sizes["valid_time"], 3)
                self.assertTrue(np.all(np.diff(merged["valid_time"].values) > np.timedelta64(0, "h")))

    def test_download_chunked_uses_monthly_requests(self) -> None:
        from cds_chunked_download import download_era5_land_year_chunked

        calls: list[dict] = []

        class FakeClient:
            def retrieve(self, dataset, request, target):
                calls.append({"dataset": dataset, "request": request, "target": target})
                times = np.array(
                    [f"2025-{request['month'][0]}-{day:02d}T00" for day in range(1, 3)],
                    dtype="datetime64[h]",
                )
                ds = xr.Dataset(
                    {"t2m": (("valid_time", "latitude", "longitude"), np.ones((len(times), 1, 1)))},
                    coords={"valid_time": times, "latitude": [30.0], "longitude": [91.0]},
                )
                Path(target).parent.mkdir(parents=True, exist_ok=True)
                ds.to_netcdf(target)

        with tempfile.TemporaryDirectory() as temp_dir:
            out = Path(temp_dir) / "era5_t2m_hourly_2025.nc"
            download_era5_land_year_chunked(
                FakeClient(),
                variable="2m_temperature",
                year=2025,
                area=[30, 90, 28, 93],
                output_file=out,
                times=[f"{h:02d}:00" for h in range(24)],
                chunk_months=1,
            )
            self.assertTrue(out.exists())
            self.assertEqual(len(calls), 12)
            self.assertEqual(calls[0]["request"]["month"], ["01"])
            self.assertEqual(calls[-1]["request"]["month"], ["12"])
            self.assertEqual(len(calls[0]["request"]["time"]), 24)


class HourlyYearlyNcFilterTests(unittest.TestCase):
    def test_yearly_hourly_filter_ignores_month_shards(self) -> None:
        from services.forcing_validation import _yearly_hourly_nc_files

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (root / "era5_t2m_hourly_2025.nc").write_bytes(b"x" * 10)
            (root / "era5_t2m_hourly_2025_01.nc").write_bytes(b"x" * 10)
            (root / "era5_t2m_hourly_2025_01-02.nc").write_bytes(b"x" * 10)
            files = _yearly_hourly_nc_files(root, "era5_t2m_hourly")
            self.assertEqual([path.name for path in files], ["era5_t2m_hourly_2025.nc"])


if __name__ == "__main__":
    unittest.main()
