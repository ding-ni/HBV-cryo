#!/usr/bin/env python
# -*- coding: utf-8 -*-
from __future__ import annotations

import copy
import hashlib
import re
import threading
import time
import unicodedata
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

import pandas as pd

from services.meteo_config import (
    METEO_CUSTOM_PET_DIR_KEY,
    METEO_CUSTOM_PREC_DIR_KEY,
    METEO_CUSTOM_TEMP_DIR_KEY,
    METEO_HOURLY_PREC_DIR_KEY,
    METEO_PET_SOURCE_KEY,
    METEO_PRECIP_MODE_KEY,
    METEO_STATION_META_KEY,
    METEO_STATION_PREC_KEY,
    METEO_TEMP_SOURCE_KEY,
    configured_precip_source,
)
from services.time_utils import expected_warmup_end, format_timestamp_for_display


CONFIG_PATH_FIELDS = ("运行目录", "流域边界_shp", "DEM_tif", "冰川边界_shp")
METEO_PATH_FIELDS = (
    METEO_STATION_PREC_KEY,
    METEO_STATION_META_KEY,
    METEO_HOURLY_PREC_DIR_KEY,
    METEO_CUSTOM_TEMP_DIR_KEY,
    METEO_CUSTOM_PREC_DIR_KEY,
    METEO_CUSTOM_PET_DIR_KEY,
)
BOUNDARY_PATH_FIELDS = ("上游边界入流_csv",)
EVENT_PATH_FIELDS = ("事件表路径", "events_file", "event_file")
WIZARD_STALE_KEYS = frozenset({
    "name",
    "timescale",
    "object",
    "basin_shp",
    "obs_csv",
    "dem_tif",
    "glacier_shp",
    "warmup_start",
    "warmup_end",
    "calib_start",
    "calib_end",
    "valid_start",
    "valid_end",
    "cfmax",
    "fao_elev",
    "boundary_csv",
    "gap_fill",
    "boundary_date",
    "boundary_flow",
    "time_basis",
    "event_file",
})

_WORKSPACE_LIST_CACHE_TTL_SECONDS = 10.0
_WORKSPACE_LIST_CACHE_LOCK = threading.Lock()
_WORKSPACE_LIST_CACHE: dict[
    str,
    tuple[tuple[tuple[str, int, int], ...], float, list[dict[str, Any]]],
] = {}


@dataclass(frozen=True)
class WorkspaceCatalogContext:
    template_dir: Path
    workspace_dir: Path
    project_runtime_dir: Path
    default_workspace_path: Path
    builtin_glacier_shp: Path
    builtin_dem: Path
    profile_daily: str
    profile_hourly: str
    time_basis_continuous: str
    time_basis_event_windows: str
    object_regression: str
    object_interbasin: str
    object_full_upstream: str
    observed_flow_key: str
    meteo_key: str
    meteo_precip_source_key: str
    meteo_precip_source_legacy_key: str
    read_json_file: Callable[[Path], dict[str, Any]]
    read_runtime_config: Callable[[Path], dict[str, Any]]
    replace_placeholders: Callable[[Any], Any]
    resolve_any_path: Callable[..., Path]
    resolve_profile: Callable[[dict[str, Any], str | None], str]
    normalize_objective_mode: Callable[[Any], str]
    default_initial_state: dict[str, Any]
    write_json_file: Callable[[Path, Any], None]
    to_display_path: Callable[[Path], str]
    to_portable_path: Callable[[str], str]
    workspace_workflow_summary: Callable[..., dict[str, Any]]
    normalize_time_step_hours: Callable[[Any], float]
    ensure_within: Callable[[Path, Path], Path]
    inspect_observed_csv: Callable[..., dict[str, Any]]
    fill_bbox_from_shp: Callable[[str], dict[str, float] | None]
    suggest_cfmax_threshold: Callable[[str, str], dict[str, Any]]
    stage_vector_shapefile: Callable[..., Path]
    stage_observed_runoff_file: Callable[..., Path]


