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
import pyproj
import rasterio

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "公共"))

from 公共函数 import config_base_dir, read_config, resolve_path  # type: ignore
from profile_runner import PROFILE_DAILY, build_profile_paths, configured_precip_source, resolve_profile


MIN_GRID_PRECIP_MM = 0.05
WET_STATION_MEAN_MM = 0.10
RATIO_CLIP = (0.2, 5.0)
IDW_POWER = 2.0
IDW_MIN_DISTANCE_M = 100.0
IDW_CHUNK_SIZE = 200_000


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
    parser.add_argument("--降水源", "--prec-source", dest="降水源", choices=["era5", "mswep", "cmfd", "custom_tif"], default=None)
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


def read_csv_auto(path: Path) -> pd.DataFrame:
    last_error: Exception | None = None
    for encoding in ("utf-8-sig", "utf-8", "gbk"):
        try:
            return pd.read_csv(path, encoding=encoding)
        except UnicodeDecodeError as exc:
            last_error = exc
    if last_error is not None:
        raise last_error
    return pd.read_csv(path)


def load_station_metadata(path: Path, raster_crs: Any) -> pd.DataFrame:
    frame = read_csv_auto(path)
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
    out["x_raw"] = pd.to_numeric(out["x_raw"], errors="coerce")
    out["y_raw"] = pd.to_numeric(out["y_raw"], errors="coerce")
    out["weight"] = pd.to_numeric(out["weight"], errors="coerce") if "weight" in out.columns else 1.0
    out["weight"] = out["weight"].fillna(1.0).clip(lower=0.0)
    out = out.dropna(subset=["x_raw", "y_raw"])
    if out.empty:
        raise ValueError("站点信息 csv 中没有有效坐标。")

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
    frame = read_csv_auto(path)
    time_col = detect_time_column(frame)
    id_col = detect_column(list(frame.columns), ["station_id", "station", "id", "name", "站点", "站号"])
    value_col = detect_column(list(frame.columns), ["precip", "prec", "ppt", "rain", "value", "降水", "降水量"])

    if id_col and value_col and id_col != time_col and value_col != time_col:
        data = frame[[time_col, id_col, value_col]].copy()
        data.columns = ["time", "station_id", "value"]
        data["time"] = pd.to_datetime(data["time"], errors="coerce")
        data["station_id"] = data["station_id"].astype(str).str.strip()
        data["value"] = pd.to_numeric(data["value"], errors="coerce")
        wide = data.pivot_table(index="time", columns="station_id", values="value", aggfunc="mean")
        wide.columns = [str(col).strip() for col in wide.columns]
        return wide.sort_index(), "long"

    wide = frame.copy()
    wide[time_col] = pd.to_datetime(wide[time_col], errors="coerce")
    wide = wide.set_index(time_col).sort_index()
    wide.columns = [str(col).strip() for col in wide.columns]
    for column in list(wide.columns):
        wide[column] = pd.to_numeric(wide[column], errors="coerce")
    return wide, "wide"


def base_and_target_dirs(config: dict[str, Any], prec_source: str) -> tuple[Path, Path]:
    profile = resolve_profile(config, None)
    paths = build_profile_paths(config, profile)
    if str(prec_source or "").strip().lower() == "custom_tif" or configured_precip_source(config) == "custom_tif":
        return Path(paths["aligned_prec_custom_base_dir"]), Path(paths["aligned_prec_custom_corrected_dir"])
    if prec_source == "era5":
        return Path(paths["aligned_prec_era5_base_dir"]), Path(paths["aligned_prec_era5_corrected_dir"])
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


def metric_transformer_for_points(raster_crs: Any, x_values: np.ndarray, y_values: np.ndarray) -> pyproj.Transformer | None:
    if raster_crs is None:
        return None
    crs = pyproj.CRS.from_user_input(raster_crs)
    if not crs.is_geographic:
        return None
    lon0 = float(np.nanmean(x_values)) if x_values.size else 0.0
    lat0 = float(np.nanmean(y_values)) if y_values.size else 0.0
    target = pyproj.CRS.from_proj4(
        f"+proj=aeqd +lat_0={lat0:.8f} +lon_0={lon0:.8f} +datum=WGS84 +units=m +no_defs"
    )
    return pyproj.Transformer.from_crs(crs, target, always_xy=True)


def transform_metric_xy(
    x_values: np.ndarray,
    y_values: np.ndarray,
    transformer: pyproj.Transformer | None,
) -> tuple[np.ndarray, np.ndarray]:
    if transformer is None:
        return x_values.astype("float64", copy=False), y_values.astype("float64", copy=False)
    mx, my = transformer.transform(x_values, y_values)
    return np.asarray(mx, dtype="float64"), np.asarray(my, dtype="float64")


