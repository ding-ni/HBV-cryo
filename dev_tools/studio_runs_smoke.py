#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Smoke checks for HBV-Studio run listing endpoint."""

from __future__ import annotations

import argparse
import json
import urllib.request
from typing import Any


def request_json(url: str, timeout: float = 60.0) -> dict[str, Any]:
    with urllib.request.urlopen(url, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8", errors="replace"))


def require_keys(payload: dict[str, Any], keys: set[str], label: str) -> None:
    missing = sorted(key for key in keys if key not in payload)
    if missing:
        raise RuntimeError(f"{label} missing keys: {missing}; payload={payload!r}")


def main() -> int:
    parser = argparse.ArgumentParser(description="Check /api/runs for discovered run summaries.")
    parser.add_argument("--url", default="http://127.0.0.1:8765")
    parser.add_argument("--require-runs", action="store_true")
    args = parser.parse_args()

    base_url = args.url.rstrip("/")
    payload = request_json(f"{base_url}/api/runs")
    if not payload.get("ok"):
        raise RuntimeError(payload.get("error") or "runs endpoint returned ok=false")
    runs = payload.get("data")
    if not isinstance(runs, list):
        raise RuntimeError(f"runs endpoint should return a list: {payload!r}")
    if args.require_runs and not runs:
        raise RuntimeError("runs endpoint returned no runs in a workspace expected to contain results")

    if runs:
        required = {
            "name",
            "display_name",
            "path",
            "display_path",
            "updated_at",
            "updated_at_ns",
            "run_type",
            "run_type_label",
            "workspace_name",
            "studio_compatible",
            "hydrology_summary",
            "forecast_source_ready",
        }
        require_keys(runs[0], required, "first run summary")
        timestamps = [float(item.get("updated_at") or 0.0) for item in runs]
        if timestamps != sorted(timestamps, reverse=True):
            raise RuntimeError("runs endpoint should return items sorted by updated_at descending")

    dashboard_payload = request_json(f"{base_url}/api/dashboard")
    if not dashboard_payload.get("ok"):
        raise RuntimeError(dashboard_payload.get("error") or "dashboard endpoint returned ok=false")
    dashboard = dashboard_payload.get("data") or {}
    dashboard_count = int((dashboard.get("counts") or {}).get("runs") or 0)
    if dashboard_count != len(runs):
        raise RuntimeError(f"dashboard run count mismatch: dashboard={dashboard_count}, runs={len(runs)}")

    summary = {
        "run_count": len(runs),
        "first_run": {
            "name": runs[0].get("name"),
            "run_type": runs[0].get("run_type"),
            "workspace_name": runs[0].get("workspace_name"),
            "studio_compatible": runs[0].get("studio_compatible"),
        }
        if runs
        else None,
        "dashboard_count": dashboard_count,
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
