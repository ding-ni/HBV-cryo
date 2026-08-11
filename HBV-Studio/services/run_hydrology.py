#!/usr/bin/env python
# -*- coding: utf-8 -*-
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable


HYDROLOGY_PROCESS_REVIEW_REPORT_NAME = "水文过程复核报告.md"
HYDROLOGY_DIAGNOSTIC_REPORT_NAME = HYDROLOGY_PROCESS_REVIEW_REPORT_NAME
LEGACY_HYDROLOGY_DIAGNOSTIC_REPORT_NAME = "水文诊断摘要.md"
CURRENT_DAILY_OBJECTIVE_FAMILY = "daily_unified_professional_v1"
FLOOD_EVENT_OBJECTIVE_FAMILY = "flood_event_calibration_v1"
HISTORICAL_OBJECTIVE_FAMILIES = {"weighted_daily_universal", "weighted_multi_criteria"}


@dataclass(frozen=True)
class RunHydrologyContext:
    to_display_path: Callable[[Path], str]


def safe_float(value: Any) -> float | None:
    try:
        if value is None:
            return None
        number = float(value)
    except (TypeError, ValueError):
        return None
    if number != number:
        return None
    return number


def metadata_objective_family(metadata: dict[str, Any]) -> str:
    return str(
        metadata.get("recorded_objective_family")
        or metadata.get("objective_family")
        or metadata.get("effective_objective_mode")
        or metadata.get("optimization", {}).get("effective_objective_mode")
        or metadata.get("optimization", {}).get("objective_mode")
        or metadata.get("objective_profile", {}).get("type")
        or metadata.get("objective", {}).get("type")
        or ""
    ).strip()


def percent_text(value: Any, digits: int = 1) -> str:
    num = safe_float(value)
    if num is None:
        return "—"
    return f"{num * 100:.{digits}f}%"


def component_basis_text(value: Any) -> str:
    key = str(value or "").strip()
    if key == "local_runoff_calibration_period":
        return "率定期本地径流口径，不含上游边界入流"
    if key in {"total_runoff_calibration_period", "calibration_period"}:
        return "率定期模拟总流量口径"
    return "率定期模拟径流口径"


def component_fraction_report(metadata: dict[str, Any]) -> dict[str, Any]:
    return dict(metadata.get("diagnostics", {}).get("component_fraction_report", {}) or {})


def local_component_fraction(report: dict[str, Any], key: str) -> Any:
    explicit = report.get(f"local_{key}_fraction")
    if explicit is not None:
        return explicit
    local = safe_float(report.get("local_runoff_fraction"))
    value = safe_float(report.get(f"{key}_fraction"))
    if local is None or value is None or abs(local) <= 1e-12:
        return None
    return value / local


def q_score_basis_text(metadata: dict[str, Any]) -> str:
    explicit = str(metadata.get("q_score_basis_label") or "").strip()
    if explicit:
        return explicit
    key = str(
        metadata.get("q_score_basis")
        or flood_event_evaluation(metadata).get("evaluation_basis")
        or ""
    ).strip()
    if key == "q_total":
        return "出口总流量（本地产流 + 上游边界入流）"
    if key == "q_local":
        return "区间本地产流"
    return "未记录"


def metric_text(value: Any, digits: int = 4, suffix: str = "") -> str:
    num = safe_float(value)
    if num is None:
        return "—"
    return f"{num:.{digits}f}{suffix}"


def flood_event_evaluation(metadata: dict[str, Any]) -> dict[str, Any]:
    raw = metadata.get("flood_event_evaluation")
    if isinstance(raw, dict):
        return raw
    diagnostics = dict(metadata.get("diagnostics", {}) or {})
    raw = diagnostics.get("flood_event_evaluation")
    return dict(raw) if isinstance(raw, dict) else {}


def flood_event_report_lines(metadata: dict[str, Any]) -> list[str]:
    evaluation = flood_event_evaluation(metadata)
    if not bool(evaluation.get("enabled")):
        return []
    events = list(evaluation.get("events", []) or [])
    lines = [
        "## 4. 场次洪水评价",
        "",
        f"- 场次洪水评价状态：{evaluation.get('status', '—')}",
        f"- 有效场次数：{evaluation.get('valid_event_count', 0)}/{evaluation.get('event_count', 0)}",
        f"- 场次洪水目标函数：{'已启用' if evaluation.get('objective_enabled') else '未启用，仅作诊断'}",
        "",
    ]
    if not events:
        lines.extend(["当前结果未写出可显示的场次洪水。", ""])
        return lines
    lines.extend([
        "| 场次洪水 | 用途 | 洪峰流量误差 | 峰现时间误差 | 洪量误差 | NSE | KGE | 高流量NSE | 高流量KGE | 退水过程误差 |",
        "| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |",
    ])
    for event in events:
        if not isinstance(event, dict):
            continue
        lines.append(
            "| "
            + " | ".join([
                str(event.get("name", "—") or "—"),
                str(event.get("type", "—") or "—"),
                metric_text(event.get("peak_error_percent"), 2, "%"),
                metric_text(event.get("peak_time_error_hours"), 1, " h"),
                metric_text(event.get("volume_error_percent"), 2, "%"),
                metric_text(event.get("nse")),
                metric_text(event.get("kge")),
                metric_text(event.get("high_flow_weighted_nse")),
                metric_text(event.get("high_flow_kge")),
                metric_text(event.get("recession_slope_error_percent"), 2, "%"),
            ])
            + " |"
        )
    lines.append("")
    return lines


