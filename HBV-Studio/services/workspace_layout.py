#!/usr/bin/env python
# -*- coding: utf-8 -*-
from __future__ import annotations

import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable


_PATH_ENTRY_COUNT_CACHE_LOCK = threading.Lock()
_PATH_ENTRY_COUNT_CACHE: dict[str, dict[str, Any]] = {}


@dataclass(frozen=True)
class WorkspaceLayoutContext:
    load_workspace_config: Callable[[str], tuple[Path, dict[str, Any]]]
    current_profile: Callable[[dict[str, Any]], str]
    build_profile_paths: Callable[[dict[str, Any], str], dict[str, Any]]
    effective_precip_paths: Callable[[dict[str, Any], str], tuple[str, str, str]]
    display_runtime_precip_label: Callable[[dict[str, Any]], str]
    count_path_entries: Callable[..., tuple[int, bool]]
    to_display_path: Callable[[Path], str]
    detect_object_type: Callable[[dict[str, Any]], str]
    profile_labels: dict[str, str]


def _path_entry_count_signature(path: Path) -> tuple[Any, ...] | None:
    try:
        root_stat = path.stat()
    except Exception:
        return None
    return (int(getattr(root_stat, "st_mtime_ns", int(root_stat.st_mtime * 1e9))),)


def count_path_entries(
    path: Path,
    *,
    pattern: str = "*",
    recursive: bool = False,
    only_dirs: bool = False,
    limit: int | None = None,
) -> tuple[int, bool]:
    if not path.exists() or not path.is_dir():
        return 0, False
    cache_key = ""
    signature = None
    if recursive:
        signature = _path_entry_count_signature(path)
        if signature is not None:
            cache_key = f"{path.resolve(strict=False)}|{pattern}|{int(recursive)}|{int(only_dirs)}|{limit or 0}"
            with _PATH_ENTRY_COUNT_CACHE_LOCK:
                cached = _PATH_ENTRY_COUNT_CACHE.get(cache_key)
                if cached and cached.get("signature") == signature:
                    return int(cached.get("count", 0)), bool(cached.get("truncated", False))
    try:
        iterator = path.rglob(pattern) if recursive else (path.iterdir() if pattern == "*" else path.glob(pattern))
        total = 0
        truncated = False
        for item in iterator:
            if only_dirs:
                if item.is_dir():
                    total += 1
            else:
                if item.is_file():
                    total += 1
            if limit is not None and total >= limit:
                truncated = True
                break
        if cache_key and signature is not None:
            with _PATH_ENTRY_COUNT_CACHE_LOCK:
                _PATH_ENTRY_COUNT_CACHE[cache_key] = {
                    "signature": signature,
                    "count": int(total),
                    "truncated": bool(truncated),
                }
        return total, truncated
    except Exception:
        return 0, False


def _workspace_relative_path(root: Path, path: Path, context: WorkspaceLayoutContext) -> str:
    resolved_root = root.resolve(strict=False)
    resolved = path.resolve(strict=False)
    try:
        rel = resolved.relative_to(resolved_root)
        text = str(rel).replace("\\", "/")
        return text or "."
    except ValueError:
        return context.to_display_path(resolved)


def _workspace_layout_item(
    root: Path,
    label: str,
    path: Path,
    purpose: str,
    context: WorkspaceLayoutContext,
    *,
    stage_hint: str,
    target_step: int | None = None,
    kind: str = "dir",
    pattern: str | None = "*",
    recursive: bool = False,
    only_dirs: bool = False,
    count_noun: str = "个文件",
    empty_status: str = "目录已创建，暂未写入内容",
    scan_limit: int | None = None,
) -> dict[str, Any]:
    target = Path(path)
    exists = target.exists()
    count = 1 if exists and kind == "file" else 0
    count_truncated = False
    if exists and kind == "dir" and pattern is not None:
        count, count_truncated = context.count_path_entries(
            target,
            pattern=pattern,
            recursive=recursive,
            only_dirs=only_dirs,
            limit=scan_limit,
        )
    if kind == "file":
        status = "已存在" if exists else "未生成"
    elif not exists:
        status = "目录未创建"
    elif count > 0:
        status = f"已有 {count}{'+' if count_truncated else ''} {count_noun}"
    else:
        status = empty_status
    return {
        "label": label,
        "path": str(target.resolve(strict=False)),
        "display_path": _workspace_relative_path(root, target, context),
        "exists": exists,
        "kind": kind,
        "count": int(count),
        "count_is_approx": bool(count_truncated),
        "status": status,
        "purpose": purpose,
        "stage_hint": stage_hint,
        "target_step": target_step,
    }


