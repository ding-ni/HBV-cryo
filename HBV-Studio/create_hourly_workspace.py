#!/usr/bin/env python
# -*- coding: utf-8 -*-
from __future__ import annotations

import argparse
import copy
import json
from pathlib import Path
from typing import Any

import pandas as pd


HYDRO_DAY_START_HOUR = 8
HOURLY_OBJECTIVE_MODE = "hourly_alpine_qtp_v1"
HOURLY_PARAM_BOUNDS_PROFILE = "hourly_qtp_alpine_default"


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, data: dict[str, Any], *, overwrite: bool = False) -> None:
    if path.exists() and not overwrite:
        raise FileExistsError(f"输出文件已存在：{path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def _date_start(value: Any) -> pd.Timestamp:
    return pd.Timestamp(value).normalize() + pd.Timedelta(hours=HYDRO_DAY_START_HOUR)


def _date_end(value: Any) -> pd.Timestamp:
    return pd.Timestamp(value).normalize() + pd.Timedelta(days=1, hours=HYDRO_DAY_START_HOUR - 1)


def _fmt(value: pd.Timestamp) -> str:
    return pd.Timestamp(value).strftime("%Y-%m-%d %H:%M")


def build_hourly_time_config(time_cfg: dict[str, Any], *, validation_end: str | None = None) -> dict[str, Any]:
    warmup_start = _date_start(time_cfg["预热开始"])
    calib_start = _date_start(time_cfg["率定开始"])
    valid_start = _date_start(time_cfg["验证开始"])
    valid_end = pd.Timestamp(validation_end) if validation_end else _date_end(time_cfg["验证结束"])
    return {
        **time_cfg,
        "预热开始": _fmt(warmup_start),
        "预热结束": _fmt(calib_start - pd.Timedelta(hours=1)),
        "率定开始": _fmt(calib_start),
        "率定结束": _fmt(valid_start - pd.Timedelta(hours=1)),
        "验证开始": _fmt(valid_start),
        "验证结束": _fmt(valid_end),
    }


def build_hourly_workspace(
    daily_config: dict[str, Any],
    *,
    suffix: str = "_hourly",
    validation_end: str | None = None,
) -> dict[str, Any]:
    config = copy.deepcopy(daily_config)
    basin_id = str(config.get("流域编号") or config.get("流域名称") or "workspace")
    config["率定模式"] = "hourly"
    config["时间步长_小时"] = 1.0
    config["目标函数模式"] = HOURLY_OBJECTIVE_MODE
    config["参数边界档案"] = HOURLY_PARAM_BOUNDS_PROFILE
    config["率定流程"] = "single_pass"
    config["流域编号"] = basin_id if basin_id.endswith(suffix) else basin_id + suffix
    if "流域名称" in config and not str(config["流域名称"]).endswith(" 小时尺度"):
        config["流域名称"] = f"{config['流域名称']} 小时尺度"
    config["时间"] = build_hourly_time_config(dict(config.get("时间", {}) or {}), validation_end=validation_end)
    config["_小时尺度说明"] = [
        "由日尺度 workspace 派生；原日尺度配置不应被覆盖。",
        "时间字段已按 08:00-次日07:00 水文日展开，小时模式必须保留显式小时。",
        "小时强迫应位于 数据/模型输入/小时尺度，降水默认读取 降水_本地导入_站点订正。",
        "当前正式生产流程为 single_pass；建议用日尺度最优参数作为初值后再做小时率定。",
        "若观测或上游边界只到某一小时，验证结束应显式截到该小时，或补齐至完整水文日。",
    ]
    return config


def default_output_path(input_path: Path, suffix: str) -> Path:
    stem = input_path.stem
    if not stem.endswith(suffix):
        stem += suffix
    return input_path.with_name(stem + input_path.suffix)


def main() -> None:
    parser = argparse.ArgumentParser(description="Create an hourly HBV-Studio workspace JSON from a daily workspace JSON.")
    parser.add_argument("--input", "-i", required=True, help="日尺度 workspace JSON")
    parser.add_argument("--output", "-o", default="", help="小时尺度 workspace JSON；默认写到输入文件同目录并加 _hourly")
    parser.add_argument("--suffix", default="_hourly")
    parser.add_argument("--validation-end", default="", help="显式验证结束小时，例如 2025-10-31 08:00")
    parser.add_argument("--overwrite", action="store_true")
    args = parser.parse_args()

    input_path = Path(args.input)
    output_path = Path(args.output) if args.output else default_output_path(input_path, args.suffix)
    config = build_hourly_workspace(
        load_json(input_path),
        suffix=args.suffix,
        validation_end=args.validation_end or None,
    )
    write_json(output_path, config, overwrite=bool(args.overwrite))
    print(str(output_path.resolve(strict=False)))


if __name__ == "__main__":
    main()
