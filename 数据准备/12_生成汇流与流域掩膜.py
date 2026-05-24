# -*- coding: utf-8 -*-
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "公共"))

from 公共函数 import (
    basin_paths,
    build_workspace_paths,
    ensure_workspace_dirs,
    example_config_path,
    mask_raster_to_basin,
    read_config,
)


def main():
    parser = argparse.ArgumentParser(description="生成 flow_direction_masked 和 flow_accumulation_masked。")
    parser.add_argument("--配置", "--config", dest="配置", default=str(example_config_path()))
    args = parser.parse_args()

    config = read_config(args.配置)
    paths = build_workspace_paths(config)
    basin = basin_paths(config)
    ensure_workspace_dirs(paths)

    mask_raster_to_basin(
        paths["gis_dir"] / "flow_direction.tif",
        paths["gis_dir"] / "flow_direction_masked.tif",
        basin["basin_shp"],
    )
    mask_raster_to_basin(
        paths["gis_dir"] / "flow_accumulation.tif",
        paths["gis_dir"] / "flow_accumulation_masked.tif",
        basin["basin_shp"],
    )
    print("已生成掩膜后的流向和流量累积文件。")


if __name__ == "__main__":
    main()

