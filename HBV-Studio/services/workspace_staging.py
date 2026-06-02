#!/usr/bin/env python
# -*- coding: utf-8 -*-
from __future__ import annotations

import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable


OBSERVED_FLOW_SUFFIXES = {".csv", ".xlsx", ".xls", ".xlsm"}


@dataclass(frozen=True)
class WorkspaceStagingContext:
    resolve_any_path: Callable[..., Path]
    replace_placeholders: Callable[[Any], Any]
    build_workspace_paths: Callable[[dict[str, Any]], dict[str, Any]]
    workspace_dir: Path
    vector_bundle_suffixes: tuple[str, ...]


def _resolved_staging_config(
    config: dict[str, Any],
    context: WorkspaceStagingContext,
    config_path: Path | None,
) -> dict[str, Any]:
    resolved_config = context.replace_placeholders(dict(config))
    if config_path is not None:
        resolved_config["_config_path"] = str(config_path.resolve(strict=False))
    elif not str(resolved_config.get("_config_path", "")).strip():
        resolved_config["_config_path"] = str((context.workspace_dir / "_staging_context.json").resolve(strict=False))
    return resolved_config


def stage_vector_shapefile(
    config: dict[str, Any],
    raw_path: Any,
    context: WorkspaceStagingContext,
    *,
    role: str,
    config_path: Path | None = None,
) -> Path:
    src = context.resolve_any_path(str(raw_path), must_exist=True)
    if not src.is_file():
        raise ValueError(f"shp 路径不是文件：{src}")
    if src.suffix.lower() != ".shp":
        raise ValueError(f"当前只支持 .shp 文件：{src}")

    resolved_config = _resolved_staging_config(config, context, config_path)
    if not str(resolved_config.get("运行目录", "")).strip():
        raise ValueError("缺少运行目录，无法归档 shp 文件。")

    paths = context.build_workspace_paths(resolved_config)
    gis_dir = Path(paths["gis_dir"]).resolve(strict=False)
    if role == "basin":
        dst = (gis_dir / "basin.shp").resolve(strict=False)
    elif role == "glacier":
        dst = (gis_dir / "glacier_shp" / "glacier.shp").resolve(strict=False)
    else:
        raise ValueError(f"未知 shp 类型：{role}")
    dst.parent.mkdir(parents=True, exist_ok=True)

    copied = False
    for suffix in context.vector_bundle_suffixes:
        sidecar = src.with_suffix(suffix)
        if not sidecar.exists():
            continue
        target = dst.with_suffix(suffix)
        if sidecar.resolve(strict=False) != target.resolve(strict=False):
            shutil.copy2(sidecar, target)
        copied = True
    if not copied:
        shutil.copy2(src, dst)
    return dst


def stage_observed_runoff_file(
    config: dict[str, Any],
    raw_path: Any,
    context: WorkspaceStagingContext,
    *,
    config_path: Path | None = None,
) -> Path:
    src = context.resolve_any_path(str(raw_path), must_exist=True)
    if not src.is_file():
        raise ValueError(f"观测径流路径不是文件：{src}")
    if src.suffix.lower() not in OBSERVED_FLOW_SUFFIXES:
        allowed = ", ".join(sorted(OBSERVED_FLOW_SUFFIXES))
        raise ValueError(f"观测径流文件类型不支持：{src.suffix or '(无扩展名)'}，支持 {allowed}")

    resolved_config = _resolved_staging_config(config, context, config_path)
    if not str(resolved_config.get("运行目录", "")).strip():
        raise ValueError("缺少运行目录，无法归档观测径流文件。")
    paths = context.build_workspace_paths(resolved_config)
    observed_dir = Path(paths["observed_dir"]).resolve(strict=False)
    observed_dir.mkdir(parents=True, exist_ok=True)
    dst = (observed_dir / src.name).resolve(strict=False)

    if src.resolve(strict=False) != dst:
        shutil.copy2(src, dst)
    return dst
