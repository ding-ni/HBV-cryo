# -*- coding: utf-8 -*-
from __future__ import annotations

import argparse
import sys
from datetime import timedelta
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
    data_date_range,
    ensure_workspace_dirs,
    era5_download_bbox_list,
    example_config_path,
    read_config,
)


def download_variable(client, dataset: str, variable: str, year: int, area: list[float], output_file: Path, *, chunk_months: int, start_date, end_date) -> None:
    cumulative = variable in ("total_precipitation", "surface_solar_radiation_downwards")
    request_start = start_date - timedelta(days=1) if cumulative else start_date
    download_era5_land_year_chunked(
        client,
        variable=variable,
        year=year,
        area=area,
        output_file=output_file,
        times=HOURLY_TIMES,
        chunk_months=chunk_months,
        start_date=request_start,
        end_date=end_date,
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
    start_date, end_date = data_date_range(config)
    # Hourly cumulative fields need the preceding hour at the interval start.
    years = list(range(start_date.year, end_date.year + 1))
    temp_source = str(meteo.get("温度来源", "era5")).lower()
    pet_source = str(meteo.get("潜在蒸散发来源", meteo.get("蒸散发来源", "era5_fao56"))).lower()
    client = cdsapi.Client()

    # January starts need a predecessor in the previous year's annual file.
    if start_date.month == 1 and start_date.day == 1:
        previous_year = start_date.year - 1
        for variable, key, prefix, needed in [
            ("total_precipitation", "raw_prec_era5_dir", "tp", prec_source == "era5"),
            ("surface_solar_radiation_downwards", "raw_solar_dir", "ssrd", pet_source != "custom_tif"),
        ]:
            if needed:
                download_variable(client, "reanalysis-era5-land", variable, previous_year, area,
                                  paths[key] / f"era5_{prefix}_hourly_{previous_year}.nc",
                                  chunk_months=chunk_months, start_date=start_date, end_date=end_date)

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
                start_date=start_date,
                end_date=end_date,
            )
        if temp_source == "custom_tif" and pet_source == "custom_tif":
            continue
        download_variable(
            client,
            "reanalysis-era5-land",
            "2m_temperature",
            year,
            area,
            paths["raw_temp_dir"] / f"era5_t2m_hourly_{year}.nc",
            chunk_months=chunk_months,
            start_date=start_date,
            end_date=end_date,
        )
        if pet_source == "custom_tif":
            continue
        download_variable(
            client,
            "reanalysis-era5-land",
            "surface_solar_radiation_downwards",
            year,
            area,
            paths["raw_solar_dir"] / f"era5_ssrd_hourly_{year}.nc",
            chunk_months=chunk_months,
            start_date=start_date,
            end_date=end_date,
        )
        download_variable(
            client,
            "reanalysis-era5-land",
            "10m_u_component_of_wind",
            year,
            area,
            paths["raw_wind_dir"] / f"era5_u10_hourly_{year}.nc",
            chunk_months=chunk_months,
            start_date=start_date,
            end_date=end_date,
        )
        download_variable(
            client,
            "reanalysis-era5-land",
            "10m_v_component_of_wind",
            year,
            area,
            paths["raw_wind_dir"] / f"era5_v10_hourly_{year}.nc",
            chunk_months=chunk_months,
            start_date=start_date,
            end_date=end_date,
        )
        download_variable(
            client,
            "reanalysis-era5-land",
            "2m_dewpoint_temperature",
            year,
            area,
            paths["raw_dewpoint_dir"] / f"era5_d2m_hourly_{year}.nc",
            chunk_months=chunk_months,
            start_date=start_date,
            end_date=end_date,
        )

    print("[完成] 小时尺度 ERA5 变量下载完成。")


if __name__ == "__main__":
    main()
