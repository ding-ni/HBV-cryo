#!/usr/bin/env python
# -*- coding: utf-8 -*-
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable


METEO_STATE_FILENAME = "_meteo_state.json"


@dataclass(frozen=True)
class MeteoStateContext:
    current_profile: Callable[[dict[str, Any]], str]
    build_profile_paths: Callable[[dict[str, Any], str], dict[str, Any]]
    read_json_file: Callable[[Path], dict[str, Any]]
    write_json_file: Callable[[Path, dict[str, Any]], None]


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


def meteo_state_path(
    config: dict[str, Any],
    context: MeteoStateContext,
    profile: str | None = None,
) -> Path:
    active_profile = profile or context.current_profile(config)
    paths = context.build_profile_paths(config, active_profile)
    return Path(paths["aligned_dir"]) / METEO_STATE_FILENAME


def read_meteo_state(
    config: dict[str, Any],
    context: MeteoStateContext,
    profile: str | None = None,
) -> dict[str, Any]:
    path = meteo_state_path(config, context, profile)
    if not path.exists():
        return {}
    try:
        data = context.read_json_file(path)
    except Exception:
        return {}
    if isinstance(data, dict):
        data["_state_path"] = str(path)
        return data
    return {}


def write_meteo_state(
    config: dict[str, Any],
    data: dict[str, Any],
    context: MeteoStateContext,
    profile: str | None = None,
) -> Path:
    path = meteo_state_path(config, context, profile)
    payload = dict(data)
    payload.pop("_state_path", None)
    context.write_json_file(path, payload)
    return path


def clear_meteo_state(
    config: dict[str, Any],
    context: MeteoStateContext,
    profile: str | None = None,
) -> None:
    path = meteo_state_path(config, context, profile)
    if path.exists():
        path.unlink()
