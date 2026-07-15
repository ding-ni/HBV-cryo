#!/usr/bin/env python
# -*- coding: utf-8 -*-
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
import time
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import pyproj
import rasterio

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "公共"))

from 公共函数 import config_base_dir, read_config, resolve_path  # type: ignore
from profile_runner import PROFILE_DAILY, build_profile_paths, configured_precip_source, resolve_profile
from services.time_utils import summarize_time_coverage, time_step_count_text


MIN_GRID_PRECIP_MM = 0.05
WET_STATION_MEAN_MM = 0.10
RATIO_CLIP = (0.2, 5.0)
STATION_CORRECTION_ALGORITHM_V2 = "occurrence_amount_v2"
STATION_CORRECTION_ALGORITHM_LEGACY = "legacy_ratio_v1"
DEFAULT_STATION_CORRECTION_ALGORITHM = STATION_CORRECTION_ALGORITHM_V2
CONFIG_FALLBACK_STATION_CORRECTION_ALGORITHM = STATION_CORRECTION_ALGORITHM_LEGACY
MIN_STATION_SUPPORT_RADIUS_M = 30_000.0
OCCURRENCE_DECISION_THRESHOLD = 0.5
EXACT_DRY_CONFIDENCE = 0.8
MAX_MONTHLY_REDISTRIBUTION_FACTOR = 2.0
MAX_MONTHLY_REMOVED_FRACTION = 0.30
IDW_POWER = 2.0
IDW_MIN_DISTANCE_M = 100.0
IDW_CHUNK_SIZE = 200_000
HYDROLOGICAL_DAY_START_HOUR = 8
MIN_DAILY_PRECIP_HOURS = 24
TRANSFER_RULES_JSON = "station_bias_transfer_rules.json"
TRANSFER_RULES_NPZ = "station_bias_transfer_rules.npz"
TRANSFER_RULES_SCHEMA = "station_bias_transfer_rules_v1"
TIME_BASIS_CONTINUOUS = "continuous"
TIME_BASIS_EVENT_WINDOWS = "event_windows"
TIME_BASIS_FORECAST_WINDOW = "forecast_window"
TIME_BASIS_LABELS = {
    TIME_BASIS_CONTINUOUS: "连续时段",
    TIME_BASIS_EVENT_WINDOWS: "洪水事件窗口",
    TIME_BASIS_FORECAST_WINDOW: "预报窗口",
}

STATION_DUPLICATE_MATCH_FRACTION = 0.999
STATION_DUPLICATE_MIN_OVERLAP = 24


