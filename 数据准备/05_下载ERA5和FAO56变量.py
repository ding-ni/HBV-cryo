# -*- coding: utf-8 -*-
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "公共"))

from 公共函数 import (
    build_workspace_paths,
    ensure_workspace_dirs,
    example_config_path,
    load_legacy_module,
    old_script_path,
    patch_module,
    read_config,
    era5_download_bbox_list,
    year_range,
)


def main():
    parser = argparse.ArgumentParser(description="下载潜在蒸散发所需的 ERA5 / FAO56 变量。")
    parser.add_argument("--配置", "--config", dest="配置", default=str(example_config_path()))
    parser.add_argument("--内容", choices=["pet", "era5", "fao56", "mswep说明"], default="pet")
    args = parser.parse_args()

    config = read_config(args.配置)
    paths = build_workspace_paths(config)
    ensure_workspace_dirs(paths)
    years = list(year_range(config))
    meteo = dict(config.get("气象策略", {}))
    temp_source = str(meteo.get("温度来源", "era5")).strip().lower()
    prec_source = str(meteo.get("降水来源", meteo.get("降水源", config.get("默认降水源", "era5")))).strip().lower()
    pet_source = str(meteo.get("潜在蒸散发来源", meteo.get("蒸散发来源", "era5_fao56"))).strip().lower()
    need_prec_download = prec_source == "era5"
    need_temp_download = temp_source != "custom_tif" or pet_source != "custom_tif"
    need_pet_inputs = pet_source != "custom_tif"
    print("=" * 60)
    print("ERA5 变量下载")
    print("=" * 60)
    print(f"当前工作区运行目录: {paths['workspace_root']}")
    print(f"当前降水来源: {'ERA5 自动下载' if prec_source == 'era5' else '本地栅格' if prec_source == 'custom_tif' else '本地原始格点文件'}")
    print(f"当前气温来源: {'本地栅格' if temp_source == 'custom_tif' else 'ERA5'}")
    print(f"当前潜在蒸散发来源: {'本地栅格' if pet_source == 'custom_tif' else 'ERA5+FAO56'}")
    if not need_prec_download and not need_temp_download and not need_pet_inputs:
        print("当前方案不需要下载 ERA5 变量。")
        return
    if need_prec_download:
        print("本次下载：ERA5 total_precipitation 降水。")
    if need_pet_inputs and temp_source == "custom_tif":
        print("本次下载：用于计算潜在蒸散发的 ERA5 温度、太阳辐射、风速、露点。")
    elif need_pet_inputs:
        print("本次下载：ERA5 温度，以及计算潜在蒸散发要用的变量。")
    else:
        print("本次下载：ERA5 温度。")
    if not need_prec_download:
        print("这里不会下载降水。")
    print(f"ERA5 温度目录: {paths['raw_temp_dir']}")
    if need_pet_inputs:
        print(f"太阳辐射目录: {paths['raw_solar_dir']}")
        print(f"风速目录: {paths['raw_wind_dir']}")
        print(f"露点温度目录: {paths['raw_dewpoint_dir']}")
    download_bbox = era5_download_bbox_list(config)
    print(f"ERA5 下载范围[N,W,S,E]已外扩0.2°: {download_bbox}")

    if (need_temp_download or need_prec_download) and args.内容 in {"pet", "era5", "mswep说明"}:
        module = load_legacy_module(old_script_path(config, "scripts", "02_download_meteorological_data.py"))
        patch_module(
            module,
            {
                "PROJECT_ROOT": str(paths["workspace_root"]),
                "RAW_TEMP_DIR": str(paths["raw_temp_dir"]),
                "RAW_EVAP_DIR": str(paths["raw_evap_dir"]),
                "RAW_PREC_DIR": str(paths["raw_prec_root"]),
                "RAW_PREC_ERA5_DIR": str(paths["raw_prec_era5_dir"]),
                "TUOTUOHE_BBOX": download_bbox,
                "START_YEAR": years[0],
                "END_YEAR": years[-1],
            },
        )
        if args.内容 in {"pet", "era5"}:
            module.download_era5_all(
                download_precipitation=need_prec_download,
                download_temperature=need_temp_download,
            )
        if args.内容 == "mswep说明":
            module.print_mswep_instructions()

    if need_pet_inputs and args.内容 in {"pet", "fao56"}:
        module = load_legacy_module(old_script_path(config, "scripts", "02f_download_fao56_variables.py"))
        patch_module(
            module,
            {
                "PROJECT_ROOT": str(paths["workspace_root"]),
                "TUOTUOHE_BBOX": download_bbox,
                "START_YEAR": years[0],
                "END_YEAR": years[-1],
                "RAW_DIR": str(paths["raw_root"]),
                "SOLAR_DIR": str(paths["raw_solar_dir"]),
                "WIND_DIR": str(paths["raw_wind_dir"]),
                "DEWPOINT_DIR": str(paths["raw_dewpoint_dir"]),
            },
        )
        module.main()


if __name__ == "__main__":
    main()

