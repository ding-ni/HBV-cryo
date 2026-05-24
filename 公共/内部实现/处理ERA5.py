# -*- coding: utf-8 -*-
"""
阶段2B：ERA5 NetCDF 数据后处理

将 ERA5-Land NetCDF 数据转换为逐日 GeoTIFF 格式

输入：
- 数据/原始气象/气温/era5_t2m_*.nc
- 数据/原始气象/蒸散发/era5_evap_*.nc

输出：
- 数据/原始气象/气温/日尺度/*.tif
- 数据/原始气象/蒸散发/日尺度/*.tif
"""

import os
import sys

import numpy as np
import pandas as pd
import xarray as xr
import rasterio
from rasterio.crs import CRS
from datetime import datetime

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from 公共函数 import open_netcdf_dataset_safe

# ============================================================
# 路径配置
# ============================================================
def _prefer_existing_path(*paths):
    for path in paths:
        if os.path.exists(path):
            return path
    return paths[0]


PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "运行目录", "默认流域"))
DATA_ROOT = ""
RAW_ROOT = ""
RAW_TEMP_DIR = ""
RAW_EVAP_DIR = ""
TEMP_DAILY_DIR = ""
EVAP_DAILY_DIR = ""

YEARS = range(2006, 2021)
OVERWRITE = False


def refresh_workspace_paths():
    global DATA_ROOT, RAW_ROOT, RAW_TEMP_DIR, RAW_EVAP_DIR, TEMP_DAILY_DIR, EVAP_DAILY_DIR
    DATA_ROOT = _prefer_existing_path(os.path.join(PROJECT_ROOT, "数据"), os.path.join(PROJECT_ROOT, "data"))
    RAW_ROOT = _prefer_existing_path(os.path.join(DATA_ROOT, "原始气象"), os.path.join(DATA_ROOT, "raw"))
    RAW_TEMP_DIR = _prefer_existing_path(os.path.join(RAW_ROOT, "气温"), os.path.join(RAW_ROOT, "temperature"))
    RAW_EVAP_DIR = _prefer_existing_path(os.path.join(RAW_ROOT, "蒸散发"), os.path.join(RAW_ROOT, "evaporation"))
    TEMP_DAILY_DIR = _prefer_existing_path(os.path.join(RAW_TEMP_DIR, "日尺度"), os.path.join(RAW_TEMP_DIR, "daily"))
    EVAP_DAILY_DIR = _prefer_existing_path(os.path.join(RAW_EVAP_DIR, "日尺度"), os.path.join(RAW_EVAP_DIR, "daily"))


refresh_workspace_paths()


def coords_of(arr):
    lons = arr.longitude.values if 'longitude' in arr.coords else arr.lon.values
    lats = arr.latitude.values if 'latitude' in arr.coords else arr.lat.values
    return np.asarray(lons), np.asarray(lats)


def rename_time_dim(arr):
    time_dim = 'valid_time' if 'valid_time' in arr.dims else 'time'
    if time_dim != 'time':
        return arr.rename({time_dim: 'time'})
    return arr


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


def output_transform(lons, lats):
    res_x = abs(lons[1] - lons[0]) if len(lons) > 1 else 0.1
    res_y = abs(lats[1] - lats[0]) if len(lats) > 1 else 0.1
    return rasterio.transform.from_bounds(
        lons.min() - res_x / 2,
        lats.min() - res_y / 2,
        lons.max() + res_x / 2,
        lats.max() + res_y / 2,
        len(lons),
        len(lats)
    )


def daily_totals_from_cumulative(arr):
    accum = rename_time_dim(arr)
    times = pd.DatetimeIndex(pd.to_datetime(accum["time"].values))
    if times.empty:
        return accum.isel(time=slice(0, 0))

    available_days = sorted({ts.normalize() for ts in times})
    selected_indices = {}
    fallback_indices = {}
    available_day_set = set(available_days)

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


# ============================================================
# 处理温度数据
# ============================================================
def process_temperature(year):
    """处理单年温度数据"""

    nc_file = os.path.join(RAW_TEMP_DIR, f"era5_t2m_{year}.nc")

    if not os.path.exists(nc_file):
        print(f"   [WARN] {year}: NetCDF文件不存在")
        return 0

    print(f"   处理 {year} 年温度数据...")

    with open_netcdf_dataset_safe(nc_file) as ds:
        # ERA5 温度变量名可能是 't2m' 或 'VAR_2T'
        var_name = 't2m' if 't2m' in ds.data_vars else list(ds.data_vars)[0]
        temp = ds[var_name]

        # 从 Kelvin 转换为 Celsius
        temp_c = temp - 273.15

        # 从小时/6小时聚合到日平均
        temp_daily = rename_time_dim(temp_c).resample(time='1D').mean()

        # 确保输出目录存在
        os.makedirs(TEMP_DAILY_DIR, exist_ok=True)

        # 获取坐标信息
        lons, lats = coords_of(temp_daily)
        _, lons_out, lats_out = orient_grid(np.zeros((len(lats), len(lons)), dtype=np.float32), lons, lats)

        # 输出计数
        count = 0

        # 获取时间坐标
        time_values = temp_daily["time"].values

        # 逐日保存为 GeoTIFF
        for i, time in enumerate(time_values):
            date = np.datetime_as_string(time, unit='D')
            date_str = date.replace('-', '.')

            output_file = os.path.join(TEMP_DAILY_DIR, f"T_{date_str}.tif")
            if (not OVERWRITE) and os.path.exists(output_file):
                count += 1
                continue

            # 提取该天的数据
            data = temp_daily.isel(time=i).values

            # 处理 NaN
            data = np.where(np.isnan(data), -9999, data)
            data, _, _ = orient_grid(data, lons, lats)
            transform = output_transform(lons_out, lats_out)

            # 保存
            with rasterio.open(
                output_file, 'w',
                driver='GTiff',
                height=data.shape[0],
                width=data.shape[1],
                count=1,
                dtype=data.dtype,
                crs=CRS.from_epsg(4326),
                transform=transform,
                nodata=-9999
            ) as dst:
                dst.write(data, 1)

            count += 1
    print(f"   [OK] {year}: 生成 {count} 个日温度文件")
    return count


