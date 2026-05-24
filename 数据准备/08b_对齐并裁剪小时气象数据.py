# -*- coding: utf-8 -*-
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

import geopandas as gpd
import numpy as np
import rasterio
from rasterio.features import geometry_mask
from rasterio.warp import reproject, Resampling

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
)  # type: ignore
from profile_runner import PROFILE_HOURLY, build_profile_paths, configured_precip_source


TIME_RE = [
    re.compile(r"(\d{4}\.\d{2}\.\d{2}\.\d{2}\.\d{2})"),
    re.compile(r"(\d{4}\.\d{2}\.\d{2}\.\d{2})"),
    re.compile(r"(\d{4}-\d{2}-\d{2}T\d{2}:\d{2})"),
    re.compile(r"(\d{4}-\d{2}-\d{2} \d{2}:\d{2})"),
    re.compile(r"(\d{4}-\d{2}-\d{2}\.\d{2})"),
]


def resolve_config_entry_path(config, raw_value):
    resolved = resolve_path(str(raw_value or "").strip(), base=config_base_dir(config))
    return Path(resolved).resolve(strict=False) if resolved else Path("")


def parse_stamp(name: str) -> str | None:
    for pattern in TIME_RE:
        match = pattern.search(Path(name).stem)
        if match:
            token = match.group(1).replace("-", ".").replace("T", ".").replace(":", ".").replace(" ", ".")
            parts = token.split(".")
            return ".".join(parts[:4])
    return None


def collect_files(directory: Path) -> list[tuple[str, Path]]:
    records: list[tuple[str, Path]] = []
    if not directory.exists():
        return records
    seen_stamps: dict[str, list[str]] = {}
    for file_path in directory.glob("*.tif"):
        stamp = parse_stamp(file_path.name)
        if stamp:
            seen_stamps.setdefault(stamp, []).append(file_path.name)
            records.append((stamp, file_path))
    duplicates = {stamp: names for stamp, names in seen_stamps.items() if len(names) > 1}
    if duplicates:
        first_stamp, names = next(iter(sorted(duplicates.items(), key=lambda item: item[0])))
        sample = "、".join(names[:3])
        raise RuntimeError(f"输入目录 {directory} 存在重复时间戳 {first_stamp}，例如：{sample}")
    return sorted(records, key=lambda item: item[0])


def align_single(input_file: Path, dem_profile: dict[str, object], dem_shape: tuple[int, int], basin_mask: np.ndarray) -> np.ndarray:
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


def write_series(
    records: list[tuple[str, Path]],
    output_dir: Path,
    prefix: str,
    dem_profile: dict[str, object],
    dem_shape: tuple[int, int],
    basin_mask: np.ndarray,
    *,
    overwrite: bool = False,
) -> int:
    output_dir.mkdir(parents=True, exist_ok=True)
    profile = dem_profile.copy()
    profile.update(dtype="float32", count=1, nodata=-9999.0, compress="lzw")
    count = 0
    for index, (stamp, input_file) in enumerate(records):
        output_file = output_dir / f"{index}_{prefix}_{stamp}.tif"
        if (not overwrite) and output_file.exists():
            count += 1
            continue
        data = align_single(input_file, dem_profile, dem_shape, basin_mask)
        with rasterio.open(output_file, "w", **profile) as dst:
            dst.write(np.where(np.isfinite(data), data, profile["nodata"]).astype("float32"), 1)
        count += 1
    return count