def grid_cell_coordinates(mask: np.ndarray, transform: Any) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    rows, cols = np.where(mask)
    xs = transform.c + (cols + 0.5) * transform.a + (rows + 0.5) * transform.b
    ys = transform.f + (cols + 0.5) * transform.d + (rows + 0.5) * transform.e
    return rows, cols, xs.astype("float64"), ys.astype("float64")


def idw_interpolate_to_points(
    station_x: np.ndarray,
    station_y: np.ndarray,
    station_values: np.ndarray,
    target_x: np.ndarray,
    target_y: np.ndarray,
    *,
    power: float = IDW_POWER,
    min_distance: float = IDW_MIN_DISTANCE_M,
) -> np.ndarray:
    valid = np.isfinite(station_x) & np.isfinite(station_y) & np.isfinite(station_values)
    station_x = station_x[valid]
    station_y = station_y[valid]
    station_values = station_values[valid]
    if station_values.size == 0:
        return np.full(target_x.shape, np.nan, dtype="float64")
    if station_values.size == 1:
        return np.full(target_x.shape, float(station_values[0]), dtype="float64")

    result = np.empty(target_x.shape, dtype="float64")
    for start in range(0, target_x.size, IDW_CHUNK_SIZE):
        end = min(start + IDW_CHUNK_SIZE, target_x.size)
        dx = target_x[start:end, None] - station_x[None, :]
        dy = target_y[start:end, None] - station_y[None, :]
        dist = np.sqrt(dx * dx + dy * dy)
        exact = dist <= min_distance
        if np.any(exact):
            values = np.empty(end - start, dtype="float64")
            has_exact = exact.any(axis=1)
            first_exact = np.argmax(exact, axis=1)
            values[has_exact] = station_values[first_exact[has_exact]]
            if np.any(~has_exact):
                safe_dist = np.maximum(dist[~has_exact], min_distance)
                weights = 1.0 / np.power(safe_dist, power)
                values[~has_exact] = np.sum(weights * station_values[None, :], axis=1) / np.sum(weights, axis=1)
            result[start:end] = values
        else:
            safe_dist = np.maximum(dist, min_distance)
            weights = 1.0 / np.power(safe_dist, power)
            result[start:end] = np.sum(weights * station_values[None, :], axis=1) / np.sum(weights, axis=1)
    return result


