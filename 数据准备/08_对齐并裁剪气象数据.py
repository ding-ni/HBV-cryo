# -*- coding: utf-8 -*-
import argparse
import json
import re
import sys
import time
from datetime import datetime
from pathlib import Path

import geopandas as gpd
import numpy as np
import rasterio
from rasterio.features import geometry_mask
from rasterio.warp import Resampling, reproject

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "公共"))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "HBV-Studio"))

from 公共函数 import (
    basin_paths,
    build_workspace_paths,
    config_base_dir,
    ensure_workspace_dirs,
    example_config_path,
    infer_dem_kind_from_raster,
    read_config,
    resolve_path,
    resolve_workspace_dem_path,
)
from profile_runner import PROFILE_DAILY, build_profile_paths, configured_precip_source  # type: ignore
from services.meteo_import import DAILY_FORCING_MANIFEST_SCHEMA, tif_series_digest  # type: ignore
from services.time_utils import summarize_time_coverage  # type: ignore


DATE_RE = re.compile(r"(?<!\d)(\d{4})[._-](\d{2})[._-](\d{2})(?!\d)")
NODATA = -9999.0
MAX_REPAIR_CELLS = 5
MAX_REPAIR_FRACTION = 0.02


def resolve_config_entry_path(config, raw_value):
    resolved = resolve_path(str(raw_value or "").strip(), base=config_base_dir(config))
    return Path(resolved).resolve(strict=False) if resolved else Path("")


def parse_raster_date(file_name):
    match = DATE_RE.search(Path(file_name).name)
    if not match:
        return None
    return datetime(int(match.group(1)), int(match.group(2)), int(match.group(3)))


def collect_files(input_dir, start_date, end_date):
    records = []
    directory = Path(input_dir)
    if not directory.exists():
        return records
    seen_dates: dict[datetime, list[str]] = {}
    for file in directory.glob("*.tif"):
        date = parse_raster_date(file.name)
        if date is None:
            continue
        if start_date <= date <= end_date:
            seen_dates.setdefault(date, []).append(file.name)
            records.append((date, file))
    duplicates = {date: names for date, names in seen_dates.items() if len(names) > 1}
    if duplicates:
        first_date, names = next(iter(sorted(duplicates.items(), key=lambda item: item[0])))
        sample = "、".join(names[:3])
        raise RuntimeError(f"输入目录 {directory} 存在重复日期 {first_date.strftime('%Y.%m.%d')}，例如：{sample}")
    records.sort(key=lambda item: item[0])
    return records


def require_records(records, label, input_dir):
    if records:
        return records
    raise FileNotFoundError(
        f"{label}目录没有找到目标时段内的日尺度 TIF：{input_dir}。"
        "文件名需包含 YYYY-MM-DD、YYYY.MM.DD 或 YYYY_MM_DD 日期。"
    )


def resolve_processing_window(time_cfg):
    default_start = datetime.strptime(f"{int(time_cfg['开始年份'])}-01-01", "%Y-%m-%d")
    default_end = datetime.strptime(f"{int(time_cfg['结束年份'])}-12-31", "%Y-%m-%d")

    def parsed_values(keys):
        values = []
        for key in keys:
            raw = str(time_cfg.get(key, "") or "").strip()
            if raw:
                values.append(datetime.strptime(raw[:10], "%Y-%m-%d"))
        return values

    starts = parsed_values(("预热开始", "率定开始", "验证开始"))
    ends = parsed_values(("预热结束", "率定结束", "验证结束"))
    return min(starts) if starts else default_start, max(ends) if ends else default_end


def validate_mask_dates(prec_masks, temp_masks, evap_masks):
    date_sets = {
        "降水": set(prec_masks),
        "气温": set(temp_masks),
        "蒸散发": set(evap_masks),
    }
    expected = date_sets["降水"]
    if any(dates != expected for dates in date_sets.values()):
        union = set().union(*date_sets.values())
        details = []
        for label, dates in date_sets.items():
            missing = sorted(union - dates)
            if missing:
                details.append(f"{label}缺少 {missing[:5]}")
        raise RuntimeError("降水/气温/蒸散发日期不一致：" + "；".join(details))
    return sorted(expected)


def _finite_mask(data):
    return np.isfinite(data) & (data > -9000.0) & (data < 1.0e10)


