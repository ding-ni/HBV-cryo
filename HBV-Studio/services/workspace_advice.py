#!/usr/bin/env python
# -*- coding: utf-8 -*-
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable


@dataclass(frozen=True)
class WorkspaceAdviceContext:
    resolve_any_path: Callable[..., Path]
    read_runtime_config: Callable[[Path], dict[str, Any]]
    current_profile: Callable[[dict[str, Any]], str]
    resolve_precip_source: Callable[[dict[str, Any], Any], str]
    workspace_completeness: Callable[..., dict[str, Any]]
    validate_workspace_fields: Callable[..., dict[str, Any]]
    validate_forcing_bundle: Callable[..., dict[str, Any]]
    list_manual_presets: Callable[..., dict[str, Any]]
    detect_object_type: Callable[[dict[str, Any]], str]
    profile_daily: str
    profile_hourly: str
    object_interbasin: str
    daily_param_bounds_profile: str
    hourly_param_bounds_profile: str
    param_bounds_profile_labels: dict[str, str]


def _target_step_for_missing_message(message: str) -> int:
    target_step = 7
    if any(token in message for token in ("流域边界", "观测径流", "时间.", "时间顺序")):
        target_step = 2
    elif "上游边界入流" in message:
        target_step = 3
    elif any(token in message for token in ("站点", "自带降水", "自带温度", "自带蒸散发", "本地降水栅格", "本地气温栅格", "本地蒸散发栅格")):
        target_step = 4
    elif any(token in message for token in ("dem_1km", "dem_0p1deg", "flow_accumulation_masked", "DEM", "流量累积", "流域掩膜", "高程分区")):
        target_step = 5
    elif any(token in message for token in ("降水目录", "气温目录", "蒸散发目录", "时间覆盖", "时间戳", "气象驱动", "forcing", ".tif")):
        target_step = 6
    return target_step


def workspace_advice(config_path_raw: str, context: WorkspaceAdviceContext, precip_source: Any = None) -> dict[str, Any]:
    cfg_path = context.resolve_any_path(config_path_raw, must_exist=True)
    config = context.read_runtime_config(cfg_path)
    profile = context.current_profile(config)
    runtime_prec_source = context.resolve_precip_source(config, precip_source)
    comp = context.workspace_completeness(str(cfg_path), precip_source=runtime_prec_source)
    validation = context.validate_workspace_fields(str(cfg_path), stage="calibration", precip_source=runtime_prec_source)
    forcing = context.validate_forcing_bundle(config, profile, precip_source=runtime_prec_source)
    presets = context.list_manual_presets(str(cfg_path)).get("presets", [])
    cpu_total = max(1, int(os.cpu_count() or 4))
    expected_steps = int(forcing.get("expected_steps") or 0)
    object_type = context.detect_object_type(config)

    advice_items: list[dict[str, Any]] = []
    missing_text = "；".join(validation.get("missing", [])[:2]) if validation.get("missing") else ""
    if comp.get("ready_for_calibration"):
        headline = "输入已基本就绪，可以进入率定。"
    else:
        headline = f"当前还不能率定，优先补齐：{missing_text or '向导中的缺项'}"

    for message in validation.get("missing", []):
        target_step = _target_step_for_missing_message(message)
        advice_items.append(
            {
                "kind": "fix",
                "title": f"先完成第 {target_step} 步",
                "detail": message,
                "target_step": target_step,
            }
        )

    for message in validation.get("warnings", [])[:4]:
        advice_items.append(
            {
                "kind": "warn",
                "title": "需要注意",
                "detail": message,
                "target_step": None,
            }
        )

    heavy_profile = profile == context.profile_hourly or expected_steps >= 4000
    recommended_method = "mc_screen_de"
    recommended_workers = min(cpu_total, 4 if heavy_profile else 6)
    recommended_maxiter = 18 if heavy_profile else 24
    recommended_popsize = 6 if heavy_profile else 8
    recommended_mc_samples = 240 if heavy_profile else 300
    recommended_bound_shrink = 0.25 if presets else 0.0
    calibration_reasons: list[str] = []

    if presets:
        calibration_reasons.append("已存在手调参数集，可以在较小范围内继续精细搜索或局部精修。")
    else:
        calibration_reasons.append("尚无手调参数集，建议先在结果页按雪过程、土壤过程、产汇流顺序手调一轮。")
    if heavy_profile:
        calibration_reasons.append("当前时段较长或为小时尺度，自动率定负载会明显变大，建议先完成输入完整性检查并控制搜索规模。")
        recommended_method = "mc_screen_de"
    else:
        calibration_reasons.append("当前负载处于可控范围，适合先筛选再精修。")
    if object_type == context.object_interbasin:
        calibration_reasons.append("区间流域对边界入流更敏感，建议先核对边界入流过程是否合理。")
    if forcing.get("warnings"):
        calibration_reasons.append("虽然当前可率定，但气象驱动仍有警告，建议先在第 7 步确认时间覆盖。")

    advice_items.append(
        {
            "kind": "plan",
            "title": "推荐率定策略",
            "detail": "先完成输入完整性检查，再手动调参，最后自动率定。",
            "target_step": None,
        }
    )
    if not presets:
        advice_items.append(
            {
                "kind": "plan",
                "title": "推荐手调顺序",
                "detail": "先调雪过程，再调土壤过程，最后调产汇流。每次只改少量参数并重算观察变化。",
                "target_step": None,
            }
        )

    param_bounds_profile = (
        context.daily_param_bounds_profile
        if profile == context.profile_daily
        else context.hourly_param_bounds_profile
    )
    return {
        "headline": headline,
        "ready_for_calibration": bool(comp.get("ready_for_calibration", False)),
        "profile": profile,
        "object_type": object_type,
        "recommended_step": comp.get("next_step"),
        "recommendations": advice_items[:8],
        "calibration": {
            "method": recommended_method,
            "method_label": {
                "mc_screen_de": "快速筛选 + 精细搜索",
                "de": "精细搜索（差分进化）",
                "mc_only": "仅快速筛选",
            }[recommended_method],
            "workers": recommended_workers,
            "maxiter": recommended_maxiter,
            "popsize": recommended_popsize,
            "mc_samples": recommended_mc_samples,
            "init_bound_shrink": recommended_bound_shrink,
            "param_bounds_profile": param_bounds_profile,
            "param_bounds_profile_label": context.param_bounds_profile_labels.get(param_bounds_profile, ""),
            "reasons": calibration_reasons,
            "expected_steps": expected_steps,
            "has_manual_presets": bool(presets),
            "manual_preset_count": len(presets),
            "quick_test_first": False,
        },
    }
