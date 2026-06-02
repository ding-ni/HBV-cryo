#!/usr/bin/env python
# -*- coding: utf-8 -*-
from __future__ import annotations

from typing import Any


CALIBRATION_PARAM_NAMES = [
    "TT", "FC", "BETA", "LP",
    "RFCF", "SFCF",
    "CFR", "CWH",
    "CFMAX_low", "CFMAX_high",
    "K", "K1", "K2", "UZL", "PERC",
    "ICE_FACTOR", "K_MUSK", "X_MUSK",
]

DEFAULT_MANUAL_START_VECTOR = [
    -1.2, 1200.0, 1.0, 0.95, 1.0, 1.05,
    0.05, 0.05, 3.5, 5.5, 0.25, 0.05,
    0.005, 30.0, 1.8, 2.0, 1.2, 0.05,
]


def safe_float(value: Any) -> float | None:
    if value in (None, "", "nan", "NaN"):
        return None
    try:
        out = float(value)
    except Exception:
        return None
    if out != out:
        return None
    return out


def sanitize_param_values(params: dict[str, Any]) -> dict[str, float]:
    clean: dict[str, float] = {}
    for name in CALIBRATION_PARAM_NAMES:
        if name in params:
            value = safe_float(params[name])
            if value is None:
                raise ValueError(f"参数 {name} 不是有效数字。")
            clean[name] = float(value)
    if not clean:
        raise ValueError("参数集中没有可识别的 HBV 参数。")
    return clean


def build_runtime_param_vector(
    module: Any,
    params: dict[str, Any] | None,
    *,
    base_params: dict[str, Any] | None = None,
) -> tuple[list[float], dict[str, float], bool]:
    configure_time_step = getattr(module, "configure_time_step", None)
    if callable(configure_time_step):
        configure_time_step()

    merged: dict[str, float] = {}
    if base_params:
        merged.update(sanitize_param_values(dict(base_params)))
    if params:
        merged.update(sanitize_param_values(dict(params)))

    runtime_default: list[float] = []
    default_builder = getattr(module, "default_test_vector", None)
    if callable(default_builder):
        try:
            runtime_default = [float(v) for v in list(default_builder())]
        except Exception:
            runtime_default = []

    vector: list[float] = []
    for idx, name in enumerate(module.param_names):
        if name in merged:
            value = float(merged[name])
        elif idx < len(runtime_default):
            value = float(runtime_default[idx])
        elif idx < len(DEFAULT_MANUAL_START_VECTOR):
            value = float(DEFAULT_MANUAL_START_VECTOR[idx])
        else:
            value = 0.0
        vector.append(float(value))

    sanitized_vector = list(vector)
    sanitizer = getattr(module, "sanitize_initial_param_vector", None)
    if callable(sanitizer):
        try:
            sanitized_vector = [float(v) for v in list(sanitizer(vector))]
        except Exception:
            sanitized_vector = list(vector)

    validator = getattr(module, "validate_parameter_vector", None)
    if callable(validator):
        sanitized_vector = [float(v) for v in list(validator(sanitized_vector))]

    adjusted = any(abs(float(a) - float(b)) > 1e-10 for a, b in zip(vector, sanitized_vector))
    clean_params = {name: round(float(val), 6) for name, val in zip(module.param_names, sanitized_vector)}
    return sanitized_vector, clean_params, adjusted