def _nearest_fill_small_gaps(data, fill_mask, valid_mask, label, stamp):
    missing_mask = fill_mask & ~valid_mask
    missing = int(np.count_nonzero(missing_mask))
    if missing <= 0:
        return data, 0
    allowed = max(MAX_REPAIR_CELLS, int(np.ceil(int(np.count_nonzero(fill_mask)) * MAX_REPAIR_FRACTION)))
    if missing > allowed:
        raise RuntimeError(
            f"{label} {stamp} 在流域内缺少 {missing} 个有效像元，超过允许修补阈值 {allowed}。"
            "这通常是 ERA5/PET 原始 NetCDF 下载范围卡边导致的，请用外扩后的 bbox 重新下载/生成。"
        )
    try:
        from scipy import ndimage
    except Exception as exc:
        raise RuntimeError(
            f"{label} {stamp} 在流域内缺少 {missing} 个有效像元，但当前环境缺少 scipy，无法做小范围最近邻修补。"
            "请重新生成覆盖完整的原始栅格。"
        ) from exc
    if not np.any(valid_mask):
        raise RuntimeError(f"{label} {stamp} 没有任何有效像元，无法修补。")
    _, indices = ndimage.distance_transform_edt(~valid_mask, return_indices=True)
    repaired = data.copy()
    repaired[missing_mask] = data[indices[0][missing_mask], indices[1][missing_mask]]
    print(f"[修补] {label} {stamp}: 最近邻补齐流域边缘缺口 {missing} 个像元")
    return repaired, missing


def resampling_for_series(prefix):
    return Resampling.average if str(prefix).upper() == "PREC" else Resampling.bilinear


def align_single(input_file, dem_profile, dem_shape, basin_mask, resampling):
    with rasterio.open(input_file) as src:
        out = np.full(dem_shape, np.nan, dtype="float32")
        nodata = src.nodata
        reproject(
            source=rasterio.band(src, 1),
            destination=out,
            src_transform=src.transform,
            src_crs=src.crs,
            dst_transform=dem_profile["transform"],
            dst_crs=dem_profile["crs"],
            src_nodata=nodata,
            dst_nodata=np.nan,
            resampling=resampling,
        )
        if nodata is not None:
            out[out == nodata] = np.nan
    out[~basin_mask] = np.nan
    out[~_finite_mask(out)] = np.nan
    return out


def write_series(records, output_dir, prefix, dem_profile, dem_shape, basin_mask, overwrite=False, reference_masks=None):
    Path(output_dir).mkdir(parents=True, exist_ok=True)
    profile = dem_profile.copy()
    profile.update(dtype="float32", count=1, nodata=NODATA, compress="lzw")
    count = 0
    masks = {}
    repaired_total = 0
    resampling = resampling_for_series(prefix)
    print(f"[重采样] {prefix}: {resampling.name}")
    for index, (date, input_file) in enumerate(records):
        stamp = date.strftime("%Y.%m.%d")
        output_file = Path(output_dir) / f"{index}_{prefix}_{date.strftime('%Y.%m.%d')}.tif"
        if (not overwrite) and output_file.exists():
            existing = align_existing_mask(output_file, basin_mask)
            if reference_masks is not None:
                expected = reference_masks.get(stamp)
                if expected is not None and not np.array_equal(existing, expected):
                    raise RuntimeError(f"{prefix} {stamp} 已有输出与参考有效掩膜不一致，请使用 --覆盖 重新生成。")
            elif not np.array_equal(existing, basin_mask):
                missing = int(np.count_nonzero(basin_mask & ~existing))
                raise RuntimeError(f"{prefix} {stamp} 已有输出在流域内缺少 {missing} 个有效像元，请使用 --覆盖 重新生成。")
            masks[stamp] = existing
            count += 1
            continue
        data = align_single(input_file, dem_profile, dem_shape, basin_mask, resampling)
        valid_mask = _finite_mask(data) & basin_mask
        if reference_masks is not None:
            expected = reference_masks.get(stamp)
            if expected is None:
                raise RuntimeError(f"{prefix} {stamp} 找不到对应参考掩膜，不能保证 P/T/PET 一致。")
            data, repaired = _nearest_fill_small_gaps(data, expected, valid_mask, prefix, stamp)
            repaired_total += repaired
            valid_mask = _finite_mask(data) & basin_mask
            if not np.array_equal(valid_mask, expected):
                missing = int(np.count_nonzero(expected & ~valid_mask))
                extra = int(np.count_nonzero(valid_mask & ~expected))
                raise RuntimeError(f"{prefix} {stamp} 有效掩膜仍不一致：缺少 {missing} 个，多出 {extra} 个。")
        elif not np.array_equal(valid_mask, basin_mask):
            data, repaired = _nearest_fill_small_gaps(data, basin_mask, valid_mask, prefix, stamp)
            repaired_total += repaired
            valid_mask = _finite_mask(data) & basin_mask
            if not np.array_equal(valid_mask, basin_mask):
                missing = int(np.count_nonzero(basin_mask & ~valid_mask))
                raise RuntimeError(f"{prefix} {stamp} 在流域内仍缺少 {missing} 个有效像元。")
        with rasterio.open(output_file, "w", **profile) as dst:
            dst.write(np.where(np.isfinite(data), data, profile["nodata"]).astype("float32"), 1)
        masks[stamp] = valid_mask
        count += 1
    return count, masks, repaired_total


