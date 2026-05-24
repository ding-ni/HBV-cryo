# -*- coding: utf-8 -*-
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "公共"))

from 公共函数 import (
    add_hapi_src,
    basin_paths,
    build_workspace_paths,
    ensure_workspace_dirs,
    example_config_path,
    infer_dem_kind_from_raster,
    load_legacy_module,
    old_script_path,
    patch_module,
    print_config_summary,
    read_config,
    remove_other_workspace_dem_variants,
    workspace_dem_filename,
)


def main():
    parser = argparse.ArgumentParser(description="裁剪 DEM 到当前流域运行目录。")
    parser.add_argument("--配置", "--config", dest="配置", default=str(example_config_path()))
    parser.add_argument("--重采样到1km", action="store_true")
    args = parser.parse_args()

    config = read_config(args.配置)
    paths = build_workspace_paths(config)
    basin = basin_paths(config)
    ensure_workspace_dirs(paths)
    add_hapi_src(config)
    print_config_summary(config, paths)
    dem_kind = infer_dem_kind_from_raster(basin["raw_dem"])
    output_dem = paths["gis_dir"] / workspace_dem_filename(dem_kind)

    module = load_legacy_module(old_script_path(config, "scripts", "00b_clip_dem.py"))
    patch_module(
        module,
        {
            "PROJECT_ROOT": str(paths["workspace_root"]),
            "TP_DEM_FILE": str(basin["raw_dem"]),
            "BASIN_SHP": str(basin["basin_shp"]),
            "OUTPUT_DEM": str(output_dem),
        },
    )

    ok = module.clip_dem_to_basin()
    if not ok:
        raise RuntimeError(f"DEM 裁剪未完成，未生成预期文件：{output_dem}")
    if not output_dem.exists():
        raise FileNotFoundError(f"DEM 裁剪步骤返回成功，但未找到输出文件：{output_dem}")

    remove_other_workspace_dem_variants(paths["gis_dir"], output_dem)
    if args.重采样到1km and hasattr(module, "resample_to_1km"):
        if dem_kind == "0p1deg":
            print("当前 DEM 已识别为 0.1° 档位，跳过“重采样到1km”。")
            return
        module.resample_to_1km()
        if not output_dem.exists():
            raise FileNotFoundError(f"DEM 重采样后未找到输出文件：{output_dem}")


if __name__ == "__main__":
    main()