def slugify_workspace_name(name: str) -> str:
    raw = str(name or "").strip()
    if not raw:
        return "新工作区"
    normalized = unicodedata.normalize("NFKC", raw)
    digest = hashlib.md5(raw.encode("utf-8")).hexdigest()[:8]
    safe = re.sub(r'[<>:"/\\|?*\x00-\x1f]+', "_", normalized)
    safe = re.sub(r"\s+", "_", safe)
    safe = re.sub(r"_+", "_", safe).strip(" ._")[:48].strip(" ._")
    if not safe:
        return f"workspace_{digest}"
    if re.fullmatch(r"(?i:con|prn|aux|nul|com[1-9]|lpt[1-9])", safe):
        return f"{safe}_{digest[:4]}"
    return safe


def runtime_root_for_workspace(name: str, project_runtime_dir: Path) -> Path:
    return project_runtime_dir / slugify_workspace_name(name)


def detect_profile_from_payload(
    data: dict[str, Any],
    *,
    profile_daily: str = "daily",
    profile_hourly: str = "hourly",
) -> str:
    explicit = str(data.get("率定模式", "")).strip().lower()
    if explicit in {profile_daily, profile_hourly}:
        return explicit
    try:
        numeric_step = float(data.get("时间步长_小时", 24.0))
    except Exception:
        numeric_step = 24.0
    return profile_hourly if numeric_step <= 1.5 else profile_daily


def detect_object_type(
    data: dict[str, Any],
    *,
    object_regression: str = "regression_validation",
    object_interbasin: str = "interbasin_with_boundary",
    object_full_upstream: str = "full_upstream_basin",
) -> str:
    explicit = str(data.get("项目对象", "")).strip().lower()
    if explicit in {object_regression, object_interbasin, object_full_upstream}:
        return explicit
    boundary = dict(data.get("边界条件", {}) or {})
    if boundary.get("上游边界入流_csv"):
        return object_interbasin
    return object_full_upstream


def build_empty_workspace(name: str = "新流域工作区", profile: str = "", context: WorkspaceCatalogContext | None = None) -> dict[str, Any]:
    if context is None:
        raise ValueError("build_empty_workspace requires a WorkspaceCatalogContext.")
    selected_profile = profile or context.profile_daily
    glacier_default = str(context.builtin_glacier_shp.resolve()) if context.builtin_glacier_shp.exists() else ""
    return {
        "_说明": [
            "HBV-Studio 生成的工作区配置。",
            "导入 shp + 观测径流后，系统会自动补齐范围、时间和默认 DEM。",
        ],
        "项目对象": context.object_full_upstream,
        "率定模式": selected_profile,
        "目标函数模式": "auto",
        "任务时段模式": context.time_basis_continuous,
        "运行目录": str(runtime_root_for_workspace(name, context.project_runtime_dir)),
        "流域名称": name,
        "流域编号": slugify_workspace_name(name),
        "流域边界_shp": "",
        "DEM_tif": str(context.builtin_dem.resolve()),
        context.observed_flow_key: "",
        "观测口径模式": "full_year",
        "事件资料模式": {
            "启用": False,
            "事件窗口资料": False,
            "事件表路径": "",
            "允许事件间断": True,
            "初始条件策略": "event_warmup",
        },
        "洪水事件率定": {
            "启用": False,
            "事件窗口资料": False,
            "事件表路径": "",
            "模式": "diagnostic",
        },
        "边界条件": {
            "上游边界入流_csv": "",
            "时间字段": "date",
            "流量字段": "flow",
            "缺失填补": "preserve_missing",
        },
        "气象策略": {
            "降水方案": "grid_only",
            "station_correction_algorithm": "occurrence_amount_v2",
            "降水来源": "era5",
            "降水源": "era5",
            "站点降水_csv": "",
            "站点信息_csv": "",
            "原始小时降水目录": "",
            "自带降水tif目录": "",
            "温度来源": "era5",
            "自带温度tif目录": "",
            "潜在蒸散发来源": "era5_fao56",
            "自带蒸散发tif目录": "",
        },
        "区间评价": {
            "目标约束启用": False,
            "目标约束权重": 0.15,
        },
        "冰川边界_shp": glacier_default,
        "范围_bbox": {"北": None, "西": None, "南": None, "东": None},
        "时间": {
            "开始年份": 2006,
            "结束年份": 2020,
            "预热开始": "",
            "预热结束": "",
            "率定开始": "",
            "率定结束": "",
            "验证开始": "",
            "验证结束": "",
        },
        "时间步长_小时": 24.0 if selected_profile == context.profile_daily else 1.0,
        "初始状态": dict(context.default_initial_state),
        "FAO56平均海拔_m": 4500.0,
        "默认降水源": "era5",
        "CFMAX分区阈值_m": 5000.0,
    }


