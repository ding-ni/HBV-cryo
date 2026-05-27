# -*- coding: utf-8 -*-
import argparse
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
import os
import re
import sys
import threading
import time
from datetime import datetime
from glob import glob
from math import log, radians, sin
from multiprocessing.pool import ThreadPool
from types import SimpleNamespace

import numpy as np
import pandas as pd
import rasterio
from affine import Affine
from numba import njit
from scipy.optimize import differential_evolution

PUBLIC_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "公共"))
if PUBLIC_DIR not in sys.path:
    sys.path.insert(0, PUBLIC_DIR)
CURRENT_DIR = os.path.abspath(os.path.dirname(__file__))
if CURRENT_DIR not in sys.path:
    sys.path.insert(0, CURRENT_DIR)

from 观测径流处理 import DEFAULT_MIN_DAILY_HOURS, inspect_observed_discharge

import daily_unified_objective
from 上游边界入流 import read_boundary_inflow_series
from 公共函数 import infer_dem_kind_from_raster, resolve_workspace_dem_path


class _ExecutorThreadPool:
    def __init__(self, processes):
        self._executor = ThreadPoolExecutor(max_workers=max(1, int(processes)))

    def map(self, func, iterable):
        return list(self._executor.map(func, iterable))

    def close(self):
        self._executor.shutdown(wait=False, cancel_futures=False)

    def join(self):
        return None


def _json_safe_value(value):
    if isinstance(value, dict):
        return {key: _json_safe_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_json_safe_value(item) for item in value]
    if isinstance(value, np.ndarray):
        return _json_safe_value(value.tolist())
    if isinstance(value, np.generic):
        return _json_safe_value(value.item())
    if isinstance(value, float):
        return value if np.isfinite(value) else None
    return value


def json_dump_safe(data, fp, *, indent=2):
    json.dump(_json_safe_value(data), fp, indent=indent, ensure_ascii=False, allow_nan=False)


def _prefer_existing_path(*paths):
    for path in paths:
        if os.path.exists(path):
            return path
    return paths[0]


PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "运行目录", "默认流域"))
DATA_ROOT = _prefer_existing_path(os.path.join(PROJECT_ROOT, "数据"), os.path.join(PROJECT_ROOT, "data"))
ALIGNED_ROOT = _prefer_existing_path(os.path.join(DATA_ROOT, "模型输入"), os.path.join(DATA_ROOT, "aligned_masked"))
OBSERVED_ROOT = _prefer_existing_path(os.path.join(DATA_ROOT, "观测数据"), os.path.join(DATA_ROOT, "observed"))
GIS_ROOT = _prefer_existing_path(os.path.join(DATA_ROOT, "地理数据"), os.path.join(DATA_ROOT, "gis"))
RESULTS_ROOT = _prefer_existing_path(os.path.join(PROJECT_ROOT, "结果"), os.path.join(PROJECT_ROOT, "results"))
PREC_DIR_MSWEP = _prefer_existing_path(os.path.join(ALIGNED_ROOT, "降水_MSWEP"), os.path.join(ALIGNED_ROOT, "prec"))
PREC_DIR_CMFD = _prefer_existing_path(os.path.join(ALIGNED_ROOT, "降水_CMFD"), os.path.join(ALIGNED_ROOT, "prec_cmfd"))
PREC_DIR_ERA5 = _prefer_existing_path(os.path.join(ALIGNED_ROOT, "降水"), os.path.join(ALIGNED_ROOT, "precipitation"))
PREC_DIR = PREC_DIR_MSWEP
TEMP_DIR = _prefer_existing_path(os.path.join(ALIGNED_ROOT, "气温"), os.path.join(ALIGNED_ROOT, "temp"))
EVAP_DIR = _prefer_existing_path(os.path.join(ALIGNED_ROOT, "蒸散发"), os.path.join(ALIGNED_ROOT, "evap"))
GLACIER_MELT_DIR = _prefer_existing_path(os.path.join(ALIGNED_ROOT, "冰川融水"), os.path.join(ALIGNED_ROOT, "glacier_melt"))
OBS_FILE = os.path.join(OBSERVED_ROOT, "discharge.csv")
FLOW_ACC_PATH = os.path.join(GIS_ROOT, "flow_accumulation_masked.tif")
GLACIER_MASK_PATH = os.path.join(GIS_ROOT, "glacier_mask.tif")
GLACIER_FRACTION_PATH = os.path.join(GIS_ROOT, "glacier_fraction.tif")
GLACIER_ELEV_PATH = os.path.join(GIS_ROOT, "glacier_elev.tif")
LOG_DIR = _prefer_existing_path(os.path.join(RESULTS_ROOT, "日志"), os.path.join(RESULTS_ROOT, "logs"))
RUNS_DIR = _prefer_existing_path(os.path.join(RESULTS_ROOT, "运行记录"), os.path.join(RESULTS_ROOT, "runs"))
CACHE_DIR = _prefer_existing_path(os.path.join(RESULTS_ROOT, "缓存"), os.path.join(RESULTS_ROOT, "cache"))
BOUNDARY_INFLOW_FILE = ""
BOUNDARY_INFLOW_DATE_FIELD = "date"
BOUNDARY_INFLOW_FLOW_FIELD = "inflow_m3s"
BOUNDARY_INFLOW_GAP_FILL = "zero"

SWE_ICE_THRESHOLD_MM = 10.0
GLACIER_LAPSE_RATE_PER_M = 0.0065

GLACIER_FRAC_WINDOW = None
GLACIER_FRAC_WEIGHT = 0.25
SIGNATURE_SWR_ENABLED = True
SIGNATURE_SWR_WEIGHT = 0.20
SIGNATURE_SWR_TOL_RATIO = 0.20
SIGNATURE_PEAK_ENABLED = True
SIGNATURE_PEAK_WEIGHT = 0.10
SIGNATURE_PEAK_TOL_MONTHS = 1

EPS = 1e-12

FLOOD_EVENT_OBJECTIVE_FAMILY = "flood_event_calibration_v1"
FLOOD_EVENT_SCHEMA = "flood_event_evaluation_v1"
DEFAULT_FLOOD_EVENT_WEIGHTS = {
    "peak_flow_error": 0.30,
    "peak_time_error": 0.25,
    "volume_error": 0.25,
    "recession_error": 0.10,
    "high_flow_skill": 0.10,
}
FLOOD_EVENT_WEIGHT_ALIASES = {
    "洪峰流量误差": "peak_flow_error",
    "peak_flow_error": "peak_flow_error",
    "peak_error": "peak_flow_error",
    "峰现时间误差": "peak_time_error",
    "peak_time_error": "peak_time_error",
    "峰现误差": "peak_time_error",
    "洪量误差": "volume_error",
    "volume_error": "volume_error",
    "退水过程误差": "recession_error",
    "recession_error": "recession_error",
    "高流量加权NSE": "high_flow_skill",
    "高流量加权 NSE": "high_flow_skill",
    "high_flow_weighted_nse": "high_flow_skill",
    "高流量加权KGE": "high_flow_skill",
    "高流量加权 KGE": "high_flow_skill",
    "high_flow_kge": "high_flow_skill",
    "高流量过程效率": "high_flow_skill",
    "high_flow_skill": "high_flow_skill",
}
FLOOD_EVENT_OBJECTIVE_MODE_VALUES = {
    "objective",
    "event_objective",
    "flood_event_objective",
    "calibration",
    "event_calibration",
    "flood_event_calibration_v1",
    "目标函数",
    "事件目标函数",
    "事件率定",
    "洪水事件率定",
}
FLOOD_EVENT_CALIBRATION_TYPE_ALIASES = {"calibration", "calib", "train", "training", "率定", "训练"}

MUSK_DT = 1.0
BAD_OBJ = 1e6

TIME_STEP_HOURS = 24.0

CFMAX_ZONE_ELEV = 5000.0

WARMUP_START = "2006-01-01"
WARMUP_END = "2008-12-31"
CALIB_START = "2009-01-01"
CALIB_END = "2017-12-31"
VALID_START = "2018-01-01"
VALID_END = "2020-12-31"
SIM_START = WARMUP_START
SIM_END = VALID_END
OBS_MODE_OVERRIDE = "full_year"
OBS_MODE_APPLIED = "full_year"

PREC_3D = None
TEMP_3D = None
ET_3D = None
LL_TEMP_3D = None
PREC_CELLS = None
TEMP_CELLS = None
ET_CELLS = None
LL_TEMP_CELLS = None
FLOW_ACC = None
PX_AREA = None
VALID_CELLS = None
GLACIER_MASK = None
GLACIER_FRACTION = None
GLACIER_DELTA_T = None
ZONE_LOW = None
ZONE_HIGH = None
GLACIER_CELLS = None
GLACIER_FRACTION_CELLS = None
GLACIER_DELTA_T_CELLS = None
ZONE_HIGH_CELLS = None
CELL_SCALE = None
SIM_DATES = None
CALIB_MASK = None
VALID_MASK = None
Q_OBS_FULL = None
Q_OBS_OBJ = None
Q_OBS_CALIB = None
Q_OBS_VALID = None
WARMUP_STEPS = None
CATCHMENT_AREA = None
BOUNDARY_INFLOW_SERIES = None
BOUNDARY_INFLOW_ENABLED = False
GLACIER_MELT_REF_RAW = None
GLACIER_MODEL_MODE = "binary_legacy"
GLACIER_ELEV_STATUS = "unknown"
RELIABILITY_FLAG = "ok"
OBS_MONTHLY_CALIB = None
BASIN_GLACIER_AREA_FRACTION = float("nan")
PROJECT_OBJECT_TYPE = "full_upstream_basin"
FLOOD_EVENT_CONFIG = {}
EVENT_RUNTIME_ENABLED = False
EVENT_RUNTIME_MODE = "continuous"
EVENT_RUNTIME_DATES = None
EVENT_RUNTIME_WINDOWS = []
EVENT_RUNTIME_META = {}
EVENT_INITIAL_STATE_POLICY = "continuous_state"

RUN_ID = None
LOG_FILE = None
PROGRESS_FILE = None
PROGRESS_FILE_MAIN = None
PROGRESS_FILE_REFINE = None
eval_count = 0
gen_count = 0
best_score = -np.inf
best_objective = np.inf
best_params = None
DEBUG_WINDOW_INFO = None
start_time = None
args = None
STACK_CACHE_VERSION = 4
DATA_LOAD_SUMMARY = {}
OBJECTIVE_STATE_LOCK = threading.Lock()
OPTIMIZATION_STAGE_STATS = {}
CALIBRATION_WORKFLOW_SINGLE = "single_pass"
CALIBRATION_WORKFLOW_STAGED = "staged_calibration_v1"
CALIBRATION_WORKFLOW_SELECTED = CALIBRATION_WORKFLOW_SINGLE
STAGED_CALIBRATION_METADATA = {}


def calibration_workflow_status(workflow):
    workflow_key = str(workflow or CALIBRATION_WORKFLOW_SINGLE).strip().lower()
    if workflow_key == CALIBRATION_WORKFLOW_STAGED:
        return "experimental"
    return "default_production"

OBSERVED_DATE_COLUMN_HINTS = ("date", "datetime", "time", "日期", "时间")
OBSERVED_FLOW_COLUMN_HINTS = (
    "discharge (m3/s)",
    "discharge",
    "flow",
    "streamflow",
    "runoff",
    "q_obs",
    "流量",
    "径流",
    "观测流量",
    "观测径流",
)

param_names = [
    "TT", "FC", "BETA", "LP",
    "RFCF", "SFCF",
    "CFR", "CWH",
    "CFMAX_low", "CFMAX_high",
    "K", "K1", "K2", "UZL", "PERC",
    "ICE_FACTOR", "K_MUSK", "X_MUSK",
]

PARAM_BOUNDS_PROFILE_QTP = "qtp_alpine_default"
PARAM_BOUNDS_PROFILE_GENERIC = "generic_wide"
DEFAULT_PARAM_BOUNDS_PROFILE = PARAM_BOUNDS_PROFILE_QTP

PARAM_BOUNDS_PROFILE_LABELS = {
    PARAM_BOUNDS_PROFILE_QTP: "青藏高原高寒区默认范围",
    PARAM_BOUNDS_PROFILE_GENERIC: "通用宽范围",
}

PARAM_BOUNDS_PROFILE_NOTES = {
    PARAM_BOUNDS_PROFILE_QTP: "默认用于青藏高原高寒区率定，收窄土壤、雪冰和退水自由度，降低异参同效。",
    PARAM_BOUNDS_PROFILE_GENERIC: "保留原通用硬边界，适合资料较充分、先验不确定或需要放宽搜索的流域。",
}

GENERIC_PARAM_BOUNDS = [
    (-2.0, 2.0),
    (100.0, 1600.0),
    (0.5, 4.0),
    (0.2, 1.0),
    (0.8, 1.2),
    (0.5, 1.6),
    (0.0, 0.12),
    (0.01, 0.12),
    (2.0, 6.0),
    (3.0, 9.0),
    (0.02, 0.5),
    (0.01, 0.2),
    (0.0005, 0.02),
    (5.0, 80.0),
    (0.01, 6.0),
    (1.2, 4.5),
    (0.65, 2.6),
    (0.05, 0.35),
]

QTP_ALPINE_PARAM_BOUNDS = [
    (-1.5, 1.5),
    (150.0, 800.0),
    (1.0, 4.0),
    (0.3, 0.9),
    (0.8, 1.3),
    (0.75, 1.3),
    (0.0, 0.1),
    (0.03, 0.15),
    (1.5, 5.5),
    (2.5, 7.0),
    (0.03, 0.45),
    (0.01, 0.18),
    (0.0005, 0.03),
    (5.0, 70.0),
    (0.05, 4.0),
    (1.2, 3.2),
    (0.65, 2.6),
    (0.05, 0.35),
]

PARAM_BOUNDS_BY_PROFILE = {
    PARAM_BOUNDS_PROFILE_QTP: QTP_ALPINE_PARAM_BOUNDS,
    PARAM_BOUNDS_PROFILE_GENERIC: GENERIC_PARAM_BOUNDS,
}
PARAM_BOUNDS_PROFILE_SELECTED = DEFAULT_PARAM_BOUNDS_PROFILE
PARAM_BOUNDS = [tuple(bound) for bound in PARAM_BOUNDS_BY_PROFILE[PARAM_BOUNDS_PROFILE_SELECTED]]

FIXED = {
    "E_CORR": 0.0,
}

CALIBRATION_PROFILE = None
CALIBRATION_PROFILE_LABEL = ""
OBJECTIVE_FAMILY_DAILY = daily_unified_objective.OBJECTIVE_FAMILY
OBJECTIVE_MODE_SELECTED = "auto"
REQUESTED_OBJECTIVE_MODE = "auto"
OBJECTIVE_PROFILE = None
PARAMETER_PROFILE = None


def normalize_param_bounds_profile(value):
    raw = str(value or "").strip().lower()
    if raw in {"", "auto", "default", "qtp", "tibetan_plateau", "qinghai_tibet", "alpine", PARAM_BOUNDS_PROFILE_QTP}:
        return PARAM_BOUNDS_PROFILE_QTP
    if raw in {"generic", "wide", "universal", "legacy", PARAM_BOUNDS_PROFILE_GENERIC}:
        return PARAM_BOUNDS_PROFILE_GENERIC
    raise ValueError(f"未知参数边界档案：{value}")


def select_param_bounds_profile(value):
    global PARAM_BOUNDS_PROFILE_SELECTED, PARAM_BOUNDS, PARAMETER_PROFILE
    profile = normalize_param_bounds_profile(value)
    PARAM_BOUNDS_PROFILE_SELECTED = profile
    PARAM_BOUNDS = [tuple(bound) for bound in PARAM_BOUNDS_BY_PROFILE[profile]]
    PARAMETER_PROFILE = None
    return profile

INIT_ST = np.array([0.0, 5.0, 0.0, 0.0, 0.0], dtype=np.float64)


@njit(cache=False, fastmath=True, nogil=True)
def hbv_cell(prec, temp, et, ll_temp, par, init_st, is_glacier, ice_factor, glacier_delta_t):
    n = len(prec)
    q_uz = np.zeros(n, dtype=np.float32)
    q_lz = np.zeros(n, dtype=np.float32)
    q_rain = np.zeros(n, dtype=np.float32)
    q_snow = np.zeros(n, dtype=np.float32)
    q_ice = np.zeros(n, dtype=np.float32)

    tt, rfcf, sfcf, cfmax, cwh, cfr = par[0], par[1], par[2], par[3], par[4], par[5]
    fc, beta, e_corr, lp = par[6], par[7], par[8], par[9]
    k, k1, k2, uzl, perc = par[10], par[11], par[12], par[13], par[14]

    fc = max(fc, 10.0)
    beta = max(min(beta, 10.0), 0.1)
    lp = max(min(lp, 0.99), 0.01)

    sp, sm, init_uz, init_lz, wc = init_st[0], init_st[1], init_st[2], init_st[3], init_st[4]
    init_uz = max(float(init_uz), 0.0)
    init_lz = max(float(init_lz), 0.0)
    uz_r, uz_s, uz_i = init_uz, 0.0, 0.0
    lz_r, lz_s, lz_i = init_lz, 0.0, 0.0

    for i in range(n):
        p = prec[i]
        t = temp[i]
        e = et[i]
        tm = ll_temp[i]

        if np.isnan(p) or np.isnan(t) or np.isnan(e):
            continue

        p = max(p, 0.0)
        e = max(e, 0.0)

        t_eff = t + glacier_delta_t if is_glacier else t

        if t_eff <= tt:
            rf, sf = 0.0, p * sfcf
        else:
            rf, sf = p * rfcf, 0.0

        melt = 0.0
        ice_melt = 0.0
        if t_eff > tt:
            ddt = t_eff - tt
            avail_snow = sp + sf
            melt_pot_snow = cfmax * ddt
            melt = min(melt_pot_snow, avail_snow)
            sp = max(avail_snow - melt, 0.0)
            if is_glacier and (sp <= SWE_ICE_THRESHOLD_MM) and (melt_pot_snow > 0.0):
                f_snow = melt / (melt_pot_snow + EPS)
                if f_snow < 0.0:
                    f_snow = 0.0
                elif f_snow > 1.0:
                    f_snow = 1.0
                melt_pot_ice = (cfmax * ice_factor) * ddt
                ice_melt = max(melt_pot_ice * (1.0 - f_snow), 0.0)
            wc_int = wc + melt + rf + ice_melt
        else:
            refr = min(cfr * cfmax * (tt - t_eff), wc + rf)
            sp = sp + sf + refr
            wc_int = max(wc - refr + rf, 0.0)

        sp = min(sp, 10000.0)
        if wc_int > cwh * sp:
            inf = wc_int - cwh * sp
            wc = cwh * sp
        else:
            inf = 0.0
            wc = wc_int

        input_total = rf + melt + ice_melt
        den_in = input_total + EPS
        frac_r = rf / den_in
        frac_s = melt / den_in
        frac_i = ice_melt / den_in

        sm_ratio = min(max(sm / fc, 0.0), 1.0)
        r = (sm_ratio ** beta) * inf
        r_r = r * frac_r
        r_s = r * frac_s
        r_i = r * frac_i

        ep_adj = max((1.0 + (t_eff - tm) * e_corr) * e, 0.0)
        lp_fc = lp * fc
        if lp_fc > 0.001:
            ea = min(ep_adj, (sm / lp_fc) * ep_adj)
        else:
            ea = ep_adj
        ea = min(ea, sm)

        uz_r += r_r
        uz_s += r_s
        uz_i += r_i
        uz_int = uz_r + uz_s + uz_i
        sm = max(min(sm + inf - r - ea, fc), 0.0)

        perc_actual = min(perc, uz_int)
        den_uz = uz_int + EPS
        frac_ur = uz_r / den_uz
        frac_us = uz_s / den_uz
        frac_ui = uz_i / den_uz
        uz_r -= perc_actual * frac_ur
        uz_s -= perc_actual * frac_us
        uz_i -= perc_actual * frac_ui
        lz_r += perc_actual * frac_ur
        lz_s += perc_actual * frac_us
        lz_i += perc_actual * frac_ui

        uz_int2 = uz_r + uz_s + uz_i
        q0 = k * max(uz_int2 - uzl, 0.0)
        q1 = k1 * uz_int2
        if q0 + q1 > uz_int2:
            q0 = uz_int2 * 0.67
            q1 = uz_int2 * 0.33

        den_uz2 = uz_int2 + EPS
        frac_ur2 = uz_r / den_uz2
        frac_us2 = uz_s / den_uz2
        frac_ui2 = uz_i / den_uz2
        q0_r = q0 * frac_ur2
        q0_s = q0 * frac_us2
        q0_i = q0 * frac_ui2
        q1_r = q1 * frac_ur2
        q1_s = q1 * frac_us2
        q1_i = q1 * frac_ui2

        uz_r = max(uz_r - (q0_r + q1_r), 0.0)
        uz_s = max(uz_s - (q0_s + q1_s), 0.0)
        uz_i = max(uz_i - (q0_i + q1_i), 0.0)

        lz_int = lz_r + lz_s + lz_i
        q2 = k2 * lz_int
        if q2 > lz_int:
            q2 = lz_int

        den_lz = lz_int + EPS
        frac_lr = lz_r / den_lz
        frac_ls = lz_s / den_lz
        frac_li = lz_i / den_lz
        q2_r = q2 * frac_lr
        q2_s = q2 * frac_ls
        q2_i = q2 * frac_li

        lz_r = max(lz_r - q2_r, 0.0)
        lz_s = max(lz_s - q2_s, 0.0)
        lz_i = max(lz_i - q2_i, 0.0)

        q_uz[i] = q0 + q1
        q_lz[i] = q2
        q_rain[i] = q0_r + q1_r + q2_r
        q_snow[i] = q0_s + q1_s + q2_s
        q_ice[i] = q0_i + q1_i + q2_i

    return q_uz, q_lz, q_rain, q_snow, q_ice


@njit(cache=False, fastmath=True, nogil=True)
def run_all_cells(prec_3d, temp_3d, et_3d, ll_temp_3d, par_base, cfmax_grid, init_st,
                  valid_cells, cell_scale, glacier_mask, glacier_on, ice_factor):
    n_cells = valid_cells.shape[0]
    ts = prec_3d.shape[2]
    q_total = np.zeros(ts, dtype=np.float64)
    q_rain = np.zeros(ts, dtype=np.float64)
    q_snow = np.zeros(ts, dtype=np.float64)
    q_ice = np.zeros(ts, dtype=np.float64)

    tt = par_base[0]
    rfcf = par_base[1]
    sfcf = par_base[2]
    cwh = par_base[4]
    cfr = par_base[5]
    fc_base = par_base[6]
    beta_base = par_base[7]
    e_corr = par_base[8]
    lp_base = par_base[9]
    k = par_base[10]
    k1 = par_base[11]
    k2 = par_base[12]
    uzl = par_base[13]
    perc = par_base[14]

    fc_base = max(fc_base, 10.0)
    beta_base = max(min(beta_base, 10.0), 0.1)
    lp_base = max(min(lp_base, 0.99), 0.01)

    for idx in range(n_cells):
        x = valid_cells[idx, 0]
        y = valid_cells[idx, 1]
        scale = cell_scale[idx]
        cfmax = cfmax_grid[x, y]
        is_glacier = glacier_on and glacier_mask[x, y]
        sp = init_st[0]
        sm = init_st[1]
        init_uz = max(float(init_st[2]), 0.0)
        init_lz = max(float(init_st[3]), 0.0)
        wc = init_st[4]
        uz_r = init_uz
        uz_s = 0.0
        uz_i = 0.0
        lz_r = init_lz
        lz_s = 0.0
        lz_i = 0.0

        for t_idx in range(ts):
            p = prec_3d[x, y, t_idx]
            t = temp_3d[x, y, t_idx]
            e = et_3d[x, y, t_idx]
            tm = ll_temp_3d[x, y, t_idx]

            if np.isnan(p) or np.isnan(t) or np.isnan(e):
                continue

            p = max(p, 0.0)
            e = max(e, 0.0)

            if t <= tt:
                rf = 0.0
                sf = p * sfcf
            else:
                rf = p * rfcf
                sf = 0.0

            melt = 0.0
            ice_melt = 0.0
            if t > tt:
                ddt = t - tt
                avail_snow = sp + sf
                melt_pot_snow = cfmax * ddt
                melt = min(melt_pot_snow, avail_snow)
                sp = max(avail_snow - melt, 0.0)
                if is_glacier and (sp <= SWE_ICE_THRESHOLD_MM) and (melt_pot_snow > 0.0):
                    f_snow = melt / (melt_pot_snow + EPS)
                    if f_snow < 0.0:
                        f_snow = 0.0
                    elif f_snow > 1.0:
                        f_snow = 1.0
                    melt_pot_ice = (cfmax * ice_factor) * ddt
                    ice_melt = max(melt_pot_ice * (1.0 - f_snow), 0.0)
                wc_int = wc + melt + rf + ice_melt
            else:
                refr = min(cfr * cfmax * (tt - t), wc + rf)
                sp = sp + sf + refr
                wc_int = max(wc - refr + rf, 0.0)

            sp = min(sp, 10000.0)
            if wc_int > cwh * sp:
                inf = wc_int - cwh * sp
                wc = cwh * sp
            else:
                inf = 0.0
                wc = wc_int

            input_total = rf + melt + ice_melt
            den_in = input_total + EPS
            frac_r = rf / den_in
            frac_s = melt / den_in
            frac_i = ice_melt / den_in

            sm_ratio = min(max(sm / fc_base, 0.0), 1.0)
            r = (sm_ratio ** beta_base) * inf
            r_r = r * frac_r
            r_s = r * frac_s
            r_i = r * frac_i

            ep_adj = max((1.0 + (t - tm) * e_corr) * e, 0.0)
            lp_fc = lp_base * fc_base
            if lp_fc > 0.001:
                ea = min(ep_adj, (sm / lp_fc) * ep_adj)
            else:
                ea = ep_adj
            ea = min(ea, sm)

            uz_r += r_r
            uz_s += r_s
            uz_i += r_i
            uz_int = uz_r + uz_s + uz_i
            sm = max(min(sm + inf - r - ea, fc_base), 0.0)

            perc_actual = min(perc, uz_int)
            den_uz = uz_int + EPS
            frac_ur = uz_r / den_uz
            frac_us = uz_s / den_uz
            frac_ui = uz_i / den_uz
            uz_r -= perc_actual * frac_ur
            uz_s -= perc_actual * frac_us
            uz_i -= perc_actual * frac_ui
            lz_r += perc_actual * frac_ur
            lz_s += perc_actual * frac_us
            lz_i += perc_actual * frac_ui

            uz_int2 = uz_r + uz_s + uz_i
            q0 = k * max(uz_int2 - uzl, 0.0)
            q1 = k1 * uz_int2
            if q0 + q1 > uz_int2:
                q0 = uz_int2 * 0.67
                q1 = uz_int2 * 0.33

            den_uz2 = uz_int2 + EPS
            frac_ur2 = uz_r / den_uz2
            frac_us2 = uz_s / den_uz2
            frac_ui2 = uz_i / den_uz2
            q0_r = q0 * frac_ur2
            q0_s = q0 * frac_us2
            q0_i = q0 * frac_ui2
            q1_r = q1 * frac_ur2
            q1_s = q1 * frac_us2
            q1_i = q1 * frac_ui2

            uz_r = max(uz_r - (q0_r + q1_r), 0.0)
            uz_s = max(uz_s - (q0_s + q1_s), 0.0)
            uz_i = max(uz_i - (q0_i + q1_i), 0.0)

            lz_int = lz_r + lz_s + lz_i
            q2 = k2 * lz_int
            if q2 > lz_int:
                q2 = lz_int

            den_lz = lz_int + EPS
            frac_lr = lz_r / den_lz
            frac_ls = lz_s / den_lz
            frac_li = lz_i / den_lz
            q2_r = q2 * frac_lr
            q2_s = q2 * frac_ls
            q2_i = q2 * frac_li

            lz_r = max(lz_r - q2_r, 0.0)
            lz_s = max(lz_s - q2_s, 0.0)
            lz_i = max(lz_i - q2_i, 0.0)

            q_total[t_idx] += (q0 + q1 + q2) * scale
            q_rain[t_idx] += (q0_r + q1_r + q2_r) * scale
            q_snow[t_idx] += (q0_s + q1_s + q2_s) * scale
            q_ice[t_idx] += (q0_i + q1_i + q2_i) * scale

    return q_total, q_rain, q_snow, q_ice


@njit(cache=False, fastmath=True, nogil=True)
def run_all_cells_total_only(prec_3d, temp_3d, et_3d, ll_temp_3d, par_base, cfmax_grid, init_st,
                             valid_cells, cell_scale, glacier_mask, glacier_on, ice_factor):
    n_cells = valid_cells.shape[0]
    ts = prec_3d.shape[2]
    q_total = np.zeros(ts, dtype=np.float64)

    tt = par_base[0]
    rfcf = par_base[1]
    sfcf = par_base[2]
    cwh = par_base[4]
    cfr = par_base[5]
    fc_base = max(par_base[6], 10.0)
    beta_base = max(min(par_base[7], 10.0), 0.1)
    e_corr = par_base[8]
    lp_base = max(min(par_base[9], 0.99), 0.01)
    k = par_base[10]
    k1 = par_base[11]
    k2 = par_base[12]
    uzl = par_base[13]
    perc = par_base[14]

    for idx in range(n_cells):
        x = valid_cells[idx, 0]
        y = valid_cells[idx, 1]
        scale = cell_scale[idx]
        cfmax = cfmax_grid[x, y]
        is_glacier = glacier_on and glacier_mask[x, y]

        sp = init_st[0]
        sm = init_st[1]
        wc = init_st[4]
        uz = max(float(init_st[2]), 0.0)
        lz = max(float(init_st[3]), 0.0)

        for t_idx in range(ts):
            p = prec_3d[x, y, t_idx]
            t = temp_3d[x, y, t_idx]
            e = et_3d[x, y, t_idx]
            tm = ll_temp_3d[x, y, t_idx]

            if np.isnan(p) or np.isnan(t) or np.isnan(e):
                continue

            p = max(p, 0.0)
            e = max(e, 0.0)

            if t <= tt:
                rf = 0.0
                sf = p * sfcf
            else:
                rf = p * rfcf
                sf = 0.0

            melt = 0.0
            ice_melt = 0.0
            if t > tt:
                ddt = t - tt
                avail_snow = sp + sf
                melt_pot_snow = cfmax * ddt
                melt = min(melt_pot_snow, avail_snow)
                sp = max(avail_snow - melt, 0.0)
                if is_glacier and (sp <= SWE_ICE_THRESHOLD_MM) and (melt_pot_snow > 0.0):
                    f_snow = melt / (melt_pot_snow + EPS)
                    if f_snow < 0.0:
                        f_snow = 0.0
                    elif f_snow > 1.0:
                        f_snow = 1.0
                    melt_pot_ice = (cfmax * ice_factor) * ddt
                    ice_melt = max(melt_pot_ice * (1.0 - f_snow), 0.0)
                wc_int = wc + melt + rf + ice_melt
            else:
                refr = min(cfr * cfmax * (tt - t), wc + rf)
                sp = sp + sf + refr
                wc_int = max(wc - refr + rf, 0.0)

            sp = min(sp, 10000.0)
            if wc_int > cwh * sp:
                inf = wc_int - cwh * sp
                wc = cwh * sp
            else:
                inf = 0.0
                wc = wc_int

            sm_ratio = min(max(sm / fc_base, 0.0), 1.0)
            recharge = (sm_ratio ** beta_base) * inf

            ep_adj = max((1.0 + (t - tm) * e_corr) * e, 0.0)
            lp_fc = lp_base * fc_base
            if lp_fc > 0.001:
                ea = min(ep_adj, (sm / lp_fc) * ep_adj)
            else:
                ea = ep_adj
            ea = min(ea, sm)

            uz += recharge
            sm = max(min(sm + inf - recharge - ea, fc_base), 0.0)

            perc_actual = min(perc, uz)
            uz -= perc_actual
            lz += perc_actual

            q0 = k * max(uz - uzl, 0.0)
            q1 = k1 * uz
            if q0 + q1 > uz:
                q0 = uz * 0.67
                q1 = uz * 0.33
            uz = max(uz - (q0 + q1), 0.0)

            q2 = k2 * lz
            if q2 > lz:
                q2 = lz
            lz = max(lz - q2, 0.0)

            q_total[t_idx] += (q0 + q1 + q2) * scale

    return q_total


@njit(cache=False, fastmath=True, nogil=True)
def run_all_cells_total_ice(prec_3d, temp_3d, et_3d, ll_temp_3d, par_base, cfmax_grid, init_st,
                            valid_cells, cell_scale, glacier_mask, glacier_on, ice_factor):
    n_cells = valid_cells.shape[0]
    ts = prec_3d.shape[2]
    q_total = np.zeros(ts, dtype=np.float64)
    q_ice = np.zeros(ts, dtype=np.float64)

    tt = par_base[0]
    rfcf = par_base[1]
    sfcf = par_base[2]
    cwh = par_base[4]
    cfr = par_base[5]
    fc_base = max(par_base[6], 10.0)
    beta_base = max(min(par_base[7], 10.0), 0.1)
    e_corr = par_base[8]
    lp_base = max(min(par_base[9], 0.99), 0.01)
    k = par_base[10]
    k1 = par_base[11]
    k2 = par_base[12]
    uzl = par_base[13]
    perc = par_base[14]

    for idx in range(n_cells):
        x = valid_cells[idx, 0]
        y = valid_cells[idx, 1]
        scale = cell_scale[idx]
        cfmax = cfmax_grid[x, y]
        is_glacier = glacier_on and glacier_mask[x, y]

        sp = init_st[0]
        sm = init_st[1]
        wc = init_st[4]
        uz = max(float(init_st[2]), 0.0)
        lz = max(float(init_st[3]), 0.0)
        uz_i = 0.0
        lz_i = 0.0

        for t_idx in range(ts):
            p = prec_3d[x, y, t_idx]
            t = temp_3d[x, y, t_idx]
            e = et_3d[x, y, t_idx]
            tm = ll_temp_3d[x, y, t_idx]

            if np.isnan(p) or np.isnan(t) or np.isnan(e):
                continue

            p = max(p, 0.0)
            e = max(e, 0.0)

            if t <= tt:
                rf = 0.0
                sf = p * sfcf
            else:
                rf = p * rfcf
                sf = 0.0

            melt = 0.0
            ice_melt = 0.0
            if t > tt:
                ddt = t - tt
                avail_snow = sp + sf
                melt_pot_snow = cfmax * ddt
                melt = min(melt_pot_snow, avail_snow)
                sp = max(avail_snow - melt, 0.0)
                if is_glacier and (sp <= SWE_ICE_THRESHOLD_MM) and (melt_pot_snow > 0.0):
                    f_snow = melt / (melt_pot_snow + EPS)
                    if f_snow < 0.0:
                        f_snow = 0.0
                    elif f_snow > 1.0:
                        f_snow = 1.0
                    melt_pot_ice = (cfmax * ice_factor) * ddt
                    ice_melt = max(melt_pot_ice * (1.0 - f_snow), 0.0)
                wc_int = wc + melt + rf + ice_melt
            else:
                refr = min(cfr * cfmax * (tt - t), wc + rf)
                sp = sp + sf + refr
                wc_int = max(wc - refr + rf, 0.0)

            sp = min(sp, 10000.0)
            if wc_int > cwh * sp:
                inf = wc_int - cwh * sp
                wc = cwh * sp
            else:
                inf = 0.0
                wc = wc_int

            input_total = rf + melt + ice_melt
            frac_i = ice_melt / (input_total + EPS)
            sm_ratio = min(max(sm / fc_base, 0.0), 1.0)
            recharge = (sm_ratio ** beta_base) * inf
            recharge_i = recharge * frac_i

            ep_adj = max((1.0 + (t - tm) * e_corr) * e, 0.0)
            lp_fc = lp_base * fc_base
            if lp_fc > 0.001:
                ea = min(ep_adj, (sm / lp_fc) * ep_adj)
            else:
                ea = ep_adj
            ea = min(ea, sm)

            uz += recharge
            uz_i += recharge_i
            sm = max(min(sm + inf - recharge - ea, fc_base), 0.0)

            perc_actual = min(perc, uz)
            frac_uz_i = uz_i / (uz + EPS)
            perc_i = perc_actual * frac_uz_i
            uz -= perc_actual
            uz_i -= perc_i
            lz += perc_actual
            lz_i += perc_i

            q0 = k * max(uz - uzl, 0.0)
            q1 = k1 * uz
            if q0 + q1 > uz:
                q0 = uz * 0.67
                q1 = uz * 0.33

            frac_uz_i2 = uz_i / (uz + EPS)
            q0_i = q0 * frac_uz_i2
            q1_i = q1 * frac_uz_i2

            uz -= (q0 + q1)
            uz_i = max(uz_i - (q0_i + q1_i), 0.0)

            q2 = k2 * lz
            if q2 > lz:
                q2 = lz
            frac_lz_i = lz_i / (lz + EPS)
            q2_i = q2 * frac_lz_i
            lz -= q2
            lz_i = max(lz_i - q2_i, 0.0)

            q_total[t_idx] += (q0 + q1 + q2) * scale
            q_ice[t_idx] += (q0_i + q1_i + q2_i) * scale

    return q_total, q_ice


@njit(cache=False, fastmath=True, nogil=True)
def run_all_cells_flat(prec_cells, temp_cells, et_cells, ll_temp_cells, par_base, zone_high_cells,
                       init_st, cell_scale, glacier_cells, glacier_on, ice_factor,
                       cfmax_low, cfmax_high, glacier_delta_t_cells):
    n_cells = prec_cells.shape[0]
    ts = prec_cells.shape[1]
    q_total = np.zeros(ts, dtype=np.float64)
    q_rain = np.zeros(ts, dtype=np.float64)
    q_snow = np.zeros(ts, dtype=np.float64)
    q_ice = np.zeros(ts, dtype=np.float64)

    tt = par_base[0]
    rfcf = par_base[1]
    sfcf = par_base[2]
    cwh = par_base[4]
    cfr = par_base[5]
    fc_base = max(par_base[6], 10.0)
    beta_base = max(min(par_base[7], 10.0), 0.1)
    e_corr = par_base[8]
    lp_base = max(min(par_base[9], 0.99), 0.01)
    k = par_base[10]
    k1 = par_base[11]
    k2 = par_base[12]
    uzl = par_base[13]
    perc = par_base[14]

    for idx in range(n_cells):
        scale = cell_scale[idx]
        cfmax = cfmax_high if zone_high_cells[idx] else cfmax_low
        is_glacier = glacier_on and glacier_cells[idx]
        delta_t_here = glacier_delta_t_cells[idx] if is_glacier else 0.0

        sp = init_st[0]
        sm = init_st[1]
        init_uz = max(float(init_st[2]), 0.0)
        init_lz = max(float(init_st[3]), 0.0)
        wc = init_st[4]
        uz_r = init_uz
        uz_s = 0.0
        uz_i = 0.0
        lz_r = init_lz
        lz_s = 0.0
        lz_i = 0.0

        for t_idx in range(ts):
            p = prec_cells[idx, t_idx]
            t = temp_cells[idx, t_idx]
            e = et_cells[idx, t_idx]
            tm = ll_temp_cells[idx, t_idx]

            if np.isnan(p) or np.isnan(t) or np.isnan(e):
                continue

            p = max(p, 0.0)
            e = max(e, 0.0)

            t_eff = t + delta_t_here

            if t_eff <= tt:
                rf = 0.0
                sf = p * sfcf
            else:
                rf = p * rfcf
                sf = 0.0

            melt = 0.0
            ice_melt = 0.0
            if t_eff > tt:
                ddt = t_eff - tt
                avail_snow = sp + sf
                melt_pot_snow = cfmax * ddt
                melt = min(melt_pot_snow, avail_snow)
                sp = max(avail_snow - melt, 0.0)
                if is_glacier and (sp <= SWE_ICE_THRESHOLD_MM) and (melt_pot_snow > 0.0):
                    f_snow = melt / (melt_pot_snow + EPS)
                    if f_snow < 0.0:
                        f_snow = 0.0
                    elif f_snow > 1.0:
                        f_snow = 1.0
                    melt_pot_ice = (cfmax * ice_factor) * ddt
                    ice_melt = max(melt_pot_ice * (1.0 - f_snow), 0.0)
                wc_int = wc + melt + rf + ice_melt
            else:
                refr = min(cfr * cfmax * (tt - t_eff), wc + rf)
                sp = sp + sf + refr
                wc_int = max(wc - refr + rf, 0.0)

            sp = min(sp, 10000.0)
            if wc_int > cwh * sp:
                inf = wc_int - cwh * sp
                wc = cwh * sp
            else:
                inf = 0.0
                wc = wc_int

            input_total = rf + melt + ice_melt
            den_in = input_total + EPS
            frac_r = rf / den_in
            frac_s = melt / den_in
            frac_i = ice_melt / den_in

            sm_ratio = min(max(sm / fc_base, 0.0), 1.0)
            recharge = (sm_ratio ** beta_base) * inf
            r_r = recharge * frac_r
            r_s = recharge * frac_s
            r_i = recharge * frac_i

            ep_adj = max((1.0 + (t_eff - tm) * e_corr) * e, 0.0)
            lp_fc = lp_base * fc_base
            if lp_fc > 0.001:
                ea = min(ep_adj, (sm / lp_fc) * ep_adj)
            else:
                ea = ep_adj
            ea = min(ea, sm)

            uz_r += r_r
            uz_s += r_s
            uz_i += r_i
            uz_int = uz_r + uz_s + uz_i
            sm = max(min(sm + inf - recharge - ea, fc_base), 0.0)

            perc_actual = min(perc, uz_int)
            den_uz = uz_int + EPS
            frac_ur = uz_r / den_uz
            frac_us = uz_s / den_uz
            frac_ui = uz_i / den_uz
            uz_r -= perc_actual * frac_ur
            uz_s -= perc_actual * frac_us
            uz_i -= perc_actual * frac_ui
            lz_r += perc_actual * frac_ur
            lz_s += perc_actual * frac_us
            lz_i += perc_actual * frac_ui

            uz_int2 = uz_r + uz_s + uz_i
            q0 = k * max(uz_int2 - uzl, 0.0)
            q1 = k1 * uz_int2
            if q0 + q1 > uz_int2:
                q0 = uz_int2 * 0.67
                q1 = uz_int2 * 0.33

            den_uz2 = uz_int2 + EPS
            frac_ur2 = uz_r / den_uz2
            frac_us2 = uz_s / den_uz2
            frac_ui2 = uz_i / den_uz2
            q0_r = q0 * frac_ur2
            q0_s = q0 * frac_us2
            q0_i = q0 * frac_ui2
            q1_r = q1 * frac_ur2
            q1_s = q1 * frac_us2
            q1_i = q1 * frac_ui2

            uz_r = max(uz_r - (q0_r + q1_r), 0.0)
            uz_s = max(uz_s - (q0_s + q1_s), 0.0)
            uz_i = max(uz_i - (q0_i + q1_i), 0.0)

            lz_int = lz_r + lz_s + lz_i
            q2 = k2 * lz_int
            if q2 > lz_int:
                q2 = lz_int

            den_lz = lz_int + EPS
            frac_lr = lz_r / den_lz
            frac_ls = lz_s / den_lz
            frac_li = lz_i / den_lz
            q2_r = q2 * frac_lr
            q2_s = q2 * frac_ls
            q2_i = q2 * frac_li

            lz_r = max(lz_r - q2_r, 0.0)
            lz_s = max(lz_s - q2_s, 0.0)
            lz_i = max(lz_i - q2_i, 0.0)

            q_total[t_idx] += (q0 + q1 + q2) * scale
            q_rain[t_idx] += (q0_r + q1_r + q2_r) * scale
            q_snow[t_idx] += (q0_s + q1_s + q2_s) * scale
            q_ice[t_idx] += (q0_i + q1_i + q2_i) * scale

    return q_total, q_rain, q_snow, q_ice


@njit(cache=False, fastmath=True, nogil=True)
def run_cells_from_state_flat(prec_cells, temp_cells, et_cells, ll_temp_cells, par_base, zone_high_cells,
                              state_sp, state_sm, state_wc,
                              state_uz_r, state_uz_s, state_uz_i,
                              state_lz_r, state_lz_s, state_lz_i,
                              active_cells, cell_scale, glacier_cells, glacier_on, ice_factor,
                              cfmax_low, cfmax_high, glacier_delta_t_cells):
    n_cells = prec_cells.shape[0]
    ts = prec_cells.shape[1]
    q_total = np.zeros(ts, dtype=np.float64)
    q_rain = np.zeros(ts, dtype=np.float64)
    q_snow = np.zeros(ts, dtype=np.float64)
    q_ice = np.zeros(ts, dtype=np.float64)

    sp_end = np.full(n_cells, np.nan, dtype=np.float32)
    sm_end = np.full(n_cells, np.nan, dtype=np.float32)
    wc_end = np.full(n_cells, np.nan, dtype=np.float32)
    uz_r_end = np.full(n_cells, np.nan, dtype=np.float32)
    uz_s_end = np.full(n_cells, np.nan, dtype=np.float32)
    uz_i_end = np.full(n_cells, np.nan, dtype=np.float32)
    lz_r_end = np.full(n_cells, np.nan, dtype=np.float32)
    lz_s_end = np.full(n_cells, np.nan, dtype=np.float32)
    lz_i_end = np.full(n_cells, np.nan, dtype=np.float32)

    tt = par_base[0]
    rfcf = par_base[1]
    sfcf = par_base[2]
    cwh = par_base[4]
    cfr = par_base[5]
    fc_base = max(par_base[6], 10.0)
    beta_base = max(min(par_base[7], 10.0), 0.1)
    e_corr = par_base[8]
    lp_base = max(min(par_base[9], 0.99), 0.01)
    k = par_base[10]
    k1 = par_base[11]
    k2 = par_base[12]
    uzl = par_base[13]
    perc = par_base[14]

    for idx in range(n_cells):
        if not active_cells[idx]:
            continue

        scale = cell_scale[idx]
        cfmax = cfmax_high if zone_high_cells[idx] else cfmax_low
        is_glacier = glacier_on and glacier_cells[idx]
        delta_t_here = glacier_delta_t_cells[idx] if is_glacier else 0.0

        sp = state_sp[idx]
        sm = state_sm[idx]
        wc = state_wc[idx]
        uz_r = state_uz_r[idx]
        uz_s = state_uz_s[idx]
        uz_i = state_uz_i[idx]
        lz_r = state_lz_r[idx]
        lz_s = state_lz_s[idx]
        lz_i = state_lz_i[idx]
        if np.isnan(sp):
            sp = 0.0
        if np.isnan(sm):
            sm = 0.0
        if np.isnan(wc):
            wc = 0.0
        if np.isnan(uz_r):
            uz_r = 0.0
        if np.isnan(uz_s):
            uz_s = 0.0
        if np.isnan(uz_i):
            uz_i = 0.0
        if np.isnan(lz_r):
            lz_r = 0.0
        if np.isnan(lz_s):
            lz_s = 0.0
        if np.isnan(lz_i):
            lz_i = 0.0

        for t_idx in range(ts):
            p = prec_cells[idx, t_idx]
            t = temp_cells[idx, t_idx]
            e = et_cells[idx, t_idx]
            tm = ll_temp_cells[idx, t_idx]

            if np.isnan(p) or np.isnan(t) or np.isnan(e):
                continue

            p = max(p, 0.0)
            e = max(e, 0.0)

            t_eff = t + delta_t_here

            if t_eff <= tt:
                rf = 0.0
                sf = p * sfcf
            else:
                rf = p * rfcf
                sf = 0.0

            melt = 0.0
            ice_melt = 0.0
            if t_eff > tt:
                ddt = t_eff - tt
                avail_snow = sp + sf
                melt_pot_snow = cfmax * ddt
                melt = min(melt_pot_snow, avail_snow)
                sp = max(avail_snow - melt, 0.0)
                if is_glacier and (sp <= SWE_ICE_THRESHOLD_MM) and (melt_pot_snow > 0.0):
                    f_snow = melt / (melt_pot_snow + EPS)
                    if f_snow < 0.0:
                        f_snow = 0.0
                    elif f_snow > 1.0:
                        f_snow = 1.0
                    melt_pot_ice = (cfmax * ice_factor) * ddt
                    ice_melt = max(melt_pot_ice * (1.0 - f_snow), 0.0)
                wc_int = wc + melt + rf + ice_melt
            else:
                refr = min(cfr * cfmax * (tt - t_eff), wc + rf)
                sp = sp + sf + refr
                wc_int = max(wc - refr + rf, 0.0)

            sp = min(sp, 10000.0)
            if wc_int > cwh * sp:
                inf = wc_int - cwh * sp
                wc = cwh * sp
            else:
                inf = 0.0
                wc = wc_int

            input_total = rf + melt + ice_melt
            den_in = input_total + EPS
            frac_r = rf / den_in
            frac_s = melt / den_in
            frac_i = ice_melt / den_in

            sm_ratio = min(max(sm / fc_base, 0.0), 1.0)
            recharge = (sm_ratio ** beta_base) * inf
            r_r = recharge * frac_r
            r_s = recharge * frac_s
            r_i = recharge * frac_i

            ep_adj = max((1.0 + (t_eff - tm) * e_corr) * e, 0.0)
            lp_fc = lp_base * fc_base
            if lp_fc > 0.001:
                ea = min(ep_adj, (sm / lp_fc) * ep_adj)
            else:
                ea = ep_adj
            ea = min(ea, sm)

            uz_r += r_r
            uz_s += r_s
            uz_i += r_i
            uz_int = uz_r + uz_s + uz_i
            sm = max(min(sm + inf - recharge - ea, fc_base), 0.0)

            perc_actual = min(perc, uz_int)
            den_uz = uz_int + EPS
            frac_ur = uz_r / den_uz
            frac_us = uz_s / den_uz
            frac_ui = uz_i / den_uz
            uz_r -= perc_actual * frac_ur
            uz_s -= perc_actual * frac_us
            uz_i -= perc_actual * frac_ui
            lz_r += perc_actual * frac_ur
            lz_s += perc_actual * frac_us
            lz_i += perc_actual * frac_ui

            uz_int2 = uz_r + uz_s + uz_i
            q0 = k * max(uz_int2 - uzl, 0.0)
            q1 = k1 * uz_int2
            if q0 + q1 > uz_int2:
                q0 = uz_int2 * 0.67
                q1 = uz_int2 * 0.33

            den_uz2 = uz_int2 + EPS
            frac_ur2 = uz_r / den_uz2
            frac_us2 = uz_s / den_uz2
            frac_ui2 = uz_i / den_uz2
            q0_r = q0 * frac_ur2
            q0_s = q0 * frac_us2
            q0_i = q0 * frac_ui2
            q1_r = q1 * frac_ur2
            q1_s = q1 * frac_us2
            q1_i = q1 * frac_ui2

            uz_r = max(uz_r - (q0_r + q1_r), 0.0)
            uz_s = max(uz_s - (q0_s + q1_s), 0.0)
            uz_i = max(uz_i - (q0_i + q1_i), 0.0)

            lz_int = lz_r + lz_s + lz_i
            q2 = k2 * lz_int
            if q2 > lz_int:
                q2 = lz_int

            den_lz = lz_int + EPS
            frac_lr = lz_r / den_lz
            frac_ls = lz_s / den_lz
            frac_li = lz_i / den_lz
            q2_r = q2 * frac_lr
            q2_s = q2 * frac_ls
            q2_i = q2 * frac_li

            lz_r = max(lz_r - q2_r, 0.0)
            lz_s = max(lz_s - q2_s, 0.0)
            lz_i = max(lz_i - q2_i, 0.0)

            q_total[t_idx] += (q0 + q1 + q2) * scale
            q_rain[t_idx] += (q0_r + q1_r + q2_r) * scale
            q_snow[t_idx] += (q0_s + q1_s + q2_s) * scale
            q_ice[t_idx] += (q0_i + q1_i + q2_i) * scale

        sp_end[idx] = sp
        sm_end[idx] = sm
        wc_end[idx] = wc
        uz_r_end[idx] = uz_r
        uz_s_end[idx] = uz_s
        uz_i_end[idx] = uz_i
        lz_r_end[idx] = lz_r
        lz_s_end[idx] = lz_s
        lz_i_end[idx] = lz_i

    return (
        q_total, q_rain, q_snow, q_ice,
        sp_end, sm_end, wc_end,
        uz_r_end, uz_s_end, uz_i_end,
        lz_r_end, lz_s_end, lz_i_end,
    )


@njit(cache=False, fastmath=True, nogil=True)
def run_all_cells_total_only_flat(prec_cells, temp_cells, et_cells, ll_temp_cells, par_base, zone_high_cells,
                                  init_st, cell_scale, glacier_cells, glacier_on, ice_factor,
                                  cfmax_low, cfmax_high, glacier_delta_t_cells):
    n_cells = prec_cells.shape[0]
    ts = prec_cells.shape[1]
    q_total = np.zeros(ts, dtype=np.float64)

    tt = par_base[0]
    rfcf = par_base[1]
    sfcf = par_base[2]
    cwh = par_base[4]
    cfr = par_base[5]
    fc_base = max(par_base[6], 10.0)
    beta_base = max(min(par_base[7], 10.0), 0.1)
    e_corr = par_base[8]
    lp_base = max(min(par_base[9], 0.99), 0.01)
    k = par_base[10]
    k1 = par_base[11]
    k2 = par_base[12]
    uzl = par_base[13]
    perc = par_base[14]

    for idx in range(n_cells):
        scale = cell_scale[idx]
        cfmax = cfmax_high if zone_high_cells[idx] else cfmax_low
        is_glacier = glacier_on and glacier_cells[idx]
        delta_t_here = glacier_delta_t_cells[idx] if is_glacier else 0.0

        sp = init_st[0]
        sm = init_st[1]
        wc = init_st[4]
        uz = max(float(init_st[2]), 0.0)
        lz = max(float(init_st[3]), 0.0)

        for t_idx in range(ts):
            p = prec_cells[idx, t_idx]
            t = temp_cells[idx, t_idx]
            e = et_cells[idx, t_idx]
            tm = ll_temp_cells[idx, t_idx]

            if np.isnan(p) or np.isnan(t) or np.isnan(e):
                continue

            p = max(p, 0.0)
            e = max(e, 0.0)

            t_eff = t + delta_t_here

            if t_eff <= tt:
                rf = 0.0
                sf = p * sfcf
            else:
                rf = p * rfcf
                sf = 0.0

            melt = 0.0
            ice_melt = 0.0
            if t_eff > tt:
                ddt = t_eff - tt
                avail_snow = sp + sf
                melt_pot_snow = cfmax * ddt
                melt = min(melt_pot_snow, avail_snow)
                sp = max(avail_snow - melt, 0.0)
                if is_glacier and (sp <= SWE_ICE_THRESHOLD_MM) and (melt_pot_snow > 0.0):
                    f_snow = melt / (melt_pot_snow + EPS)
                    if f_snow < 0.0:
                        f_snow = 0.0
                    elif f_snow > 1.0:
                        f_snow = 1.0
                    melt_pot_ice = (cfmax * ice_factor) * ddt
                    ice_melt = max(melt_pot_ice * (1.0 - f_snow), 0.0)
                wc_int = wc + melt + rf + ice_melt
            else:
                refr = min(cfr * cfmax * (tt - t_eff), wc + rf)
                sp = sp + sf + refr
                wc_int = max(wc - refr + rf, 0.0)

            sp = min(sp, 10000.0)
            if wc_int > cwh * sp:
                inf = wc_int - cwh * sp
                wc = cwh * sp
            else:
                inf = 0.0
                wc = wc_int

            sm_ratio = min(max(sm / fc_base, 0.0), 1.0)
            recharge = (sm_ratio ** beta_base) * inf

            ep_adj = max((1.0 + (t_eff - tm) * e_corr) * e, 0.0)
            lp_fc = lp_base * fc_base
            if lp_fc > 0.001:
                ea = min(ep_adj, (sm / lp_fc) * ep_adj)
            else:
                ea = ep_adj
            ea = min(ea, sm)

            uz += recharge
            sm = max(min(sm + inf - recharge - ea, fc_base), 0.0)

            perc_actual = min(perc, uz)
            uz -= perc_actual
            lz += perc_actual

            q0 = k * max(uz - uzl, 0.0)
            q1 = k1 * uz
            if q0 + q1 > uz:
                q0 = uz * 0.67
                q1 = uz * 0.33
            uz = max(uz - (q0 + q1), 0.0)

            q2 = k2 * lz
            if q2 > lz:
                q2 = lz
            lz = max(lz - q2, 0.0)

            q_total[t_idx] += (q0 + q1 + q2) * scale

    return q_total


@njit(cache=False, fastmath=True, nogil=True)
def run_all_cells_total_ice_flat(prec_cells, temp_cells, et_cells, ll_temp_cells, par_base, zone_high_cells,
                                 init_st, cell_scale, glacier_cells, glacier_on, ice_factor,
                                 cfmax_low, cfmax_high, glacier_delta_t_cells):
    n_cells = prec_cells.shape[0]
    ts = prec_cells.shape[1]
    q_total = np.zeros(ts, dtype=np.float64)
    q_ice = np.zeros(ts, dtype=np.float64)

    tt = par_base[0]
    rfcf = par_base[1]
    sfcf = par_base[2]
    cwh = par_base[4]
    cfr = par_base[5]
    fc_base = max(par_base[6], 10.0)
    beta_base = max(min(par_base[7], 10.0), 0.1)
    e_corr = par_base[8]
    lp_base = max(min(par_base[9], 0.99), 0.01)
    k = par_base[10]
    k1 = par_base[11]
    k2 = par_base[12]
    uzl = par_base[13]
    perc = par_base[14]

    for idx in range(n_cells):
        scale = cell_scale[idx]
        cfmax = cfmax_high if zone_high_cells[idx] else cfmax_low
        is_glacier = glacier_on and glacier_cells[idx]
        delta_t_here = glacier_delta_t_cells[idx] if is_glacier else 0.0

        sp = init_st[0]
        sm = init_st[1]
        wc = init_st[4]
        uz = max(float(init_st[2]), 0.0)
        lz = max(float(init_st[3]), 0.0)
        uz_i = 0.0
        lz_i = 0.0

        for t_idx in range(ts):
            p = prec_cells[idx, t_idx]
            t = temp_cells[idx, t_idx]
            e = et_cells[idx, t_idx]
            tm = ll_temp_cells[idx, t_idx]

            if np.isnan(p) or np.isnan(t) or np.isnan(e):
                continue

            p = max(p, 0.0)
            e = max(e, 0.0)

            t_eff = t + delta_t_here

            if t_eff <= tt:
                rf = 0.0
                sf = p * sfcf
            else:
                rf = p * rfcf
                sf = 0.0

            melt = 0.0
            ice_melt = 0.0
            if t_eff > tt:
                ddt = t_eff - tt
                avail_snow = sp + sf
                melt_pot_snow = cfmax * ddt
                melt = min(melt_pot_snow, avail_snow)
                sp = max(avail_snow - melt, 0.0)
                if is_glacier and (sp <= SWE_ICE_THRESHOLD_MM) and (melt_pot_snow > 0.0):
                    f_snow = melt / (melt_pot_snow + EPS)
                    if f_snow < 0.0:
                        f_snow = 0.0
                    elif f_snow > 1.0:
                        f_snow = 1.0
                    melt_pot_ice = (cfmax * ice_factor) * ddt
                    ice_melt = max(melt_pot_ice * (1.0 - f_snow), 0.0)
                wc_int = wc + melt + rf + ice_melt
            else:
                refr = min(cfr * cfmax * (tt - t_eff), wc + rf)
                sp = sp + sf + refr
                wc_int = max(wc - refr + rf, 0.0)

            sp = min(sp, 10000.0)
            if wc_int > cwh * sp:
                inf = wc_int - cwh * sp
                wc = cwh * sp
            else:
                inf = 0.0
                wc = wc_int

            input_total = rf + melt + ice_melt
            frac_i = ice_melt / (input_total + EPS)
            sm_ratio = min(max(sm / fc_base, 0.0), 1.0)
            recharge = (sm_ratio ** beta_base) * inf
            recharge_i = recharge * frac_i

            ep_adj = max((1.0 + (t_eff - tm) * e_corr) * e, 0.0)
            lp_fc = lp_base * fc_base
            if lp_fc > 0.001:
                ea = min(ep_adj, (sm / lp_fc) * ep_adj)
            else:
                ea = ep_adj
            ea = min(ea, sm)

            uz += recharge
            uz_i += recharge_i
            sm = max(min(sm + inf - recharge - ea, fc_base), 0.0)

            perc_actual = min(perc, uz)
            frac_uz_i = uz_i / (uz + EPS)
            perc_i = perc_actual * frac_uz_i
            uz -= perc_actual
            uz_i -= perc_i
            lz += perc_actual
            lz_i += perc_i

            q0 = k * max(uz - uzl, 0.0)
            q1 = k1 * uz
            if q0 + q1 > uz:
                q0 = uz * 0.67
                q1 = uz * 0.33

            frac_uz_i2 = uz_i / (uz + EPS)
            q0_i = q0 * frac_uz_i2
            q1_i = q1 * frac_uz_i2

            uz -= (q0 + q1)
            uz_i = max(uz_i - (q0_i + q1_i), 0.0)

            q2 = k2 * lz
            if q2 > lz:
                q2 = lz
            frac_lz_i = lz_i / (lz + EPS)
            q2_i = q2 * frac_lz_i
            lz -= q2
            lz_i = max(lz_i - q2_i, 0.0)

            q_total[t_idx] += (q0 + q1 + q2) * scale
            q_ice[t_idx] += (q0_i + q1_i + q2_i) * scale

    return q_total, q_ice


@njit(cache=False, fastmath=True, nogil=True)
def run_cells_state_snapshot_flat(prec_cells, temp_cells, et_cells, ll_temp_cells, par_base, zone_high_cells,
                                  init_st, active_cells, glacier_cells, glacier_on, ice_factor,
                                  cfmax_low, cfmax_high, glacier_delta_t_cells):
    n_cells = prec_cells.shape[0]
    ts = prec_cells.shape[1]

    sp_end = np.full(n_cells, np.nan, dtype=np.float32)
    sm_end = np.full(n_cells, np.nan, dtype=np.float32)
    wc_end = np.full(n_cells, np.nan, dtype=np.float32)
    uz_r_end = np.full(n_cells, np.nan, dtype=np.float32)
    uz_s_end = np.full(n_cells, np.nan, dtype=np.float32)
    uz_i_end = np.full(n_cells, np.nan, dtype=np.float32)
    lz_r_end = np.full(n_cells, np.nan, dtype=np.float32)
    lz_s_end = np.full(n_cells, np.nan, dtype=np.float32)
    lz_i_end = np.full(n_cells, np.nan, dtype=np.float32)

    tt = par_base[0]
    rfcf = par_base[1]
    sfcf = par_base[2]
    cwh = par_base[4]
    cfr = par_base[5]
    fc_base = max(par_base[6], 10.0)
    beta_base = max(min(par_base[7], 10.0), 0.1)
    e_corr = par_base[8]
    lp_base = max(min(par_base[9], 0.99), 0.01)
    k = par_base[10]
    k1 = par_base[11]
    k2 = par_base[12]
    uzl = par_base[13]
    perc = par_base[14]

    for idx in range(n_cells):
        if not active_cells[idx]:
            continue

        cfmax = cfmax_high if zone_high_cells[idx] else cfmax_low
        is_glacier = glacier_on and glacier_cells[idx]
        delta_t_here = glacier_delta_t_cells[idx] if is_glacier else 0.0

        sp = init_st[0]
        sm = init_st[1]
        init_uz = max(float(init_st[2]), 0.0)
        init_lz = max(float(init_st[3]), 0.0)
        wc = init_st[4]
        uz_r = init_uz
        uz_s = 0.0
        uz_i = 0.0
        lz_r = init_lz
        lz_s = 0.0
        lz_i = 0.0

        for t_idx in range(ts):
            p = prec_cells[idx, t_idx]
            t = temp_cells[idx, t_idx]
            e = et_cells[idx, t_idx]
            tm = ll_temp_cells[idx, t_idx]

            if np.isnan(p) or np.isnan(t) or np.isnan(e):
                continue

            p = max(p, 0.0)
            e = max(e, 0.0)

            t_eff = t + delta_t_here

            if t_eff <= tt:
                rf = 0.0
                sf = p * sfcf
            else:
                rf = p * rfcf
                sf = 0.0

            melt = 0.0
            ice_melt = 0.0
            if t_eff > tt:
                ddt = t_eff - tt
                avail_snow = sp + sf
                melt_pot_snow = cfmax * ddt
                melt = min(melt_pot_snow, avail_snow)
                sp = max(avail_snow - melt, 0.0)
                if is_glacier and (sp <= SWE_ICE_THRESHOLD_MM) and (melt_pot_snow > 0.0):
                    f_snow = melt / (melt_pot_snow + EPS)
                    if f_snow < 0.0:
                        f_snow = 0.0
                    elif f_snow > 1.0:
                        f_snow = 1.0
                    melt_pot_ice = (cfmax * ice_factor) * ddt
                    ice_melt = max(melt_pot_ice * (1.0 - f_snow), 0.0)
                wc_int = wc + melt + rf + ice_melt
            else:
                refr = min(cfr * cfmax * (tt - t_eff), wc + rf)
                sp = sp + sf + refr
                wc_int = max(wc - refr + rf, 0.0)

            sp = min(sp, 10000.0)
            if wc_int > cwh * sp:
                inf = wc_int - cwh * sp
                wc = cwh * sp
            else:
                inf = 0.0
                wc = wc_int

            input_total = rf + melt + ice_melt
            den_in = input_total + EPS
            frac_r = rf / den_in
            frac_s = melt / den_in
            frac_i = ice_melt / den_in

            sm_ratio = min(max(sm / fc_base, 0.0), 1.0)
            recharge = (sm_ratio ** beta_base) * inf
            r_r = recharge * frac_r
            r_s = recharge * frac_s
            r_i = recharge * frac_i

            ep_adj = max((1.0 + (t_eff - tm) * e_corr) * e, 0.0)
            lp_fc = lp_base * fc_base
            if lp_fc > 0.001:
                ea = min(ep_adj, (sm / lp_fc) * ep_adj)
            else:
                ea = ep_adj
            ea = min(ea, sm)

            uz_r += r_r
            uz_s += r_s
            uz_i += r_i
            uz_int = uz_r + uz_s + uz_i
            sm = max(min(sm + inf - recharge - ea, fc_base), 0.0)

            perc_actual = min(perc, uz_int)
            den_uz = uz_int + EPS
            frac_ur = uz_r / den_uz
            frac_us = uz_s / den_uz
            frac_ui = uz_i / den_uz
            uz_r -= perc_actual * frac_ur
            uz_s -= perc_actual * frac_us
            uz_i -= perc_actual * frac_ui
            lz_r += perc_actual * frac_ur
            lz_s += perc_actual * frac_us
            lz_i += perc_actual * frac_ui

            uz_int2 = uz_r + uz_s + uz_i
            q0 = k * max(uz_int2 - uzl, 0.0)
            q1 = k1 * uz_int2
            if q0 + q1 > uz_int2:
                q0 = uz_int2 * 0.67
                q1 = uz_int2 * 0.33

            den_uz2 = uz_int2 + EPS
            frac_ur2 = uz_r / den_uz2
            frac_us2 = uz_s / den_uz2
            frac_ui2 = uz_i / den_uz2
            q0_r = q0 * frac_ur2
            q0_s = q0 * frac_us2
            q0_i = q0 * frac_ui2
            q1_r = q1 * frac_ur2
            q1_s = q1 * frac_us2
            q1_i = q1 * frac_ui2

            uz_r = max(uz_r - (q0_r + q1_r), 0.0)
            uz_s = max(uz_s - (q0_s + q1_s), 0.0)
            uz_i = max(uz_i - (q0_i + q1_i), 0.0)

            lz_int = lz_r + lz_s + lz_i
            q2 = k2 * lz_int
            if q2 > lz_int:
                q2 = lz_int

            den_lz = lz_int + EPS
            frac_lr = lz_r / den_lz
            frac_ls = lz_s / den_lz
            frac_li = lz_i / den_lz
            q2_r = q2 * frac_lr
            q2_s = q2 * frac_ls
            q2_i = q2 * frac_li

            lz_r = max(lz_r - q2_r, 0.0)
            lz_s = max(lz_s - q2_s, 0.0)
            lz_i = max(lz_i - q2_i, 0.0)

        sp_end[idx] = sp
        sm_end[idx] = sm
        wc_end[idx] = wc
        uz_r_end[idx] = uz_r
        uz_s_end[idx] = uz_s
        uz_i_end[idx] = uz_i
        lz_r_end[idx] = lz_r
        lz_s_end[idx] = lz_s
        lz_i_end[idx] = lz_i

    return sp_end, sm_end, wc_end, uz_r_end, uz_s_end, uz_i_end, lz_r_end, lz_s_end, lz_i_end


@njit(cache=False, fastmath=True, nogil=True)
def muskingum_route(q_in, k, x, dt):
    n = len(q_in)
    q_out = np.zeros(n, dtype=np.float64)
    q_out[0] = q_in[0]

    denom = 2 * k * (1 - x) + dt
    c0 = (dt - 2 * k * x) / denom
    c1 = (dt + 2 * k * x) / denom
    c2 = (2 * k * (1 - x) - dt) / denom

    for i in range(1, n):
        q_out[i] = c0 * q_in[i] + c1 * q_in[i - 1] + c2 * q_out[i - 1]
        if q_out[i] < 0:
            q_out[i] = 0.0

    return q_out


@njit(cache=False, nogil=True)
def nse_numba(obs, sim):
    n = len(obs)
    sum_obs = 0.0
    count = 0

    for i in range(n):
        if not (np.isnan(obs[i]) or np.isnan(sim[i])):
            sum_obs += obs[i]
            count += 1

    if count == 0:
        return -999.0

    mean_obs = sum_obs / count
    ss_err = 0.0
    ss_tot = 0.0

    for i in range(n):
        if not (np.isnan(obs[i]) or np.isnan(sim[i])):
            ss_err += (obs[i] - sim[i]) ** 2
            ss_tot += (obs[i] - mean_obs) ** 2

    if ss_tot == 0:
        return -999.0

    return 1.0 - ss_err / ss_tot


def rmse(obs, sim):
    obs = np.asarray(obs, dtype=np.float64)
    sim = np.asarray(sim, dtype=np.float64)
    mask = np.isfinite(obs) & np.isfinite(sim)
    if not np.any(mask):
        return float("nan")
    return float(np.sqrt(np.nanmean((obs[mask] - sim[mask]) ** 2)))


def nse_safe(obs, sim):
    obs = np.asarray(obs, dtype=np.float64)
    sim = np.asarray(sim, dtype=np.float64)
    mask = np.isfinite(obs) & np.isfinite(sim)
    if np.sum(mask) < 2:
        return float("nan")
    obs_valid = obs[mask]
    sim_valid = sim[mask]
    mean_obs = float(np.mean(obs_valid))
    ss_tot = float(np.sum((obs_valid - mean_obs) ** 2))
    if ss_tot <= EPS:
        return float("nan")
    return float(nse_numba(obs_valid, sim_valid))


def pearson_r(obs, sim):
    obs = np.asarray(obs, dtype=np.float64)
    sim = np.asarray(sim, dtype=np.float64)
    mask = np.isfinite(obs) & np.isfinite(sim)
    if np.sum(mask) < 2:
        return float("nan")
    obs_masked = obs[mask]
    sim_masked = sim[mask]
    obs_centered = obs_masked - np.mean(obs_masked)
    sim_centered = sim_masked - np.mean(sim_masked)
    denom = np.sqrt(np.sum(obs_centered ** 2) * np.sum(sim_centered ** 2))
    if denom <= EPS:
        return float("nan")
    return float(np.sum(obs_centered * sim_centered) / denom)


@njit(cache=False, nogil=True)
def kge_numba(obs, sim):
    n = len(obs)
    sum_o = 0.0
    sum_s = 0.0
    count = 0
    for i in range(n):
        if not (np.isnan(obs[i]) or np.isnan(sim[i])):
            sum_o += obs[i]
            sum_s += sim[i]
            count += 1
    if count < 2:
        return -999.0, -999.0, -999.0, -999.0
    mean_o = sum_o / count
    mean_s = sum_s / count
    ss_oo = 0.0
    ss_ss = 0.0
    ss_os = 0.0
    for i in range(n):
        if not (np.isnan(obs[i]) or np.isnan(sim[i])):
            do = obs[i] - mean_o
            ds = sim[i] - mean_s
            ss_oo += do * do
            ss_ss += ds * ds
            ss_os += do * ds
    std_o = (ss_oo / count) ** 0.5
    std_s = (ss_ss / count) ** 0.5
    if std_o < 1e-12:
        return -999.0, -999.0, -999.0, -999.0
    r = ss_os / (count * std_o * std_s) if std_s > 1e-12 else 0.0
    alpha = std_s / std_o
    beta = mean_s / mean_o if abs(mean_o) > 1e-12 else 0.0
    kge = 1.0 - ((r - 1.0) ** 2 + (alpha - 1.0) ** 2 + (beta - 1.0) ** 2) ** 0.5
    return kge, r, alpha, beta


def log_nse(obs, sim):
    obs = np.asarray(obs, dtype=np.float64)
    sim = np.asarray(sim, dtype=np.float64)
    mask = np.isfinite(obs) & np.isfinite(sim)
    if np.sum(mask) < 2:
        return float("nan")
    o = obs[mask]
    s = sim[mask]
    eps = max(0.01 * np.mean(o), 1e-6)
    lo = np.log(o + eps)
    ls = np.log(s + eps)
    return nse_safe(lo, ls)


def pbias(obs, sim):
    obs = np.asarray(obs, dtype=np.float64)
    sim = np.asarray(sim, dtype=np.float64)
    mask = np.isfinite(obs) & np.isfinite(sim)
    total_obs = np.sum(obs[mask])
    if abs(total_obs) < 1e-12:
        return float("nan")
    return float(100.0 * np.sum(sim[mask] - obs[mask]) / total_obs)


def flow_duration_curve(series):
    s = np.asarray(series, dtype=np.float64)
    s = s[np.isfinite(s)]
    if len(s) == 0:
        return {"exceedance": [], "flow": []}
    s_sorted = np.sort(s)[::-1]
    n = len(s_sorted)
    exc = [(i + 1) / (n + 1) * 100.0 for i in range(n)]
    step = max(1, n // 200)
    return {
        "exceedance": [round(exc[i], 2) for i in range(0, n, step)],
        "flow": [round(float(s_sorted[i]), 4) for i in range(0, n, step)],
    }


def monthly_metrics(dates, obs, sim):
    obs = np.asarray(obs, dtype=np.float64)
    sim = np.asarray(sim, dtype=np.float64)
    result = {}
    for m in range(1, 13):
        idx = np.array([i for i, d in enumerate(dates) if d.month == m])
        if len(idx) < 5:
            result[str(m)] = {"nse": None, "kge": None}
            continue
        o = obs[idx]
        s = sim[idx]
        mask = np.isfinite(o) & np.isfinite(s)
        if np.sum(mask) < 5:
            result[str(m)] = {"nse": None, "kge": None}
            continue
        nse_val = nse_safe(o[mask], s[mask])
        kge_val, _, _, _ = kge_numba(o[mask], s[mask])
        result[str(m)] = {
            "nse": round(nse_val, 4) if np.isfinite(nse_val) else None,
            "kge": round(float(kge_val), 4) if kge_val > -900 else None,
        }
    return result


def compare_series(reference, simulated):
    if reference is None or simulated is None:
        return None

    ref = np.asarray(reference, dtype=np.float64)
    sim = np.asarray(simulated, dtype=np.float64)
    mask = np.isfinite(ref) & np.isfinite(sim)
    count = int(np.sum(mask))
    if count == 0:
        return None

    ref_valid = ref[mask]
    sim_valid = sim[mask]
    total_ref = float(np.sum(ref_valid))
    total_sim = float(np.sum(sim_valid))
    nse_value = nse_safe(ref_valid, sim_valid)

    kge_val, kge_r, kge_a, kge_b = kge_numba(ref_valid, sim_valid)
    metrics = {
        "count": count,
        "nse": nse_value,
        "kge": round(float(kge_val), 4) if kge_val > -900 else None,
        "log_nse": round(log_nse(ref_valid, sim_valid), 4),
        "pbias": round(pbias(ref_valid, sim_valid), 2),
        "rmse_m3s": rmse(ref_valid, sim_valid),
        "mae_m3s": float(np.mean(np.abs(sim_valid - ref_valid))),
        "bias_m3s": float(np.mean(sim_valid - ref_valid)),
        "corr": pearson_r(ref_valid, sim_valid),
        "sum_reference_series": total_ref,
        "sum_simulated_series": total_sim,
        "volume_ratio": float(total_sim / total_ref) if abs(total_ref) > EPS else float("nan"),
    }
    return metrics


def _glacier_analysis_window(reference, simulated):
    if reference is None or simulated is None:
        return pd.DatetimeIndex([]), np.asarray([], dtype=np.float64), np.asarray([], dtype=np.float64)
    ref = np.asarray(reference, dtype=np.float64)
    sim = np.asarray(simulated, dtype=np.float64)
    count = min(len(ref), len(sim))
    if count <= 0:
        return pd.DatetimeIndex([]), np.asarray([], dtype=np.float64), np.asarray([], dtype=np.float64)
    ref = ref[:count]
    sim = sim[:count]
    if SIM_DATES is not None and len(SIM_DATES) >= count:
        dates = pd.DatetimeIndex(SIM_DATES[:count])
        analysis_mask = np.ones(count, dtype=bool)
        if CALIB_MASK is not None and VALID_MASK is not None and len(CALIB_MASK) >= count and len(VALID_MASK) >= count:
            analysis_mask = np.asarray(CALIB_MASK[:count] | VALID_MASK[:count], dtype=bool)
    else:
        dates = pd.date_range("2000-01-01", periods=count, freq="D")
        analysis_mask = np.ones(count, dtype=bool)
    finite_mask = np.isfinite(ref) & np.isfinite(sim) & analysis_mask
    if not np.any(finite_mask):
        return pd.DatetimeIndex([]), np.asarray([], dtype=np.float64), np.asarray([], dtype=np.float64)
    return dates[finite_mask], ref[finite_mask], sim[finite_mask]


def _series_to_monthly_sums(series, dates=None):
    if series is None:
        return None
    try:
        arr = np.asarray(series, dtype=np.float64)
    except Exception:
        return None
    if arr.ndim != 1 or arr.shape[0] == 0:
        return None
    if dates is None:
        if SIM_DATES is not None and len(SIM_DATES) >= arr.shape[0]:
            dates = pd.DatetimeIndex(SIM_DATES[: arr.shape[0]])
        else:
            return None
    dates = pd.DatetimeIndex(dates[: arr.shape[0]])
    mask = np.isfinite(arr)
    if not np.any(mask):
        return None
    s = pd.Series(arr[mask], index=dates[mask])
    monthly = s.groupby(s.index.month).sum().reindex(range(1, 13), fill_value=0.0)
    return monthly.to_numpy(dtype=np.float64)


def compute_swr_penalty(obs_monthly, sim_monthly, weight=0.20, tol_ratio=0.20):
    info = {
        "swr_obs": float("nan"),
        "swr_sim": float("nan"),
        "log_deviation": float("nan"),
        "tolerance": float("nan"),
        "weight": float(weight),
        "status": "unavailable",
    }
    if obs_monthly is None or sim_monthly is None:
        return 0.0, info
    obs = np.asarray(obs_monthly, dtype=np.float64)
    sim = np.asarray(sim_monthly, dtype=np.float64)
    if obs.shape[0] != 12 or sim.shape[0] != 12:
        return 0.0, info
    summer_idx = [4, 5, 6, 7, 8]
    winter_idx = [10, 11, 0, 1, 2]
    obs_sum = float(obs[summer_idx].sum())
    obs_win = float(obs[winter_idx].sum())
    sim_sum = float(sim[summer_idx].sum())
    sim_win = float(sim[winter_idx].sum())
    if obs_win <= EPS or sim_win <= EPS or obs_sum <= EPS or sim_sum <= EPS:
        info["status"] = "insufficient_data"
        return 0.0, info
    swr_obs = obs_sum / obs_win
    swr_sim = sim_sum / sim_win
    log_dev = float(np.log(swr_sim / swr_obs))
    tol = float(np.log(1.0 + max(float(tol_ratio), 0.0)))
    excess = max(abs(log_dev) - tol, 0.0)
    info["swr_obs"] = float(swr_obs)
    info["swr_sim"] = float(swr_sim)
    info["log_deviation"] = log_dev
    info["tolerance"] = tol
    info["status"] = "in_tolerance" if excess <= 0.0 else "out_of_tolerance"
    penalty = float(weight) * (excess ** 2)
    return float(penalty), info


def compute_peak_month_penalty(obs_monthly, sim_monthly, weight=0.10, tol_months=1):
    info = {
        "peak_obs": None,
        "peak_sim": None,
        "diff": float("nan"),
        "tolerance": int(tol_months),
        "weight": float(weight),
        "status": "unavailable",
    }
    if obs_monthly is None or sim_monthly is None:
        return 0.0, info
    obs = np.asarray(obs_monthly, dtype=np.float64)
    sim = np.asarray(sim_monthly, dtype=np.float64)
    if obs.shape[0] != 12 or sim.shape[0] != 12:
        return 0.0, info
    if not (np.any(obs > EPS) and np.any(sim > EPS)):
        info["status"] = "zero_series"
        return 0.0, info
    peak_obs = int(np.argmax(obs)) + 1
    peak_sim = int(np.argmax(sim)) + 1
    gap = abs(peak_obs - peak_sim)
    diff = float(min(gap, 12 - gap))
    info["peak_obs"] = peak_obs
    info["peak_sim"] = peak_sim
    info["diff"] = diff
    if diff <= float(tol_months):
        info["status"] = "in_tolerance"
        return 0.0, info
    info["status"] = "out_of_tolerance"
    penalty = float(weight) * ((diff - float(tol_months)) ** 2)
    return float(penalty), info


def compute_glacier_fraction_penalty(q_ice, q_total, window, weight=0.25):
    info = {
        "f_ice": float("nan"),
        "f_min": float("nan"),
        "f_max": float("nan"),
        "weight": float(weight),
        "status": "unavailable",
    }
    if q_ice is None or q_total is None or window is None:
        return 0.0, info
    try:
        q_ice_arr = np.asarray(q_ice, dtype=np.float64)
        q_total_arr = np.asarray(q_total, dtype=np.float64)
    except Exception:
        return 0.0, info
    count = min(q_ice_arr.shape[0], q_total_arr.shape[0])
    if count <= 0:
        return 0.0, info
    q_ice_arr = q_ice_arr[:count]
    q_total_arr = q_total_arr[:count]
    mask = np.isfinite(q_ice_arr) & np.isfinite(q_total_arr)
    if not np.any(mask):
        return 0.0, info
    total_ice = float(np.sum(q_ice_arr[mask]))
    total_all = float(np.sum(q_total_arr[mask]))
    if total_all <= EPS:
        info["status"] = "zero_total"
        return 0.0, info
    f_ice = float(total_ice / total_all)
    try:
        f_min_raw, f_max_raw = window
        f_min = float(f_min_raw)
        f_max = float(f_max_raw)
    except Exception:
        return 0.0, info
    if not (np.isfinite(f_min) and np.isfinite(f_max)) or f_max <= f_min:
        return 0.0, info
    info["f_ice"] = f_ice
    info["f_min"] = f_min
    info["f_max"] = f_max
    if f_ice < f_min:
        f_ref = max(f_ice, 1e-6)
        log_dev = float(np.log(f_min / f_ref))
        info["status"] = "below_window"
    elif f_ice > f_max:
        log_dev = float(np.log(f_ice / max(f_max, 1e-6)))
        info["status"] = "above_window"
    else:
        info["status"] = "in_window"
        return 0.0, info
    penalty = float(weight) * (log_dev ** 2)
    return float(penalty), info


def glacier_fraction_eval_series(sim):
    if sim is None:
        return None, None
    q_ice = sim.get("q_ice")
    if q_ice is None:
        return None, None
    if bool(sim.get("boundary_enabled")) and sim.get("q_local") is not None:
        q_total = sim.get("q_local")
    else:
        q_total = sim.get("q_total")
    if q_total is None:
        return None, None
    try:
        q_ice_arr = np.asarray(q_ice, dtype=np.float64)
        q_total_arr = np.asarray(q_total, dtype=np.float64)
    except Exception:
        return None, None
    count = min(q_ice_arr.shape[0], q_total_arr.shape[0])
    if count <= 0:
        return None, None
    q_ice_arr = q_ice_arr[:count]
    q_total_arr = q_total_arr[:count]
    if CALIB_MASK is None:
        return q_ice_arr, q_total_arr
    calib_mask = np.asarray(CALIB_MASK[:count], dtype=bool)
    if calib_mask.shape[0] == count and np.any(calib_mask):
        return q_ice_arr[calib_mask], q_total_arr[calib_mask]
    return q_ice_arr, q_total_arr


def infer_glacier_fraction_window(
    f_area,
    strategy="default",
    lower_cap=0.02,
    upper_cap=0.70,
    low_mult=0.5,
    high_mult=3.0,
):
    if f_area is None:
        return None
    try:
        fa = float(f_area)
    except Exception:
        return None
    if not np.isfinite(fa) or fa <= 0.0:
        return None

    low_mult_eff = float(low_mult)
    high_mult_eff = float(high_mult)
    upper_floor = 0.0
    if fa < 0.03:
        # Small glacierized alpine basins can still have much larger annual ice-runoff
        # contribution than raw glacier area fraction suggests, so 3x is too restrictive.
        high_mult_eff = max(high_mult_eff, 15.0)
        upper_floor = 0.15
    elif fa < 0.08:
        high_mult_eff = max(high_mult_eff, 8.0)
        upper_floor = 0.12

    f_min = max(low_mult_eff * fa, float(lower_cap))
    f_max = min(max(high_mult_eff * fa, upper_floor), float(upper_cap))
    if f_max <= f_min:
        f_max = min(max(f_min * 1.5, f_min + 0.02), float(upper_cap))
    if f_max <= f_min:
        return None
    return (float(f_min), float(f_max))


def compute_glacier_physical_checks(reference, simulated):
    checks = {
        "available": False,
        "passed": False,
        "status": "unavailable",
        "analysis_count": 0,
        "analysis_start": "",
        "analysis_end": "",
        "annual_volume_ratio": float("nan"),
        "annual_volume_pass": False,
        "active_months": [],
        "active_month_correlation": float("nan"),
        "active_month_correlation_pass": False,
        "peak_month_reference": None,
        "peak_month_simulated": None,
        "peak_month_diff": float("nan"),
        "peak_month_pass": False,
        "warm_season_pass": False,
        "cold_season_share_reference": float("nan"),
        "cold_season_share_simulated": float("nan"),
        "cold_season_share_limit": float("nan"),
        "cold_season_share_excess": 0.0,
        "cold_season_pass": False,
    }
    dates, ref_valid, sim_valid = _glacier_analysis_window(reference, simulated)
    if len(ref_valid) <= 0:
        return checks
    checks["analysis_count"] = int(len(ref_valid))
    checks["analysis_start"] = str(dates.min().date()) if len(dates) else ""
    checks["analysis_end"] = str(dates.max().date()) if len(dates) else ""

    total_ref = float(np.sum(ref_valid))
    total_sim = float(np.sum(sim_valid))
    if total_ref <= EPS:
        checks["status"] = "zero_reference"
        return checks

    checks["available"] = True
    checks["annual_volume_ratio"] = float(total_sim / total_ref) if abs(total_ref) > EPS else float("nan")
    checks["annual_volume_pass"] = bool(0.7 <= checks["annual_volume_ratio"] <= 1.3) if np.isfinite(checks["annual_volume_ratio"]) else False

    ref_monthly = pd.Series(ref_valid, index=dates).groupby(dates.month).sum().reindex(range(1, 13), fill_value=0.0)
    sim_monthly = pd.Series(sim_valid, index=dates).groupby(dates.month).sum().reindex(range(1, 13), fill_value=0.0)
    positive_ref = ref_monthly[ref_monthly > EPS].sort_values(ascending=False)
    if positive_ref.empty:
        checks["status"] = "zero_reference"
        return checks

    active_ranked: list[int] = []
    accum = 0.0
    positive_total = float(positive_ref.sum())
    for month, value in positive_ref.items():
        active_ranked.append(int(month))
        accum += float(value)
        if len(active_ranked) >= 3 and (accum / positive_total) >= 0.9:
            break
    if len(active_ranked) < 3:
        for month in positive_ref.index.tolist():
            month_int = int(month)
            if month_int not in active_ranked:
                active_ranked.append(month_int)
            if len(active_ranked) >= 3:
                break
    if len(active_ranked) > 6:
        active_ranked = active_ranked[:6]
    active_months = sorted(active_ranked)
    checks["active_months"] = active_months

    active_ref = ref_monthly.loc[active_months].to_numpy(dtype=np.float64) if active_months else np.asarray([], dtype=np.float64)
    active_sim = sim_monthly.loc[active_months].to_numpy(dtype=np.float64) if active_months else np.asarray([], dtype=np.float64)
    if active_ref.size >= 2 and np.nanstd(active_ref) > EPS and np.nanstd(active_sim) > EPS:
        active_corr = float(pearson_r(active_ref, active_sim))
    elif active_ref.size >= 2:
        active_corr = 1.0 if np.allclose(active_ref, active_sim, atol=1e-9, rtol=1e-6) else float("nan")
    else:
        active_corr = float("nan")
    checks["active_month_correlation"] = active_corr
    checks["active_month_correlation_pass"] = bool(np.isfinite(active_corr) and active_corr >= 0.8)

    peak_ref = int(ref_monthly.idxmax()) if float(ref_monthly.sum()) > EPS else None
    peak_sim = int(sim_monthly.idxmax()) if float(sim_monthly.sum()) > EPS else None
    checks["peak_month_reference"] = peak_ref
    checks["peak_month_simulated"] = peak_sim
    if peak_ref is not None and peak_sim is not None:
        month_gap = abs(peak_ref - peak_sim)
        peak_diff = float(min(month_gap, 12 - month_gap))
    else:
        peak_diff = float("nan")
    checks["peak_month_diff"] = peak_diff
    checks["peak_month_pass"] = bool(np.isfinite(peak_diff) and peak_diff <= 1.0)
    checks["warm_season_pass"] = bool(checks["active_month_correlation_pass"] and checks["peak_month_pass"])

    cold_months = [month for month in range(1, 13) if month not in active_months]
    cold_ref = float(ref_monthly.loc[cold_months].sum()) if cold_months else 0.0
    cold_sim = float(sim_monthly.loc[cold_months].sum()) if cold_months else 0.0
    cold_ref_share = float(cold_ref / total_ref) if total_ref > EPS else float("nan")
    cold_sim_share = float(cold_sim / total_sim) if total_sim > EPS else float("nan")
    cold_limit = min(0.10, cold_ref_share + 0.05) if np.isfinite(cold_ref_share) else 0.10
    checks["cold_season_share_reference"] = cold_ref_share
    checks["cold_season_share_simulated"] = cold_sim_share
    checks["cold_season_share_limit"] = cold_limit
    if np.isfinite(cold_sim_share):
        checks["cold_season_share_excess"] = float(max(cold_sim_share - cold_limit, 0.0))
    checks["cold_season_pass"] = bool(
        np.isfinite(cold_sim_share)
        and cold_sim_share <= 0.10 + 1e-12
        and cold_sim_share <= cold_ref_share + 0.05 + 1e-12
    )

    checks["passed"] = bool(checks["annual_volume_pass"] and checks["warm_season_pass"] and checks["cold_season_pass"])
    checks["status"] = "ok" if checks["passed"] else "fail"
    return checks


def muskingum_is_valid(k, x):
    if not np.isfinite(k) or not np.isfinite(x):
        return False
    if k <= 0.0 or x < 0.0 or x >= 0.5:
        return False
    denom = 2.0 * k * (1.0 - x) + MUSK_DT
    if denom <= 0.0:
        return False
    c0 = (MUSK_DT - 2.0 * k * x) / denom
    c1 = (MUSK_DT + 2.0 * k * x) / denom
    c2 = (2.0 * k * (1.0 - x) - MUSK_DT) / denom
    return (c0 >= 0.0) and (c1 >= 0.0) and (c2 >= 0.0)


def muskingum_coefficients(k, x):
    try:
        k_val = float(k)
        x_val = float(x)
    except Exception:
        return {"C0": None, "C1": None, "C2": None}
    if not np.isfinite(k_val) or not np.isfinite(x_val):
        return {"C0": None, "C1": None, "C2": None}
    denom = 2.0 * k_val * (1.0 - x_val) + MUSK_DT
    if abs(denom) <= EPS:
        return {"C0": None, "C1": None, "C2": None}
    return {
        "C0": float((MUSK_DT - 2.0 * k_val * x_val) / denom),
        "C1": float((MUSK_DT + 2.0 * k_val * x_val) / denom),
        "C2": float((2.0 * k_val * (1.0 - x_val) - MUSK_DT) / denom),
    }


def current_project_object_type():
    raw = str(PROJECT_OBJECT_TYPE or "").strip().lower()
    if raw in {"regression_validation", "full_upstream_basin", "interbasin_with_boundary"}:
        return raw
    return "interbasin_with_boundary" if bool(BOUNDARY_INFLOW_ENABLED) else "full_upstream_basin"


def current_q_score_basis():
    return "q_local" if current_project_object_type() == "interbasin_with_boundary" else "q_total"


def scoring_series(sim):
    basis = current_q_score_basis()
    if basis == "q_local" and isinstance(sim, dict) and sim.get("q_local") is not None:
        return np.asarray(sim["q_local"], dtype=np.float64), basis
    if isinstance(sim, dict) and sim.get("q_total") is not None:
        return np.asarray(sim["q_total"], dtype=np.float64), "q_total"
    return None, basis


def validate_parameter_vector(opt_params):
    values = np.asarray(opt_params, dtype=np.float64)
    if values.shape[0] != len(param_names):
        raise ValueError(f"参数维度不一致：期望 {len(param_names)}，实际 {values.shape[0]}")
    if not np.all(np.isfinite(values)):
        bad = [param_names[idx] for idx, item in enumerate(values) if not np.isfinite(item)]
        raise ValueError(f"参数中存在非有限值：{', '.join(bad[:5])}")

    k0 = float(values[10])
    k1 = float(values[11])
    k2 = float(values[12])
    if not (k0 > k1 > k2 > 0.0):
        raise ValueError(
            f"退水参数必须满足 K > K1 > K2 > 0，当前为 K={k0:.6f}, K1={k1:.6f}, K2={k2:.6f}"
        )

    k_musk = float(values[16])
    x_musk = float(values[17])
    if not muskingum_is_valid(k_musk, x_musk):
        raise ValueError(
            f"Muskingum 参数无效：K_MUSK={k_musk:.6f}, X_MUSK={x_musk:.6f}, dt={MUSK_DT:.6f}"
        )
    return values


def default_muskingum_pair():
    k_lo, k_hi = [float(v) for v in PARAM_BOUNDS[16]]
    x_lo, x_hi = [float(v) for v in PARAM_BOUNDS[17]]
    preferred_x = [0.05, 0.02, 0.0, x_lo]
    preferred_k = [1.2, 0.8, 0.4, 0.2]

    for x_candidate in preferred_x:
        x_val = min(max(float(x_candidate), x_lo), x_hi)
        lower = max(k_lo, MUSK_DT / (2.0 * max(1.0 - x_val, EPS)) + 1e-6)
        if x_val <= EPS:
            upper = k_hi
        else:
            upper = min(k_hi, MUSK_DT / (2.0 * x_val) - 1e-6)
        if lower > upper:
            continue
        for k_candidate in preferred_k:
            if lower <= float(k_candidate) <= upper:
                return float(k_candidate), float(x_val)
        return float((lower + upper) / 2.0), float(x_val)

    return float(k_lo), float(x_lo)


def default_test_vector():
    vector = np.array(
        [-1.2, 1200.0, 1.0, 0.95, 1.0, 1.05, 0.05, 0.05, 3.5, 5.5, 0.25, 0.05, 0.005, 30.0, 1.8, 2.0, 0.4, 0.05],
        dtype=np.float64,
    )
    if len(PARAM_BOUNDS) == len(vector):
        for idx, (lo, hi) in enumerate(PARAM_BOUNDS):
            vector[idx] = min(max(vector[idx], float(lo)), float(hi))
    vector[16], vector[17] = default_muskingum_pair()
    return vector.tolist()


def sanitize_initial_param_vector(values):
    vector = np.asarray(values, dtype=np.float64).copy()
    defaults = np.asarray(default_test_vector(), dtype=np.float64)
    if vector.shape[0] != len(param_names):
        raise ValueError(f"初始参数长度不一致：期望 {len(param_names)}，实际 {vector.shape[0]}")

    for idx, (lo, hi) in enumerate(PARAM_BOUNDS):
        if not np.isfinite(vector[idx]):
            vector[idx] = defaults[idx]
        vector[idx] = min(max(float(vector[idx]), float(lo)), float(hi))

    if not (vector[10] > vector[11] > vector[12] > 0.0):
        vector[10] = defaults[10]
        vector[11] = defaults[11]
        vector[12] = defaults[12]

    if not muskingum_is_valid(vector[16], vector[17]):
        vector[16], vector[17] = default_muskingum_pair()

    return vector


def warmup_jit():
    n = 10
    prec = np.random.rand(n).astype(np.float32)
    temp = np.random.rand(n).astype(np.float32) * 10
    et = np.random.rand(n).astype(np.float32)
    ll_temp = np.random.rand(n).astype(np.float32) * 5
    par = np.array([0.0, 1.0, 1.0, 3.0, 0.05, 0.05, 200.0, 1.0, 0.0, 0.5, 0.2, 0.05, 0.005, 30.0, 2.0], dtype=np.float64)
    init_st = np.array([0.0, 5.0, 5.0, 5.0, 0.0], dtype=np.float64)
    _ = hbv_cell(prec, temp, et, ll_temp, par, init_st, True, 1.5, 0.0)
    q = np.random.rand(n).astype(np.float64)
    _ = muskingum_route(q, 1.0, 0.2, 1.0)
    prec_3d = prec.reshape(1, 1, n)
    temp_3d = temp.reshape(1, 1, n)
    et_3d = et.reshape(1, 1, n)
    ll_temp_3d = ll_temp.reshape(1, 1, n)
    cfmax_grid = np.full((1, 1), 3.0, dtype=np.float64)
    valid_cells = np.array([[0, 0]], dtype=np.int64)
    cell_scale = np.array([1.0], dtype=np.float64)
    glacier_mask = np.array([[True]], dtype=np.bool_)
    _ = run_all_cells(prec_3d, temp_3d, et_3d, ll_temp_3d, par, cfmax_grid, init_st, valid_cells, cell_scale, glacier_mask, True, 1.5)
    prec_cells = prec.reshape(1, n)
    temp_cells = temp.reshape(1, n)
    et_cells = et.reshape(1, n)
    ll_temp_cells = ll_temp.reshape(1, n)
    zone_high_cells = np.array([True], dtype=np.bool_)
    glacier_cells = np.array([True], dtype=np.bool_)
    glacier_delta_t_cells = np.zeros(1, dtype=np.float32)
    _ = run_all_cells_flat(prec_cells, temp_cells, et_cells, ll_temp_cells, par, zone_high_cells, init_st, cell_scale, glacier_cells, True, 1.5, 3.0, 4.0, glacier_delta_t_cells)
    _ = run_all_cells_total_only_flat(prec_cells, temp_cells, et_cells, ll_temp_cells, par, zone_high_cells, init_st, cell_scale, glacier_cells, True, 1.5, 3.0, 4.0, glacier_delta_t_cells)
    _ = run_all_cells_total_ice_flat(prec_cells, temp_cells, et_cells, ll_temp_cells, par, zone_high_cells, init_st, cell_scale, glacier_cells, True, 1.5, 3.0, 4.0, glacier_delta_t_cells)
    _ = nse_numba(q, q)
    _ = kge_numba(q, q)


def parse_args():
    parser = argparse.ArgumentParser(description="HBV-Cryo calibration")
    parser.add_argument("--maxiter", type=int, default=40)
    parser.add_argument("--popsize", type=int, default=8)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--log-every", type=int, default=10)
    parser.add_argument("--tol", type=float, default=0.001)
    parser.add_argument("--polish", action="store_true", default=False)
    parser.add_argument("--no-polish", dest="polish", action="store_false")
    parser.add_argument("--refine-maxiter", dest="refine_maxiter", type=int, default=-1,
                        help="局部精修轮数。-1 表示按默认规则自动选择，0 表示禁用，>0 显式指定")
    parser.add_argument("--method", choices=["de", "mc_screen_de", "mc_only"], default="mc_screen_de")
    parser.add_argument("--mc-samples", type=int, default=600)
    parser.add_argument("--init-params-file", type=str, default=None)
    parser.add_argument("--init-bound-shrink", type=float, default=0.0)
    parser.add_argument("--flood-events-file", "--洪水事件文件", dest="flood_events_file", type=str, default=None)
    parser.add_argument(
        "--param-bounds-profile",
        "--参数边界档案",
        dest="param_bounds_profile",
        choices=[PARAM_BOUNDS_PROFILE_QTP, PARAM_BOUNDS_PROFILE_GENERIC],
        default=DEFAULT_PARAM_BOUNDS_PROFILE,
        help="参数搜索边界档案：默认使用青藏高原高寒区推荐范围，可切换为通用宽范围。",
    )
    parser.add_argument("--prec-source", choices=["era5", "mswep", "cmfd", "custom_tif"], default="era5")
    parser.add_argument("--prec-dir", type=str, default=None)
    parser.add_argument("--glacier-mode", choices=["inline", "off"], default="inline")
    parser.add_argument(
        "--目标函数",
        "--objective-mode",
        dest="objective_mode",
        choices=["auto", "single_objective_nse", "weighted_multi_criteria", OBJECTIVE_FAMILY_DAILY, FLOOD_EVENT_OBJECTIVE_FAMILY],
        default="auto",
    )
    parser.add_argument("--fill-nan", dest="fill_nan", action="store_true", default=True)
    parser.add_argument("--no-fill-nan", dest="fill_nan", action="store_false")
    parser.add_argument("--debug-days", type=int, default=0)
    parser.add_argument("--quick-test", action="store_true", default=False)
    parser.add_argument("--quick-days", type=int, default=30)
    parser.add_argument(
        "--calibration-workflow",
        choices=[CALIBRATION_WORKFLOW_SINGLE, CALIBRATION_WORKFLOW_STAGED],
        default=CALIBRATION_WORKFLOW_SINGLE,
    )
    return parser.parse_args()


def setup_logging():
    global RUN_ID, LOG_FILE, PROGRESS_FILE, PROGRESS_FILE_MAIN, PROGRESS_FILE_REFINE, start_time, gen_count
    RUN_ID = datetime.now().strftime("%Y%m%d_%H%M%S")
    os.makedirs(LOG_DIR, exist_ok=True)
    os.makedirs(RUNS_DIR, exist_ok=True)
    os.makedirs(CACHE_DIR, exist_ok=True)
    LOG_FILE = os.path.join(LOG_DIR, f"hbv_cryo_{RUN_ID}.log")
    PROGRESS_FILE = os.path.join(LOG_DIR, f"progress_{RUN_ID}.csv")
    PROGRESS_FILE_MAIN = PROGRESS_FILE
    PROGRESS_FILE_REFINE = None
    start_time = time.time()
    gen_count = 0
    init_progress_file(PROGRESS_FILE)


def init_progress_file(path):
    with open(path, "w", encoding="utf-8") as f:
        f.write("timestamp,gen,nse_cal,nse_val,obj,convergence,elapsed_sec\n")


def log_msg(msg):
    print(msg)
    if LOG_FILE:
        with open(LOG_FILE, "a", encoding="utf-8") as f:
            f.write(msg + "\n")


def _increment_eval_count():
    global eval_count
    with OBJECTIVE_STATE_LOCK:
        eval_count += 1
        return int(eval_count)


def _increment_gen_count():
    global gen_count
    with OBJECTIVE_STATE_LOCK:
        gen_count += 1
        return int(gen_count)


def _update_best_state(obj, terms, vector):
    global best_score, best_objective, best_params
    if not terms:
        return
    obj_val = float(obj)
    if not np.isfinite(obj_val):
        return
    with OBJECTIVE_STATE_LOCK:
        if obj_val < float(best_objective):
            best_objective = obj_val
            best_score = float(terms.get("nse_cal", float("nan")))
            best_params = np.array(vector).copy()


def _snapshot_objective_state():
    with OBJECTIVE_STATE_LOCK:
        return (
            int(eval_count),
            int(gen_count),
            float(best_score),
            float(best_objective),
            None if best_params is None else np.array(best_params).copy(),
        )


def _is_valid_optimization_result(result):
    if result is None:
        return False
    fun = getattr(result, "fun", np.inf)
    if (not np.isfinite(fun)) or float(fun) >= BAD_OBJ:
        return False
    vector = getattr(result, "x", None)
    if vector is None:
        return False
    try:
        validate_parameter_vector(np.asarray(vector, dtype=np.float64))
    except Exception:
        return False
    return True


def _result_stat_int(result, key):
    if result is None:
        return 0
    value = getattr(result, key, None)
    if value is None:
        return 0
    try:
        return int(value)
    except Exception:
        return 0


def _build_result_stage_stats(result, **extra):
    stats = {key: value for key, value in extra.items() if value is not None}
    stats["executed"] = bool(result is not None)
    if result is None:
        return stats or None
    stats.update(
        {
            "success": bool(getattr(result, "success", False)),
            "valid": bool(_is_valid_optimization_result(result)),
            "nfev": _result_stat_int(result, "nfev"),
            "nit": _result_stat_int(result, "nit"),
            "message": str(getattr(result, "message", "") or ""),
        }
    )
    objective_value = getattr(result, "fun", np.nan)
    try:
        objective_value = float(objective_value)
    except Exception:
        objective_value = float("nan")
    stats["objective_value"] = round(objective_value, 6) if np.isfinite(objective_value) else None
    stage = str(getattr(result, "result_stage", "") or "").strip().lower()
    if stage:
        stats["stage"] = stage
    for attr_name in ("valid_samples", "invalid_samples", "processed_samples", "target_samples", "seed_samples", "progress_points"):
        if hasattr(result, attr_name):
            try:
                stats[attr_name] = int(getattr(result, attr_name))
            except Exception:
                pass
    return stats


def append_progress(gen, nse_cal, nse_val, obj, convergence):
    elapsed = time.time() - start_time
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    with open(PROGRESS_FILE, "a", encoding="utf-8") as f:
        f.write(f"{ts},{gen},{nse_cal:.6f},{nse_val:.6f},{obj:.6f},{convergence:.6f},{elapsed:.1f}\n")


def format_elapsed_hint(seconds):
    seconds = max(0.0, float(seconds or 0.0))
    if seconds < 60:
        return f"{seconds:.0f} 秒"
    minutes = seconds / 60.0
    if minutes < 60:
        return f"{minutes:.1f} 分钟"
    hours = minutes / 60.0
    return f"{hours:.1f} 小时"


def configure_time_step():
    global TIME_STEP_HOURS, MUSK_DT
    TIME_STEP_HOURS = float(TIME_STEP_HOURS)
    if TIME_STEP_HOURS <= 0.0:
        raise ValueError("TIME_STEP_HOURS 必须为正值。")
    MUSK_DT = TIME_STEP_HOURS / 24.0


def time_step_days():
    return TIME_STEP_HOURS / 24.0


def time_step_timedelta():
    return pd.to_timedelta(TIME_STEP_HOURS, unit="h")


def normalized_time_step_hours(value):
    hours = float(value)
    return 1.0 if hours <= 1.5 else 24.0


def detect_series_step_hours(index):
    timestamps = pd.DatetimeIndex(index).sort_values().drop_duplicates()
    if len(timestamps) < 2:
        return None
    diffs = timestamps.to_series().diff().dropna()
    if diffs.empty:
        return None
    median_hours = diffs.median() / pd.Timedelta(hours=1)
    return normalized_time_step_hours(median_hours)


def is_date_only_string(value):
    if not isinstance(value, str):
        return False
    text = value.strip()
    return (" " not in text) and ("T" not in text) and (len(text) <= 10)


def normalize_time_value(value, is_end=False):
    ts = pd.to_datetime(value)
    if is_end and (TIME_STEP_HOURS < 24.0) and is_date_only_string(value):
        ts = ts + pd.Timedelta(days=1) - time_step_timedelta()
    return ts


def build_time_index(start_date, end_date):
    return pd.date_range(normalize_time_value(start_date), normalize_time_value(end_date, is_end=True), freq=time_step_timedelta())


def format_time_value(value):
    ts = pd.to_datetime(value)
    if abs(TIME_STEP_HOURS - 24.0) < EPS and ts.hour == 0 and ts.minute == 0 and ts.second == 0:
        return ts.strftime("%Y-%m-%d")
    return ts.strftime("%Y-%m-%d %H:%M")


def compute_warmup_steps():
    start_ts = normalize_time_value(WARMUP_START)
    warmup_end_raw = str(WARMUP_END or "").strip()
    if warmup_end_raw:
        warmup_end = normalize_time_value(warmup_end_raw, is_end=True)
    else:
        calib_ts = normalize_time_value(CALIB_START)
        if calib_ts <= start_ts:
            return 0
        warmup_end = calib_ts - time_step_timedelta()
    if warmup_end < start_ts:
        return 0
    return len(build_time_index(start_ts, warmup_end))


def _load_debug_observation_series():
    if not OBS_FILE or (not os.path.exists(OBS_FILE)):
        return None
    try:
        info = inspect_observed_discharge(
            OBS_FILE,
            target_step_hours=TIME_STEP_HOURS,
            allow_hourly_to_daily=True,
            min_daily_hours=DEFAULT_MIN_DAILY_HOURS,
            return_series=True,
        )
    except Exception:
        return None
    series = info.get("series")
    if series is None:
        return None
    return series.astype(np.float64)


def _find_valid_debug_window(debug_days):
    obs_series = _load_debug_observation_series()
    if obs_series is None or obs_series.empty:
        return None

    requested_start = normalize_time_value(CALIB_START)
    search_end = min(normalize_time_value(CALIB_END, is_end=True), normalize_time_value(SIM_END, is_end=True))
    if search_end < requested_start:
        return None

    requested_end = min(
        requested_start + pd.to_timedelta(max(debug_days, 1), unit="D") - time_step_timedelta(),
        search_end,
    )
    search_index = pd.date_range(requested_start, search_end, freq=time_step_timedelta())
    if search_index.empty:
        return None

    window_steps = len(pd.date_range(requested_start, requested_end, freq=time_step_timedelta()))
    if window_steps <= 0:
        return None

    aligned = obs_series.reindex(search_index)
    min_valid_steps = min(window_steps, 3 if TIME_STEP_HOURS >= 24.0 else 12)
    rolling_count = aligned.rolling(window_steps, min_periods=min_valid_steps).count()
    rolling_std = aligned.rolling(window_steps, min_periods=min_valid_steps).std(ddof=0)

    for end_idx in range(window_steps - 1, len(search_index)):
        count_value = rolling_count.iloc[end_idx]
        std_value = rolling_std.iloc[end_idx]
        if pd.isna(count_value) or pd.isna(std_value):
            continue
        if float(count_value) < float(min_valid_steps) or float(std_value) <= EPS:
            continue
        start_idx = end_idx - window_steps + 1
        return {
            "requested_start": requested_start,
            "requested_end": requested_end,
            "effective_start": search_index[start_idx],
            "effective_end": search_index[end_idx],
            "shifted": search_index[start_idx] != requested_start,
            "window_steps": window_steps,
            "valid_obs_steps": int(count_value),
            "obs_std": float(std_value),
        }
    return {
        "requested_start": requested_start,
        "requested_end": requested_end,
        "effective_start": requested_start,
        "effective_end": requested_end,
        "shifted": False,
        "window_steps": window_steps,
        "valid_obs_steps": int(rolling_count.max()) if len(rolling_count) else 0,
        "obs_std": float(rolling_std.max()) if len(rolling_std) else float("nan"),
        "no_valid_window": True,
    }


def apply_debug_window(debug_days):
    global CALIB_START, CALIB_END, SIM_START, VALID_START, VALID_END, SIM_END
    debug_days = int(debug_days or 0)
    if debug_days <= 0:
        return None
    debug_info = _find_valid_debug_window(debug_days)
    if debug_info and debug_info.get("no_valid_window"):
        raise ValueError(
            f"短窗调试窗口 {debug_days} 天内没有足够变化的有效观测，建议增大 debug_days 或调整率定起始时间。"
        )
    calib_start_ts = pd.Timestamp(debug_info["effective_start"]) if debug_info else normalize_time_value(CALIB_START)
    full_end_ts = normalize_time_value(SIM_END, is_end=True)
    debug_end_ts = calib_start_ts + pd.to_timedelta(max(debug_days, 1), unit="D") - time_step_timedelta()
    final_end_ts = min(debug_end_ts, full_end_ts)
    calib_end_ts = min(normalize_time_value(CALIB_END, is_end=True), final_end_ts)
    original_valid_start_ts = normalize_time_value(VALID_START)
    valid_end_ts = min(normalize_time_value(VALID_END, is_end=True), final_end_ts)
    valid_start_ts = original_valid_start_ts if original_valid_start_ts <= valid_end_ts else valid_end_ts
    CALIB_START = format_time_value(calib_start_ts)
    CALIB_END = format_time_value(calib_end_ts)
    SIM_START = WARMUP_START
    VALID_START = format_time_value(valid_start_ts)
    VALID_END = format_time_value(valid_end_ts)
    SIM_END = format_time_value(final_end_ts)
    return {
        "debug_days": debug_days,
        "requested_start": format_time_value(debug_info["requested_start"]) if debug_info else CALIB_START,
        "requested_end": format_time_value(debug_info["requested_end"]) if debug_info else format_time_value(final_end_ts),
        "calib_start": CALIB_START,
        "calib_end": CALIB_END,
        "valid_start": VALID_START,
        "valid_end": VALID_END,
        "shifted": bool(debug_info and debug_info.get("shifted")),
        "valid_obs_steps": int(debug_info.get("valid_obs_steps", 0)) if debug_info else 0,
        "obs_std": float(debug_info.get("obs_std", float("nan"))) if debug_info else float("nan"),
        "sim_end": SIM_END,
    }


def scale_linear_to_step(value):
    return float(value) * time_step_days()


def scale_recession_to_step(value):
    clipped = min(max(float(value), 0.0), 0.999999)
    return 1.0 - ((1.0 - clipped) ** time_step_days())


def mm_km2_to_m3s_scale():
    return 1.0 / (3.6 * TIME_STEP_HOURS)


def compute_row_areas_km2(transform, height):
    pixel_width_deg = transform.a
    pixel_height_deg = -transform.e
    top_lat = transform.f
    r = 6371000.0
    dlon = radians(pixel_width_deg)
    row_areas = np.zeros(height, dtype=np.float64)
    for row in range(height):
        lat_n = top_lat - row * pixel_height_deg
        lat_s = top_lat - (row + 1) * pixel_height_deg
        row_areas[row] = (r ** 2) * dlon * (sin(radians(lat_n)) - sin(radians(lat_s))) / 1e6
    return row_areas


def parse_time_from_name(name):
    stem = os.path.splitext(os.path.basename(name))[0]
    candidates = [
        ("%Y.%m.%d.%H.%M", [r"\d{4}\.\d{2}\.\d{2}\.\d{2}\.\d{2}"]),
        ("%Y.%m.%d.%H", [r"\d{4}\.\d{2}\.\d{2}\.\d{2}"]),
        ("%Y-%m-%d %H:%M", [r"\d{4}-\d{2}-\d{2} \d{2}:\d{2}"]),
        ("%Y-%m-%dT%H:%M", [r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}"]),
        ("%Y.%m.%d", [r"\d{4}\.\d{2}\.\d{2}"]),
        ("%Y-%m-%d", [r"\d{4}-\d{2}-\d{2}"]),
    ]
    for fmt, patterns in candidates:
        for pattern in patterns:
            match = re.search(pattern, stem)
            if match:
                try:
                    return pd.to_datetime(match.group(0), format=fmt)
                except Exception:
                    pass
    try:
        return pd.to_datetime(stem)
    except Exception:
        return None


def detect_observed_time_column(frame):
    candidates = []
    for name in OBSERVED_DATE_COLUMN_HINTS:
        if name in frame.columns and name not in candidates:
            candidates.append(name)
    candidates.extend([col for col in frame.columns if col not in candidates])
    threshold = max(1, len(frame) // 3)
    for column in candidates:
        parsed = pd.to_datetime(frame[column], errors="coerce")
        if parsed.notna().sum() >= threshold:
            return column
    return None


def detect_observed_flow_column(frame, excluded=None):
    excluded_set = set(excluded or [])
    candidates = []
    for name in OBSERVED_FLOW_COLUMN_HINTS:
        if name in frame.columns and name not in excluded_set and name not in candidates:
            candidates.append(name)
    candidates.extend([col for col in frame.columns if col not in excluded_set and col not in candidates])
    threshold = max(1, len(frame) // 3)
    for column in candidates:
        numeric = pd.to_numeric(frame[column], errors="coerce")
        if numeric.notna().sum() >= threshold:
            return column
    return None


def build_time_file_map(directory):
    file_date_map = {}
    for file_path in glob(os.path.join(directory, "*.tif")):
        time_key = parse_time_from_name(file_path)
        if time_key is not None:
            file_date_map[time_key] = file_path
    return file_date_map


def scan_time_file_entries(directory):
    file_date_map = {}
    signature_entries = []
    duplicate_entries = {}
    for file_path in sorted(glob(os.path.join(directory, "*.tif"))):
        try:
            stat = os.stat(file_path)
        except OSError:
            continue
        time_key = parse_time_from_name(file_path)
        signature_entries.append(
            {
                "name": os.path.basename(file_path),
                "mtime_ns": int(getattr(stat, "st_mtime_ns", int(stat.st_mtime * 1e9))),
                "size": int(stat.st_size),
                "timestamp": (pd.Timestamp(time_key).isoformat() if time_key is not None else ""),
            }
        )
        if time_key is not None:
            if time_key in file_date_map:
                duplicate_entries.setdefault(time_key, [os.path.basename(file_date_map[time_key])]).append(os.path.basename(file_path))
            file_date_map[time_key] = file_path
    if duplicate_entries:
        first_time = sorted(duplicate_entries)[0]
        sample = "、".join(duplicate_entries[first_time][:3])
        raise ValueError(f"目录存在重复时间戳 {first_time}，例如：{sample}")
    return file_date_map, signature_entries


def safe_cache_label(cache_label):
    return re.sub(r"[^A-Za-z0-9_-]+", "_", str(cache_label or "stack")).strip("_") or "stack"


def stack_cache_source_payload(directory, cache_label, signature_entries):
    label = str(cache_label or os.path.basename(directory) or "stack")
    return {
        "version": STACK_CACHE_VERSION,
        "directory": os.path.abspath(directory),
        "label": label,
        "time_step_hours": float(TIME_STEP_HOURS),
        "entries": signature_entries,
    }


def stack_cache_source_token(directory, cache_label, signature_entries):
    payload = stack_cache_source_payload(directory, cache_label, signature_entries)
    token = hashlib.sha1(json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest()
    return payload, token


def stack_cache_paths(directory, start_date, end_date, cache_label, signature_entries):
    os.makedirs(CACHE_DIR, exist_ok=True)
    source_payload, source_token = stack_cache_source_token(directory, cache_label, signature_entries)
    payload = {
        "version": STACK_CACHE_VERSION,
        "source_token": source_token,
        "start": pd.Timestamp(normalize_time_value(start_date)).isoformat(),
        "end": pd.Timestamp(normalize_time_value(end_date, is_end=True)).isoformat(),
    }
    token = hashlib.sha1(json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest()
    base_path = os.path.join(CACHE_DIR, f"{safe_cache_label(source_payload['label'])}_{token[:16]}")
    return base_path + ".npy", base_path + ".json", token, source_token


def record_data_cache(cache_label, payload):
    DATA_LOAD_SUMMARY[str(cache_label)] = dict(payload)


def file_state_signature(path):
    try:
        stat = os.stat(path)
    except OSError:
        return {"path": os.path.abspath(path), "exists": False}
    return {
        "path": os.path.abspath(path),
        "exists": True,
        "mtime_ns": int(getattr(stat, "st_mtime_ns", int(stat.st_mtime * 1e9))),
        "size": int(stat.st_size),
    }


def summarize_time_samples(values, limit=5):
    samples = [format_time_value(value) for value in list(values)[: max(1, int(limit))]]
    return "、".join(samples)


def ensure_expected_time_steps(label, dates, file_date_map, directory):
    missing_dates = [date for date in dates if date not in file_date_map]
    if missing_dates:
        sample = summarize_time_samples(missing_dates)
        raise ValueError(
            f"{label} 缺少 {len(missing_dates)} 个期望时步，目录：{directory}，例如：{sample}"
        )


def ensure_raster_alignment(label, src, expected_shape, expected_transform, expected_crs, file_path):
    current_shape = (int(src.height), int(src.width))
    if current_shape != tuple(expected_shape):
        raise ValueError(
            f"{label} 栅格尺寸不一致：{os.path.basename(file_path)} 为 {current_shape}，期望 {tuple(expected_shape)}"
        )
    if src.transform != expected_transform:
        raise ValueError(
            f"{label} 栅格变换不一致：{os.path.basename(file_path)} 与首个栅格不一致"
        )
    if src.crs != expected_crs:
        raise ValueError(
            f"{label} 栅格坐标系不一致：{os.path.basename(file_path)} 为 {src.crs}，期望 {expected_crs}"
        )


def ensure_loaded_stack_alignment(label, actual_shape, actual_transform, actual_crs, expected_shape, expected_transform, expected_crs):
    if tuple(actual_shape) != tuple(expected_shape):
        raise ValueError(
            f"{label} 栅格堆栈形状不一致：actual={list(actual_shape)} expected={list(expected_shape)}"
        )
    if actual_transform != expected_transform:
        raise ValueError(f"{label} 栅格变换与主降水网格不一致")
    if actual_crs != expected_crs:
        raise ValueError(f"{label} 栅格坐标系与主降水网格不一致：actual={actual_crs} expected={expected_crs}")


def cache_meta_matches_source(meta, label, directory, source_token):
    if str(meta.get("label", "") or "").strip() != str(label or "").strip():
        return False
    if os.path.abspath(str(meta.get("directory", "") or "")) != os.path.abspath(directory):
        return False
    if str(meta.get("source_token", "") or "").strip() != str(source_token or "").strip():
        return False
    try:
        return abs(float(meta.get("time_step_hours", TIME_STEP_HOURS)) - float(TIME_STEP_HOURS)) < EPS
    except Exception:
        return False


def covering_stack_cache(label, directory, requested_dates, expected_shape, expected_transform, expected_crs, source_token, exclude_meta_path=None):
    pattern = os.path.join(CACHE_DIR, f"{safe_cache_label(label)}_*.json")
    candidates = []
    exclude_abs = os.path.abspath(exclude_meta_path) if exclude_meta_path else ""
    for meta_path in glob(pattern):
        if exclude_abs and os.path.abspath(meta_path) == exclude_abs:
            continue
        try:
            with open(meta_path, "r", encoding="utf-8") as f:
                meta = json.load(f)
        except Exception:
            continue
        if not cache_meta_matches_source(meta, label, directory, source_token):
            continue
        try:
            shape = tuple(int(v) for v in meta.get("shape", ()))
            start_ts = normalize_time_value(meta["start"])
            end_ts = normalize_time_value(meta["end"], is_end=True)
        except Exception:
            continue
        if len(shape) != 3 or tuple(shape[:2]) != tuple(expected_shape):
            continue
        if start_ts > requested_dates[0] or end_ts < requested_dates[-1]:
            continue
        candidates.append((int(shape[2]), meta_path, meta))

    for _, meta_path, meta in sorted(candidates, key=lambda item: item[0]):
        data_path = os.path.splitext(meta_path)[0] + ".npy"
        if not os.path.exists(data_path):
            continue
        try:
            data = np.load(data_path, allow_pickle=False)
            shape = tuple(int(v) for v in meta.get("shape", ()))
            if tuple(data.shape) != shape:
                raise ValueError(f"缓存形状不一致：meta={list(shape)} actual={list(data.shape)}")
            transform = Affine(*meta["transform"])
            crs_text = str(meta.get("crs", "") or "").strip()
            crs = rasterio.crs.CRS.from_string(crs_text) if crs_text else None
            if tuple(data.shape[:2]) != tuple(expected_shape):
                raise ValueError(f"缓存空间形状不一致：actual={list(data.shape[:2])} expected={list(expected_shape)}")
            if transform != expected_transform:
                raise ValueError("缓存栅格变换与当前网格不一致")
            if crs != expected_crs:
                raise ValueError(f"缓存坐标系不一致：actual={crs} expected={expected_crs}")
            cached_dates = build_time_index(meta["start"], meta["end"])
            start_idx = int(cached_dates.get_indexer([requested_dates[0]])[0])
            end_idx = int(cached_dates.get_indexer([requested_dates[-1]])[0])
            if start_idx < 0 or end_idx < start_idx:
                raise ValueError("缓存时间索引无法覆盖请求时间窗")
            cached_window = cached_dates[start_idx:end_idx + 1]
            if (len(cached_window) != len(requested_dates)) or (not cached_window.equals(requested_dates)):
                raise ValueError("缓存时间窗与请求时间窗不完全一致")
            subset = data[:, :, start_idx:end_idx + 1]
            all_nan_steps = np.where(~np.isfinite(subset).any(axis=(0, 1)))[0]
            if len(all_nan_steps):
                bad_dates = [requested_dates[int(idx)] for idx in all_nan_steps[:5]]
                raise ValueError(f"缓存存在空白时步：{summarize_time_samples(bad_dates)}")
            return subset, data_path
        except Exception as exc:
            log_msg(f"[缓存候选跳过] {label} 覆盖缓存校验失败：{os.path.basename(data_path)} ({exc})")
    return None, None


def covering_series_cache(label, directory, requested_dates, source_token, exclude_meta_path=None):
    pattern = os.path.join(CACHE_DIR, f"{safe_cache_label(label)}_*.json")
    candidates = []
    exclude_abs = os.path.abspath(exclude_meta_path) if exclude_meta_path else ""
    for meta_path in glob(pattern):
        if exclude_abs and os.path.abspath(meta_path) == exclude_abs:
            continue
        try:
            with open(meta_path, "r", encoding="utf-8") as f:
                meta = json.load(f)
        except Exception:
            continue
        if not cache_meta_matches_source(meta, label, directory, source_token):
            continue
        try:
            shape = tuple(int(v) for v in meta.get("shape", ()))
            start_ts = normalize_time_value(meta["start"])
            end_ts = normalize_time_value(meta["end"], is_end=True)
        except Exception:
            continue
        if len(shape) != 1:
            continue
        if start_ts > requested_dates[0] or end_ts < requested_dates[-1]:
            continue
        candidates.append((int(shape[0]), meta_path, meta))

    for _, meta_path, meta in sorted(candidates, key=lambda item: item[0]):
        data_path = os.path.splitext(meta_path)[0] + ".npy"
        if not os.path.exists(data_path):
            continue
        try:
            series = np.load(data_path, allow_pickle=False)
            shape = tuple(int(v) for v in meta.get("shape", ()))
            if tuple(series.shape) != shape:
                raise ValueError(f"缓存形状不一致：meta={list(shape)} actual={list(series.shape)}")
            cached_dates = build_time_index(meta["start"], meta["end"])
            start_idx = int(cached_dates.get_indexer([requested_dates[0]])[0])
            end_idx = int(cached_dates.get_indexer([requested_dates[-1]])[0])
            if start_idx < 0 or end_idx < start_idx:
                raise ValueError("缓存时间索引无法覆盖请求时间窗")
            cached_window = cached_dates[start_idx:end_idx + 1]
            if (len(cached_window) != len(requested_dates)) or (not cached_window.equals(requested_dates)):
                raise ValueError("缓存时间窗与请求时间窗不完全一致")
            subset = series[start_idx:end_idx + 1]
            all_nan_steps = np.where(~np.isfinite(subset))[0]
            if len(all_nan_steps):
                bad_dates = [requested_dates[int(idx)] for idx in all_nan_steps[:5]]
                raise ValueError(f"缓存存在空白时步：{summarize_time_samples(bad_dates)}")
            return subset, data_path
        except Exception as exc:
            log_msg(f"[缓存候选跳过] {label} 覆盖缓存校验失败：{os.path.basename(data_path)} ({exc})")
    return None, None


def load_raster_stack(directory, start_date, end_date, cache_label=None):
    dates = build_time_index(start_date, end_date)
    file_date_map, signature_entries = scan_time_file_entries(directory)
    if not file_date_map:
        raise ValueError(f"目录中未找到 .tif 文件：{directory}")

    label = str(cache_label or os.path.basename(directory) or "stack")
    ensure_expected_time_steps(label, dates, file_date_map, directory)
    cache_data_path, cache_meta_path, cache_token, source_token = stack_cache_paths(directory, start_date, end_date, label, signature_entries)
    if os.path.exists(cache_data_path) and os.path.exists(cache_meta_path):
        try:
            with open(cache_meta_path, "r", encoding="utf-8") as f:
                cache_meta = json.load(f)
            data = np.load(cache_data_path, allow_pickle=False)
            transform = Affine(*cache_meta["transform"])
            crs_text = str(cache_meta.get("crs", "") or "").strip()
            crs = rasterio.crs.CRS.from_string(crs_text) if crs_text else None
            if tuple(cache_meta.get("shape", ())) != tuple(data.shape):
                raise ValueError(f"缓存形状不一致：meta={cache_meta.get('shape')} actual={list(data.shape)}")
            all_nan_steps = np.where(~np.isfinite(data).any(axis=(0, 1)))[0]
            if len(all_nan_steps):
                bad_dates = [dates[int(idx)] for idx in all_nan_steps[:5]]
                raise ValueError(f"缓存存在空白时步：{summarize_time_samples(bad_dates)}")
            record_data_cache(
                label,
                {
                    "cache_hit": True,
                    "cache_hit_type": "exact",
                    "cache_path": cache_data_path,
                    "source_dir": directory,
                    "time_steps": int(len(dates)),
                    "source_files": int(len(signature_entries)),
                    "shape": [int(v) for v in data.shape],
                    "source_token": source_token,
                },
            )
            log_msg(f"[缓存命中] {label} 栅格堆栈 -> {cache_data_path}")
            return data, transform, crs
        except Exception as exc:
            log_msg(f"[缓存失效] {label} 读取缓存失败，将重建：{exc}")

    first_file = next(iter(file_date_map.values()))
    with rasterio.open(first_file) as src:
        rows, cols = src.height, src.width
        transform = src.transform
        crs = src.crs

    covering_data, covering_path = covering_stack_cache(
        label,
        directory,
        dates,
        (rows, cols),
        transform,
        crs,
        source_token,
        exclude_meta_path=cache_meta_path,
    )
    if covering_data is not None:
        record_data_cache(
            label,
            {
                "cache_hit": True,
                "cache_hit_type": "covering_slice",
                "cache_path": covering_path,
                "source_dir": directory,
                "time_steps": int(len(dates)),
                "source_files": int(len(signature_entries)),
                "shape": [int(v) for v in covering_data.shape],
                "source_token": source_token,
            },
        )
        log_msg(f"[缓存命中] {label} 栅格堆栈 -> {covering_path}（覆盖切片）")
        return covering_data, transform, crs

    data = np.full((rows, cols, len(dates)), np.nan, dtype=np.float32)
    for i, date in enumerate(dates):
        file_path = file_date_map[date]
        with rasterio.open(file_path) as src:
            ensure_raster_alignment(label, src, (rows, cols), transform, crs, file_path)
            arr = src.read(1).astype(np.float32)
            nodata = src.nodata
            if nodata is not None:
                arr[arr == nodata] = np.nan
            arr[arr < -9000] = np.nan
            arr[arr > 1e10] = np.nan
            data[:, :, i] = arr

    all_nan_steps = np.where(~np.isfinite(data).any(axis=(0, 1)))[0]
    if len(all_nan_steps):
        bad_dates = [dates[int(idx)] for idx in all_nan_steps[:5]]
        raise ValueError(f"{label} 存在整步空白栅格：{summarize_time_samples(bad_dates)}")

    cache_meta = {
        "version": STACK_CACHE_VERSION,
        "label": label,
        "directory": os.path.abspath(directory),
        "shape": [int(rows), int(cols), int(len(dates))],
        "dtype": str(data.dtype),
        "transform": [float(transform.a), float(transform.b), float(transform.c), float(transform.d), float(transform.e), float(transform.f)],
        "crs": (crs.to_string() if crs is not None else ""),
        "time_step_hours": float(TIME_STEP_HOURS),
        "start": pd.Timestamp(normalize_time_value(start_date)).isoformat(),
        "end": pd.Timestamp(normalize_time_value(end_date, is_end=True)).isoformat(),
        "token": cache_token,
        "source_token": source_token,
        "source_files": int(len(signature_entries)),
        "built_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    }
    try:
        tmp_data_path = cache_data_path + ".tmp"
        tmp_meta_path = cache_meta_path + ".tmp"
        with open(tmp_data_path, "wb") as f:
            np.save(f, data, allow_pickle=False)
        with open(tmp_meta_path, "w", encoding="utf-8") as f:
            json.dump(cache_meta, f, ensure_ascii=False, indent=2)
        os.replace(tmp_data_path, cache_data_path)
        os.replace(tmp_meta_path, cache_meta_path)
        log_msg(f"[缓存写入] {label} 栅格堆栈 -> {cache_data_path}")
    except Exception as exc:
        log_msg(f"[缓存跳过] {label} 栅格堆栈写入失败：{exc}")

    record_data_cache(
        label,
        {
            "cache_hit": False,
            "cache_hit_type": "rebuilt",
            "cache_path": cache_data_path,
            "source_dir": directory,
            "time_steps": int(len(dates)),
            "source_files": int(len(signature_entries)),
            "shape": [int(rows), int(cols), int(len(dates))],
            "source_token": source_token,
        },
    )

    return data, transform, crs


def _is_contiguous_unique_index(dates):
    dates = pd.DatetimeIndex(dates)
    if len(dates) <= 1:
        return True
    if dates.has_duplicates:
        return False
    diffs = dates[1:] - dates[:-1]
    return bool(np.all(diffs == time_step_timedelta()))


def load_raster_stack_for_dates(directory, dates, cache_label=None):
    dates = pd.DatetimeIndex(dates)
    if len(dates) == 0:
        raise ValueError(f"{cache_label or directory} 没有需要读取的时步。")
    if _is_contiguous_unique_index(dates):
        return load_raster_stack(directory, dates[0], dates[-1], cache_label=cache_label)

    file_date_map, signature_entries = scan_time_file_entries(directory)
    if not file_date_map:
        raise ValueError(f"目录中未找到 .tif 文件：{directory}")

    label = str(cache_label or os.path.basename(directory) or "stack")
    ensure_expected_time_steps(label, dates, file_date_map, directory)

    first_file = next(iter(file_date_map.values()))
    with rasterio.open(first_file) as src:
        rows, cols = src.height, src.width
        transform = src.transform
        crs = src.crs

    data = np.full((rows, cols, len(dates)), np.nan, dtype=np.float32)
    for i, date in enumerate(dates):
        file_path = file_date_map[pd.Timestamp(date)]
        with rasterio.open(file_path) as src:
            ensure_raster_alignment(label, src, (rows, cols), transform, crs, file_path)
            arr = src.read(1).astype(np.float32)
            nodata = src.nodata
            if nodata is not None:
                arr[arr == nodata] = np.nan
            arr[arr < -9000] = np.nan
            arr[arr > 1e10] = np.nan
            data[:, :, i] = arr

    all_nan_steps = np.where(~np.isfinite(data).any(axis=(0, 1)))[0]
    if len(all_nan_steps):
        bad_dates = [dates[int(idx)] for idx in all_nan_steps[:5]]
        raise ValueError(f"{label} 存在整步空白栅格：{summarize_time_samples(bad_dates)}")

    _source_payload, source_token = stack_cache_source_token(directory, label, signature_entries)
    record_data_cache(
        label,
        {
            "cache_hit": False,
            "cache_hit_type": "event_window_direct",
            "cache_path": "",
            "source_dir": directory,
            "time_steps": int(len(dates)),
            "source_files": int(len(signature_entries)),
            "shape": [int(rows), int(cols), int(len(dates))],
            "source_token": source_token,
            "event_window_runtime": True,
        },
    )
    log_msg(
        f"[事件资料] {label} 按 {len(dates)} 个事件窗口时步读取，"
        "事件之间不要求连续栅格。"
    )
    return data, transform, crs


def trim_warmup(arr):
    if arr is None:
        return None
    return arr


def glacier_processing_mode():
    mode = str(GLACIER_MODEL_MODE or "").strip().lower()
    return mode or "binary_legacy"


def glacier_feature_enabled():
    if args.glacier_mode != "inline":
        return False
    if glacier_processing_mode() == "fractional_subgrid":
        return bool((GLACIER_FRACTION is not None) and np.any((GLACIER_FRACTION > 0.0) & np.isfinite(FLOW_ACC)))
    return bool((GLACIER_MASK is not None) and np.any(GLACIER_MASK & np.isfinite(FLOW_ACC)))


def glacier_reference_active_cells():
    if glacier_processing_mode() == "fractional_subgrid" and GLACIER_FRACTION is not None:
        return (GLACIER_FRACTION > 0.0) & np.isfinite(FLOW_ACC)
    if GLACIER_MASK is None:
        return None
    return GLACIER_MASK & np.isfinite(FLOW_ACC)


def run_fractional_subgrid_simulation_arrays(
    mode_name,
    par_base,
    ice_factor,
    cfmax_low_step,
    cfmax_high_step,
    prec_cells,
    temp_cells,
    et_cells,
    ll_temp_cells,
):
    glacier_scale = (CELL_SCALE * GLACIER_FRACTION_CELLS).astype(np.float64, copy=False)
    nonglacier_scale = (CELL_SCALE * (1.0 - GLACIER_FRACTION_CELLS)).astype(np.float64, copy=False)
    glacier_cells = np.ascontiguousarray(GLACIER_FRACTION_CELLS > 0.0, dtype=np.bool_)
    nonglacier_cells = np.zeros_like(glacier_cells, dtype=np.bool_)

    if mode_name == "objective_total":
        q_total_glacier = run_all_cells_total_only_flat(
            prec_cells, temp_cells, et_cells, ll_temp_cells,
            par_base, ZONE_HIGH_CELLS, INIT_ST, glacier_scale,
            glacier_cells, True, ice_factor, cfmax_low_step, cfmax_high_step,
            GLACIER_DELTA_T_CELLS,
        )
        q_total_nonglacier = run_all_cells_total_only_flat(
            prec_cells, temp_cells, et_cells, ll_temp_cells,
            par_base, ZONE_HIGH_CELLS, INIT_ST, nonglacier_scale,
            nonglacier_cells, False, ice_factor, cfmax_low_step, cfmax_high_step,
            GLACIER_DELTA_T_CELLS,
        )
        return {"q_total": q_total_glacier + q_total_nonglacier}

    if mode_name == "objective_ice":
        q_total_glacier, q_ice_glacier = run_all_cells_total_ice_flat(
            prec_cells, temp_cells, et_cells, ll_temp_cells,
            par_base, ZONE_HIGH_CELLS, INIT_ST, glacier_scale,
            glacier_cells, True, ice_factor, cfmax_low_step, cfmax_high_step,
            GLACIER_DELTA_T_CELLS,
        )
        q_total_nonglacier, q_ice_nonglacier = run_all_cells_total_ice_flat(
            prec_cells, temp_cells, et_cells, ll_temp_cells,
            par_base, ZONE_HIGH_CELLS, INIT_ST, nonglacier_scale,
            nonglacier_cells, False, ice_factor, cfmax_low_step, cfmax_high_step,
            GLACIER_DELTA_T_CELLS,
        )
        return {
            "q_total": q_total_glacier + q_total_nonglacier,
            "q_ice": q_ice_glacier + q_ice_nonglacier,
        }

    q_total_glacier, q_rain_glacier, q_snow_glacier, q_ice_glacier = run_all_cells_flat(
        prec_cells, temp_cells, et_cells, ll_temp_cells,
        par_base, ZONE_HIGH_CELLS, INIT_ST, glacier_scale,
        glacier_cells, True, ice_factor, cfmax_low_step, cfmax_high_step,
        GLACIER_DELTA_T_CELLS,
    )
    q_total_nonglacier, q_rain_nonglacier, q_snow_nonglacier, q_ice_nonglacier = run_all_cells_flat(
        prec_cells, temp_cells, et_cells, ll_temp_cells,
        par_base, ZONE_HIGH_CELLS, INIT_ST, nonglacier_scale,
        nonglacier_cells, False, ice_factor, cfmax_low_step, cfmax_high_step,
        GLACIER_DELTA_T_CELLS,
    )
    return {
        "q_total": q_total_glacier + q_total_nonglacier,
        "q_rain": q_rain_glacier + q_rain_nonglacier,
        "q_snow": q_snow_glacier + q_snow_nonglacier,
        "q_ice": q_ice_glacier + q_ice_nonglacier,
        "q_snow_glacier": q_snow_glacier,
        "q_glacier_total": q_snow_glacier + q_ice_glacier,
    }


def run_fractional_subgrid_simulation(mode_name, par_base, ice_factor, cfmax_low_step, cfmax_high_step):
    return run_fractional_subgrid_simulation_arrays(
        mode_name,
        par_base,
        ice_factor,
        cfmax_low_step,
        cfmax_high_step,
        PREC_CELLS,
        TEMP_CELLS,
        ET_CELLS,
        LL_TEMP_CELLS,
    )


def build_cfmax_grid(cfmax_low, cfmax_high):
    cfmax_grid = np.zeros((PREC_3D.shape[0], PREC_3D.shape[1]), dtype=np.float64)
    cfmax_grid[ZONE_LOW] = cfmax_low
    cfmax_grid[ZONE_HIGH] = cfmax_high
    return cfmax_grid


def route_series_set(q_total, boundary_full, q_rain, q_snow, q_ice, k_musk, x_musk):
    q_total_in = q_total + boundary_full
    return {
        "q_total": trim_warmup(muskingum_route(q_total_in, k_musk, x_musk, MUSK_DT)),
        "q_local": trim_warmup(muskingum_route(q_total, k_musk, x_musk, MUSK_DT)),
        "q_boundary": trim_warmup(muskingum_route(boundary_full, k_musk, x_musk, MUSK_DT)),
        "q_rain": trim_warmup(muskingum_route(q_rain, k_musk, x_musk, MUSK_DT)),
        "q_snow": trim_warmup(muskingum_route(q_snow, k_musk, x_musk, MUSK_DT)),
        "q_ice": trim_warmup(muskingum_route(q_ice, k_musk, x_musk, MUSK_DT)),
        "q_local_raw": trim_warmup(q_total),
        "q_boundary_raw": trim_warmup(boundary_full),
        "q_rain_raw": trim_warmup(q_rain),
        "q_snow_raw": trim_warmup(q_snow),
        "q_ice_raw": trim_warmup(q_ice),
    }


def event_runtime_independent_active():
    return bool(
        EVENT_RUNTIME_ENABLED
        and EVENT_RUNTIME_WINDOWS
        and str(EVENT_RUNTIME_MODE or "").strip().lower() in {"independent_event_windows", "event_windows", "event_segments"}
    )


def _event_runtime_slices(length):
    if not event_runtime_independent_active():
        return [slice(0, int(length))]
    slices = []
    for window in EVENT_RUNTIME_WINDOWS:
        start = max(0, int(window.get("start_idx", 0) or 0))
        end = min(int(length) - 1, int(window.get("end_idx", start) or start))
        if end >= start:
            slices.append(slice(start, end + 1))
    return slices or [slice(0, int(length))]


def route_event_window_series(q_in, k_musk, x_musk):
    arr = np.asarray(q_in, dtype=np.float64)
    if arr.size == 0:
        return arr.copy()
    routed = np.full(arr.shape, np.nan, dtype=np.float64)
    for seg in _event_runtime_slices(len(arr)):
        routed[seg] = muskingum_route(arr[seg], k_musk, x_musk, MUSK_DT)
    return trim_warmup(routed)


def route_runtime_series(q_in, k_musk, x_musk):
    if event_runtime_independent_active():
        return route_event_window_series(q_in, k_musk, x_musk)
    return trim_warmup(muskingum_route(q_in, k_musk, x_musk, MUSK_DT))


def route_event_window_series_set(q_total, boundary_full, q_rain, q_snow, q_ice, k_musk, x_musk):
    q_total_in = q_total + boundary_full
    return {
        "q_total": route_event_window_series(q_total_in, k_musk, x_musk),
        "q_local": route_event_window_series(q_total, k_musk, x_musk),
        "q_boundary": route_event_window_series(boundary_full, k_musk, x_musk),
        "q_rain": route_event_window_series(q_rain, k_musk, x_musk),
        "q_snow": route_event_window_series(q_snow, k_musk, x_musk),
        "q_ice": route_event_window_series(q_ice, k_musk, x_musk),
        "q_local_raw": trim_warmup(q_total),
        "q_boundary_raw": trim_warmup(boundary_full),
        "q_rain_raw": trim_warmup(q_rain),
        "q_snow_raw": trim_warmup(q_snow),
        "q_ice_raw": trim_warmup(q_ice),
    }


def run_event_window_source_parts(
    mode_name,
    par_base,
    ice_factor,
    cfmax_low_step,
    cfmax_high_step,
    glacier_on,
    use_fractional_subgrid,
):
    chunks = []
    for seg in _event_runtime_slices(PREC_CELLS.shape[1]):
        prec_seg = np.ascontiguousarray(PREC_CELLS[:, seg], dtype=np.float32)
        temp_seg = np.ascontiguousarray(TEMP_CELLS[:, seg], dtype=np.float32)
        et_seg = np.ascontiguousarray(ET_CELLS[:, seg], dtype=np.float32)
        ll_temp_seg = np.ascontiguousarray(LL_TEMP_CELLS[:, seg], dtype=np.float32)
        if use_fractional_subgrid:
            parts = run_fractional_subgrid_simulation_arrays(
                mode_name,
                par_base,
                ice_factor,
                cfmax_low_step,
                cfmax_high_step,
                prec_seg,
                temp_seg,
                et_seg,
                ll_temp_seg,
            )
        elif mode_name == "objective_total":
            parts = {
                "q_total": run_all_cells_total_only_flat(
                    prec_seg, temp_seg, et_seg, ll_temp_seg,
                    par_base, ZONE_HIGH_CELLS, INIT_ST, CELL_SCALE,
                    GLACIER_CELLS, glacier_on, ice_factor, cfmax_low_step, cfmax_high_step,
                    GLACIER_DELTA_T_CELLS,
                )
            }
        elif mode_name == "objective_ice":
            q_total, q_ice = run_all_cells_total_ice_flat(
                prec_seg, temp_seg, et_seg, ll_temp_seg,
                par_base, ZONE_HIGH_CELLS, INIT_ST, CELL_SCALE,
                GLACIER_CELLS, glacier_on, ice_factor, cfmax_low_step, cfmax_high_step,
                GLACIER_DELTA_T_CELLS,
            )
            parts = {"q_total": q_total, "q_ice": q_ice}
        else:
            q_total, q_rain, q_snow, q_ice = run_all_cells_flat(
                prec_seg, temp_seg, et_seg, ll_temp_seg,
                par_base, ZONE_HIGH_CELLS, INIT_ST, CELL_SCALE,
                GLACIER_CELLS, glacier_on, ice_factor, cfmax_low_step, cfmax_high_step,
                GLACIER_DELTA_T_CELLS,
            )
            q_snow_glacier = np.asarray(q_snow, dtype=np.float64).copy() if glacier_on else np.zeros_like(q_total, dtype=np.float64)
            parts = {
                "q_total": q_total,
                "q_rain": q_rain,
                "q_snow": q_snow,
                "q_ice": q_ice,
                "q_snow_glacier": q_snow_glacier,
                "q_glacier_total": q_snow_glacier + np.asarray(q_ice, dtype=np.float64),
            }
        chunks.append(parts)

    keys = sorted({key for chunk in chunks for key in chunk.keys()})
    combined = {}
    for key in keys:
        values = [np.asarray(chunk[key], dtype=np.float64) for chunk in chunks if key in chunk]
        if values:
            combined[key] = np.concatenate(values)
    return combined


def _last_finite_value(values):
    if values is None:
        return float("nan")
    try:
        arr = np.asarray(values, dtype=np.float64).reshape(-1)
    except Exception:
        return float("nan")
    finite = arr[np.isfinite(arr)]
    return float(finite[-1]) if finite.size else float("nan")


def _snapshot_scalar(snapshot, key, default=float("nan")):
    try:
        value = snapshot.get(key, default) if isinstance(snapshot, dict) else snapshot[key]
    except Exception:
        return float(default)
    try:
        arr = np.asarray(value, dtype=np.float64).reshape(-1)
    except Exception:
        return float(default)
    if arr.size == 0 or not np.isfinite(arr[0]):
        return float(default)
    return float(arr[0])


def muskingum_route_warm_start(q_in, k, x, dt, previous_in=None, previous_out=None):
    q_in = np.asarray(q_in, dtype=np.float64)
    n = len(q_in)
    q_out = np.zeros(n, dtype=np.float64)
    if n == 0:
        return q_out
    denom = 2 * k * (1 - x) + dt
    c0 = (dt - 2 * k * x) / denom
    c1 = (dt + 2 * k * x) / denom
    c2 = (2 * k * (1 - x) - dt) / denom
    prev_in = float(previous_in) if previous_in is not None and np.isfinite(float(previous_in)) else float("nan")
    prev_out = float(previous_out) if previous_out is not None and np.isfinite(float(previous_out)) else float("nan")
    if np.isfinite(prev_in) and np.isfinite(prev_out):
        q_out[0] = c0 * q_in[0] + c1 * prev_in + c2 * prev_out
    else:
        q_out[0] = q_in[0]
    if q_out[0] < 0:
        q_out[0] = 0.0
    for i in range(1, n):
        q_out[i] = c0 * q_in[i] + c1 * q_in[i - 1] + c2 * q_out[i - 1]
        if q_out[i] < 0:
            q_out[i] = 0.0
    return q_out


def build_routing_state_snapshot(sim):
    if not isinstance(sim, dict):
        return {}
    local_raw = sim.get("q_local_raw")
    boundary_raw = sim.get("q_boundary_raw")
    if local_raw is not None and boundary_raw is not None:
        try:
            q_total_in = np.asarray(local_raw, dtype=np.float64) + np.asarray(boundary_raw, dtype=np.float64)
        except Exception:
            q_total_in = None
    else:
        q_total_in = sim.get("q_total_raw")
    fields = {
        "routing_q_total": (q_total_in, sim.get("q_total")),
        "routing_q_local": (local_raw, sim.get("q_local")),
        "routing_q_boundary": (boundary_raw, sim.get("q_boundary")),
        "routing_q_rain": (sim.get("q_rain_raw"), sim.get("q_rain")),
        "routing_q_snow": (sim.get("q_snow_raw"), sim.get("q_snow")),
        "routing_q_ice": (sim.get("q_ice_raw"), sim.get("q_ice")),
    }
    state = {}
    for prefix, (raw_values, routed_values) in fields.items():
        state[f"{prefix}_in_last"] = _last_finite_value(raw_values)
        state[f"{prefix}_out_last"] = _last_finite_value(routed_values)
    return state


def append_routing_state_to_snapshot(snapshot_arrays, sim):
    for key, value in build_routing_state_snapshot(sim).items():
        snapshot_arrays[key] = np.asarray([float(value)], dtype=np.float64)


def _route_forecast_series_set(q_total, boundary_full, q_rain, q_snow, q_ice, k_musk, x_musk, routing_state=None):
    routing_state = dict(routing_state or {})
    q_total_in = q_total + boundary_full

    def routed(name, raw):
        return muskingum_route_warm_start(
            raw,
            k_musk,
            x_musk,
            MUSK_DT,
            routing_state.get(f"routing_{name}_in_last"),
            routing_state.get(f"routing_{name}_out_last"),
        )

    return {
        "q_total": routed("q_total", q_total_in),
        "q_local": routed("q_local", q_total),
        "q_boundary": routed("q_boundary", boundary_full),
        "q_rain": routed("q_rain", q_rain),
        "q_snow": routed("q_snow", q_snow),
        "q_ice": routed("q_ice", q_ice),
        "q_local_raw": np.asarray(q_total, dtype=np.float64),
        "q_boundary_raw": np.asarray(boundary_full, dtype=np.float64),
        "q_rain_raw": np.asarray(q_rain, dtype=np.float64),
        "q_snow_raw": np.asarray(q_snow, dtype=np.float64),
        "q_ice_raw": np.asarray(q_ice, dtype=np.float64),
    }


def load_state_snapshot(path):
    snapshot_path = os.fspath(path)
    with np.load(snapshot_path, allow_pickle=False) as data:
        return {key: data[key].copy() for key in data.files}


def _snapshot_branch_tuple(snapshot, prefix):
    required = ("sp", "sm", "wc", "uz_r", "uz_s", "uz_i", "lz_r", "lz_s", "lz_i")
    arrays = []
    for name in required:
        key = f"{prefix}{name}"
        if key not in snapshot:
            raise ValueError(f"状态快照缺少 {key}。")
        arrays.append(np.ascontiguousarray(snapshot[key], dtype=np.float32))
    return tuple(arrays)


def _validate_snapshot_grid(snapshot):
    if VALID_CELLS is None:
        raise ValueError("尚未加载未来预报网格，无法校验状态快照。")
    expected_count = int(len(VALID_CELLS))
    rows = snapshot.get("valid_cell_rows")
    cols = snapshot.get("valid_cell_cols")
    if rows is None or cols is None:
        raise ValueError("状态快照缺少有效像元索引。")
    rows = np.asarray(rows, dtype=np.int64)
    cols = np.asarray(cols, dtype=np.int64)
    if rows.shape[0] != expected_count or cols.shape[0] != expected_count:
        raise ValueError(f"状态快照像元数与当前工作区不一致：快照 {rows.shape[0]}，当前 {expected_count}。")
    if not (
        np.array_equal(rows, np.asarray(VALID_CELLS[:, 0], dtype=np.int64))
        and np.array_equal(cols, np.asarray(VALID_CELLS[:, 1], dtype=np.int64))
    ):
        raise ValueError("状态快照有效像元顺序与当前地理网格不一致，不能热启动。")


def _forecast_par_base(opt_params):
    opt_params = validate_parameter_vector(opt_params)
    TT, FC, BETA, LP, RFCF, SFCF, CFR, CWH, CFMAX_low, CFMAX_high, K, K1, K2, UZL, PERC, ICE_FACTOR, K_MUSK, X_MUSK = opt_params
    cfmax_low_step = scale_linear_to_step(CFMAX_low)
    cfmax_high_step = scale_linear_to_step(CFMAX_high)
    cfr_step = scale_linear_to_step(CFR)
    k_step = scale_recession_to_step(K)
    k1_step = scale_recession_to_step(K1)
    k2_step = scale_recession_to_step(K2)
    perc_step = scale_linear_to_step(PERC)
    par_base = np.array([
        TT, RFCF, SFCF, 0.0, CWH, cfr_step,
        FC, BETA, FIXED["E_CORR"], LP, k_step, k1_step, k2_step, UZL, perc_step,
    ], dtype=np.float64)
    return par_base, ICE_FACTOR, K_MUSK, X_MUSK, cfmax_low_step, cfmax_high_step


def _run_forecast_branch(snapshot, prefix, active_cells, cell_scale, glacier_cells, glacier_on,
                         par_base, ice_factor, cfmax_low_step, cfmax_high_step):
    states = _snapshot_branch_tuple(snapshot, prefix)
    result = run_cells_from_state_flat(
        PREC_CELLS,
        TEMP_CELLS,
        ET_CELLS,
        LL_TEMP_CELLS,
        par_base,
        ZONE_HIGH_CELLS,
        states[0],
        states[1],
        states[2],
        states[3],
        states[4],
        states[5],
        states[6],
        states[7],
        states[8],
        np.ascontiguousarray(active_cells, dtype=np.bool_),
        np.ascontiguousarray(cell_scale, dtype=np.float64),
        np.ascontiguousarray(glacier_cells, dtype=np.bool_),
        bool(glacier_on),
        float(ice_factor),
        float(cfmax_low_step),
        float(cfmax_high_step),
        GLACIER_DELTA_T_CELLS,
    )
    branch_arrays = _state_branch_arrays(prefix, result[4:])
    return result[0], result[1], result[2], result[3], branch_arrays


def run_forecast_from_state(opt_params, snapshot_path=None, snapshot=None, boundary_series=None):
    if snapshot is None:
        if not snapshot_path:
            raise ValueError("必须提供状态快照文件。")
        snapshot = load_state_snapshot(snapshot_path)
    snapshot = dict(snapshot)
    _validate_snapshot_grid(snapshot)
    if PREC_CELLS is None or TEMP_CELLS is None or ET_CELLS is None:
        raise ValueError("尚未加载未来气象输入。")
    par_base, ice_factor, k_musk, x_musk, cfmax_low_step, cfmax_high_step = _forecast_par_base(opt_params)
    glacier_on = glacier_feature_enabled()
    n_cells = int(PREC_CELLS.shape[0])
    use_fractional_snapshot = "glacier_sp" in snapshot and "nonglacier_sp" in snapshot
    use_fractional_current = bool(
        glacier_on
        and glacier_processing_mode() == "fractional_subgrid"
        and GLACIER_FRACTION_CELLS is not None
    )

    forecast_state_arrays = {
        "valid_cell_rows": np.asarray(VALID_CELLS[:, 0], dtype=np.int32),
        "valid_cell_cols": np.asarray(VALID_CELLS[:, 1], dtype=np.int32),
        "zone_high_cells": np.asarray(ZONE_HIGH_CELLS, dtype=np.uint8),
    }
    if use_fractional_snapshot or use_fractional_current:
        if not (use_fractional_snapshot and use_fractional_current):
            raise ValueError("状态快照冰川子格模式与当前工作区不一致，不能热启动。")
        glacier_active = np.asarray(snapshot.get("glacier_active_cells"), dtype=np.uint8).astype(bool)
        nonglacier_active = np.asarray(snapshot.get("nonglacier_active_cells"), dtype=np.uint8).astype(bool)
        glacier_scale = (CELL_SCALE * GLACIER_FRACTION_CELLS).astype(np.float64, copy=False)
        nonglacier_scale = (CELL_SCALE * (1.0 - GLACIER_FRACTION_CELLS)).astype(np.float64, copy=False)
        nonglacier_glacier_cells = np.zeros(n_cells, dtype=np.bool_)
        q_total_g, q_rain_g, q_snow_g, q_ice_g, glacier_state = _run_forecast_branch(
            snapshot, "glacier_", glacier_active, glacier_scale, glacier_active, True,
            par_base, ice_factor, cfmax_low_step, cfmax_high_step,
        )
        q_total_ng, q_rain_ng, q_snow_ng, q_ice_ng, nonglacier_state = _run_forecast_branch(
            snapshot, "nonglacier_", nonglacier_active, nonglacier_scale, nonglacier_glacier_cells, False,
            par_base, ice_factor, cfmax_low_step, cfmax_high_step,
        )
        q_total = q_total_g + q_total_ng
        q_rain = q_rain_g + q_rain_ng
        q_snow = q_snow_g + q_snow_ng
        q_ice = q_ice_g + q_ice_ng
        q_snow_glacier_raw = q_snow_g
        forecast_state_arrays["glacier_fraction_cells"] = np.asarray(GLACIER_FRACTION_CELLS, dtype=np.float32)
        forecast_state_arrays["glacier_active_cells"] = np.asarray(glacier_active, dtype=np.uint8)
        forecast_state_arrays["nonglacier_active_cells"] = np.asarray(nonglacier_active, dtype=np.uint8)
        forecast_state_arrays.update(glacier_state)
        forecast_state_arrays.update(nonglacier_state)
        branches = ["glacier", "nonglacier"]
    else:
        active_cells = np.ones(n_cells, dtype=np.bool_)
        glacier_cells = (
            np.ascontiguousarray(GLACIER_CELLS, dtype=np.bool_)
            if GLACIER_CELLS is not None
            else np.zeros(n_cells, dtype=np.bool_)
        )
        q_total, q_rain, q_snow, q_ice, main_state = _run_forecast_branch(
            snapshot, "main_", active_cells, CELL_SCALE, glacier_cells, glacier_on,
            par_base, ice_factor, cfmax_low_step, cfmax_high_step,
        )
        q_snow_glacier_raw = np.asarray(q_snow, dtype=np.float64).copy() if glacier_on else np.zeros_like(q_total)
        forecast_state_arrays["glacier_active_cells"] = np.asarray(glacier_cells if glacier_on else np.zeros(n_cells, dtype=np.bool_), dtype=np.uint8)
        forecast_state_arrays.update(main_state)
        branches = ["main"]

    if boundary_series is None:
        if BOUNDARY_INFLOW_ENABLED and BOUNDARY_INFLOW_SERIES is not None:
            boundary_full = np.asarray(BOUNDARY_INFLOW_SERIES, dtype=np.float64)
        else:
            boundary_full = np.zeros_like(q_total)
    else:
        boundary_full = np.asarray(boundary_series, dtype=np.float64)
    if len(boundary_full) != len(q_total):
        raise ValueError(f"边界入流长度与预报时段不一致：期望 {len(q_total)}，实际 {len(boundary_full)}。")

    routing_state = {
        key: _snapshot_scalar(snapshot, key)
        for key in (
            "routing_q_total_in_last",
            "routing_q_total_out_last",
            "routing_q_local_in_last",
            "routing_q_local_out_last",
            "routing_q_boundary_in_last",
            "routing_q_boundary_out_last",
            "routing_q_rain_in_last",
            "routing_q_rain_out_last",
            "routing_q_snow_in_last",
            "routing_q_snow_out_last",
            "routing_q_ice_in_last",
            "routing_q_ice_out_last",
        )
    }
    sim = _route_forecast_series_set(q_total, boundary_full, q_rain, q_snow, q_ice, k_musk, x_musk, routing_state)
    q_glacier_total_raw = np.asarray(q_snow_glacier_raw, dtype=np.float64) + np.asarray(q_ice, dtype=np.float64)
    sim["q_snow_glacier"] = muskingum_route_warm_start(q_snow_glacier_raw, k_musk, x_musk, MUSK_DT)
    sim["q_glacier_total"] = muskingum_route_warm_start(q_glacier_total_raw, k_musk, x_musk, MUSK_DT)
    sim["q_forecast"] = sim["q_total"]
    sim["date"] = pd.DatetimeIndex(SIM_DATES) if SIM_DATES is not None else None
    sim["q_obs"] = Q_OBS_FULL
    sim["forecast_restart"] = {
        "schema": "continuous_state_forecast_v1",
        "status": "ok",
        "source_snapshot": os.fspath(snapshot_path) if snapshot_path else "",
        "snapshot_mode": str(snapshot.get("snapshot_mode", "")),
        "branches": list(branches),
        "cell_count": int(n_cells),
        "time_steps": int(len(q_total)),
        "routing_state_available": bool(np.isfinite(routing_state.get("routing_q_total_out_last", float("nan")))),
    }
    forecast_state_meta = {
        "schema": "per_cell_branch_states_v1",
        "snapshot_mode": "forecast_restart",
        "source_snapshot_mode": str(snapshot.get("snapshot_mode", "")),
        "branch_count": int(len(branches)),
        "branches": list(branches),
        "cell_count": int(n_cells),
        "time_steps": int(len(q_total)),
        "forecast_restart_schema": "continuous_state_forecast_v1",
    }
    append_routing_state_to_snapshot(forecast_state_arrays, sim)
    sim["forecast_state_snapshot_arrays"] = forecast_state_arrays
    sim["forecast_state_snapshot_meta"] = forecast_state_meta
    return sim


def load_glacier_melt_reference_series(start_date, end_date):
    if not os.path.isdir(GLACIER_MELT_DIR):
        return None
    if GLACIER_MASK is None or FLOW_ACC is None or PX_AREA is None:
        return None

    glacier_cells = glacier_reference_active_cells()
    if glacier_cells is None:
        return None
    if not np.any(glacier_cells):
        return None

    file_date_map, signature_entries = scan_time_file_entries(GLACIER_MELT_DIR)
    if not file_date_map:
        return None

    dates = build_time_index(start_date, end_date)
    ensure_expected_time_steps("glacier_ref", dates, file_date_map, GLACIER_MELT_DIR)
    weights = (PX_AREA[glacier_cells] * mm_km2_to_m3s_scale()).astype(np.float64)
    glacier_source_payload = {
        "version": STACK_CACHE_VERSION,
        "label": "glacier_ref",
        "directory": os.path.abspath(GLACIER_MELT_DIR),
        "time_step_hours": float(TIME_STEP_HOURS),
        "weights_len": int(len(weights)),
        "weights_sum": round(float(np.sum(weights)), 12),
        "glacier_cells": int(np.sum(glacier_cells)),
        "glacier_model_mode": glacier_processing_mode(),
        "glacier_mask": file_state_signature(GLACIER_MASK_PATH),
        "glacier_fraction": file_state_signature(GLACIER_FRACTION_PATH),
        "entries": signature_entries,
    }
    glacier_source_token = hashlib.sha1(
        json.dumps(glacier_source_payload, ensure_ascii=False, sort_keys=True).encode("utf-8")
    ).hexdigest()
    cache_payload = {
        "version": STACK_CACHE_VERSION,
        "label": "glacier_ref",
        "source_token": glacier_source_token,
        "start": pd.Timestamp(normalize_time_value(start_date)).isoformat(),
        "end": pd.Timestamp(normalize_time_value(end_date, is_end=True)).isoformat(),
    }
    glacier_token = hashlib.sha1(json.dumps(cache_payload, ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest()
    glacier_cache_path = os.path.join(CACHE_DIR, f"glacier_ref_{glacier_token[:16]}.npy")
    glacier_meta_path = os.path.join(CACHE_DIR, f"glacier_ref_{glacier_token[:16]}.json")
    if os.path.exists(glacier_cache_path) and os.path.exists(glacier_meta_path):
        try:
            series = np.load(glacier_cache_path, allow_pickle=False)
            if tuple(series.shape) != (len(dates),):
                raise ValueError(f"缓存形状不一致：actual={list(series.shape)} expected={[int(len(dates))]}")
            all_nan_steps = np.where(~np.isfinite(series))[0]
            if len(all_nan_steps):
                bad_dates = [dates[int(idx)] for idx in all_nan_steps[:5]]
                raise ValueError(f"缓存存在空白时步：{summarize_time_samples(bad_dates)}")
            record_data_cache(
                "glacier_ref",
                {
                    "cache_hit": True,
                    "cache_hit_type": "exact",
                    "cache_path": glacier_cache_path,
                    "source_dir": GLACIER_MELT_DIR,
                    "time_steps": int(len(dates)),
                    "source_files": int(len(signature_entries)),
                    "shape": [int(series.shape[0])],
                    "source_token": glacier_source_token,
                },
            )
            log_msg(f"[缓存命中] glacier_ref 参考序列 -> {glacier_cache_path}")
            return series
        except Exception as exc:
            log_msg(f"[缓存失效] glacier_ref 读取缓存失败，将重建：{exc}")

    covering_series, covering_path = covering_series_cache(
        "glacier_ref",
        GLACIER_MELT_DIR,
        dates,
        glacier_source_token,
        exclude_meta_path=glacier_meta_path,
    )
    if covering_series is not None:
        record_data_cache(
            "glacier_ref",
            {
                "cache_hit": True,
                "cache_hit_type": "covering_slice",
                "cache_path": covering_path,
                "source_dir": GLACIER_MELT_DIR,
                "time_steps": int(len(dates)),
                "source_files": int(len(signature_entries)),
                "shape": [int(covering_series.shape[0])],
                "source_token": glacier_source_token,
            },
        )
        log_msg(f"[缓存命中] glacier_ref 参考序列 -> {covering_path}（覆盖切片）")
        return covering_series

    first_file = next(iter(file_date_map.values()))
    with rasterio.open(first_file) as src:
        rows, cols = src.height, src.width
        transform = src.transform
        crs = src.crs

    series = np.full(len(dates), np.nan, dtype=np.float64)

    for i, date in enumerate(dates):
        file_path = file_date_map[date]
        with rasterio.open(file_path) as src:
            ensure_raster_alignment("glacier_ref", src, (rows, cols), transform, crs, file_path)
            arr = src.read(1).astype(np.float32)
            nodata = src.nodata
            if nodata is not None:
                arr[arr == nodata] = np.nan
        arr[arr < 0.0] = 0.0
        values = arr[glacier_cells]
        if np.any(np.isfinite(values)):
            series[i] = float(np.nansum(values * weights))

    all_nan_steps = np.where(~np.isfinite(series))[0]
    if len(all_nan_steps):
        bad_dates = [dates[int(idx)] for idx in all_nan_steps[:5]]
        raise ValueError(f"glacier_ref 存在空白时步：{summarize_time_samples(bad_dates)}")

    try:
        tmp_data_path = glacier_cache_path + ".tmp"
        tmp_meta_path = glacier_meta_path + ".tmp"
        with open(tmp_data_path, "wb") as f:
            np.save(f, series, allow_pickle=False)
        with open(tmp_meta_path, "w", encoding="utf-8") as f:
            json.dump(
                {
                    "version": STACK_CACHE_VERSION,
                    "label": "glacier_ref",
                    "directory": os.path.abspath(GLACIER_MELT_DIR),
                    "shape": [int(series.shape[0])],
                    "time_step_hours": float(TIME_STEP_HOURS),
                    "start": pd.Timestamp(normalize_time_value(start_date)).isoformat(),
                    "end": pd.Timestamp(normalize_time_value(end_date, is_end=True)).isoformat(),
                    "token": glacier_token,
                    "source_token": glacier_source_token,
                    "source_files": int(len(signature_entries)),
                    "built_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                },
                f,
                ensure_ascii=False,
                indent=2,
            )
        os.replace(tmp_data_path, glacier_cache_path)
        os.replace(tmp_meta_path, glacier_meta_path)
        log_msg(f"[缓存写入] glacier_ref 参考序列 -> {glacier_cache_path}")
    except Exception as exc:
        log_msg(f"[缓存跳过] glacier_ref 参考序列写入失败：{exc}")

    record_data_cache(
        "glacier_ref",
        {
            "cache_hit": False,
            "cache_hit_type": "rebuilt",
            "cache_path": glacier_cache_path,
            "source_dir": GLACIER_MELT_DIR,
            "time_steps": int(len(dates)),
            "source_files": int(len(signature_entries)),
            "shape": [int(series.shape[0])],
            "source_token": glacier_source_token,
        },
    )
    return series


def load_glacier_melt_reference_series_for_dates(dates):
    dates = pd.DatetimeIndex(dates)
    if not os.path.isdir(GLACIER_MELT_DIR):
        return None
    if GLACIER_MASK is None or FLOW_ACC is None or PX_AREA is None:
        return None

    glacier_cells = glacier_reference_active_cells()
    if glacier_cells is None or not np.any(glacier_cells):
        return None

    file_date_map, signature_entries = scan_time_file_entries(GLACIER_MELT_DIR)
    if not file_date_map:
        return None

    ensure_expected_time_steps("glacier_ref", dates, file_date_map, GLACIER_MELT_DIR)
    first_file = next(iter(file_date_map.values()))
    with rasterio.open(first_file) as src:
        rows, cols = src.height, src.width
        transform = src.transform
        crs = src.crs

    weights = (PX_AREA[glacier_cells] * mm_km2_to_m3s_scale()).astype(np.float64)
    series = np.full(len(dates), np.nan, dtype=np.float64)
    for i, date in enumerate(dates):
        file_path = file_date_map[pd.Timestamp(date)]
        with rasterio.open(file_path) as src:
            ensure_raster_alignment("glacier_ref", src, (rows, cols), transform, crs, file_path)
            arr = src.read(1).astype(np.float32)
            nodata = src.nodata
            if nodata is not None:
                arr[arr == nodata] = np.nan
        arr[arr < 0.0] = 0.0
        values = arr[glacier_cells]
        if np.any(np.isfinite(values)):
            series[i] = float(np.nansum(values * weights))

    if np.any(~np.isfinite(series)):
        bad_dates = [dates[int(idx)] for idx in np.where(~np.isfinite(series))[0][:5]]
        raise ValueError(f"glacier_ref 存在空白时步：{summarize_time_samples(bad_dates)}")

    source_payload = {
        "version": STACK_CACHE_VERSION,
        "label": "glacier_ref",
        "directory": os.path.abspath(GLACIER_MELT_DIR),
        "time_step_hours": float(TIME_STEP_HOURS),
        "entries": signature_entries,
    }
    source_token = hashlib.sha1(
        json.dumps(source_payload, ensure_ascii=False, sort_keys=True).encode("utf-8")
    ).hexdigest()
    record_data_cache(
        "glacier_ref",
        {
            "cache_hit": False,
            "cache_hit_type": "event_window_direct",
            "cache_path": "",
            "source_dir": GLACIER_MELT_DIR,
            "time_steps": int(len(dates)),
            "source_files": int(len(signature_entries)),
            "shape": [int(series.shape[0])],
            "source_token": source_token,
            "event_window_runtime": True,
        },
    )
    return series


def detect_obs_eval_mask():
    mode = str(OBS_MODE_OVERRIDE or "").strip().lower() or "full_year"
    if SIM_DATES is None:
        return np.ones(0, dtype=bool), mode
    default_mask = np.ones(len(SIM_DATES), dtype=bool)
    if mode in {"all", "all_valid", "full_period", "available_only"}:
        return default_mask, mode
    if mode != "full_year":
        return default_mask, mode

    sim_index = pd.DatetimeIndex(SIM_DATES)
    if sim_index.empty:
        return default_mask, mode

    keep = np.zeros(len(sim_index), dtype=bool)
    for year in sorted(set(sim_index.year)):
        year_start = pd.Timestamp(year=year, month=1, day=1)
        year_end = pd.Timestamp(year=year, month=12, day=31)
        if TIME_STEP_HOURS < 24.0:
            year_end = year_end + pd.Timedelta(days=1) - time_step_timedelta()
        expected = pd.date_range(year_start, year_end, freq=time_step_timedelta())
        if expected.empty:
            continue
        year_mask = sim_index.year == year
        if int(np.sum(year_mask)) != len(expected):
            continue
        year_slice = sim_index[year_mask]
        if year_slice[0] == expected[0] and year_slice[-1] == expected[-1]:
            if (
                Q_OBS_FULL is not None
                and len(Q_OBS_FULL) == len(sim_index)
                and not np.all(np.isfinite(Q_OBS_FULL[year_mask]))
            ):
                continue
            keep[year_mask] = True

    if np.any(keep) and Q_OBS_FULL is not None and len(Q_OBS_FULL) == len(sim_index):
        def _segment_lost_valid_obs(segment_mask):
            if segment_mask is None or len(segment_mask) != len(sim_index):
                return False
            segment_mask = np.asarray(segment_mask, dtype=bool)
            if not np.any(segment_mask):
                return False
            before = np.isfinite(Q_OBS_FULL[segment_mask])
            if not np.any(before):
                return False
            after = np.isfinite(Q_OBS_FULL[segment_mask & keep])
            return not np.any(after)

        if _segment_lost_valid_obs(CALIB_MASK) or _segment_lost_valid_obs(VALID_MASK):
            return default_mask, "all_valid"

    if np.any(keep):
        return keep, mode
    return default_mask, "all_valid"


def _event_config_field(event, *names):
    event = dict(event or {}) if isinstance(event, dict) else {}
    for name in names:
        if name in event and event.get(name) not in (None, ""):
            return event.get(name)
    lower_map = {str(key).strip().lower(): value for key, value in event.items()}
    for name in names:
        value = lower_map.get(str(name).strip().lower())
        if value not in (None, ""):
            return value
    return None


def _event_purpose_key(event):
    raw = str(
        _event_config_field(event, "purpose", "用途", "类型", "type")
        or "calibration"
    ).strip().lower()
    if raw in {"calibration", "calib", "train", "training", "率定", "训练"}:
        return "calibration"
    if raw in {"validation", "valid", "test", "验证", "检验"}:
        return "validation"
    if raw in {"diagnostic", "diag", "诊断"}:
        return "diagnostic"
    return raw or "calibration"


def event_runtime_requested(config=None):
    raw = FLOOD_EVENT_CONFIG if config is None else config
    if isinstance(raw, list):
        return False
    if not isinstance(raw, dict):
        return False
    if _config_bool(raw.get("事件窗口资料", raw.get("event_windows_enabled")), default=False):
        return True
    mode = str(raw.get("event_runtime_mode", raw.get("运行资料模式", raw.get("资料模式", ""))) or "").strip().lower()
    return mode in {"event_windows", "independent_event_windows", "event_segments", "事件窗口", "事件资料"}


def _event_runtime_time(value, *, end=False):
    if value in (None, ""):
        return None
    return normalize_time_value(value, is_end=end)


def _event_runtime_date_range(start, end):
    return build_time_index(start, end)


def _as_message_list(value):
    if value in (None, ""):
        return []
    if isinstance(value, (list, tuple, set)):
        return [str(item) for item in value if str(item)]
    return [str(value)]


def build_event_runtime_context(config=None):
    parsed = parse_flood_event_config(config)
    raw_config = dict(parsed.get("raw_config", {}) or {})
    if not event_runtime_requested(raw_config):
        return {"enabled": False, "dates": None, "windows": [], "warnings": [], "errors": []}

    raw_events = list(parsed.get("events", []) or [])
    objective_indices = selected_flood_event_indices_for_objective(raw_events, raw_config)
    dates_parts = []
    calib_parts = []
    valid_parts = []
    windows = []
    warnings = _as_message_list(parsed.get("warnings", [])) + _as_message_list(raw_config.get("warnings", []))
    errors = _as_message_list(raw_config.get("errors", []))
    for idx, raw_event in enumerate(raw_events):
        event = dict(raw_event or {}) if isinstance(raw_event, dict) else {}
        token = json.dumps(event, ensure_ascii=False, sort_keys=True, default=str).encode("utf-8")
        event_id = str(_event_config_field(event, "event_id", "id", "编号", "name", "名称") or "").strip()
        if not event_id:
            event_id = f"event_{hashlib.sha1(token).hexdigest()[:8]}"
        try:
            score_start = _event_runtime_time(
                _event_config_field(event, "score_start", "评分开始", "事件开始", "start"),
                end=False,
            )
            score_end = _event_runtime_time(
                _event_config_field(event, "score_end", "评分结束", "事件结束", "end"),
                end=True,
            )
            run_start = _event_runtime_time(
                _event_config_field(event, "run_start", "运行开始", "预热开始", "warmup_start")
                or score_start,
                end=False,
            )
            run_end = _event_runtime_time(
                _event_config_field(event, "run_end", "运行结束", "退水结束")
                or score_end,
                end=True,
            )
        except Exception as exc:
            errors.append(f"{event_id}: 事件时间无法解析：{exc}")
            continue
        if None in (run_start, score_start, score_end, run_end):
            errors.append(f"{event_id}: 事件缺少运行窗口或评分窗口时间。")
            continue
        if not (run_start <= score_start <= score_end <= run_end):
            errors.append(f"{event_id}: 事件时间顺序必须满足 run_start <= score_start <= score_end <= run_end。")
            continue

        event_dates = _event_runtime_date_range(run_start, run_end)
        if len(event_dates) == 0:
            errors.append(f"{event_id}: 事件运行窗口没有有效时间步。")
            continue
        start_idx = sum(len(part) for part in dates_parts)
        end_idx = start_idx + len(event_dates) - 1
        score_mask = (event_dates >= score_start) & (event_dates <= score_end)
        purpose = _event_purpose_key(event)
        in_objective = bool(idx in objective_indices)
        dates_parts.append(event_dates)
        calib_parts.append(np.asarray(score_mask & in_objective, dtype=bool))
        valid_parts.append(np.asarray(score_mask & (purpose == "validation"), dtype=bool))
        windows.append(
            {
                "index": int(idx),
                "event_id": event_id,
                "name": str(_event_config_field(event, "name", "名称") or event_id),
                "purpose": purpose,
                "used_in_objective": in_objective,
                "start_idx": int(start_idx),
                "end_idx": int(end_idx),
                "time_steps_run": int(len(event_dates)),
                "time_steps_score": int(np.sum(score_mask)),
                "run_start": format_time_value(run_start),
                "score_start": format_time_value(score_start),
                "score_end": format_time_value(score_end),
                "run_end": format_time_value(run_end),
            }
        )

    if errors:
        return {"enabled": True, "dates": None, "windows": windows, "warnings": warnings, "errors": errors}
    if not dates_parts:
        return {
            "enabled": True,
            "dates": None,
            "windows": [],
            "warnings": warnings,
            "errors": ["事件窗口资料模式已启用，但事件表中没有可运行事件。"],
        }

    runtime_dates = pd.DatetimeIndex(np.concatenate([part.to_numpy() for part in dates_parts]))
    calib_mask = np.concatenate(calib_parts).astype(bool)
    valid_mask = np.concatenate(valid_parts).astype(bool)
    if not np.any(calib_mask):
        warnings.append("事件目标窗口为空，已把全部事件评分窗口作为率定目标窗口。")
        calib_mask = np.concatenate([
            np.asarray((part >= pd.Timestamp(win["score_start"])) & (part <= pd.Timestamp(win["score_end"])), dtype=bool)
            for part, win in zip(dates_parts, windows)
        ]).astype(bool)
        for win in windows:
            win["used_in_objective"] = True

    return {
        "enabled": True,
        "dates": runtime_dates,
        "calib_mask": calib_mask,
        "valid_mask": valid_mask,
        "windows": windows,
        "warnings": warnings,
        "errors": [],
        "initial_state_policy": str(raw_config.get("初始条件策略", raw_config.get("event_initial_state_policy", "event_warmup")) or "event_warmup"),
        "runtime_mode": str(raw_config.get("event_runtime_mode", "independent_event_windows") or "independent_event_windows"),
        "event_count": int(len(windows)),
        "objective_event_count": int(sum(1 for item in windows if item.get("used_in_objective"))),
        "validation_event_count": int(sum(1 for item in windows if item.get("purpose") == "validation")),
    }


def load_observed_discharge_series(csv_path, target_index):
    info = inspect_observed_discharge(
        csv_path,
        expected_index=pd.DatetimeIndex(target_index),
        target_step_hours=TIME_STEP_HOURS,
        allow_hourly_to_daily=True,
        min_daily_hours=DEFAULT_MIN_DAILY_HOURS,
        return_series=True,
    )
    duplicate_count = int(info.get("duplicate_count", 0) or 0)
    if duplicate_count > 0:
        log_msg(f"[WARN] 观测径流存在 {duplicate_count} 个重复时间戳，运行时将按同一时刻求平均。")
    if bool(info.get("resampled_to_daily")):
        aggregation = dict(info.get("daily_aggregation") or {})
        log_msg(
            "[INFO] 观测径流已从小时尺度按自然日聚合为日平均流量："
            f"有效日数={int(aggregation.get('valid_days', 0) or 0)} "
            f"覆盖不足日数={int(aggregation.get('insufficient_days', 0) or 0)} "
            f"阈值={int(aggregation.get('min_hours_per_day', DEFAULT_MIN_DAILY_HOURS) or DEFAULT_MIN_DAILY_HOURS)}h"
        )

    grouped = info["series"].astype(np.float64)
    target_datetime_index = pd.DatetimeIndex(target_index)
    aligned = grouped.reindex(target_datetime_index)
    series = aligned.values.astype(np.float64)
    matched_steps = int(np.isfinite(series).sum())
    if matched_steps == 0:
        raise ValueError("观测径流在当前模拟时段内没有任何可对齐的有效记录。")
    return series, {
        "date_field": str(info.get("date_field", "")),
        "flow_field": str(info.get("flow_field", "")),
        "duplicate_count": duplicate_count,
        "valid_rows": int(info.get("valid_rows", 0) or 0),
        "matched_steps": matched_steps,
        "coverage_ratio": float(info.get("coverage_ratio", 0.0) or 0.0),
        "time_step_hours": float(info.get("effective_time_step_hours", normalized_time_step_hours(TIME_STEP_HOURS))),
        "source_time_step_hours": float(info.get("suggested_time_step_hours", normalized_time_step_hours(TIME_STEP_HOURS))),
        "resampled_to_daily": bool(info.get("resampled_to_daily", False)),
    }


def load_all_data(end_date_override=None, skip_obs=False):
    global PREC_3D, TEMP_3D, ET_3D, LL_TEMP_3D, PREC_CELLS, TEMP_CELLS, ET_CELLS, LL_TEMP_CELLS, FLOW_ACC, PX_AREA
    global VALID_CELLS, GLACIER_MASK, GLACIER_FRACTION, GLACIER_DELTA_T, ZONE_LOW, ZONE_HIGH, GLACIER_CELLS, GLACIER_FRACTION_CELLS, GLACIER_DELTA_T_CELLS, ZONE_HIGH_CELLS, CELL_SCALE
    global SIM_DATES, CALIB_MASK, VALID_MASK, Q_OBS_FULL, Q_OBS_OBJ, Q_OBS_CALIB, Q_OBS_VALID
    global WARMUP_STEPS, CATCHMENT_AREA, BOUNDARY_INFLOW_SERIES, BOUNDARY_INFLOW_ENABLED, GLACIER_MELT_REF_RAW, GLACIER_MODEL_MODE, GLACIER_ELEV_STATUS, RELIABILITY_FLAG, DATA_LOAD_SUMMARY, OBS_MODE_APPLIED
    global OBS_MONTHLY_CALIB, GLACIER_FRAC_WINDOW, BASIN_GLACIER_AREA_FRACTION
    global EVENT_RUNTIME_ENABLED, EVENT_RUNTIME_MODE, EVENT_RUNTIME_DATES, EVENT_RUNTIME_WINDOWS, EVENT_RUNTIME_META, EVENT_INITIAL_STATE_POLICY

    load_end = end_date_override or SIM_END
    DATA_LOAD_SUMMARY = {}
    load_started = time.time()

    event_context = build_event_runtime_context()
    EVENT_RUNTIME_ENABLED = bool(event_context.get("enabled") and event_context.get("dates") is not None)
    if event_context.get("errors"):
        raise ValueError("洪水事件窗口资料模式无法启动：" + "；".join(str(item) for item in event_context["errors"][:5]))
    if EVENT_RUNTIME_ENABLED:
        runtime_dates = pd.DatetimeIndex(event_context["dates"])
        EVENT_RUNTIME_DATES = runtime_dates
        EVENT_RUNTIME_WINDOWS = list(event_context.get("windows", []) or [])
        EVENT_RUNTIME_MODE = str(event_context.get("runtime_mode") or "independent_event_windows")
        EVENT_INITIAL_STATE_POLICY = str(event_context.get("initial_state_policy") or "event_warmup")
        EVENT_RUNTIME_META = {
            "enabled": True,
            "runtime_mode": EVENT_RUNTIME_MODE,
            "initial_state_policy": EVENT_INITIAL_STATE_POLICY,
            "event_count": int(event_context.get("event_count", len(EVENT_RUNTIME_WINDOWS)) or 0),
            "objective_event_count": int(event_context.get("objective_event_count", 0) or 0),
            "validation_event_count": int(event_context.get("validation_event_count", 0) or 0),
            "time_steps": int(len(runtime_dates)),
            "allows_gaps_between_events": True,
            "state_continuity_between_events": False,
            "windows": EVENT_RUNTIME_WINDOWS,
            "warnings": list(event_context.get("warnings", []) or []),
        }
        if event_context.get("warnings"):
            for warning in event_context.get("warnings", [])[:5]:
                log_msg(f"[事件资料] {warning}")
        log_msg(
            f"[事件资料] 启用事件窗口资料模式：{len(EVENT_RUNTIME_WINDOWS)} 场，"
            f"读取 {len(runtime_dates)} 个事件内时步；事件之间不作为连续状态演化。"
        )
    else:
        runtime_dates = build_time_index(WARMUP_START, load_end)
        EVENT_RUNTIME_DATES = None
        EVENT_RUNTIME_WINDOWS = []
        EVENT_RUNTIME_MODE = "continuous"
        EVENT_INITIAL_STATE_POLICY = "continuous_state"
        EVENT_RUNTIME_META = {"enabled": False, "runtime_mode": "continuous"}

    PREC_3D, transform, forcing_crs = load_raster_stack_for_dates(PREC_DIR, runtime_dates, cache_label="prec")
    rows, cols, ts = PREC_3D.shape
    TEMP_3D, temp_transform, temp_crs = load_raster_stack_for_dates(TEMP_DIR, runtime_dates, cache_label="temp")
    ensure_loaded_stack_alignment("temp", TEMP_3D.shape, temp_transform, temp_crs, PREC_3D.shape, transform, forcing_crs)
    ET_3D, et_transform, et_crs = load_raster_stack_for_dates(EVAP_DIR, runtime_dates, cache_label="evap")
    ensure_loaded_stack_alignment("evap", ET_3D.shape, et_transform, et_crs, PREC_3D.shape, transform, forcing_crs)

    temp_valid = np.isfinite(TEMP_3D)
    temp_valid_count = temp_valid.sum(axis=2, keepdims=True)
    temp_sum = np.where(temp_valid, TEMP_3D, 0.0).sum(axis=2, keepdims=True, dtype=np.float64)
    global_valid_count = int(temp_valid.sum())
    global_temp_mean = float(temp_sum.sum() / global_valid_count) if global_valid_count > 0 else 0.0
    temp_fill_base = np.full((rows, cols, 1), global_temp_mean, dtype=np.float64)
    np.divide(temp_sum, temp_valid_count, out=temp_fill_base, where=temp_valid_count > 0)
    LL_TEMP_3D = np.broadcast_to(temp_fill_base.astype(np.float32), TEMP_3D.shape)

    if args.fill_nan:
        PREC_3D = np.nan_to_num(PREC_3D, nan=0.0)
        ET_3D = np.nan_to_num(ET_3D, nan=0.0)
        TEMP_3D = np.where(np.isnan(TEMP_3D), LL_TEMP_3D, TEMP_3D)

    with rasterio.open(FLOW_ACC_PATH) as src:
        ensure_raster_alignment("flow_acc", src, (rows, cols), transform, forcing_crs, FLOW_ACC_PATH)
        FLOW_ACC = src.read(1).astype(np.float32)
        nodata = src.nodata
        if nodata is not None:
            FLOW_ACC[FLOW_ACC == nodata] = np.nan

    valid_mask = ~np.isnan(FLOW_ACC)
    VALID_CELLS = np.argwhere(valid_mask).astype(np.int64)

    _basin_shp_path = os.path.join(GIS_ROOT, "basin.shp")
    if os.path.exists(_basin_shp_path):
        try:
            import geopandas as _gpd
            from rasterio.features import rasterize as _rasterize
            _basin_gdf = _gpd.read_file(_basin_shp_path)
            if _basin_gdf.crs is not None and _basin_gdf.crs != forcing_crs:
                _basin_gdf = _basin_gdf.to_crs(forcing_crs)
            _basin_shapes = [(g, 1) for g in _basin_gdf.geometry if g is not None and not g.is_empty]
            if _basin_shapes:
                _basin_rast = _rasterize(
                    _basin_shapes,
                    out_shape=(rows, cols),
                    transform=transform,
                    fill=0,
                    dtype="uint8",
                )
                _basin_from_shp = _basin_rast == 1
                _basin_from_flow = valid_mask
                _only_in_flow = int(np.sum(_basin_from_flow & ~_basin_from_shp))
                _only_in_shp = int(np.sum(_basin_from_shp & ~_basin_from_flow))
                _total_flow = int(np.sum(_basin_from_flow))
                _diff_ratio = (max(_only_in_flow, _only_in_shp) / _total_flow) if _total_flow > 0 else 0.0
                if _diff_ratio > 0.05:
                    log_msg(
                        f"[WARN] basin.shp 与 flow_accumulation 差异占比 {_diff_ratio * 100:.1f}%："
                        f"仅在 flow_acc 中 {_only_in_flow} 像元，仅在 basin.shp 中 {_only_in_shp} 像元。"
                        "差异较大，建议复核流域边界与 DEM 水文处理口径一致性。"
                    )
                elif _only_in_flow + _only_in_shp > 0:
                    log_msg(
                        f"[INFO] basin.shp 与 flow_accumulation 存在 {_only_in_flow + _only_in_shp} 像元的边界级差异"
                        f"（占比 {_diff_ratio * 100:.2f}%），通常源于 rasterize 边界规则与 nodata 处理差异，不影响运行。"
                    )
        except Exception as _e:
            log_msg(f"[WARN] basin.shp 一致性检查失败（已跳过）：{_e}")

    dem_path = str(resolve_workspace_dem_path(os.path.dirname(FLOW_ACC_PATH)))
    with rasterio.open(dem_path) as src:
        ensure_raster_alignment("dem", src, (rows, cols), transform, forcing_crs, dem_path)
        dem = src.read(1).astype(np.float32)
    valid_dem = np.isfinite(dem) & (dem > 0) & valid_mask
    ZONE_LOW = (dem < CFMAX_ZONE_ELEV) & valid_dem
    ZONE_HIGH = (dem >= CFMAX_ZONE_ELEV) & valid_dem

    PX_AREA = np.zeros((rows, cols), dtype=np.float64)
    row_areas = compute_row_areas_km2(transform, rows)
    for i in range(rows):
        PX_AREA[i, :] = row_areas[i]
    CATCHMENT_AREA = float(np.sum(PX_AREA[valid_mask]))
    CELL_SCALE = (PX_AREA[VALID_CELLS[:, 0], VALID_CELLS[:, 1]] * mm_km2_to_m3s_scale()).astype(np.float64)

    dem_kind = infer_dem_kind_from_raster(dem_path)
    GLACIER_MODEL_MODE = "binary_legacy" if dem_kind == "1km" else "fractional_subgrid"

    GLACIER_FRACTION = None
    if glacier_processing_mode() == "fractional_subgrid" and os.path.exists(GLACIER_FRACTION_PATH):
        with rasterio.open(GLACIER_FRACTION_PATH) as src:
            ensure_raster_alignment("glacier_fraction", src, (rows, cols), transform, forcing_crs, GLACIER_FRACTION_PATH)
            raw_fraction = src.read(1).astype(np.float32)
            nodata = src.nodata
            if nodata is not None:
                raw_fraction = np.where(raw_fraction == nodata, 0.0, raw_fraction)
        GLACIER_FRACTION = np.clip(raw_fraction, 0.0, 1.0)

    if os.path.exists(GLACIER_MASK_PATH):
        with rasterio.open(GLACIER_MASK_PATH) as src:
            ensure_raster_alignment("glacier_mask", src, (rows, cols), transform, forcing_crs, GLACIER_MASK_PATH)
            raw = src.read(1)
            nodata = src.nodata
            if nodata is not None:
                raw = np.where(raw == nodata, 0, raw)
        GLACIER_MASK = raw.astype(bool)
    else:
        GLACIER_MASK = np.zeros((rows, cols), dtype=bool)

    if glacier_processing_mode() == "fractional_subgrid":
        if GLACIER_FRACTION is None:
            GLACIER_FRACTION = GLACIER_MASK.astype(np.float32)
            log_msg("[WARN] 未找到 glacier_fraction.tif，已临时退回为 0/1 冰川覆盖率。")
        GLACIER_MASK = GLACIER_FRACTION > 0.0
    else:
        GLACIER_FRACTION = GLACIER_MASK.astype(np.float32)

    GLACIER_DELTA_T = np.zeros((rows, cols), dtype=np.float32)
    GLACIER_ELEV_STATUS = "unknown"
    RELIABILITY_FLAG = "ok"
    glacier_mode_now = glacier_processing_mode()
    glacier_enabled_now = bool(
        (glacier_mode_now == "fractional_subgrid" and np.any(GLACIER_FRACTION > 0.0))
        or (glacier_mode_now == "binary_legacy" and np.any(GLACIER_MASK))
    )
    if glacier_mode_now == "binary_legacy":
        GLACIER_ELEV_STATUS = "not_needed_1km"
    elif os.path.exists(GLACIER_ELEV_PATH):
        with rasterio.open(GLACIER_ELEV_PATH) as src:
            ensure_raster_alignment("glacier_elev", src, (rows, cols), transform, forcing_crs, GLACIER_ELEV_PATH)
            raw_elev = src.read(1).astype(np.float32)
            elev_nodata = src.nodata
            if elev_nodata is not None:
                raw_elev = np.where(raw_elev == elev_nodata, np.nan, raw_elev)
        valid_elev_mask = np.isfinite(raw_elev) & (GLACIER_FRACTION > 0.0) & np.isfinite(dem)
        if np.any(valid_elev_mask):
            delta_t = np.zeros((rows, cols), dtype=np.float32)
            delta_t[valid_elev_mask] = -(raw_elev[valid_elev_mask] - dem[valid_elev_mask]) * GLACIER_LAPSE_RATE_PER_M
            GLACIER_DELTA_T = delta_t
            GLACIER_ELEV_STATUS = "ok"
            covered = int(np.sum(valid_elev_mask))
            expected = int(np.sum(GLACIER_FRACTION > 0.0))
            log_msg(
                f"[冰川高程] 已启用冰川子格温度递减，覆盖 {covered}/{expected} 冰川像元，"
                f"Δt 范围 [{float(np.nanmin(delta_t[valid_elev_mask])):.2f}, "
                f"{float(np.nanmax(delta_t[valid_elev_mask])):.2f}] °C"
            )
            if covered < expected:
                log_msg(
                    f"[WARN] 有 {expected - covered} 个冰川像元缺少高程数据，已按 Δt=0 处理；"
                    "若占比高建议重跑 11_生成冰川高程栅格.py。"
                )
        else:
            GLACIER_ELEV_STATUS = "missing"
            if glacier_enabled_now:
                RELIABILITY_FLAG = "degraded_missing_glacier_elev"
                log_msg(
                    "[ERROR] glacier_elev.tif 存在但无有效高程值，0.1° 冰川子格温度递减未启用。"
                    "冰川融水可能系统性偏高 15–30%，结果已标记为 degraded。"
                )
    else:
        GLACIER_ELEV_STATUS = "missing"
        if glacier_enabled_now:
            RELIABILITY_FLAG = "degraded_missing_glacier_elev"
            log_msg(
                "[ERROR] 未找到 glacier_elev.tif，0.1° 冰川子格温度递减未启用。"
                "冰川融水可能系统性偏高 15–30%，结果已标记为 degraded。"
                "请运行数据准备步骤 11.5 或设置 HBV_HIGH_RES_DEM 环境变量后重跑。"
            )
        else:
            log_msg("[INFO] 0.1° 方案未找到 glacier_elev.tif，但冰川模块未启用，无影响。")

    PREC_CELLS = np.ascontiguousarray(PREC_3D[valid_mask, :], dtype=np.float32)
    TEMP_CELLS = np.ascontiguousarray(TEMP_3D[valid_mask, :], dtype=np.float32)
    ET_CELLS = np.ascontiguousarray(ET_3D[valid_mask, :], dtype=np.float32)
    LL_TEMP_CELLS = np.ascontiguousarray(LL_TEMP_3D[valid_mask, :], dtype=np.float32)
    GLACIER_CELLS = np.ascontiguousarray(GLACIER_MASK[valid_mask], dtype=np.bool_)
    GLACIER_FRACTION_CELLS = np.ascontiguousarray(GLACIER_FRACTION[valid_mask], dtype=np.float32)
    GLACIER_DELTA_T_CELLS = np.ascontiguousarray(GLACIER_DELTA_T[valid_mask], dtype=np.float32)
    ZONE_HIGH_CELLS = np.ascontiguousarray(ZONE_HIGH[valid_mask], dtype=np.bool_)

    PREC_3D = None
    TEMP_3D = None
    ET_3D = None
    LL_TEMP_3D = None

    full_run_dates = pd.DatetimeIndex(runtime_dates)
    SIM_DATES = full_run_dates
    if EVENT_RUNTIME_ENABLED:
        CALIB_MASK = np.asarray(event_context.get("calib_mask"), dtype=bool)
        VALID_MASK = np.asarray(event_context.get("valid_mask"), dtype=bool)
        WARMUP_STEPS = 0
    else:
        calib_start_ts = normalize_time_value(CALIB_START)
        calib_end_ts = normalize_time_value(CALIB_END, is_end=True)
        valid_start_ts = normalize_time_value(VALID_START)
        valid_end_ts = normalize_time_value(VALID_END, is_end=True)
        CALIB_MASK = (SIM_DATES >= calib_start_ts) & (SIM_DATES <= calib_end_ts)
        VALID_MASK = (SIM_DATES >= valid_start_ts) & (SIM_DATES <= valid_end_ts)
        WARMUP_STEPS = compute_warmup_steps()

    if skip_obs or (not os.path.exists(OBS_FILE)):
        Q_OBS_FULL = np.full(len(SIM_DATES), np.nan, dtype=np.float64)
        Q_OBS_OBJ = Q_OBS_FULL.copy()
        OBS_MODE_APPLIED = "no_obs"
    else:
        Q_OBS_FULL, obs_info = load_observed_discharge_series(OBS_FILE, SIM_DATES)
        obs_mask, OBS_MODE_APPLIED = detect_obs_eval_mask()
        Q_OBS_OBJ = Q_OBS_FULL.copy()
        Q_OBS_OBJ[~obs_mask] = np.nan
        log_msg(
            f"[观测] 时间列={obs_info['date_field']} 流量列={obs_info['flow_field']} "
            f"有效记录={obs_info['valid_rows']} 口径模式={OBS_MODE_APPLIED}"
        )
        coverage_ratio = float(obs_info.get("coverage_ratio", 1.0) or 0.0)
        matched_steps = int(obs_info.get("matched_steps", 0) or 0)
        if coverage_ratio < 0.99:
            log_msg(
                f"[WARN] 观测径流与当前模拟时段仅对齐 {coverage_ratio * 100:.1f}% 时间步"
                f"（{matched_steps}/{len(SIM_DATES)}）。"
            )
        if str(OBS_MODE_OVERRIDE or "").strip().lower() == "full_year" and OBS_MODE_APPLIED != "full_year":
            log_msg(
                f"[WARN] 观测口径已从 full_year 回退为 {OBS_MODE_APPLIED}，"
                "原因可能是观测并非整年连续覆盖，或当前短窗/时段裁剪会把有效观测全部排除。"
            )

    Q_OBS_CALIB = Q_OBS_OBJ[CALIB_MASK]
    Q_OBS_VALID = Q_OBS_OBJ[VALID_MASK]
    if (not skip_obs) and os.path.exists(OBS_FILE) and (not np.any(np.isfinite(Q_OBS_CALIB))):
        raise ValueError("率定期内没有有效观测径流，无法计算目标函数。")
    BOUNDARY_INFLOW_SERIES, _ = read_boundary_inflow_series(
        BOUNDARY_INFLOW_FILE,
        full_run_dates,
        date_field=BOUNDARY_INFLOW_DATE_FIELD,
        flow_field=BOUNDARY_INFLOW_FLOW_FIELD,
        gap_fill=BOUNDARY_INFLOW_GAP_FILL,
        expected_step_hours=TIME_STEP_HOURS,
    )
    BOUNDARY_INFLOW_ENABLED = bool(BOUNDARY_INFLOW_FILE)
    if EVENT_RUNTIME_ENABLED:
        GLACIER_MELT_REF_RAW = load_glacier_melt_reference_series_for_dates(full_run_dates)
    else:
        GLACIER_MELT_REF_RAW = load_glacier_melt_reference_series(WARMUP_START, load_end)

    try:
        if Q_OBS_CALIB is not None and SIM_DATES is not None and CALIB_MASK is not None:
            calib_dates_idx = pd.DatetimeIndex(SIM_DATES)[CALIB_MASK]
            OBS_MONTHLY_CALIB = _series_to_monthly_sums(Q_OBS_CALIB, calib_dates_idx)
        else:
            OBS_MONTHLY_CALIB = None
    except Exception as _exc:
        log_msg(f"[WARN] 观测流量月度聚合失败（将禁用出口 signatures）：{_exc}")
        OBS_MONTHLY_CALIB = None

    BASIN_GLACIER_AREA_FRACTION = float("nan")
    GLACIER_FRAC_WINDOW = None
    try:
        if PX_AREA is not None and VALID_CELLS is not None and VALID_CELLS.size > 0:
            basin_area_total = float(np.nansum(PX_AREA[VALID_CELLS[:, 0], VALID_CELLS[:, 1]]))
            glacier_area = 0.0
            if GLACIER_FRACTION is not None:
                frac_at_cells = GLACIER_FRACTION[VALID_CELLS[:, 0], VALID_CELLS[:, 1]]
                px_at_cells = PX_AREA[VALID_CELLS[:, 0], VALID_CELLS[:, 1]]
                glacier_area = float(np.nansum(frac_at_cells * px_at_cells))
            elif GLACIER_MASK is not None:
                mask_at_cells = GLACIER_MASK[VALID_CELLS[:, 0], VALID_CELLS[:, 1]]
                px_at_cells = PX_AREA[VALID_CELLS[:, 0], VALID_CELLS[:, 1]]
                glacier_area = float(np.nansum(mask_at_cells * px_at_cells))
            if basin_area_total > 0.0 and glacier_area > 0.0:
                BASIN_GLACIER_AREA_FRACTION = float(glacier_area / basin_area_total)
                GLACIER_FRAC_WINDOW = infer_glacier_fraction_window(BASIN_GLACIER_AREA_FRACTION)
                if GLACIER_FRAC_WINDOW is not None:
                    log_msg(
                        f"[冰川占比] 流域冰川覆盖率={BASIN_GLACIER_AREA_FRACTION * 100:.2f}%"
                        f"，径流占比软区间=[{GLACIER_FRAC_WINDOW[0] * 100:.1f}%, {GLACIER_FRAC_WINDOW[1] * 100:.1f}%]"
                    )
                else:
                    log_msg(f"[INFO] 冰川占比区间未推导（f_area={BASIN_GLACIER_AREA_FRACTION:.4f}）。")
            else:
                log_msg("[INFO] 流域内未检测到冰川面积，冰川占比约束默认关闭。")
    except Exception as _exc:
        log_msg(f"[WARN] 冰川占比区间推导失败（将不启用占比约束）：{_exc}")
        GLACIER_FRAC_WINDOW = None

    load_elapsed = time.time() - load_started
    cache_hits = sum(1 for item in DATA_LOAD_SUMMARY.values() if item.get("cache_hit"))
    print(f"数据加载完成，用时 {load_elapsed:.2f} s（栅格缓存命中 {cache_hits}/{len(DATA_LOAD_SUMMARY)}）")

def run_simulation(opt_params, mode="full"):
    opt_params = validate_parameter_vector(opt_params)
    TT, FC, BETA, LP, RFCF, SFCF, CFR, CWH, CFMAX_low, CFMAX_high, K, K1, K2, UZL, PERC, ICE_FACTOR, K_MUSK, X_MUSK = opt_params
    cfmax_low_step = scale_linear_to_step(CFMAX_low)
    cfmax_high_step = scale_linear_to_step(CFMAX_high)
    cfr_step = scale_linear_to_step(CFR)
    k_step = scale_recession_to_step(K)
    k1_step = scale_recession_to_step(K1)
    k2_step = scale_recession_to_step(K2)
    perc_step = scale_linear_to_step(PERC)

    par_base = np.array([
        TT, RFCF, SFCF, 0.0, CWH, cfr_step,
        FC, BETA, FIXED["E_CORR"], LP, k_step, k1_step, k2_step, UZL, perc_step,
    ], dtype=np.float64)

    glacier_on = glacier_feature_enabled()
    mode_name = str(mode or "full").strip().lower()
    use_fractional_subgrid = bool(
        glacier_on
        and glacier_processing_mode() == "fractional_subgrid"
        and GLACIER_FRACTION_CELLS is not None
    )
    if event_runtime_independent_active():
        sim_parts = run_event_window_source_parts(
            mode_name,
            par_base,
            ICE_FACTOR,
            cfmax_low_step,
            cfmax_high_step,
            glacier_on,
            use_fractional_subgrid,
        )
        q_total = sim_parts["q_total"]
        q_rain = sim_parts.get("q_rain")
        q_snow = sim_parts.get("q_snow")
        q_ice = sim_parts.get("q_ice")
        q_snow_glacier = sim_parts.get("q_snow_glacier")
        q_glacier_total = sim_parts.get("q_glacier_total")
    elif use_fractional_subgrid:
        sim_parts = run_fractional_subgrid_simulation(
            mode_name,
            par_base,
            ICE_FACTOR,
            cfmax_low_step,
            cfmax_high_step,
        )
        q_total = sim_parts["q_total"]
        q_rain = sim_parts.get("q_rain")
        q_snow = sim_parts.get("q_snow")
        q_ice = sim_parts.get("q_ice")
        q_snow_glacier = sim_parts.get("q_snow_glacier")
        q_glacier_total = sim_parts.get("q_glacier_total")
    elif mode_name == "objective_total":
        q_total = run_all_cells_total_only_flat(
            PREC_CELLS, TEMP_CELLS, ET_CELLS, LL_TEMP_CELLS,
            par_base, ZONE_HIGH_CELLS, INIT_ST, CELL_SCALE,
            GLACIER_CELLS, glacier_on, ICE_FACTOR, cfmax_low_step, cfmax_high_step,
            GLACIER_DELTA_T_CELLS,
        )
        q_rain = q_snow = q_ice = None
        q_snow_glacier = q_glacier_total = None
    elif mode_name == "objective_ice":
        q_total, q_ice = run_all_cells_total_ice_flat(
            PREC_CELLS, TEMP_CELLS, ET_CELLS, LL_TEMP_CELLS,
            par_base, ZONE_HIGH_CELLS, INIT_ST, CELL_SCALE,
            GLACIER_CELLS, glacier_on, ICE_FACTOR, cfmax_low_step, cfmax_high_step,
            GLACIER_DELTA_T_CELLS,
        )
        q_rain = q_snow = None
        q_snow_glacier = q_glacier_total = None
    else:
        q_total, q_rain, q_snow, q_ice = run_all_cells_flat(
            PREC_CELLS, TEMP_CELLS, ET_CELLS, LL_TEMP_CELLS,
            par_base, ZONE_HIGH_CELLS, INIT_ST, CELL_SCALE,
            GLACIER_CELLS, glacier_on, ICE_FACTOR, cfmax_low_step, cfmax_high_step,
            GLACIER_DELTA_T_CELLS,
        )
        if glacier_on:
            q_snow_glacier = np.asarray(q_snow, dtype=np.float64).copy()
        else:
            q_snow_glacier = np.zeros_like(q_total, dtype=np.float64)
        q_glacier_total = (
            np.asarray(q_snow_glacier, dtype=np.float64) + np.asarray(q_ice, dtype=np.float64)
        )

    boundary_full = np.zeros_like(q_total)
    if BOUNDARY_INFLOW_ENABLED and (BOUNDARY_INFLOW_SERIES is not None):
        if len(BOUNDARY_INFLOW_SERIES) != len(q_total):
            raise ValueError(
                f"上游边界入流长度与本次模拟时段不一致：期望 {len(q_total)}，实际 {len(BOUNDARY_INFLOW_SERIES)}"
            )
        boundary_full = BOUNDARY_INFLOW_SERIES.astype(np.float64, copy=True)

    if mode_name == "objective_total":
        sim = {
            "q_total": route_runtime_series(q_total + boundary_full, K_MUSK, X_MUSK),
        }
    elif mode_name == "objective_ice":
        sim = {
            "q_total": route_runtime_series(q_total + boundary_full, K_MUSK, X_MUSK),
            "q_ice": route_runtime_series(q_ice, K_MUSK, X_MUSK),
        }
    else:
        if event_runtime_independent_active():
            sim = route_event_window_series_set(q_total, boundary_full, q_rain, q_snow, q_ice, K_MUSK, X_MUSK)
            sim["q_snow_glacier"] = route_event_window_series(q_snow_glacier, K_MUSK, X_MUSK)
            sim["q_glacier_total"] = route_event_window_series(q_glacier_total, K_MUSK, X_MUSK)
        else:
            sim = route_series_set(q_total, boundary_full, q_rain, q_snow, q_ice, K_MUSK, X_MUSK)
            sim["q_snow_glacier"] = trim_warmup(muskingum_route(q_snow_glacier, K_MUSK, X_MUSK, MUSK_DT))
            sim["q_glacier_total"] = trim_warmup(muskingum_route(q_glacier_total, K_MUSK, X_MUSK, MUSK_DT))
    glacier_reference_available = bool(glacier_on and GLACIER_MELT_REF_RAW is not None)
    sim["glacier_enabled"] = glacier_on
    sim["glacier_model_mode"] = glacier_processing_mode()
    sim["glacier_area_ratio"] = (
        float(BASIN_GLACIER_AREA_FRACTION)
        if np.isfinite(BASIN_GLACIER_AREA_FRACTION)
        else None
    )
    sim["glacier_mask_exists"] = bool(os.path.exists(GLACIER_MASK_PATH))
    sim["glacier_fraction_exists"] = bool(os.path.exists(GLACIER_FRACTION_PATH))
    sim["glacier_elev_exists"] = bool(os.path.exists(GLACIER_ELEV_PATH))
    sim["glacier_reference_available"] = glacier_reference_available
    glacier_reference_used_in_objective = False
    sim["glacier_reference_enabled"] = glacier_reference_used_in_objective
    sim["glacier_reference_used_in_objective"] = glacier_reference_used_in_objective
    sim["boundary_enabled"] = bool(BOUNDARY_INFLOW_ENABLED)
    sim["event_runtime"] = dict(EVENT_RUNTIME_META or {})
    sim["project_object_type"] = current_project_object_type()
    sim["q_score_basis"] = current_q_score_basis()
    sim["reliability_flag"] = RELIABILITY_FLAG
    sim["date"] = pd.DatetimeIndex(SIM_DATES) if SIM_DATES is not None else None
    sim["q_obs"] = Q_OBS_FULL
    sim["q_obs_obj"] = Q_OBS_OBJ
    sim["calib_mask"] = np.asarray(CALIB_MASK, dtype=bool) if CALIB_MASK is not None else None
    sim["valid_mask"] = np.asarray(VALID_MASK, dtype=bool) if VALID_MASK is not None else None
    sim["muskingum_coeffs"] = muskingum_coefficients(K_MUSK, X_MUSK)
    sim["state_minima"] = None
    if mode_name == "objective_total" or (not glacier_reference_available):
        sim["q_ice_reference_raw"] = None
        sim["q_ice_reference"] = None
    else:
        sim["q_ice_reference_raw"] = trim_warmup(GLACIER_MELT_REF_RAW)
        sim["q_ice_reference"] = trim_warmup(muskingum_route(GLACIER_MELT_REF_RAW, K_MUSK, X_MUSK, MUSK_DT))
    if "q_snow_glacier" not in sim:
        q_total_trimmed = sim.get("q_total")
        if q_total_trimmed is not None:
            fallback_len = len(q_total_trimmed)
            if glacier_on and sim.get("q_snow") is not None:
                sim["q_snow_glacier"] = np.asarray(sim.get("q_snow"), dtype=np.float64)[:fallback_len]
            else:
                sim["q_snow_glacier"] = np.zeros(fallback_len, dtype=np.float64)
            q_ice_series = np.asarray(sim.get("q_ice"), dtype=np.float64)[:fallback_len] if sim.get("q_ice") is not None else np.zeros(fallback_len, dtype=np.float64)
            sim["q_glacier_total"] = np.asarray(sim["q_snow_glacier"], dtype=np.float64)[:fallback_len] + q_ice_series

    sim["obs_monthly"] = OBS_MONTHLY_CALIB
    try:
        q_total_arr = sim.get("q_total")
        if q_total_arr is not None and SIM_DATES is not None and CALIB_MASK is not None:
            q_sim_calib = np.asarray(q_total_arr, dtype=np.float64)[CALIB_MASK]
            calib_dates_idx = pd.DatetimeIndex(SIM_DATES)[CALIB_MASK]
            sim["sim_monthly"] = _series_to_monthly_sums(q_sim_calib, calib_dates_idx)
        else:
            sim["sim_monthly"] = None
    except Exception:
        sim["sim_monthly"] = None

    return sim


def _state_branch_arrays(prefix, branch_tuple):
    sp, sm, wc, uz_r, uz_s, uz_i, lz_r, lz_s, lz_i = branch_tuple
    uz = uz_r + uz_s + uz_i
    lz = lz_r + lz_s + lz_i
    return {
        f"{prefix}sp": np.asarray(sp, dtype=np.float32),
        f"{prefix}sm": np.asarray(sm, dtype=np.float32),
        f"{prefix}wc": np.asarray(wc, dtype=np.float32),
        f"{prefix}uz": np.asarray(uz, dtype=np.float32),
        f"{prefix}lz": np.asarray(lz, dtype=np.float32),
        f"{prefix}uz_r": np.asarray(uz_r, dtype=np.float32),
        f"{prefix}uz_s": np.asarray(uz_s, dtype=np.float32),
        f"{prefix}uz_i": np.asarray(uz_i, dtype=np.float32),
        f"{prefix}lz_r": np.asarray(lz_r, dtype=np.float32),
        f"{prefix}lz_s": np.asarray(lz_s, dtype=np.float32),
        f"{prefix}lz_i": np.asarray(lz_i, dtype=np.float32),
    }


def compute_state_snapshot(opt_params):
    opt_params = validate_parameter_vector(opt_params)
    TT, FC, BETA, LP, RFCF, SFCF, CFR, CWH, CFMAX_low, CFMAX_high, K, K1, K2, UZL, PERC, ICE_FACTOR, _, _ = opt_params
    cfmax_low_step = scale_linear_to_step(CFMAX_low)
    cfmax_high_step = scale_linear_to_step(CFMAX_high)
    cfr_step = scale_linear_to_step(CFR)
    k_step = scale_recession_to_step(K)
    k1_step = scale_recession_to_step(K1)
    k2_step = scale_recession_to_step(K2)
    perc_step = scale_linear_to_step(PERC)

    par_base = np.array([
        TT, RFCF, SFCF, 0.0, CWH, cfr_step,
        FC, BETA, FIXED["E_CORR"], LP, k_step, k1_step, k2_step, UZL, perc_step,
    ], dtype=np.float64)

    if VALID_CELLS is None or ZONE_HIGH_CELLS is None:
        raise ValueError("未加载有效像元，无法生成状态快照。")

    snapshot_arrays = {
        "valid_cell_rows": np.asarray(VALID_CELLS[:, 0], dtype=np.int32),
        "valid_cell_cols": np.asarray(VALID_CELLS[:, 1], dtype=np.int32),
        "zone_high_cells": np.asarray(ZONE_HIGH_CELLS, dtype=np.uint8),
    }
    snapshot_meta = {
        "schema": "per_cell_branch_states_v1",
        "snapshot_mode": glacier_processing_mode(),
        "branch_count": 0,
        "branches": [],
        "cell_count": int(len(VALID_CELLS)),
        "time_steps": int(PREC_CELLS.shape[1]) if PREC_CELLS is not None else 0,
        "time_step_hours": float(TIME_STEP_HOURS),
        "snapshot_time": format_time_value(SIM_DATES[-1]) if SIM_DATES is not None and len(SIM_DATES) else "",
        "hot_start_supported": True,
    }

    glacier_on = glacier_feature_enabled()
    use_fractional_subgrid = bool(
        glacier_on
        and glacier_processing_mode() == "fractional_subgrid"
        and GLACIER_FRACTION_CELLS is not None
    )

    if use_fractional_subgrid:
        glacier_active_cells = np.ascontiguousarray(GLACIER_FRACTION_CELLS > 0.0, dtype=np.bool_)
        nonglacier_active_cells = np.ascontiguousarray(GLACIER_FRACTION_CELLS < (1.0 - EPS), dtype=np.bool_)
        nonglacier_glacier_cells = np.zeros_like(glacier_active_cells, dtype=np.bool_)

        glacier_branch = run_cells_state_snapshot_flat(
            PREC_CELLS, TEMP_CELLS, ET_CELLS, LL_TEMP_CELLS,
            par_base, ZONE_HIGH_CELLS, INIT_ST, glacier_active_cells,
            glacier_active_cells, True, ICE_FACTOR, cfmax_low_step, cfmax_high_step,
            GLACIER_DELTA_T_CELLS,
        )
        nonglacier_branch = run_cells_state_snapshot_flat(
            PREC_CELLS, TEMP_CELLS, ET_CELLS, LL_TEMP_CELLS,
            par_base, ZONE_HIGH_CELLS, INIT_ST, nonglacier_active_cells,
            nonglacier_glacier_cells, False, ICE_FACTOR, cfmax_low_step, cfmax_high_step,
            GLACIER_DELTA_T_CELLS,
        )
        snapshot_arrays["glacier_fraction_cells"] = np.asarray(GLACIER_FRACTION_CELLS, dtype=np.float32)
        snapshot_arrays["glacier_active_cells"] = np.asarray(glacier_active_cells, dtype=np.uint8)
        snapshot_arrays["nonglacier_active_cells"] = np.asarray(nonglacier_active_cells, dtype=np.uint8)
        snapshot_arrays.update(_state_branch_arrays("glacier_", glacier_branch))
        snapshot_arrays.update(_state_branch_arrays("nonglacier_", nonglacier_branch))
        snapshot_meta["branch_count"] = 2
        snapshot_meta["branches"] = ["glacier", "nonglacier"]
    else:
        active_cells = np.ones_like(ZONE_HIGH_CELLS, dtype=np.bool_)
        glacier_cells = (
            np.ascontiguousarray(GLACIER_CELLS, dtype=np.bool_)
            if GLACIER_CELLS is not None
            else np.zeros_like(active_cells, dtype=np.bool_)
        )
        main_branch = run_cells_state_snapshot_flat(
            PREC_CELLS, TEMP_CELLS, ET_CELLS, LL_TEMP_CELLS,
            par_base, ZONE_HIGH_CELLS, INIT_ST, active_cells,
            glacier_cells, glacier_on, ICE_FACTOR, cfmax_low_step, cfmax_high_step,
            GLACIER_DELTA_T_CELLS,
        )
        snapshot_arrays["glacier_active_cells"] = np.asarray(glacier_cells if glacier_on else np.zeros_like(active_cells, dtype=np.bool_), dtype=np.uint8)
        snapshot_arrays.update(_state_branch_arrays("main_", main_branch))
        snapshot_meta["branch_count"] = 1
        snapshot_meta["branches"] = ["main"]

    return snapshot_arrays, snapshot_meta


def compute_metrics(q_sim):
    if q_sim is None:
        return {
            "obs_count_cal": 0,
            "obs_count_val": 0,
            "nse_cal": float("nan"),
            "nse_val": float("nan"),
            "rmse_cal": float("nan"),
            "rmse_val": float("nan"),
            "kge_cal": float("nan"),
            "kge_val": float("nan"),
            "kge_r_cal": float("nan"),
            "kge_alpha_cal": float("nan"),
            "kge_beta_cal": float("nan"),
            "kge_r_val": float("nan"),
            "kge_alpha_val": float("nan"),
            "kge_beta_val": float("nan"),
            "log_nse_cal": float("nan"),
            "log_nse_val": float("nan"),
            "pbias_cal": float("nan"),
            "pbias_val": float("nan"),
        }
    q_sim_calib = q_sim[CALIB_MASK]
    q_sim_valid = q_sim[VALID_MASK]
    min_cal = min(len(q_sim_calib), len(Q_OBS_CALIB))
    min_val = min(len(q_sim_valid), len(Q_OBS_VALID))
    obs_cal = Q_OBS_CALIB[:min_cal]
    sim_cal = q_sim_calib[:min_cal]
    obs_val = Q_OBS_VALID[:min_val]
    sim_val = q_sim_valid[:min_val]
    cal_mask = np.isfinite(obs_cal) & np.isfinite(sim_cal)
    val_mask = np.isfinite(obs_val) & np.isfinite(sim_val)
    cal_count = int(np.sum(cal_mask))
    val_count = int(np.sum(val_mask))

    kge_c, kge_r_c, kge_a_c, kge_b_c = kge_numba(obs_cal, sim_cal)
    if val_count >= 2:
        kge_v, kge_r_v, kge_a_v, kge_b_v = kge_numba(obs_val, sim_val)
    else:
        kge_v = kge_r_v = kge_a_v = kge_b_v = float("nan")

    result = {
        "obs_count_cal": cal_count,
        "obs_count_val": val_count,
        "nse_cal": nse_safe(obs_cal, sim_cal),
        "nse_val": nse_safe(obs_val, sim_val) if val_count >= 2 else float("nan"),
        "rmse_cal": rmse(obs_cal, sim_cal) if cal_count >= 2 else float("nan"),
        "rmse_val": rmse(obs_val, sim_val) if val_count >= 2 else float("nan"),
        "kge_cal": float(kge_c) if kge_c > -900 else float("nan"),
        "kge_val": float(kge_v) if kge_v > -900 else float("nan"),
        "kge_r_cal": float(kge_r_c) if kge_r_c > -900 else float("nan"),
        "kge_alpha_cal": float(kge_a_c) if kge_a_c > -900 else float("nan"),
        "kge_beta_cal": float(kge_b_c) if kge_b_c > -900 else float("nan"),
        "kge_r_val": float(kge_r_v) if kge_r_v > -900 else float("nan"),
        "kge_alpha_val": float(kge_a_v) if kge_a_v > -900 else float("nan"),
        "kge_beta_val": float(kge_b_v) if kge_b_v > -900 else float("nan"),
        "log_nse_cal": log_nse(obs_cal, sim_cal),
        "log_nse_val": log_nse(obs_val, sim_val) if val_count >= 2 else float("nan"),
        "pbias_cal": pbias(obs_cal, sim_cal),
        "pbias_val": pbias(obs_val, sim_val) if val_count >= 2 else float("nan"),
    }
    return result


def load_flood_event_config_file(path):
    if not path:
        return {}
    suffix = os.path.splitext(str(path))[1].lower()
    if suffix == ".json":
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    if suffix in {".xlsx", ".xls"}:
        frame = pd.read_excel(path)
    else:
        last_error = None
        for encoding in ("utf-8-sig", "utf-8", "gbk"):
            try:
                frame = pd.read_csv(path, encoding=encoding)
                break
            except Exception as exc:
                last_error = exc
        else:
            raise ValueError(f"洪水事件表读取失败：{last_error}")
    events = frame.where(pd.notna(frame), None).to_dict(orient="records")
    return {"启用": True, "事件表": events, "事件表路径": str(path)}


def _config_bool(value, default=False):
    if isinstance(value, bool):
        return value
    if value is None:
        return default
    raw = str(value).strip().lower()
    if raw in {"1", "true", "yes", "y", "on", "启用", "是"}:
        return True
    if raw in {"0", "false", "no", "n", "off", "禁用", "否"}:
        return False
    return default


def _finite_float(value, default=float("nan")):
    try:
        value = float(value)
    except Exception:
        return default
    return value if np.isfinite(value) else default


def _event_time_text(value):
    if value is None:
        return None
    try:
        return pd.Timestamp(value).isoformat()
    except Exception:
        return str(value)


def normalize_flood_event_weights(raw_weights=None):
    weights = dict(DEFAULT_FLOOD_EVENT_WEIGHTS)
    if isinstance(raw_weights, dict):
        for raw_key, raw_value in raw_weights.items():
            key = FLOOD_EVENT_WEIGHT_ALIASES.get(str(raw_key).strip(), str(raw_key).strip())
            if key not in weights:
                continue
            value = _finite_float(raw_value)
            if np.isfinite(value) and value >= 0.0:
                weights[key] = value
    total = float(sum(weights.values()))
    if total <= EPS:
        weights = dict(DEFAULT_FLOOD_EVENT_WEIGHTS)
        total = float(sum(weights.values()))
    return {
        "raw": {key: float(value) for key, value in weights.items()},
        "normalized": {key: float(value) / total for key, value in weights.items()},
    }


def parse_flood_event_config(config=None):
    raw = FLOOD_EVENT_CONFIG if config is None else config
    if raw is None:
        raw = {}
    if isinstance(raw, list):
        cfg = {"启用": True, "事件表": raw}
    elif isinstance(raw, dict):
        cfg = dict(raw)
    else:
        return {
            "enabled": False,
            "events": [],
            "weights": normalize_flood_event_weights(),
            "warnings": ["洪水事件配置不是对象或数组，已跳过。"],
            "peak_time_tolerance_hours": max(float(TIME_STEP_HOURS), 24.0),
        }

    events = cfg.get("事件表", cfg.get("events", []))
    event_file = str(cfg.get("事件表路径", cfg.get("events_file", cfg.get("event_file", ""))) or "").strip()
    if event_file and not events:
        try:
            loaded = load_flood_event_config_file(event_file)
            if isinstance(loaded, dict):
                events = loaded.get("事件表", loaded.get("events", []))
                cfg.setdefault("事件表路径", event_file)
            elif isinstance(loaded, list):
                events = loaded
        except Exception as exc:
            return {
                "enabled": _config_bool(cfg.get("启用", cfg.get("enabled")), default=True),
                "events": [],
                "weights": normalize_flood_event_weights(cfg.get("目标权重", cfg.get("weights", {}))),
                "warnings": [f"洪水事件表读取失败：{exc}"],
                "peak_time_tolerance_hours": max(float(TIME_STEP_HOURS), 24.0),
                "raw_config": cfg,
            }
    if not isinstance(events, list):
        events = []
    enabled_default = bool(events)
    enabled = _config_bool(cfg.get("启用", cfg.get("enabled")), default=enabled_default)
    weights = normalize_flood_event_weights(cfg.get("目标权重", cfg.get("weights", {})))
    peak_time_tolerance_hours = _finite_float(
        cfg.get("峰现容许误差小时", cfg.get("peak_time_tolerance_hours", max(float(TIME_STEP_HOURS), 24.0))),
        default=max(float(TIME_STEP_HOURS), 24.0),
    )
    if peak_time_tolerance_hours <= 0.0:
        peak_time_tolerance_hours = max(float(TIME_STEP_HOURS), 24.0)
    return {
        "enabled": bool(enabled),
        "events": list(events),
        "weights": weights,
        "warnings": [],
        "peak_time_tolerance_hours": float(peak_time_tolerance_hours),
        "raw_config": cfg,
    }


def flood_event_objective_enabled(config=None):
    raw = FLOOD_EVENT_CONFIG if config is None else config
    if raw is None:
        return False
    if isinstance(raw, list):
        return False
    if not isinstance(raw, dict):
        return False
    parsed = parse_flood_event_config(raw)
    if not parsed.get("enabled"):
        return False
    explicit = (
        raw.get("作为目标函数")
        if "作为目标函数" in raw
        else raw.get("目标函数启用")
        if "目标函数启用" in raw
        else raw.get("objective_enabled")
        if "objective_enabled" in raw
        else raw.get("use_as_objective")
    )
    if explicit is not None:
        return _config_bool(explicit, default=False)
    mode = str(raw.get("模式", raw.get("mode", raw.get("率定模式", ""))) or "").strip().lower()
    return mode in FLOOD_EVENT_OBJECTIVE_MODE_VALUES


def _event_type_key(value):
    return str(value or "").strip().lower()


def _configured_event_type_set(raw_config):
    raw = None
    if isinstance(raw_config, dict):
        raw = raw_config.get("目标事件类型", raw_config.get("objective_event_types"))
    if raw is None or raw == "":
        return None
    if isinstance(raw, str):
        items = [item.strip() for item in re.split(r"[,;，；、\s]+", raw) if item.strip()]
    elif isinstance(raw, (list, tuple, set)):
        items = [str(item).strip() for item in raw if str(item).strip()]
    else:
        items = [str(raw).strip()]
    return {_event_type_key(item) for item in items if item}


def selected_flood_event_indices_for_objective(events, raw_config=None):
    if not events:
        return set()
    configured = _configured_event_type_set(raw_config)
    type_keys = []
    for item in events:
        event = dict(item or {}) if isinstance(item, dict) else {}
        type_keys.append(_event_type_key(event.get("类型", event.get("type", event.get("purpose", event.get("用途", ""))))))
    if configured:
        selected = {idx for idx, item_type in enumerate(type_keys) if item_type in configured}
        return selected
    calibration_indices = {
        idx for idx, item_type in enumerate(type_keys)
        if item_type in FLOOD_EVENT_CALIBRATION_TYPE_ALIASES
    }
    return calibration_indices if calibration_indices else set(range(len(events)))


def high_flow_weighted_nse(obs, sim, quantile=0.70):
    obs = np.asarray(obs, dtype=np.float64)
    sim = np.asarray(sim, dtype=np.float64)
    mask = np.isfinite(obs) & np.isfinite(sim)
    if int(np.sum(mask)) < 2:
        return float("nan")
    o = obs[mask]
    s = sim[mask]
    threshold = float(np.nanquantile(o, min(max(float(quantile), 0.0), 1.0)))
    if not np.isfinite(threshold) or threshold <= EPS:
        threshold = max(float(np.nanmean(o)), EPS)
    weights = np.ones_like(o, dtype=np.float64)
    high_mask = o >= threshold
    weights[high_mask] = np.maximum(1.0, o[high_mask] / threshold)
    weight_sum = float(np.sum(weights))
    if weight_sum <= EPS:
        return float("nan")
    weighted_mean = float(np.sum(weights * o) / weight_sum)
    denominator = float(np.sum(weights * (o - weighted_mean) ** 2))
    if denominator <= EPS:
        return float("nan")
    numerator = float(np.sum(weights * (o - s) ** 2))
    return float(1.0 - numerator / denominator)


def high_flow_kge(obs, sim, quantile=0.70):
    obs = np.asarray(obs, dtype=np.float64)
    sim = np.asarray(sim, dtype=np.float64)
    mask = np.isfinite(obs) & np.isfinite(sim)
    if int(np.sum(mask)) < 2:
        return float("nan")
    threshold = float(np.nanquantile(obs[mask], min(max(float(quantile), 0.0), 1.0)))
    high_mask = mask & (obs >= threshold)
    if int(np.sum(high_mask)) < 2:
        return float("nan")
    value, _, _, _ = kge_numba(obs[high_mask], sim[high_mask])
    return float(value) if value > -900 else float("nan")


def _log_recession_slope_per_day(dates, series, peak_pos):
    dates = pd.DatetimeIndex(dates)
    q = np.asarray(series, dtype=np.float64)
    if peak_pos is None or peak_pos < 0 or peak_pos >= len(q):
        return float("nan"), 0
    dates = dates[peak_pos:]
    q = q[peak_pos:]
    mask = np.isfinite(q) & (q > EPS)
    count = int(np.sum(mask))
    if count < 3:
        return float("nan"), count
    dates = dates[mask]
    q = q[mask]
    days = np.asarray((dates - dates[0]) / pd.Timedelta(days=1), dtype=np.float64)
    if float(np.nanmax(days) - np.nanmin(days)) <= EPS:
        return float("nan"), count
    slope = float(np.polyfit(days, np.log(q), 1)[0])
    return slope, count


def compute_flood_event_recession_metrics(dates, obs, sim, obs_peak_pos, sim_peak_pos):
    obs_slope, obs_count = _log_recession_slope_per_day(dates, obs, obs_peak_pos)
    sim_slope, sim_count = _log_recession_slope_per_day(dates, sim, sim_peak_pos)
    slope_error = float("nan")
    slope_error_percent = float("nan")
    if np.isfinite(obs_slope) and np.isfinite(sim_slope):
        slope_error = float(sim_slope - obs_slope)
        if abs(obs_slope) > EPS:
            slope_error_percent = float(100.0 * slope_error / abs(obs_slope))

    obs = np.asarray(obs, dtype=np.float64)
    sim = np.asarray(sim, dtype=np.float64)
    paired_nse = float("nan")
    paired_count = 0
    if obs_peak_pos is not None and 0 <= obs_peak_pos < len(obs):
        obs_tail = obs[obs_peak_pos:]
        sim_tail = sim[obs_peak_pos:]
        mask = np.isfinite(obs_tail) & np.isfinite(sim_tail)
        paired_count = int(np.sum(mask))
        if paired_count >= 2:
            paired_nse = nse_safe(obs_tail[mask], sim_tail[mask])

    return {
        "obs_log_slope_per_day": obs_slope,
        "sim_log_slope_per_day": sim_slope,
        "slope_error_per_day": slope_error,
        "slope_error_percent": slope_error_percent,
        "obs_recession_count": int(obs_count),
        "sim_recession_count": int(sim_count),
        "paired_recession_count": int(paired_count),
        "paired_recession_nse": paired_nse,
    }


def flood_event_component_scores(metrics, peak_time_tolerance_hours):
    components = {}
    peak_error = _finite_float(metrics.get("peak_error_percent"))
    if np.isfinite(peak_error):
        components["peak_flow_error"] = abs(peak_error) / 100.0
    peak_time = _finite_float(metrics.get("peak_time_error_hours"))
    if np.isfinite(peak_time):
        components["peak_time_error"] = abs(peak_time) / max(float(peak_time_tolerance_hours), EPS)
    volume_error = _finite_float(metrics.get("volume_error_percent"))
    if np.isfinite(volume_error):
        components["volume_error"] = abs(volume_error) / 100.0
    recession_error = _finite_float(metrics.get("recession_slope_error_percent"))
    if np.isfinite(recession_error):
        components["recession_error"] = abs(recession_error) / 100.0
    high_flow_nse = _finite_float(metrics.get("high_flow_weighted_nse"))
    high_flow_penalties = []
    if np.isfinite(high_flow_nse):
        high_flow_penalties.append(max(0.0, 1.0 - high_flow_nse))
    high_flow_kge_value = _finite_float(metrics.get("high_flow_kge"))
    if np.isfinite(high_flow_kge_value):
        high_flow_penalties.append(max(0.0, 1.0 - high_flow_kge_value))
    if high_flow_penalties:
        components["high_flow_skill"] = float(np.mean(high_flow_penalties))
    return components


def flood_event_diagnostic_objective(metrics, weights, peak_time_tolerance_hours):
    components = flood_event_component_scores(metrics, peak_time_tolerance_hours)
    normalized = dict(weights.get("normalized", {}) or {})
    numerator = 0.0
    denominator = 0.0
    for key, value in components.items():
        if not np.isfinite(value):
            continue
        weight = float(normalized.get(key, 0.0) or 0.0)
        if weight <= 0.0:
            continue
        numerator += weight * float(value)
        denominator += weight
    score = float("nan") if denominator <= EPS else float(numerator / denominator)
    return {
        "score": score,
        "components": {key: float(value) for key, value in components.items()},
    }


def compute_single_flood_event_metrics(dates, q_obs, q_sim, event_config, weights, peak_time_tolerance_hours):
    event_config = dict(event_config or {}) if isinstance(event_config, dict) else {}
    event_id = str(event_config.get("event_id", event_config.get("id", event_config.get("编号", ""))) or "").strip()
    event_name = str(event_config.get("名称", event_config.get("name", event_id)) or "").strip()
    event_type = str(
        event_config.get(
            "类型",
            event_config.get("type", event_config.get("purpose", event_config.get("用途", "calibration"))),
        )
        or "calibration"
    ).strip()
    if not event_name:
        token = json.dumps(event_config, ensure_ascii=False, sort_keys=True, default=str).encode("utf-8")
        event_name = f"event_{hashlib.sha1(token).hexdigest()[:8]}"
    if not event_id:
        event_id = event_name
    event_weight = _finite_float(event_config.get("weight", event_config.get("权重", 1.0)), default=1.0)
    if not np.isfinite(event_weight) or event_weight <= 0.0:
        event_weight = 1.0
    identity = {
        "event_id": event_id,
        "name": event_name,
        "purpose": event_type,
        "type": event_type,
        "weight": float(event_weight),
        "note": str(event_config.get("note", event_config.get("备注", "")) or ""),
    }

    warnings = []
    event_start_raw = event_config.get("score_start", event_config.get("评分开始", event_config.get("事件开始", event_config.get("start"))))
    event_end_raw = event_config.get("score_end", event_config.get("评分结束", event_config.get("事件结束", event_config.get("end"))))
    if event_start_raw in (None, "") or event_end_raw in (None, ""):
        return {
            **identity,
            "status": "missing_event_dates",
            "valid": False,
            "warnings": ["事件缺少开始或结束时间。"],
        }
    try:
        event_start = normalize_time_value(event_start_raw)
        event_end = normalize_time_value(event_end_raw, is_end=True)
    except Exception as exc:
        return {
            **identity,
            "status": "invalid_event_dates",
            "valid": False,
            "warnings": [f"事件起止时间无法解析：{exc}"],
        }
    if event_end < event_start:
        return {
            **identity,
            "status": "invalid_event_order",
            "valid": False,
            "event_start": _event_time_text(event_start),
            "event_end": _event_time_text(event_end),
            "warnings": ["事件结束时间早于事件开始时间。"],
        }

    warmup_start_raw = event_config.get("run_start", event_config.get("运行开始", event_config.get("预热开始", event_config.get("warmup_start"))))
    run_end_raw = event_config.get("run_end", event_config.get("运行结束", event_config.get("退水结束")))
    warmup_start = None
    run_end = None
    if warmup_start_raw:
        try:
            warmup_start = normalize_time_value(warmup_start_raw)
            if warmup_start > event_start:
                warnings.append("预热开始晚于事件开始；当前仅按连续模拟结果进行事件评价。")
        except Exception as exc:
            warnings.append(f"预热开始无法解析：{exc}")
    if run_end_raw:
        try:
            run_end = normalize_time_value(run_end_raw, is_end=True)
            if run_end < event_end:
                warnings.append("运行结束早于事件结束；当前仅按评分窗口评价洪水事件。")
        except Exception as exc:
            warnings.append(f"运行结束无法解析：{exc}")

    date_index = pd.DatetimeIndex(dates)
    q_obs = np.asarray(q_obs, dtype=np.float64)
    q_sim = np.asarray(q_sim, dtype=np.float64)
    n = min(len(date_index), len(q_obs), len(q_sim))
    date_index = date_index[:n]
    q_obs = q_obs[:n]
    q_sim = q_sim[:n]
    if n == 0:
        return {
            **identity,
            "status": "empty_series",
            "valid": False,
            "warnings": warnings + ["模拟序列为空，无法评价洪水事件。"],
        }

    if event_start < date_index[0] or event_end > date_index[-1]:
        warnings.append("事件窗口超出当前连续模拟时段，已按可用时段裁剪评价。")
    window_mask = (date_index >= event_start) & (date_index <= event_end)
    if not np.any(window_mask):
        return {
            **identity,
            "status": "outside_simulation_period",
            "valid": False,
            "event_start": _event_time_text(event_start),
            "event_end": _event_time_text(event_end),
            "warmup_start": _event_time_text(warmup_start),
            "run_start": _event_time_text(warmup_start),
            "score_start": _event_time_text(event_start),
            "score_end": _event_time_text(event_end),
            "run_end": _event_time_text(run_end),
            "warnings": warnings,
        }

    event_dates = date_index[window_mask]
    obs_event = q_obs[window_mask]
    sim_event = q_sim[window_mask]
    valid_mask = np.isfinite(obs_event) & np.isfinite(sim_event)
    valid_count = int(np.sum(valid_mask))
    total_steps = int(len(obs_event))
    duration_hours = float((event_dates[-1] - event_dates[0]) / pd.Timedelta(hours=1) + TIME_STEP_HOURS)
    base = {
        **identity,
        "status": "ok" if valid_count >= 2 else "insufficient_valid_points",
        "valid": bool(valid_count >= 2),
        "event_start": _event_time_text(event_start),
        "event_end": _event_time_text(event_end),
        "warmup_start": _event_time_text(warmup_start),
        "run_start": _event_time_text(warmup_start),
        "score_start": _event_time_text(event_start),
        "score_end": _event_time_text(event_end),
        "run_end": _event_time_text(run_end),
        "window_start_used": _event_time_text(event_dates[0]),
        "window_end_used": _event_time_text(event_dates[-1]),
        "total_steps": total_steps,
        "valid_count": valid_count,
        "duration_hours": duration_hours,
        "warnings": warnings,
    }
    if valid_count < 2:
        base["diagnostic_objective"] = flood_event_diagnostic_objective(base, weights, peak_time_tolerance_hours)
        return base

    obs_valid = obs_event[valid_mask]
    sim_valid = sim_event[valid_mask]
    dates_valid = pd.DatetimeIndex(event_dates[valid_mask])
    obs_peak_pos = int(np.nanargmax(obs_valid))
    sim_peak_pos = int(np.nanargmax(sim_valid))
    obs_peak = float(obs_valid[obs_peak_pos])
    sim_peak = float(sim_valid[sim_peak_pos])
    obs_peak_time = dates_valid[obs_peak_pos]
    sim_peak_time = dates_valid[sim_peak_pos]
    peak_error_percent = float("nan")
    if abs(obs_peak) > EPS:
        peak_error_percent = float(100.0 * (sim_peak - obs_peak) / obs_peak)
    peak_time_error_hours = float((sim_peak_time - obs_peak_time) / pd.Timedelta(hours=1))

    dt_seconds = float(TIME_STEP_HOURS) * 3600.0
    obs_volume = float(np.nansum(obs_valid) * dt_seconds)
    sim_volume = float(np.nansum(sim_valid) * dt_seconds)
    volume_error_percent = float("nan")
    if abs(obs_volume) > EPS:
        volume_error_percent = float(100.0 * (sim_volume - obs_volume) / obs_volume)

    kge_value, kge_r, kge_alpha, kge_beta = kge_numba(obs_valid, sim_valid)
    if kge_value <= -900:
        kge_value = kge_r = kge_alpha = kge_beta = float("nan")
    recession = compute_flood_event_recession_metrics(
        dates_valid,
        obs_valid,
        sim_valid,
        obs_peak_pos,
        sim_peak_pos,
    )

    base.update({
        "obs_peak_m3s": obs_peak,
        "sim_peak_m3s": sim_peak,
        "peak_error_percent": peak_error_percent,
        "obs_peak_time": _event_time_text(obs_peak_time),
        "sim_peak_time": _event_time_text(sim_peak_time),
        "peak_time_error_hours": peak_time_error_hours,
        "peak_time_error_steps": float(peak_time_error_hours / max(float(TIME_STEP_HOURS), EPS)),
        "obs_volume_m3": obs_volume,
        "sim_volume_m3": sim_volume,
        "volume_error_percent": volume_error_percent,
        "nse": nse_safe(obs_valid, sim_valid),
        "kge": float(kge_value) if np.isfinite(kge_value) else float("nan"),
        "kge_r": float(kge_r) if np.isfinite(kge_r) else float("nan"),
        "kge_alpha": float(kge_alpha) if np.isfinite(kge_alpha) else float("nan"),
        "kge_beta": float(kge_beta) if np.isfinite(kge_beta) else float("nan"),
        "rmse_m3s": rmse(obs_valid, sim_valid),
        "pbias": pbias(obs_valid, sim_valid),
        "high_flow_weighted_nse": high_flow_weighted_nse(obs_valid, sim_valid),
        "high_flow_kge": high_flow_kge(obs_valid, sim_valid),
        "high_flow_quantile": 0.70,
        "recession_obs_log_slope_per_day": recession["obs_log_slope_per_day"],
        "recession_sim_log_slope_per_day": recession["sim_log_slope_per_day"],
        "recession_slope_error_per_day": recession["slope_error_per_day"],
        "recession_slope_error_percent": recession["slope_error_percent"],
        "recession_obs_count": recession["obs_recession_count"],
        "recession_sim_count": recession["sim_recession_count"],
        "recession_paired_count": recession["paired_recession_count"],
        "recession_paired_nse": recession["paired_recession_nse"],
    })
    base["diagnostic_objective"] = flood_event_diagnostic_objective(
        base,
        weights,
        peak_time_tolerance_hours,
    )
    return base


def _finite_mean(items, key, absolute=False):
    values = []
    for item in items:
        value = _finite_float(item.get(key))
        if np.isfinite(value):
            values.append(abs(value) if absolute else value)
    return float(np.mean(values)) if values else float("nan")


def aggregate_flood_event_metrics(events):
    valid_events = [item for item in events if bool(item.get("valid"))]

    def _summary(items):
        scores = []
        for item in items:
            score = _finite_float(dict(item.get("diagnostic_objective", {}) or {}).get("score"))
            if np.isfinite(score):
                scores.append(score)
        return {
            "event_count": int(len(items)),
            "valid_event_count": int(sum(1 for item in items if bool(item.get("valid")))),
            "mean_abs_peak_error_percent": _finite_mean(items, "peak_error_percent", absolute=True),
            "mean_abs_peak_time_error_hours": _finite_mean(items, "peak_time_error_hours", absolute=True),
            "mean_abs_volume_error_percent": _finite_mean(items, "volume_error_percent", absolute=True),
            "mean_nse": _finite_mean(items, "nse"),
            "mean_kge": _finite_mean(items, "kge"),
            "mean_high_flow_weighted_nse": _finite_mean(items, "high_flow_weighted_nse"),
            "mean_high_flow_kge": _finite_mean(items, "high_flow_kge"),
            "mean_diagnostic_objective": float(np.mean(scores)) if scores else float("nan"),
        }

    result = {"all": _summary(valid_events)}
    for event_type in sorted({str(item.get("type", "") or "") for item in valid_events}):
        result[event_type or "unspecified"] = _summary([
            item for item in valid_events if str(item.get("type", "") or "") == event_type
        ])
    return result


def compute_flood_event_evaluation(dates, q_obs, q_sim, config=None, evaluation_basis=None, objective_only=False):
    parsed = parse_flood_event_config(config)
    raw_events = list(parsed["events"])
    selected_indices = selected_flood_event_indices_for_objective(raw_events, parsed.get("raw_config", {}))
    indexed_events = [
        (idx, event)
        for idx, event in enumerate(raw_events)
        if (not objective_only) or idx in selected_indices
    ]
    result = {
        "schema": FLOOD_EVENT_SCHEMA,
        "enabled": bool(parsed["enabled"]),
        "status": "disabled",
        "evaluation_basis": str(evaluation_basis or current_q_score_basis()),
        "time_step_hours": float(TIME_STEP_HOURS),
        "peak_time_tolerance_hours": float(parsed["peak_time_tolerance_hours"]),
        "weights": parsed["weights"],
        "event_count": int(len(raw_events)),
        "objective_event_count": int(len(selected_indices)),
        "valid_event_count": 0,
        "valid_objective_event_count": 0,
        "events": [],
        "summary": {},
        "warnings": list(parsed.get("warnings", [])),
        "objective_enabled": bool(
            flood_event_objective_enabled(config)
            or current_objective_mode() == FLOOD_EVENT_OBJECTIVE_FAMILY
        ),
        "objective_only": bool(objective_only),
        "notes": [
            (
                "事件窗口资料模式按场独立运行并评价评分窗口，事件之间不传递模型状态。"
                if event_runtime_independent_active()
                else "洪水事件评价基于连续模拟序列裁剪事件窗口计算。"
            ),
            "只有显式启用事件目标函数时，事件指标才进入优化目标；默认仍作为诊断输出。",
        ],
    }
    result["diagnostic_only"] = not bool(result["objective_enabled"])
    if not result["enabled"]:
        return result
    if len(raw_events) == 0:
        result["status"] = "no_events"
        result["warnings"].append("洪水事件率定已启用，但事件表为空。")
        return result
    if objective_only and len(indexed_events) == 0:
        result["status"] = "no_objective_events"
        result["warnings"].append("未找到用于事件目标函数的洪水事件。")
        return result

    events = []
    for idx, item in indexed_events:
        event_metrics = compute_single_flood_event_metrics(
            dates,
            q_obs,
            q_sim,
            item,
            parsed["weights"],
            parsed["peak_time_tolerance_hours"],
        )
        event_metrics["used_in_objective"] = bool(result["objective_enabled"] and idx in selected_indices)
        events.append(event_metrics)
    result["events"] = events
    result["valid_event_count"] = int(sum(1 for item in events if bool(item.get("valid"))))
    result["valid_objective_event_count"] = int(sum(
        1 for item in events
        if bool(item.get("valid")) and bool(item.get("used_in_objective"))
    ))
    result["status"] = "ok" if result["valid_event_count"] > 0 else "no_valid_events"
    result["summary"] = aggregate_flood_event_metrics(events)
    return result


def flatten_flood_event_record(event):
    diagnostic = dict(event.get("diagnostic_objective", {}) or {})
    return {
        "event_id": event.get("event_id"),
        "name": event.get("name"),
        "purpose": event.get("purpose", event.get("type")),
        "type": event.get("type"),
        "weight": event.get("weight"),
        "note": event.get("note"),
        "status": event.get("status"),
        "valid": event.get("valid"),
        "used_in_objective": event.get("used_in_objective"),
        "run_start": event.get("run_start", event.get("warmup_start")),
        "score_start": event.get("score_start", event.get("event_start")),
        "score_end": event.get("score_end", event.get("event_end")),
        "run_end": event.get("run_end"),
        "event_start": event.get("event_start"),
        "event_end": event.get("event_end"),
        "window_start_used": event.get("window_start_used"),
        "window_end_used": event.get("window_end_used"),
        "total_steps": event.get("total_steps"),
        "valid_count": event.get("valid_count"),
        "obs_peak_m3s": event.get("obs_peak_m3s"),
        "sim_peak_m3s": event.get("sim_peak_m3s"),
        "peak_error_percent": event.get("peak_error_percent"),
        "obs_peak_time": event.get("obs_peak_time"),
        "sim_peak_time": event.get("sim_peak_time"),
        "peak_time_error_hours": event.get("peak_time_error_hours"),
        "obs_volume_m3": event.get("obs_volume_m3"),
        "sim_volume_m3": event.get("sim_volume_m3"),
        "volume_error_percent": event.get("volume_error_percent"),
        "nse": event.get("nse"),
        "kge": event.get("kge"),
        "rmse_m3s": event.get("rmse_m3s"),
        "pbias": event.get("pbias"),
        "high_flow_weighted_nse": event.get("high_flow_weighted_nse"),
        "high_flow_kge": event.get("high_flow_kge"),
        "recession_obs_log_slope_per_day": event.get("recession_obs_log_slope_per_day"),
        "recession_sim_log_slope_per_day": event.get("recession_sim_log_slope_per_day"),
        "recession_slope_error_percent": event.get("recession_slope_error_percent"),
        "recession_paired_nse": event.get("recession_paired_nse"),
        "diagnostic_objective": diagnostic.get("score"),
        "warnings": "; ".join(str(item) for item in event.get("warnings", []) or []),
    }


def write_flood_event_outputs(run_dir, evaluation):
    if not isinstance(evaluation, dict) or not evaluation.get("enabled"):
        return None
    events = list(evaluation.get("events", []) or [])
    if not events:
        return None
    path = os.path.join(run_dir, "flood_events.csv")
    pd.DataFrame([flatten_flood_event_record(item) for item in events]).to_csv(
        path,
        index=False,
        encoding="utf-8-sig",
    )
    return os.path.basename(path)


def flood_event_objective_score(evaluation):
    if not isinstance(evaluation, dict) or evaluation.get("status") != "ok":
        return float("nan")
    summary = dict(evaluation.get("summary", {}).get("all", {}) or {})
    return _finite_float(summary.get("mean_diagnostic_objective"))


def compute_flood_event_objective_terms(metrics, sim):
    q_score_series, q_score_basis = scoring_series(sim)
    if q_score_series is None:
        return BAD_OBJ, None
    event_eval = compute_flood_event_evaluation(
        SIM_DATES,
        Q_OBS_FULL,
        q_score_series,
        FLOOD_EVENT_CONFIG,
        evaluation_basis=q_score_basis,
        objective_only=True,
    )
    score = flood_event_objective_score(event_eval)
    if (not np.isfinite(score)) or int(event_eval.get("valid_event_count", 0) or 0) <= 0:
        return BAD_OBJ, None
    nse_cal = float(metrics.get("nse_cal", float("nan")))
    nse_val = float(metrics.get("nse_val", float("nan")))
    log_nse_cal = float(metrics.get("log_nse_cal", float("nan")))
    log_nse_val = float(metrics.get("log_nse_val", float("nan")))
    pbias_cal = float(metrics.get("pbias_cal", float("nan")))
    pbias_val = float(metrics.get("pbias_val", float("nan")))
    return float(score), {
        "objective_family": FLOOD_EVENT_OBJECTIVE_FAMILY,
        "objective_value": float(score),
        "event_objective_value": float(score),
        "event_count": int(event_eval.get("event_count", 0) or 0),
        "objective_event_count": int(event_eval.get("objective_event_count", 0) or 0),
        "valid_objective_event_count": int(event_eval.get("valid_event_count", 0) or 0),
        "nse_cal": nse_cal,
        "nse_val": nse_val,
        "log_nse_cal": log_nse_cal if np.isfinite(log_nse_cal) else nse_cal,
        "log_nse_val": log_nse_val,
        "pbias_cal": pbias_cal,
        "pbias_val": pbias_val,
        "objective_terms": {
            "flood_events": {
                "score": float(score),
                "weights": dict(event_eval.get("weights", {}) or {}),
                "summary": dict(event_eval.get("summary", {}) or {}),
            }
        },
        "diagnostics": {
            "flood_event_evaluation": event_eval,
        },
    }


def objective(x):
    _increment_eval_count()
    try:
        k0 = float(x[10])
        k1 = float(x[11])
        k2 = float(x[12])
        k_musk = float(x[16])
        x_musk = float(x[17])
        if not (k0 > k1 > k2 > 0.0):
            return BAD_OBJ
        if not muskingum_is_valid(k_musk, x_musk):
            return BAD_OBJ

        sim = run_simulation(x, mode=objective_simulation_mode())
        q_score_series, _ = scoring_series(sim)
        obj, terms = compute_objective_terms(compute_metrics(q_score_series), sim)
        if (not np.isfinite(obj)) or (terms is None):
            return BAD_OBJ

        _update_best_state(obj, terms, x)

        return float(obj)
    except Exception:
        return BAD_OBJ


def objective_with_logging(x):
    obj = objective(x)
    log_every = max(1, int(getattr(args, "log_every", 10) or 10))
    current_eval, _, current_best_score, current_best_objective, _ = _snapshot_objective_state()
    if np.isfinite(obj) and (current_eval % log_every == 0):
        elapsed = time.time() - start_time
        rate = current_eval / elapsed if elapsed > 0 else 0.0
        try:
            sim = run_simulation(x, mode=objective_simulation_mode())
            q_score_series, _ = scoring_series(sim)
            _, terms = compute_objective_terms(compute_metrics(q_score_series), sim)
        except Exception:
            terms = None
        if terms:
            log_line = (
                f"[评估 {current_eval}] 率定期NSE={terms['nse_cal']:.4f} "
                f"验证期NSE={terms['nse_val']:.4f} 目标值={obj:.4f} "
            )
            if current_objective_mode() == FLOOD_EVENT_OBJECTIVE_FAMILY:
                log_line += (
                    f"事件有效场次={int(terms.get('valid_objective_event_count', 0) or 0)}/"
                    f"{int(terms.get('objective_event_count', 0) or 0)} "
                )
            elif current_objective_mode() == OBJECTIVE_FAMILY_DAILY:
                log_line += (
                    f"logNSE_cal={terms['log_nse_cal']:.4f} "
                    f"PBIAS_cal={terms['pbias_cal']:+.2f}% "
                )
                frac_info = (
                    dict(terms.get("diagnostics", {}).get("glacier_fraction_report", {}) or {})
                    if isinstance(terms.get("diagnostics"), dict)
                    else {}
                )
                f_ice_val = frac_info.get("f_ice")
                if f_ice_val is not None and np.isfinite(float(f_ice_val)):
                    log_line += f"冰川占比={float(f_ice_val) * 100:.1f}% "
            log_line += f"当前最优NSE={current_best_score:.4f} 当前最优目标值={current_best_objective:.4f} 评估速率={rate:.1f} 次/s"
            log_msg(log_line)
    return obj


def make_refine_bounds(x_best, bounds, shrink=0.15, min_width=0.05):
    x_best = np.asarray(x_best, dtype=np.float64)
    out = []
    for xi, (lo, hi) in zip(x_best, bounds):
        width = hi - lo
        window = max(shrink * width, min_width * width)
        out.append((max(lo, xi - window), min(hi, xi + window)))
    return out


def validate_search_bounds(bounds):
    checked = []
    for idx, (lo, hi) in enumerate(bounds):
        lo_val = float(lo)
        hi_val = float(hi)
        if (not np.isfinite(lo_val)) or (not np.isfinite(hi_val)):
            raise ValueError(f"搜索边界包含非有限值：{param_names[idx]}")
        if hi_val <= lo_val:
            raise ValueError(f"搜索边界无效：{param_names[idx]} [{lo_val}, {hi_val}]")
        checked.append((lo_val, hi_val))

    probe_rng = np.random.default_rng(0)
    sample_feasible_recession_triplet(checked, probe_rng, max_attempts=32)
    sample_feasible_muskingum_pair(checked, probe_rng, max_attempts=32)
    return checked


def ensure_feasible_search_bounds(bounds, fallback_bounds=None, stage_label="搜索范围"):
    try:
        return validate_search_bounds(bounds)
    except Exception as exc:
        if fallback_bounds is None:
            raise
        fallback = validate_search_bounds(fallback_bounds)
        log_msg(f"[WARN] {stage_label} 不可行（{exc}）；已回退到上一层搜索范围。")
        return fallback


def clip_vector_to_bounds(vector, bounds):
    arr = np.asarray(vector, dtype=np.float64).copy()
    if arr.shape[0] != len(bounds):
        raise ValueError(f"参数维度不一致：期望 {len(bounds)}，实际 {arr.shape[0]}")
    for idx, (lo, hi) in enumerate(bounds):
        arr[idx] = min(max(float(arr[idx]), float(lo)), float(hi))
    return arr


def normalize_seed_vectors(bounds, seed_vectors=None):
    normalized = []
    seen = set()
    for vector in list(seed_vectors or []):
        if vector is None:
            continue
        try:
            arr = clip_vector_to_bounds(vector, bounds)
            arr = validate_parameter_vector(arr)
        except Exception:
            continue
        key = tuple(round(float(v), 12) for v in arr.tolist())
        if key in seen:
            continue
        seen.add(key)
        normalized.append(np.asarray(arr, dtype=np.float64))
    return normalized


def load_initial_param_vector(path):
    if not path:
        return None
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    if isinstance(data, dict) and isinstance(data.get("params"), dict):
        data = data["params"]
    if isinstance(data, dict):
        missing = [name for name in param_names if name not in data]
        if missing:
            raise ValueError(f"初始参数文件缺少以下参数：{', '.join(missing)}")
        values = [float(data[name]) for name in param_names]
        return sanitize_initial_param_vector(values)
    if isinstance(data, list):
        if len(data) != len(param_names):
            raise ValueError(f"初始参数长度不一致：期望 {len(param_names)}，实际 {len(data)}")
        return sanitize_initial_param_vector([float(v) for v in data])
    raise ValueError("不支持的初始参数文件格式。")


def apply_initial_bounds(bounds, init_vector, shrink):
    if init_vector is None or shrink <= 0.0:
        return list(bounds)
    return make_refine_bounds(init_vector, bounds, shrink=max(shrink, 0.01), min_width=0.03)


def sample_feasible_recession_triplet(bounds, rng, max_attempts=256):
    eps = 1e-6
    k_lo, k_hi = [float(v) for v in bounds[10]]
    k1_lo, k1_hi = [float(v) for v in bounds[11]]
    k2_lo, k2_hi = [float(v) for v in bounds[12]]

    k_lower = max(k_lo, k1_lo + eps)
    k1_lower = max(k1_lo, k2_lo + eps)
    if k_hi <= k_lower or k1_hi <= k1_lower or k2_hi <= k2_lo:
        raise ValueError("退水参数边界不存在可行解。")

    for _ in range(max_attempts):
        k = float(rng.uniform(k_lower, k_hi))
        k1_upper = min(k1_hi, k - eps)
        if k1_upper <= k1_lower:
            continue
        k1 = float(rng.uniform(k1_lower, k1_upper))
        k2_upper = min(k2_hi, k1 - eps)
        if k2_upper <= k2_lo:
            continue
        k2 = float(rng.uniform(k2_lo, k2_upper))
        if k > k1 > k2 > 0.0:
            return k, k1, k2

    k = float(k_hi)
    k1 = float(min(k1_hi, k - eps))
    k2 = float(min(k2_hi, k1 - eps))
    if not (k > k1 > k2 > 0.0):
        raise ValueError("无法从当前边界生成满足 K > K1 > K2 > 0 的初始种群。")
    return k, k1, k2


def sample_feasible_muskingum_pair(bounds, rng, max_attempts=256):
    eps = 1e-6
    k_lo, k_hi = [float(v) for v in bounds[16]]
    x_lo, x_hi = [float(v) for v in bounds[17]]
    x_hi = min(x_hi, 0.5 - eps)
    if k_hi <= k_lo or x_hi < x_lo:
        raise ValueError("Muskingum 参数边界不存在可行解。")

    for _ in range(max_attempts):
        x_val = float(rng.uniform(x_lo, x_hi))
        lower = max(k_lo, MUSK_DT / (2.0 * max(1.0 - x_val, EPS)) + eps)
        if x_val <= eps:
            upper = k_hi
        else:
            upper = min(k_hi, MUSK_DT / (2.0 * x_val) - eps)
        if lower > upper:
            continue
        k_val = float(rng.uniform(lower, upper))
        if muskingum_is_valid(k_val, x_val):
            return k_val, x_val

    x_candidates = [float(x_lo), float((x_lo + x_hi) / 2.0), float(x_hi)]
    for x_val in x_candidates:
        lower = max(k_lo, MUSK_DT / (2.0 * max(1.0 - x_val, EPS)) + eps)
        if x_val <= eps:
            upper = k_hi
        else:
            upper = min(k_hi, MUSK_DT / (2.0 * x_val) - eps)
        if lower <= upper:
            k_val = float((lower + upper) / 2.0)
            if muskingum_is_valid(k_val, x_val):
                return k_val, x_val

    raise ValueError("无法从当前边界生成满足 Muskingum 约束的初始种群。")


def sample_feasible_candidate(bounds, rng):
    vector = np.array(
        [
            float(lo) if float(hi) <= float(lo) else float(rng.uniform(float(lo), float(hi)))
            for (lo, hi) in bounds
        ],
        dtype=np.float64,
    )
    vector[10], vector[11], vector[12] = sample_feasible_recession_triplet(bounds, rng)
    vector[16], vector[17] = sample_feasible_muskingum_pair(bounds, rng)
    return vector


def build_de_initial_population(bounds, popsize, seed, seed_vectors=None):
    bounds = validate_search_bounds(list(bounds))
    dim = len(bounds)
    population = max(5, int(popsize) * dim)
    rng = np.random.default_rng(seed)
    init = np.zeros((population, dim), dtype=np.float64)
    filled = 0
    for candidate in normalize_seed_vectors(bounds, seed_vectors):
        if filled >= population:
            break
        init[filled, :] = candidate
        filled += 1
    while filled < population:
        init[filled, :] = sample_feasible_candidate(bounds, rng)
        filled += 1
    return init


def summarize_candidate(x):
    try:
        sim = run_simulation(x)
        q_score_series, _ = scoring_series(sim)
        metrics = compute_metrics(q_score_series)
        return float(metrics.get("nse_cal", np.nan)), float(metrics.get("nse_val", np.nan))
    except Exception:
        return float("nan"), float("nan")


def staged_calibration_phase_definitions():
    return [
        {
            "name": "hydrologic_skeleton",
            "label": "Phase 1 水文骨架",
            "released_parameters": ["RFCF", "FC", "BETA", "LP", "K", "K1", "K2", "UZL", "PERC"],
            "purpose": "先识别雨洪、土壤、地下水和退水骨架，锁住雪冰高自由度，防止冰川或雪过程过早代偿。",
            "guardrail_notes": [
                "ICE_FACTOR 在本阶段固定在种子值附近。",
                "glacier temperature correction 为数据派生项，本阶段不作为可调参数释放。",
            ],
        },
        {
            "name": "snow_process",
            "label": "Phase 2 雪过程",
            "released_parameters": ["TT", "SFCF", "CFR", "CWH", "CFMAX_low", "CFMAX_high"],
            "purpose": "在水文骨架稳定后识别春季起涨、融雪季体积和雪储量释放。",
            "guardrail_notes": [
                "水文骨架参数继承 Phase 1 最优值并固定。",
                "ICE_FACTOR 继续固定，避免雪过程未识别清楚时由冰川代偿。",
            ],
        },
        {
            "name": "glacier_refinement",
            "label": "Phase 3 冰川微调",
            "released_parameters": ["ICE_FACTOR"],
            "purpose": "最后释放冰川参数，只允许冰川解释晚融季、暖季、雪耗尽后的额外径流。",
            "guardrail_notes": [
                "水文骨架与雪过程参数继承前两阶段最优值并固定。",
                "fractional glacier / glacier_elev 在当前参数体系中为输入或派生栅格，不作为可调标量参数释放。",
            ],
        },
    ]


def _parameter_map_from_vector(vector):
    arr = np.asarray(vector, dtype=np.float64)
    return {name: round(float(arr[idx]), 6) for idx, name in enumerate(param_names)}


def _score_summary_for_vector(vector, objective_value=None):
    try:
        sim = run_simulation(vector, mode=objective_simulation_mode())
        q_score_series, _ = scoring_series(sim)
        metrics = compute_metrics(q_score_series)
        summary = {
            "objective_value": (
                round(float(objective_value), 6)
                if objective_value is not None and np.isfinite(float(objective_value))
                else None
            ),
            "nse_cal": round(float(metrics.get("nse_cal", np.nan)), 4)
            if np.isfinite(float(metrics.get("nse_cal", np.nan)))
            else None,
            "nse_val": round(float(metrics.get("nse_val", np.nan)), 4)
            if np.isfinite(float(metrics.get("nse_val", np.nan)))
            else None,
            "kge_cal": round(float(metrics.get("kge_cal", np.nan)), 4)
            if np.isfinite(float(metrics.get("kge_cal", np.nan)))
            else None,
            "pbias_cal": round(float(metrics.get("pbias_cal", np.nan)), 2)
            if np.isfinite(float(metrics.get("pbias_cal", np.nan)))
            else None,
        }
        if current_objective_mode() == OBJECTIVE_FAMILY_DAILY:
            try:
                _, evaluation = compute_objective_terms(metrics, sim)
                flow_guard = dict(evaluation.get("objective_terms", {}).get("flow_guard", {}) or {})
                cryo_terms = dict(evaluation.get("objective_terms", {}).get("cryo_consistency", {}) or {})
                diagnostics = dict(evaluation.get("diagnostics", {}) or {})
                summary["flow_guard_status"] = flow_guard.get("status")
                summary["ice_dominance_guard_status"] = (
                    dict(cryo_terms.get("ice_dominance_guard", {}) or {}).get("status")
                )
                summary["peak_source_guard_status"] = (
                    dict(cryo_terms.get("peak_source_guard", {}) or {}).get("status")
                )
                summary["recession_takeover_status"] = (
                    dict(diagnostics.get("recession_takeover_diagnostic", {}) or {}).get("status")
                )
            except Exception:
                pass
        return summary
    except Exception as exc:
        return {
            "objective_value": (
                round(float(objective_value), 6)
                if objective_value is not None and np.isfinite(float(objective_value))
                else None
            ),
            "error": str(exc),
        }


def _tight_bound_around_value(value, base_bound):
    lo, hi = [float(v) for v in base_bound]
    val = min(max(float(value), lo), hi)
    width = max((hi - lo) * 1e-6, 1e-6)
    out_lo = max(lo, val - width)
    out_hi = min(hi, val + width)
    if out_hi <= out_lo:
        if out_lo <= lo:
            out_hi = min(hi, out_lo + width)
        else:
            out_lo = max(lo, out_hi - width)
    if out_hi <= out_lo:
        out_hi = out_lo + max(width, 1e-9)
    return (float(out_lo), float(out_hi))


def build_staged_phase_bounds(base_bounds, seed_vector, released_parameters):
    release_set = {str(name) for name in released_parameters}
    seed = sanitize_initial_param_vector(seed_vector)
    phase_bounds = []
    fixed_parameters = []
    fixed_values = {}
    for idx, (name, bound) in enumerate(zip(param_names, base_bounds)):
        if name in release_set:
            phase_bounds.append(tuple(float(v) for v in bound))
        else:
            phase_bounds.append(_tight_bound_around_value(seed[idx], bound))
            fixed_parameters.append(name)
            fixed_values[name] = round(float(seed[idx]), 6)
    phase_bounds = validate_search_bounds(phase_bounds)
    return phase_bounds, fixed_parameters, fixed_values


def build_staged_calibration_metadata(phases, final_phase):
    return {
        "calibration_workflow": CALIBRATION_WORKFLOW_STAGED,
        "calibration_phases": list(phases),
        "final_selected_phase": str(final_phase or ""),
        "final_parameters_from_phase": str(final_phase or ""),
        "objective_family": OBJECTIVE_FAMILY_DAILY,
        "active_objective_guards": [
            "flow_guard",
            "nonflow_cap",
            "ice_dominance_guard",
            "peak_source_guard",
            "recession_takeover_diagnostic",
        ],
        "notes": [
            "三阶段率定流程只改变参数释放顺序和 phase metadata，不重写 HBV-Cryo 前向核心。",
            "各阶段仍使用 daily_unified_professional_v1 与其 flow-first guarded objective。",
        ],
    }


def run_search_pipeline(search_bounds, init_vector, t_single, worker_map=None, *, seed_offset=0, stage_label_prefix=""):
    global PROGRESS_FILE, PROGRESS_FILE_REFINE, gen_count
    result_mc = None
    result_global = None
    result_refine = None
    refine_enabled = (not args.polish) and (args.workers > 1) and (args.method in {"de", "mc_screen_de"})
    refine_maxiter_default = min(20, max(6, int(round(args.maxiter * 0.25))))
    refine_maxiter_override = int(getattr(args, "refine_maxiter", -1))
    if refine_maxiter_override == 0:
        refine_enabled = False
        refine_maxiter = 0
    elif refine_maxiter_override > 0:
        refine_enabled = (args.method in {"de", "mc_screen_de"}) and not args.polish
        refine_maxiter = refine_maxiter_override
    else:
        refine_maxiter = refine_maxiter_default
    refine_popsize = max(6, int(round(args.popsize * 0.5)))
    refine_tol = max(args.tol * 0.5, 1e-4)
    global_bounds = list(search_bounds)
    phase_seed = int(args.seed) + int(seed_offset)
    label_prefix = str(stage_label_prefix or "")

    if args.method in {"mc_only", "mc_screen_de"}:
        log_msg(f"{label_prefix}蒙特卡洛筛选样本数: {args.mc_samples}")
        mc_log_interval = max(1, min(25, args.mc_samples // 20 if args.mc_samples >= 20 else 1))
        mc_workers = max(1, args.workers)
        mc_hint = (mc_log_interval * t_single) / mc_workers
        log_msg(f"{label_prefix}预计首个筛选进度点约在 {format_elapsed_hint(mc_hint)} 后出现。")
        result_mc = run_monte_carlo_search(
            search_bounds,
            args.mc_samples,
            phase_seed,
            worker_map=worker_map,
            stage_label=f"{label_prefix}MC",
            seed_vectors=[init_vector] if init_vector is not None else None,
        )
        setattr(result_mc, "result_stage", "mc")
        if args.method != "mc_only":
            global_bounds = ensure_feasible_search_bounds(
                make_refine_bounds(result_mc.x, search_bounds, shrink=0.20, min_width=0.05),
                fallback_bounds=search_bounds,
                stage_label=f"{label_prefix}MC 精修搜索范围",
            )
            log_msg(f"{label_prefix}蒙特卡洛筛选完成，将围绕当前最优样本收缩差分进化搜索范围。")

    if args.method in {"de", "mc_screen_de"}:
        population = max(1, args.popsize * len(PARAM_BOUNDS))
        de_workers = max(1, args.workers)
        first_gen_hint = (population * t_single) / de_workers
        log_msg(f"{label_prefix}差分进化即将开始：首个进度点预计约 {format_elapsed_hint(first_gen_hint)} 后出现。")
        global_seed_vectors = []
        if result_mc is not None:
            global_seed_vectors.append(result_mc.x)
        if init_vector is not None:
            global_seed_vectors.append(init_vector)
        try:
            result_global = run_differential_evolution(
                global_bounds,
                worker_map=worker_map,
                seed=phase_seed,
                seed_vectors=global_seed_vectors or None,
            )
            setattr(result_global, "result_stage", "global")
        except Exception as exc:
            if _is_valid_optimization_result(result_mc):
                result_global = None
                log_msg(f"[WARN] {label_prefix}Global DE stage failed; fallback to MC result: {exc}")
            else:
                raise
        if refine_enabled and _is_valid_optimization_result(result_global):
            PROGRESS_FILE_REFINE = os.path.join(LOG_DIR, f"progress_refine_{RUN_ID}.csv")
            init_progress_file(PROGRESS_FILE_REFINE)
            PROGRESS_FILE = PROGRESS_FILE_REFINE
            with OBJECTIVE_STATE_LOCK:
                gen_count = 0
            refine_population = max(1, refine_popsize * len(PARAM_BOUNDS))
            refine_hint = (refine_population * t_single) / de_workers
            log_msg(f"{label_prefix}进入局部精修：首个进度点预计约 {format_elapsed_hint(refine_hint)} 后出现。")
            try:
                result_refine = run_differential_evolution(
                    ensure_feasible_search_bounds(
                        make_refine_bounds(result_global.x, global_bounds),
                        fallback_bounds=global_bounds,
                        stage_label=f"{label_prefix}局部精修搜索范围",
                    ),
                    worker_map=worker_map,
                    maxiter=refine_maxiter,
                    popsize=refine_popsize,
                    seed=phase_seed + 1,
                    tol=refine_tol,
                    polish=False,
                    seed_vectors=[result_global.x],
                )
                setattr(result_refine, "result_stage", "refine")
            except Exception as exc:
                result_refine = None
                log_msg(f"[WARN] {label_prefix}Refine stage failed; keeping the previous best result: {exc}")
            finally:
                PROGRESS_FILE = PROGRESS_FILE_MAIN
        elif refine_enabled and result_global is not None:
            log_msg(f"[WARN] {label_prefix}差分进化全局阶段未产出有效结果，已跳过局部精修。")

    stats = {
        "refine_requested": bool(refine_enabled),
        "refine_enabled": bool(refine_enabled),
        "mc": _build_result_stage_stats(
            result_mc,
            requested=bool(args.method in {"mc_only", "mc_screen_de"}),
            label=f"{label_prefix}蒙特卡洛筛选".strip(),
        ),
        "global": _build_result_stage_stats(
            result_global,
            requested=bool(args.method in {"de", "mc_screen_de"}),
            label=f"{label_prefix}差分进化全局搜索".strip(),
            polish=bool(effective_global_polish_enabled()),
        ),
        "refine": _build_result_stage_stats(
            result_refine,
            requested=bool(refine_enabled),
            label=f"{label_prefix}局部精修".strip(),
            polish=False if refine_enabled else None,
            skipped_reason=(
                "global_result_invalid"
                if (
                    refine_enabled
                    and result_refine is None
                    and result_global is not None
                    and (not _is_valid_optimization_result(result_global))
                )
                else None
            ),
        ),
    }
    result = choose_best_result(result_mc, result_global, result_refine)
    if result is None:
        raise RuntimeError(f"{label_prefix}Calibration did not produce a valid result.")
    return result, stats


def run_staged_calibration_workflow(base_bounds, init_vector, t_single, worker_map=None):
    global OPTIMIZATION_STAGE_STATS, STAGED_CALIBRATION_METADATA
    phase_seed = sanitize_initial_param_vector(init_vector if init_vector is not None else default_test_vector())
    phase_records = []
    final_result = None
    final_phase_name = ""
    final_stats = {}

    for phase_index, phase in enumerate(staged_calibration_phase_definitions(), start=1):
        phase_name = str(phase["name"])
        released = list(phase["released_parameters"])
        phase_bounds, fixed_parameters, fixed_values = build_staged_phase_bounds(base_bounds, phase_seed, released)
        seed_from_previous = phase_index > 1
        log_msg("=" * 70)
        log_msg(f"[staged_calibration_v1] Phase {phase_index}: {phase_name}")
        log_msg(f"释放参数: {', '.join(released)}")
        log_msg(f"固定参数: {', '.join(fixed_parameters)}")
        label_prefix = f"Phase {phase_index} {phase_name} | "
        result, phase_stats = run_search_pipeline(
            phase_bounds,
            phase_seed,
            t_single,
            worker_map=worker_map,
            seed_offset=phase_index * 1000,
            stage_label_prefix=label_prefix,
        )
        best_parameters = _parameter_map_from_vector(result.x)
        score_summary = _score_summary_for_vector(result.x, getattr(result, "fun", None))
        phase_record = {
            "phase_index": int(phase_index),
            "name": phase_name,
            "label": str(phase.get("label", phase_name)),
            "purpose": str(phase.get("purpose", "")),
            "released_parameters": released,
            "locked_parameters": list(fixed_parameters),
            "fixed_parameters": list(fixed_parameters),
            "fixed_parameter_values": fixed_values,
            "fixed_non_tunable_terms": [
                "glacier_temperature_correction_raster(GLACIER_DELTA_T)",
                "glacier_fraction_raster",
                "glacier_elev_raster",
            ],
            "seed_from_previous_phase": bool(seed_from_previous),
            "seed_source": "previous_phase_best" if seed_from_previous else "initial_params_or_default",
            "best_objective": (
                round(float(getattr(result, "fun", np.nan)), 6)
                if np.isfinite(float(getattr(result, "fun", np.nan)))
                else None
            ),
            "score_summary": score_summary,
            "selected_search_stage": str(getattr(result, "result_stage", "") or ""),
            "search_stats": phase_stats,
            "best_parameters": best_parameters,
            "guardrail_notes": list(phase.get("guardrail_notes", []) or []),
        }
        phase_records.append(phase_record)
        phase_seed = np.asarray(result.x, dtype=np.float64).copy()
        final_result = result
        final_phase_name = phase_name
        final_stats = phase_stats
        log_msg(
            f"[staged_calibration_v1] Phase {phase_index} 完成：目标值={phase_record['best_objective']} "
            f"NSE_cal={score_summary.get('nse_cal')} PBIAS_cal={score_summary.get('pbias_cal')}"
        )

    if final_result is None:
        raise RuntimeError("staged_calibration_v1 did not produce a valid result.")
    STAGED_CALIBRATION_METADATA = build_staged_calibration_metadata(phase_records, final_phase_name)
    OPTIMIZATION_STAGE_STATS = final_stats
    setattr(final_result, "calibration_workflow", CALIBRATION_WORKFLOW_STAGED)
    setattr(final_result, "calibration_phases", phase_records)
    setattr(final_result, "final_selected_phase", final_phase_name)
    setattr(final_result, "final_parameters_from_phase", final_phase_name)
    return final_result


def run_monte_carlo_search(bounds, samples, seed, worker_map=None, stage_label="MC", seed_vectors=None):
    global PROGRESS_FILE
    bounds = validate_search_bounds(list(bounds))
    if samples <= 0:
        raise ValueError("mc_samples 必须为正整数。")
    seed_candidates = normalize_seed_vectors(bounds, seed_vectors)
    rng = np.random.default_rng(seed)
    batch_size = max(1, min(samples, args.workers * 4 if worker_map is not None else 32))
    log_interval = max(1, min(25, samples // 20 if samples >= 20 else 1))
    best_x = None
    best_obj = np.inf
    best_nse_cal = float("nan")
    best_nse_val = float("nan")
    processed = 0
    valid_processed = 0
    invalid_processed = 0
    max_attempts = max(samples, samples * 12) + len(seed_candidates)

    mc_progress = os.path.join(LOG_DIR, f"progress_mc_{RUN_ID}.csv")
    previous_progress = PROGRESS_FILE
    PROGRESS_FILE = mc_progress
    init_progress_file(PROGRESS_FILE)
    gen_mark = 0

    try:
        if seed_candidates:
            log_msg(f"{stage_label} 已注入 {len(seed_candidates)} 组初值参数作为优先样本。")
            if worker_map is not None and len(seed_candidates) > 1:
                seed_objs = list(worker_map(objective, seed_candidates))
            else:
                seed_objs = [objective(x) for x in seed_candidates]
            for seed_idx, (x, obj) in enumerate(zip(seed_candidates, seed_objs), start=1):
                processed += 1
                if np.isfinite(obj) and obj < BAD_OBJ:
                    valid_processed += 1
                else:
                    invalid_processed += 1
                    continue
                if obj < best_obj:
                    best_obj = float(obj)
                    best_x = np.asarray(x, dtype=np.float64).copy()
                    best_nse_cal, best_nse_val = summarize_candidate(best_x)
                should_log = (
                    (valid_processed % log_interval == 0)
                    or (valid_processed >= samples)
                    or (seed_idx == len(seed_candidates))
                )
                if should_log and best_x is not None:
                    progress_count = min(valid_processed, samples)
                    gen_mark = max(gen_mark, progress_count)
                    append_progress(gen_mark, best_nse_cal, best_nse_val, best_obj, 0.0)
                    log_msg(
                        f"[{stage_label} 初值样本 {seed_idx}/{len(seed_candidates)}] "
                        f"当前最优率定NSE={best_nse_cal:.4f} 验证NSE={best_nse_val:.4f} 目标值={best_obj:.4f}"
                    )

                if valid_processed >= samples:
                    break

        while valid_processed < samples and processed < max_attempts:
            batch_n = min(batch_size, max_attempts - processed)
            batch = []
            for _ in range(batch_n):
                x = sample_feasible_candidate(bounds, rng)
                batch.append(x)
            if worker_map is not None and batch_n > 1:
                objs = list(worker_map(objective, batch))
            else:
                objs = [objective(x) for x in batch]

            for x, obj in zip(batch, objs):
                processed += 1
                if np.isfinite(obj) and obj < BAD_OBJ:
                    valid_processed += 1
                else:
                    invalid_processed += 1
                    continue
                if obj < best_obj:
                    best_obj = float(obj)
                    best_x = np.asarray(x, dtype=np.float64).copy()
                    best_nse_cal, best_nse_val = summarize_candidate(best_x)
                should_log = (valid_processed % log_interval == 0) or (valid_processed >= samples)
                if should_log and best_x is not None:
                    progress_count = min(valid_processed, samples)
                    gen_mark = max(gen_mark, progress_count)
                    append_progress(gen_mark, best_nse_cal, best_nse_val, best_obj, 0.0)
                    log_msg(
                        f"[{stage_label} 有效样本 {progress_count}/{samples}] "
                        f"当前最优 率定期NSE={best_nse_cal:.4f} 验证期NSE={best_nse_val:.4f} 目标值={best_obj:.4f}"
                    )
    except Exception as exc:
        if best_x is None:
            raise
        if (not np.isfinite(best_nse_cal)) or (not np.isfinite(best_nse_val)):
            best_nse_cal, best_nse_val = summarize_candidate(best_x)
        log_msg(f"[WARN] {stage_label} stage interrupted after finding a valid candidate; preserving current best sample: {exc}")
        return SimpleNamespace(
            x=np.asarray(best_x, dtype=np.float64),
            fun=float(best_obj),
            nfev=int(processed),
            nit=0,
            success=False,
            message=f"{stage_label} partial result preserved after exception: {exc}",
            valid_samples=int(valid_processed),
            invalid_samples=int(invalid_processed),
            processed_samples=int(processed),
            target_samples=int(samples),
            seed_samples=int(len(seed_candidates)),
            progress_points=int(gen_mark or valid_processed),
        )
    finally:
        PROGRESS_FILE = previous_progress
    if valid_processed < samples and best_x is not None:
        log_msg(
            f"[WARN] {stage_label} 仅获得 {valid_processed}/{samples} 个有效样本，"
            f"另有 {invalid_processed} 个无效样本；将采用当前最优样本继续。"
        )
    if best_x is None:
        fallback_vectors = []
        init_file = str(getattr(args, "init_params_file", "") or "").strip()
        if init_file:
            try:
                fallback_vectors.append(("初始参数集", np.asarray(load_initial_param_vector(init_file), dtype=np.float64)))
            except Exception as exc:
                log_msg(f"[WARN] 初始参数集回退失败：{exc}")
        try:
            fallback_vectors.append(("默认测试参数", np.asarray(default_test_vector(), dtype=np.float64)))
        except Exception:
            pass
        for label, candidate in fallback_vectors:
            fallback_obj = objective(candidate)
            processed += 1
            if not np.isfinite(fallback_obj) or fallback_obj >= BAD_OBJ:
                invalid_processed += 1
                continue
            best_x = np.asarray(candidate, dtype=np.float64).copy()
            best_obj = float(fallback_obj)
            best_nse_cal, best_nse_val = summarize_candidate(best_x)
            valid_processed = max(valid_processed, 1)
            gen_mark = max(gen_mark, valid_processed)
            log_msg(f"[WARN] {stage_label} 未找到有效随机样本，已回退到{label}继续。")
            break
    if best_x is None or (not np.isfinite(best_obj)) or best_obj >= BAD_OBJ:
        raise RuntimeError(f"蒙特卡洛筛选未找到有效参数集（已尝试 {processed} 次，其中无效样本 {invalid_processed} 次）。")
    return SimpleNamespace(
        x=np.asarray(best_x, dtype=np.float64),
        fun=float(best_obj),
        nfev=int(processed),
        nit=0,
        success=True,
        message=f"{stage_label} completed",
        valid_samples=int(valid_processed),
        invalid_samples=int(invalid_processed),
        processed_samples=int(processed),
        target_samples=int(samples),
        seed_samples=int(len(seed_candidates)),
        progress_points=int(gen_mark or valid_processed),
    )


def run_differential_evolution(bounds, worker_map=None, maxiter=None, popsize=None, seed=None, tol=None, polish=None, seed_vectors=None):
    bounds = validate_search_bounds(list(bounds))
    use_workers = worker_map if worker_map is not None else 1
    updating = "deferred" if worker_map is not None else "immediate"
    objective_fn = objective if worker_map is not None else objective_with_logging
    population_seed = args.seed if seed is None else seed
    effective_popsize = args.popsize if popsize is None else popsize
    effective_polish = effective_global_polish_enabled() if polish is None else bool(polish)
    init_population = build_de_initial_population(bounds, effective_popsize, population_seed, seed_vectors=seed_vectors)
    return differential_evolution(
        objective_fn,
        list(bounds),
        strategy="best1bin",
        maxiter=args.maxiter if maxiter is None else maxiter,
        popsize=effective_popsize,
        seed=args.seed if seed is None else seed,
        tol=args.tol if tol is None else tol,
        disp=True,
        polish=effective_polish,
        callback=de_callback,
        workers=use_workers,
        updating=updating,
        init=init_population,
    )


def choose_best_result(*results):
    candidates = []
    for item in results:
        if not _is_valid_optimization_result(item):
            continue
        candidates.append(item)
    if not candidates:
        return None
    return min(candidates, key=lambda item: float(getattr(item, "fun", np.inf)))


def effective_global_polish_enabled():
    if bool(getattr(args, "polish", False)):
        return True
    try:
        workers = int(getattr(args, "workers", 1) or 1)
    except Exception:
        workers = 1
    method = str(getattr(args, "method", "") or "").strip().lower()
    return workers <= 1 and method in {"de", "mc_screen_de"}


def de_callback(xk, convergence):
    current_gen = _increment_gen_count()
    try:
        sim = run_simulation(xk, mode=objective_simulation_mode())
        q_score_series, _ = scoring_series(sim)
        obj, terms = compute_objective_terms(compute_metrics(q_score_series), sim)
        _update_best_state(obj, terms, xk)
        nse_cal = float(terms["nse_cal"]) if terms else float("nan")
        nse_val = float(terms["nse_val"]) if terms else float("nan")
        append_progress(current_gen, float(nse_cal), float(nse_val), float(obj), float(convergence))
        stage = "局部精修" if (PROGRESS_FILE_REFINE and PROGRESS_FILE == PROGRESS_FILE_REFINE) else "全局搜索"
        log_line = (
            f"[{stage} 第 {current_gen} 代] 率定期NSE={nse_cal:.4f} "
            f"验证期NSE={nse_val:.4f} 目标值={obj:.4f} "
        )
        if terms and current_objective_mode() == FLOOD_EVENT_OBJECTIVE_FAMILY:
            log_line += (
                f"事件有效场次={int(terms.get('valid_objective_event_count', 0) or 0)}/"
                f"{int(terms.get('objective_event_count', 0) or 0)} "
            )
        elif terms and current_objective_mode() == OBJECTIVE_FAMILY_DAILY:
            log_line += f"logNSE_cal={terms['log_nse_cal']:.4f} PBIAS_cal={terms['pbias_cal']:+.2f}% "
            frac_info = (
                dict(terms.get("diagnostics", {}).get("glacier_fraction_report", {}) or {})
                if isinstance(terms.get("diagnostics"), dict)
                else {}
            )
            f_ice_val = frac_info.get("f_ice")
            if f_ice_val is not None and np.isfinite(float(f_ice_val)):
                log_line += f"冰川占比={float(f_ice_val) * 100:.1f}% "
        log_line += f"收敛指标={convergence:.3e}"
        log_msg(log_line)
    except Exception as exc:
        log_msg(f"[第 {current_gen} 代] 回调记录失败：{exc}")
    return False


def clean_metrics_dict(metrics):
    if metrics is None:
        return None

    cleaned = {}
    for key, value in metrics.items():
        if isinstance(value, (np.floating, float)):
            cleaned[key] = round(float(value), 6) if np.isfinite(value) else None
        elif isinstance(value, (np.integer, int)):
            cleaned[key] = int(value)
        else:
            cleaned[key] = value
    return cleaned


def current_calibration_profile():
    profile = str(CALIBRATION_PROFILE or "").strip().lower()
    if profile in {"daily", "hourly"}:
        return profile
    return "hourly" if float(TIME_STEP_HOURS) <= 1.5 else "daily"


def current_objective_mode():
    raw_selected = str(OBJECTIVE_MODE_SELECTED or "").strip().lower()
    raw_profile_type = (
        str(OBJECTIVE_PROFILE.get("type", "") or "").strip().lower()
        if isinstance(OBJECTIVE_PROFILE, dict)
        else ""
    )
    if (
        flood_event_objective_enabled()
        or raw_selected in {FLOOD_EVENT_OBJECTIVE_FAMILY, "flood_event", "event_objective"}
        or raw_profile_type in {FLOOD_EVENT_OBJECTIVE_FAMILY, "flood_event", "event_objective"}
    ):
        return FLOOD_EVENT_OBJECTIVE_FAMILY
    profile_name = current_calibration_profile()
    if profile_name == "daily":
        return OBJECTIVE_FAMILY_DAILY
    raw = ""
    if isinstance(OBJECTIVE_PROFILE, dict):
        raw = str(OBJECTIVE_PROFILE.get("type", "") or "").strip().lower()
    if not raw:
        raw = str(OBJECTIVE_MODE_SELECTED or "").strip().lower()
    if raw in {"single_objective_nse", "single", "single_nse", "nse"}:
        return "single_objective_nse"
    if raw in {FLOOD_EVENT_OBJECTIVE_FAMILY, "flood_event", "event_objective"}:
        return FLOOD_EVENT_OBJECTIVE_FAMILY
    return "single_objective_nse"


def objective_simulation_mode():
    if current_objective_mode() == FLOOD_EVENT_OBJECTIVE_FAMILY:
        return "full"
    if current_objective_mode() == OBJECTIVE_FAMILY_DAILY:
        return "full"
    return "objective_total"


def compute_objective_terms(metrics, sim=None):
    nse_cal = float(metrics.get("nse_cal", float("nan")))
    if current_objective_mode() == FLOOD_EVENT_OBJECTIVE_FAMILY:
        return compute_flood_event_objective_terms(metrics, sim or {})
    if current_objective_mode() == OBJECTIVE_FAMILY_DAILY:
        translated = dict(sim or {})
        translated["glacier_fraction_window"] = (
            [float(GLACIER_FRAC_WINDOW[0]), float(GLACIER_FRAC_WINDOW[1])]
            if GLACIER_FRAC_WINDOW is not None
            else None
        )
        evaluation = daily_unified_objective.evaluate_daily_unified_objective(
            translated,
            metrics,
            bad_obj=BAD_OBJ,
        )
        return float(evaluation.get("objective_value", BAD_OBJ)), evaluation
    if not np.isfinite(nse_cal):
        return BAD_OBJ, None

    nse_val = float(metrics.get("nse_val", float("nan")))
    log_nse_cal = float(metrics.get("log_nse_cal", float("nan")))
    log_nse_val = float(metrics.get("log_nse_val", float("nan")))
    pbias_cal = float(metrics.get("pbias_cal", float("nan")))
    pbias_val = float(metrics.get("pbias_val", float("nan")))
    obj = 1.0 - nse_cal
    return float(obj), {
        "objective_family": "single_objective_nse",
        "objective_value": float(obj),
        "nse_cal": nse_cal,
        "nse_val": nse_val,
        "log_nse_cal": log_nse_cal if np.isfinite(log_nse_cal) else nse_cal,
        "log_nse_val": log_nse_val,
        "pbias_cal": pbias_cal,
        "pbias_val": pbias_val,
    }


def current_parameter_profile():
    if isinstance(PARAMETER_PROFILE, dict):
        profile = dict(PARAMETER_PROFILE)
        bounds = profile.get("bounds")
        if isinstance(bounds, dict) and bounds:
            return profile
    profile_name = current_calibration_profile()
    bounds_profile = str(PARAM_BOUNDS_PROFILE_SELECTED or DEFAULT_PARAM_BOUNDS_PROFILE)
    return {
        "name": profile_name,
        "label": "小时尺度率定" if profile_name == "hourly" else "日尺度率定",
        "bounds_profile": bounds_profile,
        "bounds_profile_label": PARAM_BOUNDS_PROFILE_LABELS.get(bounds_profile, bounds_profile),
        "notes": [
            PARAM_BOUNDS_PROFILE_NOTES.get(bounds_profile, "参数边界取自当前核心运行配置。"),
            "参数边界取自当前核心运行配置。",
        ],
        "bounds": {
            name: [float(lo), float(hi)]
            for name, (lo, hi) in zip(param_names, PARAM_BOUNDS)
        },
    }


def build_daily_unified_objective_meta(profile_name=None):
    profile_name = str(profile_name or current_calibration_profile()).strip().lower()
    if profile_name not in {"daily", "hourly"}:
        profile_name = current_calibration_profile()
    profile_label = "统一日尺度率定" if profile_name == "daily" else "小时尺度率定"
    return {
        "type": OBJECTIVE_FAMILY_DAILY,
        "profile": profile_name,
        "label": profile_label,
        "summary": "唯一正式主线：flow-first guarded objective；flow 与 flow_guard 优先，非 flow 项封顶排序，diagnostics 只解释不计分。",
        "formula": "flow + flow_guard + min(seasonality + process_signatures + cryo_consistency + external_evidence, nonflow_cap) + ice_dominance_guard",
        "weights": {
            "flow": {
                "nse_calibration": 1.0,
                "log_nse_calibration": 0.35,
                "nse_validation": 0.35,
                "log_nse_validation": 0.1225,
                "pbias_calibration": 0.10,
                "pbias_validation": 0.10,
            },
            "flow_guard": {
                "nse_calibration_floor": 0.60,
                "nse_validation_floor": 0.60,
                "kge_calibration_floor": 0.65,
                "kge_validation_floor": 0.65,
                "abs_pbias_calibration_max": 15.0,
                "abs_pbias_validation_max": 15.0,
            },
            "seasonality": {
                "warm_fraction": 0.10,
                "djf_fraction": 0.05,
            },
            "process_signatures": {
                "swr": 0.20,
                "rise_timing": 0.06,
                "rise_shape": 0.08,
                "peak_timing": 0.08,
                "peak_magnitude_bias": 0.08,
                "flow_centroid_date": 0.06,
                "recession_slope": 0.08,
            },
            "cryo_consistency": {
                "winter_ice_ratio": 0.10,
                "snow_to_ice_centroid_lag": 0.08,
                "peak_source_guard": 0.10,
                "recession_takeover_diagnostic": "diagnostic_only",
            },
            "external_evidence": {
                "gm": "inactive",
                "sca": 0.10,
                "geodetic_mb": 0.10,
            },
            "objective_controls": {
                "nonflow_cap": 0.35,
                "ice_dominance_guard_weight": 3.0,
                "ice_dominance_guard_mode": "basin_adaptive",
                "binary_legacy_upper": "min(0.45, max(0.30, base_upper * 1.20))",
                "binary_legacy_tolerance": 0.05,
                "fractional_subgrid_upper": "min(0.85, max(0.20, base_upper * 1.25))",
                "fractional_subgrid_tolerance": "max(0.05, 0.15 * upper)",
                "external_evidence_behavior": "controlled_by_external_evidence",
            },
        },
        "diagnostic_only_constraints": {
            "glacier_fraction_window": True,
        },
        "notes": [
            "flow 主体项沿用现有成熟 NSE / logNSE / PBIAS 骨架，并记录 KGE 供 flow_guard 使用。",
            "flow_guard 为连续软惩罚；数据不足的项跳过，不直接 hard fail。",
            "季节性、水文过程特征和冰雪过程一致性作为辅助评价项；外部冰融水参考约束默认不启用。",
            "ice_dominance_guard 是宽松过程保护项，防止无外部证据时 q_ice 极端支配。",
            "glacier_fraction_window 固定退到 diagnostics.glacier_fraction_report，不进入默认总分。",
            "hard checks 固定先于总分执行，并输出合同约定的失败码与结构。",
        ],
    }


def build_flood_event_objective_meta(profile_name=None):
    profile_name = str(profile_name or current_calibration_profile()).strip().lower()
    if profile_name not in {"daily", "hourly"}:
        profile_name = current_calibration_profile()
    parsed = parse_flood_event_config()
    event_runtime = event_runtime_requested(parsed.get("raw_config", {}))
    return {
        "type": FLOOD_EVENT_OBJECTIVE_FAMILY,
        "profile": profile_name,
        "label": "事件洪水率定目标函数",
        "summary": (
            "按洪水事件窗口组织资料，每场事件独立预热并合成洪峰、峰现时间、洪量、退水和高流量过程效率目标。"
            if event_runtime
            else "连续运行模型，只在配置洪水事件窗口内合成洪峰、峰现时间、洪量、退水和高流量过程效率目标。"
        ),
        "formula": "weighted_mean(|peak_error|, |peak_time_error|, |volume_error|, recession_error, 1 - high_flow_skill)",
        "weights": parsed.get("weights", {}).get("raw", dict(DEFAULT_FLOOD_EVENT_WEIGHTS)),
        "diagnostic_only_constraints": {
            "continuous_state_evolution": not event_runtime,
            "event_independent_warmup": bool(event_runtime),
            "non_event_period_state_update_only": not event_runtime,
        },
        "notes": (
            [
                "事件窗口资料模式只读取各场事件运行窗口内的强迫资料，事件之间允许资料间断。",
                "每场事件从统一初始状态进入自身预热段，事件之间不传递土壤、水库和汇流状态。",
                "验证类事件可用于结果复核，默认不参与事件目标函数。",
            ]
            if event_runtime
            else [
                "气象驱动和状态演化仍按完整连续时段运行，事件窗口只决定目标函数取样范围。",
                "未显式启用事件目标函数时，洪水事件评价只作为结果诊断输出。",
                "验证类事件可用于结果复核，默认不参与事件目标函数。",
            ]
        ),
    }


def build_single_objective_meta(profile_name=None):
    profile_name = str(profile_name or current_calibration_profile()).strip().lower()
    if profile_name not in {"daily", "hourly"}:
        profile_name = current_calibration_profile()
    profile_label = "小时尺度率定" if profile_name == "hourly" else "日尺度率定"
    return {
        "type": "single_objective_nse",
        "profile": profile_name,
        "label": profile_label,
        "summary": "单目标：1 - 率定期 NSE",
        "formula": "1 - NSE(calibration_period)",
        "notes": [
            "日尺度率定直接优化 1 - NSE(calibration_period)。"
            if profile_name == "daily"
            else "小时尺度率定直接优化 1 - NSE(calibration_period)。"
        ],
    }


def current_objective_profile():
    objective_mode = current_objective_mode()
    profile_name = current_calibration_profile()
    base_profile = (
        build_flood_event_objective_meta(profile_name)
        if objective_mode == FLOOD_EVENT_OBJECTIVE_FAMILY
        else
        build_daily_unified_objective_meta(profile_name)
        if objective_mode == OBJECTIVE_FAMILY_DAILY
        else build_single_objective_meta(profile_name)
    )
    if objective_mode == FLOOD_EVENT_OBJECTIVE_FAMILY:
        return base_profile
    if isinstance(OBJECTIVE_PROFILE, dict):
        profile = dict(base_profile)
        profile.update(dict(OBJECTIVE_PROFILE))
        profile["type"] = objective_mode
        profile["profile"] = profile_name
        profile.setdefault("label", base_profile.get("label"))
        return profile
    return base_profile


def save_results(result):
    elapsed_total = time.time() - start_time
    selected_stage = str(getattr(result, "result_stage", "") or "").strip().lower()
    selected_stage_evaluations = _result_stat_int(result, "nfev")
    selected_stage_generations = _result_stat_int(result, "nit") if selected_stage in {"global", "refine"} else 0
    selected_stage_progress_points = _result_stat_int(result, "progress_points")
    stage_stats = {}
    for key, value in (
        ("mc", OPTIMIZATION_STAGE_STATS.get("mc")),
        ("global", OPTIMIZATION_STAGE_STATS.get("global")),
        ("refine", OPTIMIZATION_STAGE_STATS.get("refine")),
    ):
        if not value:
            continue
        if isinstance(value, dict):
            stage_info = dict(value)
            if not stage_info.get("requested") and not stage_info.get("executed"):
                continue
            stage_info["selected"] = key == selected_stage
            stage_stats[key] = stage_info
        else:
            stage_stats[key] = value
    total_generations = sum(
        int(dict(value).get("nit", 0) or 0)
        for value in stage_stats.values()
        if isinstance(value, dict) and str(dict(value).get("stage", "") or "").strip().lower() in {"global", "refine"}
    )
    total_progress_points = sum(
        int(dict(value).get("progress_points", 0) or 0)
        for value in stage_stats.values()
        if isinstance(value, dict)
    )
    total_evaluations = max(int(_snapshot_objective_state()[0]), selected_stage_evaluations)
    sim = run_simulation(result.x)
    q_sim = sim["q_total"]
    q_local = sim["q_local"]
    q_boundary = sim["q_boundary"]
    q_rain = sim["q_rain"]
    q_snow = sim["q_snow"]
    q_ice = sim["q_ice"]
    q_ice_raw = sim["q_ice_raw"]
    q_ice_ref = sim["q_ice_reference"]
    q_ice_ref_raw = sim["q_ice_reference_raw"]
    q_score_series, q_score_basis = scoring_series(sim)
    metrics = compute_metrics(q_score_series)
    objective_value, objective_evaluation = compute_objective_terms(metrics, sim)

    q_sim_calib = q_sim[CALIB_MASK]
    q_sim_valid = q_sim[VALID_MASK]
    rain_calib = q_rain[CALIB_MASK]
    snow_calib = q_snow[CALIB_MASK]
    ice_calib = q_ice[CALIB_MASK]
    rain_valid = q_rain[VALID_MASK]
    snow_valid = q_snow[VALID_MASK]
    ice_valid = q_ice[VALID_MASK]
    glacier_cmp_routed = compare_series(q_ice_ref, q_ice)
    glacier_cmp_raw = compare_series(q_ice_ref_raw, q_ice_raw)
    glacier_physical_checks = compute_glacier_physical_checks(q_ice_ref, q_ice)
    if RELIABILITY_FLAG == "degraded_missing_glacier_elev":
        reliability_notes = ["glacier_elev 缺失，0.1° 冰川子格温度递减未启用；冰川链条物理一致性降级。"]
    elif not bool(sim.get("glacier_enabled", False)):
        reliability_notes = ["当前未启用冰川模块。"]
    else:
        reliability_notes = []

    den_q_cal = np.nansum(q_sim_calib)
    den_q_val = np.nansum(q_sim_valid)
    rain_frac_cal = float(np.nansum(rain_calib) / den_q_cal) if den_q_cal > 0 else 0.0
    snow_frac_cal = float(np.nansum(snow_calib) / den_q_cal) if den_q_cal > 0 else 0.0
    ice_frac_cal = float(np.nansum(ice_calib) / den_q_cal) if den_q_cal > 0 else 0.0
    rain_frac_val = float(np.nansum(rain_valid) / den_q_val) if den_q_val > 0 else 0.0
    snow_frac_val = float(np.nansum(snow_valid) / den_q_val) if den_q_val > 0 else 0.0
    ice_frac_val = float(np.nansum(ice_valid) / den_q_val) if den_q_val > 0 else 0.0

    run_dir = os.path.join(RUNS_DIR, f"hbv_cryo_{args.prec_source}_{args.glacier_mode}_{RUN_ID}")
    os.makedirs(run_dir, exist_ok=True)
    flood_event_evaluation = compute_flood_event_evaluation(
        SIM_DATES,
        Q_OBS_FULL,
        q_score_series if q_score_series is not None else q_sim,
        FLOOD_EVENT_CONFIG,
        evaluation_basis=q_score_basis,
    )
    flood_event_file = write_flood_event_outputs(run_dir, flood_event_evaluation)
    if flood_event_file:
        flood_event_evaluation["output_file"] = flood_event_file

    export_start = max(int(WARMUP_STEPS or 0), 0)
    q_sim_export = q_sim[export_start:]
    q_local_export = q_local[export_start:]
    q_boundary_export = q_boundary[export_start:]
    q_rain_export = q_rain[export_start:]
    q_snow_export = q_snow[export_start:]
    q_ice_export = q_ice[export_start:]
    q_ice_raw_export = q_ice_raw[export_start:]
    q_obs_export = Q_OBS_FULL[export_start:] if Q_OBS_FULL is not None else np.full(len(q_sim_export), np.nan, dtype=np.float64)
    date_export = SIM_DATES[export_start:] if SIM_DATES is not None else np.arange(len(q_sim_export))
    min_len = min(len(q_sim_export), len(q_obs_export), len(date_export))
    q_ice_ref_export = q_ice_ref[export_start:] if q_ice_ref is not None else np.full(len(q_sim_export), np.nan, dtype=np.float64)
    q_ice_ref_raw_export = q_ice_ref_raw[export_start:] if q_ice_ref_raw is not None else np.full(len(q_sim_export), np.nan, dtype=np.float64)
    q_ice_ref_csv = q_ice_ref_export[:min_len]
    q_ice_ref_raw_csv = q_ice_ref_raw_export[:min_len]
    df = pd.DataFrame({
        "date": date_export[:min_len],
        "q_sim": q_sim_export[:min_len],
        "q_sim_model": q_local_export[:min_len],
        "q_local": q_local_export[:min_len],
        "q_boundary_inflow": q_boundary_export[:min_len],
        "q_obs": q_obs_export[:min_len],
        "q_rain": q_rain_export[:min_len],
        "q_snow": q_snow_export[:min_len],
        "q_ice": q_ice_export[:min_len],
        "q_ice_raw": q_ice_raw_export[:min_len],
        "q_ice_reference": q_ice_ref_csv,
        "q_ice_reference_raw": q_ice_ref_raw_csv,
    })
    df.to_csv(os.path.join(run_dir, "simulation.csv"), index=False)

    snapshot_file_name = "state_snapshot.npz"
    state_snapshot_path = os.path.join(run_dir, snapshot_file_name)
    state_snapshot_saved = False
    state_snapshot_error = None
    state_snapshot_meta = {
        "schema": "per_cell_branch_states_v1",
        "snapshot_mode": glacier_processing_mode(),
        "branch_count": 0,
        "branches": [],
        "cell_count": int(len(VALID_CELLS)) if VALID_CELLS is not None else 0,
        "time_steps": int(len(SIM_DATES)) if SIM_DATES is not None else 0,
    }
    if event_runtime_independent_active():
        state_snapshot_error = "事件窗口独立运行不形成连续末状态，不作为连续状态预报起点。"
        state_snapshot_meta.update(
            {
                "hot_start_supported": False,
                "snapshot_time": "",
                "routing_state_available": False,
                "event_runtime_independent": True,
            }
        )
    else:
        try:
            snapshot_arrays, snapshot_meta = compute_state_snapshot(result.x)
            append_routing_state_to_snapshot(snapshot_arrays, sim)
            snapshot_meta["routing_state_available"] = True
            state_snapshot_meta.update(snapshot_meta)
            np.savez_compressed(state_snapshot_path, **snapshot_arrays)
            state_snapshot_saved = True
        except Exception as exc:
            state_snapshot_error = str(exc)

    profile_name = current_calibration_profile()
    requested_objective_mode = str(REQUESTED_OBJECTIVE_MODE or "").strip().lower() or "auto"
    objective_mode = current_objective_mode()
    parameter_profile = current_parameter_profile()
    objective_profile = current_objective_profile()
    workflow_metadata = {}
    result_workflow = str(
        getattr(result, "calibration_workflow", CALIBRATION_WORKFLOW_SELECTED) or CALIBRATION_WORKFLOW_SINGLE
    ).strip().lower()
    if result_workflow == CALIBRATION_WORKFLOW_STAGED:
        workflow_metadata = dict(STAGED_CALIBRATION_METADATA or {})
        if not workflow_metadata:
            workflow_metadata = build_staged_calibration_metadata(
                list(getattr(result, "calibration_phases", []) or []),
                str(getattr(result, "final_selected_phase", "") or ""),
            )
    result_workflow_status = calibration_workflow_status(result_workflow)
    objective_meta = {
        "obs_mode": OBS_MODE_APPLIED,
        "cfmax_zone_threshold_m": float(CFMAX_ZONE_ELEV),
        "glacier_physical_check_active": bool(glacier_physical_checks.get("available", False)),
    }
    for key in (
        "type",
        "profile",
        "label",
        "summary",
        "formula",
        "weights",
        "diagnostic_only_constraints",
        "notes",
    ):
        if key in objective_profile:
            objective_meta[key] = objective_profile[key]
    glacier_mask_summary = None
    if GLACIER_MASK_PATH:
        glacier_summary_path = os.path.join(os.path.dirname(GLACIER_MASK_PATH), "glacier_mask_summary.json")
        if os.path.exists(glacier_summary_path):
            try:
                with open(glacier_summary_path, "r", encoding="utf-8") as fh:
                    glacier_mask_summary = json.load(fh)
            except Exception:
                glacier_mask_summary = None

    metadata = {
        "run_id": RUN_ID,
        "run_time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "elapsed_seconds": round(elapsed_total, 1),
        "evaluations": total_evaluations,
        "reliability_flag": RELIABILITY_FLAG,
        "reliability_notes": (
            ["glacier_elev 缺失，0.1° 冰川子格未做温度递减修正，冰川融水可能系统性偏高 15–30%。"]
            if RELIABILITY_FLAG == "degraded_missing_glacier_elev"
            else ["所有物理修正已启用"]
        ),
        "data_sources": {
            "prec_source": args.prec_source,
            "runtime_prec_source": args.prec_source,
            "configured_precip_source": args.prec_source,
            "prec_dir": PREC_DIR,
            "temp_dir": TEMP_DIR,
            "evap_dir": EVAP_DIR,
            "glacier_melt_dir": GLACIER_MELT_DIR,
            "glacier_mode": args.glacier_mode,
            "glacier_model_mode": sim.get("glacier_model_mode", glacier_processing_mode()),
            "glacier_mask": GLACIER_MASK_PATH,
            "glacier_fraction": GLACIER_FRACTION_PATH,
            "glacier_elev": GLACIER_ELEV_PATH,
            "obs_file": OBS_FILE,
        },
        "data_cache": DATA_LOAD_SUMMARY,
        "optional_modules": {
            "glacier": {
                "enabled": bool(sim["glacier_enabled"]),
                "model_mode": sim.get("glacier_model_mode", glacier_processing_mode()),
                "mask_exists": bool(os.path.exists(GLACIER_MASK_PATH)),
                "fraction_exists": bool(os.path.exists(GLACIER_FRACTION_PATH)),
                "elev_exists": bool(os.path.exists(GLACIER_ELEV_PATH)),
                "elev_status": GLACIER_ELEV_STATUS,
                "reference_available": bool(sim.get("glacier_reference_available", GLACIER_MELT_REF_RAW is not None)),
                "reference_used_in_objective": bool(sim.get("glacier_reference_used_in_objective", False)),
                "reference_role": (
                    "soft_constraint_external_evidence_gm"
                    if bool(sim.get("glacier_reference_used_in_objective", False))
                    else (
                        "future_optional_diagnostic_only"
                        if bool(sim.get("glacier_reference_available", GLACIER_MELT_REF_RAW is not None))
                        else "not_available"
                    )
                ),
                "mask_summary": glacier_mask_summary,
                "delta_t_min": float(np.nanmin(GLACIER_DELTA_T)) if GLACIER_DELTA_T is not None and GLACIER_DELTA_T.size else 0.0,
                "delta_t_max": float(np.nanmax(GLACIER_DELTA_T)) if GLACIER_DELTA_T is not None and GLACIER_DELTA_T.size else 0.0,
                "delta_t_mean_nonzero": (
                    float(np.nanmean(GLACIER_DELTA_T[GLACIER_DELTA_T != 0]))
                    if GLACIER_DELTA_T is not None and np.any(GLACIER_DELTA_T != 0)
                    else 0.0
                ),
            },
            "boundary_inflow": {
                "enabled": bool(sim["boundary_enabled"]),
                "file": BOUNDARY_INFLOW_FILE if BOUNDARY_INFLOW_FILE else None,
                "gap_fill": BOUNDARY_INFLOW_GAP_FILL,
            },
        },
        "boundary_condition": {
            "enabled": bool(sim["boundary_enabled"]),
            "boundary_inflow_file": BOUNDARY_INFLOW_FILE if BOUNDARY_INFLOW_FILE else None,
            "date_field": BOUNDARY_INFLOW_DATE_FIELD,
            "flow_field": BOUNDARY_INFLOW_FLOW_FIELD,
            "gap_fill": BOUNDARY_INFLOW_GAP_FILL,
        },
        "time_config": {
            "time_step_hours": float(TIME_STEP_HOURS),
            "time_step_days": float(time_step_days()),
            "warmup_start": WARMUP_START,
            "warmup_end": WARMUP_END,
            "calib_start": CALIB_START,
            "calib_end": CALIB_END,
            "valid_start": VALID_START,
            "valid_end": VALID_END,
            "warmup_steps": int(WARMUP_STEPS),
            "event_runtime": dict(EVENT_RUNTIME_META or {}),
        },
        "initial_state": {
            "mode": "uniform_vector",
            "event_initial_state_policy": EVENT_INITIAL_STATE_POLICY,
            "vector": {
                "SP": round(float(INIT_ST[0]), 6),
                "SM": round(float(INIT_ST[1]), 6),
                "UZ": round(float(INIT_ST[2]), 6),
                "LZ": round(float(INIT_ST[3]), 6),
                "WC": round(float(INIT_ST[4]), 6),
            },
            "state_snapshot_available": bool(state_snapshot_saved),
            "state_snapshot_file": snapshot_file_name if state_snapshot_saved else None,
            "state_snapshot_schema": state_snapshot_meta.get("schema"),
            "state_snapshot_mode": state_snapshot_meta.get("snapshot_mode"),
            "state_snapshot_branches": list(state_snapshot_meta.get("branches", [])),
            "state_snapshot_branch_count": int(state_snapshot_meta.get("branch_count", 0) or 0),
            "state_snapshot_cell_count": int(state_snapshot_meta.get("cell_count", 0) or 0),
            "state_snapshot_time_steps": int(state_snapshot_meta.get("time_steps", 0) or 0),
            "state_snapshot_time": state_snapshot_meta.get("snapshot_time", ""),
            "state_snapshot_routing_state": bool(state_snapshot_meta.get("routing_state_available", False)),
            "state_snapshot_error": state_snapshot_error,
            "hot_start_supported": bool(state_snapshot_saved),
            "hot_start_enabled": bool(state_snapshot_saved),
            "notes": (
                [
                    "事件窗口资料模式按场独立预热，不把事件之间的大缺口当作连续状态演化。",
                    "该类结果可用于事件参数率定和逐场洪水评价，但不形成可直接接续未来预报的连续末状态。",
                ]
                if event_runtime_independent_active()
                else [
                    "当前核心支持统一初始状态向量 INIT_ST，也支持从结果末端按像元状态快照继续预报。",
                    (
                        "当前结果已保存 SP/SM/WC/UZ/LZ 及雨、雪、冰水源分支状态，可作为未来预报热启动状态。"
                        if state_snapshot_saved
                        else "当前结果未成功保存按像元末状态快照。"
                    ),
                    "状态重启预报不重新率定参数；未来气象输入进入热启动预报运行。",
                ]
            ),
        },
        "basin_info": {
            "catchment_area_km2": round(float(CATCHMENT_AREA), 6),
            "valid_cells": int(len(VALID_CELLS)),
            "glacier_cells": int(GLACIER_MASK.sum()),
            "glacier_fraction_sum": round(float(np.sum(GLACIER_FRACTION)), 6) if GLACIER_FRACTION is not None else 0.0,
            "zone_low_cells": int(ZONE_LOW.sum()),
            "zone_high_cells": int(ZONE_HIGH.sum()),
        },
        "project_object_type": current_project_object_type(),
        "calibration_workflow": result_workflow,
        "calibration_workflow_status": result_workflow_status,
        "calibration_phases": list(workflow_metadata.get("calibration_phases", []) or []),
        "final_selected_phase": str(workflow_metadata.get("final_selected_phase", "") or ""),
        "final_parameters_from_phase": str(workflow_metadata.get("final_parameters_from_phase", "") or ""),
        "calibration_workflow_guards": list(workflow_metadata.get("active_objective_guards", []) or []),
        "calibration_workflow_notes": list(workflow_metadata.get("notes", []) or []),
        "calibration_profile": profile_name,
        "rate_mode": profile_name,
        "requested_objective_mode": requested_objective_mode,
        "effective_objective_mode": objective_mode,
        "param_bounds_profile": str(PARAM_BOUNDS_PROFILE_SELECTED),
        "param_bounds_profile_label": PARAM_BOUNDS_PROFILE_LABELS.get(
            str(PARAM_BOUNDS_PROFILE_SELECTED),
            str(PARAM_BOUNDS_PROFILE_SELECTED),
        ),
        "parameter_profile": parameter_profile,
        "objective_profile": objective_profile,
        "objective_family": objective_evaluation.get("objective_family", objective_mode) if objective_evaluation else objective_mode,
        "objective": objective_meta,
        "hard_checks": dict(objective_evaluation.get("hard_checks", {}) or {}) if objective_evaluation else {},
        "objective_terms": dict(objective_evaluation.get("objective_terms", {}) or {}) if objective_evaluation else {},
        "diagnostics": dict(objective_evaluation.get("diagnostics", {}) or {}) if objective_evaluation else {},
        "diagnostic_only_constraints": dict(objective_evaluation.get("diagnostic_only_constraints", {}) or {}) if objective_evaluation else {"glacier_fraction_window": True},
        "evidence_registry": dict(objective_evaluation.get("evidence_registry", {}) or {}) if objective_evaluation else {},
        "event_mode": dict(EVENT_RUNTIME_META or {}),
        "event_initial_state_policy": EVENT_INITIAL_STATE_POLICY,
        "event_count": int(dict(EVENT_RUNTIME_META or {}).get("event_count", 0) or 0),
        "flood_event_evaluation": flood_event_evaluation,
        "optimization": {
            "method": str(getattr(args, "method", "de")),
            "mc_samples": int(getattr(args, "mc_samples", 0)),
            "maxiter": int(getattr(args, "maxiter", 0)),
            "popsize": int(getattr(args, "popsize", 0)),
            "tol": float(getattr(args, "tol", 0.0)),
            "workers": int(getattr(args, "workers", 1)),
            "debug_days": int(getattr(args, "debug_days", 0) or 0),
            "requested_polish": bool(getattr(args, "polish", False)),
            "polish": bool(effective_global_polish_enabled()),
            "refine_requested": bool(OPTIMIZATION_STAGE_STATS.get("refine_requested", False)),
            "refine_enabled": bool(OPTIMIZATION_STAGE_STATS.get("refine_requested", False)),
            "refine_executed": bool(dict(stage_stats.get("refine", {})).get("executed", False)),
            "init_params_file": str(getattr(args, "init_params_file", "") or ""),
            "init_bound_shrink": float(getattr(args, "init_bound_shrink", 0.0) or 0.0),
            "param_bounds_profile": str(PARAM_BOUNDS_PROFILE_SELECTED),
            "param_bounds_profile_label": PARAM_BOUNDS_PROFILE_LABELS.get(
                str(PARAM_BOUNDS_PROFILE_SELECTED),
                str(PARAM_BOUNDS_PROFILE_SELECTED),
            ),
            "calibration_workflow": result_workflow,
            "calibration_workflow_status": result_workflow_status,
            "final_selected_phase": str(workflow_metadata.get("final_selected_phase", "") or ""),
            "objective_mode": objective_mode,
            "requested_objective_mode": requested_objective_mode,
            "effective_objective_mode": objective_mode,
            "selected_stage_evaluations": selected_stage_evaluations,
            "selected_stage_generations": selected_stage_generations,
            "selected_stage_progress_points": selected_stage_progress_points,
            "total_evaluations": total_evaluations,
            "total_generations": int(total_generations),
            "total_progress_points": int(total_progress_points),
            "selected_result_stage": selected_stage,
            "selected_result_label": (
                "局部精修结果"
                if selected_stage == "refine"
                else (
                    "全局搜索结果（含末端精修）"
                    if (selected_stage == "global" and bool(dict(stage_stats.get("global", {})).get("polish", False)))
                    else (
                        "全局搜索结果"
                        if selected_stage == "global"
                        else ("随机筛选结果" if selected_stage == "mc" else "优化结果")
                    )
                )
            ),
            "objective_value": (
                round(float(objective_value), 6)
                if np.isfinite(float(objective_value))
                else None
            ),
            "stage_stats": stage_stats or None,
            "debug_window": dict(DEBUG_WINDOW_INFO) if isinstance(DEBUG_WINDOW_INFO, dict) else None,
        },
        "optimized_params": {name: round(float(val), 6) for name, val in zip(param_names, result.x)},
        "fixed_params": {k: float(v) for k, v in FIXED.items()},
        "metrics": {
            "calibration": {
                "sample_count": int(metrics["obs_count_cal"]),
                "nse": round(metrics["nse_cal"], 4),
                "kge": round(metrics["kge_cal"], 4) if np.isfinite(metrics["kge_cal"]) else None,
                "kge_r": round(metrics["kge_r_cal"], 4) if np.isfinite(metrics["kge_r_cal"]) else None,
                "kge_alpha": round(metrics["kge_alpha_cal"], 4) if np.isfinite(metrics["kge_alpha_cal"]) else None,
                "kge_beta": round(metrics["kge_beta_cal"], 4) if np.isfinite(metrics["kge_beta_cal"]) else None,
                "log_nse": round(metrics["log_nse_cal"], 4) if np.isfinite(metrics["log_nse_cal"]) else None,
                "pbias": round(metrics["pbias_cal"], 2) if np.isfinite(metrics["pbias_cal"]) else None,
                "rmse_m3s": round(metrics["rmse_cal"], 4) if np.isfinite(metrics["rmse_cal"]) else None,
                "rain_fraction": round(rain_frac_cal, 4),
                "snow_fraction": round(snow_frac_cal, 4),
                "ice_fraction": round(ice_frac_cal, 4),
            },
            "validation": {
                "sample_count": int(metrics["obs_count_val"]),
                "nse": round(metrics["nse_val"], 4) if np.isfinite(metrics["nse_val"]) else None,
                "kge": round(metrics["kge_val"], 4) if np.isfinite(metrics["kge_val"]) else None,
                "kge_r": round(metrics["kge_r_val"], 4) if np.isfinite(metrics["kge_r_val"]) else None,
                "kge_alpha": round(metrics["kge_alpha_val"], 4) if np.isfinite(metrics["kge_alpha_val"]) else None,
                "kge_beta": round(metrics["kge_beta_val"], 4) if np.isfinite(metrics["kge_beta_val"]) else None,
                "log_nse": round(metrics["log_nse_val"], 4) if np.isfinite(metrics["log_nse_val"]) else None,
                "pbias": round(metrics["pbias_val"], 2) if np.isfinite(metrics["pbias_val"]) else None,
                "rmse_m3s": round(metrics["rmse_val"], 4) if np.isfinite(metrics["rmse_val"]) else None,
                "rain_fraction": round(rain_frac_val, 4),
                "snow_fraction": round(snow_frac_val, 4),
                "ice_fraction": round(ice_frac_val, 4),
            },
        },
        "glacier_reference_comparison": {
            "routed": clean_metrics_dict(glacier_cmp_routed),
            "raw": clean_metrics_dict(glacier_cmp_raw),
        },
        "flow_duration": {
            "obs_cal": flow_duration_curve(Q_OBS_CALIB[:min(len(q_sim_calib), len(Q_OBS_CALIB))]),
            "sim_cal": flow_duration_curve(q_sim_calib[:min(len(q_sim_calib), len(Q_OBS_CALIB))]),
            "obs_val": flow_duration_curve(Q_OBS_VALID[:min(len(q_sim_valid), len(Q_OBS_VALID))]),
            "sim_val": flow_duration_curve(q_sim_valid[:min(len(q_sim_valid), len(Q_OBS_VALID))]),
        },
        "monthly_metrics": monthly_metrics(
            SIM_DATES[CALIB_MASK][:min(len(q_sim_calib), len(Q_OBS_CALIB))],
            Q_OBS_CALIB[:min(len(q_sim_calib), len(Q_OBS_CALIB))],
            q_sim_calib[:min(len(q_sim_calib), len(Q_OBS_CALIB))],
        ),
    }
    metadata["reliability_flag"] = RELIABILITY_FLAG
    metadata["reliability_notes"] = reliability_notes
    metadata["glacier_physical_checks"] = glacier_physical_checks
    metadata["objective"]["glacier_physical_check_active"] = bool(glacier_physical_checks.get("available", False))
    metadata["optional_modules"]["glacier"]["physical_checks"] = glacier_physical_checks
    metadata["optional_modules"]["glacier"]["fraction_report"] = dict(
        metadata.get("diagnostics", {}).get("glacier_fraction_report", {}) or {}
    )

    with open(os.path.join(run_dir, "metadata.json"), "w", encoding="utf-8") as f:
        json_dump_safe(metadata, f, indent=2)

    with open(os.path.join(run_dir, "parameters.txt"), "w", encoding="utf-8") as f:
        f.write("HBV-Cryo 率定结果\n")
        f.write("=" * 60 + "\n")
        f.write(f"运行编号: {RUN_ID}\n")
        f.write(f"生成时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
        f.write(f"率定期 NSE: {metrics['nse_cal']:.4f}\n")
        if np.isfinite(metrics["kge_cal"]):
            f.write(f"率定期 KGE: {metrics['kge_cal']:.4f}\n")
        if np.isfinite(metrics["log_nse_cal"]):
            f.write(f"率定期 log-NSE: {metrics['log_nse_cal']:.4f}\n")
        if np.isfinite(metrics["pbias_cal"]):
            f.write(f"率定期 PBIAS: {metrics['pbias_cal']:.2f}%\n")
        if np.isfinite(metrics["nse_val"]):
            f.write(f"验证期 NSE: {metrics['nse_val']:.4f}\n")
        if np.isfinite(metrics["kge_val"]):
            f.write(f"验证期 KGE: {metrics['kge_val']:.4f}\n")
        if glacier_cmp_routed is not None:
            routed_rmse = glacier_cmp_routed["rmse_m3s"]
            if np.isfinite(routed_rmse):
                f.write(f"冰川融水参考 RMSE（汇流后）: {routed_rmse:.4f} m3/s\n")
        if flood_event_evaluation.get("enabled"):
            f.write(
                "洪水事件评价: "
                f"{int(flood_event_evaluation.get('valid_event_count', 0))}/"
                f"{int(flood_event_evaluation.get('event_count', 0))} 场有效"
            )
            if flood_event_file:
                f.write(f"（详见 {flood_event_file}）")
            f.write("\n")
        f.write("\n参数结果\n")
        for name, val in zip(param_names, result.x):
            f.write(f"{name} = {float(val):.6f}\n")

    print("\n最终指标")
    print(f"  率定期 NSE: {metrics['nse_cal']:.4f}")
    if np.isfinite(metrics["kge_cal"]):
        print(f"  率定期 KGE: {metrics['kge_cal']:.4f}")
    if np.isfinite(metrics["log_nse_cal"]):
        print(f"  率定期 log-NSE: {metrics['log_nse_cal']:.4f}")
    if np.isfinite(metrics["pbias_cal"]):
        print(f"  率定期 PBIAS: {metrics['pbias_cal']:.2f}%")
    if np.isfinite(metrics["nse_val"]):
        print(f"  验证期 NSE: {metrics['nse_val']:.4f}")
    if np.isfinite(metrics["kge_val"]):
        print(f"  验证期 KGE: {metrics['kge_val']:.4f}")
    if np.isfinite(metrics["rmse_cal"]):
        print(f"  率定期 RMSE: {metrics['rmse_cal']:.2f} m3/s")
    if np.isfinite(metrics["rmse_val"]):
        print(f"  验证期 RMSE: {metrics['rmse_val']:.2f} m3/s")
    if glacier_cmp_routed is not None and np.isfinite(glacier_cmp_routed["rmse_m3s"]):
        print(f"  冰川融水参考 RMSE（汇流后）: {glacier_cmp_routed['rmse_m3s']:.2f} m3/s")
    if flood_event_evaluation.get("enabled"):
        print(
            "  洪水事件评价: "
            f"{int(flood_event_evaluation.get('valid_event_count', 0))}/"
            f"{int(flood_event_evaluation.get('event_count', 0))} 场有效"
        )
    print(f"  结果目录: {run_dir}")


def main():
    global args, eval_count, best_score, best_objective, best_params, DEBUG_WINDOW_INFO, PREC_DIR, PROGRESS_FILE, PROGRESS_FILE_REFINE, gen_count, OBJECTIVE_MODE_SELECTED, REQUESTED_OBJECTIVE_MODE, OPTIMIZATION_STAGE_STATS, CALIBRATION_WORKFLOW_SELECTED, STAGED_CALIBRATION_METADATA, FLOOD_EVENT_CONFIG
    args = parse_args()
    if getattr(args, "flood_events_file", None):
        FLOOD_EVENT_CONFIG = load_flood_event_config_file(args.flood_events_file)
    if bool(getattr(args, "quick_test", False)):
        args.debug_days = 0
    patched_parameter_profile = (
        isinstance(PARAMETER_PROFILE, dict)
        and isinstance(PARAMETER_PROFILE.get("bounds"), dict)
        and bool(PARAMETER_PROFILE.get("bounds"))
    )
    if not patched_parameter_profile:
        select_param_bounds_profile(getattr(args, "param_bounds_profile", DEFAULT_PARAM_BOUNDS_PROFILE))
    CALIBRATION_WORKFLOW_SELECTED = str(
        getattr(args, "calibration_workflow", CALIBRATION_WORKFLOW_SINGLE) or CALIBRATION_WORKFLOW_SINGLE
    ).strip().lower()
    if CALIBRATION_WORKFLOW_SELECTED not in {CALIBRATION_WORKFLOW_SINGLE, CALIBRATION_WORKFLOW_STAGED}:
        CALIBRATION_WORKFLOW_SELECTED = CALIBRATION_WORKFLOW_SINGLE
    STAGED_CALIBRATION_METADATA = {}
    REQUESTED_OBJECTIVE_MODE = str(getattr(args, "objective_mode", "auto") or "auto").strip().lower() or "auto"
    OBJECTIVE_MODE_SELECTED = REQUESTED_OBJECTIVE_MODE
    configure_time_step()
    OBJECTIVE_MODE_SELECTED = current_objective_mode()
    debug_window = apply_debug_window(args.debug_days)
    setup_logging()
    with OBJECTIVE_STATE_LOCK:
        eval_count = 0
        gen_count = 0
        best_score = -np.inf
        best_objective = np.inf
        best_params = None
    OPTIMIZATION_STAGE_STATS = {}
    DEBUG_WINDOW_INFO = dict(debug_window) if isinstance(debug_window, dict) else None

    if args.prec_source == "custom_tif" and not args.prec_dir:
        raise ValueError("prec-source=custom_tif 时必须提供 --prec-dir")

    if args.prec_dir:
        PREC_DIR = args.prec_dir
    elif args.prec_source == "era5":
        PREC_DIR = PREC_DIR_ERA5
    elif args.prec_source == "cmfd":
        PREC_DIR = PREC_DIR_CMFD
    else:
        PREC_DIR = PREC_DIR_MSWEP

    log_msg("=" * 70)
    log_msg(f"HBV-Cryo 空间分区率定 ({len(param_names)} 参数)")
    log_msg("=" * 70)
    precip_label_map = {
        "era5": "ERA5 格点降水",
        "cmfd": "CMFD 格点降水",
        "mswep": "MSWEP 格点降水",
        "custom_tif": "本地降水目录",
    }
    precip_label = f"本地降水目录（{args.prec_dir}）" if args.prec_dir else precip_label_map.get(args.prec_source, args.prec_source)
    glacier_label = "联动计算" if args.glacier_mode == "inline" else "关闭"
    log_msg(f"并行线程数: {args.workers}")
    log_msg(f"最大迭代轮数: {args.maxiter}")
    log_msg(f"搜索种群规模: {args.popsize * len(PARAM_BOUNDS)}")
    log_msg(f"降水驱动来源: {precip_label}")
    log_msg(f"冰川模块: {glacier_label}")
    log_msg(
        "参数边界档案: "
        f"{PARAM_BOUNDS_PROFILE_LABELS.get(PARAM_BOUNDS_PROFILE_SELECTED, PARAM_BOUNDS_PROFILE_SELECTED)}"
    )
    log_msg(f"时间步长: {TIME_STEP_HOURS:.3f} h")
    if debug_window is not None:
        log_msg(f"短窗调试天数: {debug_window['debug_days']}")
        log_msg(f"短窗率定起点: {debug_window['calib_start']}")
        log_msg(f"短窗模拟截止: {debug_window['sim_end']}")
        if debug_window.get("shifted"):
            log_msg(
                f"[WARN] 原始短窗起点 {debug_window['requested_start']} 缺少足够变化的有效观测，"
                f"已自动平移到 {debug_window['calib_start']}。"
            )

    log_msg("正在预热数值核心，首次启动可能稍慢……")
    warmup_jit()
    log_msg("数值核心预热完成。")

    if args.quick_test:
        quick_end_ts = pd.to_datetime(WARMUP_START) + pd.to_timedelta(max(args.quick_days, 1), unit="D") - time_step_timedelta()
        quick_end = format_time_value(quick_end_ts)
        log_msg(f"开始快速检查：仅加载至 {quick_end}。")
        load_all_data(end_date_override=quick_end, skip_obs=True)
        log_msg("快速检查完成。")
        return

    log_msg("开始加载气象、地理和观测数据……")
    load_all_data()
    log_msg("数据装载完成，开始估算单次前向模拟耗时。")

    x_test = default_test_vector()
    t0 = time.time()
    _ = run_simulation(x_test)
    t_single = time.time() - t0
    log_msg(f"单次前向模拟耗时: {t_single:.3f} s")

    log_msg(f"搜索策略: {args.method}")
    log_msg(f"率定流程: {CALIBRATION_WORKFLOW_SELECTED}")

    init_vector = load_initial_param_vector(args.init_params_file) if args.init_params_file else None
    base_bounds = validate_search_bounds(PARAM_BOUNDS)
    search_bounds = ensure_feasible_search_bounds(
        apply_initial_bounds(base_bounds, init_vector, args.init_bound_shrink),
        fallback_bounds=base_bounds if (init_vector is not None and args.init_bound_shrink > 0) else None,
        stage_label="初始参数收缩后的搜索范围",
    )
    if init_vector is not None:
        log_msg(f"初始参数集: {args.init_params_file}")
        if args.init_bound_shrink > 0:
            log_msg(f"初始参数范围收缩比例: {args.init_bound_shrink:.3f}")

    pool = None
    if args.workers > 1:
        try:
            pool = ThreadPool(processes=args.workers)
        except PermissionError as exc:
            log_msg(f"[WARN] ThreadPool 创建失败，已回退到 ThreadPoolExecutor: {exc}")
            pool = _ExecutorThreadPool(args.workers)
    worker_map = pool.map if pool is not None else None
    try:
        if CALIBRATION_WORKFLOW_SELECTED == CALIBRATION_WORKFLOW_STAGED:
            result = run_staged_calibration_workflow(search_bounds, init_vector, t_single, worker_map=worker_map)
        else:
            result, OPTIMIZATION_STAGE_STATS = run_search_pipeline(
                search_bounds,
                init_vector,
                t_single,
                worker_map=worker_map,
            )
    finally:
        if pool is not None:
            pool.close()
            pool.join()

    if result is None:
        raise RuntimeError("Calibration did not produce a valid result.")
    selected_stage = str(getattr(result, "result_stage", "") or "")
    selected_label = {
        "refine": "局部精修结果",
        "global": "差分进化结果",
        "mc": "蒙特卡洛结果",
    }.get(selected_stage, "优化结果")
    log_msg(f"最终采用：{selected_label}，目标值={float(getattr(result, 'fun', np.nan)):.4f}")

    save_results(result)


if __name__ == "__main__":
    main()
