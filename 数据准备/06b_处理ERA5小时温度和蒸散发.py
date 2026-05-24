# -*- coding: utf-8 -*-
from __future__ import annotations

import argparse
import contextlib
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import rasterio
import xarray as xr
from rasterio.crs import CRS

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "公共"))

from 公共函数 import build_workspace_paths, ensure_workspace_dirs, example_config_path, load_legacy_module, old_script_path, open_netcdf_dataset_safe, read_config, year_range  # type: ignore


def time_dim_name(arr: xr.DataArray) -> str:
    return "valid_time" if "valid_time" in arr.dims else "time"


def rename_time_dim(arr: xr.DataArray) -> xr.DataArray:
    time_dim = time_dim_name(arr)
    if time_dim != "time":
        return arr.rename({time_dim: "time"})
    return arr


def coords_of(arr: xr.DataArray) -> tuple[np.ndarray, np.ndarray]:
    lons = arr.longitude.values if "longitude" in arr.coords else arr.lon.values
    lats = arr.latitude.values if "latitude" in arr.coords else arr.lat.values
    return np.asarray(lons), np.asarray(lats)


def orient_grid(data: np.ndarray, lons: np.ndarray, lats: np.ndarray) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    out = np.asarray(data)
    lon_out = np.asarray(lons)
    lat_out = np.asarray(lats)
    if lat_out.size > 1 and lat_out[0] < lat_out[-1]:
        out = np.flip(out, axis=0)
        lat_out = lat_out[::-1]
    if lon_out.size > 1 and lon_out[0] > lon_out[-1]:
        out = np.flip(out, axis=1)
        lon_out = lon_out[::-1]
    return out, lon_out, lat_out


def output_profile(lons: np.ndarray, lats: np.ndarray) -> dict[str, object]:
    res_x = abs(lons[1] - lons[0]) if len(lons) > 1 else 0.1
    res_y = abs(lats[1] - lats[0]) if len(lats) > 1 else 0.1
    transform = rasterio.transform.from_bounds(
        lons.min() - res_x / 2,
        lats.min() - res_y / 2,
        lons.max() + res_x / 2,
        lats.max() + res_y / 2,
        len(lons),
        len(lats),
    )
    return {
        "driver": "GTiff",
        "height": len(lats),
        "width": len(lons),
        "count": 1,
        "dtype": "float32",
        "crs": CRS.from_epsg(4326),
        "transform": transform,
        "nodata": -9999.0,
        "compress": "lzw",
    }


def hourly_increments_from_cumulative(arr: xr.DataArray) -> xr.DataArray:
    accum = rename_time_dim(arr)
    values = np.asarray(accum.values, dtype=np.float64)
    increments = np.full(values.shape, np.nan, dtype=np.float32)
    times = pd.DatetimeIndex(pd.to_datetime(accum["time"].values))
    if values.shape[0] == 0:
        return accum.astype("float32")

    for idx, ts in enumerate(times):
        current = values[idx]
        if idx == 0:
            delta = np.zeros_like(current) if ts.hour == 0 else np.clip(current, 0.0, None)
        else:
            prev_ts = times[idx - 1]
            prev = values[idx - 1]
            gap = ts - prev_ts
            if ts.hour == 0 and gap <= pd.Timedelta(hours=1.5):
                delta = current - prev
            elif ts.hour == 1 or prev_ts.normalize() != ts.normalize() or gap > pd.Timedelta(hours=1.5):
                delta = current
            else:
                delta = current - prev
            delta = np.where(np.isfinite(delta), np.clip(delta, 0.0, None), np.nan)
        increments[idx] = delta.astype(np.float32)

    return xr.DataArray(increments, coords=accum.coords, dims=accum.dims, attrs=accum.attrs)


