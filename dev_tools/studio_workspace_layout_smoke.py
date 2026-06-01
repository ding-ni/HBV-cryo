#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Smoke checks for HBV-Studio workspace layout endpoint."""

from __future__ import annotations

import argparse
import json
import urllib.parse
import urllib.request
from typing import Any


def request_json(url: str, timeout: float = 30.0) -> dict[str, Any]:
    with urllib.request.urlopen(url, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8", errors="replace"))


def main() -> int:
    parser = argparse.ArgumentParser(description="Check /api/workspace/layout for a known workspace.")
    parser.add_argument("--url", default="http://127.0.0.1:8765")
    parser.add_argument("--workspace-config", default="workspaces/tuotuohe_test.json")
    args = parser.parse_args()

    base_url = args.url.rstrip("/")
    query = urllib.parse.urlencode({"config_path": args.workspace_config})
    payload = request_json(f"{base_url}/api/workspace/layout?{query}")
    if not payload.get("ok"):
        raise RuntimeError(payload.get("error") or "workspace layout endpoint returned ok=false")
    data = payload.get("data") or {}
    if data.get("flow_name") != "沱沱河":
        raise RuntimeError(f"unexpected flow_name: {data.get('flow_name')!r}")
    if data.get("profile") != "daily":
        raise RuntimeError(f"unexpected profile: {data.get('profile')!r}")
    if not data.get("workspace_root") or not data.get("results_root"):
        raise RuntimeError("layout is missing workspace_root or results_root")
    groups = data.get("groups") or []
    if len(groups) < 3:
        raise RuntimeError(f"expected at least 3 layout groups, got {len(groups)}")
    items = [item for group in groups for item in (group.get("items") or [])]
    labels = {item.get("label") for item in items}
    required_labels = {"工作区配置文件", "工程根目录", "地理数据目录", "标准气象驱动目录"}
    missing_labels = sorted(required_labels - labels)
    if missing_labels:
        raise RuntimeError(f"layout missing labels: {missing_labels}")
    if not any(str(label or "").endswith("结果目录") for label in labels):
        raise RuntimeError(f"layout missing profile result directory label: {sorted(labels)}")
    if not any(item.get("exists") for item in items if item.get("label") == "工作区配置文件"):
        raise RuntimeError("workspace config file item should exist")
    next_focus = data.get("next_focus") or {}
    if not next_focus.get("label") or not next_focus.get("reason"):
        raise RuntimeError(f"layout next_focus is incomplete: {next_focus}")
    notes = data.get("notes") or []
    if not notes:
        raise RuntimeError("layout notes should not be empty")

    summary = {
        "flow_name": data.get("flow_name"),
        "profile": data.get("profile"),
        "group_count": len(groups),
        "item_count": len(items),
        "next_focus": next_focus,
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
