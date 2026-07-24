# -*- coding: utf-8 -*-
from __future__ import annotations

import argparse
import contextlib
import re
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import rasterio
import xarray as xr
from rasterio.crs import CRS

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "公共"))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "HBV-Studio"))

from cds_chunked_download import is_usable_netcdf  # type: ignore
from 公共函数 import build_workspace_paths, ensure_workspace_dirs, example_config_path, load_legacy_module, old_script_path, open_netcdf_dataset_safe, read_config, year_range  # type: ignore
from services.raster_time_series import validate_tif_time_series  # type: ignore

# 只认下载合并后的按年文件：era5_t2m_hourly_2025.nc
# 不认分片目录或 era5_t2m_hourly_2025_01.nc
YEARLY_HOURLY_NC_RE = re.compile(r"^era5_.+_hourly_\d{4}\.nc$", re.IGNORECASE)



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


def require_yearly_hourly_nc(path: Path, *, label: str) -> Path:
    target = Path(path)
    if not YEARLY_HOURLY_NC_RE.match(target.name):
        raise FileNotFoundError(
            f"{label} 需要按年小时 NC（如 era5_t2m_hourly_2025.nc），收到：{target.name}"
        )
    if not is_usable_netcdf(target):
        chunk_dir = target.parent / f".{target.stem}_chunks"
        hint = f"；若存在未合并分片可重跑下载：{chunk_dir}" if chunk_dir.exists() else ""
        raise FileNotFoundError(f"{label} 年文件不可用：{target}{hint}")
    return target


def monthly_time_slices(times: pd.DatetimeIndex) -> list[tuple[pd.Timestamp, pd.Timestamp]]:
    if len(times) == 0:
        return []
    periods = sorted({(ts.year, ts.month) for ts in times})
    slices: list[tuple[pd.Timestamp, pd.Timestamp]] = []
    for year, month in periods:
        start = pd.Timestamp(year=year, month=month, day=1)
        end = start + pd.offsets.MonthBegin(1)
        slices.append((start, end))
    return slices


def hourly_increments_from_cumulative(
    arr: xr.DataArray,
    *,
    prev_time: pd.Timestamp | None = None,
    prev_values: np.ndarray | None = None,
) -> tuple[xr.DataArray, pd.Timestamp | None, np.ndarray | None]:
    """累计型小时量转增量；支持跨月衔接（prev_* 为上一窗口最后一时次）。"""
    accum = rename_time_dim(arr)
    values = np.asarray(accum.values, dtype=np.float64)
    increments = np.full(values.shape, np.nan, dtype=np.float32)
    times = pd.DatetimeIndex(pd.to_datetime(accum["time"].values))
    if values.shape[0] == 0:
        return accum.astype("float32"), prev_time, prev_values

    last_ts = prev_time
    last_vals = prev_values
    for idx, ts in enumerate(times):
        current = values[idx]
        if last_ts is None or last_vals is None:
            delta = np.zeros_like(current) if ts.hour == 0 else np.clip(current, 0.0, None)
        else:
            gap = ts - last_ts
            if ts.hour == 0 and gap <= pd.Timedelta(hours=1.5):
                delta = current - last_vals
            elif ts.hour == 1 or last_ts.normalize() != ts.normalize() or gap > pd.Timedelta(hours=1.5):
                delta = current
            else:
                delta = current - last_vals
            delta = np.where(np.isfinite(delta), np.clip(delta, 0.0, None), np.nan)
        increments[idx] = delta.astype(np.float32)
        last_ts = ts
        last_vals = current

    out = xr.DataArray(increments, coords=accum.coords, dims=accum.dims, attrs=accum.attrs)
    return out, last_ts, None if last_vals is None else np.asarray(last_vals)


def write_hourly_stack(arr: xr.DataArray, out_dir: Path, prefix: str, value_transform, *, overwrite: bool = False) -> int:
    out_dir.mkdir(parents=True, exist_ok=True)
    series = rename_time_dim(arr)
    lons, lats = coords_of(series)
    _, lons_out, lats_out = orient_grid(np.zeros((len(lats), len(lons)), dtype=np.float32), lons, lats)
    profile = output_profile(lons_out, lats_out)
    count = 0
    # 按月写出，避免一次把整年 isel 循环的中间态撑爆
    times = pd.DatetimeIndex(pd.to_datetime(series["time"].values))
    if len(times) == 0:
        return 0
    for start, end in monthly_time_slices(times):
        month_mask = (times >= start) & (times < end)
        if not month_mask.any():
            continue
        month_idx = np.where(month_mask)[0]
        month_arr = series.isel(time=month_idx)
        for i, time_value in enumerate(month_arr["time"].values):
            ts = np.datetime64(time_value).astype("datetime64[m]")
            date = str(ts).replace("-", ".").replace("T", ".").replace(":", ".")
            out_path = out_dir / f"{prefix}_{date}.tif"
            if (not overwrite) and out_path.exists():
                count += 1
                continue
            data = value_transform(month_arr.isel(time=i).values)
            data, _, _ = orient_grid(data, lons, lats)
            data = np.where(np.isfinite(data), data, profile["nodata"]).astype("float32")
            with rasterio.open(out_path, "w", **profile) as dst:
                dst.write(data, 1)
            count += 1
    return count


