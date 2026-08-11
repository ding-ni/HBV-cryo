#!/usr/bin/env python
# -*- coding: utf-8 -*-
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable


@dataclass(frozen=True)
class GlacierStatusContext:
    current_profile: Callable[[dict[str, Any]], str]
    build_profile_paths: Callable[[dict[str, Any], str], dict[str, Any]]
    read_json_file: Callable[[Path], dict[str, Any]]
    count_matching: Callable[[Any], int]
    workspace_dem_path: Callable[..., Path]
    configured_dem_kind: Callable[[dict[str, Any]], str | None]
    infer_dem_kind_from_raster: Callable[[str], str]
    resolve_objective_mode: Callable[[dict[str, Any], Any, str], str]
    objective_mode_multi: str
    objective_mode_flood_event: str


def check_glacier_mask(config: dict[str, Any], context: GlacierStatusContext) -> tuple[bool, str, int]:
    glacier_shp = str(config.get("冰川边界_shp", "")).strip()
    if not glacier_shp:
        return True, "未启用（未提供冰川边界 shp）", 0
    paths = context.build_profile_paths(config, context.current_profile(config))
    target = Path(paths["gis_dir"]) / "glacier_mask.tif"
    fraction_target = Path(paths["gis_dir"]) / "glacier_fraction.tif"
    summary_path = Path(paths["gis_dir"]) / "glacier_mask_summary.json"
    summary_message = ""
    glacier_mode = ""
    if summary_path.exists():
        try:
            summary = context.read_json_file(summary_path)
            summary_message = str(summary.get("message", "")).strip()
            glacier_mode = str(summary.get("glacier_mode", "")).strip().lower()
        except Exception:
            summary_message = ""
            glacier_mode = ""
    if target.exists():
        if glacier_mode == "fractional_subgrid":
            message = summary_message or (
                "已生成冰川分数栅格 glacier_fraction.tif，并同步生成兼容用 glacier_mask.tif。"
            )
        elif fraction_target.exists():
            message = summary_message or "已生成 glacier_mask.tif 和 glacier_fraction.tif。"
        else:
            message = summary_message or "冰川掩膜已生成"
        return True, message, 1
    return False, (summary_message or "未生成/可选"), 0


def check_glacier_reference(config: dict[str, Any], context: GlacierStatusContext) -> tuple[bool, str, int]:
    glacier_shp = str(config.get("冰川边界_shp", "")).strip()
    if not glacier_shp:
        return True, "未启用（未提供冰川边界 shp）", 0
    paths = context.build_profile_paths(config, context.current_profile(config))
    count = context.count_matching(paths["glacier_melt_dir"])
    return count > 0, f"冰川工程先验栅格数：{count}", count


def check_glacier_elev(config: dict[str, Any], context: GlacierStatusContext) -> tuple[bool, str, int]:
    glacier_shp = str(config.get("冰川边界_shp", "")).strip()
    if not glacier_shp:
        return True, "未启用（未提供冰川边界 shp）", 0
    paths = context.build_profile_paths(config, context.current_profile(config))
    summary_path = Path(paths["gis_dir"]) / "glacier_elev_summary.json"
    target = Path(paths["gis_dir"]) / "glacier_elev.tif"
    if summary_path.exists():
        try:
            summary = context.read_json_file(summary_path)
            status = str(summary.get("status", "unknown")).strip().lower()
            covered = int(summary.get("glacier_pixels_with_elev", 0) or 0)
            missing = int(summary.get("glacier_pixels_without_elev", 0) or 0)
            mean_elev = summary.get("area_weighted_elev_mean") or summary.get("elev_mean")
            if status == "ok" and target.exists():
                extra = f"，面积加权均值 {float(mean_elev):.0f} m" if mean_elev is not None else ""
                return True, f"已生成（冰川像元 {covered} 个有高程，{missing} 个缺失{extra}）", covered
            if status == "not_needed_1km":
                return True, "1km 方案无需此步", 0
            if status == "no_high_res_dem":
                return False, "未找到 1km 高分辨率 DEM，需手动配置 HBV_HIGH_RES_DEM", 0
            if status == "no_intersection":
                return False, "流域内冰川像元未匹配到高分辨率 DEM 有效值", 0
            if status == "no_glacier_shp":
                return True, "无冰川 shp，跳过", 0
            if status == "empty_glacier":
                return True, "冰川 shp 无有效几何，跳过", 0
            return False, f"状态异常：{status}", covered
        except Exception:
            pass
    if target.exists():
        return True, "glacier_elev.tif 已生成（无摘要）", 0
    return False, "未执行", 0