def workflow_label_zh(metadata: dict[str, Any]) -> str:
    family = metadata_objective_family(metadata)
    workflow = str(metadata.get("calibration_workflow") or "").strip()
    workflow_status = str(metadata.get("calibration_workflow_status") or "").strip()
    if family in HISTORICAL_OBJECTIVE_FAMILIES or workflow_status == "historical":
        return "历史率定结果"
    if family == FLOOD_EVENT_OBJECTIVE_FAMILY:
        return "场次洪水评价"
    if workflow == "staged_calibration_v1" or workflow_status == "experimental":
        return "过程复核结果"
    if workflow == "single_pass" or not workflow:
        return "单流程参数率定"
    return "单流程参数率定"


def objective_label_zh(metadata: dict[str, Any]) -> str:
    family = metadata_objective_family(metadata)
    if family == FLOOD_EVENT_OBJECTIVE_FAMILY:
        return "场次洪水目标函数"
    if family == CURRENT_DAILY_OBJECTIVE_FAMILY:
        return "统一日尺度综合水文目标函数"
    if family in HISTORICAL_OBJECTIVE_FAMILIES:
        return "历史目标函数结果（仅兼容查看）"
    return "统一日尺度综合水文目标函数" if not family else "其他目标函数"


def flow_status_zh(metadata: dict[str, Any]) -> str:
    flow_guard = dict(metadata.get("objective_terms", {}).get("flow_guard", {}) or {})
    status = str(flow_guard.get("status") or "").strip()
    if status in {"ok", "pass"}:
        return "径流拟合达标"
    if status and status not in {"skipped", "skipped_insufficient_data"}:
        return "径流拟合未达标"
    metrics = dict(metadata.get("metrics", {}) or {})
    cal = dict(metrics.get("calibration", {}) or {})
    val = dict(metrics.get("validation", {}) or {})
    nse_cal = safe_float(cal.get("nse"))
    nse_val = safe_float(val.get("nse"))
    pbias_cal = safe_float(cal.get("pbias"))
    pbias_val = safe_float(val.get("pbias"))
    if (
        nse_cal is not None
        and nse_cal >= 0.60
        and (nse_val is None or nse_val >= 0.50)
        and (pbias_cal is None or abs(pbias_cal) <= 20.0)
        and (pbias_val is None or abs(pbias_val) <= 25.0)
    ):
        return "径流拟合达标"
    return "径流拟合未达标"


def ice_status_zh(metadata: dict[str, Any]) -> str:
    glacier_enabled = bool(metadata.get("optional_modules", {}).get("glacier", {}).get("enabled"))
    if not glacier_enabled:
        return "未启用冰川模块"
    component_report = component_fraction_report(metadata)
    boundary = component_report.get("boundary_inflow_fraction")
    local = component_report.get("local_runoff_fraction")
    rain = component_report.get("rain_fraction")
    snow = component_report.get("snow_fraction")
    ice = component_report.get("ice_fraction")
    if rain is None and snow is None and ice is None:
        return "已启用冰川模块"
    if boundary is not None or local is not None:
        return (
            f"边界 {percent_text(boundary)} / "
            f"区间 {percent_text(local)}"
        )
    return (
        f"降雨 {percent_text(rain)} / "
        f"融雪 {percent_text(snow)} / "
        f"裸冰 {percent_text(ice)}"
    )


def build_hydrology_summary(metadata: dict[str, Any], run_dir: Path, context: RunHydrologyContext) -> dict[str, Any]:
    report_path = run_dir / HYDROLOGY_DIAGNOSTIC_REPORT_NAME
    return {
        "workflow_label_zh": workflow_label_zh(metadata),
        "objective_label_zh": objective_label_zh(metadata),
        "flow_status_zh": flow_status_zh(metadata),
        "q_score_basis_zh": q_score_basis_text(metadata),
        "ice_status_zh": ice_status_zh(metadata),
        "diagnostics_detail_path": str(report_path.resolve(strict=False)),
        "diagnostics_detail_display_path": context.to_display_path(report_path),
        "diagnostics_detail_note": "水文模拟结果说明已保存至本地结果目录。",
    }


