#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Smoke checks for HBV-Studio data-prep GET endpoints."""

from __future__ import annotations

import argparse
import json
import urllib.parse
import urllib.request
from typing import Any


def request_json(url: str, timeout: float = 45.0) -> dict[str, Any]:
    with urllib.request.urlopen(url, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8", errors="replace"))


def main() -> int:
    parser = argparse.ArgumentParser(description="Check /api/data-prep/steps and /api/data-prep/status.")
    parser.add_argument("--url", default="http://127.0.0.1:8765")
    parser.add_argument("--workspace-config", default="workspaces/tuotuohe_test.json")
    args = parser.parse_args()

    base_url = args.url.rstrip("/")
    query = urllib.parse.urlencode({"config_path": args.workspace_config})

    steps_payload = request_json(f"{base_url}/api/data-prep/steps?{query}")
    if not steps_payload.get("ok"):
        raise RuntimeError(steps_payload.get("error") or "data-prep steps endpoint returned ok=false")
    steps = steps_payload.get("data") or []
    if len(steps) < 8:
        raise RuntimeError(f"expected at least 8 data-prep steps, got {len(steps)}")
    step_ids = [str(item.get("id", "")) for item in steps]
    for expected in ("clip_dem", "flow_acc", "masked_flow", "elevation_zone"):
        if expected not in step_ids:
            raise RuntimeError(f"data-prep steps missing {expected}: {step_ids!r}")
    for item in steps:
        for key in ("id", "title", "description", "depends_on", "optional", "manual", "needs_prec_source", "supports_overwrite"):
            if key not in item:
                raise RuntimeError(f"data-prep step missing {key}: {item!r}")

    status_payload = request_json(f"{base_url}/api/data-prep/status?{query}")
    if not status_payload.get("ok"):
        raise RuntimeError(status_payload.get("error") or "data-prep status endpoint returned ok=false")
    status = status_payload.get("data") or []
    if len(status) != len(steps):
        raise RuntimeError(f"data-prep status count mismatch: steps={len(steps)}, status={len(status)}")
    status_ids = [str(item.get("id", "")) for item in status]
    if status_ids != step_ids:
        raise RuntimeError(f"data-prep status ids differ from steps: {status_ids!r} vs {step_ids!r}")
    for item in status:
        for key in ("done", "message", "file_count", "blocked_by", "deps_met", "running", "script"):
            if key not in item:
                raise RuntimeError(f"data-prep status item missing {key}: {item!r}")
        if not isinstance(item.get("done"), bool) or not isinstance(item.get("running"), bool):
            raise RuntimeError(f"done/running should be boolean: {item!r}")

    summary = {
        "step_count": len(steps),
        "done_count": sum(1 for item in status if item.get("done")),
        "blocked_count": sum(1 for item in status if item.get("blocked_by")),
        "first_step": status[0].get("id") if status else None,
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
