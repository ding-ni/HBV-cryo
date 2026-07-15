#!/usr/bin/env python
# -*- coding: utf-8 -*-
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

import numpy as np
import pandas as pd
from services.time_utils import parse_time_from_name, time_step_count_text


@dataclass(frozen=True)
class ForcingValidationContext:
    current_profile: Callable[[dict[str, Any]], str]
    build_profile_paths: Callable[[dict[str, Any], str], dict[str, Any]]
    normalize_time_step_hours: Callable[[Any], float]
    task_time_basis: Callable[..., str]
    time_basis_labels: dict[str, str]
    time_basis_event_windows: str
    build_expected_forcing_index: Callable[..., pd.DatetimeIndex | None]
    normalized_flood_events: Callable[..., dict[str, Any]]
    effective_precip_paths: Callable[..., tuple[Path, Path, str]]
    validate_tif_time_series: Callable[..., dict[str, Any]]
    workspace_dem_path: Callable[..., Path]
    configured_dem_kind: Callable[[dict[str, Any]], str | None]
    validate_tif_grid_alignment: Callable[..., dict[str, Any]]
    event_windows_ui_summary: Callable[[dict[str, Any] | None, float], dict[str, Any] | None]
    event_forcing_coverage_summary: Callable[..., dict[str, Any] | None]


@dataclass(frozen=True)
class ForcingAlignedStatusContext:
    build_profile_paths: Callable[[dict[str, Any], str], dict[str, Any]]
    effective_precip_paths: Callable[..., tuple[Path, Path, str]]
    normalize_time_step_hours: Callable[[Any], float]
    validate_tif_time_series: Callable[..., dict[str, Any]]


@dataclass(frozen=True)
class ForcingInputsReadyContext:
    build_profile_paths: Callable[[dict[str, Any], str], dict[str, Any]]
    workspace_dem_path: Callable[..., Path]
    configured_dem_kind: Callable[[dict[str, Any]], str | None]
    resolve_config_related_path: Callable[[dict[str, Any], Any], Path | None]
    validate_forcing_bundle: Callable[..., dict[str, Any]]
    observed_flow_key: str


@dataclass(frozen=True)
class ForcingPreprocessStatusContext:
    build_workspace_paths: Callable[[dict[str, Any]], dict[str, Any]]
    build_profile_paths: Callable[[dict[str, Any], str], dict[str, Any]]
    resolve_precip_source: Callable[[dict[str, Any], Any], str]
    effective_precip_source: Callable[[str], str]
    count_matching: Callable[..., int]
    validate_tif_time_series: Callable[..., dict[str, Any]]


@dataclass(frozen=True)
class ForcingDownloadStatusContext:
    build_workspace_paths: Callable[[dict[str, Any]], dict[str, Any]]
    configured_precip_source: Callable[[dict[str, Any]], str]


@dataclass(frozen=True)
class HourlyForcingReadyContext:
    build_workspace_paths: Callable[[dict[str, Any]], dict[str, Any]]
    validate_forcing_bundle: Callable[..., dict[str, Any]]


def forcing_period_text(result: dict[str, Any], step_hours: float | None = None) -> str:
    summary = str(result.get("period_summary", "") or "").strip()
    if summary:
        return summary
    count = int(result.get("valid_time_steps", 0) or 0)
    if step_hours is None:
        return f"仅识别到 {count} 个时段，旧检查结果未提供起止时间"
    return f"仅识别到 {time_step_count_text(count, step_hours)}，旧检查结果未提供起止时间"


def series_group_status(
    entries: list[tuple[str, Path]],
    step_hours: float,
    context: ForcingPreprocessStatusContext,
) -> tuple[bool, str, int, list[dict[str, Any]]]:
    results: list[dict[str, Any]] = []
    total = 0
    for label, directory in entries:
        result = context.validate_tif_time_series(label, directory, step_hours)
        results.append(result)
        total += int(result["valid_time_steps"])
    ready = all(result["ok"] and int(result["valid_time_steps"]) > 0 for result in results)
    if ready:
        message = "；".join(
            f"{result.get('label') or entries[index][0]}：{forcing_period_text(result, step_hours)}"
            for index, result in enumerate(results)
        )
        return True, message, total, results
    issues = [result["errors"][0] for result in results if result["errors"]]
    if issues:
        return False, "；".join(issues[:2]), total, results
    return False, "未检测到有效 tif 时间序列。", total, results


