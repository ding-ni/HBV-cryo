# -*- coding: utf-8 -*-
"""
Generate daily glacier melt rasters (mm/d) using ERA5 ssrd + temperature.

Outputs:
  数据/模型输入/冰川融水/GM_YYYY.MM.DD.tif
"""
import argparse
import os
import re
import sys
from datetime import datetime

import numpy as np
import pandas as pd
import rasterio
from rasterio.transform import from_origin
from rasterio.warp import reproject, Resampling
import xarray as xr

_PUBLIC_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if _PUBLIC_DIR not in sys.path:
    sys.path.insert(0, _PUBLIC_DIR)
from 公共 import 公共函数 as _common  # noqa: E402


def _prefer_existing_path(*paths):
    for path in paths:
        if os.path.exists(path):
            return path
    return paths[0]


PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "运行目录", "默认流域"))
DATA_ROOT = _prefer_existing_path(os.path.join(PROJECT_ROOT, "数据"), os.path.join(PROJECT_ROOT, "data"))
ALIGNED_ROOT = _prefer_existing_path(os.path.join(DATA_ROOT, "模型输入"), os.path.join(DATA_ROOT, "aligned_masked"))
RAW_ROOT = _prefer_existing_path(os.path.join(DATA_ROOT, "原始气象"), os.path.join(DATA_ROOT, "raw"))
GIS_ROOT = _prefer_existing_path(os.path.join(DATA_ROOT, "地理数据"), os.path.join(DATA_ROOT, "gis"))
TEMP_DIR = _prefer_existing_path(os.path.join(ALIGNED_ROOT, "气温"), os.path.join(ALIGNED_ROOT, "temp"))
RAD_DIR = _prefer_existing_path(os.path.join(RAW_ROOT, "太阳辐射"), os.path.join(RAW_ROOT, "solar_radiation"))
OUT_DIR = _prefer_existing_path(os.path.join(ALIGNED_ROOT, "冰川融水"), os.path.join(ALIGNED_ROOT, "glacier_melt"))
DEM_PATH = str(_common.resolve_workspace_dem_path(GIS_ROOT))
FLOW_ACC_PATH = os.path.join(GIS_ROOT, "flow_accumulation_masked.tif")
GLACIER_MASK_PATH = os.path.join(GIS_ROOT, "glacier_mask.tif")
GLACIER_FRACTION_PATH = os.path.join(GIS_ROOT, "glacier_fraction.tif")

# Glacier melt parameters
TTM = 0.0           # 温度融化阈值 (°C)
TTM_RAD = -5.0      # 辐射融化阈值 (°C) - 低于此温度不考虑辐射融化
CFMAX_GLACIER = 5.5 # 度日因子 (mm/°C/d)
RAD_COEF = 0.002    # 辐射系数 (降低以减少辐射融化贡献)

NODATA = -9999.0
OVERWRITE = True


def time_dim_name(arr):
    return "valid_time" if "valid_time" in arr.dims else "time"


def rename_time_dim(arr):
    time_dim = time_dim_name(arr)
    if time_dim != "time":
        return arr.rename({time_dim: "time"})
    return arr


def coords_of(arr):
    lons = arr.longitude.values if "longitude" in arr.coords else arr.lon.values
    lats = arr.latitude.values if "latitude" in arr.coords else arr.lat.values
    return np.asarray(lons), np.asarray(lats)


def orient_grid(data, lons, lats):
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


def daily_totals_from_cumulative(arr):
    accum = rename_time_dim(arr)
    times = pd.DatetimeIndex(pd.to_datetime(accum["time"].values))
    if times.empty:
        return accum.isel(time=slice(0, 0))

    available_days = sorted({ts.normalize() for ts in times})
    available_day_set = set(available_days)
    selected_indices = {}
    fallback_indices = {}

    for idx, ts in enumerate(times):
        day = ts.normalize()
        fallback_indices[day] = idx
        prev_day = day - pd.Timedelta(days=1)
        if ts.hour == 0 and prev_day in available_day_set:
            selected_indices[prev_day] = idx

    slices = []
    output_days = []
    for day in available_days:
        idx = selected_indices.get(day, fallback_indices.get(day))
        if idx is None:
            continue
        slices.append(accum.isel(time=idx))
        output_days.append(day)

    if not slices:
        return accum.isel(time=slice(0, 0))
    return xr.concat(slices, dim=pd.Index(pd.DatetimeIndex(output_days), name="time")).sortby("time")


def parse_args():
    parser = argparse.ArgumentParser(description="Generate glacier melt rasters from ERA5 ssrd.")
    parser.add_argument("--start-year", type=int, default=None, help="Start year (inclusive).")
    parser.add_argument("--end-year", type=int, default=None, help="End year (inclusive).")
    parser.add_argument("--overwrite", dest="overwrite", action="store_true")
    parser.add_argument("--no-overwrite", dest="overwrite", action="store_false")
    parser.set_defaults(overwrite=OVERWRITE)
    return parser.parse_args()


def parse_date_from_name(name):
    match = re.search(r"\d{4}\.\d{2}\.\d{2}", name)
    if not match:
        return None
    return datetime.strptime(match.group(0), "%Y.%m.%d").date()


def build_src_transform(lats, lons):
    lat_res = abs(float(lats[1] - lats[0]))
    lon_res = abs(float(lons[1] - lons[0]))
    west = float(lons.min()) - lon_res / 2.0
    north = float(lats.max()) + lat_res / 2.0
    return from_origin(west, north, lon_res, lat_res)