DATE_PATTERNS = [
    ("%Y.%m.%d.%H.%M", [r"\d{4}\.\d{2}\.\d{2}\.\d{2}\.\d{2}"]),
    ("%Y.%m.%d.%H", [r"\d{4}\.\d{2}\.\d{2}\.\d{2}"]),
    ("%Y-%m-%d %H:%M", [r"\d{4}-\d{2}-\d{2} \d{2}:\d{2}"]),
    ("%Y-%m-%dT%H:%M", [r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}"]),
    ("%Y.%m.%d", [r"\d{4}\.\d{2}\.\d{2}"]),
    ("%Y-%m-%d", [r"\d{4}-\d{2}-\d{2}"]),
]

STATION_ONLY_TEMPLATE_CANDIDATES = (
    "flow_accumulation_masked.tif",
    "dem_1km.tif",
    "dem_0p1deg.tif",
    "dem.tif",
)


def configured_station_correction_algorithm(meteo: dict[str, Any]) -> str:
    """Replay legacy workspaces unless an algorithm version was explicitly recorded."""
    return str(
        meteo.get("station_correction_algorithm", CONFIG_FALLBACK_STATION_CORRECTION_ALGORITHM)
        or CONFIG_FALLBACK_STATION_CORRECTION_ALGORITHM
    ).strip().lower()


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
    time_names = {"time", "datetime", "date", "时间", "日期"}
    for column in frame.columns:
        if str(column).strip().lower() in time_names:
            parsed = pd.to_datetime(frame[column], errors="coerce")
            if parsed.notna().sum() >= max(1, len(frame) // 3):
                return column
    for column in frame.columns:
        if pd.api.types.is_numeric_dtype(frame[column]):
            continue
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


def truthy_config(value: Any, *, default: bool = False) -> bool:
    if value is None or value == "":
        return default
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    return str(value).strip().lower() in {"1", "true", "yes", "on", "启用", "是", "事件窗口资料"}


def is_date_only_string(value: Any) -> bool:
    text = str(value or "").strip()
    return bool(re.fullmatch(r"\d{4}[-/.]\d{1,2}[-/.]\d{1,2}", text))


def normalize_time_step_hours(value: Any) -> float:
    try:
        step = float(value)
    except Exception:
        step = 24.0
    return step if step > 0 else 24.0


def detect_station_series_step_hours(index: Any) -> float | None:
    try:
        timestamps = pd.DatetimeIndex(pd.to_datetime(index, errors="coerce"))
    except Exception:
        return None
    timestamps = timestamps[timestamps.notna()].drop_duplicates().sort_values()
    if len(timestamps) < 2:
        return None
    diffs = pd.Series(timestamps).diff().dropna()
    if diffs.empty:
        return None
    median_hours = float(diffs.median() / pd.Timedelta(hours=1))
    return 1.0 if median_hours <= 1.5 else 24.0


def aggregate_station_precip_for_model_step(
    station_series: pd.DataFrame,
    target_step_hours: float,
    *,
    min_daily_hours: int = MIN_DAILY_PRECIP_HOURS,
    day_start_hour: int = HYDROLOGICAL_DAY_START_HOUR,
) -> tuple[pd.DataFrame, dict[str, Any]]:
    source_step_hours = detect_station_series_step_hours(station_series.index)
    meta: dict[str, Any] = {
        "enabled": False,
        "method": "none",
        "source_time_step_hours": source_step_hours,
        "effective_time_step_hours": float(target_step_hours),
    }
    if (
        station_series.empty
        or float(target_step_hours) < 24.0
        or source_step_hours is None
        or float(source_step_hours) > 1.5
    ):
        return station_series, meta

    working = station_series.copy()
    source_index = pd.DatetimeIndex(pd.to_datetime(working.index, errors="coerce"))
    valid_index = source_index.notna()
    working = working.loc[valid_index].copy()
    source_index = pd.DatetimeIndex(source_index[valid_index])
    hydrological_day = (source_index - pd.Timedelta(hours=int(day_start_hour))).normalize()
    working.index = hydrological_day
    grouped = working.groupby(level=0)
    hourly_counts = grouped.count()
    daily_sum = grouped.sum(min_count=1).where(hourly_counts >= int(min_daily_hours))
    daily_sum.index.name = station_series.index.name

    day_has_any_station = (hourly_counts >= int(min_daily_hours)).any(axis=1) if not hourly_counts.empty else pd.Series(dtype=bool)
    meta.update(
        {
            "enabled": True,
            "method": "hourly_sum_to_hydrological_day",
            "source_time_step_hours": source_step_hours,
            "effective_time_step_hours": 24.0,
            "day_start_hour": int(day_start_hour),
            "day_label": "start",
            "min_hours_per_day": int(min_daily_hours),
            "source_rows": int(len(station_series)),
            "daily_rows": int(len(daily_sum)),
            "valid_days": int(day_has_any_station.sum()) if len(day_has_any_station) else 0,
            "insufficient_station_days": int((hourly_counts < int(min_daily_hours)).sum().sum()) if not hourly_counts.empty else 0,
            "source_start": str(source_index.min()) if len(source_index) else "",
            "source_end": str(source_index.max()) if len(source_index) else "",
            "effective_start": str(daily_sum.index.min()) if len(daily_sum.index) else "",
            "effective_end": str(daily_sum.index.max()) if len(daily_sum.index) else "",
        }
    )
    return daily_sum.sort_index(), meta


def flood_event_raw_config(config: dict[str, Any]) -> dict[str, Any]:
    raw = config.get("洪水事件率定", {})
    if isinstance(raw, list):
        cfg: dict[str, Any] = {"启用": bool(raw), "事件表": raw}
    elif isinstance(raw, dict):
        cfg = dict(raw)
    else:
        cfg = {}
    event_mode = config.get("事件资料模式", {})
    if isinstance(event_mode, dict):
        for key, value in event_mode.items():
            cfg.setdefault(key, value)
    for key in ("事件表", "events"):
        if key in config and key not in cfg:
            cfg[key] = config.get(key)
    return cfg


def task_time_basis(config: dict[str, Any], *, context: str = "calibration") -> str:
    if context == "forecast":
        return TIME_BASIS_FORECAST_WINDOW
    raw = str(
        config.get("任务时段模式")
        or config.get("time_basis")
        or config.get("资料时段模式")
        or ""
    ).strip().lower()
    if raw in {"event", "events", "event_window", "event_windows", "flood_event", "洪水事件", "事件窗口", "事件资料"}:
        return TIME_BASIS_EVENT_WINDOWS
    if raw in {"forecast", "forecast_window", "预报", "预报窗口"}:
        return TIME_BASIS_FORECAST_WINDOW
    event_cfg = flood_event_raw_config(config)
    event_mode = config.get("事件资料模式", {})
    event_enabled = truthy_config(event_cfg.get("启用", event_cfg.get("enabled")), default=False)
    event_data_enabled = truthy_config(
        event_cfg.get("事件窗口资料", event_cfg.get("event_windows_enabled")),
        default=False,
    )
    if isinstance(event_mode, dict):
        event_data_enabled = truthy_config(event_mode.get("启用", event_mode.get("enabled")), default=event_data_enabled)
    has_events = bool(event_cfg.get("事件表") or event_cfg.get("events") or event_cfg.get("事件表路径") or event_cfg.get("events_file"))
    if event_enabled and (event_data_enabled or raw in {"event_segments", "事件资料模式"}):
        return TIME_BASIS_EVENT_WINDOWS
    return TIME_BASIS_EVENT_WINDOWS if event_data_enabled and has_events else TIME_BASIS_CONTINUOUS


def event_field(event: dict[str, Any], *names: str) -> Any:
    for name in names:
        if name in event and event.get(name) not in (None, ""):
            return event.get(name)
    lower_map = {str(key).strip().lower(): value for key, value in event.items()}
    for name in names:
        value = lower_map.get(str(name).strip().lower())
        if value not in (None, ""):
            return value
    return None


def parse_event_timestamp(value: Any, *, end: bool, step_hours: float) -> pd.Timestamp | None:
    if value in (None, ""):
        return None
    ts = pd.to_datetime(value)
    if end and step_hours < 24.0 and is_date_only_string(value):
        ts = ts + pd.Timedelta(days=1) - pd.Timedelta(hours=step_hours)
    return pd.Timestamp(ts)


def event_date_range(start: pd.Timestamp, end: pd.Timestamp, step_hours: float) -> pd.DatetimeIndex:
    if end < start:
        return pd.DatetimeIndex([])
    return pd.date_range(start, end, freq=pd.Timedelta(hours=step_hours))


def read_event_table_file(path: Path) -> list[dict[str, Any]]:
    if path.suffix.lower() in {".xlsx", ".xls", ".xlsm"}:
        frame = pd.read_excel(path)
    else:
        frame = read_csv_auto(path)
    return frame.to_dict(orient="records")


def normalized_event_windows(config: dict[str, Any], *, step_hours: float) -> dict[str, Any]:
    cfg = flood_event_raw_config(config)
    raw_events = cfg.get("事件表", cfg.get("events", []))
    event_file_raw = str(cfg.get("事件表路径", cfg.get("events_file", cfg.get("event_file", ""))) or "").strip()
    if event_file_raw:
        event_file = resolve_config_entry_path(config, event_file_raw)
        raw_events = read_event_table_file(event_file) if event_file.exists() else []
    if isinstance(raw_events, dict):
        raw_events = raw_events.get("events", raw_events.get("事件表", []))
    if not isinstance(raw_events, list):
        raw_events = []

    events: list[dict[str, Any]] = []
    for index, raw_event in enumerate(raw_events, start=1):
        if not isinstance(raw_event, dict):
            continue
        event_id = str(event_field(raw_event, "event_id", "id", "编号") or f"event_{index}").strip()
        name = str(event_field(raw_event, "name", "名称", "事件名称") or event_id).strip()
        purpose = str(event_field(raw_event, "purpose", "用途", "类型") or "diagnostic").strip().lower()
        score_start_raw = event_field(raw_event, "score_start", "评分开始", "事件开始", "洪水开始", "开始时间", "起始时间", "start")
        score_end_raw = event_field(raw_event, "score_end", "评分结束", "事件结束", "洪水结束", "结束时间", "终止时间", "end")
        run_start_raw = event_field(raw_event, "run_start", "运行开始", "预热开始", "warmup_start") or score_start_raw
        run_end_raw = event_field(raw_event, "run_end", "运行结束", "退水结束") or score_end_raw
        try:
            run_start = parse_event_timestamp(run_start_raw, end=False, step_hours=step_hours)
            score_start = parse_event_timestamp(score_start_raw, end=False, step_hours=step_hours)
            score_end = parse_event_timestamp(score_end_raw, end=True, step_hours=step_hours)
            run_end = parse_event_timestamp(run_end_raw, end=True, step_hours=step_hours)
        except Exception:
            continue
        if run_start is None or score_start is None or score_end is None or run_end is None:
            continue
        if not (run_start <= score_start <= score_end <= run_end):
            continue
        events.append(
            {
                "event_id": event_id,
                "name": name,
                "purpose": purpose,
                "run_start": run_start,
                "score_start": score_start,
                "score_end": score_end,
                "run_end": run_end,
            }
        )
    return {"valid_events": sorted(events, key=lambda item: (item["run_start"], item["event_id"])), "valid_event_count": len(events)}


def event_window_index(events: list[dict[str, Any]], start_key: str, end_key: str, step_hours: float) -> pd.DatetimeIndex:
    values: list[pd.Timestamp] = []
    for event in events:
        start = event.get(start_key)
        end = event.get(end_key)
        if start is None or end is None:
            continue
        values.extend(list(event_date_range(pd.Timestamp(start), pd.Timestamp(end), step_hours)))
    if not values:
        return pd.DatetimeIndex([])
    return pd.DatetimeIndex(sorted(set(pd.Timestamp(item) for item in values)))


def build_expected_time_index(config: dict[str, Any]) -> pd.DatetimeIndex | None:
    time_cfg = dict(config.get("时间", {}) or {})
    start_raw = time_cfg.get("预热开始") or time_cfg.get("率定开始")
    end_raw = time_cfg.get("验证结束") or time_cfg.get("率定结束")
    if not start_raw or not end_raw:
        return None
    step_hours = normalize_time_step_hours(config.get("时间步长_小时", 24.0))
    start_ts = pd.to_datetime(start_raw)
    end_ts = pd.to_datetime(end_raw)
    if step_hours < 24.0 and is_date_only_string(end_raw):
        end_ts = end_ts + pd.Timedelta(days=1) - pd.Timedelta(hours=step_hours)
    return pd.date_range(start_ts, end_ts, freq=pd.Timedelta(hours=step_hours))


def build_expected_forcing_index(config: dict[str, Any], *, context: str = "calibration") -> pd.DatetimeIndex | None:
    step_hours = normalize_time_step_hours(config.get("时间步长_小时", 24.0))
    if task_time_basis(config, context=context) == TIME_BASIS_EVENT_WINDOWS:
        event_info = normalized_event_windows(config, step_hours=step_hours)
        index = event_window_index(event_info.get("valid_events", []), "run_start", "run_end", step_hours)
        if len(index) > 0:
            return index
    return build_expected_time_index(config)


def load_station_metadata(path: Path, raster_crs: Any) -> pd.DataFrame:
    frame = read_csv_auto(path)
    columns = list(frame.columns)
    id_col = detect_column(columns, ["station_id", "station", "id", "name", "站点", "站号"])
    lon_col = detect_column(columns, ["lon", "longitude", "x", "经度"])
    lat_col = detect_column(columns, ["lat", "latitude", "y", "纬度"])
    if not id_col or not lon_col or not lat_col:
        raise ValueError("站点信息 csv 至少需要站号、经度、纬度字段。")

    out = frame[[id_col, lon_col, lat_col]].copy()
    out.columns = ["station_id", "x_raw", "y_raw"]
    out["station_id"] = out["station_id"].astype(str).str.strip()
    out["x_raw"] = pd.to_numeric(out["x_raw"], errors="coerce")
    out["y_raw"] = pd.to_numeric(out["y_raw"], errors="coerce")
    out["weight"] = 1.0
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
        data = data.dropna(subset=["time"])
        wide = data.pivot_table(index="time", columns="station_id", values="value", aggfunc="mean")
        wide.columns = [str(col).strip() for col in wide.columns]
        return wide.sort_index(), "long"

    wide = frame.copy()
    wide[time_col] = pd.to_datetime(wide[time_col], errors="coerce")
    wide = wide.dropna(subset=[time_col]).set_index(time_col).sort_index()
    wide.columns = [str(col).strip() for col in wide.columns]
    for column in list(wide.columns):
        wide[column] = pd.to_numeric(wide[column], errors="coerce")
    if wide.index.has_duplicates:
        wide = wide.groupby(level=0).mean(numeric_only=True).sort_index()
    return wide, "wide"


def station_series_integrity_diagnostics(
    station_series: pd.DataFrame,
    station_ids: list[str] | None = None,
    *,
    match_fraction_threshold: float = STATION_DUPLICATE_MATCH_FRACTION,
    min_overlap: int = STATION_DUPLICATE_MIN_OVERLAP,
) -> dict[str, Any]:
    ids = [str(item) for item in (station_ids or list(station_series.columns)) if str(item) in station_series.columns]
    required_overlap = min(max(3, int(min_overlap)), max(3, len(station_series)))
    duplicate_pairs: list[dict[str, Any]] = []
    for left_index, left_id in enumerate(ids):
        left = pd.to_numeric(station_series[left_id], errors="coerce")
        for right_id in ids[left_index + 1 :]:
            right = pd.to_numeric(station_series[right_id], errors="coerce")
            common = left.notna() & right.notna()
            overlap = int(common.sum())
            if overlap < required_overlap:
                continue
            left_values = left[common].to_numpy(dtype="float64")
            right_values = right[common].to_numpy(dtype="float64")
            matches = np.isclose(left_values, right_values, rtol=0.0, atol=1e-9)
            match_fraction = float(np.mean(matches)) if matches.size else 0.0
            nonzero_overlap = int(np.count_nonzero((np.abs(left_values) > 1e-12) | (np.abs(right_values) > 1e-12)))
            if match_fraction < float(match_fraction_threshold) or nonzero_overlap <= 0:
                continue
            duplicate_pairs.append(
                {
                    "station_a": left_id,
                    "station_b": right_id,
                    "overlap_count": overlap,
                    "matching_count": int(np.count_nonzero(matches)),
                    "matching_fraction": match_fraction,
                    "nonzero_overlap_count": nonzero_overlap,
                    "total_a_mm": float(np.nansum(left_values)),
                    "total_b_mm": float(np.nansum(right_values)),
                }
            )
    return {
        "schema": "station_series_integrity_v1",
        "station_count": int(len(ids)),
        "minimum_overlap": int(required_overlap),
        "matching_fraction_threshold": float(match_fraction_threshold),
        "duplicate_pair_count": int(len(duplicate_pairs)),
        "duplicate_pairs": duplicate_pairs,
        "qc_blocked": bool(duplicate_pairs),
        "interpretation": (
            "Different station identifiers with effectively identical non-zero time series are not independent evidence. "
            "The source identity or coordinates must be resolved before formal spatial correction."
        ),
    }


def sha256_file_identity(path: Path) -> dict[str, Any]:
    resolved = Path(path).resolve(strict=False)
    if not resolved.exists() or not resolved.is_file():
        return {"path": str(resolved), "available": False}
    digest = hashlib.sha256()
    with resolved.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return {
        "path": str(resolved),
        "available": True,
        "size_bytes": int(resolved.stat().st_size),
        "sha256": digest.hexdigest(),
    }


def raster_series_fingerprint(
    records: list[tuple[pd.Timestamp, Path]],
    *,
    directory: Path | None = None,
    use_timestamp_names: bool = False,
) -> dict[str, Any]:
    aggregate = hashlib.sha256()
    file_count = 0
    total_bytes = 0
    missing_files: list[str] = []
    for timestamp, source_path in records:
        path = (
            Path(directory) / (raster_name_from_timestamp(timestamp) if use_timestamp_names else source_path.name)
            if directory is not None
            else source_path
        )
        if not path.exists():
            missing_files.append(str(path.resolve(strict=False)))
            continue
        identity = sha256_file_identity(path)
        file_count += 1
        total_bytes += int(identity.get("size_bytes", 0) or 0)
        aggregate.update(
            (
                f"{pd.Timestamp(timestamp).isoformat()}\0{path.name}\0"
                f"{identity.get('size_bytes', 0)}\0{identity.get('sha256', '')}\n"
            ).encode("utf-8")
        )
    return {
        "algorithm": "sha256(file_content)+sha256(ordered_series)",
        "file_count": int(file_count),
        "total_bytes": int(total_bytes),
        "series_sha256": aggregate.hexdigest(),
        "missing_file_count": int(len(missing_files)),
        "missing_file_samples": missing_files[:5],
    }


def station_elevation_support_diagnostics(
    config: dict[str, Any],
    stations: pd.DataFrame,
) -> dict[str, Any]:
    meteo = dict(config.get("气象策略", {}) or {})
    dem_raw = str(
        meteo.get("站点高程DEM_tif", meteo.get("station_elevation_dem_tif", "")) or ""
    ).strip()
    threshold_raw = meteo.get(
        "站点高程支持阈值_m",
        meteo.get("station_elevation_support_threshold_m", config.get("CFMAX分区阈值_m")),
    )
    try:
        threshold_m = float(threshold_raw)
    except (TypeError, ValueError):
        threshold_m = float("nan")
    if not dem_raw:
        return {
            "schema": "station_elevation_support_v1",
            "available": False,
            "status": "not_configured",
            "threshold_m": threshold_m if np.isfinite(threshold_m) else None,
        }
    dem_candidate = Path(dem_raw).expanduser()
    dem_path = (
        dem_candidate.resolve(strict=False)
        if dem_candidate.is_absolute()
        else resolve_config_entry_path(config, dem_raw)
    )
    if not dem_path.exists():
        return {
            "schema": "station_elevation_support_v1",
            "available": False,
            "status": "dem_missing",
            "dem": str(dem_path),
            "threshold_m": threshold_m if np.isfinite(threshold_m) else None,
        }
    if stations.empty:
        return {
            "schema": "station_elevation_support_v1",
            "available": False,
            "status": "no_matched_stations",
            "dem": str(dem_path),
            "threshold_m": threshold_m if np.isfinite(threshold_m) else None,
        }
    x_raw = pd.to_numeric(stations.get("x_raw"), errors="coerce").to_numpy(dtype="float64")
    y_raw = pd.to_numeric(stations.get("y_raw"), errors="coerce").to_numpy(dtype="float64")
    valid_coordinates = np.isfinite(x_raw) & np.isfinite(y_raw)
    elevations = np.full(len(stations), np.nan, dtype="float64")
    with rasterio.open(dem_path) as src:
        x_values = x_raw.copy()
        y_values = y_raw.copy()
        looks_lonlat = bool(
            np.any(valid_coordinates)
            and np.nanmax(np.abs(x_values[valid_coordinates])) <= 180.0
            and np.nanmax(np.abs(y_values[valid_coordinates])) <= 90.0
        )
        if src.crs is not None and looks_lonlat and str(src.crs).upper() not in {"EPSG:4326", "OGC:CRS84"}:
            transformer = pyproj.Transformer.from_crs("EPSG:4326", src.crs, always_xy=True)
            transformed_x, transformed_y = transformer.transform(x_values[valid_coordinates], y_values[valid_coordinates])
            x_values[valid_coordinates] = transformed_x
            y_values[valid_coordinates] = transformed_y
        samples = list(src.sample(zip(x_values[valid_coordinates], y_values[valid_coordinates])))
        sampled = np.asarray([item[0] for item in samples], dtype="float64") if samples else np.asarray([], dtype="float64")
        if src.nodata is not None:
            sampled[np.isclose(sampled, float(src.nodata))] = np.nan
        sampled[sampled < -500.0] = np.nan
        elevations[valid_coordinates] = sampled
    finite = np.isfinite(elevations)
    high = finite & (elevations >= threshold_m) if np.isfinite(threshold_m) else np.zeros_like(finite)
    valid_count = int(np.count_nonzero(finite))
    high_count = int(np.count_nonzero(high))
    if not np.isfinite(threshold_m):
        status = "threshold_missing"
    elif high_count == 0:
        status = "high_zone_unsupported"
    elif high_count < 2 or high_count / max(valid_count, 1) < 0.1:
        status = "high_zone_sparsely_supported"
    else:
        status = "supported"
    station_items = []
    for station_id, elevation in zip(stations["station_id"].astype(str), elevations):
        station_items.append(
            {
                "station_id": station_id,
                "elevation_m": float(elevation) if np.isfinite(elevation) else None,
                "supports_high_zone": bool(np.isfinite(elevation) and np.isfinite(threshold_m) and elevation >= threshold_m),
            }
        )
    return {
        "schema": "station_elevation_support_v1",
        "available": bool(valid_count > 0),
        "status": status,
        "dem": sha256_file_identity(dem_path),
        "threshold_m": float(threshold_m) if np.isfinite(threshold_m) else None,
        "station_count": int(len(stations)),
        "valid_elevation_count": valid_count,
        "elevation_min_m": float(np.nanmin(elevations)) if valid_count else None,
        "elevation_mean_m": float(np.nanmean(elevations)) if valid_count else None,
        "elevation_max_m": float(np.nanmax(elevations)) if valid_count else None,
        "high_zone_station_count": high_count,
        "high_zone_station_fraction": float(high_count / valid_count) if valid_count else 0.0,
        "stations": station_items,
        "interpretation": (
            "This is a representativeness diagnostic. Sparse or absent high-elevation gauges do not prove the background field is wrong, "
            "but station residual correction cannot independently validate the high zone."
        ),
    }


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


def raster_name_from_timestamp(ts: pd.Timestamp) -> str:
    ts = pd.to_datetime(ts)
    if ts.minute or ts.second or ts.microsecond or ts.nanosecond:
        return ts.strftime("%Y.%m.%d.%H.%M.tif")
    if ts.hour:
        return ts.strftime("%Y.%m.%d.%H.tif")
    return ts.strftime("%Y.%m.%d.tif")


def resolve_station_only_template(paths: dict[str, Path]) -> Path:
    gis_dir = Path(paths["gis_dir"])
    for name in STATION_ONLY_TEMPLATE_CANDIDATES:
        candidate = gis_dir / name
        if candidate.exists():
            return candidate
    raise FileNotFoundError(
        "站点泰森分配需要目标格网模板。请先完成地理数据生成，确保流域掩膜或 DEM 栅格已生成。"
    )


def records_from_station_times(station_series: pd.DataFrame, template_path: Path) -> list[tuple[pd.Timestamp, Path]]:
    index = pd.DatetimeIndex(pd.to_datetime(station_series.index, errors="coerce"))
    index = index[index.notna()].drop_duplicates().sort_values()
    return [(pd.Timestamp(ts), template_path) for ts in index]


def filter_records_to_expected(
    records: list[tuple[pd.Timestamp, Path]],
    expected_index: pd.DatetimeIndex | None,
) -> tuple[list[tuple[pd.Timestamp, Path]], list[pd.Timestamp], int]:
    if expected_index is None or len(expected_index) <= 0:
        return records, [], 0
    expected_set = {pd.Timestamp(ts) for ts in expected_index}
    filtered = [(pd.Timestamp(ts), path) for ts, path in records if pd.Timestamp(ts) in expected_set]
    available_set = {pd.Timestamp(ts) for ts, _ in filtered}
    missing = [pd.Timestamp(ts) for ts in expected_index if pd.Timestamp(ts) not in available_set]
    skipped = max(0, len(records) - len(filtered))
    return filtered, missing, skipped


def max_consecutive_true(values: Any) -> int:
    longest = 0
    current = 0
    for value in list(values):
        if bool(value):
            current += 1
            longest = max(longest, current)
        else:
            current = 0
    return int(longest)


def finite_array(values: Any) -> np.ndarray:
    arr = np.asarray(values, dtype="float64")
    return arr[np.isfinite(arr)]


def safe_stat(values: Any, fn: Any) -> float | None:
    arr = finite_array(values)
    if arr.size == 0:
        return None
    return float(fn(arr))


def ratio_percent(numerator: float | int | None, denominator: float | int | None) -> float | None:
    try:
        den = float(denominator)
        if den <= 0:
            return None
        return float(numerator or 0.0) / den * 100.0
    except Exception:
        return None


def relative_change_percent(after: float | None, before: float | None) -> float | None:
    if before is None or after is None or abs(float(before)) <= 1e-12:
        return None
    return (float(after) - float(before)) / float(before) * 100.0


def raster_hydro_stats(path: Path) -> dict[str, float | int | None]:
    with rasterio.open(path) as src:
        arr = src.read(1).astype("float64")
        nodata = src.nodata
        if nodata is not None:
            arr[arr == nodata] = np.nan
        arr[arr < -9000] = np.nan
    valid = finite_array(arr)
    if valid.size == 0:
        return {
            "valid_pixels": 0,
            "mean_mm": None,
            "max_mm": None,
            "wet_pixel_ratio": None,
        }
    wet_pixels = int(np.sum(valid >= WET_STATION_MEAN_MM))
    return {
        "valid_pixels": int(valid.size),
        "mean_mm": float(np.mean(valid)),
        "max_mm": float(np.max(valid)),
        "wet_pixel_ratio": float(wet_pixels / valid.size),
    }


def paired_station_metrics(obs_values: list[float], sim_values: list[float]) -> dict[str, Any]:
    obs = np.asarray(obs_values, dtype="float64")
    sim = np.asarray(sim_values, dtype="float64")
    count = min(obs.size, sim.size)
    if count <= 0:
        return {
            "sample_count": 0,
            "mean_observed_mm": None,
            "mean_simulated_mm": None,
            "mae_mm": None,
            "rmse_mm": None,
            "pbias_percent": None,
            "correlation": None,
        }
    obs = obs[:count]
    sim = sim[:count]
    mask = np.isfinite(obs) & np.isfinite(sim)
    if not np.any(mask):
        return {
            "sample_count": 0,
            "mean_observed_mm": None,
            "mean_simulated_mm": None,
            "mae_mm": None,
            "rmse_mm": None,
            "pbias_percent": None,
            "correlation": None,
        }
    diff = sim[mask] - obs[mask]
    obs_sum = float(np.sum(obs[mask]))
    pbias_value = float(np.sum(diff) / obs_sum * 100.0) if abs(obs_sum) > 1e-12 else None
    correlation = None
    if int(np.sum(mask)) >= 2:
        obs_std = float(np.std(obs[mask]))
        sim_std = float(np.std(sim[mask]))
        if obs_std > 1e-12 and sim_std > 1e-12:
            correlation = float(np.corrcoef(obs[mask], sim[mask])[0, 1])
    return {
        "sample_count": int(np.sum(mask)),
        "mean_observed_mm": float(np.mean(obs[mask])),
        "mean_simulated_mm": float(np.mean(sim[mask])),
        "mae_mm": float(np.mean(np.abs(diff))),
        "rmse_mm": float(np.sqrt(np.mean(diff * diff))),
        "pbias_percent": pbias_value,
        "correlation": correlation,
    }


def precipitation_occurrence_metrics(
    obs_values: list[float],
    sim_values: list[float],
    *,
    wet_threshold_mm: float = WET_STATION_MEAN_MM,
) -> dict[str, Any]:
    obs = np.asarray(obs_values, dtype="float64")
    sim = np.asarray(sim_values, dtype="float64")
    count = min(obs.size, sim.size)
    if count <= 0:
        return {
            "wet_threshold_mm": float(wet_threshold_mm),
            "sample_count": 0,
            "hits": 0,
            "misses": 0,
            "false_alarms": 0,
            "correct_negatives": 0,
            "pod": None,
            "far": None,
            "csi": None,
        }
    obs = obs[:count]
    sim = sim[:count]
    mask = np.isfinite(obs) & np.isfinite(sim) & (obs >= 0.0) & (sim >= 0.0)
    obs_wet = obs[mask] >= float(wet_threshold_mm)
    sim_wet = sim[mask] >= float(wet_threshold_mm)
    hits = int(np.sum(obs_wet & sim_wet))
    misses = int(np.sum(obs_wet & ~sim_wet))
    false_alarms = int(np.sum(~obs_wet & sim_wet))
    correct_negatives = int(np.sum(~obs_wet & ~sim_wet))

    def ratio(numerator: int, denominator: int) -> float | None:
        return float(numerator / denominator) if denominator > 0 else None

    return {
        "wet_threshold_mm": float(wet_threshold_mm),
        "sample_count": int(np.sum(mask)),
        "hits": hits,
        "misses": misses,
        "false_alarms": false_alarms,
        "correct_negatives": correct_negatives,
        "pod": ratio(hits, hits + misses),
        "far": ratio(false_alarms, hits + false_alarms),
        "csi": ratio(hits, hits + misses + false_alarms),
    }


def precipitation_sequence_metrics(values: list[float]) -> dict[str, Any]:
    finite = [float(value) for value in values if np.isfinite(float(value))]
    wet = [value >= WET_STATION_MEAN_MM for value in finite]
    dry = [not flag for flag in wet]
    trace_count = int(sum(0.0 < value < WET_STATION_MEAN_MM for value in finite))
    return {
        "sample_count": int(len(finite)),
        "dry_day_count": int(sum(dry)),
        "wet_day_count": int(sum(wet)),
        "trace_day_count": trace_count,
        "trace_day_frequency_percent": ratio_percent(trace_count, len(finite)),
        "longest_dry_spell_steps": max_consecutive_true(dry),
        "longest_wet_spell_steps": max_consecutive_true(wet),
    }


def monthly_precipitation_totals(records: list[tuple[pd.Timestamp, float]]) -> dict[str, float]:
    totals: dict[str, float] = {}
    for timestamp, value in records:
        if not np.isfinite(float(value)):
            continue
        key = pd.Timestamp(timestamp).strftime("%Y-%m")
        totals[key] = totals.get(key, 0.0) + float(value)
    return totals


def station_product_day_basis_diagnostics(
    records: list[tuple[pd.Timestamp, Path]],
    stations: pd.DataFrame,
    station_series_raw: pd.DataFrame,
    *,
    model_step_hours: float,
) -> dict[str, Any]:
    source_step = detect_station_series_step_hours(station_series_raw.index)
    if abs(float(model_step_hours) - 24.0) > 1e-9 or source_step is None or source_step > 1.5:
        return {
            "schema": "precipitation_day_basis_diagnostics_v1",
            "status": "not_applicable",
            "source_time_step_hours": source_step,
        }
    station_ids = [str(item) for item in stations["station_id"].tolist()]
    grid_by_time: dict[pd.Timestamp, np.ndarray] = {}
    for ts, path in records:
        if not path.exists():
            continue
        with rasterio.open(path) as src:
            grid_by_time[pd.Timestamp(ts).normalize()] = sample_station_values(src, stations)

    candidates: list[dict[str, Any]] = []
    for day_start_hour, basis in (
        (0, "calendar_day_00_local"),
        (HYDROLOGICAL_DAY_START_HOUR, "hydrological_day_08_local"),
    ):
        aggregated, aggregation_meta = aggregate_station_precip_for_model_step(
            station_series_raw,
            model_step_hours,
            day_start_hour=day_start_hour,
        )
        for label_shift_days in (-1, 0, 1):
            shifted = aggregated.copy()
            shifted.index = pd.DatetimeIndex(shifted.index) + pd.Timedelta(days=label_shift_days)
            observed: list[float] = []
            simulated: list[float] = []
            for stamp, grid_values in grid_by_time.items():
                if stamp not in shifted.index:
                    continue
                obs = shifted.loc[stamp, station_ids]
                if isinstance(obs, pd.DataFrame):
                    obs = obs.mean(axis=0, numeric_only=True)
                obs_values = obs.to_numpy(dtype="float64")
                valid = np.isfinite(obs_values) & np.isfinite(grid_values) & (obs_values >= 0.0) & (grid_values >= 0.0)
                if np.any(valid):
                    observed.extend(obs_values[valid].tolist())
                    simulated.extend(grid_values[valid].tolist())
            metrics = paired_station_metrics(observed, simulated)
            candidates.append(
                {
                    "basis": basis,
                    "day_start_hour": int(day_start_hour),
                    "station_label_shift_days": int(label_shift_days),
                    "aggregation": aggregation_meta,
                    "amount_metrics": metrics,
                    "occurrence_metrics": precipitation_occurrence_metrics(observed, simulated),
                }
            )

    ranked = sorted(
        candidates,
        key=lambda item: (
            -float(item["amount_metrics"].get("correlation"))
            if item["amount_metrics"].get("correlation") is not None else float("inf"),
            float(item["amount_metrics"].get("mae_mm"))
            if item["amount_metrics"].get("mae_mm") is not None else float("inf"),
        ),
    )
    best = ranked[0] if ranked else None
    second = ranked[1] if len(ranked) > 1 else None
    best_corr = dict(best.get("amount_metrics", {}) if best else {}).get("correlation")
    second_corr = dict(second.get("amount_metrics", {}) if second else {}).get("correlation")
    correlation_margin = (
        float(best_corr) - float(second_corr)
        if best_corr is not None and second_corr is not None else None
    )
    evidence_status = "inconclusive"
    if best is not None and int(best["amount_metrics"].get("sample_count", 0) or 0) >= 100:
        if correlation_margin is not None and correlation_margin >= 0.02:
            evidence_status = "preferred_candidate"
    return {
        "schema": "precipitation_day_basis_diagnostics_v1",
        "status": "ok",
        "source_time_step_hours": float(source_step),
        "formal_confirmation": False,
        "evidence_status": evidence_status,
        "correlation_margin_to_second": correlation_margin,
        "preferred_candidate": best,
        "candidates": candidates,
        "interpretation": (
            "This ranks temporal alignment against station observations; it does not replace product metadata."
        ),
    }


def leave_one_station_out_diagnostics(
    records: list[tuple[pd.Timestamp, Path]],
    stations: pd.DataFrame,
    station_series: pd.DataFrame,
) -> dict[str, Any]:
    """Evaluate v2 at held-out station points, including pointwise monthly redistribution."""
    station_ids = [str(item) for item in stations["station_id"].tolist()]
    weights = stations["weight"].to_numpy(dtype="float64")
    station_x = stations["x"].to_numpy(dtype="float64")
    station_y = stations["y"].to_numpy(dtype="float64")
    samples: list[dict[str, Any]] = []
    skipped_insufficient_network = 0

    for ts, path in records:
        if not path.exists():
            continue
        with rasterio.open(path) as src:
            grid_station = sample_station_values(src, stations)
            obs = station_values_for_time(station_series, pd.Timestamp(ts), station_ids)
            valid = valid_station_observation_mask(obs, grid_station, weights)
            if int(np.count_nonzero(valid)) < 2:
                skipped_insufficient_network += int(np.count_nonzero(valid))
                continue
            transformer = metric_transformer_for_points(src.crs, station_x, station_y)
            station_x_m, station_y_m = transform_metric_xy(station_x, station_y, transformer)

        for held_out in np.where(valid)[0]:
            training = valid.copy()
            training[held_out] = False
            if not np.any(training):
                skipped_insufficient_network += 1
                continue
            amount_valid = training & (obs >= WET_STATION_MEAN_MM) & (grid_station >= WET_STATION_MEAN_MM)
            target_x = np.asarray([station_x_m[held_out]], dtype="float64")
            target_y = np.asarray([station_y_m[held_out]], dtype="float64")
            if np.any(amount_valid):
                raw_ratio = obs[amount_valid] / np.maximum(grid_station[amount_valid], MIN_GRID_PRECIP_MM)
                log_ratio = idw_interpolate_to_points(
                    station_x_m[amount_valid],
                    station_y_m[amount_valid],
                    np.log(np.clip(raw_ratio, RATIO_CLIP[0], RATIO_CLIP[1])),
                    target_x,
                    target_y,
                )
                ratio = np.exp(log_ratio)
            else:
                ratio = np.ones(1, dtype="float64")
            station_amount = idw_interpolate_to_points(
                station_x_m[training], station_y_m[training], obs[training], target_x, target_y,
            )
            station_occurrence = idw_interpolate_to_points(
                station_x_m[training],
                station_y_m[training],
                (obs[training] >= WET_STATION_MEAN_MM).astype("float64"),
                target_x,
                target_y,
            )
            support_radius = station_support_radius_m(station_x_m[training], station_y_m[training])
            nearest_distance = nearest_station_distance_to_points(
                station_x_m[training], station_y_m[training], target_x, target_y,
            )
            possible_training = max(int(np.count_nonzero(weights_positive(stations))) - 1, 1)
            temporal_confidence = float(np.count_nonzero(training) / possible_training)
            spatial_confidence = np.exp(-np.square(nearest_distance / max(support_radius, 1.0)))
            confidence = np.clip(temporal_confidence * spatial_confidence, 0.0, 1.0)
            correction = apply_station_observation_correction(
                np.asarray([grid_station[held_out]], dtype="float64"),
                ratio_values=ratio,
                station_prec_values=station_amount,
                station_occurrence_values=station_occurrence,
                confidence_values=confidence,
                allow_exact_dry=bool(np.all(obs[training] < WET_STATION_MEAN_MM)),
            )
            samples.append(
                {
                    "timestamp": pd.Timestamp(ts),
                    "station_id": station_ids[held_out],
                    "observed": float(obs[held_out]),
                    "background": float(grid_station[held_out]),
                    "target_amount": float(correction["amount_corrected"][0]),
                    "corrected": float(correction["corrected"][0]),
                }
            )

    grouped: dict[tuple[str, int, int], list[int]] = {}
    for index, sample in enumerate(samples):
        stamp = pd.Timestamp(sample["timestamp"])
        grouped.setdefault((str(sample["station_id"]), int(stamp.year), int(stamp.month)), []).append(index)
    high_factor_groups = 0
    high_removed_fraction_groups = 0
    unresolved_groups = 0
    for indices in grouped.values():
        target_sum = float(sum(max(float(samples[index]["target_amount"]), 0.0) for index in indices))
        corrected_sum = float(sum(max(float(samples[index]["corrected"]), 0.0) for index in indices))
        removed_fraction = max(target_sum - corrected_sum, 0.0) / target_sum if target_sum > MIN_GRID_PRECIP_MM else 0.0
        if corrected_sum > MIN_GRID_PRECIP_MM:
            factor = target_sum / corrected_sum
            for index in indices:
                samples[index]["corrected"] = max(float(samples[index]["corrected"]), 0.0) * factor
            if factor > MAX_MONTHLY_REDISTRIBUTION_FACTOR:
                high_factor_groups += 1
        elif target_sum > MIN_GRID_PRECIP_MM:
            unresolved_groups += 1
        if removed_fraction > MAX_MONTHLY_REMOVED_FRACTION:
            high_removed_fraction_groups += 1

    observed = [float(item["observed"]) for item in samples]
    background = [float(item["background"]) for item in samples]
    corrected = [float(item["corrected"]) for item in samples]
    per_station: list[dict[str, Any]] = []
    for station_id in station_ids:
        selected = [item for item in samples if item["station_id"] == station_id]
        per_station.append(
            {
                "station_id": station_id,
                "before": paired_station_metrics(
                    [float(item["observed"]) for item in selected],
                    [float(item["background"]) for item in selected],
                ),
                "after": paired_station_metrics(
                    [float(item["observed"]) for item in selected],
                    [float(item["corrected"]) for item in selected],
                ),
                "occurrence_after": precipitation_occurrence_metrics(
                    [float(item["observed"]) for item in selected],
                    [float(item["corrected"]) for item in selected],
                ),
            }
        )
    return {
        "schema": "precipitation_station_leave_one_out_v1",
        "method": "hold_out_one_station_then_apply_occurrence_amount_v2_and_point_monthly_redistribution",
        "independence_note": "The held-out station is excluded from this local correction, but may have been used upstream to create v2.",
        "sample_count": int(len(samples)),
        "skipped_insufficient_network_samples": int(skipped_insufficient_network),
        "before": paired_station_metrics(observed, background),
        "after": paired_station_metrics(observed, corrected),
        "occurrence_before": precipitation_occurrence_metrics(observed, background),
        "occurrence_after": precipitation_occurrence_metrics(observed, corrected),
        "monthly_qc": {
            "group_count": int(len(grouped)),
            "high_factor_group_count": int(high_factor_groups),
            "high_removed_fraction_group_count": int(high_removed_fraction_groups),
            "unresolved_group_count": int(unresolved_groups),
        },
        "per_station": per_station,
    }


def summarize_precipitation_hydro_diagnostics(
    records: list[tuple[pd.Timestamp, Path]],
    target_dir: Path,
    stations: pd.DataFrame,
    station_series: pd.DataFrame,
    mode: str,
    *,
    use_timestamp_names: bool = False,
    algorithm: str = STATION_CORRECTION_ALGORITHM_LEGACY,
) -> dict[str, Any]:
    station_ids = [str(item) for item in stations["station_id"].tolist()]
    base_basin_means: list[float] = []
    corrected_basin_means: list[float] = []
    base_basin_records: list[tuple[pd.Timestamp, float]] = []
    corrected_basin_records: list[tuple[pd.Timestamp, float]] = []
    base_daily_max: list[float] = []
    corrected_daily_max: list[float] = []
    base_wet_ratios: list[float] = []
    corrected_wet_ratios: list[float] = []
    correction_factors: list[float] = []
    obs_for_base: list[float] = []
    base_at_station: list[float] = []
    obs_for_corrected: list[float] = []
    corrected_at_station: list[float] = []
    available_station_counts: list[int] = []
    clipped_step_count = 0
    clipped_station_sample_count = 0
    occurrence_repair_step_count = 0
    target_file_count = 0
    spatial_abs_change_sum = 0.0
    spatial_relative_change_sum = 0.0
    spatial_change_cell_steps = 0
    spatial_changed_gt_10pct_cell_steps = 0
    spatial_max_abs_change = 0.0

    for ts, path in records:
        output = target_dir / (raster_name_from_timestamp(ts) if use_timestamp_names else path.name)
        obs = station_values_for_time(station_series, pd.Timestamp(ts), station_ids)
        obs_valid = np.isfinite(obs) & (obs >= 0.0)
        available_station_counts.append(int(np.sum(obs_valid)))

        base_station_values = np.full(len(station_ids), np.nan, dtype="float64")
        base_grid_values: np.ndarray | None = None
        base_mean = None
        if path.exists():
            base_stats = raster_hydro_stats(path)
            base_mean = base_stats["mean_mm"]
            if base_mean is not None:
                base_basin_means.append(float(base_mean))
                base_basin_records.append((pd.Timestamp(ts), float(base_mean)))
            if base_stats["max_mm"] is not None:
                base_daily_max.append(float(base_stats["max_mm"]))
            if base_stats["wet_pixel_ratio"] is not None:
                base_wet_ratios.append(float(base_stats["wet_pixel_ratio"]))
            with rasterio.open(path) as src:
                base_station_values = sample_station_values(src, stations)
                base_grid_values = src.read(1).astype("float64")
                if src.nodata is not None:
                    base_grid_values[base_grid_values == src.nodata] = np.nan

        corrected_station_values = np.full(len(station_ids), np.nan, dtype="float64")
        corrected_grid_values: np.ndarray | None = None
        corrected_mean = None
        if output.exists():
            target_file_count += 1
            corrected_stats = raster_hydro_stats(output)
            corrected_mean = corrected_stats["mean_mm"]
            if corrected_mean is not None:
                corrected_basin_means.append(float(corrected_mean))
                corrected_basin_records.append((pd.Timestamp(ts), float(corrected_mean)))
            if corrected_stats["max_mm"] is not None:
                corrected_daily_max.append(float(corrected_stats["max_mm"]))
            if corrected_stats["wet_pixel_ratio"] is not None:
                corrected_wet_ratios.append(float(corrected_stats["wet_pixel_ratio"]))
            with rasterio.open(output) as src:
                corrected_station_values = sample_station_values(src, stations)
                corrected_grid_values = src.read(1).astype("float64")
                if src.nodata is not None:
                    corrected_grid_values[corrected_grid_values == src.nodata] = np.nan

        if (
            base_grid_values is not None
            and corrected_grid_values is not None
            and base_grid_values.shape == corrected_grid_values.shape
        ):
            common = np.isfinite(base_grid_values) & np.isfinite(corrected_grid_values)
            if np.any(common):
                absolute_change = np.abs(corrected_grid_values[common] - base_grid_values[common])
                relative_change = absolute_change / np.maximum(base_grid_values[common], WET_STATION_MEAN_MM)
                spatial_abs_change_sum += float(np.sum(absolute_change))
                spatial_relative_change_sum += float(np.sum(relative_change))
                spatial_change_cell_steps += int(absolute_change.size)
                spatial_changed_gt_10pct_cell_steps += int(np.count_nonzero(relative_change > 0.10))
                spatial_max_abs_change = max(spatial_max_abs_change, float(np.max(absolute_change)))

        station_base_mask = obs_valid & np.isfinite(base_station_values) & (base_station_values >= 0.0)
        if np.any(station_base_mask):
            obs_for_base.extend(obs[station_base_mask].astype("float64").tolist())
            base_at_station.extend(base_station_values[station_base_mask].astype("float64").tolist())
            raw_ratios = obs[station_base_mask] / np.maximum(base_station_values[station_base_mask], MIN_GRID_PRECIP_MM)
            clipped = np.abs(raw_ratios - np.clip(raw_ratios, RATIO_CLIP[0], RATIO_CLIP[1])) > 1e-9
            if np.any(clipped):
                clipped_step_count += 1
                clipped_station_sample_count += int(np.sum(clipped))
            obs_mean = float(np.mean(obs[station_base_mask]))
            grid_mean = float(np.mean(base_station_values[station_base_mask]))
            if grid_mean < MIN_GRID_PRECIP_MM and obs_mean >= WET_STATION_MEAN_MM:
                occurrence_repair_step_count += 1

        station_corrected_mask = obs_valid & np.isfinite(corrected_station_values) & (corrected_station_values >= 0.0)
        if np.any(station_corrected_mask):
            obs_for_corrected.extend(obs[station_corrected_mask].astype("float64").tolist())
            corrected_at_station.extend(corrected_station_values[station_corrected_mask].astype("float64").tolist())

        if base_mean is not None and corrected_mean is not None and float(base_mean) >= MIN_GRID_PRECIP_MM:
            correction_factors.append(float(corrected_mean) / max(float(base_mean), MIN_GRID_PRECIP_MM))

    base_total = safe_stat(base_basin_means, np.sum)
    corrected_total = safe_stat(corrected_basin_means, np.sum)
    before_metrics = paired_station_metrics(obs_for_base, base_at_station)
    after_metrics = paired_station_metrics(obs_for_corrected, corrected_at_station)
    occurrence_before = precipitation_occurrence_metrics(obs_for_base, base_at_station)
    occurrence_after = precipitation_occurrence_metrics(obs_for_corrected, corrected_at_station)
    possible_station_day_samples = int(len(records) * len(station_ids))
    valid_station_day_samples = int(sum(available_station_counts))
    missing_station_day_samples = max(0, possible_station_day_samples - valid_station_day_samples)
    mae_before = before_metrics.get("mae_mm")
    mae_after = after_metrics.get("mae_mm")
    pbias_before = before_metrics.get("pbias_percent")
    pbias_after = after_metrics.get("pbias_percent")
    mae_change = relative_change_percent(float(mae_after), float(mae_before)) if mae_before is not None and mae_after is not None else None
    pbias_abs_change = (
        relative_change_percent(abs(float(pbias_after)), abs(float(pbias_before)))
        if pbias_before is not None and pbias_after is not None and abs(float(pbias_before)) > 1e-12
        else None
    )
    leave_one_out = (
        leave_one_station_out_diagnostics(records, stations, station_series)
        if mode == "grid_plus_station_bias" and algorithm == STATION_CORRECTION_ALGORITHM_V2
        else {
            "schema": "precipitation_station_leave_one_out_v1",
            "status": "not_applicable",
            "algorithm": algorithm,
        }
    )

    return {
        "schema": "precipitation_hydro_diagnostics_v2",
        "mode": mode,
        "target_file_count": int(target_file_count),
        "time_step_count": int(len(records)),
        "station_count": int(len(station_ids)),
        "station_day_samples_total": possible_station_day_samples,
        "station_day_samples_available": valid_station_day_samples,
        "station_day_samples_missing": missing_station_day_samples,
        "station_day_missing_rate_percent": ratio_percent(missing_station_day_samples, possible_station_day_samples),
        "min_available_station_count": int(min(available_station_counts)) if available_station_counts else None,
        "mean_available_station_count": safe_stat(available_station_counts, np.mean),
        "basin_precip_total_before_mm": base_total,
        "basin_precip_total_after_mm": corrected_total,
        "basin_precip_total_change_mm": (
            float(corrected_total) - float(base_total)
            if corrected_total is not None and base_total is not None
            else None
        ),
        "basin_precip_total_change_percent": relative_change_percent(corrected_total, base_total),
        "basin_mean_daily_before_mm": safe_stat(base_basin_means, np.mean),
        "basin_mean_daily_after_mm": safe_stat(corrected_basin_means, np.mean),
        "basin_monthly_total_before_mm": monthly_precipitation_totals(base_basin_records),
        "basin_monthly_total_after_mm": monthly_precipitation_totals(corrected_basin_records),
        "basin_max_daily_before_mm": safe_stat(base_daily_max, np.max),
        "basin_max_daily_after_mm": safe_stat(corrected_daily_max, np.max),
        "wet_day_count_before": int(np.sum(np.asarray(base_basin_means) >= WET_STATION_MEAN_MM)) if base_basin_means else None,
        "wet_day_count_after": int(np.sum(np.asarray(corrected_basin_means) >= WET_STATION_MEAN_MM)) if corrected_basin_means else None,
        "basin_occurrence_before": precipitation_sequence_metrics(base_basin_means),
        "basin_occurrence_after": precipitation_sequence_metrics(corrected_basin_means),
        "mean_wet_pixel_ratio_before_percent": (safe_stat(base_wet_ratios, np.mean) or 0.0) * 100.0 if base_wet_ratios else None,
        "mean_wet_pixel_ratio_after_percent": (safe_stat(corrected_wet_ratios, np.mean) or 0.0) * 100.0 if corrected_wet_ratios else None,
        "station_point_before": before_metrics,
        "station_point_after": after_metrics,
        "station_occurrence_before": occurrence_before,
        "station_occurrence_after": occurrence_after,
        "station_leave_one_out": leave_one_out,
        "station_point_mae_change_percent": mae_change,
        "station_point_abs_pbias_change_percent": pbias_abs_change,
        "correction_factor_mean": safe_stat(correction_factors, np.mean),
        "correction_factor_min": safe_stat(correction_factors, np.min),
        "correction_factor_max": safe_stat(correction_factors, np.max),
        "spatial_correction_strength": {
            "cell_step_count": int(spatial_change_cell_steps),
            "mean_absolute_change_mm": (
                float(spatial_abs_change_sum / spatial_change_cell_steps)
                if spatial_change_cell_steps > 0 else None
            ),
            "mean_relative_change_percent": (
                float(spatial_relative_change_sum / spatial_change_cell_steps * 100.0)
                if spatial_change_cell_steps > 0 else None
            ),
            "changed_gt_10_percent_cell_step_count": int(spatial_changed_gt_10pct_cell_steps),
            "changed_gt_10_percent_cell_step_percent": ratio_percent(
                spatial_changed_gt_10pct_cell_steps, spatial_change_cell_steps,
            ),
            "max_absolute_change_mm": float(spatial_max_abs_change) if spatial_change_cell_steps > 0 else None,
        },
        "ratio_clip_step_count": int(clipped_step_count),
        "ratio_clip_station_sample_count": int(clipped_station_sample_count),
        "grid_missed_precip_repair_step_count": int(occurrence_repair_step_count),
        "hydrological_time_basis_note": (
            "小时站点降水已按水文日 08:00-次日08:00 累计为日降水；"
            "日尺度栅格降水、气温和蒸散发按文件日期使用，若来源产品不是 08:00-08:00，日峰时间可能存在半天到一天偏差。"
        ),
    }


def format_time(value: Any, step_hours: float) -> str:
    if value in (None, ""):
        return ""
    ts = pd.to_datetime(value)
    if abs(step_hours - 24.0) < 1e-9 and ts.hour == 0 and ts.minute == 0 and ts.second == 0:
        return ts.strftime("%Y-%m-%d")
    return ts.strftime("%Y-%m-%d %H:%M")


def record_period_text(records: list[tuple[pd.Timestamp, Path]], step_hours: float) -> str:
    coverage = summarize_time_coverage([timestamp for timestamp, _ in records], step_hours)
    return str(coverage["period_summary"])


def summarize_record_participation(
    *,
    config: dict[str, Any],
    mode: str,
    profile: str,
    prec_source: str,
    records: list[tuple[pd.Timestamp, Path]],
    expected_index: pd.DatetimeIndex | None,
    missing_expected_steps: list[pd.Timestamp],
    skipped_out_of_scope: int,
    stations: pd.DataFrame,
    station_series: pd.DataFrame,
    station_format: str,
    station_time_aggregation: dict[str, Any] | None,
    base_dir: Path,
    target_dir: Path,
    written: int,
    use_timestamp_names: bool = False,
    transfer_rule_summary: dict[str, Any] | None = None,
    processing_stats: dict[str, Any] | None = None,
    day_basis_diagnostics: dict[str, Any] | None = None,
) -> dict[str, Any]:
    step_hours = normalize_time_step_hours(config.get("时间步长_小时", 24.0))
    time_basis = task_time_basis(config, context="calibration")
    time_basis_label = TIME_BASIS_LABELS.get(time_basis, "当前任务时段")
    timestamps = pd.DatetimeIndex([pd.Timestamp(ts) for ts, _ in records])
    station_ids = [str(item) for item in stations["station_id"].tolist()]
    expected_steps = int(len(expected_index)) if expected_index is not None else int(len(timestamps))
    if len(timestamps) > 0 and station_ids:
        present = station_series.reindex(timestamps)[station_ids]
        available_counts = ((present.notna()) & (present >= 0.0)).sum(axis=1)
        station_missing = present.isna().mean(axis=0).sort_values(ascending=False)
        zero_flags = available_counts == 0
        covered_station_steps = int((available_counts > 0).sum())
        zero_station_steps = int(zero_flags.sum())
        max_zero = max_consecutive_true(zero_flags.tolist())
        min_available = int(available_counts.min()) if not available_counts.empty else None
        mean_available = float(available_counts.mean()) if not available_counts.empty else None
        station_missing_rates = [
            {"station_id": str(station_id), "missing_rate": float(rate)}
            for station_id, rate in station_missing.head(20).items()
        ]
    else:
        available_counts = pd.Series(dtype="int64")
        covered_station_steps = 0
        zero_station_steps = int(len(timestamps))
        max_zero = int(len(timestamps))
        min_available = None
        mean_available = None
        station_missing_rates = []
    possible_station_day_samples = int(len(timestamps) * len(station_ids))
    valid_station_day_samples = int(available_counts.sum()) if not available_counts.empty else 0
    missing_station_day_samples = max(0, possible_station_day_samples - valid_station_day_samples)

    event_info = normalized_event_windows(config, step_hours=step_hours) if time_basis == TIME_BASIS_EVENT_WINDOWS else {"valid_events": []}
    record_set = {pd.Timestamp(ts) for ts in timestamps}
    event_coverage: list[dict[str, Any]] = []
    for event in event_info.get("valid_events", []):
        event_index = event_date_range(event["run_start"], event["run_end"], step_hours)
        event_selected = [pd.Timestamp(ts) for ts in event_index if pd.Timestamp(ts) in record_set]
        if len(event_index) > 0 and station_ids:
            event_present = station_series.reindex(event_index)[station_ids]
            event_available = ((event_present.notna()) & (event_present >= 0.0)).sum(axis=1)
            event_zero = event_available == 0
            event_station_covered = int((event_available > 0).sum())
            event_min_available = int(event_available.min()) if not event_available.empty else None
            event_mean_available = float(event_available.mean()) if not event_available.empty else None
            event_zero_steps = int(event_zero.sum())
            event_max_zero = max_consecutive_true(event_zero.tolist())
        else:
            event_station_covered = 0
            event_min_available = None
            event_mean_available = None
            event_zero_steps = int(len(event_index))
            event_max_zero = int(len(event_index))
        event_expected = int(len(event_index))
        event_file_coverage = len(event_selected) / event_expected if event_expected else None
        event_station_coverage = event_station_covered / event_expected if event_expected else None
        if event_expected and len(event_selected) == event_expected and event_zero_steps == 0:
            status = "ok"
        elif mode == "thiessen_station_only" and (len(event_selected) < event_expected or event_zero_steps > 0):
            status = "fail"
        elif len(event_selected) == 0 or event_station_covered == 0:
            status = "fail"
        else:
            status = "warn"
        event_coverage.append(
            {
                "event_id": event.get("event_id"),
                "name": event.get("name"),
                "purpose": event.get("purpose"),
                "run_start": format_time(event.get("run_start"), step_hours),
                "run_end": format_time(event.get("run_end"), step_hours),
                "expected_steps": event_expected,
                "selected_steps": int(len(event_selected)),
                "file_coverage_ratio": event_file_coverage,
                "station_coverage_ratio": event_station_coverage,
                "zero_available_steps": event_zero_steps,
                "max_consecutive_zero_steps": event_max_zero,
                "available_station_min": event_min_available,
                "available_station_mean": event_mean_available,
                "status": status,
            }
        )
    station_integrity = station_series_integrity_diagnostics(station_series, station_ids)
    combined_processing_stats = dict(processing_stats or {})
    combined_processing_stats["station_series_integrity"] = station_integrity
    combined_processing_stats["qc_blocked"] = bool(
        combined_processing_stats.get("qc_blocked", False) or station_integrity.get("qc_blocked", False)
    )
    hydro_diagnostics = summarize_precipitation_hydro_diagnostics(
        records,
        target_dir,
        stations,
        station_series,
        mode,
        use_timestamp_names=use_timestamp_names,
        algorithm=str(
            combined_processing_stats.get("algorithm", STATION_CORRECTION_ALGORITHM_LEGACY)
            or STATION_CORRECTION_ALGORITHM_LEGACY
        ),
    )

    return {
        "schema": "precipitation_strategy_summary_v1",
        "created_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "profile": profile,
        "mode": mode,
        "precip_source": prec_source,
        "time_basis": time_basis,
        "time_basis_label": time_basis_label,
        "time_step_hours": float(step_hours),
        "expected_steps": expected_steps,
        "selected_steps": int(len(records)),
        "written_files": int(written),
        "missing_expected_steps": int(len(missing_expected_steps)),
        "missing_expected_samples": [format_time(ts, step_hours) for ts in missing_expected_steps[:10]],
        "skipped_out_of_scope_steps": int(skipped_out_of_scope),
        "actual_start": format_time(timestamps[0], step_hours) if len(timestamps) else "",
        "actual_end": format_time(timestamps[-1], step_hours) if len(timestamps) else "",
        "actual_period": record_period_text(records, step_hours),
        "station_format": station_format,
        "station_time_aggregation": station_time_aggregation or {"enabled": False},
        "matched_station_count": int(len(station_ids)),
        "covered_station_steps": int(covered_station_steps),
        "zero_available_station_steps": int(zero_station_steps),
        "max_consecutive_zero_station_steps": int(max_zero),
        "station_day_samples_total": possible_station_day_samples,
        "station_day_samples_available": valid_station_day_samples,
        "station_day_samples_missing": missing_station_day_samples,
        "station_day_missing_rate_percent": ratio_percent(missing_station_day_samples, possible_station_day_samples),
        "min_available_station_count": min_available,
        "mean_available_station_count": mean_available,
        "station_missing_rates": station_missing_rates,
        "station_series_integrity": station_integrity,
        "event_coverage": event_coverage,
        "hydrological_diagnostics": hydro_diagnostics,
        "day_basis_diagnostics": day_basis_diagnostics or {
            "schema": "precipitation_day_basis_diagnostics_v1",
            "status": "not_run",
        },
        "transfer_rules": transfer_rule_summary or {"available": False, "status": "not_requested"},
        "processing_stats": combined_processing_stats,
        "base_dir": str(base_dir.resolve(strict=False)),
        "target_dir": str(target_dir.resolve(strict=False)),
    }


def write_strategy_summary(target_dir: Path, summary: dict[str, Any]) -> Path:
    path = target_dir / "precipitation_strategy_summary.json"
    path.write_text(json.dumps(summary, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    return path


def remove_stale_strategy_rasters(
    target_dir: Path,
    records: list[tuple[pd.Timestamp, Path]],
    *,
    use_timestamp_names: bool = False,
) -> int:
    expected_names = {
        raster_name_from_timestamp(ts) if use_timestamp_names else source_path.name
        for ts, source_path in records
    }
    removed = 0
    for path in target_dir.glob("*.tif"):
        if path.name in expected_names:
            continue
        path.unlink()
        removed += 1
    return removed


def sample_station_values(src: rasterio.io.DatasetReader, stations: pd.DataFrame) -> np.ndarray:
    coords = [(float(row.x), float(row.y)) for row in stations.itertuples(index=False)]
    samples = np.array([value[0] for value in src.sample(coords)], dtype="float64")
    if src.nodata is not None:
        samples[samples == src.nodata] = np.nan
    samples[samples < -9000] = np.nan
    return samples


def valid_station_observation_mask(obs: np.ndarray, grid_station: np.ndarray, weights: np.ndarray) -> np.ndarray:
    return np.isfinite(obs) & np.isfinite(grid_station) & (obs >= 0.0) & (grid_station >= 0.0) & (weights > 0)


def interpolated_station_correction_fields(
    src: rasterio.io.DatasetReader,
    raster_values: np.ndarray,
    stations: pd.DataFrame,
    obs: np.ndarray,
    grid_station: np.ndarray,
    valid: np.ndarray,
) -> dict[str, Any]:
    valid_mask = np.isfinite(raster_values)
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

    amount_valid = valid & (obs >= WET_STATION_MEAN_MM) & (grid_station >= WET_STATION_MEAN_MM)
    raw_ratios = obs[amount_valid] / np.maximum(grid_station[amount_valid], MIN_GRID_PRECIP_MM)
    clipped_ratios = np.clip(raw_ratios, RATIO_CLIP[0], RATIO_CLIP[1])
    residuals = obs[valid] - grid_station[valid]
    if np.any(amount_valid):
        log_ratio_values = idw_interpolate_to_points(
            station_x_m[amount_valid],
            station_y_m[amount_valid],
            np.log(clipped_ratios),
            grid_x_m,
            grid_y_m,
        )
        ratio_values = np.exp(log_ratio_values)
    else:
        ratio_values = np.ones(grid_x_m.shape, dtype="float64")
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
    station_occurrence_values = idw_interpolate_to_points(
        station_x_m[valid],
        station_y_m[valid],
        (obs[valid] >= WET_STATION_MEAN_MM).astype("float64"),
        grid_x_m,
        grid_y_m,
    )
    support_radius_m = station_support_radius_m(station_x_m[valid], station_y_m[valid])
    nearest_distance_m = nearest_station_distance_to_points(
        station_x_m[valid], station_y_m[valid], grid_x_m, grid_y_m,
    )
    temporal_confidence = float(np.sum(valid) / max(np.sum(weights_positive(stations)), 1))
    spatial_confidence = np.exp(-np.square(nearest_distance_m / max(support_radius_m, 1.0)))
    confidence_values = np.clip(temporal_confidence * spatial_confidence, 0.0, 1.0)
    return {
        "rows": rows,
        "cols": cols,
        "ratio_values": ratio_values,
        "residual_values": residual_values,
        "station_prec_values": station_prec_values,
        "station_occurrence_values": station_occurrence_values,
        "confidence_values": confidence_values,
        "support_radius_m": float(support_radius_m),
        "temporal_confidence": temporal_confidence,
        "raw_ratios": raw_ratios,
        "clipped_ratios": clipped_ratios,
        "residuals": residuals,
    }


def weights_positive(stations: pd.DataFrame) -> np.ndarray:
    if "weight" not in stations.columns:
        return np.ones(len(stations), dtype=bool)
    return stations["weight"].to_numpy(dtype="float64") > 0.0


def station_support_radius_m(station_x_m: np.ndarray, station_y_m: np.ndarray) -> float:
    x = np.asarray(station_x_m, dtype="float64")
    y = np.asarray(station_y_m, dtype="float64")
    valid = np.isfinite(x) & np.isfinite(y)
    x = x[valid]
    y = y[valid]
    if x.size < 2:
        return MIN_STATION_SUPPORT_RADIUS_M
    dx = x[:, None] - x[None, :]
    dy = y[:, None] - y[None, :]
    distances = np.sqrt(dx * dx + dy * dy)
    distances[distances <= 0.0] = np.inf
    nearest = np.min(distances, axis=1)
    finite = nearest[np.isfinite(nearest)]
    if finite.size == 0:
        return MIN_STATION_SUPPORT_RADIUS_M
    return float(max(MIN_STATION_SUPPORT_RADIUS_M, 2.0 * np.median(finite)))


def nearest_station_distance_to_points(
    station_x: np.ndarray,
    station_y: np.ndarray,
    target_x: np.ndarray,
    target_y: np.ndarray,
) -> np.ndarray:
    sx = np.asarray(station_x, dtype="float64")
    sy = np.asarray(station_y, dtype="float64")
    tx = np.asarray(target_x, dtype="float64")
    ty = np.asarray(target_y, dtype="float64")
    result = np.full(tx.shape, np.inf, dtype="float64")
    for start in range(0, tx.size, IDW_CHUNK_SIZE):
        end = min(start + IDW_CHUNK_SIZE, tx.size)
        dx = tx[start:end, None] - sx[None, :]
        dy = ty[start:end, None] - sy[None, :]
        result[start:end] = np.min(np.sqrt(dx * dx + dy * dy), axis=1)
    return result


def apply_legacy_station_observation_correction(
    base_values: np.ndarray,
    rows: np.ndarray,
    cols: np.ndarray,
    *,
    ratio_values: np.ndarray,
    residual_values: np.ndarray,
    station_prec_values: np.ndarray,
    obs_mean: float,
    grid_mean: float,
) -> np.ndarray:
    corrected_values = base_values * ratio_values
    residual_corrected = np.clip(base_values + residual_values, 0.0, None)
    if np.isfinite(grid_mean) and np.isfinite(obs_mean) and grid_mean < MIN_GRID_PRECIP_MM and obs_mean >= WET_STATION_MEAN_MM:
        corrected_values = np.clip(station_prec_values, 0.0, None)
    else:
        residual_weight = 0.0
        if np.isfinite(grid_mean) and np.isfinite(obs_mean) and obs_mean > grid_mean:
            residual_weight = float(np.clip((WET_STATION_MEAN_MM - grid_mean) / WET_STATION_MEAN_MM, 0.0, 1.0))
        corrected_values = (1.0 - residual_weight) * corrected_values + residual_weight * residual_corrected
        occurrence_gap = (base_values < MIN_GRID_PRECIP_MM) & (station_prec_values >= WET_STATION_MEAN_MM)
        if np.any(occurrence_gap):
            corrected_values[occurrence_gap] = np.maximum(
                corrected_values[occurrence_gap],
                residual_corrected[occurrence_gap],
            )
    return np.clip(corrected_values, 0.0, None)


def apply_station_observation_correction(
    base_values: np.ndarray,
    *,
    ratio_values: np.ndarray,
    station_prec_values: np.ndarray,
    station_occurrence_values: np.ndarray,
    confidence_values: np.ndarray,
    allow_exact_dry: bool = True,
) -> dict[str, np.ndarray]:
    base = np.clip(np.asarray(base_values, dtype="float64"), 0.0, None)
    confidence = np.clip(np.asarray(confidence_values, dtype="float64"), 0.0, 1.0)
    station_occurrence = np.clip(np.asarray(station_occurrence_values, dtype="float64"), 0.0, 1.0)
    background_occurrence = (base >= WET_STATION_MEAN_MM).astype("float64")
    occurrence_probability = (1.0 - confidence) * background_occurrence + confidence * station_occurrence
    wet_mask = occurrence_probability >= OCCURRENCE_DECISION_THRESHOLD

    ratios = np.clip(np.asarray(ratio_values, dtype="float64"), RATIO_CLIP[0], RATIO_CLIP[1])
    amount_corrected = base * np.exp(confidence * np.log(ratios))
    station_amount = np.clip(np.asarray(station_prec_values, dtype="float64"), 0.0, None)
    occurrence_gap = wet_mask & (background_occurrence < 0.5) & (station_occurrence >= OCCURRENCE_DECISION_THRESHOLD)
    if np.any(occurrence_gap):
        amount_corrected[occurrence_gap] = (
            (1.0 - confidence[occurrence_gap]) * base[occurrence_gap]
            + confidence[occurrence_gap] * station_amount[occurrence_gap]
        )
    high_confidence_dry = bool(allow_exact_dry) & (~wet_mask) & (confidence >= EXACT_DRY_CONFIDENCE) & (
        station_occurrence < OCCURRENCE_DECISION_THRESHOLD
    )
    corrected = np.clip(amount_corrected, 0.0, None)
    corrected[high_confidence_dry] = 0.0
    return {
        "corrected": corrected,
        "amount_corrected": np.clip(amount_corrected, 0.0, None),
        "wet_mask": wet_mask,
        "high_confidence_dry": high_confidence_dry,
        "occurrence_probability": occurrence_probability,
    }


def _empty_rule_accumulators(shape: tuple[int, int]) -> dict[str, np.ndarray]:
    return {
        "ratio_sum": np.zeros(shape, dtype="float64"),
        "ratio_count": np.zeros(shape, dtype="int32"),
        "residual_sum": np.zeros(shape, dtype="float64"),
        "residual_count": np.zeros(shape, dtype="int32"),
    }


def _accumulate_rule_field(acc: dict[str, np.ndarray], rows: np.ndarray, cols: np.ndarray, ratios: np.ndarray, residuals: np.ndarray) -> None:
    ratio_valid = np.isfinite(ratios)
    if np.any(ratio_valid):
        rr = rows[ratio_valid]
        cc = cols[ratio_valid]
        np.add.at(acc["ratio_sum"], (rr, cc), ratios[ratio_valid])
        np.add.at(acc["ratio_count"], (rr, cc), 1)
    residual_valid = np.isfinite(residuals)
    if np.any(residual_valid):
        rr = rows[residual_valid]
        cc = cols[residual_valid]
        np.add.at(acc["residual_sum"], (rr, cc), residuals[residual_valid])
        np.add.at(acc["residual_count"], (rr, cc), 1)


def _finalize_rule_array(total: np.ndarray, count: np.ndarray, fill_value: float) -> np.ndarray:
    result = np.full(total.shape, fill_value, dtype="float32")
    valid = count > 0
    if np.any(valid):
        result[valid] = (total[valid] / np.maximum(count[valid], 1)).astype("float32")
    return result


def _rule_paths(target_dir: Path) -> tuple[Path, Path]:
    return target_dir / TRANSFER_RULES_JSON, target_dir / TRANSFER_RULES_NPZ


def fit_grid_bias_transfer_rules(
    records: list[tuple[pd.Timestamp, Path]],
    target_dir: Path,
    stations: pd.DataFrame,
    station_series: pd.DataFrame,
    *,
    overwrite: bool = False,
) -> dict[str, Any]:
    json_path, npz_path = _rule_paths(target_dir)
    if json_path.exists() and npz_path.exists() and not overwrite:
        try:
            summary = json.loads(json_path.read_text(encoding="utf-8"))
            summary["loaded_existing"] = True
            return summary
        except Exception:
            pass

    weights = stations["weight"].to_numpy(dtype="float64")
    station_ids = stations["station_id"].tolist()
    global_acc: dict[str, np.ndarray] | None = None
    month_acc: dict[int, dict[str, np.ndarray]] = {}
    shape: tuple[int, int] | None = None
    crs_text = ""
    transform_values: list[float] = []
    training_days = 0
    valid_station_samples = 0
    monthly_training_days: dict[int, int] = {month: 0 for month in range(1, 13)}
    clipped_days = 0
    raw_ratio_values: list[float] = []

    for ts, path in records:
        if not path.exists():
            continue
        with rasterio.open(path) as src:
            arr = src.read(1).astype("float64")
            nodata = src.nodata
            if nodata is not None:
                arr[arr == nodata] = np.nan
            grid_station = sample_station_values(src, stations)
            obs = station_values_for_time(station_series, pd.Timestamp(ts), station_ids)
            valid = valid_station_observation_mask(obs, grid_station, weights)
            if not np.any(valid):
                continue
            if shape is None:
                shape = arr.shape
                global_acc = _empty_rule_accumulators(shape)
                crs_text = str(src.crs) if src.crs is not None else ""
                transform_values = [float(item) for item in src.transform.to_gdal()]
            if arr.shape != shape:
                continue
            fields = interpolated_station_correction_fields(src, arr, stations, obs, grid_station, valid)
            rows = fields["rows"]
            cols = fields["cols"]
            ratios = np.asarray(fields["ratio_values"], dtype="float64")
            residuals = np.asarray(fields["residual_values"], dtype="float64")
            assert global_acc is not None
            _accumulate_rule_field(global_acc, rows, cols, ratios, residuals)
            month = int(pd.Timestamp(ts).month)
            month_acc.setdefault(month, _empty_rule_accumulators(shape))
            _accumulate_rule_field(month_acc[month], rows, cols, ratios, residuals)
            training_days += 1
            monthly_training_days[month] += 1
            valid_station_samples += int(np.sum(valid))
            raw_ratios = np.asarray(fields["raw_ratios"], dtype="float64")
            clipped_ratios = np.asarray(fields["clipped_ratios"], dtype="float64")
            if np.any(np.abs(raw_ratios - clipped_ratios) > 1e-9):
                clipped_days += 1
            raw_ratio_values.extend(raw_ratios[np.isfinite(raw_ratios)].tolist())

    if shape is None or global_acc is None or training_days <= 0:
        summary = {
            "schema": TRANSFER_RULES_SCHEMA,
            "available": False,
            "status": "no_training_samples",
            "training_days": 0,
            "valid_station_samples": 0,
            "json_path": str(json_path.resolve(strict=False)),
            "npz_path": str(npz_path.resolve(strict=False)),
        }
        target_dir.mkdir(parents=True, exist_ok=True)
        json_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
        return summary

    global_ratio = _finalize_rule_array(global_acc["ratio_sum"], global_acc["ratio_count"], 1.0)
    global_residual = _finalize_rule_array(global_acc["residual_sum"], global_acc["residual_count"], 0.0)
    arrays: dict[str, np.ndarray] = {
        "global_ratio": global_ratio,
        "global_residual": global_residual,
    }
    monthly_meta: dict[str, Any] = {}
    for month in range(1, 13):
        acc = month_acc.get(month)
        if acc is None or monthly_training_days.get(month, 0) <= 0:
            arrays[f"month_{month:02d}_ratio"] = global_ratio
            arrays[f"month_{month:02d}_residual"] = global_residual
            monthly_meta[f"{month:02d}"] = {"training_days": 0, "fallback": "global"}
            continue
        arrays[f"month_{month:02d}_ratio"] = _finalize_rule_array(acc["ratio_sum"], acc["ratio_count"], 1.0)
        arrays[f"month_{month:02d}_residual"] = _finalize_rule_array(acc["residual_sum"], acc["residual_count"], 0.0)
        monthly_meta[f"{month:02d}"] = {"training_days": int(monthly_training_days[month]), "fallback": ""}

    ratio_finite = global_ratio[np.isfinite(global_ratio)]
    residual_finite = global_residual[np.isfinite(global_residual)]
    raw_ratio_arr = np.asarray(raw_ratio_values, dtype="float64")
    summary = {
        "schema": TRANSFER_RULES_SCHEMA,
        "available": True,
        "status": "ok",
        "created_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "method": "station_observed_days_to_monthly_idw_ratio_residual_fields",
        "training_days": int(training_days),
        "valid_station_samples": int(valid_station_samples),
        "clipped_training_days": int(clipped_days),
        "ratio_clip": [float(RATIO_CLIP[0]), float(RATIO_CLIP[1])],
        "shape": [int(shape[0]), int(shape[1])],
        "crs": crs_text,
        "transform": transform_values,
        "monthly": monthly_meta,
        "global_ratio_mean": safe_stat(ratio_finite, np.mean),
        "global_ratio_min": safe_stat(ratio_finite, np.min),
        "global_ratio_max": safe_stat(ratio_finite, np.max),
        "global_residual_mean_mm": safe_stat(residual_finite, np.mean),
        "raw_station_ratio_mean": safe_stat(raw_ratio_arr, np.mean),
        "json_path": str(json_path.resolve(strict=False)),
        "npz_path": str(npz_path.resolve(strict=False)),
    }
    target_dir.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(npz_path, **arrays)
    json_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    return summary


def load_grid_bias_transfer_rules(rule_dir: Path) -> dict[str, Any] | None:
    json_path, npz_path = _rule_paths(rule_dir)
    if not json_path.exists() or not npz_path.exists():
        return None
    try:
        summary = json.loads(json_path.read_text(encoding="utf-8"))
        if not bool(summary.get("available", False)):
            return None
        with np.load(npz_path) as loaded:
            arrays = {key: np.asarray(loaded[key]).copy() for key in loaded.files}
        return {"summary": summary, "arrays": arrays, "json_path": json_path, "npz_path": npz_path}
    except Exception:
        return None


def apply_transfer_rule_to_array(arr: np.ndarray, rules: dict[str, Any], ts: pd.Timestamp) -> tuple[np.ndarray, bool, str]:
    arrays = rules.get("arrays")
    if arrays is None:
        return arr.copy(), False, "none"
    month = int(pd.Timestamp(ts).month)
    monthly = dict(dict(rules.get("summary", {}) or {}).get("monthly", {}) or {})
    month_meta = dict(monthly.get(f"{month:02d}", {}) or {})
    ratio_key = f"month_{month:02d}_ratio"
    residual_key = f"month_{month:02d}_residual"
    if ratio_key not in arrays or residual_key not in arrays:
        ratio_key = "global_ratio"
        residual_key = "global_residual"
        source = "global"
    else:
        source = "global" if str(month_meta.get("fallback", "")) == "global" else f"month_{month:02d}"
    ratio = np.asarray(arrays[ratio_key], dtype="float64")
    residual = np.asarray(arrays[residual_key], dtype="float64")
    if ratio.shape != arr.shape or residual.shape != arr.shape:
        return arr.copy(), False, "shape_mismatch"
    out = arr.copy()
    valid = np.isfinite(out)
    if not np.any(valid):
        return out, False, source
    ratio_values = np.where(np.isfinite(ratio[valid]), ratio[valid], 1.0)
    residual_values = np.where(np.isfinite(residual[valid]), residual[valid], 0.0)
    base_values = out[valid]
    ratio_corrected = base_values * ratio_values
    residual_corrected = np.clip(base_values + residual_values, 0.0, None)
    residual_weight = np.clip((WET_STATION_MEAN_MM - base_values) / WET_STATION_MEAN_MM, 0.0, 1.0)
    residual_weight = np.where(residual_values > 0.0, residual_weight, 0.0)
    corrected = (1.0 - residual_weight) * ratio_corrected + residual_weight * residual_corrected
    occurrence_gap = (base_values < MIN_GRID_PRECIP_MM) & (residual_values >= WET_STATION_MEAN_MM)
    if np.any(occurrence_gap):
        corrected[occurrence_gap] = np.maximum(corrected[occurrence_gap], residual_corrected[occurrence_gap])
    out[valid] = np.clip(corrected, 0.0, None)
    return out, True, source


def apply_transfer_rule_to_raster(
    ts: pd.Timestamp,
    source_path: Path,
    target_path: Path,
    rules: dict[str, Any],
    *,
    overwrite: bool = True,
) -> tuple[bool, str]:
    if target_path.exists() and not overwrite:
        return True, "existing"
    with rasterio.open(source_path) as src:
        arr = src.read(1).astype("float64")
        nodata = src.nodata
        if nodata is not None:
            arr[arr == nodata] = np.nan
        out, applied, source = apply_transfer_rule_to_array(arr, rules, pd.Timestamp(ts))
        profile = src.profile.copy()
        profile.update(dtype="float32", compress="lzw")
        if nodata is None:
            profile["nodata"] = -9999.0
        out_to_write = np.where(np.isfinite(out), out, profile["nodata"]).astype("float32")
        write_raster(target_path, profile, out_to_write)
    return applied, source


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


def station_values_for_time(station_series: pd.DataFrame, ts: pd.Timestamp, station_ids: list[str]) -> np.ndarray:
    if ts not in station_series.index:
        return np.full(len(station_ids), np.nan)
    values = station_series.loc[ts, station_ids]
    if isinstance(values, pd.DataFrame):
        values = values.mean(axis=0, numeric_only=True)
    return values.to_numpy(dtype="float64")


def no_available_station_steps(
    records: list[tuple[pd.Timestamp, Path]],
    stations: pd.DataFrame,
    station_series: pd.DataFrame,
) -> list[pd.Timestamp]:
    station_ids = stations["station_id"].tolist()
    missing: list[pd.Timestamp] = []
    for ts, _ in records:
        obs = station_values_for_time(station_series, pd.Timestamp(ts), station_ids)
        if not np.any(np.isfinite(obs) & (obs >= 0.0)):
            missing.append(pd.Timestamp(ts))
    return missing


def enforce_monthly_occurrence_conservation(
    records: list[tuple[pd.Timestamp, Path]],
    target_dir: Path,
    stations: pd.DataFrame,
    station_series: pd.DataFrame,
) -> dict[str, Any]:
    grouped: dict[tuple[int, int], list[tuple[pd.Timestamp, Path]]] = {}
    for ts, path in records:
        stamp = pd.Timestamp(ts)
        grouped.setdefault((int(stamp.year), int(stamp.month)), []).append((stamp, path))

    weights = stations["weight"].to_numpy(dtype="float64")
    station_ids = stations["station_id"].tolist()
    month_summaries: list[dict[str, Any]] = []
    max_factor = 1.0
    high_factor_cell_count = 0
    high_factor_target_volume_mm = 0.0
    eligible_cell_month_count = 0
    unresolved_cell_count = 0
    unresolved_volume_mm = 0.0
    high_removed_fraction_cell_count = 0
    high_removed_fraction_volume_mm = 0.0
    target_volume_mm = 0.0
    removed_volume_mm = 0.0

    for (year, month), month_records in sorted(grouped.items()):
        target_sum: np.ndarray | None = None
        corrected_sum: np.ndarray | None = None
        output_paths: list[Path] = []
        profile: dict[str, Any] | None = None
        for day_index, (ts, source_path) in enumerate(month_records):
            output_path = target_dir / source_path.name
            if not output_path.exists():
                continue
            output_paths.append(output_path)
            with rasterio.open(source_path) as src:
                arr = src.read(1).astype("float64")
                nodata = src.nodata
                if nodata is not None:
                    arr[arr == nodata] = np.nan
                target = arr.copy()
                occurrence_probability = (arr >= WET_STATION_MEAN_MM).astype("float64")
                grid_station = sample_station_values(src, stations)
                obs = station_values_for_time(station_series, ts, station_ids)
                valid = valid_station_observation_mask(obs, grid_station, weights)
                if np.any(valid):
                    fields = interpolated_station_correction_fields(src, arr, stations, obs, grid_station, valid)
                    rows = fields["rows"]
                    cols = fields["cols"]
                    correction = apply_station_observation_correction(
                        arr[rows, cols],
                        ratio_values=np.asarray(fields["ratio_values"], dtype="float64"),
                        station_prec_values=np.asarray(fields["station_prec_values"], dtype="float64"),
                        station_occurrence_values=np.asarray(fields["station_occurrence_values"], dtype="float64"),
                        confidence_values=np.asarray(fields["confidence_values"], dtype="float64"),
                        allow_exact_dry=bool(np.all(obs[valid] < WET_STATION_MEAN_MM)),
                    )
                    target[rows, cols] = correction["amount_corrected"]
                    occurrence_probability[rows, cols] = correction["occurrence_probability"]
                if profile is None:
                    profile = src.profile.copy()
            with rasterio.open(output_path) as corrected_src:
                corrected = corrected_src.read(1).astype("float64")
                if corrected_src.nodata is not None:
                    corrected[corrected == corrected_src.nodata] = np.nan
            valid_grid = np.isfinite(target)
            if target_sum is None:
                target_sum = np.zeros(target.shape, dtype="float64")
                corrected_sum = np.zeros(target.shape, dtype="float64")
            target_sum[valid_grid] += np.clip(target[valid_grid], 0.0, None)
            corrected_valid = valid_grid & np.isfinite(corrected)
            assert corrected_sum is not None
            corrected_sum[corrected_valid] += np.clip(corrected[corrected_valid], 0.0, None)

        if target_sum is None or corrected_sum is None or profile is None:
            continue

        factor = np.ones(target_sum.shape, dtype="float64")
        scalable = corrected_sum > MIN_GRID_PRECIP_MM
        factor[scalable] = target_sum[scalable] / corrected_sum[scalable]
        factor = np.clip(factor, 0.0, None)
        unresolved = (target_sum > MIN_GRID_PRECIP_MM) & ~scalable
        high_factor = scalable & (factor > MAX_MONTHLY_REDISTRIBUTION_FACTOR)
        removed = np.clip(target_sum - corrected_sum, 0.0, None)
        removed_fraction = np.zeros(target_sum.shape, dtype="float64")
        eligible = target_sum > MIN_GRID_PRECIP_MM
        removed_fraction[eligible] = removed[eligible] / target_sum[eligible]
        high_removed_fraction = eligible & (removed_fraction > MAX_MONTHLY_REMOVED_FRACTION)
        month_max_factor = float(np.nanmax(factor[scalable])) if np.any(scalable) else 1.0
        month_unresolved_volume = float(np.sum(target_sum[unresolved])) if np.any(unresolved) else 0.0
        month_high_factor_volume = float(np.sum(target_sum[high_factor])) if np.any(high_factor) else 0.0
        month_target_volume = float(np.sum(target_sum[eligible])) if np.any(eligible) else 0.0
        month_removed_volume = float(np.sum(removed[eligible])) if np.any(eligible) else 0.0
        month_high_removed_volume = (
            float(np.sum(target_sum[high_removed_fraction])) if np.any(high_removed_fraction) else 0.0
        )
        month_eligible_count = int(np.count_nonzero(eligible))
        max_factor = max(max_factor, month_max_factor)
        high_factor_cell_count += int(np.count_nonzero(high_factor))
        high_factor_target_volume_mm += month_high_factor_volume
        eligible_cell_month_count += month_eligible_count
        unresolved_cell_count += int(np.count_nonzero(unresolved))
        unresolved_volume_mm += month_unresolved_volume
        high_removed_fraction_cell_count += int(np.count_nonzero(high_removed_fraction))
        high_removed_fraction_volume_mm += month_high_removed_volume
        target_volume_mm += month_target_volume
        removed_volume_mm += month_removed_volume

        for _ts, source_path in month_records:
            output_path = target_dir / source_path.name
            if not output_path.exists():
                continue
            with rasterio.open(output_path) as src:
                corrected = src.read(1).astype("float64")
                nodata = src.nodata
                if nodata is not None:
                    corrected[corrected == nodata] = np.nan
                adjusted = corrected.copy()
                wet = np.isfinite(adjusted) & (adjusted > 0.0) & scalable
                adjusted[wet] *= factor[wet]
                out_profile = src.profile.copy()
                out_profile.update(dtype="float32", compress="lzw")
                if nodata is None:
                    out_profile["nodata"] = -9999.0
            out_to_write = np.where(np.isfinite(adjusted), adjusted, out_profile["nodata"]).astype("float32")
            write_raster(output_path, out_profile, out_to_write)

        month_summaries.append(
            {
                "month": f"{year:04d}-{month:02d}",
                "max_redistribution_factor": month_max_factor,
                "eligible_cell_count": month_eligible_count,
                "high_factor_cell_count": int(np.count_nonzero(high_factor)),
                "high_factor_target_volume_mm": month_high_factor_volume,
                "max_removed_fraction": float(np.max(removed_fraction[eligible])) if np.any(eligible) else 0.0,
                "max_allowed_removed_fraction": float(MAX_MONTHLY_REMOVED_FRACTION),
                "high_removed_fraction_cell_count": int(np.count_nonzero(high_removed_fraction)),
                "high_removed_fraction_target_volume_mm": month_high_removed_volume,
                "target_volume_mm": month_target_volume,
                "removed_volume_mm": month_removed_volume,
                "removed_volume_percent": ratio_percent(month_removed_volume, month_target_volume),
                "unresolved_cell_count": int(np.count_nonzero(unresolved)),
                "unresolved_volume_mm": month_unresolved_volume,
            }
        )

    return {
        "method": "same_cell_same_month_amount_conservation",
        "months": month_summaries,
        "max_redistribution_factor": float(max_factor),
        "max_allowed_redistribution_factor": float(MAX_MONTHLY_REDISTRIBUTION_FACTOR),
        "eligible_cell_month_count": int(eligible_cell_month_count),
        "high_factor_cell_count": int(high_factor_cell_count),
        "high_factor_cell_month_percent": ratio_percent(high_factor_cell_count, eligible_cell_month_count),
        "high_factor_target_volume_mm": float(high_factor_target_volume_mm),
        "max_allowed_removed_fraction": float(MAX_MONTHLY_REMOVED_FRACTION),
        "high_removed_fraction_cell_count": int(high_removed_fraction_cell_count),
        "high_removed_fraction_cell_month_percent": ratio_percent(
            high_removed_fraction_cell_count, eligible_cell_month_count,
        ),
        "high_removed_fraction_target_volume_mm": float(high_removed_fraction_volume_mm),
        "target_volume_mm": float(target_volume_mm),
        "removed_volume_mm": float(removed_volume_mm),
        "removed_volume_percent": ratio_percent(removed_volume_mm, target_volume_mm),
        "unresolved_cell_count": int(unresolved_cell_count),
        "unresolved_volume_mm": float(unresolved_volume_mm),
        "qc_blocked": bool(
            high_factor_cell_count > 0
            or high_removed_fraction_cell_count > 0
            or unresolved_cell_count > 0
        ),
    }


def apply_grid_bias_correction(
    records: list[tuple[pd.Timestamp, Path]],
    target_dir: Path,
    stations: pd.DataFrame,
    station_series: pd.DataFrame,
    overwrite: bool,
    transfer_rules: dict[str, Any] | None = None,
    *,
    return_stats: bool = False,
    algorithm: str = DEFAULT_STATION_CORRECTION_ALGORITHM,
    step_hours: float = 24.0,
) -> int | dict[str, Any]:
    algorithm_key = str(algorithm or DEFAULT_STATION_CORRECTION_ALGORITHM).strip().lower()
    if algorithm_key not in {STATION_CORRECTION_ALGORITHM_V2, STATION_CORRECTION_ALGORITHM_LEGACY}:
        raise ValueError(f"Unknown station precipitation correction algorithm: {algorithm}")
    written = 0
    processed_count = 0
    skipped_existing_count = 0
    no_station_step_count = 0
    transfer_rule_step_count = 0
    pass_through_step_count = 0
    clipped_step_count = 0
    occurrence_repair_count = 0
    total_valid_station_steps = 0
    weights = stations["weight"].to_numpy(dtype="float64")
    station_ids = stations["station_id"].tolist()
    for ts, path in records:
        output = target_dir / path.name
        if output.exists() and not overwrite:
            skipped_existing_count += 1
            written += 1
            continue
        with rasterio.open(path) as src:
            arr = src.read(1).astype("float64")
            nodata = src.nodata
            if nodata is not None:
                arr[arr == nodata] = np.nan
            grid_station = sample_station_values(src, stations)
            obs = station_values_for_time(station_series, pd.Timestamp(ts), station_ids)
            valid = valid_station_observation_mask(obs, grid_station, weights)
            out = arr.copy()
            if np.any(valid):
                obs_mean = np.average(obs[valid], weights=weights[valid])
                grid_mean = np.average(grid_station[valid], weights=weights[valid])
                total_valid_station_steps += int(np.sum(valid))
                fields = interpolated_station_correction_fields(src, out, stations, obs, grid_station, valid)
                raw_ratios = np.asarray(fields["raw_ratios"], dtype="float64")
                clipped_ratios = np.asarray(fields["clipped_ratios"], dtype="float64")
                if np.any(np.abs(raw_ratios - clipped_ratios) > 1e-9):
                    clipped_step_count += 1
                if np.isfinite(grid_mean) and np.isfinite(obs_mean) and grid_mean < MIN_GRID_PRECIP_MM and obs_mean >= WET_STATION_MEAN_MM:
                    occurrence_repair_count += 1
                rows = fields["rows"]
                cols = fields["cols"]
                base_values = out[rows, cols]
                if algorithm_key == STATION_CORRECTION_ALGORITHM_LEGACY:
                    corrected_values = apply_legacy_station_observation_correction(
                        base_values,
                        rows,
                        cols,
                        ratio_values=np.asarray(fields["ratio_values"], dtype="float64"),
                        residual_values=np.asarray(fields["residual_values"], dtype="float64"),
                        station_prec_values=np.asarray(fields["station_prec_values"], dtype="float64"),
                        obs_mean=float(obs_mean),
                        grid_mean=float(grid_mean),
                    )
                    out[rows, cols] = np.clip(corrected_values, 0.0, None)
                else:
                    correction = apply_station_observation_correction(
                        base_values,
                        ratio_values=np.asarray(fields["ratio_values"], dtype="float64"),
                        station_prec_values=np.asarray(fields["station_prec_values"], dtype="float64"),
                        station_occurrence_values=np.asarray(fields["station_occurrence_values"], dtype="float64"),
                        confidence_values=np.asarray(fields["confidence_values"], dtype="float64"),
                        allow_exact_dry=bool(np.all(obs[valid] < WET_STATION_MEAN_MM)),
                    )
                    out[rows, cols] = correction["corrected"]
            else:
                no_station_step_count += 1
                if algorithm_key == STATION_CORRECTION_ALGORITHM_LEGACY and transfer_rules is not None:
                    out, applied, _source = apply_transfer_rule_to_array(out, transfer_rules, pd.Timestamp(ts))
                    if applied:
                        transfer_rule_step_count += 1
                    else:
                        pass_through_step_count += 1
                else:
                    pass_through_step_count += 1
            profile = src.profile.copy()
            profile.update(dtype="float32", compress="lzw")
            if nodata is None:
                profile["nodata"] = -9999.0
            out_to_write = np.where(np.isfinite(out), out, profile["nodata"]).astype("float32")
            write_raster(output, profile, out_to_write)
            processed_count += 1
            written += 1
    period_text = record_period_text(records, step_hours)
    print(
        "空间订正摘要: "
        f"处理范围 {period_text}；"
        f"本次新计算 {time_step_count_text(processed_count, step_hours)}；"
        f"已有输出复用 {time_step_count_text(skipped_existing_count, step_hours)}；"
        f"有效站点-时段样本 {total_valid_station_steps}；"
        f"无可用站点 {time_step_count_text(no_station_step_count, step_hours)}；"
        f"规则外推 {time_step_count_text(transfer_rule_step_count, step_hours)}；"
        f"原样保留 {time_step_count_text(pass_through_step_count, step_hours)}；"
        f"倍率裁剪 {time_step_count_text(clipped_step_count, step_hours)}；"
        f"格点漏报修复 {time_step_count_text(occurrence_repair_count, step_hours)}"
    )
    if skipped_existing_count and processed_count == 0:
        print("提示: 本次没有重新计算已有订正文件；如需刷新空间订正统计和结果，请启用覆盖。")
    monthly_conservation: dict[str, Any] | None = None
    if (
        algorithm_key == STATION_CORRECTION_ALGORITHM_V2
        and processed_count > 0
        and skipped_existing_count == 0
    ):
        monthly_conservation = enforce_monthly_occurrence_conservation(
            records, target_dir, stations, station_series,
        )
    stats = {
        "method": "grid_plus_station_bias",
        "algorithm": algorithm_key,
        "written_files": int(written),
        "processed_steps": int(processed_count),
        "skipped_existing_steps": int(skipped_existing_count),
        "direct_station_corrected_steps": int(processed_count - no_station_step_count),
        "no_available_station_steps": int(no_station_step_count),
        "transfer_rule_applied_steps": int(transfer_rule_step_count),
        "pass_through_steps": int(pass_through_step_count),
        "valid_station_step_samples": int(total_valid_station_steps),
        "ratio_clip_steps": int(clipped_step_count),
        "grid_missed_precip_repair_steps": int(occurrence_repair_count),
        "transfer_rules_available": bool(transfer_rules is not None),
        "monthly_conservation": monthly_conservation,
        "qc_blocked": bool(monthly_conservation and monthly_conservation.get("qc_blocked")),
    }
    return stats if return_stats else written


def apply_thiessen(
    records: list[tuple[pd.Timestamp, Path]],
    target_dir: Path,
    stations: pd.DataFrame,
    station_series: pd.DataFrame,
    overwrite: bool,
    *,
    use_timestamp_names: bool = False,
) -> int:
    written = 0
    processed_count = 0
    skipped_existing_count = 0
    station_ids = stations["station_id"].tolist()
    nearest_cache: dict[tuple[int, ...], np.ndarray] = {}
    valid_mask: np.ndarray | None = None
    no_station_step_count = 0
    for ts, path in records:
        output = target_dir / (raster_name_from_timestamp(ts) if use_timestamp_names else path.name)
        if output.exists() and not overwrite:
            skipped_existing_count += 1
            written += 1
            continue
        with rasterio.open(path) as src:
            arr = src.read(1).astype("float64")
            nodata = src.nodata
            if nodata is not None:
                arr[arr == nodata] = np.nan
            if valid_mask is None:
                valid_mask = np.isfinite(arr)
            obs = station_values_for_time(station_series, pd.Timestamp(ts), station_ids)
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
                raise ValueError(f"纯站点泰森分配在 {format_time(ts, 1.0)} 没有任何可用站点，已停止生成。")
            profile = src.profile.copy()
            profile.update(dtype="float32", compress="lzw")
            if nodata is None:
                profile["nodata"] = -9999.0
            out_to_write = np.where(np.isfinite(out), out, profile["nodata"]).astype("float32")
            write_raster(output, profile, out_to_write)
            processed_count += 1
            written += 1
    step_hours = 24.0 if all(pd.Timestamp(ts).hour == 0 for ts, _ in records) else 1.0
    print(
        "泰森分配摘要: "
        f"处理范围 {record_period_text(records, step_hours)}；"
        f"本次新计算 {time_step_count_text(processed_count, step_hours)}；"
        f"已有输出复用 {time_step_count_text(skipped_existing_count, step_hours)}；"
        f"可用站点组合 {len(nearest_cache)}；"
        f"无可用站点 {time_step_count_text(no_station_step_count, step_hours)}"
    )
    if skipped_existing_count and processed_count == 0:
        print("提示: 本次没有重新计算已有泰森分配文件；如需刷新结果，请启用覆盖。")
    return written


def main() -> None:
    args = parse_args()
    config = read_config(args.配置)
    meteo = dict(config.get("气象策略", {}))
    mode = str(meteo.get("降水方案", "grid_only")).strip()
    correction_algorithm = configured_station_correction_algorithm(meteo)
    prec_source = args.降水源 or configured_precip_source(config)
    profile = resolve_profile(config, None)
    paths = build_profile_paths(config, profile)
    base_dir, target_dir = base_and_target_dirs(config, prec_source)

    if mode == "grid_only":
        print("当前降水方案为 grid_only，不需要额外处理。")
        return

    station_prec_path = resolve_config_entry_path(config, meteo.get("站点降水_csv", ""))
    station_meta_path = resolve_config_entry_path(config, meteo.get("站点信息_csv", ""))
    if not station_prec_path.exists():
        raise FileNotFoundError(f"站点降水文件不存在：{station_prec_path}")
    if not station_meta_path.exists():
        raise FileNotFoundError(f"站点信息文件不存在：{station_meta_path}")

    station_series, fmt = load_station_precip(station_prec_path)
    station_series.index = pd.to_datetime(station_series.index)
    station_series.columns = [str(col).strip() for col in station_series.columns]
    station_series_raw = station_series.copy()
    model_step_hours = normalize_time_step_hours(config.get("时间步长_小时", 24.0))
    station_series, station_time_aggregation = aggregate_station_precip_for_model_step(
        station_series,
        model_step_hours,
    )

    expected_index = build_expected_forcing_index(config, context="calibration")
    missing_expected_steps: list[pd.Timestamp] = []
    skipped_out_of_scope = 0
    records = list_rasters(base_dir) if base_dir.exists() else []
    all_base_records = list(records)
    use_timestamp_names = False
    if mode == "grid_plus_station_bias":
        if not base_dir.exists():
            raise FileNotFoundError(f"基础降水目录不存在：{base_dir}")
        if not records:
            raise FileNotFoundError(f"基础降水目录没有 tif：{base_dir}")
    elif mode == "thiessen_station_only" and not records:
        template_path = resolve_station_only_template(paths)
        records = records_from_station_times(station_series, template_path)
        use_timestamp_names = True
        if not records:
            raise ValueError("站点降水文件没有可用时间，无法生成逐栅格降水。")
    elif mode != "thiessen_station_only":
        raise ValueError(f"未知降水方案：{mode}")
    records, missing_expected_steps, skipped_out_of_scope = filter_records_to_expected(records, expected_index)
    if not records:
        raise ValueError("降水方案没有落在当前资料口径内的可用时间步，请检查时间设置、事件表或站点降水资料。")
    if missing_expected_steps:
        sample = "、".join(format_time(ts, normalize_time_step_hours(config.get("时间步长_小时", 24.0))) for ts in missing_expected_steps[:5])
        raise ValueError(
            f"降水方案缺少当前资料口径内 {time_step_count_text(len(missing_expected_steps), model_step_hours)}，"
            f"例如：{sample}。"
        )

    with rasterio.open(records[0][1]) as src:
        stations = load_station_metadata(station_meta_path, src.crs)
    available_ids = set(station_series.columns)
    stations = stations[stations["station_id"].isin(available_ids)].copy()
    if stations.empty:
        raise ValueError("站点信息与站点降水之间没有可匹配的站号。")
    day_basis_diagnostics = station_product_day_basis_diagnostics(
        records,
        stations,
        station_series_raw,
        model_step_hours=model_step_hours,
    )
    if mode == "thiessen_station_only":
        no_station_steps = no_available_station_steps(records, stations, station_series)
        if no_station_steps:
            step_hours = normalize_time_step_hours(config.get("时间步长_小时", 24.0))
            sample = "、".join(format_time(ts, step_hours) for ts in no_station_steps[:5])
            raise ValueError(
                f"纯站点泰森分配存在 {len(no_station_steps)} 个无可用站点时间步，例如：{sample}。"
                "请补齐站点资料、改用格点+站点偏差订正，或缩短运行时段。"
            )

    print(f"率定模式: {profile}")
    print(f"降水方案: {mode}")
    if mode == "grid_plus_station_bias":
        print(f"站点订正算法: {correction_algorithm}")
    print(f"降水源: {prec_source}")
    print(f"资料口径: {TIME_BASIS_LABELS.get(task_time_basis(config, context='calibration'), '当前任务时段')}")
    print(f"基础目录: {base_dir}")
    print(f"目标目录: {target_dir}")
    print(f"站点格式: {fmt}")
    if station_time_aggregation.get("enabled"):
        print(
            "站点降水聚合: 小时资料已按水文日 "
            f"{int(station_time_aggregation.get('day_start_hour', HYDROLOGICAL_DAY_START_HOUR)):02d}:00-次日"
            f"{int(station_time_aggregation.get('day_start_hour', HYDROLOGICAL_DAY_START_HOUR)):02d}:00 "
            f"累计为日降水；有效日数 {int(station_time_aggregation.get('valid_days', 0))}"
        )
    print(f"匹配站点数: {len(stations)}")
    print(f"处理时间范围: {record_period_text(records, model_step_hours)}")
    if skipped_out_of_scope:
        print(f"已忽略资料口径外时间步: {skipped_out_of_scope}")
    if use_timestamp_names:
        print(f"站点-only 目标格网模板: {records[0][1]}")

    target_dir.mkdir(parents=True, exist_ok=True)
    transfer_rule_summary: dict[str, Any] | None = None
    transfer_rules: dict[str, Any] | None = None
    processing_stats: dict[str, Any] = {}
    if mode == "grid_plus_station_bias":
        if correction_algorithm == STATION_CORRECTION_ALGORITHM_LEGACY:
            transfer_rule_summary = fit_grid_bias_transfer_rules(
                all_base_records,
                target_dir,
                stations,
                station_series,
                overwrite=args.覆盖,
            )
        else:
            transfer_rule_summary = {
                "schema": TRANSFER_RULES_SCHEMA,
                "available": False,
                "status": "disabled_for_occurrence_amount_v2",
            }
        if transfer_rule_summary.get("available"):
            month_count = sum(
                1
                for item in dict(transfer_rule_summary.get("monthly", {}) or {}).values()
                if int(dict(item).get("training_days", 0) or 0) > 0
            )
            print(
                "订正规则: "
                f"训练日 {int(transfer_rule_summary.get('training_days', 0) or 0)}；"
                f"有效站点样本 {int(transfer_rule_summary.get('valid_station_samples', 0) or 0)}；"
                f"有独立月规则 {month_count}/12；"
                f"平均倍率 {transfer_rule_summary.get('global_ratio_mean', '未形成')}"
            )
            transfer_rules = load_grid_bias_transfer_rules(target_dir)
        else:
            print("订正规则: 未形成可外推规则；无站点时段将保留格点基线。")
        correction_result = apply_grid_bias_correction(
            records,
            target_dir,
            stations,
            station_series,
            args.覆盖,
            transfer_rules,
            return_stats=True,
            algorithm=correction_algorithm,
            step_hours=model_step_hours,
        )
        processing_stats = dict(correction_result) if isinstance(correction_result, dict) else {}
        written = int(processing_stats.get("written_files", correction_result if isinstance(correction_result, int) else 0))
    elif mode == "thiessen_station_only":
        written = apply_thiessen(records, target_dir, stations, station_series, args.覆盖, use_timestamp_names=use_timestamp_names)
        processing_stats = {"method": "thiessen_station_only", "written_files": int(written)}
    if args.覆盖:
        processing_stats["removed_stale_files"] = remove_stale_strategy_rasters(
            target_dir,
            records,
            use_timestamp_names=use_timestamp_names,
        )
    summary = summarize_record_participation(
        config=config,
        mode=mode,
        profile=profile,
        prec_source=prec_source,
        records=records,
        expected_index=expected_index,
        missing_expected_steps=missing_expected_steps,
        skipped_out_of_scope=skipped_out_of_scope,
        stations=stations,
        station_series=station_series,
        station_format=fmt,
        station_time_aggregation=station_time_aggregation,
        base_dir=base_dir,
        target_dir=target_dir,
        written=written,
        use_timestamp_names=use_timestamp_names,
        transfer_rule_summary=transfer_rule_summary,
        processing_stats=processing_stats,
        day_basis_diagnostics=day_basis_diagnostics,
    )
    summary["station_elevation_support"] = station_elevation_support_diagnostics(config, stations)
    summary["provenance"] = {
        "schema": "precipitation_correction_provenance_v1",
        "base_precipitation_series": raster_series_fingerprint(records),
        "corrected_precipitation_series": raster_series_fingerprint(
            records,
            directory=target_dir,
            use_timestamp_names=use_timestamp_names,
        ),
        "station_precipitation_input": sha256_file_identity(station_prec_path),
        "station_metadata_input": sha256_file_identity(station_meta_path),
        "source_daily_forcing_manifest": sha256_file_identity(base_dir.parent / "daily_forcing_manifest.json"),
    }
    summary_path = write_strategy_summary(target_dir, summary)
    print(
        f"完成：{record_period_text(records, model_step_hours)}；"
        f"结果已写入或复用 {target_dir}"
    )
    print(f"降水方案摘要: {summary_path}")


if __name__ == "__main__":
    main()
