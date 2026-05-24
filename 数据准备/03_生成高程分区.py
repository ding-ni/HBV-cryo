# -*- coding: utf-8 -*-
import argparse
import sys
from pathlib import Path

import numpy as np
import rasterio

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "公共"))

from 公共函数 import (
    build_workspace_paths,
    cfmax_zone_threshold,
    ensure_workspace_dirs,
    example_config_path,
    infer_dem_kind_from_raster,
    read_config,
    resolve_workspace_dem_path,
)


def save_zone(profile, data, output_file):
    profile = profile.copy()
    profile.update(dtype=rasterio.uint8, count=1, nodata=0, compress="lzw")
    with rasterio.open(output_file, "w", **profile) as dst:
        dst.write(data.astype(np.uint8), 1)


def main():
    parser = argparse.ArgumentParser(description="按照高程生成 CFMAX 的低/高两个分区。")
    parser.add_argument("--配置", "--config", dest="配置", default=str(example_config_path()))
    parser.add_argument("--分界高程", type=float, default=None)
    args = parser.parse_args()

    config = read_config(args.配置)
    paths = build_workspace_paths(config)
    ensure_workspace_dirs(paths)
    zone_threshold = cfmax_zone_threshold(config) if args.分界高程 is None else float(args.分界高程)

    dem_file = resolve_workspace_dem_path(paths["gis_dir"], prefer=infer_dem_kind_from_raster(config.get("DEM_tif", "")))
    with rasterio.open(dem_file) as src:
        dem = src.read(1)
        profile = src.profile.copy()

    valid = np.isfinite(dem) & (dem > 0)
    zone_low = ((dem < zone_threshold) & valid).astype(np.uint8)
    zone_high = ((dem >= zone_threshold) & valid).astype(np.uint8)

    save_zone(profile, zone_low, paths["gis_dir"] / "elevation_zone_low.tif")
    save_zone(profile, zone_high, paths["gis_dir"] / "elevation_zone_high.tif")
    save_zone(profile, zone_low + zone_high * 2, paths["gis_dir"] / "elevation_zones.tif")

    total = int(zone_low.sum() + zone_high.sum())
    print(f"低海拔像元: {int(zone_low.sum())}")
    print(f"高海拔像元: {int(zone_high.sum())} (分界高程 {zone_threshold:.1f} m)")
    print(f"总像元数: {total}")


if __name__ == "__main__":
    main()

