from __future__ import annotations

import copy
import math
from typing import Any

import numpy as np
import pandas as pd


OBJECTIVE_FAMILY = "daily_unified_professional_v1"
EPS = 1e-12
NONFLOW_CAP = 0.35
ICE_DOMINANCE_GUARD_WEIGHT = 3.0
ICE_DOMINANCE_BINARY_DEFAULT_UPPER = 0.30
ICE_DOMINANCE_BINARY_MIN_UPPER = 0.30
ICE_DOMINANCE_BINARY_MAX_UPPER = 0.45
ICE_DOMINANCE_BINARY_WINDOW_FACTOR = 1.20
ICE_DOMINANCE_BINARY_TOLERANCE = 0.05
ICE_DOMINANCE_FRACTIONAL_MIN_UPPER = 0.20
ICE_DOMINANCE_FRACTIONAL_MAX_UPPER = 0.85
ICE_DOMINANCE_FRACTIONAL_WINDOW_FACTOR = 1.25
ICE_DOMINANCE_FRACTIONAL_MIN_TOLERANCE = 0.05
ICE_DOMINANCE_FRACTIONAL_TOLERANCE_RATIO = 0.15
PEAK_SOURCE_GUARD_WEIGHT = 0.10
PEAK_SOURCE_ICE_DOMINANCE_THRESHOLD = 0.50
PEAK_SOURCE_NO_EVIDENCE_THRESHOLD = 0.60
PEAK_SOURCE_SMALL_GLACIER_AREA = 0.10
PEAK_SOURCE_LATE_MELT_MONTHS = (7, 8, 9)
RECESSION_TAKEOVER_WINDOW_DAYS = 30
RECESSION_TAKEOVER_CONSECUTIVE_DAYS = 12
RECESSION_TAKEOVER_MEAN_FRACTION = 0.55

FLOW_GUARD_CONFIG = {
    "nse_cal": {"threshold": 0.60, "tolerance": 0.20, "weight": 3.0, "direction": "min"},
    "nse_val": {"threshold": 0.60, "tolerance": 0.20, "weight": 2.0, "direction": "min"},
    "kge_cal": {"threshold": 0.65, "tolerance": 0.20, "weight": 2.0, "direction": "min"},
    "kge_val": {"threshold": 0.65, "tolerance": 0.20, "weight": 1.5, "direction": "min"},
    "pbias_cal": {"threshold": 15.0, "tolerance": 10.0, "weight": 1.5, "direction": "abs_max"},
    "pbias_val": {"threshold": 15.0, "tolerance": 10.0, "weight": 1.0, "direction": "abs_max"},
}


def _to_float(value: Any, default: float | None = None) -> float | None:
    try:
        result = float(value)
    except Exception:
        return default
    if not np.isfinite(result):
        return default
    return result


def _to_optional_bool(value: Any) -> bool | None:
    if value is None:
        return None
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"true", "1", "yes", "y"}:
            return True
        if normalized in {"false", "0", "no", "n", ""}:
            return False
        return None
    return bool(value)


def _empty_series(length: int) -> np.ndarray:
    return np.full(int(max(length, 0)), np.nan, dtype=np.float64)


def _as_series(data: dict[str, Any], key: str, length: int | None = None) -> np.ndarray | None:
    value = data.get(key)
    if value is None:
        return None
    try:
        arr = np.asarray(value, dtype=np.float64)
    except Exception:
        return None
    if arr.ndim != 1:
        return None
    if length is not None and arr.shape[0] != int(length):
        return None
    return arr


def _as_dates(data: dict[str, Any]) -> pd.DatetimeIndex | None:
    value = data.get("date")
    if value is None:
        return None
    try:
        dates = pd.DatetimeIndex(pd.to_datetime(value))
    except Exception:
        return None
    return dates


def _as_mask(data: dict[str, Any], key: str, length: int | None = None) -> np.ndarray | None:
    value = data.get(key)
    if value is None:
        return None
    try:
        arr = np.asarray(value, dtype=bool)
    except Exception:
        return None
    if arr.ndim != 1:
        return None
    if length is not None and arr.shape[0] != int(length):
        return None
    return arr


