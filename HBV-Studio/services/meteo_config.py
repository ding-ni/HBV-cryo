from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable


METEO_KEY = "\u6c14\u8c61\u7b56\u7565"
METEO_PRECIP_MODE_KEY = "\u964d\u6c34\u65b9\u6848"
METEO_PRECIP_SOURCE_KEY = "\u964d\u6c34\u6765\u6e90"
METEO_PRECIP_SOURCE_LEGACY_KEY = "\u964d\u6c34\u6e90"
METEO_STATION_PREC_KEY = "\u7ad9\u70b9\u964d\u6c34_csv"
METEO_STATION_META_KEY = "\u7ad9\u70b9\u4fe1\u606f_csv"
METEO_HOURLY_PREC_DIR_KEY = "\u539f\u59cb\u5c0f\u65f6\u964d\u6c34\u76ee\u5f55"
METEO_TEMP_SOURCE_KEY = "\u6e29\u5ea6\u6765\u6e90"
METEO_CUSTOM_TEMP_DIR_KEY = "\u81ea\u5e26\u6e29\u5ea6tif\u76ee\u5f55"
METEO_CUSTOM_PREC_DIR_KEY = "\u81ea\u5e26\u964d\u6c34tif\u76ee\u5f55"
METEO_PET_SOURCE_KEY = "\u6f5c\u5728\u84b8\u6563\u53d1\u6765\u6e90"
METEO_CUSTOM_PET_DIR_KEY = "\u81ea\u5e26\u84b8\u6563\u53d1tif\u76ee\u5f55"

VALID_PRECIP_SOURCES = {"era5", "mswep", "cmfd", "custom_tif"}
DIRECT_RUNTIME_PRECIP_SOURCES = {"era5", "cmfd", "mswep"}

PRECIP_SOURCE_LABELS = {
    "era5": "ERA5 \u81ea\u52a8\u4e0b\u8f7d\u964d\u6c34",
    "mswep": "MSWEP \u672c\u5730\u539f\u59cb\u6587\u4ef6",
    "cmfd": "CMFD \u672c\u5730\u539f\u59cb\u6587\u4ef6",
    "custom_tif": "\u672c\u5730\u964d\u6c34\u6805\u683c\u76ee\u5f55",
}


@dataclass(frozen=True)
class EffectivePrecipPathContext:
    current_profile: Callable[[dict[str, Any]], str]
    build_profile_paths: Callable[[dict[str, Any], str], dict[str, Any]]


def configured_precip_source(config: dict[str, Any]) -> str:
    meteo = dict(config.get(METEO_KEY, {}))
    source = str(meteo.get(METEO_PRECIP_SOURCE_KEY, "")).strip().lower()
    legacy_source = str(meteo.get(METEO_PRECIP_SOURCE_LEGACY_KEY, "")).strip().lower()
    top_level_source = str(config.get("\u9ed8\u8ba4\u964d\u6c34\u6e90", "")).strip().lower()
    if source:
        return source
    if top_level_source in {"era5", "cmfd", "custom_tif"} and legacy_source in {"", "mswep"}:
        return top_level_source
    return legacy_source or top_level_source or "era5"


def resolve_precip_source(config: dict[str, Any], source: Any = None) -> str:
    raw = str(source or "").strip().lower()
    if raw in VALID_PRECIP_SOURCES:
        return raw
    configured = configured_precip_source(config)
    if configured in VALID_PRECIP_SOURCES:
        return configured
    return "era5"


def effective_precip_source(source: str) -> str:
    key = str(source).strip().lower()
    if key in DIRECT_RUNTIME_PRECIP_SOURCES:
        return key
    return "era5"


def display_precip_source_label(source: str) -> str:
    key = str(source or "").strip().lower()
    return PRECIP_SOURCE_LABELS.get(key, str(source or "").strip() or "MSWEP \u683c\u70b9\u964d\u6c34")


def display_runtime_precip_label(config: dict[str, Any]) -> str:
    configured = configured_precip_source(config)
    if configured == "custom_tif":
        return "\u5de5\u7a0b\u72ec\u7acb\u964d\u6c34\u76ee\u5f55\uff08\u672c\u5730\u5bfc\u5165\uff09"
    return display_precip_source_label(effective_precip_source(configured))


def effective_precip_paths(
    config: dict[str, Any],
    context: EffectivePrecipPathContext,
    profile: str | None = None,
    precip_source: Any = None,
) -> tuple[Path, Path, str]:
    active_profile = profile or context.current_profile(config)
    paths = context.build_profile_paths(config, active_profile)
    selected_source = resolve_precip_source(config, precip_source)
    if selected_source == "era5":
        return Path(paths["aligned_prec_era5_base_dir"]), Path(paths["aligned_prec_era5_dir"]), selected_source
    if selected_source == "custom_tif":
        return Path(paths["aligned_prec_custom_base_dir"]), Path(paths["aligned_prec_custom_dir"]), selected_source
    if selected_source == "cmfd":
        return Path(paths["aligned_prec_cmfd_base_dir"]), Path(paths["aligned_prec_cmfd_dir"]), selected_source
    return Path(paths["aligned_prec_base_dir"]), Path(paths["aligned_prec_dir"]), selected_source