def glacier_elev_required(config: dict[str, Any], context: GlacierStatusContext) -> bool:
    glacier_shp = str(config.get("冰川边界_shp", "")).strip()
    if not glacier_shp:
        return False
    return context.infer_dem_kind_from_raster(str(config.get("DEM_tif", "") or "")) != "1km"


def glacier_formal_requirements(
    config: dict[str, Any],
    context: GlacierStatusContext,
    profile: str | None = None,
) -> dict[str, Any]:
    """Return the glacier status snapshot retained for older callers."""
    profile_name = str(profile or context.current_profile(config)).strip().lower() or context.current_profile(config)
    glacier_shp = str(config.get("冰川边界_shp", "")).strip()
    result: dict[str, Any] = {
        "enabled": bool(glacier_shp),
        "objective_mode": context.resolve_objective_mode(config, None, profile_name),
        "objective_is_multi": False,
        "objective_is_event": False,
        "reference_count": 0,
        "reference_ready": False,
        "dem_kind": "",
        "glacier_elev_required": False,
        "glacier_elev_ready": True,
        "glacier_elev_message": "未启用",
        "formal_preconditions_ready": True,
        "blocking_reasons": [],
        "diagnostic_notes": [],
    }
    result["objective_is_multi"] = result["objective_mode"] == context.objective_mode_multi
    result["objective_is_event"] = result["objective_mode"] == context.objective_mode_flood_event
    if not result["enabled"]:
        return result

    paths = context.build_profile_paths(config, profile_name)
    result["reference_count"] = context.count_matching(paths["glacier_melt_dir"])
    result["reference_ready"] = result["reference_count"] > 0
    dem_path = context.workspace_dem_path(paths["gis_dir"], prefer=context.configured_dem_kind(config))
    if dem_path.exists():
        try:
            result["dem_kind"] = context.infer_dem_kind_from_raster(str(dem_path))
        except Exception:
            result["dem_kind"] = context.configured_dem_kind(config)
    else:
        result["dem_kind"] = context.configured_dem_kind(config)
    result["glacier_elev_required"] = glacier_elev_required(config, context)
    if result["glacier_elev_required"]:
        elev_ready, elev_message, _ = check_glacier_elev(config, context)
        result["glacier_elev_ready"] = bool(elev_ready)
        result["glacier_elev_message"] = str(elev_message or "未生成")
    else:
        result["glacier_elev_ready"] = True
        result["glacier_elev_message"] = "1km 无需此步"

    notes: list[str] = []
    if result["glacier_elev_required"] and not result["glacier_elev_ready"]:
        notes.append(
            f"0.1° 工作区尚未生成 glacier_elev.tif：{result['glacier_elev_message']}；"
            "冰川子格温度递减将降级运行，冰川融水趋势可能偏高。"
        )
    if result["objective_is_event"]:
        notes.append("当前工作区启用场次洪水目标函数，应重点复核场次表、洪峰流量、峰现时间、洪量和退水过程。")
    elif not result["objective_is_multi"]:
        notes.append(
            "当前结果使用简化径流评价口径；启用冰川模块时，建议采用统一日尺度综合水文评价口径，并重点复核径流过程、冰川面积占比与冰雪融水分量。"
        )
    result["diagnostic_notes"] = notes
    return result
