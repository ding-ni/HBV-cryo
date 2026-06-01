#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Smoke checks for HBV-Studio boundary inflow preview endpoint."""

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


def default_boundary_path(workspace_config: str) -> str:
    path = Path("HBV-Studio") / workspace_config
    data = json.loads(path.read_text(encoding="utf-8"))
    value = str(data.get("观测径流_csv", "") or "").strip()
    if not value:
        raise RuntimeError(f"workspace config missing 观测径流_csv: {path}")
    return value


def main() -> int:
    parser = argparse.ArgumentParser(description="Check /api/boundary-preview for a known daily CSV.")
    parser.add_argument("--url", default="http://127.0.0.1:8765")
    parser.add_argument("--workspace-config", default="workspaces/tuotuohe_test.json")
    parser.add_argument("--boundary-path", default="")
    args = parser.parse_args()

    base_url = args.url.rstrip("/")
    boundary_path = args.boundary_path or default_boundary_path(args.workspace_config)
    config_path = str((Path("HBV-Studio") / args.workspace_config).resolve())
    query = urllib.parse.urlencode(
        {
            "path": boundary_path,
            "date_field": "date",
            "flow_field": "discharge (m3/s)",
            "config_path": config_path,
        }
    )
    payload = request_json(f"{base_url}/api/boundary-preview?{query}")
    if not payload.get("ok"):
        raise RuntimeError(payload.get("error") or "boundary-preview endpoint returned ok=false")
    data = payload.get("data") or {}
    required = {
        "columns",
        "total_rows",
        "valid_rows",
        "time_step_hours",
        "expected_time_step_hours",
        "coverage_ratio",
        "expected_steps",
        "missing_count",
        "out_of_range_count",
        "date_range",
        "flow_stats",
        "preview",
    }
    missing = sorted(key for key in required if key not in data)
    if missing:
        raise RuntimeError(f"boundary-preview missing keys: {missing}; payload={data!r}")
    if int(data.get("total_rows") or 0) <= 0 or int(data.get("valid_rows") or 0) <= 0:
        raise RuntimeError(f"boundary-preview should include positive row counts: {data!r}")
    if float(data.get("time_step_hours") or 0) != 24.0:
        raise RuntimeError(f"boundary-preview should detect a daily time step: {data!r}")
    if float(data.get("expected_time_step_hours") or 0) != 24.0:
        raise RuntimeError(f"boundary-preview should infer daily expected time step: {data!r}")
    if float(data.get("coverage_ratio") or 0.0) < 0.99:
        raise RuntimeError(f"boundary-preview should cover the known workspace range: {data!r}")
    if int(data.get("duplicate_count") or 0) != 0:
        raise RuntimeError(f"boundary-preview should not report duplicate timestamps: {data!r}")
    if not data.get("preview"):
        raise RuntimeError(f"boundary-preview should include preview rows: {data!r}")

    summary = {
        "total_rows": data.get("total_rows"),
        "valid_rows": data.get("valid_rows"),
        "time_step_hours": data.get("time_step_hours"),
        "expected_time_step_hours": data.get("expected_time_step_hours"),
        "coverage_ratio": data.get("coverage_ratio"),
        "missing_count": data.get("missing_count"),
        "out_of_range_count": data.get("out_of_range_count"),
        "date_range": data.get("date_range"),
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
