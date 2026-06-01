#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Smoke checks for HBV-Studio workspace completeness endpoint."""

from __future__ import annotations

import argparse
import json
import urllib.parse
import urllib.request
from typing import Any


def request_json(url: str, timeout: float = 30.0) -> dict[str, Any]:
    with urllib.request.urlopen(url, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8", errors="replace"))


def fetch_completeness(base_url: str, workspace_config: str, *, quick: bool) -> dict[str, Any]:
    query = urllib.parse.urlencode(
        {
            "config_path": workspace_config,
            "quick": "1" if quick else "0",
        }
    )
    payload = request_json(f"{base_url}/api/workspace/completeness?{query}")
    if not payload.get("ok"):
        raise RuntimeError(payload.get("error") or "workspace completeness endpoint returned ok=false")
    return payload.get("data") or {}


def check_completeness(data: dict[str, Any], *, quick: bool) -> None:
    mode = "quick" if quick else "full"
    if data.get("profile") != "daily":
        raise RuntimeError(f"{mode} completeness unexpected profile: {data.get('profile')!r}")
    all_steps = data.get("all_steps") or []
    completed = data.get("steps_completed") or []
    remaining = data.get("steps_remaining") or []
    if len(all_steps) < 6:
        raise RuntimeError(f"{mode} completeness has too few steps: {all_steps!r}")
    if int(data.get("total_steps") or 0) != len(all_steps):
        raise RuntimeError(f"{mode} completeness total_steps mismatch: {data!r}")
    if int(data.get("completed_count") or 0) != len(completed):
        raise RuntimeError(f"{mode} completeness completed_count mismatch: {data!r}")
    if len(completed) + len(remaining) != len(all_steps):
        raise RuntimeError(f"{mode} completeness step partition mismatch: {data!r}")
    ratio = float(data.get("completion_ratio") or 0.0)
    if ratio < 0.0 or ratio > 1.0:
        raise RuntimeError(f"{mode} completeness invalid completion_ratio: {ratio!r}")
    if not isinstance(data.get("ready_for_calibration"), bool):
        raise RuntimeError(f"{mode} readiness should be boolean")
    if not data.get("object_type"):
        raise RuntimeError(f"{mode} completeness missing object_type")


def main() -> int:
    parser = argparse.ArgumentParser(description="Check /api/workspace/completeness for a known workspace.")
    parser.add_argument("--url", default="http://127.0.0.1:8765")
    parser.add_argument("--workspace-config", default="workspaces/tuotuohe_test.json")
    args = parser.parse_args()

    base_url = args.url.rstrip("/")
    full = fetch_completeness(base_url, args.workspace_config, quick=False)
    quick = fetch_completeness(base_url, args.workspace_config, quick=True)
    check_completeness(full, quick=False)
    check_completeness(quick, quick=True)

    summary = {
        "full": {
            "profile": full.get("profile"),
            "completed_count": full.get("completed_count"),
            "total_steps": full.get("total_steps"),
            "ready_for_calibration": full.get("ready_for_calibration"),
            "next_step": full.get("next_step"),
        },
        "quick": {
            "profile": quick.get("profile"),
            "completed_count": quick.get("completed_count"),
            "total_steps": quick.get("total_steps"),
            "ready_for_calibration": quick.get("ready_for_calibration"),
            "next_step": quick.get("next_step"),
        },
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
