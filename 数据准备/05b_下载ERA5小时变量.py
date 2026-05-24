# -*- coding: utf-8 -*-
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "公共"))

from 公共函数 import bbox_dict, build_workspace_paths, ensure_workspace_dirs, example_config_path, read_config, year_range  # type: ignore


HOURLY_TIMES = [f"{hour:02d}:00" for hour in range(24)]


def check_cdsapi() -> None:
    try:
        import cdsapi  # noqa: F401
    except ImportError as exc:
        raise RuntimeError("缺少 cdsapi，请先安装：pip install cdsapi") from exc

    config_file = Path.home() / ".cdsapirc"
    if not config_file.exists():
        raise RuntimeError(f"未找到 CDS API 配置文件：{config_file}")


def download_variable(client, dataset: str, variable: str, year: int, area: list[float], output_file: Path) -> None:
    if output_file.exists():
        print(f"[跳过] 已存在 {output_file.name}")
        return
    output_file.parent.mkdir(parents=True, exist_ok=True)
    print(f"[下载] {output_file.name}")
    client.retrieve(
        dataset,
        {
            "variable": variable,
            "year": str(year),
            "month": [f"{month:02d}" for month in range(1, 13)],
            "day": [f"{day:02d}" for day in range(1, 32)],
            "time": HOURLY_TIMES,
            "area": area,
            "format": "netcdf",
        },
        str(output_file),
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="下载小时尺度 ERA5-Land 变量。")
    parser.add_argument("--配置", "--config", dest="配置", default=str(example_config_path()))
    args = parser.parse_args()

    check_cdsapi()
    import cdsapi

    config = read_config(args.配置)
    paths = build_workspace_paths(config)
    ensure_workspace_dirs(paths)
    bbox = bbox_dict(config)
    area = [bbox["lat_max"], bbox["lon_min"], bbox["lat_min"], bbox["lon_max"]]
    years = list(year_range(config))
    client = cdsapi.Client()

    for year in years:
        download_variable(client, "reanalysis-era5-land", "2m_temperature", year, area, paths["raw_temp_dir"] / f"era5_t2m_hourly_{year}.nc")
        download_variable(client, "reanalysis-era5-land", "surface_solar_radiation_downwards", year, area, paths["raw_solar_dir"] / f"era5_ssrd_hourly_{year}.nc")
        download_variable(client, "reanalysis-era5-land", "10m_u_component_of_wind", year, area, paths["raw_wind_dir"] / f"era5_u10_hourly_{year}.nc")
        download_variable(client, "reanalysis-era5-land", "10m_v_component_of_wind", year, area, paths["raw_wind_dir"] / f"era5_v10_hourly_{year}.nc")
        download_variable(client, "reanalysis-era5-land", "2m_dewpoint_temperature", year, area, paths["raw_dewpoint_dir"] / f"era5_d2m_hourly_{year}.nc")

    print("[完成] 小时尺度 ERA5 变量下载完成。")


if __name__ == "__main__":
    main()