def workspace_layout_summary(config_path_raw: str, context: WorkspaceLayoutContext) -> dict[str, Any]:
    cfg_path, config = context.load_workspace_config(config_path_raw)
    profile = context.current_profile(config)
    paths = context.build_profile_paths(config, profile)
    workspace_root = Path(paths["workspace_root"]).resolve(strict=False)
    effective_prec_base_dir, effective_prec_dir, _ = context.effective_precip_paths(config, profile)
    result_profile_root = Path(paths["results_root"]).resolve(strict=False)
    profile_label = context.profile_labels[profile]
    gis_item = _workspace_layout_item(
        workspace_root,
        "地理数据目录",
        Path(paths["gis_dir"]),
        "DEM 裁剪、流量累积、流域掩膜、高程分区和冰川掩膜都保存在这里。",
        context,
        stage_hint="第 5 步重点查看",
        target_step=5,
        pattern="*.tif",
        recursive=False,
        count_noun="个栅格文件",
        empty_status="目录已创建，尚未生成地理栅格",
    )
    aligned_item = _workspace_layout_item(
        workspace_root,
        "标准气象驱动目录",
        Path(paths["aligned_dir"]),
        "模型实际读取的标准网格驱动都在这里，检查问题时优先看这个目录。",
        context,
        stage_hint="第 6 步重点查看",
        target_step=6,
        pattern="*.tif",
        recursive=True,
        scan_limit=120,
        count_noun="个驱动栅格",
        empty_status="目录已创建，尚未形成模型驱动",
    )
    runs_item = _workspace_layout_item(
        workspace_root,
        f"{profile_label}结果目录",
        Path(paths["runs_dir"]),
        "每一次率定、手调或输入预核算都会在这里生成独立结果子目录。",
        context,
        stage_hint="率定运行后查看",
        pattern="*",
        recursive=False,
        only_dirs=True,
        count_noun="组结果",
        empty_status="目录已创建，尚无运行结果",
    )
    items = [
        {
            "title": "入口与主目录",
            "items": [
                _workspace_layout_item(
                    workspace_root,
                    "工作区配置文件",
                    cfg_path,
                    "保存流域名称、时间分段、输入路径和率定配置，是整个工程的入口文件。",
                    context,
                    stage_hint="第 1 步保存后生成",
                    target_step=1,
                    kind="file",
                ),
                _workspace_layout_item(
                    workspace_root,
                    "工程根目录",
                    workspace_root,
                    "这个目录下面统一放数据、过程产物、日志和率定结果。",
                    context,
                    stage_hint="本地工程主目录",
                    target_step=1,
                    pattern=None,
                    empty_status="目录已创建",
                ),
            ],
        },
        {
            "title": "数据目录",
            "items": [
                gis_item,
                _workspace_layout_item(
                    workspace_root,
                    "原始气象资料目录",
                    Path(paths["raw_root"]),
                    "下载或导入后、裁剪对齐前的原始气象数据放在这里。",
                    context,
                    stage_hint="第 6 步上游输入",
                    target_step=6,
                    pattern="*",
                    recursive=True,
                    scan_limit=80,
                    count_noun="个原始文件",
                    empty_status="目录已创建，尚未写入原始气象数据",
                ),
                aligned_item,
                _workspace_layout_item(
                    workspace_root,
                    "观测与对比资料目录",
                    Path(paths["observed_dir"]),
                    "用于保存观测相关副本或中间产物；原始观测 csv 仍按配置路径读取。",
                    context,
                    stage_hint="观测相关",
                    target_step=2,
                    pattern="*",
                    recursive=True,
                    scan_limit=40,
                    count_noun="个文件",
                ),
            ],
        },
        {
            "title": "当前率定与输出",
            "items": [
                _workspace_layout_item(
                    workspace_root,
                    f"当前降水驱动目录（{context.display_runtime_precip_label(config)}）",
                    Path(effective_prec_dir),
                    "这是当前率定真正读取的降水目录。若启用了站点订正，这里就是订正后的运行目录；若未启用订正，这里就是基线目录。",
                    context,
                    stage_hint="排查降水问题时优先看这里",
                    target_step=6,
                    pattern="*.tif",
                    recursive=True,
                    scan_limit=120,
                    count_noun="个降水栅格",
                    empty_status="目录已创建，尚未形成可运行降水驱动",
                ),
                _workspace_layout_item(
                    workspace_root,
                    "降水基线目录",
                    Path(effective_prec_base_dir),
                    "这是裁剪对齐后的基线降水目录。目录名里的 custom 表示本地导入栅格，corrected 表示站点订正后的运行副本。",
                    context,
                    stage_hint="核对基线输入",
                    target_step=6,
                    pattern="*.tif",
                    recursive=True,
                    scan_limit=120,
                    count_noun="个栅格",
                ),
                _workspace_layout_item(
                    workspace_root,
                    "气温驱动目录",
                    Path(paths["aligned_temp_dir"]),
                    "模型运行时使用的标准气温栅格。",
                    context,
                    stage_hint="排查气温问题时查看",
                    target_step=6,
                    pattern="*.tif",
                    recursive=True,
                    scan_limit=120,
                    count_noun="个气温栅格",
                ),
                _workspace_layout_item(
                    workspace_root,
                    "蒸散发驱动目录",
                    Path(paths["aligned_evap_dir"]),
                    "模型运行时使用的标准潜在蒸散发栅格。",
                    context,
                    stage_hint="排查蒸散发问题时查看",
                    target_step=6,
                    pattern="*.tif",
                    recursive=True,
                    scan_limit=120,
                    count_noun="个蒸散发栅格",
                ),
                runs_item,
                _workspace_layout_item(
                    workspace_root,
                    "运行日志目录",
                    Path(paths["logs_dir"]),
                    "率定过程日志和阶段信息会写入这里。",
                    context,
                    stage_hint="查看运行过程",
                    pattern="*",
                    recursive=False,
                    count_noun="个日志文件",
                    empty_status="目录已创建，尚未产生运行日志",
                ),
                _workspace_layout_item(
                    workspace_root,
                    "加速缓存目录",
                    Path(paths["cache_dir"]),
                    "数据栈缓存和运行时缓存放在这里，用于减少重复加载。",
                    context,
                    stage_hint="提速相关",
                    pattern="*",
                    recursive=False,
                    count_noun="个缓存文件",
                    empty_status="目录已创建，尚未写入缓存",
                ),
            ],
        },
    ]
    if not gis_item["exists"] or gis_item["count"] <= 0:
        next_focus = {
            "label": "地理数据目录",
            "path": str(Path(paths["gis_dir"]).resolve(strict=False)),
            "reason": "先完成第 5 步，确保 DEM、流量累积和流域掩膜已经生成。",
        }
    elif not aligned_item["exists"] or aligned_item["count"] <= 0:
        next_focus = {
            "label": "模型驱动目录",
            "path": str(Path(paths["aligned_dir"]).resolve(strict=False)),
            "reason": "下一步应检查第 6 步输出，确认降水、气温和蒸散发已形成标准驱动。",
        }
    elif runs_item["count"] <= 0:
        next_focus = {
            "label": f"{profile_label}结果目录",
            "path": str(Path(paths["runs_dir"]).resolve(strict=False)),
            "reason": "输入已经基本具备，接下来可以生成手调起点或启动率定。",
        }
    else:
        next_focus = {
            "label": f"{profile_label}结果目录",
            "path": str(Path(paths["runs_dir"]).resolve(strict=False)),
            "reason": "当前已有历史结果，可直接对比结果、日志和加速缓存。",
        }
    return {
        "config_path": str(cfg_path.resolve()),
        "config_display_path": context.to_display_path(cfg_path),
        "workspace_root": str(workspace_root),
        "workspace_display_root": context.to_display_path(workspace_root),
        "results_root": str(result_profile_root),
        "results_display_root": context.to_display_path(result_profile_root),
        "flow_name": str(config.get("流域名称", cfg_path.stem)).strip() or cfg_path.stem,
        "profile": profile,
        "profile_label": context.profile_labels.get(profile, profile),
        "object_type": context.detect_object_type(config),
        "headline": "一个工作区由“配置文件 + 本地工程目录”组成；真正参与模型运行的核心目录是“地理数据目录”“标准气象驱动目录”和“结果目录”。",
        "next_focus": next_focus,
        "groups": items,
        "notes": [
            "删除工作区配置文件不会自动删除工程目录中的数据。",
            "排查输入问题时，优先查看“标准气象驱动目录”，而不是原始气象资料目录。",
            "率定结果、日志和缓存都按率定模式分别存放在对应的日尺度或小时尺度结果目录下。",
        ],
    }
