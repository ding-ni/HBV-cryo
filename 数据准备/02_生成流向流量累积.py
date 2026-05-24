# -*- coding: utf-8 -*-
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "公共"))

from 公共函数 import (
    add_hapi_src,
    build_workspace_paths,
    ensure_workspace_dirs,
    example_config_path,
    infer_dem_kind_from_raster,
    load_legacy_module,
    old_script_path,
    patch_module,
    print_config_summary,
    read_config,
    resolve_workspace_dem_path,
)


def main():
    parser = argparse.ArgumentParser(description="生成流向和流量累积栅格。")
    parser.add_argument("--配置", "--config", dest="配置", default=str(example_config_path()))
    parser.add_argument("--方法", choices=["whitebox", "arcpy"], default="whitebox")
    args = parser.parse_args()

    config = read_config(args.配置)
    paths = build_workspace_paths(config)
    ensure_workspace_dirs(paths)
    add_hapi_src(config)
    print_config_summary(config, paths)
    dem_path = resolve_workspace_dem_path(paths["gis_dir"], prefer=infer_dem_kind_from_raster(config.get("DEM_tif", "")))

    module = load_legacy_module(old_script_path(config, "scripts", "01_generate_flow_direction.py"))
    patch_module(
        module,
        {
            "GIS_DIR": str(paths["gis_dir"]),
            "DEM_INPUT": str(dem_path),
            "DEM_FILLED": str(paths["gis_dir"] / "dem_filled.tif"),
            "FLOW_DIR": str(paths["gis_dir"] / "flow_direction.tif"),
            "FLOW_ACC": str(paths["gis_dir"] / "flow_accumulation.tif"),
        },
    )

    if args.方法 == "whitebox":
        module.run_whitebox()
    else:
        module.run_arcpy()
    module.verify_results()


if __name__ == "__main__":
    main()

