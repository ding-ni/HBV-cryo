#!/usr/bin/env python
# -*- coding: utf-8 -*-
from __future__ import annotations

import csv
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable


@dataclass(frozen=True)
class GeoOverviewContext:
    load_workspace_config: Callable[[str], tuple[Path, dict[str, Any]]]
    read_json_file: Callable[[Path], dict[str, Any]]
    current_profile: Callable[[dict[str, Any]], str]
    build_profile_paths: Callable[[dict[str, Any], str], dict[str, Any]]
    resolve_config_related_path: Callable[[dict[str, Any], Any], Path | None]
    workspace_dem_path: Callable[[Path | str, str | None], Path]
    configured_dem_kind: Callable[[dict[str, Any]], str]
    to_display_path: Callable[[Path], str]
    profile_labels: dict[str, str]


def _geo_empty_layer(
    layer_id: str,
    label: str,
    kind: str,
    path: Path | None,
    status: str,
    message: str,
    context: GeoOverviewContext,
) -> dict[str, Any]:
    resolved = path.resolve(strict=False) if path is not None else None
    return {
        "id": layer_id,
        "label": label,
        "kind": kind,
        "status": status,
        "message": message,
        "path": str(resolved) if resolved is not None else "",
        "display_path": context.to_display_path(resolved) if resolved is not None else "",
        "bounds": None,
        "rings": [],
        "points": [],
        "metrics": {},
    }


def _geo_bounds_dict(values: Any) -> dict[str, float] | None:
    try:
        west, south, east, north = [float(item) for item in values]
    except Exception:
        return None
    if not all(math.isfinite(item) for item in (west, south, east, north)):
        return None
    if east <= west or north <= south:
        return None
    return {"west": west, "south": south, "east": east, "north": north}


def _merge_geo_bounds(bounds_items: list[dict[str, float] | None]) -> dict[str, float] | None:
    valid = [item for item in bounds_items if item]
    if not valid:
        return None
    return {
        "west": min(item["west"] for item in valid),
        "south": min(item["south"] for item in valid),
        "east": max(item["east"] for item in valid),
        "north": max(item["north"] for item in valid),
    }


def _geo_rect_ring(bounds: dict[str, float] | None) -> list[dict[str, Any]]:
    if not bounds:
        return []
    return [
        {
            "points": [
                [round(bounds["west"], 6), round(bounds["south"], 6)],
                [round(bounds["east"], 6), round(bounds["south"], 6)],
                [round(bounds["east"], 6), round(bounds["north"], 6)],
                [round(bounds["west"], 6), round(bounds["north"], 6)],
                [round(bounds["west"], 6), round(bounds["south"], 6)],
            ]
        }
    ]


def _detect_table_column(columns: list[str], candidates: list[str]) -> str | None:
    lookup = {str(column).strip().lower(): str(column) for column in columns}
    for candidate in candidates:
        found = lookup.get(str(candidate).strip().lower())
        if found:
            return found
    return None


def _points_bounds(points: list[dict[str, Any]]) -> dict[str, float] | None:
    valid: list[tuple[float, float]] = []
    for item in points:
        coord = item.get("coord")
        if not isinstance(coord, list) or len(coord) < 2:
            continue
        lon = float(coord[0])
        lat = float(coord[1])
        if math.isfinite(lon) and math.isfinite(lat):
            valid.append((lon, lat))
    if not valid:
        return None
    west = min(item[0] for item in valid)
    east = max(item[0] for item in valid)
    south = min(item[1] for item in valid)
    north = max(item[1] for item in valid)
    if east <= west:
        west -= 0.02
        east += 0.02
    if north <= south:
        south -= 0.02
        north += 0.02
    return {"west": west, "south": south, "east": east, "north": north}


def _thin_geo_points(coords: Any, max_points: int = 220) -> list[list[float]]:
    points = [[round(float(x), 6), round(float(y), 6)] for x, y, *_ in coords]
    if len(points) <= max_points:
        return points
    step = max(1, math.ceil(len(points) / max_points))
    thinned = points[::step]
    if points[-1] != thinned[-1]:
        thinned.append(points[-1])
    return thinned


