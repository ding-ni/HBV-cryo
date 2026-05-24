# -*- coding: utf-8 -*-
"""
Create glacier raster products from glacier shapefile using DEM grid.

Outputs:
  - 数据/地理数据/glacier_mask.tif
  - 数据/地理数据/glacier_fraction.tif (fractional mode only)
"""
import json
import os
from math import radians, sin

import geopandas as gpd
import numpy as np
import rasterio
from pyproj import CRS, Transformer
from rasterio.features import rasterize
from shapely.geometry import box
from shapely.ops import transform as shapely_transform


def _prefer_existing_path(*paths):
    for path in paths:
        if os.path.exists(path):
            return path
    return paths[0]


PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "运行目录", "默认流域"))
DATA_ROOT = _prefer_existing_path(os.path.join(PROJECT_ROOT, "数据"), os.path.join(PROJECT_ROOT, "data"))
GIS_ROOT = _prefer_existing_path(os.path.join(DATA_ROOT, "地理数据"), os.path.join(DATA_ROOT, "gis"))
DEM_FILE = os.path.join(GIS_ROOT, "dem_1km.tif")
BASIN_SHP = os.path.join(GIS_ROOT, "basin.shp")
GLACIER_SHP = os.path.join(GIS_ROOT, "glacier_shp", "glacier.shp")
OUT_FILE = os.path.join(GIS_ROOT, "glacier_mask.tif")
FRACTION_FILE = os.path.join(GIS_ROOT, "glacier_fraction.tif")
SUMMARY_FILE = os.path.join(GIS_ROOT, "glacier_mask_summary.json")

FRACTION_NODATA = -9999.0
MASK_NODATA = 255


def compute_area_km2_from_mask(mask, transform):
    """Compute binary area for EPSG:4326-like rasters."""
    pixel_width_deg = abs(float(transform.a))
    pixel_height_deg = abs(float(transform.e))
    top_lat = transform.f
    earth_radius = 6371000.0
    dlon = radians(pixel_width_deg)
    total_area_m2 = 0.0
    for row in range(mask.shape[0]):
        count = int((mask[row, :] > 0).sum())
        if count == 0:
            continue
        lat_n = top_lat - row * pixel_height_deg
        lat_s = top_lat - (row + 1) * pixel_height_deg
        area_row_m2 = (earth_radius ** 2) * dlon * (sin(radians(lat_n)) - sin(radians(lat_s)))
        total_area_m2 += area_row_m2 * count
    return total_area_m2 / 1e6


def infer_dem_kind(dem_path, profile, transform):
    lowered = os.path.basename(str(dem_path)).lower()
    if "0p1" in lowered or "0.1" in lowered:
        return "0p1deg"
    if "1km" in lowered:
        return "1km"
    crs_text = str(profile.get("crs") or "").upper()
    res_x = abs(float(transform.a))
    res_y = abs(float(transform.e))
    if "EPSG:4326" in crs_text or "EPSG:4490" in crs_text:
        if abs(res_x - 0.1) <= 0.002 and abs(res_y - 0.1) <= 0.002:
            return "0p1deg"
        if abs(res_x - (1.0 / 120.0)) <= 0.002 and abs(res_y - (1.0 / 120.0)) <= 0.002:
            return "1km"
    return "0p1deg"


def pick_area_crs(*crs_candidates):
    for candidate in crs_candidates:
        if not candidate:
            continue
        try:
            crs = CRS.from_user_input(candidate)
        except Exception:
            continue
        if not crs.is_geographic:
            return crs
    return CRS.from_epsg(6933)


def cell_polygon(transform, row, col):
    left = transform.c + col * transform.a
    top = transform.f + row * transform.e
    right = left + transform.a
    bottom = top + transform.e
    return box(min(left, right), min(bottom, top), max(left, right), max(bottom, top))


def build_fraction_raster(out_shape, transform, clipped_glacier_dem, area_crs, basin_mask):
    rows, cols = out_shape
    fraction = np.zeros((rows, cols), dtype=np.float32)
    if clipped_glacier_dem.empty:
        return fraction, 0.0, 0

    glacier_proj = clipped_glacier_dem.to_crs(area_crs)
    if glacier_proj.empty:
        return fraction, 0.0, 0

    transformer = Transformer.from_crs(clipped_glacier_dem.crs, area_crs, always_xy=True)
    to_area = transformer.transform
    sindex = glacier_proj.sindex
    represented_area_m2 = 0.0
    nonzero_pixels = 0

    active_rows, active_cols = np.where(basin_mask == 1)
    for row, col in zip(active_rows.tolist(), active_cols.tolist()):
        cell_dem = cell_polygon(transform, row, col)
        cell_proj = shapely_transform(to_area, cell_dem)
        cell_area = float(cell_proj.area)
        if cell_area <= 0.0:
            continue

        candidate_idx = list(sindex.intersection(cell_proj.bounds))
        if not candidate_idx:
            continue
        overlap_area = 0.0
        for geom in glacier_proj.geometry.iloc[candidate_idx]:
            if geom is None or geom.is_empty or (not geom.intersects(cell_proj)):
                continue
            overlap_area += float(geom.intersection(cell_proj).area)
        if overlap_area <= 0.0:
            continue

        frac = max(0.0, min(overlap_area / cell_area, 1.0))
        if frac <= 0.0:
            continue
        fraction[row, col] = np.float32(frac)
        represented_area_m2 += frac * cell_area
        nonzero_pixels += 1

    return fraction, represented_area_m2 / 1e6, nonzero_pixels


