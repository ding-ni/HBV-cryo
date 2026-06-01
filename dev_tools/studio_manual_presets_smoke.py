#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Smoke checks for HBV-Studio manual preset endpoints."""

from __future__ import annotations

import argparse
import json
import shutil
import tempfile
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any


def request_json(url: str, timeout: float = 60.0, *, data: dict[str, Any] | None = None) -> dict[str, Any]:
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


def list_presets(base_url: str, config_path: Path, *, scope: str = "workspace") -> dict[str, Any]:
    query = urllib.parse.urlencode(
        {
            "config_path": str(config_path),
            "calibration_profile": "daily",
            "scope": scope,
        }
    )
    payload = request_json(f"{base_url}/api/manual-presets?{query}")
    if not payload.get("ok"):
        raise RuntimeError(payload.get("error") or "manual presets endpoint returned ok=false")
    data = payload.get("data") or {}
    require_keys(data, {"config_path", "store_path", "scope", "calibration_profile", "presets"}, "manual presets")
    return data


def main() -> int:
    parser = argparse.ArgumentParser(description="Check manual preset list/save/delete endpoints.")
    parser.add_argument("--url", default="http://127.0.0.1:8765")
    args = parser.parse_args()

    base_url = args.url.rstrip("/")
    temp_root = Path(tempfile.mkdtemp(prefix="hbvstudio_manual_presets_"))
    try:
        workspace_root = temp_root / "workspace"
        workspace_root.mkdir(parents=True, exist_ok=True)
        config_path = temp_root / "manual_preset_workspace.json"
        config_path.write_text(
            json.dumps(
                {
                    "流域名称": "Smoke Manual Preset",
                    "流域编号": "smoke_manual_preset",
                    "项目对象": "regression_validation",
                    "率定模式": "daily",
                    "运行目录": str(workspace_root),
                    "时间步长_小时": 24.0,
                    "气象策略": {
                        "降水方案": "grid_only",
                        "降水来源": "mswep",
                        "降水源": "mswep",
                    },
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )

        initial = list_presets(base_url, config_path)
        if initial.get("scope") != "workspace":
            raise RuntimeError(f"unexpected initial manual preset scope: {initial!r}")
        if initial.get("presets"):
            raise RuntimeError(f"temporary workspace should start without presets: {initial!r}")

        save_response = request_json(
            f"{base_url}/api/manual-preset/save",
            data={
                "config_path": str(config_path),
                "name": "Smoke Manual Preset",
                "scope": "workspace",
                "calibration_profile": "daily",
                "params": {"TT": -1.0, "FC": 120.0},
                "prec_source": "mswep",
                "glacier_mode": "off",
                "notes": "smoke test",
            },
        )
        if not save_response.get("ok"):
            raise RuntimeError(save_response.get("error") or "manual preset save endpoint returned ok=false")
        save_data = save_response.get("data") or {}
        require_keys(save_data, {"saved", "preset", "store_path"}, "manual preset save")
        preset = save_data.get("preset") or {}
        require_keys(preset, {"id", "name", "scope", "parameters", "calibration_profile"}, "saved manual preset")
        if not save_data.get("saved") or preset.get("name") != "Smoke Manual Preset":
            raise RuntimeError(f"manual preset save did not return the saved preset: {save_data!r}")
        if preset.get("scope") != "workspace" or preset.get("calibration_profile") != "daily":
            raise RuntimeError(f"manual preset save returned wrong metadata: {preset!r}")
        store_path = Path(str(save_data.get("store_path") or ""))
        if not store_path.exists():
            raise RuntimeError(f"manual preset save should create a store file: {save_data!r}")

        listed = list_presets(base_url, config_path)
        presets = listed.get("presets") or []
        if len(presets) != 1 or presets[0].get("id") != preset.get("id"):
            raise RuntimeError(f"manual preset list should include the saved preset: {listed!r}")

        delete_response = request_json(
            f"{base_url}/api/manual-preset/delete",
            data={
                "config_path": str(config_path),
                "preset_id": str(preset.get("id")),
                "scope": "workspace",
            },
        )
        if not delete_response.get("ok"):
            raise RuntimeError(delete_response.get("error") or "manual preset delete endpoint returned ok=false")
        delete_data = delete_response.get("data") or {}
        require_keys(delete_data, {"deleted", "preset_id", "store_path"}, "manual preset delete")
        if not delete_data.get("deleted"):
            raise RuntimeError(f"manual preset delete did not report success: {delete_data!r}")

        after_delete = list_presets(base_url, config_path)
        if after_delete.get("presets"):
            raise RuntimeError(f"manual preset delete should remove the temporary preset: {after_delete!r}")

        summary = {
            "saved": True,
            "deleted": True,
            "store_path": str(store_path),
            "preset_count_after_delete": len(after_delete.get("presets") or []),
        }
        print(json.dumps(summary, ensure_ascii=False, indent=2))
        return 0
    finally:
        shutil.rmtree(temp_root, ignore_errors=True)


if __name__ == "__main__":
    raise SystemExit(main())
