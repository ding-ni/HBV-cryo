# -*- coding: utf-8 -*-
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "公共"))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "HBV-Studio"))

from 公共函数 import example_config_path, read_config  # type: ignore
from profile_runner import PROFILE_HOURLY
from studio_service import OBJECT_LABELS, PROFILE_LABELS, validate_workspace_fields, workspace_detailed_check  # type: ignore


def print_items(title, items):
    if not items:
        return
    print(title)
    for item in items:
        print(f"  - {item}")


def print_summary_rows(rows):
    current_group = None
    for row in rows:
        group = row.get("group", "")
        if group != current_group:
            current_group = group
            print(f"[{group}]")
        status = row.get("ok", None)
        marker = "OK" if status is True else ("INFO" if status is None else "FAIL")
        print(f"  {marker:<4} {row.get('label')}: {row.get('value')}")


def main() -> None:
    parser = argparse.ArgumentParser(description="检查当前流域小时尺度输入是否齐全。")
    parser.add_argument("--配置", "--config", dest="配置", default=str(example_config_path()))
    parser.add_argument("--降水源", "--prec-source", dest="降水源", choices=["mswep", "cmfd", "custom_tif"], default=None)
    args = parser.parse_args()
    config_path = str(read_config(args.配置).get("_config_path", str(Path(args.配置).resolve())))

    validation = validate_workspace_fields(config_path, stage="calibration", precip_source=getattr(args, "降水源", None))
    details = workspace_detailed_check(config_path, precip_source=getattr(args, "降水源", None))
    if details.get("profile") != PROFILE_HOURLY:
        raise ValueError("当前配置不是小时尺度，请改用 13_输入完整性检查.py 或检查配置里的时间步长/率定模式。")

    print("=" * 72)
    print(f"率定模式: {PROFILE_LABELS.get(details['profile'], details['profile'])}")
    print(f"项目类型: {OBJECT_LABELS.get(details['object_type'], details['object_type'])}")
    print(f"输入检查: {'通过' if validation.get('valid') else '未通过'}")
    print("=" * 72)

    print_items("[缺失 / 错误]", validation.get("missing", []))
    print_items("[警告]", validation.get("warnings", []))

    print("-" * 72)
    print_summary_rows(details.get("summary", []))
    print("-" * 72)


if __name__ == "__main__":
    main()