def prefer_raw_or_aligned_group_status(
    raw_entries: list[tuple[str, Path]],
    aligned_entries: list[tuple[str, Path]],
    step_hours: float,
    context: ForcingPreprocessStatusContext,
) -> tuple[bool, str, int]:
    raw_ok, raw_message, raw_count, raw_results = series_group_status(raw_entries, step_hours, context)
    aligned_ok, aligned_message, aligned_count, aligned_results = series_group_status(aligned_entries, step_hours, context)
    if raw_ok:
        return True, raw_message, raw_count
    if aligned_ok:
        return True, f"{aligned_message}（已导入并完成网格对齐）", aligned_count
    raw_has_files = any(int(result.get("total_files", 0) or 0) > 0 for result in raw_results)
    aligned_has_files = any(int(result.get("total_files", 0) or 0) > 0 for result in aligned_results)
    if aligned_has_files:
        return False, aligned_message, aligned_count
    if raw_has_files:
        return False, raw_message, raw_count
    return False, raw_message, 0


def configured_daily_meteo_sources(config: dict[str, Any]) -> tuple[str, str]:
    meteo = dict(config.get("气象策略", {}) or {})
    temp_source = str(meteo.get("温度来源", "era5")).strip().lower() or "era5"
    pet_source = str(meteo.get("潜在蒸散发来源", meteo.get("蒸散发来源", "era5_fao56"))).strip().lower() or "era5_fao56"
    return temp_source, pet_source


def glob_count(path: Path, pattern: str) -> int:
    if not path.exists():
        return 0
    return len(list(path.glob(pattern)))


def _is_date_only_text(value: Any) -> bool:
    if not isinstance(value, str):
        return False
    text = value.strip()
    return bool(text) and (" " not in text) and ("T" not in text) and len(text) <= 10


def _format_hourly_time(value: Any) -> str:
    try:
        return pd.Timestamp(value).strftime("%Y-%m-%d %H:%M")
    except Exception:
        return str(value)


def _same_path(left: Any, right: Any) -> bool:
    try:
        return str(Path(left).resolve(strict=False)).lower() == str(Path(right).resolve(strict=False)).lower()
    except Exception:
        return str(left).strip().lower() == str(right).strip().lower()


def _int_or_none(value: Any) -> int | None:
    try:
        return int(value)
    except Exception:
        return None


def hourly_explicit_time_errors(config: dict[str, Any], step_hours: float) -> list[str]:
    if float(step_hours) >= 24.0:
        return []
    time_cfg = dict(config.get("时间", {}) or {})
    errors: list[str] = []
    for key in ("预热开始", "预热结束", "率定开始", "率定结束", "验证开始", "验证结束"):
        value = time_cfg.get(key)
        if _is_date_only_text(value):
            errors.append(f"小时尺度时间字段“{key}”必须写到小时，例如 2025-06-01 08:00，不能只写 {value}。")
    return errors


