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
    format_timestamp_for_display: Callable[[pd.Timestamp, float], str]
    resolve_objective_mode: Callable[..., str]
    count_matching: Callable[..., int]
    profile_daily: str
    profile_labels: dict[str, str]
    object_labels: dict[str, str]
    object_interbasin: str
    objective_mode_multi: str
    observed_flow_key: str


def sample_daily_raster_stats(
    directory: Path,
    *,
    max_samples_per_file: int = 2048,
    above_thresholds: tuple[float, ...] = (),
    below_thresholds: tuple[float, ...] = (),
) -> dict[str, Any]:
    import numpy as np
    import rasterio

    tif_files = sorted(directory.glob("*.tif")) if directory.exists() else []
    if not tif_files:
        return {"ok": False, "message": f"目录中没有 tif：{directory}", "path": str(directory)}

    sampled_values: list[Any] = []
    valid_pixels = 0
    zero_pixels = 0
    negative_pixels = 0
    above_counts = {threshold: 0 for threshold in above_thresholds}
    below_counts = {threshold: 0 for threshold in below_thresholds}
    global_min: float | None = None
    global_max: float | None = None
    valid_files = 0

    for tif_path in tif_files:
        with rasterio.open(tif_path) as src:
            arr = src.read(1).astype("float64")
            mask = np.isfinite(arr)
            if src.nodata is not None:
                mask &= arr != src.nodata
            values = arr[mask]
            if values.size == 0:
                continue
            valid_files += 1
            valid_pixels += int(values.size)
            zero_pixels += int(np.sum(values == 0))
            negative_pixels += int(np.sum(values < 0))
            for threshold in above_thresholds:
                above_counts[threshold] += int(np.sum(values > threshold))
            for threshold in below_thresholds:
                below_counts[threshold] += int(np.sum(values < threshold))
            local_min = float(np.min(values))
            local_max = float(np.max(values))
            global_min = local_min if global_min is None else min(global_min, local_min)
            global_max = local_max if global_max is None else max(global_max, local_max)
            if values.size <= max_samples_per_file:
                sampled_values.append(values.astype("float32", copy=False))
            else:
                stride = max(1, values.size // max_samples_per_file)
                sampled_values.append(values[::stride][:max_samples_per_file].astype("float32", copy=False))

    if valid_pixels <= 0 or not sampled_values:
        return {"ok": False, "message": f"没有读到有效像元：{directory}", "path": str(directory)}

    sample = np.concatenate(sampled_values)
    return {
        "ok": True,
        "path": str(directory),
        "valid_files": valid_files,
        "valid_pixels": valid_pixels,
        "zero_pixels": zero_pixels,
        "negative_pixels": negative_pixels,
        "min": global_min,
        "max": global_max,
        "p5": float(np.percentile(sample, 5)),
        "p50": float(np.percentile(sample, 50)),
        "p95": float(np.percentile(sample, 95)),
        "above_counts": above_counts,
        "below_counts": below_counts,
    }


def ratio_percent(numerator: int, denominator: int) -> float:
    return (float(numerator) / float(max(1, denominator))) * 100.0


def fmt_num(value: Any, digits: int = 2, suffix: str = "") -> str:
    if value is None:
        return "—"
    try:
        return f"{float(value):.{digits}f}{suffix}"
    except Exception:
        return "—"


def build_reasonableness_checks(
    config: dict[str, Any],
    forcing: dict[str, Any],
    context: WorkspaceDetailedCheckContext,
    *,
    dem_stats: dict[str, Any] | None = None,
    glacier_mask_summary: dict[str, Any] | None = None,
    glacier_mask_exists: bool = False,
    gis_dir: Path | str | None = None,
) -> list[dict[str, Any]]:
    checks: list[dict[str, Any]] = []
    profile = context.current_profile(config)
    if profile != context.profile_daily:
        return checks
    objective_mode = context.resolve_objective_mode(config, None, profile)

    directory_map = {
        "prec": Path(str(forcing.get("directories", {}).get("prec", {}).get("path", "") or "")),
        "temp": Path(str(forcing.get("directories", {}).get("temp", {}).get("path", "") or "")),
        "evap": Path(str(forcing.get("directories", {}).get("evap", {}).get("path", "") or "")),
    }

    def build_data_unavailable(title: str, message: str) -> dict[str, Any]:
        return {"title": title, "summary": message, "status": "warn", "items": [{"label": "状态", "value": message, "status": "warn"}]}

    precip_stats = sample_daily_raster_stats(directory_map["prec"], above_thresholds=(120.0, 250.0), below_thresholds=(-0.1,))
    if not precip_stats["ok"]:
        checks.append(build_data_unavailable("降水合理性检查", "当前还没有足够的降水运行栅格，暂不做数值检查。"))
    else:
        precip_status = "ok"
        precip_summary = "降水范围基本正常。"
        if int(precip_stats["below_counts"].get(-0.1, 0)) > 0:
            precip_status = "fail"
            precip_summary = "降水中出现了负值，建议先检查单位或写入过程。"
        elif float(precip_stats["max"] or 0.0) > 250.0:
            precip_status = "fail"
            precip_summary = "降水极大值过高，建议重点复查原始栅格和单位。"
        elif float(precip_stats["p95"] or 0.0) > 50.0 or int(precip_stats["above_counts"].get(120.0, 0)) > 0:
            precip_status = "warn"
            precip_summary = "降水整体可以继续用，但高值偏多，建议抽样复核。"
        checks.append(
            {
                "title": "降水合理性检查",
                "summary": precip_summary,
                "status": precip_status,
                "items": [
                    {"label": "最小值", "value": fmt_num(precip_stats["min"], 2, " mm/d"), "status": "fail" if int(precip_stats["below_counts"].get(-0.1, 0)) > 0 else "ok"},
                    {"label": "最大值", "value": fmt_num(precip_stats["max"], 2, " mm/d"), "status": "fail" if float(precip_stats["max"] or 0.0) > 250.0 else ("warn" if float(precip_stats["max"] or 0.0) > 120.0 else "ok")},
                    {"label": "P95", "value": fmt_num(precip_stats["p95"], 2, " mm/d"), "status": "warn" if float(precip_stats["p95"] or 0.0) > 50.0 else "ok"},
                    {"label": "负值比例", "value": fmt_num(ratio_percent(int(precip_stats["negative_pixels"]), int(precip_stats["valid_pixels"])), 3, "%"), "status": "fail" if int(precip_stats["below_counts"].get(-0.1, 0)) > 0 else "ok"},
                    {"label": "零值比例", "value": fmt_num(ratio_percent(int(precip_stats["zero_pixels"]), int(precip_stats["valid_pixels"])), 2, "%"), "status": "ok"},
                ],
            }
        )

    temp_stats = sample_daily_raster_stats(directory_map["temp"], above_thresholds=(45.0,), below_thresholds=(-60.0,))
    if not temp_stats["ok"]:
        checks.append(build_data_unavailable("气温合理性检查", "当前还没有足够的气温运行栅格，暂不做数值检查。"))
    else:
        temp_status = "ok"
        temp_summary = "气温范围基本正常。"
        if float(temp_stats["p50"] or 0.0) > 120.0:
            temp_status = "fail"
            temp_summary = "气温中位数异常偏高，疑似仍为 Kelvin，尚未转为 Celsius。"
        elif float(temp_stats["min"] or 0.0) < -60.0 or float(temp_stats["max"] or 0.0) > 45.0:
            temp_status = "fail"
            temp_summary = "气温极值超出高原项目常见范围，建议优先检查。"
        elif float(temp_stats["p5"] or 0.0) < -45.0 or float(temp_stats["p95"] or 0.0) > 30.0:
            temp_status = "warn"
            temp_summary = "气温整体可用，但冷热端偏激，建议抽样复核。"
        checks.append(
            {
                "title": "气温合理性检查",
                "summary": temp_summary,
                "status": temp_status,
                "items": [
                    {"label": "最小值", "value": fmt_num(temp_stats["min"], 2, " ℃"), "status": "fail" if float(temp_stats["min"] or 0.0) < -60.0 else ("warn" if float(temp_stats["p5"] or 0.0) < -45.0 else "ok")},
                    {"label": "最大值", "value": fmt_num(temp_stats["max"], 2, " ℃"), "status": "fail" if float(temp_stats["max"] or 0.0) > 45.0 else ("warn" if float(temp_stats["p95"] or 0.0) > 30.0 else "ok")},
                    {"label": "P5 / P95", "value": f"{fmt_num(temp_stats['p5'], 2, ' ℃')} / {fmt_num(temp_stats['p95'], 2, ' ℃')}", "status": "warn" if float(temp_stats["p5"] or 0.0) < -45.0 or float(temp_stats["p95"] or 0.0) > 30.0 else "ok"},
                    {"label": "中位数", "value": fmt_num(temp_stats["p50"], 2, " ℃"), "status": "fail" if float(temp_stats["p50"] or 0.0) > 120.0 else "ok"},
                    {"label": "温标判断", "value": "疑似 Kelvin" if float(temp_stats["p50"] or 0.0) > 120.0 else "看起来正常", "status": "fail" if float(temp_stats["p50"] or 0.0) > 120.0 else "ok"},
                ],
            }
        )

    evap_stats = sample_daily_raster_stats(directory_map["evap"], above_thresholds=(15.0, 25.0), below_thresholds=(-0.5,))
    if not evap_stats["ok"]:
        checks.append(build_data_unavailable("潜在蒸散发合理性检查", "当前还没有足够的潜在蒸散发运行栅格，暂不做数值检查。"))
    else:
        evap_status = "ok"
        evap_summary = "潜在蒸散发范围基本正常。"
        negative_ratio = ratio_percent(int(evap_stats["negative_pixels"]), int(evap_stats["valid_pixels"]))
        if float(evap_stats["min"] or 0.0) < -0.5 or negative_ratio > 1.0 or float(evap_stats["max"] or 0.0) > 25.0:
            evap_status = "fail"
            evap_summary = "潜在蒸散发存在明显异常值，建议优先检查计算结果。"
        elif float(evap_stats["p95"] or 0.0) > 10.0 or float(evap_stats["max"] or 0.0) > 15.0:
            evap_status = "warn"
            evap_summary = "潜在蒸散发整体可用，但高值偏大，建议抽样复核。"
        checks.append(
            {
                "title": "潜在蒸散发合理性检查",
                "summary": evap_summary,
                "status": evap_status,
                "items": [
                    {"label": "最小值", "value": fmt_num(evap_stats["min"], 2, " mm/d"), "status": "fail" if float(evap_stats["min"] or 0.0) < -0.5 else "ok"},
                    {"label": "最大值", "value": fmt_num(evap_stats["max"], 2, " mm/d"), "status": "fail" if float(evap_stats["max"] or 0.0) > 25.0 else ("warn" if float(evap_stats["max"] or 0.0) > 15.0 else "ok")},
                    {"label": "P95", "value": fmt_num(evap_stats["p95"], 2, " mm/d"), "status": "warn" if float(evap_stats["p95"] or 0.0) > 10.0 else "ok"},
                    {"label": "负值比例", "value": fmt_num(negative_ratio, 3, "%"), "status": "fail" if negative_ratio > 1.0 or float(evap_stats["min"] or 0.0) < -0.5 else "ok"},
                    {"label": "零值比例", "value": fmt_num(ratio_percent(int(evap_stats["zero_pixels"]), int(evap_stats["valid_pixels"])), 2, "%"), "status": "ok"},
                ],
            }
        )

    dem_info = dem_stats or {}
    dem_valid = int(dem_info.get("valid_pixels", 0) or 0)
    if dem_valid <= 0:
        checks.append(build_data_unavailable("DEM 合理性检查", "当前还没有可用 DEM，暂不做数值检查。"))
    else:
        dem_status = "ok"
        dem_summary = "DEM 范围基本正常。"
        dem_min = float(dem_info.get("min", 0.0) or 0.0)
        dem_max = float(dem_info.get("max", 0.0) or 0.0)
        dem_median = float(dem_info.get("median", 0.0) or 0.0)
        if dem_min < -500.0 or dem_max > 9000.0:
            dem_status = "fail"
            dem_summary = "DEM 极值明显异常，建议检查输入栅格。"
        elif dem_median < 1500.0:
            dem_status = "warn"
            dem_summary = "DEM 中位高程偏低，和当前高原项目认知不一致时要重点复查。"
        checks.append(
            {
                "title": "DEM 合理性检查",
                "summary": dem_summary,
                "status": dem_status,
                "items": [
                    {"label": "最小值", "value": fmt_num(dem_min, 0, " m"), "status": "fail" if dem_min < -500.0 else "ok"},
                    {"label": "最大值", "value": fmt_num(dem_max, 0, " m"), "status": "fail" if dem_max > 9000.0 else "ok"},
                    {"label": "中位高程", "value": fmt_num(dem_median, 0, " m"), "status": "warn" if dem_median < 1500.0 else "ok"},
                    {"label": "分辨率", "value": str(dem_info.get("resolution_text", "—")), "status": "ok"},
                    {"label": "有效像元数", "value": str(dem_valid), "status": "ok"},
                ],
            }
        )

    glacier_shp = str(config.get("冰川边界_shp", "")).strip()
    if not glacier_shp:
        checks.append(
            {
                "title": "冰川合理性检查",
                "summary": "当前未启用冰川输入。",
                "status": "ok",
                "items": [{"label": "状态", "value": "未启用", "status": "ok"}],
            }
        )
    else:
        glacier_mode = str((glacier_mask_summary or {}).get("glacier_mode", "") or "").strip().lower()
        glacier_pixels = int((glacier_mask_summary or {}).get("glacier_pixels", 0) or 0)
        glacier_area = float((glacier_mask_summary or {}).get("glacier_area_km2", 0.0) or 0.0)
        true_glacier_area = float((glacier_mask_summary or {}).get("true_glacier_area_km2", 0.0) or 0.0)
        represented_area = float((glacier_mask_summary or {}).get("represented_area_km2", glacier_area) or glacier_area or 0.0)
        area_bias_ratio = float((glacier_mask_summary or {}).get("area_bias_ratio", 0.0) or 0.0)
        nonzero_fraction_pixels = int((glacier_mask_summary or {}).get("nonzero_fraction_pixels", 0) or 0)
        glacier_ratio = ratio_percent(glacier_pixels, dem_valid) if dem_valid > 0 else 0.0
        glacier_status = "ok"
        glacier_mode_label = "0.1° 分数法" if glacier_mode == "fractional_subgrid" else "1km 二值法"
        glacier_summary = "冰川范围表达基本正常。"
        glacier_reference_count = context.count_matching(context.build_profile_paths(config, profile)["glacier_melt_dir"])
        if objective_mode == context.objective_mode_multi and glacier_reference_count > 0:
            glacier_constraint_value = "已纳入综合水文过程评价（径流过程特征 + 冰川面积占比复核；另有冰融水参考序列可供复核）"
            glacier_constraint_status = "ok"
        elif objective_mode == context.objective_mode_multi:
            glacier_constraint_value = "已纳入综合水文过程评价（径流过程特征 + 冰川面积占比复核）"
            glacier_constraint_status = "ok"
        else:
            if glacier_reference_count > 0:
                glacier_constraint_value = "仅采用径流拟合评价；冰融水参考序列仅作过程复核"
            else:
                glacier_constraint_value = "仅采用径流拟合评价"
            glacier_constraint_status = "warn"
        if not glacier_mask_exists:
            glacier_status = "fail"
            glacier_summary = "已经配置冰川 shp，但当前还没有生成冰川掩膜。"
        elif glacier_mode == "fractional_subgrid" and nonzero_fraction_pixels <= 0:
            glacier_status = "fail"
            glacier_summary = "当前是 0.1° 分数法，但没有有效冰川分数像元，建议先复核流域范围和冰川 shp。"
        elif glacier_mode == "fractional_subgrid" and represented_area <= 0.0 and true_glacier_area > 0.0:
            glacier_status = "fail"
            glacier_summary = "当前存在真实冰川面积，但分数化后的表达面积为 0，建议检查 DEM 与冰川 shp 的空间关系。"
        elif glacier_mode == "fractional_subgrid" and area_bias_ratio > 1.5:
            glacier_status = "warn"
            glacier_summary = "0.1° 分数法已经可用，但表达面积偏大，建议复核空间叠加结果。"
        elif glacier_mode == "fractional_subgrid" and 0.0 < area_bias_ratio < 0.5:
            glacier_status = "warn"
            glacier_summary = "0.1° 分数法已经可用，但表达面积偏小，建议结合流域位置再核一下。"
        elif glacier_ratio > 70.0:
            glacier_status = "fail"
            glacier_summary = "冰川面积占比异常偏大，建议检查冰川 shp 或流域范围。"
        elif glacier_ratio == 0.0 or glacier_ratio > 40.0:
            glacier_status = "warn"
            glacier_summary = "冰川面积占比需要复核，建议结合流域位置再确认一次。"
        elif glacier_constraint_status == "warn":
            glacier_status = "warn"
            glacier_summary = "冰川空间表达已生成，但当前评价口径较简化；裸冰融化分量应作为模型水源分解结果解读。"
        glacier_elev_summary_local = {}
        glacier_elev_summary_path_local = (Path(gis_dir) / "glacier_elev_summary.json") if gis_dir else None
        if glacier_elev_summary_path_local is not None and glacier_elev_summary_path_local.exists():
            try:
                glacier_elev_summary_local = context.read_json_file(glacier_elev_summary_path_local)
            except Exception:
                glacier_elev_summary_local = {}
        elev_status_val = str(glacier_elev_summary_local.get("status", "unknown")).strip().lower()
        if glacier_mode == "fractional_subgrid":
            if elev_status_val == "ok":
                mean_elev = glacier_elev_summary_local.get("area_weighted_elev_mean") or glacier_elev_summary_local.get("elev_mean")
                try:
                    elev_value_text = f"已启用（面积加权均值 {float(mean_elev):.0f} m）" if mean_elev is not None else "已启用"
                except Exception:
                    elev_value_text = "已启用"
                elev_item_status = "ok"
            elif elev_status_val == "no_high_res_dem":
                elev_value_text = "未找到 1km 高分辨率 DEM"
                elev_item_status = "fail"
            elif elev_status_val == "no_intersection":
                elev_value_text = "无有效高程像元"
                elev_item_status = "fail"
            else:
                elev_value_text = "未启用（结果会被标 degraded）"
                elev_item_status = "fail"
        else:
            elev_value_text = "1km 无需此步"
            elev_item_status = "ok"
        checks.append(
            {
                "title": "冰川合理性检查",
                "summary": glacier_summary,
                "status": glacier_status,
                "items": [
                    {"label": "冰川表达模式", "value": glacier_mode_label, "status": "ok" if glacier_mask_exists else "fail"},
                    {"label": "冰川像元数", "value": str(glacier_pixels), "status": "fail" if not glacier_mask_exists else ("warn" if glacier_ratio == 0.0 else "ok")},
                    {"label": "真实冰川面积", "value": fmt_num(true_glacier_area, 3, " km²"), "status": "ok" if glacier_mask_exists else "fail"},
                    {"label": "表达冰川面积", "value": fmt_num(represented_area, 3, " km²"), "status": "ok" if glacier_mask_exists else "fail"},
                    {"label": "面积偏差倍率", "value": fmt_num(area_bias_ratio, 3, ""), "status": "warn" if glacier_mode == "fractional_subgrid" and (area_bias_ratio > 1.5 or (0.0 < area_bias_ratio < 0.5)) else "ok"},
                    {"label": "面积占比", "value": fmt_num(glacier_ratio, 2, "%"), "status": "fail" if glacier_ratio > 70.0 else ("warn" if glacier_ratio == 0.0 or glacier_ratio > 40.0 else "ok")},
                    {"label": "分数像元数", "value": str(nonzero_fraction_pixels), "status": "warn" if glacier_mode == "fractional_subgrid" and nonzero_fraction_pixels <= 0 else "ok"},
                    {"label": "掩膜状态", "value": "已生成" if glacier_mask_exists else "未生成", "status": "ok" if glacier_mask_exists else "fail"},
                    {"label": "冰川分量约束", "value": glacier_constraint_value, "status": glacier_constraint_status},
                    {"label": "冰川高程修正", "value": elev_value_text, "status": elev_item_status},
                ],
            }
        )

    return checks


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
            summary.append({"group": "地理数据", "label": "真实冰川面积", "value": fmt_num(true_glacier_area, 3, " km²"), "ok": None})
        if represented_area is not None:
            summary.append({"group": "地理数据", "label": "表达冰川面积", "value": fmt_num(represented_area, 3, " km²"), "ok": None})
        if area_bias_ratio is not None:
            summary.append({"group": "地理数据", "label": "面积偏差倍率", "value": fmt_num(area_bias_ratio, 3, ""), "ok": None})
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
    mask_consistency = dict(forcing.get("mask_consistency") or {})
    if mask_consistency:
        checked_steps = int(mask_consistency.get("checked_steps", 0) or 0)
        examples = list(mask_consistency.get("examples", []) or [])
        if examples:
            first = dict(examples[0] or {})
            detail = (
                f"{first.get('time', '示例时步')} {first.get('variable', '变量')}"
                f"缺 {int(first.get('missing_vs_precip', 0) or 0)} 格"
            )
        else:
            detail = f"已抽查 {checked_steps} 个时间步"
        summary.append(
            {
                "group": "气象数据",
                "label": "P/T/PET有效像元一致性",
                "value": "一致" if mask_consistency.get("ok", True) else detail,
                "ok": bool(mask_consistency.get("ok", True)),
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
    reasonableness_checks = build_reasonableness_checks(
        config,
        forcing,
        context,
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
