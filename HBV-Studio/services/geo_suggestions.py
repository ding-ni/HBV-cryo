#!/usr/bin/env python
# -*- coding: utf-8 -*-
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable


@dataclass(frozen=True)
class GeoSuggestionContext:
    resolve_path: Callable[[str], Path]


def fill_bbox_from_shp(shp_path: str, context: GeoSuggestionContext) -> dict[str, float] | None:
    if not shp_path:
        return None
    try:
        import geopandas as gpd
    except Exception:
        return None
    path = context.resolve_path(shp_path)
    gdf = gpd.read_file(path)
    minx, miny, maxx, maxy = gdf.total_bounds
    return {"北": float(maxy), "西": float(minx), "南": float(miny), "东": float(maxx)}


def suggest_cfmax_threshold(shp_path: str, dem_path: str, context: GeoSuggestionContext) -> dict[str, Any]:
    import geopandas as gpd
    import numpy as np
    import rasterio
    from rasterio.mask import mask

    shp = context.resolve_path(shp_path)
    dem = context.resolve_path(dem_path)
    basin = gpd.read_file(shp)
    with rasterio.open(dem) as src:
        basin_reproj = basin.to_crs(src.crs)
        masked, _ = mask(src, basin_reproj.geometry, crop=True, filled=False)
        arr = masked[0].astype("float64")
        if src.nodata is not None:
            arr[arr == src.nodata] = float("nan")
    valid = np.asarray(arr[np.isfinite(arr) & (arr > 0)], dtype="float64")
    if valid.size == 0:
        raise ValueError("DEM 与流域边界叠置后没有有效高程。")
    threshold = float(np.nanmedian(valid))
    return {
        "suggested_threshold_m": round(threshold, 2),
        "min_m": round(float(np.nanmin(valid)), 2),
        "median_m": round(float(np.nanmedian(valid)), 2),
        "max_m": round(float(np.nanmax(valid)), 2),
        "rule": "按流域有效 DEM 的中位高程生成建议阈值，可再手工微调。",
    }
