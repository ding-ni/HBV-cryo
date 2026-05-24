# -*- coding: utf-8 -*-
import argparse
import re
import sys
from datetime import datetime
from pathlib import Path

import geopandas as gpd
import numpy as np
import rasterio
from rasterio.features import geometry_mask
from rasterio.warp import Resampling, reproject

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "公共"))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "HBV-Studio"))

from 公共函数 import (
    basin_paths,
    build_workspace_paths,
    config_base_dir,
    ensure_workspace_dirs,
    example_config_path,
    infer_dem_kind_from_raster,
    read_config,
    resolve_path,
    resolve_workspace_dem_path,
)
from profile_runner import PROFILE_DAILY, build_profile_paths, configured_precip_source  # type: ignore


DATE_RE = re.compile(r"(\d{4}\.\d{2}\.\d{2})")


def resolve_config_entry_path(config, raw_value):
    resolved = resolve_path(str(raw_value or "").strip(), base=config_base_dir(config))
    return Path(resolved).resolve(strict=False) if resolved else Path("")


def collect_files(input_dir, start_date, end_date):
    records = []
    directory = Path(input_dir)
    if not directory.exists():
        return records
    seen_dates: dict[datetime, list[str]] = {}
    for file in directory.glob("*.tif"):
        match = DATE_RE.search(file.name)
        if not match:
            continue
        date = datetime.strptime(match.group(1), "%Y.%m.%d")
        if start_date <= date <= end_date:
            seen_dates.setdefault(date, []).append(file.name)
            records.append((date, file))
    duplicates = {date: names for date, names in seen_dates.items() if len(names) > 1}
    if duplicates:
        first_date, names = next(iter(sorted(duplicates.items(), key=lambda item: item[0])))
        sample = "、".join(names[:3])
        raise RuntimeError(f"输入目录 {directory} 存在重复日期 {first_date.strftime('%Y.%m.%d')}，例如：{sample}")
    records.sort(key=lambda item: item[0])
    return records


def align_single(input_file, dem_profile, dem_shape, basin_mask):
    with rasterio.open(input_file) as src:
        out = np.full(dem_shape, np.nan, dtype="float32")
        reproject(
            source=rasterio.band(src, 1),
            destination=out,
            src_transform=src.transform,
            src_crs=src.crs,
            dst_transform=dem_profile["transform"],
            dst_crs=dem_profile["crs"],
            resampling=Resampling.bilinear,
        )
        nodata = src.nodata
        if nodata is not None:
            out[out == nodata] = np.nan
    out[~basin_mask] = np.nan
    return out


def write_series(records, output_dir, prefix, dem_profile, dem_shape, basin_mask, overwrite=False):
    Path(output_dir).mkdir(parents=True, exist_ok=True)
    profile = dem_profile.copy()
    profile.update(dtype="float32", count=1, nodata=-9999.0, compress="lzw")
    count = 0
    for index, (date, input_file) in enumerate(records):
        output_file = Path(output_dir) / f"{index}_{prefix}_{date.strftime('%Y.%m.%d')}.tif"
        if (not overwrite) and output_file.exists():
            count += 1
            continue
        data = align_single(input_file, dem_profile, dem_shape, basin_mask)
        with rasterio.open(output_file, "w", **profile) as dst:
            dst.write(np.where(np.isfinite(data), data, profile["nodata"]).astype("float32"), 1)
        count += 1
    return count


