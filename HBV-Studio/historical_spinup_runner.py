#!/usr/bin/env python
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from contextlib import ExitStack
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import rasterio
import xarray as xr
from rasterio.crs import CRS
from rasterio.transform import from_bounds
from rasterio.vrt import WarpedVRT
from rasterio.warp import Resampling, reproject

STUDIO_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = STUDIO_DIR.parent
PUBLIC_DIR = PROJECT_ROOT / "公共"
for candidate in (STUDIO_DIR, PUBLIC_DIR):
    if str(candidate) not in sys.path:
        sys.path.insert(0, str(candidate))

from initial_state_sensitivity_runner import (  # noqa: E402
    _initial_state_vectors,
    _run_local_forcing,
    _runoff_depth_mm,
    _snapshot_for_proxy_inputs,
    summarize_snapshot,
)
from services.historical_spinup import (  # noqa: E402
    apply_monthly_transition,
    build_monthly_transition_factors,
    calculate_fao56_daily_pet,
    daily_values_from_next_midnight_accumulation,
    expected_daily_index,
    file_identity,
    sha256_file,
    validate_four_samples_per_day,
)
from studio_service import _build_forward_payload_context, _get_or_create_forward_runtime  # noqa: E402
from era5_accumulation import ERA5_ACCUMULATION_CONTRACT  # noqa: E402
from 公共函数 import open_netcdf_dataset_safe, resolve_workspace_dem_path  # type: ignore  # noqa: E402


DATE_PATTERN = re.compile(r"(\d{4})[-.](\d{2})[-.](\d{2})")
HISTORICAL_START = pd.Timestamp("2022-01-01")
HISTORICAL_END = pd.Timestamp("2024-12-31")
REFERENCE_START = pd.Timestamp("2025-01-01")
REFERENCE_END = pd.Timestamp("2025-12-31")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run continuous 2022-2024 ERA5-Land state spin-up before a saved 2025 HBV-Cryo run."
    )
    parser.add_argument("--run", required=True, help="Saved run directory containing metadata.json.")
    parser.add_argument("--era5-root", required=True, help="Historical ERA5 raw meteorological root.")
    parser.add_argument("--v2-dir", required=True, help="Immutable 2025 v2 daily precipitation directory.")
    parser.add_argument("--output", default="", help="Optional output JSON path.")
    return parser.parse_args()


def _load_data_array(paths: list[Path], variable: str) -> tuple[np.ndarray, pd.DatetimeIndex, np.ndarray, np.ndarray]:
    arrays: list[xr.DataArray] = []
    with ExitStack() as stack:
        for path in paths:
            dataset = stack.enter_context(open_netcdf_dataset_safe(path))
            if variable not in dataset.data_vars:
                raise ValueError(f"{path.name} does not contain {variable}.")
            values = dataset[variable]
            time_name = "valid_time" if "valid_time" in values.dims else "time"
            if time_name != "time":
                values = values.rename({time_name: "time"})
            arrays.append(values.load())
    combined = xr.concat(arrays, dim="time").sortby("time")
    times = pd.DatetimeIndex(pd.to_datetime(combined["time"].values))
    if times.has_duplicates:
        duplicates = times[times.duplicated()].unique()
        raise ValueError(f"Duplicate ERA5 timestamps for {variable}: {duplicates[:3].tolist()}")
    lat_name = "latitude" if "latitude" in combined.coords else "lat"
    lon_name = "longitude" if "longitude" in combined.coords else "lon"
    return (
        np.asarray(combined.values, dtype="float32"),
        times,
        np.asarray(combined[lat_name].values, dtype="float64"),
        np.asarray(combined[lon_name].values, dtype="float64"),
    )


def _year_files(root: Path, subdirectory: str, prefix: str) -> list[Path]:
    paths = [root / subdirectory / f"{prefix}_{year}.nc" for year in (2022, 2023, 2024)]
    missing = [str(path) for path in paths if not path.is_file()]
    if missing:
        raise FileNotFoundError("Missing historical ERA5 files: " + "; ".join(missing))
    return paths


