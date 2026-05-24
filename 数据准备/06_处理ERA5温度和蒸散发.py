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
    year_range,
)


def main():
    parser = argparse.ArgumentParser(description="生成当前方案需要的日尺度结果。")
    parser.add_argument("--配置", "--config", dest="配置", default=str(example_config_path()))
    parser.add_argument("--蒸散发方法", choices=["fao56", "era5"], default="fao56")
    parser.add_argument("--覆盖", "--overwrite", dest="覆盖", action="store_true")
    args = parser.parse_args()

    config = read_config(args.配置)
    paths = build_workspace_paths(config)
    ensure_workspace_dirs(paths)
    years = list(year_range(config))
    meteo = dict(config.get("气象策略", {}))
    temp_source = str(meteo.get("温度来源", "era5")).strip().lower()
    pet_source = str(meteo.get("潜在蒸散发来源", meteo.get("蒸散发来源", "era5_fao56"))).strip().lower()
    need_temp_daily = temp_source != "custom_tif"
    need_pet_daily = pet_source != "custom_tif"

    if not need_temp_daily and not need_pet_daily:
        print("当前方案不需要生成日尺度气温或潜在蒸散发。")
        return

    era5_module = load_legacy_module(old_script_path(config, "scripts", "02b_process_era5_netcdf.py"))
    patch_module(
        era5_module,
        {
            "PROJECT_ROOT": str(paths["workspace_root"]),
            "RAW_TEMP_DIR": str(paths["raw_temp_dir"]),
            "RAW_EVAP_DIR": str(paths["raw_evap_dir"]),
            "TEMP_DAILY_DIR": str(paths["raw_temp_daily_dir"]),
            "EVAP_DAILY_DIR": str(paths["raw_evap_daily_dir"]),
            "YEARS": years,
            "OVERWRITE": bool(args.覆盖),
        },
    )

    if need_temp_daily or args.蒸散发方法 == "era5":
        for year in years:
            if need_temp_daily:
                era5_module.process_temperature(year)
            if need_pet_daily and args.蒸散发方法 == "era5":
                era5_module.process_evaporation(year)

    if need_pet_daily and args.蒸散发方法 == "fao56":
        et_module = load_legacy_module(old_script_path(config, "scripts", "02g_calculate_fao56_et.py"))
        patch_module(
            et_module,
            {
                "PROJECT_ROOT": str(paths["workspace_root"]),
                "TEMP_DIR": str(paths["raw_temp_dir"]),
                "SOLAR_DIR": str(paths["raw_solar_dir"]),
                "WIND_DIR": str(paths["raw_wind_dir"]),
                "DEWPOINT_DIR": str(paths["raw_dewpoint_dir"]),
                "OUTPUT_DIR": str(paths["raw_evap_daily_dir"]),
                "YEARS": years,
                "ELEVATION": float(config.get("FAO56平均海拔_m", 4500.0)),
                "OVERWRITE": bool(args.覆盖),
            },
        )
        for year in years:
            et_module.process_year(year)


if __name__ == "__main__":
    main()

