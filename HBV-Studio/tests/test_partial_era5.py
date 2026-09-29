from __future__ import annotations

import importlib.util
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import numpy as np
import pandas as pd
import xarray as xr

from cds_chunked_download import download_era5_land_year_chunked, netcdf_covers_range
from 公共函数 import data_date_range
from services.data_prep import resolve_data_prep_step
from services.forcing_validation import summarize_nc_download_status
from services.forcing_validation import ForcingPreprocessStatusContext, check_hourly_temp_evap_status

ROOT = Path(__file__).resolve().parents[2]


def write_nc(path, times, variable="tp", values=None):
    times = pd.DatetimeIndex(times)
    values = np.ones(len(times)) if values is None else np.asarray(values)
    xr.Dataset({variable: (("time", "latitude", "longitude"), values[:, None, None])},
               coords={"time": times, "latitude": [30.0], "longitude": [90.0]}).to_netcdf(path)


class FakeClient:
    def __init__(self):
        self.requests = []

    def retrieve(self, dataset, request, target):
        self.requests.append(request)
        stamps = []
        for month in request["month"]:
            for day in request["day"]:
                try:
                    start = pd.Timestamp(f'{request["year"]}-{month}-{day}')
                except ValueError:
                    continue
                stamps.extend(start + pd.Timedelta(hours=int(hour[:2])) for hour in request["time"])
        write_nc(target, stamps)


