#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Smoke checks for HBV-Studio run listing endpoint."""

from __future__ import annotations

import argparse
import json
import urllib.parse
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

    run_detail_summary = None
    if runs:
        detail_query = urllib.parse.urlencode({"path": str(runs[0].get("path") or "")})
        detail_payload = request_json(f"{base_url}/api/run?{detail_query}")
        if not detail_payload.get("ok"):
            raise RuntimeError(detail_payload.get("error") or "run detail endpoint returned ok=false")
        detail = detail_payload.get("data") or {}
        require_keys(
            detail,
            {"run", "metadata", "hydrology_summary", "series", "series_range", "sampling", "parameters", "studio_compatible"},
            "run detail",
        )
        run_summary = detail.get("run") or {}
        require_keys(run_summary, {"name", "path", "updated_at", "hydrology_summary"}, "run detail summary")
        series = detail.get("series") or {}
        sampling = detail.get("sampling") or {}
        if not isinstance(series.get("dates"), list):
            raise RuntimeError(f"run detail should return date series: {detail!r}")
        sampled_points = int(sampling.get("sampled_points") or 0)
        total_points = int(sampling.get("total_points") or 0)
        if sampled_points <= 0 or total_points <= 0:
            raise RuntimeError(f"run detail should include positive sampling counts: {detail!r}")
        if sampled_points != len(series.get("dates") or []):
            raise RuntimeError(
                f"run detail sampled_points mismatch: sampled={sampled_points}, dates={len(series.get('dates') or [])}"
            )
        run_detail_summary = {
            "name": run_summary.get("name"),
            "sampled_points": sampled_points,
            "total_points": total_points,
            "studio_compatible": detail.get("studio_compatible"),
        }

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
        "run_detail": run_detail_summary,
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