def _geometry_to_geo_rings(geometry: Any, bounds: dict[str, float] | None, max_rings: int = 12) -> list[dict[str, Any]]:
    if geometry is None or getattr(geometry, "is_empty", True):
        return []
    tolerance = 0.0
    if bounds:
        tolerance = max(bounds["east"] - bounds["west"], bounds["north"] - bounds["south"]) / 700.0
    try:
        if tolerance > 0:
            geometry = geometry.simplify(tolerance, preserve_topology=True)
    except Exception:
        pass

    rings: list[dict[str, Any]] = []

    def add_polygon(poly: Any) -> None:
        if len(rings) >= max_rings:
            return
        try:
            points = _thin_geo_points(list(poly.exterior.coords))
        except Exception:
            return
        if len(points) >= 3:
            rings.append({"points": points})

    geom_type = getattr(geometry, "geom_type", "")
    if geom_type == "Polygon":
        add_polygon(geometry)
    elif geom_type == "MultiPolygon":
        polygons = sorted(list(geometry.geoms), key=lambda item: getattr(item, "area", 0.0), reverse=True)
        for poly in polygons[:max_rings]:
            add_polygon(poly)
    elif hasattr(geometry, "geoms"):
        for item in list(geometry.geoms)[:max_rings]:
            if getattr(item, "geom_type", "") in {"Polygon", "MultiPolygon"}:
                rings.extend(_geometry_to_geo_rings(item, bounds, max_rings=max_rings - len(rings)))
            if len(rings) >= max_rings:
                break
    return rings


def _vector_geo_layer(layer_id: str, label: str, path: Path | None, context: GeoOverviewContext) -> dict[str, Any]:
    if path is None:
        return _geo_empty_layer(layer_id, label, "vector", None, "missing", "未配置", context)
    if not path.exists():
        return _geo_empty_layer(layer_id, label, "vector", path, "missing", "文件不存在", context)
    try:
        import geopandas as gpd

        gdf = gpd.read_file(path)
        if gdf.empty:
            return _geo_empty_layer(layer_id, label, "vector", path, "missing", "文件为空", context)
        if gdf.crs:
            gdf = gdf.to_crs("EPSG:4326")
        bounds = _geo_bounds_dict(gdf.total_bounds)
        rings: list[dict[str, Any]] = []
        try:
            if path.stat().st_size <= 8 * 1024 * 1024:
                rings = _geometry_to_geo_rings(gdf.geometry.unary_union, bounds)
        except Exception:
            rings = []
        if not rings:
            rings = _geo_rect_ring(bounds)
        resolved = path.resolve(strict=False)
        return {
            "id": layer_id,
            "label": label,
            "kind": "vector",
            "status": "ok",
            "message": f"{len(gdf)} 个要素",
            "path": str(resolved),
            "display_path": context.to_display_path(resolved),
            "bounds": bounds,
            "rings": rings,
            "points": [],
            "metrics": {"feature_count": int(len(gdf))},
        }
    except Exception as exc:
        return _geo_empty_layer(layer_id, label, "vector", path, "error", f"读取失败：{exc}", context)


def _raster_geo_layer(layer_id: str, label: str, path: Path | None, context: GeoOverviewContext) -> dict[str, Any]:
    if path is None:
        return _geo_empty_layer(layer_id, label, "raster", None, "missing", "未配置", context)
    if not path.exists():
        return _geo_empty_layer(layer_id, label, "raster", path, "missing", "文件不存在", context)
    try:
        import numpy as np
        import rasterio
        from rasterio.warp import transform_bounds

        with rasterio.open(path) as src:
            raw_bounds = src.bounds
            if src.crs:
                bounds_values = transform_bounds(src.crs, "EPSG:4326", *raw_bounds, densify_pts=21)
                crs_text = str(src.crs)
            else:
                bounds_values = raw_bounds
                crs_text = ""
            bounds = _geo_bounds_dict(bounds_values)
            sample_h = min(64, max(1, src.height))
            sample_w = min(64, max(1, src.width))
            arr = src.read(1, out_shape=(sample_h, sample_w), masked=True)
            values = np.asarray(arr.compressed() if hasattr(arr, "compressed") else arr.ravel(), dtype="float64")
            values = values[np.isfinite(values)]
            stats = {}
            if values.size:
                stats = {
                    "min": round(float(values.min()), 2),
                    "max": round(float(values.max()), 2),
                    "mean": round(float(values.mean()), 2),
                }
            res_x, res_y = src.res
            resolved = path.resolve(strict=False)
            return {
                "id": layer_id,
                "label": label,
                "kind": "raster",
                "status": "ok",
                "message": f"{src.width} x {src.height}",
                "path": str(resolved),
                "display_path": context.to_display_path(resolved),
                "bounds": bounds,
                "rings": _geo_rect_ring(bounds),
                "points": [],
                "metrics": {
                    "width": int(src.width),
                    "height": int(src.height),
                    "crs": crs_text,
                    "resolution": [round(float(res_x), 6), round(float(res_y), 6)],
                    "stats": stats,
                },
            }
    except Exception as exc:
        return _geo_empty_layer(layer_id, label, "raster", path, "error", f"读取失败：{exc}", context)


