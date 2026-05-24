#!/usr/bin/env python
# -*- coding: utf-8 -*-
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import rasterio

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "公共"))

from 公共函数 import config_base_dir, read_config, resolve_path  # type: ignore
from profile_runner import PROFILE_DAILY, build_profile_paths, configured_precip_source, resolve_profile


DATE_PATTERNS = [
    ("%Y.%m.%d.%H.%M", [r"\d{4}\.\d{2}\.\d{2}\.\d{2}\.\d{2}"]),
    ("%Y.%m.%d.%H", [r"\d{4}\.\d{2}\.\d{2}\.\d{2}"]),
    ("%Y-%m-%d %H:%M", [r"\d{4}-\d{2}-\d{2} \d{2}:\d{2}"]),
    ("%Y-%m-%dT%H:%M", [r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}"]),
    ("%Y.%m.%d", [r"\d{4}\.\d{2}\.\d{2}"]),
    ("%Y-%m-%d", [r"\d{4}-\d{2}-\d{2}"]),
]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Apply precipitation strategy for HBV-Studio workspaces.")
    parser.add_argument("--配置", "--config", dest="配置", required=True)
    parser.add_argument("--降水源", "--prec-source", dest="降水源", choices=["mswep", "cmfd", "custom_tif"], default=None)
    parser.add_argument("--覆盖", "--overwrite", dest="覆盖", action="store_true")
    return parser.parse_args()


def parse_time_from_name(name: str) -> pd.Timestamp | None:
    stem = Path(name).stem
    for fmt, patterns in DATE_PATTERNS:
        for pattern in patterns:
            match = re.search(pattern, stem)
            if match:
                try:
                    return pd.to_datetime(match.group(0), format=fmt)
                except Exception:
                    pass
    try:
        return pd.to_datetime(stem)
    except Exception:
        return None


def detect_column(columns: list[str], candidates: list[str]) -> str | None:
    lowered = {col.lower(): col for col in columns}
    for candidate in candidates:
        if candidate.lower() in lowered:
            return lowered[candidate.lower()]
    return None


def detect_time_column(frame: pd.DataFrame) -> str:
    for column in frame.columns:
        parsed = pd.to_datetime(frame[column], errors="coerce")
        if parsed.notna().sum() >= max(1, len(frame) // 3):
            return column
    raise ValueError("未识别到时间列。")


def load_station_metadata(path: Path, raster_crs: Any) -> pd.DataFrame:
    frame = pd.read_csv(path)
    columns = list(frame.columns)
    id_col = detect_column(columns, ["station_id", "station", "id", "name", "站点", "站号"])
    lon_col = detect_column(columns, ["lon", "longitude", "x", "经度"])
    lat_col = detect_column(columns, ["lat", "latitude", "y", "纬度"])
    weight_col = detect_column(columns, ["weight", "thiessen_weight", "area_weight", "权重"])
    if not id_col or not lon_col or not lat_col:
        raise ValueError("站点信息 csv 至少需要站号、经度、纬度字段。")

    out = frame[[id_col, lon_col, lat_col] + ([weight_col] if weight_col else [])].copy()
    out.columns = ["station_id", "x_raw", "y_raw"] + (["weight"] if weight_col else [])
    out["station_id"] = out["station_id"].astype(str).str.strip()
    out["weight"] = out["weight"] if "weight" in out.columns else 1.0

    import geopandas as gpd

    looks_like_lonlat = out["x_raw"].abs().max() <= 180 and out["y_raw"].abs().max() <= 90
    crs = "EPSG:4326" if looks_like_lonlat else raster_crs
    gdf = gpd.GeoDataFrame(out, geometry=gpd.points_from_xy(out["x_raw"], out["y_raw"]), crs=crs)
    if raster_crs is not None:
        gdf = gdf.to_crs(raster_crs)
    gdf["x"] = gdf.geometry.x
    gdf["y"] = gdf.geometry.y
    return pd.DataFrame(gdf.drop(columns=["geometry"]))


def load_station_precip(path: Path) -> tuple[pd.DataFrame, str]:
    frame = pd.read_csv(path)
    time_col = detect_time_column(frame)
    id_col = detect_column(list(frame.columns), ["station_id", "station", "id", "name", "站点", "站号"])
    value_col = detect_column(list(frame.columns), ["precip", "prec", "ppt", "rain", "value", "降水", "降水量"])

    if id_col and value_col and id_col != time_col and value_col != time_col:
        data = frame[[time_col, id_col, value_col]].copy()
        data.columns = ["time", "station_id", "value"]
        data["time"] = pd.to_datetime(data["time"], errors="coerce")
        data["station_id"] = data["station_id"].astype(str).str.strip()
        wide = data.pivot_table(index="time", columns="station_id", values="value", aggfunc="mean")
        return wide.sort_index(), "long"

    wide = frame.copy()
    wide[time_col] = pd.to_datetime(wide[time_col], errors="coerce")
    wide = wide.set_index(time_col).sort_index()
    wide.columns = [str(col).strip() for col in wide.columns]
    return wide, "wide"


def base_and_target_dirs(config: dict[str, Any], prec_source: str) -> tuple[Path, Path]:
    profile = resolve_profile(config, None)
    paths = build_profile_paths(config, profile)
    if str(prec_source or "").strip().lower() == "custom_tif" or configured_precip_source(config) == "custom_tif":
        return Path(paths["aligned_prec_custom_base_dir"]), Path(paths["aligned_prec_custom_corrected_dir"])
    if prec_source == "cmfd":
        return Path(paths["aligned_prec_cmfd_base_dir"]), Path(paths["aligned_prec_cmfd_corrected_dir"])
    return Path(paths["aligned_prec_base_dir"]), Path(paths["aligned_prec_corrected_dir"])


def resolve_config_entry_path(config: dict[str, Any], raw_value: Any) -> Path:
    base = config_base_dir(config)
    resolved = resolve_path(str(raw_value or "").strip(), base=base)
    if resolved is None:
        return Path("")
    return Path(resolved).resolve(strict=False)


def list_rasters(directory: Path) -> list[tuple[pd.Timestamp, Path]]:
    records: list[tuple[pd.Timestamp, Path]] = []
    for path in directory.glob("*.tif"):
        ts = parse_time_from_name(path.name)
        if ts is not None:
            records.append((ts, path))
    return sorted(records, key=lambda item: item[0])


def sample_station_values(src: rasterio.io.DatasetReader, stations: pd.DataFrame) -> np.ndarray:
    coords = [(float(row.x), float(row.y)) for row in stations.itertuples(index=False)]
    samples = np.array([value[0] for value in src.sample(coords)], dtype="float64")
    if src.nodata is not None:
        samples[samples == src.nodata] = np.nan
    samples[samples < -9000] = np.nan
    return samples


def build_nearest_station_map(mask: np.ndarray, transform: Any, stations: pd.DataFrame) -> np.ndarray:
    rows, cols = np.where(mask)
    xs = transform.c + (cols + 0.5) * transform.a + (rows + 0.5) * transform.b
    ys = transform.f + (cols + 0.5) * transform.d + (rows + 0.5) * transform.e
    station_x = stations["x"].to_numpy(dtype="float64")
    station_y = stations["y"].to_numpy(dtype="float64")

    nearest = np.full(mask.shape, -1, dtype="int32")
    best = np.full(xs.shape, np.inf, dtype="float64")
    best_idx = np.full(xs.shape, -1, dtype="int32")
    for idx in range(len(station_x)):
        dist = (xs - station_x[idx]) ** 2 + (ys - station_y[idx]) ** 2
        update = dist < best
        best[update] = dist[update]
        best_idx[update] = idx
    nearest[rows, cols] = best_idx
    return nearest


def write_raster(output_path: Path, profile: dict[str, Any], data: np.ndarray) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with rasterio.open(output_path, "w", **profile) as dst:
        dst.write(data.astype(profile["dtype"]), 1)


def apply_grid_bias_correction(records: list[tuple[pd.Timestamp, Path]], target_dir: Path, stations: pd.DataFrame, station_series: pd.DataFrame, overwrite: bool) -> int:
    written = 0
    weights = stations["weight"].to_numpy(dtype="float64")
    station_ids = stations["station_id"].tolist()
    for ts, path in records:
        output = target_dir / path.name
        if output.exists() and not overwrite:
            written += 1
            continue
        with rasterio.open(path) as src:
            arr = src.read(1).astype("float64")
            nodata = src.nodata
            if nodata is not None:
                arr[arr == nodata] = np.nan
            grid_station = sample_station_values(src, stations)
            obs = station_series.loc[ts, station_ids].to_numpy(dtype="float64") if ts in station_series.index else np.full(len(station_ids), np.nan)
            valid = np.isfinite(obs) & np.isfinite(grid_station) & (weights > 0)
            ratio = 1.0
            if np.any(valid):
                obs_mean = np.average(obs[valid], weights=weights[valid])
                grid_mean = np.average(grid_station[valid], weights=weights[valid])
                if np.isfinite(obs_mean) and np.isfinite(grid_mean):
                    if abs(grid_mean) < 1e-6 and abs(obs_mean) < 1e-6:
                        ratio = 1.0
                    else:
                        ratio = obs_mean / max(grid_mean, 1e-6)
                        ratio = float(np.clip(ratio, 0.2, 5.0))
            out = arr.copy()
            valid_mask = np.isfinite(out)
            out[valid_mask] = np.clip(out[valid_mask] * ratio, 0.0, None)
            profile = src.profile.copy()
            profile.update(dtype="float32", compress="lzw")
            if nodata is None:
                profile["nodata"] = -9999.0
            out_to_write = np.where(np.isfinite(out), out, profile["nodata"]).astype("float32")
            write_raster(output, profile, out_to_write)
            written += 1
    return written


def apply_thiessen(records: list[tuple[pd.Timestamp, Path]], target_dir: Path, stations: pd.DataFrame, station_series: pd.DataFrame, overwrite: bool) -> int:
    written = 0
    station_ids = stations["station_id"].tolist()
    nearest_map: np.ndarray | None = None
    valid_mask: np.ndarray | None = None
    for ts, path in records:
        output = target_dir / path.name
        if output.exists() and not overwrite:
            written += 1
            continue
        with rasterio.open(path) as src:
            arr = src.read(1).astype("float64")
            nodata = src.nodata
            if nodata is not None:
                arr[arr == nodata] = np.nan
            if valid_mask is None:
                valid_mask = np.isfinite(arr)
                nearest_map = build_nearest_station_map(valid_mask, src.transform, stations)
            obs = station_series.loc[ts, station_ids].to_numpy(dtype="float64") if ts in station_series.index else np.full(len(station_ids), np.nan)
            if np.isfinite(obs).any():
                fill_value = float(np.nanmean(obs))
                obs = np.where(np.isfinite(obs), obs, fill_value)
            else:
                obs = np.full_like(obs, 0.0)
            out = np.full(arr.shape, np.nan, dtype="float64")
            mask = valid_mask if valid_mask is not None else np.isfinite(arr)
            assert nearest_map is not None
            rows, cols = np.where(mask)
            out[rows, cols] = obs[nearest_map[rows, cols]]
            profile = src.profile.copy()
            profile.update(dtype="float32", compress="lzw")
            if nodata is None:
                profile["nodata"] = -9999.0
            out_to_write = np.where(np.isfinite(out), out, profile["nodata"]).astype("float32")
            write_raster(output, profile, out_to_write)
            written += 1
    return written


def main() -> None:
    args = parse_args()
    config = read_config(args.配置)
    meteo = dict(config.get("气象策略", {}))
    mode = str(meteo.get("降水方案", "grid_only")).strip()
    prec_source = args.降水源 or configured_precip_source(config)
    profile = resolve_profile(config, None)
    base_dir, target_dir = base_and_target_dirs(config, prec_source)

    if mode == "grid_only":
      print("当前降水方案为 grid_only，不需要额外处理。")
      return

    if not base_dir.exists():
        raise FileNotFoundError(f"基础降水目录不存在：{base_dir}")
    records = list_rasters(base_dir)
    if not records:
        raise FileNotFoundError(f"基础降水目录没有 tif：{base_dir}")

    station_prec_path = resolve_config_entry_path(config, meteo.get("站点降水_csv", ""))
    station_meta_path = resolve_config_entry_path(config, meteo.get("站点信息_csv", ""))
    if not station_prec_path.exists():
        raise FileNotFoundError(f"站点降水文件不存在：{station_prec_path}")
    if not station_meta_path.exists():
        raise FileNotFoundError(f"站点信息文件不存在：{station_meta_path}")

    with rasterio.open(records[0][1]) as src:
        stations = load_station_metadata(station_meta_path, src.crs)
    station_series, fmt = load_station_precip(station_prec_path)
    station_series.index = pd.to_datetime(station_series.index)
    station_series.columns = [str(col).strip() for col in station_series.columns]
    available_ids = set(station_series.columns)
    stations = stations[stations["station_id"].isin(available_ids)].copy()
    if stations.empty:
        raise ValueError("站点信息与站点降水之间没有可匹配的站号。")

    print(f"率定模式: {profile}")
    print(f"降水方案: {mode}")
    print(f"降水源: {prec_source}")
    print(f"基础目录: {base_dir}")
    print(f"目标目录: {target_dir}")
    print(f"站点格式: {fmt}")
    print(f"匹配站点数: {len(stations)}")
    print(f"时间步文件数: {len(records)}")

    target_dir.mkdir(parents=True, exist_ok=True)
    if mode == "grid_plus_station_bias":
        written = apply_grid_bias_correction(records, target_dir, stations, station_series, args.覆盖)
    elif mode == "thiessen_station_only":
        written = apply_thiessen(records, target_dir, stations, station_series, args.覆盖)
    else:
        raise ValueError(f"未知降水方案：{mode}")
    print(f"完成：{written} 个文件写入 {target_dir}")


if __name__ == "__main__":
    main()
