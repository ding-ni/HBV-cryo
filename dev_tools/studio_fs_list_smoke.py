#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Smoke checks for HBV-Studio filesystem list endpoint."""

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
    parser = argparse.ArgumentParser(description="Check /api/fs/list for workspace config browsing.")
    parser.add_argument("--url", default="http://127.0.0.1:8765")
    args = parser.parse_args()

    base_url = args.url.rstrip("/")
    roots_payload = request_json(f"{base_url}/api/fs/list")
    if not roots_payload.get("ok"):
        raise RuntimeError(roots_payload.get("error") or "fs list roots returned ok=false")
    roots_data = roots_payload.get("data") or {}
    if roots_data.get("current_path") != "":
        raise RuntimeError(f"empty fs list should not select a current path: {roots_data!r}")
    if not roots_data.get("roots"):
        raise RuntimeError("empty fs list should include filesystem roots")

    query = urllib.parse.urlencode({"path": "workspaces", "extensions": ".json", "kind": "file"})
    payload = request_json(f"{base_url}/api/fs/list?{query}")
    if not payload.get("ok"):
        raise RuntimeError(payload.get("error") or "fs list workspaces returned ok=false")
    data = payload.get("data") or {}
    files = data.get("files") or []
    if data.get("kind") != "file":
        raise RuntimeError(f"unexpected fs list kind: {data.get('kind')!r}")
    if not data.get("current_path") or "workspaces" not in str(data.get("current_path", "")).replace("\\", "/"):
        raise RuntimeError(f"unexpected current_path for workspaces: {data.get('current_path')!r}")
    if not isinstance(data.get("directories"), list):
        raise RuntimeError("fs list directories should be a list")
    if int(data.get("file_count") or 0) < len(files):
        raise RuntimeError(f"fs list file_count is smaller than returned files: {data!r}")
    if not any(item.get("name") == "tuotuohe_test.json" and item.get("suffix") == ".json" for item in files):
        raise RuntimeError(f"fs list should include tuotuohe_test.json: {files!r}")

    summary = {
        "roots": roots_data.get("roots"),
        "current_path": data.get("current_path"),
        "file_count": data.get("file_count"),
        "shown_file_count": data.get("shown_file_count"),
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