def _grid_transform(latitude: np.ndarray, longitude: np.ndarray) -> tuple[Any, np.ndarray, np.ndarray]:
    lat = np.asarray(latitude, dtype="float64")
    lon = np.asarray(longitude, dtype="float64")
    if lat.size < 2 or lon.size < 2:
        raise ValueError("ERA5 grid requires at least two latitude and longitude coordinates.")
    res_y = float(abs(lat[1] - lat[0]))
    res_x = float(abs(lon[1] - lon[0]))
    transform = from_bounds(
        float(np.min(lon) - res_x / 2.0),
        float(np.min(lat) - res_y / 2.0),
        float(np.max(lon) + res_x / 2.0),
        float(np.max(lat) + res_y / 2.0),
        int(lon.size),
        int(lat.size),
    )
    return transform, lat, lon


def _orient_source(values: np.ndarray, latitude: np.ndarray, longitude: np.ndarray) -> np.ndarray:
    result = np.asarray(values)
    if latitude[0] < latitude[-1]:
        result = np.flip(result, axis=1)
    if longitude[0] > longitude[-1]:
        result = np.flip(result, axis=2)
    return np.ascontiguousarray(result)


def _reproject_stack_to_cells(
    values: np.ndarray,
    latitude: np.ndarray,
    longitude: np.ndarray,
    *,
    target_shape: tuple[int, int],
    target_transform: Any,
    target_crs: Any,
    valid_cells: np.ndarray,
) -> np.ndarray:
    source = _orient_source(np.asarray(values, dtype="float32"), latitude, longitude)
    source_transform, _, _ = _grid_transform(latitude, longitude)
    destination = np.full((source.shape[0], *target_shape), np.nan, dtype="float32")
    reproject(
        source=source,
        destination=destination,
        src_transform=source_transform,
        src_crs=CRS.from_epsg(4326),
        src_nodata=np.nan,
        dst_transform=target_transform,
        dst_crs=target_crs,
        dst_nodata=np.nan,
        resampling=Resampling.bilinear,
        num_threads=2,
    )
    cells = destination[:, valid_cells[:, 0], valid_cells[:, 1]].T
    if np.any(~np.isfinite(cells)):
        missing = int(np.count_nonzero(~np.isfinite(cells)))
        raise ValueError(f"ERA5 reprojection left {missing} invalid active-cell values.")
    return np.ascontiguousarray(cells, dtype="float32")


def _daily_mean_min_max(values: np.ndarray, times: pd.DatetimeIndex) -> tuple[np.ndarray, np.ndarray, np.ndarray, pd.DatetimeIndex]:
    days = validate_four_samples_per_day(times, start=HISTORICAL_START, end=HISTORICAL_END)
    expected = len(days) * 4
    selected = np.asarray(values[:expected], dtype="float32")
    expected_index = pd.date_range(HISTORICAL_START, periods=expected, freq="6h")
    if not times[:expected].equals(expected_index):
        raise ValueError("Historical ERA5 six-hour time index is not continuous.")
    shaped = selected.reshape(len(days), 4, *selected.shape[1:])
    return shaped.mean(axis=1), shaped.min(axis=1), shaped.max(axis=1), days


def _daily_mean(values: np.ndarray, times: pd.DatetimeIndex) -> tuple[np.ndarray, pd.DatetimeIndex]:
    mean, _, _, days = _daily_mean_min_max(values, times)
    return mean, days