def inspect_hourly_forcing_summary(
    aligned_dir: Path,
    *,
    expected_index: pd.DatetimeIndex | None,
    precip_dir: Path,
    temp_dir: Path,
    evap_dir: Path,
) -> dict[str, Any]:
    summary_path = Path(aligned_dir) / "hourly_forcing_summary.json"
    result: dict[str, Any] = {
        "path": str(summary_path.resolve(strict=False)),
        "exists": summary_path.exists(),
        "errors": [],
        "warnings": [],
        "summary": None,
    }
    if not summary_path.exists():
        result["warnings"].append("未找到小时强迫摘要 hourly_forcing_summary.json，无法核对 08:00 水文日时间基准和守恒检查结果。")
        return result
    try:
        summary = json.loads(summary_path.read_text(encoding="utf-8"))
    except Exception as exc:
        result["errors"].append(f"小时强迫摘要无法读取：{exc}")
        return result
    result["summary"] = summary

    if summary.get("time_basis") != "hydrological_day_08_to_08_local":
        result["warnings"].append("小时强迫摘要未声明 hydrological_day_08_to_08_local 时间基准，请确认小时 TIF 与 workspace 时间一致。")
    expected_hours = _int_or_none(summary.get("expected_hours"))
    actual_hours = _int_or_none(summary.get("actual_hours"))
    if expected_hours is not None and actual_hours is not None and actual_hours < expected_hours:
        result["errors"].append(f"小时强迫输出不完整：实际完整小时 {actual_hours}，期望 {expected_hours}。")

    conservation = dict(summary.get("conservation_checks", {}) or {})
    if conservation and not bool(conservation.get("ok", False)):
        failed = []
        for key, item in dict(conservation.get("items", {}) or {}).items():
            item_dict = dict(item or {}) if isinstance(item, dict) else {}
            failed_days = _int_or_none(item_dict.get("failed_days", 0)) or 0
            invalid_cells = _int_or_none(item_dict.get("invalid_cell_count", 0)) or 0
            if failed_days > 0 or invalid_cells > 0:
                failed.append(str(key))
        suffix = f"：{', '.join(failed[:3])}" if failed else ""
        result["errors"].append(f"小时强迫守恒检查未通过{suffix}。")

    outputs = dict(summary.get("outputs", {}) or {})
    output_checks = [
        ("降水", outputs.get("precipitation_dir"), precip_dir),
        ("气温", outputs.get("temperature_dir"), temp_dir),
        ("蒸散发", outputs.get("evaporation_dir"), evap_dir),
    ]
    for label, recorded, current in output_checks:
        if recorded and not _same_path(recorded, current):
            result["warnings"].append(f"小时强迫摘要中的{label}目录与当前配置读取目录不同：{recorded} -> {current}")

    first_raw = summary.get("first_output_time")
    last_raw = summary.get("last_output_time")
    first = pd.to_datetime(first_raw, errors="coerce") if first_raw else pd.NaT
    last = pd.to_datetime(last_raw, errors="coerce") if last_raw else pd.NaT
    if expected_index is not None and len(expected_index) > 0:
        expected_start = pd.Timestamp(expected_index[0])
        expected_end = pd.Timestamp(expected_index[-1])
        if pd.notna(first) and first > expected_start:
            result["errors"].append(
                f"小时强迫开始时间晚于配置期望：强迫 {_format_hourly_time(first)}，配置 {_format_hourly_time(expected_start)}。"
            )
        if pd.notna(last) and last < expected_end:
            result["errors"].append(
                f"小时强迫结束时间早于配置期望：强迫 {_format_hourly_time(last)}，配置 {_format_hourly_time(expected_end)}。"
            )
        if pd.notna(first) and pd.notna(last) and (first != expected_start or last != expected_end):
            result["warnings"].append(
                "小时强迫摘要时间范围与当前 workspace 不完全相同："
                f"强迫 {_format_hourly_time(first)} 至 {_format_hourly_time(last)}；"
                f"配置 {_format_hourly_time(expected_start)} 至 {_format_hourly_time(expected_end)}。"
            )
    return result


def _valid_raster_mask(path: Path) -> np.ndarray:
    import rasterio

    with rasterio.open(path) as src:
        arr = src.read(1).astype("float64")
        mask = np.isfinite(arr) & (arr > -9000.0) & (arr < 1.0e10)
        if src.nodata is not None:
            mask &= arr != src.nodata
        return mask


def _time_file_map(directory: Path) -> dict[pd.Timestamp, Path]:
    mapping: dict[pd.Timestamp, Path] = {}
    if not directory.exists():
        return mapping
    for path in sorted(directory.glob("*.tif")):
        stamp = parse_time_from_name(path.name)
        if stamp is not None and stamp not in mapping:
            mapping[pd.Timestamp(stamp)] = path
    return mapping


