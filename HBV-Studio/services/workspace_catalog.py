#!/usr/bin/env python
# -*- coding: utf-8 -*-
from __future__ import annotations

import hashlib
import re
import unicodedata
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

import pandas as pd


@dataclass(frozen=True)
class WorkspaceCatalogContext:
    template_dir: Path
    workspace_dir: Path
    project_runtime_dir: Path
    default_workspace_path: Path
    builtin_glacier_shp: Path
    builtin_dem: Path
    profile_daily: str
    profile_hourly: str
    time_basis_continuous: str
    object_regression: str
    object_interbasin: str
    object_full_upstream: str
    observed_flow_key: str
    meteo_key: str
    meteo_precip_source_key: str
    meteo_precip_source_legacy_key: str
    read_json_file: Callable[[Path], dict[str, Any]]
    read_runtime_config: Callable[[Path], dict[str, Any]]
    replace_placeholders: Callable[[Any], Any]
    resolve_any_path: Callable[..., Path]
    resolve_profile: Callable[[dict[str, Any], str | None], str]
    normalize_config_before_save: Callable[[dict[str, Any], Path], dict[str, Any]]
    detect_object_type: Callable[[dict[str, Any]], str]
    default_initial_state: dict[str, Any]
    write_json_file: Callable[[Path, Any], None]
    to_display_path: Callable[[Path], str]
    workspace_workflow_summary: Callable[..., dict[str, Any]]
    normalize_time_step_hours: Callable[[Any], float]
    ensure_within: Callable[[Path, Path], Path]
    inspect_observed_csv: Callable[..., dict[str, Any]]
    fill_bbox_from_shp: Callable[[str], dict[str, float] | None]
    suggest_time_windows: Callable[[pd.Timestamp, pd.Timestamp, str], dict[str, str]]
    suggest_cfmax_threshold: Callable[[str, str], dict[str, Any]]
    stage_vector_shapefile: Callable[..., Path]
    stage_observed_runoff_file: Callable[..., Path]


def slugify_workspace_name(name: str) -> str:
    raw = str(name or "").strip()
    if not raw:
        return "新工作区"
    normalized = unicodedata.normalize("NFKC", raw)
    digest = hashlib.md5(raw.encode("utf-8")).hexdigest()[:8]
    safe = re.sub(r'[<>:"/\\|?*\x00-\x1f]+', "_", normalized)
    safe = re.sub(r"\s+", "_", safe)
    safe = re.sub(r"_+", "_", safe).strip(" ._")[:48].strip(" ._")
    if not safe:
        return f"workspace_{digest}"
    if re.fullmatch(r"(?i:con|prn|aux|nul|com[1-9]|lpt[1-9])", safe):
        return f"{safe}_{digest[:4]}"
    return safe


def runtime_root_for_workspace(name: str, project_runtime_dir: Path) -> Path:
    return project_runtime_dir / slugify_workspace_name(name)


def build_empty_workspace(name: str = "新流域工作区", profile: str = "", context: WorkspaceCatalogContext | None = None) -> dict[str, Any]:
    if context is None:
        raise ValueError("build_empty_workspace requires a WorkspaceCatalogContext.")
    selected_profile = profile or context.profile_daily
    glacier_default = str(context.builtin_glacier_shp.resolve()) if context.builtin_glacier_shp.exists() else ""
    return {
        "_说明": [
            "HBV-Studio 生成的工作区配置。",
            "导入 shp + 观测径流后，系统会自动补齐范围、时间和默认 DEM。",
        ],
        "项目对象": context.object_full_upstream,
        "率定模式": selected_profile,
        "目标函数模式": "auto",
        "任务时段模式": context.time_basis_continuous,
        "运行目录": str(runtime_root_for_workspace(name, context.project_runtime_dir)),
        "流域名称": name,
        "流域编号": slugify_workspace_name(name),
        "流域边界_shp": "",
        "DEM_tif": str(context.builtin_dem.resolve()),
        context.observed_flow_key: "",
        "观测口径模式": "full_year",
        "事件资料模式": {
            "启用": False,
            "事件窗口资料": False,
            "事件表路径": "",
            "允许事件间断": True,
            "初始条件策略": "event_warmup",
        },
        "洪水事件率定": {
            "启用": False,
            "事件窗口资料": False,
            "事件表路径": "",
            "模式": "diagnostic",
        },
        "边界条件": {
            "上游边界入流_csv": "",
            "时间字段": "date",
            "流量字段": "inflow_m3s",
            "缺失填补": "zero",
        },
        "气象策略": {
            "降水方案": "grid_only",
            "降水来源": "era5",
            "降水源": "era5",
            "站点降水_csv": "",
            "站点信息_csv": "",
            "原始小时降水目录": "",
            "自带降水tif目录": "",
            "温度来源": "era5",
            "自带温度tif目录": "",
            "潜在蒸散发来源": "era5_fao56",
            "自带蒸散发tif目录": "",
        },
        "冰川边界_shp": glacier_default,
        "范围_bbox": {"北": None, "西": None, "南": None, "东": None},
        "时间": {
            "开始年份": 2006,
            "结束年份": 2020,
            "预热开始": "",
            "预热结束": "",
            "率定开始": "",
            "率定结束": "",
            "验证开始": "",
            "验证结束": "",
        },
        "时间步长_小时": 24.0 if selected_profile == context.profile_daily else 1.0,
        "初始状态": dict(context.default_initial_state),
        "FAO56平均海拔_m": 4500.0,
        "默认降水源": "era5",
        "CFMAX分区阈值_m": 5000.0,
    }


