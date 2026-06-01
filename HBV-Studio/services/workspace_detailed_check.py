#!/usr/bin/env python
# -*- coding: utf-8 -*-
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

import pandas as pd


@dataclass(frozen=True)
class WorkspaceDetailedCheckContext:
    resolve_path: Callable[..., Path]
    read_config: Callable[[Path], dict[str, Any]]
    current_profile: Callable[[dict[str, Any]], str]
    build_profile_paths: Callable[[dict[str, Any], str], dict[str, Any]]
    configured_precip_source: Callable[[dict[str, Any]], str]
    resolve_precip_source: Callable[..., str]
    detect_object_type: Callable[[dict[str, Any]], str]
    read_meteo_state: Callable[[dict[str, Any], str], dict[str, Any]]
    workspace_dem_path: Callable[..., Path]
    configured_dem_kind: Callable[[dict[str, Any]], str | None]
    read_json_file: Callable[[Path], dict[str, Any]]
    validate_forcing_bundle: Callable[..., dict[str, Any]]
    normalize_time_step_hours: Callable[[Any], float]
    resolve_config_related_path: Callable[[dict[str, Any], Any], Path | None]
    build_reasonableness_checks: Callable[..., list[dict[str, Any]]]
    format_timestamp_for_display: Callable[[pd.Timestamp, float], str]
    fmt_num: Callable[[Any, int, str], str]
    profile_labels: dict[str, str]
    object_labels: dict[str, str]
    object_interbasin: str
    observed_flow_key: str