def _status_item(
    *,
    active: bool,
    status: str,
    value_obs: Any = None,
    value_sim: Any = None,
    tolerance: Any = None,
    weight: Any = None,
    penalty: float = 0.0,
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    item = {
        "active": bool(active),
        "status": str(status),
        "value_obs": value_obs,
        "value_sim": value_sim,
        "tolerance": tolerance,
        "weight": weight,
        "penalty": float(penalty),
    }
    if extra:
        item.update(extra)
    return item


def _skipped_item(
    *,
    tolerance: Any = None,
    weight: Any = None,
    status: str = "skipped_insufficient_data",
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return _status_item(
        active=False,
        status=status,
        tolerance=tolerance,
        weight=weight,
        penalty=0.0,
        extra=extra,
    )


def _normalized_doy(dates: pd.DatetimeIndex) -> np.ndarray:
    doy = dates.dayofyear.to_numpy(dtype=np.int32, copy=True)
    leap_after_feb = np.asarray(dates.is_leap_year & (dates.month > 2), dtype=np.int32)
    return doy - leap_after_feb


def _select_q_score_base(bundle: dict[str, Any], project_object_type: str) -> tuple[np.ndarray | None, str, str]:
    return _as_series(bundle, "q_total"), "q_total", "total_runoff_calibration_period"


def _finite_common_mask(obs: np.ndarray | None, sim: np.ndarray | None) -> np.ndarray:
    if obs is None or sim is None:
        return np.zeros(0, dtype=bool)
    count = min(obs.shape[0], sim.shape[0])
    if count <= 0:
        return np.zeros(0, dtype=bool)
    return np.isfinite(obs[:count]) & np.isfinite(sim[:count])


def _monthly_sum_by_month(dates: pd.DatetimeIndex, values: np.ndarray) -> np.ndarray | None:
    if len(dates) != values.shape[0]:
        return None
    mask = np.isfinite(values)
    if not np.any(mask):
        return None
    series = pd.Series(values[mask], index=dates[mask])
    monthly = series.groupby(series.index.month).sum().reindex(range(1, 13), fill_value=0.0)
    return monthly.to_numpy(dtype=np.float64)


def _complete_calibration_year_masks(
    dates: pd.DatetimeIndex,
    calib_mask: np.ndarray,
    q_obs_obj: np.ndarray,
    q_sim: np.ndarray,
) -> list[np.ndarray]:
    masks: list[np.ndarray] = []
    for year in sorted(np.unique(dates[calib_mask].year)):
        year_mask = calib_mask & (dates.year == int(year))
        year_dates = dates[year_mask]
        if year_dates.empty:
            continue
        if year_dates.min().month != 1 or year_dates.min().day != 1:
            continue
        if year_dates.max().month != 12 or year_dates.max().day != 31:
            continue
        common_mask = year_mask & np.isfinite(q_obs_obj) & np.isfinite(q_sim)
        if int(np.sum(common_mask)) < 300:
            continue
        masks.append(common_mask)
    return masks


def _build_daily_climatology(
    dates: pd.DatetimeIndex,
    q_obs_obj: np.ndarray,
    q_sim: np.ndarray,
    calib_mask: np.ndarray,
) -> tuple[pd.Series | None, pd.Series | None, int]:
    common_mask = calib_mask & np.isfinite(q_obs_obj) & np.isfinite(q_sim)
    if int(np.sum(common_mask)) < 30:
        return None, None, int(np.sum(common_mask))

    dates_sel = dates[common_mask]
    obs_sel = q_obs_obj[common_mask]
    sim_sel = q_sim[common_mask]
    non_feb29 = ~((dates_sel.month == 2) & (dates_sel.day == 29))
    dates_sel = dates_sel[non_feb29]
    obs_sel = obs_sel[non_feb29]
    sim_sel = sim_sel[non_feb29]
    if len(dates_sel) < 30:
        return None, None, len(dates_sel)

    doy = _normalized_doy(dates_sel)
    obs_series = pd.Series(obs_sel, index=doy).groupby(level=0).median().reindex(range(1, 366))
    sim_series = pd.Series(sim_sel, index=doy).groupby(level=0).median().reindex(range(1, 366))
    obs_series = obs_series.rolling(7, center=True, min_periods=1).mean()
    sim_series = sim_series.rolling(7, center=True, min_periods=1).mean()
    return obs_series, sim_series, len(dates_sel)


def _hydro_features(h: pd.Series | None, *, allow_fallback: bool) -> dict[str, Any]:
    result = {
        "available": False,
        "q_base": None,
        "q_peak": None,
        "d_peak": None,
        "amplitude": None,
        "d20": None,
        "d60": None,
        "d80_fall": None,
        "d30_fall": None,
    }
    if h is None or h.empty:
        return result
    arr = np.asarray(h.to_numpy(dtype=np.float64), dtype=np.float64)
    doys = np.arange(1, arr.shape[0] + 1, dtype=np.int32)

    def _window_mask(start: int, end: int) -> np.ndarray:
        return (doys >= int(start)) & (doys <= int(end))

    base_mask = _window_mask(1, 59) & np.isfinite(arr)
    peak_mask = _window_mask(60, 320) & np.isfinite(arr)
    onset_mask = _window_mask(60, 250) & np.isfinite(arr)
    if not np.any(base_mask) or not np.any(peak_mask):
        return result
    q_base = float(np.nanmedian(arr[base_mask]))
    peak_values = arr[peak_mask]
    peak_doys = doys[peak_mask]
    peak_idx = int(np.nanargmax(peak_values))
    q_peak = float(peak_values[peak_idx])
    d_peak = int(peak_doys[peak_idx])
    amplitude = max(q_peak - q_base, EPS)
    result.update(
        {
            "available": True,
            "q_base": q_base,
            "q_peak": q_peak,
            "d_peak": d_peak,
            "amplitude": amplitude,
        }
    )

    def _first_crossing(threshold: float, start: int, end: int, *, ge: bool, fallback: int | None) -> int | None:
        mask = _window_mask(start, end) & np.isfinite(arr)
        if not np.any(mask):
            return fallback
        local_vals = arr[mask]
        local_doys = doys[mask]
        hit = np.where(local_vals >= threshold)[0] if ge else np.where(local_vals <= threshold)[0]
        if hit.size:
            return int(local_doys[int(hit[0])])
        return fallback

    d20 = _first_crossing(q_base + 0.20 * amplitude, 60, 250, ge=True, fallback=250 if allow_fallback else None)
    d60 = _first_crossing(q_base + 0.60 * amplitude, 60, 250, ge=True, fallback=250 if allow_fallback else None)
    d80_fall = _first_crossing(q_base + 0.80 * amplitude, d_peak, 365, ge=False, fallback=365 if allow_fallback else None)
    d30_fall = _first_crossing(q_base + 0.30 * amplitude, d_peak, 365, ge=False, fallback=365 if allow_fallback else None)
    if d30_fall is not None and d80_fall is not None and d30_fall < d80_fall:
        d30_fall = d80_fall

    result.update(
        {
            "d20": d20,
            "d60": d60,
            "d80_fall": d80_fall,
            "d30_fall": d30_fall,
        }
    )
    return result


def _logratio_error(value_sim: float, value_obs: float) -> float | None:
    if value_sim is None or value_obs is None:
        return None
    if (not np.isfinite(value_sim)) or (not np.isfinite(value_obs)):
        return None
    if value_sim <= 0.0 or value_obs <= 0.0:
        return None
    return float(np.log(value_sim / value_obs))


def _logratio_penalty(value_sim: float, value_obs: float, weight: float, tol_ratio: float) -> tuple[float, float | None]:
    log_err = _logratio_error(value_sim, value_obs)
    if log_err is None:
        return 0.0, None
    tol = float(np.log(1.0 + max(float(tol_ratio), 0.0)))
    excess = max(0.0, abs(log_err) - tol)
    penalty = float(weight) * ((excess / max(tol, EPS)) ** 2)
    return penalty, log_err


def _abs_penalty(delta: float, weight: float, tolerance: float) -> float:
    excess = max(0.0, abs(float(delta)) - float(tolerance))
    return float(weight) * ((excess / max(float(tolerance), EPS)) ** 2)


def _centroid_doy(dates: pd.DatetimeIndex, values: np.ndarray) -> float | None:
    mask = np.isfinite(values)
    if not np.any(mask):
        return None
    valid_values = values[mask]
    total = float(np.sum(valid_values))
    if total <= EPS:
        return None
    doy = _normalized_doy(dates[mask]).astype(np.float64)
    return float(np.sum(doy * valid_values) / total)


def _continuous_threshold_doy(dates: pd.DatetimeIndex, values: np.ndarray, *, threshold: float, start_doy: int, days: int) -> int | None:
    if len(dates) != values.shape[0]:
        return None
    doy = _normalized_doy(dates)
    mask = (doy >= int(start_doy)) & np.isfinite(values)
    if not np.any(mask):
        return None
    valid_doy = doy[mask]
    below = np.asarray(values[mask] < float(threshold), dtype=bool)
    run = 0
    for idx, flag in enumerate(below):
        run = run + 1 if flag else 0
        if run >= int(days):
            return int(valid_doy[idx - days + 1])
    return None


def _build_evidence_registry(bundle: dict[str, Any], length: int) -> dict[str, Any]:
    gm_obs = _as_series(bundle, "q_ice_reference_raw", length=length)
    gm_available = bool(gm_obs is not None and np.any(np.isfinite(gm_obs)))
    return {
        "gm": {
            "active": False,
            "available": gm_available,
            "status": "disabled_by_default" if gm_available else "skipped_inactive",
            "obs_series": gm_obs,
            "uncertainty": None,
        },
        "sca": {
            "active": False,
            "obs_series": None,
            "uncertainty": None,
        },
        "geodetic_mb": {
            "active": False,
            "obs_value": None,
            "uncertainty": None,
        },
    }


def _build_initial_payload(bundle: dict[str, Any], metrics: dict[str, Any], bad_obj: float) -> dict[str, Any]:
    q_total = _as_series(bundle, "q_total")
    length = int(q_total.shape[0]) if q_total is not None else 0
    evidence_registry = _build_evidence_registry(bundle, length)
    return {
        "objective_family": OBJECTIVE_FAMILY,
        "objective_value": float(bad_obj),
        "nse_cal": _to_float(metrics.get("nse_cal"), float("nan")),
        "nse_val": _to_float(metrics.get("nse_val"), float("nan")),
        "log_nse_cal": _to_float(metrics.get("log_nse_cal"), float("nan")),
        "log_nse_val": _to_float(metrics.get("log_nse_val"), float("nan")),
        "pbias_cal": _to_float(metrics.get("pbias_cal"), float("nan")),
        "pbias_val": _to_float(metrics.get("pbias_val"), float("nan")),
        "hard_checks": {
            "status": "fail",
            "failed_code": "H001_REQUIRED_SERIES_MISSING",
            "failed_reason": "required translated series missing or inconsistent length",
            "details": {
                "missing_fields": [],
                "length_summary": {},
            },
        },
        "objective_terms": {
            "flow": _skipped_item(status="skipped_hard_checks"),
            "flow_guard": {
                "active": False,
                "status": "skipped_hard_checks",
                "summary": "flow floor guard; skipped metrics are not hard failures",
                "checks": {},
                "penalty": 0.0,
            },
            "seasonality": _skipped_item(status="skipped_hard_checks"),
            "process_signatures": {
                "active": False,
                "status": "skipped_hard_checks",
                "penalty": 0.0,
                "swr": _skipped_item(status="skipped_hard_checks"),
                "rise_slope": _skipped_item(status="skipped_hard_checks"),
                "peak_timing": _skipped_item(status="skipped_hard_checks"),
                "peak_magnitude_bias": _skipped_item(status="skipped_hard_checks"),
                "flow_centroid_date": _skipped_item(status="skipped_hard_checks"),
                "recession_slope": _skipped_item(status="skipped_hard_checks"),
            },
            "cryo_consistency": {
                "active": False,
                "status": "skipped_hard_checks",
                "penalty": 0.0,
                "winter_ice_ratio": _skipped_item(status="skipped_hard_checks"),
                "snow_to_ice_centroid_lag": _skipped_item(status="skipped_hard_checks"),
                "peak_source_guard": _skipped_item(status="skipped_hard_checks"),
                "recession_takeover_diagnostic": _skipped_item(status="skipped_hard_checks"),
                "ice_dominance_guard": _skipped_item(status="skipped_hard_checks"),
            },
            "external_evidence": {
                "active": False,
                "status": "skipped_hard_checks",
                "penalty": 0.0,
                "gm": _skipped_item(status="skipped_hard_checks"),
                "gm_constraint": _skipped_item(status="skipped_hard_checks"),
                "sca": _skipped_item(status="skipped_hard_checks"),
                "geodetic_mb": _skipped_item(status="skipped_hard_checks"),
            },
            "secondary_terms": {
                "active": False,
                "status": "skipped_hard_checks",
                "nonflow_penalty_raw": 0.0,
                "nonflow_penalty_capped": 0.0,
                "nonflow_cap": float(NONFLOW_CAP),
                "whether_capped": False,
            },
        },
        "diagnostics": {
            "glacier_fraction_report": {
                "diagnostic_only": True,
                "evaluation_basis": None,
                "f_ice": None,
                "window": bundle.get("glacier_fraction_window"),
                "status": "unavailable",
            },
            "cryo_timing_report": {
                "centroid_snow_doy": None,
                "centroid_ice_doy": None,
                "lag_days": None,
                "winter_ice_ratio_djf": None,
                "winter_ice_mean_m3s": None,
            },
            "peak_source_report": {},
            "recession_takeover_diagnostic": {},
            "component_fraction_report": {
                "rain_fraction": None,
                "snow_fraction": None,
                "ice_fraction": None,
                "glacier_total_fraction": None,
                "evaluation_period": "calibration_period",
            },
            "process_signature_report": {},
            "external_evidence_report": {},
            "gm_constraint": _skipped_item(status="skipped_hard_checks"),
        },
        "diagnostic_only_constraints": {
            "glacier_fraction_window": True,
        },
        "evidence_registry": evidence_registry,
    }


def _run_hard_checks(bundle: dict[str, Any], diagnostics: dict[str, Any], evidence_registry: dict[str, Any]) -> dict[str, Any]:
    required_fields = (
        "date",
        "q_total",
        "q_local",
        "q_boundary",
        "q_rain",
        "q_snow",
        "q_ice",
        "q_snow_glacier",
        "calib_mask",
    )
    length_summary: dict[str, Any] = {}
    missing_fields: list[str] = []
    dates = _as_dates(bundle)
    if dates is None:
        missing_fields.append("date")
        series_length = None
    else:
        series_length = int(len(dates))
        length_summary["date"] = series_length

    resolved_series: dict[str, np.ndarray | None] = {}
    for key in required_fields[1:-1]:
        arr = _as_series(bundle, key)
        resolved_series[key] = arr
        length_summary[key] = None if arr is None else int(arr.shape[0])
        if arr is None:
            missing_fields.append(key)
    calib_mask = _as_mask(bundle, "calib_mask", length=series_length if series_length is not None else None)
    if calib_mask is None:
        missing_fields.append("calib_mask")
        length_summary["calib_mask"] = None
    else:
        length_summary["calib_mask"] = int(calib_mask.shape[0])
    if series_length is not None:
        for key, arr in resolved_series.items():
            if arr is not None and arr.shape[0] != series_length:
                if key not in missing_fields:
                    missing_fields.append(key)
    if missing_fields:
        return {
            "status": "fail",
            "failed_code": "H001_REQUIRED_SERIES_MISSING",
            "failed_reason": "required translated series missing or inconsistent length",
            "details": {
                "missing_fields": sorted(set(missing_fields)),
                "length_summary": length_summary,
            },
        }

    q_total = resolved_series["q_total"]
    q_local = resolved_series["q_local"]
    q_boundary = resolved_series["q_boundary"]
    q_rain = resolved_series["q_rain"]
    q_snow = resolved_series["q_snow"]
    q_ice = resolved_series["q_ice"]
    q_snow_glacier = resolved_series["q_snow_glacier"]
    assert dates is not None and q_total is not None and q_local is not None and q_boundary is not None
    assert q_rain is not None and q_snow is not None and q_ice is not None and q_snow_glacier is not None and calib_mask is not None

    project_object_type = str(bundle.get("project_object_type") or "").strip().lower()
    if project_object_type not in {"regression_validation", "full_upstream_basin", "interbasin_with_boundary"}:
        project_object_type = "interbasin_with_boundary" if np.any(np.abs(q_boundary) > EPS) else "full_upstream_basin"

    eval_basis_key = "q_total"
    eval_basis_label = "total_runoff_calibration_period"
    q_score_base = q_total

    calib_idx = np.asarray(calib_mask, dtype=bool)
    calib_dates = dates[calib_idx]

    # H002
    invalid_fields: list[str] = []
    first_invalid_date = None
    for key in ("q_total", "q_local", "q_boundary", "q_rain", "q_snow", "q_ice", "q_snow_glacier"):
        arr = resolved_series[key]
        assert arr is not None
        invalid = ~np.isfinite(arr[calib_idx])
        if np.any(invalid):
            invalid_fields.append(key)
            if first_invalid_date is None and len(calib_dates) == invalid.shape[0]:
                first_invalid_date = str(calib_dates[int(np.where(invalid)[0][0])].date())
    if invalid_fields:
        return {
            "status": "fail",
            "failed_code": "H002_INVALID_NUMERIC",
            "failed_reason": "non-finite values found in translated daily series",
            "details": {
                "first_invalid_date": first_invalid_date,
                "invalid_fields": invalid_fields,
            },
        }

    # H003
    minima = {
        "min_q_rain": float(np.nanmin(q_rain[calib_idx])) if np.any(calib_idx) else None,
        "min_q_snow": float(np.nanmin(q_snow[calib_idx])) if np.any(calib_idx) else None,
        "min_q_ice": float(np.nanmin(q_ice[calib_idx])) if np.any(calib_idx) else None,
        "min_q_snow_glacier": float(np.nanmin(q_snow_glacier[calib_idx])) if np.any(calib_idx) else None,
        "state_minima": bundle.get("state_minima"),
    }
    if any(
        value is not None and float(value) < -1e-6
        for value in (
            minima["min_q_rain"],
            minima["min_q_snow"],
            minima["min_q_ice"],
            minima["min_q_snow_glacier"],
        )
    ):
        return {
            "status": "fail",
            "failed_code": "H003_NEGATIVE_COMPONENT_OR_STATE",
            "failed_reason": "negative component flow or state detected",
            "details": minima,
        }

    # H004
    muskingum_coeffs = dict(bundle.get("muskingum_coeffs", {}) or {})
    c0 = _to_float(muskingum_coeffs.get("C0"))
    c1 = _to_float(muskingum_coeffs.get("C1"))
    c2 = _to_float(muskingum_coeffs.get("C2"))
    if (
        c0 is None or c1 is None or c2 is None
        or not (0.0 <= c0 <= 1.0)
        or not (0.0 <= c1 <= 1.0)
        or not (0.0 <= c2 <= 1.0)
        or abs((c0 + c1 + c2) - 1.0) > 1e-6
    ):
        return {
            "status": "fail",
            "failed_code": "H004_ROUTING_STABILITY_FAIL",
            "failed_reason": "routing coefficients outside stable domain",
            "details": {
                "C0": c0,
                "C1": c1,
                "C2": c2,
            },
        }

    # H005
    if project_object_type == "interbasin_with_boundary":
        residual_local = np.max(np.abs(q_local[calib_idx] - (q_rain[calib_idx] + q_snow[calib_idx] + q_ice[calib_idx]))) if np.any(calib_idx) else 0.0
        residual_total = np.max(np.abs(q_total[calib_idx] - (q_local[calib_idx] + q_boundary[calib_idx]))) if np.any(calib_idx) else 0.0
        closure_basis = "interbasin_with_boundary"
    else:
        residual_local = np.max(np.abs(q_total[calib_idx] - (q_rain[calib_idx] + q_snow[calib_idx] + q_ice[calib_idx]))) if np.any(calib_idx) else 0.0
        residual_total = residual_local
        closure_basis = project_object_type or "full_upstream_basin"
    if max(residual_local, residual_total) > 1e-3:
        return {
            "status": "fail",
            "failed_code": "H005_COMPONENT_CLOSURE_FAIL",
            "failed_reason": "component closure violated",
            "details": {
                "closure_basis": closure_basis,
                "max_abs_residual_local_components": float(residual_local),
                "max_abs_residual_total_balance": float(residual_total),
            },
        }

    # H006
    actual_basis = str(bundle.get("q_score_basis") or eval_basis_key).strip().lower() or eval_basis_key
    expected_basis = eval_basis_key
    if actual_basis != expected_basis:
        return {
            "status": "fail",
            "failed_code": "H006_OBJECT_BASIS_MISMATCH",
            "failed_reason": "object-type-specific evaluation basis mismatch",
            "details": {
                "project_object_type": project_object_type,
                "expected_basis": expected_basis,
                "actual_basis": actual_basis,
            },
        }

    # H007
    djf_mask = calib_idx & np.isin(dates.month.to_numpy(dtype=np.int32), np.array([12, 1, 2], dtype=np.int32))
    winter_score_total = float(np.sum(q_score_base[djf_mask])) if np.any(djf_mask) else 0.0
    winter_ice_total = float(np.sum(q_ice[djf_mask])) if np.any(djf_mask) else 0.0
    winter_ice_ratio = float(winter_ice_total / winter_score_total) if winter_score_total > EPS else 0.0
    winter_ice_mean = float(np.mean(q_ice[djf_mask])) if np.any(djf_mask) else 0.0
    winter_score_mean = float(np.mean(q_score_base[djf_mask])) if np.any(djf_mask) else 0.0
    if winter_ice_ratio > 0.35 or (winter_ice_ratio > 0.20 and winter_ice_mean > 1.0):
        return {
            "status": "fail",
            "failed_code": "H007_WINTER_ICE_LEAKAGE_HARD",
            "failed_reason": "winter ice leakage exceeds hard limit",
            "details": {
                "winter_ice_ratio_djf": float(winter_ice_ratio),
                "winter_ice_mean_m3s": float(winter_ice_mean),
                "winter_score_base_mean_m3s": float(winter_score_mean),
            },
        }

    # H008
    basin_has_glacier = bool(np.nanmax(q_ice) > EPS or np.nanmax(q_snow_glacier) > EPS)
    snow_series = q_snow_glacier
    if np.allclose(snow_series[calib_idx], 0.0, atol=1e-9) and not basin_has_glacier:
        lag_days = None
    else:
        centroid_ice = _centroid_doy(calib_dates, q_ice[calib_idx])
        centroid_snow = _centroid_doy(calib_dates, snow_series[calib_idx])
        cryo_total = float(np.sum(q_ice[calib_idx]) + np.sum(snow_series[calib_idx]))
        ice_fraction_of_cryo = float(np.sum(q_ice[calib_idx]) / cryo_total) if cryo_total > EPS else 0.0
        lag_days = None if (centroid_ice is None or centroid_snow is None) else float(centroid_ice - centroid_snow)
        if ice_fraction_of_cryo >= 0.10 and lag_days is not None and lag_days < -5.0:
            return {
                "status": "fail",
                "failed_code": "H008_CRYO_ORDERING_HARD",
                "failed_reason": "ice timing leads snow timing beyond hard limit",
                "details": {
                    "centroid_ice_doy": centroid_ice,
                    "centroid_snow_glacier_doy": centroid_snow,
                    "lag_days": lag_days,
                    "ice_fraction_of_cryo": ice_fraction_of_cryo,
                },
            }

    # H009
    gm_registry = dict(evidence_registry.get("gm", {}) or {})
    if bool(gm_registry.get("active")):
        obs_series = gm_registry.get("obs_series")
        if obs_series is None or np.asarray(obs_series, dtype=np.float64).shape[0] == 0:
            return {
                "status": "fail",
                "failed_code": "H009_DECLARED_EVIDENCE_MISSING",
                "failed_reason": "declared evidence is active but required payload is missing",
                "details": {
                    "evidence_type": "gm",
                    "missing_payload_fields": ["obs_series"],
                },
            }

    return {
        "status": "pass",
        "failed_code": None,
        "failed_reason": "",
        "details": {
            "routing_ok": True,
            "closure_ok": True,
            "basis_ok": True,
            "winter_ice_ratio_djf": float(winter_ice_ratio),
            "winter_ice_mean_m3s": float(winter_ice_mean),
            "lag_days": lag_days,
            "closure_basis": closure_basis,
            "process_signature_report_available": bool(diagnostics.get("process_signature_report")),
        },
    }


def _compute_flow_terms(metrics: dict[str, Any]) -> tuple[float, dict[str, Any]]:
    nse_cal = _to_float(metrics.get("nse_cal"), float("nan"))
    log_nse_cal = _to_float(metrics.get("log_nse_cal"), float("nan"))
    nse_val = _to_float(metrics.get("nse_val"), float("nan"))
    log_nse_val = _to_float(metrics.get("log_nse_val"), float("nan"))
    kge_cal = _to_float(metrics.get("kge_cal"), float("nan"))
    kge_val = _to_float(metrics.get("kge_val"), float("nan"))
    pbias_cal = _to_float(metrics.get("pbias_cal"), float("nan"))
    pbias_val = _to_float(metrics.get("pbias_val"), float("nan"))
    obs_count_val = int(_to_float(metrics.get("obs_count_val"), 0) or 0)
    valid_val = bool(obs_count_val >= 30 and np.isfinite(nse_val) and np.isfinite(log_nse_val))
    if not np.isfinite(nse_cal):
        return float("nan"), {
            "active": False,
            "status": "skipped_invalid_flow_metrics",
            "nse_cal": None,
            "lognse_cal": None,
            "nse_val": None,
            "lognse_val": None,
            "kge_cal": None,
            "kge_val": None,
            "pbias_cal": None,
            "pbias_val": None,
            "weight_config": {},
            "penalty": None,
        }
    if not np.isfinite(log_nse_cal):
        log_nse_cal = nse_cal
    penalty = (1.0 - nse_cal) + 0.35 * (1.0 - log_nse_cal)
    if valid_val:
        penalty += 0.35 * (1.0 - nse_val) + 0.1225 * (1.0 - log_nse_val)
        if np.isfinite(pbias_val):
            penalty += 0.10 * (abs(pbias_val) / 100.0)
    if np.isfinite(pbias_cal):
        penalty += 0.10 * (abs(pbias_cal) / 100.0)
    term = {
        "active": True,
        "status": "ok",
        "nse_cal": nse_cal,
        "lognse_cal": log_nse_cal,
        "nse_val": nse_val if np.isfinite(nse_val) else None,
        "lognse_val": log_nse_val if np.isfinite(log_nse_val) else None,
        "kge_cal": kge_cal if np.isfinite(kge_cal) else None,
        "kge_val": kge_val if np.isfinite(kge_val) else None,
        "pbias_cal": pbias_cal if np.isfinite(pbias_cal) else None,
        "pbias_val": pbias_val if np.isfinite(pbias_val) else None,
        "weight_config": {
            "nse_cal": 1.0,
            "lognse_cal": 0.35,
            "nse_val": 0.35 if valid_val else 0.0,
            "lognse_val": 0.1225 if valid_val else 0.0,
            "pbias_cal": 0.10 if np.isfinite(pbias_cal) else 0.0,
            "pbias_val": 0.10 if (valid_val and np.isfinite(pbias_val)) else 0.0,
        },
        "penalty": float(penalty),
    }
    return float(penalty), term


def _flow_guard_check(value: float | None, *, threshold: float, tolerance: float, weight: float, direction: str) -> tuple[str, float]:
    if value is None or not np.isfinite(value):
        return "skipped_insufficient_data", 0.0
    if direction == "abs_max":
        excess = max(0.0, abs(float(value)) - float(threshold))
        status = "ok" if excess <= 0.0 else "outside_flow_floor"
        penalty = float(weight) * ((excess / max(float(tolerance), EPS)) ** 2)
    else:
        deficit = max(0.0, float(threshold) - float(value))
        status = "ok" if deficit <= 0.0 else "below_flow_floor"
        penalty = float(weight) * ((deficit / max(float(tolerance), EPS)) ** 2)
    return status, float(penalty)


def _compute_flow_guard_terms(metrics: dict[str, Any]) -> tuple[float, dict[str, Any]]:
    obs_count_val = int(_to_float(metrics.get("obs_count_val"), 0) or 0)
    checks: dict[str, Any] = {}
    total_penalty = 0.0
    active_count = 0
    for key, cfg in FLOW_GUARD_CONFIG.items():
        is_validation_metric = key.endswith("_val")
        raw_value = _to_float(metrics.get(key), None)
        if is_validation_metric and obs_count_val < 30:
            checks[key] = {
                "active": False,
                "status": "skipped_no_validation_period",
                "value": raw_value,
                "threshold": cfg["threshold"],
                "tolerance": cfg["tolerance"],
                "weight": cfg["weight"],
                "penalty": 0.0,
            }
            continue
        status, penalty = _flow_guard_check(
            raw_value,
            threshold=float(cfg["threshold"]),
            tolerance=float(cfg["tolerance"]),
            weight=float(cfg["weight"]),
            direction=str(cfg["direction"]),
        )
        active = status != "skipped_insufficient_data"
        if active:
            active_count += 1
            total_penalty += penalty
        checks[key] = {
            "active": bool(active),
            "status": status,
            "value": raw_value,
            "threshold": float(cfg["threshold"]),
            "tolerance": float(cfg["tolerance"]),
            "weight": float(cfg["weight"]),
            "penalty": float(penalty),
        }
    group = {
        "active": bool(active_count > 0),
        "status": "ok" if total_penalty <= EPS else "penalized",
        "summary": "flow floor guard; skipped metrics are not hard failures",
        "checks": checks,
        "penalty": float(total_penalty),
    }
    return float(total_penalty), group


def _compute_seasonality_terms(
    dates: pd.DatetimeIndex,
    q_obs_obj: np.ndarray,
    q_sim: np.ndarray,
    calib_mask: np.ndarray,
) -> tuple[float, dict[str, Any]]:
    year_masks = _complete_calibration_year_masks(dates, calib_mask, q_obs_obj, q_sim)
    if len(year_masks) < 2:
        return 0.0, {
            "active": False,
            "status": "skipped_insufficient_data",
            "warm_fraction_obs": None,
            "warm_fraction_sim": None,
            "djf_fraction_obs": None,
            "djf_fraction_sim": None,
            "tolerances": {
                "warm_fraction_abs": 0.05,
                "djf_fraction_positive_bias": 0.02,
            },
            "penalty_warm": 0.0,
            "penalty_djf": 0.0,
            "penalty": 0.0,
        }

    warm_obs_values: list[float] = []
    warm_sim_values: list[float] = []
    djf_obs_values: list[float] = []
    djf_sim_values: list[float] = []
    for mask in year_masks:
        year_dates = dates[mask]
        obs_values = q_obs_obj[mask]
        sim_values = q_sim[mask]
        obs_monthly = pd.Series(obs_values, index=year_dates).groupby(year_dates.month).sum().reindex(range(1, 13), fill_value=0.0)
        sim_monthly = pd.Series(sim_values, index=year_dates).groupby(year_dates.month).sum().reindex(range(1, 13), fill_value=0.0)
        obs_total = float(obs_monthly.sum())
        sim_total = float(sim_monthly.sum())
        if obs_total <= EPS or sim_total <= EPS:
            continue
        warm_obs_values.append(float(obs_monthly.loc[[5, 6, 7, 8, 9, 10]].sum() / obs_total))
        warm_sim_values.append(float(sim_monthly.loc[[5, 6, 7, 8, 9, 10]].sum() / sim_total))
        djf_obs_values.append(float(obs_monthly.loc[[12, 1, 2]].sum() / obs_total))
        djf_sim_values.append(float(sim_monthly.loc[[12, 1, 2]].sum() / sim_total))

    if len(warm_obs_values) < 2:
        return 0.0, {
            "active": False,
            "status": "skipped_insufficient_data",
            "warm_fraction_obs": None,
            "warm_fraction_sim": None,
            "djf_fraction_obs": None,
            "djf_fraction_sim": None,
            "tolerances": {
                "warm_fraction_abs": 0.05,
                "djf_fraction_positive_bias": 0.02,
            },
            "penalty_warm": 0.0,
            "penalty_djf": 0.0,
            "penalty": 0.0,
        }

    warm_fraction_obs = float(np.median(warm_obs_values))
    warm_fraction_sim = float(np.median(warm_sim_values))
    djf_fraction_obs = float(np.median(djf_obs_values))
    djf_fraction_sim = float(np.median(djf_sim_values))
    penalty_warm = 0.10 * ((max(0.0, abs(warm_fraction_sim - warm_fraction_obs) - 0.05) / 0.05) ** 2)
    penalty_djf = 0.05 * ((max(0.0, (djf_fraction_sim - djf_fraction_obs) - 0.02) / 0.02) ** 2)
    total_penalty = float(penalty_warm + penalty_djf)
    return total_penalty, {
        "active": True,
        "status": "ok",
        "warm_fraction_obs": warm_fraction_obs,
        "warm_fraction_sim": warm_fraction_sim,
        "djf_fraction_obs": djf_fraction_obs,
        "djf_fraction_sim": djf_fraction_sim,
        "tolerances": {
            "warm_fraction_abs": 0.05,
            "djf_fraction_positive_bias": 0.02,
        },
        "penalty_warm": float(penalty_warm),
        "penalty_djf": float(penalty_djf),
        "penalty": total_penalty,
    }


def _compute_process_signature_terms(
    dates: pd.DatetimeIndex,
    q_obs_obj: np.ndarray,
    q_sim: np.ndarray,
    calib_mask: np.ndarray,
) -> tuple[float, dict[str, Any], dict[str, Any]]:
    obs_h, sim_h, sample_count = _build_daily_climatology(dates, q_obs_obj, q_sim, calib_mask)
    diag_report: dict[str, Any] = {}
    group = {
        "active": True,
        "status": "ok",
        "penalty": 0.0,
    }

    obs_calib_dates = dates[calib_mask]
    obs_calib = q_obs_obj[calib_mask]
    sim_calib = q_sim[calib_mask]
    valid_mask = np.isfinite(obs_calib) & np.isfinite(sim_calib)
    monthly_obs = _monthly_sum_by_month(obs_calib_dates[valid_mask], obs_calib[valid_mask]) if np.any(valid_mask) else None
    monthly_sim = _monthly_sum_by_month(obs_calib_dates[valid_mask], sim_calib[valid_mask]) if np.any(valid_mask) else None

    if obs_h is None or sim_h is None or sample_count < 30:
        skipped = _skipped_item(status="skipped_insufficient_data")
        group.update(
            {
                "active": False,
                "status": "skipped_insufficient_data",
                "swr": _skipped_item(tolerance=0.20, weight=0.20),
                "rise_slope": _skipped_item(
                    tolerance={"rise_onset_error_days": 7, "rise_slope_log_error": math.log(1.25)},
                    weight={"timing": 0.06, "shape": 0.08},
                ),
                "peak_timing": _skipped_item(tolerance=7, weight=0.08),
                "peak_magnitude_bias": _skipped_item(tolerance=0.15, weight=0.08),
                "flow_centroid_date": _skipped_item(tolerance=10, weight=0.06),
                "recession_slope": _skipped_item(tolerance=0.25, weight=0.08),
                "penalty": 0.0,
            }
        )
        diag_report.update({key: copy.deepcopy(value) for key, value in group.items() if key in {
            "swr", "rise_slope", "peak_timing", "peak_magnitude_bias", "flow_centroid_date", "recession_slope"
        }})
        return 0.0, group, diag_report

    obs_feat = _hydro_features(obs_h, allow_fallback=False)
    sim_feat = _hydro_features(sim_h, allow_fallback=True)

    # SWR
    if monthly_obs is None or monthly_sim is None:
        swr_item = _skipped_item(tolerance=0.20, weight=0.20)
    else:
        obs_summer = float(np.sum(monthly_obs[[4, 5, 6, 7, 8]]))
        obs_winter = float(np.sum(monthly_obs[[10, 11, 0, 1, 2]]))
        sim_summer = float(np.sum(monthly_sim[[4, 5, 6, 7, 8]]))
        sim_winter = float(np.sum(monthly_sim[[10, 11, 0, 1, 2]]))
        if obs_summer <= EPS or obs_winter <= EPS or sim_summer <= EPS or sim_winter <= EPS:
            swr_item = _skipped_item(tolerance=0.20, weight=0.20)
        else:
            swr_obs = obs_summer / obs_winter
            swr_sim = sim_summer / sim_winter
            swr_penalty, swr_log_error = _logratio_penalty(swr_sim, swr_obs, 0.20, 0.20)
            swr_item = _status_item(
                active=True,
                status="ok",
                value_obs=float(swr_obs),
                value_sim=float(swr_sim),
                tolerance=0.20,
                weight=0.20,
                penalty=float(swr_penalty),
                extra={"log_error": swr_log_error},
            )

    # Rise slope
    if obs_feat.get("d20") is None or obs_feat.get("d60") is None:
        rise_item = _skipped_item(
            tolerance={"rise_onset_error_days": 7, "rise_slope_log_error": math.log(1.25)},
            weight={"timing": 0.06, "shape": 0.08},
        )
    else:
        sim_d20 = sim_feat.get("d20")
        sim_d60 = sim_feat.get("d60")
        if sim_d20 is None:
            sim_d20 = 250
        if sim_d60 is None:
            sim_d60 = max(int(sim_d20), 250)
        rise_obs = 0.40 / max(int(obs_feat["d60"]) - int(obs_feat["d20"]), 1)
        rise_sim = 0.40 / max(int(sim_d60) - int(sim_d20), 1)
        onset_error = float(int(sim_d20) - int(obs_feat["d20"]))
        penalty_timing = _abs_penalty(onset_error, 0.06, 7)
        penalty_shape, rise_log_error = _logratio_penalty(rise_sim, rise_obs, 0.08, 0.25)
        rise_item = _status_item(
            active=True,
            status="ok",
            value_obs=float(rise_obs),
            value_sim=float(rise_sim),
            tolerance={"rise_onset_error_days": 7, "rise_slope_log_error": math.log(1.25)},
            weight={"timing": 0.06, "shape": 0.08},
            penalty=float(penalty_timing + penalty_shape),
            extra={
                "rise_onset_obs_doy": int(obs_feat["d20"]),
                "rise_onset_sim_doy": int(sim_d20),
                "rise_onset_error_days": onset_error,
                "rise_slope_obs": float(rise_obs),
                "rise_slope_sim": float(rise_sim),
                "rise_slope_log_error": rise_log_error,
                "penalty_timing": float(penalty_timing),
                "penalty_shape": float(penalty_shape),
            },
        )

    # Peak timing
    if obs_feat.get("d_peak") is None or sim_feat.get("d_peak") is None:
        peak_timing_item = _skipped_item(tolerance=7, weight=0.08)
    else:
        delta_peak = float(int(sim_feat["d_peak"]) - int(obs_feat["d_peak"]))
        peak_timing_item = _status_item(
            active=True,
            status="ok",
            value_obs=int(obs_feat["d_peak"]),
            value_sim=int(sim_feat["d_peak"]),
            tolerance=7,
            weight=0.08,
            penalty=float(_abs_penalty(delta_peak, 0.08, 7)),
            extra={"peak_timing_error_days": delta_peak},
        )

    # Peak magnitude
    if obs_feat.get("q_peak") is None or sim_feat.get("q_peak") is None:
        peak_mag_item = _skipped_item(tolerance=0.15, weight=0.08)
    else:
        peak_mag_penalty, peak_mag_log_error = _logratio_penalty(float(sim_feat["q_peak"]), float(obs_feat["q_peak"]), 0.08, 0.15)
        peak_mag_item = _status_item(
            active=True,
            status="ok",
            value_obs=float(obs_feat["q_peak"]),
            value_sim=float(sim_feat["q_peak"]),
            tolerance=0.15,
            weight=0.08,
            penalty=float(peak_mag_penalty),
            extra={"peak_magnitude_log_error": peak_mag_log_error},
        )

    # Flow centroid
    centroid_obs = _centroid_doy(obs_calib_dates[valid_mask], obs_calib[valid_mask]) if np.any(valid_mask) else None
    centroid_sim = _centroid_doy(obs_calib_dates[valid_mask], sim_calib[valid_mask]) if np.any(valid_mask) else None
    if centroid_obs is None or centroid_sim is None:
        centroid_item = _skipped_item(tolerance=10, weight=0.06)
    else:
        centroid_error = float(centroid_sim - centroid_obs)
        centroid_item = _status_item(
            active=True,
            status="ok",
            value_obs=float(centroid_obs),
            value_sim=float(centroid_sim),
            tolerance=10,
            weight=0.06,
            penalty=float(_abs_penalty(centroid_error, 0.06, 10)),
            extra={"flow_centroid_error_days": centroid_error},
        )

    # Recession
    if obs_feat.get("d80_fall") is None or obs_feat.get("d30_fall") is None:
        recession_item = _skipped_item(tolerance=0.25, weight=0.08)
    else:
        sim_d80 = sim_feat.get("d80_fall")
        sim_d30 = sim_feat.get("d30_fall")
        if sim_d80 is None:
            sim_d80 = 365
        if sim_d30 is None:
            sim_d30 = 365
        if sim_d30 < sim_d80:
            sim_d30 = sim_d80
        recession_obs = 0.50 / max(int(obs_feat["d30_fall"]) - int(obs_feat["d80_fall"]), 1)
        recession_sim = 0.50 / max(int(sim_d30) - int(sim_d80), 1)
        recession_penalty, recession_log_error = _logratio_penalty(recession_sim, recession_obs, 0.08, 0.25)
        recession_item = _status_item(
            active=True,
            status="ok",
            value_obs=float(recession_obs),
            value_sim=float(recession_sim),
            tolerance=0.25,
            weight=0.08,
            penalty=float(recession_penalty),
            extra={"recession_slope_log_error": recession_log_error},
        )

    group.update(
        {
            "swr": swr_item,
            "rise_slope": rise_item,
            "peak_timing": peak_timing_item,
            "peak_magnitude_bias": peak_mag_item,
            "flow_centroid_date": centroid_item,
            "recession_slope": recession_item,
        }
    )
    group["penalty"] = float(
        swr_item["penalty"]
        + rise_item["penalty"]
        + peak_timing_item["penalty"]
        + peak_mag_item["penalty"]
        + centroid_item["penalty"]
        + recession_item["penalty"]
    )
    diag_report = {
        "swr": copy.deepcopy(swr_item),
        "rise_slope": copy.deepcopy(rise_item),
        "peak_timing": copy.deepcopy(peak_timing_item),
        "peak_magnitude_bias": copy.deepcopy(peak_mag_item),
        "flow_centroid_date": copy.deepcopy(centroid_item),
        "recession_slope": copy.deepcopy(recession_item),
    }
    return float(group["penalty"]), group, diag_report


def _threshold_value(features: dict[str, Any] | None, fraction: float) -> float | None:
    feat = dict(features or {})
    q_base = _to_float(feat.get("q_base"))
    amplitude = _to_float(feat.get("amplitude"))
    if q_base is None or amplitude is None:
        return None
    return float(q_base + float(fraction) * amplitude)


def _local_peak_candidates(
    h: pd.Series | None,
    *,
    start: int = 60,
    end: int = 320,
    top_n: int = 10,
) -> list[dict[str, Any]]:
    if h is None or h.empty or top_n <= 0:
        return []
    arr = np.asarray(h.to_numpy(dtype=np.float64), dtype=np.float64)
    doys = np.arange(1, arr.shape[0] + 1, dtype=np.int32)
    mask = (doys >= int(start)) & (doys <= int(end)) & np.isfinite(arr)
    if not np.any(mask):
        return []
    local_vals = arr[mask]
    local_doys = doys[mask]
    candidates: list[tuple[float, int]] = []
    for idx, value in enumerate(local_vals):
        left = local_vals[idx - 1] if idx > 0 else -np.inf
        right = local_vals[idx + 1] if idx + 1 < local_vals.shape[0] else -np.inf
        if value >= left and value >= right:
            candidates.append((float(value), int(local_doys[idx])))
    if not candidates:
        order = np.argsort(local_vals)[::-1]
        candidates = [(float(local_vals[idx]), int(local_doys[idx])) for idx in order]
    candidates.sort(key=lambda item: (-item[0], item[1]))
    return [
        {"doy": int(doy), "value": float(value)}
        for value, doy in candidates[: int(top_n)]
    ]


def build_process_signature_alignment_debug_report(
    dates: pd.DatetimeIndex,
    q_obs_obj: np.ndarray,
    q_sim: np.ndarray,
    calib_mask: np.ndarray,
    *,
    existing_terms: dict[str, Any] | None = None,
) -> dict[str, Any]:
    existing_terms = dict(existing_terms or {})
    common_mask = np.asarray(calib_mask, dtype=bool) & np.isfinite(q_obs_obj) & np.isfinite(q_sim)
    common_dates = dates[common_mask]
    common_obs = q_obs_obj[common_mask]
    common_sim = q_sim[common_mask]
    feb29_mask = (common_dates.month == 2) & (common_dates.day == 29)
    feb29_count = int(np.sum(feb29_mask))
    non_feb29 = ~feb29_mask
    dates_no_feb29 = common_dates[non_feb29]
    obs_h, sim_h, sample_count = _build_daily_climatology(dates, q_obs_obj, q_sim, calib_mask)
    obs_feat = _hydro_features(obs_h, allow_fallback=False)
    sim_feat = _hydro_features(sim_h, allow_fallback=True)

    peak_item = dict(existing_terms.get("peak_timing", {}) or {})
    recession_item = dict(existing_terms.get("recession_slope", {}) or {})
    current_peak = _to_float(peak_item.get("peak_timing_error_days"))
    current_recession = _to_float(recession_item.get("recession_slope_log_error"))

    recomputed_peak = None
    if obs_feat.get("d_peak") is not None and sim_feat.get("d_peak") is not None:
        recomputed_peak = float(int(sim_feat["d_peak"]) - int(obs_feat["d_peak"]))

    obs_recession = None
    sim_recession = None
    recomputed_recession = None
    if (
        obs_feat.get("d80_fall") is not None
        and obs_feat.get("d30_fall") is not None
        and sim_feat.get("d80_fall") is not None
        and sim_feat.get("d30_fall") is not None
    ):
        obs_recession = 0.50 / max(int(obs_feat["d30_fall"]) - int(obs_feat["d80_fall"]), 1)
        sim_recession = 0.50 / max(int(sim_feat["d30_fall"]) - int(sim_feat["d80_fall"]), 1)
        recomputed_recession = _logratio_error(sim_recession, obs_recession)

    peak_matches_metadata = (
        current_peak is None
        or recomputed_peak is None
        or abs(float(current_peak) - float(recomputed_peak)) <= 1e-9
    )
    recession_matches_metadata = (
        current_recession is None
        or recomputed_recession is None
        or abs(float(current_recession) - float(recomputed_recession)) <= 1e-9
    )
    peak_gate_pass = recomputed_peak is not None and abs(float(recomputed_peak)) <= 10.0
    recession_gate_pass = (
        recomputed_recession is not None
        and abs(float(recomputed_recession)) <= math.log(1.35)
    )

    if not peak_matches_metadata or not recession_matches_metadata:
        root_cause = "translator_bug_or_stale_metadata"
    elif peak_gate_pass and recession_gate_pass:
        root_cause = "process_consistency_pass"
    else:
        root_cause = "parameter_group_under_process_consistency"

    return {
        "current_metadata_terms": {
            "peak_timing_error_days": current_peak,
            "recession_slope_log_error": current_recession,
        },
        "recomputed_contract_terms": {
            "peak_timing_error_days": recomputed_peak,
            "recession_slope_log_error": recomputed_recession,
        },
        "contract_checks": {
            "calibration_common_mask_only": True,
            "feb29_removed": bool(len(dates_no_feb29) == len(common_dates) - feb29_count),
            "climatology_point_count": int(len(obs_h)) if obs_h is not None else 0,
            "climatology_365_points": bool(obs_h is not None and sim_h is not None and len(obs_h) == 365 and len(sim_h) == 365),
            "rolling_mean_window_days": 7,
            "rolling_mean_centered": True,
            "peak_search_window": [60, 320],
            "rise_search_window": [60, 250],
            "recession_search_window": ["D_peak", 365],
        },
        "sample_sizes": {
            "common_mask_count": int(np.sum(common_mask)),
            "feb29_removed_count": feb29_count,
            "post_feb29_count": int(len(dates_no_feb29)),
            "climatology_sample_count": int(sample_count),
        },
        "observed_climatology": {
            "Q_base": _to_float(obs_feat.get("q_base")),
            "Q_peak": _to_float(obs_feat.get("q_peak")),
            "D_peak": obs_feat.get("d_peak"),
            "D20": obs_feat.get("d20"),
            "D60": obs_feat.get("d60"),
            "D80_fall": obs_feat.get("d80_fall"),
            "D30_fall": obs_feat.get("d30_fall"),
            "Q20_threshold": _threshold_value(obs_feat, 0.20),
            "Q60_threshold": _threshold_value(obs_feat, 0.60),
            "Q80_fall_threshold": _threshold_value(obs_feat, 0.80),
            "Q30_fall_threshold": _threshold_value(obs_feat, 0.30),
            "local_peak_candidates": _local_peak_candidates(obs_h),
        },
        "simulated_climatology": {
            "Q_base": _to_float(sim_feat.get("q_base")),
            "Q_peak": _to_float(sim_feat.get("q_peak")),
            "D_peak": sim_feat.get("d_peak"),
            "D20": sim_feat.get("d20"),
            "D60": sim_feat.get("d60"),
            "D80_fall": sim_feat.get("d80_fall"),
            "D30_fall": sim_feat.get("d30_fall"),
            "Q20_threshold": _threshold_value(sim_feat, 0.20),
            "Q60_threshold": _threshold_value(sim_feat, 0.60),
            "Q80_fall_threshold": _threshold_value(sim_feat, 0.80),
            "Q30_fall_threshold": _threshold_value(sim_feat, 0.30),
            "local_peak_candidates": _local_peak_candidates(sim_h),
        },
        "recession_slope_components": {
            "obs_recession_slope": obs_recession,
            "sim_recession_slope": sim_recession,
        },
        "process_consistency_gate": {
            "peak_timing_error_days_abs_max": 10.0,
            "recession_slope_log_error_abs_max": math.log(1.35),
            "peak_timing_pass": bool(peak_gate_pass),
            "recession_slope_pass": bool(recession_gate_pass),
        },
        "classification": {
            "root_cause": root_cause,
            "contract_consistent": bool(peak_matches_metadata and recession_matches_metadata),
            "peak_timing_matches_metadata": bool(peak_matches_metadata),
            "recession_matches_metadata": bool(recession_matches_metadata),
            "judgement": (
                "合同实现正确，但该参数组在当前统一 objective 下仍未通过 process_signatures 门槛"
                if root_cause == "parameter_group_under_process_consistency"
                else (
                    "重算值与 metadata 不一致，需继续排查 translator 或结果重存链"
                    if root_cause == "translator_bug_or_stale_metadata"
                    else "当前 run 已满足 peak/recession 过程一致性门槛"
                )
            ),
        },
    }


def _compute_cryo_terms(
    dates: pd.DatetimeIndex,
    q_ice: np.ndarray,
    q_snow_glacier: np.ndarray,
    q_snow: np.ndarray,
    q_score_base: np.ndarray,
    calib_mask: np.ndarray,
) -> tuple[float, dict[str, Any], dict[str, Any]]:
    djf_mask = calib_mask & np.isin(dates.month.to_numpy(dtype=np.int32), np.array([12, 1, 2], dtype=np.int32))
    winter_score_total = float(np.sum(q_score_base[djf_mask])) if np.any(djf_mask) else 0.0
    winter_ice_total = float(np.sum(q_ice[djf_mask])) if np.any(djf_mask) else 0.0
    winter_ice_ratio = float(winter_ice_total / winter_score_total) if winter_score_total > EPS else 0.0
    winter_ice_mean = float(np.mean(q_ice[djf_mask])) if np.any(djf_mask) else 0.0
    winter_penalty = 0.10 * ((max(0.0, winter_ice_ratio - 0.05) / 0.05) ** 2)
    winter_item = _status_item(
        active=True,
        status="ok",
        value_obs=0.05,
        value_sim=float(winter_ice_ratio),
        tolerance=0.05,
        weight=0.10,
        penalty=float(winter_penalty),
        extra={"winter_ice_ratio_djf": float(winter_ice_ratio)},
    )

    calib_dates = dates[calib_mask]
    snow_ref = q_snow_glacier if np.any(np.abs(q_snow_glacier[calib_mask]) > EPS) else q_snow
    centroid_snow = _centroid_doy(calib_dates, snow_ref[calib_mask])
    centroid_ice = _centroid_doy(calib_dates, q_ice[calib_mask])
    lag_days = None if centroid_snow is None or centroid_ice is None else float(centroid_ice - centroid_snow)
    if lag_days is None:
        lag_item = _skipped_item(tolerance=7, weight=0.08)
    else:
        lag_penalty = 0.08 * ((max(0.0, 7.0 - lag_days) / 7.0) ** 2)
        lag_item = _status_item(
            active=True,
            status="ok",
            value_obs=7.0,
            value_sim=float(lag_days),
            tolerance=7.0,
            weight=0.08,
            penalty=float(lag_penalty),
            extra={"lag_days": float(lag_days)},
        )
    total_penalty = float(winter_item["penalty"] + lag_item["penalty"])
    group = {
        "active": True,
        "status": "ok",
        "winter_ice_ratio": winter_item,
        "snow_to_ice_centroid_lag": lag_item,
        "penalty": total_penalty,
    }
    diag = {
        "centroid_snow_doy": centroid_snow,
        "centroid_ice_doy": centroid_ice,
        "lag_days": lag_days,
        "winter_ice_ratio_djf": float(winter_ice_ratio),
        "winter_ice_mean_m3s": float(winter_ice_mean),
    }
    return total_penalty, group, diag


def _build_gm_constraint_item(gm_item: dict[str, Any]) -> dict[str, Any]:
    ratio = _to_float(gm_item.get("volume_ratio"), None)
    value_obs = _to_float(gm_item.get("value_obs"), None)
    value_sim = _to_float(gm_item.get("value_sim"), None)
    tolerance = gm_item.get("tolerance", [0.70, 1.30])
    status = str(gm_item.get("status", "skipped_inactive") or "skipped_inactive")
    active = bool(gm_item.get("active", False))
    if active and ratio is not None:
        if ratio > 1.30:
            status = "above_guard"
        elif ratio < 0.70:
            status = "below_guard"
        elif ratio > 1.15 or ratio < 0.85:
            status = "soft_warning"
        else:
            status = "ok"
    elif not active:
        status = status or "skipped_inactive"
    return _status_item(
        active=active,
        status=status,
        value_obs=value_obs,
        value_sim=value_sim,
        tolerance=tolerance,
        weight=gm_item.get("weight", 0.12),
        penalty=float(gm_item.get("penalty", 0.0) or 0.0),
        extra={
            "mode": "external_glacier_melt_soft_constraint" if active else "gm_constraint_inactive",
            "source": "q_ice_reference_raw" if active else None,
            "simulated_ice_melt": value_sim,
            "expected_or_guard_range": (
                [float(value_obs * 0.70), float(value_obs * 1.30)]
                if value_obs is not None
                else None
            ),
            "volume_ratio": ratio,
            "weighting": "soft_guard_capped_by_nonflow_cap",
            "note": (
                "仅在显式启用外部冰融水参考时，该序列才作为软约束项。"
                if active
                else "外部冰融水参考约束未启用；该字段仅保留为过程复核信息。"
            ),
        },
    )


def _compute_external_evidence_terms(
    bundle: dict[str, Any],
    dates: pd.DatetimeIndex,
    calib_mask: np.ndarray,
    q_ice_raw: np.ndarray,
    evidence_registry: dict[str, Any],
) -> tuple[float, dict[str, Any], dict[str, Any]]:
    gm_registry = dict(evidence_registry.get("gm", {}) or {})
    gm_available = bool(gm_registry.get("available", False))
    gm_item = _skipped_item(
        status="disabled_by_default" if gm_available else "skipped_inactive",
        tolerance=[0.70, 1.30],
        weight=0.12,
        extra={"available": gm_available},
    )
    if bool(gm_registry.get("active")):
        gm_obs = np.asarray(gm_registry.get("obs_series"), dtype=np.float64)
        count = min(gm_obs.shape[0], q_ice_raw.shape[0], calib_mask.shape[0], dates.shape[0])
        month_mask = np.isin(dates[:count].month.to_numpy(dtype=np.int32), np.array([4, 5, 6, 7, 8, 9], dtype=np.int32))
        active_mask = np.asarray(calib_mask[:count], dtype=bool) & month_mask & np.isfinite(gm_obs[:count]) & np.isfinite(q_ice_raw[:count])
        if np.any(active_mask):
            obs_value = float(np.sum(gm_obs[:count][active_mask]))
            sim_value = float(np.sum(q_ice_raw[:count][active_mask]))
            ratio = float(sim_value / obs_value) if obs_value > EPS else None
            if ratio is None or ratio <= 0.0:
                gm_penalty = 0.0
                gm_status = "skipped_insufficient_data"
            else:
                if ratio < 0.70:
                    gm_penalty = 0.12 * ((math.log(0.70 / ratio) / math.log(1.30)) ** 2)
                    gm_status = "below_guard"
                elif ratio > 1.30:
                    gm_penalty = 0.12 * ((math.log(ratio / 1.30) / math.log(1.30)) ** 2)
                    gm_status = "above_guard"
                else:
                    gm_penalty = 0.0
                    gm_status = "soft_warning" if (ratio > 1.15 or ratio < 0.85) else "ok"
            gm_item = _status_item(
                active=True,
                status=gm_status,
                value_obs=obs_value,
                value_sim=sim_value,
                tolerance=[0.70, 1.30],
                weight=0.12,
                penalty=float(gm_penalty),
                extra={"uncertainty": None, "volume_ratio": ratio},
            )
        else:
            gm_item = _skipped_item(status="skipped_insufficient_data", tolerance=[0.70, 1.30], weight=0.12)

    sca_item = _skipped_item(status="skipped_inactive", tolerance=7, weight=0.10)
    geodetic_item = _skipped_item(status="skipped_inactive", tolerance=1.0, weight=0.10)
    gm_constraint_item = _build_gm_constraint_item(gm_item)
    total_penalty = float(gm_item["penalty"] + sca_item["penalty"] + geodetic_item["penalty"])
    group_status = "ok"
    if str(gm_constraint_item.get("status", "")).strip().lower() in {"above_guard", "below_guard", "soft_warning"}:
        group_status = "soft_warning"
    group = {
        "active": True,
        "status": group_status,
        "gm": gm_item,
        "gm_constraint": gm_constraint_item,
        "sca": sca_item,
        "geodetic_mb": geodetic_item,
        "penalty": total_penalty,
    }
    report = {
        "gm": copy.deepcopy(gm_item),
        "gm_constraint": copy.deepcopy(gm_constraint_item),
        "sca": copy.deepcopy(sca_item),
        "geodetic_mb": copy.deepcopy(geodetic_item),
    }
    return total_penalty, group, report


def _compute_component_diagnostics(
    q_rain: np.ndarray,
    q_snow: np.ndarray,
    q_ice: np.ndarray,
    q_glacier_total: np.ndarray,
    q_score_base: np.ndarray,
    calib_mask: np.ndarray,
    evaluation_period: str,
) -> dict[str, Any]:
    total = float(np.sum(q_score_base[calib_mask])) if np.any(calib_mask) else 0.0
    if total <= EPS:
        return {
            "rain_fraction": None,
            "snow_fraction": None,
            "ice_fraction": None,
            "glacier_total_fraction": None,
            "evaluation_period": evaluation_period,
        }
    return {
        "rain_fraction": float(np.sum(q_rain[calib_mask]) / total),
        "snow_fraction": float(np.sum(q_snow[calib_mask]) / total),
        "ice_fraction": float(np.sum(q_ice[calib_mask]) / total),
        "glacier_total_fraction": float(np.sum(q_glacier_total[calib_mask]) / total),
        "evaluation_period": evaluation_period,
    }


def _compute_glacier_fraction_report(
    q_ice: np.ndarray,
    q_score_base: np.ndarray,
    calib_mask: np.ndarray,
    evaluation_basis: str,
    window: Any,
) -> dict[str, Any]:
    total = float(np.sum(q_score_base[calib_mask])) if np.any(calib_mask) else 0.0
    f_ice = float(np.sum(q_ice[calib_mask]) / total) if total > EPS else None
    status = "unavailable"
    lower_bound = None
    upper_bound = None
    if f_ice is not None:
        if isinstance(window, (list, tuple)) and len(window) >= 2:
            try:
                f_min = float(window[0])
                f_max = float(window[1])
            except Exception:
                f_min = f_max = None
            if f_min is not None and f_max is not None and np.isfinite(f_min) and np.isfinite(f_max) and f_max > f_min:
                lower_bound = float(f_min)
                upper_bound = float(f_max)
                if f_ice < f_min:
                    status = "below_window"
                elif f_ice > f_max:
                    status = "above_window"
                else:
                    status = "in_window"
            else:
                status = "computed_without_window"
        else:
            status = "computed_without_window"
    return {
        "diagnostic_only": True,
        "evaluation_basis": evaluation_basis,
        "f_ice": f_ice,
        "window": window,
        "lower_bound": lower_bound,
        "upper_bound": upper_bound,
        "status": status,
    }


def _has_active_external_evidence(evidence_registry: dict[str, Any]) -> bool:
    for key in ("gm", "sca", "geodetic_mb"):
        item = dict(evidence_registry.get(key, {}) or {})
        if bool(item.get("active")):
            return True
    return False


def _has_valid_active_external_evidence(evidence_registry: dict[str, Any]) -> bool:
    for key in ("gm", "sca", "geodetic_mb"):
        item = dict(evidence_registry.get(key, {}) or {})
        if not bool(item.get("active")):
            continue
        if key in {"gm", "sca"}:
            obs_series = item.get("obs_series")
            if obs_series is None:
                continue
            try:
                arr = np.asarray(obs_series, dtype=np.float64)
            except Exception:
                continue
            if arr.size > 0 and np.any(np.isfinite(arr)):
                return True
        else:
            obs_value = _to_float(item.get("obs_value"), None)
            if obs_value is not None:
                return True
    return False


def _window_upper_from_report(glacier_fraction_report: dict[str, Any]) -> float | None:
    upper_bound = _to_float(glacier_fraction_report.get("upper_bound"), None)
    if upper_bound is not None and upper_bound > 0.0:
        return upper_bound
    window = glacier_fraction_report.get("window")
    if isinstance(window, (list, tuple)) and len(window) >= 2:
        parsed = _to_float(window[1], None)
        if parsed is not None and parsed > 0.0:
            return parsed
    return None


def _derived_upper_from_glacier_area(glacier_area_ratio: float | None) -> float | None:
    if glacier_area_ratio is None or not np.isfinite(glacier_area_ratio) or glacier_area_ratio <= 0.0:
        return None
    fa = float(glacier_area_ratio)
    high_mult = 3.0
    upper_floor = 0.0
    if fa < 0.03:
        high_mult = 15.0
        upper_floor = 0.15
    elif fa < 0.08:
        high_mult = 8.0
        upper_floor = 0.12
    return float(min(max(high_mult * fa, upper_floor), 0.70))


def _ice_guard_config(
    *,
    glacier_model_mode: str,
    glacier_fraction_exists: bool | None,
    glacier_area_ratio: float | None,
    window_upper: float | None,
) -> dict[str, Any]:
    area_upper = _derived_upper_from_glacier_area(glacier_area_ratio)
    upper_candidates = [value for value in (window_upper, area_upper) if value is not None]
    derived_upper = max(upper_candidates) if upper_candidates else None
    high_glacier_area = bool(
        (glacier_area_ratio is not None and glacier_area_ratio >= 0.20)
        or (derived_upper is not None and derived_upper > 0.35)
    )
    mode = str(glacier_model_mode or "").strip().lower()

    if mode == "fractional_subgrid" and glacier_fraction_exists is True:
        base_upper = derived_upper if derived_upper is not None else ICE_DOMINANCE_FRACTIONAL_MIN_UPPER
        upper = min(
            ICE_DOMINANCE_FRACTIONAL_MAX_UPPER,
            max(ICE_DOMINANCE_FRACTIONAL_MIN_UPPER, float(base_upper) * ICE_DOMINANCE_FRACTIONAL_WINDOW_FACTOR),
        )
        tolerance = max(ICE_DOMINANCE_FRACTIONAL_MIN_TOLERANCE, ICE_DOMINANCE_FRACTIONAL_TOLERANCE_RATIO * upper)
        reason = "high_glacier_area_relaxed_guard" if high_glacier_area else "fractional_subgrid_dynamic_guard"
        return {
            "upper": float(upper),
            "base_upper": float(base_upper),
            "tolerance": float(tolerance),
            "reason": reason,
            "guard_type": "fractional_subgrid_dynamic",
            "high_glacier_area": high_glacier_area,
        }

    if high_glacier_area:
        base_upper = derived_upper if derived_upper is not None else 0.35
        upper = min(
            ICE_DOMINANCE_FRACTIONAL_MAX_UPPER,
            max(0.35, float(base_upper) * ICE_DOMINANCE_FRACTIONAL_WINDOW_FACTOR),
        )
        tolerance = max(ICE_DOMINANCE_FRACTIONAL_MIN_TOLERANCE, ICE_DOMINANCE_FRACTIONAL_TOLERANCE_RATIO * upper)
        return {
            "upper": float(upper),
            "base_upper": float(base_upper),
            "tolerance": float(tolerance),
            "reason": "high_glacier_area_relaxed_guard",
            "guard_type": "high_glacier_area_relaxed",
            "high_glacier_area": True,
        }

    if mode == "binary_legacy":
        base_upper = window_upper if window_upper is not None else ICE_DOMINANCE_BINARY_DEFAULT_UPPER
        upper = min(
            ICE_DOMINANCE_BINARY_MAX_UPPER,
            max(ICE_DOMINANCE_BINARY_MIN_UPPER, float(base_upper) * ICE_DOMINANCE_BINARY_WINDOW_FACTOR),
        )
        return {
            "upper": float(upper),
            "base_upper": float(base_upper),
            "tolerance": float(ICE_DOMINANCE_BINARY_TOLERANCE),
            "reason": "binary_legacy_conservative_guard",
            "guard_type": "binary_legacy_conservative",
            "high_glacier_area": False,
        }

    base_upper = derived_upper if derived_upper is not None else ICE_DOMINANCE_BINARY_DEFAULT_UPPER
    upper = min(
        ICE_DOMINANCE_FRACTIONAL_MAX_UPPER,
        max(ICE_DOMINANCE_BINARY_MIN_UPPER, float(base_upper) * ICE_DOMINANCE_BINARY_WINDOW_FACTOR),
    )
    tolerance = max(ICE_DOMINANCE_FRACTIONAL_MIN_TOLERANCE, ICE_DOMINANCE_FRACTIONAL_TOLERANCE_RATIO * upper)
    return {
        "upper": float(upper),
        "base_upper": float(base_upper),
        "tolerance": float(tolerance),
        "reason": "adaptive_guard_unknown_glacier_mode",
        "guard_type": "adaptive_unknown_mode",
        "high_glacier_area": False,
    }


def _compute_ice_dominance_guard(
    *,
    q_ice: np.ndarray,
    q_score_base: np.ndarray,
    calib_mask: np.ndarray,
    glacier_enabled: bool,
    glacier_model_mode: str,
    glacier_area_ratio: float | None,
    glacier_mask_exists: bool | None,
    glacier_fraction_exists: bool | None,
    glacier_elev_exists: bool | None,
    glacier_fraction_report: dict[str, Any],
    evidence_registry: dict[str, Any],
    evaluation_basis: str,
) -> dict[str, Any]:
    window_upper = _window_upper_from_report(glacier_fraction_report)
    config = _ice_guard_config(
        glacier_model_mode=glacier_model_mode,
        glacier_fraction_exists=glacier_fraction_exists,
        glacier_area_ratio=glacier_area_ratio,
        window_upper=window_upper,
    )
    base = {
        "active": False,
        "status": "skipped",
        "f_ice": None,
        "upper": float(config["upper"]),
        "base_upper": config.get("base_upper"),
        "window_upper": window_upper,
        "penalty": 0.0,
        "weight": float(ICE_DOMINANCE_GUARD_WEIGHT),
        "tolerance": float(config["tolerance"]),
        "basis": evaluation_basis,
        "glacier_model_mode": str(glacier_model_mode or "unknown"),
        "glacier_area_ratio": glacier_area_ratio,
        "glacier_mask_exists": glacier_mask_exists,
        "glacier_fraction_exists": glacier_fraction_exists,
        "glacier_elev_exists": glacier_elev_exists,
        "evidence_controlled": False,
        "reason": "",
        "guard_type": config.get("guard_type"),
        "high_glacier_area": bool(config.get("high_glacier_area", False)),
        "external_evidence_active": bool(_has_active_external_evidence(evidence_registry)),
        "external_evidence_valid": bool(_has_valid_active_external_evidence(evidence_registry)),
    }
    active_mask = np.asarray(calib_mask, dtype=bool) & np.isfinite(q_ice) & np.isfinite(q_score_base)
    no_glacier_inputs = (
        glacier_mask_exists is False
        and glacier_fraction_exists is False
        and (glacier_area_ratio is None or glacier_area_ratio <= EPS)
    )
    no_glacier_area = glacier_area_ratio is not None and glacier_area_ratio <= EPS
    if (not bool(glacier_enabled)) or no_glacier_inputs or no_glacier_area:
        base["status"] = "not_applicable_no_glacier"
        base["reason"] = "no_glacier"
        return base
    if not np.any(active_mask):
        base["status"] = "skipped_insufficient_data"
        base["reason"] = "q_ice or q_score_base has no valid calibration-period data"
        return base
    q_ice_valid = np.asarray(q_ice[active_mask], dtype=np.float64)
    q_score_valid = np.asarray(q_score_base[active_mask], dtype=np.float64)
    if not np.any(np.abs(q_ice_valid) > EPS):
        base["f_ice"] = 0.0
        if no_glacier_inputs or no_glacier_area:
            base["status"] = "not_applicable_no_glacier"
            base["reason"] = "no_glacier"
        else:
            base["status"] = "skipped_zero_q_ice"
            base["reason"] = "q_ice exists but is zero during the calibration period"
        return base
    total = float(np.sum(q_score_valid))
    if total <= EPS:
        base["status"] = "skipped_no_score_base"
        base["reason"] = "q_score_base total is zero or unavailable"
        return base
    f_ice = float(np.sum(q_ice_valid) / total)
    base["f_ice"] = f_ice
    if base["external_evidence_valid"]:
        base["status"] = "controlled_by_external_evidence"
        base["evidence_controlled"] = True
        base["reason"] = "controlled_by_external_evidence"
        if f_ice > 0.90:
            base["status"] = "sanity_warning_external_evidence"
        return base
    upper = float(config["upper"])
    tolerance = float(config["tolerance"])
    excess = max(0.0, f_ice - upper)
    penalty = 0.0 if excess <= 0.0 else ICE_DOMINANCE_GUARD_WEIGHT * ((excess / max(tolerance, EPS)) ** 2)
    base.update(
        {
            "active": True,
            "status": "ok" if penalty <= EPS else "above_guard",
            "penalty": float(penalty),
            "reason": str(config["reason"]),
        }
    )
    return base


def _max_consecutive_true(values: np.ndarray) -> int:
    max_run = 0
    run = 0
    for value in np.asarray(values, dtype=bool):
        if bool(value):
            run += 1
            max_run = max(max_run, run)
        else:
            run = 0
    return int(max_run)


def _recession_takeover_for_peak(
    dates: pd.DatetimeIndex,
    q_ice: np.ndarray,
    q_score_base: np.ndarray,
    calib_mask: np.ndarray,
    peak_idx: int,
) -> dict[str, Any]:
    peak_date = dates[int(peak_idx)]
    end_date = peak_date + pd.Timedelta(days=int(RECESSION_TAKEOVER_WINDOW_DAYS))
    window_mask = (
        np.asarray(calib_mask, dtype=bool)
        & (dates > peak_date)
        & (dates <= end_date)
        & np.isfinite(q_ice)
        & np.isfinite(q_score_base)
        & (q_score_base > EPS)
    )
    if not np.any(window_mask):
        return {
            "active": False,
            "status": "skipped_insufficient_data",
            "window_days": int(RECESSION_TAKEOVER_WINDOW_DAYS),
            "sample_count": 0,
            "mean_ice_fraction": None,
            "max_ice_fraction": None,
            "ice_dominant_days": 0,
            "max_consecutive_ice_dominant_days": 0,
            "takeover": False,
            "score": 0.0,
        }
    fractions = np.clip(q_ice[window_mask] / np.maximum(q_score_base[window_mask], EPS), 0.0, None)
    dominant = fractions >= float(PEAK_SOURCE_ICE_DOMINANCE_THRESHOLD)
    max_consecutive = _max_consecutive_true(dominant)
    mean_fraction = float(np.mean(fractions))
    takeover = bool(
        max_consecutive >= int(RECESSION_TAKEOVER_CONSECUTIVE_DAYS)
        or mean_fraction >= float(RECESSION_TAKEOVER_MEAN_FRACTION)
    )
    score = 0.0
    if takeover:
        score += max(0.0, (float(max_consecutive) - float(RECESSION_TAKEOVER_CONSECUTIVE_DAYS)) / 12.0)
        score += max(0.0, (mean_fraction - float(RECESSION_TAKEOVER_MEAN_FRACTION)) / 0.20)
    return {
        "active": True,
        "status": "takeover" if takeover else "ok",
        "window_days": int(RECESSION_TAKEOVER_WINDOW_DAYS),
        "sample_count": int(fractions.shape[0]),
        "mean_ice_fraction": float(mean_fraction),
        "max_ice_fraction": float(np.max(fractions)),
        "ice_dominant_days": int(np.sum(dominant)),
        "max_consecutive_ice_dominant_days": int(max_consecutive),
        "takeover": bool(takeover),
        "score": float(score),
    }


def _compute_peak_source_guard(
    *,
    dates: pd.DatetimeIndex,
    q_rain: np.ndarray,
    q_snow: np.ndarray,
    q_ice: np.ndarray,
    q_score_base: np.ndarray,
    calib_mask: np.ndarray,
    glacier_enabled: bool,
    glacier_model_mode: str,
    glacier_area_ratio: float | None,
    glacier_elev_exists: bool | None,
    evidence_registry: dict[str, Any],
    cryo_report: dict[str, Any],
    evaluation_basis: str,
) -> tuple[float, dict[str, Any], dict[str, Any], dict[str, Any]]:
    glacier_mode = str(glacier_model_mode or "unknown").strip().lower()
    fractional_mode = glacier_mode == "fractional_subgrid"
    binary_mode = glacier_mode == "binary_legacy"
    base_report = {
        "active": False,
        "status": "skipped",
        "evaluation_basis": evaluation_basis,
        "thresholds": {
            "ice_dominance_fraction": float(PEAK_SOURCE_ICE_DOMINANCE_THRESHOLD),
            "no_evidence_high_fraction": float(PEAK_SOURCE_NO_EVIDENCE_THRESHOLD),
            "small_glacier_area": float(PEAK_SOURCE_SMALL_GLACIER_AREA),
            "late_melt_months": list(PEAK_SOURCE_LATE_MELT_MONTHS),
            "recession_window_days": int(RECESSION_TAKEOVER_WINDOW_DAYS),
            "recession_takeover_consecutive_days": int(RECESSION_TAKEOVER_CONSECUTIVE_DAYS),
            "recession_takeover_mean_fraction": float(RECESSION_TAKEOVER_MEAN_FRACTION),
        },
        "glacier_model_mode": glacier_mode or "unknown",
        "fraction_elevation_inputs_required": bool(fractional_mode),
        "binary_fraction_elevation_note": (
            "1km binary glacier mode does not require glacier_fraction/glacier_elev rasters"
            if binary_mode
            else ""
        ),
        "glacier_area_ratio": glacier_area_ratio,
        "glacier_elev_exists": glacier_elev_exists,
        "external_evidence_active": bool(_has_active_external_evidence(evidence_registry)),
        "external_evidence_valid": bool(_has_valid_active_external_evidence(evidence_registry)),
        "snow_to_ice_centroid_lag_days": _to_float(cryo_report.get("lag_days"), None),
        "annual_peak_sources": [],
        "flagged_years": [],
        "plausible_ice_peak_years": [],
    }
    skipped_term = _skipped_item(
        status="not_applicable_no_glacier" if not bool(glacier_enabled) else "skipped_insufficient_data",
        tolerance=float(PEAK_SOURCE_ICE_DOMINANCE_THRESHOLD),
        weight=float(PEAK_SOURCE_GUARD_WEIGHT),
    )
    recession_report = {
        "active": False,
        "status": "skipped",
        "annual": [],
        "flagged_years": [],
    }
    if not bool(glacier_enabled):
        base_report["status"] = "not_applicable_no_glacier"
        recession_report["status"] = "not_applicable_no_glacier"
        return 0.0, skipped_term, base_report, recession_report

    valid_mask = (
        np.asarray(calib_mask, dtype=bool)
        & np.isfinite(q_score_base)
        & np.isfinite(q_rain)
        & np.isfinite(q_snow)
        & np.isfinite(q_ice)
        & (q_score_base > EPS)
    )
    if not np.any(valid_mask):
        base_report["status"] = "skipped_insufficient_data"
        recession_report["status"] = "skipped_insufficient_data"
        return 0.0, skipped_term, base_report, recession_report

    base_report["active"] = True
    recession_report["active"] = True
    years = sorted({int(year) for year in dates[valid_mask].year})
    issue_scores: list[float] = []
    annual: list[dict[str, Any]] = []
    recession_annual: list[dict[str, Any]] = []
    valid_external = bool(base_report["external_evidence_valid"])
    small_or_unknown_glacier = (
        glacier_area_ratio is None
        or (np.isfinite(float(glacier_area_ratio)) and float(glacier_area_ratio) <= float(PEAK_SOURCE_SMALL_GLACIER_AREA))
    )
    lag_days = _to_float(cryo_report.get("lag_days"), None)

    for year in years:
        year_mask = valid_mask & (dates.year.to_numpy(dtype=np.int32) == int(year))
        if int(np.sum(year_mask)) < 20:
            continue
        indices = np.flatnonzero(year_mask)
        local_peak_pos = int(np.nanargmax(q_score_base[indices]))
        peak_idx = int(indices[local_peak_pos])
        peak_total = float(max(q_score_base[peak_idx], EPS))
        components = {
            "rain": float(max(q_rain[peak_idx], 0.0)),
            "snow": float(max(q_snow[peak_idx], 0.0)),
            "ice": float(max(q_ice[peak_idx], 0.0)),
        }
        fractions = {key: float(value / peak_total) for key, value in components.items()}
        source = max(components.items(), key=lambda item: (item[1], item[0]))[0]
        ice_fraction = float(fractions.get("ice", 0.0))
        month = int(dates[peak_idx].month)
        late_melt_peak = bool(month in set(PEAK_SOURCE_LATE_MELT_MONTHS))
        ice_dominant = bool(source == "ice" and ice_fraction >= float(PEAK_SOURCE_ICE_DOMINANCE_THRESHOLD))
        reasons: list[str] = []
        event_score = 0.0
        recession = _recession_takeover_for_peak(dates, q_ice, q_score_base, calib_mask, peak_idx)

        if ice_dominant:
            if not late_melt_peak:
                reasons.append("ice_peak_outside_late_melt_season")
                event_score += ((max(0.0, ice_fraction - float(PEAK_SOURCE_ICE_DOMINANCE_THRESHOLD)) / 0.25) ** 2) + 0.25
            if not valid_external:
                reasons.append("no_external_evidence")
                if small_or_unknown_glacier and ice_fraction >= float(PEAK_SOURCE_NO_EVIDENCE_THRESHOLD):
                    reasons.append("small_or_unknown_glacier_area_high_ice_peak")
                    event_score += (max(0.0, ice_fraction - float(PEAK_SOURCE_NO_EVIDENCE_THRESHOLD)) / 0.25) ** 2 + 0.20
            if lag_days is not None and lag_days < 7.0:
                reasons.append("ice_centroid_not_later_than_snow")
                event_score += (max(0.0, 7.0 - float(lag_days)) / 7.0) ** 2
            if fractional_mode and glacier_elev_exists is False:
                reasons.append("missing_glacier_elev_lowers_confidence")
        if bool(recession.get("takeover")):
            reasons.append("recession_ice_takeover")
            if (not valid_external) or small_or_unknown_glacier or (fractional_mode and glacier_elev_exists is False):
                event_score += float(recession.get("score", 0.0) or 0.0)

        if ice_dominant and event_score <= EPS:
            judgement = "plausible_late_melt_ice_peak" if late_melt_peak else "ice_peak_requires_context"
            base_report["plausible_ice_peak_years"].append(int(year))
        elif event_score > EPS:
            judgement = "suspicious_or_evidence_limited_ice_peak"
            base_report["flagged_years"].append(int(year))
            issue_scores.append(float(min(event_score, 4.0)))
        else:
            judgement = "non_ice_peak"

        item = {
            "year": int(year),
            "date": dates[peak_idx].strftime("%Y-%m-%d"),
            "month": int(month),
            "q_peak": float(q_score_base[peak_idx]),
            "dominant_source": source,
            "fractions": fractions,
            "ice_dominant": bool(ice_dominant),
            "late_melt_peak": bool(late_melt_peak),
            "judgement": judgement,
            "reasons": reasons,
            "score": float(event_score),
        }
        annual.append(item)
        recession_item = dict(recession)
        recession_item.update({"year": int(year), "peak_date": item["date"]})
        recession_annual.append(recession_item)

    if not annual:
        base_report["status"] = "skipped_insufficient_data"
        recession_report["status"] = "skipped_insufficient_data"
        return 0.0, skipped_term, base_report, recession_report

    penalty = float(PEAK_SOURCE_GUARD_WEIGHT * min(2.0, (sum(issue_scores) / max(len(annual), 1))))
    status = "ok" if penalty <= EPS else "above_guard"
    base_report.update(
        {
            "status": status,
            "penalty": float(penalty),
            "annual_peak_sources": annual,
            "flagged_years": sorted({int(item) for item in base_report["flagged_years"]}),
            "plausible_ice_peak_years": sorted({int(item) for item in base_report["plausible_ice_peak_years"]}),
            "max_peak_ice_fraction": float(max(float(item["fractions"].get("ice", 0.0)) for item in annual)),
            "ice_dominant_peak_year_count": int(sum(1 for item in annual if bool(item.get("ice_dominant")))),
        }
    )
    recession_flagged = sorted({int(item["year"]) for item in recession_annual if bool(item.get("takeover"))})
    recession_report.update(
        {
            "status": "takeover" if recession_flagged else "ok",
            "annual": recession_annual,
            "flagged_years": recession_flagged,
        }
    )
    term = _status_item(
        active=True,
        status=status,
        value_obs=float(PEAK_SOURCE_ICE_DOMINANCE_THRESHOLD),
        value_sim=base_report.get("max_peak_ice_fraction"),
        tolerance=float(PEAK_SOURCE_NO_EVIDENCE_THRESHOLD - PEAK_SOURCE_ICE_DOMINANCE_THRESHOLD),
        weight=float(PEAK_SOURCE_GUARD_WEIGHT),
        penalty=float(penalty),
        extra={
            "flagged_years": base_report["flagged_years"],
            "plausible_ice_peak_years": base_report["plausible_ice_peak_years"],
            "ice_dominant_peak_year_count": base_report["ice_dominant_peak_year_count"],
            "external_evidence_valid": valid_external,
            "diagnostic_report": "diagnostics.peak_source_report",
        },
    )
    return penalty, term, base_report, recession_report


def evaluate_daily_unified_objective(bundle: dict[str, Any], metrics: dict[str, Any], *, bad_obj: float) -> dict[str, Any]:
    payload = _build_initial_payload(bundle, metrics, bad_obj)
    initial_hard_checks = _run_hard_checks(bundle, payload["diagnostics"], payload["evidence_registry"])
    payload["hard_checks"] = initial_hard_checks
    if initial_hard_checks.get("status") != "pass":
        return payload
    dates = _as_dates(bundle)
    q_total = _as_series(bundle, "q_total")
    if dates is None or q_total is None:
        return payload

    length = int(q_total.shape[0])
    q_local = _as_series(bundle, "q_local", length=length)
    q_boundary = _as_series(bundle, "q_boundary", length=length)
    q_rain = _as_series(bundle, "q_rain", length=length)
    q_snow = _as_series(bundle, "q_snow", length=length)
    q_ice = _as_series(bundle, "q_ice", length=length)
    q_ice_raw = _as_series(bundle, "q_ice_raw", length=length)
    q_snow_glacier = _as_series(bundle, "q_snow_glacier", length=length)
    q_glacier_total = _as_series(bundle, "q_glacier_total", length=length)
    q_obs_obj = _as_series(bundle, "q_obs_obj", length=length)
    calib_mask = _as_mask(bundle, "calib_mask", length=length)
    if any(item is None for item in (q_local, q_boundary, q_rain, q_snow, q_ice, q_obs_obj, calib_mask)):
        return payload
    assert q_local is not None and q_boundary is not None and q_rain is not None and q_snow is not None
    assert q_ice is not None and q_obs_obj is not None and calib_mask is not None
    if q_ice_raw is None:
        q_ice_raw = np.asarray(q_ice, dtype=np.float64).copy()
    if q_snow_glacier is None:
        q_snow_glacier = np.asarray(q_snow, dtype=np.float64).copy()
    if q_glacier_total is None:
        q_glacier_total = np.asarray(q_ice + q_snow_glacier, dtype=np.float64)

    project_object_type = str(bundle.get("project_object_type") or "").strip().lower()
    if project_object_type not in {"regression_validation", "full_upstream_basin", "interbasin_with_boundary"}:
        project_object_type = "interbasin_with_boundary" if np.any(np.abs(q_boundary) > EPS) else "full_upstream_basin"

    q_score_base, q_score_basis, evaluation_basis = _select_q_score_base(bundle, project_object_type)
    if q_score_base is None:
        return payload
    q_score_base = np.asarray(q_score_base, dtype=np.float64)
    bundle = dict(bundle)
    bundle["project_object_type"] = project_object_type
    bundle["q_score_basis"] = q_score_basis
    evidence_registry = payload["evidence_registry"]

    diagnostics = {
        "glacier_fraction_report": _compute_glacier_fraction_report(
            q_ice,
            q_score_base,
            calib_mask,
            evaluation_basis,
            bundle.get("glacier_fraction_window"),
        ),
        "cryo_timing_report": {
            "centroid_snow_doy": None,
            "centroid_ice_doy": None,
            "lag_days": None,
            "winter_ice_ratio_djf": None,
            "winter_ice_mean_m3s": None,
        },
        "peak_source_report": {},
        "recession_takeover_diagnostic": {},
        "component_fraction_report": _compute_component_diagnostics(
            q_rain,
            q_snow,
            q_ice,
            q_glacier_total,
            q_score_base,
            calib_mask,
            evaluation_basis,
        ),
        "process_signature_report": {},
        "external_evidence_report": {},
    }

    diagnostics["process_signature_report"] = {"available": True}
    hard_checks = _run_hard_checks(bundle, diagnostics, evidence_registry)
    payload["hard_checks"] = hard_checks
    payload["diagnostics"] = diagnostics
    payload["evidence_registry"] = evidence_registry
    if hard_checks["status"] != "pass":
        return payload

    flow_penalty, flow_term = _compute_flow_terms(metrics)
    flow_guard_penalty, flow_guard_term = _compute_flow_guard_terms(metrics)
    seasonality_penalty, seasonality_term = _compute_seasonality_terms(dates, q_obs_obj, q_score_base, calib_mask)
    signatures_penalty, signature_terms, signature_report = _compute_process_signature_terms(dates, q_obs_obj, q_score_base, calib_mask)
    cryo_penalty, cryo_terms, cryo_report = _compute_cryo_terms(dates, q_ice, q_snow_glacier, q_snow, q_score_base, calib_mask)
    evidence_penalty, evidence_terms, evidence_report = _compute_external_evidence_terms(bundle, dates, calib_mask, q_ice_raw, evidence_registry)
    ice_guard_term = _compute_ice_dominance_guard(
        q_ice=q_ice,
        q_score_base=q_score_base,
        calib_mask=calib_mask,
        glacier_enabled=bool(bundle.get("glacier_enabled", False)),
        glacier_model_mode=str(bundle.get("glacier_model_mode") or "unknown"),
        glacier_area_ratio=_to_float(bundle.get("glacier_area_ratio"), None),
        glacier_mask_exists=_to_optional_bool(bundle.get("glacier_mask_exists")),
        glacier_fraction_exists=_to_optional_bool(bundle.get("glacier_fraction_exists")),
        glacier_elev_exists=_to_optional_bool(bundle.get("glacier_elev_exists")),
        glacier_fraction_report=diagnostics["glacier_fraction_report"],
        evidence_registry=evidence_registry,
        evaluation_basis=evaluation_basis,
    )
    peak_source_penalty, peak_source_term, peak_source_report, recession_takeover_report = _compute_peak_source_guard(
        dates=dates,
        q_rain=q_rain,
        q_snow=q_snow,
        q_ice=q_ice,
        q_score_base=q_score_base,
        calib_mask=calib_mask,
        glacier_enabled=bool(bundle.get("glacier_enabled", False)),
        glacier_model_mode=str(bundle.get("glacier_model_mode") or "unknown"),
        glacier_area_ratio=_to_float(bundle.get("glacier_area_ratio"), None),
        glacier_elev_exists=_to_optional_bool(bundle.get("glacier_elev_exists")),
        evidence_registry=evidence_registry,
        cryo_report=cryo_report,
        evaluation_basis=evaluation_basis,
    )
    cryo_penalty = float(cryo_penalty) + float(peak_source_penalty)
    cryo_terms["base_penalty"] = float(cryo_terms.get("penalty", 0.0) or 0.0)
    cryo_terms["penalty"] = float(cryo_penalty)
    cryo_terms["peak_source_guard"] = peak_source_term
    cryo_terms["recession_takeover_diagnostic"] = {
        "active": bool(recession_takeover_report.get("active", False)),
        "status": str(recession_takeover_report.get("status", "skipped")),
        "flagged_years": list(recession_takeover_report.get("flagged_years", []) or []),
        "diagnostic_report": "diagnostics.recession_takeover_diagnostic",
    }
    cryo_terms["ice_dominance_guard"] = ice_guard_term
    cryo_terms["guarded_penalty"] = float(cryo_terms.get("penalty", 0.0) or 0.0) + float(ice_guard_term.get("penalty", 0.0) or 0.0)

    diagnostics["cryo_timing_report"] = cryo_report
    diagnostics["peak_source_report"] = peak_source_report
    diagnostics["recession_takeover_diagnostic"] = recession_takeover_report
    diagnostics["process_signature_report"] = signature_report
    diagnostics["external_evidence_report"] = evidence_report
    diagnostics["gm_constraint"] = copy.deepcopy(evidence_report.get("gm_constraint", {}))

    nonflow_penalty_raw = float(seasonality_penalty + signatures_penalty + cryo_penalty + evidence_penalty)
    nonflow_penalty_capped = min(nonflow_penalty_raw, float(NONFLOW_CAP))
    secondary_terms = {
        "active": True,
        "status": "capped" if nonflow_penalty_raw > NONFLOW_CAP else "ok",
        "seasonality_penalty": float(seasonality_penalty),
        "process_signatures_penalty": float(signatures_penalty),
        "cryo_consistency_penalty": float(cryo_penalty),
        "external_evidence_penalty": float(evidence_penalty),
        "nonflow_penalty_raw": float(nonflow_penalty_raw),
        "nonflow_penalty_capped": float(nonflow_penalty_capped),
        "nonflow_cap": float(NONFLOW_CAP),
        "whether_capped": bool(nonflow_penalty_raw > NONFLOW_CAP),
        "note": "secondary terms are capped so they can rank acceptable flow solutions but not dominate flow fit",
    }
    objective_value = (
        flow_penalty
        + flow_guard_penalty
        + nonflow_penalty_capped
        + float(ice_guard_term.get("penalty", 0.0) or 0.0)
    )
    payload["objective_value"] = float(objective_value)
    payload["objective_terms"] = {
        "flow": flow_term,
        "flow_guard": flow_guard_term,
        "seasonality": seasonality_term,
        "process_signatures": signature_terms,
        "cryo_consistency": cryo_terms,
        "external_evidence": evidence_terms,
        "secondary_terms": secondary_terms,
    }
    if not math.isfinite(payload["objective_value"]):
        payload["objective_value"] = float(bad_obj)
    payload["diagnostics"] = diagnostics
    return payload
