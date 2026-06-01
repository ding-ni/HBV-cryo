#!/usr/bin/env python
# -*- coding: utf-8 -*-
from __future__ import annotations

import csv
import math
import struct
import zlib
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable


_ELEVATION_ZONE_SPECS: tuple[tuple[str, str, str], ...] = (
    ("low", "低高程带", "elevation_zone_low.tif"),
    ("mid", "中高程带", "elevation_zone_mid.tif"),
    ("high", "高高程带", "elevation_zone_high.tif"),
)

_ELEVATION_ZONE_PROPERTY_KEYS = (
    "zone",
    "elev",
    "elev_min_m",
    "elev_max_m",
    "elev_label",
    "cfmax_threshold_m",
    "class_order",
)

_STATION_TYPE_LABELS = {
    "rain": "雨量站",
    "hydrology": "水文站",
    "outlet": "出口站",
    "station": "站点",
}


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


def _load_workspace_geo_sources(
    config_path_raw: str,
    context: GeoOverviewContext,
) -> tuple[Path, dict[str, Any], dict[str, Any], str, dict[str, Any], Path]:
    cfg_path, config = context.load_workspace_config(config_path_raw)
    try:
        raw_config = context.read_json_file(cfg_path)
    except Exception:
        raw_config = {}
    profile = context.current_profile(config)
    paths = context.build_profile_paths(config, profile)
    gis_dir = Path(paths["gis_dir"]).resolve(strict=False)
    return cfg_path, config, raw_config, profile, paths, gis_dir


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


def _finite_float(value: Any) -> float | None:
    try:
        result = float(value)
    except Exception:
        return None
    return result if math.isfinite(result) else None


def _fmt_elevation(value: float) -> str:
    return str(int(round(value))) if math.isfinite(value) else ""


def _elevation_zone_metadata(zone: str, threshold_m: float | None) -> dict[str, Any]:
    base: dict[str, Any] = {
        "zone": zone,
        "class_order": {"low": 1, "mid": 2, "high": 3}.get(zone, 0),
    }
    if threshold_m is None:
        return base
    base["elev"] = threshold_m
    base["cfmax_threshold_m"] = threshold_m
    if zone == "high":
        base["elev_min_m"] = threshold_m
        base["elev_label"] = f"> {_fmt_elevation(threshold_m)} m"
    elif zone in {"low", "mid"}:
        base["elev_max_m"] = threshold_m
        base["elev_label"] = f"<= {_fmt_elevation(threshold_m)} m"
    return base


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


def _png_chunk(kind: bytes, data: bytes) -> bytes:
    return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF)


def _encode_rgba_png(image: Any) -> bytes:
    height, width, channels = image.shape
    if channels != 4:
        raise ValueError("PNG image must be RGBA")
    rows = b"".join(b"\x00" + image[row].tobytes() for row in range(height))
    header = struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0)
    return (
        b"\x89PNG\r\n\x1a\n"
        + _png_chunk(b"IHDR", header)
        + _png_chunk(b"IDAT", zlib.compress(rows, level=6))
        + _png_chunk(b"IEND", b"")
    )


def _normalise_unit(values: Any, valid: Any) -> Any:
    import numpy as np

    if not np.any(valid):
        return np.zeros_like(values, dtype="float64")
    finite = values[valid]
    lo = float(np.nanpercentile(finite, 2))
    hi = float(np.nanpercentile(finite, 98))
    if not math.isfinite(lo) or not math.isfinite(hi) or hi <= lo:
        lo = float(np.nanmin(finite))
        hi = float(np.nanmax(finite))
    if not math.isfinite(lo) or not math.isfinite(hi) or hi <= lo:
        return np.zeros_like(values, dtype="float64")
    return np.clip((values - lo) / (hi - lo), 0.0, 1.0)