def validate_forcing_mask_consistency(
    directories: dict[str, dict[str, Any]],
    *,
    max_checked_steps: int = 12,
) -> dict[str, Any]:
    result: dict[str, Any] = {
        "ok": True,
        "checked_steps": 0,
        "errors": [],
        "warnings": [],
        "examples": [],
    }
    path_texts = {key: str(item.get("path", "") or "").strip() for key, item in directories.items()}
    if any(not text for text in path_texts.values()):
        return result
    path_map = {key: Path(text) for key, text in path_texts.items()}
    if any(not path.exists() for path in path_map.values()):
        result["warnings"].append("气象驱动目录尚未齐全，暂不做 P/T/PET 有效像元一致性检查。")
        return result
    maps = {key: _time_file_map(path) for key, path in path_map.items()}
    common = sorted(set(maps["prec"]) & set(maps["temp"]) & set(maps["evap"]))
    if not common:
        result["warnings"].append("没有共同时间步，暂不做 P/T/PET 有效像元一致性检查。")
        return result
    if len(common) <= max_checked_steps:
        samples = common
    else:
        last = len(common) - 1
        indices = sorted({round(pos * last / (max_checked_steps - 1)) for pos in range(max_checked_steps)})
        samples = [common[idx] for idx in indices]

    for stamp in samples:
        try:
            masks = {key: _valid_raster_mask(maps[key][stamp]) for key in ("prec", "temp", "evap")}
        except Exception as exc:
            result["errors"].append(f"有效像元一致性检查读取失败：{stamp}（{exc}）")
            continue
        if masks["prec"].shape != masks["temp"].shape or masks["prec"].shape != masks["evap"].shape:
            result["errors"].append(f"有效像元一致性检查失败：{stamp} 三类栅格尺寸不一致。")
            continue
        for key, label in (("temp", "气温"), ("evap", "蒸散发/PET")):
            missing = int(np.count_nonzero(masks["prec"] & ~masks[key]))
            extra = int(np.count_nonzero(masks[key] & ~masks["prec"]))
            if missing or extra:
                result["examples"].append(
                    {
                        "time": str(stamp),
                        "variable": label,
                        "missing_vs_precip": missing,
                        "extra_vs_precip": extra,
                    }
                )
    result["checked_steps"] = int(len(samples))
    if result["examples"]:
        preview = "；".join(
            f"{item['time']} {item['variable']} 缺 {item['missing_vs_precip']} 格/多 {item['extra_vs_precip']} 格"
            for item in result["examples"][:5]
        )
        result["errors"].append(
            "降水、气温、潜在蒸散发的有效像元掩膜不一致，不能用于率定；"
            f"例如：{preview}。请覆盖重跑气象对齐裁剪步骤。"
        )
    result["ok"] = len(result["errors"]) == 0
    return result


def summarize_nc_download_status(entries: list[tuple[str, Path, str]]) -> tuple[bool, str, int]:
    if not entries:
        return True, "当前方案不需要这一步。", 0
    existing: list[str] = []
    missing: list[str] = []
    total = 0
    for label, directory, pattern in entries:
        count = glob_count(directory, pattern)
        total += count
        if count > 0:
            existing.append(f"{label} {count} 个")
        else:
            missing.append(label)
    if not missing:
        return True, "已下载：" + "；".join(existing), total
    if existing:
        return False, "已下载：" + "；".join(existing) + f"；仍缺少：{'、'.join(missing)}", total
    return False, "还没有下载到这一步需要的 ERA5 原始文件。", 0


