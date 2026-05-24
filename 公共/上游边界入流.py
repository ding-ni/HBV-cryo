# -*- coding: utf-8 -*-
from pathlib import Path

import numpy as np
import pandas as pd


def _normalize_step_hours(step_hours):
    value = float(step_hours)
    return 1.0 if value <= 1.5 else 24.0


def _detect_series_step_hours(index):
    timestamps = pd.DatetimeIndex(index).sort_values().drop_duplicates()
    if len(timestamps) < 2:
        return None
    diffs = timestamps.to_series().diff().dropna()
    if diffs.empty:
        return None
    median_hours = diffs.median() / pd.Timedelta(hours=1)
    return _normalize_step_hours(median_hours)


def read_boundary_inflow_series(
    csv_path,
    dates,
    date_field="date",
    flow_field="inflow_m3s",
    gap_fill="zero",
    expected_step_hours=None,
):
    if not csv_path:
        return np.zeros(len(dates), dtype=np.float64), False

    path = Path(csv_path)
    if not path.exists():
        raise FileNotFoundError(f"上游边界入流文件不存在: {path}")

    df = pd.read_csv(path)
    if date_field not in df.columns:
        raise KeyError(f"上游边界入流文件缺少时间字段: {date_field}")
    if flow_field not in df.columns:
        raise KeyError(f"上游边界入流文件缺少流量字段: {flow_field}")

    valid = df[[date_field, flow_field]].copy()
    valid[date_field] = pd.to_datetime(valid[date_field], errors="coerce")
    valid[flow_field] = pd.to_numeric(valid[flow_field], errors="coerce")
    valid = valid.dropna(subset=[date_field, flow_field]).copy()
    if valid.empty:
        raise ValueError("上游边界入流文件中没有可识别的有效时间和流量记录。")
    if (valid[flow_field] < 0).any():
        raise ValueError("上游边界入流文件中存在负流量，请先修正数据。")

    grouped = (
        valid
        .groupby(date_field, as_index=True)[flow_field]
        .mean()
        .sort_index()
    )
    actual_index = pd.DatetimeIndex(grouped.index)
    detected_step_hours = _detect_series_step_hours(actual_index)
    if expected_step_hours is not None and detected_step_hours is not None:
        expected_step = _normalize_step_hours(expected_step_hours)
        if detected_step_hours != expected_step:
            raise ValueError(
                f"上游边界入流时间步识别为 {int(detected_step_hours)} 小时，与当前模型时间步长 {int(expected_step)} 小时不一致。"
            )

    target_index = pd.DatetimeIndex(dates)
    series = grouped.reindex(target_index)
    gap_mode = str(gap_fill).strip().lower()
    if gap_mode == "interpolate":
        series = series.interpolate(method="linear", limit_direction="both")
    elif gap_mode not in {"", "zero", "0"}:
        raise ValueError(f"不支持的上游边界入流缺失填补方式：{gap_fill}")
    if expected_step_hours is not None and series.isna().any():
        if gap_mode in {"", "zero", "0"}:
            series = series.fillna(0.0)
        else:
            missing = target_index[series.isna()]
            sample = "、".join(pd.Timestamp(item).strftime("%Y-%m-%d %H:%M") for item in missing[:3])
            raise ValueError(
                f"上游边界入流时间覆盖不完整，缺少 {int(series.isna().sum())} 个时间步，例如：{sample or '请检查原始 CSV'}"
            )
    series = series.fillna(0.0).astype(float)
    return series.values.astype(np.float64), True
