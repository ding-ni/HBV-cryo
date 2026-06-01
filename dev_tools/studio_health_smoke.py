#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Smoke checks for HBV-Studio health endpoint."""

from __future__ import annotations

import argparse
import json
import urllib.request
from typing import Any


def request_json(url: str, timeout: float = 30.0) -> dict[str, Any]:
    with urllib.request.urlopen(url, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8", errors="replace"))


def main() -> int:
    parser = argparse.ArgumentParser(description="Check /api/health response shape.")
    parser.add_argument("--url", default="http://127.0.0.1:8765")
    args = parser.parse_args()

    base_url = args.url.rstrip("/")
    data = request_json(f"{base_url}/api/health")
    if data.get("ok") is not True:
        raise RuntimeError(f"health endpoint returned ok={data.get('ok')!r}")
    for key in ("time", "server_started_at", "source_latest_mtime"):
        if not isinstance(data.get(key), (int, float)):
            raise RuntimeError(f"{key} should be numeric: {data!r}")
    for key in ("server_time", "server_started_at_text", "version", "source_latest_file"):
        if not data.get(key):
            raise RuntimeError(f"{key} should be present: {data!r}")
    if not isinstance(data.get("source_stale"), bool):
        raise RuntimeError(f"source_stale should be boolean: {data!r}")
    if data["time"] < data["server_started_at"]:
        raise RuntimeError(f"health time should not precede server start: {data!r}")

    summary = {
        "version": data.get("version"),
        "source_stale": data.get("source_stale"),
        "source_latest_file": data.get("source_latest_file"),
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