def _station_geo_layer(path: Path | None, context: GeoOverviewContext) -> dict[str, Any]:
    if path is None:
        return _geo_empty_layer("stations", "站点", "point", None, "missing", "未配置", context)
    if not path.exists():
        return _geo_empty_layer("stations", "站点", "point", path, "missing", "文件不存在", context)
    try:
        with path.open("r", encoding="utf-8-sig", newline="") as fh:
            reader = csv.DictReader(fh)
            columns = [str(column) for column in (reader.fieldnames or [])]
            id_col = _detect_table_column(columns, ["station_id", "station", "id", "name", "站点", "站号"])
            lon_col = _detect_table_column(columns, ["lon", "longitude", "x", "经度"])
            lat_col = _detect_table_column(columns, ["lat", "latitude", "y", "纬度"])
            if not id_col or not lon_col or not lat_col:
                return _geo_empty_layer("stations", "站点", "point", path, "error", "未识别到站号或经纬度字段", context)
            points: list[dict[str, Any]] = []
            for idx, row in enumerate(reader):
                try:
                    lon = float(row.get(lon_col, ""))
                    lat = float(row.get(lat_col, ""))
                except Exception:
                    continue
                if not (math.isfinite(lon) and math.isfinite(lat)):
                    continue
                station_id = str(row.get(id_col, "") or "").strip() or f"station_{idx + 1}"
                points.append({
                    "id": station_id,
                    "label": station_id,
                    "coord": [round(lon, 6), round(lat, 6)],
                })
        if not points:
            return _geo_empty_layer("stations", "站点", "point", path, "missing", "无有效经纬度", context)
        resolved = path.resolve(strict=False)
        return {
            "id": "stations",
            "label": "站点",
            "kind": "point",
            "status": "ok",
            "message": f"{len(points)} 个站点",
            "path": str(resolved),
            "display_path": context.to_display_path(resolved),
            "bounds": _points_bounds(points),
            "rings": [],
            "points": points[:500],
            "metrics": {"station_count": len(points)},
        }
    except Exception as exc:
        return _geo_empty_layer("stations", "站点", "point", path, "error", f"读取失败：{exc}", context)


def _point_layer_geojson(layer: dict[str, Any]) -> dict[str, Any]:
    features = []
    for point in layer.get("points", []) or []:
        coord = point.get("coord")
        if not isinstance(coord, list) or len(coord) < 2:
            continue
        lon = float(coord[0])
        lat = float(coord[1])
        if not (math.isfinite(lon) and math.isfinite(lat)):
            continue
        features.append({
            "type": "Feature",
            "geometry": {"type": "Point", "coordinates": [lon, lat]},
            "properties": {
                "id": str(point.get("id", "") or ""),
                "label": str(point.get("label", "") or point.get("id", "") or "站点"),
                "layer": str(layer.get("id", "") or ""),
                "layer_label": str(layer.get("label", "") or ""),
            },
        })
    return {
        "type": "FeatureCollection",
        "features": features,
        "properties": {
            "id": str(layer.get("id", "") or ""),
            "label": str(layer.get("label", "") or ""),
            "status": str(layer.get("status", "") or ""),
            "message": str(layer.get("message", "") or ""),
            "bounds": layer.get("bounds"),
            "metrics": layer.get("metrics", {}),
        },
    }


def _polygon_layer_geojson(layer: dict[str, Any]) -> dict[str, Any]:
    features = []
    for idx, ring in enumerate(layer.get("rings", []) or []):
        points = ring.get("points") if isinstance(ring, dict) else None
        if not isinstance(points, list) or len(points) < 3:
            continue
        coords: list[list[float]] = []
        for point in points:
            if not isinstance(point, list) or len(point) < 2:
                continue
            lon = float(point[0])
            lat = float(point[1])
            if math.isfinite(lon) and math.isfinite(lat):
                coords.append([lon, lat])
        if len(coords) < 3:
            continue
        if coords[0] != coords[-1]:
            coords.append(coords[0])
        features.append({
            "type": "Feature",
            "geometry": {"type": "Polygon", "coordinates": [coords]},
            "properties": {
                "id": str(layer.get("id", "") or ""),
                "label": str(layer.get("label", "") or ""),
                "layer": str(layer.get("id", "") or ""),
                "feature_index": idx,
            },
        })
    return {
        "type": "FeatureCollection",
        "features": features,
        "properties": {
            "id": str(layer.get("id", "") or ""),
            "label": str(layer.get("label", "") or ""),
            "status": str(layer.get("status", "") or ""),
            "message": str(layer.get("message", "") or ""),
            "bounds": layer.get("bounds"),
            "metrics": layer.get("metrics", {}),
        },
    }


