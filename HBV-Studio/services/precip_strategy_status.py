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
            if time_basis_label:
                parts.append(f"资料口径：{time_basis_label}")
            if selected_steps or written_files:
                parts.append(f"参与时段：{written_files or selected_steps}/{selected_steps or count}")
            if zero_steps:
                parts.append(f"无可用站点时段：{zero_steps}")
            if skipped_steps:
                parts.append(f"已忽略口径外时段：{skipped_steps}")
            return count > 0, "；".join(parts), count
        except Exception:
            pass
    return count > 0, f"{label}文件数：{count}", count