def normalize_config_before_save(data: dict[str, Any], save_path: Path, context: WorkspaceCatalogContext) -> dict[str, Any]:
    config = dict(data)
    config.pop("_config_path", None)
    config = context.replace_placeholders(config)
    profile = detect_profile_from_payload(
        config,
        profile_daily=context.profile_daily,
        profile_hourly=context.profile_hourly,
    )
    object_type = detect_object_type(
        config,
        object_regression=context.object_regression,
        object_interbasin=context.object_interbasin,
        object_full_upstream=context.object_full_upstream,
    )
    config["项目对象"] = object_type
    config["率定模式"] = profile
    config["时间步长_小时"] = 1.0 if profile == context.profile_hourly else 24.0
    config["目标函数模式"] = context.normalize_objective_mode(config.get("目标函数模式", "auto"))
    config["观测口径模式"] = config.get("观测口径模式", "full_year") or "full_year"

    raw_time_basis = str(
        config.get("任务时段模式")
        or config.get("资料时段模式")
        or config.get("time_basis")
        or ""
    ).strip().lower()
    if raw_time_basis in {"event", "events", "event_window", "event_windows", "flood_event", "洪水事件", "事件窗口", "事件资料"}:
        config["任务时段模式"] = context.time_basis_event_windows
    else:
        config["任务时段模式"] = context.time_basis_continuous
    event_workflow = str(config.get("场次洪水工作流", "") or "").strip().lower()
    if event_workflow not in {"continuous", "continuous_events", "event_windows"}:
        event_workflow = "event_windows" if config["任务时段模式"] == context.time_basis_event_windows else "continuous"
    config["场次洪水工作流"] = event_workflow
    if not config.get("DEM_tif"):
        config["DEM_tif"] = str(context.builtin_dem.resolve())
    if (not str(config.get("冰川边界_shp", "")).strip()) and context.builtin_glacier_shp.exists():
        config["冰川边界_shp"] = str(context.builtin_glacier_shp.resolve())

    time_cfg = dict(config.get("时间", {}))
    step_hours = context.normalize_time_step_hours(config.get("时间步长_小时", 24.0))
    if time_cfg.get("预热开始") and time_cfg.get("率定开始") and (not time_cfg.get("预热结束")):
        try:
            time_values = {
                "预热开始": pd.to_datetime(time_cfg["预热开始"]),
                "率定开始": pd.to_datetime(time_cfg["率定开始"]),
            }
            warmup_end = expected_warmup_end(time_values, step_hours)
            if warmup_end is not None and time_values["预热开始"] <= warmup_end:
                time_cfg["预热结束"] = format_timestamp_for_display(warmup_end, step_hours)
        except Exception:
            pass
    parsed_starts = [pd.to_datetime(value) for value in [time_cfg.get("预热开始"), time_cfg.get("率定开始")] if value]
    parsed_ends = [pd.to_datetime(value) for value in [time_cfg.get("验证结束"), time_cfg.get("率定结束")] if value]
    if parsed_starts:
        time_cfg["开始年份"] = int(min(parsed_starts).year)
    if parsed_ends:
        time_cfg["结束年份"] = int(max(parsed_ends).year)
    config["时间"] = time_cfg

    bbox = context.fill_bbox_from_shp(config.get("流域边界_shp", ""))
    if bbox is not None:
        config["范围_bbox"] = bbox

    if not config.get("流域编号"):
        config["流域编号"] = save_path.stem
    if not config.get("流域名称"):
        config["流域名称"] = save_path.stem

    init_state = dict(config.get("初始状态", {}) or {})
    for key, value in context.default_initial_state.items():
        init_state.setdefault(key, value)
    config["初始状态"] = init_state

    boundary = dict(config.get("边界条件", {}))
    boundary.setdefault("上游边界入流_csv", "")
    boundary.setdefault("时间字段", "date")
    boundary.setdefault("流量字段", "flow")
    boundary.setdefault("缺失填补", "preserve_missing")
    config["边界条件"] = boundary

    event_mode = dict(config.get("事件资料模式", {}) or {})
    flood_events = dict(config.get("洪水事件率定", {}) or {}) if isinstance(config.get("洪水事件率定", {}), dict) else {}
    event_file = str(
        event_mode.get("事件表路径")
        or event_mode.get("events_file")
        or flood_events.get("事件表路径")
        or flood_events.get("events_file")
        or ""
    ).strip()
    if event_file:
        event_mode["事件表路径"] = event_file
        flood_events["事件表路径"] = event_file
    if event_workflow == "event_windows":
        event_mode["启用"] = True
        event_mode["事件窗口资料"] = True
        event_mode.setdefault("允许事件间断", True)
        event_mode.setdefault("初始条件策略", "event_warmup")
        flood_events.setdefault("启用", True)
        flood_events["事件窗口资料"] = True
        flood_events.setdefault("模式", "diagnostic")
    elif event_workflow == "continuous_events":
        event_mode["启用"] = False
        event_mode["事件窗口资料"] = False
        event_mode["允许事件间断"] = False
        event_mode["初始条件策略"] = "continuous_state"
        flood_events["启用"] = True
        flood_events["事件窗口资料"] = False
        flood_events["模式"] = "objective"
        flood_events["作为目标函数"] = True
        flood_events["初始条件策略"] = "continuous_state"
        flood_events.setdefault("边界汇流预热天数", 14.0)
        flood_events.setdefault("目标事件类型", ["calibration"])
        config["目标函数模式"] = "flood_event_calibration_v1"
    else:
        event_mode.setdefault("启用", False)
        event_mode.setdefault("事件窗口资料", False)
    config["事件资料模式"] = event_mode
    config["洪水事件率定"] = flood_events

    meteo = dict(config.get(context.meteo_key, {}))
    meteo.setdefault(METEO_PRECIP_MODE_KEY, "grid_only")
    source_value = configured_precip_source(config)
    meteo[context.meteo_precip_source_key] = source_value
    meteo[context.meteo_precip_source_legacy_key] = source_value
    config["默认降水源"] = source_value
    meteo.setdefault(METEO_STATION_PREC_KEY, "")
    meteo.setdefault(METEO_STATION_META_KEY, "")
    meteo.setdefault(METEO_HOURLY_PREC_DIR_KEY, "")
    meteo.setdefault(METEO_TEMP_SOURCE_KEY, "era5")
    meteo.setdefault(METEO_CUSTOM_TEMP_DIR_KEY, "")
    meteo.setdefault(METEO_CUSTOM_PREC_DIR_KEY, "")
    meteo.setdefault(METEO_PET_SOURCE_KEY, "era5_fao56")
    meteo.setdefault(METEO_CUSTOM_PET_DIR_KEY, "")
    legacy_temp = {"era5_land": "era5", "local_or_era5_hourly": "era5"}
    legacy_pet = {"era5_land_fao56": "era5_fao56", "hourly_era5_or_external": "era5_fao56"}
    if meteo[METEO_TEMP_SOURCE_KEY] in legacy_temp:
        meteo[METEO_TEMP_SOURCE_KEY] = legacy_temp[meteo[METEO_TEMP_SOURCE_KEY]]
    if meteo[METEO_PET_SOURCE_KEY] in legacy_pet:
        meteo[METEO_PET_SOURCE_KEY] = legacy_pet[meteo[METEO_PET_SOURCE_KEY]]
    config[context.meteo_key] = meteo

    for key in (*CONFIG_PATH_FIELDS, context.observed_flow_key):
        if config.get(key):
            config[key] = context.to_portable_path(config[key])
    boundary = dict(config.get("边界条件", {}))
    for key in BOUNDARY_PATH_FIELDS:
        if boundary.get(key):
            boundary[key] = context.to_portable_path(boundary[key])
    config["边界条件"] = boundary
    event_mode = dict(config.get("事件资料模式", {}))
    for key in EVENT_PATH_FIELDS:
        if event_mode.get(key):
            event_mode[key] = context.to_portable_path(event_mode[key])
    config["事件资料模式"] = event_mode
    flood_events = dict(config.get("洪水事件率定", {})) if isinstance(config.get("洪水事件率定", {}), dict) else {}
    for key in EVENT_PATH_FIELDS:
        if flood_events.get(key):
            flood_events[key] = context.to_portable_path(flood_events[key])
    config["洪水事件率定"] = flood_events
    meteo = dict(config.get(context.meteo_key, {}))
    for key in METEO_PATH_FIELDS:
        if meteo.get(key):
            meteo[key] = context.to_portable_path(meteo[key])
    config[context.meteo_key] = meteo

    for key in WIZARD_STALE_KEYS:
        config.pop(key, None)

    return config