def _dem_array_to_png(values: Any, style: str = "hillshade") -> bytes:
    import numpy as np

    arr = np.asarray(values, dtype="float64")
    valid = np.isfinite(arr)
    if not np.any(valid):
        rgba = np.zeros((max(1, arr.shape[0]), max(1, arr.shape[1]), 4), dtype=np.uint8)
        return _encode_rgba_png(rgba)

    fill_value = float(np.nanmedian(arr[valid]))
    filled = np.where(valid, arr, fill_value)
    elevation = _normalise_unit(filled, valid)

    if style == "gray":
        tone = elevation
    elif style == "hillshade":
        grad_y, grad_x = np.gradient(filled)
        slope = np.pi / 2.0 - np.arctan(np.hypot(grad_x, grad_y))
        aspect = np.arctan2(-grad_x, grad_y)
        azimuth = np.deg2rad(315.0)
        altitude = np.deg2rad(45.0)
        shade = (
            np.sin(altitude) * np.sin(slope)
            + np.cos(altitude) * np.cos(slope) * np.cos(azimuth - aspect)
        )
        shade = np.clip((shade + 1.0) / 2.0, 0.0, 1.0)
        tone = np.clip(0.68 * shade + 0.32 * elevation, 0.0, 1.0)
    else:
        raise ValueError("不支持的 DEM 样式。")

    rgba = np.zeros((arr.shape[0], arr.shape[1], 4), dtype=np.uint8)
    rgba[..., 0] = np.clip(54 + tone * 142, 0, 255).astype(np.uint8)
    rgba[..., 1] = np.clip(73 + tone * 145, 0, 255).astype(np.uint8)
    rgba[..., 2] = np.clip(90 + tone * 150, 0, 255).astype(np.uint8)
    rgba[..., 3] = np.where(valid, 255, 0).astype(np.uint8)
    return _encode_rgba_png(rgba)


def _detect_table_column(columns: list[str], candidates: list[str]) -> str | None:
    lookup = {str(column).strip().lower(): str(column) for column in columns}
    for candidate in candidates:
        found = lookup.get(str(candidate).strip().lower())
        if found:
            return found
    return None


def _station_type_metadata(raw_value: Any) -> tuple[str, str]:
    text = str(raw_value or "").strip().lower()
    compact = text.replace(" ", "").replace("_", "").replace("-", "")
    if not compact:
        station_type = "station"
    elif (
        compact in {"outlet", "control", "controlsection", "exit", "basinoutlet"}
        or "出口" in compact
        or "控制断面" in compact
        or "流域出口" in compact
        or "出水口" in compact
    ):
        station_type = "outlet"
    elif (
        compact in {"rain", "rainfall", "precip", "precipitation", "meteo", "meteorological", "weather"}
        or "雨量" in compact
        or "降水" in compact
        or "气象" in compact
    ):
        station_type = "rain"
    elif (
        compact in {"hydro", "hydrology", "hydrological", "discharge", "flow", "streamflow", "runoff", "river"}
        or "水文" in compact
        or "径流" in compact
        or "流量" in compact
    ):
        station_type = "hydrology"
    else:
        station_type = "station"
    return station_type, _STATION_TYPE_LABELS[station_type]


