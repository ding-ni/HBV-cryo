# -*- coding: utf-8 -*-
from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "公共"))

from 公共函数 import build_workspace_paths, config_base_dir, ensure_workspace_dirs, example_config_path, read_config, resolve_path  # type: ignore


SUPPORTED_SUFFIXES = {".tif", ".tiff"}


def parse_time_token(name: str) -> str | None:
    import re
    from pathlib import Path

    stem = Path(name).stem
    for pattern in [r"\d{4}\.\d{2}\.\d{2}\.\d{2}\.\d{2}", r"\d{4}\.\d{2}\.\d{2}\.\d{2}", r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}", r"\d{4}-\d{2}-\d{2} \d{2}:\d{2}", r"\d{4}-\d{2}-\d{2}\.\d{2}"]:
        match = re.search(pattern, stem)
        if match:
            token = match.group(0).replace("-", ".").replace("T", ".").replace(":", ".").replace(" ", ".")
            parts = token.split(".")
            if len(parts) == 4:
                return token
            if len(parts) >= 5:
                return ".".join(parts[:4])
    return None


def main() -> None:
    parser = argparse.ArgumentParser(description="处理或标准化小时尺度降水文件。")
    parser.add_argument("--配置", "--config", dest="配置", default=str(example_config_path()))
    parser.add_argument("--降水源", "--prec-source", dest="降水源", choices=["era5", "mswep", "cmfd", "custom_tif"], default=None)
    parser.add_argument("--覆盖", "--overwrite", dest="覆盖", action="store_true")
    args = parser.parse_args()

    config = read_config(args.配置)
    paths = build_workspace_paths(config)
    ensure_workspace_dirs(paths)
    meteo = dict(config.get("气象策略", {}))
    configured_source = str(
        meteo.get("降水来源", meteo.get("降水源", config.get("默认降水源", "era5")))
    ).strip().lower()
    runtime_source = str(args.降水源 or configured_source or "era5").strip().lower()
    if runtime_source == "custom_tif":
        print("[跳过] 当前工作区为本地降水栅格模式，不执行小时格点降水标准化。")
        return
    if runtime_source == "era5":
        target_dir = Path(paths["raw_prec_era5_hourly_dir"])
        if list(target_dir.glob("*.tif")):
            print(f"[完成] ERA5 小时降水已生成 -> {target_dir}")
            return
        yearly = sorted(Path(paths["raw_prec_era5_dir"]).glob("era5_tp_hourly_????.nc"))
        if yearly:
            raise FileNotFoundError(
                "已找到按年小时降水 NC，但尚未生成小时 TIF。"
                "请先运行“处理小时温度与蒸散”（06b）以写出 ERA5 小时降水栅格。"
                f" 年文件示例：{yearly[0].name}"
            )
        raise FileNotFoundError(
            "当前降水来源为 ERA5，请先完成“下载小时 ERA5 变量”，再运行“处理小时温度与蒸散”；"
            "该步骤会同步生成 ERA5 小时降水。"
        )
    source_dir_raw = str(meteo.get("原始小时降水目录", "")).strip()
    if source_dir_raw:
        source_dir = Path(resolve_path(source_dir_raw, base=config_base_dir(config))).resolve(strict=False)
    else:
        source_dir = Path(paths["raw_prec_hourly_dir"] if runtime_source == "mswep" else paths["raw_prec_cmfd_hourly_dir"])
    target_dir = Path(paths["raw_prec_hourly_dir"] if runtime_source == "mswep" else paths["raw_prec_cmfd_hourly_dir"])
    target_dir.mkdir(parents=True, exist_ok=True)

    if not source_dir.exists():
        raise FileNotFoundError(f"原始小时降水目录不存在：{source_dir}")

    files = [path for path in source_dir.iterdir() if path.is_file() and path.suffix.lower() in SUPPORTED_SUFFIXES]
    if not files:
        raise FileNotFoundError(f"目录中没有小时降水 GeoTIFF：{source_dir}")

    token_map: dict[str, list[Path]] = {}
    for path in files:
        token = parse_time_token(path.name)
        if token:
            token_map.setdefault(token, []).append(path)
    duplicates = {token: items for token, items in token_map.items() if len(items) > 1}
    if duplicates:
        first_token, dup_files = next(iter(sorted(duplicates.items())))
        sample = "、".join(item.name for item in dup_files[:3])
        raise RuntimeError(f"发现重复小时降水时间戳 {first_token}，例如：{sample}")

    copied = 0
    for path in sorted(files):
        token = parse_time_token(path.name)
        if not token:
            continue
        output = target_dir / f"PREC_{token}.tif"
        if output.exists() and not args.覆盖:
            copied += 1
            continue
        shutil.copy2(path, output)
        copied += 1

    if copied == 0:
        raise RuntimeError("未从原始小时降水目录中识别到可用文件名时间戳。")
    print(f"[完成] 已标准化小时降水文件 {copied} 个 -> {target_dir}")


if __name__ == "__main__":
    main()