def hydrology_diagnostic_report_text(metadata: dict[str, Any], summary: dict[str, Any]) -> str:
    metrics = dict(metadata.get("metrics", {}) or {})
    cal = dict(metrics.get("calibration", {}) or {})
    val = dict(metrics.get("validation", {}) or {})
    component_report = component_fraction_report(metadata)
    boundary_fraction = component_report.get("boundary_inflow_fraction")
    local_fraction = component_report.get("local_runoff_fraction")
    has_boundary_components = boundary_fraction is not None or local_fraction is not None
    local_rain = local_component_fraction(component_report, "rain")
    local_snow = local_component_fraction(component_report, "snow")
    local_ice = local_component_fraction(component_report, "ice")

    lines = [
        "# 水文模拟结果说明",
        "",
        "本文件由 HBV-Studio 自动生成，记录本次率定运行的关键参数与结果。",
        "",
        "## 1. 运行信息",
        "",
        f"- 率定流程：{summary.get('workflow_label_zh', '—')}",
        f"- 评分标准：{summary.get('objective_label_zh', '—')}",
        f"- 径流评价口径：{summary.get('q_score_basis_zh', '—')}",
        f"- 结果时间：{metadata.get('run_time', '—')}",
        f"- 运行目录：{summary.get('diagnostics_detail_display_path', '—')}",
        "",
        "## 2. 径流拟合精度",
        "",
        f"- 率定期 NSE / KGE / PBIAS / RMSE：{metric_text(cal.get('nse'))} / {metric_text(cal.get('kge'))} / {metric_text(cal.get('pbias'), 2, '%')} / {metric_text(cal.get('rmse'))}",
        f"- 验证期 NSE / KGE / PBIAS / RMSE：{metric_text(val.get('nse'))} / {metric_text(val.get('kge'))} / {metric_text(val.get('pbias'), 2, '%')} / {metric_text(val.get('rmse'))}",
        f"- 综合判断：{summary.get('flow_status_zh', '—')}",
        "",
        "## 3. 出口流量构成与区间三水源",
        "",
        "对区间流域项目，出口模拟总流量由上游边界入流和区间本地产流共同组成；区间本地产流再按降雨产流、融雪径流、裸冰融化拆分。",
        "",
        "| 分量 | 占出口模拟总流量比例 |",
        "| --- | --- |",
        *(
            [
                f"| 上游边界入流 | {percent_text(boundary_fraction)} |",
                f"| 区间本地产流 | {percent_text(local_fraction)} |",
            ]
            if has_boundary_components
            else []
        ),
        f"| 降雨产流 | {percent_text(component_report.get('rain_fraction'))} |",
        f"| 融雪径流 | {percent_text(component_report.get('snow_fraction'))} |",
        f"| 裸冰融化 | {percent_text(component_report.get('ice_fraction'))} |",
        "",
        f"- 出口构成口径：{component_basis_text(component_report.get('evaluation_period'))}",
        "",
    ]
    if has_boundary_components:
        lines.extend(
            [
                "| 区间本地产流水源 | 占区间本地产流比例 |",
                "| --- | --- |",
                f"| 降雨产流 | {percent_text(local_rain)} |",
                f"| 融雪径流 | {percent_text(local_snow)} |",
                f"| 裸冰融化 | {percent_text(local_ice)} |",
                "",
            ]
        )
    event_lines = flood_event_report_lines(metadata)
    if event_lines:
        lines.extend(event_lines)
        remarks_title = "## 5. 备注"
    else:
        remarks_title = "## 4. 备注"
    lines.extend([
        remarks_title,
        "",
        "- 区间三水源比例为模型按 HBV 标准三水源追踪算法逐时步累加得到；上游边界入流来自边界条件，不再拆分为区间三水源。",
        "- 具体数值受流域冰川面积、气温递减率、降水相态划分和参数率定结果共同影响。",
        "",
    ])
    return "\n".join(lines)


def ensure_hydrology_diagnostic_report(
    run_dir: Path,
    metadata: dict[str, Any],
    summary: dict[str, Any],
    context: RunHydrologyContext,
) -> dict[str, Any]:
    report_path = run_dir / HYDROLOGY_DIAGNOSTIC_REPORT_NAME
    legacy_report_path = run_dir / LEGACY_HYDROLOGY_DIAGNOSTIC_REPORT_NAME
    updated_summary = dict(summary)
    try:
        report_text = hydrology_diagnostic_report_text(metadata, updated_summary)
        if not report_path.exists() or report_path.read_text(encoding="utf-8") != report_text:
            report_path.write_text(report_text, encoding="utf-8")
        if legacy_report_path.exists():
            legacy_report_path.write_text(report_text, encoding="utf-8")
        updated_summary["diagnostics_detail_path"] = str(report_path.resolve(strict=False))
        updated_summary["diagnostics_detail_display_path"] = context.to_display_path(report_path)
        updated_summary["diagnostics_report_status"] = "available"
    except Exception as exc:
        updated_summary["diagnostics_report_status"] = "write_failed"
        updated_summary["diagnostics_report_error"] = str(exc)
    return updated_summary