def _station_type_counts(points: list[dict[str, Any]]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for point in points:
        station_type = str(point.get("station_type", "") or "station")
        counts[station_type] = counts.get(station_type, 0) + 1
    return counts


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


def _workspace_dem_file(config: dict[str, Any], gis_dir: Path, context: GeoOverviewContext) -> Path | None:
    configured_dem_path = context.resolve_config_related_path(config, config.get("DEM_tif"))
    workspace_dem = context.workspace_dem_path(gis_dir, context.configured_dem_kind(config))
    return workspace_dem if workspace_dem.exists() else configured_dem_path


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
            type_col = _detect_table_column(
                columns,
                ["station_type", "type", "role", "kind", "class", "类别", "类型", "站点类型", "站类", "站别"],
            )
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
                station_type, station_type_label = _station_type_metadata(row.get(type_col, "") if type_col else "")
                points.append({
                    "id": station_id,
                    "label": station_id,
                    "coord": [round(lon, 6), round(lat, 6)],
                    "station_type": station_type,
                    "station_type_label": station_type_label,
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
            "metrics": {"station_count": len(points), "station_type_counts": _station_type_counts(points)},
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
        properties = {
            "id": str(point.get("id", "") or ""),
            "label": str(point.get("label", "") or point.get("id", "") or "站点"),
            "layer": str(layer.get("id", "") or ""),
            "layer_label": str(layer.get("label", "") or ""),
        }
        for key in ("station_type", "station_type_label"):
            value = str(point.get(key, "") or "")
            if value:
                properties[key] = value
        features.append({
            "type": "Feature",
            "geometry": {"type": "Point", "coordinates": [lon, lat]},
            "properties": properties,
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


def _polygon_layer_geojson(
    layer: dict[str, Any],
    feature_properties: dict[str, Any] | None = None,
) -> dict[str, Any]:
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
        properties = {
            "id": str(layer.get("id", "") or ""),
            "label": str(layer.get("label", "") or ""),
            "layer": str(layer.get("id", "") or ""),
            "feature_index": idx,
        }
        if feature_properties:
            properties.update(feature_properties)
        features.append({
            "type": "Feature",
            "geometry": {"type": "Polygon", "coordinates": [coords]},
            "properties": properties,
        })
    return {
        "type": "FeatureCollection",
        "features": features,
        "properties": {
            "id": str(layer.get("id", "") or ""),
            "label": str(layer.get("label", "") or ""),
            "kind": str(layer.get("kind", "") or ""),
            "status": str(layer.get("status", "") or ""),
            "message": str(layer.get("message", "") or ""),
            "bounds": layer.get("bounds"),
            "metrics": layer.get("metrics", {}),
        },
    }


def _polygon_layers_geojson(layer_id: str, label: str, layers: list[dict[str, Any]]) -> dict[str, Any]:
    features = []
    for layer in layers:
        extra = {
            "source_layer": str(layer.get("id", "") or ""),
            "source_label": str(layer.get("label", "") or ""),
        }
        for key in _ELEVATION_ZONE_PROPERTY_KEYS:
            if layer.get(key) is not None:
                extra[key] = layer[key]
        for feature in _polygon_layer_geojson(layer, extra).get("features", []):
            features.append(feature)

    ok_layers = [layer for layer in layers if layer.get("status") == "ok"]
    status = "ok" if ok_layers else ("error" if any(layer.get("status") == "error" for layer in layers) else "missing")
    message = f"{len(ok_layers)} 个图层" if ok_layers else (str(layers[0].get("message", "") or "未配置") if layers else "未配置")
    return {
        "type": "FeatureCollection",
        "features": features,
        "properties": {
            "id": layer_id,
            "label": label,
            "status": status,
            "message": message,
            "bounds": _merge_geo_bounds([layer.get("bounds") for layer in ok_layers]),
            "metrics": {
                "layer_count": len(ok_layers),
                "feature_count": len(features),
            },
            "layers": [
                {
                    "id": str(layer.get("id", "") or ""),
                    "label": str(layer.get("label", "") or ""),
                    "status": str(layer.get("status", "") or ""),
                    "message": str(layer.get("message", "") or ""),
                    "bounds": layer.get("bounds"),
                    "metrics": layer.get("metrics", {}),
                    **{
                        key: layer[key]
                        for key in _ELEVATION_ZONE_PROPERTY_KEYS
                        if layer.get(key) is not None
                    },
                }
                for layer in layers
            ],
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
    cfg_path, config, raw_config, profile, paths, gis_dir = _load_workspace_geo_sources(config_path_raw, context)
    basin_path = context.resolve_config_related_path(config, config.get("流域边界_shp"))
    dem_path = _workspace_dem_file(config, gis_dir, context)

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


def workspace_glacier_geojson(config_path_raw: str, context: GeoOverviewContext) -> dict[str, Any]:
    overview = workspace_geo_overview(config_path_raw, context)
    glacier_layer = next((layer for layer in overview.get("layers", []) if layer.get("id") == "glacier"), None)
    if not glacier_layer:
        return _empty_geojson_layer("glacier", "冰川")
    return _polygon_layer_geojson(
        glacier_layer,
        {"source_kind": str(glacier_layer.get("kind", "") or "")},
    )


def workspace_elevation_zones_geojson(config_path_raw: str, context: GeoOverviewContext) -> dict[str, Any]:
    _cfg_path, config, _raw_config, _profile, _paths, gis_dir = _load_workspace_geo_sources(config_path_raw, context)
    threshold_m = _finite_float(config.get("CFMAX分区阈值_m", 5000.0))
    layers: list[dict[str, Any]] = []
    for zone, label, filename in _ELEVATION_ZONE_SPECS:
        path = gis_dir / filename
        if not path.exists():
            continue
        layer = _raster_geo_layer(f"elevation_zone_{zone}", label, path, context)
        layer.update(_elevation_zone_metadata(zone, threshold_m))
        layers.append(layer)
    if not layers:
        return _empty_geojson_layer("elevation_zones", "高程分区", message="未生成高程分区")
    return _polygon_layers_geojson("elevation_zones", "高程分区", layers)


def workspace_dem_png(config_path_raw: str, context: GeoOverviewContext, style: str = "hillshade") -> dict[str, Any]:
    import numpy as np
    import rasterio
    from rasterio.warp import transform_bounds

    _cfg_path, config, _raw_config, _profile, _paths, gis_dir = _load_workspace_geo_sources(config_path_raw, context)
    dem_path = _workspace_dem_file(config, gis_dir, context)
    if dem_path is None:
        raise FileNotFoundError("DEM 未配置。")
    if not dem_path.exists():
        raise FileNotFoundError(f"DEM 文件不存在：{dem_path}")
    clean_style = str(style or "hillshade").strip().lower()
    if clean_style not in {"hillshade", "gray"}:
        raise ValueError("不支持的 DEM 样式。")

    try:
        with rasterio.open(dem_path) as src:
            if src.crs:
                bounds_values = transform_bounds(src.crs, "EPSG:4326", *src.bounds, densify_pts=21)
                crs_text = str(src.crs)
            else:
                bounds_values = src.bounds
                crs_text = ""
            bounds = _geo_bounds_dict(bounds_values)
            if not bounds:
                raise ValueError("DEM 范围无效。")
            max_dim = 768
            scale = min(1.0, max_dim / max(1, src.width), max_dim / max(1, src.height))
            out_width = max(2, int(round(src.width * scale)))
            out_height = max(2, int(round(src.height * scale)))
            arr = src.read(1, out_shape=(out_height, out_width), masked=True)
            if np.ma.isMaskedArray(arr):
                values = np.asarray(arr.astype("float64").filled(np.nan), dtype="float64")
            else:
                values = np.asarray(arr, dtype="float64")
            body = _dem_array_to_png(values, style=clean_style)
            return {
                "content_type": "image/png",
                "body": body,
                "bounds": bounds,
                "path": str(dem_path.resolve(strict=False)),
                "display_path": context.to_display_path(dem_path.resolve(strict=False)),
                "metrics": {
                    "width": int(src.width),
                    "height": int(src.height),
                    "preview_width": int(out_width),
                    "preview_height": int(out_height),
                    "crs": crs_text,
                    "style": clean_style,
                },
            }
    except FileNotFoundError:
        raise
    except ValueError:
        raise
    except Exception as exc:
        raise ValueError(f"DEM 晕渲失败：{exc}") from exc