def _empty_geojson_layer(layer_id: str, label: str, status: str = "missing", message: str = "未配置") -> dict[str, Any]:
    return {
        "type": "FeatureCollection",
        "features": [],
        "properties": {
            "id": layer_id,
            "label": label,
            "status": status,
            "message": message,
            "bounds": None,
            "metrics": {},
        },
    }


def workspace_geo_overview(config_path_raw: str, context: GeoOverviewContext) -> dict[str, Any]:
    cfg_path, config = context.load_workspace_config(config_path_raw)
    try:
        raw_config = context.read_json_file(cfg_path)
    except Exception:
        raw_config = {}
    profile = context.current_profile(config)
    paths = context.build_profile_paths(config, profile)
    gis_dir = Path(paths["gis_dir"]).resolve(strict=False)
    basin_path = context.resolve_config_related_path(config, config.get("流域边界_shp"))
    configured_dem_path = context.resolve_config_related_path(config, config.get("DEM_tif"))
    workspace_dem = context.workspace_dem_path(gis_dir, context.configured_dem_kind(config))
    dem_path = workspace_dem if workspace_dem.exists() else configured_dem_path

    zone_candidates = [
        gis_dir / "elevation_zone_low.tif",
        gis_dir / "elevation_zone_mid.tif",
        gis_dir / "elevation_zone_high.tif",
    ]
    zone_path = next((item for item in zone_candidates if item.exists()), None)
    glacier_raster = next(
        (item for item in [gis_dir / "glacier_fraction.tif", gis_dir / "glacier_mask.tif"] if item.exists()),
        None,
    )
    raw_glacier = str(raw_config.get("冰川边界_shp", "") or "").strip()
    glacier_vector = (
        context.resolve_config_related_path(config, config.get("冰川边界_shp"))
        if raw_glacier
        else None
    )
    glacier_path = glacier_raster or glacier_vector
    meteo = dict(config.get("气象策略", {}) or {})
    raw_station_meta = str(meteo.get("站点信息_csv", "") or "").strip()
    station_meta_path = context.resolve_config_related_path(config, raw_station_meta) if raw_station_meta else None

    layers = [
        _vector_geo_layer("basin", "流域边界", basin_path, context),
        _raster_geo_layer("dem", "DEM", dem_path, context),
        _raster_geo_layer("elevation_zone", "高程分区", zone_path, context),
        (
            _raster_geo_layer("glacier", "冰川", glacier_path, context)
            if glacier_path and glacier_path.suffix.lower() in {".tif", ".tiff"}
            else _vector_geo_layer("glacier", "冰川", glacier_path, context)
        ),
        _station_geo_layer(station_meta_path, context),
    ]
    ok_layers = [layer for layer in layers if layer.get("status") == "ok"]
    bounds = _merge_geo_bounds([layer.get("bounds") for layer in ok_layers])
    vector_focus = next((layer.get("bounds") for layer in ok_layers if layer.get("id") == "basin"), None)
    focus_bounds = (
        vector_focus
        or _merge_geo_bounds([layer.get("bounds") for layer in ok_layers if layer.get("kind") == "vector"])
        or bounds
    )
    return {
        "status": "ok" if ok_layers else "missing",
        "config_path": str(cfg_path.resolve(strict=False)),
        "flow_name": str(config.get("流域名称", cfg_path.stem) or cfg_path.stem),
        "profile": profile,
        "profile_label": context.profile_labels.get(profile, profile),
        "bounds": bounds,
        "focus_bounds": focus_bounds,
        "available_layer_count": len(ok_layers),
        "layers": layers,
        "notes": [
            "空间预览只读取本地文件，不访问在线底图。",
            "DEM 与栅格图层在此处以范围和统计摘要表达，完整栅格仍由本地工作区保存。",
        ],
    }


def workspace_station_geojson(config_path_raw: str, context: GeoOverviewContext) -> dict[str, Any]:
    overview = workspace_geo_overview(config_path_raw, context)
    station_layer = next((layer for layer in overview.get("layers", []) if layer.get("id") == "stations"), None)
    if not station_layer:
        return _empty_geojson_layer("stations", "站点")
    return _point_layer_geojson(station_layer)


def workspace_basin_geojson(config_path_raw: str, context: GeoOverviewContext) -> dict[str, Any]:
    overview = workspace_geo_overview(config_path_raw, context)
    basin_layer = next((layer for layer in overview.get("layers", []) if layer.get("id") == "basin"), None)
    if not basin_layer:
        return _empty_geojson_layer("basin", "流域边界")
    return _polygon_layer_geojson(basin_layer)