def load_daily_radiation(year):
    nc_path = os.path.join(RAD_DIR, f"era5_ssrd_{year}.nc")
    if not os.path.exists(nc_path):
        return None, None, None

    ds = xr.open_dataset(nc_path)
    if "ssrd" not in ds.variables:
        ds.close()
        return None, None, None

    ssrd = ds["ssrd"]
    daily = daily_totals_from_cumulative(ssrd)
    lons, lats = coords_of(daily)
    _, lons_out, lats_out = orient_grid(np.zeros((len(lats), len(lons)), dtype=np.float32), lons, lats)
    daily_dates = [pd.to_datetime(t).date() for t in daily["time"].values]

    data = []
    for i in range(len(daily_dates)):
        oriented, _, _ = orient_grid(daily.isel(time=i).values, lons, lats)
        data.append(oriented.astype(np.float32))
    ds.close()
    if not data:
        return None, None, None
    return daily_dates, np.stack(data, axis=0), (lats_out, lons_out)


def main():
    args = parse_args()
    os.makedirs(OUT_DIR, exist_ok=True)

    with rasterio.open(DEM_PATH) as dem:
        ref_profile = dem.profile.copy()
        ref_transform = dem.transform
        ref_crs = dem.crs
        ref_shape = dem.shape

    with rasterio.open(FLOW_ACC_PATH) as src:
        flow_acc = src.read(1)
        flow_nodata = src.nodata
    if flow_nodata is None:
        basin_mask = np.isfinite(flow_acc)
    else:
        basin_mask = flow_acc != flow_nodata

    with rasterio.open(GLACIER_MASK_PATH) as src:
        glacier_raw = src.read(1)
        glacier_nodata = src.nodata
    if glacier_nodata is not None:
        glacier_raw = np.where(glacier_raw == glacier_nodata, 0, glacier_raw)
    glacier_mask = (glacier_raw > 0) & basin_mask

    glacier_fraction = None
    glacier_mode = "binary_legacy"
    if os.path.exists(GLACIER_FRACTION_PATH):
        with rasterio.open(GLACIER_FRACTION_PATH) as src:
            frac_raw = src.read(1).astype(np.float32)
            frac_nodata = src.nodata
        if frac_nodata is not None:
            frac_raw = np.where(frac_raw == frac_nodata, 0.0, frac_raw)
        glacier_fraction = np.clip(frac_raw, 0.0, 1.0)
        glacier_fraction = np.where(basin_mask, glacier_fraction, 0.0).astype(np.float32)
        glacier_mode = "fractional_subgrid"

    temp_files = [f for f in os.listdir(TEMP_DIR) if f.lower().endswith(".tif")]
    temp_by_year = {}
    for fname in temp_files:
        date = parse_date_from_name(fname)
        if date is None:
            continue
        temp_by_year.setdefault(date.year, []).append((date, os.path.join(TEMP_DIR, fname)))

    years = sorted(temp_by_year.keys())
    if args.start_year is not None:
        years = [y for y in years if y >= args.start_year]
    if args.end_year is not None:
        years = [y for y in years if y <= args.end_year]
    print(f"Found temperature years: {years}")
    print(f"Glacier mode: {glacier_mode}")

    for year in years:
        dates, rad_data, coords = load_daily_radiation(year)
        if dates is None:
            print(f"[WARN] Missing radiation for {year}, skipping")
            continue
        lats, lons = coords

        src_transform = build_src_transform(lats, lons)
        src_crs = "EPSG:4326"

        rad_by_date = {d: rad_data[i] for i, d in enumerate(dates)}

        year_files = sorted(temp_by_year[year], key=lambda x: x[0])
        print(f"{year}: {len(year_files)} days")

        for date, temp_path in year_files:
            out_name = f"GM_{date.strftime('%Y.%m.%d')}.tif"
            out_path = os.path.join(OUT_DIR, out_name)
            if (not args.overwrite) and os.path.exists(out_path):
                continue

            if date not in rad_by_date:
                continue

            with rasterio.open(temp_path) as src:
                temp = src.read(1)
                temp_nodata = src.nodata

            rad_src = rad_by_date[date].astype(np.float32)
            rad_dst = np.full(ref_shape, np.nan, dtype=np.float32)
            reproject(
                source=rad_src,
                destination=rad_dst,
                src_transform=src_transform,
                src_crs=src_crs,
                dst_transform=ref_transform,
                dst_crs=ref_crs,
                resampling=Resampling.bilinear,
            )

            if temp_nodata is not None:
                temp = np.where(temp == temp_nodata, np.nan, temp)

            rad_wm2 = np.where(np.isfinite(rad_dst), rad_dst, 0.0) / 86400.0

            melt = np.zeros(ref_shape, dtype=np.float32)
            temp_eff = np.where(np.isfinite(temp), temp, -999.0)

            # 温度融化: 仅当T > TTM时
            melt_temp = np.maximum(temp_eff - TTM, 0.0) * CFMAX_GLACIER

            # 辐射融化: 仅当T > TTM_RAD时 (避免冬季不合理融水)
            rad_melt = np.where(temp_eff > TTM_RAD,
                               np.maximum(rad_wm2, 0.0) * RAD_COEF,
                               0.0)

            melt_val = melt_temp + rad_melt
            melt_val = np.maximum(melt_val, 0.0)

            if glacier_mode == "fractional_subgrid" and glacier_fraction is not None:
                melt = melt_val * glacier_fraction
            else:
                melt[glacier_mask] = melt_val[glacier_mask]
            melt[~basin_mask] = NODATA

            profile = ref_profile.copy()
            profile.update(dtype=rasterio.float32, count=1, nodata=NODATA)
            with rasterio.open(out_path, "w", **profile) as dst:
                dst.write(melt, 1)

        print(f"[OK] {year} done")


if __name__ == "__main__":
    main()