def check_daily_era5_download_status(
    config: dict[str, Any],
    context: ForcingDownloadStatusContext,
) -> tuple[bool, str, int]:
    paths = context.build_workspace_paths(config)
    temp_source, pet_source = configured_daily_meteo_sources(config)
    precip_source = context.configured_precip_source(config)
    entries: list[tuple[str, Path, str]] = []
    if precip_source == "era5":
        entries.append(("ERA5 降水", Path(paths["raw_prec_era5_dir"]), "era5_tp_*.nc"))
    if temp_source != "custom_tif" or pet_source != "custom_tif":
        entries.append(("ERA5 温度", Path(paths["raw_temp_dir"]), "era5_t2m_*.nc"))
    if pet_source != "custom_tif":
        entries.extend(
            [
                ("太阳辐射", Path(paths["raw_solar_dir"]), "era5_ssrd_*.nc"),
                ("风速(U)", Path(paths["raw_wind_dir"]), "era5_u10_*.nc"),
                ("风速(V)", Path(paths["raw_wind_dir"]), "era5_v10_*.nc"),
                ("露点温度", Path(paths["raw_dewpoint_dir"]), "era5_d2m_*.nc"),
            ]
        )
    return summarize_nc_download_status(entries)


def check_hourly_era5_download_status(
    config: dict[str, Any],
    context: ForcingDownloadStatusContext,
) -> tuple[bool, str, int]:
    paths = context.build_workspace_paths(config)
    patterns = [
        Path(paths["raw_temp_dir"]).glob("era5_t2m_hourly_*.nc"),
        Path(paths["raw_solar_dir"]).glob("era5_ssrd_hourly_*.nc"),
        Path(paths["raw_wind_dir"]).glob("era5_u10_hourly_*.nc"),
        Path(paths["raw_wind_dir"]).glob("era5_v10_hourly_*.nc"),
        Path(paths["raw_dewpoint_dir"]).glob("era5_d2m_hourly_*.nc"),
    ]
    if context.configured_precip_source(config) == "era5":
        patterns.append(Path(paths["raw_prec_era5_dir"]).glob("era5_tp_hourly_*.nc"))
    count = sum(len(list(items)) for items in patterns)
    time_cfg = dict(config.get("时间", {}) or {})
    start = str(time_cfg.get("预热开始", "") or "").replace("T", " ")
    end = str(time_cfg.get("验证结束", "") or "").replace("T", " ")
    period = f"目标时段 {start} 至 {end}；" if start and end else ""
    coverage_note = period or "下载目标时段尚未填写；"
    return count > 0, f"{coverage_note}小时 ERA5 原始文件组已准备 {count} 个，处理后将逐小时核验起止时间与缺测", count


def hourly_forcing_ready_status(
    config: dict[str, Any],
    context: HourlyForcingReadyContext,
    *,
    profile: str,
    precip_source: Any = None,
) -> tuple[bool, str, int]:
    base_paths = context.build_workspace_paths(config)
    forcing = context.validate_forcing_bundle(config, profile, precip_source=precip_source)
    labels = {"prec": "降水", "temp": "气温", "evap": "蒸散发"}
    periods = {
        key: forcing_period_text(forcing["directories"][key], 1.0)
        for key in ("prec", "temp", "evap")
    }
    detail = ""
    if forcing["errors"]:
        detail = f"；问题：{'；'.join(forcing['errors'][:2])}"
    message = (
        "小时气象驱动："
        + "；".join(f"{labels[key]}：{periods[key]}" for key in ("prec", "temp", "evap"))
        + f"（工程目录={base_paths['workspace_root']}）{detail}"
    )
    return (
        forcing["ok"],
        message,
        forcing["total_valid_steps"],
    )


def check_daily_temp_evap_status(
    config: dict[str, Any],
    context: ForcingPreprocessStatusContext,
    *,
    profile: str,
) -> tuple[bool, str, int]:
    paths = context.build_profile_paths(config, profile)
    return prefer_raw_or_aligned_group_status(
        [
            ("日尺度 ERA5 温度中间结果", Path(paths["raw_temp_daily_dir"])),
            ("日尺度潜在蒸散发中间结果", Path(paths["raw_evap_daily_dir"])),
        ],
        [
            ("工程气温输入", Path(paths["aligned_temp_dir"])),
            ("工程潜在蒸散发输入", Path(paths["aligned_evap_dir"])),
        ],
        24.0,
        context,
    )


