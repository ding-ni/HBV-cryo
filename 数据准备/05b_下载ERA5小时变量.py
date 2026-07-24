# -*- coding: utf-8 -*-
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "公共"))

from cds_chunked_download import (  # type: ignore
    DEFAULT_CHUNK_MONTHS,
    HOURLY_TIMES,
    download_era5_land_year_chunked,
    ensure_cdsapi_configured,
    format_cds_size_error,
    summarize_request_cost_hint,
)
from 公共函数 import (  # type: ignore
    build_workspace_paths,
    ensure_workspace_dirs,
    era5_download_bbox_list,
    example_config_path,
    read_config,
    year_range,
)


def download_variable(client, dataset: str, variable: str, year: int, area: list[float], output_file: Path, *, chunk_months: int) -> None:
    download_era5_land_year_chunked(
        client,
        variable=variable,
        year=year,
        area=area,
        output_file=output_file,
        times=HOURLY_TIMES,
        chunk_months=chunk_months,
        dataset=dataset,
        on_chunk_error=lambda exc: format_cds_size_error(
            exc,
            hint="小时 ERA5-Land 请保持按月分片（默认 1 个月）；勿一次请求整年 24 小时数据。",
        ),
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="下载小时尺度 ERA5-Land 变量（按月分片，合并为年文件）。")
    parser.add_argument("--配置", "--config", dest="配置", default=str(example_config_path()))
    parser.add_argument(
        "--分片月数",
        "--chunk-months",
        dest="chunk_months",
        type=int,
        default=DEFAULT_CHUNK_MONTHS,
        help="每个 CDS 请求包含的月份数，默认 1。",
    )
    args = parser.parse_args()

    ensure_cdsapi_configured()
    import cdsapi

    config = read_config(args.配置)
    paths = build_workspace_paths(config)
    ensure_workspace_dirs(paths)
    meteo = dict(config.get("气象策略", {}))
    prec_source = str(meteo.get("降水来源", meteo.get("降水源", config.get("默认降水源", "era5")))).strip().lower()
    area = era5_download_bbox_list(config)
    chunk_months = max(1, min(int(args.chunk_months), 12))
    print(f"[范围] ERA5 小时下载范围[N,W,S,E]已外扩0.2°: {area}")
    print(f"[策略] {summarize_request_cost_hint(HOURLY_TIMES, chunk_months)}；最终仍输出按年 NC")
    years = list(year_range(config))
    client = cdsapi.Client()

    for year in years:
        if prec_source == "era5":
            download_variable(
                client,
                "reanalysis-era5-land",
                "total_precipitation",
                year,
                area,
                paths["raw_prec_era5_dir"] / f"era5_tp_hourly_{year}.nc",
                chunk_months=chunk_months,
            )
        download_variable(
            client,
            "reanalysis-era5-land",
            "2m_temperature",
            year,
            area,
            paths["raw_temp_dir"] / f"era5_t2m_hourly_{year}.nc",
            chunk_months=chunk_months,
        )
        download_variable(
            client,
            "reanalysis-era5-land",
            "surface_solar_radiation_downwards",
            year,
            area,
            paths["raw_solar_dir"] / f"era5_ssrd_hourly_{year}.nc",
            chunk_months=chunk_months,
        )
        download_variable(
            client,
            "reanalysis-era5-land",
            "10m_u_component_of_wind",
            year,
            area,
            paths["raw_wind_dir"] / f"era5_u10_hourly_{year}.nc",
            chunk_months=chunk_months,
        )
        download_variable(
            client,
            "reanalysis-era5-land",
            "10m_v_component_of_wind",
            year,
            area,
            paths["raw_wind_dir"] / f"era5_v10_hourly_{year}.nc",
            chunk_months=chunk_months,
        )
        download_variable(
            client,
            "reanalysis-era5-land",
            "2m_dewpoint_temperature",
            year,
            area,
            paths["raw_dewpoint_dir"] / f"era5_d2m_hourly_{year}.nc",
            chunk_months=chunk_months,
        )

    print("[完成] 小时尺度 ERA5 变量下载完成。")


if __name__ == "__main__":
    main()