# ============================================================
# 处理蒸散发数据
# ============================================================
def process_evaporation(year):
    """处理单年蒸散发数据"""

    nc_file = os.path.join(RAW_EVAP_DIR, f"era5_evap_{year}.nc")

    if not os.path.exists(nc_file):
        print(f"   [WARN] {year}: NetCDF文件不存在")
        return 0

    print(f"   处理 {year} 年蒸散发数据...")

    with open_netcdf_dataset_safe(nc_file) as ds:
        # ERA5 蒸散发变量名
        var_name = 'e' if 'e' in ds.data_vars else list(ds.data_vars)[0]
        evap = ds[var_name]

        # ERA5 蒸散发单位是 m，转换为 mm
        # 且 ERA5 蒸散发是负值（向下为正），取绝对值
        evap_mm = np.abs(evap) * 1000

        # ERA5-Land 累积量在下一天 00:00 才给出上一日总量；若跨年缺少该时次，则退回当日最后一个时次。
        evap_daily = daily_totals_from_cumulative(evap_mm)

        # 确保输出目录存在
        os.makedirs(EVAP_DAILY_DIR, exist_ok=True)

        # 获取坐标信息
        lons, lats = coords_of(evap_daily)
        _, lons_out, lats_out = orient_grid(np.zeros((len(lats), len(lons)), dtype=np.float32), lons, lats)

        count = 0

        # 获取时间坐标
        time_values = evap_daily["time"].values

        for i, time in enumerate(time_values):
            date = np.datetime_as_string(time, unit='D')
            date_str = date.replace('-', '.')

            output_file = os.path.join(EVAP_DAILY_DIR, f"ET_{date_str}.tif")
            if (not OVERWRITE) and os.path.exists(output_file):
                count += 1
                continue

            data = evap_daily.isel(time=i).values
            data = np.where(np.isnan(data), -9999, data)
            data, _, _ = orient_grid(data, lons, lats)
            transform = output_transform(lons_out, lats_out)

            with rasterio.open(
                output_file, 'w',
                driver='GTiff',
                height=data.shape[0],
                width=data.shape[1],
                count=1,
                dtype=np.float32,
                crs=CRS.from_epsg(4326),
                transform=transform,
                nodata=-9999
            ) as dst:
                dst.write(data.astype(np.float32), 1)

            count += 1
    print(f"   [OK] {year}: 生成 {count} 个日蒸散发文件")
    return count


# ============================================================
# 主函数
# ============================================================
if __name__ == "__main__":
    print("=" * 60)
    print("ERA5 数据后处理：NetCDF → 逐日 GeoTIFF")
    print("=" * 60)

    # 检查是否有 NetCDF 文件
    temp_files = [f for f in os.listdir(RAW_TEMP_DIR) if f.endswith('.nc')] if os.path.exists(RAW_TEMP_DIR) else []
    evap_files = [f for f in os.listdir(RAW_EVAP_DIR) if f.endswith('.nc')] if os.path.exists(RAW_EVAP_DIR) else []

    print(f"\n找到温度 NetCDF 文件: {len(temp_files)}")
    print(f"找到蒸散发 NetCDF 文件: {len(evap_files)}")

    if not temp_files and not evap_files:
        print("\n[WARN] 未找到 ERA5 NetCDF 文件")
        print("   请先运行 02_download_meteorological_data.py 下载数据")
        sys.exit(0)

    # 处理温度
    if temp_files:
        print("\n[1/2] 处理温度数据")
        total_temp = 0
        for year in YEARS:
            total_temp += process_temperature(year)
        print(f"   共生成 {total_temp} 个温度文件")

    # 处理蒸散发
    if evap_files:
        print("\n[2/2] 处理蒸散发数据")
        total_evap = 0
        for year in YEARS:
            total_evap += process_evaporation(year)
        print(f"   共生成 {total_evap} 个蒸散发文件")

    print("\n[OK] 后处理完成！")

