#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Smoke checks for HBV-Studio observed-flow info endpoint."""

from __future__ import annotations

import argparse
import json
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any


def request_json(url: str, timeout: float = 45.0) -> dict[str, Any]:
    with urllib.request.urlopen(url, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8", errors="replace"))


def default_observed_path(workspace_config: str) -> str:
    path = Path("HBV-Studio") / workspace_config
    data = json.loads(path.read_text(encoding="utf-8"))
    value = str(data.get("观测径流_csv", "") or "").strip()
    if not value:
        raise RuntimeError(f"workspace config missing 观测径流_csv: {path}")
    return value


def main() -> int:
    parser = argparse.ArgumentParser(description="Check /api/obs-info for a known observed-flow CSV.")
    parser.add_argument("--url", default="http://127.0.0.1:8765")
    parser.add_argument("--workspace-config", default="workspaces/tuotuohe_test.json")
    parser.add_argument("--observed-path", default="")
    args = parser.parse_args()

    base_url = args.url.rstrip("/")
    observed_path = args.observed_path or default_observed_path(args.workspace_config)
    query = urllib.parse.urlencode({"path": observed_path, "target_step_hours": "24"})
    payload = request_json(f"{base_url}/api/obs-info?{query}")
    if not payload.get("ok"):
        raise RuntimeError(payload.get("error") or "obs-info endpoint returned ok=false")
    data = payload.get("data") or {}
    if not data.get("date_field") or not data.get("flow_field"):
        raise RuntimeError(f"obs-info should include detected date/flow fields: {data!r}")
    if int(data.get("row_count") or 0) <= 0 or int(data.get("valid_rows") or 0) <= 0:
        raise RuntimeError(f"obs-info should include positive row counts: {data!r}")
    if not data.get("start") or not data.get("end"):
        raise RuntimeError(f"obs-info should include date range: {data!r}")
    if not data.get("suggested_calibration_mode"):
        raise RuntimeError(f"obs-info should suggest calibration mode: {data!r}")

    summary = {
        "date_field": data.get("date_field"),
        "flow_field": data.get("flow_field"),
        "row_count": data.get("row_count"),
        "valid_rows": data.get("valid_rows"),
        "start": data.get("start"),
        "end": data.get("end"),
        "suggested_calibration_mode": data.get("suggested_calibration_mode"),
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