def check_daily_era5_processed_status(
    config: dict[str, Any],
    context: ForcingPreprocessStatusContext,
    *,
    profile: str,
) -> tuple[bool, str, int]:
    paths = context.build_profile_paths(config, profile)
    temp_source, pet_source = configured_daily_meteo_sources(config)
    raw_entries: list[tuple[str, Path]] = []
    aligned_entries: list[tuple[str, Path]] = []
    if temp_source != "custom_tif":
        raw_entries.append(("日尺度气温结果", Path(paths["raw_temp_daily_dir"])))
        aligned_entries.append(("工程气温输入", Path(paths["aligned_temp_dir"])))
    if pet_source != "custom_tif":
        raw_entries.append(("日尺度潜在蒸散发结果", Path(paths["raw_evap_daily_dir"])))
        aligned_entries.append(("工程潜在蒸散发输入", Path(paths["aligned_evap_dir"])))
    if not raw_entries:
        return True, "当前方案不需要这一步。", 0
    return prefer_raw_or_aligned_group_status(raw_entries, aligned_entries, 24.0, context)


def check_daily_prec_status(
    config: dict[str, Any],
    context: ForcingPreprocessStatusContext,
    *,
    profile: str,
    precip_source: Any = None,
) -> tuple[bool, str, int]:
    paths = context.build_profile_paths(config, profile)
    source_key = context.resolve_precip_source(config, precip_source)
    if source_key == "custom_tif":
        aligned = Path(paths["aligned_prec_custom_base_dir"])
        ready, message, count, _ = series_group_status([("工程本地降水输入", aligned)], 24.0, context)
        if count > 0:
            return ready, message, count
        return True, "当前为本地栅格降水模式，不需要执行原始降水预处理。", 0
    source = context.effective_precip_source(source_key)
    if source == "era5":
        target = paths["raw_prec_era5_daily_dir"]
        aligned = paths["aligned_prec_era5_base_dir"]
    elif source == "cmfd":
        target = paths["raw_prec_cmfd_daily_dir"]
        aligned = paths["aligned_prec_cmfd_base_dir"]
    else:
        target = paths["raw_prec_daily_dir"]
        aligned = paths["aligned_prec_base_dir"]
    return prefer_raw_or_aligned_group_status(
        [("日尺度降水中间结果", Path(target))],
        [("工程降水输入", Path(aligned))],
        24.0,
        context,
    )


def check_hourly_temp_evap_status(
    config: dict[str, Any],
    context: ForcingPreprocessStatusContext,
    *,
    profile: str,
) -> tuple[bool, str, int]:
    paths = context.build_workspace_paths(config)
    profile_paths = context.build_profile_paths(config, profile)
    return prefer_raw_or_aligned_group_status(
        [
            ("小时尺度 ERA5 温度中间结果", Path(paths["raw_temp_hourly_dir"])),
            ("小时尺度潜在蒸散发中间结果", Path(paths["raw_evap_hourly_dir"])),
        ],
        [
            ("工程气温输入", Path(profile_paths["aligned_temp_dir"])),
            ("工程潜在蒸散发输入", Path(profile_paths["aligned_evap_dir"])),
        ],
        1.0,
        context,
    )