def build_nearest_station_map(mask: np.ndarray, transform: Any, stations: pd.DataFrame, raster_crs: Any = None) -> np.ndarray:
    rows, cols, xs, ys = grid_cell_coordinates(mask, transform)
    station_x = stations["x"].to_numpy(dtype="float64")
    station_y = stations["y"].to_numpy(dtype="float64")
    transformer = metric_transformer_for_points(raster_crs, np.concatenate([xs, station_x]), np.concatenate([ys, station_y]))
    xs_m, ys_m = transform_metric_xy(xs, ys, transformer)
    station_x_m, station_y_m = transform_metric_xy(station_x, station_y, transformer)

    nearest = np.full(mask.shape, -1, dtype="int32")
    best = np.full(xs.shape, np.inf, dtype="float64")
    best_idx = np.full(xs.shape, -1, dtype="int32")
    for idx in range(len(station_x_m)):
        dist = (xs_m - station_x_m[idx]) ** 2 + (ys_m - station_y_m[idx]) ** 2
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
    no_station_step_count = 0
    clipped_step_count = 0
    occurrence_repair_count = 0
    total_valid_station_steps = 0
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
            valid = np.isfinite(obs) & np.isfinite(grid_station) & (obs >= 0.0) & (grid_station >= 0.0) & (weights > 0)
            out = arr.copy()
            if np.any(valid):
                obs_mean = np.average(obs[valid], weights=weights[valid])
                grid_mean = np.average(grid_station[valid], weights=weights[valid])
                total_valid_station_steps += int(np.sum(valid))
                valid_mask = np.isfinite(out)
                rows, cols, grid_x, grid_y = grid_cell_coordinates(valid_mask, src.transform)
                station_x = stations["x"].to_numpy(dtype="float64")
                station_y = stations["y"].to_numpy(dtype="float64")
                transformer = metric_transformer_for_points(
                    src.crs,
                    np.concatenate([grid_x, station_x]),
                    np.concatenate([grid_y, station_y]),
                )
                grid_x_m, grid_y_m = transform_metric_xy(grid_x, grid_y, transformer)
                station_x_m, station_y_m = transform_metric_xy(station_x, station_y, transformer)

                raw_ratios = obs[valid] / np.maximum(grid_station[valid], MIN_GRID_PRECIP_MM)
                clipped_ratios = np.clip(raw_ratios, RATIO_CLIP[0], RATIO_CLIP[1])
                if np.any(np.abs(raw_ratios - clipped_ratios) > 1e-9):
                    clipped_step_count += 1
                residuals = obs[valid] - grid_station[valid]

                ratio_values = idw_interpolate_to_points(
                    station_x_m[valid],
                    station_y_m[valid],
                    clipped_ratios,
                    grid_x_m,
                    grid_y_m,
                )
                residual_values = idw_interpolate_to_points(
                    station_x_m[valid],
                    station_y_m[valid],
                    residuals,
                    grid_x_m,
                    grid_y_m,
                )
                station_prec_values = idw_interpolate_to_points(
                    station_x_m[valid],
                    station_y_m[valid],
                    obs[valid],
                    grid_x_m,
                    grid_y_m,
                )

                base_values = out[rows, cols]
                ratio_corrected = base_values * ratio_values
                residual_corrected = np.clip(base_values + residual_values, 0.0, None)
                if np.isfinite(grid_mean) and np.isfinite(obs_mean) and grid_mean < MIN_GRID_PRECIP_MM and obs_mean >= WET_STATION_MEAN_MM:
                    corrected_values = np.clip(station_prec_values, 0.0, None)
                    occurrence_repair_count += 1
                else:
                    residual_weight = 0.0
                    if np.isfinite(grid_mean) and np.isfinite(obs_mean) and obs_mean > grid_mean:
                        residual_weight = float(np.clip((WET_STATION_MEAN_MM - grid_mean) / WET_STATION_MEAN_MM, 0.0, 1.0))
                    corrected_values = (1.0 - residual_weight) * ratio_corrected + residual_weight * residual_corrected
                    occurrence_gap = (base_values < MIN_GRID_PRECIP_MM) & (station_prec_values >= WET_STATION_MEAN_MM)
                    if np.any(occurrence_gap):
                        corrected_values[occurrence_gap] = np.maximum(
                            corrected_values[occurrence_gap],
                            residual_corrected[occurrence_gap],
                        )
                out[rows, cols] = np.clip(corrected_values, 0.0, None)
            else:
                no_station_step_count += 1
            profile = src.profile.copy()
            profile.update(dtype="float32", compress="lzw")
            if nodata is None:
                profile["nodata"] = -9999.0
            out_to_write = np.where(np.isfinite(out), out, profile["nodata"]).astype("float32")
            write_raster(output, profile, out_to_write)
            written += 1
    print(
        "空间订正摘要: "
        f"有效站点-时段样本 {total_valid_station_steps}；"
        f"无可用站点时段 {no_station_step_count}；"
        f"倍率裁剪时段 {clipped_step_count}；"
        f"格点漏报降水修复时段 {occurrence_repair_count}"
    )
    return written


def apply_thiessen(records: list[tuple[pd.Timestamp, Path]], target_dir: Path, stations: pd.DataFrame, station_series: pd.DataFrame, overwrite: bool) -> int:
    written = 0
    station_ids = stations["station_id"].tolist()
    nearest_cache: dict[tuple[int, ...], np.ndarray] = {}
    valid_mask: np.ndarray | None = None
    no_station_step_count = 0
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
            obs = station_series.loc[ts, station_ids].to_numpy(dtype="float64") if ts in station_series.index else np.full(len(station_ids), np.nan)
            out = np.full(arr.shape, np.nan, dtype="float64")
            mask = valid_mask if valid_mask is not None else np.isfinite(arr)
            available = tuple(int(idx) for idx in np.where(np.isfinite(obs) & (obs >= 0.0))[0])
            if available:
                if available not in nearest_cache:
                    nearest_cache[available] = build_nearest_station_map(
                        mask,
                        src.transform,
                        stations.iloc[list(available)].reset_index(drop=True),
                        src.crs,
                    )
                nearest_map = nearest_cache[available]
                rows, cols = np.where(mask)
                available_values = obs[list(available)]
                out[rows, cols] = available_values[nearest_map[rows, cols]]
            else:
                no_station_step_count += 1
                out[mask] = 0.0
            profile = src.profile.copy()
            profile.update(dtype="float32", compress="lzw")
            if nodata is None:
                profile["nodata"] = -9999.0
            out_to_write = np.where(np.isfinite(out), out, profile["nodata"]).astype("float32")
            write_raster(output, profile, out_to_write)
            written += 1
    print(
        "泰森分配摘要: "
        f"输出时段 {written}；"
        f"可用站点组合 {len(nearest_cache)}；"
        f"无可用站点时段 {no_station_step_count}"
    )
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