def write_hourly_stack_from_yearly_nc(
    nc_file: Path,
    *,
    variable_candidates: list[str],
    out_dir: Path,
    prefix: str,
    value_transform,
    cumulative: bool = False,
    scale: float = 1.0,
    overwrite: bool = False,
    label: str = "小时变量",
) -> int:
    """从按年小时 NC 按月切片写出 TIF，降低整年数组常驻内存。"""
    require_yearly_hourly_nc(nc_file, label=label)
    count = 0
    prev_time: pd.Timestamp | None = None
    prev_values: np.ndarray | None = None
    with open_netcdf_dataset_safe(nc_file) as ds:
        var_name = next((name for name in variable_candidates if name in ds.data_vars), None)
        if var_name is None:
            var_name = list(ds.data_vars)[0]
        series = rename_time_dim(ds[var_name] * scale)
        times = pd.DatetimeIndex(pd.to_datetime(series["time"].values))
        if len(times) == 0:
            return 0
        for start, end in monthly_time_slices(times):
            month_mask = (times >= start) & (times < end)
            if not month_mask.any():
                continue
            month_idx = np.where(month_mask)[0]
            month_arr = series.isel(time=month_idx)
            if cumulative:
                month_arr, prev_time, prev_values = hourly_increments_from_cumulative(
                    month_arr,
                    prev_time=prev_time,
                    prev_values=prev_values,
                )
            count += write_hourly_stack(
                month_arr,
                out_dir,
                prefix,
                value_transform,
                overwrite=overwrite,
            )
            print(f"      [{label}] {nc_file.name} {start.strftime('%Y-%m')}: 累计写出 {count}")
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
    temp_file = require_yearly_hourly_nc(paths["raw_temp_dir"] / f"era5_t2m_hourly_{year}.nc", label="小时气温")
    solar_file = require_yearly_hourly_nc(paths["raw_solar_dir"] / f"era5_ssrd_hourly_{year}.nc", label="小时太阳辐射")
    u10_file = require_yearly_hourly_nc(paths["raw_wind_dir"] / f"era5_u10_hourly_{year}.nc", label="小时风速U")
    v10_file = require_yearly_hourly_nc(paths["raw_wind_dir"] / f"era5_v10_hourly_{year}.nc", label="小时风速V")
    dew_file = require_yearly_hourly_nc(paths["raw_dewpoint_dir"] / f"era5_d2m_hourly_{year}.nc", label="小时露点")

    et_module = prepare_daily_et_module(config)
    written = 0
    prev_ssrd_time: pd.Timestamp | None = None
    prev_ssrd_vals: np.ndarray | None = None

    with contextlib.ExitStack() as stack:
        ds_temp = stack.enter_context(open_netcdf_dataset_safe(temp_file))
        ds_solar = stack.enter_context(open_netcdf_dataset_safe(solar_file))
        ds_u10 = stack.enter_context(open_netcdf_dataset_safe(u10_file))
        ds_v10 = stack.enter_context(open_netcdf_dataset_safe(v10_file))
        ds_dew = stack.enter_context(open_netcdf_dataset_safe(dew_file))
        t2m_all = rename_time_dim(ds_temp["t2m"] - 273.15)
        ssrd_all = rename_time_dim(ds_solar["ssrd"] / 1e6)
        u10_all = rename_time_dim(ds_u10["u10"])
        v10_all = rename_time_dim(ds_v10["v10"])
        d2m_all = rename_time_dim(ds_dew["d2m"] - 273.15)

        times = pd.DatetimeIndex(pd.to_datetime(t2m_all["time"].values))
        if len(times) == 0:
            return 0

        # 取空间网格一次即可
        sample = t2m_all.isel(time=0)
        lons, lats = coords_of(sample)
        _, lons_out, lats_out = orient_grid(np.zeros((len(lats), len(lons)), dtype=np.float32), lons, lats)
        lon_grid, lat_grid = np.meshgrid(lons, lats)
        profile = output_profile(lons_out, lats_out)
        out_dir = paths["raw_evap_hourly_dir"]
        out_dir.mkdir(parents=True, exist_ok=True)

        for start, end in monthly_time_slices(times):
            month_mask = (times >= start) & (times < end)
            if not month_mask.any():
                continue
            month_idx = np.where(month_mask)[0]
            t2m = t2m_all.isel(time=month_idx)
            ssrd_month = ssrd_all.isel(time=month_idx)
            ssrd_hourly, prev_ssrd_time, prev_ssrd_vals = hourly_increments_from_cumulative(
                ssrd_month,
                prev_time=prev_ssrd_time,
                prev_values=prev_ssrd_vals,
            )
            u10 = u10_all.isel(time=month_idx)
            v10 = v10_all.isel(time=month_idx)
            d2m = d2m_all.isel(time=month_idx)

            t_mean = t2m.resample(time="1D").mean()
            t_min = t2m.resample(time="1D").min()
            t_max = t2m.resample(time="1D").max()
            rs_daily = ssrd_hourly.resample(time="1D").sum().reindex(time=t_mean["time"].values)
            u10_mean = u10.resample(time="1D").mean().reindex(time=t_mean["time"].values)
            v10_mean = v10.resample(time="1D").mean().reindex(time=t_mean["time"].values)
            d2m_mean = d2m.resample(time="1D").mean().reindex(time=t_mean["time"].values)

            daily_times = t_mean["time"].values
            ssrd_times = pd.to_datetime(ssrd_hourly["time"].values)
            for i, day_time in enumerate(daily_times):
                date = pd.Timestamp(day_time)
                doy = int(date.strftime("%j"))
                day_mask = ssrd_times.normalize() == date.normalize()
                hourly_times = ssrd_times[day_mask]
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
                    hourly_et = np.where(
                        np.isfinite(daily_et),
                        np.clip(daily_et * norm_weights[j], 0.0, None),
                        profile["nodata"],
                    )
                    hourly_et, _, _ = orient_grid(hourly_et, lons, lats)
                    with rasterio.open(out_path, "w", **profile) as dst:
                        dst.write(
                            np.where(np.isfinite(hourly_et), hourly_et, profile["nodata"]).astype("float32"),
                            1,
                        )
                    written += 1
            print(f"      [小时潜在蒸散发] {year}-{start.month:02d}: 累计写出 {written}")
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
    meteo = dict(config.get("气象策略", {}))
    prec_source = str(meteo.get("降水来源", meteo.get("降水源", config.get("默认降水源", "era5")))).strip().lower()

    def kelvin_to_celsius(values: np.ndarray) -> np.ndarray:
        arr = np.asarray(values, dtype=np.float64)
        finite = arr[np.isfinite(arr)]
        if finite.size and float(np.nanmedian(finite)) > 100.0:
            return (arr - 273.15).astype(np.float32)
        return arr.astype(np.float32)

    missing: list[str] = []
    prec_count = 0
    if prec_source == "era5":
        for year in years:
            nc_file = paths["raw_prec_era5_dir"] / f"era5_tp_hourly_{year}.nc"
            if not nc_file.exists():
                missing.append(str(nc_file))
                continue
            prec_count += write_hourly_stack_from_yearly_nc(
                nc_file,
                variable_candidates=["tp"],
                out_dir=paths["raw_prec_era5_hourly_dir"],
                prefix="PREC",
                value_transform=lambda values: np.clip(values, 0.0, None),
                cumulative=True,
                scale=1000.0,
                overwrite=bool(args.覆盖),
                label="小时降水",
            )

    temp_count = 0
    for year in years:
        nc_file = paths["raw_temp_dir"] / f"era5_t2m_hourly_{year}.nc"
        if not nc_file.exists():
            missing.append(str(nc_file))
            continue
        temp_count += write_hourly_stack_from_yearly_nc(
            nc_file,
            variable_candidates=["t2m"],
            out_dir=paths["raw_temp_hourly_dir"],
            prefix="T",
            value_transform=kelvin_to_celsius,
            cumulative=False,
            scale=1.0,
            overwrite=bool(args.覆盖),
            label="小时气温",
        )

    evap_count = 0
    for year in years:
        try:
            evap_count += build_hourly_et(year, paths, config, overwrite=bool(args.覆盖))
        except FileNotFoundError as exc:
            missing.append(str(exc))
            print(f"[跳过] {year} 小时潜在蒸散发：{exc}")

    if missing and temp_count == 0 and prec_count == 0 and evap_count == 0:
        raise FileNotFoundError(
            "未找到可用的按年小时 ERA5 NC。请先完成“下载小时 ERA5 变量”。缺失示例：\n- "
            + "\n- ".join(missing[:8])
        )

    outputs = []
    if prec_source == "era5":
        outputs.append(("小时降水", paths["raw_prec_era5_hourly_dir"]))
    outputs.extend(
        [
            ("小时气温", paths["raw_temp_hourly_dir"]),
            ("小时潜在蒸散发", paths["raw_evap_hourly_dir"]),
        ]
    )
    print(f"[统计] 降水TIF={prec_count}, 气温TIF={temp_count}, 潜在蒸散发TIF={evap_count}")
    for label, directory in outputs:
        check = validate_tif_time_series(label, Path(directory), 1.0)
        print(f"[完成] {label}: {check['period_summary']}")


if __name__ == "__main__":
    main()
