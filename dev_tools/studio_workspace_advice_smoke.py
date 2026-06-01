#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Smoke checks for HBV-Studio workspace advice endpoint."""

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
    parser = argparse.ArgumentParser(description="Check /api/workspace/advice for a known workspace.")
    parser.add_argument("--url", default="http://127.0.0.1:8765")
    parser.add_argument("--workspace-config", default="workspaces/tuotuohe_test.json")
    args = parser.parse_args()

    base_url = args.url.rstrip("/")
    query = urllib.parse.urlencode({"config_path": args.workspace_config})
    payload = request_json(f"{base_url}/api/workspace/advice?{query}")
    if not payload.get("ok"):
        raise RuntimeError(payload.get("error") or "workspace advice endpoint returned ok=false")
    data = payload.get("data") or {}
    if not data.get("headline"):
        raise RuntimeError("workspace advice is missing headline")
    if data.get("profile") != "daily":
        raise RuntimeError(f"unexpected profile: {data.get('profile')!r}")
    if not isinstance(data.get("ready_for_calibration"), bool):
        raise RuntimeError("ready_for_calibration should be a boolean")
    recommendations = data.get("recommendations") or []
    if not recommendations:
        raise RuntimeError("workspace advice should include recommendations")
    if not any(item.get("kind") == "plan" for item in recommendations):
        raise RuntimeError(f"workspace advice missing plan recommendation: {recommendations!r}")
    calibration = data.get("calibration") or {}
    if calibration.get("method") != "mc_screen_de":
        raise RuntimeError(f"unexpected recommended method: {calibration.get('method')!r}")
    if not calibration.get("method_label") or not calibration.get("param_bounds_profile"):
        raise RuntimeError(f"calibration recommendation is incomplete: {calibration!r}")
    if int(calibration.get("workers") or 0) <= 0:
        raise RuntimeError(f"invalid worker recommendation: {calibration.get('workers')!r}")
    if not calibration.get("reasons"):
        raise RuntimeError("calibration recommendation should include reasons")

    summary = {
        "headline": data.get("headline"),
        "profile": data.get("profile"),
        "ready_for_calibration": data.get("ready_for_calibration"),
        "recommendation_count": len(recommendations),
        "calibration": {
            "method": calibration.get("method"),
            "workers": calibration.get("workers"),
            "expected_steps": calibration.get("expected_steps"),
            "manual_preset_count": calibration.get("manual_preset_count"),
        },
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
