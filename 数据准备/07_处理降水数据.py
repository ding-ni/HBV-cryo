# -*- coding: utf-8 -*-
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "公共"))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "HBV-Studio"))

from 公共函数 import (
    bbox_dict,
    build_workspace_paths,
    ensure_workspace_dirs,
    example_config_path,
    load_legacy_module,
    old_script_path,
    patch_module,
    read_config,
    temporary_argv,
    year_range,
)
from services.raster_time_series import validate_tif_time_series  # type: ignore


def main():
    parser = argparse.ArgumentParser(description="处理降水数据，支持 MSWEP、CMFD 和本地栅格模式跳过。")
    parser.add_argument("--配置", "--config", dest="配置", default=str(example_config_path()))
    parser.add_argument("--降水源", "--prec-source", dest="降水源", choices=["era5", "mswep", "cmfd", "custom_tif"], default=None)
    parser.add_argument("--覆盖", action="store_true")
    args = parser.parse_args()

    config = read_config(args.配置)
    paths = build_workspace_paths(config)
    ensure_workspace_dirs(paths)
    years = list(year_range(config))
    configured_source = str(
        dict(config.get("气象策略", {})).get(
            "降水来源",
            dict(config.get("气象策略", {})).get("降水源", config.get("默认降水源", "era5")),
        )
    ).strip().lower()
    runtime_source = str(args.降水源 or configured_source or "era5").strip().lower()

    if runtime_source == "custom_tif":
        print("[跳过] 当前工作区为本地降水栅格模式，不执行格点降水预处理。")
        return

    if runtime_source == "era5":
        module = load_legacy_module(old_script_path(config, "scripts", "02b_process_era5_netcdf.py"))
        patch_module(
            module,
            {
                "PROJECT_ROOT": str(paths["workspace_root"]),
                "RAW_PREC_ERA5_DIR": str(paths["raw_prec_era5_dir"]),
                "PREC_ERA5_DAILY_DIR": str(paths["raw_prec_era5_daily_dir"]),
                "YEARS": years,
                "OVERWRITE": bool(args.覆盖),
            },
        )
        total = 0
        for year in years:
            total += module.process_precipitation(year)
        check = validate_tif_time_series("ERA5 日降水", Path(paths["raw_prec_era5_daily_dir"]), 24.0)
        print(f"[完成] ERA5 日降水：{check['period_summary']}")
        return

    if runtime_source == "mswep":
        module = load_legacy_module(old_script_path(config, "scripts", "02c_process_mswep.py"))
        patch_module(
            module,
            {
                "PROJECT_ROOT": str(paths["workspace_root"]),
                "MSWEP_INPUT_DIR": str(paths["raw_prec_mswep_dir"]),
                "PREC_OUTPUT_DIR": str(paths["raw_prec_daily_dir"]),
                "TUOTUOHE_BBOX": bbox_dict(config),
                "START_YEAR": years[0],
                "END_YEAR": years[-1],
            },
        )
        module.main()
        return

    flow_acc_masked = paths["gis_dir"] / "flow_accumulation_masked.tif"
    if not flow_acc_masked.exists():
        raise FileNotFoundError("CMFD 分支需要先生成 flow_accumulation_masked.tif。请先运行 12_生成汇流与流域掩膜.py")

    module = load_legacy_module(old_script_path(config, "scripts", "02i_process_cmfd.py"))
    patch_module(
        module,
        {
            "PROJECT_ROOT": str(paths["workspace_root"]),
            "CMFD_DIR": str(paths["raw_prec_cmfd_dir"]),
            "OUT_DIR": str(paths["raw_prec_cmfd_daily_dir"]),
            "FLOW_ACC_PATH": str(flow_acc_masked),
        },
    )

    argv = ["07_处理降水数据.py"]
    if args.覆盖:
        argv.append("--overwrite")
    with temporary_argv(argv):
        module.main()


if __name__ == "__main__":
    main()

