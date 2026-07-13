from __future__ import annotations

from typing import Any
from pathlib import Path

import numpy as np
import pandas as pd
import xarray as xr


ERA5_ACCUMULATION_CONTRACT = "hbv_cryo_era5_accumulation_following_midnight_v1"


def boundary_file_candidates(directory: Any, prefix: str, year: int) -> list[Path]:
    root = Path(directory)
    next_year = int(year) + 1
    return [
        root / f"{prefix}_{next_year}.nc",
        root / f"{prefix}_boundary_{next_year}.nc",
        root / f"{prefix}_{next_year}_boundary.nc",
    ]


def find_boundary_file(directory: Any, prefix: str, year: int) -> Path:
    candidates = boundary_file_candidates(directory, prefix, year)
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    raise FileNotFoundError(
        f"{year} 年累计变量缺少次年 01-01 00:00 收尾样本；"
        f"请准备边界文件 {candidates[1]}。"
    )


def rename_time_dimension(values: xr.DataArray) -> xr.DataArray:
    time_name = "valid_time" if "valid_time" in values.dims else "time"
    if time_name not in values.dims:
        raise ValueError("ERA5 accumulation has no time dimension.")
    return values.rename({time_name: "time"}) if time_name != "time" else values


def append_following_midnight(
    values: xr.DataArray,
    boundary_values: xr.DataArray,
    *,
    boundary_time: Any,
) -> xr.DataArray:
    accumulation = rename_time_dimension(values)
    boundary = rename_time_dimension(boundary_values)
    target = pd.Timestamp(boundary_time)
    index = pd.DatetimeIndex(pd.to_datetime(boundary["time"].values))
    positions = np.flatnonzero(index == target)
    if positions.size != 1:
        raise ValueError(
            f"ERA5 boundary must contain exactly one {target.isoformat()} sample; "
            f"found {int(positions.size)}."
        )
    selected = boundary.isel(time=[int(positions[0])])
    combined = xr.concat([accumulation, selected], dim="time").sortby("time")
    combined_index = pd.DatetimeIndex(pd.to_datetime(combined["time"].values))
    if combined_index.has_duplicates:
        raise ValueError("ERA5 accumulation contains duplicate timestamps after boundary append.")
    return combined


def daily_totals_from_following_midnight(
    values: xr.DataArray,
    *,
    start_date: Any,
    end_date: Any,
) -> xr.DataArray:
    accumulation = rename_time_dimension(values)
    index = pd.DatetimeIndex(pd.to_datetime(accumulation["time"].values))
    if index.has_duplicates:
        raise ValueError("ERA5 accumulation contains duplicate timestamps.")
    days = pd.date_range(pd.Timestamp(start_date).normalize(), pd.Timestamp(end_date).normalize(), freq="1D")
    target_times = days + pd.Timedelta(days=1)
    positions = index.get_indexer(target_times)
    missing = np.flatnonzero(positions < 0)
    if missing.size:
        samples = [target_times[int(item)].isoformat() for item in missing[:5]]
        raise ValueError(
            "ERA5 accumulated daily totals require the following 00:00 sample; "
            f"missing {int(missing.size)} boundary timestamps, for example {samples}."
        )
    slices = [accumulation.isel(time=int(position)) for position in positions]
    return xr.concat(slices, dim=pd.Index(days, name="time"))
