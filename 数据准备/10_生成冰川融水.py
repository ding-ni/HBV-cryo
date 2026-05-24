# -*- coding: utf-8 -*-
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "公共"))

from 公共函数 import (
    build_workspace_paths,
    ensure_workspace_dirs,
    example_config_path,
    infer_dem_kind_from_raster,
    load_legacy_module,
    old_script_path,
    patch_module,
    read_config,
    resolve_workspace_dem_path,
    temporary_argv,
)


def main():
    parser = argparse.ArgumentParser(description="利用温度和辐射生成冰川融水栅格。")
    parser.add_argument("--配置", "--config", dest="配置", default=str(example_config_path()))
    parser.add_argument("--覆盖", action="store_true")
    args = parser.parse_args()

    config = read_config(args.配置)
    paths = build_workspace_paths(config)
    ensure_workspace_dirs(paths)
    dem_path = resolve_workspace_dem_path(paths["gis_dir"], prefer=infer_dem_kind_from_raster(config.get("DEM_tif", "")))

    module = load_legacy_module(old_script_path(config, "glacier", "06_generate_glacier_melt_from_era5.py"))
    patch_module(
        module,
        {
            "PROJECT_ROOT": str(paths["workspace_root"]),
            "TEMP_DIR": str(paths["aligned_temp_dir"]),
            "RAD_DIR": str(paths["raw_solar_dir"]),
            "OUT_DIR": str(paths["glacier_melt_dir"]),
            "DEM_PATH": str(dem_path),
            "FLOW_ACC_PATH": str(paths["gis_dir"] / "flow_accumulation_masked.tif"),
            "GLACIER_MASK_PATH": str(paths["gis_dir"] / "glacier_mask.tif"),
        },
    )

    argv = ["10_生成冰川融水.py"]
    if args.覆盖:
        argv.append("--overwrite")
    else:
        argv.append("--no-overwrite")
    with temporary_argv(argv):
        module.main()


if __name__ == "__main__":
    main()