def suggest_time_windows(
    start_date: pd.Timestamp,
    end_date: pd.Timestamp,
    profile: str,
    *,
    profile_daily: str = "daily",
    profile_hourly: str = "hourly",
) -> dict[str, str]:
    start_ts = pd.to_datetime(start_date)
    end_ts = pd.to_datetime(end_date)
    date_format = "%Y-%m-%d %H:%M" if profile == profile_hourly else "%Y-%m-%d"
    if end_ts <= start_ts:
        return {
            "预热开始": start_ts.strftime(date_format),
            "预热结束": start_ts.strftime(date_format),
            "率定开始": start_ts.strftime(date_format),
            "率定结束": end_ts.strftime(date_format),
            "验证开始": end_ts.strftime(date_format),
            "验证结束": end_ts.strftime(date_format),
        }

    if profile == profile_daily:
        start_is_year_start = (start_ts.month, start_ts.day) == (1, 1)
        end_is_year_end = (end_ts.month, end_ts.day) == (12, 31)
        first_full_year = start_ts.year if start_is_year_start else (start_ts.year + 1)
        last_full_year = end_ts.year if end_is_year_end else (end_ts.year - 1)
        full_year_count = last_full_year - first_full_year + 1
        if full_year_count >= 3:
            warmup_years = 2 if full_year_count >= 12 else 1
            valid_years = 3 if full_year_count >= 8 else (2 if full_year_count >= 5 else 1)
            while (full_year_count - warmup_years - valid_years) < 1:
                if valid_years > 1:
                    valid_years -= 1
                elif warmup_years > 1:
                    warmup_years -= 1
                else:
                    break
            if (full_year_count - warmup_years - valid_years) >= 1:
                warmup_end = pd.Timestamp(year=first_full_year + warmup_years - 1, month=12, day=31)
                calib_start = warmup_end + pd.Timedelta(days=1)
                valid_start = pd.Timestamp(year=last_full_year - valid_years + 1, month=1, day=1)
                calib_end = valid_start - pd.Timedelta(days=1)
                if calib_start <= calib_end:
                    return {
                        "预热开始": start_ts.strftime(date_format),
                        "预热结束": warmup_end.strftime(date_format),
                        "率定开始": calib_start.strftime(date_format),
                        "率定结束": calib_end.strftime(date_format),
                        "验证开始": valid_start.strftime(date_format),
                        "验证结束": end_ts.strftime(date_format),
                    }

    total_days = max((end_ts - start_ts).days, 1)
    if total_days < 365:
        warmup_end = start_ts
    elif total_days < 1095:
        warmup_end = start_ts + pd.DateOffset(years=1) - pd.Timedelta(days=1)
    else:
        warmup_end = start_ts + pd.DateOffset(years=2) - pd.Timedelta(days=1)
    remaining_start = warmup_end + pd.Timedelta(days=1)
    remaining_days = max((end_ts - remaining_start).days, 1)
    calib_end = remaining_start + pd.Timedelta(days=int(remaining_days * 0.7))
    valid_start = calib_end + pd.Timedelta(days=1)
    if valid_start > end_ts:
        valid_start = end_ts
        calib_end = max(remaining_start, valid_start - pd.Timedelta(days=1))
    return {
        "预热开始": start_ts.strftime(date_format),
        "预热结束": warmup_end.strftime(date_format),
        "率定开始": remaining_start.strftime(date_format),
        "率定结束": calib_end.strftime(date_format),
        "验证开始": valid_start.strftime(date_format),
        "验证结束": end_ts.strftime(date_format),
    }


