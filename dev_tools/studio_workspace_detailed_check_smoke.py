#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Smoke checks for HBV-Studio workspace detailed-check endpoint."""

from __future__ import annotations

import argparse
import json
import shutil
import tempfile
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any


def request_json(url: str, timeout: float = 90.0) -> dict[str, Any]:
    with urllib.request.urlopen(url, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8", errors="replace"))


def require_keys(payload: dict[str, Any], keys: set[str], label: str) -> None:
    missing = sorted(key for key in keys if key not in payload)
    if missing:
        raise RuntimeError(f"{label} missing keys: {missing}; payload={payload!r}")


def main() -> int:
    parser = argparse.ArgumentParser(description="Check /api/workspace/detailed-check for a known workspace.")
    parser.add_argument("--url", default="http://127.0.0.1:8765")
    args = parser.parse_args()

    base_url = args.url.rstrip("/")
    temp_root = Path(tempfile.mkdtemp(prefix="hbvstudio_detailed_check_"))
    try:
        workspace_root = temp_root / "workspace"
        workspace_root.mkdir(parents=True, exist_ok=True)
        config_path = temp_root / "detailed_check_workspace.json"
        config_path.write_text(
            json.dumps(
                {
                    "流域名称": "Smoke Detailed Check",
                    "流域编号": "smoke_detailed_check",
                    "项目对象": "regression_validation",
                    "率定模式": "daily",
                    "运行目录": str(workspace_root),
                    "时间步长_小时": 24.0,
                    "时间": {
                        "预热开始": "2020-01-01",
                        "预热结束": "2020-01-05",
                        "率定开始": "2020-01-06",
                        "率定结束": "2020-01-10",
                        "验证开始": "2020-01-11",
                        "验证结束": "2020-01-15",
                    },
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
        query = urllib.parse.urlencode({"config_path": str(config_path)})
        payload = request_json(f"{base_url}/api/workspace/detailed-check?{query}")
        if not payload.get("ok"):
            raise RuntimeError(payload.get("error") or "workspace detailed-check endpoint returned ok=false")
        data = payload.get("data") or {}
        require_keys(data, {"summary", "reasonableness_checks", "all_ok", "profile", "object_type"}, "workspace detailed-check")
        if data.get("profile") != "daily":
            raise RuntimeError(f"temporary workspace should be daily profile: {data!r}")
        if data.get("object_type") != "regression_validation":
            raise RuntimeError(f"temporary workspace should keep regression_validation object type: {data!r}")
        summary = data.get("summary") or []
        reasonableness = data.get("reasonableness_checks") or []
        if len(summary) < 15:
            raise RuntimeError(f"detailed-check should include rich summary rows: {data!r}")
        if not reasonableness:
            raise RuntimeError("detailed-check should include reasonableness checks")
        groups = {str(item.get("group") or "") for item in summary if isinstance(item, dict)}
        required_groups = {"基本配置", "时间分段", "地理数据", "气象数据", "输入文件"}
        missing_groups = sorted(required_groups - groups)
        if missing_groups:
            raise RuntimeError(f"detailed-check missing summary groups: {missing_groups}; groups={sorted(groups)!r}")
        if not isinstance(data.get("all_ok"), bool):
            raise RuntimeError(f"detailed-check all_ok should be boolean: {data!r}")

        summary_payload = {
            "profile": data.get("profile"),
            "object_type": data.get("object_type"),
            "all_ok": data.get("all_ok"),
            "summary_count": len(summary),
            "reasonableness_count": len(reasonableness),
            "groups": sorted(groups),
        }
        print(json.dumps(summary_payload, ensure_ascii=False, indent=2))
        return 0
    finally:
        shutil.rmtree(temp_root, ignore_errors=True)


if __name__ == "__main__":
    raise SystemExit(main())
