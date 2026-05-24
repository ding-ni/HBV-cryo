# -*- coding: utf-8 -*-
import argparse
import importlib
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "公共"))

from 公共函数 import (
    add_hapi_src,
    basin_paths,
    build_workspace_paths,
    default_builtin_glacier_path,
    ensure_workspace_dirs,
    example_config_path,
    patch_module,
    read_config,
)


def main():
    parser = argparse.ArgumentParser(
        description="从高分辨率 (1km) DEM 提取每个 0.1° 像元内冰川区的面积加权平均高程，生成 glacier_elev.tif。"
    )
    parser.add_argument("--配置", "--config", dest="配置", default=str(example_config_path()))
    args = parser.parse_args()

    config = read_config(args.配置)
    paths = build_workspace_paths(config)
    basin = basin_paths(config)
    ensure_workspace_dirs(paths)
    add_hapi_src(config)

    glacier_shp = basin["glacier_shp"]
    if not glacier_shp:
        builtin_glacier_shp = default_builtin_glacier_path()
        if builtin_glacier_shp.exists():
            glacier_shp = builtin_glacier_shp
            print(f"[冰川高程] 未填写单独路径，改用内置冰川 shp: {glacier_shp}")
        else:
            print("[冰川高程] 未找到可用的冰川 shp，跳过 glacier_elev.tif 生成。")
            return
    if not Path(glacier_shp).exists():
        raise FileNotFoundError(f"冰川 shp 不存在: {glacier_shp}")

    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    if "公共.内部实现.生成冰川高程栅格" in sys.modules:
        module = importlib.reload(sys.modules["公共.内部实现.生成冰川高程栅格"])
    else:
        module = importlib.import_module("公共.内部实现.生成冰川高程栅格")

    patch_module(
        module,
        {
            "PROJECT_ROOT": str(paths["workspace_root"]),
            "DATA_ROOT": str(paths["data_root"]),
            "GIS_ROOT": str(paths["gis_dir"]),
            "BASIN_SHP": str(basin["basin_shp"]),
            "GLACIER_SHP": str(glacier_shp),
            "OUT_FILE": str(paths["gis_dir"] / "glacier_elev.tif"),
            "SUMMARY_FILE": str(paths["gis_dir"] / "glacier_elev_summary.json"),
        },
    )
    module.main()


if __name__ == "__main__":
    main()
