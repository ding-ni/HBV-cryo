from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd


def sha256_file(path: Path, *, chunk_size: int = 1024 * 1024) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        while True:
            chunk = handle.read(chunk_size)
            if not chunk:
                break
            digest.update(chunk)
    return digest.hexdigest()


def file_identity(path: Path) -> dict[str, Any]:
    source = Path(path).resolve(strict=True)
    stat = source.stat()
    return {
        "path": str(source),
        "size_bytes": int(stat.st_size),
        "sha256": sha256_file(source),
    }


def expected_daily_index(start: Any, end: Any) -> pd.DatetimeIndex:
    return pd.date_range(pd.Timestamp(start).normalize(), pd.Timestamp(end).normalize(), freq="1D")


def daily_values_from_next_midnight_accumulation(
    values: np.ndarray,
    times: Any,
    *,
    start: Any,
    end: Any,
) -> tuple[np.ndarray, pd.DatetimeIndex]:
    """Select each day's accumulated value stored at the following 00:00 timestamp."""
    index = pd.DatetimeIndex(pd.to_datetime(times))
    raw = np.asarray(values)
    if raw.shape[0] != len(index):
        raise ValueError(f"Accumulation time axis mismatch: {raw.shape[0]} != {len(index)}")
    if index.has_duplicates:
        duplicates = index[index.duplicated()].unique()
        raise ValueError(f"Accumulation input contains duplicate timestamps: {duplicates[:3].tolist()}")
    if not index.is_monotonic_increasing:
        order = np.argsort(index.values)
        index = index[order]
        raw = raw[order]

    days = expected_daily_index(start, end)
    target_times = days + pd.Timedelta(days=1)
    positions = index.get_indexer(target_times)
    missing = np.flatnonzero(positions < 0)
    if missing.size:
        samples = [target_times[int(item)].isoformat() for item in missing[:5]]
        raise ValueError(
            "Accumulated daily forcing requires the next-day 00:00 boundary; "
            f"missing {int(missing.size)} timestamps, for example {samples}."
        )
    selected = raw[positions]
    if selected.shape[0] != len(days):
        raise ValueError("Daily accumulation selection produced an unexpected time dimension.")
    return selected, days


def validate_four_samples_per_day(times: Any, *, start: Any, end: Any) -> pd.DatetimeIndex:
    index = pd.DatetimeIndex(pd.to_datetime(times))
    days = expected_daily_index(start, end)
    selected = index[(index >= days[0]) & (index < days[-1] + pd.Timedelta(days=1))]
    counts = pd.Series(1, index=selected).resample("1D").sum().reindex(days, fill_value=0)
    bad = counts[counts != 4]
    if not bad.empty:
        samples = {stamp.strftime("%Y-%m-%d"): int(value) for stamp, value in bad.iloc[:5].items()}
        raise ValueError(f"Expected four ERA5 samples per UTC day; invalid days: {samples}")
    expected_hours = {0, 6, 12, 18}
    for day in days:
        actual = set(selected[selected.normalize() == day].hour.tolist())
        if actual != expected_hours:
            raise ValueError(f"Unexpected ERA5 hours on {day.date()}: {sorted(actual)}")
    return days