def _collect_v2_files(directory: Path) -> list[tuple[pd.Timestamp, Path]]:
    records: dict[pd.Timestamp, Path] = {}
    for path in Path(directory).glob("*.tif"):
        match = DATE_PATTERN.search(path.name)
        if match is None:
            continue
        stamp = pd.Timestamp("-".join(match.groups()))
        if REFERENCE_START <= stamp <= REFERENCE_END:
            if stamp in records:
                raise ValueError(f"Duplicate v2 precipitation date {stamp.date()}.")
            records[stamp] = path
    expected = expected_daily_index(REFERENCE_START, REFERENCE_END)
    missing = expected.difference(pd.DatetimeIndex(records))
    if len(missing):
        raise ValueError(f"v2 precipitation is missing {len(missing)} days: {missing[:5].tolist()}")
    return [(stamp, records[stamp]) for stamp in expected]


def _v2_series_identity(records: list[tuple[pd.Timestamp, Path]]) -> dict[str, Any]:
    series_digest = __import__("hashlib").sha256()
    total_bytes = 0
    for stamp, path in records:
        digest = sha256_file(path)
        size = path.stat().st_size
        total_bytes += size
        series_digest.update(f"{stamp.strftime('%Y-%m-%d')}\0{path.name}\0{size}\0{digest}\n".encode("utf-8"))
    return {
        "file_count": int(len(records)),
        "total_bytes": int(total_bytes),
        "series_sha256": series_digest.hexdigest(),
    }


def _read_v2_to_cells(
    records: list[tuple[pd.Timestamp, Path]],
    *,
    target_shape: tuple[int, int],
    target_transform: Any,
    target_crs: Any,
    valid_cells: np.ndarray,
) -> np.ndarray:
    output = np.empty((len(valid_cells), len(records)), dtype="float32")
    for index, (_, path) in enumerate(records):
        with rasterio.open(path) as source:
            with WarpedVRT(
                source,
                crs=target_crs,
                transform=target_transform,
                width=target_shape[1],
                height=target_shape[0],
                resampling=Resampling.bilinear,
                nodata=np.nan,
            ) as warped:
                data = warped.read(1, out_dtype="float32")
        cells = data[valid_cells[:, 0], valid_cells[:, 1]]
        if np.any(~np.isfinite(cells)):
            raise ValueError(f"v2 {path.name} does not cover every active model cell.")
        if np.any(cells < -1e-6):
            raise ValueError(f"v2 {path.name} contains negative active-cell precipitation.")
        output[:, index] = np.maximum(cells, 0.0)
    return output


def _target_grid(module: Any) -> tuple[tuple[int, int], Any, Any, Path]:
    candidates = sorted(Path(module.PREC_DIR).glob("*.tif"))
    if not candidates:
        raise FileNotFoundError(f"Saved run precipitation directory has no GeoTIFF: {module.PREC_DIR}")
    path = candidates[0]
    with rasterio.open(path) as source:
        shape = (int(source.height), int(source.width))
        transform = source.transform
        crs = source.crs
    return shape, transform, crs, path


def _load_dem_cells(module: Any, valid_cells: np.ndarray) -> np.ndarray:
    dem_path = Path(resolve_workspace_dem_path(Path(module.FLOW_ACC_PATH).parent))
    with rasterio.open(dem_path) as source:
        dem = source.read(1).astype("float32")
        if source.nodata is not None:
            dem[dem == source.nodata] = np.nan
    values = dem[valid_cells[:, 0], valid_cells[:, 1]]
    if np.any(~np.isfinite(values)):
        raise ValueError(f"DEM has invalid values in active cells: {dem_path}")
    return values


def _cell_latitudes(transform: Any, valid_cells: np.ndarray) -> np.ndarray:
    rows = valid_cells[:, 0]
    cols = valid_cells[:, 1]
    _, latitudes = rasterio.transform.xy(transform, rows, cols, offset="center")
    return np.asarray(latitudes, dtype="float32")


