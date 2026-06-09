from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

import numpy as np
import pandas as pd

from services.event_config import TIME_BASIS_EVENT_WINDOWS, TIME_BASIS_FORECAST_WINDOW, TIME_BASIS_LABELS, event_date_range
from services.meteo_config import METEO_KEY, METEO_PRECIP_MODE_KEY, METEO_STATION_META_KEY, METEO_STATION_PREC_KEY


@dataclass(frozen=True)
class StationPrecipAnalysisContext:
    resolve_config_related_path: Callable[[dict[str, Any], Any], Path | None]
    normalize_time_step_hours: Callable[[Any], float]
    task_time_basis: Callable[..., str]
    normalized_flood_events: Callable[..., dict[str, Any]]
    build_expected_forcing_index: Callable[..., pd.DatetimeIndex | None]


@dataclass(frozen=True)
class StationPrecipStrategyStatusContext:
    normalize_time_step_hours: Callable[[Any], float]
    analyze_station_precip_inputs: Callable[..., dict[str, Any]]


def check_station_precip_strategy_status(
    config: dict[str, Any],
    context: StationPrecipStrategyStatusContext,
) -> tuple[bool, str, int]:
    analysis = context.analyze_station_precip_inputs(
        config,
        step_hours=context.normalize_time_step_hours(config.get("时间步长_小时", 24.0)),
    )
    if not analysis.get("enabled"):
        return True, str(analysis.get("summary", "当前为格点基线模式，未启用站点订正。")), 0
    status = str(analysis.get("status", "fail"))
    matched = int(analysis.get("matched_station_count", 0) or 0)
    warnings = list(analysis.get("warnings", []) or [])
    message = str(analysis.get("summary", "站点降水资料已检查。"))
    if matched:
        message += f" 站点匹配：{matched} 个。"
    if warnings:
        message += " " + "；".join(str(item) for item in warnings[:2])
    return status != "fail", message, matched


def detect_table_column(columns: list[str], candidates: list[str]) -> str | None:
    lowered = {str(col).strip().lower(): str(col) for col in columns}
    for candidate in candidates:
        found = lowered.get(candidate.lower())
        if found is not None:
            return found
    return None


