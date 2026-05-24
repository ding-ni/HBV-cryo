# -*- coding: utf-8 -*-
import argparse
import json
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
    infer_dem_kind_from_raster,
    load_legacy_module,
    old_script_path,
    patch_module,
    read_config,
    resolve_workspace_dem_path,
)


def main():
    parser = argparse.ArgumentParser(description="根据冰川 shp 生成 glacier_mask.tif。")
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
            print(f"[冰川] 未填写单独路径，改用内置冰川 shp: {glacier_shp}")
        else:
            summary_path = paths["gis_dir"] / "glacier_mask_summary.json"
            summary_path.write_text(
                json.dumps(
                    {
                        "status": "skipped",
                        "message": "没有填写冰川 shp，且当前安装内容中也没有找到内置冰川 shp，已跳过该步骤。",
                    },
                    ensure_ascii=False,
                    indent=2,
                ),
                encoding="utf-8",
            )
            print("[冰川] 未找到可用的冰川 shp，跳过生成冰川掩膜。")
            return
    if not Path(glacier_shp).exists():
        raise FileNotFoundError(f"冰川 shp 不存在: {glacier_shp}")
    dem_file = resolve_workspace_dem_path(paths["gis_dir"], prefer=infer_dem_kind_from_raster(config.get("DEM_tif", "")))

    module = load_legacy_module(old_script_path(config, "glacier", "06_make_glacier_mask_from_shp.py"))
    patch_module(
        module,
        {
            "PROJECT_ROOT": str(paths["workspace_root"]),
            "DATA_ROOT": str(paths["data_root"]),
            "GIS_ROOT": str(paths["gis_dir"]),
            "DEM_FILE": str(dem_file),
            "BASIN_SHP": str(basin["basin_shp"]),
            "GLACIER_SHP": str(glacier_shp),
            "OUT_FILE": str(paths["gis_dir"] / "glacier_mask.tif"),
            "FRACTION_FILE": str(paths["gis_dir"] / "glacier_fraction.tif"),
            "SUMMARY_FILE": str(paths["gis_dir"] / "glacier_mask_summary.json"),
        },
    )
    module.main()


if __name__ == "__main__":
    main()

