#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Smoke checks for HBV-Studio wizard validation endpoints."""

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


def require_keys(payload: dict[str, Any], keys: set[str], label: str) -> None:
    missing = sorted(key for key in keys if key not in payload)
    if missing:
        raise RuntimeError(f"{label} missing keys: {missing}; payload={payload!r}")


def main() -> int:
    parser = argparse.ArgumentParser(description="Check wizard validation endpoints for a known workspace.")
    parser.add_argument("--url", default="http://127.0.0.1:8765")
    parser.add_argument("--workspace-config", default="workspaces/tuotuohe_test.json")
    args = parser.parse_args()

    base_url = args.url.rstrip("/")
    config_path = str((Path("HBV-Studio") / args.workspace_config).resolve())
    step_summaries: list[dict[str, Any]] = []
    for step in (1, 2, 3, 4):
        query = urllib.parse.urlencode({"config_path": config_path, "step": str(step)})
        payload = request_json(f"{base_url}/api/wizard/validate-step?{query}")
        if not payload.get("ok"):
            raise RuntimeError(payload.get("error") or f"wizard validate step {step} returned ok=false")
        data = payload.get("data") or {}
        require_keys(data, {"step", "valid", "missing", "warnings"}, f"wizard step {step}")
        if int(data.get("step") or 0) != step:
            raise RuntimeError(f"wizard step {step} returned wrong step: {data!r}")
        if not isinstance(data.get("missing"), list) or not isinstance(data.get("warnings"), list):
            raise RuntimeError(f"wizard step {step} should return list diagnostics: {data!r}")
        step_summaries.append(
            {
                "step": data.get("step"),
                "valid": data.get("valid"),
                "missing_count": len(data.get("missing") or []),
                "warning_count": len(data.get("warnings") or []),
            }
        )

    validate_query = urllib.parse.urlencode({"config_path": config_path, "stage": "quick_test"})
    validate_payload = request_json(f"{base_url}/api/config/validate?{validate_query}")
    if not validate_payload.get("ok"):
        raise RuntimeError(validate_payload.get("error") or "config validate returned ok=false")
    validate_data = validate_payload.get("data") or {}
    require_keys(
        validate_data,
        {"valid", "missing", "warnings", "profile", "object_type", "stage"},
        "config validate",
    )
    if validate_data.get("profile") != "daily":
        raise RuntimeError(f"known workspace should validate as daily profile: {validate_data!r}")

    summary = {
        "wizard_steps": step_summaries,
        "config_validate": {
            "valid": validate_data.get("valid"),
            "profile": validate_data.get("profile"),
            "object_type": validate_data.get("object_type"),
            "stage": validate_data.get("stage"),
            "missing_count": len(validate_data.get("missing") or []),
            "warning_count": len(validate_data.get("warnings") or []),
        },
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
