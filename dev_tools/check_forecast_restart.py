# -*- coding: utf-8 -*-
"""Synthetic continuity check for state-restart forecast mode."""

import importlib.util
import argparse
import math
import pathlib
import tempfile

import numpy as np
import pandas as pd


REPO_ROOT = pathlib.Path(__file__).resolve().parents[1]
CORE_PATH = REPO_ROOT / "HBV-Cryo" / "\u7387\u5b9a\u6838\u5fc3.py"


def load_core():
    spec = importlib.util.spec_from_file_location("hbv_core_forecast_restart_check", CORE_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def main():
    core = load_core()
    core.TIME_STEP_HOURS = 24.0
    core.MUSK_DT = 1.0
    core.args = argparse.Namespace(glacier_mode="inline")
    core.INIT_ST = np.array([8.0, 60.0, 12.0, 35.0, 1.5], dtype=np.float64)
    core.FIXED["E_CORR"] = 0.0
    core.GLACIER_MODEL_MODE = "binary_legacy"
    core.GLACIER_FRACTION_CELLS = None
    core.GLACIER_MASK = np.array([[False, True], [False, False]], dtype=bool)
    core.FLOW_ACC = np.array([[1.0, 1.0], [1.0, np.nan]], dtype=np.float32)
    core.BOUNDARY_INFLOW_ENABLED = False
    core.BOUNDARY_INFLOW_SERIES = None

    params = np.array([
        0.0, 120.0, 1.2, 0.85,
        1.0, 1.05,
        0.03, 0.08,
        2.4, 3.1,
        0.22, 0.08, 0.015, 5.0, 1.2,
        1.4, 1.3, 0.08,
    ], dtype=np.float64)
    par_base, ice_factor, k_musk, x_musk, cfmax_low, cfmax_high = core._forecast_par_base(params)

    prec = np.array([
        [4.0, 0.0, 18.0, 10.0, 0.0, 3.0],
        [2.0, 6.0, 12.0, 14.0, 4.0, 0.0],
        [0.0, 5.0, 10.0, 2.0, 6.0, 9.0],
    ], dtype=np.float32)
    temp = np.array([
        [-1.0, 1.0, 3.0, 4.0, 2.5, -0.5],
        [0.5, 2.0, 5.0, 4.5, 3.0, 1.0],
        [-2.0, -1.0, 1.5, 3.0, 5.0, 4.0],
    ], dtype=np.float32)
    evap = np.full_like(prec, 0.8, dtype=np.float32)
    ll_temp = np.zeros_like(prec, dtype=np.float32)
    zone_high = np.array([False, True, False], dtype=np.bool_)
    cell_scale = np.array([0.15, 0.20, 0.12], dtype=np.float64)
    glacier_cells = np.array([False, True, False], dtype=np.bool_)
    delta_t = np.array([0.0, -0.6, 0.0], dtype=np.float32)
    active = np.ones(3, dtype=np.bool_)

    init = core.INIT_ST
    init_state = (
        np.full(3, init[0], dtype=np.float32),
        np.full(3, init[1], dtype=np.float32),
        np.full(3, init[4], dtype=np.float32),
        np.full(3, init[2], dtype=np.float32),
        np.zeros(3, dtype=np.float32),
        np.zeros(3, dtype=np.float32),
        np.full(3, init[3], dtype=np.float32),
        np.zeros(3, dtype=np.float32),
        np.zeros(3, dtype=np.float32),
    )

    full = core.run_cells_from_state_flat(
        prec, temp, evap, ll_temp, par_base, zone_high,
        *init_state,
        active, cell_scale, glacier_cells, True, ice_factor, cfmax_low, cfmax_high, delta_t,
    )
    first = core.run_cells_from_state_flat(
        prec[:, :3], temp[:, :3], evap[:, :3], ll_temp[:, :3], par_base, zone_high,
        *init_state,
        active, cell_scale, glacier_cells, True, ice_factor, cfmax_low, cfmax_high, delta_t,
    )
    first_sim = core._route_forecast_series_set(
        first[0], np.zeros(3, dtype=np.float64), first[1], first[2], first[3],
        k_musk, x_musk, {},
    )
    full_sim = core._route_forecast_series_set(
        full[0], np.zeros(6, dtype=np.float64), full[1], full[2], full[3],
        k_musk, x_musk, {},
    )

    snapshot = {
        "valid_cell_rows": np.array([0, 0, 1], dtype=np.int32),
        "valid_cell_cols": np.array([0, 1, 0], dtype=np.int32),
        "zone_high_cells": zone_high.astype(np.uint8),
        "glacier_active_cells": glacier_cells.astype(np.uint8),
    }
    snapshot.update(core._state_branch_arrays("main_", first[4:]))
    core.append_routing_state_to_snapshot(snapshot, first_sim)

    core.PREC_CELLS = np.ascontiguousarray(prec[:, 3:], dtype=np.float32)
    core.TEMP_CELLS = np.ascontiguousarray(temp[:, 3:], dtype=np.float32)
    core.ET_CELLS = np.ascontiguousarray(evap[:, 3:], dtype=np.float32)
    core.LL_TEMP_CELLS = np.ascontiguousarray(ll_temp[:, 3:], dtype=np.float32)
    core.VALID_CELLS = np.array([[0, 0], [0, 1], [1, 0]], dtype=np.int64)
    core.ZONE_HIGH_CELLS = np.ascontiguousarray(zone_high, dtype=np.bool_)
    core.CELL_SCALE = cell_scale
    core.GLACIER_CELLS = np.ascontiguousarray(glacier_cells, dtype=np.bool_)
    core.GLACIER_DELTA_T_CELLS = np.ascontiguousarray(delta_t, dtype=np.float32)
    core.SIM_DATES = pd.date_range("2020-07-04", periods=3, freq="D")
    core.Q_OBS_FULL = np.full(3, np.nan, dtype=np.float64)

    with tempfile.TemporaryDirectory() as tmp:
        snapshot_path = pathlib.Path(tmp) / "state_snapshot.npz"
        np.savez_compressed(snapshot_path, **snapshot)
        forecast = core.run_forecast_from_state(params, snapshot_path=snapshot_path)

    for key in ("q_total", "q_local", "q_rain", "q_snow", "q_ice"):
        np.testing.assert_allclose(forecast[key], full_sim[key][3:], rtol=1e-6, atol=1e-6, err_msg=key)
    assert forecast["forecast_restart"]["status"] == "ok"
    assert forecast["forecast_restart"]["routing_state_available"] is True
    assert "forecast_state_snapshot_arrays" in forecast
    assert math.isfinite(float(forecast["forecast_state_snapshot_arrays"]["routing_q_total_out_last"][0]))

    print("forecast_restart_check=ok")


if __name__ == "__main__":
    main()
