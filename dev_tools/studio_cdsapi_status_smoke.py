#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Smoke checks for HBV-Studio CDS API status endpoint."""

from __future__ import annotations

import argparse
import json
import urllib.request
from typing import Any


def request_json(url: str, timeout: float = 30.0) -> dict[str, Any]:
    with urllib.request.urlopen(url, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8", errors="replace"))


def main() -> int:
    parser = argparse.ArgumentParser(description="Check /api/cdsapi/status response shape.")
    parser.add_argument("--url", default="http://127.0.0.1:8765")
    args = parser.parse_args()

    base_url = args.url.rstrip("/")
    payload = request_json(f"{base_url}/api/cdsapi/status")
    if not payload.get("ok"):
        raise RuntimeError(payload.get("error") or "cdsapi status endpoint returned ok=false")
    data = payload.get("data") or {}
    for key in ("exists", "readable", "looks_valid"):
        if not isinstance(data.get(key), bool):
            raise RuntimeError(f"{key} should be boolean: {data!r}")
    if not data.get("path") or not str(data.get("path")).endswith(".cdsapirc"):
        raise RuntimeError(f"unexpected cdsapi config path: {data.get('path')!r}")
    if not data.get("home_dir"):
        raise RuntimeError("home_dir should be present")

    summary = {
        "exists": data.get("exists"),
        "readable": data.get("readable"),
        "looks_valid": data.get("looks_valid"),
        "path": data.get("path"),
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
