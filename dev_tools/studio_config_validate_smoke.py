#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Smoke checks for HBV-Studio workspace config validation endpoint."""

from __future__ import annotations

import argparse
import json
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any


def request_json(url: str, timeout: float = 60.0) -> dict[str, Any]:
    with urllib.request.urlopen(url, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8", errors="replace"))


def require_keys(payload: dict[str, Any], keys: set[str], label: str) -> None:
    missing = sorted(key for key in keys if key not in payload)
    if missing:
        raise RuntimeError(f"{label} missing keys: {missing}; payload={payload!r}")


def validate_stage(base_url: str, config_path: str, stage: str) -> dict[str, Any]:
    query = urllib.parse.urlencode({"config_path": config_path, "stage": stage})
    payload = request_json(f"{base_url}/api/config/validate?{query}")
    if not payload.get("ok"):
        raise RuntimeError(payload.get("error") or f"config validate returned ok=false for {stage}")
    data = payload.get("data") or {}
    require_keys(
        data,
        {
            "valid",
            "missing",
            "warnings",
            "profile",
            "object_type",
            "stage",
            "focus_checks",
            "input_time_summary",
            "time_basis",
            "time_basis_label",
        },
        f"config validate {stage}",
    )
    if data.get("profile") != "daily":
        raise RuntimeError(f"known workspace should validate as daily profile: {data!r}")
    if data.get("object_type") != "regression_validation":
        raise RuntimeError(f"known workspace should keep regression_validation object type: {data!r}")
    if data.get("stage") != stage:
        raise RuntimeError(f"config validate returned wrong stage for {stage}: {data!r}")
    if not isinstance(data.get("missing"), list) or not isinstance(data.get("warnings"), list):
        raise RuntimeError(f"config validate should return list diagnostics for {stage}: {data!r}")
    if not isinstance(data.get("focus_checks"), list):
        raise RuntimeError(f"config validate should return focus check list for {stage}: {data!r}")
    return data


def main() -> int:
    parser = argparse.ArgumentParser(description="Check /api/config/validate for a known workspace.")
    parser.add_argument("--url", default="http://127.0.0.1:8765")
    parser.add_argument("--workspace-config", default="workspaces/tuotuohe_test.json")
    args = parser.parse_args()

    base_url = args.url.rstrip("/")
    config_path = str((Path("HBV-Studio") / args.workspace_config).resolve())
    quick_test = validate_stage(base_url, config_path, "quick_test")
    calibration = validate_stage(base_url, config_path, "calibration")
    if not quick_test.get("valid"):
        raise RuntimeError(f"known workspace should pass quick_test validation: {quick_test!r}")

    summary = {
        "quick_test": {
            "valid": quick_test.get("valid"),
            "missing_count": len(quick_test.get("missing") or []),
            "warning_count": len(quick_test.get("warnings") or []),
            "focus_check_count": len(quick_test.get("focus_checks") or []),
        },
        "calibration": {
            "valid": calibration.get("valid"),
            "missing_count": len(calibration.get("missing") or []),
            "warning_count": len(calibration.get("warnings") or []),
            "focus_check_count": len(calibration.get("focus_checks") or []),
        },
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