def template_files(context: WorkspaceCatalogContext) -> list[Path]:
    if not context.template_dir.exists():
        return []
    files = {path.resolve(): path for path in context.template_dir.glob("*.json")}
    files.update({path.resolve(): path for path in context.template_dir.glob("*.template.json")})
    return sorted(files.values())


def list_templates(context: WorkspaceCatalogContext) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    for path in template_files(context):
        try:
            raw = context.read_json_file(path)
            resolved = context.replace_placeholders(raw)
            meta = raw.get("_studio_template", {})
            runtime_root = resolved.get("运行目录", "")
            runtime_path = Path(runtime_root) if runtime_root else None
            asset_ok = True
            for key in ("流域边界_shp", context.observed_flow_key):
                candidate = resolved.get(key, "")
                candidate_path = None
                if candidate:
                    try:
                        candidate_path = context.resolve_any_path(str(candidate), must_exist=False)
                    except Exception:
                        candidate_path = Path(str(candidate)).expanduser()
                if candidate and (candidate_path is None or not candidate_path.exists()):
                    asset_ok = False
                    break
            results.append(
                {
                    "id": meta.get("id", path.stem),
                    "title": meta.get("title", path.stem),
                    "description": meta.get("description", ""),
                    "calibration_mode": resolved.get("率定模式", context.profile_daily),
                    "object_type": context.detect_object_type(resolved),
                    "path": str(path.resolve()),
                    "display_path": context.to_display_path(path),
                    "builtin": bool(meta.get("builtin", True)),
                    "runtime_root": str(runtime_path) if runtime_path else "",
                    "runtime_ready": bool(runtime_path and runtime_path.exists()),
                    "assets_ready": asset_ok,
                    "sync_hint": meta.get("sync_hint", ""),
                }
            )
        except Exception:
            continue
    return results


def find_template(template_id: str, context: WorkspaceCatalogContext) -> Path:
    for path in template_files(context):
        raw = context.read_json_file(path)
        meta = raw.get("_studio_template", {})
        if meta.get("id") == template_id or path.stem == template_id:
            return path
    raise FileNotFoundError(template_id)


def instantiate_template(payload: dict[str, Any], context: WorkspaceCatalogContext) -> dict[str, Any]:
    template_id = str(payload.get("template_id", "")).strip()
    if not template_id:
        raise ValueError("缺少模板 ID。")
    target_name = str(payload.get("workspace_name", "")).strip() or "新流域工作区"
    template_path = find_template(template_id, context)
    raw = context.replace_placeholders(context.read_json_file(template_path))
    profile = context.resolve_profile(raw, None)
    config = context.normalize_config_before_save(raw, context.default_workspace_path)
    if (not str(config.get("冰川边界_shp", "")).strip()) and context.builtin_glacier_shp.exists():
        config["冰川边界_shp"] = str(context.builtin_glacier_shp.resolve())
    if context.detect_object_type(config) != context.object_regression:
        config["流域名称"] = target_name
        config["流域编号"] = slugify_workspace_name(target_name)
    if template_id == "blank-workspace":
        config["运行目录"] = str(runtime_root_for_workspace(target_name, context.project_runtime_dir))
    workspace_path = context.workspace_dir / f"{slugify_workspace_name(target_name)}.json"
    context.write_json_file(workspace_path, context.normalize_config_before_save(config, workspace_path))
    return {
        "workspace_path": str(workspace_path.resolve()),
        "config": context.read_json_file(workspace_path),
        "template_id": template_id,
        "profile": profile,
    }


def list_workspaces(context: WorkspaceCatalogContext) -> list[dict[str, Any]]:
    context.workspace_dir.mkdir(parents=True, exist_ok=True)
    results: list[dict[str, Any]] = []
    for path in sorted(context.workspace_dir.glob("*.json")):
        try:
            data = context.read_runtime_config(path)
            workflow = context.workspace_workflow_summary(str(path.resolve()), quick=True)
        except Exception:
            continue
        profile = context.resolve_profile(data, None)
        runtime_root = str(data.get("运行目录", "")).strip()
        results.append(
            {
                "name": path.stem,
                "path": str(path.resolve()),
                "display_path": context.to_display_path(path),
                "flow_name": data.get("流域名称", path.stem),
                "flow_id": data.get("流域编号", path.stem),
                "object_type": context.detect_object_type(data),
                "calibration_mode": profile,
                "time_step_hours": context.normalize_time_step_hours(data.get("时间步长_小时", 24.0)),
                "workspace_root": runtime_root,
                "runtime_display_path": (context.to_display_path(Path(runtime_root)) if runtime_root else ""),
                "workflow": workflow,
                "updated_at": path.stat().st_mtime,
            }
        )
    return sorted(results, key=lambda item: item["updated_at"], reverse=True)


