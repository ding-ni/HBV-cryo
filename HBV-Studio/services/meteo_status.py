#!/usr/bin/env python
# -*- coding: utf-8 -*-
from __future__ import annotations

from pathlib import Path
from typing import Any


def cdsapi_status() -> dict[str, Any]:
    home_dir = Path.home().resolve(strict=False)
    config_path = (home_dir / ".cdsapirc").resolve(strict=False)
    exists = config_path.exists() and config_path.is_file()
    looks_valid = False
    readable = False
    if exists:
        try:
            text = config_path.read_text(encoding="utf-8", errors="ignore")
            lower = text.lower()
            readable = True
            looks_valid = ("url:" in lower) and ("key:" in lower)
        except Exception:
            readable = False
    return {
        "exists": bool(exists),
        "readable": bool(readable),
        "looks_valid": bool(looks_valid),
        "path": str(config_path),
        "home_dir": str(home_dir),
    }