def check_hourly_prec_status(
    config: dict[str, Any],
    context: ForcingPreprocessStatusContext,
    *,
    profile: str,
    precip_source: Any = None,
) -> tuple[bool, str, int]:
    paths = context.build_workspace_paths(config)
    profile_paths = context.build_profile_paths(config, profile)
    source_key = context.resolve_precip_source(config, precip_source)
    if source_key == "custom_tif":
        aligned = Path(profile_paths.get("aligned_prec_custom_dir", profile_paths["aligned_prec_custom_base_dir"]))
        ready, message, count, _ = series_group_status([("工程小时降水输入", aligned)], 1.0, context)
        if count > 0:
            return ready, message, count
        return True, "当前为本地栅格降水模式，不需要执行原始小时降水标准化。", 0
    source = context.effective_precip_source(source_key)
    if source == "era5":
        target = paths["raw_prec_era5_hourly_dir"]
        aligned = profile_paths["aligned_prec_era5_base_dir"]
    elif source == "cmfd":
        target = paths["raw_prec_cmfd_hourly_dir"]
        aligned = profile_paths["aligned_prec_cmfd_base_dir"]
    else:
        target = paths["raw_prec_hourly_dir"]
        aligned = profile_paths["aligned_prec_base_dir"]
    return prefer_raw_or_aligned_group_status(
        [("小时尺度降水中间结果", Path(target))],
        [("工程降水输入", Path(aligned))],
        1.0,
        context,
    )


def check_aligned_forcing_status(
    config: dict[str, Any],
    context: ForcingAlignedStatusContext,
    *,
    profile: str,
    label: str,
    precip_source: Any = None,
) -> tuple[bool, str, int]:
    paths = context.build_profile_paths(config, profile)
    precip_dir, _, _ = context.effective_precip_paths(config, profile, precip_source=precip_source)
    step_hours = context.normalize_time_step_hours(config.get("时间步长_小时", 24.0))
    scans = [
        context.validate_tif_time_series("降水", precip_dir, step_hours),
        context.validate_tif_time_series("气温", Path(paths["aligned_temp_dir"]), step_hours),
        context.validate_tif_time_series("蒸散发", Path(paths["aligned_evap_dir"]), step_hours),
    ]
    count = sum(int(item["valid_time_steps"]) for item in scans)
    ready = all(item["ok"] for item in scans)
    fallback_labels = ("降水", "气温", "蒸散发")
    message = "；".join(item["errors"][0] for item in scans if item["errors"]) or "；".join(
        f"{item.get('label') or fallback_labels[index]}：{forcing_period_text(item, step_hours)}"
        for index, item in enumerate(scans)
    )
    return ready, message, count


def check_forcing_inputs_ready(
    config: dict[str, Any],
    context: ForcingInputsReadyContext,
    *,
    profile: str,
    forcing_label: str = "",
    precip_source: Any = None,
) -> tuple[bool, str, int]:
    paths = context.build_profile_paths(config, profile)
    required = [
        context.workspace_dem_path(paths["gis_dir"], prefer=context.configured_dem_kind(config)),
        Path(paths["gis_dir"]) / "flow_accumulation_masked.tif",
    ]
    basin_path = context.resolve_config_related_path(config, config.get("流域边界_shp"))
    obs_path = context.resolve_config_related_path(config, config.get(context.observed_flow_key))
    if basin_path is not None:
        required.append(basin_path)
    if obs_path is not None:
        required.append(obs_path)
    base_ready = all(Path(item).exists() for item in required)
    if basin_path is None or obs_path is None:
        base_ready = False

    forcing = context.validate_forcing_bundle(config, profile, precip_source=precip_source)
    step_hours = float(config.get("时间步长_小时", 1.0 if profile == "hourly" else 24.0) or 24.0)
    directories = dict(forcing.get("directories", {}) or {})
    if all(key in directories for key in ("prec", "temp", "evap")):
        fallback_labels = {"prec": "降水", "temp": "气温", "evap": "蒸散发"}
        period_message = "；".join(
            f"{directories[key].get('label') or fallback_labels[key]}："
            f"{forcing_period_text(directories[key], step_hours)}"
            for key in ("prec", "temp", "evap")
        )
    else:
        period_message = (
            f"气象驱动旧检查结果仅返回 {time_step_count_text(int(forcing.get('total_valid_steps', 0) or 0), step_hours)}，"
            "未返回各变量起止时间"
        )
    message = f"基础输入{'齐全' if base_ready else '缺失'}；{period_message}"
    if forcing["errors"]:
        message += f"；问题：{'；'.join(forcing['errors'][:2])}"
    return base_ready and forcing["ok"], message, int(forcing["total_valid_steps"]) + int(base_ready)