def main() -> None:
    parser = argparse.ArgumentParser(description="把小时尺度降水、温度、蒸散发对齐到 DEM 并裁剪到流域。")
    parser.add_argument("--配置", "--config", dest="配置", default=str(example_config_path()))
    parser.add_argument("--降水源", "--prec-source", dest="降水源", choices=["era5", "mswep", "cmfd", "custom_tif"], default=None)
    parser.add_argument("--覆盖", "--overwrite", dest="覆盖", action="store_true")
    args = parser.parse_args()

    config = read_config(args.配置)
    base_paths = build_workspace_paths(config)
    paths = build_profile_paths(config, PROFILE_HOURLY)
    basin = basin_paths(config)
    ensure_workspace_dirs(paths)

    dem_file = resolve_workspace_dem_path(base_paths["gis_dir"], prefer=infer_dem_kind_from_raster(config.get("DEM_tif", "")))
    with rasterio.open(dem_file) as dem:
        dem_profile = dem.profile.copy()
        dem_profile.update(dtype="float32", nodata=-9999.0)
        dem_shape = (dem.height, dem.width)
        basin_gdf = gpd.read_file(basin["basin_shp"]).to_crs(dem.crs)
        basin_mask = ~geometry_mask(basin_gdf.geometry, out_shape=dem_shape, transform=dem.transform, invert=False)

    meteo = config.get("气象策略", {})
    custom_prec_dir = str(meteo.get("自带降水tif目录", "")).strip()
    custom_prec_path = resolve_config_entry_path(config, custom_prec_dir)
    runtime_source = str(getattr(args, "降水源", None) or configured_precip_source(config) or "era5").strip().lower()
    if runtime_source == "custom_tif":
        if not custom_prec_dir or not custom_prec_path.is_dir():
            raise FileNotFoundError(f"当前降水来源为 custom_tif，但自带降水tif目录无效：{custom_prec_dir or '未设置'}")
        precip_input = custom_prec_path
        precip_output = paths["aligned_prec_custom_base_dir"]
        print(f"[降水] 使用自带 tif 目录: {precip_input}")
    elif runtime_source == "era5":
        precip_input = base_paths["raw_prec_era5_hourly_dir"]
        precip_output = paths["aligned_prec_era5_base_dir"]
        print(f"[降水] 使用 ERA5 小时降水目录: {precip_input}")
    elif runtime_source == "cmfd":
        precip_input = base_paths["raw_prec_cmfd_hourly_dir"]
        precip_output = paths["aligned_prec_cmfd_base_dir"]
        print(f"[降水] 使用 CMFD 目录: {precip_input}")
    else:
        precip_input = base_paths["raw_prec_hourly_dir"]
        precip_output = paths["aligned_prec_base_dir"]
        print(f"[降水] 使用 MSWEP 目录: {precip_input}")

    # --- 温度：ERA5 处理结果或自带 tif ---
    temp_source = str(meteo.get("温度来源", "era5")).strip().lower()
    custom_temp_dir = str(meteo.get("自带温度tif目录", "")).strip()
    custom_temp_path = resolve_config_entry_path(config, custom_temp_dir)
    if temp_source == "custom_tif":
        if not custom_temp_dir or not custom_temp_path.is_dir():
            raise FileNotFoundError(f"当前温度来源为 custom_tif，但自带温度tif目录无效：{custom_temp_dir or '未设置'}")
        temp_input_dir = custom_temp_path
        print(f"[温度] 使用自带 tif 目录: {temp_input_dir}")
    else:
        temp_input_dir = base_paths["raw_temp_hourly_dir"]
        print(f"[温度] 使用 ERA5 处理结果: {temp_input_dir}")

    # --- 潜在蒸散发：ERA5/FAO56 处理结果或自带 tif ---
    pet_source = str(meteo.get("潜在蒸散发来源", "era5_fao56")).strip().lower()
    custom_pet_dir = str(meteo.get("自带蒸散发tif目录", "")).strip()
    custom_pet_path = resolve_config_entry_path(config, custom_pet_dir)
    if pet_source == "custom_tif":
        if not custom_pet_dir or not custom_pet_path.is_dir():
            raise FileNotFoundError(f"当前潜在蒸散发来源为 custom_tif，但自带蒸散发tif目录无效：{custom_pet_dir or '未设置'}")
        evap_input_dir = custom_pet_path
        print(f"[蒸散发] 使用自带 tif 目录: {evap_input_dir}")
    else:
        evap_input_dir = base_paths["raw_evap_hourly_dir"]
        print(f"[蒸散发] 使用 ERA5 处理结果: {evap_input_dir}")

    summary = {
        "降水": write_series(
            collect_files(precip_input),
            precip_output,
            "PREC",
            dem_profile,
            dem_shape,
            basin_mask,
            overwrite=bool(args.覆盖),
        ),
        "温度": write_series(
            collect_files(temp_input_dir),
            paths["aligned_temp_dir"],
            "TEMP",
            dem_profile,
            dem_shape,
            basin_mask,
            overwrite=bool(args.覆盖),
        ),
        "蒸散发": write_series(
            collect_files(evap_input_dir),
            paths["aligned_evap_dir"],
            "EVAP",
            dem_profile,
            dem_shape,
            basin_mask,
            overwrite=bool(args.覆盖),
        ),
    }
    for name, value in summary.items():
        print(f"{name}: {value} 个文件")


if __name__ == "__main__":
    main()