def template_files(context: WorkspaceCatalogContext) -> list[Path]:
    if not context.template_dir.exists():
        return []
    files = {path.resolve(): path for path in context.template_dir.glob("*.json")}
    files.update({path.resolve(): path for path in context.template_dir.glob("*.template.json")})
    return sorted(files.values())


def list_templates(context: WorkspaceCatalogContext) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    for path in template_files(context):
        try:
            raw = context.read_json_file(path)
            resolved = context.replace_placeholders(raw)
            meta = raw.get("_studio_template", {})
            runtime_root = resolved.get("运行目录", "")
            runtime_path = Path(runtime_root) if runtime_root else None
            asset_ok = True
            for key in ("流域边界_shp", context.observed_flow_key):
                candidate = resolved.get(key, "")
                candidate_path = None
                if candidate:
                    try:
                        candidate_path = context.resolve_any_path(str(candidate), must_exist=False)
                    except Exception:
                        candidate_path = Path(str(candidate)).expanduser()
                if candidate and (candidate_path is None or not candidate_path.exists()):
                    asset_ok = False
                    break
            results.append(
                {
                    "id": meta.get("id", path.stem),
                    "title": meta.get("title", path.stem),
                    "description": meta.get("description", ""),
                    "calibration_mode": resolved.get("率定模式", context.profile_daily),
                    "object_type": detect_object_type(
                        resolved,
                        object_regression=context.object_regression,
                        object_interbasin=context.object_interbasin,
                        object_full_upstream=context.object_full_upstream,
                    ),
                    "path": str(path.resolve()),
                    "display_path": context.to_display_path(path),
                    "builtin": bool(meta.get("builtin", True)),
                    "runtime_root": str(runtime_path) if runtime_path else "",
                    "runtime_ready": bool(runtime_path and runtime_path.exists()),
                    "assets_ready": asset_ok,
                    "sync_hint": meta.get("sync_hint", ""),
                }
            )
        except Exception:
            continue
    return results


