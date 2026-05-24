#!/usr/bin/env python
# -*- coding: utf-8 -*-
from __future__ import annotations

import argparse
import shutil
from pathlib import Path


COPY_DIRS = [
    (("模型输入",), ("aligned_masked",)),
    (("地理数据",), ("gis",)),
    (("观测数据",), ("observed",)),
]


def copy_tree(src: Path, dst: Path) -> None:
    if not src.exists():
        print(f"[跳过] 不存在: {src}")
        return
    dst.mkdir(parents=True, exist_ok=True)
    for item in src.iterdir():
        target = dst / item.name
        if item.is_dir():
            shutil.copytree(item, target, dirs_exist_ok=True)
        else:
            shutil.copy2(item, target)
    print(f"[完成] {src} -> {dst}")


def pick_path(root: Path, *variants: tuple[str, ...]) -> Path:
    candidates = [Path(root).joinpath(*parts) for parts in variants]
    for candidate in candidates:
        if candidate.exists():
            return candidate
    return candidates[0]


def main() -> None:
    parser = argparse.ArgumentParser(description="同步历史 Hapi/data 的沱沱河工作区数据到当前仓库。")
    parser.add_argument("--source", required=True)
    parser.add_argument("--target", required=True)
    parser.add_argument("--include-raw", action="store_true")
    args = parser.parse_args()

    source_root = Path(args.source)
    target_root = Path(args.target)
    if not source_root.exists():
        raise FileNotFoundError(source_root)

    copy_dirs = list(COPY_DIRS)
    if args.include_raw:
        copy_dirs.append((("原始气象",), ("raw",)))

    print(f"源目录: {source_root}")
    print(f"目标目录: {target_root}")
    for primary_parts, legacy_parts in copy_dirs:
        src_dir = pick_path(source_root, primary_parts, legacy_parts)
        dst_dir = target_root.joinpath(*primary_parts)
        copy_tree(src_dir, dst_dir)
    print("同步结束。")


if __name__ == "__main__":
    main()
