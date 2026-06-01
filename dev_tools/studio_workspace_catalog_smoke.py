#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Smoke checks for HBV-Studio workspace catalog endpoints."""

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
    parser = argparse.ArgumentParser(description="Check template and workspace catalog endpoints.")
    parser.add_argument("--url", default="http://127.0.0.1:8765")
    parser.add_argument("--workspace-config", default="workspaces/tuotuohe_test.json")
    args = parser.parse_args()

    base_url = args.url.rstrip("/")

    templates_payload = request_json(f"{base_url}/api/templates")
    if not templates_payload.get("ok"):
        raise RuntimeError(templates_payload.get("error") or "templates endpoint returned ok=false")
    templates = templates_payload.get("data") or []
    if not isinstance(templates, list) or not templates:
        raise RuntimeError("templates endpoint should return a non-empty list")
    required_template_keys = {"id", "title", "calibration_mode", "object_type", "path", "assets_ready"}
    if not required_template_keys <= set(templates[0]):
        raise RuntimeError(f"template item is missing required keys: {templates[0]!r}")

    workspaces_payload = request_json(f"{base_url}/api/workspaces")
    if not workspaces_payload.get("ok"):
        raise RuntimeError(workspaces_payload.get("error") or "workspaces endpoint returned ok=false")
    workspaces = workspaces_payload.get("data") or []
    if not isinstance(workspaces, list) or not workspaces:
        raise RuntimeError("workspaces endpoint should return a non-empty list")
    tuotuohe = next((item for item in workspaces if str(item.get("flow_name", "")).strip() == "沱沱河"), None)
    if not tuotuohe:
        raise RuntimeError("workspaces endpoint should include 沱沱河")
    for key in ("path", "workflow", "calibration_mode", "object_type", "updated_at"):
        if key not in tuotuohe:
            raise RuntimeError(f"沱沱河 workspace item missing {key}: {tuotuohe!r}")

    query = urllib.parse.urlencode({"path": args.workspace_config})
    workspace_payload = request_json(f"{base_url}/api/workspace?{query}")
    if not workspace_payload.get("ok"):
        raise RuntimeError(workspace_payload.get("error") or "workspace endpoint returned ok=false")
    config = workspace_payload.get("data") or {}
    if str(config.get("流域名称", "")).strip() != "沱沱河":
        raise RuntimeError(f"unexpected workspace flow name: {config.get('流域名称')!r}")
    if not workspace_payload.get("display_path"):
        raise RuntimeError("workspace endpoint should include display_path")

    summary = {
        "template_count": len(templates),
        "workspace_count": len(workspaces),
        "tuotuohe_profile": tuotuohe.get("calibration_mode"),
        "workspace_display_path": workspace_payload.get("display_path"),
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