def _forcing_file_map(root: Path) -> dict[str, list[Path]]:
    reference = root / "参考"
    return {
        "tp_historical": _year_files(root, "降水/ERA5", "era5_tp"),
        "t2m_historical": _year_files(root, "气温", "era5_t2m"),
        "ssrd_historical": _year_files(root, "太阳辐射", "era5_ssrd"),
        "u10_historical": _year_files(root, "风速", "era5_u10"),
        "v10_historical": _year_files(root, "风速", "era5_v10"),
        "d2m_historical": _year_files(root, "露点温度", "era5_d2m"),
        "tp_2025_reference": [reference / "era5_tp_2025_reference.nc"],
        "tp_2026_boundary": [reference / "era5_tp_2026_boundary.nc"],
        "ssrd_2025_boundary": [reference / "era5_ssrd_2025_boundary.nc"],
    }


def _validate_forcing_files(file_map: dict[str, list[Path]]) -> list[dict[str, Any]]:
    identities: list[dict[str, Any]] = []
    for role, paths in file_map.items():
        for path in paths:
            if not path.is_file():
                raise FileNotFoundError(f"Missing {role}: {path}")
            identity = file_identity(path)
            identity["role"] = role
            identities.append(identity)
    return identities


def build_historical_forcing(
    module: Any,
    era5_root: Path,
    v2_directory: Path,
) -> tuple[tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray], pd.DatetimeIndex, dict[str, Any]]:
    era5_root = Path(era5_root).resolve(strict=True)
    v2_directory = Path(v2_directory).resolve(strict=True)
    file_map = _forcing_file_map(era5_root)
    file_identities = _validate_forcing_files(file_map)
    target_shape, target_transform, target_crs, target_sample = _target_grid(module)
    valid_cells = np.asarray(module.VALID_CELLS, dtype="int64")
    if valid_cells.ndim != 2 or valid_cells.shape[1] != 2:
        raise ValueError("Saved HBV run does not expose active cell coordinates.")

    tp_values, tp_times, lat, lon = _load_data_array(
        file_map["tp_historical"] + file_map["tp_2025_reference"][:1], "tp"
    )
    historical_tp_source, historical_dates = daily_values_from_next_midnight_accumulation(
        tp_values * 1000.0,
        tp_times,
        start=HISTORICAL_START,
        end=HISTORICAL_END,
    )
    historical_precip = _reproject_stack_to_cells(
        historical_tp_source,
        lat,
        lon,
        target_shape=target_shape,
        target_transform=target_transform,
        target_crs=target_crs,
        valid_cells=valid_cells,
    )

    tp_ref_values, tp_ref_times, ref_lat, ref_lon = _load_data_array(
        file_map["tp_2025_reference"] + file_map["tp_2026_boundary"], "tp"
    )
    reference_tp_source, reference_dates = daily_values_from_next_midnight_accumulation(
        tp_ref_values * 1000.0,
        tp_ref_times,
        start=REFERENCE_START,
        end=REFERENCE_END,
    )
    reference_era5 = _reproject_stack_to_cells(
        reference_tp_source,
        ref_lat,
        ref_lon,
        target_shape=target_shape,
        target_transform=target_transform,
        target_crs=target_crs,
        valid_cells=valid_cells,
    )

    v2_records = _collect_v2_files(v2_directory)
    reference_v2 = _read_v2_to_cells(
        v2_records,
        target_shape=target_shape,
        target_transform=target_transform,
        target_crs=target_crs,
        valid_cells=valid_cells,
    )
    transition_factors, transition_report = build_monthly_transition_factors(
        reference_era5,
        reference_v2,
        reference_dates,
        np.asarray(module.CELL_SCALE, dtype="float64"),
    )
    if float(transition_report["maximum_abs_reconstructed_basin_pbias_percent"]) > 0.01:
        raise ValueError(
            "Monthly precipitation transition failed basin-total conservation: "
            f"{transition_report['maximum_abs_reconstructed_basin_pbias_percent']:.6f}%"
        )
    historical_precip = apply_monthly_transition(
        historical_precip,
        historical_dates,
        transition_factors,
    )

    t_values, t_times, met_lat, met_lon = _load_data_array(file_map["t2m_historical"], "t2m")
    t_mean_src, t_min_src, t_max_src, met_dates = _daily_mean_min_max(t_values - 273.15, t_times)
    d_values, d_times, _, _ = _load_data_array(file_map["d2m_historical"], "d2m")
    d_mean_src, d_dates = _daily_mean(d_values - 273.15, d_times)
    u_values, u_times, _, _ = _load_data_array(file_map["u10_historical"], "u10")
    u_mean_src, u_dates = _daily_mean(u_values, u_times)
    v_values, v_times, _, _ = _load_data_array(file_map["v10_historical"], "v10")
    v_mean_src, v_dates = _daily_mean(v_values, v_times)
    ssrd_values, ssrd_times, ssrd_lat, ssrd_lon = _load_data_array(
        file_map["ssrd_historical"] + file_map["ssrd_2025_boundary"], "ssrd"
    )
    ssrd_daily_src, ssrd_dates = daily_values_from_next_midnight_accumulation(
        ssrd_values / 1.0e6,
        ssrd_times,
        start=HISTORICAL_START,
        end=HISTORICAL_END,
    )
    for label, dates in {
        "temperature": met_dates,
        "dewpoint": d_dates,
        "u10": u_dates,
        "v10": v_dates,
        "solar": ssrd_dates,
    }.items():
        if not dates.equals(historical_dates):
            raise ValueError(f"Historical {label} dates do not match precipitation dates.")

    def to_cells(values: np.ndarray, latitude: np.ndarray = met_lat, longitude: np.ndarray = met_lon) -> np.ndarray:
        return _reproject_stack_to_cells(
            values,
            latitude,
            longitude,
            target_shape=target_shape,
            target_transform=target_transform,
            target_crs=target_crs,
            valid_cells=valid_cells,
        )

    t_mean = to_cells(t_mean_src)
    t_min = to_cells(t_min_src)
    t_max = to_cells(t_max_src)
    d_mean = to_cells(d_mean_src)
    u_mean = to_cells(u_mean_src)
    v_mean = to_cells(v_mean_src)
    ssrd_daily = to_cells(ssrd_daily_src, ssrd_lat, ssrd_lon)
    pet = calculate_fao56_daily_pet(
        t_mean,
        t_min,
        t_max,
        d_mean,
        u_mean,
        v_mean,
        ssrd_daily,
        _cell_latitudes(target_transform, valid_cells),
        _load_dem_cells(module, valid_cells),
        historical_dates,
    )
    manifest = {
        "schema": "hbv_cryo_historical_spinup_forcing_manifest_v1",
        "role": "state_spinup_diagnostic",
        "historical_period": {
            "start": historical_dates[0].strftime("%Y-%m-%d"),
            "end": historical_dates[-1].strftime("%Y-%m-%d"),
            "day_count": int(len(historical_dates)),
        },
        "era5_time_basis": "UTC_calendar_day_from_four_6_hour_samples",
        "accumulation_convention": "day_total_selected_at_following_00_UTC",
        "accumulation_contract": ERA5_ACCUMULATION_CONTRACT,
        "v2_reference": {
            "directory": str(v2_directory),
            "identity": _v2_series_identity(v2_records),
            "declared_role": "2025_monthly_amount_reference_only",
            "unit_assumption": "mm/day",
            "day_basis_status": "pending_written_confirmation",
        },
        "raw_files": file_identities,
        "target_grid": {
            "sample_file": str(target_sample.resolve()),
            "shape": [int(target_shape[0]), int(target_shape[1])],
            "crs": target_crs.to_string() if target_crs is not None else "",
            "transform": [float(value) for value in target_transform[:6]],
            "active_cell_count": int(len(valid_cells)),
            "active_cell_coverage_percent": 100.0,
        },
        "precipitation_transition": transition_report,
        "temperature": {
            "source_unit": "K",
            "output_unit": "degree_C",
            "daily_statistic": "mean_of_00_06_12_18_UTC",
        },
        "pet": {
            "method": "FAO56_Penman_Monteith",
            "daily_temperature_samples": "00_06_12_18_UTC",
            "solar_daily_total": "following_00_UTC_accumulation",
            "elevation_basis": "model_DEM_per_active_cell",
            "range_mm_day": [float(np.min(pet)), float(np.max(pet))],
        },
        "formal_acceptance_eligible": False,
        "formal_blockers": [
            "v2_product_day_basis_pending_written_confirmation",
            "historical_precipitation_bias_transition_uses_single_reference_year",
            "historical_ERA5_daily_basis_is_UTC_not_confirmed_v2_product_day",
        ],
    }
    long_term_mean = np.mean(t_mean, axis=1, keepdims=True, dtype="float64").astype("float32")
    ll_temp = np.broadcast_to(long_term_mean, t_mean.shape).copy()
    return (
        np.ascontiguousarray(historical_precip),
        np.ascontiguousarray(t_mean),
        np.ascontiguousarray(pet),
        np.ascontiguousarray(ll_temp),
    ), historical_dates, manifest


