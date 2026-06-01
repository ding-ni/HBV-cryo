#!/usr/bin/env python
# -*- coding: utf-8 -*-
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable


@dataclass(frozen=True)
class WorkspaceCatalogContext:
    template_dir: Path
    workspace_dir: Path
    default_workspace_path: Path
    builtin_glacier_shp: Path
    profile_daily: str
    object_regression: str
    observed_flow_key: str
    read_json_file: Callable[[Path], dict[str, Any]]
    read_runtime_config: Callable[[Path], dict[str, Any]]
    replace_placeholders: Callable[[Any], Any]
    resolve_any_path: Callable[..., Path]
    resolve_profile: Callable[[dict[str, Any], str | None], str]
    normalize_config_before_save: Callable[[dict[str, Any], Path], dict[str, Any]]
    detect_object_type: Callable[[dict[str, Any]], str]
    slugify_workspace_name: Callable[[str], str]
    runtime_root_for_workspace: Callable[[str], Path]
    write_json_file: Callable[[Path, Any], None]
    to_display_path: Callable[[Path], str]
    workspace_workflow_summary: Callable[..., dict[str, Any]]
    normalize_time_step_hours: Callable[[Any], float]
    ensure_within: Callable[[Path, Path], Path]


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
        config["流域编号"] = context.slugify_workspace_name(target_name)
    if template_id == "blank-workspace":
        config["运行目录"] = str(context.runtime_root_for_workspace(target_name))
    workspace_path = context.workspace_dir / f"{context.slugify_workspace_name(target_name)}.json"
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