def align_existing_mask(output_file, basin_mask):
    with rasterio.open(output_file) as src:
        arr = src.read(1).astype("float32")
        if src.nodata is not None:
            arr[arr == src.nodata] = np.nan
    return _finite_mask(arr) & basin_mask


def write_daily_forcing_manifest(
    *,
    manifest_path,
    start_date,
    end_date,
    date_count,
    source_records,
    source_dirs,
    target_dirs,
    dem_file,
    dem_profile,
    dem_shape,
):
    manifest = {
        "schema": DAILY_FORCING_MANIFEST_SCHEMA,
        "created_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "producer": "HBV-Studio/08_对齐并裁剪气象数据.py",
        "preparation_mode": "align_daily_forcing_to_dem_basin_mask",
        "profile": PROFILE_DAILY,
        "time_step_hours": 24.0,
        "start_date": start_date.strftime("%Y-%m-%d"),
        "end_date": end_date.strftime("%Y-%m-%d"),
        "date_count": int(date_count),
        "precipitation": {
            "input_unit": "mm/day",
            "output_unit": "mm/day",
            "day_basis": "product_calendar_day",
            "unit_confirmed": True,
            "day_basis_confirmed": True,
        },
        "source_series": {
            key: {
                "source_dir": str(Path(source_dirs[key]).resolve(strict=False)),
                **tif_series_digest(list(source_records[key])),
            }
            for key in ("prec", "temp", "evap")
        },
        "target_dirs": {
            key: str(Path(target_dirs[key]).resolve(strict=False))
            for key in ("prec", "temp", "evap")
        },
        "grid": {
            "dem": str(Path(dem_file).resolve(strict=False)),
            "crs": str(dem_profile.get("crs")),
            "width": int(dem_shape[1]),
            "height": int(dem_shape[0]),
            "transform": [float(value) for value in dem_profile["transform"][:6]],
            "active_mask_required": True,
        },
        "qc": {
            "validation_ok": True,
            "validation_errors": [],
            "validation_warnings": [],
            "expected_steps": int(date_count),
            "valid_steps": int(date_count),
            "date_sets_equal": True,
            "active_masks_equal": True,
        },
    }
    manifest_path = Path(manifest_path)
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    return manifest_path


