# -*- coding: utf-8 -*-
"""受控修复 ERA5-Land 累计太阳辐射的已知单点缺测。

ERA5-Land ``ssrd`` 是累计量，缺一个时刻会同时污染相邻小时差分。因此，
只有明确登记的单点单时刻允许在做差分前用四个周边网格点双线性插值；
其余缺测一律阻断流程，避免把数据源问题静默传播到模型结果。
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Iterable

import numpy as np
import pandas as pd
import xarray as xr


ERA5_SSRD_REPAIR_VERSION = "2026.10.05.2"
ERA5_SSRD_COORD_TOLERANCE = 1e-4

# 仅允许修复已经核实的 ERA5-Land 单点单时刻缺测。
ERA5_SSRD_REPAIR_WHITELIST = (
    {
        "time": pd.Timestamp("2022-02-01 01:00:00"),
        "longitude": 92.0,
        "latitude": 29.7,
        "reason": "CDS 原始传输包及独立 ssrd 重下载均复现的单点单时刻缺测",
    },
    {
        "time": pd.Timestamp("2023-01-28 01:00:00"),
        "longitude": 92.2,
        "latitude": 29.6,
        "reason": "ERA5-Land 原始 ssrd 已确认的单点单时刻缺测",
    },
)


def _time_dim(arr: xr.DataArray) -> str:
    if "valid_time" in arr.dims:
        return "valid_time"
    if "time" in arr.dims:
        return "time"
    raise ValueError("ERA5 ssrd 缺少 time/valid_time 时间维度。")


def _coord_name(arr: xr.DataArray, *names: str) -> str:
    for name in names:
        if name in arr.coords and name in arr.dims:
            return name
    raise ValueError(f"ERA5 ssrd 缺少一维坐标：{names}。")


def _missing_mask(values: np.ndarray, arr: xr.DataArray) -> np.ndarray:
    mask = ~np.isfinite(values)
    markers: list[float] = []
    for container in (arr.attrs, arr.encoding):
        for key in ("_FillValue", "missing_value"):
            value = container.get(key)
            if value is None:
                continue
            try:
                markers.extend(float(item) for item in np.asarray(value).reshape(-1))
            except (TypeError, ValueError):
                continue
    for marker in markers:
        if np.isfinite(marker):
            mask |= np.isclose(values, marker, rtol=0.0, atol=max(abs(marker) * 1e-12, 1e-12))
    return mask


def _find_index(values: np.ndarray, target: float, label: str) -> int:
    distances = np.abs(np.asarray(values, dtype=float) - float(target))
    index = int(np.nanargmin(distances))
    if not np.isfinite(distances[index]) or distances[index] > ERA5_SSRD_COORD_TOLERANCE:
        raise ValueError(
            f"白名单坐标 {label}={target} 不在 ERA5 网格中；最近值为 {values[index]!r}。"
        )
    return index


def _bracketing_indices(values: np.ndarray, target_index: int) -> tuple[int, int]:
    numeric = np.asarray(values, dtype=float)
    order = np.argsort(numeric)
    position = int(np.flatnonzero(order == target_index)[0])
    if position == 0 or position == len(order) - 1:
        raise ValueError("白名单缺测点位于网格边界，无法使用四个周边网格点插值。")
    return int(order[position - 1]), int(order[position + 1])


def _file_records(source_paths: Iterable[Path | str] | None) -> list[dict[str, object]]:
    records: list[dict[str, object]] = []
    for raw_path in source_paths or ():
        path = Path(raw_path)
        item: dict[str, object] = {"path": str(path)}
        if path.is_file():
            digest = hashlib.sha256()
            try:
                with path.open("rb") as handle:
                    for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                        digest.update(chunk)
                item["sha256"] = digest.hexdigest()
                item["size"] = path.stat().st_size
            except OSError as exc:
                item["hash_error"] = str(exc)
        records.append(item)
    return records


def repair_ssrd_single_point(
    arr: xr.DataArray,
    *,
    source_paths: Iterable[Path | str] | None = None,
    report_path: Path | str | None = None,
) -> xr.DataArray:
    """修复白名单中的 `ssrd` 缺测，并返回与输入维度顺序一致的数组。"""
    time_dim = _time_dim(arr)
    lon_name = _coord_name(arr, "longitude", "lon")
    lat_name = _coord_name(arr, "latitude", "lat")
    if arr.ndim != 3:
        raise ValueError(f"ERA5 ssrd 应为三维时间-纬度-经度数组，实际维度为 {arr.dims}。")

    work = arr.transpose(time_dim, lat_name, lon_name)
    values = np.asarray(work.values, dtype=np.float64).copy()
    times = pd.DatetimeIndex(pd.to_datetime(work[time_dim].values))
    lons = np.asarray(work[lon_name].values, dtype=float)
    lats = np.asarray(work[lat_name].values, dtype=float)
    missing = _missing_mask(values, work)
    repairs: list[dict[str, object]] = []

    for case in ERA5_SSRD_REPAIR_WHITELIST:
        timestamp = pd.Timestamp(case["time"])
        time_matches = np.flatnonzero(times == timestamp)
        if len(time_matches) == 0:
            continue
        # A project may not cover this registered location. Such a grid must
        # still pass its own quality audit, but has nothing to repair here.
        if (not np.any(np.isclose(lons, float(case["longitude"]), rtol=0.0, atol=ERA5_SSRD_COORD_TOLERANCE))
                or not np.any(np.isclose(lats, float(case["latitude"]), rtol=0.0, atol=ERA5_SSRD_COORD_TOLERANCE))):
            continue
        time_index = int(time_matches[0])
        lon_index = _find_index(lons, float(case["longitude"]), "longitude")
        lat_index = _find_index(lats, float(case["latitude"]), "latitude")
        if not missing[time_index, lat_index, lon_index]:
            continue

        lat_lo, lat_hi = _bracketing_indices(lats, lat_index)
        lon_lo, lon_hi = _bracketing_indices(lons, lon_index)
        corner_indices = {
            "southwest": (lat_lo, lon_lo),
            "southeast": (lat_lo, lon_hi),
            "northwest": (lat_hi, lon_lo),
            "northeast": (lat_hi, lon_hi),
        }
        corner_values = {
            name: float(values[time_index, lat_idx, lon_idx])
            for name, (lat_idx, lon_idx) in corner_indices.items()
        }
        if any(missing[time_index, lat_idx, lon_idx] for lat_idx, lon_idx in corner_indices.values()):
            raise ValueError(
                f"ERA5-Land ssrd 白名单点 {timestamp:%Y-%m-%d %H:%M} "
                f"({case['longitude']}, {case['latitude']}) 的四个周边网格点也有缺测，拒绝静默填补。"
            )

        lon0, lon1 = sorted((float(lons[lon_lo]), float(lons[lon_hi])))
        lat0, lat1 = sorted((float(lats[lat_lo]), float(lats[lat_hi])))
        tx = (float(case["longitude"]) - lon0) / (lon1 - lon0)
        ty = (float(case["latitude"]) - lat0) / (lat1 - lat0)
        interpolated = (
            (1.0 - tx) * (1.0 - ty) * corner_values["southwest"]
            + tx * (1.0 - ty) * corner_values["southeast"]
            + (1.0 - tx) * ty * corner_values["northwest"]
            + tx * ty * corner_values["northeast"]
        )
        if not np.isfinite(interpolated):
            raise ValueError("ERA5-Land ssrd 双线性插值结果不是有限值。")
        interpolated = max(float(interpolated), 0.0)
        values[time_index, lat_index, lon_index] = interpolated
        missing[time_index, lat_index, lon_index] = False
        repairs.append(
            {
                "time_utc": timestamp.strftime("%Y-%m-%dT%H:%M:%SZ"),
                "longitude": float(case["longitude"]),
                "latitude": float(case["latitude"]),
                "method": "bilinear_interpolation_from_four_diagonal_neighbors",
                "neighbor_values": corner_values,
                "interpolated_value": interpolated,
                "reason": case["reason"],
            }
        )

    result = xr.DataArray(values, coords=work.coords, dims=work.dims, attrs=work.attrs, name=work.name)
    result = result.transpose(*arr.dims)
    # Preserve encoded finite fill markers so other, unregistered missing
    # cells remain detectable by the mandatory post-repair quality audit.
    result.encoding = dict(arr.encoding)
    if repairs and report_path is not None:
        report = {
            "schema": "hbv_era5_ssrd_repair_manifest_v1",
            "repair_version": ERA5_SSRD_REPAIR_VERSION,
            "source_files": _file_records(source_paths),
            "repairs": repairs,
        }
        path = Path(report_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return result


def validate_ssrd_cumulative(arr: xr.DataArray, *, label: str = "ERA5-Land ssrd") -> None:
    """在累计差分前阻断白名单之外的缺测。"""
    time_dim = _time_dim(arr)
    lon_name = _coord_name(arr, "longitude", "lon")
    lat_name = _coord_name(arr, "latitude", "lat")
    work = arr.transpose(time_dim, lat_name, lon_name)
    values = np.asarray(work.values, dtype=np.float64)
    bad = _missing_mask(values, work)
    if not bad.any():
        return
    time_index, lat_index, lon_index = (int(item) for item in np.argwhere(bad)[0])
    timestamp = pd.Timestamp(work[time_dim].values[time_index])
    longitude = float(work[lon_name].values[lon_index])
    latitude = float(work[lat_name].values[lat_index])
    raise ValueError(
        f"{label} 在累计差分前仍有未处理缺测：{timestamp:%Y-%m-%d %H:%M} UTC "
        f"({longitude:.6f}, {latitude:.6f})。仅允许白名单中的已确认单点缺测。"
    )
