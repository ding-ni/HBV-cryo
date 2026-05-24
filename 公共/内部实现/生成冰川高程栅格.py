# -*- coding: utf-8 -*-
"""
Generate glacier_elev.tif: per-pixel area-weighted mean glacier elevation.

Algorithm (same coordinate convention as 生成冰川掩膜.py::build_fraction_raster):
  For each 0.1° target pixel inside basin, intersect its geometry with the
  glacier polygon union in an equal-area CRS, then area-weight-average the
  1km DEM elevations over the intersection.

Outputs:
  数据/地理数据/glacier_elev.tif         (float32, nodata=-9999)
  数据/地理数据/glacier_elev_summary.json
"""
import json
import os
import sys
from math import radians, sin

import geopandas as gpd
import numpy as np
import rasterio
from pyproj import CRS, Transformer
from rasterio.features import rasterize
from rasterio.windows import from_bounds
from shapely.geometry import box
from shapely.ops import transform as shapely_transform, unary_union

_HERE = os.path.dirname(__file__)
_PUBLIC_DIR = os.path.abspath(os.path.join(_HERE, "..", ".."))
if _PUBLIC_DIR not in sys.path:
    sys.path.insert(0, _PUBLIC_DIR)

from 公共 import 公共函数 as _common  # noqa: E402


def _prefer_existing_path(*paths):
    for path in paths:
        if os.path.exists(path):
            return path
    return paths[0]


PROJECT_ROOT = os.path.abspath(os.path.join(_HERE, "..", "..", "运行目录", "默认流域"))
DATA_ROOT = _prefer_existing_path(os.path.join(PROJECT_ROOT, "数据"), os.path.join(PROJECT_ROOT, "data"))
GIS_ROOT = _prefer_existing_path(os.path.join(DATA_ROOT, "地理数据"), os.path.join(DATA_ROOT, "gis"))
BASIN_SHP = os.path.join(GIS_ROOT, "basin.shp")
GLACIER_SHP = os.path.join(GIS_ROOT, "glacier_shp", "glacier.shp")
OUT_FILE = os.path.join(GIS_ROOT, "glacier_elev.tif")
SUMMARY_FILE = os.path.join(GIS_ROOT, "glacier_elev_summary.json")

NODATA_OUT = -9999.0

_HBVCRYO_ROOT_CANDIDATES = [
    os.path.abspath(os.path.join(_HERE, "..", "..")),
    os.path.abspath(os.path.join(_HERE, "..", "..", "..")),
]
_FALLBACK_HIDEM_RELPATH = os.path.join("基础数据", "DEM源", "青藏高原_1km_DEM.tif")


def _fallback_hidem_paths():
    paths = []
    for root in _HBVCRYO_ROOT_CANDIDATES:
        paths.append(os.path.join(root, _FALLBACK_HIDEM_RELPATH))
    return paths


def locate_high_res_dem():
    """Return (path, source_label) or (None, None)."""
    candidates = []
    gis_1km = os.path.join(GIS_ROOT, "dem_1km.tif")
    candidates.append((gis_1km, "workspace:dem_1km.tif"))

    env_path = os.environ.get("HBV_HIGH_RES_DEM", "").strip()
    if env_path:
        candidates.append((env_path, "env:HBV_HIGH_RES_DEM"))

    for fb in _fallback_hidem_paths():
        candidates.append((fb, "fallback:基础数据/DEM源"))

    for path, label in candidates:
        if path and os.path.exists(path):
            return path, label, [c[0] for c in candidates]
    return None, None, [c[0] for c in candidates]


def cell_polygon(transform, row, col):
    left = transform.c + col * transform.a
    top = transform.f + row * transform.e
    right = left + transform.a
    bottom = top + transform.e
    return box(min(left, right), min(bottom, top), max(left, right), max(bottom, top))


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


def write_summary(status, **kwargs):
    payload = {"status": status}
    payload.update(kwargs)
    with open(SUMMARY_FILE, "w", encoding="utf-8") as fh:
        json.dump(payload, fh, ensure_ascii=False, indent=2)


def _log_and_summary_for_no_hidem(target_dem_path, candidates, basin_from_shp):
    msg = (
        "未找到高分辨率 (1km) DEM，glacier_elev.tif 未生成。"
        "率定时 0.1° 冰川子格温度递减不会启用，结果会被标记为 degraded。"
    )
    print(f"[ERROR] {msg}")
    print("  检查过以下候选路径:")
    for c in candidates:
        print(f"    - {c}")
    write_summary(
        "no_high_res_dem",
        dem_kind="0p1deg",
        target_dem=target_dem_path,
        high_res_dem_candidates=candidates,
        message=msg,
    )