def find_template(template_id: str, context: WorkspaceCatalogContext) -> Path:
    for path in template_files(context):
        raw = context.read_json_file(path)
        meta = raw.get("_studio_template", {})
        if meta.get("id") == template_id or path.stem == template_id:
            return path
    raise FileNotFoundError(template_id)


def instantiate_template(payload: dict[str, Any], context: WorkspaceCatalogContext) -> dict[str, Any]:
    template_id = str(payload.get("template_id", "")).strip()
    if not template_id:
        raise ValueError("缺少模板 ID。")
    target_name = str(payload.get("workspace_name", "")).strip() or "新流域工作区"
    template_path = find_template(template_id, context)
    raw = context.replace_placeholders(context.read_json_file(template_path))
    profile = context.resolve_profile(raw, None)
    config = normalize_config_before_save(raw, context.default_workspace_path, context)
    if (not str(config.get("冰川边界_shp", "")).strip()) and context.builtin_glacier_shp.exists():
        config["冰川边界_shp"] = str(context.builtin_glacier_shp.resolve())
    if detect_object_type(
        config,
        object_regression=context.object_regression,
        object_interbasin=context.object_interbasin,
        object_full_upstream=context.object_full_upstream,
    ) != context.object_regression:
        config["流域名称"] = target_name
        config["流域编号"] = slugify_workspace_name(target_name)
    if template_id == "blank-workspace":
        config["运行目录"] = str(runtime_root_for_workspace(target_name, context.project_runtime_dir))
    workspace_path = context.workspace_dir / f"{slugify_workspace_name(target_name)}.json"
    context.write_json_file(workspace_path, normalize_config_before_save(config, workspace_path, context))
    return {
        "workspace_path": str(workspace_path.resolve()),
        "config": context.read_json_file(workspace_path),
        "template_id": template_id,
        "profile": profile,
    }


