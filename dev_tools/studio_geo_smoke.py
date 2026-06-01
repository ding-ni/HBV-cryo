#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Smoke check for the HBV-Studio geo overview endpoint."""

from __future__ import annotations

import argparse
import json
import urllib.parse
import urllib.request
from typing import Any


def request_json(url: str, timeout: float = 20.0) -> dict[str, Any]:
    with urllib.request.urlopen(url, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8", errors="replace"))


def main() -> int:
    parser = argparse.ArgumentParser(description="Check /api/geo/overview for a known workspace.")
    parser.add_argument("--url", default="http://127.0.0.1:8765")
    parser.add_argument("--workspace-config", default="workspaces/tuotuohe_test.json")
    parser.add_argument("--min-layers", type=int, default=3)
    args = parser.parse_args()

    base_url = args.url.rstrip("/")
    query = urllib.parse.urlencode({"config_path": args.workspace_config})
    payload = request_json(f"{base_url}/api/geo/overview?{query}")
    if not payload.get("ok"):
        raise RuntimeError(payload.get("error") or "geo overview endpoint returned ok=false")
    data = payload.get("data") or {}
    layers = data.get("layers") or []
    ok_layers = [item for item in layers if item.get("status") == "ok"]
    if len(ok_layers) < args.min_layers:
        raise RuntimeError(f"expected at least {args.min_layers} geo layers, got {len(ok_layers)}: {layers}")
    if not data.get("focus_bounds"):
        raise RuntimeError("geo overview did not return focus_bounds")
    summary = {
        "workspace": data.get("flow_name"),
        "available_layer_count": len(ok_layers),
        "ok_layers": [item.get("id") for item in ok_layers],
        "focus_bounds": data.get("focus_bounds"),
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