def main():
    parser = argparse.ArgumentParser(description="把温度、降水、蒸散发统一对齐到 DEM 并裁到流域。")
    parser.add_argument("--配置", "--config", dest="配置", default=str(example_config_path()))
    parser.add_argument("--降水源", "--prec-source", dest="降水源", choices=["era5", "mswep", "cmfd", "custom_tif"], default=None)
    parser.add_argument("--覆盖", "--overwrite", dest="覆盖", action="store_true")
    args = parser.parse_args()

    config = read_config(args.配置)
    paths = build_workspace_paths(config)
    profile_paths = build_profile_paths(config, PROFILE_DAILY)
    basin_info = basin_paths(config)
    ensure_workspace_dirs(paths)

    time_cfg = config["时间"]
    start_date = datetime.strptime(f"{int(time_cfg['开始年份'])}-01-01", "%Y-%m-%d")
    end_date = datetime.strptime(f"{int(time_cfg['结束年份'])}-12-31", "%Y-%m-%d")

    dem_file = resolve_workspace_dem_path(paths["gis_dir"], prefer=infer_dem_kind_from_raster(config.get("DEM_tif", "")))
    with rasterio.open(dem_file) as dem:
        dem_profile = dem.profile.copy()
        dem_profile.update(dtype="float32", nodata=-9999.0)
        dem_shape = (dem.height, dem.width)
        basin = gpd.read_file(basin_info["basin_shp"]).to_crs(dem.crs)
        basin_mask = ~geometry_mask(basin.geometry, out_shape=dem_shape, transform=dem.transform, invert=False)

    meteo = config.get("气象策略", {})
    configured_source = configured_precip_source(config)
    runtime_source = str(args.降水源 or configured_source or "era5").strip().lower()
    custom_prec_dir = str(meteo.get("自带降水tif目录", "")).strip()
    custom_prec_path = resolve_config_entry_path(config, custom_prec_dir)
    if runtime_source == "custom_tif":
        if not custom_prec_dir or not custom_prec_path.is_dir():
            raise FileNotFoundError(f"当前降水来源为 custom_tif，但自带降水tif目录无效：{custom_prec_dir or '未设置'}")
        prec_input = custom_prec_path
        prec_output = profile_paths["aligned_prec_custom_base_dir"]
        print(f"[降水] 使用自带 tif 目录: {prec_input}")
    elif runtime_source == "era5":
        prec_input = paths["raw_prec_era5_daily_dir"]
        prec_output = profile_paths["aligned_prec_era5_base_dir"]
        print(f"[降水] 使用 ERA5 日降水目录: {prec_input}")
    else:
        prec_input = paths["raw_prec_daily_dir"] if runtime_source == "mswep" else paths["raw_prec_cmfd_daily_dir"]
        prec_output = profile_paths["aligned_prec_base_dir"] if runtime_source == "mswep" else profile_paths["aligned_prec_cmfd_base_dir"]
        print(f"[降水] 使用格点目录: {prec_input}")

    temp_source = str(meteo.get("温度来源", "era5")).strip().lower()
    custom_temp_dir = str(meteo.get("自带温度tif目录", "")).strip()
    custom_temp_path = resolve_config_entry_path(config, custom_temp_dir)
    if temp_source == "custom_tif":
        if not custom_temp_dir or not custom_temp_path.is_dir():
            raise FileNotFoundError(f"当前温度来源为 custom_tif，但自带温度tif目录无效：{custom_temp_dir or '未设置'}")
        temp_input = custom_temp_path
        print(f"[温度] 使用自带 tif 目录: {temp_input}")
    else:
        temp_input = paths["raw_temp_daily_dir"]
        print(f"[温度] 使用 ERA5 处理结果: {temp_input}")

    pet_source = str(meteo.get("潜在蒸散发来源", "era5_fao56")).strip().lower()
    custom_pet_dir = str(meteo.get("自带蒸散发tif目录", "")).strip()
    custom_pet_path = resolve_config_entry_path(config, custom_pet_dir)
    if pet_source == "custom_tif":
        if not custom_pet_dir or not custom_pet_path.is_dir():
            raise FileNotFoundError(f"当前潜在蒸散发来源为 custom_tif，但自带蒸散发tif目录无效：{custom_pet_dir or '未设置'}")
        evap_input = custom_pet_path
        print(f"[蒸散发] 使用自带 tif 目录: {evap_input}")
    else:
        evap_input = paths["raw_evap_daily_dir"]
        print(f"[蒸散发] 使用 ERA5 处理结果: {evap_input}")

    summary = {
        "降水": write_series(
            collect_files(prec_input, start_date, end_date),
            prec_output,
            "PREC",
            dem_profile,
            dem_shape,
            basin_mask,
            overwrite=bool(args.覆盖),
        ),
        "温度": write_series(
            collect_files(temp_input, start_date, end_date),
            paths["aligned_temp_dir"],
            "TEMP",
            dem_profile,
            dem_shape,
            basin_mask,
            overwrite=bool(args.覆盖),
        ),
        "蒸散发": write_series(
            collect_files(evap_input, start_date, end_date),
            paths["aligned_evap_dir"],
            "EVAP",
            dem_profile,
            dem_shape,
            basin_mask,
            overwrite=bool(args.覆盖),
        ),
    }

    for name, count in summary.items():
        print(f"{name}: {count} 个文件")


if __name__ == "__main__":
    main()