def main():
    parser = argparse.ArgumentParser(description="把温度、降水、蒸散发统一对齐到 DEM 并裁到流域。")
    parser.add_argument("--配置", "--config", dest="配置", default=str(example_config_path()))
    parser.add_argument("--降水源", "--prec-source", dest="降水源", choices=["era5", "mswep", "cmfd", "custom_tif"], default=None)
    parser.add_argument("--覆盖", "--overwrite", dest="覆盖", action="store_true")
    args = parser.parse_args()

    config = read_config(args.配置)
    paths = build_workspace_paths(config)
    profile_paths = build_profile_paths(config, PROFILE_DAILY)
    basin_info = basin_paths(config)
    ensure_workspace_dirs(paths)

    time_cfg = config["时间"]
    start_date, end_date = resolve_processing_window(time_cfg)
    print(f"[时段] 按工作区实际计算窗口处理：{start_date:%Y-%m-%d} 至 {end_date:%Y-%m-%d}")

    dem_file = resolve_workspace_dem_path(paths["gis_dir"], prefer=infer_dem_kind_from_raster(config.get("DEM_tif", "")))
    with rasterio.open(dem_file) as dem:
        dem_profile = dem.profile.copy()
        dem_profile.update(dtype="float32", nodata=-9999.0)
        dem_shape = (dem.height, dem.width)
        basin = gpd.read_file(basin_info["basin_shp"]).to_crs(dem.crs)
        basin_mask = ~geometry_mask(basin.geometry, out_shape=dem_shape, transform=dem.transform, invert=False)

    meteo = config.get("气象策略", {})
    configured_source = configured_precip_source(config)
    runtime_source = str(args.降水源 or configured_source or "era5").strip().lower()
    custom_prec_dir = str(meteo.get("自带降水tif目录", "")).strip()
    custom_prec_path = resolve_config_entry_path(config, custom_prec_dir)
    if runtime_source == "custom_tif":
        if not custom_prec_dir or not custom_prec_path.is_dir():
            raise FileNotFoundError(f"当前降水来源为 custom_tif，但自带降水tif目录无效：{custom_prec_dir or '未设置'}")
        prec_input = custom_prec_path
        prec_output = profile_paths["aligned_prec_custom_base_dir"]
        print(f"[降水] 使用自带 tif 目录: {prec_input}")
    elif runtime_source == "era5":
        prec_input = paths["raw_prec_era5_daily_dir"]
        prec_output = profile_paths["aligned_prec_era5_base_dir"]
        print(f"[降水] 使用 ERA5 日降水目录: {prec_input}")
    else:
        prec_input = paths["raw_prec_daily_dir"] if runtime_source == "mswep" else paths["raw_prec_cmfd_daily_dir"]
        prec_output = profile_paths["aligned_prec_base_dir"] if runtime_source == "mswep" else profile_paths["aligned_prec_cmfd_base_dir"]
        print(f"[降水] 使用格点目录: {prec_input}")

    temp_source = str(meteo.get("温度来源", "era5")).strip().lower()
    custom_temp_dir = str(meteo.get("自带温度tif目录", "")).strip()
    custom_temp_path = resolve_config_entry_path(config, custom_temp_dir)
    if temp_source == "custom_tif":
        if not custom_temp_dir or not custom_temp_path.is_dir():
            raise FileNotFoundError(f"当前温度来源为 custom_tif，但自带温度tif目录无效：{custom_temp_dir or '未设置'}")
        temp_input = custom_temp_path
        print(f"[温度] 使用自带 tif 目录: {temp_input}")
    else:
        temp_input = paths["raw_temp_daily_dir"]
        print(f"[温度] 使用 ERA5 处理结果: {temp_input}")

    pet_source = str(meteo.get("潜在蒸散发来源", "era5_fao56")).strip().lower()
    custom_pet_dir = str(meteo.get("自带蒸散发tif目录", "")).strip()
    custom_pet_path = resolve_config_entry_path(config, custom_pet_dir)
    if pet_source == "custom_tif":
        if not custom_pet_dir or not custom_pet_path.is_dir():
            raise FileNotFoundError(f"当前潜在蒸散发来源为 custom_tif，但自带蒸散发tif目录无效：{custom_pet_dir or '未设置'}")
        evap_input = custom_pet_path
        print(f"[蒸散发] 使用自带 tif 目录: {evap_input}")
    else:
        evap_input = paths["raw_evap_daily_dir"]
        print(f"[蒸散发] 使用 ERA5 处理结果: {evap_input}")

    prec_records = require_records(collect_files(prec_input, start_date, end_date), "降水", prec_input)
    temp_records = require_records(collect_files(temp_input, start_date, end_date), "气温", temp_input)
    evap_records = require_records(collect_files(evap_input, start_date, end_date), "蒸散发", evap_input)

    prec_count, prec_masks, prec_repaired = write_series(
        prec_records,
        prec_output,
        "PREC",
        dem_profile,
        dem_shape,
        basin_mask,
        overwrite=bool(args.覆盖),
    )
    temp_count, temp_masks, temp_repaired = write_series(
        temp_records,
        paths["aligned_temp_dir"],
        "TEMP",
        dem_profile,
        dem_shape,
        basin_mask,
        overwrite=bool(args.覆盖),
    )
    evap_count, evap_masks, evap_repaired = write_series(
        evap_records,
        paths["aligned_evap_dir"],
        "EVAP",
        dem_profile,
        dem_shape,
        basin_mask,
        overwrite=bool(args.覆盖),
    )
    for stamp in validate_mask_dates(prec_masks, temp_masks, evap_masks):
        if not np.array_equal(prec_masks[stamp], temp_masks[stamp]) or not np.array_equal(prec_masks[stamp], evap_masks[stamp]):
            raise RuntimeError(f"{stamp} 降水/气温/蒸散发有效像元掩膜不一致。")
    manifest_path = write_daily_forcing_manifest(
        manifest_path=Path(profile_paths["aligned_dir"]) / "daily_forcing_manifest.json",
        start_date=start_date,
        end_date=end_date,
        date_count=len(prec_masks),
        source_records={"prec": prec_records, "temp": temp_records, "evap": evap_records},
        source_dirs={"prec": prec_input, "temp": temp_input, "evap": evap_input},
        target_dirs={
            "prec": prec_output,
            "temp": paths["aligned_temp_dir"],
            "evap": paths["aligned_evap_dir"],
        },
        dem_file=dem_file,
        dem_profile=dem_profile,
        dem_shape=dem_shape,
    )
    summary = {
        "降水": prec_records,
        "气温": temp_records,
        "潜在蒸散发": evap_records,
    }

    for name, records in summary.items():
        coverage = summarize_time_coverage([timestamp for timestamp, _ in records], 24.0)
        print(f"{name}: {coverage['period_summary']}")
    repaired_total = int(prec_repaired + temp_repaired + evap_repaired)
    if repaired_total:
        print(f"[修补统计] 共最近邻补齐 {repaired_total} 个流域边缘缺口像元。")
    print("[校验] 降水/气温/蒸散发逐日有效像元掩膜一致。")
    print(f"[清单] 日强迫输入契约已写入: {manifest_path}")


if __name__ == "__main__":
    main()
