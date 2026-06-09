#!/usr/bin/env python
# -*- coding: utf-8 -*-
from __future__ import annotations

import argparse
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


MIN_GRID_PRECIP_MM = 0.05
WET_STATION_MEAN_MM = 0.10
RATIO_CLIP = (0.2, 5.0)
IDW_POWER = 2.0
IDW_MIN_DISTANCE_M = 100.0
IDW_CHUNK_SIZE = 200_000
TIME_BASIS_CONTINUOUS = "continuous"
TIME_BASIS_EVENT_WINDOWS = "event_windows"
TIME_BASIS_FORECAST_WINDOW = "forecast_window"
TIME_BASIS_LABELS = {
    TIME_BASIS_CONTINUOUS: "连续时段",
    TIME_BASIS_EVENT_WINDOWS: "洪水事件窗口",
    TIME_BASIS_FORECAST_WINDOW: "预报窗口",
}


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


def format_time(value: Any, step_hours: float) -> str:
    if value in (None, ""):
        return ""
    ts = pd.to_datetime(value)
    if abs(step_hours - 24.0) < 1e-9 and ts.hour == 0 and ts.minute == 0 and ts.second == 0:
        return ts.strftime("%Y-%m-%d")
    return ts.strftime("%Y-%m-%d %H:%M")


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
    base_dir: Path,
    target_dir: Path,
    written: int,
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
        covered_station_steps = 0
        zero_station_steps = int(len(timestamps))
        max_zero = int(len(timestamps))
        min_available = None
        mean_available = None
        station_missing_rates = []

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

    return {
        "schema": "precipitation_strategy_summary_v1",
        "created_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "profile": profile,
        "mode": mode,
        "precip_source": prec_source,
        "time_basis": time_basis,
        "time_basis_label": time_basis_label,
        "expected_steps": expected_steps,
        "selected_steps": int(len(records)),
        "written_files": int(written),
        "missing_expected_steps": int(len(missing_expected_steps)),
        "missing_expected_samples": [format_time(ts, step_hours) for ts in missing_expected_steps[:10]],
        "skipped_out_of_scope_steps": int(skipped_out_of_scope),
        "actual_start": format_time(timestamps[0], step_hours) if len(timestamps) else "",
        "actual_end": format_time(timestamps[-1], step_hours) if len(timestamps) else "",
        "station_format": station_format,
        "matched_station_count": int(len(station_ids)),
        "covered_station_steps": int(covered_station_steps),
        "zero_available_station_steps": int(zero_station_steps),
        "max_consecutive_zero_station_steps": int(max_zero),
        "min_available_station_count": min_available,
        "mean_available_station_count": mean_available,
        "station_missing_rates": station_missing_rates,
        "event_coverage": event_coverage,
        "base_dir": str(base_dir.resolve(strict=False)),
        "target_dir": str(target_dir.resolve(strict=False)),
    }


def write_strategy_summary(target_dir: Path, summary: dict[str, Any]) -> Path:
    path = target_dir / "precipitation_strategy_summary.json"
    path.write_text(json.dumps(summary, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    return path


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
            obs = station_values_for_time(station_series, pd.Timestamp(ts), station_ids)
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
    station_ids = stations["station_id"].tolist()
    nearest_cache: dict[tuple[int, ...], np.ndarray] = {}
    valid_mask: np.ndarray | None = None
    no_station_step_count = 0
    for ts, path in records:
        output = target_dir / (raster_name_from_timestamp(ts) if use_timestamp_names else path.name)
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

    expected_index = build_expected_forcing_index(config, context="calibration")
    missing_expected_steps: list[pd.Timestamp] = []
    skipped_out_of_scope = 0
    records = list_rasters(base_dir) if base_dir.exists() else []
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
        raise ValueError(f"降水方案缺少当前资料口径内 {len(missing_expected_steps)} 个时间步，例如：{sample}。")

    with rasterio.open(records[0][1]) as src:
        stations = load_station_metadata(station_meta_path, src.crs)
    available_ids = set(station_series.columns)
    stations = stations[stations["station_id"].isin(available_ids)].copy()
    if stations.empty:
        raise ValueError("站点信息与站点降水之间没有可匹配的站号。")
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
    print(f"降水源: {prec_source}")
    print(f"资料口径: {TIME_BASIS_LABELS.get(task_time_basis(config, context='calibration'), '当前任务时段')}")
    print(f"基础目录: {base_dir}")
    print(f"目标目录: {target_dir}")
    print(f"站点格式: {fmt}")
    print(f"匹配站点数: {len(stations)}")
    print(f"时间步文件数: {len(records)}")
    if skipped_out_of_scope:
        print(f"已忽略资料口径外时间步: {skipped_out_of_scope}")
    if use_timestamp_names:
        print(f"站点-only 目标格网模板: {records[0][1]}")

    target_dir.mkdir(parents=True, exist_ok=True)
    if mode == "grid_plus_station_bias":
        written = apply_grid_bias_correction(records, target_dir, stations, station_series, args.覆盖)
    elif mode == "thiessen_station_only":
        written = apply_thiessen(records, target_dir, stations, station_series, args.覆盖, use_timestamp_names=use_timestamp_names)
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
        base_dir=base_dir,
        target_dir=target_dir,
        written=written,
    )
    summary_path = write_strategy_summary(target_dir, summary)
    print(f"完成：{written} 个文件写入 {target_dir}")
    print(f"降水方案摘要: {summary_path}")


if __name__ == "__main__":
    main()