def detect_table_time_column(frame: pd.DataFrame) -> str | None:
    time_names = {"time", "datetime", "date", "\u65f6\u95f4", "\u65e5\u671f"}
    for column in frame.columns:
        if str(column).strip().lower() in time_names:
            parsed = pd.to_datetime(frame[column], errors="coerce")
            if int(parsed.notna().sum()) >= max(1, len(frame) // 3):
                return str(column)
    for column in frame.columns:
        if pd.api.types.is_numeric_dtype(frame[column]):
            continue
        parsed = pd.to_datetime(frame[column], errors="coerce")
        if int(parsed.notna().sum()) >= max(1, len(frame) // 3):
            return str(column)
    return None


def read_station_csv(path: Path) -> pd.DataFrame:
    last_error: Exception | None = None
    for encoding in ("utf-8-sig", "utf-8", "gbk"):
        try:
            return pd.read_csv(path, encoding=encoding)
        except UnicodeDecodeError as exc:
            last_error = exc
    if last_error is not None:
        raise last_error
    return pd.read_csv(path)


def load_station_precip_table(path: Path) -> tuple[pd.DataFrame, str, str | None]:
    frame = read_station_csv(path)
    if frame.empty:
        raise ValueError("\u7ad9\u70b9\u964d\u6c34 csv \u4e3a\u7a7a\u3002")
    time_col = detect_table_time_column(frame)
    if not time_col:
        raise ValueError("\u7ad9\u70b9\u964d\u6c34 csv \u672a\u8bc6\u522b\u5230\u65f6\u95f4\u5217\u3002")

    columns = [str(col) for col in frame.columns]
    id_col = detect_table_column(columns, ["station_id", "station", "id", "name", "\u7ad9\u70b9", "\u7ad9\u53f7"])
    value_col = detect_table_column(columns, ["precip", "prec", "ppt", "rain", "value", "\u964d\u6c34", "\u964d\u6c34\u91cf"])
    if id_col and value_col and id_col != time_col and value_col != time_col:
        data = frame[[time_col, id_col, value_col]].copy()
        data.columns = ["time", "station_id", "value"]
        data["time"] = pd.to_datetime(data["time"], errors="coerce")
        data["station_id"] = data["station_id"].astype(str).str.strip()
        data["value"] = pd.to_numeric(data["value"], errors="coerce")
        wide = data.pivot_table(index="time", columns="station_id", values="value", aggfunc="mean")
        wide.columns = [str(col).strip() for col in wide.columns]
        return wide.sort_index(), "\u957f\u8868", time_col

    wide = frame.copy()
    wide[time_col] = pd.to_datetime(wide[time_col], errors="coerce")
    wide = wide.dropna(subset=[time_col]).set_index(time_col).sort_index()
    wide.columns = [str(col).strip() for col in wide.columns]
    for column in list(wide.columns):
        wide[column] = pd.to_numeric(wide[column], errors="coerce")
    if wide.index.has_duplicates:
        wide = wide.groupby(level=0).mean(numeric_only=True).sort_index()
    return wide, "\u5bbd\u8868", time_col


def load_station_metadata_table(path: Path) -> tuple[pd.DataFrame, dict[str, str | None]]:
    frame = read_station_csv(path)
    if frame.empty:
        raise ValueError("\u7ad9\u70b9\u4fe1\u606f csv \u4e3a\u7a7a\u3002")
    columns = [str(col) for col in frame.columns]
    id_col = detect_table_column(columns, ["station_id", "station", "id", "name", "\u7ad9\u70b9", "\u7ad9\u53f7"])
    lon_col = detect_table_column(columns, ["lon", "longitude", "x", "\u7ecf\u5ea6"])
    lat_col = detect_table_column(columns, ["lat", "latitude", "y", "\u7eac\u5ea6"])
    if not id_col:
        raise ValueError("\u7ad9\u70b9\u4fe1\u606f csv \u672a\u8bc6\u522b\u5230\u7ad9\u53f7\u5b57\u6bb5\u3002")
    out = frame.copy()
    out["_station_id"] = out[id_col].astype(str).str.strip()
    return out, {"id": id_col, "lon": lon_col, "lat": lat_col}


def format_time_for_check(value: Any, step_hours: float) -> str:
    if value in (None, ""):
        return ""
    try:
        ts = pd.to_datetime(value)
    except Exception:
        return "\u672a\u8bc6\u522b"
    if pd.isna(ts):
        return ""
    if abs(float(step_hours) - 24.0) < 1e-9 and ts.hour == 0 and ts.minute == 0 and ts.second == 0:
        return ts.strftime("%Y-%m-%d")
    return ts.strftime("%Y-%m-%d %H:%M")


def station_precip_mode_label(mode: str) -> str:
    return {
        "grid_plus_station_bias": "\u683c\u70b9 + \u7ad9\u70b9\u504f\u5dee\u8ba2\u6b63",
        "thiessen_station_only": "\u7eaf\u7ad9\u70b9\u6cf0\u68ee\u5206\u914d",
    }.get(str(mode or "").strip(), "\u7ad9\u70b9\u964d\u6c34\u65b9\u6848")


def index_display_range(index: pd.DatetimeIndex | None, step_hours: float) -> tuple[str, str, int]:
    if index is None or len(index) <= 0:
        return "", "", 0
    return (
        format_time_for_check(index[0], step_hours),
        format_time_for_check(index[-1], step_hours),
        int(len(index)),
    )


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


def station_count_text(min_count: int | None, mean_count: float | None) -> str:
    if min_count is None:
        return "\u672a\u5f62\u6210"
    if mean_count is None:
        return str(int(min_count))
    return f"\u6700\u5c11 {int(min_count)}\uff0c\u5e73\u5747 {mean_count:.1f}"


def station_precip_id_match_summary(
    station_series: pd.DataFrame,
    station_meta: pd.DataFrame,
    meta_columns: dict[str, str | None],
) -> dict[str, Any]:
    precip_ids = [str(col).strip() for col in station_series.columns if str(col).strip()]
    meta_values = station_meta["_station_id"].tolist() if "_station_id" in station_meta.columns else []
    meta_ids = [str(item).strip() for item in meta_values if str(item).strip()]
    valid_meta_ids = meta_ids
    invalid_coord_ids: list[str] = []
    lon_col = meta_columns.get("lon")
    lat_col = meta_columns.get("lat")
    if lon_col and lat_col and lon_col in station_meta.columns and lat_col in station_meta.columns:
        lon_values = pd.to_numeric(station_meta[lon_col], errors="coerce")
        lat_values = pd.to_numeric(station_meta[lat_col], errors="coerce")
        valid_mask = lon_values.notna() & lat_values.notna()
        valid_meta_ids = [
            str(item).strip()
            for item in station_meta.loc[valid_mask, "_station_id"].tolist()
            if str(item).strip()
        ]
        invalid_coord_ids = [
            str(item).strip()
            for item in station_meta.loc[~valid_mask, "_station_id"].tolist()
            if str(item).strip()
        ]
    precip_id_set = set(precip_ids)
    meta_id_set = set(meta_ids)
    valid_meta_id_set = set(valid_meta_ids)
    matched_ids = sorted(precip_id_set & valid_meta_id_set)
    missing_in_precip = sorted(valid_meta_id_set - precip_id_set)
    missing_in_meta = sorted(precip_id_set - valid_meta_id_set)

    missing: list[str] = []
    warnings: list[str] = []
    if not matched_ids:
        missing.append("\u7ad9\u70b9\u4fe1\u606f\u4e0e\u7ad9\u70b9\u964d\u6c34\u4e4b\u95f4\u6ca1\u6709\u53ef\u5339\u914d\u7684\u7ad9\u53f7\u3002")
    elif missing_in_precip:
        warnings.append(f"{len(missing_in_precip)} \u4e2a\u7ad9\u70b9\u5728\u7ad9\u70b9\u4fe1\u606f\u4e2d\u5b58\u5728\uff0c\u4f46\u7ad9\u70b9\u964d\u6c34\u8868\u6ca1\u6709\u5bf9\u5e94\u5217\u3002")
    if missing_in_meta:
        warnings.append(f"{len(missing_in_meta)} \u4e2a\u7ad9\u70b9\u964d\u6c34\u5217\u6ca1\u6709\u5bf9\u5e94\u7ad9\u70b9\u4fe1\u606f\u3002")
    if invalid_coord_ids:
        sample = "\u3001".join(invalid_coord_ids[:5])
        warnings.append(f"{len(invalid_coord_ids)} \u4e2a\u7ad9\u70b9\u4fe1\u606f\u7f3a\u5c11\u6709\u6548\u7ecf\u7eac\u5ea6\uff0c\u4e0d\u4f1a\u53c2\u4e0e\u8fd0\u884c\uff0c\u4f8b\u5982\uff1a{sample}\u3002")
    if not meta_columns.get("lon") or not meta_columns.get("lat"):
        warnings.append("\u7ad9\u70b9\u4fe1\u606f\u672a\u8bc6\u522b\u5230\u7ecf\u7eac\u5ea6\u6216\u5750\u6807\u5b57\u6bb5\uff0c\u6267\u884c\u964d\u6c34\u65b9\u6848\u65f6\u4f1a\u5931\u8d25\u3002")

    return {
        "precip_ids": precip_ids,
        "meta_ids": meta_ids,
        "valid_meta_ids": valid_meta_ids,
        "invalid_coordinate_ids": invalid_coord_ids,
        "matched_ids": matched_ids,
        "missing_in_precip": missing_in_precip,
        "missing_in_meta": missing_in_meta,
        "precip_station_count": int(len(precip_id_set)),
        "station_count": int(len(valid_meta_id_set)),
        "metadata_station_count": int(len(meta_id_set)),
        "missing": missing,
        "warnings": warnings,
    }


def station_precip_expected_coverage(
    matched_series: pd.DataFrame,
    expected_index: pd.DatetimeIndex | None,
    *,
    mode: str,
    time_basis_label: str,
) -> dict[str, Any]:
    expected_count = 0
    covered_count = 0
    coverage_ratio: float | None = None
    zero_available_steps = 0
    max_consecutive_zero_steps = 0
    min_available_station_count: int | None = None
    mean_available_station_count: float | None = None
    quality_series = matched_series
    missing: list[str] = []
    warnings: list[str] = []
    if expected_index is not None and len(expected_index) > 0:
        expected_count = int(len(expected_index))
        if expected_count > 0 and not matched_series.empty:
            present = matched_series.reindex(expected_index)
            quality_series = present
            available_counts = ((present.notna()) & (present >= 0.0)).sum(axis=1)
            covered_count = int((available_counts > 0).sum())
            coverage_ratio = covered_count / expected_count
            zero_flags = available_counts == 0
            zero_available_steps = int(zero_flags.sum())
            max_consecutive_zero_steps = max_consecutive_true(zero_flags.tolist())
            min_available_station_count = int(available_counts.min()) if not available_counts.empty else None
            mean_available_station_count = float(available_counts.mean()) if not available_counts.empty else None
            if covered_count == 0:
                missing.append(f"\u7ad9\u70b9\u964d\u6c34\u65f6\u95f4\u8303\u56f4\u4e0e{time_basis_label}\u5b8c\u5168\u4e0d\u91cd\u53e0\u3002")
            elif coverage_ratio < 0.99:
                message = f"\u7ad9\u70b9\u964d\u6c34\u5728{time_basis_label}\u5185\u8986\u76d6\u4e0d\u8db3\uff1a\u8986\u76d6 {coverage_ratio * 100:.1f}%\u3002"
                if mode == "thiessen_station_only":
                    missing.append(message)
                else:
                    warnings.append(message)
    return {
        "expected_count": expected_count,
        "covered_count": covered_count,
        "coverage_ratio": coverage_ratio,
        "zero_available_steps": zero_available_steps,
        "max_consecutive_zero_steps": max_consecutive_zero_steps,
        "min_available_station_count": min_available_station_count,
        "mean_available_station_count": mean_available_station_count,
        "quality_series": quality_series,
        "missing": missing,
        "warnings": warnings,
    }


def station_precip_event_coverage_summary(
    matched_series: pd.DataFrame,
    event_info: dict[str, Any] | None,
    *,
    step_hours: float,
    mode: str,
) -> dict[str, Any]:
    event_coverage: list[dict[str, Any]] = []
    missing: list[str] = []
    warnings: list[str] = []
    if not event_info:
        return {"event_coverage": event_coverage, "missing": missing, "warnings": warnings}

    for event in event_info.get("valid_events", []):
        event_index = event_date_range(pd.Timestamp(event["run_start"]), pd.Timestamp(event["run_end"]), step_hours)
        if len(event_index) <= 0 or matched_series.empty:
            covered_event = 0
            zero_event = int(len(event_index))
            event_available_min = None if len(event_index) <= 0 else 0
            event_available_mean = None if len(event_index) <= 0 else 0.0
            event_max_zero = int(len(event_index))
        else:
            event_present = matched_series.reindex(event_index)
            event_available_counts = ((event_present.notna()) & (event_present >= 0.0)).sum(axis=1)
            event_zero_flags = event_available_counts == 0
            covered_event = int((event_available_counts > 0).sum())
            zero_event = int(event_zero_flags.sum())
            event_available_min = int(event_available_counts.min()) if not event_available_counts.empty else None
            event_available_mean = float(event_available_counts.mean()) if not event_available_counts.empty else None
            event_max_zero = max_consecutive_true(event_zero_flags.tolist())
        event_steps = int(len(event_index))
        event_ratio = covered_event / event_steps if event_steps else None
        if event_ratio is not None and event_ratio >= 0.99 and zero_event == 0:
            event_status = "ok"
        elif mode == "thiessen_station_only" and zero_event > 0:
            event_status = "fail"
        elif covered_event == 0:
            event_status = "fail"
        else:
            event_status = "warn"
        event_coverage.append(
            {
                "event_id": event.get("event_id"),
                "name": event.get("name"),
                "purpose": event.get("purpose"),
                "run_start": format_time_for_check(event.get("run_start"), step_hours),
                "run_end": format_time_for_check(event.get("run_end"), step_hours),
                "expected_steps": event_steps,
                "covered_steps": covered_event,
                "coverage_ratio": event_ratio,
                "missing_ratio": (1.0 - event_ratio) if event_ratio is not None else None,
                "zero_available_steps": zero_event,
                "max_consecutive_zero_steps": event_max_zero,
                "available_station_min": event_available_min,
                "available_station_mean": event_available_mean,
                "status": event_status,
            }
        )

    uncovered_events = [item for item in event_coverage if int(item.get("zero_available_steps", 0) or 0) > 0]
    if uncovered_events:
        sample = "\u3001".join(str(item.get("event_id") or item.get("name")) for item in uncovered_events[:3])
        message = f"\u6709 {len(uncovered_events)} \u573a\u4e8b\u4ef6\u8fd0\u884c\u7a97\u53e3\u5185\u5b58\u5728\u65e0\u53ef\u7528\u7ad9\u70b9\u65f6\u95f4\u6b65\uff0c\u4f8b\u5982\uff1a{sample}\u3002"
        if mode == "thiessen_station_only":
            missing.append(message)
        else:
            warnings.append(message)

    return {"event_coverage": event_coverage, "missing": missing, "warnings": warnings}


def station_precip_quality_summary(
    quality_series: pd.DataFrame,
    matched_ids: list[str],
    *,
    step_hours: float,
) -> dict[str, Any]:
    numeric_values = quality_series.to_numpy(dtype="float64") if not quality_series.empty else np.empty((0, 0), dtype="float64")
    negative_count = int(np.sum(numeric_values < 0)) if numeric_values.size else 0
    extreme_threshold = 80.0 if abs(float(step_hours) - 1.0) < 1e-9 else 300.0
    extreme_count = int(np.sum(numeric_values > extreme_threshold)) if numeric_values.size else 0
    all_zero_count = 0
    max_missing_rate = 0.0
    station_missing_rates: list[dict[str, Any]] = []
    if matched_ids:
        for col in matched_ids:
            values = quality_series[col].dropna().to_numpy(dtype="float64") if col in quality_series.columns else np.array([], dtype="float64")
            if values.size and bool(np.nanmax(np.abs(values)) <= 1e-9):
                all_zero_count += 1
        missing_rates = quality_series[matched_ids].isna().mean(axis=0) if not quality_series.empty else pd.Series(dtype="float64")
        max_missing_rate = float(missing_rates.max()) if not missing_rates.empty else 0.0
        station_missing_rates = [
            {"station_id": str(station_id), "missing_rate": float(rate)}
            for station_id, rate in missing_rates.sort_values(ascending=False).head(20).items()
        ]

    warnings: list[str] = []
    if negative_count > 0:
        warnings.append(f"\u7ad9\u70b9\u964d\u6c34\u5b58\u5728 {negative_count} \u6761\u8d1f\u503c\u8bb0\u5f55\u3002")
    if extreme_count > 0:
        unit_label = "\u5c0f\u65f6" if abs(float(step_hours) - 1.0) < 1e-9 else "\u65e5"
        warnings.append(f"\u7ad9\u70b9\u964d\u6c34\u5b58\u5728 {extreme_count} \u6761\u8d85\u8fc7 {extreme_threshold:g} mm/{unit_label} \u7684\u5f02\u5e38\u5927\u503c\u3002")
    if all_zero_count > 0:
        warnings.append(f"{all_zero_count} \u4e2a\u5339\u914d\u7ad9\u70b9\u5728\u5f53\u524d\u8d44\u6599\u4e2d\u4e3a\u5168\u96f6\u5e8f\u5217\u3002")
    if max_missing_rate > 0.20:
        warnings.append(f"\u5355\u7ad9\u6700\u5927\u7f3a\u6d4b\u7387\u4e3a {max_missing_rate * 100:.1f}%\uff0c\u5efa\u8bae\u6838\u5bf9\u8d44\u6599\u5b8c\u6574\u6027\u3002")

    return {
        "negative_count": negative_count,
        "extreme_threshold": extreme_threshold,
        "extreme_count": extreme_count,
        "all_zero_count": all_zero_count,
        "max_missing_rate": max_missing_rate,
        "station_missing_rates": station_missing_rates,
        "warnings": warnings,
    }


def station_precip_analysis_status(missing: list[Any], warnings: list[Any]) -> dict[str, str]:
    if missing:
        return {
            "status": "fail",
            "summary": "\u7ad9\u70b9\u964d\u6c34\u65b9\u6848\u4ecd\u6709\u5173\u952e\u95ee\u9898\uff0c\u65e0\u6cd5\u4f5c\u4e3a\u7387\u5b9a\u8f93\u5165\u3002",
        }
    if warnings:
        return {
            "status": "warn",
            "summary": "\u7ad9\u70b9\u964d\u6c34\u8d44\u6599\u53ef\u4ee5\u7ee7\u7eed\u5904\u7406\uff0c\u4f46\u5b58\u5728\u7f3a\u6d4b\u3001\u5f02\u5e38\u503c\u6216\u7ad9\u53f7\u5339\u914d\u98ce\u9669\u3002",
        }
    return {
        "status": "ok",
        "summary": "\u7ad9\u70b9\u964d\u6c34\u8d44\u6599\u5339\u914d\u548c\u65f6\u95f4\u8986\u76d6\u57fa\u672c\u5408\u7406\uff0c\u53ef\u7528\u4e8e\u964d\u6c34\u8ba2\u6b63\u6216\u6cf0\u68ee\u5206\u914d\u3002",
    }


def station_precip_analysis_items(
    *,
    mode: str,
    task_context: dict[str, Any],
    time_basis_label: str,
    matched_station_count: int,
    station_count: int,
    missing_in_precip: list[Any],
    missing_in_meta: list[Any],
    station_format: str,
    station_start: Any,
    station_end: Any,
    step_hours: float,
    coverage_ratio: float | None,
    covered_count: int,
    zero_available_steps: int,
    max_consecutive_zero_steps: int,
    min_available_station_count: int | None,
    mean_available_station_count: float | None,
    max_missing_rate: float,
    negative_count: int,
    extreme_count: int,
    event_coverage: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    items = [
        {"label": "\u964d\u6c34\u65b9\u6848", "value": "\u683c\u70b9+\u7ad9\u70b9\u504f\u5dee\u8ba2\u6b63" if mode == "grid_plus_station_bias" else "\u7ad9\u70b9\u6cf0\u68ee\u5206\u914d", "status": "ok"},
        {"label": "\u68c0\u67e5\u53e3\u5f84", "value": task_context["headline"], "status": str(task_context.get("status", "warn"))},
        {"label": "\u8d44\u6599\u53e3\u5f84", "value": time_basis_label, "status": "ok"},
        {"label": "\u7ad9\u53f7\u5339\u914d", "value": f"{matched_station_count}/{station_count}", "status": "ok" if matched_station_count and not missing_in_precip else "warn" if matched_station_count else "fail"},
        {"label": "\u964d\u6c34\u8868\u989d\u5916\u7ad9\u53f7", "value": str(len(missing_in_meta)), "status": "ok" if not missing_in_meta else "warn"},
        {"label": "\u8d44\u6599\u683c\u5f0f", "value": station_format, "status": "ok"},
        {"label": "\u65f6\u95f4\u8303\u56f4", "value": f"{format_time_for_check(station_start, step_hours)} \u81f3 {format_time_for_check(station_end, step_hours)}", "status": "ok" if coverage_ratio is None or coverage_ratio >= 0.99 else "warn" if covered_count > 0 else "fail"},
        {"label": f"{time_basis_label}\u8986\u76d6", "value": f"{coverage_ratio * 100:.1f}%" if coverage_ratio is not None else "\u672a\u914d\u7f6e\u5b8c\u6574\u65f6\u6bb5", "status": "ok" if coverage_ratio is None or coverage_ratio >= 0.99 else "warn" if covered_count > 0 else "fail"},
        {"label": "\u65e0\u53ef\u7528\u7ad9\u70b9\u65f6\u95f4\u6b65", "value": str(zero_available_steps), "status": "ok" if zero_available_steps == 0 else "fail" if mode == "thiessen_station_only" else "warn"},
        {"label": "\u6700\u5927\u8fde\u7eed\u65e0\u7ad9\u70b9", "value": f"{max_consecutive_zero_steps} \u6b65", "status": "ok" if max_consecutive_zero_steps == 0 else "fail" if mode == "thiessen_station_only" else "warn"},
        {"label": "\u53ef\u7528\u7ad9\u70b9\u6570", "value": station_count_text(min_available_station_count, mean_available_station_count), "status": "ok" if min_available_station_count and min_available_station_count > 0 else "fail" if mode == "thiessen_station_only" else "warn"},
        {"label": "\u5355\u7ad9\u6700\u5927\u7f3a\u6d4b\u7387", "value": f"{max_missing_rate * 100:.1f}%", "status": "warn" if max_missing_rate > 0.20 else "ok"},
        {"label": "\u8d1f\u964d\u6c34\u8bb0\u5f55", "value": str(negative_count), "status": "ok" if negative_count == 0 else "warn"},
        {"label": "\u5f02\u5e38\u5927\u503c\u8bb0\u5f55", "value": str(extreme_count), "status": "ok" if extreme_count == 0 else "warn"},
    ]
    for event_item in event_coverage[:5]:
        ratio = event_item.get("coverage_ratio")
        station_text = station_count_text(
            event_item.get("available_station_min"),
            event_item.get("available_station_mean"),
        )
        value = f"{float(ratio) * 100:.1f}% / {station_text} / \u8fde\u7eed\u65e0\u7ad9\u70b9 {int(event_item.get('max_consecutive_zero_steps', 0) or 0)} \u6b65" if ratio is not None else "\u672a\u8986\u76d6"
        items.append(
            {
                "label": f"\u4e8b\u4ef6 {event_item.get('event_id')}",
                "value": value,
                "status": str(event_item.get("status", "warn")),
            }
        )
    return items


def analyze_station_precip_inputs(
    config: dict[str, Any],
    analysis_context: StationPrecipAnalysisContext,
    *,
    step_hours: float | None = None,
    context: str = "calibration",
) -> dict[str, Any]:
    meteo = dict(config.get(METEO_KEY, {}) or {})
    mode = str(meteo.get(METEO_PRECIP_MODE_KEY, "grid_only")).strip() or "grid_only"
    if mode == "grid_only":
        return {
            "enabled": False,
            "mode": mode,
            "status": "ok",
            "summary": "\u5f53\u524d\u4e3a\u683c\u70b9\u57fa\u7ebf\u6a21\u5f0f\uff0c\u672a\u542f\u7528\u7ad9\u70b9\u964d\u6c34\u8ba2\u6b63\u6216\u6cf0\u68ee\u5206\u914d\u3002",
            "items": [],
            "warnings": [],
            "missing": [],
            "matched_station_count": 0,
        }

    step = float(step_hours if step_hours is not None else analysis_context.normalize_time_step_hours(config.get("\u65f6\u95f4\u6b65\u957f_\u5c0f\u65f6", 24.0)))
    runtime_context = str(context or "calibration").strip().lower() or "calibration"
    time_basis = analysis_context.task_time_basis(config, context=runtime_context)
    time_basis_label = TIME_BASIS_LABELS.get(time_basis, "\u5f53\u524d\u4efb\u52a1\u65f6\u6bb5")
    event_info = analysis_context.normalized_flood_events(config, step_hours=step) if time_basis == TIME_BASIS_EVENT_WINDOWS else None
    expected_index = analysis_context.build_expected_forcing_index(config, context=runtime_context)
    station_prec_raw = str(meteo.get(METEO_STATION_PREC_KEY, "") or "").strip()
    station_meta_raw = str(meteo.get(METEO_STATION_META_KEY, "") or "").strip()
    station_prec_path = analysis_context.resolve_config_related_path(config, station_prec_raw)
    station_meta_path = analysis_context.resolve_config_related_path(config, station_meta_raw)
    missing: list[str] = []
    warnings: list[str] = []

    if not station_prec_raw:
        missing.append("\u964d\u6c34\u65b9\u6848\u9700\u8981 \u7ad9\u70b9\u964d\u6c34_csv\u3002")
    elif station_prec_path is None or not station_prec_path.exists():
        missing.append(f"\u7ad9\u70b9\u964d\u6c34\u6587\u4ef6\u4e0d\u5b58\u5728\uff1a{station_prec_raw}")
    if not station_meta_raw:
        missing.append("\u964d\u6c34\u65b9\u6848\u9700\u8981 \u7ad9\u70b9\u4fe1\u606f_csv\u3002")
    elif station_meta_path is None or not station_meta_path.exists():
        missing.append(f"\u7ad9\u70b9\u4fe1\u606f\u6587\u4ef6\u4e0d\u5b58\u5728\uff1a{station_meta_raw}")
    if missing:
        return {
            "enabled": True,
            "mode": mode,
            "status": "fail",
            "summary": "\u7ad9\u70b9\u964d\u6c34\u65b9\u6848\u7f3a\u5c11\u5fc5\u8981\u8f93\u5165\u6587\u4ef6\u3002",
            "items": [
                {"label": "\u7ad9\u70b9\u964d\u6c34\u6587\u4ef6", "value": "\u5df2\u63d0\u4f9b" if station_prec_path is not None and station_prec_path.exists() else "\u7f3a\u5931", "status": "ok" if station_prec_path is not None and station_prec_path.exists() else "fail"},
                {"label": "\u7ad9\u70b9\u4fe1\u606f\u6587\u4ef6", "value": "\u5df2\u63d0\u4f9b" if station_meta_path is not None and station_meta_path.exists() else "\u7f3a\u5931", "status": "ok" if station_meta_path is not None and station_meta_path.exists() else "fail"},
            ],
            "warnings": warnings,
            "missing": missing,
            "matched_station_count": 0,
            "time_basis": time_basis,
            "time_basis_label": time_basis_label,
            "task_context": station_precip_task_context_summary(
                mode=mode,
                context=runtime_context,
                time_basis=time_basis,
                time_basis_label=time_basis_label,
                step_hours=step,
                expected_index=expected_index,
                expected_count=int(len(expected_index)) if expected_index is not None else 0,
                covered_count=0,
                coverage_ratio=None,
                zero_available_steps=0,
                event_info=event_info,
                event_coverage=[],
            ),
        }

    assert station_prec_path is not None and station_meta_path is not None
    try:
        station_series, station_format, _ = load_station_precip_table(station_prec_path)
        station_meta, meta_columns = load_station_metadata_table(station_meta_path)
    except Exception as exc:
        return {
            "enabled": True,
            "mode": mode,
            "status": "fail",
            "summary": f"\u7ad9\u70b9\u964d\u6c34\u8d44\u6599\u8bfb\u53d6\u5931\u8d25\uff1a{exc}",
            "items": [{"label": "\u8bfb\u53d6\u72b6\u6001", "value": str(exc), "status": "fail"}],
            "warnings": warnings,
            "missing": [f"\u7ad9\u70b9\u964d\u6c34\u8d44\u6599\u8bfb\u53d6\u5931\u8d25\uff1a{exc}"],
            "matched_station_count": 0,
            "time_basis": time_basis,
            "time_basis_label": time_basis_label,
            "task_context": station_precip_task_context_summary(
                mode=mode,
                context=runtime_context,
                time_basis=time_basis,
                time_basis_label=time_basis_label,
                step_hours=step,
                expected_index=expected_index,
                expected_count=int(len(expected_index)) if expected_index is not None else 0,
                covered_count=0,
                coverage_ratio=None,
                zero_available_steps=0,
                event_info=event_info,
                event_coverage=[],
            ),
        }

    station_series = station_series.loc[station_series.index.notna()].copy()
    station_series = station_series[~station_series.index.duplicated(keep="first")].sort_index()
    match_info = station_precip_id_match_summary(station_series, station_meta, meta_columns)
    matched_ids = list(match_info["matched_ids"])
    missing_in_precip = list(match_info["missing_in_precip"])
    missing_in_meta = list(match_info["missing_in_meta"])
    station_count = int(match_info["station_count"])
    precip_station_count = int(match_info["precip_station_count"])
    missing.extend(match_info["missing"])
    warnings.extend(match_info["warnings"])

    matched_series = station_series[matched_ids].copy() if matched_ids else pd.DataFrame(index=station_series.index)
    coverage_info = station_precip_expected_coverage(
        matched_series,
        expected_index,
        mode=mode,
        time_basis_label=time_basis_label,
    )
    expected_count = int(coverage_info["expected_count"])
    covered_count = int(coverage_info["covered_count"])
    coverage_ratio = coverage_info["coverage_ratio"]
    zero_available_steps = int(coverage_info["zero_available_steps"])
    max_consecutive_zero_steps = int(coverage_info["max_consecutive_zero_steps"])
    min_available_station_count = coverage_info["min_available_station_count"]
    mean_available_station_count = coverage_info["mean_available_station_count"]
    quality_series = coverage_info["quality_series"]
    missing.extend(coverage_info["missing"])
    warnings.extend(coverage_info["warnings"])

    event_info_summary = station_precip_event_coverage_summary(
        matched_series,
        event_info,
        step_hours=step,
        mode=mode,
    )
    event_coverage = list(event_info_summary["event_coverage"])
    missing.extend(event_info_summary["missing"])
    warnings.extend(event_info_summary["warnings"])

    quality_info = station_precip_quality_summary(quality_series, matched_ids, step_hours=step)
    negative_count = int(quality_info["negative_count"])
    extreme_count = int(quality_info["extreme_count"])
    max_missing_rate = float(quality_info["max_missing_rate"])
    station_missing_rates = list(quality_info["station_missing_rates"])
    warnings.extend(quality_info["warnings"])

    status_info = station_precip_analysis_status(missing, warnings)
    status = status_info["status"]
    summary = status_info["summary"]

    station_start = station_series.index.min() if len(station_series.index) else None
    station_end = station_series.index.max() if len(station_series.index) else None
    task_context = station_precip_task_context_summary(
        mode=mode,
        context=runtime_context,
        time_basis=time_basis,
        time_basis_label=time_basis_label,
        step_hours=step,
        expected_index=expected_index,
        expected_count=expected_count,
        covered_count=covered_count,
        coverage_ratio=coverage_ratio,
        zero_available_steps=zero_available_steps,
        max_consecutive_zero_steps=max_consecutive_zero_steps,
        min_available_station_count=min_available_station_count,
        mean_available_station_count=mean_available_station_count,
        station_start=station_start,
        station_end=station_end,
        event_info=event_info,
        event_coverage=event_coverage,
    )
    items = station_precip_analysis_items(
        mode=mode,
        task_context=task_context,
        time_basis_label=time_basis_label,
        matched_station_count=len(matched_ids),
        station_count=station_count,
        missing_in_precip=missing_in_precip,
        missing_in_meta=missing_in_meta,
        station_format=station_format,
        station_start=station_start,
        station_end=station_end,
        step_hours=step,
        coverage_ratio=coverage_ratio,
        covered_count=covered_count,
        zero_available_steps=zero_available_steps,
        max_consecutive_zero_steps=max_consecutive_zero_steps,
        min_available_station_count=min_available_station_count,
        mean_available_station_count=mean_available_station_count,
        max_missing_rate=max_missing_rate,
        negative_count=negative_count,
        extreme_count=extreme_count,
        event_coverage=event_coverage,
    )
    return {
        "enabled": True,
        "mode": mode,
        "status": status,
        "summary": summary,
        "items": items,
        "warnings": warnings,
        "missing": missing,
        "matched_station_count": len(matched_ids),
        "station_count": station_count,
        "precip_station_count": precip_station_count,
        "missing_in_precip": missing_in_precip[:20],
        "missing_in_meta": missing_in_meta[:20],
        "expected_time_steps": expected_count,
        "covered_time_steps": covered_count,
        "coverage_ratio": coverage_ratio,
        "zero_available_steps": zero_available_steps,
        "max_consecutive_zero_steps": max_consecutive_zero_steps,
        "min_available_station_count": min_available_station_count,
        "mean_available_station_count": mean_available_station_count,
        "station_missing_rates": station_missing_rates,
        "time_basis": time_basis,
        "time_basis_label": time_basis_label,
        "task_context": task_context,
        "event_coverage": event_coverage,
    }


def station_precip_task_context_summary(
    *,
    mode: str,
    context: str,
    time_basis: str,
    time_basis_label: str,
    step_hours: float,
    expected_index: pd.DatetimeIndex | None,
    expected_count: int,
    covered_count: int,
    coverage_ratio: float | None,
    zero_available_steps: int,
    max_consecutive_zero_steps: int = 0,
    min_available_station_count: int | None = None,
    mean_available_station_count: float | None = None,
    station_start: Any = None,
    station_end: Any = None,
    event_info: dict[str, Any] | None = None,
    event_coverage: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    start, end, expected_steps = index_display_range(expected_index, step_hours)
    station_start_text = format_time_for_check(station_start, step_hours)
    station_end_text = format_time_for_check(station_end, step_hours)
    coverage_text = (
        f"{covered_count}/{expected_count} \u6b65\uff08{coverage_ratio * 100:.1f}%\uff09"
        if coverage_ratio is not None and expected_count > 0
        else "\u672a\u5f62\u6210\u53ef\u6838\u5bf9\u65f6\u6bb5"
    )
    events = list(event_coverage or [])
    event_ok_count = sum(1 for item in events if str(item.get("status", "") or "") == "ok")
    event_count = int(len(events))
    event_valid_count = int((event_info or {}).get("valid_event_count", event_count) or 0)
    if time_basis == TIME_BASIS_EVENT_WINDOWS and event_valid_count <= 0:
        status = "fail"
    elif expected_count <= 0:
        status = "warn"
    elif coverage_ratio is None or covered_count <= 0:
        status = "fail"
    elif coverage_ratio >= 0.99 and zero_available_steps == 0 and all(str(item.get("status", "")) == "ok" for item in events):
        status = "ok"
    elif mode == "thiessen_station_only" and zero_available_steps > 0:
        status = "fail"
    else:
        status = "warn"

    count_text = station_count_text(min_available_station_count, mean_available_station_count)
    if time_basis == TIME_BASIS_EVENT_WINDOWS:
        headline = (
            f"\u5f53\u524d\u6309 {event_valid_count} \u573a\u6d2a\u6c34\u4e8b\u4ef6\u8fd0\u884c\u7a97\u53e3\u6838\u5bf9\u7ad9\u70b9\u964d\u6c34\uff0c\u4e8b\u4ef6\u4e4b\u95f4\u5141\u8bb8\u8d44\u6599\u95f4\u65ad\u3002"
            if event_valid_count > 0
            else "\u5f53\u524d\u9009\u62e9\u6d2a\u6c34\u4e8b\u4ef6\u7a97\u53e3\uff0c\u4f46\u5c1a\u672a\u5f62\u6210\u53ef\u6838\u5bf9\u7684\u6709\u6548\u4e8b\u4ef6\u3002"
        )
        detail = (
            "\u7ad9\u70b9\u964d\u6c34\u5b8c\u6574\u6027\u53ea\u5728\u4e8b\u4ef6\u8fd0\u884c\u7a97\u53e3\u5185\u8bc4\u4ef7\uff1b\u4e8b\u4ef6\u5185\u90e8\u82e5\u51fa\u73b0\u65e0\u53ef\u7528\u7ad9\u70b9\u65f6\u95f4\u6b65\uff0c"
            "\u7eaf\u7ad9\u70b9\u6cf0\u68ee\u5206\u914d\u4e0d\u80fd\u76f4\u63a5\u8fd0\u884c\uff0c\u683c\u70b9\u8ba2\u6b63\u4e5f\u5e94\u4f5c\u4e3a\u98ce\u9669\u5904\u7406\u3002"
        )
        scope_value = f"{start} \u81f3 {end}" if start and end else "\u672a\u5f62\u6210\u4e8b\u4ef6\u8fd0\u884c\u7a97\u53e3"
        items = [
            {"label": "\u68c0\u67e5\u53e3\u5f84", "value": time_basis_label, "status": "ok" if event_valid_count > 0 else "fail"},
            {"label": "\u4e8b\u4ef6\u8986\u76d6", "value": f"{event_ok_count}/{event_count} \u573a\u5b8c\u6574" if event_count else "\u672a\u5f62\u6210", "status": "ok" if event_count and event_ok_count == event_count else "fail" if event_valid_count <= 0 else "warn"},
            {"label": "\u8fd0\u884c\u7a97\u53e3\u5e76\u96c6", "value": scope_value, "status": "ok" if expected_steps else "warn"},
            {"label": "\u8986\u76d6\u6b65\u6570", "value": coverage_text, "status": "ok" if coverage_ratio is not None and coverage_ratio >= 0.99 else "warn" if covered_count > 0 else "fail"},
            {"label": "\u53ef\u7528\u7ad9\u70b9", "value": count_text, "status": "ok" if min_available_station_count and min_available_station_count > 0 else "fail" if mode == "thiessen_station_only" else "warn"},
            {"label": "\u65e0\u7ad9\u70b9\u65f6\u95f4\u6b65", "value": str(zero_available_steps), "status": "ok" if zero_available_steps == 0 else "fail" if mode == "thiessen_station_only" else "warn"},
            {"label": "\u6700\u5927\u8fde\u7eed\u65e0\u7ad9\u70b9", "value": f"{max_consecutive_zero_steps} \u6b65", "status": "ok" if max_consecutive_zero_steps == 0 else "fail" if mode == "thiessen_station_only" else "warn"},
        ]
    elif time_basis == TIME_BASIS_FORECAST_WINDOW or context == "forecast":
        headline = (
            f"\u5f53\u524d\u6309\u8fde\u7eed\u72b6\u6001\u9884\u62a5\u7a97\u53e3\u6838\u5bf9\u7ad9\u70b9\u964d\u6c34\uff1a{start} \u81f3 {end}\u3002"
            if start and end
            else "\u5f53\u524d\u6309\u8fde\u7eed\u72b6\u6001\u9884\u62a5\u7a97\u53e3\u6838\u5bf9\u7ad9\u70b9\u964d\u6c34\uff0c\u4f46\u9884\u62a5\u8d77\u6b62\u65f6\u95f4\u5c1a\u672a\u5b8c\u6574\u914d\u7f6e\u3002"
        )
        detail = (
            "\u9884\u62a5\u8fd0\u884c\u4e3b\u7ebf\u8bfb\u53d6\u5df2\u7ecf\u5236\u5907\u597d\u7684\u964d\u6c34\u6805\u683c\uff1b\u5982\u679c\u672a\u6765\u964d\u6c34\u6765\u81ea\u7ad9\u70b9\u8d44\u6599\uff0c\u5e94\u5148\u5728\u6c14\u8c61\u51c6\u5907\u6d41\u7a0b\u4e2d\u5b8c\u6210\u8ba2\u6b63\u6216\u6cf0\u68ee\u5236\u56fe\uff0c"
            "\u518d\u5c06\u751f\u6210\u7684\u9884\u62a5\u7a97\u53e3\u6805\u683c\u4ea4\u7ed9\u8fde\u7eed\u72b6\u6001\u9884\u62a5\u3002"
        )
        items = [
            {"label": "\u68c0\u67e5\u53e3\u5f84", "value": time_basis_label, "status": "ok" if expected_steps else "warn"},
            {"label": "\u9884\u62a5\u7a97\u53e3", "value": f"{start} \u81f3 {end}" if start and end else "\u672a\u5b8c\u6574\u914d\u7f6e", "status": "ok" if expected_steps else "warn"},
            {"label": "\u8986\u76d6\u6b65\u6570", "value": coverage_text, "status": "ok" if coverage_ratio is not None and coverage_ratio >= 0.99 else "warn" if covered_count > 0 else "fail"},
            {"label": "\u53ef\u7528\u7ad9\u70b9", "value": count_text, "status": "ok" if min_available_station_count and min_available_station_count > 0 else "warn"},
            {"label": "\u6700\u5927\u8fde\u7eed\u65e0\u7ad9\u70b9", "value": f"{max_consecutive_zero_steps} \u6b65", "status": "ok" if max_consecutive_zero_steps == 0 else "warn"},
            {"label": "\u964d\u6c34\u5904\u7406", "value": "\u9884\u62a5\u9875\u4f7f\u7528\u76ee\u6807\u6805\u683c\uff0c\u7ad9\u70b9\u96e8\u91cf\u5148\u5728\u6c14\u8c61\u51c6\u5907\u4e2d\u5236\u56fe", "status": "ok"},
        ]
    else:
        headline = (
            f"\u5f53\u524d\u6309\u8fde\u7eed\u65f6\u6bb5\u6838\u5bf9\u7ad9\u70b9\u964d\u6c34\uff1a{start} \u81f3 {end}\u3002"
            if start and end
            else "\u5f53\u524d\u6309\u8fde\u7eed\u65f6\u6bb5\u6838\u5bf9\u7ad9\u70b9\u964d\u6c34\uff0c\u4f46\u9884\u70ed\u3001\u7387\u5b9a\u6216\u9a8c\u8bc1\u65f6\u95f4\u5c1a\u672a\u5b8c\u6574\u914d\u7f6e\u3002"
        )
        detail = (
            "\u8fde\u7eed\u6a21\u62df\u8981\u6c42\u76ee\u6807\u65f6\u95f4\u8f74\u5185\u7ad9\u70b9\u964d\u6c34\u8fde\u7eed\u53c2\u4e0e\uff1b\u4e2d\u95f4\u7f3a\u53e3\u4f1a\u5f71\u54cd\u571f\u58e4\u542b\u6c34\u91cf\u3001\u79ef\u96ea\u3001\u6c34\u5e93\u72b6\u6001\u548c\u6c47\u6d41\u8bb0\u5fc6\u3002"
        )
        items = [
            {"label": "\u68c0\u67e5\u53e3\u5f84", "value": time_basis_label, "status": "ok" if expected_steps else "warn"},
            {"label": "\u8fde\u7eed\u65f6\u6bb5", "value": f"{start} \u81f3 {end}" if start and end else "\u672a\u5b8c\u6574\u914d\u7f6e", "status": "ok" if expected_steps else "warn"},
            {"label": "\u8986\u76d6\u6b65\u6570", "value": coverage_text, "status": "ok" if coverage_ratio is not None and coverage_ratio >= 0.99 else "warn" if covered_count > 0 else "fail"},
            {"label": "\u53ef\u7528\u7ad9\u70b9", "value": count_text, "status": "ok" if min_available_station_count and min_available_station_count > 0 else "fail" if mode == "thiessen_station_only" else "warn"},
            {"label": "\u65e0\u7ad9\u70b9\u65f6\u95f4\u6b65", "value": str(zero_available_steps), "status": "ok" if zero_available_steps == 0 else "fail" if mode == "thiessen_station_only" else "warn"},
            {"label": "\u6700\u5927\u8fde\u7eed\u65e0\u7ad9\u70b9", "value": f"{max_consecutive_zero_steps} \u6b65", "status": "ok" if max_consecutive_zero_steps == 0 else "fail" if mode == "thiessen_station_only" else "warn"},
        ]

    return {
        "schema": "station_precip_task_context_v1",
        "context": context,
        "mode": mode,
        "mode_label": station_precip_mode_label(mode),
        "time_basis": time_basis,
        "time_basis_label": time_basis_label,
        "headline": headline,
        "detail": detail,
        "status": status,
        "start": start,
        "end": end,
        "expected_steps": int(expected_steps),
        "covered_steps": int(covered_count),
        "coverage_ratio": coverage_ratio,
        "zero_available_steps": int(zero_available_steps),
        "max_consecutive_zero_steps": int(max_consecutive_zero_steps),
        "min_available_station_count": min_available_station_count,
        "mean_available_station_count": mean_available_station_count,
        "station_time_range": {
            "start": station_start_text,
            "end": station_end_text,
        },
        "event_count": event_count,
        "event_ok_count": int(event_ok_count),
        "items": items,
    }