def workspace_detailed_check(
    config_path_raw: str,
    context: WorkspaceDetailedCheckContext,
    precip_source: Any = None,
) -> dict[str, Any]:
    """Return a detailed summary of all input data for the workspace."""
    import numpy as np

    cfg_path = context.resolve_path(config_path_raw, must_exist=True)
    config = context.read_config(cfg_path)
    profile = context.current_profile(config)
    paths = context.build_profile_paths(config, profile)
    configured_source = context.configured_precip_source(config)
    source = context.resolve_precip_source(config, precip_source)
    object_type = context.detect_object_type(config)
    time_cfg = config.get("时间", {})
    meteo_state = context.read_meteo_state(config, profile)

    summary: list[dict[str, Any]] = []
    dem_stats: dict[str, Any] = {}

    summary.append({"group": "基本配置", "label": "率定模式", "value": context.profile_labels.get(profile, profile)})
    summary.append({"group": "基本配置", "label": "项目对象", "value": context.object_labels.get(object_type, object_type)})
    summary.append({"group": "基本配置", "label": "时间步长", "value": f"{config.get('时间步长_小时', 24)} 小时"})
    summary.append({"group": "基本配置", "label": "降水来源配置", "value": configured_source.upper()})
    summary.append({"group": "基本配置", "label": "运行降水源", "value": source.upper()})
    summary.append({"group": "基本配置", "label": "CFMAX 分区阈值", "value": f"{config.get('CFMAX分区阈值_m', '未设置')} m"})
    summary.append({"group": "基本配置", "label": "FAO56 平均海拔", "value": f"{config.get('FAO56平均海拔_m', '未设置')} m"})

    for key in ("预热开始", "预热结束", "率定开始", "率定结束", "验证开始", "验证结束"):
        val = time_cfg.get(key, "")
        summary.append({"group": "时间分段", "label": key, "value": val or "未设置", "ok": bool(val)})

    dem_path = context.workspace_dem_path(paths["gis_dir"], prefer=context.configured_dem_kind(config))
    if dem_path.exists():
        try:
            import rasterio
            with rasterio.open(dem_path) as src:
                arr = src.read(1).astype("float64")
                if src.nodata is not None:
                    arr[arr == src.nodata] = float("nan")
                valid = arr[np.isfinite(arr) & (arr > 0)]
                dem_stats = {
                    "min": float(np.nanmin(valid)) if valid.size else None,
                    "max": float(np.nanmax(valid)) if valid.size else None,
                    "median": float(np.nanmedian(valid)) if valid.size else None,
                    "valid_pixels": int(valid.size),
                    "resolution_text": f"{abs(src.res[0]):.6f}° x {abs(src.res[1]):.6f}°",
                }
                summary.append({"group": "地理数据", "label": "DEM 裁剪栅格", "value": "已生成", "ok": True})
                summary.append({"group": "地理数据", "label": "DEM 高程范围", "value": f"{float(np.nanmin(valid)):.0f} ~ {float(np.nanmax(valid)):.0f} m"})
                summary.append({"group": "地理数据", "label": "DEM 中位高程", "value": f"{float(np.nanmedian(valid)):.0f} m"})
                summary.append({"group": "地理数据", "label": "DEM 有效像元数", "value": f"{valid.size}"})
                summary.append({"group": "地理数据", "label": "DEM 分辨率", "value": f"{abs(src.res[0]):.6f}° x {abs(src.res[1]):.6f}°"})
        except Exception:
            summary.append({"group": "地理数据", "label": "DEM 裁剪栅格", "value": "已生成（读取详情失败）", "ok": True})
    else:
        summary.append({"group": "地理数据", "label": "DEM 裁剪栅格", "value": "缺失", "ok": False})

    flow_acc = Path(paths["gis_dir"]) / "flow_accumulation.tif"
    flow_masked = Path(paths["gis_dir"]) / "flow_accumulation_masked.tif"
    summary.append({"group": "地理数据", "label": "流量累积", "value": "已生成" if flow_acc.exists() else "缺失", "ok": flow_acc.exists()})
    summary.append({"group": "地理数据", "label": "流域掩膜", "value": "已生成" if flow_masked.exists() else "缺失", "ok": flow_masked.exists()})

    low_exists = (Path(paths["gis_dir"]) / "elevation_zone_low.tif").exists() or (Path(paths["gis_dir"]) / "elevation_zone_mid.tif").exists()
    high_exists = (Path(paths["gis_dir"]) / "elevation_zone_high.tif").exists()
    zone_count = int(low_exists) + int(high_exists)
    summary.append({"group": "地理数据", "label": "高程分区", "value": f"{zone_count}/2 已生成", "ok": zone_count == 2})

    glacier_shp = str(config.get("冰川边界_shp", "")).strip()
    glacier_mask = Path(paths["gis_dir"]) / "glacier_mask.tif"
    glacier_fraction = Path(paths["gis_dir"]) / "glacier_fraction.tif"
    glacier_mask_summary = {}
    glacier_mask_summary_path = Path(paths["gis_dir"]) / "glacier_mask_summary.json"
    if glacier_mask_summary_path.exists():
        try:
            glacier_mask_summary = context.read_json_file(glacier_mask_summary_path)
        except Exception:
            glacier_mask_summary = {}
    if glacier_shp:
        glacier_mode = str(glacier_mask_summary.get("glacier_mode", "") or "").strip().lower()
        glacier_mode_label = "0.1° 分数法" if glacier_mode == "fractional_subgrid" else ("1km 二值法" if glacier_mask.exists() else "待生成")
        summary.append(
            {
                "group": "地理数据",
                "label": "冰川掩膜（可选）",
                "value": (
                    str(glacier_mask_summary.get("message", "")).strip()
                    or ("已生成" if glacier_mask.exists() else "未生成（可选）")
                ),
                "ok": True if glacier_mask.exists() else None,
            }
        )
        summary.append(
            {
                "group": "地理数据",
                "label": "冰川表达模式",
                "value": glacier_mode_label,
                "ok": True if glacier_mask.exists() else None,
            }
        )
        if glacier_fraction.exists() or glacier_mode == "fractional_subgrid":
            summary.append(
                {
                    "group": "地理数据",
                    "label": "冰川分数栅格",
                    "value": "已生成" if glacier_fraction.exists() else "应生成但当前缺失",
                    "ok": True if glacier_fraction.exists() else False,
                }
            )
        true_glacier_area = glacier_mask_summary.get("true_glacier_area_km2")
        represented_area = glacier_mask_summary.get("represented_area_km2")
        area_bias_ratio = glacier_mask_summary.get("area_bias_ratio")
        if true_glacier_area is not None:
            summary.append({"group": "地理数据", "label": "真实冰川面积", "value": context.fmt_num(true_glacier_area, 3, " km²"), "ok": None})
        if represented_area is not None:
            summary.append({"group": "地理数据", "label": "表达冰川面积", "value": context.fmt_num(represented_area, 3, " km²"), "ok": None})
        if area_bias_ratio is not None:
            summary.append({"group": "地理数据", "label": "面积偏差倍率", "value": context.fmt_num(area_bias_ratio, 3, ""), "ok": None})
        glacier_elev_summary = {}
        glacier_elev_summary_path = Path(paths["gis_dir"]) / "glacier_elev_summary.json"
        if glacier_elev_summary_path.exists():
            try:
                glacier_elev_summary = context.read_json_file(glacier_elev_summary_path)
            except Exception:
                glacier_elev_summary = {}
        elev_status = str(glacier_elev_summary.get("status", "unknown")).strip().lower()
        if glacier_mode == "fractional_subgrid":
            if elev_status == "ok":
                mean_elev = glacier_elev_summary.get("area_weighted_elev_mean") or glacier_elev_summary.get("elev_mean")
                value = "已启用"
                if mean_elev is not None:
                    try:
                        value = f"已启用（面积加权均值 {float(mean_elev):.0f} m）"
                    except Exception:
                        pass
                summary.append({"group": "地理数据", "label": "冰川高程修正", "value": value, "ok": True})
            elif elev_status == "no_high_res_dem":
                summary.append({"group": "地理数据", "label": "冰川高程修正", "value": "未找到 1km 高分辨率 DEM", "ok": False})
            elif elev_status == "no_intersection":
                summary.append({"group": "地理数据", "label": "冰川高程修正", "value": "无有效高程像元", "ok": False})
            else:
                summary.append({"group": "地理数据", "label": "冰川高程修正", "value": "未启用（结果会被标 degraded）", "ok": False})
        elif glacier_mode == "binary_legacy":
            summary.append({"group": "地理数据", "label": "冰川高程修正", "value": "1km 无需此步", "ok": True})
    else:
        summary.append({"group": "地理数据", "label": "冰川掩膜（可选）", "value": "未启用（未提供冰川边界 shp）", "ok": None})

    forcing = context.validate_forcing_bundle(config, profile, precip_source=source)
    step_hours = context.normalize_time_step_hours(config.get("时间步长_小时", 24.0))
    if meteo_state:
        summary.append(
            {
                "group": "气象数据",
                "label": "气象驱动准备方式",
                "value": str(meteo_state.get("preparation_mode_label", "本地栅格导入")),
                "ok": True,
            }
        )
        completed_at = str(meteo_state.get("completed_at", "")).strip()
        if completed_at:
            summary.append({"group": "气象数据", "label": "最近导入时间", "value": completed_at, "ok": None})
        source_dirs = dict(meteo_state.get("source_dirs", {}) or {})
        target_dirs = dict(meteo_state.get("target_dirs", {}) or {})
        for key, label in (("prec", "降水"), ("temp", "气温"), ("evap", "蒸散发")):
            source_dir = str(source_dirs.get(key, "") or "").strip()
            target_dir = str(target_dirs.get(key, "") or "").strip()
            if source_dir:
                summary.append({"group": "气象数据", "label": f"{label}来源目录", "value": source_dir, "ok": None})
            if target_dir:
                summary.append({"group": "气象数据", "label": f"{label}工程目录", "value": target_dir, "ok": None})
    elif source == "custom_tif":
        summary.append(
            {
                "group": "气象数据",
                "label": "气象驱动准备方式",
                "value": "本地栅格模式（尚无导入记录，可能为历史数据）",
                "ok": None,
            }
        )
    if forcing["expected_steps"] is not None:
        summary.append({"group": "气象数据", "label": "资料口径", "value": str(forcing.get("time_basis_label", "连续时段")), "ok": True})
        summary.append({"group": "气象数据", "label": "期望时间步数", "value": str(forcing["expected_steps"]), "ok": True})
    event_windows = dict(forcing.get("event_windows") or {})
    if event_windows:
        summary.append(
            {
                "group": "气象数据",
                "label": "洪水事件窗口",
                "value": f"{int(event_windows.get('valid_event_count', 0) or 0)}/{int(event_windows.get('event_count', 0) or 0)} 场有效",
                "ok": int(event_windows.get("valid_event_count", 0) or 0) > 0,
            }
        )
    event_coverage = dict(forcing.get("event_forcing_coverage") or {})
    if event_coverage:
        summary.append(
            {
                "group": "气象数据",
                "label": "事件内气象覆盖",
                "value": f"{int(event_coverage.get('complete_event_count', 0) or 0)}/{int(event_coverage.get('event_count', 0) or 0)} 场完整",
                "ok": str(event_coverage.get("status", "")).lower() == "ok",
            }
        )
    for key, label in (("prec", "降水"), ("temp", "气温"), ("evap", "蒸散发")):
        item = forcing["directories"][key]
        summary.append(
            {
                "group": "气象数据",
                "label": f"{label}有效时间栅格",
                "value": f"{item['valid_time_steps']} / {item['total_files']}",
                "ok": item["ok"],
            }
        )
        if item["invalid_files"]:
            sample = "、".join(item["invalid_files"][:3])
            summary.append(
                {
                    "group": "气象数据",
                    "label": f"{label}非法文件名",
                    "value": f"{len(item['invalid_files'])} 个，例如 {sample}",
                    "ok": False,
                }
            )
        if item["duplicate_timestamps"]:
            first_ts, names = next(iter(item["duplicate_timestamps"].items()))
            summary.append(
                {
                    "group": "气象数据",
                    "label": f"{label}重复时间戳",
                    "value": f"{context.format_timestamp_for_display(first_ts, step_hours)} -> {'、'.join(names[:3])}",
                    "ok": False,
                }
            )
        if item["missing_steps"]:
            sample = "、".join(context.format_timestamp_for_display(ts, step_hours) for ts in item["missing_steps"][:3])
            summary.append(
                {
                    "group": "气象数据",
                    "label": f"{label}时间覆盖",
                    "value": f"缺少 {len(item['missing_steps'])} 个时间步，例如 {sample}",
                    "ok": False,
                }
            )
        elif forcing["expected_steps"] is not None:
            summary.append(
                {
                    "group": "气象数据",
                    "label": f"{label}时间覆盖",
                    "value": f"已覆盖{forcing.get('time_basis_label', '当前任务时段')} {forcing['expected_steps']} 个时间步",
                    "ok": item["ok"],
                }
            )

    shp = config.get("流域边界_shp", "")
    obs = config.get(context.observed_flow_key, "")
    shp_path = context.resolve_config_related_path(config, shp)
    obs_path = context.resolve_config_related_path(config, obs)
    summary.append({"group": "输入文件", "label": "流域边界 shp", "value": ("已配置" if shp and shp_path is not None and shp_path.exists() else "缺失"), "ok": bool(shp and shp_path is not None and shp_path.exists())})
    summary.append({"group": "输入文件", "label": "观测径流文件", "value": ("已配置" if obs and obs_path is not None and obs_path.exists() else "缺失"), "ok": bool(obs and obs_path is not None and obs_path.exists())})

    if object_type == context.object_interbasin:
        boundary_csv = str(dict(config.get("边界条件", {})).get("上游边界入流_csv", "")).strip()
        boundary_path = context.resolve_config_related_path(config, boundary_csv)
        summary.append({"group": "输入文件", "label": "上游边界入流 csv", "value": ("已配置" if boundary_csv and boundary_path is not None and boundary_path.exists() else "缺失"), "ok": bool(boundary_csv and boundary_path is not None and boundary_path.exists())})

    all_ok = all(item.get("ok") is not False for item in summary)
    reasonableness_checks = context.build_reasonableness_checks(
        config,
        forcing,
        dem_stats=dem_stats,
        glacier_mask_summary=glacier_mask_summary,
        glacier_mask_exists=glacier_mask.exists(),
        gis_dir=Path(paths["gis_dir"]),
    )

    return {
        "summary": summary,
        "reasonableness_checks": reasonableness_checks,
        "all_ok": all_ok,
        "profile": profile,
        "object_type": object_type,
    }