def write_hourly_stack(arr: xr.DataArray, out_dir: Path, prefix: str, value_transform, *, overwrite: bool = False) -> int:
    out_dir.mkdir(parents=True, exist_ok=True)
    series = rename_time_dim(arr)
    lons, lats = coords_of(series)
    _, lons_out, lats_out = orient_grid(np.zeros((len(lats), len(lons)), dtype=np.float32), lons, lats)
    profile = output_profile(lons_out, lats_out)
    count = 0
    for i, time_value in enumerate(series["time"].values):
        ts = np.datetime64(time_value).astype("datetime64[m]")
        date = str(ts).replace("-", ".").replace("T", ".").replace(":", ".")
        out_path = out_dir / f"{prefix}_{date}.tif"
        if (not overwrite) and out_path.exists():
            count += 1
            continue
        data = value_transform(series.isel(time=i).values)
        data, _, _ = orient_grid(data, lons, lats)
        data = np.where(np.isfinite(data), data, profile["nodata"]).astype("float32")
        with rasterio.open(out_path, "w", **profile) as dst:
            dst.write(data, 1)
        count += 1
    return count


def prepare_daily_et_module(config: dict[str, object]):
    module = load_legacy_module(old_script_path(config, "scripts", "02g_calculate_fao56_et.py"))
    return module


def wind_10m_to_2m(u10: np.ndarray) -> np.ndarray:
    return u10 * 4.87 / np.log(67.8 * 10 - 5.42)


def rh_from_dewpoint(t_air: np.ndarray, t_dew: np.ndarray) -> np.ndarray:
    es = 6.112 * np.exp(17.67 * t_air / (t_air + 243.5))
    e = 6.112 * np.exp(17.67 * t_dew / (t_dew + 243.5))
    rh = 100 * e / np.maximum(es, 1e-6)
    return np.clip(rh, 0, 100)


