#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Smoke checks for HBV-Studio geo suggestion endpoints."""

from __future__ import annotations

import argparse
import json
import math
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any


def request_json(url: str, timeout: float = 30.0) -> dict[str, Any]:
    with urllib.request.urlopen(url, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8", errors="replace"))


def finite_number(value: Any) -> float:
    out = float(value)
    if not math.isfinite(out):
        raise ValueError(f"not finite: {value!r}")
    return out


def main() -> int:
    parser = argparse.ArgumentParser(description="Check /api/suggest geo endpoints for a known workspace.")
    parser.add_argument("--url", default="http://127.0.0.1:8765")
    parser.add_argument("--workspace-config", default="HBV-Studio/workspaces/tuotuohe_test.json")
    args = parser.parse_args()

    base_url = args.url.rstrip("/")
    config = json.loads(Path(args.workspace_config).read_text(encoding="utf-8-sig"))
    shp_path = str(config.get("流域边界_shp") or "").strip()
    dem_path = str(config.get("DEM_tif") or "").strip()
    if not shp_path or not dem_path:
        raise RuntimeError("workspace config is missing 流域边界_shp or DEM_tif")

    bbox_payload = request_json(f"{base_url}/api/suggest/bbox?{urllib.parse.urlencode({'shp_path': shp_path})}")
    if not bbox_payload.get("ok"):
        raise RuntimeError(bbox_payload.get("error") or "bbox endpoint returned ok=false")
    bbox = bbox_payload.get("data") or {}
    north = finite_number(bbox.get("北"))
    south = finite_number(bbox.get("南"))
    east = finite_number(bbox.get("东"))
    west = finite_number(bbox.get("西"))
    if not (north > south and east > west):
        raise RuntimeError(f"invalid bbox ordering: {bbox}")
    if not (30.0 <= south <= north <= 40.0 and 85.0 <= west <= east <= 100.0):
        raise RuntimeError(f"bbox outside expected Tuotuohe range: {bbox}")

    cfmax_payload = request_json(
        f"{base_url}/api/suggest/cfmax-threshold?"
        f"{urllib.parse.urlencode({'shp_path': shp_path, 'dem_path': dem_path})}",
        timeout=60.0,
    )
    if not cfmax_payload.get("ok"):
        raise RuntimeError(cfmax_payload.get("error") or "cfmax endpoint returned ok=false")
    cfmax = cfmax_payload.get("data") or {}
    threshold = finite_number(cfmax.get("suggested_threshold_m"))
    min_m = finite_number(cfmax.get("min_m"))
    median_m = finite_number(cfmax.get("median_m"))
    max_m = finite_number(cfmax.get("max_m"))
    if not (min_m <= threshold <= max_m and abs(threshold - median_m) <= 0.01):
        raise RuntimeError(f"invalid CFMAX threshold stats: {cfmax}")
    if not (3500.0 <= threshold <= 6000.0):
        raise RuntimeError(f"CFMAX threshold outside expected Tuotuohe elevation range: {threshold}")

    print(json.dumps({"bbox": bbox, "cfmax": cfmax}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