def build_monthly_transition_factors(
    era5_reference_mm: np.ndarray,
    v2_reference_mm: np.ndarray,
    dates: Any,
    cell_weights: np.ndarray,
    *,
    support_mm: float = 20.0,
    minimum_factor: float = 0.2,
    maximum_factor: float = 5.0,
) -> tuple[np.ndarray, dict[str, Any]]:
    """Build spatially shrunk factors while conserving each basin-month total.

    The bounds constrain each cell's multiplier relative to the basin monthly
    ratio. They are not absolute precipitation factors; an absolute 0.2 floor
    would substantially over-wet very dry alpine winter months.
    """
    era5 = np.asarray(era5_reference_mm, dtype="float64")
    v2 = np.asarray(v2_reference_mm, dtype="float64")
    index = pd.DatetimeIndex(pd.to_datetime(dates))
    weights = np.asarray(cell_weights, dtype="float64")
    if era5.shape != v2.shape:
        raise ValueError(f"Reference precipitation shapes differ: {era5.shape} != {v2.shape}")
    if era5.ndim != 2 or era5.shape[1] != len(index):
        raise ValueError("Reference precipitation must have shape (cell, day).")
    if weights.shape != (era5.shape[0],):
        raise ValueError("Cell weights do not match the precipitation cell axis.")
    if np.any(~np.isfinite(era5)) or np.any(~np.isfinite(v2)):
        raise ValueError("Reference precipitation contains non-finite values.")
    if np.any(era5 < -1e-9) or np.any(v2 < -1e-9):
        raise ValueError("Reference precipitation contains negative values.")
    if support_mm <= 0.0:
        raise ValueError("support_mm must be positive.")
    if not (0.0 < minimum_factor <= maximum_factor):
        raise ValueError("Invalid transition factor bounds.")

    weights = np.where(np.isfinite(weights) & (weights > 0.0), weights, 0.0)
    if float(weights.sum()) <= 0.0:
        raise ValueError("At least one positive cell weight is required.")
    weights = weights / float(weights.sum())
    factors = np.ones((era5.shape[0], 12), dtype="float64")
    reports: list[dict[str, Any]] = []

    for month in range(1, 13):
        month_mask = index.month == month
        if not np.any(month_mask):
            raise ValueError(f"Reference period does not contain month {month}.")
        era_total = np.sum(era5[:, month_mask], axis=1, dtype="float64")
        v2_total = np.sum(v2[:, month_mask], axis=1, dtype="float64")
        basin_era = float(np.sum(era_total * weights))
        basin_v2 = float(np.sum(v2_total * weights))
        if basin_era <= 1e-9:
            if basin_v2 > 1e-9:
                raise ValueError(f"ERA5 reference month {month} is dry while v2 has precipitation.")
            month_factor = np.ones_like(era_total)
            basin_ratio = 1.0
            spatial_multiplier = np.ones_like(era_total)
        elif basin_v2 <= 1e-12:
            basin_ratio = 0.0
            month_factor = np.zeros_like(era_total)
            spatial_multiplier = np.ones_like(era_total)
        else:
            basin_ratio = basin_v2 / basin_era
            raw_ratio = np.full_like(era_total, basin_ratio)
            supported = era_total > 1e-9
            raw_ratio[supported] = v2_total[supported] / era_total[supported]
            confidence = era_total / (era_total + float(support_mm))
            month_factor = confidence * raw_ratio + (1.0 - confidence) * basin_ratio
            spatial_multiplier = np.clip(
                month_factor / basin_ratio,
                minimum_factor,
                maximum_factor,
            )
            month_factor = basin_ratio * spatial_multiplier

            # The relative spatial bounds must not prevent basin-month amount conservation.
            reconstructed = float(np.sum(era_total * month_factor * weights))
            if reconstructed <= 1e-12:
                raise ValueError(f"Month {month} transition has no reconstructable ERA5 amount.")
            month_factor *= basin_v2 / reconstructed

        reconstructed_cells = era_total * month_factor
        reconstructed_basin = float(np.sum(reconstructed_cells * weights))
        basin_pbias = (
            (reconstructed_basin - basin_v2) / basin_v2 * 100.0
            if basin_v2 > 1e-12 else 0.0
        )
        raw_supported = era_total > 1e-9
        raw_ratios = np.full_like(era_total, np.nan)
        raw_ratios[raw_supported] = v2_total[raw_supported] / era_total[raw_supported]
        clipped = (
            (spatial_multiplier <= minimum_factor + 1e-12)
            | (spatial_multiplier >= maximum_factor - 1e-12)
        )
        zero_source_wet_target = (era_total <= 1e-9) & (v2_total > 1e-9)
        factors[:, month - 1] = month_factor
        reports.append(
            {
                "month": int(month),
                "era5_basin_mean_mm": basin_era,
                "v2_basin_mean_mm": basin_v2,
                "basin_ratio": float(basin_ratio),
                "factor_min": float(np.min(month_factor)),
                "factor_median": float(np.median(month_factor)),
                "factor_max": float(np.max(month_factor)),
                "spatial_multiplier_min": float(np.min(spatial_multiplier)),
                "spatial_multiplier_median": float(np.median(spatial_multiplier)),
                "spatial_multiplier_max": float(np.max(spatial_multiplier)),
                "raw_ratio_median": (
                    float(np.nanmedian(raw_ratios)) if np.any(raw_supported) else None
                ),
                "clipped_cell_count": int(np.count_nonzero(clipped)),
                "zero_era5_wet_v2_cell_count": int(np.count_nonzero(zero_source_wet_target)),
                "reconstructed_basin_mean_mm": reconstructed_basin,
                "reconstructed_basin_pbias_percent": float(basin_pbias),
            }
        )

    maximum_abs_pbias = max(abs(float(item["reconstructed_basin_pbias_percent"])) for item in reports)
    report = {
        "schema": "hbv_cryo_monthly_precipitation_transition_v1",
        "method": "spatial_ratio_shrinkage_with_basin_month_conservation",
        "reference_period": {
            "start": index[0].strftime("%Y-%m-%d"),
            "end": index[-1].strftime("%Y-%m-%d"),
            "day_count": int(len(index)),
        },
        "support_mm": float(support_mm),
        "minimum_spatial_multiplier_relative_to_basin_ratio": float(minimum_factor),
        "maximum_spatial_multiplier_relative_to_basin_ratio": float(maximum_factor),
        "months": reports,
        "maximum_abs_reconstructed_basin_pbias_percent": float(maximum_abs_pbias),
        "preserves_era5_daily_occurrence": True,
        "uses_single_reference_year": True,
        "formal_climatological_bias_product": False,
    }
    return factors.astype("float32"), report