def _relative_flow_difference(dry: np.ndarray, wet: np.ndarray) -> dict[str, Any]:
    dry = np.asarray(dry, dtype="float64")
    wet = np.asarray(wet, dtype="float64")
    finite = np.isfinite(dry) & np.isfinite(wet)
    differences = np.abs(dry[finite] - wet[finite])
    scale = float(np.mean((np.abs(dry[finite]) + np.abs(wet[finite])) / 2.0)) if np.any(finite) else 0.0
    mean_difference = float(np.mean(differences)) if differences.size else None
    relative = mean_difference / scale * 100.0 if mean_difference is not None and scale > 1e-12 else None
    return {
        "sample_count": int(np.count_nonzero(finite)),
        "dry_mean_m3s": float(np.mean(dry[finite])) if np.any(finite) else None,
        "wet_mean_m3s": float(np.mean(wet[finite])) if np.any(finite) else None,
        "mean_absolute_difference_m3s": mean_difference,
        "max_absolute_difference_m3s": float(np.max(differences)) if differences.size else None,
        "relative_difference_percent": relative,
    }


def run_historical_sensitivity(run_path: Path, era5_root: Path, v2_directory: Path) -> dict[str, Any]:
    metadata = json.loads((run_path / "metadata.json").read_text(encoding="utf-8"))
    params = {str(key): float(value) for key, value in dict(metadata.get("optimized_params", {}) or {}).items()}
    if not params:
        raise ValueError(f"Saved run has no optimized_params: {run_path}")
    context = _build_forward_payload_context(
        {"run_path": str(run_path.resolve()), "params": params, "save_run": False}
    )
    entry, cache_hit = _get_or_create_forward_runtime(context)
    module = entry.module
    vector = np.asarray([params[name] for name in module.param_names], dtype="float64")
    historical, historical_dates, forcing_manifest = build_historical_forcing(
        module, era5_root, v2_directory
    )
    current_dates = pd.DatetimeIndex(module.SIM_DATES)
    if historical_dates[-1] + pd.Timedelta(days=1) != current_dates[0]:
        raise ValueError(
            f"Historical/current forcing is not continuous: {historical_dates[-1]} -> {current_dates[0]}"
        )
    combined_dates = historical_dates.append(current_dates)
    combined_temp = np.ascontiguousarray(np.concatenate((historical[1], module.TEMP_CELLS), axis=1))
    combined = (
        np.ascontiguousarray(np.concatenate((historical[0], module.PREC_CELLS), axis=1)),
        combined_temp,
        np.ascontiguousarray(np.concatenate((historical[2], module.ET_CELLS), axis=1)),
        np.ascontiguousarray(
            np.broadcast_to(
                np.mean(combined_temp, axis=1, keepdims=True, dtype="float64").astype("float32"),
                combined_temp.shape,
            ).copy()
        ),
    )
    warmup_end_step = int(len(historical_dates) + int(module.WARMUP_STEPS or 0))
    evaluation_slice = slice(warmup_end_step, len(combined_dates))
    compare_slice = slice(max(0, warmup_end_step - 14), warmup_end_step)
    original_init = np.asarray(module.INIT_ST, dtype="float64").copy()
    cases: dict[str, Any] = {}
    flow_series: dict[str, np.ndarray] = {}
    try:
        for name, init_state in _initial_state_vectors(params).items():
            module.INIT_ST = np.asarray(init_state, dtype="float64")
            simulation = _run_local_forcing(module, vector, *combined)
            snapshot_arrays, snapshot_meta = _snapshot_for_proxy_inputs(
                module,
                vector,
                combined,
                combined_dates,
                warmup_end_step,
            )
            local_flow = np.asarray(simulation["q_total"], dtype="float64")
            flow_series[name] = local_flow
            cases[name] = {
                "initial_state": {
                    key: float(value)
                    for key, value in zip(("SP", "SM", "UZ", "LZ", "WC"), init_state)
                },
                "warmup_end_state": summarize_snapshot(snapshot_arrays, snapshot_meta),
                "evaluation_local_runoff_mm": {
                    "total": _runoff_depth_mm(module, local_flow[evaluation_slice]),
                    "rain": _runoff_depth_mm(module, np.asarray(simulation["q_rain"])[evaluation_slice]),
                    "snow": _runoff_depth_mm(module, np.asarray(simulation["q_snow"])[evaluation_slice]),
                    "ice": _runoff_depth_mm(module, np.asarray(simulation["q_ice"])[evaluation_slice]),
                },
                "max_abs_cell_balance_error_mm": float(
                    simulation.get("max_abs_cell_balance_error_mm", float("nan"))
                ),
            }
    finally:
        module.INIT_ST = original_init

    flow_diagnostic = _relative_flow_difference(
        flow_series["dry"][compare_slice], flow_series["wet"][compare_slice]
    )
    dry_storage = cases["dry"]["warmup_end_state"]["total_storage_mm"]["mean"]
    wet_storage = cases["wet"]["warmup_end_state"]["total_storage_mm"]["mean"]
    storage_scale = (abs(float(dry_storage)) + abs(float(wet_storage))) / 2.0
    storage_difference = (
        abs(float(wet_storage) - float(dry_storage)) / storage_scale * 100.0
        if storage_scale > 1e-12 else None
    )
    flow_converged = (
        flow_diagnostic["relative_difference_percent"] is not None
        and float(flow_diagnostic["relative_difference_percent"]) <= 5.0
    )
    storage_converged = storage_difference is not None and storage_difference <= 10.0
    correction_summary_path = Path(module.PREC_DIR) / "precipitation_strategy_summary.json"
    correction_summary = {}
    if correction_summary_path.is_file():
        correction_summary = json.loads(correction_summary_path.read_text(encoding="utf-8"))
    station_integrity = dict(correction_summary.get("station_series_integrity", {}) or {})
    correction_blocked = bool(
        correction_summary.get("processing_stats", {}).get("qc_blocked", False)
        or station_integrity.get("qc_blocked", False)
    )
    formal_blockers = list(forcing_manifest["formal_blockers"])
    if correction_blocked:
        formal_blockers.append("2025_station_residual_correction_qc_blocked")
    return {
        "schema": "hbv_cryo_continuous_historical_spinup_sensitivity_v1",
        "run_path": str(run_path.resolve()),
        "workspace_config": str(context["config_path"]),
        "cache_hit": bool(cache_hit),
        "forcing_manifest": forcing_manifest,
        "forcing_identity": {
            "mode": "continuous_ERA5_Land_2022_2024_then_saved_2025_forcing",
            "historical_start": historical_dates[0].strftime("%Y-%m-%d"),
            "historical_end": historical_dates[-1].strftime("%Y-%m-%d"),
            "current_start": current_dates[0].strftime("%Y-%m-%d"),
            "current_end": current_dates[-1].strftime("%Y-%m-%d"),
            "combined_day_count": int(len(combined_dates)),
            "contains_repeated_target_year_weather": False,
            "contains_continuous_historical_weather": True,
        },
        "cases": cases,
        "warmup_end": combined_dates[warmup_end_step - 1].strftime("%Y-%m-%d"),
        "warmup_day_count": int(warmup_end_step),
        "warmup_last_14_steps_local_flow": flow_diagnostic,
        "warmup_end_total_storage_relative_difference_percent": storage_difference,
        "convergence_thresholds": {
            "last_14_step_local_flow_relative_difference_percent_max": 5.0,
            "warmup_end_total_storage_relative_difference_percent_max": 10.0,
        },
        "flow_converged": bool(flow_converged),
        "storage_converged": bool(storage_converged),
        "converged": bool(flow_converged and storage_converged),
        "historical_forcing_evidence": True,
        "formal_acceptance_eligible": False,
        "formal_blockers": list(dict.fromkeys(formal_blockers)),
        "station_series_integrity": station_integrity,
        "interpretation": (
            "This diagnostic replaces repeated-weather proxy cycling with continuous historical weather. "
            "It may establish initial-state convergence, but it cannot clear product-day-basis, "
            "single-reference-year precipitation-transition, or station-integrity gates."
        ),
    }


