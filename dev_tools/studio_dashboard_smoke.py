#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Smoke checks for HBV-Studio dashboard endpoint."""

from __future__ import annotations

import argparse
import json
import urllib.request
from typing import Any


def request_json(url: str, timeout: float = 30.0) -> dict[str, Any]:
    with urllib.request.urlopen(url, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8", errors="replace"))


def main() -> int:
    parser = argparse.ArgumentParser(description="Check /api/dashboard aggregate payload.")
    parser.add_argument("--url", default="http://127.0.0.1:8765")
    args = parser.parse_args()

    base_url = args.url.rstrip("/")
    payload = request_json(f"{base_url}/api/dashboard")
    if not payload.get("ok"):
        raise RuntimeError(payload.get("error") or "dashboard endpoint returned ok=false")
    data = payload.get("data") or {}
    project = data.get("project") or {}
    counts = data.get("counts") or {}
    for key in ("project_root", "gui_root", "builtin_dem", "builtin_dems", "runtime_root"):
        if not project.get(key):
            raise RuntimeError(f"dashboard project missing {key}: {project!r}")
    builtin_dems = project.get("builtin_dems") or {}
    if not builtin_dems.get("1km") or not builtin_dems.get("0p1deg"):
        raise RuntimeError(f"dashboard builtin_dems is incomplete: {builtin_dems!r}")
    for key in ("templates", "workspaces", "runs", "tasks"):
        items = data.get(key)
        if not isinstance(items, list):
            raise RuntimeError(f"dashboard {key} should be a list")
        if int(counts.get(key, -1)) != len(items):
            raise RuntimeError(f"dashboard {key} count mismatch: count={counts.get(key)!r}, len={len(items)}")
    if counts.get("workspaces", 0) <= 0:
        raise RuntimeError("dashboard should include at least one workspace in this repository")
    if not any(str(item.get("flow_name", "")).strip() == "沱沱河" for item in data.get("workspaces", [])):
        raise RuntimeError("dashboard workspaces should include 沱沱河 test workspace")

    summary = {
        "counts": counts,
        "project_root": project.get("project_root"),
        "runtime_root": project.get("runtime_root"),
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
