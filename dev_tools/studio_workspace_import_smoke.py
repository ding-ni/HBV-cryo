#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Smoke checks for HBV-Studio workspace auto-import endpoint."""

from __future__ import annotations

import argparse
import json
import shutil
import time
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any


def request_json(url: str, timeout: float = 90.0, *, data: dict[str, Any] | None = None) -> dict[str, Any]:
    body = json.dumps(data, ensure_ascii=False).encode("utf-8") if data is not None else None
    request = urllib.request.Request(
        url,
        data=body,
        method="POST" if data is not None else "GET",
        headers={"Content-Type": "application/json"} if data is not None else {},
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8", errors="replace"))


def require_keys(payload: dict[str, Any], keys: set[str], label: str) -> None:
    missing = sorted(key for key in keys if key not in payload)
    if missing:
        raise RuntimeError(f"{label} missing keys: {missing}; payload={payload!r}")


def resolve_studio_path(value: Any) -> Path:
    text = str(value or "")
    project_root = Path.cwd().resolve()
    gui_root = project_root / "HBV-Studio"
    text = text.replace("__PROJECT_ROOT__", str(project_root))
    text = text.replace("__GUI_ROOT__", str(gui_root))
    return Path(text)


def safe_cleanup_workspace(workspace_path: Path | None, runtime_root: Path | None, workspace_name: str) -> None:
    if workspace_path is not None and workspace_path.exists() and workspace_name in workspace_path.stem:
        workspace_path.unlink()
    if runtime_root is not None and runtime_root.exists() and workspace_name in runtime_root.name:
        shutil.rmtree(runtime_root, ignore_errors=True)


def main() -> int:
    parser = argparse.ArgumentParser(description="Check /api/import-workspace creates and stages a workspace.")
    parser.add_argument("--url", default="http://127.0.0.1:8765")
    args = parser.parse_args()

    base_url = args.url.rstrip("/")
    asset_root = Path("HBV-Studio") / "templates" / "assets" / "tuotuohe"
    basin_shp = (asset_root / "tuotuohe_basin.shp").resolve()
    obs_csv = (asset_root / "discharge_tuotuohe.csv").resolve()
    workspace_name = f"Smoke_Auto_Config_{int(time.time())}"
    workspace_path: Path | None = None
    runtime_root: Path | None = None
    try:
        response = request_json(
            f"{base_url}/api/import-workspace",
            data={
                "basin_shp": str(basin_shp),
                "obs_csv": str(obs_csv),
                "workspace_name": workspace_name,
                "calibration_mode": "daily",
                "object_type": "regression_validation",
                "prec_source": "mswep",
            },
        )
        if not response.get("ok"):
            raise RuntimeError(response.get("error") or "workspace import endpoint returned ok=false")
        data = response.get("data") or {}
        require_keys(data, {"workspace_path", "config", "obs_info", "suggested_mode", "profile"}, "workspace import")
        workspace_path = Path(str(data.get("workspace_path") or ""))
        config = data.get("config") or {}
        runtime_root = resolve_studio_path(config.get("运行目录"))
        if not workspace_path.exists():
            raise RuntimeError(f"workspace import should create a workspace file: {data!r}")
        if data.get("profile") != "daily" or data.get("suggested_mode") != "daily":
            raise RuntimeError(f"workspace import should resolve daily mode for the fixture: {data!r}")
        if config.get("流域名称") != workspace_name:
            raise RuntimeError(f"workspace import should preserve workspace name: {config!r}")
        for key in ("流域边界_shp", "观测径流_csv"):
            staged = resolve_studio_path(config.get(key))
            if not staged.exists():
                raise RuntimeError(f"workspace import should stage {key}: {config!r}")
        bbox = config.get("范围_bbox") or {}
        if not all(bbox.get(key) is not None for key in ("北", "西", "南", "东")):
            raise RuntimeError(f"workspace import should populate bbox: {config!r}")
        obs_info = data.get("obs_info") or {}
        if int(obs_info.get("valid_rows") or 0) <= 0:
            raise RuntimeError(f"workspace import should inspect observed runoff: {data!r}")

        query = urllib.parse.urlencode({"path": str(workspace_path)})
        loaded = request_json(f"{base_url}/api/workspace?{query}")
        if not loaded.get("ok"):
            raise RuntimeError(loaded.get("error") or "created workspace should load through /api/workspace")
        loaded_config = loaded.get("data") or {}
        if loaded_config.get("流域名称") != workspace_name:
            raise RuntimeError(f"created workspace load mismatch: {loaded!r}")

        summary = {
            "workspace_name": workspace_name,
            "profile": data.get("profile"),
            "suggested_mode": data.get("suggested_mode"),
            "workspace_file": str(workspace_path),
            "runtime_root": str(runtime_root),
            "observed_valid_rows": obs_info.get("valid_rows"),
        }
        print(json.dumps(summary, ensure_ascii=False, indent=2))
        return 0
    finally:
        safe_cleanup_workspace(workspace_path, runtime_root, workspace_name)


if __name__ == "__main__":
    raise SystemExit(main())