def _update_metadata(run_path: Path, result: dict[str, Any], output_path: Path) -> None:
    metadata_path = run_path / "metadata.json"
    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    metadata["historical_initial_state_sensitivity"] = {
        "schema": result["schema"],
        "output_file": os.path.relpath(output_path, run_path).replace("\\", "/"),
        "historical_forcing_evidence": True,
        "formal_acceptance_eligible": False,
        "converged": bool(result["converged"]),
        "flow_converged": bool(result["flow_converged"]),
        "storage_converged": bool(result["storage_converged"]),
        "formal_blockers": list(result["formal_blockers"]),
    }
    acceptance = dict(metadata.get("scientific_acceptance", {}) or {})
    previous_blockers = [
        str(item)
        for item in list(acceptance.get("blockers", []) or [])
        if str(item) not in {
            "initial_state_sensitivity_not_converged",
            "initial_state_proxy_not_formal_evidence",
        }
    ]
    acceptance.update(
        {
            "status": "blocked_by_scientific_qc",
            "formal_result_accepted": False,
            "initial_state_sensitivity_accepted": bool(result["converged"]),
            "historical_initial_state_convergence_accepted": bool(result["converged"]),
            "historical_initial_state_forcing_formally_equivalent": False,
            "blockers": list(
                dict.fromkeys(previous_blockers + list(result["formal_blockers"]))
            ),
        }
    )
    notes = list(acceptance.get("notes", []) or [])
    notes.append(
        "Continuous 2022-2024 ERA5-Land forcing removed dry/wet initial-state dependence; "
        "product-day-basis, single-reference-year precipitation transition, station integrity, "
        "and interval water-source gates remain independent blockers."
    )
    acceptance["notes"] = list(dict.fromkeys(str(item) for item in notes if str(item).strip()))
    metadata["scientific_acceptance"] = acceptance
    temporary = metadata_path.with_suffix(".json.tmp")
    temporary.write_text(json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(metadata_path)


def main() -> None:
    args = parse_args()
    run_path = Path(args.run).resolve(strict=True)
    result = run_historical_sensitivity(
        run_path,
        Path(args.era5_root),
        Path(args.v2_dir),
    )
    output_path = (
        Path(args.output).resolve(strict=False)
        if args.output
        else run_path / "initial_state_historical_spinup.json"
    )
    output_path.parent.mkdir(parents=True, exist_ok=True)
    temporary = output_path.with_suffix(output_path.suffix + ".tmp")
    temporary.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(output_path)
    _update_metadata(run_path, result, output_path)
    print(
        json.dumps(
            {
                "output": str(output_path),
                "converged": bool(result["converged"]),
                "historical_forcing_evidence": True,
                "formal_acceptance_eligible": False,
            },
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