def write_fraction_raster(path, profile, basin_mask, fraction):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    out = np.full(fraction.shape, FRACTION_NODATA, dtype=np.float32)
    out[basin_mask == 1] = fraction[basin_mask == 1]
    profile_fraction = profile.copy()
    profile_fraction.update(dtype="float32", count=1, nodata=FRACTION_NODATA, compress="lzw")
    with rasterio.open(path, "w", **profile_fraction) as dst:
        dst.write(out, 1)


def write_mask_raster(path, profile, basin_mask, mask):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    out = np.where(basin_mask == 1, mask, MASK_NODATA).astype("uint8")
    profile_mask = profile.copy()
    profile_mask.update(dtype="uint8", count=1, nodata=MASK_NODATA, compress="lzw")
    with rasterio.open(path, "w", **profile_mask) as dst:
        dst.write(out, 1)


def main():
    if not os.path.exists(DEM_FILE):
        raise FileNotFoundError(DEM_FILE)
    if not os.path.exists(GLACIER_SHP):
        raise FileNotFoundError(GLACIER_SHP)

    with rasterio.open(DEM_FILE) as dem:
        profile = dem.profile.copy()
        transform = dem.transform
        out_shape = (dem.height, dem.width)
        dem_crs = dem.crs
        dem_kind = infer_dem_kind(DEM_FILE, profile, transform)

    glacier_source = gpd.read_file(GLACIER_SHP)
    glacier_source = glacier_source.loc[
        glacier_source.geometry.notnull() & (~glacier_source.geometry.is_empty)
    ].copy()
    if glacier_source.empty:
        raise ValueError("No valid glacier geometries found.")

    glacier_dem = glacier_source.to_crs(dem_crs) if glacier_source.crs != dem_crs else glacier_source.copy()
    basin_mask = np.ones(out_shape, dtype="uint8")
    clipped_glacier_dem = glacier_dem.copy()
    basin_crs = None
    intersecting_count = None
    clipped_to_basin = False

    if os.path.exists(BASIN_SHP):
        basin_gdf = gpd.read_file(BASIN_SHP)
        basin_crs = basin_gdf.crs
        if basin_gdf.crs != dem_crs:
            basin_gdf = basin_gdf.to_crs(dem_crs)
        basin_shapes = [(geom, 1) for geom in basin_gdf.geometry if geom is not None and not geom.is_empty]
        if basin_shapes:
            basin_mask = rasterize(
                basin_shapes,
                out_shape=out_shape,
                transform=transform,
                fill=0,
                dtype="uint8",
            )
            if len(clipped_glacier_dem):
                basin_union = basin_gdf.geometry.union_all() if hasattr(basin_gdf.geometry, "union_all") else basin_gdf.geometry.unary_union
                intersects = clipped_glacier_dem.geometry.intersects(basin_union)
                intersecting_count = int(np.sum(intersects))
                if 0 < intersecting_count < int(len(clipped_glacier_dem)):
                    clipped_to_basin = True
                if intersecting_count > 0:
                    clipped_glacier_dem = clipped_glacier_dem.loc[intersects].copy()
                    clipped_glacier_dem["geometry"] = clipped_glacier_dem.geometry.intersection(basin_union)
                    clipped_glacier_dem = clipped_glacier_dem.loc[
                        clipped_glacier_dem.geometry.notnull() & (~clipped_glacier_dem.geometry.is_empty)
                    ].copy()
                else:
                    clipped_glacier_dem = clipped_glacier_dem.iloc[0:0].copy()

    area_crs = pick_area_crs(glacier_source.crs, basin_crs, dem_crs)
    if clipped_glacier_dem.empty:
        true_glacier_area_km2 = 0.0
    else:
        true_glacier_area_km2 = float(clipped_glacier_dem.to_crs(area_crs).geometry.area.sum() / 1e6)

    summary = {
        "status": "ok",
        "message": "",
        "glacier_mode": "binary_legacy" if dem_kind == "1km" else "fractional_subgrid",
        "dem_kind": dem_kind,
        "dem_crs": str(dem_crs) if dem_crs else "",
        "area_crs": str(area_crs),
        "input_feature_count": int(len(glacier_source)),
        "valid_feature_count": int(len(glacier_source)),
        "intersecting_feature_count": intersecting_count,
        "reprojected_to_dem": bool(glacier_source.crs != dem_crs),
        "clipped_to_basin": clipped_to_basin,
        "mask_exists": False,
        "fraction_exists": False,
        "glacier_pixels": 0,
        "glacier_area_km2": 0.0,
        "true_glacier_area_km2": round(float(true_glacier_area_km2), 6),
        "represented_area_km2": 0.0,
        "nonzero_fraction_pixels": 0,
        "fraction_min": 0.0,
        "fraction_max": 0.0,
        "fraction_mean": 0.0,
        "area_bias_ratio": 0.0,
    }

    os.makedirs(os.path.dirname(OUT_FILE), exist_ok=True)
    if summary["glacier_mode"] == "binary_legacy":
        glacier_shapes = [
            (geom, 1)
            for geom in clipped_glacier_dem.geometry
            if geom is not None and not geom.is_empty
        ]
        if glacier_shapes:
            glacier_mask = rasterize(
                glacier_shapes,
                out_shape=out_shape,
                transform=transform,
                fill=0,
                dtype="uint8",
            )
        else:
            glacier_mask = np.zeros(out_shape, dtype="uint8")
            if intersecting_count == 0:
                summary["status"] = "no_intersection"
                summary["message"] = "输入冰川 shp 与当前流域不相交，已生成空冰川掩膜。"

        write_mask_raster(OUT_FILE, profile, basin_mask, glacier_mask)
        valid_mask = (glacier_mask > 0) & (basin_mask == 1)
        mask_area_km2 = compute_area_km2_from_mask(valid_mask.astype("uint8"), transform)
        summary["mask_exists"] = True
        summary["glacier_pixels"] = int(valid_mask.sum())
        summary["glacier_area_km2"] = round(float(mask_area_km2), 6)
        summary["represented_area_km2"] = round(float(mask_area_km2), 6)
        if true_glacier_area_km2 > 0.0:
            summary["area_bias_ratio"] = round(float(mask_area_km2 / true_glacier_area_km2), 6)
        if summary["status"] == "ok" and summary["clipped_to_basin"]:
            summary["message"] = "输入冰川 shp 已裁到当前流域，并按 1km 二值法生成冰川掩膜。"
        if not summary["message"]:
            summary["message"] = "冰川掩膜已按 1km 二值法生成。"
    else:
        fraction, represented_area_km2, nonzero_pixels = build_fraction_raster(
            out_shape,
            transform,
            clipped_glacier_dem,
            area_crs,
            basin_mask,
        )
        glacier_mask = np.where(fraction > 0.0, 1, 0).astype("uint8")
        write_fraction_raster(FRACTION_FILE, profile, basin_mask, fraction)
        write_mask_raster(OUT_FILE, profile, basin_mask, glacier_mask)

        positive_fraction = fraction[fraction > 0.0]
        summary["mask_exists"] = True
        summary["fraction_exists"] = True
        summary["glacier_pixels"] = int((glacier_mask > 0).sum())
        summary["glacier_area_km2"] = round(float(represented_area_km2), 6)
        summary["represented_area_km2"] = round(float(represented_area_km2), 6)
        summary["nonzero_fraction_pixels"] = int(nonzero_pixels)
        if positive_fraction.size:
            summary["fraction_min"] = round(float(np.min(positive_fraction)), 6)
            summary["fraction_max"] = round(float(np.max(positive_fraction)), 6)
            summary["fraction_mean"] = round(float(np.mean(positive_fraction)), 6)
        if true_glacier_area_km2 > 0.0:
            summary["area_bias_ratio"] = round(float(represented_area_km2 / true_glacier_area_km2), 6)

        if intersecting_count == 0:
            summary["status"] = "no_intersection"
            summary["message"] = "输入冰川 shp 与当前流域不相交，已生成空冰川分数栅格。"
        elif nonzero_pixels == 0:
            summary["status"] = "empty_fraction"
            summary["message"] = "流域内存在冰川，但分数面积栅格为空，请检查输入范围或 DEM。"
        else:
            summary["message"] = "当前为 0.1° 分数法，已生成 glacier_fraction.tif 与兼容用 glacier_mask.tif。"

    os.makedirs(os.path.dirname(SUMMARY_FILE), exist_ok=True)
    with open(SUMMARY_FILE, "w", encoding="utf-8") as fh:
        json.dump(summary, fh, ensure_ascii=False, indent=2)

    print(f"[OK] glacier_mask.tif written: {OUT_FILE}")
    if summary["fraction_exists"]:
        print(f"[OK] glacier_fraction.tif written: {FRACTION_FILE}")
        print(f"      glacier mode: {summary['glacier_mode']}")
        print(f"      true glacier area: {summary['true_glacier_area_km2']:.2f} km2")
        print(f"      represented area: {summary['represented_area_km2']:.2f} km2")
        print(f"      nonzero fraction pixels: {summary['nonzero_fraction_pixels']}")
    else:
        print(f"      glacier mode: {summary['glacier_mode']}")
        print(f"      glacier pixels: {summary['glacier_pixels']}")
        print(f"      glacier area: {summary['glacier_area_km2']:.2f} km2")
    print(f"      summary: {summary['message']}")


if __name__ == "__main__":
    main()
