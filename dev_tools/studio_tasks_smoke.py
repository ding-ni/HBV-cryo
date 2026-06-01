#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Smoke checks for HBV-Studio task listing endpoint."""

from __future__ import annotations

import argparse
import json
import urllib.request
from typing import Any


def request_json(url: str, timeout: float = 30.0) -> dict[str, Any]:
    with urllib.request.urlopen(url, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8", errors="replace"))


def main() -> int:
    parser = argparse.ArgumentParser(description="Check /api/tasks response shape.")
    parser.add_argument("--url", default="http://127.0.0.1:8765")
    args = parser.parse_args()

    base_url = args.url.rstrip("/")
    payload = request_json(f"{base_url}/api/tasks")
    if not payload.get("ok"):
        raise RuntimeError(payload.get("error") or "tasks endpoint returned ok=false")
    tasks = payload.get("data")
    if not isinstance(tasks, list):
        raise RuntimeError(f"tasks data should be a list: {tasks!r}")
    for task in tasks:
        for key in ("id", "task_type", "label", "status", "created_at", "updated_at", "metadata"):
            if key not in task:
                raise RuntimeError(f"task item missing {key}: {task!r}")
        if not isinstance(task.get("metadata"), dict):
            raise RuntimeError(f"task metadata should be a dict: {task!r}")

    summary = {
        "task_count": len(tasks),
        "running_count": sum(1 for task in tasks if task.get("status") == "running"),
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
