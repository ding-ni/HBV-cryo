#!/usr/bin/env python
# -*- coding: utf-8 -*-
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable


@dataclass(frozen=True)
class GeoStatusContext:
    current_profile: Callable[[dict[str, Any]], str]
    build_profile_paths: Callable[[dict[str, Any], str], dict[str, Any]]
    workspace_dem_path: Callable[..., Path]
    configured_dem_kind: Callable[[dict[str, Any]], str | None]


def check_clip_dem(config: dict[str, Any], context: GeoStatusContext) -> tuple[bool, str, int]:
    paths = context.build_profile_paths(config, context.current_profile(config))
    target = context.workspace_dem_path(paths["gis_dir"], prefer=context.configured_dem_kind(config))
    return target.exists(), "已生成 DEM" if target.exists() else "尚未生成", 1 if target.exists() else 0


def check_flow_acc(config: dict[str, Any], context: GeoStatusContext) -> tuple[bool, str, int]:
    paths = context.build_profile_paths(config, context.current_profile(config))
    target = Path(paths["gis_dir"]) / "flow_accumulation.tif"
    return target.exists(), "已生成流量累积" if target.exists() else "尚未生成", 1 if target.exists() else 0


def check_masked_flow(config: dict[str, Any], context: GeoStatusContext) -> tuple[bool, str, int]:
    paths = context.build_profile_paths(config, context.current_profile(config))
    target = Path(paths["gis_dir"]) / "flow_accumulation_masked.tif"
    return target.exists(), "已生成流域掩膜" if target.exists() else "尚未生成", 1 if target.exists() else 0


def check_elevation_zone(config: dict[str, Any], context: GeoStatusContext) -> tuple[bool, str, int]:
    paths = context.build_profile_paths(config, context.current_profile(config))
    gis_dir = Path(paths["gis_dir"])
    low_exists = (gis_dir / "elevation_zone_low.tif").exists() or (gis_dir / "elevation_zone_mid.tif").exists()
    high_exists = (gis_dir / "elevation_zone_high.tif").exists()
    count = int(low_exists) + int(high_exists)
    return count == 2, f"高程分区文件 {count}/2", count