class PartialEra5Tests(unittest.TestCase):
    def test_precipitation_only_hourly_processing_is_not_skipped(self):
        from services.raster_time_series import validate_tif_time_series
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            paths = {"raw_prec_era5_hourly_dir": root / "raw", "aligned_prec_era5_base_dir": root / "aligned"}
            context = ForcingPreprocessStatusContext(
                build_workspace_paths=lambda config: paths,
                build_profile_paths=lambda config, profile: paths,
                resolve_precip_source=lambda config, source: "era5",
                effective_precip_source=lambda source: source,
                count_matching=lambda *args: 0,
                validate_tif_time_series=validate_tif_time_series,
            )
            config = {"气象策略": {"温度来源": "custom_tif", "潜在蒸散发来源": "custom_tif"},
                      "时间": {"预热开始": "2025-05-10", "验证结束": "2025-05-10"}}
            self.assertFalse(check_hourly_temp_evap_status(config, context, profile="hourly")[0])
            paths["raw_prec_era5_hourly_dir"].mkdir()
            for stamp in pd.date_range("2025-05-10", periods=24, freq="h"):
                (paths["raw_prec_era5_hourly_dir"] / f"PREC_{stamp:%Y.%m.%d.%H}.tif").touch()
            self.assertTrue(check_hourly_temp_evap_status(config, context, profile="hourly")[0])
            config["时间"]["验证结束"] = "2025-05-11"
            self.assertFalse(check_hourly_temp_evap_status(config, context, profile="hourly")[0])

    def test_date_contract_and_dependencies(self):
        config = {"时间": {"开始年份": 2000, "结束年份": 2030, "率定开始": "2025-05-10", "率定结束": "2025-10-20"}}
        first, last = data_date_range(config)
        self.assertEqual((str(first), str(last)), ("2025-05-10", "2025-10-20"))
        step = resolve_data_prep_step({"id": "download_era5", "description": "ERA5"}, config)
        self.assertEqual(step["time_window"]["start"], "2025-05-10")
        self.assertEqual(resolve_data_prep_step({"id": "process_prec"}, config)["depends_on"], ["download_era5"])
        config["时间"]["率定结束"] = "2024-01-01"
        with self.assertRaises(ValueError):
            data_date_range(config)

    def test_exact_partial_edges_and_retained_coverage(self):
        with tempfile.TemporaryDirectory() as folder:
            output = Path(folder) / "era5_tp_2025.nc"
            client = FakeClient()
            kwargs = dict(variable="total_precipitation", year=2025, area=[31, 89, 29, 91], output_file=output, times=["00:00"], chunk_months=3)
            download_era5_land_year_chunked(client, start_date="2025-05-10", end_date="2025-06-05", **kwargs)
            self.assertEqual(client.requests[0]["month"], ["05"])
            self.assertEqual(client.requests[0]["day"][0], "10")
            self.assertEqual(client.requests[1]["day"][-1], "05")
            download_era5_land_year_chunked(client, start_date="2025-07-01", end_date="2025-07-02", **kwargs)
            self.assertTrue(netcdf_covers_range(output, "2025-05-10", "2025-06-05", ["00:00"]))
            self.assertTrue(netcdf_covers_range(output, "2025-07-01", "2025-07-02", ["00:00"]))

    def test_failed_partial_shard_cannot_satisfy_broader_retry(self):
        with tempfile.TemporaryDirectory() as folder:
            output = Path(folder) / "era5_tp_2025.nc"
            client = FakeClient()
            kwargs = dict(variable="total_precipitation", year=2025, area=[31, 89, 29, 91], output_file=output, times=["00:00"])
            with patch("cds_chunked_download.merge_netcdf_files", side_effect=RuntimeError("interrupted")):
                with self.assertRaises(RuntimeError):
                    download_era5_land_year_chunked(client, start_date="2025-05-10", end_date="2025-05-11", **kwargs)
            download_era5_land_year_chunked(client, start_date="2025-05-01", end_date="2025-05-20", **kwargs)
            self.assertEqual(len(client.requests), 2)
            self.assertTrue(netcdf_covers_range(output, "2025-05-01", "2025-05-20", ["00:00"]))

    def test_daily_readiness_requires_following_midnight(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            config = {"时间": {"预热开始": "2025-12-31", "验证结束": "2025-12-31"}}
            entries = [("precipitation", root, "era5_tp_*.nc")]
            write_nc(root / "era5_tp_2025.nc", pd.date_range("2025-12-31", periods=4, freq="6h"))
            self.assertFalse(summarize_nc_download_status(entries, config)[0])
            write_nc(root / "era5_tp_boundary_2026.nc", ["2026-01-01"])
            self.assertTrue(summarize_nc_download_status(entries, config)[0])
            config["时间"]["预热开始"] = "2025-12-30"
            self.assertFalse(summarize_nc_download_status(entries, config)[0])

    def test_daily_readiness_accepts_non_year_end_boundary(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            config = {"时间": {"预热开始": "2025-05-10", "验证结束": "2025-05-10"}}
            entries = [("precipitation", root, "era5_tp_*.nc")]
            write_nc(root / "era5_tp_2025.nc", list(pd.date_range("2025-05-10", periods=4, freq="6h")) + [pd.Timestamp("2025-05-11")])
            self.assertTrue(summarize_nc_download_status(entries, config)[0])

    def test_hourly_predecessor_and_partial_output(self):
        script = ROOT / "数据准备" / "06b_处理ERA5小时温度和蒸散发.py"
        spec = importlib.util.spec_from_file_location("partial_hourly", script)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            annual = root / "era5_tp_hourly_2025.nc"
            write_nc(root / "era5_tp_hourly_2024.nc", ["2024-12-31 23:00"], values=[0.023])
            write_nc(annual, pd.date_range("2025-01-01", periods=24, freq="h"), values=[0.024] + [i / 1000 for i in range(1, 24)])
            count = module.write_hourly_stack_from_yearly_nc(annual, variable_candidates=["tp"], out_dir=root / "tif", prefix="PREC", value_transform=lambda x: x, cumulative=True, scale=1000, date_start=pd.Timestamp("2025-01-01"), date_end=pd.Timestamp("2025-01-01 23:00"))
            self.assertEqual(count, 24)
            import rasterio
            with rasterio.open(root / "tif" / "PREC_2025.01.01.00.00.tif") as dataset:
                self.assertAlmostEqual(float(dataset.read(1)[0, 0]), 1.0, places=4)

    def test_daily_precipitation_entry_passes_dates_and_writes_only_window(self):
        from datetime import date
        from 公共函数 import load_legacy_module, patch_module
        module = load_legacy_module(ROOT / "公共" / "内部实现" / "处理ERA5.py")
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            raw = root / "data" / "raw" / "precipitation" / "era5"
            daily = raw.parent / "era5_daily"
            raw.mkdir(parents=True)
            daily.mkdir()
            write_nc(raw / "era5_tp_2025.nc", pd.date_range("2025-05-10", periods=12, freq="6h"), values=np.full(12, 0.005))
            patch_module(module, {"PROJECT_ROOT": str(root), "RAW_PREC_ERA5_DIR": str(raw), "PREC_ERA5_DAILY_DIR": str(daily),
                                  "START_DATE": date(2025, 5, 10), "END_DATE": date(2025, 5, 11)})
            self.assertEqual(module.process_precipitation(2025), 2)
            self.assertEqual(len(list(daily.glob("*.tif"))), 2)
            script = ROOT / "数据准备" / "07_处理降水数据.py"
            spec = importlib.util.spec_from_file_location("partial_daily_entry", script)
            entry = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(entry)
            config = {"时间": {"开始年份": 2000, "结束年份": 2030, "预热开始": "2025-05-10", "验证结束": "2025-05-11"}}
            with patch.object(entry, "read_config", return_value=config), patch.object(entry, "build_workspace_paths", return_value={"workspace_root": root, "raw_prec_era5_dir": raw, "raw_prec_era5_daily_dir": daily}), patch.object(entry, "ensure_workspace_dirs"), patch.object(entry, "old_script_path", return_value=ROOT / "公共" / "内部实现" / "处理ERA5.py"), patch.object(entry, "load_legacy_module", return_value=module), patch("sys.argv", [str(script)]):
                entry.main()
            self.assertEqual(module.YEARS, [2025])
            self.assertEqual(module.START_DATE, date(2025, 5, 10))


if __name__ == "__main__":
    unittest.main()
