#!/usr/bin/env python
# -*- coding: utf-8 -*-
from __future__ import annotations

import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class HealthContext:
    gui_root: Path
    app_version: str
    server_started_at: float


def source_files_latest_mtime(context: HealthContext) -> tuple[float, str]:
    candidates = [
        context.gui_root / "studio_service.py",
        context.gui_root / "launch.py",
        context.gui_root / "forecast_run.py",
        context.gui_root / "profile_runner.py",
        context.gui_root / "precipitation_strategy_runner.py",
        context.gui_root / "web" / "app.js",
        context.gui_root / "web" / "index.html",
        context.gui_root / "web" / "styles.css",
        context.gui_root / "web" / "js" / "forecastView.js",
        context.gui_root / "web" / "js" / "eventMode.js",
        context.gui_root / "web" / "js" / "geoPreview.js",
        context.gui_root / "web" / "js" / "parameterLibrary.js",
        context.gui_root / "web" / "js" / "stationPrecip.js",
        context.gui_root / "web" / "js" / "taskView.js",
        context.gui_root / "web" / "js" / "workspaceLayout.js",
    ]
    services_dir = context.gui_root / "services"
    if services_dir.exists():
        candidates.extend(sorted(services_dir.glob("*.py")))
    latest = 0.0
    latest_file = ""
    for path in candidates:
        try:
            stamp = path.stat().st_mtime
        except OSError:
            continue
        if stamp > latest:
            latest = stamp
            latest_file = str(path)
    return latest, latest_file


def health_payload(context: HealthContext) -> dict[str, Any]:
    latest_source_mtime, latest_source_file = source_files_latest_mtime(context)
    return {
        "ok": True,
        "time": time.time(),
        "server_time": time.strftime("%Y-%m-%d %H:%M:%S"),
        "server_started_at": context.server_started_at,
        "server_started_at_text": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(context.server_started_at)),
        "version": context.app_version,
        "source_latest_mtime": latest_source_mtime,
        "source_latest_file": latest_source_file,
        "source_stale": bool(latest_source_mtime and latest_source_mtime > context.server_started_at + 1.0),
    }