def main():
    target_dem_path = str(_common.resolve_workspace_dem_path(GIS_ROOT))
    if not os.path.exists(target_dem_path):
        raise FileNotFoundError(target_dem_path)

    with rasterio.open(target_dem_path) as target_src:
        target_profile = target_src.profile.copy()
        target_transform = target_src.transform
        target_crs = target_src.crs
        out_shape = (target_src.height, target_src.width)
        target_dem_arr = target_src.read(1).astype(np.float32)
        target_nodata = target_src.nodata

    if target_nodata is not None:
        target_dem_arr = np.where(target_dem_arr == target_nodata, np.nan, target_dem_arr)

    dem_kind = _common.infer_dem_kind_from_raster(target_dem_path)

    if dem_kind == "1km":
        msg = "1km 工作区无需生成 glacier_elev.tif (像元高程即冰川高程)。"
        print(f"[SKIP] {msg}")
        write_summary("not_needed_1km", dem_kind="1km", target_dem=target_dem_path, message=msg)
        return

    if not os.path.exists(GLACIER_SHP):
        msg = f"未找到冰川 shp: {GLACIER_SHP}"
        print(f"[SKIP] {msg}")
        write_summary("no_glacier_shp", dem_kind=dem_kind, target_dem=target_dem_path, message=msg)
        return

    hidem_path, hidem_label, hidem_candidates = locate_high_res_dem()

    basin_mask = np.ones(out_shape, dtype="uint8")
    basin_crs = None
    if os.path.exists(BASIN_SHP):
        basin_gdf = gpd.read_file(BASIN_SHP)
        basin_crs = basin_gdf.crs
        if basin_gdf.crs != target_crs:
            basin_gdf = basin_gdf.to_crs(target_crs)
        basin_shapes = [(g, 1) for g in basin_gdf.geometry if g is not None and not g.is_empty]
        if basin_shapes:
            basin_mask = rasterize(
                basin_shapes,
                out_shape=out_shape,
                transform=target_transform,
                fill=0,
                dtype="uint8",
            )

    if hidem_path is None:
        _log_and_summary_for_no_hidem(target_dem_path, hidem_candidates, basin_mask)
        sys.exit(2)

    glacier_gdf_source = gpd.read_file(GLACIER_SHP)
    glacier_gdf_source = glacier_gdf_source.loc[
        glacier_gdf_source.geometry.notnull() & (~glacier_gdf_source.geometry.is_empty)
    ].copy()
    if glacier_gdf_source.empty:
        msg = "冰川 shp 中无有效几何。"
        print(f"[SKIP] {msg}")
        write_summary("empty_glacier", dem_kind=dem_kind, target_dem=target_dem_path, message=msg)
        return

    area_crs = pick_area_crs(glacier_gdf_source.crs, basin_crs, target_crs)

    glacier_in_target = (
        glacier_gdf_source.to_crs(target_crs)
        if glacier_gdf_source.crs != target_crs
        else glacier_gdf_source.copy()
    )

    with rasterio.open(hidem_path) as hi_src:
        hi_transform = hi_src.transform
        hi_crs = hi_src.crs
        hi_shape = (hi_src.height, hi_src.width)
        hi_nodata = hi_src.nodata

        transformer_to_area_from_target = Transformer.from_crs(target_crs, area_crs, always_xy=True).transform
        transformer_to_area_from_hi = Transformer.from_crs(hi_crs, area_crs, always_xy=True).transform
        transformer_target_to_hi = Transformer.from_crs(target_crs, hi_crs, always_xy=True).transform

        glacier_in_target_proj_area = glacier_in_target.to_crs(area_crs)
        glacier_sindex = glacier_in_target_proj_area.sindex

        glacier_elev = np.full(out_shape, np.nan, dtype=np.float32)
        covered = 0
        missing_coverage = 0
        ew_sum = 0.0
        area_sum = 0.0

        active_rows, active_cols = np.where(basin_mask == 1)
        n_active = len(active_rows)
        print(f"[INFO] 基底 DEM: {target_dem_path}")
        print(f"[INFO] 高分辨率 DEM: {hidem_path} (来源: {hidem_label})")
        print(f"[INFO] 冰川 shp: {GLACIER_SHP}")
        print(f"[INFO] 等面积投影: {area_crs.to_string()}")
        print(f"[INFO] 流域内像元数: {n_active}")

        for prog, (row, col) in enumerate(zip(active_rows.tolist(), active_cols.tolist())):
            if prog % 5000 == 0 and prog > 0:
                print(f"  进度 {prog}/{n_active}")

            cell_geom_target = cell_polygon(target_transform, row, col)
            cell_geom_area = shapely_transform(transformer_to_area_from_target, cell_geom_target)
            if cell_geom_area.is_empty or cell_geom_area.area <= 0:
                continue

            candidate_idx = list(glacier_sindex.intersection(cell_geom_area.bounds))
            if not candidate_idx:
                continue

            glacier_parts_area = []
            for geom in glacier_in_target_proj_area.geometry.iloc[candidate_idx]:
                if geom is None or geom.is_empty:
                    continue
                if not geom.intersects(cell_geom_area):
                    continue
                inter = geom.intersection(cell_geom_area)
                if inter.is_empty or inter.area <= 0:
                    continue
                glacier_parts_area.append(inter)
            if not glacier_parts_area:
                continue
            glacier_in_cell_area = unary_union(glacier_parts_area)
            if glacier_in_cell_area.is_empty or glacier_in_cell_area.area <= 0:
                continue

            cell_geom_hi = shapely_transform(transformer_target_to_hi, cell_geom_target)
            hi_bounds = cell_geom_hi.bounds
            try:
                window = from_bounds(*hi_bounds, transform=hi_transform).round_offsets().round_lengths()
            except Exception:
                continue

            row_off = max(int(window.row_off) - 1, 0)
            col_off = max(int(window.col_off) - 1, 0)
            row_end = min(int(window.row_off + window.height) + 1, hi_shape[0])
            col_end = min(int(window.col_off + window.width) + 1, hi_shape[1])
            if row_end <= row_off or col_end <= col_off:
                continue

            sub_window = rasterio.windows.Window(col_off, row_off, col_end - col_off, row_end - row_off)
            sub_arr = hi_src.read(1, window=sub_window).astype(np.float64)
            sub_transform = hi_src.window_transform(sub_window)
            if hi_nodata is not None:
                sub_arr = np.where(sub_arr == hi_nodata, np.nan, sub_arr)

            numerator = 0.0
            denominator = 0.0
            sub_rows, sub_cols = sub_arr.shape
            for ii in range(sub_rows):
                for jj in range(sub_cols):
                    elev_ij = sub_arr[ii, jj]
                    if not np.isfinite(elev_ij):
                        continue
                    px_hi = cell_polygon(sub_transform, ii, jj)
                    if not px_hi.intersects(cell_geom_hi):
                        continue
                    px_area_geom = shapely_transform(transformer_to_area_from_hi, px_hi)
                    if px_area_geom.is_empty:
                        continue
                    overlap = px_area_geom.intersection(glacier_in_cell_area)
                    if overlap.is_empty or overlap.area <= 0:
                        continue
                    numerator += float(elev_ij) * float(overlap.area)
                    denominator += float(overlap.area)

            if denominator > 0:
                elev_value = numerator / denominator
                glacier_elev[row, col] = np.float32(elev_value)
                covered += 1
                ew_sum += elev_value * denominator
                area_sum += denominator
            else:
                missing_coverage += 1

    out_arr = np.where(np.isfinite(glacier_elev), glacier_elev, NODATA_OUT).astype(np.float32)
    out_profile = target_profile.copy()
    out_profile.update(dtype="float32", count=1, nodata=NODATA_OUT, compress="lzw")
    with rasterio.open(OUT_FILE, "w", **out_profile) as dst:
        dst.write(out_arr, 1)

    finite_elev = glacier_elev[np.isfinite(glacier_elev)]
    summary_payload = {
        "dem_kind": dem_kind,
        "target_dem": target_dem_path,
        "high_res_dem_source": hidem_path,
        "high_res_dem_label": hidem_label,
        "area_crs": area_crs.to_string(),
        "glacier_pixels_with_elev": int(covered),
        "glacier_pixels_without_elev": int(missing_coverage),
        "elev_min": round(float(finite_elev.min()), 3) if finite_elev.size else None,
        "elev_max": round(float(finite_elev.max()), 3) if finite_elev.size else None,
        "elev_mean": round(float(finite_elev.mean()), 3) if finite_elev.size else None,
        "area_weighted_elev_mean": round(float(ew_sum / area_sum), 3) if area_sum > 0 else None,
        "notes": ["面积加权算法 (等面积 CRS 下 polygon 交集 × 1km 像素加权)"],
    }

    if covered == 0:
        summary_payload["message"] = "流域内冰川像元均未覆盖到高分辨率 DEM 有效值，glacier_elev.tif 全 nodata。"
        write_summary("no_intersection", **summary_payload)
        print("[WARN] 流域内冰川像元均未匹配到高分辨率 DEM 有效值。")
    else:
        summary_payload["message"] = (
            f"已生成 glacier_elev.tif，冰川像元 {covered} 个有高程，"
            f"{missing_coverage} 个缺失。"
        )
        write_summary("ok", **summary_payload)
        print(f"[OK] glacier_elev.tif written: {OUT_FILE}")
        print(f"      覆盖像元: {covered} (缺失 {missing_coverage})")
        if finite_elev.size:
            print(
                f"      高程范围: [{float(finite_elev.min()):.1f}, {float(finite_elev.max()):.1f}] m"
                f"  面积加权均值: {ew_sum / area_sum:.1f} m"
            )


if __name__ == "__main__":
    main()