def validate_forcing_bundle(
    config: dict[str, Any],
    context: ForcingValidationContext,
    profile: str | None = None,
    precip_source: Any = None,
) -> dict[str, Any]:
    active_profile = profile or context.current_profile(config)
    paths = context.build_profile_paths(config, active_profile)
    step_hours = context.normalize_time_step_hours(config.get("时间步长_小时", 24.0))
    time_basis = context.task_time_basis(config, context="calibration")
    time_basis_label = context.time_basis_labels.get(time_basis, "当前任务时段")
    expected_index = context.build_expected_forcing_index(config, context="calibration")
    event_info = (
        context.normalized_flood_events(config, step_hours=step_hours)
        if time_basis == context.time_basis_event_windows
        else None
    )
    _, precip_dir, selected_source = context.effective_precip_paths(
        config,
        active_profile,
        precip_source=precip_source,
    )
    precip_label = "降水（本地栅格）" if selected_source == "custom_tif" else "降水"
    directories = {
        "prec": context.validate_tif_time_series(precip_label, Path(precip_dir), step_hours, expected_index, time_basis_label),
        "temp": context.validate_tif_time_series("气温", Path(paths["aligned_temp_dir"]), step_hours, expected_index, time_basis_label),
        "evap": context.validate_tif_time_series("蒸散发", Path(paths["aligned_evap_dir"]), step_hours, expected_index, time_basis_label),
    }
    errors: list[str] = []
    warnings: list[str] = []
    for item in directories.values():
        errors.extend(item["errors"])
        warnings.extend(item["warnings"])
    dem_path = context.workspace_dem_path(paths["gis_dir"], prefer=context.configured_dem_kind(config))
    grid_checks = {
        "prec": context.validate_tif_grid_alignment(precip_label, Path(precip_dir), dem_path),
        "temp": context.validate_tif_grid_alignment("气温", Path(paths["aligned_temp_dir"]), dem_path),
        "evap": context.validate_tif_grid_alignment("蒸散发", Path(paths["aligned_evap_dir"]), dem_path),
    }
    for item in grid_checks.values():
        if not item.get("ok") and item.get("error"):
            errors.append(str(item["error"]))
    mask_consistency = validate_forcing_mask_consistency(directories)
    errors.extend(mask_consistency["errors"])
    warnings.extend(mask_consistency["warnings"])
    hourly_summary = None
    if active_profile == "hourly" or step_hours < 24.0:
        explicit_time_errors = hourly_explicit_time_errors(config, step_hours)
        errors.extend(explicit_time_errors)
        aligned_dir = Path(paths.get("aligned_dir", Path(paths["aligned_temp_dir"]).parent))
        hourly_summary = inspect_hourly_forcing_summary(
            aligned_dir,
            expected_index=expected_index,
            precip_dir=Path(precip_dir),
            temp_dir=Path(paths["aligned_temp_dir"]),
            evap_dir=Path(paths["aligned_evap_dir"]),
        )
        errors.extend(hourly_summary["errors"])
        warnings.extend(hourly_summary["warnings"])
    return {
        "ok": len(errors) == 0,
        "errors": errors,
        "warnings": warnings,
        "expected_steps": len(expected_index) if expected_index is not None else None,
        "expected_start": expected_index[0] if expected_index is not None and len(expected_index) else None,
        "expected_end": expected_index[-1] if expected_index is not None and len(expected_index) else None,
        "directories": directories,
        "grid_checks": grid_checks,
        "mask_consistency": mask_consistency,
        "total_valid_steps": sum(int(item["valid_time_steps"]) for item in directories.values()),
        "profile": active_profile,
        "time_basis": time_basis,
        "time_basis_label": time_basis_label,
        "hourly_forcing_summary": hourly_summary,
        "event_windows": context.event_windows_ui_summary(event_info, step_hours) if event_info is not None else None,
        "event_forcing_coverage": (
            context.event_forcing_coverage_summary(event_info, directories, step_hours)
            if event_info is not None
            else None
        ),
    }