def _workspace_file_signature(paths: list[Path]) -> tuple[tuple[str, int, int], ...]:
    signature: list[tuple[str, int, int]] = []
    for path in paths:
        try:
            stat = path.stat()
        except (FileNotFoundError, PermissionError, OSError):
            continue
        signature.append(
            (
                str(path.resolve()).lower(),
                int(getattr(stat, "st_mtime_ns", int(stat.st_mtime * 1e9))),
                int(stat.st_size),
            )
        )
    return tuple(signature)


def list_workspaces(context: WorkspaceCatalogContext) -> list[dict[str, Any]]:
    context.workspace_dir.mkdir(parents=True, exist_ok=True)
    paths = sorted(context.workspace_dir.glob("*.json"))
    signature = _workspace_file_signature(paths)
    cache_key = str(context.workspace_dir.resolve()).lower()
    now = time.monotonic()
    with _WORKSPACE_LIST_CACHE_LOCK:
        cached = _WORKSPACE_LIST_CACHE.get(cache_key)
        if cached and cached[0] == signature and now - cached[1] <= _WORKSPACE_LIST_CACHE_TTL_SECONDS:
            return copy.deepcopy(cached[2])

    results: list[dict[str, Any]] = []
    for path in paths:
        try:
            data = context.read_runtime_config(path)
            workflow = context.workspace_workflow_summary(str(path.resolve()), quick=True)
        except Exception:
            continue
        profile = context.resolve_profile(data, None)
        runtime_root = str(data.get("运行目录", "")).strip()
        results.append(
            {
                "name": path.stem,
                "path": str(path.resolve()),
                "display_path": context.to_display_path(path),
                "flow_name": data.get("流域名称", path.stem),
                "flow_id": data.get("流域编号", path.stem),
                "object_type": detect_object_type(
                    data,
                    object_regression=context.object_regression,
                    object_interbasin=context.object_interbasin,
                    object_full_upstream=context.object_full_upstream,
                ),
                "calibration_mode": profile,
                "time_step_hours": context.normalize_time_step_hours(data.get("时间步长_小时", 24.0)),
                "workspace_root": runtime_root,
                "runtime_display_path": (context.to_display_path(Path(runtime_root)) if runtime_root else ""),
                "workflow": workflow,
                "updated_at": path.stat().st_mtime,
            }
        )
    sorted_results = sorted(results, key=lambda item: item["updated_at"], reverse=True)
    with _WORKSPACE_LIST_CACHE_LOCK:
        _WORKSPACE_LIST_CACHE[cache_key] = (signature, time.monotonic(), copy.deepcopy(sorted_results))
    return sorted_results


def load_workspace_config(path_value: str, context: WorkspaceCatalogContext) -> tuple[Path, dict[str, Any]]:
    path = context.resolve_any_path(path_value, must_exist=True)
    return path, context.read_runtime_config(path)


def delete_workspace(path_value: str, context: WorkspaceCatalogContext) -> dict[str, Any]:
    path = context.resolve_any_path(path_value, must_exist=True)
    context.ensure_within(context.workspace_dir, path)
    name = path.stem
    path.unlink()
    return {"deleted": True, "name": name, "path": str(path)}