def build_hourly_et(year: int, paths: dict[str, Path], config: dict[str, object], *, overwrite: bool = False) -> int:
    temp_file = paths["raw_temp_dir"] / f"era5_t2m_hourly_{year}.nc"
    solar_file = paths["raw_solar_dir"] / f"era5_ssrd_hourly_{year}.nc"
    u10_file = paths["raw_wind_dir"] / f"era5_u10_hourly_{year}.nc"
    v10_file = paths["raw_wind_dir"] / f"era5_v10_hourly_{year}.nc"
    dew_file = paths["raw_dewpoint_dir"] / f"era5_d2m_hourly_{year}.nc"
    for file_path in [temp_file, solar_file, u10_file, v10_file, dew_file]:
        if not file_path.exists():
            raise FileNotFoundError(file_path)

    et_module = prepare_daily_et_module(config)

    with contextlib.ExitStack() as stack:
        ds_temp = stack.enter_context(open_netcdf_dataset_safe(temp_file))
        ds_solar = stack.enter_context(open_netcdf_dataset_safe(solar_file))
        ds_u10 = stack.enter_context(open_netcdf_dataset_safe(u10_file))
        ds_v10 = stack.enter_context(open_netcdf_dataset_safe(v10_file))
        ds_dew = stack.enter_context(open_netcdf_dataset_safe(dew_file))
        t2m = rename_time_dim(ds_temp["t2m"] - 273.15)
        ssrd_hourly = hourly_increments_from_cumulative(ds_solar["ssrd"] / 1e6)
        u10 = rename_time_dim(ds_u10["u10"])
        v10 = rename_time_dim(ds_v10["v10"])
        d2m = rename_time_dim(ds_dew["d2m"] - 273.15)

        t_mean = t2m.resample(time="1D").mean()
        t_min = t2m.resample(time="1D").min()
        t_max = t2m.resample(time="1D").max()
        rs_daily = ssrd_hourly.resample(time="1D").sum().reindex(time=t_mean["time"].values)
        u10_mean = u10.resample(time="1D").mean().reindex(time=t_mean["time"].values)
        v10_mean = v10.resample(time="1D").mean().reindex(time=t_mean["time"].values)
        d2m_mean = d2m.resample(time="1D").mean().reindex(time=t_mean["time"].values)

        lons, lats = coords_of(t_mean)
        _, lons_out, lats_out = orient_grid(np.zeros((len(lats), len(lons)), dtype=np.float32), lons, lats)
        lon_grid, lat_grid = np.meshgrid(lons, lats)
        profile = output_profile(lons_out, lats_out)
        out_dir = paths["raw_evap_hourly_dir"]
        out_dir.mkdir(parents=True, exist_ok=True)

        daily_times = t_mean["time"].values
        written = 0
        for i, day_time in enumerate(daily_times):
            date = pd.Timestamp(day_time)
            doy = int(date.strftime("%j"))
            day_mask = (pd.to_datetime(ssrd_hourly["time"].values).normalize() == date.normalize())
            hourly_times = pd.to_datetime(ssrd_hourly["time"].values[day_mask])
            out_paths = [out_dir / f"ET_{ts.strftime('%Y.%m.%d.%H')}.tif" for ts in hourly_times]
            if (not overwrite) and out_paths and all(path.exists() for path in out_paths):
                written += len(out_paths)
                continue

            t_m = t_mean.isel(time=i).values
            t_mn = t_min.isel(time=i).values
            t_mx = t_max.isel(time=i).values
            u2_d = wind_10m_to_2m(np.sqrt(u10_mean.isel(time=i).values ** 2 + v10_mean.isel(time=i).values ** 2))
            rh_d = rh_from_dewpoint(t_m, d2m_mean.isel(time=i).values)
            rs_d = rs_daily.isel(time=i).values
            daily_et = et_module.calculate_et0_fao56(
                t_mean=t_m,
                t_min=t_mn,
                t_max=t_mx,
                rh_mean=rh_d,
                u2=u2_d,
                rs=rs_d,
                lat=lat_grid,
                doy=doy,
                elevation=float(config.get("FAO56平均海拔_m", 4500.0)),
            )

            hourly_rs = ssrd_hourly.isel(time=np.where(day_mask)[0]).values
            if hourly_rs.ndim == 2:
                hourly_rs = hourly_rs[np.newaxis, ...]
            weights = np.clip(hourly_rs, 0.0, None)
            weight_sum = np.sum(weights, axis=0)
            fallback = np.full_like(weights, 1.0 / max(weights.shape[0], 1))
            norm_weights = np.where(weight_sum > 0, weights / np.maximum(weight_sum, 1e-6), fallback)

            for j, ts in enumerate(hourly_times):
                out_path = out_paths[j]
                if (not overwrite) and out_path.exists():
                    written += 1
                    continue
                hourly_et = np.where(np.isfinite(daily_et), np.clip(daily_et * norm_weights[j], 0.0, None), profile["nodata"])
                hourly_et, _, _ = orient_grid(hourly_et, lons, lats)
                with rasterio.open(out_path, "w", **profile) as dst:
                    dst.write(np.where(np.isfinite(hourly_et), hourly_et, profile["nodata"]).astype("float32"), 1)
                written += 1
        return written


def main() -> None:
    parser = argparse.ArgumentParser(description="处理小时尺度 ERA5 温度与蒸散发。")
    parser.add_argument("--配置", "--config", dest="配置", default=str(example_config_path()))
    parser.add_argument("--覆盖", "--overwrite", dest="覆盖", action="store_true")
    args = parser.parse_args()

    config = read_config(args.配置)
    paths = build_workspace_paths(config)
    ensure_workspace_dirs(paths)
    years = list(year_range(config))

    temp_count = 0
    for year in years:
        nc_file = paths["raw_temp_dir"] / f"era5_t2m_hourly_{year}.nc"
        if not nc_file.exists():
            continue
        with open_netcdf_dataset_safe(nc_file) as ds:
            temp_count += write_hourly_stack(
                rename_time_dim(ds["t2m"] - 273.15),
                paths["raw_temp_hourly_dir"],
                "T",
                lambda values: values,
                overwrite=bool(args.覆盖),
            )

    evap_count = 0
    for year in years:
        evap_count += build_hourly_et(year, paths, config, overwrite=bool(args.覆盖))

    print(f"[完成] 小时温度文件数: {temp_count}")
    print(f"[完成] 小时蒸散发文件数: {evap_count}")


if __name__ == "__main__":
    main()
