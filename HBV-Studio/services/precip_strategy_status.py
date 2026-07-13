#!/usr/bin/env python
# -*- coding: utf-8 -*-
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable


@dataclass(frozen=True)
class PrecipStrategyStatusContext:
    meteo_key: str
    meteo_precip_mode_key: str
    current_profile: Callable[[dict[str, Any]], str]
    effective_precip_paths: Callable[..., tuple[Path, Path, str]]
    count_matching: Callable[[Any], int]
    read_json_file: Callable[[Path], dict[str, Any]]


def _fmt_float(value: Any, digits: int = 1, suffix: str = "") -> str:
    try:
        number = float(value)
    except Exception:
        return "未形成"
    if not (number == number):
        return "未形成"
    return f"{number:.{digits}f}{suffix}"


def _hydro_diagnostic_message(summary: dict[str, Any]) -> list[str]:
    hydro = dict(summary.get("hydrological_diagnostics", {}) or {})
    parts: list[str] = []
    stats = dict(summary.get("processing_stats", {}) or {})
    if stats:
        algorithm = str(stats.get("algorithm", "") or "").strip()
        if algorithm:
            parts.append(f"站点订正算法：{algorithm}")
        station_steps = int(stats.get("direct_station_corrected_steps", 0) or 0)
        rule_steps = int(stats.get("transfer_rule_applied_steps", 0) or 0)
        pass_steps = int(stats.get("pass_through_steps", 0) or 0)
        skipped_steps = int(stats.get("skipped_existing_steps", 0) or 0)
        if station_steps or rule_steps or pass_steps or skipped_steps:
            parts.append(
                "订正执行："
                f"实测站点 {station_steps} 时段；"
                f"规则外推 {rule_steps} 时段；"
                f"原样保留 {pass_steps} 时段；"
                f"已有输出跳过 {skipped_steps} 时段"
            )
    rules = dict(summary.get("transfer_rules", {}) or {})
    if rules:
        if bool(rules.get("available", False)):
            month_count = sum(
                1
                for item in dict(rules.get("monthly", {}) or {}).values()
                if int(dict(item).get("training_days", 0) or 0) > 0
            )
            parts.append(
                "站点订正规则："
                f"训练日 {int(rules.get('training_days', 0) or 0)}；"
                f"有效站点样本 {int(rules.get('valid_station_samples', 0) or 0)}；"
                f"独立月规则 {month_count}/12；"
                f"平均倍率 {_fmt_float(rules.get('global_ratio_mean'), 2)}"
            )
        elif str(rules.get("status", "") or "") not in {"", "not_requested"}:
            parts.append(f"站点订正规则：未形成（{rules.get('status')}）")
    if not hydro:
        return parts
    available = hydro.get("station_day_samples_available")
    total = hydro.get("station_day_samples_total")
    missing_rate = hydro.get("station_day_missing_rate_percent")
    if total:
        parts.append(f"站点日样本：{available}/{total}，缺测率 {_fmt_float(missing_rate, 1, '%')}")
    before = dict(hydro.get("station_point_before", {}) or {})
    after = dict(hydro.get("station_point_after", {}) or {})
    if before.get("sample_count") and after.get("sample_count"):
        parts.append(
            "站点处MAE："
            f"{_fmt_float(before.get('mae_mm'), 2, ' mm')}→{_fmt_float(after.get('mae_mm'), 2, ' mm')}；"
            "PBIAS："
            f"{_fmt_float(before.get('pbias_percent'), 1, '%')}→{_fmt_float(after.get('pbias_percent'), 1, '%')}"
        )
    basin_before = hydro.get("basin_precip_total_before_mm")
    basin_after = hydro.get("basin_precip_total_after_mm")
    basin_change = hydro.get("basin_precip_total_change_percent")
    if basin_before is not None and basin_after is not None:
        parts.append(
            "流域面降水总量："
            f"{_fmt_float(basin_before, 1, ' mm')}→{_fmt_float(basin_after, 1, ' mm')}"
            f"（{_fmt_float(basin_change, 1, '%')}）"
        )
    factor = hydro.get("correction_factor_mean")
    if factor is not None:
        parts.append(f"平均订正倍率：{_fmt_float(factor, 2)}")
    clipped = int(hydro.get("ratio_clip_step_count", 0) or 0)
    repaired = int(hydro.get("grid_missed_precip_repair_step_count", 0) or 0)
    if clipped or repaired:
        parts.append(f"倍率裁剪日：{clipped}；格点漏报修复日：{repaired}")
    note = str(hydro.get("hydrological_time_basis_note", "") or "").strip()
    if note:
        parts.append(f"时间口径：{note}")
    return parts


def check_precip_strategy_outputs(
    config: dict[str, Any],
    context: PrecipStrategyStatusContext,
    precip_source: Any = None,
) -> tuple[bool, str, int]:
    meteo = dict(config.get(context.meteo_key, {}))
    mode = str(meteo.get(context.meteo_precip_mode_key, "grid_only")).strip()
    profile = context.current_profile(config)
    base_dir, corrected_dir, selected_source = context.effective_precip_paths(
        config,
        profile,
        precip_source=precip_source,
    )
    if mode == "grid_only":
        count = context.count_matching(base_dir)
        label = (
            "当前为本地栅格基线方案，不需要额外订正。"
            if selected_source == "custom_tif"
            else "当前为格点基线方案，不需要额外订正。"
        )
        return count > 0, label, count

    count = context.count_matching(corrected_dir)
    label = "站点订正降水" if mode == "grid_plus_station_bias" else "泰森插值降水"
    summary_path = Path(corrected_dir) / "precipitation_strategy_summary.json"
    if summary_path.exists():
        try:
            summary = context.read_json_file(summary_path)
            time_basis_label = str(summary.get("time_basis_label", "") or "").strip()
            selected_steps = int(summary.get("selected_steps", 0) or 0)
            written_files = int(summary.get("written_files", 0) or 0)
            zero_steps = int(summary.get("zero_available_station_steps", 0) or 0)
            skipped_steps = int(summary.get("skipped_out_of_scope_steps", 0) or 0)
            parts = [f"{label}文件数：{count}"]
            processing_stats = dict(summary.get("processing_stats", {}) or {})
            qc_blocked = bool(processing_stats.get("qc_blocked", False))
            if time_basis_label:
                parts.append(f"资料口径：{time_basis_label}")
            if selected_steps or written_files:
                parts.append(f"参与时段：{written_files or selected_steps}/{selected_steps or count}")
            if zero_steps:
                parts.append(f"无可用站点时段：{zero_steps}")
            if skipped_steps:
                parts.append(f"已忽略口径外时段：{skipped_steps}")
            parts.extend(_hydro_diagnostic_message(summary))
            if qc_blocked:
                monthly = dict(processing_stats.get("monthly_conservation", {}) or {})
                parts.append(
                    "月量守恒质量检查未通过："
                    f"高倍率像元 {int(monthly.get('high_factor_cell_count', 0) or 0)}；"
                    f"移除比例超限像元 {int(monthly.get('high_removed_fraction_cell_count', 0) or 0)}；"
                    f"未分配像元 {int(monthly.get('unresolved_cell_count', 0) or 0)}"
                )
            return count > 0 and not qc_blocked, "；".join(parts), count
        except Exception:
            pass
    return count > 0, f"{label}文件数：{count}", count