def apply_monthly_transition(
    precipitation_mm: np.ndarray,
    dates: Any,
    factors: np.ndarray,
) -> np.ndarray:
    values = np.asarray(precipitation_mm, dtype="float64")
    index = pd.DatetimeIndex(pd.to_datetime(dates))
    transition = np.asarray(factors, dtype="float64")
    if values.ndim != 2 or values.shape[1] != len(index):
        raise ValueError("Historical precipitation must have shape (cell, day).")
    if transition.shape != (values.shape[0], 12):
        raise ValueError("Monthly transition factors must have shape (cell, 12).")
    month_columns = transition[:, index.month.to_numpy() - 1]
    corrected = values * month_columns
    if np.any(~np.isfinite(corrected)) or np.any(corrected < -1e-9):
        raise ValueError("Monthly transition produced invalid precipitation values.")
    return np.maximum(corrected, 0.0).astype("float32")


def calculate_fao56_daily_pet(
    t_mean_c: np.ndarray,
    t_min_c: np.ndarray,
    t_max_c: np.ndarray,
    dewpoint_mean_c: np.ndarray,
    u10_mean_ms: np.ndarray,
    v10_mean_ms: np.ndarray,
    solar_radiation_mj_m2_day: np.ndarray,
    latitude_degrees: np.ndarray,
    elevation_m: np.ndarray,
    dates: Any,
) -> np.ndarray:
    """Calculate daily FAO-56 reference ET with cell-specific elevation."""
    t_mean = np.asarray(t_mean_c, dtype="float64")
    t_min = np.asarray(t_min_c, dtype="float64")
    t_max = np.asarray(t_max_c, dtype="float64")
    dewpoint = np.asarray(dewpoint_mean_c, dtype="float64")
    u10 = np.asarray(u10_mean_ms, dtype="float64")
    v10 = np.asarray(v10_mean_ms, dtype="float64")
    radiation = np.asarray(solar_radiation_mj_m2_day, dtype="float64")
    arrays = (t_mean, t_min, t_max, dewpoint, u10, v10, radiation)
    if any(item.shape != t_mean.shape for item in arrays[1:]):
        raise ValueError("FAO56 meteorological arrays must have identical shapes.")
    if t_mean.ndim != 2:
        raise ValueError("FAO56 arrays must have shape (cell, day).")
    index = pd.DatetimeIndex(pd.to_datetime(dates))
    if t_mean.shape[1] != len(index):
        raise ValueError("FAO56 date count does not match the meteorological arrays.")
    lat = np.asarray(latitude_degrees, dtype="float64")
    elevation = np.asarray(elevation_m, dtype="float64")
    if lat.shape != (t_mean.shape[0],) or elevation.shape != (t_mean.shape[0],):
        raise ValueError("FAO56 latitude and elevation must have one value per cell.")
    if any(np.any(~np.isfinite(item)) for item in arrays):
        raise ValueError("FAO56 meteorological arrays contain non-finite values.")
    if np.any(~np.isfinite(lat)) or np.any(~np.isfinite(elevation)):
        raise ValueError("FAO56 latitude or elevation contains non-finite values.")

    pressure = 101.3 * ((293.0 - 0.0065 * elevation[:, None]) / 293.0) ** 5.26
    gamma = 0.000665 * pressure
    es_tmax = 0.6108 * np.exp(17.27 * t_max / (t_max + 237.3))
    es_tmin = 0.6108 * np.exp(17.27 * t_min / (t_min + 237.3))
    es = (es_tmax + es_tmin) / 2.0
    ea = 0.6108 * np.exp(17.27 * dewpoint / (dewpoint + 237.3))
    ea = np.minimum(np.maximum(ea, 0.0), es)
    delta = (
        4098.0
        * (0.6108 * np.exp(17.27 * t_mean / (t_mean + 237.3)))
        / (t_mean + 237.3) ** 2
    )

    day_of_year = index.dayofyear.to_numpy(dtype="float64")[None, :]
    dr = 1.0 + 0.033 * np.cos(2.0 * np.pi * day_of_year / 365.0)
    solar_declination = 0.409 * np.sin(2.0 * np.pi * day_of_year / 365.0 - 1.39)
    latitude_radians = np.deg2rad(lat)[:, None]
    sunset_argument = -np.tan(latitude_radians) * np.tan(solar_declination)
    sunset_hour_angle = np.arccos(np.clip(sunset_argument, -1.0, 1.0))
    extraterrestrial = (
        (24.0 * 60.0 / np.pi)
        * 0.0820
        * dr
        * (
            sunset_hour_angle * np.sin(latitude_radians) * np.sin(solar_declination)
            + np.cos(latitude_radians)
            * np.cos(solar_declination)
            * np.sin(sunset_hour_angle)
        )
    )
    extraterrestrial = np.maximum(extraterrestrial, 0.0)
    clear_sky = (0.75 + 0.00002 * elevation[:, None]) * extraterrestrial
    radiation = np.maximum(radiation, 0.0)
    net_shortwave = 0.77 * radiation
    cloud_ratio = np.clip(radiation / np.maximum(clear_sky, 0.01), 0.0, 1.0)
    net_longwave = (
        4.903e-9
        * ((t_max + 273.16) ** 4 + (t_min + 273.16) ** 4)
        / 2.0
        * (0.34 - 0.14 * np.sqrt(np.maximum(ea, 0.0)))
        * (1.35 * cloud_ratio - 0.35)
    )
    net_radiation = net_shortwave - net_longwave
    wind_10m = np.sqrt(u10 * u10 + v10 * v10)
    wind_2m = wind_10m * 4.87 / np.log(67.8 * 10.0 - 5.42)
    vapour_deficit = np.maximum(es - ea, 0.0)
    numerator = (
        0.408 * delta * net_radiation
        + gamma * 900.0 / np.maximum(t_mean + 273.0, 1.0) * wind_2m * vapour_deficit
    )
    denominator = delta + gamma * (1.0 + 0.34 * wind_2m)
    pet = np.divide(numerator, denominator, out=np.zeros_like(numerator), where=denominator > 0.0)
    pet = np.clip(pet, 0.0, 15.0)
    if np.any(~np.isfinite(pet)):
        raise ValueError("FAO56 calculation produced non-finite PET values.")
    return pet.astype("float32")