def load_workspace_config(path_value: str, context: WorkspaceCatalogContext) -> tuple[Path, dict[str, Any]]:
    path = context.resolve_any_path(path_value, must_exist=True)
    return path, context.read_runtime_config(path)


def delete_workspace(path_value: str, context: WorkspaceCatalogContext) -> dict[str, Any]:
    path = context.resolve_any_path(path_value, must_exist=True)
    context.ensure_within(context.workspace_dir, path)
    name = path.stem
    path.unlink()
    return {"deleted": True, "name": name, "path": str(path)}


def create_workspace_from_import(payload: dict[str, Any], context: WorkspaceCatalogContext) -> dict[str, Any]:
    basin_shp = str(payload.get("basin_shp", "")).strip()
    obs_csv = str(payload.get("obs_csv", "")).strip()
    calibration_mode = str(payload.get("calibration_mode", "")).strip().lower()
    object_type = str(payload.get("object_type", "")).strip().lower() or context.object_full_upstream
    if object_type not in {context.object_regression, context.object_interbasin, context.object_full_upstream}:
        object_type = context.object_full_upstream
    workspace_name = str(payload.get("workspace_name", "")).strip()
    prec_source = str(payload.get("prec_source", "era5")).strip()
    if not basin_shp:
        raise ValueError("缺少流域边界 shapefile。")
    if not obs_csv:
        raise ValueError("缺少观测径流文件。")
    shp_path = context.resolve_any_path(basin_shp, must_exist=True)
    obs_path = context.resolve_any_path(obs_csv, must_exist=True)
    obs_info = context.inspect_observed_csv(str(obs_path))
    suggested_mode = obs_info["suggested_calibration_mode"]
    profile = calibration_mode if calibration_mode in {context.profile_daily, context.profile_hourly} else suggested_mode
    start_date = pd.to_datetime(obs_info["start"])
    end_date = pd.to_datetime(obs_info["end"])
    bbox = context.fill_bbox_from_shp(str(shp_path))
    if bbox is None:
        raise ValueError("无法从 shapefile 中读取范围。")
    if not workspace_name:
        workspace_name = shp_path.stem

    windows = context.suggest_time_windows(start_date, end_date, profile)

    cfmax_threshold = 5000.0
    if context.builtin_dem.exists():
        try:
            cfmax_threshold = context.suggest_cfmax_threshold(str(shp_path), str(context.builtin_dem))["suggested_threshold_m"]
        except Exception:
            pass

    config = build_empty_workspace(workspace_name, profile, context)
    config.update(
        {
            "_说明": [
                "由 HBV-Studio 导入流域向导自动生成。",
                f"源数据: basin={shp_path.name}, obs={obs_path.name}",
            ],
            "项目对象": object_type,
            "率定模式": profile,
            "运行目录": str(runtime_root_for_workspace(workspace_name, context.project_runtime_dir)),
            "流域名称": workspace_name,
            "流域编号": slugify_workspace_name(workspace_name),
            "流域边界_shp": str(shp_path),
            context.observed_flow_key: str(obs_path),
            "时间步长_小时": 24.0 if profile == context.profile_daily else 1.0,
            "默认降水源": prec_source,
            "FAO56平均海拔_m": cfmax_threshold,
            "CFMAX分区阈值_m": cfmax_threshold,
            "范围_bbox": bbox,
            "时间": {
                "开始年份": int(start_date.year),
                "结束年份": int(end_date.year),
                **windows,
            },
        }
    )
    meteo = dict(config.get(context.meteo_key, {}))
    meteo[context.meteo_precip_source_key] = prec_source
    meteo[context.meteo_precip_source_legacy_key] = prec_source
    config[context.meteo_key] = meteo
    workspace_path = context.workspace_dir / f"{slugify_workspace_name(workspace_name)}.json"
    config["流域边界_shp"] = str(context.stage_vector_shapefile(config, shp_path, role="basin", config_path=workspace_path))
    if str(config.get("冰川边界_shp", "")).strip():
        config["冰川边界_shp"] = str(
            context.stage_vector_shapefile(config, config["冰川边界_shp"], role="glacier", config_path=workspace_path)
        )
    config[context.observed_flow_key] = str(context.stage_observed_runoff_file(config, obs_path, config_path=workspace_path))
    context.write_json_file(workspace_path, context.normalize_config_before_save(config, workspace_path))
    return {
        "workspace_path": str(workspace_path.resolve()),
        "config": context.read_json_file(workspace_path),
        "obs_info": obs_info,
        "suggested_mode": suggested_mode,
        "profile": profile,
    }