def create_workspace_from_import(payload: dict[str, Any], context: WorkspaceCatalogContext) -> dict[str, Any]:
    basin_shp = str(payload.get("basin_shp", "")).strip()
    obs_csv = str(payload.get("obs_csv", "")).strip()
    calibration_mode = str(payload.get("calibration_mode", "")).strip().lower()
    object_type = str(payload.get("object_type", "")).strip().lower() or context.object_full_upstream
    if object_type not in {context.object_regression, context.object_interbasin, context.object_full_upstream}:
        object_type = context.object_full_upstream
    workspace_name = str(payload.get("workspace_name", "")).strip()
    prec_source = str(payload.get("prec_source", "era5")).strip()
    if not basin_shp:
        raise ValueError("缺少流域边界 shapefile。")
    if not obs_csv:
        raise ValueError("缺少观测径流文件。")
    shp_path = context.resolve_any_path(basin_shp, must_exist=True)
    obs_path = context.resolve_any_path(obs_csv, must_exist=True)
    obs_info = context.inspect_observed_csv(str(obs_path))
    suggested_mode = obs_info["suggested_calibration_mode"]
    profile = calibration_mode if calibration_mode in {context.profile_daily, context.profile_hourly} else suggested_mode
    start_date = pd.to_datetime(obs_info["start"])
    end_date = pd.to_datetime(obs_info["end"])
    bbox = context.fill_bbox_from_shp(str(shp_path))
    if bbox is None:
        raise ValueError("无法从 shapefile 中读取范围。")
    if not workspace_name:
        workspace_name = shp_path.stem

    windows = suggest_time_windows(
        start_date,
        end_date,
        profile,
        profile_daily=context.profile_daily,
        profile_hourly=context.profile_hourly,
    )

    cfmax_threshold = 5000.0
    if context.builtin_dem.exists():
        try:
            cfmax_threshold = context.suggest_cfmax_threshold(str(shp_path), str(context.builtin_dem))["suggested_threshold_m"]
        except Exception:
            pass

    config = build_empty_workspace(workspace_name, profile, context)
    config.update(
        {
            "_说明": [
                "由 HBV-Studio 导入流域向导自动生成。",
                f"源数据: basin={shp_path.name}, obs={obs_path.name}",
            ],
            "项目对象": object_type,
            "率定模式": profile,
            "运行目录": str(runtime_root_for_workspace(workspace_name, context.project_runtime_dir)),
            "流域名称": workspace_name,
            "流域编号": slugify_workspace_name(workspace_name),
            "流域边界_shp": str(shp_path),
            context.observed_flow_key: str(obs_path),
            "时间步长_小时": 24.0 if profile == context.profile_daily else 1.0,
            "默认降水源": prec_source,
            "FAO56平均海拔_m": cfmax_threshold,
            "CFMAX分区阈值_m": cfmax_threshold,
            "范围_bbox": bbox,
            "时间": {
                "开始年份": int(start_date.year),
                "结束年份": int(end_date.year),
                **windows,
            },
        }
    )
    meteo = dict(config.get(context.meteo_key, {}))
    meteo[context.meteo_precip_source_key] = prec_source
    meteo[context.meteo_precip_source_legacy_key] = prec_source
    config[context.meteo_key] = meteo
    workspace_path = context.workspace_dir / f"{slugify_workspace_name(workspace_name)}.json"
    config["流域边界_shp"] = str(context.stage_vector_shapefile(config, shp_path, role="basin", config_path=workspace_path))
    if str(config.get("冰川边界_shp", "")).strip():
        config["冰川边界_shp"] = str(
            context.stage_vector_shapefile(config, config["冰川边界_shp"], role="glacier", config_path=workspace_path)
        )
    config[context.observed_flow_key] = str(context.stage_observed_runoff_file(config, obs_path, config_path=workspace_path))
    context.write_json_file(workspace_path, normalize_config_before_save(config, workspace_path, context))
    return {
        "workspace_path": str(workspace_path.resolve()),
        "config": context.read_json_file(workspace_path),
        "obs_info": obs_info,
        "suggested_mode": suggested_mode,
        "profile": profile,
    }
