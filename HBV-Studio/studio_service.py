#!/usr/bin/env python
# -*- coding: utf-8 -*-
from __future__ import annotations

import argparse
import contextlib
import copy
import csv
import hashlib
import io
import json
import locale
import math
import mimetypes
import os
import re
import shutil
import socket
import string
import subprocess
import sys
import threading
import time
import traceback
import unicodedata
import uuid
from dataclasses import dataclass, field
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Callable
from urllib.parse import parse_qs, unquote, urlparse

import numpy as np
import pandas as pd

import profile_runner
from profile_runner import (
    PROFILE_DAILY,
    PROFILE_HOURLY,
    PROFILE_LABELS,
    build_profile_paths,
    build_workspace_paths,
    resolve_profile,
)
from 观测径流处理 import (
    DEFAULT_MIN_DAILY_HOURS,
    detect_observed_flow_column as shared_detect_observed_flow_column,
    detect_time_column as shared_detect_time_column,
    inspect_observed_discharge,
)
from 公共函数 import (
    builtin_dem_path as shared_builtin_dem_path,
    default_builtin_glacier_path,
    default_builtin_dem_path,
    infer_dem_kind_from_raster,
    remove_other_workspace_dem_variants,
    resolve_workspace_dem_path,
    workspace_dem_filename,
)

OBJECT_REGRESSION = "regression_validation"
OBJECT_INTERBASIN = "interbasin_with_boundary"
OBJECT_FULL_UPSTREAM = "full_upstream_basin"
OBJECT_LABELS = {
    OBJECT_REGRESSION: "回归验证样例",
    OBJECT_INTERBASIN: "区间流域 + 上游边界入流",
    OBJECT_FULL_UPSTREAM: "完整上游流域",
}
CALIBRATION_PARAM_NAMES = [
    "TT", "FC", "BETA", "LP",
    "RFCF", "SFCF",
    "CFR", "CWH",
    "CFMAX_low", "CFMAX_high",
    "K", "K1", "K2", "UZL", "PERC",
    "ICE_FACTOR", "K_MUSK", "X_MUSK",
]
CALIBRATION_METHODS = {
    "de": "Differential Evolution",
    "mc_screen_de": "Monte Carlo 预筛 + DE",
    "mc_only": "Monte Carlo 采样",
}
DEFAULT_MANUAL_START_VECTOR = [
    -1.2, 1200.0, 1.0, 0.95, 1.0, 1.05,
    0.05, 0.05, 3.5, 5.5, 0.25, 0.05,
    0.005, 30.0, 1.8, 2.0, 1.2, 0.05,
]
RUN_KIND_LABELS = {
    "manual_starter": "手调起点",
    "manual_result": "手调结果",
    "forecast_restart": "连续状态预报",
    "calibration": "正式率定",
    "legacy": "历史结果",
}
TIME_BASIS_CONTINUOUS = "continuous"
TIME_BASIS_EVENT_WINDOWS = "event_windows"
TIME_BASIS_FORECAST_WINDOW = "forecast_window"
TIME_BASIS_LABELS = {
    TIME_BASIS_CONTINUOUS: "连续时段",
    TIME_BASIS_EVENT_WINDOWS: "洪水事件窗口",
    TIME_BASIS_FORECAST_WINDOW: "预报窗口",
}
EVENT_PURPOSE_ALIASES = {
    "calibration": "calibration",
    "calib": "calibration",
    "train": "calibration",
    "training": "calibration",
    "率定": "calibration",
    "训练": "calibration",
    "validation": "validation",
    "valid": "validation",
    "val": "validation",
    "verify": "validation",
    "验证": "validation",
    "diagnostic": "diagnostic",
    "diag": "diagnostic",
    "诊断": "diagnostic",
    "复核": "diagnostic",
}
EVENT_INITIAL_STATE_POLICY_ALIASES = {
    "event_warmup": "event_warmup",
    "event-preheat": "event_warmup",
    "event_preheat": "event_warmup",
    "independent_warmup": "event_warmup",
    "warmup_each_event": "event_warmup",
    "warmup": "event_warmup",
    "事件预热": "event_warmup",
    "逐场预热": "event_warmup",
    "fixed_initial": "fixed_initial",
    "fixed": "fixed_initial",
    "default_initial": "fixed_initial",
    "constant": "fixed_initial",
    "固定初值": "fixed_initial",
    "固定初始状态": "fixed_initial",
    "默认初值": "fixed_initial",
    "source_state": "source_state",
    "restart_state": "source_state",
    "snapshot": "source_state",
    "hot_start": "source_state",
    "来源状态": "source_state",
    "状态快照": "source_state",
    "起报状态": "source_state",
    "continuous_state": "continuous_state",
    "continuous": "continuous_state",
    "carryover": "continuous_state",
    "carry_over": "continuous_state",
    "连续状态": "continuous_state",
    "事件间连续": "continuous_state",
}
EVENT_INITIAL_STATE_POLICY_SUMMARIES = {
    "event_warmup": {
        "label": "事件预热",
        "state_continuity_between_events": False,
        "note": "每场事件从运行开始独立预热至评分开始，事件之间不传递状态。",
        "warning": "",
    },
    "fixed_initial": {
        "label": "固定初值",
        "state_continuity_between_events": False,
        "note": "每场事件使用默认或指定初始状态，事件之间不传递状态。",
        "warning": "固定初值对前期含水量、积雪和汇流记忆的不确定性较高，宜仅用于资料极短的次洪复核。",
    },
    "source_state": {
        "label": "来源状态",
        "state_continuity_between_events": False,
        "note": "每场事件使用外部连续模拟状态作为初值，事件之间不直接传递状态。",
        "warning": "",
    },
    "continuous_state": {
        "label": "连续状态",
        "state_continuity_between_events": True,
        "note": "事件间按连续过程传递状态，要求事件之间强迫资料连续。",
        "warning": "连续状态策略不适合事件之间存在资料缺口的事件窗口集合。",
    },
}
SYSTEM_RESULT_TITLES = frozenset({"手调起点", "手调结果"})
RUN_EXPORT_FIELD_LABELS = {
    "q_sim": "模拟总径流(m3/s)",
    "q_sim_model": "模型本地产流(m3/s)",
    "q_boundary_inflow": "边界入流(m3/s)",
    "q_obs": "观测径流(m3/s)",
    "q_rain": "降雨径流(m3/s)",
    "q_snow": "融雪径流(m3/s)",
    "q_ice": "裸冰融化径流(m3/s)",
    "q_ice_raw": "裸冰融化原始分量(m3/s)",
    "q_ice_reference": "冰川参考径流(m3/s)",
    "q_ice_reference_raw": "冰川参考原始融水(m3/s)",
}
DEFAULT_RUN_EXPORT_FIELDS = ("q_sim", "q_obs", "q_rain", "q_snow", "q_ice")


def run_boundary_enabled(metadata: dict[str, Any] | None) -> bool:
    meta = dict(metadata or {})
    optional_modules = dict(meta.get("optional_modules", {}) or {})
    boundary_meta = dict(meta.get("boundary_condition", {}) or {})
    return bool(
        meta.get("project_object_type") == OBJECT_INTERBASIN
        or dict(optional_modules.get("boundary_inflow", {}) or {}).get("enabled")
        or boundary_meta.get("enabled")
        or boundary_meta.get("boundary_inflow_file")
    )


def default_run_export_fields(metadata: dict[str, Any] | None) -> list[str]:
    fields = ["q_sim", "q_obs", "q_rain", "q_snow", "q_ice"]
    if run_boundary_enabled(metadata):
        fields.append("q_boundary_inflow")
    return fields


def _env_path(name: str, default: Path) -> Path:
    raw = str(os.environ.get(name, "")).strip()
    if not raw:
        return default
    return Path(raw).expanduser().resolve(strict=False)


GUI_ROOT = Path(__file__).resolve().parent
PROJECT_ROOT = GUI_ROOT.parent
WEB_ROOT = _env_path("HBV_STUDIO_WEB_ROOT", GUI_ROOT / "web")
WORKSPACE_DIR = _env_path("HBV_STUDIO_WORKSPACE_DIR", GUI_ROOT / "workspaces")
TEMPLATE_DIR = _env_path("HBV_STUDIO_TEMPLATE_DIR", GUI_ROOT / "templates")
DOCS_DIR = _env_path("HBV_STUDIO_DOCS_DIR", GUI_ROOT / "docs")
PROJECT_RUNTIME_DIR = _env_path("HBV_STUDIO_RUNTIME_ROOT", PROJECT_ROOT / "运行目录")
GLOBAL_PARAMETER_LIBRARY_PATH = _env_path(
    "HBV_STUDIO_PARAMETER_LIBRARY",
    PROJECT_RUNTIME_DIR / "parameter_library" / "global_parameter_sets.json",
)
DATA_PREP_DIR = PROJECT_ROOT / "数据准备"
BUILTIN_DEM_1KM = shared_builtin_dem_path("1km")
BUILTIN_DEM_0P1 = shared_builtin_dem_path("0p1deg")
BUILTIN_DEM = default_builtin_dem_path()
BUILTIN_GLACIER_SHP = default_builtin_glacier_path()
MODEL_RUNNER = GUI_ROOT / "profile_runner.py"


def bundled_plotly_js_path() -> Path | None:
    try:
        import plotly  # type: ignore
    except Exception:
        return None
    path = Path(plotly.__file__).resolve().parent / "package_data" / "plotly.min.js"
    return path if path.exists() else None


def _workspace_dem_path(gis_dir: Path | str, prefer: str | None = None) -> Path:
    return resolve_workspace_dem_path(Path(gis_dir), prefer=prefer)


def _configured_dem_kind(config: dict[str, Any]) -> str:
    return infer_dem_kind_from_raster(str(config.get("DEM_tif", "") or ""))


def _find_python() -> str:
    """Find the best Python executable: bundled venv > current interpreter."""
    if getattr(sys, "frozen", False):
        return sys.executable
    venv_python = PROJECT_ROOT / "runtime" / "venv" / "Scripts" / "python.exe"
    if venv_python.exists():
        return str(venv_python)
    return sys.executable


PYTHON_EXE = _find_python()
SELF_CHECK = PROJECT_ROOT / "系统自检.py"
TUOTUOHE_SYNC_SCRIPT = GUI_ROOT / "sync_tuotuohe_data.py"
MAX_TASK_OUTPUT = 1200
FORWARD_SIM_TIMEOUT_SEC = 900
DEFAULT_WORKSPACE_PATH = WORKSPACE_DIR / "新流域工作区.json"
METEO_STATE_FILENAME = "_meteo_state.json"
RUN_PY_FILE_ROLE = "__run_py_file__"
DIR_BROWSER_FILE_PREVIEW_ITEMS = 12
FORCING_PIPELINE_STEP_IDS = frozenset({
    "align_inputs",
    "apply_precip_strategy",
    "align_hourly_inputs",
})

PLACEHOLDERS = {
    "__PROJECT_ROOT__": str(PROJECT_ROOT),
    "__GUI_ROOT__": str(GUI_ROOT),
}

LAST_SERVER_REQUEST_AT = time.time()
LAST_WINDOW_UNLOAD_AT = 0.0
SERVER_ACTIVITY_LOCK = threading.Lock()
INSTALLED_IDLE_SHUTDOWN_SECONDS = 90.0
WINDOW_UNLOAD_SHUTDOWN_GRACE_SECONDS = 3.0
APP_VERSION = "2026-05-24-meteo-shp-staging"
SERVER_STARTED_AT = time.time()


def env_flag(name: str, default: bool = False) -> bool:
    raw = str(os.environ.get(name, "")).strip().lower()
    if not raw:
        return default
    return raw in {"1", "true", "yes", "on"}


def installed_mode() -> bool:
    return env_flag("HBV_STUDIO_INSTALLED_MODE", default=False)


def mark_server_activity(*, unload: bool = False) -> None:
    now = time.time()
    with SERVER_ACTIVITY_LOCK:
        global LAST_SERVER_REQUEST_AT, LAST_WINDOW_UNLOAD_AT
        LAST_SERVER_REQUEST_AT = now
        if unload:
            LAST_WINDOW_UNLOAD_AT = now


def server_activity_snapshot() -> tuple[float, float]:
    with SERVER_ACTIVITY_LOCK:
        return LAST_SERVER_REQUEST_AT, LAST_WINDOW_UNLOAD_AT


def has_running_tasks() -> bool:
    with TASK_LOCK:
        return any(task.status == "running" for task in TASKS.values())


def request_server_shutdown(server: ThreadingHTTPServer, message: str, *, delay_sec: float = 0.0) -> None:
    if getattr(server, "_hbv_shutdown_started", False):
        return
    setattr(server, "_hbv_shutdown_started", True)

    def _shutdown() -> None:
        if delay_sec > 0:
            time.sleep(delay_sec)
        print(message, flush=True)
        server.shutdown()

    threading.Thread(target=_shutdown, daemon=True).start()


def monitor_server_lifecycle(server: ThreadingHTTPServer) -> None:
    while not getattr(server, "_hbv_shutdown_started", False):
        time.sleep(2.0)
        if not installed_mode():
            continue
        if has_running_tasks():
            continue
        last_request_at, last_unload_at = server_activity_snapshot()
        now = time.time()
        if last_unload_at and last_request_at <= last_unload_at and (now - last_unload_at) >= WINDOW_UNLOAD_SHUTDOWN_GRACE_SECONDS:
            request_server_shutdown(server, "[HBV-Studio] 浏览器页面已关闭，后台空闲，正在退出。")
            break
        if (now - last_request_at) >= INSTALLED_IDLE_SHUTDOWN_SECONDS:
            request_server_shutdown(server, "[HBV-Studio] 安装版空闲超时，后台服务自动退出。")
            break


@dataclass
class TaskRecord:
    id: str
    task_type: str
    label: str
    command: list[str]
    cwd: str
    status: str = "running"
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)
    return_code: int | None = None
    output: list[str] = field(default_factory=list)
    detected_runs: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    def append(self, line: str) -> None:
        text = line.rstrip("\n")
        if not text:
            return
        self.output.append(text)
        if len(self.output) > MAX_TASK_OUTPUT:
            self.output = self.output[-MAX_TASK_OUTPUT:]
        self.updated_at = time.time()

    def as_dict(self) -> dict[str, Any]:
        progress = task_progress_snapshot(self)
        return {
            "id": self.id,
            "task_type": self.task_type,
            "label": self.label,
            "command": self.command,
            "cwd": self.cwd,
            "status": self.status,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "return_code": self.return_code,
            "output": self.output[-200:],
            "detected_runs": self.detected_runs,
            "progress": progress,
            "ui_progress": self.metadata.get("ui_progress"),
            "result": self.metadata.get("result"),
            "config_path": self.metadata.get("config_path"),
            "run_path": self.metadata.get("run_path"),
            "step_id": self.metadata.get("step_id"),
            "step_title": self.metadata.get("step_title"),
            "step_titles": self.metadata.get("step_titles"),
            "profile": self.metadata.get("profile"),
            "calibration_workflow": self.metadata.get("calibration_workflow"),
            "calibration_workflow_status": self.metadata.get("calibration_workflow_status"),
            "runtime_prec_source": self.metadata.get("runtime_prec_source"),
            "objective_mode": self.metadata.get("objective_mode"),
            "glacier_mode": self.metadata.get("glacier_mode"),
            "method": self.metadata.get("method"),
            "quick_test": self.metadata.get("quick_test"),
            "mc_samples": self.metadata.get("mc_samples"),
            "maxiter": self.metadata.get("maxiter"),
            "refine_maxiter": self.metadata.get("refine_maxiter"),
        }


class TaskOutputRelay:
    """Collect line-oriented stdout/stderr and forward it into task output."""

    def __init__(self, callback: Callable[[str], None], mirror: Any = None) -> None:
        self.callback = callback
        self.mirror = mirror
        self._buffer = ""

    def write(self, text: str) -> int:
        if not isinstance(text, str):
            text = str(text)
        if self.mirror is not None:
            try:
                self.mirror.write(text)
            except Exception:
                pass
        self._buffer += text
        while "\n" in self._buffer:
            line, self._buffer = self._buffer.split("\n", 1)
            line = line.rstrip("\r")
            if line.strip():
                self.callback(line)
        return len(text)

    def flush(self) -> None:
        if self._buffer:
            line = self._buffer.rstrip("\r")
            if line.strip():
                self.callback(line)
            self._buffer = ""
        if self.mirror is not None:
            try:
                self.mirror.flush()
            except Exception:
                pass

    def isatty(self) -> bool:
        return False


def call_with_output_capture(callback: Callable[[str], None] | None, fn: Callable[..., Any], *args: Any, **kwargs: Any) -> Any:
    if callback is None:
        return fn(*args, **kwargs)
    stdout_relay = TaskOutputRelay(callback, mirror=sys.stdout)
    stderr_relay = TaskOutputRelay(callback, mirror=sys.stderr)
    try:
        with contextlib.redirect_stdout(stdout_relay), contextlib.redirect_stderr(stderr_relay):
            return fn(*args, **kwargs)
    finally:
        stdout_relay.flush()
        stderr_relay.flush()


TASKS: dict[str, TaskRecord] = {}
TASK_LOCK = threading.Lock()
RUN_LIST_CACHE_LOCK = threading.Lock()
RUN_LIST_CACHE_SIGNATURE: tuple[tuple[Any, ...], ...] | None = None
RUN_LIST_CACHE_ITEMS: list[dict[str, Any]] = []
TIF_SCAN_CACHE_LOCK = threading.Lock()
TIF_SCAN_CACHE: dict[str, dict[str, Any]] = {}
GRID_ALIGNMENT_CACHE_LOCK = threading.Lock()
GRID_ALIGNMENT_CACHE: dict[str, dict[str, Any]] = {}
GRID_ALIGNMENT_SAMPLE_LIMIT = 12
PATH_ENTRY_COUNT_CACHE_LOCK = threading.Lock()
PATH_ENTRY_COUNT_CACHE: dict[str, dict[str, Any]] = {}
BOUNDARY_CSV_CACHE_LOCK = threading.Lock()
BOUNDARY_CSV_CACHE: dict[str, dict[str, Any]] = {}
MAX_BOUNDARY_CSV_CACHE = 6
MAX_BROWSER_FILE_ITEMS = 300


def _snapshot_tasks() -> list[TaskRecord]:
    """Clone task state so expensive reads can happen outside TASK_LOCK."""
    with TASK_LOCK:
        return [
            TaskRecord(
                id=task.id,
                task_type=task.task_type,
                label=task.label,
                command=list(task.command),
                cwd=task.cwd,
                status=task.status,
                created_at=task.created_at,
                updated_at=task.updated_at,
                return_code=task.return_code,
                output=list(task.output),
                detected_runs=list(task.detected_runs),
                metadata=copy.deepcopy(task.metadata),
            )
            for task in TASKS.values()
        ]


@dataclass
class ForwardRuntimeCacheEntry:
    key: str
    config_path: str
    profile: str
    prec_source: str
    glacier_mode: str
    data_token: str
    module: Any
    observation_state: dict[str, Any] = field(default_factory=dict)
    created_at: float = field(default_factory=time.time)
    last_used: float = field(default_factory=time.time)
    lock: threading.Lock = field(default_factory=threading.Lock)


FORWARD_RUNTIME_CACHE: dict[str, ForwardRuntimeCacheEntry] = {}
FORWARD_RUNTIME_CACHE_LOCK = threading.Lock()
MAX_FORWARD_RUNTIME_CACHE = 4

METEO_KEY = "\u6c14\u8c61\u7b56\u7565"
OBSERVED_FLOW_KEY = "\u89c2\u6d4b\u5f84\u6d41_csv"
OBSERVED_FLOW_SUFFIXES = {".csv", ".xlsx", ".xls", ".xlsm"}
VECTOR_BUNDLE_SUFFIXES = tuple(
    getattr(
        profile_runner,
        "VECTOR_BUNDLE_SUFFIXES",
        (".shp", ".dbf", ".shx", ".prj", ".cpg", ".sbn", ".sbx", ".xml"),
    )
)
METEO_PRECIP_MODE_KEY = "\u964d\u6c34\u65b9\u6848"
METEO_PRECIP_SOURCE_KEY = "\u964d\u6c34\u6765\u6e90"
METEO_PRECIP_SOURCE_LEGACY_KEY = "\u964d\u6c34\u6e90"
METEO_STATION_PREC_KEY = "\u7ad9\u70b9\u964d\u6c34_csv"
METEO_STATION_META_KEY = "\u7ad9\u70b9\u4fe1\u606f_csv"
METEO_HOURLY_PREC_DIR_KEY = "\u539f\u59cb\u5c0f\u65f6\u964d\u6c34\u76ee\u5f55"
METEO_TEMP_SOURCE_KEY = "\u6e29\u5ea6\u6765\u6e90"
METEO_CUSTOM_TEMP_DIR_KEY = "\u81ea\u5e26\u6e29\u5ea6tif\u76ee\u5f55"
METEO_CUSTOM_PREC_DIR_KEY = "\u81ea\u5e26\u964d\u6c34tif\u76ee\u5f55"
METEO_PET_SOURCE_KEY = "\u6f5c\u5728\u84b8\u6563\u53d1\u6765\u6e90"
METEO_CUSTOM_PET_DIR_KEY = "\u81ea\u5e26\u84b8\u6563\u53d1tif\u76ee\u5f55"


def configured_precip_source(config: dict[str, Any]) -> str:
    meteo = dict(config.get(METEO_KEY, {}))
    source = str(meteo.get(METEO_PRECIP_SOURCE_KEY, "")).strip().lower()
    legacy_source = str(meteo.get(METEO_PRECIP_SOURCE_LEGACY_KEY, "")).strip().lower()
    top_level_source = str(config.get("默认降水源", "")).strip().lower()
    if source:
        return source
    if top_level_source in {"era5", "cmfd", "custom_tif"} and legacy_source in {"", "mswep"}:
        return top_level_source
    return legacy_source or top_level_source or "era5"


def resolve_precip_source(config: dict[str, Any], source: Any = None) -> str:
    raw = str(source or "").strip().lower()
    if raw in {"era5", "mswep", "cmfd", "custom_tif"}:
        return raw
    configured = configured_precip_source(config)
    if configured in {"era5", "mswep", "cmfd", "custom_tif"}:
        return configured
    return "era5"


def effective_precip_source(source: str) -> str:
    key = str(source).strip().lower()
    if key in {"era5", "cmfd"}:
        return key
    if key == "mswep":
        return "mswep"
    return "era5"


PRECIP_SOURCE_LABELS = {
    "era5": "ERA5 自动下载降水",
    "mswep": "MSWEP 本地原始文件",
    "cmfd": "CMFD 本地原始文件",
    "custom_tif": "本地降水栅格目录",
}


def display_precip_source_label(source: str) -> str:
    key = str(source or "").strip().lower()
    return PRECIP_SOURCE_LABELS.get(key, str(source or "").strip() or "MSWEP 格点降水")


def display_runtime_precip_label(config: dict[str, Any]) -> str:
    configured = configured_precip_source(config)
    if configured == "custom_tif":
        return "工程独立降水目录（本地导入）"
    return display_precip_source_label(effective_precip_source(configured))


def effective_precip_paths(
    config: dict[str, Any],
    profile: str | None = None,
    precip_source: Any = None,
) -> tuple[Path, Path, str]:
    active_profile = profile or current_profile(config)
    paths = build_profile_paths(config, active_profile)
    selected_source = resolve_precip_source(config, precip_source)
    if selected_source == "era5":
        return Path(paths["aligned_prec_era5_base_dir"]), Path(paths["aligned_prec_era5_dir"]), selected_source
    if selected_source == "custom_tif":
        return Path(paths["aligned_prec_custom_base_dir"]), Path(paths["aligned_prec_custom_dir"]), selected_source
    if selected_source == "cmfd":
        return Path(paths["aligned_prec_cmfd_base_dir"]), Path(paths["aligned_prec_cmfd_dir"]), selected_source
    return Path(paths["aligned_prec_base_dir"]), Path(paths["aligned_prec_dir"]), selected_source


def seed_workspace_runtime_dirs(config: dict[str, Any]) -> None:
    runtime_root = str(config.get("运行目录", "")).strip()
    if not runtime_root:
        return
    profile = current_profile(config)
    paths = build_profile_paths(config, profile)
    precip_base_dir, precip_effective_dir, _ = effective_precip_paths(config, profile)
    required_dirs = [
        Path(paths["workspace_root"]),
        Path(paths["data_root"]),
        Path(paths["gis_dir"]),
        Path(paths["observed_dir"]),
        Path(paths["raw_root"]),
        Path(paths["aligned_dir"]),
        Path(precip_base_dir),
        Path(precip_effective_dir),
        Path(paths["aligned_temp_dir"]),
        Path(paths["aligned_evap_dir"]),
        Path(paths["results_root"]),
    ]

    created: set[Path] = set()
    for dir_path in required_dirs:
        resolved = dir_path.resolve(strict=False)
        if resolved in created:
            continue
        dir_path.mkdir(parents=True, exist_ok=True)
        created.add(resolved)


def stage_vector_shapefile(
    config: dict[str, Any],
    raw_path: Any,
    *,
    role: str,
    config_path: Path | None = None,
) -> Path:
    """Copy a shapefile bundle into the active workspace GIS directory."""
    src = resolve_any_path(str(raw_path), must_exist=True)
    if not src.is_file():
        raise ValueError(f"shp 路径不是文件：{src}")
    if src.suffix.lower() != ".shp":
        raise ValueError(f"当前只支持 .shp 文件：{src}")

    resolved_config = replace_placeholders(dict(config))
    if config_path is not None:
        resolved_config["_config_path"] = str(config_path.resolve(strict=False))
    elif not str(resolved_config.get("_config_path", "")).strip():
        resolved_config["_config_path"] = str((WORKSPACE_DIR / "_staging_context.json").resolve(strict=False))
    if not str(resolved_config.get("运行目录", "")).strip():
        raise ValueError("缺少运行目录，无法归档 shp 文件。")

    paths = build_workspace_paths(resolved_config)
    gis_dir = Path(paths["gis_dir"]).resolve(strict=False)
    if role == "basin":
        dst = (gis_dir / "basin.shp").resolve(strict=False)
    elif role == "glacier":
        dst = (gis_dir / "glacier_shp" / "glacier.shp").resolve(strict=False)
    else:
        raise ValueError(f"未知 shp 类型：{role}")
    dst.parent.mkdir(parents=True, exist_ok=True)

    copied = False
    for suffix in VECTOR_BUNDLE_SUFFIXES:
        sidecar = src.with_suffix(suffix)
        if not sidecar.exists():
            continue
        target = dst.with_suffix(suffix)
        if sidecar.resolve(strict=False) != target.resolve(strict=False):
            shutil.copy2(sidecar, target)
        copied = True
    if not copied:
        shutil.copy2(src, dst)
    return dst


def stage_observed_runoff_file(config: dict[str, Any], raw_path: Any, *, config_path: Path | None = None) -> Path:
    """Copy the selected observed runoff file into the active workspace."""
    src = resolve_any_path(str(raw_path), must_exist=True)
    if not src.is_file():
        raise ValueError(f"观测径流路径不是文件：{src}")
    if src.suffix.lower() not in OBSERVED_FLOW_SUFFIXES:
        allowed = ", ".join(sorted(OBSERVED_FLOW_SUFFIXES))
        raise ValueError(f"观测径流文件类型不支持：{src.suffix or '(无扩展名)'}，支持 {allowed}")

    resolved_config = replace_placeholders(dict(config))
    if config_path is not None:
        resolved_config["_config_path"] = str(config_path.resolve(strict=False))
    elif not str(resolved_config.get("_config_path", "")).strip():
        resolved_config["_config_path"] = str((WORKSPACE_DIR / "_staging_context.json").resolve(strict=False))
    if not str(resolved_config.get("运行目录", "")).strip():
        raise ValueError("缺少运行目录，无法归档观测径流文件。")
    paths = build_workspace_paths(resolved_config)
    observed_dir = Path(paths["observed_dir"]).resolve(strict=False)
    observed_dir.mkdir(parents=True, exist_ok=True)
    dst = (observed_dir / src.name).resolve(strict=False)

    if src.resolve(strict=False) != dst:
        shutil.copy2(src, dst)
    return dst


def meteo_state_path(config: dict[str, Any], profile: str | None = None) -> Path:
    active_profile = profile or current_profile(config)
    paths = build_profile_paths(config, active_profile)
    return Path(paths["aligned_dir"]) / METEO_STATE_FILENAME


def read_meteo_state(config: dict[str, Any], profile: str | None = None) -> dict[str, Any]:
    path = meteo_state_path(config, profile)
    if not path.exists():
        return {}
    try:
        data = read_json_file(path)
    except Exception:
        return {}
    if isinstance(data, dict):
        data["_state_path"] = str(path)
        return data
    return {}


def write_meteo_state(config: dict[str, Any], data: dict[str, Any], profile: str | None = None) -> Path:
    path = meteo_state_path(config, profile)
    payload = dict(data)
    payload.pop("_state_path", None)
    write_json_file(path, payload)
    return path


def clear_meteo_state(config: dict[str, Any], profile: str | None = None) -> None:
    path = meteo_state_path(config, profile)
    if path.exists():
        path.unlink()


def _latest_progress_row(path: Path) -> dict[str, str] | None:
    try:
        with path.open("r", encoding="utf-8-sig", newline="") as handle:
            rows = list(csv.DictReader(handle))
    except Exception:
        return None
    return rows[-1] if rows else None


def _progress_history_rows(path: Path, limit: int = 160) -> list[dict[str, float | int | None]]:
    try:
        with path.open("r", encoding="utf-8-sig", newline="") as handle:
            rows = list(csv.DictReader(handle))
    except Exception:
        return []
    history: list[dict[str, float | int | None]] = []
    for row in rows[-limit:]:
        history.append(
            {
                "gen": int(float(row.get("gen", 0) or 0)),
                "nse_cal": safe_float(row.get("nse_cal")),
                "nse_val": safe_float(row.get("nse_val")),
                "obj": safe_float(row.get("obj")),
                "elapsed_sec": safe_float(row.get("elapsed_sec")),
            }
        )
    return history


def _progress_stage_name(path: Path) -> str:
    stem = path.stem.lower()
    if "refine" in stem:
        return "refine"
    if "mc" in stem:
        return "mc"
    return "global"


def _progress_stage_maxiter(task: TaskRecord, stage: str) -> int:
    if stage == "refine":
        return int(task.metadata.get("refine_maxiter", 0) or 0)
    if stage == "mc":
        return int(task.metadata.get("mc_samples", 0) or 0)
    if str(task.metadata.get("method", "")).strip().lower() == "mc_only":
        return int(task.metadata.get("mc_samples", 0) or 0)
    return int(task.metadata.get("maxiter", 0) or 0)


def task_progress_snapshot(task: TaskRecord) -> dict[str, Any] | None:
    logs_dir_raw = str(task.metadata.get("logs_dir", "")).strip()
    if task.task_type != "calibration" or not logs_dir_raw:
        return None
    logs_dir = Path(logs_dir_raw)
    if not logs_dir.exists():
        return None
    candidates = [path for path in logs_dir.glob("progress*.csv") if path.stat().st_mtime >= task.created_at - 5]
    if not candidates:
        return None
    candidate_rows: list[tuple[Path, dict[str, str]]] = []
    for candidate in candidates:
        candidate_last = _latest_progress_row(candidate)
        if candidate_last:
            candidate_rows.append((candidate, candidate_last))
    if not candidate_rows:
        return None
    latest, last_row = max(candidate_rows, key=lambda item: item[0].stat().st_mtime)
    stage = _progress_stage_name(latest)
    maxiter = _progress_stage_maxiter(task, stage)
    gen = int(float(last_row.get("gen", 0) or 0))
    elapsed_sec = float(last_row.get("elapsed_sec", 0.0) or 0.0)
    eta_sec = None
    if maxiter > 0 and gen > 0 and gen <= maxiter and elapsed_sec > 0:
        eta_sec = max(0.0, elapsed_sec / gen * (maxiter - gen))
    stage_snapshots: dict[str, Any] = {}
    for candidate, candidate_last in sorted(candidate_rows, key=lambda item: item[0].stat().st_mtime):
        candidate_stage = _progress_stage_name(candidate)
        candidate_gen = int(float(candidate_last.get("gen", 0) or 0))
        candidate_elapsed = float(candidate_last.get("elapsed_sec", 0.0) or 0.0)
        candidate_maxiter = _progress_stage_maxiter(task, candidate_stage)
        candidate_eta = None
        if candidate_maxiter > 0 and candidate_gen > 0 and candidate_gen <= candidate_maxiter and candidate_elapsed > 0:
            candidate_eta = max(0.0, candidate_elapsed / candidate_gen * (candidate_maxiter - candidate_gen))
        stage_snapshots[candidate_stage] = {
            "file": str(candidate),
            "stage": candidate_stage,
            "gen": candidate_gen,
            "maxiter": candidate_maxiter or None,
            "nse_cal": safe_float(candidate_last.get("nse_cal")),
            "nse_val": safe_float(candidate_last.get("nse_val")),
            "obj": safe_float(candidate_last.get("obj")),
            "convergence": safe_float(candidate_last.get("convergence")),
            "elapsed_sec": candidate_elapsed,
            "eta_sec": candidate_eta,
            "timestamp": candidate_last.get("timestamp"),
            "history": _progress_history_rows(candidate),
        }
    return {
        "file": str(latest),
        "stage": stage,
        "gen": gen,
        "maxiter": maxiter or None,
        "nse_cal": safe_float(last_row.get("nse_cal")),
        "nse_val": safe_float(last_row.get("nse_val")),
        "obj": safe_float(last_row.get("obj")),
        "convergence": safe_float(last_row.get("convergence")),
        "elapsed_sec": elapsed_sec,
        "eta_sec": eta_sec,
        "timestamp": last_row.get("timestamp"),
        "history": _progress_history_rows(latest),
        "stages": stage_snapshots,
    }


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


def _normalize_manual_preset_source_run(
    source_run_path_raw: Any,
    source_run_name_raw: Any = "",
) -> tuple[str, str]:
    source_run_path = str(source_run_path_raw or "").strip()
    source_run_name = str(source_run_name_raw or "").strip()
    if not source_run_path:
        return "", source_run_name
    if not source_run_name:
        try:
            source_run_name = Path(str(replace_placeholders(source_run_path))).name
        except Exception:
            source_run_name = Path(source_run_path).name
    resolved_source_run = _resolve_source_run_reference(source_run_path, source_run_name)
    if resolved_source_run:
        return to_portable_path(resolved_source_run), source_run_name
    try:
        fallback = remap_legacy_project_path(str(replace_placeholders(source_run_path)))
    except Exception:
        fallback = source_run_path
    return to_portable_path(str(fallback or source_run_path)), source_run_name


def manual_preset_store_path(config_path_raw: str, scope: str = "workspace") -> Path:
    if str(scope or "").strip().lower() in {"global", "shared", "公共", "public"}:
        return GLOBAL_PARAMETER_LIBRARY_PATH
    cfg_path = resolve_any_path(config_path_raw, must_exist=True)
    config = read_runtime_config(cfg_path)
    results_root = Path(build_workspace_paths(config)["results_root"])
    return results_root / "manual_calibration_presets.json"


def _normalize_preset_scope(scope: Any) -> str:
    raw = str(scope or "workspace").strip().lower()
    if raw in {"global", "shared", "公共", "public"}:
        return "global"
    if raw in {"all", "both", "全部"}:
        return "all"
    return "workspace"


def load_manual_preset_store(config_path_raw: str, scope: str = "workspace") -> dict[str, Any]:
    normalized_scope = _normalize_preset_scope(scope)
    if normalized_scope == "all":
        raise ValueError("load_manual_preset_store 不支持 scope=all，请使用 list_manual_presets。")
    store_path = manual_preset_store_path(config_path_raw, normalized_scope)
    if not store_path.exists():
        return {"presets": [], "scope": normalized_scope}
    data = read_json_file(store_path)
    if not isinstance(data, dict):
        return {"presets": [], "scope": normalized_scope}
    presets = data.get("presets", [])
    if not isinstance(presets, list):
        presets = []
    normalized_presets: list[dict[str, Any]] = []
    for item in presets:
        if not isinstance(item, dict):
            continue
        current = dict(item)
        preset_id = str(current.get("parameter_set_id") or current.get("id") or "").strip()
        if preset_id:
            current["parameter_set_id"] = preset_id
        if "parameters" not in current and isinstance(current.get("params"), dict):
            current["parameters"] = dict(current.get("params", {}))
        if not current.get("source_workspace") and isinstance(current.get("context"), dict):
            current["source_workspace"] = str(current["context"].get("workspace_name", "") or "").strip()
        source_run_path, source_run_name = _normalize_manual_preset_source_run(
            current.get("source_run_path"),
            current.get("source_run_name"),
        )
        if source_run_path:
            current["source_run_path"] = source_run_path
        if source_run_name:
            current["source_run_name"] = source_run_name
        current["scope"] = str(current.get("scope", normalized_scope) or normalized_scope)
        normalized_presets.append(current)
    data["presets"] = normalized_presets
    data["scope"] = normalized_scope
    return data


def write_manual_preset_store(config_path_raw: str, data: dict[str, Any], scope: str = "workspace") -> Path:
    normalized_scope = _normalize_preset_scope(scope)
    if normalized_scope == "all":
        raise ValueError("写入参数集时必须指定 workspace 或 global。")
    store_path = manual_preset_store_path(config_path_raw, normalized_scope)
    write_json_file(store_path, data)
    return store_path


def list_manual_presets(config_path_raw: str, calibration_profile: str | None = None, scope: str = "workspace") -> dict[str, Any]:
    cfg_path = resolve_any_path(config_path_raw, must_exist=True)
    normalized_scope = _normalize_preset_scope(scope)
    if normalized_scope == "all":
        workspace_presets = list_manual_presets(str(cfg_path), calibration_profile, scope="workspace")
        global_presets = list_manual_presets(str(cfg_path), calibration_profile, scope="global")
        presets = sorted(
            list(workspace_presets.get("presets", [])) + list(global_presets.get("presets", [])),
            key=lambda item: float(item.get("updated_at", 0.0)),
            reverse=True,
        )
        return {
            "config_path": str(cfg_path),
            "scope": "all",
            "store_path": workspace_presets.get("store_path"),
            "global_store_path": global_presets.get("store_path"),
            "calibration_profile": str(calibration_profile or "").strip().lower() or None,
            "presets": presets,
        }
    data = load_manual_preset_store(str(cfg_path), normalized_scope)
    profile_filter = str(calibration_profile or "").strip().lower()
    presets = list(data.get("presets", []))
    if profile_filter:
        presets = [
            item for item in presets
            if (not str(item.get("calibration_profile", "")).strip())
            or str(item.get("calibration_profile", "")).strip().lower() == profile_filter
        ]
    presets = sorted(presets, key=lambda item: float(item.get("updated_at", 0.0)), reverse=True)
    return {
        "config_path": str(cfg_path),
        "store_path": str(manual_preset_store_path(str(cfg_path), normalized_scope)),
        "scope": normalized_scope,
        "calibration_profile": profile_filter or None,
        "presets": presets,
    }


def _format_epoch_text(value: Any) -> str:
    try:
        return time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(float(value)))
    except Exception:
        return ""


def _source_run_metadata_for_preset(source_run_raw: Any) -> tuple[dict[str, Any], Path | None, Path | None]:
    raw = str(source_run_raw or "").strip()
    if not raw:
        return {}, None, None
    try:
        source_name = Path(str(replace_placeholders(raw))).name
    except Exception:
        source_name = Path(raw).name
    try:
        resolved = _resolve_source_run_reference(raw, source_name)
        run_dir = resolve_any_path(resolved, must_exist=False)
    except Exception:
        try:
            run_dir = Path(str(replace_placeholders(raw))).expanduser().resolve(strict=False)
        except Exception:
            return {}, None, None
    metadata_path = run_dir / "metadata.json"
    if not metadata_path.exists():
        return {}, run_dir, None
    try:
        metadata, resolved_config = normalize_run_metadata(read_json_file(metadata_path), run_path=run_dir)
        return metadata, run_dir, resolved_config
    except Exception:
        try:
            return read_json_file(metadata_path), run_dir, None
        except Exception:
            return {}, run_dir, None


def _period_value(time_cfg: dict[str, Any], config_time: dict[str, Any], *keys: str) -> str:
    for key in keys:
        value = time_cfg.get(key)
        if value not in (None, ""):
            return str(value)
    for key in keys:
        value = config_time.get(key)
        if value not in (None, ""):
            return str(value)
    return ""


def _parameter_period_summary(config: dict[str, Any], metadata: dict[str, Any]) -> dict[str, Any]:
    time_cfg = dict(metadata.get("time_config", {}) or {})
    config_time = dict(config.get("时间", {}) or {})
    step_hours = (
        time_cfg.get("time_step_hours")
        or time_cfg.get("时间步长_小时")
        or config.get("时间步长_小时")
        or 24.0
    )
    return {
        "warmup_start": _period_value(time_cfg, config_time, "warmup_start", "预热开始"),
        "warmup_end": _period_value(time_cfg, config_time, "warmup_end", "预热结束"),
        "calibration_start": _period_value(time_cfg, config_time, "calib_start", "calibration_start", "率定开始"),
        "calibration_end": _period_value(time_cfg, config_time, "calib_end", "calibration_end", "率定结束"),
        "validation_start": _period_value(time_cfg, config_time, "valid_start", "validation_start", "验证开始"),
        "validation_end": _period_value(time_cfg, config_time, "valid_end", "validation_end", "验证结束"),
        "time_step_hours": normalize_time_step_hours(step_hours),
    }


def _parameter_metric_summary(metadata: dict[str, Any]) -> dict[str, Any]:
    metrics = dict(metadata.get("metrics", {}) or {})
    summary: dict[str, Any] = {}
    for period in ("calibration", "validation"):
        item = metrics.get(period)
        if not isinstance(item, dict):
            continue
        summary[period] = {
            key: item.get(key)
            for key in ("nse", "kge", "pbias", "rmse", "r2")
            if item.get(key) is not None
        }
    return summary


def save_manual_preset(payload: dict[str, Any]) -> dict[str, Any]:
    config_path_raw = str(payload.get("config_path", "")).strip()
    if not config_path_raw:
        raise ValueError("缺少 config_path。")
    name = str(payload.get("name", "")).strip()
    if not name:
        raise ValueError("缺少参数集名称。")
    config_path = resolve_any_path(config_path_raw, must_exist=True)
    config = read_runtime_config(config_path)
    scope = _normalize_preset_scope(payload.get("scope", "workspace"))
    if scope == "all":
        scope = "workspace"
    calibration_profile = resolve_profile(config, str(payload.get("calibration_profile", "")).strip().lower() or None)
    raw_params = dict(payload.get("params", {}))
    params = sanitize_param_values(raw_params)
    params_adjusted = False
    objective_mode = profile_runner.resolve_objective_mode(config, payload.get("objective_mode", None), calibration_profile)
    param_bounds_profile = profile_runner.resolve_param_bounds_profile(
        config,
        payload.get("param_bounds_profile", None),
        calibration_profile,
    )
    runtime_prec_source = profile_runner.resolve_runtime_precip_source(config, payload.get("prec_source", None))
    glacier_mode = str(payload.get("glacier_mode", "inline")).strip().lower() or "inline"
    try:
        cli_args = _build_forward_runtime_cli_args(
            config_path,
            calibration_profile,
            prec_source=runtime_prec_source,
            glacier_mode=glacier_mode,
            objective_mode=objective_mode,
        )
        module = profile_runner.load_legacy_module(profile_runner.old_script_path(config, "model", "calibrate_hbv_cryo.py"))
        profile_runner.patch_runtime_environment(module, config, calibration_profile, cli_args)
        profile_runner.patch_profile_behavior(module, config, calibration_profile, objective_mode, param_bounds_profile)
        configure_time_step = getattr(module, "configure_time_step", None)
        if callable(configure_time_step):
            configure_time_step()
        _, params, params_adjusted = build_runtime_param_vector(module, raw_params)
    except Exception:
        params_adjusted = False
    now = time.time()
    data = load_manual_preset_store(config_path_raw, scope)
    presets = list(data.get("presets", []))
    source_run_path, source_run_name = _normalize_manual_preset_source_run(payload.get("run_path", ""))
    source_metadata, source_run_dir, source_resolved_config = _source_run_metadata_for_preset(payload.get("run_path", ""))
    existing = next(
        (
            item for item in presets
            if str(item.get("name", "")).strip() == name
            and str(item.get("calibration_profile", "")).strip().lower() == calibration_profile
            and str(item.get("scope", scope)).strip().lower() == scope
        ),
        None,
    )
    if existing is None:
        existing = {"id": uuid.uuid4().hex[:10], "created_at": now}
        presets.append(existing)
    created_at = float(existing.get("created_at", now) or now)
    parameter_set_id = str(existing.get("parameter_set_id") or existing.get("id") or uuid.uuid4().hex[:10]).strip()
    existing["id"] = str(existing.get("id") or parameter_set_id)
    source_run_type = ""
    source_run_type_label = ""
    if source_metadata:
        try:
            source_studio_compatible = is_studio_editable_metadata(source_metadata, source_resolved_config)
        except Exception:
            source_studio_compatible = False
        source_run_type = _run_kind_from_metadata(source_metadata, source_studio_compatible)
        source_run_type_label = _run_kind_label(source_run_type)
    meteo_cfg = dict(config.get(METEO_KEY, {}) or {})
    source_workspace = (
        _workspace_name_for_summary(source_metadata, source_resolved_config)
        if source_metadata
        else str(config.get("流域名称", "") or Path(config_path).stem)
    )
    if not source_workspace:
        source_workspace = str(config.get("流域名称", "") or Path(config_path).stem)
    source_workspace_config_raw = source_metadata.get("workspace_config") if source_metadata else ""
    source_workspace_config = str(source_workspace_config_raw or config_path.resolve(strict=False))
    source_run_id = str(source_metadata.get("run_id") or (source_run_dir.name if source_run_dir is not None else source_run_name) or "").strip()
    glacier_enabled = dict(dict(source_metadata.get("optional_modules", {}) or {}).get("glacier", {}) or {}).get("enabled")
    if glacier_enabled is None:
        glacier_enabled = glacier_mode != "off"
    existing.update(
        {
            "parameter_set_id": parameter_set_id,
            "name": name,
            "scope": scope,
            "params": params,
            "parameters": params,
            "calibration_profile": calibration_profile,
            "params_adjusted": bool(params_adjusted),
            "objective_mode": objective_mode,
            "param_bounds_profile": param_bounds_profile,
            "param_bounds_profile_label": profile_runner.PARAM_BOUNDS_PROFILE_LABELS.get(
                param_bounds_profile,
                param_bounds_profile,
            ),
            "prec_source": runtime_prec_source,
            "glacier_mode": glacier_mode,
            "created_at": created_at,
            "created_at_text": _format_epoch_text(created_at),
            "updated_at": now,
            "updated_at_text": _format_epoch_text(now),
            "source_run_path": source_run_path,
            "source_run_name": source_run_name,
            "source_workspace": source_workspace,
            "source_workspace_config": source_workspace_config,
            "source_run_id": source_run_id,
            "source_run_type": source_run_type,
            "source_run_type_label": source_run_type_label,
            "time_step": PROFILE_LABELS.get(calibration_profile, calibration_profile),
            "time_step_hours": normalize_time_step_hours(config.get("时间步长_小时", 24.0)),
            "meteo_source": runtime_prec_source,
            "precipitation_strategy": str(meteo_cfg.get(METEO_PRECIP_MODE_KEY, "grid_only")),
            "glacier_enabled": bool(glacier_enabled),
            "period_summary": _parameter_period_summary(config, source_metadata),
            "metrics": _parameter_metric_summary(source_metadata),
            "notes": str(payload.get("notes", "")).strip(),
            "context": {
                "workspace_name": str(config.get("流域名称", "") or Path(config_path).stem),
                "workspace_config": str(config_path.resolve(strict=False)),
                "time_step_hours": normalize_time_step_hours(config.get("时间步长_小时", 24.0)),
                "task_time_basis": task_time_basis(config, context="calibration"),
                "precipitation_mode": str(dict(config.get(METEO_KEY, {}) or {}).get(METEO_PRECIP_MODE_KEY, "grid_only")),
            },
        }
    )
    data["presets"] = presets
    store_path = write_manual_preset_store(config_path_raw, data, scope)
    return {"saved": True, "preset": existing, "store_path": str(store_path)}


def find_manual_preset(config_path_raw: str, preset_id: str) -> dict[str, Any]:
    for scope in ("workspace", "global"):
        data = load_manual_preset_store(config_path_raw, scope)
        for item in data.get("presets", []):
            if str(item.get("id", "")).strip() == preset_id or str(item.get("parameter_set_id", "")).strip() == preset_id:
                item = dict(item)
                item["scope"] = str(item.get("scope", scope) or scope)
                return item
    raise FileNotFoundError(f"未找到参数集：{preset_id}")


def delete_manual_preset(payload: dict[str, Any]) -> dict[str, Any]:
    config_path_raw = str(payload.get("config_path", "")).strip()
    preset_id = str(payload.get("preset_id", "")).strip()
    if not config_path_raw or not preset_id:
        raise ValueError("缺少 config_path 或 preset_id。")
    scope = _normalize_preset_scope(payload.get("scope", "workspace"))
    if scope == "all":
        existing = find_manual_preset(config_path_raw, preset_id)
        scope = _normalize_preset_scope(existing.get("scope", "workspace"))
    data = load_manual_preset_store(config_path_raw, scope)
    presets = [item for item in data.get("presets", []) if str(item.get("id", "")).strip() != preset_id]
    data["presets"] = presets
    store_path = write_manual_preset_store(config_path_raw, data, scope)
    return {"deleted": True, "preset_id": preset_id, "store_path": str(store_path)}


def resolve_any_path(raw_path: str, *, must_exist: bool = False) -> Path:
    text = str(raw_path or "").strip()
    if not text:
        raise ValueError("缺少路径参数。")
    expanded = replace_placeholders(text)
    expanded = remap_legacy_project_path(expanded)
    path = Path(str(expanded)).expanduser()
    if not path.is_absolute():
        path = (GUI_ROOT / path).resolve()
    else:
        path = path.resolve(strict=False)
    if must_exist and not path.exists():
        raise FileNotFoundError(str(path))
    return path


def ensure_within(root: Path, candidate: Path) -> Path:
    resolved_root = root.resolve()
    resolved = candidate.resolve(strict=False)
    try:
        resolved.relative_to(resolved_root)
    except ValueError as exc:
        raise ValueError(f"路径超出允许范围：{resolved}") from exc
    return resolved


def is_within_root(root: Path, candidate: Path) -> bool:
    try:
        candidate.resolve(strict=False).relative_to(root.resolve(strict=False))
        return True
    except ValueError:
        return False
    except Exception:
        return False


def is_within_current_project(candidate: Path) -> bool:
    return any(is_within_root(root, candidate) for root in (WORKSPACE_DIR, GUI_ROOT, PROJECT_ROOT))


def to_display_path(path: Path) -> str:
    for base in (GUI_ROOT, PROJECT_ROOT):
        try:
            return str(path.resolve().relative_to(base.resolve())).replace("\\", "/")
        except ValueError:
            continue
    return str(path.resolve())


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


def _placeholder_roots_for_config_path(config_path: Path | str | None) -> tuple[Path, Path]:
    try:
        path = Path(config_path).resolve(strict=False) if config_path else None
    except Exception:
        path = None
    if path is not None:
        for candidate in [path] + list(path.parents):
            if candidate.name.lower() == "hbv-studio":
                gui_root = candidate.resolve(strict=False)
                return gui_root.parent.resolve(strict=False), gui_root
    return PROJECT_ROOT, GUI_ROOT


def replace_placeholders(value: Any, *, project_root: Path | None = None, gui_root: Path | None = None) -> Any:
    project_root = project_root or PROJECT_ROOT
    gui_root = gui_root or GUI_ROOT
    placeholders = {
        "__PROJECT_ROOT__": str(project_root),
        "__GUI_ROOT__": str(gui_root),
    }
    if isinstance(value, dict):
        return {
            key: replace_placeholders(item, project_root=project_root, gui_root=gui_root)
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [replace_placeholders(item, project_root=project_root, gui_root=gui_root) for item in value]
    if isinstance(value, str):
        updated = value
        for old, new in placeholders.items():
            updated = updated.replace(old, new)
        return updated
    return value


def remap_legacy_project_path(
    raw_value: Any,
    *,
    preserve_project_root: Path | None = None,
    preserve_gui_root: Path | None = None,
) -> Any:
    if not isinstance(raw_value, str):
        return raw_value
    text = str(raw_value or "").strip()
    if (not text) or ("__PROJECT_ROOT__" in text) or ("__GUI_ROOT__" in text):
        return raw_value
    candidate = Path(text.replace("/", "\\")).expanduser()
    if not candidate.is_absolute():
        return raw_value
    try:
        if candidate.exists():
            return raw_value
    except Exception:
        return raw_value
    for root in (preserve_gui_root, preserve_project_root):
        if root is None:
            continue
        try:
            candidate.resolve(strict=False).relative_to(Path(root).resolve(strict=False))
            return raw_value
        except Exception:
            pass

    normalized = str(candidate).replace("/", "\\")
    lowered = normalized.lower()
    markers = (
        (f"\\{GUI_ROOT.name.lower()}\\", GUI_ROOT),
        (f"\\{PROJECT_ROOT.name.lower()}\\", PROJECT_ROOT),
    )
    for marker, root in markers:
        idx = lowered.find(marker)
        if idx < 0:
            suffix_marker = marker.rstrip("\\")
            if not lowered.endswith(suffix_marker):
                continue
            suffix = ""
        else:
            suffix = normalized[idx + len(marker):].lstrip("\\/")
        remapped = (root / suffix) if suffix else root
        try:
            return str(remapped.resolve(strict=False))
        except Exception:
            return str(remapped)
    legacy_markers = (
        ("\\hbv-studio\\", GUI_ROOT),
        ("\\workspaces\\", GUI_ROOT / "workspaces"),
        ("\\运行目录\\", PROJECT_ROOT / "运行目录"),
        ("\\runtime\\", PROJECT_ROOT / "运行目录"),
        ("\\hbv-cryo\\", PROJECT_ROOT / "HBV-Cryo"),
        ("\\数据准备\\", PROJECT_ROOT / "数据准备"),
        ("\\基础数据\\", PROJECT_ROOT / "基础数据"),
    )
    for marker, root in legacy_markers:
        idx = lowered.find(marker)
        if idx < 0:
            suffix_marker = marker.rstrip("\\")
            if not lowered.endswith(suffix_marker):
                continue
            suffix = ""
        else:
            suffix = normalized[idx + len(marker):].lstrip("\\/")
        remapped = (root / suffix) if suffix else root
        try:
            return str(remapped.resolve(strict=False))
        except Exception:
            return str(remapped)
    return raw_value


def normalize_legacy_project_paths(
    value: Any,
    parent_key: str = "",
    *,
    preserve_project_root: Path | None = None,
    preserve_gui_root: Path | None = None,
) -> Any:
    if isinstance(value, dict):
        return {
            key: normalize_legacy_project_paths(
                item,
                str(key),
                preserve_project_root=preserve_project_root,
                preserve_gui_root=preserve_gui_root,
            )
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [
            normalize_legacy_project_paths(
                item,
                parent_key,
                preserve_project_root=preserve_project_root,
                preserve_gui_root=preserve_gui_root,
            )
            for item in value
        ]
    if isinstance(value, str):
        key = str(parent_key or "").strip().lower()
        if (
            key.endswith(("_csv", "_shp", "_tif", "_dir", "_path"))
            or ("目录" in key)
            or key in {"运行目录", "basin_shp", "obs_csv", "dem_tif", "glacier_shp"}
        ):
            return remap_legacy_project_path(
                value,
                preserve_project_root=preserve_project_root,
                preserve_gui_root=preserve_gui_root,
            )
    return value


def normalize_time_step_hours(value: Any) -> float:
    try:
        numeric = float(value)
    except Exception:
        numeric = 24.0
    return 1.0 if numeric <= 1.5 else 24.0


def read_json_file(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def read_runtime_config(path: Path) -> dict[str, Any]:
    data = read_json_file(path)
    project_root, gui_root = _placeholder_roots_for_config_path(path)
    data = replace_placeholders(data, project_root=project_root, gui_root=gui_root)
    data = normalize_legacy_project_paths(
        data,
        preserve_project_root=project_root,
        preserve_gui_root=gui_root,
    )
    data["_config_path"] = str(path.resolve())
    repairs: dict[str, Any] = {}
    for key in ("流域边界_shp", "冰川边界_shp"):
        vector_path, vector_recovered_from = profile_runner.resolve_vector_input_path(data, key, copy_missing=True)
        if vector_path is not None:
            data[key] = str(vector_path)
        if vector_recovered_from is not None:
            repairs[key] = {
                "resolved_path": str(vector_path),
                "recovered_from": str(vector_recovered_from),
            }
    obs_path, obs_recovered_from = profile_runner.resolve_observed_csv_path(data, copy_missing=True)
    if obs_path is not None:
        data[OBSERVED_FLOW_KEY] = str(obs_path)
    if obs_recovered_from is not None:
        repairs[OBSERVED_FLOW_KEY] = {
            "resolved_path": str(obs_path),
            "recovered_from": str(obs_recovered_from),
        }
    if (not str(data.get("冰川边界_shp", "")).strip()) and BUILTIN_GLACIER_SHP.exists():
        data["冰川边界_shp"] = str(BUILTIN_GLACIER_SHP.resolve())
    if repairs:
        data["_path_repairs"] = repairs
    return data


def _config_text_value(config: dict[str, Any], key: str) -> str:
    if not isinstance(config, dict):
        return ""
    value = config[key] if key in config else ""
    if value is None:
        return ""
    return str(value).strip()


def _append_unique_message(items: list[str], text: str) -> None:
    if text and text not in items:
        items.append(text)


def _json_safe_value(value: Any) -> Any:
    if isinstance(value, dict):
        return {key: _json_safe_value(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_json_safe_value(item) for item in value]
    if isinstance(value, tuple):
        return [_json_safe_value(item) for item in value]
    if isinstance(value, float):
        return value if math.isfinite(value) else None
    return value


def json_dumps_safe(payload: Any, *, indent: int | None = None) -> str:
    return json.dumps(_json_safe_value(payload), ensure_ascii=False, indent=indent, allow_nan=False)


def write_json_file(path: Path, data: dict[str, Any]) -> None:
    payload = dict(data)
    payload.pop("_config_path", None)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json_dumps_safe(payload, indent=2), encoding="utf-8")


def detect_time_column(frame: pd.DataFrame, preferred: str | None = None) -> str | None:
    return shared_detect_time_column(frame, preferred=preferred)


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


def detect_observed_flow_column(frame: pd.DataFrame, *, excluded: list[str] | None = None) -> str | None:
    return shared_detect_observed_flow_column(frame, excluded=excluded)


def detect_series_step_hours(timestamps: pd.Series) -> float | None:
    diffs = timestamps.sort_values().drop_duplicates().diff().dropna()
    if diffs.empty:
        return None
    median_hours = diffs.median() / pd.Timedelta(hours=1)
    if median_hours <= 1.5:
        return 1.0
    return 24.0


DATE_PATTERNS = [
    ("%Y.%m.%d.%H.%M", [r"\d{4}\.\d{2}\.\d{2}\.\d{2}\.\d{2}"]),
    ("%Y.%m.%d.%H", [r"\d{4}\.\d{2}\.\d{2}\.\d{2}"]),
    ("%Y-%m-%d %H:%M", [r"\d{4}-\d{2}-\d{2} \d{2}:\d{2}"]),
    ("%Y-%m-%dT%H:%M", [r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}"]),
    ("%Y.%m.%d", [r"\d{4}\.\d{2}\.\d{2}"]),
    ("%Y-%m-%d", [r"\d{4}-\d{2}-\d{2}"]),
]


def parse_time_from_name(name: str) -> pd.Timestamp | None:
    stem = Path(name).stem
    for fmt, patterns in DATE_PATTERNS:
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


def is_date_only_string(value: Any) -> bool:
    if not isinstance(value, str):
        return False
    text = value.strip()
    return bool(text) and (" " not in text) and ("T" not in text) and len(text) <= 10


def format_timestamp_for_display(timestamp: pd.Timestamp, step_hours: float) -> str:
    ts = pd.Timestamp(timestamp)
    if normalize_time_step_hours(step_hours) >= 24.0 and ts.hour == 0 and ts.minute == 0 and ts.second == 0:
        return ts.strftime("%Y-%m-%d")
    return ts.strftime("%Y-%m-%d %H:%M")


def expected_warmup_end(time_values: dict[str, pd.Timestamp], step_hours: float) -> pd.Timestamp | None:
    calib_start = time_values.get("率定开始")
    if calib_start is None:
        return None
    return calib_start - pd.Timedelta(hours=normalize_time_step_hours(step_hours))


def time_sequence_messages(time_values: dict[str, pd.Timestamp], step_hours: float) -> list[str]:
    messages: list[str] = []
    ordered_pairs = [
        ("预热开始", "预热结束"),
        ("预热结束", "率定开始"),
        ("率定开始", "率定结束"),
        ("率定结束", "验证开始"),
        ("验证开始", "验证结束"),
    ]
    for left, right in ordered_pairs:
        if left in time_values and right in time_values and time_values[left] > time_values[right]:
            messages.append(f"时间顺序错误：{left} 晚于 {right}")

    warmup_start = time_values.get("预热开始")
    configured_warmup_end = time_values.get("预热结束")
    expected_end = expected_warmup_end(time_values, step_hours)
    if warmup_start is not None and expected_end is not None:
        if warmup_start > expected_end:
            messages.append("预热期至少需要覆盖率定开始前 1 个时间步。")
        elif configured_warmup_end is not None and configured_warmup_end != expected_end:
            expected_label = format_timestamp_for_display(expected_end, step_hours)
            messages.append(f"时间.预热结束 必须紧邻率定开始，当前应为 {expected_label}")
    return messages


def _truthy_config(value: Any, default: bool = False) -> bool:
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


def _read_csv_flexible(path: Path) -> pd.DataFrame:
    last_error: Exception | None = None
    for encoding in ("utf-8-sig", "utf-8", "gbk", "gb18030"):
        try:
            return pd.read_csv(path, encoding=encoding)
        except UnicodeDecodeError as exc:
            last_error = exc
    if last_error is not None:
        raise last_error
    return pd.read_csv(path)


def _read_event_table_file(path: Path) -> list[dict[str, Any]]:
    suffix = path.suffix.lower()
    if suffix in {".json", ".geojson"}:
        raw = read_json_file(path)
        if isinstance(raw, dict):
            events = raw.get("事件表", raw.get("events", []))
        else:
            events = raw
        return [dict(item) for item in events if isinstance(item, dict)] if isinstance(events, list) else []
    if suffix in {".xlsx", ".xls"}:
        frame = pd.read_excel(path)
    else:
        frame = _read_csv_flexible(path)
    return [
        {str(key).strip(): value for key, value in row.items() if str(key).strip()}
        for row in frame.to_dict(orient="records")
    ]


def _flood_event_raw_config(config: dict[str, Any]) -> dict[str, Any]:
    raw = config.get("洪水事件率定", {})
    if isinstance(raw, list):
        return {"启用": bool(raw), "事件表": raw}
    if isinstance(raw, dict):
        cfg = dict(raw)
    else:
        cfg = {}
    event_mode = config.get("事件资料模式", {})
    if isinstance(event_mode, dict):
        for key, value in event_mode.items():
            cfg.setdefault(key, value)
    for key in ("事件表", "events"):
        if key in config and key not in cfg:
            cfg[key] = config.get(key)
    return cfg


def normalize_event_initial_state_policy(value: Any) -> str:
    raw = str(value or "event_warmup").strip()
    if not raw:
        return "event_warmup"
    key = raw.lower()
    return EVENT_INITIAL_STATE_POLICY_ALIASES.get(key, EVENT_INITIAL_STATE_POLICY_ALIASES.get(raw, key))


def event_initial_state_policy_summary(value: Any) -> dict[str, Any]:
    policy = normalize_event_initial_state_policy(value)
    summary = dict(EVENT_INITIAL_STATE_POLICY_SUMMARIES.get(policy, {}))
    if not summary:
        summary = {
            "label": str(value or policy or "未记录"),
            "state_continuity_between_events": False,
            "note": "按配置的事件初始条件策略处理。",
            "warning": "",
        }
    summary["policy"] = policy
    return summary


def _event_field(event: dict[str, Any], *names: str) -> Any:
    for name in names:
        if name in event and event.get(name) not in (None, ""):
            return event.get(name)
    lower_map = {str(key).strip().lower(): value for key, value in event.items()}
    for name in names:
        value = lower_map.get(str(name).strip().lower())
        if value not in (None, ""):
            return value
    return None


def _parse_event_timestamp(value: Any, *, end: bool, step_hours: float) -> pd.Timestamp | None:
    if value in (None, ""):
        return None
    ts = pd.to_datetime(value)
    if end and step_hours < 24.0 and is_date_only_string(value):
        ts = ts + pd.Timedelta(days=1) - pd.Timedelta(hours=step_hours)
    return pd.Timestamp(ts)


def _event_date_range(start: pd.Timestamp, end: pd.Timestamp, step_hours: float) -> pd.DatetimeIndex:
    if end < start:
        return pd.DatetimeIndex([])
    return pd.date_range(start, end, freq=pd.Timedelta(hours=step_hours))


def task_time_basis(config: dict[str, Any], *, context: str = "calibration") -> str:
    if context == "forecast":
        return TIME_BASIS_FORECAST_WINDOW
    raw = str(
        config.get("任务时段模式")
        or config.get("time_basis")
        or config.get("资料时段模式")
        or ""
    ).strip().lower()
    if raw in {"event", "events", "event_window", "event_windows", "flood_event", "洪水事件", "事件窗口", "事件资料"}:
        return TIME_BASIS_EVENT_WINDOWS
    if raw in {"forecast", "forecast_window", "预报", "预报窗口"}:
        return TIME_BASIS_FORECAST_WINDOW
    event_cfg = _flood_event_raw_config(config)
    event_mode = config.get("事件资料模式", {})
    event_enabled = _truthy_config(event_cfg.get("启用", event_cfg.get("enabled")), default=False)
    event_data_enabled = _truthy_config(
        event_cfg.get("事件窗口资料", event_cfg.get("event_windows_enabled")),
        default=False,
    )
    if isinstance(event_mode, dict):
        event_data_enabled = _truthy_config(
            event_mode.get("启用", event_mode.get("enabled")),
            default=event_data_enabled,
        )
    has_events = bool(event_cfg.get("事件表") or event_cfg.get("events") or event_cfg.get("事件表路径") or event_cfg.get("events_file"))
    if event_enabled and (event_data_enabled or raw in {"event_segments", "事件资料模式"}):
        return TIME_BASIS_EVENT_WINDOWS
    if raw in {"continuous", "full", "连续", "连续时段", ""}:
        return TIME_BASIS_CONTINUOUS
    return TIME_BASIS_EVENT_WINDOWS if event_data_enabled and has_events else TIME_BASIS_CONTINUOUS


def normalized_flood_events(config: dict[str, Any], *, step_hours: float | None = None) -> dict[str, Any]:
    step = normalize_time_step_hours(step_hours if step_hours is not None else config.get("时间步长_小时", 24.0))
    cfg = _flood_event_raw_config(config)
    raw_events = cfg.get("事件表", cfg.get("events", []))
    warnings: list[str] = []
    errors: list[str] = []
    initial_state = event_initial_state_policy_summary(
        cfg.get(
            "初始条件策略",
            cfg.get("initial_state_policy", cfg.get("event_initial_state_policy", "event_warmup")),
        )
    )
    if initial_state.get("warning"):
        warnings.append(str(initial_state["warning"]))
    event_file_raw = str(cfg.get("事件表路径", cfg.get("events_file", cfg.get("event_file", ""))) or "").strip()
    event_file = _resolve_config_related_path(config, event_file_raw) if event_file_raw else None
    if event_file_raw:
        if event_file is None or not event_file.exists():
            errors.append(f"洪水事件表文件不存在：{event_file_raw}")
            raw_events = []
        else:
            try:
                raw_events = _read_event_table_file(event_file)
            except Exception as exc:
                errors.append(f"洪水事件表读取失败：{exc}")
                raw_events = []
    if isinstance(raw_events, dict):
        raw_events = raw_events.get("events", raw_events.get("事件表", []))
    if not isinstance(raw_events, list):
        raw_events = []

    events: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    for index, raw_event in enumerate(raw_events, start=1):
        if not isinstance(raw_event, dict):
            warnings.append(f"第 {index} 条事件不是对象，已跳过。")
            continue
        event = dict(raw_event)
        token = json.dumps(event, ensure_ascii=False, sort_keys=True, default=str).encode("utf-8")
        event_id = str(_event_field(event, "event_id", "id", "编号") or "").strip()
        name = str(_event_field(event, "name", "名称", "事件名称") or "").strip()
        if not event_id:
            event_id = name or f"event_{hashlib.sha1(token).hexdigest()[:8]}"
        purpose_raw = str(_event_field(event, "purpose", "用途", "类型", "type") or "calibration").strip()
        purpose = EVENT_PURPOSE_ALIASES.get(purpose_raw.lower(), purpose_raw.lower() or "calibration")
        if purpose not in {"calibration", "validation", "diagnostic"}:
            warnings.append(f"事件 {event_id} 的用途 {purpose_raw} 未识别，按 diagnostic 处理。")
            purpose = "diagnostic"
        if event_id in seen_ids:
            errors.append(f"洪水事件编号重复：{event_id}")
        seen_ids.add(event_id)
        score_start_raw = _event_field(event, "score_start", "评分开始", "事件开始", "start")
        score_end_raw = _event_field(event, "score_end", "评分结束", "事件结束", "end")
        run_start_raw = _event_field(event, "run_start", "运行开始", "预热开始", "warmup_start") or score_start_raw
        run_end_raw = _event_field(event, "run_end", "运行结束", "退水结束") or score_end_raw
        event_errors: list[str] = []
        try:
            run_start = _parse_event_timestamp(run_start_raw, end=False, step_hours=step)
            score_start = _parse_event_timestamp(score_start_raw, end=False, step_hours=step)
            score_end = _parse_event_timestamp(score_end_raw, end=True, step_hours=step)
            run_end = _parse_event_timestamp(run_end_raw, end=True, step_hours=step)
        except Exception as exc:
            run_start = score_start = score_end = run_end = None
            event_errors.append(f"事件时间无法解析：{exc}")
        if run_start is None or score_start is None or score_end is None or run_end is None:
            event_errors.append("事件缺少运行窗口或评分窗口时间。")
        elif not (run_start <= score_start <= score_end <= run_end):
            event_errors.append("事件时间顺序必须满足 run_start <= score_start <= score_end <= run_end。")
        weight = _event_field(event, "weight", "权重")
        try:
            weight_value = float(weight) if weight not in (None, "") else 1.0
        except Exception:
            weight_value = 1.0
            warnings.append(f"事件 {event_id} 的权重无法解析，按 1 处理。")
        if weight_value <= 0:
            warnings.append(f"事件 {event_id} 的权重小于等于 0，按 1 处理。")
            weight_value = 1.0
        if event_errors:
            errors.extend(f"{event_id}: {item}" for item in event_errors)
        events.append(
            {
                "event_id": event_id,
                "name": name or event_id,
                "purpose": purpose,
                "weight": weight_value,
                "run_start": run_start,
                "score_start": score_start,
                "score_end": score_end,
                "run_end": run_end,
                "raw": event,
                "valid": not event_errors,
                "time_steps_run": int(len(_event_date_range(run_start, run_end, step))) if run_start is not None and run_end is not None and run_end >= run_start else 0,
                "time_steps_score": int(len(_event_date_range(score_start, score_end, step))) if score_start is not None and score_end is not None and score_end >= score_start else 0,
            }
        )

    valid_events = sorted(
        [event for event in events if event.get("valid")],
        key=lambda item: (pd.Timestamp(item["run_start"]), str(item.get("event_id", ""))),
    )
    for left, right in zip(valid_events, valid_events[1:]):
        if left["run_end"] >= right["run_start"]:
            warnings.append(f"事件运行窗口可能重叠：{left['event_id']} 与 {right['event_id']}。")
    purpose_counts = {
        "calibration": sum(1 for event in valid_events if event.get("purpose") == "calibration"),
        "validation": sum(1 for event in valid_events if event.get("purpose") == "validation"),
        "diagnostic": sum(1 for event in valid_events if event.get("purpose") == "diagnostic"),
    }
    return {
        "enabled": _truthy_config(cfg.get("启用", cfg.get("enabled")), default=bool(events)),
        "source_file": str(event_file.resolve(strict=False)) if event_file is not None and event_file.exists() else "",
        "events": events,
        "valid_events": valid_events,
        "event_count": len(events),
        "valid_event_count": len(valid_events),
        "purpose_counts": purpose_counts,
        "warnings": warnings,
        "errors": errors,
        "time_basis": TIME_BASIS_EVENT_WINDOWS,
        "initial_state_policy": initial_state.get("policy", "event_warmup"),
        "initial_state_policy_label": initial_state.get("label", "事件预热"),
        "state_continuity_between_events": bool(initial_state.get("state_continuity_between_events")),
        "initial_state_note": initial_state.get("note", ""),
        "initial_state_warning": initial_state.get("warning", ""),
    }


def _event_window_index(events: list[dict[str, Any]], start_key: str, end_key: str, step_hours: float) -> pd.DatetimeIndex:
    values: list[pd.Timestamp] = []
    for event in events:
        start = event.get(start_key)
        end = event.get(end_key)
        if start is None or end is None or end < start:
            continue
        values.extend(list(_event_date_range(pd.Timestamp(start), pd.Timestamp(end), step_hours)))
    if not values:
        return pd.DatetimeIndex([])
    return pd.DatetimeIndex(sorted(set(pd.Timestamp(item) for item in values)))


def build_expected_time_index(config: dict[str, Any]) -> pd.DatetimeIndex | None:
    time_cfg = dict(config.get("时间", {}))
    start_raw = time_cfg.get("预热开始") or time_cfg.get("率定开始")
    end_raw = time_cfg.get("验证结束") or time_cfg.get("率定结束")
    if not start_raw or not end_raw:
        return None
    step_hours = normalize_time_step_hours(config.get("时间步长_小时", 24.0))
    step = pd.Timedelta(hours=step_hours)
    start_ts = pd.to_datetime(start_raw)
    end_ts = pd.to_datetime(end_raw)
    if step_hours < 24.0 and is_date_only_string(end_raw):
        end_ts = end_ts + pd.Timedelta(days=1) - step
    return pd.date_range(start_ts, end_ts, freq=step)


def build_expected_forcing_index(config: dict[str, Any], *, context: str = "calibration") -> pd.DatetimeIndex | None:
    step_hours = normalize_time_step_hours(config.get("时间步长_小时", 24.0))
    if task_time_basis(config, context=context) == TIME_BASIS_EVENT_WINDOWS:
        event_info = normalized_flood_events(config, step_hours=step_hours)
        index = _event_window_index(event_info.get("valid_events", []), "run_start", "run_end", step_hours)
        if len(index) > 0:
            return index
    return build_expected_time_index(config)


def build_expected_observation_index(config: dict[str, Any], *, context: str = "calibration") -> pd.DatetimeIndex | None:
    step_hours = normalize_time_step_hours(config.get("时间步长_小时", 24.0))
    if task_time_basis(config, context=context) == TIME_BASIS_EVENT_WINDOWS:
        event_info = normalized_flood_events(config, step_hours=step_hours)
        index = _event_window_index(event_info.get("valid_events", []), "score_start", "score_end", step_hours)
        if len(index) > 0:
            return index
    time_cfg = dict(config.get("时间", {}))
    start_raw = time_cfg.get("率定开始")
    end_raw = time_cfg.get("验证结束") or time_cfg.get("率定结束")
    if not start_raw or not end_raw:
        return None
    step_hours = normalize_time_step_hours(config.get("时间步长_小时", 24.0))
    step = pd.Timedelta(hours=step_hours)
    start_ts = pd.to_datetime(start_raw)
    end_ts = pd.to_datetime(end_raw)
    if step_hours < 24.0 and is_date_only_string(end_raw):
        end_ts = end_ts + pd.Timedelta(days=1) - step
    return pd.date_range(start_ts, end_ts, freq=step)


def _directory_scan_signature(directory: Path) -> tuple[str, int, int]:
    resolved = directory.resolve(strict=False)
    try:
        stat = resolved.stat()
    except (FileNotFoundError, PermissionError, OSError):
        return str(resolved), 0, 0
    mtime_ns = int(getattr(stat, "st_mtime_ns", int(stat.st_mtime * 1e9)))
    return str(resolved), mtime_ns, int(stat.st_size)


def scan_tif_time_series(directory: Path) -> dict[str, Any]:
    signature = _directory_scan_signature(directory)
    cache_key = signature[0].lower()
    with TIF_SCAN_CACHE_LOCK:
        cached = TIF_SCAN_CACHE.get(cache_key)
        if cached and cached.get("signature") == signature:
            return copy.deepcopy(cached["data"])

    tif_files = sorted(directory.glob("*.tif")) if directory.exists() else []
    invalid_files: list[str] = []
    duplicate_timestamps: dict[pd.Timestamp, list[str]] = {}
    unique_timestamps: dict[pd.Timestamp, str] = {}
    parseable_files = 0

    for tif_path in tif_files:
        timestamp = parse_time_from_name(tif_path.name)
        if timestamp is None:
            invalid_files.append(tif_path.name)
            continue
        parseable_files += 1
        if timestamp in unique_timestamps:
            duplicate_timestamps.setdefault(timestamp, [unique_timestamps[timestamp]]).append(tif_path.name)
        else:
            unique_timestamps[timestamp] = tif_path.name

    timestamps = sorted(unique_timestamps)
    result = {
        "exists": directory.exists(),
        "path": str(directory),
        "total_files": len(tif_files),
        "parseable_files": parseable_files,
        "valid_time_steps": len(timestamps),
        "invalid_files": invalid_files,
        "duplicate_timestamps": {ts: duplicate_timestamps[ts] for ts in sorted(duplicate_timestamps)},
        "timestamps": timestamps,
    }
    with TIF_SCAN_CACHE_LOCK:
        TIF_SCAN_CACHE[cache_key] = {"signature": signature, "data": copy.deepcopy(result)}
    return result


def _grid_alignment_signature(directory: Path, dem_path: Path) -> tuple[Any, ...]:
    dir_sig = _directory_scan_signature(directory)
    dem_sig = _file_signature(dem_path) if dem_path.exists() else (0, 0)
    return (dir_sig[0], dir_sig[1], dir_sig[2], str(dem_path.resolve(strict=False)), dem_sig[0], dem_sig[1])


def _sample_tif_files_for_grid_check(files: list[Path], limit: int = GRID_ALIGNMENT_SAMPLE_LIMIT) -> list[Path]:
    if len(files) <= limit:
        return list(files)
    if limit <= 1:
        return [files[0]]
    last_index = len(files) - 1
    indices: list[int] = []
    for pos in range(limit):
        idx = round(pos * last_index / (limit - 1))
        if (not indices) or idx != indices[-1]:
            indices.append(idx)
    return [files[idx] for idx in indices]


def validate_tif_grid_alignment(label: str, directory: Path, dem_path: Path) -> dict[str, Any]:
    import rasterio

    if not directory.exists() or not directory.is_dir():
        return {"label": label, "ok": True, "checked_files": 0, "error": None}
    if not dem_path.exists():
        return {"label": label, "ok": True, "checked_files": 0, "error": None}

    signature = _grid_alignment_signature(directory, dem_path)
    cache_key = str(directory.resolve(strict=False)).lower()
    with GRID_ALIGNMENT_CACHE_LOCK:
        cached = GRID_ALIGNMENT_CACHE.get(cache_key)
        if cached and cached.get("signature") == signature:
            return copy.deepcopy(cached["data"])

    tif_files = sorted(directory.glob("*.tif"))
    if not tif_files:
        result = {"label": label, "ok": True, "checked_files": 0, "error": None}
        with GRID_ALIGNMENT_CACHE_LOCK:
            GRID_ALIGNMENT_CACHE[cache_key] = {"signature": signature, "data": copy.deepcopy(result)}
        return result

    try:
        with rasterio.open(dem_path) as dem:
            dem_meta = {
                "height": dem.height,
                "width": dem.width,
                "crs": dem.crs,
                "transform": dem.transform,
            }
    except Exception as exc:
        result = {"label": label, "ok": False, "checked_files": 0, "error": f"{label}无法读取 DEM 网格：{exc}"}
        with GRID_ALIGNMENT_CACHE_LOCK:
            GRID_ALIGNMENT_CACHE[cache_key] = {"signature": signature, "data": copy.deepcopy(result)}
        return result

    files_to_check = _sample_tif_files_for_grid_check(tif_files)
    checked = 0
    error = None
    for tif_path in files_to_check:
        checked += 1
        try:
            with rasterio.open(tif_path) as src:
                same_grid = (
                    src.height == dem_meta["height"]
                    and src.width == dem_meta["width"]
                    and src.crs == dem_meta["crs"]
                    and src.transform == dem_meta["transform"]
                )
        except Exception as exc:
            error = f"{label}栅格读取失败：{tif_path.name}（{exc}）"
            break
        if not same_grid:
            error = f"{label}目录存在与 DEM 网格不一致的 tif：{tif_path.name}"
            break

    result = {
        "label": label,
        "ok": error is None,
        "checked_files": checked,
        "total_files": len(tif_files),
        "sampled_check": len(files_to_check) < len(tif_files),
        "error": error,
    }
    with GRID_ALIGNMENT_CACHE_LOCK:
        GRID_ALIGNMENT_CACHE[cache_key] = {"signature": signature, "data": copy.deepcopy(result)}
    return result


def validate_tif_time_series(
    label: str,
    directory: Path,
    step_hours: float,
    expected_index: pd.DatetimeIndex | None = None,
    time_basis_label: str = "当前配置时间范围",
) -> dict[str, Any]:
    result = scan_tif_time_series(directory)
    errors: list[str] = []
    warnings: list[str] = []

    if not result["exists"]:
        errors.append(f"{label}目录不存在：{directory}")
    elif result["total_files"] == 0:
        errors.append(f"{label}目录中没有 .tif 文件：{directory}")

    if result["invalid_files"]:
        sample = "、".join(result["invalid_files"][:3])
        errors.append(f"{label}目录有 {len(result['invalid_files'])} 个 tif 文件名无法解析时间，例如：{sample}")

    if result["duplicate_timestamps"]:
        first_ts, names = next(iter(result["duplicate_timestamps"].items()))
        sample = "、".join(names[:3])
        errors.append(f"{label}目录存在重复时间戳 {format_timestamp_for_display(first_ts, step_hours)}，例如：{sample}")

    missing_steps: list[pd.Timestamp] = []
    out_of_range_steps: list[pd.Timestamp] = []
    if expected_index is not None:
        expected_list = list(expected_index)
        expected_set = set(expected_list)
        actual_set = set(result["timestamps"])
        missing_steps = [ts for ts in expected_list if ts not in actual_set]
        out_of_range_steps = [ts for ts in result["timestamps"] if ts not in expected_set]
        if missing_steps:
            sample = "、".join(format_timestamp_for_display(ts, step_hours) for ts in missing_steps[:3])
            errors.append(f"{label}时间覆盖不完整，缺少 {len(missing_steps)} 个时间步，例如：{sample}")
        if out_of_range_steps:
            sample = "、".join(format_timestamp_for_display(ts, step_hours) for ts in out_of_range_steps[:3])
            warnings.append(f"{label}有 {len(out_of_range_steps)} 个时间步落在{time_basis_label}之外，例如：{sample}")

    result.update(
        {
            "label": label,
            "ok": len(errors) == 0,
            "errors": errors,
            "warnings": warnings,
            "missing_steps": missing_steps,
            "out_of_range_steps": out_of_range_steps,
        }
    )
    return result


def validate_forcing_bundle(
    config: dict[str, Any],
    profile: str | None = None,
    precip_source: Any = None,
) -> dict[str, Any]:
    active_profile = profile or current_profile(config)
    paths = build_profile_paths(config, active_profile)
    step_hours = normalize_time_step_hours(config.get("时间步长_小时", 24.0))
    time_basis = task_time_basis(config, context="calibration")
    time_basis_label = TIME_BASIS_LABELS.get(time_basis, "当前任务时段")
    expected_index = build_expected_forcing_index(config, context="calibration")
    event_info = normalized_flood_events(config, step_hours=step_hours) if time_basis == TIME_BASIS_EVENT_WINDOWS else None
    _, precip_dir, selected_source = effective_precip_paths(config, active_profile, precip_source=precip_source)
    precip_label = "降水（本地栅格）" if selected_source == "custom_tif" else "降水"
    directories = {
        "prec": validate_tif_time_series(precip_label, Path(precip_dir), step_hours, expected_index, time_basis_label),
        "temp": validate_tif_time_series("气温", Path(paths["aligned_temp_dir"]), step_hours, expected_index, time_basis_label),
        "evap": validate_tif_time_series("蒸散发", Path(paths["aligned_evap_dir"]), step_hours, expected_index, time_basis_label),
    }
    errors: list[str] = []
    warnings: list[str] = []
    for item in directories.values():
        errors.extend(item["errors"])
        warnings.extend(item["warnings"])
    dem_path = _workspace_dem_path(paths["gis_dir"], prefer=_configured_dem_kind(config))
    grid_checks = {
        "prec": validate_tif_grid_alignment(precip_label, Path(precip_dir), dem_path),
        "temp": validate_tif_grid_alignment("气温", Path(paths["aligned_temp_dir"]), dem_path),
        "evap": validate_tif_grid_alignment("蒸散发", Path(paths["aligned_evap_dir"]), dem_path),
    }
    for item in grid_checks.values():
        if not item.get("ok") and item.get("error"):
            errors.append(str(item["error"]))
    return {
        "ok": len(errors) == 0,
        "errors": errors,
        "warnings": warnings,
        "expected_steps": len(expected_index) if expected_index is not None else None,
        "directories": directories,
        "grid_checks": grid_checks,
        "total_valid_steps": sum(int(item["valid_time_steps"]) for item in directories.values()),
        "profile": active_profile,
        "time_basis": time_basis,
        "time_basis_label": time_basis_label,
        "event_windows": event_windows_ui_summary(event_info, step_hours) if event_info is not None else None,
    }


def inspect_observed_csv(
    csv_path: str,
    date_field: str | None = None,
    expected_index: pd.DatetimeIndex | None = None,
    target_step_hours: float | None = None,
) -> dict[str, Any]:
    path = resolve_any_path(csv_path, must_exist=True)
    return inspect_observed_discharge(
        path,
        date_field=date_field,
        expected_index=expected_index,
        target_step_hours=target_step_hours,
        allow_hourly_to_daily=True,
        min_daily_hours=DEFAULT_MIN_DAILY_HOURS,
        return_series=False,
    )


def observed_window_messages(config: dict[str, Any], obs_info: dict[str, Any]) -> tuple[list[str], list[str]]:
    issues: list[str] = []
    warnings: list[str] = []
    profile = current_profile(config)
    step_hours = normalize_time_step_hours(config.get("时间步长_小时", 24.0))
    effective_profile = str(
        obs_info.get("effective_calibration_mode")
        or obs_info.get("suggested_calibration_mode")
        or ""
    ).strip().lower()
    if effective_profile and effective_profile != profile:
        issues.append(f"观测径流时间步识别为 {PROFILE_LABELS[effective_profile]}，与当前率定模式不一致。")
    elif profile == PROFILE_DAILY and bool(obs_info.get("resampled_to_daily")):
        aggregation = dict(obs_info.get("daily_aggregation") or {})
        valid_days = int(aggregation.get("valid_days", 0) or 0)
        insufficient_days = int(aggregation.get("insufficient_days", 0) or 0)
        warnings.append(
            f"观测径流已从小时尺度按自然日聚合为日平均流量；有效日数 {valid_days} 天，小时覆盖不足天数 {insufficient_days} 天。"
        )
    coverage_ratio = obs_info.get("coverage_ratio")
    if coverage_ratio is not None:
        coverage_ratio = float(coverage_ratio)
        if coverage_ratio < 0.75:
            issues.append(f"观测径流在当前模拟时段内覆盖率只有 {coverage_ratio * 100:.1f}%，无法支撑稳定率定。")
        elif coverage_ratio < 0.95:
            warnings.append(f"观测径流在当前模拟时段内覆盖率只有 {coverage_ratio * 100:.1f}%，目标函数会只在部分时间步上计算。")

    obs_start = pd.to_datetime(obs_info.get("start"))
    obs_end = pd.to_datetime(obs_info.get("end"))
    time_cfg = dict(config.get("时间", {}))
    parsed: dict[str, pd.Timestamp] = {}
    for key in ("率定开始", "率定结束", "验证开始", "验证结束"):
        value = time_cfg.get(key)
        if not value:
            continue
        try:
            parsed[key] = pd.to_datetime(value)
        except Exception:
            continue

    for start_key, end_key, label in (("率定开始", "率定结束", "率定期"), ("验证开始", "验证结束", "验证期")):
        start_ts = parsed.get(start_key)
        end_ts = parsed.get(end_key)
        if start_ts is None or end_ts is None:
            continue
        if start_ts < obs_start:
            issues.append(f"{label}开始时间早于观测覆盖起点：{format_timestamp_for_display(start_ts, step_hours)} < {format_timestamp_for_display(obs_start, step_hours)}")
        if end_ts > obs_end:
            issues.append(f"{label}结束时间晚于观测覆盖终点：{format_timestamp_for_display(end_ts, step_hours)} > {format_timestamp_for_display(obs_end, step_hours)}")
        steps = int(((end_ts - start_ts) / pd.Timedelta(hours=step_hours)) + 1)
        if profile == PROFILE_DAILY and steps < 180:
            warnings.append(f"{label}长度只有 {steps} 天，正式率定通常建议至少半年以上。")
        if profile == PROFILE_HOURLY and steps < 24 * 30:
            warnings.append(f"{label}长度只有 {steps} 小时，小时尺度正式率定通常建议至少 30 天以上。")
    return issues, warnings


def _file_signature(path: Path) -> tuple[int, int]:
    stat = path.stat()
    return (
        int(getattr(stat, "st_mtime_ns", int(stat.st_mtime * 1e9))),
        int(stat.st_size),
    )


def _trim_boundary_csv_cache_locked() -> None:
    while len(BOUNDARY_CSV_CACHE) > MAX_BOUNDARY_CSV_CACHE:
        oldest_key = min(
            BOUNDARY_CSV_CACHE.items(),
            key=lambda item: float(item[1].get("used_at", 0.0)),
        )[0]
        BOUNDARY_CSV_CACHE.pop(oldest_key, None)


def _inspect_boundary_inflow_csv_base(
    csv_path_raw: str,
    date_field: str = "date",
    flow_field: str = "inflow_m3s",
) -> dict[str, Any]:
    path = resolve_any_path(csv_path_raw, must_exist=True)
    cache_key = f"{path.resolve(strict=False)}|{date_field}|{flow_field}"
    signature = _file_signature(path)
    with BOUNDARY_CSV_CACHE_LOCK:
        cached = BOUNDARY_CSV_CACHE.get(cache_key)
        if cached and cached.get("signature") == signature:
            cached["used_at"] = time.time()
            return copy.deepcopy(cached["data"])

    frame = pd.read_csv(path)
    if date_field not in frame.columns:
        raise ValueError(f"找不到时间字段 '{date_field}'，可用列：{list(frame.columns)}")
    if flow_field not in frame.columns:
        raise ValueError(f"找不到流量字段 '{flow_field}'，可用列：{list(frame.columns)}")

    frame = frame.copy()
    frame[date_field] = pd.to_datetime(frame[date_field], errors="coerce")
    frame[flow_field] = pd.to_numeric(frame[flow_field], errors="coerce")
    valid = frame.dropna(subset=[date_field, flow_field]).copy()
    if valid.empty:
        raise ValueError("上游边界入流文件中没有可识别的有效时间和流量记录。")

    valid.sort_values(date_field, inplace=True)
    duplicate_mask = valid.duplicated(subset=[date_field], keep=False)
    duplicate_timestamps = valid.loc[duplicate_mask, date_field].drop_duplicates().sort_values().tolist()
    actual_index = pd.DatetimeIndex(valid[date_field].drop_duplicates().sort_values().tolist())
    step_hours = detect_series_step_hours(pd.Series(actual_index.tolist()))
    flow_values = valid[flow_field].astype(float)

    preview_rows = []
    for _, row in valid.head(10).iterrows():
        preview_rows.append({date_field: str(row[date_field]), flow_field: float(row[flow_field])})

    base = {
        "columns": list(frame.columns),
        "total_rows": int(len(frame)),
        "valid_rows": int(len(valid)),
        "invalid_rows": int(len(frame) - len(valid)),
        "duplicate_timestamps": [pd.Timestamp(item) for item in duplicate_timestamps],
        "duplicate_count": int(len(duplicate_timestamps)),
        "time_step_hours": step_hours,
        "negative_count": int((flow_values < 0).sum()),
        "zero_count": int((flow_values == 0).sum()),
        "date_range": {
            "start": str(valid[date_field].min()),
            "end": str(valid[date_field].max()),
        },
        "flow_stats": {
            "min": round(float(flow_values.min()), 4),
            "max": round(float(flow_values.max()), 4),
            "mean": round(float(flow_values.mean()), 4),
        },
        "preview": preview_rows,
        "suggested_calibration_mode": PROFILE_HOURLY if step_hours is not None and step_hours <= 1.5 else PROFILE_DAILY,
        "_actual_index": actual_index,
    }
    with BOUNDARY_CSV_CACHE_LOCK:
        BOUNDARY_CSV_CACHE[cache_key] = {"signature": signature, "data": copy.deepcopy(base), "used_at": time.time()}
        _trim_boundary_csv_cache_locked()
    return base


def inspect_boundary_inflow_csv(
    csv_path_raw: str,
    date_field: str = "date",
    flow_field: str = "inflow_m3s",
    *,
    expected_index: pd.DatetimeIndex | None = None,
    expected_step_hours: float | None = None,
) -> dict[str, Any]:
    base = _inspect_boundary_inflow_csv_base(csv_path_raw, date_field=date_field, flow_field=flow_field)
    actual_index = pd.DatetimeIndex(base.pop("_actual_index"))
    expected_steps = None
    missing_steps: list[pd.Timestamp] = []
    out_of_range_steps: list[pd.Timestamp] = []
    coverage_ratio = None
    if expected_index is not None:
        expected_steps = len(expected_index)
        expected_list = list(expected_index)
        expected_set = set(expected_list)
        actual_set = set(actual_index.tolist())
        missing_steps = [ts for ts in expected_list if ts not in actual_set]
        out_of_range_steps = [ts for ts in actual_index.tolist() if ts not in expected_set]
        coverage_ratio = (len(expected_set & actual_set) / len(expected_set)) if expected_set else None

    return {
        **base,
        "expected_time_step_hours": expected_step_hours,
        "expected_steps": expected_steps,
        "missing_steps": missing_steps,
        "out_of_range_steps": out_of_range_steps,
        "coverage_ratio": coverage_ratio,
    }


def boundary_info_messages(
    boundary_info: dict[str, Any],
    step_hours: float,
    gap_fill: str = "zero",
) -> tuple[list[str], list[str]]:
    issues: list[str] = []
    warnings: list[str] = []
    gap_mode = str(gap_fill or "zero").strip().lower()
    detected_step = boundary_info.get("time_step_hours")
    if detected_step is not None and normalize_time_step_hours(detected_step) != step_hours:
        issues.append(
            f"上游边界入流时间步识别为 {int(detected_step)} 小时，与当前项目时间步长 {int(step_hours)} 小时不一致。"
        )
    if boundary_info.get("duplicate_count", 0) > 0:
        sample = "、".join(
            format_timestamp_for_display(ts, step_hours)
            for ts in boundary_info["duplicate_timestamps"][:3]
        )
        issues.append(f"上游边界入流存在重复时间戳 {boundary_info['duplicate_count']} 个，例如：{sample}")
    if boundary_info.get("negative_count", 0) > 0:
        issues.append(f"上游边界入流存在 {boundary_info['negative_count']} 条负流量记录。")
    missing_steps = list(boundary_info.get("missing_steps", []))
    if missing_steps:
        sample = "、".join(format_timestamp_for_display(ts, step_hours) for ts in missing_steps[:3])
        if gap_mode == "interpolate":
            warnings.append(f"上游边界入流缺少 {len(missing_steps)} 个时间步，例如：{sample}；运行时会按线性插值补齐。")
        elif gap_mode in {"", "zero", "0"}:
            warnings.append(f"上游边界入流缺少 {len(missing_steps)} 个时间步，例如：{sample}；运行时会按 0 填补。")
        else:
            issues.append(f"上游边界入流时间覆盖不完整，缺少 {len(missing_steps)} 个时间步，例如：{sample}")
    out_of_range_steps = list(boundary_info.get("out_of_range_steps", []))
    if out_of_range_steps:
        sample = "、".join(format_timestamp_for_display(ts, step_hours) for ts in out_of_range_steps[:3])
        warnings.append(f"上游边界入流有 {len(out_of_range_steps)} 个时间步落在当前配置时间范围之外，例如：{sample}")
    if boundary_info.get("invalid_rows", 0) > 0:
        warnings.append(f"上游边界入流中有 {boundary_info['invalid_rows']} 行无法解析时间或流量，已在读取时忽略。")
    zero_count = int(boundary_info.get("zero_count", 0))
    valid_rows = max(1, int(boundary_info.get("valid_rows", 0)))
    if zero_count / valid_rows >= 0.8:
        warnings.append("上游边界入流中零值比例超过 80%，请确认缺测值没有被误当成 0。")
    return issues, warnings


def fill_bbox_from_shp(shp_path: str) -> dict[str, float] | None:
    if not shp_path:
        return None
    try:
        import geopandas as gpd
    except Exception:
        return None
    path = resolve_any_path(shp_path, must_exist=True)
    gdf = gpd.read_file(path)
    minx, miny, maxx, maxy = gdf.total_bounds
    return {"北": float(maxy), "西": float(minx), "南": float(miny), "东": float(maxx)}


def suggest_cfmax_threshold(shp_path: str, dem_path: str) -> dict[str, Any]:
    import geopandas as gpd
    import numpy as np
    import rasterio
    from rasterio.mask import mask

    shp = resolve_any_path(shp_path, must_exist=True)
    dem = resolve_any_path(dem_path, must_exist=True)
    basin = gpd.read_file(shp)
    with rasterio.open(dem) as src:
        basin_reproj = basin.to_crs(src.crs)
        masked, _ = mask(src, basin_reproj.geometry, crop=True, filled=False)
        arr = masked[0].astype("float64")
        if src.nodata is not None:
            arr[arr == src.nodata] = float("nan")
    valid = np.asarray(arr[np.isfinite(arr) & (arr > 0)], dtype="float64")
    if valid.size == 0:
        raise ValueError("DEM 与流域边界叠置后没有有效高程。")
    threshold = float(np.nanmedian(valid))
    return {
        "suggested_threshold_m": round(threshold, 2),
        "min_m": round(float(np.nanmin(valid)), 2),
        "median_m": round(float(np.nanmedian(valid)), 2),
        "max_m": round(float(np.nanmax(valid)), 2),
        "rule": "按流域有效 DEM 的中位高程生成建议阈值，可再手工微调。",
    }


def slugify_workspace_name(name: str) -> str:
    raw = str(name or "").strip()
    if not raw:
        return "新工作区"
    normalized = unicodedata.normalize("NFKC", raw)
    digest = hashlib.md5(raw.encode("utf-8")).hexdigest()[:8]
    safe = re.sub(r'[<>:"/\\|?*\x00-\x1f]+', "_", normalized)
    safe = re.sub(r"\s+", "_", safe)
    safe = re.sub(r"_+", "_", safe).strip(" ._")[:48].strip(" ._")
    if not safe:
        return f"workspace_{digest}"
    if re.fullmatch(r"(?i:con|prn|aux|nul|com[1-9]|lpt[1-9])", safe):
        return f"{safe}_{digest[:4]}"
    return safe


def runtime_root_for_workspace(name: str) -> Path:
    return PROJECT_RUNTIME_DIR / slugify_workspace_name(name)


def detect_profile_from_payload(data: dict[str, Any]) -> str:
    explicit = str(data.get("率定模式", "")).strip().lower()
    if explicit in {PROFILE_DAILY, PROFILE_HOURLY}:
        return explicit
    return PROFILE_HOURLY if normalize_time_step_hours(data.get("时间步长_小时", 24.0)) <= 1.5 else PROFILE_DAILY


def detect_object_type(data: dict[str, Any]) -> str:
    explicit = str(data.get("项目对象", "")).strip().lower()
    if explicit in {OBJECT_REGRESSION, OBJECT_INTERBASIN, OBJECT_FULL_UPSTREAM}:
        return explicit
    boundary = dict(data.get("边界条件", {}))
    if boundary.get("上游边界入流_csv"):
        return OBJECT_INTERBASIN
    return OBJECT_FULL_UPSTREAM


def to_portable_path(value: str) -> str:
    """Convert an absolute path to a portable form using __PROJECT_ROOT__ / __GUI_ROOT__ placeholders."""
    if not value:
        return value
    try:
        resolved = Path(value).resolve()
    except (OSError, ValueError):
        resolved = Path(value)
    gui_resolved = GUI_ROOT.resolve()
    proj_resolved = PROJECT_ROOT.resolve()
    # Try GUI_ROOT first (it's deeper, more specific)
    try:
        rel = resolved.relative_to(gui_resolved)
        return "__GUI_ROOT__/" + str(rel).replace("\\", "/")
    except ValueError:
        pass
    try:
        rel = resolved.relative_to(proj_resolved)
        return "__PROJECT_ROOT__/" + str(rel).replace("\\", "/")
    except ValueError:
        pass
    return value


def portableize_value_paths(value: Any) -> Any:
    if isinstance(value, dict):
        return {key: portableize_value_paths(item) for key, item in value.items()}
    if isinstance(value, list):
        return [portableize_value_paths(item) for item in value]
    if isinstance(value, str):
        return to_portable_path(value)
    return value


def _append_candidate_path(candidates: list[Path], seen: set[str], value: Any, *, project_root: Path | None = None, gui_root: Path | None = None) -> None:
    if value in (None, ""):
        return
    try:
        if isinstance(value, Path):
            path = value.expanduser().resolve(strict=False)
        else:
            raw = str(value)
            if project_root is not None or gui_root is not None:
                raw = str(replace_placeholders(raw, project_root=project_root, gui_root=gui_root))
                raw = str(remap_legacy_project_path(raw))
                path = Path(raw).expanduser()
                if not path.is_absolute():
                    path = ((gui_root or GUI_ROOT) / path).resolve(strict=False)
                else:
                    path = path.resolve(strict=False)
            else:
                path = resolve_any_path(raw, must_exist=False)
    except Exception:
        try:
            path = Path(str(value)).expanduser().resolve(strict=False)
        except Exception:
            return
    key = str(path).lower()
    if key in seen:
        return
    seen.add(key)
    candidates.append(path)


def _infer_project_roots_from_run_path(run_path: Path | None) -> tuple[Path | None, Path | None]:
    if run_path is None:
        return None, None
    try:
        current = Path(run_path).resolve(strict=False)
    except Exception:
        return None, None
    for candidate in [current] + list(current.parents):
        if (candidate / "HBV-Studio" / "workspaces").exists() and (candidate / "运行目录").exists():
            return candidate.resolve(strict=False), (candidate / "HBV-Studio").resolve(strict=False)
    return None, None


def _workspace_roots_hint_from_metadata(metadata: dict[str, Any] | None) -> tuple[Path | None, Path | None]:
    meta = dict(metadata or {})
    hint_root_raw = str(meta.get("workspace_root_hint", "") or "").strip()
    gui_hint_raw = str(meta.get("workspace_gui_root_hint", "") or "").strip()
    try:
        project_root = Path(hint_root_raw).expanduser().resolve(strict=False) if hint_root_raw else None
    except Exception:
        project_root = None
    try:
        gui_root = Path(gui_hint_raw).expanduser().resolve(strict=False) if gui_hint_raw else None
    except Exception:
        gui_root = None
    if gui_root is None and project_root is not None:
        candidate = (project_root / "HBV-Studio").resolve(strict=False)
        if candidate.exists():
            gui_root = candidate
    if project_root is None and gui_root is not None:
        project_root = gui_root.parent.resolve(strict=False)
    return project_root, gui_root


def workspace_config_candidates(raw_path: str, *, project_root: Path | None = None, gui_root: Path | None = None) -> list[Path]:
    raw = str(raw_path or "").strip()
    if not raw:
        return []
    candidates: list[Path] = []
    seen: set[str] = set()
    expanded = replace_placeholders(raw, project_root=project_root, gui_root=gui_root)
    name_source = str(expanded) if isinstance(expanded, str) and expanded else raw
    name = Path(name_source).name
    raw_candidate: Path | None = None
    try:
        if project_root is not None or gui_root is not None:
            raw_candidate = Path(str(name_source)).expanduser()
            if not raw_candidate.is_absolute():
                raw_candidate = ((gui_root or GUI_ROOT) / raw_candidate).resolve(strict=False)
            else:
                raw_candidate = raw_candidate.resolve(strict=False)
        else:
            raw_candidate = resolve_any_path(name_source, must_exist=False)
    except Exception:
        try:
            raw_candidate = Path(name_source).expanduser().resolve(strict=False)
        except Exception:
            raw_candidate = None
    if raw_candidate is not None and raw_candidate.is_absolute() and raw_candidate.exists():
        _append_candidate_path(candidates, seen, raw_candidate, project_root=project_root, gui_root=gui_root)
    prefer_local_workspace = bool(name and raw_candidate is not None and not is_within_current_project(raw_candidate))
    if name and gui_root is not None:
        _append_candidate_path(candidates, seen, gui_root / "workspaces" / name, project_root=project_root, gui_root=gui_root)
    if prefer_local_workspace and name:
        _append_candidate_path(candidates, seen, WORKSPACE_DIR / name, project_root=project_root, gui_root=gui_root)
        default_workspace_dir = GUI_ROOT / "workspaces"
        if default_workspace_dir.resolve(strict=False) != WORKSPACE_DIR.resolve(strict=False):
            _append_candidate_path(candidates, seen, default_workspace_dir / name, project_root=project_root, gui_root=gui_root)
    _append_candidate_path(candidates, seen, raw, project_root=project_root, gui_root=gui_root)
    if isinstance(expanded, str) and expanded != raw:
        _append_candidate_path(candidates, seen, expanded, project_root=project_root, gui_root=gui_root)
    if name:
        if not prefer_local_workspace:
            _append_candidate_path(candidates, seen, WORKSPACE_DIR / name, project_root=project_root, gui_root=gui_root)
            default_workspace_dir = GUI_ROOT / "workspaces"
            if default_workspace_dir.resolve(strict=False) != WORKSPACE_DIR.resolve(strict=False):
                _append_candidate_path(candidates, seen, default_workspace_dir / name, project_root=project_root, gui_root=gui_root)
    return candidates


def resolve_workspace_config_reference(raw_path: str, *, run_path: Path | None = None, project_root: Path | None = None, gui_root: Path | None = None) -> Path | None:
    if project_root is None and gui_root is None:
        project_root, gui_root = _infer_project_roots_from_run_path(run_path)
    for candidate in workspace_config_candidates(raw_path, project_root=project_root, gui_root=gui_root):
        if candidate.exists():
            return candidate.resolve(strict=False)
    return None


def _first_existing_path(candidates: list[Path]) -> Path | None:
    seen: set[str] = set()
    fallback: Path | None = None
    for candidate in candidates:
        resolved = Path(candidate).resolve(strict=False)
        key = str(resolved).lower()
        if key in seen:
            continue
        seen.add(key)
        if fallback is None:
            fallback = resolved
        if resolved.exists():
            return resolved
    return fallback


def _has_parameter_bounds(metadata: dict[str, Any]) -> bool:
    profile = metadata.get("parameter_profile")
    if not isinstance(profile, dict):
        return False
    bounds = profile.get("bounds")
    if not isinstance(bounds, dict) or not bounds:
        return False
    for value in bounds.values():
        if isinstance(value, (list, tuple)) and len(value) >= 2:
            return True
    return False


def is_studio_editable_metadata(metadata: dict[str, Any], resolved_config: Path | None = None) -> bool:
    config_path = resolved_config
    if config_path is None:
        hint_project_root, hint_gui_root = _workspace_roots_hint_from_metadata(metadata)
        config_path = resolve_workspace_config_reference(
            str(metadata.get("workspace_config", "") or ""),
            project_root=hint_project_root,
            gui_root=hint_gui_root,
        )
    return bool(config_path and _has_parameter_bounds(metadata))


def _synthesized_parameter_profile(profile: str, objective_mode: str) -> dict[str, Any]:
    if profile == PROFILE_HOURLY:
        bounds = profile_runner.parameter_bounds_for_profile(PROFILE_HOURLY)
        notes = [
            (
                "小时尺度当前启用综合水文评价口径。"
                if objective_mode == profile_runner.OBJECTIVE_MODE_MULTI
                else "小时尺度当前使用简化径流评价口径。"
            ),
            "Muskingum 路由参数范围已按 1 小时步长的离散稳定性收紧，避免大面积无效搜索。",
            "小时尺度结果与日尺度结果分开保存，互不覆盖。",
        ]
        label = PROFILE_LABELS[PROFILE_HOURLY]
        bounds_profile = profile_runner.PARAM_BOUNDS_PROFILE_HOURLY
    else:
        bounds_profile = profile_runner.DEFAULT_DAILY_PARAM_BOUNDS_PROFILE
        bounds = profile_runner.parameter_bounds_for_profile(PROFILE_DAILY, bounds_profile)
        notes = [
            "日尺度当前固定使用统一日尺度综合水文目标函数，不再提供多目标函数产品分支。",
            profile_runner.PARAM_BOUNDS_PROFILE_NOTES.get(bounds_profile, "日尺度参数范围与小时尺度分开管理。"),
        ]
        label = f"{PROFILE_LABELS[PROFILE_DAILY]} · {profile_runner.PARAM_BOUNDS_PROFILE_LABELS.get(bounds_profile, bounds_profile)}"
    return {
        "name": profile,
        "label": label,
        "bounds_profile": bounds_profile,
        "bounds_profile_label": profile_runner.PARAM_BOUNDS_PROFILE_LABELS.get(bounds_profile, bounds_profile),
        "notes": notes,
        "bounds": {name: list(bound) for name, bound in zip(CALIBRATION_PARAM_NAMES, bounds)},
    }


def _synthesized_objective_profile(profile: str, objective_mode: str, current: dict[str, Any] | None = None) -> dict[str, Any]:
    current = dict(current or {})
    base = (
        profile_runner.build_weighted_multi_objective_meta(profile)
        if objective_mode == profile_runner.OBJECTIVE_MODE_MULTI
        else profile_runner.build_single_objective_meta(profile)
    )
    for key in ("profile", "label", "summary", "formula", "weights", "diagnostic_only_constraints", "notes"):
        value = current.get(key)
        if value not in (None, "", [], {}):
            base[key] = value
    base["type"] = objective_mode
    return base


def _resolve_source_run_reference(source_run_path_raw: Any, source_run_name_raw: Any) -> str:
    source_run_path = str(source_run_path_raw or "").strip()
    source_run_name = str(source_run_name_raw or "").strip()
    if not source_run_path:
        return ""

    def _is_run_dir(candidate: Path) -> bool:
        return (candidate / "metadata.json").exists() and (candidate / "simulation.csv").exists()

    def _is_workspace_dir(candidate: Path) -> bool:
        return any((candidate / item).exists() for item in ("结果", "results"))

    try:
        base_path = resolve_any_path(source_run_path, must_exist=False)
    except Exception:
        return source_run_path

    candidates: list[Path] = [base_path]
    search_names: list[str] = []
    for name in (
        source_run_name,
        Path(str(replace_placeholders(source_run_path))).name,
        base_path.name,
    ):
        cleaned = str(name or "").strip()
        if cleaned and cleaned not in search_names:
            search_names.append(cleaned)
    if source_run_name:
        candidates.append(base_path / source_run_name)
        for parts in (
            ("结果", "日尺度", "运行记录"),
            ("结果", "小时尺度", "运行记录"),
            ("results", "daily", "runs"),
            ("results", "hourly", "runs"),
        ):
            candidates.append(base_path.joinpath(*parts, source_run_name))

    for candidate in candidates:
        if _is_run_dir(candidate):
            return str(candidate.resolve(strict=False))

    try:
        runtime_roots = discover_runtime_roots()
    except Exception:
        runtime_roots = []

    for name in search_names:
        for root_dir in runtime_roots:
            root = Path(root_dir).resolve(strict=False)
            if root.name == name and (_is_workspace_dir(root) or _is_run_dir(root)):
                return str(root)
            candidate = (root / name).resolve(strict=False)
            if _is_workspace_dir(candidate) or _is_run_dir(candidate):
                return str(candidate)
        for root_dir in runtime_roots:
            for parent in iter_run_parent_dirs(Path(root_dir)):
                candidate = (parent / name).resolve(strict=False)
                if _is_run_dir(candidate):
                    return str(candidate)

    return str(base_path.resolve(strict=False))


def _normalize_metadata_object_type(value: Any) -> str:
    object_type = str(value or "").strip().lower()
    if object_type == "regression_test":
        return OBJECT_REGRESSION
    if object_type in {OBJECT_REGRESSION, OBJECT_INTERBASIN, OBJECT_FULL_UPSTREAM}:
        return object_type
    return ""


def _metadata_boundary_enabled(metadata: dict[str, Any]) -> bool | None:
    optional_modules = dict(metadata.get("optional_modules", {}) or {})
    boundary_module = dict(optional_modules.get("boundary_inflow", {}) or {})
    boundary_meta = dict(metadata.get("boundary_condition", {}) or {})
    for value in (boundary_module.get("enabled"), boundary_meta.get("enabled")):
        if isinstance(value, bool):
            return value
    boundary_file = str(
        boundary_meta.get("boundary_inflow_file")
        or boundary_module.get("file")
        or ""
    ).strip()
    if boundary_file:
        return True
    return None


def _resolve_metadata_object_type(metadata: dict[str, Any], config: dict[str, Any] | None = None) -> str:
    object_type = _normalize_metadata_object_type(metadata.get("project_object_type"))
    if object_type:
        return object_type
    boundary_enabled = _metadata_boundary_enabled(metadata)
    if boundary_enabled is True:
        return OBJECT_INTERBASIN
    if boundary_enabled is False:
        return OBJECT_FULL_UPSTREAM
    if config is not None:
        return detect_object_type(config)
    return ""


def _optimization_stage_payload(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, dict) else {}


def _optimization_stage_counter(value: Any) -> int:
    try:
        return max(0, int(value or 0))
    except Exception:
        return 0


def _optimization_stage_has_execution(stage: dict[str, Any]) -> bool:
    if not stage:
        return False
    if bool(stage.get("executed")):
        return True
    for key in ("nfev", "nit", "progress_points", "valid_samples", "processed_samples"):
        if _optimization_stage_counter(stage.get(key)) > 0:
            return True
    if any(key in stage for key in ("success", "valid", "message")):
        return True
    return stage.get("objective_value") is not None


def _infer_selected_result_stage(optimization: dict[str, Any], stage_stats: dict[str, dict[str, Any]]) -> str:
    selected_stage = str(optimization.get("selected_result_stage", "") or "").strip().lower()
    if selected_stage in {"mc", "global", "refine"}:
        return selected_stage
    for stage_name in ("refine", "global", "mc"):
        if bool(stage_stats.get(stage_name, {}).get("selected")):
            return stage_name
    label = str(optimization.get("selected_result_label", "") or "").strip()
    if "局部精修" in label:
        return "refine"
    if ("快速筛选" in label) or ("随机筛选" in label) or ("蒙特卡洛" in label):
        return "mc"
    if ("精细搜索" in label) or ("全局搜索" in label) or ("差分进化" in label):
        return "global"
    return ""


def _normalized_selected_result_label(optimization: dict[str, Any]) -> str:
    selected_stage = str(optimization.get("selected_result_stage", "") or "").strip().lower()
    if selected_stage == "global":
        return "精细搜索结果（含末端精修）" if bool(optimization.get("polish")) else "精细搜索结果"
    if selected_stage == "refine":
        return "局部精修结果"
    if selected_stage == "mc":
        return "快速筛选结果"
    return str(optimization.get("selected_result_label", "") or "").strip()


def _normalized_method_label(optimization: dict[str, Any]) -> str:
    method_key = str(optimization.get("method", "") or "").strip().lower()
    refine = _optimization_stage_payload(dict(optimization.get("stage_stats", {}) or {}).get("refine"))
    refine_requested = bool(optimization.get("refine_requested") or optimization.get("refine_enabled") or refine.get("requested"))
    refine_executed = bool(optimization.get("refine_executed") or refine.get("executed"))
    refine_skipped = bool(str(refine.get("skipped_reason", "") or "").strip())
    polish_enabled = bool(optimization.get("polish"))
    if method_key == "manual_adjustment":
        return "手调后重算"
    if method_key == "manual_start":
        return "手调起点"
    if method_key == "de":
        if refine_executed:
            return "精细搜索 + 局部精修"
        if refine_requested and refine_skipped:
            return "精细搜索（局部精修已跳过）"
        if refine_requested:
            return "精细搜索（局部精修未产出有效结果）"
        if polish_enabled:
            return "精细搜索（含末端精修）"
        return "精细搜索（差分进化）"
    if method_key == "mc_screen_de":
        if refine_executed:
            return "快速筛选 + 精细搜索 + 局部精修"
        if refine_requested and refine_skipped:
            return "快速筛选 + 精细搜索（局部精修已跳过）"
        if refine_requested:
            return "快速筛选 + 精细搜索（局部精修未产出有效结果）"
        if polish_enabled:
            return "快速筛选 + 精细搜索（含末端精修）"
        return "快速筛选 + 精细搜索"
    if method_key == "mc_only":
        return "仅快速筛选"
    return str(optimization.get("method_label", "") or "").strip() or str(optimization.get("method", "") or "").strip()


def _normalize_optimization_metadata(
    optimization: dict[str, Any],
    *,
    effective_objective_mode: str = "",
    fallback_total_evaluations: Any = None,
) -> dict[str, Any]:
    normalized = dict(optimization or {})
    method_key = str(normalized.get("method", "") or "").strip().lower()
    stage_stats_raw = dict(normalized.get("stage_stats", {}) or {})
    stage_stats: dict[str, dict[str, Any]] = {}
    for stage_name in ("mc", "global", "refine"):
        stage = _optimization_stage_payload(stage_stats_raw.get(stage_name))
        if not stage:
            continue
        if stage_name == "mc" and _optimization_stage_counter(stage.get("progress_points")) <= 0 and _optimization_stage_counter(stage.get("nit")) > 0:
            stage["progress_points"] = _optimization_stage_counter(stage.get("nit"))
        stage_stats[stage_name] = stage

    selected_stage = _infer_selected_result_stage(normalized, stage_stats)
    polish_enabled = bool(normalized.get("polish") or stage_stats.get("global", {}).get("polish"))
    normalized["polish"] = polish_enabled

    refine_stage = dict(stage_stats.get("refine", {}))
    if refine_stage and (not bool(refine_stage.get("requested"))) and str(refine_stage.get("skipped_reason", "") or "").strip():
        refine_stage["requested"] = True
        stage_stats["refine"] = refine_stage
    refine_requested = bool(normalized.get("refine_requested") or normalized.get("refine_enabled") or refine_stage.get("requested"))
    refine_executed = bool(normalized.get("refine_executed") or refine_stage.get("executed") or selected_stage == "refine" or _optimization_stage_has_execution(refine_stage))
    normalized["refine_requested"] = refine_requested
    normalized["refine_enabled"] = refine_requested
    normalized["refine_executed"] = refine_executed

    requested_by_method = {
        "mc": method_key in {"mc_only", "mc_screen_de"},
        "global": method_key in {"de", "mc_screen_de"},
        "refine": refine_requested,
    }
    global_execution_hint = bool(selected_stage in {"global", "refine"} or _optimization_stage_has_execution(stage_stats.get("global", {})))
    for stage_name in ("mc", "global", "refine"):
        stage = dict(stage_stats.get(stage_name, {}))
        requested = bool(stage.get("requested")) or requested_by_method[stage_name]
        executed = bool(stage.get("executed")) or (selected_stage == stage_name) or _optimization_stage_has_execution(stage)
        if stage_name == "global" and selected_stage == "refine":
            executed = True
        if stage_name == "mc" and method_key == "mc_screen_de" and global_execution_hint:
            executed = True
        if stage_name == "refine" and str(stage.get("skipped_reason", "") or "").strip():
            requested = True
        if stage_name == "global" and (polish_enabled or ("polish" in stage)):
            stage["polish"] = polish_enabled
        if not (stage or requested or executed or selected_stage == stage_name):
            continue
        stage["requested"] = requested
        stage["executed"] = executed
        if selected_stage == stage_name:
            stage["selected"] = True
        stage_stats[stage_name] = stage

    selected_stage_stats = dict(stage_stats.get(selected_stage, {}))
    global_stage = dict(stage_stats.get("global", {}))
    refine_stage = dict(stage_stats.get("refine", {}))
    mc_stage = dict(stage_stats.get("mc", {}))

    selected_stage_evaluations = _optimization_stage_counter(selected_stage_stats.get("nfev"))
    if selected_stage_evaluations <= 0:
        selected_stage_evaluations = _optimization_stage_counter(normalized.get("selected_stage_evaluations"))

    selected_stage_generations = _optimization_stage_counter(selected_stage_stats.get("nit")) if selected_stage in {"global", "refine"} else 0
    if selected_stage_generations <= 0 and selected_stage in {"global", "refine"}:
        selected_stage_generations = _optimization_stage_counter(normalized.get("selected_stage_generations"))

    selected_stage_progress_points = _optimization_stage_counter(selected_stage_stats.get("progress_points"))
    if selected_stage_progress_points <= 0:
        selected_stage_progress_points = _optimization_stage_counter(normalized.get("selected_stage_progress_points"))
    if selected_stage == "mc" and selected_stage_progress_points <= 0:
        selected_stage_progress_points = _optimization_stage_counter(normalized.get("selected_stage_generations"))

    total_generations = (
        _optimization_stage_counter(global_stage.get("nit"))
        + _optimization_stage_counter(refine_stage.get("nit"))
    )
    if total_generations <= 0 and method_key != "mc_only" and (
        _optimization_stage_counter(global_stage.get("nit")) <= 0
        and _optimization_stage_counter(refine_stage.get("nit")) <= 0
    ):
        total_generations = _optimization_stage_counter(normalized.get("total_generations"))

    total_progress_points = sum(
        _optimization_stage_counter(stage.get("progress_points"))
        for stage in (mc_stage, global_stage, refine_stage)
    )
    if total_progress_points <= 0:
        total_progress_points = _optimization_stage_counter(normalized.get("total_progress_points"))
    if total_progress_points <= 0 and _optimization_stage_counter(mc_stage.get("nit")) > 0:
        total_progress_points = _optimization_stage_counter(mc_stage.get("nit")) + _optimization_stage_counter(global_stage.get("progress_points")) + _optimization_stage_counter(refine_stage.get("progress_points"))

    total_evaluations = max(
        _optimization_stage_counter(fallback_total_evaluations),
        _optimization_stage_counter(normalized.get("total_evaluations")),
        selected_stage_evaluations,
        sum(_optimization_stage_counter(stage.get("nfev")) for stage in (mc_stage, global_stage, refine_stage)),
    )

    normalized["selected_result_stage"] = selected_stage
    normalized["selected_result_label"] = _normalized_selected_result_label({**normalized, "selected_result_stage": selected_stage, "polish": polish_enabled})
    normalized["method_label"] = _normalized_method_label({**normalized, "stage_stats": stage_stats, "selected_result_stage": selected_stage, "polish": polish_enabled})
    normalized["selected_stage_evaluations"] = selected_stage_evaluations
    normalized["selected_stage_generations"] = selected_stage_generations
    normalized["selected_stage_progress_points"] = selected_stage_progress_points
    normalized["total_evaluations"] = total_evaluations
    normalized["total_generations"] = total_generations
    normalized["total_progress_points"] = total_progress_points
    if effective_objective_mode:
        normalized["objective_mode"] = effective_objective_mode
        normalized["effective_objective_mode"] = effective_objective_mode
    normalized["stage_stats"] = stage_stats or None
    return normalized


def normalize_run_metadata(metadata: dict[str, Any], *, run_path: Path | None = None) -> tuple[dict[str, Any], Path | None]:
    normalized = copy.deepcopy(metadata or {})
    workspace_config = str(normalized.get("workspace_config", "") or "").strip()
    hint_project_root, hint_gui_root = _workspace_roots_hint_from_metadata(normalized)
    resolved_config = resolve_workspace_config_reference(
        workspace_config,
        run_path=run_path,
        project_root=hint_project_root,
        gui_root=hint_gui_root,
    )
    if resolved_config is not None:
        normalized["workspace_config"] = str(resolved_config)
    resolved_object_type = _resolve_metadata_object_type(normalized)

    data_sources = dict(normalized.get("data_sources", {}) or {})
    boundary_condition = dict(normalized.get("boundary_condition", {}) or {})
    optimization = dict(normalized.get("optimization", {}) or {})
    manual_result = dict(normalized.get("manual_result", {}) or {})
    replay_context = dict(normalized.get("replay_context", {}) or {})
    recorded_objective_family = str(
        normalized.get("objective_family")
        or normalized.get("effective_objective_mode")
        or optimization.get("effective_objective_mode")
        or optimization.get("objective_mode")
        or (normalized.get("objective_profile", {}) if isinstance(normalized.get("objective_profile"), dict) else {}).get("type")
        or (normalized.get("objective", {}) if isinstance(normalized.get("objective"), dict) else {}).get("type")
        or ""
    ).strip().lower()
    if recorded_objective_family:
        normalized["recorded_objective_family"] = recorded_objective_family
    cache = {
        key: (dict(value) if isinstance(value, dict) else value)
        for key, value in dict(normalized.get("data_cache", {}) or {}).items()
    }
    effective_objective_mode = str(
        normalized.get("effective_objective_mode")
        or optimization.get("effective_objective_mode")
        or ""
    ).strip().lower()

    if resolved_config is not None:
        try:
            config = read_runtime_config(resolved_config)
            profile = resolve_profile(
                config,
                str(normalized.get("calibration_profile", normalized.get("rate_mode", ""))).strip().lower() or None,
            )
            objective_mode = profile_runner.resolve_objective_mode(
                config,
                normalized.get("optimization", {}).get("objective_mode")
                or normalized.get("objective_profile", {}).get("type")
                or normalized.get("objective", {}).get("type")
                or normalized.get("目标函数模式"),
                profile,
            )
            paths = build_profile_paths(config, profile)
            configured_source = configured_precip_source(config)
            raw_source_key = str(
                data_sources.get("runtime_prec_source")
                or data_sources.get("prec_source")
                or data_sources.get("configured_precip_source")
                or configured_source
                or "era5"
            ).strip().lower()
            source_key = resolve_precip_source(config, raw_source_key)
            _, effective_prec_dir, _ = effective_precip_paths(config, profile, precip_source=source_key)
            prec_candidates: list[Path] = []
            if source_key == "era5":
                prec_candidates.extend(
                    [
                        Path(paths["aligned_prec_era5_dir"]),
                        Path(paths["aligned_prec_era5_base_dir"]),
                    ]
                )
            elif source_key == "custom_tif":
                prec_candidates.extend(
                    [
                        Path(paths["aligned_prec_custom_dir"]),
                        Path(paths["aligned_prec_custom_base_dir"]),
                    ]
                )
            elif source_key == "cmfd":
                prec_candidates.extend(
                    [
                        Path(paths["aligned_prec_cmfd_dir"]),
                        Path(paths["aligned_prec_cmfd_base_dir"]),
                    ]
                )
            else:
                prec_candidates.extend(
                    [
                        Path(paths["aligned_prec_dir"]),
                        Path(paths["aligned_prec_base_dir"]),
                    ]
                )
            raw_prec_dir = str(data_sources.get("prec_dir", "") or "").strip()
            if raw_prec_dir:
                try:
                    prec_candidates.append(resolve_any_path(raw_prec_dir, must_exist=False))
                except Exception:
                    pass
            prec_candidates.append(Path(effective_prec_dir))
            resolved_prec_dir = _first_existing_path(prec_candidates)

            if resolved_prec_dir is not None:
                data_sources["prec_dir"] = str(resolved_prec_dir)
            data_sources["temp_dir"] = str(Path(paths["aligned_temp_dir"]).resolve(strict=False))
            data_sources["evap_dir"] = str(Path(paths["aligned_evap_dir"]).resolve(strict=False))

            glacier_melt_dir = Path(paths["glacier_melt_dir"]).resolve(strict=False)
            if glacier_melt_dir.exists() or data_sources.get("glacier_melt_dir"):
                data_sources["glacier_melt_dir"] = str(glacier_melt_dir)

            glacier_mask_path = (Path(paths["gis_dir"]) / "glacier_mask.tif").resolve(strict=False)
            if glacier_mask_path.exists() or data_sources.get("glacier_mask"):
                data_sources["glacier_mask"] = str(glacier_mask_path)

            obs_path = _resolve_config_related_path(config, config.get(OBSERVED_FLOW_KEY))
            if obs_path is not None:
                data_sources["obs_file"] = str(obs_path.resolve(strict=False))

            data_sources["prec_source"] = source_key or configured_source
            data_sources["configured_precip_source"] = configured_source
            data_sources["runtime_prec_source"] = source_key or configured_source
            normalized["calibration_profile"] = str(normalized.get("calibration_profile") or profile)
            normalized["rate_mode"] = str(normalized.get("rate_mode") or profile)
            if not resolved_object_type:
                resolved_object_type = _resolve_metadata_object_type(normalized, config)
            if resolved_object_type:
                normalized["project_object_type"] = resolved_object_type
            if objective_mode:
                effective_objective_mode = str(objective_mode).strip().lower()
                optimization["effective_objective_mode"] = effective_objective_mode
            normalized["workspace_label"] = str(config.get("流域名称", resolved_config.stem)).strip() or resolved_config.stem
            if not isinstance(normalized.get("parameter_profile"), dict):
                normalized["parameter_profile"] = _synthesized_parameter_profile(profile, objective_mode)
            if not isinstance(normalized.get("objective_profile"), dict):
                normalized["objective_profile"] = _synthesized_objective_profile(profile, objective_mode, normalized.get("objective"))
            objective_meta = dict(normalized.get("objective", {}) or {})
            for key in ("type", "summary", "formula", "weights", "diagnostic_only_constraints"):
                if key in normalized["objective_profile"]:
                    objective_meta[key] = normalized["objective_profile"][key]
            if objective_meta:
                normalized["objective"] = objective_meta

            boundary_cfg = dict(config.get("边界条件", {}) or {})
            boundary_path = _resolve_config_related_path(config, boundary_cfg.get("上游边界入流_csv"))
            optional_modules = dict(normalized.get("optional_modules", {}) or {})
            boundary_module = dict(optional_modules.get("boundary_inflow", {}) or {})
            raw_boundary_file = str(
                boundary_condition.get("boundary_inflow_file")
                or boundary_module.get("file")
                or ""
            ).strip()
            boundary_candidates: list[Path] = []
            if raw_boundary_file:
                try:
                    boundary_candidates.append(resolve_any_path(raw_boundary_file, must_exist=False))
                except Exception:
                    pass
            if boundary_path is not None:
                boundary_candidates.append(boundary_path)
            resolved_boundary_path = _first_existing_path(boundary_candidates)
            if resolved_boundary_path is not None:
                boundary_condition["boundary_inflow_file"] = str(resolved_boundary_path)

            cache_dir = Path(paths["cache_dir"]).resolve(strict=False)
            source_dir_map = {
                "prec": Path(data_sources["prec_dir"]).resolve(strict=False) if data_sources.get("prec_dir") else None,
                "temp": Path(paths["aligned_temp_dir"]).resolve(strict=False),
                "evap": Path(paths["aligned_evap_dir"]).resolve(strict=False),
            }
            for key, item in list(cache.items()):
                if not isinstance(item, dict):
                    continue
                current = dict(item)
                source_dir = source_dir_map.get(key)
                if isinstance(source_dir, Path):
                    current["source_dir"] = str(source_dir)
                cache_name = Path(str(item.get("cache_path", "") or "")).name
                if cache_name:
                    current["cache_path"] = str((cache_dir / cache_name).resolve(strict=False))
                cache[key] = current
        except Exception:
            pass

    if isinstance(normalized.get("objective_profile"), dict):
        objective_meta = dict(normalized.get("objective", {}) or {})
        for key in ("type", "summary", "formula", "weights", "diagnostic_only_constraints"):
            if key in normalized["objective_profile"]:
                objective_meta[key] = normalized["objective_profile"][key]
        if objective_meta:
            normalized["objective"] = objective_meta

    if not effective_objective_mode:
        objective_profile = normalized.get("objective_profile") if isinstance(normalized.get("objective_profile"), dict) else {}
        objective_meta = normalized.get("objective") if isinstance(normalized.get("objective"), dict) else {}
        effective_objective_mode = profile_runner.normalize_objective_mode(
            optimization.get("effective_objective_mode")
            or objective_profile.get("type")
            or objective_meta.get("type")
            or optimization.get("objective_mode")
            or normalized.get("目标函数模式")
            or ""
        )
    if resolved_object_type:
        normalized["project_object_type"] = resolved_object_type

    if data_sources:
        normalized["data_sources"] = data_sources
    if boundary_condition:
        normalized["boundary_condition"] = boundary_condition
    source_run_path = _resolve_source_run_reference(
        replay_context.get("source_run_path")
        or manual_result.get("source_run_path")
        or optimization.get("source_run_path"),
        manual_result.get("source_run_name") or optimization.get("source_run_name"),
    ).strip()
    if source_run_path:
        replay_context["source_run_path"] = source_run_path
        if manual_result:
            manual_result["source_run_path"] = source_run_path
        if optimization:
            optimization["source_run_path"] = source_run_path
    if replay_context:
        normalized["replay_context"] = replay_context
    if manual_result:
        normalized["manual_result"] = manual_result
    if effective_objective_mode:
        if isinstance(normalized.get("objective_profile"), dict):
            normalized["objective_profile"]["type"] = effective_objective_mode
        if isinstance(normalized.get("objective"), dict):
            normalized["objective"]["type"] = effective_objective_mode
        normalized["effective_objective_mode"] = effective_objective_mode
        optimization["effective_objective_mode"] = effective_objective_mode
    if optimization:
        optimization = _normalize_optimization_metadata(
            optimization,
            effective_objective_mode=effective_objective_mode,
            fallback_total_evaluations=normalized.get("evaluations"),
        )
        normalized["optimization"] = optimization
        if _optimization_stage_counter(optimization.get("total_evaluations")) > 0:
            normalized["evaluations"] = _optimization_stage_counter(optimization.get("total_evaluations"))
    if cache:
        normalized["data_cache"] = cache
    return normalized, resolved_config


PATH_FIELDS = ("运行目录", "流域边界_shp", "DEM_tif", OBSERVED_FLOW_KEY, "冰川边界_shp")
METEO_PATH_FIELDS = ("站点降水_csv", "站点信息_csv", "原始小时降水目录", "自带温度tif目录", "自带降水tif目录", "自带蒸散发tif目录")
BOUNDARY_PATH_FIELDS = ("上游边界入流_csv",)
EVENT_PATH_FIELDS = ("事件表路径", "events_file", "event_file")
WIZARD_STALE_KEYS = frozenset({
    "name", "timescale", "object", "basin_shp", "obs_csv", "dem_tif", "glacier_shp",
    "warmup_start", "warmup_end", "calib_start", "calib_end", "valid_start", "valid_end",
    "cfmax", "fao_elev", "boundary_csv", "gap_fill", "boundary_date", "boundary_flow",
    "time_basis", "event_file",
})


def normalize_config_before_save(data: dict[str, Any], save_path: Path) -> dict[str, Any]:
    config = dict(data)
    config.pop("_config_path", None)
    # Expand any existing placeholders so downstream logic works with real paths
    config = replace_placeholders(config)
    profile = detect_profile_from_payload(config)
    object_type = detect_object_type(config)
    config["项目对象"] = object_type
    config["率定模式"] = profile
    config["时间步长_小时"] = 1.0 if profile == PROFILE_HOURLY else 24.0
    config["目标函数模式"] = profile_runner.normalize_objective_mode(config.get("目标函数模式", "auto"))
    config["观测口径模式"] = config.get("观测口径模式", "full_year") or "full_year"
    raw_time_basis = str(
        config.get("任务时段模式")
        or config.get("资料时段模式")
        or config.get("time_basis")
        or ""
    ).strip().lower()
    if raw_time_basis in {"event", "events", "event_window", "event_windows", "flood_event", "洪水事件", "事件窗口", "事件资料"}:
        config["任务时段模式"] = TIME_BASIS_EVENT_WINDOWS
    else:
        config["任务时段模式"] = TIME_BASIS_CONTINUOUS
    if not config.get("DEM_tif"):
        config["DEM_tif"] = str(BUILTIN_DEM.resolve())
    if (not str(config.get("冰川边界_shp", "")).strip()) and BUILTIN_GLACIER_SHP.exists():
        config["冰川边界_shp"] = str(BUILTIN_GLACIER_SHP.resolve())

    time_cfg = dict(config.get("时间", {}))
    step_hours = normalize_time_step_hours(config.get("时间步长_小时", 24.0))
    if time_cfg.get("预热开始") and time_cfg.get("率定开始") and (not time_cfg.get("预热结束")):
        try:
            time_values = {
                "预热开始": pd.to_datetime(time_cfg["预热开始"]),
                "率定开始": pd.to_datetime(time_cfg["率定开始"]),
            }
            warmup_end = expected_warmup_end(time_values, step_hours)
            if warmup_end is not None and time_values["预热开始"] <= warmup_end:
                time_cfg["预热结束"] = format_timestamp_for_display(warmup_end, step_hours)
        except Exception:
            pass
    parsed_starts = [pd.to_datetime(value) for value in [time_cfg.get("预热开始"), time_cfg.get("率定开始")] if value]
    parsed_ends = [pd.to_datetime(value) for value in [time_cfg.get("验证结束"), time_cfg.get("率定结束")] if value]
    if parsed_starts:
        time_cfg["开始年份"] = int(min(parsed_starts).year)
    if parsed_ends:
        time_cfg["结束年份"] = int(max(parsed_ends).year)
    config["时间"] = time_cfg

    bbox = fill_bbox_from_shp(config.get("流域边界_shp", ""))
    if bbox is not None:
        config["范围_bbox"] = bbox

    if not config.get("流域编号"):
        config["流域编号"] = save_path.stem
    if not config.get("流域名称"):
        config["流域名称"] = save_path.stem

    init_state = dict(config.get("初始状态", {}) or {})
    for key, value in profile_runner.DEFAULT_INIT_STATE.items():
        init_state.setdefault(key, value)
    config["初始状态"] = init_state

    boundary = dict(config.get("边界条件", {}))
    boundary.setdefault("上游边界入流_csv", "")
    boundary.setdefault("时间字段", "date")
    boundary.setdefault("流量字段", "inflow_m3s")
    boundary.setdefault("缺失填补", "zero")
    config["边界条件"] = boundary

    event_mode = dict(config.get("事件资料模式", {}) or {})
    flood_events = dict(config.get("洪水事件率定", {}) or {}) if isinstance(config.get("洪水事件率定", {}), dict) else {}
    event_file = str(
        event_mode.get("事件表路径")
        or event_mode.get("events_file")
        or flood_events.get("事件表路径")
        or flood_events.get("events_file")
        or ""
    ).strip()
    if event_file:
        event_mode["事件表路径"] = event_file
        flood_events["事件表路径"] = event_file
    if config["任务时段模式"] == TIME_BASIS_EVENT_WINDOWS:
        event_mode["启用"] = True
        event_mode["事件窗口资料"] = True
        event_mode.setdefault("允许事件间断", True)
        event_mode.setdefault("初始条件策略", "event_warmup")
        flood_events.setdefault("启用", True)
        flood_events["事件窗口资料"] = True
        flood_events.setdefault("模式", "diagnostic")
    else:
        event_mode.setdefault("启用", False)
        event_mode.setdefault("事件窗口资料", False)
    config["事件资料模式"] = event_mode
    config["洪水事件率定"] = flood_events

    meteo = dict(config.get(METEO_KEY, {}))
    meteo.setdefault(METEO_PRECIP_MODE_KEY, "grid_only")
    source_value = configured_precip_source(config)
    meteo[METEO_PRECIP_SOURCE_KEY] = source_value
    meteo[METEO_PRECIP_SOURCE_LEGACY_KEY] = source_value
    config["默认降水源"] = source_value
    meteo.setdefault(METEO_STATION_PREC_KEY, "")
    meteo.setdefault(METEO_STATION_META_KEY, "")
    meteo.setdefault(METEO_HOURLY_PREC_DIR_KEY, "")
    meteo.setdefault(METEO_TEMP_SOURCE_KEY, "era5")
    meteo.setdefault(METEO_CUSTOM_TEMP_DIR_KEY, "")
    meteo.setdefault(METEO_CUSTOM_PREC_DIR_KEY, "")
    meteo.setdefault(METEO_PET_SOURCE_KEY, "era5_fao56")
    meteo.setdefault(METEO_CUSTOM_PET_DIR_KEY, "")
    # Migrate legacy values
    legacy_temp = {"era5_land": "era5", "local_or_era5_hourly": "era5"}
    legacy_pet = {"era5_land_fao56": "era5_fao56", "hourly_era5_or_external": "era5_fao56"}
    if meteo[METEO_TEMP_SOURCE_KEY] in legacy_temp:
        meteo[METEO_TEMP_SOURCE_KEY] = legacy_temp[meteo[METEO_TEMP_SOURCE_KEY]]
    if meteo[METEO_PET_SOURCE_KEY] in legacy_pet:
        meteo[METEO_PET_SOURCE_KEY] = legacy_pet[meteo[METEO_PET_SOURCE_KEY]]
    config[METEO_KEY] = meteo

    # --- Portability: convert absolute paths to placeholders ---
    for key in PATH_FIELDS:
        if config.get(key):
            config[key] = to_portable_path(config[key])
    boundary = dict(config.get("边界条件", {}))
    for key in BOUNDARY_PATH_FIELDS:
        if boundary.get(key):
            boundary[key] = to_portable_path(boundary[key])
    config["边界条件"] = boundary
    event_mode = dict(config.get("事件资料模式", {}))
    for key in EVENT_PATH_FIELDS:
        if event_mode.get(key):
            event_mode[key] = to_portable_path(event_mode[key])
    config["事件资料模式"] = event_mode
    flood_events = dict(config.get("洪水事件率定", {})) if isinstance(config.get("洪水事件率定", {}), dict) else {}
    for key in EVENT_PATH_FIELDS:
        if flood_events.get(key):
            flood_events[key] = to_portable_path(flood_events[key])
    config["洪水事件率定"] = flood_events
    meteo = dict(config.get(METEO_KEY, {}))
    for key in METEO_PATH_FIELDS:
        if meteo.get(key):
            meteo[key] = to_portable_path(meteo[key])
    config[METEO_KEY] = meteo

    # --- Remove stale wizard keys ---
    for key in WIZARD_STALE_KEYS:
        config.pop(key, None)

    return config


def build_empty_workspace(name: str = "新流域工作区", profile: str = PROFILE_DAILY) -> dict[str, Any]:
    glacier_default = str(BUILTIN_GLACIER_SHP.resolve()) if BUILTIN_GLACIER_SHP.exists() else ""
    return {
        "_说明": [
            "HBV-Studio 生成的工作区配置。",
            "导入 shp + 观测径流后，系统会自动补齐范围、时间和默认 DEM。",
        ],
        "项目对象": OBJECT_FULL_UPSTREAM,
        "率定模式": profile,
        "目标函数模式": "auto",
        "任务时段模式": TIME_BASIS_CONTINUOUS,
        "运行目录": str(runtime_root_for_workspace(name)),
        "流域名称": name,
        "流域编号": slugify_workspace_name(name),
        "流域边界_shp": "",
        "DEM_tif": str(BUILTIN_DEM.resolve()),
        OBSERVED_FLOW_KEY: "",
        "观测口径模式": "full_year",
        "事件资料模式": {
            "启用": False,
            "事件窗口资料": False,
            "事件表路径": "",
            "允许事件间断": True,
            "初始条件策略": "event_warmup",
        },
        "洪水事件率定": {
            "启用": False,
            "事件窗口资料": False,
            "事件表路径": "",
            "模式": "diagnostic",
        },
        "边界条件": {
            "上游边界入流_csv": "",
            "时间字段": "date",
            "流量字段": "inflow_m3s",
            "缺失填补": "zero",
        },
        "气象策略": {
            "降水方案": "grid_only",
            "降水来源": "era5",
            "降水源": "era5",
            "站点降水_csv": "",
            "站点信息_csv": "",
            "原始小时降水目录": "",
            "自带降水tif目录": "",
            "温度来源": "era5",
            "自带温度tif目录": "",
            "潜在蒸散发来源": "era5_fao56",
            "自带蒸散发tif目录": "",
        },
        "冰川边界_shp": glacier_default,
        "范围_bbox": {"北": None, "西": None, "南": None, "东": None},
        "时间": {
            "开始年份": 2006,
            "结束年份": 2020,
            "预热开始": "",
            "预热结束": "",
            "率定开始": "",
            "率定结束": "",
            "验证开始": "",
            "验证结束": "",
        },
        "时间步长_小时": 24.0 if profile == PROFILE_DAILY else 1.0,
        "初始状态": dict(profile_runner.DEFAULT_INIT_STATE),
        "FAO56平均海拔_m": 4500.0,
        "默认降水源": "era5",
        "CFMAX分区阈值_m": 5000.0,
    }


def suggest_time_windows(start_date: pd.Timestamp, end_date: pd.Timestamp, profile: str) -> dict[str, str]:
    start_ts = pd.to_datetime(start_date)
    end_ts = pd.to_datetime(end_date)
    date_format = "%Y-%m-%d %H:%M" if profile == PROFILE_HOURLY else "%Y-%m-%d"
    if end_ts <= start_ts:
        return {
            "预热开始": start_ts.strftime(date_format),
            "预热结束": start_ts.strftime(date_format),
            "率定开始": start_ts.strftime(date_format),
            "率定结束": end_ts.strftime(date_format),
            "验证开始": end_ts.strftime(date_format),
            "验证结束": end_ts.strftime(date_format),
        }

    if profile == PROFILE_DAILY:
        start_is_year_start = (start_ts.month, start_ts.day) == (1, 1)
        end_is_year_end = (end_ts.month, end_ts.day) == (12, 31)
        first_full_year = start_ts.year if start_is_year_start else (start_ts.year + 1)
        last_full_year = end_ts.year if end_is_year_end else (end_ts.year - 1)
        full_year_count = last_full_year - first_full_year + 1
        if full_year_count >= 3:
            warmup_years = 2 if full_year_count >= 12 else 1
            valid_years = 3 if full_year_count >= 8 else (2 if full_year_count >= 5 else 1)
            while (full_year_count - warmup_years - valid_years) < 1:
                if valid_years > 1:
                    valid_years -= 1
                elif warmup_years > 1:
                    warmup_years -= 1
                else:
                    break
            if (full_year_count - warmup_years - valid_years) >= 1:
                warmup_end = pd.Timestamp(year=first_full_year + warmup_years - 1, month=12, day=31)
                calib_start = warmup_end + pd.Timedelta(days=1)
                valid_start = pd.Timestamp(year=last_full_year - valid_years + 1, month=1, day=1)
                calib_end = valid_start - pd.Timedelta(days=1)
                if calib_start <= calib_end:
                    return {
                        "预热开始": start_ts.strftime(date_format),
                        "预热结束": warmup_end.strftime(date_format),
                        "率定开始": calib_start.strftime(date_format),
                        "率定结束": calib_end.strftime(date_format),
                        "验证开始": valid_start.strftime(date_format),
                        "验证结束": end_ts.strftime(date_format),
                    }

    total_days = max((end_ts - start_ts).days, 1)
    if total_days < 365:
        warmup_end = start_ts
    elif total_days < 1095:
        warmup_end = start_ts + pd.DateOffset(years=1) - pd.Timedelta(days=1)
    else:
        warmup_end = start_ts + pd.DateOffset(years=2) - pd.Timedelta(days=1)
    remaining_start = warmup_end + pd.Timedelta(days=1)
    remaining_days = max((end_ts - remaining_start).days, 1)
    calib_end = remaining_start + pd.Timedelta(days=int(remaining_days * 0.7))
    valid_start = calib_end + pd.Timedelta(days=1)
    if valid_start > end_ts:
        valid_start = end_ts
        calib_end = max(remaining_start, valid_start - pd.Timedelta(days=1))
    return {
        "预热开始": start_ts.strftime(date_format),
        "预热结束": warmup_end.strftime(date_format),
        "率定开始": remaining_start.strftime(date_format),
        "率定结束": calib_end.strftime(date_format),
        "验证开始": valid_start.strftime(date_format),
        "验证结束": end_ts.strftime(date_format),
    }


def template_files() -> list[Path]:
    if not TEMPLATE_DIR.exists():
        return []
    files = {path.resolve(): path for path in TEMPLATE_DIR.glob("*.json")}
    files.update({path.resolve(): path for path in TEMPLATE_DIR.glob("*.template.json")})
    return sorted(files.values())


def list_templates() -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    for path in template_files():
        try:
            raw = read_json_file(path)
            resolved = replace_placeholders(raw)
            meta = raw.get("_studio_template", {})
            runtime_root = resolved.get("运行目录", "")
            runtime_path = Path(runtime_root) if runtime_root else None
            asset_ok = True
            for key in ("流域边界_shp", OBSERVED_FLOW_KEY):
                candidate = resolved.get(key, "")
                candidate_path = None
                if candidate:
                    try:
                        candidate_path = resolve_any_path(str(candidate), must_exist=False)
                    except Exception:
                        candidate_path = Path(str(candidate)).expanduser()
                if candidate and (candidate_path is None or not candidate_path.exists()):
                    asset_ok = False
                    break
            results.append(
                {
                    "id": meta.get("id", path.stem),
                    "title": meta.get("title", path.stem),
                    "description": meta.get("description", ""),
                    "calibration_mode": resolved.get("率定模式", PROFILE_DAILY),
                    "object_type": detect_object_type(resolved),
                    "path": str(path.resolve()),
                    "display_path": to_display_path(path),
                    "builtin": bool(meta.get("builtin", True)),
                    "runtime_root": str(runtime_path) if runtime_path else "",
                    "runtime_ready": bool(runtime_path and runtime_path.exists()),
                    "assets_ready": asset_ok,
                    "sync_hint": meta.get("sync_hint", ""),
                }
            )
        except Exception:
            continue
    return results


def find_template(template_id: str) -> Path:
    for path in template_files():
        raw = read_json_file(path)
        meta = raw.get("_studio_template", {})
        if meta.get("id") == template_id or path.stem == template_id:
            return path
    raise FileNotFoundError(template_id)


def instantiate_template(payload: dict[str, Any]) -> dict[str, Any]:
    template_id = str(payload.get("template_id", "")).strip()
    if not template_id:
        raise ValueError("缺少模板 ID。")
    target_name = str(payload.get("workspace_name", "")).strip() or "新流域工作区"
    template_path = find_template(template_id)
    raw = replace_placeholders(read_json_file(template_path))
    profile = resolve_profile(raw, None)
    config = normalize_config_before_save(raw, DEFAULT_WORKSPACE_PATH)
    if (not str(config.get("冰川边界_shp", "")).strip()) and BUILTIN_GLACIER_SHP.exists():
        config["冰川边界_shp"] = str(BUILTIN_GLACIER_SHP.resolve())
    if detect_object_type(config) != OBJECT_REGRESSION:
        config["流域名称"] = target_name
        config["流域编号"] = slugify_workspace_name(target_name)
    if template_id == "blank-workspace":
        config["运行目录"] = str(runtime_root_for_workspace(target_name))
    workspace_path = WORKSPACE_DIR / f"{slugify_workspace_name(target_name)}.json"
    write_json_file(workspace_path, normalize_config_before_save(config, workspace_path))
    return {
        "workspace_path": str(workspace_path.resolve()),
        "config": read_json_file(workspace_path),
        "template_id": template_id,
        "profile": profile,
    }


def list_workspaces() -> list[dict[str, Any]]:
    WORKSPACE_DIR.mkdir(parents=True, exist_ok=True)
    results: list[dict[str, Any]] = []
    for path in sorted(WORKSPACE_DIR.glob("*.json")):
        try:
            data = read_runtime_config(path)
            workflow = workspace_workflow_summary(str(path.resolve()), quick=True)
        except Exception:
            continue
        profile = resolve_profile(data, None)
        runtime_root = str(data.get("运行目录", "")).strip()
        results.append(
            {
                "name": path.stem,
                "path": str(path.resolve()),
                "display_path": to_display_path(path),
                "flow_name": data.get("流域名称", path.stem),
                "flow_id": data.get("流域编号", path.stem),
                "object_type": detect_object_type(data),
                "calibration_mode": profile,
                "time_step_hours": normalize_time_step_hours(data.get("时间步长_小时", 24.0)),
                "workspace_root": runtime_root,
                "runtime_display_path": (to_display_path(Path(runtime_root)) if runtime_root else ""),
                "workflow": workflow,
                "updated_at": path.stat().st_mtime,
            }
        )
    return sorted(results, key=lambda item: item["updated_at"], reverse=True)


def load_workspace_config(path_value: str) -> tuple[Path, dict[str, Any]]:
    path = resolve_any_path(path_value, must_exist=True)
    return path, read_runtime_config(path)


def _path_entry_count_signature(path: Path) -> tuple[Any, ...] | None:
    try:
        root_stat = path.stat()
    except Exception:
        return None
    return (int(getattr(root_stat, "st_mtime_ns", int(root_stat.st_mtime * 1e9))),)


def _count_path_entries(
    path: Path,
    *,
    pattern: str = "*",
    recursive: bool = False,
    only_dirs: bool = False,
    limit: int | None = None,
) -> tuple[int, bool]:
    if not path.exists() or not path.is_dir():
        return 0, False
    cache_key = ""
    signature = None
    if recursive:
        signature = _path_entry_count_signature(path)
        if signature is not None:
            cache_key = f"{path.resolve(strict=False)}|{pattern}|{int(recursive)}|{int(only_dirs)}|{limit or 0}"
            with PATH_ENTRY_COUNT_CACHE_LOCK:
                cached = PATH_ENTRY_COUNT_CACHE.get(cache_key)
                if cached and cached.get("signature") == signature:
                    return int(cached.get("count", 0)), bool(cached.get("truncated", False))
    try:
        iterator = path.rglob(pattern) if recursive else (path.iterdir() if pattern == "*" else path.glob(pattern))
        total = 0
        truncated = False
        for item in iterator:
            if only_dirs:
                if item.is_dir():
                    total += 1
            else:
                if item.is_file():
                    total += 1
            if limit is not None and total >= limit:
                truncated = True
                break
        if cache_key and signature is not None:
            with PATH_ENTRY_COUNT_CACHE_LOCK:
                PATH_ENTRY_COUNT_CACHE[cache_key] = {"signature": signature, "count": int(total), "truncated": bool(truncated)}
        return total, truncated
    except Exception:
        return 0, False


def _workspace_relative_path(root: Path, path: Path) -> str:
    resolved_root = root.resolve(strict=False)
    resolved = path.resolve(strict=False)
    try:
        rel = resolved.relative_to(resolved_root)
        text = str(rel).replace("\\", "/")
        return text or "."
    except ValueError:
        return to_display_path(resolved)


def _workspace_layout_item(
    root: Path,
    label: str,
    path: Path,
    purpose: str,
    *,
    stage_hint: str,
    target_step: int | None = None,
    kind: str = "dir",
    pattern: str | None = "*",
    recursive: bool = False,
    only_dirs: bool = False,
    count_noun: str = "个文件",
    empty_status: str = "目录已创建，暂未写入内容",
    scan_limit: int | None = None,
) -> dict[str, Any]:
    target = Path(path)
    exists = target.exists()
    count = 1 if exists and kind == "file" else 0
    count_truncated = False
    if exists and kind == "dir" and pattern is not None:
        count, count_truncated = _count_path_entries(target, pattern=pattern, recursive=recursive, only_dirs=only_dirs, limit=scan_limit)
    if kind == "file":
        status = "已存在" if exists else "未生成"
    elif not exists:
        status = "目录未创建"
    elif count > 0:
        status = f"已有 {count}{'+' if count_truncated else ''} {count_noun}"
    else:
        status = empty_status
    return {
        "label": label,
        "path": str(target.resolve(strict=False)),
        "display_path": _workspace_relative_path(root, target),
        "exists": exists,
        "kind": kind,
        "count": int(count),
        "count_is_approx": bool(count_truncated),
        "status": status,
        "purpose": purpose,
        "stage_hint": stage_hint,
        "target_step": target_step,
    }


def workspace_layout_summary(config_path_raw: str) -> dict[str, Any]:
    cfg_path, config = load_workspace_config(config_path_raw)
    profile = current_profile(config)
    paths = build_profile_paths(config, profile)
    workspace_root = Path(paths["workspace_root"]).resolve(strict=False)
    effective_prec_base_dir, effective_prec_dir, _ = effective_precip_paths(config, profile)
    result_profile_root = Path(paths["results_root"]).resolve(strict=False)
    gis_item = _workspace_layout_item(
        workspace_root,
        "地理数据目录",
        Path(paths["gis_dir"]),
        "DEM 裁剪、流量累积、流域掩膜、高程分区和冰川掩膜都保存在这里。",
        stage_hint="第 5 步重点查看",
        target_step=5,
        pattern="*.tif",
        recursive=False,
        count_noun="个栅格文件",
        empty_status="目录已创建，尚未生成地理栅格",
    )
    aligned_item = _workspace_layout_item(
        workspace_root,
        "标准气象驱动目录",
        Path(paths["aligned_dir"]),
        "模型实际读取的标准网格驱动都在这里，检查问题时优先看这个目录。",
        stage_hint="第 6 步重点查看",
        target_step=6,
        pattern="*.tif",
        recursive=True,
        scan_limit=120,
        count_noun="个驱动栅格",
        empty_status="目录已创建，尚未形成模型驱动",
    )
    runs_item = _workspace_layout_item(
        workspace_root,
        f"{PROFILE_LABELS[profile]}结果目录",
        Path(paths["runs_dir"]),
            "每一次率定、手调或输入预核算都会在这里生成独立结果子目录。",
        stage_hint="率定运行后查看",
        pattern="*",
        recursive=False,
        only_dirs=True,
        count_noun="组结果",
        empty_status="目录已创建，尚无运行结果",
    )
    items = [
        {
            "title": "入口与主目录",
            "items": [
                _workspace_layout_item(
                    workspace_root,
                    "工作区配置文件",
                    cfg_path,
                    "保存流域名称、时间分段、输入路径和率定配置，是整个工程的入口文件。",
                    stage_hint="第 1 步保存后生成",
                    target_step=1,
                    kind="file",
                ),
                _workspace_layout_item(
                    workspace_root,
                    "工程根目录",
                    workspace_root,
                    "这个目录下面统一放数据、过程产物、日志和率定结果。",
                    stage_hint="本地工程主目录",
                    target_step=1,
                    pattern=None,
                    empty_status="目录已创建",
                ),
            ],
        },
        {
            "title": "数据目录",
            "items": [
                gis_item,
                _workspace_layout_item(
                    workspace_root,
                    "原始气象资料目录",
                    Path(paths["raw_root"]),
                    "下载或导入后、裁剪对齐前的原始气象数据放在这里。",
                    stage_hint="第 6 步上游输入",
                    target_step=6,
                    pattern="*",
                    recursive=True,
                    scan_limit=80,
                    count_noun="个原始文件",
                    empty_status="目录已创建，尚未写入原始气象数据",
                ),
                aligned_item,
                _workspace_layout_item(
                    workspace_root,
                    "观测与对比资料目录",
                    Path(paths["observed_dir"]),
                    "用于保存观测相关副本或中间产物；原始观测 csv 仍按配置路径读取。",
                    stage_hint="观测相关",
                    target_step=2,
                    pattern="*",
                    recursive=True,
                    scan_limit=40,
                    count_noun="个文件",
                ),
            ],
        },
        {
            "title": "当前率定与输出",
            "items": [
                _workspace_layout_item(
                    workspace_root,
                    f"当前降水驱动目录（{display_runtime_precip_label(config)}）",
                    Path(effective_prec_dir),
                    "这是当前率定真正读取的降水目录。若启用了站点订正，这里就是订正后的运行目录；若未启用订正，这里就是基线目录。",
                    stage_hint="排查降水问题时优先看这里",
                    target_step=6,
                    pattern="*.tif",
                    recursive=True,
                    scan_limit=120,
                    count_noun="个降水栅格",
                    empty_status="目录已创建，尚未形成可运行降水驱动",
                ),
                _workspace_layout_item(
                    workspace_root,
                    "降水基线目录",
                    Path(effective_prec_base_dir),
                    "这是裁剪对齐后的基线降水目录。目录名里的 custom 表示本地导入栅格，corrected 表示站点订正后的运行副本。",
                    stage_hint="核对基线输入",
                    target_step=6,
                    pattern="*.tif",
                    recursive=True,
                    scan_limit=120,
                    count_noun="个栅格",
                ),
                _workspace_layout_item(
                    workspace_root,
                    "气温驱动目录",
                    Path(paths["aligned_temp_dir"]),
                    "模型运行时使用的标准气温栅格。",
                    stage_hint="排查气温问题时查看",
                    target_step=6,
                    pattern="*.tif",
                    recursive=True,
                    scan_limit=120,
                    count_noun="个气温栅格",
                ),
                _workspace_layout_item(
                    workspace_root,
                    "蒸散发驱动目录",
                    Path(paths["aligned_evap_dir"]),
                    "模型运行时使用的标准潜在蒸散发栅格。",
                    stage_hint="排查蒸散发问题时查看",
                    target_step=6,
                    pattern="*.tif",
                    recursive=True,
                    scan_limit=120,
                    count_noun="个蒸散发栅格",
                ),
                runs_item,
                _workspace_layout_item(
                    workspace_root,
                    "运行日志目录",
                    Path(paths["logs_dir"]),
                    "率定过程日志和阶段信息会写入这里。",
                    stage_hint="查看运行过程",
                    pattern="*",
                    recursive=False,
                    count_noun="个日志文件",
                    empty_status="目录已创建，尚未产生运行日志",
                ),
                _workspace_layout_item(
                    workspace_root,
                    "加速缓存目录",
                    Path(paths["cache_dir"]),
                    "数据栈缓存和运行时缓存放在这里，用于减少重复加载。",
                    stage_hint="提速相关",
                    pattern="*",
                    recursive=False,
                    count_noun="个缓存文件",
                    empty_status="目录已创建，尚未写入缓存",
                ),
            ],
        },
    ]
    if not gis_item["exists"] or gis_item["count"] <= 0:
        next_focus = {
            "label": "地理数据目录",
            "path": str(Path(paths["gis_dir"]).resolve(strict=False)),
            "reason": "先完成第 5 步，确保 DEM、流量累积和流域掩膜已经生成。",
        }
    elif not aligned_item["exists"] or aligned_item["count"] <= 0:
        next_focus = {
            "label": "模型驱动目录",
            "path": str(Path(paths["aligned_dir"]).resolve(strict=False)),
            "reason": "下一步应检查第 6 步输出，确认降水、气温和蒸散发已形成标准驱动。",
        }
    elif runs_item["count"] <= 0:
        next_focus = {
            "label": f"{PROFILE_LABELS[profile]}结果目录",
            "path": str(Path(paths["runs_dir"]).resolve(strict=False)),
            "reason": "输入已经基本具备，接下来可以生成手调起点或启动率定。",
        }
    else:
        next_focus = {
            "label": f"{PROFILE_LABELS[profile]}结果目录",
            "path": str(Path(paths["runs_dir"]).resolve(strict=False)),
            "reason": "当前已有历史结果，可直接对比结果、日志和加速缓存。",
        }
    return {
        "config_path": str(cfg_path.resolve()),
        "config_display_path": to_display_path(cfg_path),
        "workspace_root": str(workspace_root),
        "workspace_display_root": to_display_path(workspace_root),
        "results_root": str(result_profile_root),
        "results_display_root": to_display_path(result_profile_root),
        "flow_name": str(config.get("流域名称", cfg_path.stem)).strip() or cfg_path.stem,
        "profile": profile,
        "profile_label": PROFILE_LABELS.get(profile, profile),
        "object_type": detect_object_type(config),
        "headline": "一个工作区由“配置文件 + 本地工程目录”组成；真正参与模型运行的核心目录是“地理数据目录”“标准气象驱动目录”和“结果目录”。",
        "next_focus": next_focus,
        "groups": items,
        "notes": [
            "删除工作区配置文件不会自动删除工程目录中的数据。",
            "排查输入问题时，优先查看“标准气象驱动目录”，而不是原始气象资料目录。",
            "率定结果、日志和缓存都按率定模式分别存放在对应的日尺度或小时尺度结果目录下。",
        ],
    }


def delete_workspace(path_value: str) -> dict[str, Any]:
    path = resolve_any_path(path_value, must_exist=True)
    ensure_within(WORKSPACE_DIR, path)
    name = path.stem
    path.unlink()
    return {"deleted": True, "name": name, "path": str(path)}


def delete_run(run_path_raw: str) -> dict[str, Any]:
    run_dir = resolve_any_path(run_path_raw, must_exist=True)
    metadata_path = run_dir / "metadata.json"
    simulation_path = run_dir / "simulation.csv"
    if not run_dir.is_dir() or not metadata_path.exists() or not simulation_path.exists():
        raise ValueError("目标目录不是可识别的结果目录。")
    known_runs = {Path(item["path"]).resolve(strict=False) for item in list_runs()}
    if run_dir.resolve(strict=False) not in known_runs:
        raise ValueError("该结果目录不在当前工程可管理范围内。")
    name = summarize_run(run_dir).get("name") or run_dir.name
    shutil.rmtree(run_dir)
    invalidate_deleted_run_refs(run_dir)
    return {"deleted": True, "name": name, "path": str(run_dir.resolve(strict=False))}


def rename_run(payload: dict[str, Any]) -> dict[str, Any]:
    run_path_raw = str(payload.get("path", "")).strip()
    if not run_path_raw:
        raise ValueError("缺少结果路径。")
    run_dir = resolve_any_path(run_path_raw, must_exist=True)
    metadata_path = run_dir / "metadata.json"
    simulation_path = run_dir / "simulation.csv"
    if not run_dir.is_dir() or not metadata_path.exists() or not simulation_path.exists():
        raise ValueError("目标目录不是可识别的结果目录。")
    known_runs = {Path(item["path"]).resolve(strict=False) for item in list_runs()}
    if run_dir.resolve(strict=False) not in known_runs:
        raise ValueError("该结果目录不在当前工程可管理范围内。")
    new_title = _normalized_result_title(payload.get("title", ""))
    if len(new_title) > 60:
        raise ValueError("结果标题请控制在 60 个字符以内。")
    metadata = read_json_file(metadata_path)
    if new_title:
        metadata["result_title"] = new_title
    else:
        metadata.pop("result_title", None)
    write_json_file(metadata_path, metadata)
    updated = summarize_run(run_dir)
    return {
        "renamed": True,
        "path": str(run_dir.resolve(strict=False)),
        "title": new_title,
        "auto_named": not bool(new_title),
        "run": updated,
    }


def create_workspace_from_import(payload: dict[str, Any]) -> dict[str, Any]:
    basin_shp = str(payload.get("basin_shp", "")).strip()
    obs_csv = str(payload.get("obs_csv", "")).strip()
    calibration_mode = str(payload.get("calibration_mode", "")).strip().lower()
    object_type = str(payload.get("object_type", "")).strip().lower() or OBJECT_FULL_UPSTREAM
    if object_type not in {OBJECT_REGRESSION, OBJECT_INTERBASIN, OBJECT_FULL_UPSTREAM}:
        object_type = OBJECT_FULL_UPSTREAM
    workspace_name = str(payload.get("workspace_name", "")).strip()
    prec_source = str(payload.get("prec_source", "era5")).strip()
    if not basin_shp:
        raise ValueError("缺少流域边界 shapefile。")
    if not obs_csv:
        raise ValueError("缺少观测径流文件。")
    shp_path = resolve_any_path(basin_shp, must_exist=True)
    obs_path = resolve_any_path(obs_csv, must_exist=True)
    obs_info = inspect_observed_csv(str(obs_path))
    suggested_mode = obs_info["suggested_calibration_mode"]
    profile = calibration_mode if calibration_mode in {PROFILE_DAILY, PROFILE_HOURLY} else suggested_mode
    start_date = pd.to_datetime(obs_info["start"])
    end_date = pd.to_datetime(obs_info["end"])
    bbox = fill_bbox_from_shp(str(shp_path))
    if bbox is None:
        raise ValueError("无法从 shapefile 中读取范围。")
    if not workspace_name:
        workspace_name = shp_path.stem

    windows = suggest_time_windows(start_date, end_date, profile)

    cfmax_threshold = 5000.0
    if BUILTIN_DEM.exists():
        try:
            cfmax_threshold = suggest_cfmax_threshold(str(shp_path), str(BUILTIN_DEM))["suggested_threshold_m"]
        except Exception:
            pass

    config = build_empty_workspace(workspace_name, profile)
    config.update(
        {
            "_说明": [
                "由 HBV-Studio 导入流域向导自动生成。",
                f"源数据: basin={shp_path.name}, obs={obs_path.name}",
            ],
            "项目对象": object_type,
            "率定模式": profile,
            "运行目录": str(runtime_root_for_workspace(workspace_name)),
            "流域名称": workspace_name,
            "流域编号": slugify_workspace_name(workspace_name),
            "流域边界_shp": str(shp_path),
            OBSERVED_FLOW_KEY: str(obs_path),
            "时间步长_小时": 24.0 if profile == PROFILE_DAILY else 1.0,
            "默认降水源": prec_source,
            "FAO56平均海拔_m": cfmax_threshold,
            "CFMAX分区阈值_m": cfmax_threshold,
            "范围_bbox": bbox,
            "时间": {
                "开始年份": int(start_date.year),
                "结束年份": int(end_date.year),
                **windows,
            },
        }
    )
    meteo = dict(config.get(METEO_KEY, {}))
    meteo[METEO_PRECIP_SOURCE_KEY] = prec_source
    meteo[METEO_PRECIP_SOURCE_LEGACY_KEY] = prec_source
    config[METEO_KEY] = meteo
    workspace_path = WORKSPACE_DIR / f"{slugify_workspace_name(workspace_name)}.json"
    config["流域边界_shp"] = str(stage_vector_shapefile(config, shp_path, role="basin", config_path=workspace_path))
    if str(config.get("冰川边界_shp", "")).strip():
        config["冰川边界_shp"] = str(
            stage_vector_shapefile(config, config["冰川边界_shp"], role="glacier", config_path=workspace_path)
        )
    config[OBSERVED_FLOW_KEY] = str(stage_observed_runoff_file(config, obs_path, config_path=workspace_path))
    write_json_file(workspace_path, normalize_config_before_save(config, workspace_path))
    return {
        "workspace_path": str(workspace_path.resolve()),
        "config": read_json_file(workspace_path),
        "obs_info": obs_info,
        "suggested_mode": suggested_mode,
        "profile": profile,
    }


def current_profile(config: dict[str, Any]) -> str:
    return resolve_profile(config, None)


def count_matching(path: Path, pattern: str = "*.tif") -> int:
    if not path.exists():
        return 0
    return len(list(path.glob(pattern)))


def has_matching(path: Path, pattern: str = "*.tif") -> bool:
    if not path.exists():
        return False
    return next(path.glob(pattern), None) is not None


def _series_group_status(entries: list[tuple[str, Path]], step_hours: float) -> tuple[bool, str, int, list[dict[str, Any]]]:
    results: list[dict[str, Any]] = []
    total = 0
    for label, directory in entries:
        result = validate_tif_time_series(label, directory, step_hours)
        results.append(result)
        total += int(result["valid_time_steps"])
    ready = all(result["ok"] and int(result["valid_time_steps"]) > 0 for result in results)
    if ready:
        message = "；".join(f"{result['label']}: {result['valid_time_steps']}" for result in results)
        return True, message, total, results
    issues = [result["errors"][0] for result in results if result["errors"]]
    if issues:
        return False, "；".join(issues[:2]), total, results
    return False, "未检测到有效 tif 时间序列。", total, results


def _prefer_raw_or_aligned_group_status(
    raw_entries: list[tuple[str, Path]],
    aligned_entries: list[tuple[str, Path]],
    step_hours: float,
) -> tuple[bool, str, int]:
    raw_ok, raw_message, raw_count, raw_results = _series_group_status(raw_entries, step_hours)
    aligned_ok, aligned_message, aligned_count, aligned_results = _series_group_status(aligned_entries, step_hours)
    if raw_ok:
        return True, raw_message, raw_count
    if aligned_ok:
        return True, f"{aligned_message}（已导入并完成网格对齐）", aligned_count
    raw_has_files = any(int(result["total_files"]) > 0 for result in raw_results)
    aligned_has_files = any(int(result["total_files"]) > 0 for result in aligned_results)
    if aligned_has_files:
        return False, aligned_message, aligned_count
    if raw_has_files:
        return False, raw_message, raw_count
    return False, raw_message, 0


def _configured_daily_meteo_sources(config: dict[str, Any]) -> tuple[str, str]:
    meteo = dict(config.get("气象策略", {}))
    temp_source = str(meteo.get("温度来源", "era5")).strip().lower() or "era5"
    pet_source = str(meteo.get("潜在蒸散发来源", meteo.get("蒸散发来源", "era5_fao56"))).strip().lower() or "era5_fao56"
    return temp_source, pet_source


def _glob_count(path: Path, pattern: str) -> int:
    if not path.exists():
        return 0
    return len(list(path.glob(pattern)))


def _summarize_nc_download_status(entries: list[tuple[str, Path, str]]) -> tuple[bool, str, int]:
    if not entries:
        return True, "当前方案不需要这一步。", 0
    existing: list[str] = []
    missing: list[str] = []
    total = 0
    for label, directory, pattern in entries:
        count = _glob_count(directory, pattern)
        total += count
        if count > 0:
            existing.append(f"{label} {count} 个")
        else:
            missing.append(label)
    if not missing:
        return True, "已下载：" + "；".join(existing), total
    if existing:
        return False, "已下载：" + "；".join(existing) + f"；仍缺少：{'、'.join(missing)}", total
    return False, "还没有下载到这一步需要的 ERA5 原始文件。", 0


def hourly_forcing_ready(config: dict[str, Any], precip_source: Any = None) -> tuple[bool, str, int]:
    base_paths = build_workspace_paths(config)
    forcing = validate_forcing_bundle(config, PROFILE_HOURLY, precip_source=precip_source)
    counts = {key: forcing["directories"][key]["valid_time_steps"] for key in ("prec", "temp", "evap")}
    detail = ""
    if forcing["errors"]:
        detail = f"；问题：{'；'.join(forcing['errors'][:2])}"
    return (
        forcing["ok"],
        f"小时气象驱动：降水={counts['prec']} 气温={counts['temp']} 蒸散={counts['evap']}（工程目录={base_paths['workspace_root']}）{detail}",
        forcing["total_valid_steps"],
    )


StepCheck = Callable  # type alias: (config: dict) -> (bool, str, int)


def check_clip_dem(config: dict[str, Any]) -> tuple[bool, str, int]:
    paths = build_profile_paths(config, current_profile(config))
    target = _workspace_dem_path(paths["gis_dir"], prefer=_configured_dem_kind(config))
    return target.exists(), "已生成 DEM" if target.exists() else "尚未生成", 1 if target.exists() else 0


def check_flow_acc(config: dict[str, Any]) -> tuple[bool, str, int]:
    paths = build_profile_paths(config, current_profile(config))
    target = Path(paths["gis_dir"]) / "flow_accumulation.tif"
    return target.exists(), "已生成流量累积" if target.exists() else "尚未生成", 1 if target.exists() else 0


def check_masked_flow(config: dict[str, Any]) -> tuple[bool, str, int]:
    paths = build_profile_paths(config, current_profile(config))
    target = Path(paths["gis_dir"]) / "flow_accumulation_masked.tif"
    return target.exists(), "已生成流域掩膜" if target.exists() else "尚未生成", 1 if target.exists() else 0


def check_elevation_zone(config: dict[str, Any]) -> tuple[bool, str, int]:
    paths = build_profile_paths(config, current_profile(config))
    low_exists = (Path(paths["gis_dir"]) / "elevation_zone_low.tif").exists() or (Path(paths["gis_dir"]) / "elevation_zone_mid.tif").exists()
    high_exists = (Path(paths["gis_dir"]) / "elevation_zone_high.tif").exists()
    count = int(low_exists) + int(high_exists)
    return count == 2, f"高程分区文件 {count}/2", count


def check_daily_temp_evap(config: dict[str, Any]) -> tuple[bool, str, int]:
    paths = build_profile_paths(config, PROFILE_DAILY)
    return _prefer_raw_or_aligned_group_status(
        [
            ("日尺度 ERA5 温度中间结果", Path(paths["raw_temp_daily_dir"])),
            ("日尺度潜在蒸散发中间结果", Path(paths["raw_evap_daily_dir"])),
        ],
        [
            ("工程气温输入", Path(paths["aligned_temp_dir"])),
            ("工程潜在蒸散发输入", Path(paths["aligned_evap_dir"])),
        ],
        24.0,
    )


def check_daily_era5_download(config: dict[str, Any]) -> tuple[bool, str, int]:
    paths = build_workspace_paths(config)
    temp_source, pet_source = _configured_daily_meteo_sources(config)
    precip_source = configured_precip_source(config)
    entries: list[tuple[str, Path, str]] = []
    if precip_source == "era5":
        entries.append(("ERA5 降水", Path(paths["raw_prec_era5_dir"]), "era5_tp_*.nc"))
    if temp_source != "custom_tif" or pet_source != "custom_tif":
        entries.append(("ERA5 温度", Path(paths["raw_temp_dir"]), "era5_t2m_*.nc"))
    if pet_source != "custom_tif":
        entries.extend(
            [
                ("太阳辐射", Path(paths["raw_solar_dir"]), "era5_ssrd_*.nc"),
                ("风速(U)", Path(paths["raw_wind_dir"]), "era5_u10_*.nc"),
                ("风速(V)", Path(paths["raw_wind_dir"]), "era5_v10_*.nc"),
                ("露点温度", Path(paths["raw_dewpoint_dir"]), "era5_d2m_*.nc"),
            ]
        )
    return _summarize_nc_download_status(entries)


def check_daily_era5_processed(config: dict[str, Any]) -> tuple[bool, str, int]:
    paths = build_profile_paths(config, PROFILE_DAILY)
    temp_source, pet_source = _configured_daily_meteo_sources(config)
    raw_entries: list[tuple[str, Path]] = []
    aligned_entries: list[tuple[str, Path]] = []
    if temp_source != "custom_tif":
        raw_entries.append(("日尺度气温结果", Path(paths["raw_temp_daily_dir"])))
        aligned_entries.append(("工程气温输入", Path(paths["aligned_temp_dir"])))
    if pet_source != "custom_tif":
        raw_entries.append(("日尺度潜在蒸散发结果", Path(paths["raw_evap_daily_dir"])))
        aligned_entries.append(("工程潜在蒸散发输入", Path(paths["aligned_evap_dir"])))
    if not raw_entries:
        return True, "当前方案不需要这一步。", 0
    return _prefer_raw_or_aligned_group_status(raw_entries, aligned_entries, 24.0)


def check_daily_prec(config: dict[str, Any], precip_source: Any = None) -> tuple[bool, str, int]:
    paths = build_profile_paths(config, PROFILE_DAILY)
    source_key = resolve_precip_source(config, precip_source)
    if source_key == "custom_tif":
        aligned = Path(paths["aligned_prec_custom_base_dir"])
        if count_matching(aligned) > 0:
            return True, "当前为本地栅格降水模式，降水已导入工程独立降水目录。", count_matching(aligned)
        return True, "当前为本地栅格降水模式，不需要执行原始降水预处理。", 0
    source = effective_precip_source(source_key)
    if source == "era5":
        target = paths["raw_prec_era5_daily_dir"]
        aligned = paths["aligned_prec_era5_base_dir"]
    elif source == "cmfd":
        target = paths["raw_prec_cmfd_daily_dir"]
        aligned = paths["aligned_prec_cmfd_base_dir"]
    else:
        target = paths["raw_prec_daily_dir"]
        aligned = paths["aligned_prec_base_dir"]
    return _prefer_raw_or_aligned_group_status(
        [("日尺度降水中间结果", Path(target))],
        [("工程降水输入", Path(aligned))],
        24.0,
    )


def check_daily_aligned(config: dict[str, Any], precip_source: Any = None) -> tuple[bool, str, int]:
    paths = build_profile_paths(config, PROFILE_DAILY)
    precip_dir, _, _ = effective_precip_paths(config, PROFILE_DAILY, precip_source=precip_source)
    step_hours = normalize_time_step_hours(config.get("时间步长_小时", 24.0))
    scans = [
        validate_tif_time_series("降水", precip_dir, step_hours),
        validate_tif_time_series("气温", Path(paths["aligned_temp_dir"]), step_hours),
        validate_tif_time_series("蒸散发", Path(paths["aligned_evap_dir"]), step_hours),
    ]
    count = sum(int(item["valid_time_steps"]) for item in scans)
    ready = all(item["ok"] for item in scans)
    message = "；".join(item["errors"][0] for item in scans if item["errors"]) or f"日尺度气象驱动有效时间步：{count}"
    return ready, message, count


def check_precip_strategy_outputs(config: dict[str, Any], precip_source: Any = None) -> tuple[bool, str, int]:
    meteo = dict(config.get("气象策略", {}))
    mode = str(meteo.get("降水方案", "grid_only")).strip()
    profile = current_profile(config)
    base_dir, corrected_dir, selected_source = effective_precip_paths(config, profile, precip_source=precip_source)
    if mode == "grid_only":
        count = count_matching(base_dir)
        label = "当前为本地栅格基线方案，不需要额外订正。" if selected_source == "custom_tif" else "当前为格点基线方案，不需要额外订正。"
        return count > 0, label, count
    count = count_matching(corrected_dir)
    label = "站点订正降水" if mode == "grid_plus_station_bias" else "泰森插值降水"
    return count > 0, f"{label}文件数：{count}", count


def _detect_table_column(columns: list[str], candidates: list[str]) -> str | None:
    lowered = {str(col).strip().lower(): str(col) for col in columns}
    for candidate in candidates:
        found = lowered.get(candidate.lower())
        if found is not None:
            return found
    return None


def _detect_table_time_column(frame: pd.DataFrame) -> str | None:
    for column in frame.columns:
        parsed = pd.to_datetime(frame[column], errors="coerce")
        if int(parsed.notna().sum()) >= max(1, len(frame) // 3):
            return str(column)
    return None


def _read_station_csv(path: Path) -> pd.DataFrame:
    last_error: Exception | None = None
    for encoding in ("utf-8-sig", "utf-8", "gbk"):
        try:
            return pd.read_csv(path, encoding=encoding)
        except UnicodeDecodeError as exc:
            last_error = exc
    if last_error is not None:
        raise last_error
    return pd.read_csv(path)


def _time_range_from_config(config: dict[str, Any]) -> tuple[pd.Timestamp | None, pd.Timestamp | None]:
    time_cfg = dict(config.get("时间", {}) or {})
    start_raw = str(time_cfg.get("预热开始") or time_cfg.get("率定开始") or "").strip()
    end_raw = str(time_cfg.get("验证结束") or time_cfg.get("率定结束") or "").strip()
    try:
        start = pd.to_datetime(start_raw) if start_raw else None
    except Exception:
        start = None
    try:
        end = pd.to_datetime(end_raw) if end_raw else None
    except Exception:
        end = None
    return start, end


def _format_time_for_check(value: Any, step_hours: float) -> str:
    if value in (None, ""):
        return ""
    try:
        ts = pd.to_datetime(value)
    except Exception:
        return "未识别"
    if pd.isna(ts):
        return ""
    if abs(float(step_hours) - 24.0) < 1e-9 and ts.hour == 0 and ts.minute == 0 and ts.second == 0:
        return ts.strftime("%Y-%m-%d")
    return ts.strftime("%Y-%m-%d %H:%M")


def event_windows_ui_summary(event_info: dict[str, Any] | None, step_hours: float) -> dict[str, Any] | None:
    if not isinstance(event_info, dict):
        return None
    events = list(event_info.get("events", []) or [])
    valid_events = list(event_info.get("valid_events", []) or [])

    def convert_event(event: dict[str, Any]) -> dict[str, Any]:
        return {
            "event_id": event.get("event_id", ""),
            "name": event.get("name", "") or event.get("event_id", ""),
            "purpose": event.get("purpose", ""),
            "weight": event.get("weight"),
            "valid": bool(event.get("valid")),
            "run_start": _format_time_for_check(event.get("run_start"), step_hours),
            "score_start": _format_time_for_check(event.get("score_start"), step_hours),
            "score_end": _format_time_for_check(event.get("score_end"), step_hours),
            "run_end": _format_time_for_check(event.get("run_end"), step_hours),
            "time_steps_run": int(event.get("time_steps_run", 0) or 0),
            "time_steps_score": int(event.get("time_steps_score", 0) or 0),
        }

    return {
        "enabled": bool(event_info.get("enabled")),
        "source_file": str(event_info.get("source_file", "") or ""),
        "event_count": int(event_info.get("event_count", 0) or 0),
        "valid_event_count": int(event_info.get("valid_event_count", 0) or 0),
        "purpose_counts": dict(event_info.get("purpose_counts", {}) or {}),
        "warnings": [str(item) for item in list(event_info.get("warnings", []) or [])],
        "errors": [str(item) for item in list(event_info.get("errors", []) or [])],
        "events": [convert_event(item) for item in events if isinstance(item, dict)],
        "valid_events": [convert_event(item) for item in valid_events if isinstance(item, dict)],
        "time_basis": TIME_BASIS_EVENT_WINDOWS,
        "initial_state_policy": str(event_info.get("initial_state_policy", "event_warmup") or "event_warmup"),
        "initial_state_policy_label": str(event_info.get("initial_state_policy_label", "事件预热") or "事件预热"),
        "state_continuity_between_events": bool(event_info.get("state_continuity_between_events")),
        "initial_state_note": str(event_info.get("initial_state_note", "") or ""),
        "initial_state_warning": str(event_info.get("initial_state_warning", "") or ""),
    }


def input_time_basis_ui_summary(
    config: dict[str, Any],
    *,
    time_basis: str,
    step_hours: float,
    event_info: dict[str, Any] | None = None,
    context: str = "calibration",
) -> dict[str, Any]:
    label = TIME_BASIS_LABELS.get(time_basis, "当前任务时段")

    def index_range(index: pd.DatetimeIndex | None) -> tuple[str, str, int]:
        if index is None or len(index) <= 0:
            return "", "", 0
        return _format_time_for_check(index[0], step_hours), _format_time_for_check(index[-1], step_hours), int(len(index))

    if time_basis == TIME_BASIS_EVENT_WINDOWS:
        info = event_info if isinstance(event_info, dict) else normalized_flood_events(config, step_hours=step_hours)
        valid_events = list(info.get("valid_events", []) or [])
        run_index = _event_window_index(valid_events, "run_start", "run_end", step_hours)
        start, end, expected_steps = index_range(run_index)
        event_count = int(info.get("event_count", 0) or 0)
        valid_event_count = int(info.get("valid_event_count", 0) or 0)
        counts = dict(info.get("purpose_counts", {}) or {})
        status = "fail" if valid_event_count <= 0 else "warn" if info.get("errors") or info.get("warnings") else "ok"
        initial_label = str(info.get("initial_state_policy_label", "事件预热") or "事件预热")
        initial_note = str(info.get("initial_state_note", "") or "")
        headline = (
            f"当前按 {valid_event_count} 场洪水事件窗口检查，事件之间允许资料间断。"
            if valid_event_count > 0
            else "当前选择洪水事件窗口，但尚未识别到合法事件。"
        )
        return {
            "time_basis": time_basis,
            "time_basis_label": label,
            "headline": headline,
            "detail": "气象强迫按运行窗口检查，观测径流按评分窗口检查；事件内部资料必须连续。"
            + (f" {initial_note}" if initial_note else ""),
            "start": start,
            "end": end,
            "expected_steps": expected_steps,
            "event_count": event_count,
            "valid_event_count": valid_event_count,
            "purpose_counts": counts,
            "status": status,
            "items": [
                {"label": "资料口径", "value": label},
                {"label": "有效事件", "value": f"{valid_event_count}/{event_count} 场"},
                {"label": "事件用途", "value": f"率定 {int(counts.get('calibration', 0) or 0)}、验证 {int(counts.get('validation', 0) or 0)}、诊断 {int(counts.get('diagnostic', 0) or 0)}"},
                {"label": "运行窗口", "value": f"{start} 至 {end}" if start and end else "未形成有效运行窗口"},
                {"label": "初始条件", "value": initial_label},
                {"label": "目标时间步", "value": str(expected_steps) if expected_steps else "未形成"},
            ],
            "initial_state_policy": str(info.get("initial_state_policy", "event_warmup") or "event_warmup"),
            "initial_state_policy_label": initial_label,
            "state_continuity_between_events": bool(info.get("state_continuity_between_events")),
            "initial_state_note": initial_note,
        }

    try:
        expected_index = build_expected_forcing_index(config, context=context)
    except Exception:
        expected_index = None
    start, end, expected_steps = index_range(expected_index)
    status = "ok" if expected_steps else "warn"
    if time_basis == TIME_BASIS_FORECAST_WINDOW:
        headline = (
            f"当前按连续状态预报窗口检查：{start} 至 {end}。"
            if start and end
            else "当前按连续状态预报窗口检查，但预报起止时间尚未完整配置。"
        )
        detail = "预报窗口内降水、气温和潜在蒸散发必须连续；多余气象文件不作为本次预报依据。"
    else:
        headline = (
            f"当前按连续时段检查：{start} 至 {end}。"
            if start and end
            else "当前按连续时段检查，但预热、率定或验证时间尚未完整配置。"
        )
        detail = "连续模拟要求目标时间轴内降水、气温、潜在蒸散发和必要观测资料连续覆盖。"
    return {
        "time_basis": time_basis,
        "time_basis_label": label,
        "headline": headline,
        "detail": detail,
        "start": start,
        "end": end,
        "expected_steps": expected_steps,
        "status": status,
        "items": [
            {"label": "资料口径", "value": label},
            {"label": "检查范围", "value": f"{start} 至 {end}" if start and end else "未完整配置"},
            {"label": "目标时间步", "value": str(expected_steps) if expected_steps else "未形成"},
            {"label": "时间步长", "value": f"{step_hours:g} 小时"},
        ],
    }


def _load_station_precip_table(path: Path) -> tuple[pd.DataFrame, str, str | None]:
    frame = _read_station_csv(path)
    if frame.empty:
        raise ValueError("站点降水 csv 为空。")
    time_col = _detect_table_time_column(frame)
    if not time_col:
        raise ValueError("站点降水 csv 未识别到时间列。")

    columns = [str(col) for col in frame.columns]
    id_col = _detect_table_column(columns, ["station_id", "station", "id", "name", "站点", "站号"])
    value_col = _detect_table_column(columns, ["precip", "prec", "ppt", "rain", "value", "降水", "降水量"])
    if id_col and value_col and id_col != time_col and value_col != time_col:
        data = frame[[time_col, id_col, value_col]].copy()
        data.columns = ["time", "station_id", "value"]
        data["time"] = pd.to_datetime(data["time"], errors="coerce")
        data["station_id"] = data["station_id"].astype(str).str.strip()
        data["value"] = pd.to_numeric(data["value"], errors="coerce")
        wide = data.pivot_table(index="time", columns="station_id", values="value", aggfunc="mean")
        wide.columns = [str(col).strip() for col in wide.columns]
        return wide.sort_index(), "长表", time_col

    wide = frame.copy()
    wide[time_col] = pd.to_datetime(wide[time_col], errors="coerce")
    wide = wide.dropna(subset=[time_col]).set_index(time_col).sort_index()
    wide.columns = [str(col).strip() for col in wide.columns]
    for column in list(wide.columns):
        wide[column] = pd.to_numeric(wide[column], errors="coerce")
    return wide, "宽表", time_col


def _load_station_metadata_table(path: Path) -> tuple[pd.DataFrame, dict[str, str | None]]:
    frame = _read_station_csv(path)
    if frame.empty:
        raise ValueError("站点信息 csv 为空。")
    columns = [str(col) for col in frame.columns]
    id_col = _detect_table_column(columns, ["station_id", "station", "id", "name", "站点", "站号"])
    lon_col = _detect_table_column(columns, ["lon", "longitude", "x", "经度"])
    lat_col = _detect_table_column(columns, ["lat", "latitude", "y", "纬度"])
    if not id_col:
        raise ValueError("站点信息 csv 未识别到站号字段。")
    out = frame.copy()
    out["_station_id"] = out[id_col].astype(str).str.strip()
    return out, {"id": id_col, "lon": lon_col, "lat": lat_col}


def analyze_station_precip_inputs(config: dict[str, Any], *, step_hours: float | None = None) -> dict[str, Any]:
    meteo = dict(config.get(METEO_KEY, {}) or {})
    mode = str(meteo.get(METEO_PRECIP_MODE_KEY, "grid_only")).strip() or "grid_only"
    if mode == "grid_only":
        return {
            "enabled": False,
            "mode": mode,
            "status": "ok",
            "summary": "当前为格点基线模式，未启用站点降水订正或泰森分配。",
            "items": [],
            "warnings": [],
            "missing": [],
            "matched_station_count": 0,
        }

    step = float(step_hours if step_hours is not None else normalize_time_step_hours(config.get("时间步长_小时", 24.0)))
    station_prec_raw = str(meteo.get(METEO_STATION_PREC_KEY, "") or "").strip()
    station_meta_raw = str(meteo.get(METEO_STATION_META_KEY, "") or "").strip()
    station_prec_path = _resolve_config_related_path(config, station_prec_raw)
    station_meta_path = _resolve_config_related_path(config, station_meta_raw)
    missing: list[str] = []
    warnings: list[str] = []
    items: list[dict[str, Any]] = []

    if not station_prec_raw:
        missing.append("降水方案需要 站点降水_csv。")
    elif station_prec_path is None or not station_prec_path.exists():
        missing.append(f"站点降水文件不存在：{station_prec_raw}")
    if not station_meta_raw:
        missing.append("降水方案需要 站点信息_csv。")
    elif station_meta_path is None or not station_meta_path.exists():
        missing.append(f"站点信息文件不存在：{station_meta_raw}")
    if missing:
        return {
            "enabled": True,
            "mode": mode,
            "status": "fail",
            "summary": "站点降水方案缺少必要输入文件。",
            "items": [
                {"label": "站点降水文件", "value": "已提供" if station_prec_path is not None and station_prec_path.exists() else "缺失", "status": "ok" if station_prec_path is not None and station_prec_path.exists() else "fail"},
                {"label": "站点信息文件", "value": "已提供" if station_meta_path is not None and station_meta_path.exists() else "缺失", "status": "ok" if station_meta_path is not None and station_meta_path.exists() else "fail"},
            ],
            "warnings": warnings,
            "missing": missing,
            "matched_station_count": 0,
        }

    assert station_prec_path is not None and station_meta_path is not None
    try:
        station_series, station_format, _ = _load_station_precip_table(station_prec_path)
        station_meta, meta_columns = _load_station_metadata_table(station_meta_path)
    except Exception as exc:
        return {
            "enabled": True,
            "mode": mode,
            "status": "fail",
            "summary": f"站点降水资料读取失败：{exc}",
            "items": [{"label": "读取状态", "value": str(exc), "status": "fail"}],
            "warnings": warnings,
            "missing": [f"站点降水资料读取失败：{exc}"],
            "matched_station_count": 0,
        }

    station_series = station_series.loc[station_series.index.notna()].copy()
    station_series = station_series[~station_series.index.duplicated(keep="first")].sort_index()
    precip_ids = [str(col).strip() for col in station_series.columns if str(col).strip()]
    meta_ids = [str(item).strip() for item in station_meta["_station_id"].tolist() if str(item).strip()]
    precip_id_set = set(precip_ids)
    meta_id_set = set(meta_ids)
    matched_ids = sorted(precip_id_set & meta_id_set)
    missing_in_precip = sorted(meta_id_set - precip_id_set)
    missing_in_meta = sorted(precip_id_set - meta_id_set)

    if not matched_ids:
        missing.append("站点信息与站点降水之间没有可匹配的站号。")
    elif missing_in_precip:
        warnings.append(f"{len(missing_in_precip)} 个站点在站点信息中存在，但站点降水表没有对应列。")
    if missing_in_meta:
        warnings.append(f"{len(missing_in_meta)} 个站点降水列没有对应站点信息。")
    if not meta_columns.get("lon") or not meta_columns.get("lat"):
        warnings.append("站点信息未识别到经纬度或坐标字段，执行降水方案时会失败。")

    matched_series = station_series[matched_ids].copy() if matched_ids else pd.DataFrame(index=station_series.index)
    time_basis = task_time_basis(config, context="calibration")
    time_basis_label = TIME_BASIS_LABELS.get(time_basis, "当前任务时段")
    event_info = normalized_flood_events(config, step_hours=step) if time_basis == TIME_BASIS_EVENT_WINDOWS else None
    expected_index = build_expected_forcing_index(config, context="calibration")
    expected_count = 0
    covered_count = 0
    coverage_ratio: float | None = None
    event_coverage: list[dict[str, Any]] = []
    zero_available_steps = 0
    if expected_index is not None and len(expected_index) > 0:
        expected_count = int(len(expected_index))
        if expected_count > 0 and not matched_series.empty:
            present = matched_series.reindex(expected_index)
            covered_count = int(present.notna().any(axis=1).sum())
            coverage_ratio = covered_count / expected_count
            zero_available_steps = int((present.notna().sum(axis=1) == 0).sum())
            if covered_count == 0:
                missing.append(f"站点降水时间范围与{time_basis_label}完全不重叠。")
            elif coverage_ratio < 0.99:
                message = f"站点降水在{time_basis_label}内覆盖不足：覆盖 {coverage_ratio * 100:.1f}%。"
                if mode == "thiessen_station_only":
                    missing.append(message)
                else:
                    warnings.append(message)
    if event_info:
        for event in event_info.get("valid_events", []):
            event_index = _event_date_range(event["run_start"], event["run_end"], step)
            if len(event_index) <= 0 or matched_series.empty:
                covered_event = 0
                zero_event = int(len(event_index))
            else:
                event_present = matched_series.reindex(event_index)
                covered_event = int(event_present.notna().any(axis=1).sum())
                zero_event = int((event_present.notna().sum(axis=1) == 0).sum())
            event_steps = int(len(event_index))
            event_ratio = covered_event / event_steps if event_steps else None
            event_status = "ok" if event_ratio is not None and event_ratio >= 0.99 else "fail" if covered_event == 0 else "warn"
            event_coverage.append(
                {
                    "event_id": event.get("event_id"),
                    "name": event.get("name"),
                    "purpose": event.get("purpose"),
                    "run_start": _format_time_for_check(event.get("run_start"), step),
                    "run_end": _format_time_for_check(event.get("run_end"), step),
                    "expected_steps": event_steps,
                    "covered_steps": covered_event,
                    "coverage_ratio": event_ratio,
                    "zero_available_steps": zero_event,
                    "status": event_status,
                }
            )
        uncovered_events = [item for item in event_coverage if int(item.get("zero_available_steps", 0) or 0) > 0]
        if uncovered_events:
            sample = "、".join(str(item.get("event_id") or item.get("name")) for item in uncovered_events[:3])
            message = f"有 {len(uncovered_events)} 场事件运行窗口内存在无可用站点时间步，例如：{sample}。"
            if mode == "thiessen_station_only":
                if message not in missing:
                    missing.append(message)
            elif message not in warnings:
                warnings.append(message)

    numeric_values = matched_series.to_numpy(dtype="float64") if not matched_series.empty else np.empty((0, 0), dtype="float64")
    negative_count = int(np.sum(numeric_values < 0)) if numeric_values.size else 0
    extreme_threshold = 80.0 if abs(step - 1.0) < 1e-9 else 300.0
    extreme_count = int(np.sum(numeric_values > extreme_threshold)) if numeric_values.size else 0
    all_zero_count = 0
    max_missing_rate = 0.0
    if matched_ids:
        all_zero_count = int(sum(bool(np.nanmax(np.abs(matched_series[col].to_numpy(dtype="float64"))) <= 1e-9) for col in matched_ids if matched_series[col].notna().any()))
        missing_rates = matched_series[matched_ids].isna().mean(axis=0)
        max_missing_rate = float(missing_rates.max()) if not missing_rates.empty else 0.0
    if negative_count > 0:
        warnings.append(f"站点降水存在 {negative_count} 条负值记录。")
    if extreme_count > 0:
        unit_label = "小时" if abs(step - 1.0) < 1e-9 else "日"
        warnings.append(f"站点降水存在 {extreme_count} 条超过 {extreme_threshold:g} mm/{unit_label} 的异常大值。")
    if all_zero_count > 0:
        warnings.append(f"{all_zero_count} 个匹配站点在当前资料中为全零序列。")
    if max_missing_rate > 0.20:
        warnings.append(f"单站最大缺测率为 {max_missing_rate * 100:.1f}%，建议核对资料完整性。")

    if missing:
        status = "fail"
        summary = "站点降水方案仍有关键问题，无法作为率定输入。"
    elif warnings:
        status = "warn"
        summary = "站点降水资料可以继续处理，但存在缺测、异常值或站号匹配风险。"
    else:
        status = "ok"
        summary = "站点降水资料匹配和时间覆盖基本合理，可用于降水订正或泰森分配。"

    station_start = station_series.index.min() if len(station_series.index) else None
    station_end = station_series.index.max() if len(station_series.index) else None
    items.extend(
        [
            {"label": "降水方案", "value": "格点+站点偏差订正" if mode == "grid_plus_station_bias" else "站点泰森分配", "status": "ok"},
            {"label": "资料口径", "value": time_basis_label, "status": "ok"},
            {"label": "站号匹配", "value": f"{len(matched_ids)}/{len(meta_id_set)}", "status": "ok" if matched_ids and not missing_in_precip else "warn" if matched_ids else "fail"},
            {"label": "降水表额外站号", "value": str(len(missing_in_meta)), "status": "ok" if not missing_in_meta else "warn"},
            {"label": "资料格式", "value": station_format, "status": "ok"},
            {"label": "时间范围", "value": f"{_format_time_for_check(station_start, step)} 至 {_format_time_for_check(station_end, step)}", "status": "ok" if coverage_ratio is None or coverage_ratio >= 0.99 else "warn" if covered_count > 0 else "fail"},
            {"label": f"{time_basis_label}覆盖", "value": f"{coverage_ratio * 100:.1f}%" if coverage_ratio is not None else "未配置完整时段", "status": "ok" if coverage_ratio is None or coverage_ratio >= 0.99 else "warn" if covered_count > 0 else "fail"},
            {"label": "无可用站点时间步", "value": str(zero_available_steps), "status": "ok" if zero_available_steps == 0 else "fail" if mode == "thiessen_station_only" else "warn"},
            {"label": "单站最大缺测率", "value": f"{max_missing_rate * 100:.1f}%", "status": "warn" if max_missing_rate > 0.20 else "ok"},
            {"label": "负降水记录", "value": str(negative_count), "status": "ok" if negative_count == 0 else "warn"},
            {"label": "异常大值记录", "value": str(extreme_count), "status": "ok" if extreme_count == 0 else "warn"},
        ]
    )
    for event_item in event_coverage[:5]:
        ratio = event_item.get("coverage_ratio")
        value = f"{float(ratio) * 100:.1f}% / 无站点 {int(event_item.get('zero_available_steps', 0) or 0)} 步" if ratio is not None else "未覆盖"
        items.append(
            {
                "label": f"事件 {event_item.get('event_id')}",
                "value": value,
                "status": str(event_item.get("status", "warn")),
            }
        )
    return {
        "enabled": True,
        "mode": mode,
        "status": status,
        "summary": summary,
        "items": items,
        "warnings": warnings,
        "missing": missing,
        "matched_station_count": len(matched_ids),
        "station_count": len(meta_id_set),
        "precip_station_count": len(precip_id_set),
        "missing_in_precip": missing_in_precip[:20],
        "missing_in_meta": missing_in_meta[:20],
        "expected_time_steps": expected_count,
        "covered_time_steps": covered_count,
        "coverage_ratio": coverage_ratio,
        "zero_available_steps": zero_available_steps,
        "time_basis": time_basis,
        "time_basis_label": time_basis_label,
        "event_coverage": event_coverage,
    }


def check_station_precip_strategy(config: dict[str, Any]) -> tuple[bool, str, int]:
    analysis = analyze_station_precip_inputs(
        config,
        step_hours=normalize_time_step_hours(config.get("时间步长_小时", 24.0)),
    )
    if not analysis.get("enabled"):
        return True, str(analysis.get("summary", "当前为格点基线模式，未启用站点订正。")), 0
    status = str(analysis.get("status", "fail"))
    matched = int(analysis.get("matched_station_count", 0) or 0)
    warnings = list(analysis.get("warnings", []) or [])
    message = str(analysis.get("summary", "站点降水资料已检查。"))
    if matched:
        message += f" 站点匹配：{matched} 个。"
    if warnings:
        message += " " + "；".join(str(item) for item in warnings[:2])
    return status != "fail", message, matched


def check_glacier_mask(config: dict[str, Any]) -> tuple[bool, str, int]:
    glacier_shp = str(config.get("冰川边界_shp", "")).strip()
    if not glacier_shp:
        return True, "未启用（未提供冰川边界 shp）", 0
    paths = build_profile_paths(config, current_profile(config))
    target = Path(paths["gis_dir"]) / "glacier_mask.tif"
    fraction_target = Path(paths["gis_dir"]) / "glacier_fraction.tif"
    summary_path = Path(paths["gis_dir"]) / "glacier_mask_summary.json"
    summary_message = ""
    glacier_mode = ""
    if summary_path.exists():
        try:
            summary = read_json_file(summary_path)
            summary_message = str(summary.get("message", "")).strip()
            glacier_mode = str(summary.get("glacier_mode", "")).strip().lower()
        except Exception:
            summary_message = ""
            glacier_mode = ""
    if target.exists():
        if glacier_mode == "fractional_subgrid":
            message = summary_message or (
                "已生成冰川分数栅格 glacier_fraction.tif，并同步生成兼容用 glacier_mask.tif。"
            )
        elif fraction_target.exists():
            message = summary_message or (
                "已生成 glacier_mask.tif 和 glacier_fraction.tif。"
            )
        else:
            message = summary_message or "冰川掩膜已生成"
        return True, message, 1
    return False, (summary_message or "未生成/可选"), 0


def check_glacier_reference(config: dict[str, Any]) -> tuple[bool, str, int]:
    glacier_shp = str(config.get("冰川边界_shp", "")).strip()
    if not glacier_shp:
        return True, "未启用（未提供冰川边界 shp）", 0
    paths = build_profile_paths(config, current_profile(config))
    count = count_matching(paths["glacier_melt_dir"])
    return count > 0, f"冰川工程先验栅格数：{count}", count


def check_glacier_elev(config: dict[str, Any]) -> tuple[bool, str, int]:
    glacier_shp = str(config.get("冰川边界_shp", "")).strip()
    if not glacier_shp:
        return True, "未启用（未提供冰川边界 shp）", 0
    paths = build_profile_paths(config, current_profile(config))
    summary_path = Path(paths["gis_dir"]) / "glacier_elev_summary.json"
    target = Path(paths["gis_dir"]) / "glacier_elev.tif"
    if summary_path.exists():
        try:
            summary = read_json_file(summary_path)
            status = str(summary.get("status", "unknown")).strip().lower()
            covered = int(summary.get("glacier_pixels_with_elev", 0) or 0)
            missing = int(summary.get("glacier_pixels_without_elev", 0) or 0)
            mean_elev = summary.get("area_weighted_elev_mean") or summary.get("elev_mean")
            if status == "ok" and target.exists():
                extra = f"，面积加权均值 {float(mean_elev):.0f} m" if mean_elev is not None else ""
                return True, f"已生成（冰川像元 {covered} 个有高程，{missing} 个缺失{extra}）", covered
            if status == "not_needed_1km":
                return True, "1km 方案无需此步", 0
            if status == "no_high_res_dem":
                return False, "未找到 1km 高分辨率 DEM，需手动配置 HBV_HIGH_RES_DEM", 0
            if status == "no_intersection":
                return False, "流域内冰川像元未匹配到高分辨率 DEM 有效值", 0
            if status == "no_glacier_shp":
                return True, "无冰川 shp，跳过", 0
            if status == "empty_glacier":
                return True, "冰川 shp 无有效几何，跳过", 0
            return False, f"状态异常：{status}", covered
        except Exception:
            pass
    if target.exists():
        return True, "glacier_elev.tif 已生成（无摘要）", 0
    return False, "未执行", 0


def glacier_elev_required(config: dict[str, Any]) -> bool:
    glacier_shp = str(config.get("冰川边界_shp", "")).strip()
    if not glacier_shp:
        return False
    return infer_dem_kind_from_raster(str(config.get("DEM_tif", "") or "")) != "1km"


def glacier_formal_requirements(config: dict[str, Any], profile: str | None = None) -> dict[str, Any]:
    """返回工作区冰川状态的信息快照。

    注意：旧版本此函数用于判定 formal/diagnostic gate，新版本已取消硬性 gate。
    保留函数名仅为兼容调用方；返回字段 `formal_preconditions_ready` 始终 True，
    `blocking_reasons` 始终为空列表；`diagnostic_notes` 用于界面信息提示。
    """
    profile_name = str(profile or current_profile(config)).strip().lower() or current_profile(config)
    glacier_shp = str(config.get("冰川边界_shp", "")).strip()
    result: dict[str, Any] = {
        "enabled": bool(glacier_shp),
        "objective_mode": profile_runner.resolve_objective_mode(config, None, profile_name),
        "objective_is_multi": False,
        "objective_is_event": False,
        "reference_count": 0,
        "reference_ready": False,
        "dem_kind": "",
        "glacier_elev_required": False,
        "glacier_elev_ready": True,
        "glacier_elev_message": "未启用",
        "formal_preconditions_ready": True,
        "blocking_reasons": [],
        "diagnostic_notes": [],
    }
    result["objective_is_multi"] = result["objective_mode"] == profile_runner.OBJECTIVE_MODE_MULTI
    result["objective_is_event"] = result["objective_mode"] == getattr(profile_runner, "OBJECTIVE_MODE_FLOOD_EVENT", "")
    if not result["enabled"]:
        return result

    paths = build_profile_paths(config, profile_name)
    result["reference_count"] = count_matching(paths["glacier_melt_dir"])
    result["reference_ready"] = result["reference_count"] > 0
    dem_path = _workspace_dem_path(paths["gis_dir"], prefer=_configured_dem_kind(config))
    if dem_path.exists():
        try:
            result["dem_kind"] = infer_dem_kind_from_raster(str(dem_path))
        except Exception:
            result["dem_kind"] = _configured_dem_kind(config)
    else:
        result["dem_kind"] = _configured_dem_kind(config)
    result["glacier_elev_required"] = glacier_elev_required(config)
    if result["glacier_elev_required"]:
        elev_ready, elev_message, _ = check_glacier_elev(config)
        result["glacier_elev_ready"] = bool(elev_ready)
        result["glacier_elev_message"] = str(elev_message or "未生成")
    else:
        result["glacier_elev_ready"] = True
        result["glacier_elev_message"] = "1km 无需此步"

    notes: list[str] = []
    if result["glacier_elev_required"] and not result["glacier_elev_ready"]:
        notes.append(
            f"0.1° 工作区尚未生成 glacier_elev.tif：{result['glacier_elev_message']}；"
            "冰川子格温度递减将降级运行，冰川融水趋势可能偏高。"
        )
    if result["objective_is_event"]:
        notes.append("当前工作区启用事件洪水率定目标函数，应重点复核事件表、洪峰、峰现时间、洪量和退水过程。")
    elif not result["objective_is_multi"]:
        notes.append(
            "当前结果使用简化径流评价口径；启用冰川模块时，建议采用统一日尺度综合水文评价口径，并重点复核径流过程、冰川面积占比与冰雪融水分量。"
        )
    result["diagnostic_notes"] = notes
    return result


def check_daily_inputs_ready(config: dict[str, Any], precip_source: Any = None) -> tuple[bool, str, int]:
    paths = build_profile_paths(config, PROFILE_DAILY)
    required = [
        _workspace_dem_path(paths["gis_dir"], prefer=_configured_dem_kind(config)),
        Path(paths["gis_dir"]) / "flow_accumulation_masked.tif",
    ]
    basin_path = _resolve_config_related_path(config, config.get("流域边界_shp"))
    obs_path = _resolve_config_related_path(config, config.get(OBSERVED_FLOW_KEY))
    if basin_path is not None:
        required.append(basin_path)
    if obs_path is not None:
        required.append(obs_path)
    base_ready = all(item.exists() for item in required)
    if basin_path is None or obs_path is None:
        base_ready = False
    forcing = validate_forcing_bundle(config, PROFILE_DAILY, precip_source=precip_source)
    message = f"基础输入{'齐全' if base_ready else '缺失'}；气象驱动有效时间步数：{forcing['total_valid_steps']}"
    if forcing["errors"]:
        message += f"；问题：{'；'.join(forcing['errors'][:2])}"
    return base_ready and forcing["ok"], message, forcing["total_valid_steps"] + int(base_ready)


def check_hourly_temp_evap(config: dict[str, Any]) -> tuple[bool, str, int]:
    paths = build_workspace_paths(config)
    profile_paths = build_profile_paths(config, PROFILE_HOURLY)
    return _prefer_raw_or_aligned_group_status(
        [
            ("小时尺度 ERA5 温度中间结果", Path(paths["raw_temp_hourly_dir"])),
            ("小时尺度潜在蒸散发中间结果", Path(paths["raw_evap_hourly_dir"])),
        ],
        [
            ("工程气温输入", Path(profile_paths["aligned_temp_dir"])),
            ("工程潜在蒸散发输入", Path(profile_paths["aligned_evap_dir"])),
        ],
        1.0,
    )


def check_hourly_era5_download(config: dict[str, Any]) -> tuple[bool, str, int]:
    paths = build_workspace_paths(config)
    patterns = [
        paths["raw_temp_dir"].glob("era5_t2m_hourly_*.nc"),
        paths["raw_solar_dir"].glob("era5_ssrd_hourly_*.nc"),
        paths["raw_wind_dir"].glob("era5_u10_hourly_*.nc"),
        paths["raw_wind_dir"].glob("era5_v10_hourly_*.nc"),
        paths["raw_dewpoint_dir"].glob("era5_d2m_hourly_*.nc"),
    ]
    if configured_precip_source(config) == "era5":
        patterns.append(paths["raw_prec_era5_dir"].glob("era5_tp_hourly_*.nc"))
    count = sum(len(list(items)) for items in patterns)
    return count > 0, f"小时 ERA5 原始 NetCDF 文件数：{count}", count


def check_hourly_prec(config: dict[str, Any], precip_source: Any = None) -> tuple[bool, str, int]:
    paths = build_workspace_paths(config)
    profile_paths = build_profile_paths(config, PROFILE_HOURLY)
    source_key = resolve_precip_source(config, precip_source)
    if source_key == "custom_tif":
        aligned = Path(profile_paths["aligned_prec_custom_base_dir"])
        if count_matching(aligned) > 0:
            return True, "当前为本地栅格降水模式，小时降水已导入工程独立降水目录。", count_matching(aligned)
        return True, "当前为本地栅格降水模式，不需要执行原始小时降水标准化。", 0
    source = effective_precip_source(source_key)
    if source == "era5":
        target = paths["raw_prec_era5_hourly_dir"]
        aligned = profile_paths["aligned_prec_era5_base_dir"]
    elif source == "cmfd":
        target = paths["raw_prec_cmfd_hourly_dir"]
        aligned = profile_paths["aligned_prec_cmfd_base_dir"]
    else:
        target = paths["raw_prec_hourly_dir"]
        aligned = profile_paths["aligned_prec_base_dir"]
    return _prefer_raw_or_aligned_group_status(
        [("小时尺度降水中间结果", Path(target))],
        [("工程降水输入", Path(aligned))],
        1.0,
    )


def check_hourly_aligned(config: dict[str, Any], precip_source: Any = None) -> tuple[bool, str, int]:
    paths = build_profile_paths(config, PROFILE_HOURLY)
    precip_dir, _, _ = effective_precip_paths(config, PROFILE_HOURLY, precip_source=precip_source)
    step_hours = normalize_time_step_hours(config.get("时间步长_小时", 24.0))
    scans = [
        validate_tif_time_series("降水", precip_dir, step_hours),
        validate_tif_time_series("气温", Path(paths["aligned_temp_dir"]), step_hours),
        validate_tif_time_series("蒸散发", Path(paths["aligned_evap_dir"]), step_hours),
    ]
    count = sum(int(item["valid_time_steps"]) for item in scans)
    ready = all(item["ok"] for item in scans)
    message = "；".join(item["errors"][0] for item in scans if item["errors"]) or f"小时尺度气象驱动有效时间步：{count}"
    return ready, message, count


def check_hourly_inputs_ready(config: dict[str, Any], precip_source: Any = None) -> tuple[bool, str, int]:
    paths = build_profile_paths(config, PROFILE_HOURLY)
    required = [
        _workspace_dem_path(paths["gis_dir"], prefer=_configured_dem_kind(config)),
        Path(paths["gis_dir"]) / "flow_accumulation_masked.tif",
    ]
    basin_path = _resolve_config_related_path(config, config.get("流域边界_shp"))
    obs_path = _resolve_config_related_path(config, config.get(OBSERVED_FLOW_KEY))
    if basin_path is not None:
        required.append(basin_path)
    if obs_path is not None:
        required.append(obs_path)
    base_ready = all(item.exists() for item in required)
    if basin_path is None or obs_path is None:
        base_ready = False
    forcing = validate_forcing_bundle(config, PROFILE_HOURLY, precip_source=precip_source)
    message = f"基础输入{'齐全' if base_ready else '缺失'}；小时气象驱动有效时间步数：{forcing['total_valid_steps']}"
    if forcing["errors"]:
        message += f"；问题：{'；'.join(forcing['errors'][:2])}"
    return base_ready and forcing["ok"], message, forcing["total_valid_steps"] + int(base_ready)


def data_prep_steps(profile: str) -> list[dict[str, Any]]:
    common = [
        {
            "id": "clip_dem",
            "title": "1. 裁剪 DEM",
            "description": "根据流域边界 shp 把内置或外部 DEM 裁剪到当前运行目录。",
            "script": DATA_PREP_DIR / "01_裁剪DEM.py",
            "depends_on": [],
            "check": check_clip_dem,
        },
        {
            "id": "flow_acc",
            "title": "2. 生成流向与流量累积",
            "description": "为当前 DEM 生成流向与流量累积栅格。",
            "script": DATA_PREP_DIR / "02_生成流向流量累积.py",
            "depends_on": ["clip_dem"],
            "check": check_flow_acc,
        },
        {
            "id": "masked_flow",
            "title": "3. 生成汇流与流域掩膜",
            "description": "生成流域范围内的流量累积栅格与汇流掩膜。",
            "script": DATA_PREP_DIR / "12_生成汇流与流域掩膜.py",
            "depends_on": ["flow_acc"],
            "check": check_masked_flow,
        },
        {
            "id": "elevation_zone",
            "title": "4. 生成高程分区",
            "description": "基于 DEM 和阈值生成低/高高程区栅格。",
            "script": DATA_PREP_DIR / "03_生成高程分区.py",
            "depends_on": ["clip_dem"],
            "check": check_elevation_zone,
        },
    ]
    if profile == PROFILE_DAILY:
        common.extend(
            [
                {
                    "id": "download_era5",
                    "title": "5. 下载 ERA5 变量",
                    "description": "按当前配置下载 ERA5 降水、气温或 FAO56 所需变量；MSWEP/CMFD 不在此步自动下载。",
                    "script": DATA_PREP_DIR / "05_下载ERA5和FAO56变量.py",
                    "depends_on": [],
                    "check": check_daily_era5_download,
                },
                {
                    "id": "process_era5",
                    "title": "6. 生成日尺度结果",
                    "description": "按当前配置生成日尺度气温或潜在蒸散发。",
                    "script": DATA_PREP_DIR / "06_处理ERA5温度和蒸散发.py",
                    "depends_on": ["download_era5"],
                    "check": check_daily_era5_processed,
                    "supports_overwrite": True,
                },
                {
                    "id": "process_prec",
                    "title": "7. 处理日尺度降水",
                    "description": "处理 ERA5 自动下载降水，或处理已放入原始目录的 MSWEP/CMFD 降水数据。",
                    "script": DATA_PREP_DIR / "07_处理降水数据.py",
                    "depends_on": [],
                    "check": check_daily_prec,
                    "needs_prec_source": True,
                    "supports_overwrite": True,
                },
                {
                    "id": "station_precip_strategy",
                    "title": "8. 站点降水资料分析（按方案）",
                    "description": "当降水方案不是“格点直接使用”时，检查站点匹配、时间覆盖、缺测和异常值。",
                    "depends_on": ["process_prec"],
                    "check": check_station_precip_strategy,
                    "manual": True,
                },
                {
                    "id": "align_inputs",
                    "title": "9. 对齐并裁剪日尺度气象",
                    "description": "将降水、温度、蒸散统一到 DEM 网格并裁剪到流域内。",
                    "script": DATA_PREP_DIR / "08_对齐并裁剪气象数据.py",
                    "depends_on": ["clip_dem", "process_era5", "process_prec", "station_precip_strategy"],
                    "check": check_daily_aligned,
                    "needs_prec_source": True,
                    "supports_overwrite": True,
                },
                {
                    "id": "apply_precip_strategy",
                    "title": "10. 执行降水方案（格点 / 订正 / 泰森）",
                    "description": "根据气象策略生成最终用于率定的降水栅格目录。",
                    "script": GUI_ROOT / "precipitation_strategy_runner.py",
                    "depends_on": ["align_inputs", "station_precip_strategy"],
                    "check": check_precip_strategy_outputs,
                    "needs_prec_source": True,
                },
                {
                    "id": "glacier_mask",
                    "title": "11. 生成冰川掩膜（可选）",
                    "description": "如配置了冰川边界 shp，则按 DEM 分辨率生成冰川表达结果：1km 生成二值掩膜，0.1° 生成分数栅格并附带兼容掩膜。",
                    "script": DATA_PREP_DIR / "09_生成冰川掩膜.py",
                    "depends_on": ["clip_dem"],
                    "check": check_glacier_mask,
                    "optional": True,
                },
                {
                    "id": "glacier_elev",
                    "title": "11.5 生成冰川高程栅格（0.1° 专用，可选）",
                    "description": "从高分辨率 1km DEM 提取每个 0.1° 像元内冰川区的面积加权平均高程，用于率定时的冰川子格温度递减修正。1km 方案无需此步；0.1° 方案未做此步将在率定结果标记 reliability_flag=degraded。",
                    "script": DATA_PREP_DIR / "11_生成冰川高程栅格.py",
                    "depends_on": ["glacier_mask"],
                    "check": check_glacier_elev,
                    "optional": True,
                },
                {
                    "id": "glacier_melt",
                    "title": "12. 生成冰川工程先验序列（可选）",
                    "description": "生成冰川参考栅格序列，用于与模拟冰融水过程进行对照复核。",
                    "script": DATA_PREP_DIR / "10_生成冰川融水.py",
                    "depends_on": ["glacier_mask"],
                    "check": check_glacier_reference,
                    "optional": True,
                },
                {
                    "id": "check_inputs",
                    "title": "13. 输入完整性检查",
                    "description": "检查当前日尺度输入是否齐全，可用于率定前复核。",
                    "script": DATA_PREP_DIR / "13_输入完整性检查.py",
                    "depends_on": ["apply_precip_strategy"],
                    "check": check_daily_inputs_ready,
                    "needs_prec_source": True,
                },
            ]
        )
        return common

    common.extend(
        [
                {
                    "id": "download_hourly_era5",
                    "title": "5. 下载小时 ERA5 变量",
                    "description": "下载小时 ERA5 降水、温度与 FAO 变量（太阳辐射、风速、露点）。",
                "depends_on": [],
                "check": check_hourly_era5_download,
                "script": DATA_PREP_DIR / "05b_下载ERA5小时变量.py",
            },
            {
                "id": "process_hourly_era5",
                "title": "6. 处理小时温度与蒸散",
                "description": "生成小时温度栅格，并把 ERA5 驱动的日 ET0 分配到小时尺度。",
                "depends_on": ["download_hourly_era5"],
                "check": check_hourly_temp_evap,
                "script": DATA_PREP_DIR / "06b_处理ERA5小时温度和蒸散发.py",
                "supports_overwrite": True,
            },
            {
                "id": "process_hourly_prec",
                "title": "7. 处理小时降水",
                "description": "处理 ERA5 小时降水，或把本地小时降水栅格标准化到工程原始降水目录。",
                "depends_on": [],
                "check": check_hourly_prec,
                "needs_prec_source": True,
                "script": DATA_PREP_DIR / "07b_处理小时降水数据.py",
                "supports_overwrite": True,
            },
            {
                "id": "station_precip_strategy",
                "title": "8. 小时尺度站点降水资料分析（按方案）",
                "description": "当降水方案不是“格点直接使用”时，检查小时项目的站点匹配、时间覆盖、缺测和异常值。",
                "depends_on": ["process_hourly_prec"],
                "check": check_station_precip_strategy,
                "manual": True,
            },
            {
                "id": "align_hourly_inputs",
                "title": "9. 对齐并裁剪小时气象",
                "description": "将小时降水、温度、蒸散对齐到 DEM 网格并裁剪到流域内。",
                "depends_on": ["clip_dem", "process_hourly_era5", "process_hourly_prec"],
                "check": check_hourly_aligned,
                "needs_prec_source": True,
                "script": DATA_PREP_DIR / "08b_对齐并裁剪小时气象数据.py",
                "supports_overwrite": True,
            },
            {
                "id": "apply_precip_strategy",
                "title": "10. 执行小时降水方案（格点 / 订正 / 泰森）",
                "description": "根据气象策略生成最终用于小时率定的降水栅格目录。",
                "depends_on": ["align_hourly_inputs", "station_precip_strategy"],
                "check": check_precip_strategy_outputs,
                "needs_prec_source": True,
                "script": GUI_ROOT / "precipitation_strategy_runner.py",
            },
            {
                "id": "glacier_mask",
                "title": "11. 生成冰川掩膜（可选）",
                "description": "如配置了冰川边界 shp，则按 DEM 分辨率生成冰川表达结果：1km 生成二值掩膜，0.1° 生成分数栅格并附带兼容掩膜。",
                "script": DATA_PREP_DIR / "09_生成冰川掩膜.py",
                "depends_on": ["clip_dem"],
                "check": check_glacier_mask,
                "optional": True,
            },
            {
                "id": "glacier_elev",
                "title": "11.5 生成冰川高程栅格（0.1° 专用，可选）",
                "description": "从高分辨率 1km DEM 提取每个 0.1° 像元内冰川区的面积加权平均高程，用于率定时的冰川子格温度递减修正。1km 方案无需此步；0.1° 方案未做此步将在率定结果标记 reliability_flag=degraded。",
                "script": DATA_PREP_DIR / "11_生成冰川高程栅格.py",
                "depends_on": ["glacier_mask"],
                "check": check_glacier_elev,
                "optional": True,
            },
            {
                "id": "stage_hourly_glacier_reference",
                "title": "12. 导入小时尺度冰川工程先验（可选）",
                "description": "将小时尺度冰川参考栅格放入工程目录，用于与模拟冰融水过程进行对照复核。",
                "depends_on": ["glacier_mask"],
                "check": check_glacier_reference,
                "optional": True,
                "manual": True,
            },
            {
                "id": "check_inputs",
                "title": "13. 小时输入完整性检查",
                "description": "检查小时尺度气象驱动与基础 GIS 是否齐全。",
                "depends_on": ["apply_precip_strategy"],
                "check": check_hourly_inputs_ready,
                "script": DATA_PREP_DIR / "13b_小时输入完整性检查.py",
                "needs_prec_source": True,
            },
        ]
    )
    return common


def resolve_data_prep_step(step: dict[str, Any], config: dict[str, Any] | None = None) -> dict[str, Any]:
    resolved = dict(step)
    if config is None:
        return resolved

    glacier_enabled = bool(str(config.get("冰川边界_shp", "")).strip())
    if resolved.get("id") == "glacier_mask" and glacier_enabled:
        resolved["title"] = str(resolved.get("title", "")).replace("（可选）", "")
        resolved["description"] = (
            "当前工作区已配置冰川边界 shp，此步为必做。"
            "按 DEM 分辨率生成冰川表达结果：1km 生成二值掩膜，0.1° 生成分数栅格并附带兼容掩膜。"
        )
        resolved["optional"] = False
    elif resolved.get("id") == "glacier_elev" and glacier_elev_required(config):
        resolved["title"] = str(resolved.get("title", "")).replace("（0.1° 专用，可选）", "（0.1° 专用）")
        resolved["description"] = (
            "从高分辨率 1km DEM 提取每个 0.1° 像元内冰川区的面积加权平均高程，"
            "用于率定时的冰川子格温度递减修正。当前工作区为 0.1° 且已启用冰川，此步为必做；"
            "未做此步将在率定结果标记 reliability_flag=degraded。"
        )
        resolved["optional"] = False
    return resolved


def build_engineering_focus_checks(
    config: dict[str, Any],
    *,
    profile: str,
    object_type: str,
    step_hours: float,
    obs_info: dict[str, Any] | None = None,
    boundary_info: dict[str, Any] | None = None,
    forcing: dict[str, Any] | None = None,
    station_precip_info: dict[str, Any] | None = None,
    boundary_csv: str = "",
) -> list[dict[str, Any]]:
    checks: list[dict[str, Any]] = []

    if profile == PROFILE_DAILY:
        observed_profile = (
            obs_info.get("effective_calibration_mode")
            or obs_info.get("suggested_calibration_mode")
            if obs_info else None
        )
        resampled_to_daily = bool(obs_info.get("resampled_to_daily")) if obs_info else False
        forcing_ok = bool(forcing.get("ok")) if forcing is not None else None
        expected_steps = int(forcing.get("expected_steps") or 0) if forcing is not None and forcing.get("expected_steps") is not None else None
        time_basis_label = str(forcing.get("time_basis_label", "连续时段") if forcing else "连续时段")
        if step_hours != 24.0:
            status = "fail"
            summary = "当前设置为日尺度，但项目时间步长不是 24 小时。"
        elif observed_profile and observed_profile != PROFILE_DAILY:
            status = "fail"
            summary = "观测径流识别为小时尺度，和当前日尺度项目不一致。"
        elif resampled_to_daily:
            status = "ok"
            summary = "观测径流原始时步为小时尺度，已按自然日聚合为日平均流量后用于日尺度项目。"
        elif forcing is not None and not forcing_ok:
            status = "warn"
            summary = f"日尺度主流程已选定，但气象驱动在{time_basis_label}内的覆盖或文件命名仍有问题。"
        else:
            status = "ok"
            summary = f"日尺度主流程基本合理，重点继续检查{time_basis_label}和气象驱动完整性。"
        items = [
            {"label": "项目时间步长", "value": f"{int(step_hours)} 小时", "status": "ok" if step_hours == 24.0 else "fail"},
            {
                "label": "观测径流识别模式",
                "value": PROFILE_LABELS.get(observed_profile, "尚未识别") if observed_profile else "尚未识别",
                "status": "ok" if observed_profile in {None, PROFILE_DAILY} else "fail",
            },
        ]
        if resampled_to_daily:
            aggregation = dict(obs_info.get("daily_aggregation") or {})
            items.append(
                {
                    "label": "小时观测转日尺度",
                    "value": (
                        f"已聚合（日均；至少 {aggregation.get('min_hours_per_day', DEFAULT_MIN_DAILY_HOURS)} 小时/天）"
                    ),
                    "status": "ok",
                }
            )
        if expected_steps is not None:
            items.append(
                {
                    "label": "期望时间步数",
                    "value": str(expected_steps),
                    "status": "ok" if forcing_ok is not False else "warn",
                }
            )
        if forcing is not None:
            items.append(
                {
                    "label": "气象驱动状态",
                    "value": f"已覆盖{time_basis_label}" if forcing_ok else "仍有覆盖或命名问题",
                    "status": "ok" if forcing_ok else "warn",
                }
            )
            items.append({"label": "资料口径", "value": time_basis_label, "status": "ok"})
            event_windows = dict(forcing.get("event_windows") or {})
            if event_windows:
                items.append(
                    {
                        "label": "洪水事件",
                        "value": f"{int(event_windows.get('valid_event_count', 0) or 0)}/{int(event_windows.get('event_count', 0) or 0)} 场有效",
                        "status": "ok" if int(event_windows.get("valid_event_count", 0) or 0) > 0 else "fail",
                    }
                )
        checks.append(
            {
                "id": "daily_profile",
                "title": "日尺度专项检查",
                "summary": summary,
                "status": status,
                "target_step": 2 if any(item["status"] == "fail" for item in items[:2]) else 6,
                "items": items,
            }
        )

    if object_type == OBJECT_INTERBASIN or boundary_csv:
        if object_type != OBJECT_INTERBASIN and boundary_csv:
            checks.append(
                {
                    "id": "boundary_inflow",
                    "title": "上游边界入流专项检查",
                    "summary": "当前项目不是区间流域，但配置了上游边界入流，请确认对象类型是否正确。",
                    "status": "warn",
                    "target_step": 3,
                    "items": [
                        {"label": "项目对象", "value": OBJECT_LABELS.get(object_type, object_type), "status": "warn"},
                        {"label": "边界入流文件", "value": "已配置" if boundary_csv else "未配置", "status": "warn" if boundary_csv else "ok"},
                    ],
                }
            )
        elif not boundary_csv:
            checks.append(
                {
                    "id": "boundary_inflow",
                    "title": "上游边界入流专项检查",
                    "summary": "区间流域必须提供上游边界入流 CSV。",
                    "status": "fail",
                    "target_step": 3,
                    "items": [
                        {"label": "边界入流文件", "value": "缺失", "status": "fail"},
                    ],
                }
            )
        elif boundary_info is not None:
            coverage_ratio = boundary_info.get("coverage_ratio")
            duplicate_count = int(boundary_info.get("duplicate_count", 0) or 0)
            negative_count = int(boundary_info.get("negative_count", 0) or 0)
            out_of_range_count = len(boundary_info.get("out_of_range_steps", []) or [])
            zero_ratio = int(boundary_info.get("zero_count", 0) or 0) / max(1, int(boundary_info.get("valid_rows", 0) or 0))
            detected_step = normalize_time_step_hours(boundary_info.get("time_step_hours"))
            step_match = detected_step == step_hours if boundary_info.get("time_step_hours") is not None else None
            if duplicate_count > 0 or negative_count > 0 or step_match is False or (coverage_ratio is not None and coverage_ratio < 0.99):
                status = "fail"
                summary = "边界入流仍有关键问题，正式率定前需要先修正时间步长、覆盖率或异常值。"
            elif zero_ratio >= 0.8 or int(boundary_info.get("invalid_rows", 0) or 0) > 0 or out_of_range_count > 0:
                status = "warn"
                summary = "边界入流可以继续核查，但仍有高零值比例或范围外记录等风险。"
            else:
                status = "ok"
                summary = "边界入流时间步和覆盖范围基本合理，可进入后续调试或率定。"
            checks.append(
                {
                    "id": "boundary_inflow",
                    "title": "上游边界入流专项检查",
                    "summary": summary,
                    "status": status,
                    "target_step": 3,
                    "items": [
                        {"label": "识别时间步长", "value": f"{int(detected_step)} 小时" if detected_step is not None else "未识别", "status": "ok" if step_match in {True, None} else "fail"},
                        {
                            "label": "覆盖率",
                            "value": (f"{coverage_ratio * 100:.1f}%" if coverage_ratio is not None else "未与当前时段对比"),
                            "status": "ok" if coverage_ratio is None or coverage_ratio >= 0.99 else "fail",
                        },
                        {
                            "label": "重复时间戳",
                            "value": str(duplicate_count),
                            "status": "ok" if duplicate_count == 0 else "fail",
                        },
                        {
                            "label": "负流量记录",
                            "value": str(negative_count),
                            "status": "ok" if negative_count == 0 else "fail",
                        },
                        {
                            "label": "零值比例",
                            "value": f"{zero_ratio * 100:.1f}%",
                            "status": "warn" if zero_ratio >= 0.8 else "ok",
                        },
                    ],
                }
            )
    if station_precip_info and station_precip_info.get("enabled"):
        event_coverage = list(station_precip_info.get("event_coverage", []) or [])
        event_ok_count = sum(1 for item in event_coverage if str(item.get("status", "") or "") == "ok")
        checks.append(
            {
                "id": "station_precip",
                "title": "站点降水专项检查",
                "summary": str(station_precip_info.get("summary", "")),
                "status": str(station_precip_info.get("status", "warn") or "warn"),
                "target_step": 4,
                "items": list(station_precip_info.get("items", []) or []),
                "event_coverage": event_coverage,
                "event_coverage_summary": {
                    "enabled": bool(event_coverage),
                    "ok_count": int(event_ok_count),
                    "event_count": int(len(event_coverage)),
                },
            }
        )
    return checks


def validate_workspace_fields(
    config_path_raw: str,
    stage: str = "calibration",
    precip_source: Any = None,
    config_override: dict[str, Any] | None = None,
) -> dict[str, Any]:
    missing: list[str] = []
    warnings: list[str] = []
    try:
        cfg_path = resolve_any_path(config_path_raw, must_exist=True)
        config = copy.deepcopy(config_override) if config_override is not None else read_runtime_config(cfg_path)
    except Exception as exc:
        return {"valid": False, "missing": [f"配置文件无法读取：{exc}"], "warnings": []}

    active_meteo_import = find_running_task("meteo_import", str(cfg_path))
    if active_meteo_import is not None:
        progress = dict(active_meteo_import.metadata.get("ui_progress") or {})
        stage_label = str(progress.get("stage", "气象栅格导入任务")).strip() or "气象栅格导入任务"
        warnings.append(f"{stage_label}仍在进行，检查结果会随导入进度变化。")
        if stage in {"calibration", "forward"}:
            missing.append("气象栅格导入任务仍在运行，请等待完成后再进行输入检查或启动率定。")
            return {
                "valid": False,
                "missing": missing,
                "warnings": warnings,
                "profile": current_profile(config),
                "object_type": detect_object_type(config),
                "stage": stage,
            }

    profile = current_profile(config)
    object_type = detect_object_type(config)
    paths = build_profile_paths(config, profile)
    step_hours = normalize_time_step_hours(config.get("时间步长_小时", 24.0))
    time_basis = task_time_basis(config, context="calibration")
    event_window_info = normalized_flood_events(config, step_hours=step_hours) if time_basis == TIME_BASIS_EVENT_WINDOWS else None
    runtime_stage = str(stage or "calibration").strip().lower() or "calibration"
    require_observed_flow = runtime_stage != "quick_test"
    obs_info: dict[str, Any] | None = None
    boundary_info: dict[str, Any] | None = None
    forcing: dict[str, Any] | None = None
    station_precip_info: dict[str, Any] | None = None
    for repair_key, label in (("流域边界_shp", "流域边界"), ("冰川边界_shp", "冰川边界"), (OBSERVED_FLOW_KEY, "观测径流")):
        repair_info = dict(config.get("_path_repairs", {})).get(repair_key)
        if isinstance(repair_info, dict) and repair_info.get("recovered_from"):
            warnings.append(
                f"{label}已自动恢复到当前工作区：{repair_info.get('resolved_path', '')}（来源 {repair_info.get('recovered_from', '')}）"
            )
    if not config.get("运行目录"):
        missing.append("运行目录")
    basin_path_raw = str(config.get("流域边界_shp", "")).strip()
    basin_path = _resolve_config_related_path(config, basin_path_raw)
    runtime_gis_ready = all(
        file_path.exists()
        for file_path in (
            _workspace_dem_path(paths["gis_dir"], prefer=_configured_dem_kind(config)),
            Path(paths["gis_dir"]) / "flow_accumulation_masked.tif",
        )
    )
    if runtime_stage == "calibration":
        if not basin_path_raw:
            if runtime_gis_ready:
                warnings.append("原始流域边界 shp 未配置，但当前工作区已具备运行时 GIS 数据，可继续率定。")
            else:
                missing.append("流域边界_shp")
        elif basin_path is None or not basin_path.exists():
            if runtime_gis_ready:
                warnings.append(f"原始流域边界文件不存在：{basin_path_raw}；当前工作区已具备运行时 GIS 数据，可继续率定。")
            else:
                missing.append(f"流域边界文件不存在：{basin_path_raw}")
    obs_path = _config_text_value(config, OBSERVED_FLOW_KEY)
    obs_file = _resolve_config_related_path(config, obs_path)
    if require_observed_flow:
        if not obs_path:
            _append_unique_message(missing, OBSERVED_FLOW_KEY)
        elif obs_file is None or not obs_file.exists():
            _append_unique_message(missing, f"观测径流文件不存在：{obs_path}")
    elif not obs_path:
                warnings.append("输入预核算未配置观测径流文件；本次只检查运行资料可用性，不计算观测指标。")
    elif obs_file is None or not obs_file.exists():
                warnings.append(f"输入预核算未找到观测径流文件：{obs_path}；本次只检查运行资料可用性，不计算观测指标。")
    if profile == PROFILE_DAILY and step_hours != 24.0:
        missing.append("率定模式=日尺度 但 时间步长_小时 不是 24")
    if profile == PROFILE_HOURLY and step_hours != 1.0:
        missing.append("率定模式=小时尺度 但 时间步长_小时 不是 1")

    time_cfg = config.get("时间", {})
    if time_basis == TIME_BASIS_EVENT_WINDOWS:
        warnings.append("当前工作区采用洪水事件窗口资料口径，输入检查按事件运行窗口和评分窗口核验。")
    else:
        for key in ("预热开始", "率定开始", "率定结束", "验证结束"):
            if not time_cfg.get(key):
                missing.append(f"时间.{key}")
        time_values: dict[str, pd.Timestamp] = {}
        for key in ("预热开始", "预热结束", "率定开始", "率定结束", "验证开始", "验证结束"):
            value = time_cfg.get(key)
            if not value:
                continue
            try:
                time_values[key] = pd.to_datetime(value)
            except Exception:
                missing.append(f"时间.{key} 无法解析：{value}")
        missing.extend(time_sequence_messages(time_values, step_hours))
    if event_window_info is not None:
        for item in list(event_window_info.get("errors", []) or []):
            missing.append(str(item))
        for item in list(event_window_info.get("warnings", []) or []):
            warnings.append(str(item))
        if not event_window_info.get("valid_event_count"):
            missing.append("事件资料模式已启用，但没有可用的洪水事件窗口。")
        else:
            counts = dict(event_window_info.get("purpose_counts", {}) or {})
            warnings.append(
                "当前按洪水事件窗口检查资料："
                f"{int(event_window_info.get('valid_event_count', 0) or 0)} 场有效，"
                f"率定 {int(counts.get('calibration', 0) or 0)}、"
                f"验证 {int(counts.get('validation', 0) or 0)}、"
                f"诊断 {int(counts.get('diagnostic', 0) or 0)}。"
            )

    init_state = dict(config.get("初始状态", {}) or {})
    for key, default_value in profile_runner.DEFAULT_INIT_STATE.items():
        raw_value = init_state.get(key, default_value)
        try:
            value = float(raw_value)
        except Exception:
            missing.append(f"初始状态.{key} 不是有效数字：{raw_value}")
            continue
        if value < 0:
            missing.append(f"初始状态.{key} 不能为负值：{raw_value}")

    bbox = config.get("范围_bbox", {})
    if not all(bbox.get(dim) is not None for dim in ("北", "西", "南", "东")):
        warnings.append("范围_bbox 未完整填写，保存时可由 shp 自动生成。")

    if obs_path and obs_file is not None and obs_file.exists():
        try:
            obs_info = inspect_observed_csv(
                str(obs_file),
                expected_index=build_expected_observation_index(config, context="calibration"),
                target_step_hours=step_hours,
            )
            obs_missing, obs_warnings = observed_window_messages(config, obs_info)
            if require_observed_flow:
                missing.extend(obs_missing)
            else:
                warnings.extend(obs_missing)
            warnings.extend(obs_warnings)
            duplicate_count = int(obs_info.get("duplicate_count", 0) or 0)
            if duplicate_count > 0:
                sample = "、".join(
                    format_timestamp_for_display(item, step_hours)
                    for item in list(obs_info.get("duplicate_timestamps", []))[:3]
                )
                warnings.append(
                    f"观测径流存在 {duplicate_count} 个重复时间戳，运行时会按同一时刻求平均，例如：{sample or '请检查原始 CSV'}"
                )
        except Exception as exc:
            missing.append(f"观测径流检查失败：{exc}")

    boundary_cfg = dict(config.get("边界条件", {}))
    boundary_csv = str(boundary_cfg.get("上游边界入流_csv", "")).strip()
    boundary_file = _resolve_config_related_path(config, boundary_csv)
    boundary_date_field = str(boundary_cfg.get("时间字段", "date")).strip() or "date"
    boundary_flow_field = str(boundary_cfg.get("流量字段", "inflow_m3s")).strip() or "inflow_m3s"
    if runtime_stage in {"calibration", "forward"} and object_type == OBJECT_INTERBASIN:
        if not boundary_csv:
            missing.append("项目对象=区间流域时必须提供 上游边界入流_csv。")
        elif boundary_file is None or not boundary_file.exists():
            missing.append(f"上游边界入流文件不存在：{boundary_csv}")
        else:
            try:
                boundary_info = inspect_boundary_inflow_csv(
                    str(boundary_file),
                    date_field=boundary_date_field,
                    flow_field=boundary_flow_field,
                    expected_index=build_expected_forcing_index(config, context="calibration"),
                    expected_step_hours=step_hours,
                )
                boundary_missing, boundary_warnings = boundary_info_messages(
                    boundary_info,
                    step_hours,
                    gap_fill=str(boundary_cfg.get("缺失填补", "zero")),
                )
                missing.extend(boundary_missing)
                warnings.extend(boundary_warnings)
            except Exception as exc:
                missing.append(f"上游边界入流检查失败：{exc}")
    elif runtime_stage == "calibration" and object_type == OBJECT_FULL_UPSTREAM and boundary_csv:
        warnings.append("完整上游流域通常不需要上游边界入流；如确需使用，请确认对象类型是否正确。")

    meteo = dict(config.get(METEO_KEY, {}))
    precip_mode = str(meteo.get(METEO_PRECIP_MODE_KEY, "grid_only")).strip()
    precip_source_ui = resolve_precip_source(config, precip_source)
    if runtime_stage == "calibration" and precip_mode in {"grid_plus_station_bias", "thiessen_station_only"}:
        station_precip_info = analyze_station_precip_inputs(config, step_hours=step_hours)
        for item in list(station_precip_info.get("missing", []) or []):
            if item not in missing:
                missing.append(str(item))
        for item in list(station_precip_info.get("warnings", []) or []):
            if item not in warnings:
                warnings.append(str(item))
    if precip_mode == "thiessen_station_only":
        warnings.append("纯泰森方案建议只作为快速基线，不建议直接作为最终方案。")
    if precip_source_ui == "custom_tif":
        warnings.append("降水来源为“本地栅格目录”时，请在第 6 步使用“验证并导入”；系统会写入工程独立降水目录，运行时直接读取。")
    pet_source = str(meteo.get(METEO_PET_SOURCE_KEY, "era5_fao56")).strip().lower()
    if runtime_stage == "calibration" and pet_source == "era5_direct":
        missing.append("潜在蒸散发来源“era5_direct”尚未接通，请改用 era5_fao56 或“本地栅格目录”。")

    if runtime_stage in {"calibration", "forward"}:
        for file_path in (_workspace_dem_path(paths["gis_dir"], prefer=_configured_dem_kind(config)), Path(paths["gis_dir"]) / "flow_accumulation_masked.tif"):
            if not file_path.exists():
                missing.append(f"缺少输入文件：{file_path}")

        forcing = validate_forcing_bundle(config, profile, precip_source=precip_source_ui)
        missing.extend(forcing["errors"])
        warnings.extend(forcing["warnings"])

    glacier_requirements = glacier_formal_requirements(config, profile)
    if glacier_requirements["enabled"]:
        for note in glacier_requirements.get("diagnostic_notes", []):
            warnings.append(note)

    if require_observed_flow:
        obs_path = _config_text_value(config, OBSERVED_FLOW_KEY)
        if not obs_path:
            _append_unique_message(missing, OBSERVED_FLOW_KEY)
        elif obs_file is None or not obs_file.exists():
            _append_unique_message(missing, f"观测径流文件不存在：{obs_path}")

    focus_checks = build_engineering_focus_checks(
        config,
        profile=profile,
        object_type=object_type,
        step_hours=step_hours,
        obs_info=obs_info,
        boundary_info=boundary_info,
        forcing=forcing,
        station_precip_info=station_precip_info,
        boundary_csv=boundary_csv,
    )

    return {
        "valid": len(missing) == 0,
        "missing": missing,
        "warnings": warnings,
        "profile": profile,
        "object_type": object_type,
        "stage": stage,
        "focus_checks": focus_checks,
        "input_time_summary": input_time_basis_ui_summary(
            config,
            time_basis=time_basis,
            step_hours=step_hours,
            event_info=event_window_info,
            context="calibration",
        ),
        "time_basis": time_basis,
        "time_basis_label": TIME_BASIS_LABELS.get(time_basis, "当前任务时段"),
        "event_windows": event_windows_ui_summary(event_window_info, step_hours) if event_window_info is not None else None,
    }


def wizard_step4_meteo_validation(config: dict[str, Any]) -> tuple[list[str], list[str]]:
    missing: list[str] = []
    warnings: list[str] = []
    meteo = dict(config.get(METEO_KEY, {}))
    precip_mode = str(meteo.get(METEO_PRECIP_MODE_KEY, "grid_only")).strip()
    precip_source = configured_precip_source(config)
    temp_source = str(meteo.get(METEO_TEMP_SOURCE_KEY, "era5")).strip().lower()
    pet_source = str(meteo.get(METEO_PET_SOURCE_KEY, "era5_fao56")).strip().lower()
    station_prec_path = _resolve_config_related_path(config, meteo.get(METEO_STATION_PREC_KEY))
    station_meta_path = _resolve_config_related_path(config, meteo.get(METEO_STATION_META_KEY))
    custom_prec_path = _resolve_config_related_path(config, meteo.get(METEO_CUSTOM_PREC_DIR_KEY))
    custom_temp_path = _resolve_config_related_path(config, meteo.get(METEO_CUSTOM_TEMP_DIR_KEY))
    custom_pet_path = _resolve_config_related_path(config, meteo.get(METEO_CUSTOM_PET_DIR_KEY))
    if precip_mode in {"grid_plus_station_bias", "thiessen_station_only"}:
        if not meteo.get(METEO_STATION_PREC_KEY):
            missing.append("站点降水 csv")
        elif station_prec_path is None or not station_prec_path.exists():
            missing.append(f"站点降水 csv 文件不存在：{meteo.get(METEO_STATION_PREC_KEY)}")
        if not meteo.get(METEO_STATION_META_KEY):
            missing.append("站点信息 csv")
        elif station_meta_path is None or not station_meta_path.exists():
            missing.append(f"站点信息 csv 文件不存在：{meteo.get(METEO_STATION_META_KEY)}")
    if precip_source == "custom_tif":
        custom_prec_dir = str(meteo.get(METEO_CUSTOM_PREC_DIR_KEY, "")).strip()
        if not custom_prec_dir:
            missing.append("本地降水栅格目录")
        elif custom_prec_path is None or not custom_prec_path.exists():
            missing.append(f"本地降水栅格目录不存在：{custom_prec_dir}")
    if temp_source == "custom_tif":
        custom_temp_dir = str(meteo.get(METEO_CUSTOM_TEMP_DIR_KEY, "")).strip()
        if not custom_temp_dir:
            missing.append("本地气温栅格目录")
        elif custom_temp_path is None or not custom_temp_path.exists():
            missing.append(f"本地气温栅格目录不存在：{custom_temp_dir}")
    if pet_source == "custom_tif":
        custom_pet_dir = str(meteo.get(METEO_CUSTOM_PET_DIR_KEY, "")).strip()
        if not custom_pet_dir:
            missing.append("本地蒸散发栅格目录")
        elif custom_pet_path is None or not custom_pet_path.exists():
            missing.append(f"本地蒸散发栅格目录不存在：{custom_pet_dir}")
    return missing, warnings


def get_data_prep_status(config_path_raw: str, precip_source: Any = None) -> list[dict[str, Any]]:
    cfg_path = resolve_any_path(config_path_raw, must_exist=True)
    config = read_runtime_config(cfg_path)
    runtime_prec_source = resolve_precip_source(config, precip_source)
    steps = [resolve_data_prep_step(step, config) for step in data_prep_steps(current_profile(config))]
    active_task = find_running_task("data_prep", str(cfg_path))
    active_step_id = str(active_task.metadata.get("step_id", "")).strip() if active_task is not None else ""
    active_progress = dict(active_task.metadata.get("ui_progress") or {}) if active_task is not None else {}
    done_set: set[str] = set()
    results: list[dict[str, Any]] = []
    for step in steps:
        if step.get("needs_prec_source"):
            done, message, count = step["check"](config, runtime_prec_source)
        else:
            done, message, count = step["check"](config)
        is_running = active_step_id == step["id"]
        if is_running:
            stage_label = str(active_progress.get("stage", "正在执行")).strip() or "正在执行"
            label = str(active_progress.get("label", step["title"])).strip() or step["title"]
            current = int(active_progress.get("current", 0) or 0)
            total = int(active_progress.get("total", 0) or 0)
            message = f"{stage_label}：{label}" + (f"（{current}/{total}）" if total > 0 else "") + "。"
        blocked_by = [dep for dep in step.get("depends_on", []) if dep not in done_set]
        if done:
            done_set.add(step["id"])
        results.append(
            {
                "id": step["id"],
                "title": step["title"],
                "description": step["description"],
                "done": done,
                "message": message,
                "file_count": count,
                "depends_on": step.get("depends_on", []),
                "blocked_by": blocked_by,
                "deps_met": not blocked_by,
                "optional": bool(step.get("optional", False)),
                "manual": bool(step.get("manual", False)),
                "supports_overwrite": bool(step.get("supports_overwrite", False)),
                "needs_prec_source": bool(step.get("needs_prec_source", False)),
                "running": is_running,
                "script": str(step["script"].resolve()) if step.get("script") else "",
            }
        )
    return results


def task_step_map(profile: str, config: dict[str, Any] | None = None) -> dict[str, dict[str, Any]]:
    return {step["id"]: resolve_data_prep_step(step, config) for step in data_prep_steps(profile)}


def add_task_output(task_id: str, line: str) -> None:
    with TASK_LOCK:
        task = TASKS.get(task_id)
        if task is not None:
            task.append(line)


def set_task_metadata(task_id: str, **items: Any) -> None:
    with TASK_LOCK:
        task = TASKS.get(task_id)
        if task is None:
            return
        task.metadata.update(items)
        task.updated_at = time.time()


def invalidate_deleted_run_refs(run_path: Path) -> None:
    deleted_run = run_path.resolve(strict=False)
    with TASK_LOCK:
        for task in TASKS.values():
            changed = False
            filtered_runs = [
                item for item in task.detected_runs
                if not same_path(Path(str(item)), deleted_run)
            ]
            if len(filtered_runs) != len(task.detected_runs):
                task.detected_runs = filtered_runs
                changed = True

            task_run_path = str(task.metadata.get("run_path", "") or "").strip()
            if task_run_path and same_path(Path(task_run_path), deleted_run):
                task.metadata["run_path"] = ""
                task.metadata["deleted_run_path"] = str(deleted_run)
                changed = True

            result = task.metadata.get("result")
            if isinstance(result, dict):
                result_run_path = str(result.get("run_path", "") or "").strip()
                if result_run_path and same_path(Path(result_run_path), deleted_run):
                    updated_result = dict(result)
                    updated_result["deleted_run_path"] = result_run_path
                    updated_result["run_path"] = ""
                    task.metadata["result"] = updated_result
                    changed = True

            if changed:
                task.updated_at = time.time()


def list_tasks() -> list[dict[str, Any]]:
    items = [task.as_dict() for task in _snapshot_tasks()]
    return sorted(items, key=lambda item: item["updated_at"], reverse=True)


def find_running_task(task_type: str, config_path_raw: str) -> TaskRecord | None:
    try:
        cfg_path = resolve_any_path(config_path_raw, must_exist=False).resolve(strict=False)
    except Exception:
        return None
    with TASK_LOCK:
        for task in TASKS.values():
            if task.task_type != task_type or task.status != "running":
                continue
            task_cfg = str(task.metadata.get("config_path", "")).strip()
            if not task_cfg:
                continue
            try:
                if Path(task_cfg).resolve(strict=False) == cfg_path:
                    return task
            except Exception:
                continue
    return None


def discover_runtime_roots() -> list[Path]:
    roots: list[Path] = []
    if PROJECT_RUNTIME_DIR.exists():
        roots.append(PROJECT_RUNTIME_DIR.resolve())
    for workspace in list_workspaces():
        runtime_root = workspace.get("workspace_root")
        if runtime_root:
            try:
                path = Path(runtime_root).resolve()
                if path.exists():
                    roots.append(path)
            except Exception:
                pass
    unique: list[Path] = []
    seen: set[str] = set()
    for root in roots:
        key = str(root).lower()
        if key not in seen:
            seen.add(key)
            unique.append(root)
    return unique


def iter_run_parent_dirs(root_dir: Path) -> list[Path]:
    workspace_dirs: list[Path] = []
    direct_results_roots = [
        path for path in profile_runner.workspace_path_candidates(root_dir, ("结果",), ("results",))
        if path.exists()
    ]
    if direct_results_roots:
        workspace_dirs.append(root_dir.resolve())
    for child in _safe_iterdir(root_dir):
        try:
            if not child.is_dir():
                continue
            child_results_roots = [
                path for path in profile_runner.workspace_path_candidates(child, ("结果",), ("results",))
                if path.exists()
            ]
            if not child_results_roots:
                continue
            workspace_dirs.append(child.resolve())
        except (PermissionError, OSError):
            continue

    parents: list[Path] = []
    for workspace_dir in workspace_dirs:
        results_roots = [
            path for path in profile_runner.workspace_path_candidates(workspace_dir, ("结果",), ("results",))
            if path.exists()
        ]
        for results_root in results_roots:
            direct_runs_dirs = [
                path for path in profile_runner.workspace_path_candidates(results_root, ("运行记录",), ("runs",))
                if path.exists()
            ]
            for direct_runs_dir in direct_runs_dirs:
                parents.append(direct_runs_dir.resolve())
            for child in _safe_iterdir(results_root):
                try:
                    if not child.is_dir():
                        continue
                except (PermissionError, OSError):
                    continue
                for candidate in profile_runner.workspace_path_candidates(child, ("运行记录",), ("runs",)):
                    try:
                        if candidate.exists() and candidate.is_dir():
                            parents.append(candidate.resolve())
                    except (PermissionError, OSError):
                        continue
    unique: list[Path] = []
    seen: set[str] = set()
    for parent in parents:
        key = str(parent).lower()
        if key in seen:
            continue
        seen.add(key)
        unique.append(parent)
    return unique


def _discover_run_entries() -> list[tuple[tuple[Any, ...], Path]]:
    entries: list[tuple[tuple[Any, ...], Path]] = []
    seen: set[str] = set()
    for root_dir in discover_runtime_roots():
        for runs_dir in iter_run_parent_dirs(root_dir):
            for candidate in _safe_iterdir(runs_dir):
                try:
                    if not candidate.is_dir():
                        continue
                    metadata_path = candidate / "metadata.json"
                    simulation_path = candidate / "simulation.csv"
                    if not metadata_path.exists() or not simulation_path.exists():
                        continue
                    resolved = candidate.resolve()
                    key = str(resolved).lower()
                    if key in seen:
                        continue
                    seen.add(key)
                    run_stat = resolved.stat()
                    metadata_stat = metadata_path.stat()
                    simulation_stat = simulation_path.stat()
                except (FileNotFoundError, PermissionError, OSError):
                    continue
                entries.append(
                    (
                        (
                            key,
                            int(getattr(run_stat, "st_mtime_ns", int(run_stat.st_mtime * 1e9))),
                            int(getattr(metadata_stat, "st_mtime_ns", int(metadata_stat.st_mtime * 1e9))),
                            int(getattr(simulation_stat, "st_mtime_ns", int(simulation_stat.st_mtime * 1e9))),
                            int(simulation_stat.st_size),
                        ),
                        resolved,
                    )
                )
    entries.sort(key=lambda item: item[0][0])
    return entries


def iter_run_dirs() -> list[Path]:
    return [path for _, path in _discover_run_entries()]


def _run_update_timestamps(run_dir: Path) -> tuple[float, int]:
    updated_at = run_dir.stat().st_mtime
    updated_at_ns = int(getattr(run_dir.stat(), "st_mtime_ns", int(updated_at * 1e9)))
    for candidate in (run_dir / "metadata.json", run_dir / "simulation.csv"):
        try:
            stat = candidate.stat()
            updated_at = max(updated_at, stat.st_mtime)
            updated_at_ns = max(updated_at_ns, int(getattr(stat, "st_mtime_ns", int(stat.st_mtime * 1e9))))
        except (FileNotFoundError, PermissionError, OSError):
            pass
    return updated_at, updated_at_ns


def _workspace_name_for_summary(metadata: dict[str, Any], resolved_config: Path | None = None) -> str:
    value = str(metadata.get("workspace_label", "") or "").strip()
    if value:
        return value
    config_path = resolved_config
    if config_path is None:
        hint_project_root, hint_gui_root = _workspace_roots_hint_from_metadata(metadata)
        config_path = resolve_workspace_config_reference(
            str(metadata.get("workspace_config", "") or ""),
            project_root=hint_project_root,
            gui_root=hint_gui_root,
        )
    if config_path is not None:
        try:
            config = read_runtime_config(config_path)
            value = str(config.get("流域名称", config_path.stem)).strip()
            if value:
                return value
        except Exception:
            return config_path.stem
    raw = str(metadata.get("workspace_config", "") or "").strip()
    if raw:
        try:
            return Path(raw).stem
        except Exception:
            return raw
    return ""


def _run_kind_from_metadata(metadata: dict[str, Any] | None, studio_compatible: bool = False) -> str:
    meta = dict(metadata or {})
    forecast_result = dict(meta.get("forecast_result", {}) or {})
    manual_result = dict(meta.get("manual_result", {}) or {})
    starter_result = dict(meta.get("starter_result", {}) or {})
    if bool(forecast_result.get("enabled")) or str(meta.get("run_class", "") or "") == "forecast_restart":
        return "forecast_restart"
    if bool(manual_result.get("enabled")):
        return "manual_result"
    if bool(starter_result.get("enabled")):
        return "manual_starter"
    if studio_compatible:
        return "calibration"
    return "legacy"


def _run_kind_label(kind: str) -> str:
    return RUN_KIND_LABELS.get(kind, "结果")


def _normalized_result_title(value: Any) -> str:
    text = re.sub(r"\s+", " ", str(value or "").strip())
    return text.strip()


def _has_custom_result_title(run_dir: Path, title: str) -> bool:
    normalized = _normalized_result_title(title)
    if not normalized:
        return False
    if normalized.lower() == run_dir.name.lower():
        return False
    if normalized in SYSTEM_RESULT_TITLES:
        return False
    return True


def _run_time_label(raw_value: Any, updated_at: float | None = None) -> str:
    text = str(raw_value or "").strip()
    if text:
        return text
    if updated_at:
        try:
            return time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(float(updated_at)))
        except Exception:
            return ""
    return ""


def _source_run_meta(metadata: dict[str, Any]) -> tuple[str, str]:
    manual_result = dict(metadata.get("manual_result", {}) or {})
    optimization = dict(metadata.get("optimization", {}) or {})
    replay_context = dict(metadata.get("replay_context", {}) or {})
    source_path = str(
        replay_context.get("source_run_path")
        or manual_result.get("source_run_path")
        or optimization.get("source_run_path")
        or ""
    ).strip()
    source_name = str(
        replay_context.get("source_run_name")
        or manual_result.get("source_run_name")
        or optimization.get("source_run_name")
        or ""
    ).strip()
    if not source_name and source_path:
        try:
            source_name = Path(str(replace_placeholders(source_path))).name
        except Exception:
            source_name = Path(source_path).name
    return source_path, source_name


HYDROLOGY_PROCESS_REVIEW_REPORT_NAME = "水文过程复核报告.md"
HYDROLOGY_DIAGNOSTIC_REPORT_NAME = HYDROLOGY_PROCESS_REVIEW_REPORT_NAME
LEGACY_HYDROLOGY_DIAGNOSTIC_REPORT_NAME = "水文诊断摘要.md"
CURRENT_DAILY_OBJECTIVE_FAMILY = "daily_unified_professional_v1"
FLOOD_EVENT_OBJECTIVE_FAMILY = "flood_event_calibration_v1"
HISTORICAL_OBJECTIVE_FAMILIES = {"weighted_daily_universal", "weighted_multi_criteria"}


def _metadata_objective_family(metadata: dict[str, Any]) -> str:
    return str(
        metadata.get("recorded_objective_family")
        or metadata.get("objective_family")
        or metadata.get("effective_objective_mode")
        or metadata.get("optimization", {}).get("effective_objective_mode")
        or metadata.get("optimization", {}).get("objective_mode")
        or metadata.get("objective_profile", {}).get("type")
        or metadata.get("objective", {}).get("type")
        or ""
    ).strip()


def _status_zh(value: Any) -> str:
    key = str(value or "").strip()
    labels = {
        "": "—",
        "ok": "正常",
        "pass": "通过",
        "fail": "未通过",
        "penalized": "—",
        "outside_flow_floor": "径流拟合未达标",
        "below_flow_floor": "径流拟合未达标",
        "above_guard": "高于参考区间",
        "above_window": "高于参考区间",
        "below_window": "低于参考区间",
        "in_window": "在参考区间内",
        "takeover": "—",
        "capped": "—",
        "skipped": "未启用",
        "skipped_inactive": "未启用",
        "disabled_by_default": "未采用",
        "not_applicable_no_glacier": "无冰川模块",
        "skipped_insufficient_data": "—",
        "skipped_hard_checks": "—",
    }
    return labels.get(key, key or "—")


def _years_from(raw_value: Any) -> list[int]:
    if not isinstance(raw_value, list):
        return []
    years: list[int] = []
    for item in raw_value:
        try:
            years.append(int(item))
        except Exception:
            continue
    return sorted(set(years))


def _years_text(raw_value: Any) -> str:
    years = _years_from(raw_value)
    return "、".join(str(year) for year in years)


def _percent_text(value: Any, digits: int = 1) -> str:
    num = safe_float(value)
    if num is None:
        return "—"
    return f"{num * 100:.{digits}f}%"


def _component_basis_text(value: Any) -> str:
    key = str(value or "").strip()
    if key == "local_runoff_calibration_period":
        return "率定期本地径流口径，不含上游边界入流"
    if key in {"total_runoff_calibration_period", "calibration_period"}:
        return "率定期模拟总流量口径"
    return "率定期模拟径流口径"


def _metric_text(value: Any, digits: int = 4, suffix: str = "") -> str:
    num = safe_float(value)
    if num is None:
        return "—"
    return f"{num:.{digits}f}{suffix}"


def _flood_event_evaluation(metadata: dict[str, Any]) -> dict[str, Any]:
    raw = metadata.get("flood_event_evaluation")
    if isinstance(raw, dict):
        return raw
    diagnostics = dict(metadata.get("diagnostics", {}) or {})
    raw = diagnostics.get("flood_event_evaluation")
    return dict(raw) if isinstance(raw, dict) else {}


def _flood_event_report_lines(metadata: dict[str, Any]) -> list[str]:
    evaluation = _flood_event_evaluation(metadata)
    if not bool(evaluation.get("enabled")):
        return []
    events = list(evaluation.get("events", []) or [])
    lines = [
        "## 4. 洪水事件评价",
        "",
        f"- 事件评价状态：{evaluation.get('status', '—')}",
        f"- 有效事件场次：{evaluation.get('valid_event_count', 0)}/{evaluation.get('event_count', 0)}",
        f"- 事件目标函数：{'已启用' if evaluation.get('objective_enabled') else '未启用，仅作诊断'}",
        "",
    ]
    if not events:
        lines.extend(["当前结果未写出可显示的洪水事件。", ""])
        return lines
    lines.extend([
        "| 事件 | 类型 | 洪峰误差 | 峰现误差 | 洪量误差 | NSE | KGE | 高流量NSE | 高流量KGE | 退水误差 |",
        "| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |",
    ])
    for event in events:
        if not isinstance(event, dict):
            continue
        lines.append(
            "| "
            + " | ".join([
                str(event.get("name", "—") or "—"),
                str(event.get("type", "—") or "—"),
                _metric_text(event.get("peak_error_percent"), 2, "%"),
                _metric_text(event.get("peak_time_error_hours"), 1, " h"),
                _metric_text(event.get("volume_error_percent"), 2, "%"),
                _metric_text(event.get("nse")),
                _metric_text(event.get("kge")),
                _metric_text(event.get("high_flow_weighted_nse")),
                _metric_text(event.get("high_flow_kge")),
                _metric_text(event.get("recession_slope_error_percent"), 2, "%"),
            ])
            + " |"
        )
    lines.append("")
    return lines


def _workflow_label_zh(metadata: dict[str, Any]) -> str:
    family = _metadata_objective_family(metadata)
    workflow = str(metadata.get("calibration_workflow") or "").strip()
    workflow_status = str(metadata.get("calibration_workflow_status") or "").strip()
    if family in HISTORICAL_OBJECTIVE_FAMILIES or workflow_status == "historical":
        return "历史率定结果"
    if family == FLOOD_EVENT_OBJECTIVE_FAMILY:
        return "事件洪水率定"
    if workflow == "staged_calibration_v1" or workflow_status == "experimental":
        return "过程复核结果"
    if workflow == "single_pass" or not workflow:
        return "单流程参数率定"
    return "单流程参数率定"


def _objective_label_zh(metadata: dict[str, Any]) -> str:
    family = _metadata_objective_family(metadata)
    if family == FLOOD_EVENT_OBJECTIVE_FAMILY:
        return "事件洪水率定目标函数"
    if family == CURRENT_DAILY_OBJECTIVE_FAMILY:
        return "统一日尺度综合水文目标函数"
    if family in HISTORICAL_OBJECTIVE_FAMILIES:
        return "历史目标函数结果（仅兼容查看）"
    return "统一日尺度综合水文目标函数" if not family else "其他目标函数"


def _flow_status_zh(metadata: dict[str, Any]) -> str:
    flow_guard = dict(metadata.get("objective_terms", {}).get("flow_guard", {}) or {})
    status = str(flow_guard.get("status") or "").strip()
    if status in {"ok", "pass"}:
        return "径流拟合达标"
    if status and status not in {"skipped", "skipped_insufficient_data"}:
        return "径流拟合未达标"
    metrics = dict(metadata.get("metrics", {}) or {})
    cal = dict(metrics.get("calibration", {}) or {})
    val = dict(metrics.get("validation", {}) or {})
    nse_cal = safe_float(cal.get("nse"))
    nse_val = safe_float(val.get("nse"))
    pbias_cal = safe_float(cal.get("pbias"))
    pbias_val = safe_float(val.get("pbias"))
    if (
        nse_cal is not None
        and nse_cal >= 0.60
        and (nse_val is None or nse_val >= 0.50)
        and (pbias_cal is None or abs(pbias_cal) <= 20.0)
        and (pbias_val is None or abs(pbias_val) <= 25.0)
    ):
        return "径流拟合达标"
    return "径流拟合未达标"


def _ice_status_zh(metadata: dict[str, Any]) -> str:
    glacier_enabled = bool(metadata.get("optional_modules", {}).get("glacier", {}).get("enabled"))
    if not glacier_enabled:
        return "未启用冰川模块"
    diagnostics = dict(metadata.get("diagnostics", {}) or {})
    component_report = dict(diagnostics.get("component_fraction_report", {}) or {})
    rain = component_report.get("rain_fraction")
    snow = component_report.get("snow_fraction")
    ice = component_report.get("ice_fraction")
    if rain is None and snow is None and ice is None:
        return "已启用冰川模块"
    return (
        f"降雨 {_percent_text(rain)} / "
        f"融雪 {_percent_text(snow)} / "
        f"裸冰 {_percent_text(ice)}"
    )


def _build_hydrology_summary(metadata: dict[str, Any], run_dir: Path) -> dict[str, Any]:
    report_path = run_dir / HYDROLOGY_DIAGNOSTIC_REPORT_NAME
    return {
        "workflow_label_zh": _workflow_label_zh(metadata),
        "objective_label_zh": _objective_label_zh(metadata),
        "flow_status_zh": _flow_status_zh(metadata),
        "ice_status_zh": _ice_status_zh(metadata),
        "diagnostics_detail_path": str(report_path.resolve(strict=False)),
        "diagnostics_detail_display_path": to_display_path(report_path),
        "diagnostics_detail_note": "水文模拟结果说明已保存至本地结果目录。",
    }


def _hydrology_diagnostic_report_text(metadata: dict[str, Any], summary: dict[str, Any]) -> str:
    metrics = dict(metadata.get("metrics", {}) or {})
    cal = dict(metrics.get("calibration", {}) or {})
    val = dict(metrics.get("validation", {}) or {})
    diagnostics = dict(metadata.get("diagnostics", {}) or {})
    component_report = dict(diagnostics.get("component_fraction_report", {}) or {})

    lines = [
        "# 水文模拟结果说明",
        "",
        "本文件由 HBV-Studio 自动生成，记录本次率定运行的关键参数与结果。",
        "",
        "## 1. 运行信息",
        "",
        f"- 率定流程：{summary.get('workflow_label_zh', '—')}",
        f"- 评分标准：{summary.get('objective_label_zh', '—')}",
        f"- 结果时间：{metadata.get('run_time', '—')}",
        f"- 运行目录：{summary.get('diagnostics_detail_display_path', '—')}",
        "",
        "## 2. 径流拟合精度",
        "",
        f"- 率定期 NSE / KGE / PBIAS / RMSE：{_metric_text(cal.get('nse'))} / {_metric_text(cal.get('kge'))} / {_metric_text(cal.get('pbias'), 2, '%')} / {_metric_text(cal.get('rmse'))}",
        f"- 验证期 NSE / KGE / PBIAS / RMSE：{_metric_text(val.get('nse'))} / {_metric_text(val.get('kge'))} / {_metric_text(val.get('pbias'), 2, '%')} / {_metric_text(val.get('rmse'))}",
        f"- 综合判断：{summary.get('flow_status_zh', '—')}",
        "",
        "## 3. 三水源分量年合计",
        "",
        "依据 HBV 模型水源追踪机制，模拟总流量按降雨产流、融雪径流、裸冰融化三类水源分别累计，率定期内构成如下：",
        "",
        "| 水源类型 | 占模拟总流量比例 |",
        "| --- | --- |",
        f"| 降雨产流 | {_percent_text(component_report.get('rain_fraction'))} |",
        f"| 融雪径流 | {_percent_text(component_report.get('snow_fraction'))} |",
        f"| 裸冰融化 | {_percent_text(component_report.get('ice_fraction'))} |",
        "",
        f"- 口径：{_component_basis_text(component_report.get('evaluation_period'))}",
        "",
    ]
    event_lines = _flood_event_report_lines(metadata)
    if event_lines:
        lines.extend(event_lines)
        remarks_title = "## 5. 备注"
    else:
        remarks_title = "## 4. 备注"
    lines.extend([
        remarks_title,
        "",
        "- 三水源比例为模型按 HBV 标准三水源追踪算法逐时步累加得到的全流域汇总值。",
        "- 具体数值受流域冰川面积、气温递减率、降水相态划分和参数率定结果共同影响。",
        "",
    ])
    return "\n".join(lines)


def _ensure_hydrology_diagnostic_report(run_dir: Path, metadata: dict[str, Any], summary: dict[str, Any]) -> dict[str, Any]:
    report_path = run_dir / HYDROLOGY_DIAGNOSTIC_REPORT_NAME
    legacy_report_path = run_dir / LEGACY_HYDROLOGY_DIAGNOSTIC_REPORT_NAME
    updated_summary = dict(summary)
    try:
        report_text = _hydrology_diagnostic_report_text(metadata, updated_summary)
        if not report_path.exists() or report_path.read_text(encoding="utf-8") != report_text:
            report_path.write_text(report_text, encoding="utf-8")
        if legacy_report_path.exists():
            legacy_report_path.write_text(report_text, encoding="utf-8")
        updated_summary["diagnostics_detail_path"] = str(report_path.resolve(strict=False))
        updated_summary["diagnostics_detail_display_path"] = to_display_path(report_path)
        updated_summary["diagnostics_report_status"] = "available"
    except Exception as exc:
        updated_summary["diagnostics_report_status"] = "write_failed"
        updated_summary["diagnostics_report_error"] = str(exc)
    return updated_summary


def _display_run_title(
    run_dir: Path,
    metadata: dict[str, Any],
    resolved_config: Path | None,
    studio_compatible: bool,
    updated_at: float | None = None,
) -> dict[str, Any]:
    raw_title = _normalized_result_title(metadata.get("result_title", ""))
    workspace_name = _workspace_name_for_summary(metadata, resolved_config)
    run_kind = _run_kind_from_metadata(metadata, studio_compatible)
    run_kind_label = _run_kind_label(run_kind)
    run_time_text = _run_time_label(metadata.get("run_time"), updated_at)
    has_custom_title = _has_custom_result_title(run_dir, raw_title)
    if has_custom_title:
        display_name = raw_title
        subtitle_parts = [workspace_name, run_kind_label, run_time_text]
    else:
        display_name = " · ".join(part for part in (workspace_name, run_kind_label, run_time_text) if part)
        subtitle_parts = []
    display_name = display_name or raw_title or run_dir.name
    subtitle = " · ".join(part for part in subtitle_parts if part)
    if not subtitle and display_name != run_dir.name:
        subtitle = f"目录名：{run_dir.name}"
    return {
        "name": raw_title or run_dir.name,
        "raw_title": raw_title,
        "display_name": display_name,
        "display_subtitle": subtitle,
        "has_custom_title": has_custom_title,
        "run_type": run_kind,
        "run_type_label": run_kind_label,
        "workspace_name": workspace_name,
        "run_time_label": run_time_text,
    }


def _build_run_summary(
    run_dir: Path,
    metadata: dict[str, Any] | None = None,
    resolved_config: Path | None = None,
    *,
    updated_at: float | None = None,
    updated_at_ns: int | None = None,
) -> dict[str, Any]:
    if updated_at is None or updated_at_ns is None:
        updated_at, updated_at_ns = _run_update_timestamps(run_dir)
    summary = {
        "name": run_dir.name,
        "raw_title": "",
        "display_name": run_dir.name,
        "display_subtitle": "",
        "has_custom_title": False,
        "path": str(run_dir.resolve()),
        "display_path": to_display_path(run_dir),
        "updated_at": updated_at,
        "updated_at_ns": int(updated_at_ns),
        "run_time": None,
        "run_id": None,
        "nse_cal": None,
        "nse_val": None,
        "pbias_cal": None,
        "pbias_val": None,
        "glacier_enabled": None,
        "boundary_enabled": None,
        "time_step_hours": None,
        "time_config": {},
        "calibration_profile": None,
        "object_type": None,
        "workspace_config": "",
        "workspace_display_path": "",
        "workspace_name": "",
        "studio_compatible": False,
        "run_origin": "legacy",
        "run_type": "legacy",
        "run_type_label": RUN_KIND_LABELS["legacy"],
        "run_time_label": "",
        "source_run_path": "",
        "source_run_name": "",
        "recorded_objective_family": "",
        "objective_family": "",
        "effective_objective_mode": "",
        "flow_guard_status": "",
        "hydrology_summary": {},
        "optimized_params_available": False,
        "optimized_param_count": 0,
        "state_snapshot_available": False,
        "state_snapshot_time": "",
        "source_state_snapshot_time": "",
        "source_state_summary": {},
        "source_parameter_summary": {},
        "forecast_input_archive": {},
        "forecast_source_ready": False,
    }
    if metadata is None:
        return summary
    summary["run_time"] = metadata.get("run_time")
    summary["run_id"] = metadata.get("run_id")
    summary["nse_cal"] = metadata.get("metrics", {}).get("calibration", {}).get("nse")
    summary["nse_val"] = metadata.get("metrics", {}).get("validation", {}).get("nse")
    summary["pbias_cal"] = metadata.get("metrics", {}).get("calibration", {}).get("pbias")
    summary["pbias_val"] = metadata.get("metrics", {}).get("validation", {}).get("pbias")
    summary["glacier_enabled"] = metadata.get("optional_modules", {}).get("glacier", {}).get("enabled")
    summary["boundary_enabled"] = metadata.get("optional_modules", {}).get("boundary_inflow", {}).get("enabled")
    summary["time_step_hours"] = metadata.get("time_config", {}).get("time_step_hours")
    summary["time_config"] = dict(metadata.get("time_config", {}) or {})
    summary["calibration_profile"] = metadata.get("calibration_profile")
    summary["object_type"] = metadata.get("project_object_type")
    workspace_config = str(metadata.get("workspace_config", "") or "").strip()
    summary["workspace_config"] = workspace_config
    if workspace_config:
        try:
            summary["workspace_display_path"] = to_display_path(Path(workspace_config))
        except Exception:
            summary["workspace_display_path"] = workspace_config
    studio_compatible = is_studio_editable_metadata(metadata, resolved_config)
    summary["studio_compatible"] = studio_compatible
    summary["run_origin"] = "studio" if studio_compatible else "legacy"
    summary["recorded_objective_family"] = str(metadata.get("recorded_objective_family") or "").strip()
    summary["objective_family"] = str(
        metadata.get("recorded_objective_family")
        or metadata.get("objective_family")
        or metadata.get("effective_objective_mode")
        or metadata.get("optimization", {}).get("effective_objective_mode")
        or metadata.get("optimization", {}).get("objective_mode")
        or metadata.get("objective_profile", {}).get("type")
        or metadata.get("objective", {}).get("type")
        or ""
    ).strip()
    summary["effective_objective_mode"] = str(
        metadata.get("effective_objective_mode")
        or metadata.get("optimization", {}).get("effective_objective_mode")
        or ""
    ).strip()
    summary["flow_guard_status"] = str(
        metadata.get("objective_terms", {}).get("flow_guard", {}).get("status", "")
        or ""
    ).strip()
    summary["hydrology_summary"] = _build_hydrology_summary(metadata, run_dir)
    initial_state = dict(metadata.get("initial_state", {}) or {})
    forecast_result = dict(metadata.get("forecast_result", {}) or {})
    snapshot_file = str(initial_state.get("state_snapshot_file", "") or "").strip()
    snapshot_path = run_dir / snapshot_file if snapshot_file else run_dir / "state_snapshot.npz"
    optimized_params = metadata.get("optimized_params", {})
    summary["optimized_params_available"] = bool(isinstance(optimized_params, dict) and optimized_params)
    summary["optimized_param_count"] = int(len(optimized_params)) if isinstance(optimized_params, dict) else 0
    summary["state_snapshot_available"] = bool(snapshot_path.exists() or initial_state.get("state_snapshot_available"))
    summary["state_snapshot_time"] = str(initial_state.get("state_snapshot_time", "") or "").strip()
    summary["source_state_snapshot_time"] = str(
        initial_state.get("source_state_snapshot_time")
        or forecast_result.get("source_state_time")
        or ""
    ).strip()
    summary["source_state_summary"] = dict(
        forecast_result.get("source_state_summary")
        or metadata.get("source_state_summary")
        or {}
    )
    summary["source_parameter_summary"] = dict(
        forecast_result.get("source_parameter_summary")
        or metadata.get("source_parameter_summary")
        or {}
    )
    summary["forecast_input_archive"] = dict(
        forecast_result.get("forecast_input_archive")
        or dict(metadata.get("data_sources", {}) or {}).get("forecast_input_archive")
        or {}
    )
    summary["forecast_source_ready"] = bool(summary["optimized_params_available"] and summary["state_snapshot_available"])
    summary.update(_display_run_title(run_dir, metadata, resolved_config, studio_compatible, updated_at=updated_at))
    source_run_path, source_run_name = _source_run_meta(metadata)
    summary["source_run_path"] = source_run_path
    summary["source_run_name"] = source_run_name
    return summary


def summarize_run(run_dir: Path) -> dict[str, Any]:
    metadata_path = run_dir / "metadata.json"
    updated_at, updated_at_ns = _run_update_timestamps(run_dir)
    summary = _build_run_summary(run_dir, updated_at=updated_at, updated_at_ns=updated_at_ns)
    try:
        metadata, resolved_config = normalize_run_metadata(read_json_file(metadata_path), run_path=run_dir)
        summary = _build_run_summary(
            run_dir,
            metadata,
            resolved_config,
            updated_at=updated_at,
            updated_at_ns=updated_at_ns,
        )
    except Exception:
        pass
    return summary


def list_runs() -> list[dict[str, Any]]:
    global RUN_LIST_CACHE_SIGNATURE, RUN_LIST_CACHE_ITEMS
    entries = _discover_run_entries()
    signature = tuple(item[0] for item in entries)
    with RUN_LIST_CACHE_LOCK:
        if signature == RUN_LIST_CACHE_SIGNATURE:
            return [dict(item) for item in RUN_LIST_CACHE_ITEMS]

    items = sorted([summarize_run(path) for _, path in entries], key=lambda item: item["updated_at"], reverse=True)
    with RUN_LIST_CACHE_LOCK:
        RUN_LIST_CACHE_SIGNATURE = signature
        RUN_LIST_CACHE_ITEMS = [dict(item) for item in items]
    return items


def read_sampled_csv_rows(path: Path, max_points: int = 900) -> tuple[list[dict[str, str]], int]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        total_rows = max(sum(1 for _ in handle) - 1, 0)
    if total_rows <= 0:
        return [], 0

    stride = 1 if total_rows <= max_points else max(1, total_rows // max_points)
    sampled: list[dict[str, str]] = []
    last_row: dict[str, str] | None = None
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        for idx, row in enumerate(reader):
            last_row = row
            if stride == 1 or idx % stride == 0:
                sampled.append(row)
    if last_row is not None and (not sampled or sampled[-1] != last_row):
        sampled.append(last_row)
    return sampled, total_rows


def _run_export_time_label(timestamp: pd.Timestamp, step_hours: float) -> str:
    return format_timestamp_for_display(timestamp, step_hours).replace(":", "-").replace(" ", "_")


def export_run_excel(payload: dict[str, Any]) -> dict[str, Any]:
    run_dir = resolve_any_path(str(payload.get("path", "")), must_exist=True)
    simulation_path = run_dir / "simulation.csv"
    metadata_path = run_dir / "metadata.json"
    if not simulation_path.exists():
        raise FileNotFoundError("结果目录缺少 simulation.csv。")
    metadata = read_json_file(metadata_path) if metadata_path.exists() else {}
    time_cfg = dict(metadata.get("time_config", {}) or {})
    step_hours = normalize_time_step_hours(time_cfg.get("time_step_hours", 24.0))

    selected_fields = [
        field
        for field in [str(item).strip() for item in list(payload.get("fields", []) or [])]
        if field
    ] or default_run_export_fields(metadata)
    invalid_fields = [field for field in selected_fields if field not in RUN_EXPORT_FIELD_LABELS]
    if invalid_fields:
        raise ValueError("存在不支持的导出字段：" + "、".join(invalid_fields[:6]))

    frame = pd.read_csv(simulation_path)
    if "date" not in frame.columns:
        raise ValueError("simulation.csv 缺少 date 列。")
    frame["date"] = pd.to_datetime(frame["date"], errors="coerce")
    frame = frame.dropna(subset=["date"]).copy()
    if frame.empty:
        raise ValueError("当前结果没有可导出的有效时间记录。")

    start_raw = str(payload.get("start_date", "")).strip()
    end_raw = str(payload.get("end_date", "")).strip()
    start_ts = pd.to_datetime(start_raw) if start_raw else pd.Timestamp(frame["date"].min())
    end_ts = pd.to_datetime(end_raw) if end_raw else pd.Timestamp(frame["date"].max())
    if step_hours < 24.0 and is_date_only_string(end_raw):
        end_ts = end_ts + pd.Timedelta(days=1) - pd.Timedelta(hours=step_hours)
    if end_ts < start_ts:
        raise ValueError("导出结束时间不能早于开始时间。")

    actual_start = pd.Timestamp(frame["date"].min())
    actual_end = pd.Timestamp(frame["date"].max())
    warmup_start_raw = str(time_cfg.get("warmup_start", "") or "").strip()
    warmup_start_ts = pd.to_datetime(warmup_start_raw) if warmup_start_raw else None
    if warmup_start_ts is not None and actual_start > warmup_start_ts and start_ts < actual_start:
        raise ValueError(
            "当前结果文件只保存了率定后时段，未包含预热段。"
            "请用新版程序重新生成结果后，再导出包含预热期的全时段数据。"
        )

    filtered = frame.loc[(frame["date"] >= start_ts) & (frame["date"] <= end_ts)].copy()
    if filtered.empty:
        raise ValueError("当前时间范围内没有可导出的结果记录。")

    export_frame = pd.DataFrame()
    export_frame["日期"] = filtered["date"].dt.strftime("%Y-%m-%d" if step_hours >= 24.0 else "%Y-%m-%d %H:%M")
    for field in selected_fields:
        export_frame[RUN_EXPORT_FIELD_LABELS[field]] = filtered[field] if field in filtered.columns else pd.NA

    export_dir = run_dir / "导出"
    export_dir.mkdir(parents=True, exist_ok=True)
    run_title = str(metadata.get("result_title", "")).strip() or run_dir.name
    file_name = (
        f"{slugify_workspace_name(run_title)}"
        f"_导出_{_run_export_time_label(start_ts, step_hours)}"
        f"_{_run_export_time_label(end_ts, step_hours)}.xlsx"
    )
    export_path = export_dir / file_name
    try:
        with pd.ExcelWriter(export_path, engine="xlsxwriter") as writer:
            export_frame.to_excel(writer, sheet_name="结果数据", index=False)
            worksheet = writer.sheets["结果数据"]
            worksheet.freeze_panes(1, 1)
            worksheet.set_column(0, 0, 18)
            worksheet.set_column(1, len(export_frame.columns), 18)
    except ImportError:
        with pd.ExcelWriter(export_path, engine="openpyxl") as writer:
            export_frame.to_excel(writer, sheet_name="结果数据", index=False)

    return {
        "path": str(export_path.resolve(strict=False)),
        "display_path": to_display_path(export_path),
        "row_count": int(len(export_frame)),
        "fields": list(selected_fields),
        "labels": [RUN_EXPORT_FIELD_LABELS[field] for field in selected_fields],
        "start": export_frame.iloc[0, 0],
        "end": export_frame.iloc[-1, 0],
    }


def load_run_detail(run_path: str) -> dict[str, Any]:
    run_dir = resolve_any_path(run_path, must_exist=True)
    simulation_path = run_dir / "simulation.csv"
    metadata_path = run_dir / "metadata.json"
    if not simulation_path.exists() or not metadata_path.exists():
        raise FileNotFoundError("结果目录缺少 simulation.csv 或 metadata.json。")
    metadata, resolved_config = normalize_run_metadata(read_json_file(metadata_path), run_path=run_dir)
    updated_at, updated_at_ns = _run_update_timestamps(run_dir)
    sampled, total_rows = read_sampled_csv_rows(simulation_path)
    fields = ["q_sim", "q_sim_model", "q_boundary_inflow", "q_obs", "q_rain", "q_snow", "q_ice", "q_ice_raw", "q_ice_reference", "q_ice_reference_raw"]
    series = {field: [] for field in fields}
    dates: list[str] = []
    residuals: list[float | None] = []
    for row in sampled:
        dates.append(row.get("date", ""))
        q_sim = safe_float(row.get("q_sim"))
        q_obs = safe_float(row.get("q_obs"))
        residuals.append((q_sim - q_obs) if (q_sim is not None and q_obs is not None) else None)
        for field in fields:
            series[field].append(safe_float(row.get(field)))
    time_cfg = dict(metadata.get("time_config", {}) or {})
    actual_start = dates[0] if dates else ""
    actual_end = dates[-1] if dates else ""
    warmup_start = str(time_cfg.get("warmup_start", "") or "")
    warmup_covered = bool(actual_start and (not warmup_start or str(actual_start).strip() == warmup_start.strip()))
    hydrology_summary = _ensure_hydrology_diagnostic_report(
        run_dir,
        metadata,
        _build_hydrology_summary(metadata, run_dir),
    )
    metadata["hydrology_summary"] = hydrology_summary
    run_summary = _build_run_summary(
        run_dir,
        metadata,
        resolved_config,
        updated_at=updated_at,
        updated_at_ns=updated_at_ns,
    )
    run_summary["hydrology_summary"] = hydrology_summary
    return {
        "run": run_summary,
        "metadata": metadata,
        "hydrology_summary": hydrology_summary,
        "series": {"dates": dates, "residuals": residuals, **series},
        "series_range": {
            "actual_start": actual_start,
            "actual_end": actual_end,
            "warmup_start": warmup_start,
            "warmup_end": str(time_cfg.get("warmup_end", "") or ""),
            "warmup_covered": warmup_covered,
        },
        "sampling": {"sampled_points": len(sampled), "total_points": total_rows},
        "parameters": [{"name": key, "value": value} for key, value in metadata.get("optimized_params", {}).items()],
        "studio_compatible": is_studio_editable_metadata(metadata, resolved_config),
    }


def _load_run_series_map(run_path: Path, field: str) -> dict[str, float | None]:
    simulation_path = run_path / "simulation.csv"
    if not simulation_path.exists():
        return {}
    values: dict[str, float | None] = {}
    with simulation_path.open("r", encoding="utf-8") as fh:
        reader = csv.DictReader(fh)
        for row in reader:
            date_text = str(row.get("date", "")).strip()
            if not date_text:
                continue
            values[date_text] = safe_float(row.get(field))
    return values


def _metadata_initial_state_override(metadata: dict[str, Any]) -> dict[str, float] | None:
    initial_state = dict(metadata.get("initial_state", {}) or {})
    raw_vector = initial_state.get("vector", None)
    if not isinstance(raw_vector, dict):
        return None

    override: dict[str, float] = {}
    for key in profile_runner.DEFAULT_INIT_STATE.keys():
        if key not in raw_vector:
            continue
        raw_value = raw_vector.get(key)
        try:
            value = float(raw_value)
        except Exception as exc:
            raise ValueError(f"结果 metadata 中的 initial_state.{key} 不是有效数字：{raw_value}") from exc
        if value < 0:
            raise ValueError(f"结果 metadata 中的 initial_state.{key} 不能为负值：{raw_value}")
        override[key] = value
    return override or None


def _apply_run_replay_config_overrides(config: dict[str, Any], metadata: dict[str, Any]) -> dict[str, Any]:
    patched = copy.deepcopy(config)
    time_meta = dict(metadata.get("time_config", {}) or {})
    if time_meta:
        time_cfg = dict(patched.get("时间", {}) or {})
        key_map = {
            "warmup_start": "预热开始",
            "warmup_end": "预热结束",
            "calib_start": "率定开始",
            "calib_end": "率定结束",
            "valid_start": "验证开始",
            "valid_end": "验证结束",
        }
        for src_key, dst_key in key_map.items():
            value = time_meta.get(src_key, None)
            if value:
                time_cfg[dst_key] = str(value)
        starts = [pd.to_datetime(value) for value in [time_cfg.get("预热开始"), time_cfg.get("率定开始")] if value]
        ends = [pd.to_datetime(value) for value in [time_cfg.get("验证结束"), time_cfg.get("率定结束")] if value]
        if starts:
            time_cfg["开始年份"] = int(min(starts).year)
        if ends:
            time_cfg["结束年份"] = int(max(ends).year)
        patched["时间"] = time_cfg
        if time_meta.get("time_step_hours", None) is not None:
            patched["时间步长_小时"] = float(time_meta["time_step_hours"])

    resolved_object_type = _resolve_metadata_object_type(metadata)
    if resolved_object_type:
        patched["项目对象"] = resolved_object_type

    objective_meta = dict(metadata.get("objective", {}) or {})
    obs_mode = str(objective_meta.get("obs_mode", "") or "").strip()
    if obs_mode:
        patched["观测口径模式"] = obs_mode
    cfmax_threshold = objective_meta.get("cfmax_zone_threshold_m", None)
    if cfmax_threshold not in (None, ""):
        try:
            patched["CFMAX分区阈值_m"] = float(cfmax_threshold)
        except Exception as exc:
            raise ValueError(f"结果 metadata 中的 cfmax_zone_threshold_m 不是有效数字：{cfmax_threshold}") from exc

    initial_state_override = _metadata_initial_state_override(metadata)
    if initial_state_override is not None:
        init_state = dict(patched.get("初始状态", {}) or {})
        for key, default_value in profile_runner.DEFAULT_INIT_STATE.items():
            init_state.setdefault(key, default_value)
        init_state.update(initial_state_override)
        patched["初始状态"] = init_state

    boundary_meta = dict(metadata.get("boundary_condition", {}) or {})
    optional_modules = dict(metadata.get("optional_modules", {}) or {})
    boundary_module = dict(optional_modules.get("boundary_inflow", {}) or {})
    boundary_file = str(
        boundary_meta.get("boundary_inflow_file")
        or boundary_module.get("file")
        or ""
    ).strip()
    boundary_enabled = _metadata_boundary_enabled(metadata)
    boundary_cfg = dict(patched.get("边界条件", {}) or {})
    boundary_cfg["时间字段"] = str(boundary_meta.get("date_field", boundary_cfg.get("时间字段", "date")) or "date")
    boundary_cfg["流量字段"] = str(boundary_meta.get("flow_field", boundary_cfg.get("流量字段", "inflow_m3s")) or "inflow_m3s")
    gap_fill = boundary_meta.get("gap_fill", boundary_cfg.get("缺失填补", "zero"))
    boundary_cfg["缺失填补"] = str(gap_fill or "zero")
    if boundary_enabled is False:
        boundary_cfg["上游边界入流_csv"] = ""
    elif boundary_file:
        boundary_cfg["上游边界入流_csv"] = boundary_file
    if boundary_cfg:
        patched["边界条件"] = boundary_cfg

    return patched


def _restore_forward_observed_series(module: Any, source_obs_series: dict[str, float | None]) -> bool:
    if not source_obs_series or not hasattr(module, "SIM_DATES") or not hasattr(module, "np"):
        return False
    np_mod = module.np

    restored_values: list[float] = []
    matched = 0
    for item in module.SIM_DATES:
        key = module.format_time_value(item) if hasattr(module, "format_time_value") else str(item)
        value = source_obs_series.get(key, None)
        if value is None:
            restored_values.append(float("nan"))
        else:
            restored_values.append(float(value))
            matched += 1
    restored = np_mod.asarray(restored_values, dtype=np_mod.float64)
    if matched <= 0 or not np_mod.isfinite(restored).any():
        return False

    module.Q_OBS_FULL = restored
    module.Q_OBS_OBJ = restored.copy()
    calib_mask = getattr(module, "CALIB_MASK", None)
    valid_mask = getattr(module, "VALID_MASK", None)
    module.Q_OBS_CALIB = module.Q_OBS_OBJ[calib_mask] if calib_mask is not None else module.Q_OBS_OBJ.copy()
    module.Q_OBS_VALID = module.Q_OBS_OBJ[valid_mask] if valid_mask is not None else np_mod.asarray([], dtype=np_mod.float64)
    if hasattr(module, "OBS_MODE_APPLIED"):
        module.OBS_MODE_APPLIED = "run_replay_fallback"
    return True


def _capture_forward_observation_state(module: Any) -> dict[str, Any]:
    np_mod = getattr(module, "np", None)
    state: dict[str, Any] = {
        "obs_mode_applied": getattr(module, "OBS_MODE_APPLIED", None),
    }
    for name in ("Q_OBS_FULL", "Q_OBS_OBJ", "Q_OBS_CALIB", "Q_OBS_VALID"):
        value = getattr(module, name, None)
        if value is None:
            state[name] = None
        elif np_mod is not None:
            state[name] = np_mod.asarray(value, dtype=np_mod.float64).copy()
        else:
            try:
                state[name] = value.copy()
            except Exception:
                state[name] = value
    return state


def _restore_forward_observation_state(module: Any, state: dict[str, Any] | None) -> None:
    if not isinstance(state, dict):
        return
    np_mod = getattr(module, "np", None)
    for name in ("Q_OBS_FULL", "Q_OBS_OBJ", "Q_OBS_CALIB", "Q_OBS_VALID"):
        value = state.get(name, None)
        if value is None:
            setattr(module, name, None)
        elif np_mod is not None:
            setattr(module, name, np_mod.asarray(value, dtype=np_mod.float64).copy())
        else:
            try:
                setattr(module, name, value.copy())
            except Exception:
                setattr(module, name, value)
    if "obs_mode_applied" in state:
        setattr(module, "OBS_MODE_APPLIED", state.get("obs_mode_applied"))


def _restore_forward_boundary_series(module: Any, sim: dict[str, Any], source_boundary_series: dict[str, float | None]) -> bool:
    if not source_boundary_series or not hasattr(module, "SIM_DATES") or not hasattr(module, "np"):
        return False
    q_total = sim.get("q_total")
    if q_total is None:
        return False
    series_len = len(q_total)
    sim_dates = module.SIM_DATES[:series_len]
    restored_values: list[float] = []
    matched = 0
    for item in sim_dates:
        key = module.format_time_value(item) if hasattr(module, "format_time_value") else str(item)
        if key not in source_boundary_series:
            return False
        value = source_boundary_series.get(key, 0.0)
        restored_values.append(0.0 if value is None else float(value))
        matched += 1
    if matched != series_len:
        return False

    np_mod = module.np
    boundary_routed = np_mod.asarray(restored_values, dtype=np_mod.float64)
    local_source = sim.get("q_local")
    if local_source is None:
        local_source = q_total
    local_routed = np_mod.asarray(local_source, dtype=np_mod.float64)
    if len(local_routed) != series_len:
        local_routed = np_mod.asarray(q_total, dtype=np_mod.float64)
    sim["q_local"] = local_routed.copy()
    sim["q_boundary"] = boundary_routed
    sim["q_total"] = local_routed + boundary_routed
    sim["boundary_enabled"] = True
    sim["boundary_replay_fixed"] = True
    return True


def snapshot_run_paths() -> set[str]:
    return {item["path"] for item in list_runs()}


def _pick_latest_run_path(run_paths: list[str]) -> str:
    def sort_key(value: str) -> tuple[float, str]:
        try:
            path = Path(value)
            return (path.stat().st_mtime, str(path))
        except Exception:
            return (0.0, str(value))

    return max(run_paths, key=sort_key) if run_paths else ""


def _build_calibration_task_result(run_path: str) -> dict[str, Any] | None:
    try:
        run_dir = resolve_any_path(run_path, must_exist=True)
        metadata_path = run_dir / "metadata.json"
        if not metadata_path.exists():
            return None
        metadata, resolved_config = normalize_run_metadata(read_json_file(metadata_path), run_path=run_dir)
        updated_at, updated_at_ns = _run_update_timestamps(run_dir)
        summary = _build_run_summary(
            run_dir,
            metadata,
            resolved_config,
            updated_at=updated_at,
            updated_at_ns=updated_at_ns,
        )
    except Exception:
        return None

    optimization = dict(metadata.get("optimization", {}) or {})
    calibration = dict(metadata.get("metrics", {}).get("calibration", {}) or {})
    validation = dict(metadata.get("metrics", {}).get("validation", {}) or {})
    return {
        "run_path": str(run_dir.resolve()),
        "run_name": str(summary.get("display_name", "") or summary.get("name", "") or run_dir.name),
        "workspace_config": str(metadata.get("workspace_config", "") or ""),
        "calibration_profile": metadata.get("calibration_profile"),
        "requested_objective_mode": metadata.get("requested_objective_mode") or optimization.get("requested_objective_mode"),
        "effective_objective_mode": metadata.get("effective_objective_mode") or optimization.get("effective_objective_mode"),
        "metrics": {
            "nse_cal": calibration.get("nse"),
            "nse_val": validation.get("nse"),
            "kge_cal": calibration.get("kge"),
            "kge_val": validation.get("kge"),
            "pbias_cal": calibration.get("pbias"),
            "pbias_val": validation.get("pbias"),
        },
        "optimization": optimization,
        "studio_compatible": is_studio_editable_metadata(metadata, resolved_config),
    }


def verify_data_prep_step_output(
    step: dict[str, Any],
    config: dict[str, Any],
    runtime_prec_source: Any = None,
) -> tuple[bool, str]:
    check = step.get("check")
    if not callable(check):
        return True, "该步骤没有产物检查函数。"
    try:
        if step.get("needs_prec_source"):
            done, message, _ = check(config, runtime_prec_source)
        else:
            done, message, _ = check(config)
    except Exception as exc:
        return False, f"产物检查异常：{exc}"
    return bool(done), str(message or "")


def verify_data_prep_task_output(metadata: dict[str, Any]) -> tuple[bool, str]:
    config_path_raw = str(metadata.get("config_path", "")).strip()
    step_id = str(metadata.get("step_id", "")).strip()
    if not config_path_raw or not step_id:
        return True, "缺少步骤产物检查上下文。"
    try:
        config_path = resolve_any_path(config_path_raw, must_exist=True)
        config = read_runtime_config(config_path)
        steps = task_step_map(current_profile(config), config)
        step = steps.get(step_id)
        if step is None:
            return True, f"未知步骤 {step_id}，跳过产物复核。"
        runtime_prec_source = profile_runner.resolve_runtime_precip_source(
            config,
            metadata.get("runtime_prec_source", None),
        )
        return verify_data_prep_step_output(step, config, runtime_prec_source)
    except Exception as exc:
        return False, f"产物检查准备失败：{exc}"


def monitor_task(task_id: str, process: subprocess.Popen[Any], previous_runs: set[str]) -> None:
    try:
        if process.stdout is not None:
            for raw_line in process.stdout:
                add_task_output(task_id, _decode_subprocess_output_line(raw_line))
        rc = process.wait()
        task_type = ""
        if rc == 0:
            with TASK_LOCK:
                task = TASKS.get(task_id)
                task_type = task.task_type if task is not None else ""
                task_metadata = dict(task.metadata or {}) if task is not None else {}
            if task_type == "data_prep":
                output_ok, output_message = verify_data_prep_task_output(task_metadata)
                if not output_ok:
                    add_task_output(task_id, f"[失败] 产物检查未通过：{output_message}")
                    rc = 1
        detected_runs = sorted(snapshot_run_paths() - previous_runs) if rc == 0 else []
        calibration_result = None
        latest_run_path = _pick_latest_run_path(detected_runs)
        if rc == 0:
            if task_type == "calibration" and latest_run_path:
                calibration_result = _build_calibration_task_result(latest_run_path)
        with TASK_LOCK:
            task = TASKS[task_id]
            task.return_code = rc
            task.status = "completed" if rc == 0 else "failed"
            progress = dict(task.metadata.get("ui_progress") or {})
            if progress:
                progress["stage"] = "已完成" if rc == 0 else "执行失败"
                if rc == 0 and progress.get("total") is not None:
                    progress["current"] = progress.get("total")
                task.metadata["ui_progress"] = progress
            task.updated_at = time.time()
            task.detected_runs = detected_runs
            if calibration_result is not None:
                task.metadata["result"] = calibration_result
                task.metadata["run_path"] = calibration_result["run_path"]
    except Exception as exc:
        with TASK_LOCK:
            task = TASKS[task_id]
            task.status = "failed"
            task.return_code = -1
            progress = dict(task.metadata.get("ui_progress") or {})
            if progress:
                progress["stage"] = "执行异常"
                task.metadata["ui_progress"] = progress
            task.updated_at = time.time()
            task.append(f"[HBV-Studio] {exc}")


def _subprocess_env() -> dict[str, str]:
    """Return env dict that forces child Python to use UTF-8 I/O and unbuffered output."""
    env = os.environ.copy()
    env["PYTHONIOENCODING"] = "utf-8"
    env["PYTHONUTF8"] = "1"
    env["PYTHONUNBUFFERED"] = "1"
    return env


def _decode_subprocess_output_line(raw_line: Any) -> str:
    if raw_line is None:
        return ""
    if isinstance(raw_line, str):
        return raw_line.rstrip("\r\n")
    data = bytes(raw_line)
    encodings: list[str] = []
    for encoding in ("utf-8-sig", "utf-8", locale.getpreferredencoding(False) or "", "gb18030", "cp936"):
        normalized = str(encoding or "").strip().lower()
        if normalized and normalized not in encodings:
            encodings.append(normalized)
    for encoding in encodings:
        try:
            return data.decode(encoding).rstrip("\r\n")
        except (UnicodeDecodeError, LookupError):
            continue
    return data.decode("utf-8", errors="replace").rstrip("\r\n")


def build_python_script_command(script: Path | str, *args: Any) -> list[str]:
    script_path = str(script)
    tail = [str(arg) for arg in args]
    if getattr(sys, "frozen", False):
        return [PYTHON_EXE, RUN_PY_FILE_ROLE, script_path, *tail]
    return [PYTHON_EXE, script_path, *tail]


def start_process(task_type: str, label: str, command: list[str], cwd: Path, metadata: dict[str, Any] | None = None) -> TaskRecord:
    task_id = uuid.uuid4().hex[:10]
    process = subprocess.Popen(
        command,
        cwd=str(cwd),
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        bufsize=0,
        env=_subprocess_env(),
    )
    record = TaskRecord(id=task_id, task_type=task_type, label=label, command=command, cwd=str(cwd), metadata=metadata or {})
    with TASK_LOCK:
        TASKS[task_id] = record
    threading.Thread(target=monitor_task, args=(task_id, process, snapshot_run_paths()), daemon=True).start()
    return record


def start_self_check() -> TaskRecord:
    return start_process(
        "self_check",
        "系统自检",
        build_python_script_command(SELF_CHECK),
        PROJECT_ROOT,
        metadata={"ui_progress": {"stage": "检查环境与脚本", "label": "系统自检"}},
    )


def step_command(step: dict[str, Any], config_path: Path, payload: dict[str, Any]) -> list[str]:
    command = build_python_script_command(step["script"], "--配置", str(config_path))
    if step.get("needs_prec_source"):
        config = read_runtime_config(config_path)
        runtime_prec_source = profile_runner.resolve_runtime_precip_source(config, payload.get("prec_source", None))
        command.extend([
            "--降水源",
            runtime_prec_source if runtime_prec_source in {"era5", "custom_tif"} else profile_runner.resolve_legacy_precip_source(runtime_prec_source),
        ])
    if step.get("supports_overwrite") and bool(payload.get("overwrite", False)):
        command.append("--覆盖")
    return command


def start_data_prep(payload: dict[str, Any]) -> TaskRecord:
    config_path = resolve_any_path(str(payload.get("config_path", "")), must_exist=True)
    config = read_runtime_config(config_path)
    runtime_prec_source = profile_runner.resolve_runtime_precip_source(config, payload.get("prec_source", None))
    steps = task_step_map(current_profile(config), config)
    step_id = str(payload.get("step_id", "")).strip()
    if step_id not in steps:
        raise ValueError(f"未知的数据准备步骤：{step_id}")
    step = steps[step_id]
    if step.get("manual"):
        raise ValueError("这个步骤是手动导入步骤，不支持直接启动脚本。")
    status_map = {item["id"]: item for item in get_data_prep_status(str(config_path), precip_source=runtime_prec_source)}
    blocked_by = status_map[step_id]["blocked_by"]
    if blocked_by:
        titles = [steps[item]["title"] for item in blocked_by if item in steps]
        raise ValueError(f"步骤前置依赖未完成：{', '.join(titles)}")
    if step_id in FORCING_PIPELINE_STEP_IDS:
        clear_meteo_state(config)
    metadata = {
        "config_path": str(config_path.resolve()),
        "profile": current_profile(config),
        "runtime_prec_source": runtime_prec_source,
        "step_id": step_id,
        "step_title": step["title"],
        "step_titles": [step["title"]],
        "ui_progress": {"stage": "执行脚本", "current": 0, "total": 1, "label": step["title"]},
    }
    return start_process(
        "data_prep",
        f"数据准备 | {step['title']} | {config_path.stem}",
        step_command(step, config_path, payload),
        PROJECT_ROOT,
        metadata=metadata,
    )


def workflow_worker(task_id: str, config_path: Path, step_ids: list[str], payload: dict[str, Any]) -> None:
    from concurrent.futures import ThreadPoolExecutor, as_completed

    config = read_runtime_config(config_path)
    runtime_prec_source = profile_runner.resolve_runtime_precip_source(config, payload.get("prec_source", None))
    steps = task_step_map(current_profile(config), config)
    completed_ids: set[str] = set()
    total_steps = len(step_ids)

    def update_ui_progress(stage: str, label: str = "", current: int | None = None) -> None:
        set_task_metadata(
            task_id,
            ui_progress={
                "stage": stage,
                "current": int(len(completed_ids) if current is None else current),
                "total": int(total_steps),
                "label": label,
            },
        )

    def _run_step(step_id: str) -> tuple[str, bool]:
        step = steps[step_id]
        update_ui_progress("正在执行", step["title"])
        add_task_output(task_id, f"[运行] {step['title']}")
        if step_id in FORCING_PIPELINE_STEP_IDS:
            clear_meteo_state(config, current_profile(config))
        proc = subprocess.Popen(
            step_command(step, config_path, payload),
            cwd=str(PROJECT_ROOT), stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            bufsize=0, env=_subprocess_env(),
        )
        if proc.stdout:
            for raw_line in proc.stdout:
                add_task_output(task_id, _decode_subprocess_output_line(raw_line))
        rc = proc.wait()
        if rc != 0:
            add_task_output(task_id, f"[失败] {step['title']} 返回码 {rc}")
            update_ui_progress("执行失败", step["title"])
            return step_id, False
        output_ok, output_message = verify_data_prep_step_output(step, config, runtime_prec_source)
        if not output_ok:
            add_task_output(task_id, f"[失败] {step['title']} 产物检查未通过：{output_message}")
            update_ui_progress("产物检查失败", step["title"])
            return step_id, False
        add_task_output(task_id, f"[完成] {step['title']}")
        return step_id, True

    try:
        update_ui_progress("准备执行", "等待前置条件")
        remaining = list(step_ids)
        while remaining:
            # Find steps whose dependencies are all completed
            ready = []
            blocked = []
            for sid in remaining:
                step = steps[sid]
                status_map = {item["id"]: item for item in get_data_prep_status(str(config_path), precip_source=runtime_prec_source)}
                if status_map.get(sid, {}).get("done") and not bool(payload.get("overwrite", False)):
                    add_task_output(task_id, f"[跳过] {step['title']} 已完成")
                    completed_ids.add(sid)
                    update_ui_progress("跳过已完成", step["title"])
                    continue
                deps = step.get("depends_on", [])
                unmet = [d for d in deps if d not in completed_ids]
                if unmet:
                    blocked.append(sid)
                elif step.get("manual"):
                    add_task_output(task_id, f"[跳过] {step['title']} (手动步骤)")
                    completed_ids.add(sid)
                    update_ui_progress("跳过手动步骤", step["title"])
                else:
                    ready.append(sid)

            remaining = [s for s in remaining if s not in completed_ids]
            if not ready:
                if blocked:
                    titles = [steps[s]["title"] for s in blocked]
                    add_task_output(task_id, f"[阻塞] 以下步骤依赖未完成：{', '.join(titles)}")
                    update_ui_progress("依赖未满足", "、".join(titles))
                break

            # Run ready steps in parallel
            if len(ready) > 1:
                add_task_output(task_id, f"[并行] 同时执行 {len(ready)} 个步骤")
                update_ui_progress("并行执行", f"{len(ready)} 个步骤")
            with ThreadPoolExecutor(max_workers=min(len(ready), 4)) as pool:
                futures = {pool.submit(_run_step, sid): sid for sid in ready}
                for future in as_completed(futures):
                    sid, ok = future.result()
                    if ok:
                        completed_ids.add(sid)
                        update_ui_progress("已完成阶段", steps[sid]["title"])
                    else:
                        with TASK_LOCK:
                            t = TASKS[task_id]
                            t.status = "failed"
                            t.return_code = 1
                            t.updated_at = time.time()
                        return
            remaining = [s for s in remaining if s not in completed_ids]

        with TASK_LOCK:
            t = TASKS[task_id]
            t.status = "completed"
            t.return_code = 0
            t.updated_at = time.time()
        update_ui_progress("全部完成", "所有步骤已完成", total_steps)
    except Exception as exc:
        add_task_output(task_id, f"[HBV-Studio] {exc}")
        with TASK_LOCK:
            t = TASKS[task_id]
            t.status = "failed"
            t.return_code = -1
            t.updated_at = time.time()
        update_ui_progress("执行异常", str(exc))


def start_bootstrap(payload: dict[str, Any]) -> TaskRecord:
    config_path = resolve_any_path(str(payload.get("config_path", "")), must_exist=True)
    config = read_runtime_config(config_path)
    step_ids = ["clip_dem", "flow_acc", "masked_flow", "elevation_zone"]
    if str(config.get("冰川边界_shp", "")).strip():
        step_ids.append("glacier_mask")
    if glacier_elev_required(config):
        step_ids.append("glacier_elev")
    task_id = uuid.uuid4().hex[:10]
    steps = task_step_map(current_profile(config), config)
    record = TaskRecord(
        id=task_id,
        task_type="bootstrap",
        label=f"基础地理数据生成 | {config_path.stem}",
        command=["bootstrap"],
        cwd=str(PROJECT_ROOT),
        metadata={
            "config_path": str(config_path.resolve()),
            "profile": current_profile(config),
            "step_titles": [steps[item]["title"] for item in step_ids if item in steps],
            "ui_progress": {"stage": "准备执行", "current": 0, "total": len(step_ids), "label": "等待前置条件"},
        },
    )
    with TASK_LOCK:
        TASKS[task_id] = record
    threading.Thread(target=workflow_worker, args=(task_id, config_path, step_ids, payload), daemon=True).start()
    return record


def start_calibration(payload: dict[str, Any]) -> TaskRecord:
    config_path = resolve_any_path(str(payload.get("config_path", "")), must_exist=True)
    config = read_runtime_config(config_path)
    profile = str(payload.get("calibration_mode", "")).strip().lower() or current_profile(config)
    runtime_prec_source = profile_runner.resolve_runtime_precip_source(config, payload.get("prec_source", None))
    quick_test = bool(payload.get("quick_test", False))
    validation_stage = "quick_test" if quick_test else "calibration"
    validation = validate_workspace_fields(str(config_path), stage=validation_stage, precip_source=runtime_prec_source)
    if not validation["valid"]:
        task_label = "输入预核算" if quick_test else "率定"
        raise ValueError(f"输入检查未通过，无法启动{task_label}：\n- " + "\n- ".join(validation["missing"][:8]))
    if not quick_test:
        obs_path = _config_text_value(config, OBSERVED_FLOW_KEY)
        if not obs_path:
            raise ValueError(f"输入检查未通过，无法启动率定：\n- {OBSERVED_FLOW_KEY}")
        obs_file = _resolve_config_related_path(config, obs_path)
        if obs_file is None or not obs_file.exists():
            raise ValueError(f"输入检查未通过，无法启动率定：\n- 观测径流文件不存在：{obs_path}")
    paths = build_profile_paths(config, profile)
    maxiter = int(payload.get("maxiter", 24))
    workers = int(payload.get("workers", 4))
    legacy_prec_source = profile_runner.resolve_legacy_precip_source(runtime_prec_source)
    glacier_requirements = glacier_formal_requirements(config, profile)
    objective_mode = profile_runner.resolve_objective_mode(config, payload.get("objective_mode", None), profile)
    param_bounds_profile = profile_runner.resolve_param_bounds_profile(
        config,
        payload.get("param_bounds_profile", None),
        profile,
    )
    calibration_workflow = profile_runner.resolve_calibration_workflow(
        config,
        payload.get("calibration_workflow", None),
        profile,
    )
    calibration_workflow_status = profile_runner.calibration_workflow_status(calibration_workflow)
    method = str(payload.get("method", "de")).strip().lower() or "de"
    if method not in CALIBRATION_METHODS:
        raise ValueError(f"未知率定方法：{method}")
    mc_samples = int(payload.get("mc_samples", 300))
    init_bound_shrink = max(0.0, float(payload.get("init_bound_shrink", 0.0) or 0.0))
    debug_days = max(0, int(payload.get("debug_days", 0) or 0))
    if quick_test:
        debug_days = 0
    refine_enabled_payload = bool(payload.get("refine_enabled", False))
    refine_maxiter_payload = max(0, int(payload.get("refine_maxiter", 0) or 0))
    if quick_test or method not in {"de", "mc_screen_de"}:
        refine_cli_value = 0
        refine_metadata_value = 0
    elif refine_enabled_payload and refine_maxiter_payload > 0:
        refine_cli_value = refine_maxiter_payload
        refine_metadata_value = refine_maxiter_payload
    elif refine_enabled_payload:
        refine_cli_value = -1
        refine_metadata_value = min(20, max(6, int(round(maxiter * 0.25))))
    else:
        refine_cli_value = 0
        refine_metadata_value = 0
    init_params_file = ""
    preset_id = str(payload.get("init_preset_id", "")).strip()
    if preset_id:
        preset = find_manual_preset(str(config_path), preset_id)
        preset_profile = str(preset.get("calibration_profile", "")).strip().lower()
        if preset_profile and preset_profile != profile:
            raise ValueError(
                f"所选手调参数集属于 {PROFILE_LABELS.get(preset_profile, preset_profile)}，"
                f"与当前率定模式 {PROFILE_LABELS.get(profile, profile)} 不一致。"
            )
        paths["cache_dir"].mkdir(parents=True, exist_ok=True)
        init_file = Path(paths["cache_dir"]) / f"init_params_{preset_id}.json"
        preset_params = dict(preset.get("params", {}))
        cli_args = _build_forward_runtime_cli_args(
            config_path,
            profile,
            prec_source=runtime_prec_source,
            glacier_mode=str(payload.get("glacier_mode", "inline")).strip().lower() or "inline",
            objective_mode=objective_mode,
        )
        module = profile_runner.load_legacy_module(profile_runner.old_script_path(config, "model", "calibrate_hbv_cryo.py"))
        profile_runner.patch_runtime_environment(module, config, profile, cli_args)
        profile_runner.patch_profile_behavior(module, config, profile, objective_mode, param_bounds_profile)
        configure_time_step = getattr(module, "configure_time_step", None)
        if callable(configure_time_step):
            configure_time_step()
        _, complete_params, _ = build_runtime_param_vector(module, preset_params)
        init_file.write_text(json.dumps(complete_params, ensure_ascii=False, indent=2), encoding="utf-8")
        init_params_file = str(init_file)
    command = build_python_script_command(
        MODEL_RUNNER,
        "--配置", str(config_path),
        "--率定模式", profile,
        "--method", method,
        "--workers", str(workers),
        "--maxiter", str(maxiter),
        "--popsize", str(int(payload.get("popsize", 6))),
        "--seed", str(int(payload.get("seed", 42))),
        "--mc-samples", str(mc_samples),
        "--目标函数", objective_mode,
        "--calibration-workflow", calibration_workflow,
        "--冰川模式", str(payload.get("glacier_mode", "inline")),
    )
    if profile == PROFILE_DAILY:
        command.extend(["--param-bounds-profile", param_bounds_profile])
    if runtime_prec_source == "custom_tif":
        command.extend(["--降水源", "custom_tif", "--prec-dir", str(paths["aligned_prec_custom_dir"])])
    elif runtime_prec_source == "era5":
        command.extend(["--降水源", "era5"])
    else:
        command.extend(["--降水源", legacy_prec_source])
    if init_params_file:
        command.extend(["--init-params-file", init_params_file, "--init-bound-shrink", str(init_bound_shrink)])
    if debug_days > 0:
        command.extend(["--debug-days", str(debug_days)])
    if refine_cli_value != -1:
        command.extend(["--refine-maxiter", str(refine_cli_value)])
    if quick_test:
        command.extend(["--quick-test", "--quick-days", str(int(payload.get("quick_days", 30)))])
    task_name = "输入预核算" if quick_test else ("快速试算" if debug_days > 0 else "率定任务")
    label = f"{task_name} | {config_path.stem} | {PROFILE_LABELS.get(profile, profile)}"
    metadata = {
        "config_path": str(config_path),
        "logs_dir": str(paths["logs_dir"]),
        "profile": profile,
        "objective_mode": objective_mode,
        "param_bounds_profile": param_bounds_profile,
        "param_bounds_profile_label": profile_runner.PARAM_BOUNDS_PROFILE_LABELS.get(
            param_bounds_profile,
            param_bounds_profile,
        ),
        "calibration_workflow": calibration_workflow,
        "calibration_workflow_status": calibration_workflow_status,
        "method": method,
        "maxiter": maxiter,
        "mc_samples": mc_samples,
        "debug_days": debug_days,
        "init_preset_id": preset_id,
        "init_bound_shrink": init_bound_shrink,
        "runtime_prec_source": runtime_prec_source,
        "refine_enabled": refine_enabled_payload and refine_metadata_value > 0,
        "refine_maxiter": refine_metadata_value,
        "quick_test": quick_test,
        "ui_progress": {
            "stage": "启动率定任务",
            "label": "正在加载模型、驱动和目标函数",
        },
    }
    return start_process("calibration", label, command, PROJECT_ROOT, metadata=metadata)


def start_tuotuohe_sync(payload: dict[str, Any]) -> TaskRecord:
    source_root = str(payload.get("source_root", "")).strip()
    if not source_root:
        env_source = str(os.environ.get("HBV_TUOTUOHE_SOURCE_ROOT", "")).strip()
        if env_source and Path(env_source).exists():
            source_root = env_source
        else:
            for drive in list_drives():
                candidate = Path(drive) / "Hapi" / "data"
                if candidate.exists():
                    source_root = str(candidate.resolve(strict=False))
                    break
    if not source_root:
        raise ValueError("未找到历史数据源目录。请将旧目录放在任一盘符的 Hapi\\data 下，或显式传入 source_root。")
    target_root = str(payload.get("target_root", PROJECT_RUNTIME_DIR / "沱沱河" / "数据"))
    command = build_python_script_command(TUOTUOHE_SYNC_SCRIPT, "--source", source_root, "--target", target_root)
    if bool(payload.get("include_raw", False)):
        command.append("--include-raw")
    return start_process("sync", "同步沱沱河模板数据", command, GUI_ROOT)


def list_drives() -> list[str]:
    if os.name != "nt":
        return ["/"]
    drives = []
    for letter in string.ascii_uppercase:
        drive = f"{letter}:\\"
        if Path(drive).exists():
            drives.append(drive)
    return drives


WINDOWS_HIDDEN_DIRS = frozenset({
    "system volume information", "$recycle.bin", "$winrepackage",
    "recovery", "config.msi", "msocache", "$sysreset",
})


def _safe_iterdir(directory: Path) -> list[Path]:
    """Iterate a directory, skipping entries that raise PermissionError individually."""
    results: list[Path] = []
    try:
        scanner = os.scandir(str(directory))
    except (PermissionError, OSError):
        return results
    try:
        while True:
            try:
                entry = next(scanner)
            except StopIteration:
                break
            except (PermissionError, OSError):
                # Windows can raise per-entry errors (e.g. System Volume Information)
                continue
            results.append(Path(entry.path))
    finally:
        scanner.close()
    return results


def list_filesystem(path_value, extensions=None, kind: str = "file"):
    normalized_exts = {item.lower() for item in (extensions or []) if item}
    browse_kind = str(kind or "file").strip().lower() or "file"
    preview_only = browse_kind == "dir"
    file_limit = DIR_BROWSER_FILE_PREVIEW_ITEMS if preview_only else MAX_BROWSER_FILE_ITEMS
    if not path_value:
        return {
            "current_path": "",
            "parent_path": None,
            "roots": list_drives(),
            "directories": [],
            "files": [],
            "kind": browse_kind,
            "file_count": 0,
            "shown_file_count": 0,
            "files_truncated": False,
        }
    current = resolve_any_path(path_value, must_exist=False)
    try:
        if current.is_file():
            current = current.parent
    except (PermissionError, OSError):
        current = current.parent
    try:
        exists = current.exists()
    except (PermissionError, OSError):
        exists = False
    if not exists:
        current = current.parent
    try:
        exists = current.exists()
    except (PermissionError, OSError):
        exists = False
    if not exists:
        raise FileNotFoundError(str(current))
    directories = []
    files = []
    raw_children = _safe_iterdir(current)

    # Filter out system/hidden dirs BEFORE sorting to avoid stat calls on them
    def _is_system_entry(item: Path) -> bool:
        try:
            n = item.name.lower()
            return n in WINDOWS_HIDDEN_DIRS or n.startswith("$") or n.startswith(".")
        except Exception:
            return True

    raw_children = [child for child in raw_children if not _is_system_entry(child)]

    def _sort_key(item: Path):
        try:
            return (not item.is_dir(), item.name.lower())
        except (PermissionError, OSError):
            return (True, item.name.lower())

    file_count = 0
    for child in sorted(raw_children, key=_sort_key):
        try:
            if child.is_dir():
                directories.append({"name": child.name, "path": str(child)})
            else:
                if normalized_exts and child.suffix.lower() not in normalized_exts:
                    continue
                file_count += 1
                if len(files) >= file_limit:
                    continue
                files.append({"name": child.name, "path": str(child), "suffix": child.suffix.lower()})
        except (PermissionError, OSError):
            continue
    return {
        "current_path": str(current),
        "parent_path": str(current.parent) if current.parent != current else None,
        "roots": list_drives(),
        "directories": directories,
        "files": files,
        "kind": browse_kind,
        "file_count": file_count,
        "shown_file_count": len(files),
        "files_truncated": file_count > len(files),
    }


def _is_within_root(candidate: Path, root: Path) -> bool:
    try:
        candidate.resolve(strict=False).relative_to(root.resolve(strict=False))
        return True
    except ValueError:
        return False


def open_path_in_explorer(payload: dict[str, Any]) -> dict[str, Any]:
    raw_path = str(payload.get("path", "")).strip()
    if not raw_path:
        raise ValueError("缺少路径。")
    target = resolve_any_path(raw_path, must_exist=True)
    allowed_roots = [WORKSPACE_DIR, PROJECT_RUNTIME_DIR, PROJECT_ROOT, PROJECT_ROOT.parent]
    if not any(_is_within_root(target, root) for root in allowed_roots):
        raise ValueError(f"该路径不在允许打开的工程目录范围内：{target}")
    if os.name == "nt":
        if target.is_file():
            subprocess.Popen(["explorer.exe", f"/select,{str(target)}"])
        else:
            subprocess.Popen(["explorer.exe", str(target)])
    elif sys.platform == "darwin":
        subprocess.Popen(["open", str(target)])
    else:
        subprocess.Popen(["xdg-open", str(target)])
    return {"opened": True, "path": str(target.resolve(strict=False))}


def dashboard_payload() -> dict[str, Any]:
    templates = list_templates()
    workspaces = list_workspaces()
    runs = list_runs()
    tasks = list_tasks()
    return {
        "project": {
            "project_root": str(PROJECT_ROOT),
            "gui_root": str(GUI_ROOT),
            "builtin_dem": str(BUILTIN_DEM.resolve()),
            "builtin_dems": {
                "1km": str(BUILTIN_DEM_1KM.resolve()),
                "0p1deg": str(BUILTIN_DEM_0P1.resolve()),
            },
            "runtime_root": str(PROJECT_RUNTIME_DIR.resolve()),
        },
        "counts": {
            "templates": len(templates),
            "workspaces": len(workspaces),
            "runs": len(runs),
            "tasks": len(tasks),
        },
        "templates": templates,
        "workspaces": workspaces,
        "runs": runs,
        "tasks": tasks,
    }


def cdsapi_status() -> dict[str, Any]:
    home_dir = Path.home().resolve(strict=False)
    config_path = (home_dir / ".cdsapirc").resolve(strict=False)
    exists = config_path.exists() and config_path.is_file()
    looks_valid = False
    readable = False
    if exists:
        try:
            text = config_path.read_text(encoding="utf-8", errors="ignore")
            lower = text.lower()
            readable = True
            looks_valid = ("url:" in lower) and ("key:" in lower)
        except Exception:
            readable = False
    return {
        "exists": bool(exists),
        "readable": bool(readable),
        "looks_valid": bool(looks_valid),
        "path": str(config_path),
        "home_dir": str(home_dir),
    }


# ---------------------------------------------------------------------------
#  Wizard API helpers
# ---------------------------------------------------------------------------

WIZARD_STEP_KEYS: dict[int, list[str]] = {
    1: ["项目对象", "率定模式", "流域名称", "流域编号", "运行目录", "时间步长_小时"],
    2: ["流域边界_shp", OBSERVED_FLOW_KEY, "DEM_tif", "冰川边界_shp", "时间", "任务时段模式", "事件资料模式", "洪水事件率定", "CFMAX分区阈值_m", "FAO56平均海拔_m"],
    3: ["边界条件"],
    4: ["气象策略", "默认降水源"],
}


def wizard_save_step(payload: dict[str, Any]) -> dict[str, Any]:
    """Merge one wizard step's data into the workspace config."""
    workspace_path = str(payload.get("workspace_path", "")).strip()
    step = int(payload.get("step", 0))
    step_data = payload.get("data", {})
    if not workspace_path:
        raise ValueError("缺少 workspace_path。")
    path = resolve_any_path(workspace_path, must_exist=False)
    if path.exists():
        config = read_json_file(path)
    else:
        name = step_data.get("name", step_data.get("流域名称", path.stem))
        config = build_empty_workspace(name)

    # Map frontend step data to config structure
    if step == 1:
        if step_data.get("name"):
            config["流域名称"] = step_data["name"]
            config["流域编号"] = slugify_workspace_name(step_data["name"])
            if not config.get("运行目录") or config["运行目录"] == str(runtime_root_for_workspace("新流域")):
                config["运行目录"] = str(runtime_root_for_workspace(step_data["name"]))
        if step_data.get("timescale"):
            config["率定模式"] = step_data["timescale"]
            config["时间步长_小时"] = 1.0 if step_data["timescale"] == "hourly" else 24.0
        if step_data.get("object"):
            config["项目对象"] = step_data["object"]
    elif step == 2:
        if step_data.get("basin_shp"):
            config["流域边界_shp"] = str(
                stage_vector_shapefile(config, step_data["basin_shp"], role="basin", config_path=path)
            )
        if step_data.get("obs_csv"):
            config[OBSERVED_FLOW_KEY] = str(stage_observed_runoff_file(config, step_data["obs_csv"], config_path=path))
        if step_data.get("dem_tif"):
            config["DEM_tif"] = step_data["dem_tif"]
        if "glacier_shp" in step_data:
            glacier_shp = str(step_data.get("glacier_shp", "")).strip()
            if glacier_shp:
                config["冰川边界_shp"] = str(
                    stage_vector_shapefile(config, glacier_shp, role="glacier", config_path=path)
                )
            elif (not str(config.get("冰川边界_shp", "")).strip()) and BUILTIN_GLACIER_SHP.exists():
                config["冰川边界_shp"] = str(
                    stage_vector_shapefile(config, BUILTIN_GLACIER_SHP, role="glacier", config_path=path)
                )
        raw_time_basis = str(step_data.get("time_basis", step_data.get("任务时段模式", "")) or "").strip().lower()
        time_basis = (
            TIME_BASIS_EVENT_WINDOWS
            if raw_time_basis in {"event", "events", "event_window", "event_windows", "flood_event", "洪水事件", "事件窗口", "事件资料"}
            else TIME_BASIS_CONTINUOUS
        )
        config["任务时段模式"] = time_basis
        event_file = str(step_data.get("event_file", step_data.get("事件表路径", "")) or "").strip()
        event_mode = dict(config.get("事件资料模式", {}) or {})
        flood_events = dict(config.get("洪水事件率定", {}) or {}) if isinstance(config.get("洪水事件率定", {}), dict) else {}
        if event_file:
            event_mode["事件表路径"] = event_file
            flood_events["事件表路径"] = event_file
        if time_basis == TIME_BASIS_EVENT_WINDOWS:
            event_mode.update(
                {
                    "启用": True,
                    "事件窗口资料": True,
                    "允许事件间断": True,
                    "初始条件策略": event_mode.get("初始条件策略", "event_warmup") or "event_warmup",
                }
            )
            flood_events["启用"] = True
            flood_events["事件窗口资料"] = True
            flood_events.setdefault("模式", "diagnostic")
        else:
            event_mode["启用"] = False
            event_mode["事件窗口资料"] = False
            if "启用" not in flood_events:
                flood_events["启用"] = False
            flood_events["事件窗口资料"] = False
        config["事件资料模式"] = event_mode
        config["洪水事件率定"] = flood_events
        time_map = {
            "warmup_start": "预热开始", "warmup_end": "预热结束",
            "calib_start": "率定开始", "calib_end": "率定结束",
            "valid_start": "验证开始", "valid_end": "验证结束",
        }
        time_cfg = dict(config.get("时间", {}))
        for en_key, cn_key in time_map.items():
            if step_data.get(en_key):
                time_cfg[cn_key] = step_data[en_key]
        config["时间"] = time_cfg
        if step_data.get("cfmax"):
            config["CFMAX分区阈值_m"] = float(step_data["cfmax"])
        if step_data.get("fao_elev"):
            config["FAO56平均海拔_m"] = float(step_data["fao_elev"])
    elif step == 3:
        boundary = dict(config.get("边界条件", {}))
        if step_data.get("boundary_csv"):
            boundary["上游边界入流_csv"] = step_data["boundary_csv"]
        if step_data.get("gap_fill"):
            boundary["缺失填补"] = step_data["gap_fill"]
        date_field = step_data.get("date_field", step_data.get("boundary_date"))
        flow_field = step_data.get("flow_field", step_data.get("boundary_flow"))
        if date_field:
            boundary["时间字段"] = date_field
        if flow_field:
            boundary["流量字段"] = flow_field
        config["边界条件"] = boundary
    else:
        # Steps 4+ send Chinese keys directly — generic merge
        for key, value in step_data.items():
            if isinstance(value, dict) and isinstance(config.get(key), dict):
                config[key] = {**config[key], **value}
            else:
                config[key] = value

    config = normalize_config_before_save(config, path)
    write_json_file(path, config)

    resolved_config = read_runtime_config(path)
    seed_workspace_runtime_dirs(resolved_config)

    validation = wizard_validate_step(str(path.resolve()), step)
    return {"config": read_json_file(path), "path": str(path.resolve()), "validation": validation}


def wizard_validate_step(config_path_raw: str, step: int, precip_source: Any = None) -> dict[str, Any]:
    """Validate only the fields relevant to a single wizard step."""
    missing: list[str] = []
    warnings: list[str] = []
    try:
        cfg_path = resolve_any_path(config_path_raw, must_exist=True)
        config = read_runtime_config(cfg_path)
    except Exception as exc:
        return {"step": step, "valid": False, "missing": [str(exc)], "warnings": []}
    runtime_prec_source = resolve_precip_source(config, precip_source)
    event_windows: dict[str, Any] | None = None

    if step == 1:
        if not config.get("流域名称"):
            missing.append("流域名称")
        if not config.get("运行目录"):
            missing.append("运行目录")
    elif step == 2:
        if not config.get("流域边界_shp"):
            missing.append("流域边界 shp")
        else:
            basin_path = _resolve_config_related_path(config, config.get("流域边界_shp"))
            if basin_path is None or not basin_path.exists():
                missing.append(f"流域边界 shp 文件不存在：{config['流域边界_shp']}")
        if not config.get(OBSERVED_FLOW_KEY):
            missing.append("观测径流文件")
        else:
            obs_file = _resolve_config_related_path(config, config.get(OBSERVED_FLOW_KEY))
            if obs_file is None or not obs_file.exists():
                missing.append(f"观测径流文件不存在：{config[OBSERVED_FLOW_KEY]}")
        step_hours = normalize_time_step_hours(config.get("时间步长_小时", 24.0))
        time_basis = task_time_basis(config, context="calibration")
        if time_basis == TIME_BASIS_EVENT_WINDOWS:
            event_info = normalized_flood_events(config, step_hours=step_hours)
            event_windows = event_windows_ui_summary(event_info, step_hours)
            for item in list(event_info.get("errors", []) or []):
                missing.append(str(item))
            for item in list(event_info.get("warnings", []) or []):
                warnings.append(str(item))
            if not event_info.get("valid_event_count"):
                missing.append("洪水事件窗口模式需要至少一场合法事件。")
            else:
                counts = dict(event_info.get("purpose_counts", {}) or {})
                warnings.append(
                    "当前按洪水事件窗口组织资料："
                    f"{int(event_info.get('valid_event_count', 0) or 0)} 场有效，"
                    f"率定 {int(counts.get('calibration', 0) or 0)}、"
                    f"验证 {int(counts.get('validation', 0) or 0)}、"
                    f"诊断 {int(counts.get('diagnostic', 0) or 0)}。"
                )
        else:
            time_cfg = config.get("时间", {})
            for key in ("预热开始", "率定开始", "率定结束", "验证结束"):
                if not time_cfg.get(key):
                    missing.append(f"时间.{key}")
            time_values: dict[str, pd.Timestamp] = {}
            for key in ("预热开始", "预热结束", "率定开始", "率定结束", "验证开始", "验证结束"):
                value = time_cfg.get(key)
                if not value:
                    continue
                try:
                    time_values[key] = pd.to_datetime(value)
                except Exception:
                    missing.append(f"时间.{key} 无法解析：{value}")
            missing.extend(time_sequence_messages(time_values, step_hours))
        obs_path = str(config.get(OBSERVED_FLOW_KEY, "")).strip()
        obs_file = _resolve_config_related_path(config, obs_path)
        if obs_path and obs_file is not None and obs_file.exists():
            try:
                obs_info = inspect_observed_csv(
                    str(obs_file),
                    expected_index=build_expected_observation_index(config, context="calibration"),
                    target_step_hours=normalize_time_step_hours(config.get("时间步长_小时", 24.0)),
                )
                obs_missing, obs_warnings = observed_window_messages(config, obs_info)
                missing.extend(obs_missing)
                warnings.extend(obs_warnings)
            except Exception as exc:
                warnings.append(f"观测径流检查失败：{exc}")
    elif step == 3:
        object_type = detect_object_type(config)
        if object_type == OBJECT_INTERBASIN:
            boundary = dict(config.get("边界条件", {}))
            csv_path = str(boundary.get("上游边界入流_csv", "")).strip()
            if not csv_path:
                missing.append("上游边界入流 csv")
            else:
                boundary_file = _resolve_config_related_path(config, csv_path)
                if boundary_file is None or not boundary_file.exists():
                    missing.append(f"上游边界入流文件不存在：{csv_path}")
                    boundary_file = None
                if boundary_file is None:
                    return {"step": step, "valid": False, "missing": missing, "warnings": warnings}
                try:
                    step_hours = normalize_time_step_hours(config.get("时间步长_小时", 24.0))
                    boundary_info = inspect_boundary_inflow_csv(
                        str(boundary_file),
                        date_field=str(boundary.get("时间字段", "date")).strip() or "date",
                        flow_field=str(boundary.get("流量字段", "inflow_m3s")).strip() or "inflow_m3s",
                        expected_index=build_expected_forcing_index(config, context="calibration"),
                        expected_step_hours=step_hours,
                    )
                    boundary_missing, boundary_warnings = boundary_info_messages(
                        boundary_info,
                        step_hours,
                        gap_fill=str(boundary.get("缺失填补", "zero")),
                    )
                    missing.extend(boundary_missing)
                    warnings.extend(boundary_warnings)
                except Exception as exc:
                    missing.append(f"上游边界入流检查失败：{exc}")
        else:
            boundary_csv = str(dict(config.get("边界条件", {})).get("上游边界入流_csv", "")).strip()
            if boundary_csv:
                warnings.append("当前项目不是区间流域，但配置了上游边界入流；请确认对象类型是否正确。")
    elif step == 4:
        step_missing, step_warnings = wizard_step4_meteo_validation(config)
        missing.extend(step_missing)
        warnings.extend(step_warnings)
    elif step == 5:
        gis_checks = [
            ("DEM 裁剪", check_clip_dem(config)),
            ("流向与流量累积", check_flow_acc(config)),
            ("汇流与流域掩膜", check_masked_flow(config)),
            ("高程分区", check_elevation_zone(config)),
        ]
        for label, (done, message, _) in gis_checks:
            if not done:
                missing.append(f"{label}未完成：{message}")
    elif step == 6:
        active_meteo_import = find_running_task("meteo_import", str(cfg_path))
        if active_meteo_import is not None:
            progress = dict(active_meteo_import.metadata.get("ui_progress") or {})
            stage_label = str(progress.get("stage", "气象栅格导入")).strip() or "气象栅格导入"
            current = int(progress.get("current", 0) or 0)
            total = int(progress.get("total", 0) or 0)
            suffix = f" 当前进度 {current}/{total}。" if total > 0 else "。"
            missing.append(f"{stage_label}仍在进行，请等待完成后再检查第 6 步。{suffix}")
            return {"step": step, "valid": False, "missing": missing, "warnings": warnings}
        forcing = validate_forcing_bundle(config, current_profile(config), precip_source=runtime_prec_source)
        if runtime_prec_source == "custom_tif" and (not forcing["ok"]) and (not read_meteo_state(config, current_profile(config))):
            warnings.append("当前为本地栅格降水模式；如尚未完成气象栅格导入，请优先使用本步“验证并导入”。")
        missing.extend(forcing["errors"])
        warnings.extend(forcing["warnings"])
    elif step == 7:
        validation = validate_workspace_fields(str(cfg_path), stage="calibration", precip_source=runtime_prec_source)
        missing.extend(validation["missing"])
        warnings.extend(validation["warnings"])

    result = {"step": step, "valid": len(missing) == 0, "missing": missing, "warnings": warnings}
    if event_windows is not None:
        result["event_windows"] = event_windows
    return result


def boundary_preview(
    csv_path_raw: str,
    date_field: str = "date",
    flow_field: str = "inflow_m3s",
    *,
    config_path_raw: str = "",
    expected_start: str = "",
    expected_end: str = "",
    expected_step_hours: float | None = None,
) -> dict[str, Any]:
    """Preview the first rows and stats of a boundary inflow CSV."""
    expected_index = None
    expected_step = expected_step_hours
    if config_path_raw:
        cfg_path = resolve_any_path(config_path_raw, must_exist=True)
        config = read_runtime_config(cfg_path)
        expected_index = build_expected_time_index(config)
        expected_step = normalize_time_step_hours(config.get("时间步长_小时", 24.0))
    elif expected_start and expected_end and expected_step_hours is not None:
        try:
            step = pd.Timedelta(hours=float(expected_step_hours))
            end_ts = pd.to_datetime(expected_end)
            if float(expected_step_hours) < 24.0 and is_date_only_string(expected_end):
                end_ts = end_ts + pd.Timedelta(days=1) - step
            expected_index = pd.date_range(
                start=pd.to_datetime(expected_start),
                end=end_ts,
                freq=step,
            )
            expected_step = normalize_time_step_hours(expected_step_hours)
        except Exception:
            expected_index = None
    data = inspect_boundary_inflow_csv(
        csv_path_raw,
        date_field=date_field,
        flow_field=flow_field,
        expected_index=expected_index,
        expected_step_hours=expected_step,
    )
    return {
        "columns": data["columns"],
        "total_rows": data["total_rows"],
        "valid_rows": data["valid_rows"],
        "invalid_rows": data["invalid_rows"],
        "duplicate_count": data["duplicate_count"],
        "time_step_hours": data["time_step_hours"],
        "expected_time_step_hours": data["expected_time_step_hours"],
        "suggested_calibration_mode": data.get("suggested_calibration_mode"),
        "negative_count": data["negative_count"],
        "zero_count": data["zero_count"],
        "coverage_ratio": data.get("coverage_ratio"),
        "expected_steps": data.get("expected_steps"),
        "missing_count": len(data.get("missing_steps", [])),
        "out_of_range_count": len(data.get("out_of_range_steps", [])),
        "date_range": data["date_range"],
        "flow_stats": data["flow_stats"],
        "preview": data["preview"],
    }


def quick_workspace_completeness(config_path_raw: str, precip_source: Any = None) -> dict[str, Any]:
    """Return a lightweight workflow summary for dashboards and lists."""
    try:
        cfg_path = resolve_any_path(config_path_raw, must_exist=True)
        config = read_runtime_config(cfg_path)
    except Exception:
        return {"steps_completed": [], "steps_remaining": [1, 2, 3, 4, 5, 6, 7], "ready_for_calibration": False}

    runtime_prec_source = resolve_precip_source(config, precip_source)
    object_type = detect_object_type(config)
    all_steps = [1, 2, 3, 4, 5, 6, 7] if object_type == OBJECT_INTERBASIN else [1, 2, 4, 5, 6, 7]
    completed: list[int] = []
    for step in [s for s in all_steps if s in {1, 2, 3, 4}]:
        result = wizard_validate_step(str(cfg_path), step, precip_source=runtime_prec_source)
        if result["valid"]:
            completed.append(step)

    profile = current_profile(config)
    paths = build_profile_paths(config, profile)
    gis_dir = Path(paths["gis_dir"])
    dem_ready = _workspace_dem_path(gis_dir, prefer=_configured_dem_kind(config)).exists()
    flow_ready = (gis_dir / "flow_accumulation_masked.tif").exists()
    zone_low_ready = (gis_dir / "elevation_zone_low.tif").exists() or (gis_dir / "elevation_zone_mid.tif").exists()
    zone_high_ready = (gis_dir / "elevation_zone_high.tif").exists()
    if dem_ready and flow_ready and zone_low_ready and zone_high_ready:
        completed.append(5)

    _, precip_dir, _ = effective_precip_paths(config, profile, precip_source=runtime_prec_source)
    temp_dir = Path(paths["aligned_temp_dir"])
    evap_dir = Path(paths["aligned_evap_dir"])
    if has_matching(Path(precip_dir)) and has_matching(temp_dir) and has_matching(evap_dir):
        completed.append(6)

    completed = sorted(set(completed))
    remaining = [s for s in all_steps if s not in completed]
    pending_validation = 7 in all_steps and set(all_steps) - {7} <= set(completed)
    ready = False
    validation_missing: list[str] = []
    validation_warnings: list[str] = []
    next_step: int | None = remaining[0] if remaining else None
    if pending_validation:
        calib_validation = validate_workspace_fields(str(cfg_path), stage="calibration", precip_source=runtime_prec_source)
        ready = bool(calib_validation["valid"])
        validation_missing = list(calib_validation.get("missing", []))
        validation_warnings = list(calib_validation.get("warnings", []))
        if ready:
            completed.append(7)
            completed = sorted(set(completed))
            remaining = [s for s in all_steps if s not in completed]
            pending_validation = False
            next_step = None
        else:
            next_step = 7

    return {
        "steps_completed": completed,
        "steps_remaining": sorted(remaining),
        "all_steps": all_steps,
        "completed_count": len(completed),
        "total_steps": len(all_steps),
        "completion_ratio": (len(completed) / len(all_steps)) if all_steps else 0.0,
        "next_step": next_step,
        "ready_for_calibration": ready,
        "pending_validation": pending_validation,
        "missing": validation_missing if next_step == 7 else [],
        "warnings": validation_warnings if next_step == 7 else [],
        "object_type": object_type,
        "profile": profile,
    }


def workspace_completeness(config_path_raw: str, *, quick: bool = False, precip_source: Any = None) -> dict[str, Any]:
    """Return which wizard steps are completed for a workspace."""
    if quick:
        return quick_workspace_completeness(config_path_raw, precip_source=precip_source)
    try:
        cfg_path = resolve_any_path(config_path_raw, must_exist=True)
        config = read_runtime_config(cfg_path)
    except Exception:
        return {"steps_completed": [], "steps_remaining": [1, 2, 3, 4, 5, 6, 7], "ready_for_calibration": False}

    object_type = detect_object_type(config)
    all_steps = [1, 2, 3, 4, 5, 6, 7] if object_type == OBJECT_INTERBASIN else [1, 2, 4, 5, 6, 7]
    completed: list[int] = []
    for step in all_steps:
        result = wizard_validate_step(str(cfg_path), step, precip_source=precip_source)
        if result["valid"]:
            completed.append(step)
    remaining = [s for s in all_steps if s not in completed]

    profile = current_profile(config)
    calib_validation = validate_workspace_fields(str(cfg_path), stage="calibration", precip_source=precip_source)
    ready = calib_validation["valid"]
    next_step: int | None = remaining[0] if remaining else None

    return {
        "steps_completed": sorted(completed),
        "steps_remaining": sorted(remaining),
        "all_steps": all_steps,
        "completed_count": len(completed),
        "total_steps": len(all_steps),
        "completion_ratio": (len(completed) / len(all_steps)) if all_steps else 0.0,
        "next_step": next_step,
        "ready_for_calibration": ready,
        "pending_validation": False,
        "missing": calib_validation.get("missing", []),
        "warnings": calib_validation.get("warnings", []),
        "object_type": object_type,
        "profile": profile,
    }


def workspace_workflow_summary(config_path_raw: str, *, quick: bool = False, precip_source: Any = None) -> dict[str, Any]:
    comp = workspace_completeness(config_path_raw, quick=quick, precip_source=precip_source)
    return {
        "completed_count": int(comp.get("completed_count", 0)),
        "total_steps": int(comp.get("total_steps", 0)),
        "completion_ratio": float(comp.get("completion_ratio", 0.0)),
        "next_step": comp.get("next_step"),
        "ready_for_calibration": bool(comp.get("ready_for_calibration", False)),
        "pending_validation": bool(comp.get("pending_validation", False)),
        "missing_count": len(comp.get("missing", [])),
        "warning_count": len(comp.get("warnings", [])),
        "steps_remaining": list(comp.get("steps_remaining", [])),
    }


def _sample_daily_raster_stats(
    directory: Path,
    *,
    max_samples_per_file: int = 2048,
    above_thresholds: tuple[float, ...] = (),
    below_thresholds: tuple[float, ...] = (),
) -> dict[str, Any]:
    import numpy as np
    import rasterio

    tif_files = sorted(directory.glob("*.tif")) if directory.exists() else []
    if not tif_files:
        return {"ok": False, "message": f"目录中没有 tif：{directory}", "path": str(directory)}

    sampled_values: list[Any] = []
    valid_pixels = 0
    zero_pixels = 0
    negative_pixels = 0
    above_counts = {threshold: 0 for threshold in above_thresholds}
    below_counts = {threshold: 0 for threshold in below_thresholds}
    global_min: float | None = None
    global_max: float | None = None
    valid_files = 0

    for tif_path in tif_files:
        with rasterio.open(tif_path) as src:
            arr = src.read(1).astype("float64")
            mask = np.isfinite(arr)
            if src.nodata is not None:
                mask &= arr != src.nodata
            values = arr[mask]
            if values.size == 0:
                continue
            valid_files += 1
            valid_pixels += int(values.size)
            zero_pixels += int(np.sum(values == 0))
            negative_pixels += int(np.sum(values < 0))
            for threshold in above_thresholds:
                above_counts[threshold] += int(np.sum(values > threshold))
            for threshold in below_thresholds:
                below_counts[threshold] += int(np.sum(values < threshold))
            local_min = float(np.min(values))
            local_max = float(np.max(values))
            global_min = local_min if global_min is None else min(global_min, local_min)
            global_max = local_max if global_max is None else max(global_max, local_max)
            if values.size <= max_samples_per_file:
                sampled_values.append(values.astype("float32", copy=False))
            else:
                stride = max(1, values.size // max_samples_per_file)
                sampled_values.append(values[::stride][:max_samples_per_file].astype("float32", copy=False))

    if valid_pixels <= 0 or not sampled_values:
        return {"ok": False, "message": f"没有读到有效像元：{directory}", "path": str(directory)}

    sample = np.concatenate(sampled_values)
    return {
        "ok": True,
        "path": str(directory),
        "valid_files": valid_files,
        "valid_pixels": valid_pixels,
        "zero_pixels": zero_pixels,
        "negative_pixels": negative_pixels,
        "min": global_min,
        "max": global_max,
        "p5": float(np.percentile(sample, 5)),
        "p50": float(np.percentile(sample, 50)),
        "p95": float(np.percentile(sample, 95)),
        "above_counts": above_counts,
        "below_counts": below_counts,
    }


def _ratio_percent(numerator: int, denominator: int) -> float:
    return (float(numerator) / float(max(1, denominator))) * 100.0


def _fmt_num(value: Any, digits: int = 2, suffix: str = "") -> str:
    if value is None:
        return "—"
    try:
        return f"{float(value):.{digits}f}{suffix}"
    except Exception:
        return "—"


def build_reasonableness_checks(
    config: dict[str, Any],
    forcing: dict[str, Any],
    *,
    dem_stats: dict[str, Any] | None = None,
    glacier_mask_summary: dict[str, Any] | None = None,
    glacier_mask_exists: bool = False,
    gis_dir: Path | str | None = None,
) -> list[dict[str, Any]]:
    checks: list[dict[str, Any]] = []
    profile = current_profile(config)
    if profile != PROFILE_DAILY:
        return checks
    objective_mode = profile_runner.resolve_objective_mode(config, None, profile)

    directory_map = {
        "prec": Path(str(forcing.get("directories", {}).get("prec", {}).get("path", "") or "")),
        "temp": Path(str(forcing.get("directories", {}).get("temp", {}).get("path", "") or "")),
        "evap": Path(str(forcing.get("directories", {}).get("evap", {}).get("path", "") or "")),
    }

    def build_data_unavailable(title: str, message: str) -> dict[str, Any]:
        return {"title": title, "summary": message, "status": "warn", "items": [{"label": "状态", "value": message, "status": "warn"}]}

    precip_stats = _sample_daily_raster_stats(directory_map["prec"], above_thresholds=(120.0, 250.0), below_thresholds=(-0.1,))
    if not precip_stats["ok"]:
        checks.append(build_data_unavailable("降水合理性检查", "当前还没有足够的降水运行栅格，暂不做数值检查。"))
    else:
        precip_status = "ok"
        precip_summary = "降水范围基本正常。"
        if int(precip_stats["below_counts"].get(-0.1, 0)) > 0:
            precip_status = "fail"
            precip_summary = "降水中出现了负值，建议先检查单位或写入过程。"
        elif float(precip_stats["max"] or 0.0) > 250.0:
            precip_status = "fail"
            precip_summary = "降水极大值过高，建议重点复查原始栅格和单位。"
        elif float(precip_stats["p95"] or 0.0) > 50.0 or int(precip_stats["above_counts"].get(120.0, 0)) > 0:
            precip_status = "warn"
            precip_summary = "降水整体可以继续用，但高值偏多，建议抽样复核。"
        checks.append(
            {
                "title": "降水合理性检查",
                "summary": precip_summary,
                "status": precip_status,
                "items": [
                    {"label": "最小值", "value": _fmt_num(precip_stats["min"], 2, " mm/d"), "status": "fail" if int(precip_stats["below_counts"].get(-0.1, 0)) > 0 else "ok"},
                    {"label": "最大值", "value": _fmt_num(precip_stats["max"], 2, " mm/d"), "status": "fail" if float(precip_stats["max"] or 0.0) > 250.0 else ("warn" if float(precip_stats["max"] or 0.0) > 120.0 else "ok")},
                    {"label": "P95", "value": _fmt_num(precip_stats["p95"], 2, " mm/d"), "status": "warn" if float(precip_stats["p95"] or 0.0) > 50.0 else "ok"},
                    {"label": "负值比例", "value": _fmt_num(_ratio_percent(int(precip_stats["negative_pixels"]), int(precip_stats["valid_pixels"])), 3, "%"), "status": "fail" if int(precip_stats["below_counts"].get(-0.1, 0)) > 0 else "ok"},
                    {"label": "零值比例", "value": _fmt_num(_ratio_percent(int(precip_stats["zero_pixels"]), int(precip_stats["valid_pixels"])), 2, "%"), "status": "ok"},
                ],
            }
        )

    temp_stats = _sample_daily_raster_stats(directory_map["temp"], above_thresholds=(45.0,), below_thresholds=(-60.0,))
    if not temp_stats["ok"]:
        checks.append(build_data_unavailable("气温合理性检查", "当前还没有足够的气温运行栅格，暂不做数值检查。"))
    else:
        temp_status = "ok"
        temp_summary = "气温范围基本正常。"
        if float(temp_stats["p50"] or 0.0) > 120.0:
            temp_status = "fail"
            temp_summary = "气温中位数异常偏高，疑似仍为 Kelvin，尚未转为 Celsius。"
        elif float(temp_stats["min"] or 0.0) < -60.0 or float(temp_stats["max"] or 0.0) > 45.0:
            temp_status = "fail"
            temp_summary = "气温极值超出高原项目常见范围，建议优先检查。"
        elif float(temp_stats["p5"] or 0.0) < -45.0 or float(temp_stats["p95"] or 0.0) > 30.0:
            temp_status = "warn"
            temp_summary = "气温整体可用，但冷热端偏激，建议抽样复核。"
        checks.append(
            {
                "title": "气温合理性检查",
                "summary": temp_summary,
                "status": temp_status,
                "items": [
                    {"label": "最小值", "value": _fmt_num(temp_stats["min"], 2, " ℃"), "status": "fail" if float(temp_stats["min"] or 0.0) < -60.0 else ("warn" if float(temp_stats["p5"] or 0.0) < -45.0 else "ok")},
                    {"label": "最大值", "value": _fmt_num(temp_stats["max"], 2, " ℃"), "status": "fail" if float(temp_stats["max"] or 0.0) > 45.0 else ("warn" if float(temp_stats["p95"] or 0.0) > 30.0 else "ok")},
                    {"label": "P5 / P95", "value": f"{_fmt_num(temp_stats['p5'], 2, ' ℃')} / {_fmt_num(temp_stats['p95'], 2, ' ℃')}", "status": "warn" if float(temp_stats["p5"] or 0.0) < -45.0 or float(temp_stats["p95"] or 0.0) > 30.0 else "ok"},
                    {"label": "中位数", "value": _fmt_num(temp_stats["p50"], 2, " ℃"), "status": "fail" if float(temp_stats["p50"] or 0.0) > 120.0 else "ok"},
                    {"label": "温标判断", "value": "疑似 Kelvin" if float(temp_stats["p50"] or 0.0) > 120.0 else "看起来正常", "status": "fail" if float(temp_stats["p50"] or 0.0) > 120.0 else "ok"},
                ],
            }
        )

    evap_stats = _sample_daily_raster_stats(directory_map["evap"], above_thresholds=(15.0, 25.0), below_thresholds=(-0.5,))
    if not evap_stats["ok"]:
        checks.append(build_data_unavailable("潜在蒸散发合理性检查", "当前还没有足够的潜在蒸散发运行栅格，暂不做数值检查。"))
    else:
        evap_status = "ok"
        evap_summary = "潜在蒸散发范围基本正常。"
        negative_ratio = _ratio_percent(int(evap_stats["negative_pixels"]), int(evap_stats["valid_pixels"]))
        if float(evap_stats["min"] or 0.0) < -0.5 or negative_ratio > 1.0 or float(evap_stats["max"] or 0.0) > 25.0:
            evap_status = "fail"
            evap_summary = "潜在蒸散发存在明显异常值，建议优先检查计算结果。"
        elif float(evap_stats["p95"] or 0.0) > 10.0 or float(evap_stats["max"] or 0.0) > 15.0:
            evap_status = "warn"
            evap_summary = "潜在蒸散发整体可用，但高值偏大，建议抽样复核。"
        checks.append(
            {
                "title": "潜在蒸散发合理性检查",
                "summary": evap_summary,
                "status": evap_status,
                "items": [
                    {"label": "最小值", "value": _fmt_num(evap_stats["min"], 2, " mm/d"), "status": "fail" if float(evap_stats["min"] or 0.0) < -0.5 else "ok"},
                    {"label": "最大值", "value": _fmt_num(evap_stats["max"], 2, " mm/d"), "status": "fail" if float(evap_stats["max"] or 0.0) > 25.0 else ("warn" if float(evap_stats["max"] or 0.0) > 15.0 else "ok")},
                    {"label": "P95", "value": _fmt_num(evap_stats["p95"], 2, " mm/d"), "status": "warn" if float(evap_stats["p95"] or 0.0) > 10.0 else "ok"},
                    {"label": "负值比例", "value": _fmt_num(negative_ratio, 3, "%"), "status": "fail" if negative_ratio > 1.0 or float(evap_stats["min"] or 0.0) < -0.5 else "ok"},
                    {"label": "零值比例", "value": _fmt_num(_ratio_percent(int(evap_stats["zero_pixels"]), int(evap_stats["valid_pixels"])), 2, "%"), "status": "ok"},
                ],
            }
        )

    dem_info = dem_stats or {}
    dem_valid = int(dem_info.get("valid_pixels", 0) or 0)
    if dem_valid <= 0:
        checks.append(build_data_unavailable("DEM 合理性检查", "当前还没有可用 DEM，暂不做数值检查。"))
    else:
        dem_status = "ok"
        dem_summary = "DEM 范围基本正常。"
        dem_min = float(dem_info.get("min", 0.0) or 0.0)
        dem_max = float(dem_info.get("max", 0.0) or 0.0)
        dem_median = float(dem_info.get("median", 0.0) or 0.0)
        if dem_min < -500.0 or dem_max > 9000.0:
            dem_status = "fail"
            dem_summary = "DEM 极值明显异常，建议检查输入栅格。"
        elif dem_median < 1500.0:
            dem_status = "warn"
            dem_summary = "DEM 中位高程偏低，和当前高原项目认知不一致时要重点复查。"
        checks.append(
            {
                "title": "DEM 合理性检查",
                "summary": dem_summary,
                "status": dem_status,
                "items": [
                    {"label": "最小值", "value": _fmt_num(dem_min, 0, " m"), "status": "fail" if dem_min < -500.0 else "ok"},
                    {"label": "最大值", "value": _fmt_num(dem_max, 0, " m"), "status": "fail" if dem_max > 9000.0 else "ok"},
                    {"label": "中位高程", "value": _fmt_num(dem_median, 0, " m"), "status": "warn" if dem_median < 1500.0 else "ok"},
                    {"label": "分辨率", "value": str(dem_info.get("resolution_text", "—")), "status": "ok"},
                    {"label": "有效像元数", "value": str(dem_valid), "status": "ok"},
                ],
            }
        )

    glacier_shp = str(config.get("冰川边界_shp", "")).strip()
    if not glacier_shp:
        checks.append(
            {
                "title": "冰川合理性检查",
                "summary": "当前未启用冰川输入。",
                "status": "ok",
                "items": [{"label": "状态", "value": "未启用", "status": "ok"}],
            }
        )
    else:
        glacier_mode = str((glacier_mask_summary or {}).get("glacier_mode", "") or "").strip().lower()
        glacier_pixels = int((glacier_mask_summary or {}).get("glacier_pixels", 0) or 0)
        glacier_area = float((glacier_mask_summary or {}).get("glacier_area_km2", 0.0) or 0.0)
        true_glacier_area = float((glacier_mask_summary or {}).get("true_glacier_area_km2", 0.0) or 0.0)
        represented_area = float((glacier_mask_summary or {}).get("represented_area_km2", glacier_area) or glacier_area or 0.0)
        area_bias_ratio = float((glacier_mask_summary or {}).get("area_bias_ratio", 0.0) or 0.0)
        nonzero_fraction_pixels = int((glacier_mask_summary or {}).get("nonzero_fraction_pixels", 0) or 0)
        glacier_ratio = _ratio_percent(glacier_pixels, dem_valid) if dem_valid > 0 else 0.0
        glacier_status = "ok"
        glacier_mode_label = "0.1° 分数法" if glacier_mode == "fractional_subgrid" else "1km 二值法"
        glacier_summary = "冰川范围表达基本正常。"
        glacier_reference_count = count_matching(build_profile_paths(config, profile)["glacier_melt_dir"])
        if objective_mode == profile_runner.OBJECTIVE_MODE_MULTI and glacier_reference_count > 0:
            glacier_constraint_value = "已纳入综合水文过程评价（径流过程特征 + 冰川面积占比复核；另有冰融水参考序列可供复核）"
            glacier_constraint_status = "ok"
        elif objective_mode == profile_runner.OBJECTIVE_MODE_MULTI:
            glacier_constraint_value = "已纳入综合水文过程评价（径流过程特征 + 冰川面积占比复核）"
            glacier_constraint_status = "ok"
        else:
            if glacier_reference_count > 0:
                glacier_constraint_value = "仅采用径流拟合评价；冰融水参考序列仅作过程复核"
            else:
                glacier_constraint_value = "仅采用径流拟合评价"
            glacier_constraint_status = "warn"
        if not glacier_mask_exists:
            glacier_status = "fail"
            glacier_summary = "已经配置冰川 shp，但当前还没有生成冰川掩膜。"
        elif glacier_mode == "fractional_subgrid" and nonzero_fraction_pixels <= 0:
            glacier_status = "fail"
            glacier_summary = "当前是 0.1° 分数法，但没有有效冰川分数像元，建议先复核流域范围和冰川 shp。"
        elif glacier_mode == "fractional_subgrid" and represented_area <= 0.0 and true_glacier_area > 0.0:
            glacier_status = "fail"
            glacier_summary = "当前存在真实冰川面积，但分数化后的表达面积为 0，建议检查 DEM 与冰川 shp 的空间关系。"
        elif glacier_mode == "fractional_subgrid" and area_bias_ratio > 1.5:
            glacier_status = "warn"
            glacier_summary = "0.1° 分数法已经可用，但表达面积偏大，建议复核空间叠加结果。"
        elif glacier_mode == "fractional_subgrid" and 0.0 < area_bias_ratio < 0.5:
            glacier_status = "warn"
            glacier_summary = "0.1° 分数法已经可用，但表达面积偏小，建议结合流域位置再核一下。"
        elif glacier_ratio > 70.0:
            glacier_status = "fail"
            glacier_summary = "冰川面积占比异常偏大，建议检查冰川 shp 或流域范围。"
        elif glacier_ratio == 0.0 or glacier_ratio > 40.0:
            glacier_status = "warn"
            glacier_summary = "冰川面积占比需要复核，建议结合流域位置再确认一次。"
        elif glacier_constraint_status == "warn":
            glacier_status = "warn"
            glacier_summary = "冰川空间表达已生成，但当前评价口径较简化；裸冰融化分量应作为模型水源分解结果解读。"
        glacier_elev_summary_local = {}
        glacier_elev_summary_path_local = (Path(gis_dir) / "glacier_elev_summary.json") if gis_dir else None
        if glacier_elev_summary_path_local is not None and glacier_elev_summary_path_local.exists():
            try:
                glacier_elev_summary_local = read_json_file(glacier_elev_summary_path_local)
            except Exception:
                glacier_elev_summary_local = {}
        elev_status_val = str(glacier_elev_summary_local.get("status", "unknown")).strip().lower()
        if glacier_mode == "fractional_subgrid":
            if elev_status_val == "ok":
                mean_elev = glacier_elev_summary_local.get("area_weighted_elev_mean") or glacier_elev_summary_local.get("elev_mean")
                try:
                    elev_value_text = f"已启用（面积加权均值 {float(mean_elev):.0f} m）" if mean_elev is not None else "已启用"
                except Exception:
                    elev_value_text = "已启用"
                elev_item_status = "ok"
            elif elev_status_val == "no_high_res_dem":
                elev_value_text = "未找到 1km 高分辨率 DEM"
                elev_item_status = "fail"
            elif elev_status_val == "no_intersection":
                elev_value_text = "无有效高程像元"
                elev_item_status = "fail"
            else:
                elev_value_text = "未启用（结果会被标 degraded）"
                elev_item_status = "fail"
        else:
            elev_value_text = "1km 无需此步"
            elev_item_status = "ok"
        checks.append(
            {
                "title": "冰川合理性检查",
                "summary": glacier_summary,
                "status": glacier_status,
                "items": [
                    {"label": "冰川表达模式", "value": glacier_mode_label, "status": "ok" if glacier_mask_exists else "fail"},
                    {"label": "冰川像元数", "value": str(glacier_pixels), "status": "fail" if not glacier_mask_exists else ("warn" if glacier_ratio == 0.0 else "ok")},
                    {"label": "真实冰川面积", "value": _fmt_num(true_glacier_area, 3, " km²"), "status": "ok" if glacier_mask_exists else "fail"},
                    {"label": "表达冰川面积", "value": _fmt_num(represented_area, 3, " km²"), "status": "ok" if glacier_mask_exists else "fail"},
                    {"label": "面积偏差倍率", "value": _fmt_num(area_bias_ratio, 3, ""), "status": "warn" if glacier_mode == "fractional_subgrid" and (area_bias_ratio > 1.5 or (0.0 < area_bias_ratio < 0.5)) else "ok"},
                    {"label": "面积占比", "value": _fmt_num(glacier_ratio, 2, "%"), "status": "fail" if glacier_ratio > 70.0 else ("warn" if glacier_ratio == 0.0 or glacier_ratio > 40.0 else "ok")},
                    {"label": "分数像元数", "value": str(nonzero_fraction_pixels), "status": "warn" if glacier_mode == "fractional_subgrid" and nonzero_fraction_pixels <= 0 else "ok"},
                    {"label": "掩膜状态", "value": "已生成" if glacier_mask_exists else "未生成", "status": "ok" if glacier_mask_exists else "fail"},
                    {"label": "冰川分量约束", "value": glacier_constraint_value, "status": glacier_constraint_status},
                    {"label": "冰川高程修正", "value": elev_value_text, "status": elev_item_status},
                ],
            }
        )

    return checks


def workspace_detailed_check(config_path_raw: str, precip_source: Any = None) -> dict[str, Any]:
    """Return a detailed summary of all input data for the workspace."""
    import numpy as np

    cfg_path = resolve_any_path(config_path_raw, must_exist=True)
    config = read_runtime_config(cfg_path)
    profile = current_profile(config)
    paths = build_profile_paths(config, profile)
    configured_source = configured_precip_source(config)
    source = resolve_precip_source(config, precip_source)
    object_type = detect_object_type(config)
    time_cfg = config.get("时间", {})
    meteo_state = read_meteo_state(config, profile)

    summary: list[dict[str, Any]] = []
    dem_stats: dict[str, Any] = {}

    # Basic config
    summary.append({"group": "基本配置", "label": "率定模式", "value": PROFILE_LABELS.get(profile, profile)})
    summary.append({"group": "基本配置", "label": "项目对象", "value": OBJECT_LABELS.get(object_type, object_type)})
    summary.append({"group": "基本配置", "label": "时间步长", "value": f"{config.get('时间步长_小时', 24)} 小时"})
    summary.append({"group": "基本配置", "label": "降水来源配置", "value": configured_source.upper()})
    summary.append({"group": "基本配置", "label": "运行降水源", "value": source.upper()})
    summary.append({"group": "基本配置", "label": "CFMAX 分区阈值", "value": f"{config.get('CFMAX分区阈值_m', '未设置')} m"})
    summary.append({"group": "基本配置", "label": "FAO56 平均海拔", "value": f"{config.get('FAO56平均海拔_m', '未设置')} m"})

    # Time periods
    for key in ("预热开始", "预热结束", "率定开始", "率定结束", "验证开始", "验证结束"):
        val = time_cfg.get(key, "")
        summary.append({"group": "时间分段", "label": key, "value": val or "未设置", "ok": bool(val)})

    # DEM
    dem_path = _workspace_dem_path(paths["gis_dir"], prefer=_configured_dem_kind(config))
    if dem_path.exists():
        try:
            import rasterio
            with rasterio.open(dem_path) as src:
                arr = src.read(1).astype("float64")
                if src.nodata is not None:
                    arr[arr == src.nodata] = float("nan")
                valid = arr[np.isfinite(arr) & (arr > 0)]
                dem_stats = {
                    "min": float(np.nanmin(valid)) if valid.size else None,
                    "max": float(np.nanmax(valid)) if valid.size else None,
                    "median": float(np.nanmedian(valid)) if valid.size else None,
                    "valid_pixels": int(valid.size),
                    "resolution_text": f"{abs(src.res[0]):.6f}° x {abs(src.res[1]):.6f}°",
                }
                summary.append({"group": "地理数据", "label": "DEM 裁剪栅格", "value": "已生成", "ok": True})
                summary.append({"group": "地理数据", "label": "DEM 高程范围", "value": f"{float(np.nanmin(valid)):.0f} ~ {float(np.nanmax(valid)):.0f} m"})
                summary.append({"group": "地理数据", "label": "DEM 中位高程", "value": f"{float(np.nanmedian(valid)):.0f} m"})
                summary.append({"group": "地理数据", "label": "DEM 有效像元数", "value": f"{valid.size}"})
                summary.append({"group": "地理数据", "label": "DEM 分辨率", "value": f"{abs(src.res[0]):.6f}° x {abs(src.res[1]):.6f}°"})
        except Exception:
            summary.append({"group": "地理数据", "label": "DEM 裁剪栅格", "value": "已生成（读取详情失败）", "ok": True})
    else:
        summary.append({"group": "地理数据", "label": "DEM 裁剪栅格", "value": "缺失", "ok": False})

    # Flow accumulation
    flow_acc = Path(paths["gis_dir"]) / "flow_accumulation.tif"
    flow_masked = Path(paths["gis_dir"]) / "flow_accumulation_masked.tif"
    summary.append({"group": "地理数据", "label": "流量累积", "value": "已生成" if flow_acc.exists() else "缺失", "ok": flow_acc.exists()})
    summary.append({"group": "地理数据", "label": "流域掩膜", "value": "已生成" if flow_masked.exists() else "缺失", "ok": flow_masked.exists()})

    # Elevation zones
    low_exists = (Path(paths["gis_dir"]) / "elevation_zone_low.tif").exists() or (Path(paths["gis_dir"]) / "elevation_zone_mid.tif").exists()
    high_exists = (Path(paths["gis_dir"]) / "elevation_zone_high.tif").exists()
    zone_count = int(low_exists) + int(high_exists)
    summary.append({"group": "地理数据", "label": "高程分区", "value": f"{zone_count}/2 已生成", "ok": zone_count == 2})

    # Glacier
    glacier_shp = str(config.get("冰川边界_shp", "")).strip()
    glacier_mask = Path(paths["gis_dir"]) / "glacier_mask.tif"
    glacier_fraction = Path(paths["gis_dir"]) / "glacier_fraction.tif"
    glacier_mask_summary = {}
    glacier_mask_summary_path = Path(paths["gis_dir"]) / "glacier_mask_summary.json"
    if glacier_mask_summary_path.exists():
        try:
            glacier_mask_summary = read_json_file(glacier_mask_summary_path)
        except Exception:
            glacier_mask_summary = {}
    if glacier_shp:
        glacier_mode = str(glacier_mask_summary.get("glacier_mode", "") or "").strip().lower()
        glacier_mode_label = "0.1° 分数法" if glacier_mode == "fractional_subgrid" else ("1km 二值法" if glacier_mask.exists() else "待生成")
        summary.append(
            {
                "group": "地理数据",
                "label": "冰川掩膜（可选）",
                "value": (
                    str(glacier_mask_summary.get("message", "")).strip()
                    or ("已生成" if glacier_mask.exists() else "未生成（可选）")
                ),
                "ok": True if glacier_mask.exists() else None,
            }
        )
        summary.append(
            {
                "group": "地理数据",
                "label": "冰川表达模式",
                "value": glacier_mode_label,
                "ok": True if glacier_mask.exists() else None,
            }
        )
        if glacier_fraction.exists() or glacier_mode == "fractional_subgrid":
            summary.append(
                {
                    "group": "地理数据",
                    "label": "冰川分数栅格",
                    "value": "已生成" if glacier_fraction.exists() else "应生成但当前缺失",
                    "ok": True if glacier_fraction.exists() else False,
                }
            )
        true_glacier_area = glacier_mask_summary.get("true_glacier_area_km2")
        represented_area = glacier_mask_summary.get("represented_area_km2")
        area_bias_ratio = glacier_mask_summary.get("area_bias_ratio")
        if true_glacier_area is not None:
            summary.append({"group": "地理数据", "label": "真实冰川面积", "value": _fmt_num(true_glacier_area, 3, " km²"), "ok": None})
        if represented_area is not None:
            summary.append({"group": "地理数据", "label": "表达冰川面积", "value": _fmt_num(represented_area, 3, " km²"), "ok": None})
        if area_bias_ratio is not None:
            summary.append({"group": "地理数据", "label": "面积偏差倍率", "value": _fmt_num(area_bias_ratio, 3, ""), "ok": None})
        glacier_elev_summary = {}
        glacier_elev_summary_path = Path(paths["gis_dir"]) / "glacier_elev_summary.json"
        if glacier_elev_summary_path.exists():
            try:
                glacier_elev_summary = read_json_file(glacier_elev_summary_path)
            except Exception:
                glacier_elev_summary = {}
        elev_status = str(glacier_elev_summary.get("status", "unknown")).strip().lower()
        if glacier_mode == "fractional_subgrid":
            if elev_status == "ok":
                mean_elev = glacier_elev_summary.get("area_weighted_elev_mean") or glacier_elev_summary.get("elev_mean")
                value = "已启用"
                if mean_elev is not None:
                    try:
                        value = f"已启用（面积加权均值 {float(mean_elev):.0f} m）"
                    except Exception:
                        pass
                summary.append({"group": "地理数据", "label": "冰川高程修正", "value": value, "ok": True})
            elif elev_status == "no_high_res_dem":
                summary.append({"group": "地理数据", "label": "冰川高程修正", "value": "未找到 1km 高分辨率 DEM", "ok": False})
            elif elev_status == "no_intersection":
                summary.append({"group": "地理数据", "label": "冰川高程修正", "value": "无有效高程像元", "ok": False})
            else:
                summary.append({"group": "地理数据", "label": "冰川高程修正", "value": "未启用（结果会被标 degraded）", "ok": False})
        elif glacier_mode == "binary_legacy":
            summary.append({"group": "地理数据", "label": "冰川高程修正", "value": "1km 无需此步", "ok": True})
    else:
        summary.append({"group": "地理数据", "label": "冰川掩膜（可选）", "value": "未启用（未提供冰川边界 shp）", "ok": None})

    # Meteorological data
    forcing = validate_forcing_bundle(config, profile, precip_source=source)
    step_hours = normalize_time_step_hours(config.get("时间步长_小时", 24.0))
    if meteo_state:
        summary.append(
            {
                "group": "气象数据",
                "label": "气象驱动准备方式",
                "value": str(meteo_state.get("preparation_mode_label", "本地栅格导入")),
                "ok": True,
            }
        )
        completed_at = str(meteo_state.get("completed_at", "")).strip()
        if completed_at:
            summary.append({"group": "气象数据", "label": "最近导入时间", "value": completed_at, "ok": None})
        source_dirs = dict(meteo_state.get("source_dirs", {}) or {})
        target_dirs = dict(meteo_state.get("target_dirs", {}) or {})
        for key, label in (("prec", "降水"), ("temp", "气温"), ("evap", "蒸散发")):
            source_dir = str(source_dirs.get(key, "") or "").strip()
            target_dir = str(target_dirs.get(key, "") or "").strip()
            if source_dir:
                summary.append({"group": "气象数据", "label": f"{label}来源目录", "value": source_dir, "ok": None})
            if target_dir:
                summary.append({"group": "气象数据", "label": f"{label}工程目录", "value": target_dir, "ok": None})
    elif source == "custom_tif":
        summary.append(
            {
                "group": "气象数据",
                "label": "气象驱动准备方式",
                "value": "本地栅格模式（尚无导入记录，可能为历史数据）",
                "ok": None,
            }
        )
    if forcing["expected_steps"] is not None:
        summary.append({"group": "气象数据", "label": "资料口径", "value": str(forcing.get("time_basis_label", "连续时段")), "ok": True})
        summary.append({"group": "气象数据", "label": "期望时间步数", "value": str(forcing["expected_steps"]), "ok": True})
    event_windows = dict(forcing.get("event_windows") or {})
    if event_windows:
        summary.append(
            {
                "group": "气象数据",
                "label": "洪水事件窗口",
                "value": f"{int(event_windows.get('valid_event_count', 0) or 0)}/{int(event_windows.get('event_count', 0) or 0)} 场有效",
                "ok": int(event_windows.get("valid_event_count", 0) or 0) > 0,
            }
        )
    for key, label in (("prec", "降水"), ("temp", "气温"), ("evap", "蒸散发")):
        item = forcing["directories"][key]
        summary.append(
            {
                "group": "气象数据",
                "label": f"{label}有效时间栅格",
                "value": f"{item['valid_time_steps']} / {item['total_files']}",
                "ok": item["ok"],
            }
        )
        if item["invalid_files"]:
            sample = "、".join(item["invalid_files"][:3])
            summary.append(
                {
                    "group": "气象数据",
                    "label": f"{label}非法文件名",
                    "value": f"{len(item['invalid_files'])} 个，例如 {sample}",
                    "ok": False,
                }
            )
        if item["duplicate_timestamps"]:
            first_ts, names = next(iter(item["duplicate_timestamps"].items()))
            summary.append(
                {
                    "group": "气象数据",
                    "label": f"{label}重复时间戳",
                    "value": f"{format_timestamp_for_display(first_ts, step_hours)} -> {'、'.join(names[:3])}",
                    "ok": False,
                }
            )
        if item["missing_steps"]:
            sample = "、".join(format_timestamp_for_display(ts, step_hours) for ts in item["missing_steps"][:3])
            summary.append(
                {
                    "group": "气象数据",
                    "label": f"{label}时间覆盖",
                    "value": f"缺少 {len(item['missing_steps'])} 个时间步，例如 {sample}",
                    "ok": False,
                }
            )
        elif forcing["expected_steps"] is not None:
            summary.append(
                {
                    "group": "气象数据",
                    "label": f"{label}时间覆盖",
                    "value": f"已覆盖{forcing.get('time_basis_label', '当前任务时段')} {forcing['expected_steps']} 个时间步",
                    "ok": item["ok"],
                }
            )

    # Input files
    shp = config.get("流域边界_shp", "")
    obs = config.get(OBSERVED_FLOW_KEY, "")
    shp_path = _resolve_config_related_path(config, shp)
    obs_path = _resolve_config_related_path(config, obs)
    summary.append({"group": "输入文件", "label": "流域边界 shp", "value": ("已配置" if shp and shp_path is not None and shp_path.exists() else "缺失"), "ok": bool(shp and shp_path is not None and shp_path.exists())})
    summary.append({"group": "输入文件", "label": "观测径流文件", "value": ("已配置" if obs and obs_path is not None and obs_path.exists() else "缺失"), "ok": bool(obs and obs_path is not None and obs_path.exists())})

    if object_type == OBJECT_INTERBASIN:
        boundary_csv = str(dict(config.get("边界条件", {})).get("上游边界入流_csv", "")).strip()
        boundary_path = _resolve_config_related_path(config, boundary_csv)
        summary.append({"group": "输入文件", "label": "上游边界入流 csv", "value": ("已配置" if boundary_csv and boundary_path is not None and boundary_path.exists() else "缺失"), "ok": bool(boundary_csv and boundary_path is not None and boundary_path.exists())})

    # Overall
    all_ok = all(item.get("ok") is not False for item in summary)
    reasonableness_checks = build_reasonableness_checks(
        config,
        forcing,
        dem_stats=dem_stats,
        glacier_mask_summary=glacier_mask_summary,
        glacier_mask_exists=glacier_mask.exists(),
        gis_dir=Path(paths["gis_dir"]),
    )

    return {
        "summary": summary,
        "reasonableness_checks": reasonableness_checks,
        "all_ok": all_ok,
        "profile": profile,
        "object_type": object_type,
    }


def workspace_advice(config_path_raw: str, precip_source: Any = None) -> dict[str, Any]:
    cfg_path = resolve_any_path(config_path_raw, must_exist=True)
    config = read_runtime_config(cfg_path)
    profile = current_profile(config)
    runtime_prec_source = resolve_precip_source(config, precip_source)
    comp = workspace_completeness(str(cfg_path), precip_source=runtime_prec_source)
    validation = validate_workspace_fields(str(cfg_path), stage="calibration", precip_source=runtime_prec_source)
    forcing = validate_forcing_bundle(config, profile, precip_source=runtime_prec_source)
    presets = list_manual_presets(str(cfg_path)).get("presets", [])
    cpu_total = max(1, int(os.cpu_count() or 4))
    expected_steps = int(forcing.get("expected_steps") or 0)
    object_type = detect_object_type(config)

    advice_items: list[dict[str, Any]] = []
    missing_text = "；".join(validation.get("missing", [])[:2]) if validation.get("missing") else ""
    if comp.get("ready_for_calibration"):
        headline = "输入已基本就绪，可以进入率定。"
    else:
        headline = f"当前还不能率定，优先补齐：{missing_text or '向导中的缺项'}"

    for message in validation.get("missing", []):
        target_step = 7
        if any(token in message for token in ("流域边界", "观测径流", "时间.", "时间顺序")):
            target_step = 2
        elif "上游边界入流" in message:
            target_step = 3
        elif any(token in message for token in ("站点", "自带降水", "自带温度", "自带蒸散发", "本地降水栅格", "本地气温栅格", "本地蒸散发栅格")):
            target_step = 4
        elif any(token in message for token in ("dem_1km", "dem_0p1deg", "flow_accumulation_masked", "DEM", "流量累积", "流域掩膜", "高程分区")):
            target_step = 5
        elif any(token in message for token in ("降水目录", "气温目录", "蒸散发目录", "时间覆盖", "时间戳", "气象驱动", "forcing", ".tif")):
            target_step = 6
        advice_items.append(
            {
                "kind": "fix",
                "title": f"先完成第 {target_step} 步",
                "detail": message,
                "target_step": target_step,
            }
        )

    for message in validation.get("warnings", [])[:4]:
        advice_items.append(
            {
                "kind": "warn",
                "title": "需要注意",
                "detail": message,
                "target_step": None,
            }
        )

    heavy_profile = profile == PROFILE_HOURLY or expected_steps >= 4000
    recommended_method = "mc_screen_de"
    recommended_workers = min(cpu_total, 4 if heavy_profile else 6)
    recommended_maxiter = 18 if heavy_profile else 24
    recommended_popsize = 6 if heavy_profile else 8
    recommended_mc_samples = 240 if heavy_profile else 300
    recommended_bound_shrink = 0.25 if presets else 0.0
    calibration_reasons: list[str] = []

    if presets:
        calibration_reasons.append("已存在手调参数集，可以在较小范围内继续精细搜索或局部精修。")
    else:
        calibration_reasons.append("尚无手调参数集，建议先在结果页按雪过程、土壤过程、产汇流顺序手调一轮。")
    if heavy_profile:
        calibration_reasons.append("当前时段较长或为小时尺度，自动率定负载会明显变大，建议先完成输入完整性检查并控制搜索规模。")
        recommended_method = "mc_screen_de"
    else:
        calibration_reasons.append("当前负载处于可控范围，适合先筛选再精修。")
    if object_type == OBJECT_INTERBASIN:
        calibration_reasons.append("区间流域对边界入流更敏感，建议先核对边界入流过程是否合理。")
    if forcing.get("warnings"):
        calibration_reasons.append("虽然当前可率定，但气象驱动仍有警告，建议先在第 7 步确认时间覆盖。")

    advice_items.append(
        {
            "kind": "plan",
            "title": "推荐率定策略",
            "detail": "先完成输入完整性检查，再手动调参，最后自动率定。",
            "target_step": None,
        }
    )
    if not presets:
        advice_items.append(
            {
                "kind": "plan",
                "title": "推荐手调顺序",
                "detail": "先调雪过程，再调土壤过程，最后调产汇流。每次只改少量参数并重算观察变化。",
                "target_step": None,
            }
        )

    return {
        "headline": headline,
        "ready_for_calibration": bool(comp.get("ready_for_calibration", False)),
        "profile": profile,
        "object_type": object_type,
        "recommended_step": comp.get("next_step"),
        "recommendations": advice_items[:8],
        "calibration": {
            "method": recommended_method,
            "method_label": {
                "mc_screen_de": "快速筛选 + 精细搜索",
                "de": "精细搜索（差分进化）",
                "mc_only": "仅快速筛选",
            }[recommended_method],
            "workers": recommended_workers,
            "maxiter": recommended_maxiter,
            "popsize": recommended_popsize,
            "mc_samples": recommended_mc_samples,
            "init_bound_shrink": recommended_bound_shrink,
            "param_bounds_profile": profile_runner.DEFAULT_DAILY_PARAM_BOUNDS_PROFILE
            if profile == PROFILE_DAILY
            else profile_runner.PARAM_BOUNDS_PROFILE_HOURLY,
            "param_bounds_profile_label": profile_runner.PARAM_BOUNDS_PROFILE_LABELS.get(
                profile_runner.DEFAULT_DAILY_PARAM_BOUNDS_PROFILE
                if profile == PROFILE_DAILY
                else profile_runner.PARAM_BOUNDS_PROFILE_HOURLY,
                "",
            ),
            "reasons": calibration_reasons,
            "expected_steps": expected_steps,
            "has_manual_presets": bool(presets),
            "manual_preset_count": len(presets),
            "quick_test_first": False,
        },
    }


# ---------------------------------------------------------------------------
#  GIS / Meteorological data import
# ---------------------------------------------------------------------------

def import_gis_files(payload: dict[str, Any]) -> dict[str, Any]:
    """Copy user-provided GIS rasters into the workspace gis directory."""
    import shutil

    config_path = resolve_any_path(str(payload.get("config_path", "")), must_exist=True)
    config = read_runtime_config(config_path)
    profile = current_profile(config)
    paths = build_profile_paths(config, profile)
    gis_dir = Path(paths["gis_dir"])
    gis_dir.mkdir(parents=True, exist_ok=True)

    copied: list[str] = []
    dem_dst: Path | None = None
    file_map = {
        "flowacc_masked_path": "flow_accumulation_masked.tif",
        "flowdir_path": "flow_direction.tif",
        "glacier_mask_path": "glacier_mask.tif",
    }
    dem_src_raw = str(payload.get("dem_path", "")).strip()
    if dem_src_raw:
        dem_src = resolve_any_path(dem_src_raw, must_exist=True)
        dem_kind = infer_dem_kind_from_raster(dem_src)
        dem_dst = gis_dir / workspace_dem_filename(dem_kind)
        shutil.copy2(str(dem_src), str(dem_dst))
        remove_other_workspace_dem_variants(gis_dir, dem_dst)
        copied.append(dem_dst.name)
    for key, target_name in file_map.items():
        src_raw = str(payload.get(key, "")).strip()
        if not src_raw:
            continue
        src = resolve_any_path(src_raw, must_exist=True)
        dst = gis_dir / target_name
        shutil.copy2(str(src), str(dst))
        copied.append(target_name)

    # Auto-generate elevation zones from imported DEM
    dem_file = dem_dst or _workspace_dem_path(gis_dir, prefer=_configured_dem_kind(config))
    if dem_file.exists():
        import numpy as np
        import rasterio

        threshold = float(config.get("CFMAX分区阈值_m", 5000.0))
        with rasterio.open(dem_file) as src:
            arr = src.read(1).astype("float64")
            nodata = src.nodata
            if nodata is not None:
                arr[arr == nodata] = float("nan")
            mid = np.where(np.isfinite(arr) & (arr <= threshold), 1.0, 0.0).astype("float32")
            high = np.where(np.isfinite(arr) & (arr > threshold), 1.0, 0.0).astype("float32")
            meta = src.meta.copy()
            meta.update(dtype="float32", nodata=0, compress="lzw")
            for name, data in [("elevation_zone_low.tif", mid), ("elevation_zone_high.tif", high)]:
                with rasterio.open(gis_dir / name, "w", **meta) as dst:
                    dst.write(data, 1)
                copied.append(name)

        # Also create flow_accumulation.tif if only masked version provided
        fa = gis_dir / "flow_accumulation.tif"
        fa_masked = gis_dir / "flow_accumulation_masked.tif"
        if not fa.exists() and fa_masked.exists():
            shutil.copy2(str(fa_masked), str(fa))
            copied.append("flow_accumulation.tif")

    return {"copied": copied, "message": f"已导入 {len(copied)} 个 GIS 文件到 {gis_dir}。"}


def ordered_tif_files_by_timestamp(directory: Path) -> list[tuple[pd.Timestamp, Path]]:
    ordered: list[tuple[pd.Timestamp, Path]] = []
    for tif_path in directory.glob("*.tif"):
        timestamp = parse_time_from_name(tif_path.name)
        if timestamp is not None:
            ordered.append((timestamp, tif_path))
    ordered.sort(key=lambda item: (item[0], item[1].name))
    return ordered


def same_path(a: Path, b: Path) -> bool:
    try:
        return a.resolve(strict=False) == b.resolve(strict=False)
    except Exception:
        return str(a) == str(b)


def replace_directory_from_stage(target_dir: Path, stage_dir: Path) -> None:
    import shutil
    backup_dir = target_dir.parent / f".{target_dir.name}__backup_{uuid.uuid4().hex[:8]}"
    had_target = target_dir.exists()
    try:
        if had_target:
            target_dir.replace(backup_dir)
        stage_dir.replace(target_dir)
        if backup_dir.exists():
            shutil.rmtree(backup_dir)
    except Exception:
        if target_dir.exists() and not had_target:
            shutil.rmtree(target_dir)
        if backup_dir.exists() and not target_dir.exists():
            backup_dir.replace(target_dir)
        raise


def _should_report_file_progress(index: int, total: int) -> bool:
    if total <= 20:
        return True
    step = max(1, total // 10)
    return index == 1 or index == total or index % step == 0


def _mark_task_finished(task_id: str, *, ok: bool, return_code: int, result: dict[str, Any] | None = None) -> None:
    with TASK_LOCK:
        task = TASKS.get(task_id)
        if task is None:
            return
        task.status = "completed" if ok else "failed"
        task.return_code = return_code
        if result is not None:
            task.metadata["result"] = result
        task.updated_at = time.time()


def perform_meteo_import(payload: dict[str, Any], *, task_id: str | None = None) -> dict[str, Any]:
    """Copy user-provided meteorological tif directories into aligned_masked, in timestamp order."""
    import shutil

    import rasterio
    from rasterio.warp import reproject, Resampling

    config_path = resolve_any_path(str(payload.get("config_path", "")), must_exist=True)
    config = read_runtime_config(config_path)
    profile = current_profile(config)
    paths = build_profile_paths(config, profile)
    gis_dir = Path(paths["gis_dir"])
    dem_file = _workspace_dem_path(gis_dir, prefer=_configured_dem_kind(config))
    precip_source = profile_runner.resolve_runtime_precip_source(config, payload.get("prec_source", None))
    time_basis = task_time_basis(config, context="calibration")
    time_basis_label = TIME_BASIS_LABELS.get(time_basis, "当前任务时段")
    expected_index = build_expected_forcing_index(config, context="calibration")
    expected_time_set = set(expected_index) if expected_index is not None else None
    dir_map = {
        "prec_dir": (
            paths["aligned_prec_custom_base_dir"]
            if precip_source == "custom_tif"
            else paths["aligned_prec_era5_base_dir"]
            if precip_source == "era5"
            else (paths["aligned_prec_base_dir"] if precip_source == "mswep" else paths["aligned_prec_cmfd_base_dir"])
        ),
        "temp_dir": paths["aligned_temp_dir"],
        "evap_dir": paths["aligned_evap_dir"],
    }
    counts: dict[str, int] = {}
    needs_align = False
    label_map = {"prec_dir": "降水", "temp_dir": "气温", "evap_dir": "蒸散发"}
    prepared_inputs: list[dict[str, Any]] = []
    staged_dirs: list[Path] = []

    def log(message: str) -> None:
        if task_id:
            add_task_output(task_id, message)

    def set_progress(**items: Any) -> None:
        if task_id:
            set_task_metadata(task_id, ui_progress=items)

    # Read DEM grid info for validation
    dem_meta = None
    if dem_file.exists():
        with rasterio.open(dem_file) as src:
            dem_meta = {"height": src.height, "width": src.width, "crs": src.crs, "transform": src.transform, "res": src.res}
        log(f"[检查] 已读取 DEM 网格：{dem_meta['width']} x {dem_meta['height']}。")
    else:
        log(f"[检查] 当前工作区缺少 {dem_file.name}，将跳过网格对齐检查。")

    def matches_dem_grid(dataset: Any) -> bool:
        if dem_meta is None:
            return True
        return (
            dataset.height == dem_meta["height"]
            and dataset.width == dem_meta["width"]
            and dataset.crs == dem_meta["crs"]
            and dataset.transform == dem_meta["transform"]
        )

    for key, target_dir in dir_map.items():
        src_dir_raw = str(payload.get(key, "")).strip()
        if not src_dir_raw:
            raise ValueError(f"缺少 {key} 路径。")
        src_dir = resolve_any_path(src_dir_raw, must_exist=True)
        ordered_files = ordered_tif_files_by_timestamp(src_dir)
        if not ordered_files:
            raise ValueError(f"目录 {src_dir} 中没有 .tif 文件。")
        time_scan = scan_tif_time_series(src_dir)
        if time_scan["invalid_files"]:
            sample = "、".join(time_scan["invalid_files"][:3])
            raise ValueError(f"{label_map[key]}目录存在 {len(time_scan['invalid_files'])} 个无法解析时间戳的 tif 文件，例如：{sample}")
        if time_scan["duplicate_timestamps"]:
            first_ts, names = next(iter(time_scan["duplicate_timestamps"].items()))
            raise ValueError(
                f"{label_map[key]}目录存在重复时间戳 {format_timestamp_for_display(first_ts, config.get('时间步长_小时', 24.0))}，例如：{'、'.join(names[:3])}"
            )
        if len(ordered_files) != int(time_scan["valid_time_steps"]):
            raise ValueError(f"{label_map[key]}目录时间扫描异常，无法建立稳定的时间顺序。")
        out_of_range_count = 0
        if expected_time_set is not None:
            filtered_files = [(timestamp, tif_path) for timestamp, tif_path in ordered_files if timestamp in expected_time_set]
            out_of_range_count = len(ordered_files) - len(filtered_files)
            ordered_files = filtered_files
            if not ordered_files:
                raise ValueError(f"{label_map[key]}目录没有落在{time_basis_label}内的 tif 文件。请检查时间设置、事件表或重新选择目录。")
        target_path = Path(target_dir)
        reuse_existing = same_path(src_dir, target_path)
        start_label = format_timestamp_for_display(ordered_files[0][0], config.get("时间步长_小时", 24.0))
        end_label = format_timestamp_for_display(ordered_files[-1][0], config.get("时间步长_小时", 24.0))
        if reuse_existing:
            log(f"[扫描] {label_map[key]}：识别 {len(ordered_files)} 个时间步，范围 {start_label} -> {end_label}。源目录就是当前工作区目录，将直接复用。")
        else:
            log(f"[扫描] {label_map[key]}：识别 {len(ordered_files)} 个时间步，范围 {start_label} -> {end_label}，将按时间顺序导入。")
        if out_of_range_count > 0:
            log(f"[筛选] {label_map[key]}：已自动忽略 {out_of_range_count} 个落在{time_basis_label}之外的 tif 文件。")
        prepared_inputs.append(
            {
                "key": key,
                "label": label_map[key],
                "src_dir": src_dir,
                "target_dir": target_path,
                "ordered_files": ordered_files,
                "reuse_existing": reuse_existing,
                "out_of_range_count": out_of_range_count,
            }
        )

    for item in prepared_inputs:
        target_dir = Path(item["target_dir"])
        if item["reuse_existing"]:
            counts[str(item["key"]).replace("_dir", "")] = len(item["ordered_files"])
            continue
        target_dir.parent.mkdir(parents=True, exist_ok=True)
        stage_dir = target_dir.parent / f".{target_dir.name}__staging_{task_id or uuid.uuid4().hex[:8]}"
        if stage_dir.exists():
            shutil.rmtree(stage_dir)
        stage_dir.mkdir(parents=True, exist_ok=True)
        item["stage_dir"] = stage_dir
        staged_dirs.append(stage_dir)
        existing_count = sum(1 for _ in target_dir.glob("*.tif")) if target_dir.exists() else 0
        if existing_count:
            log(f"[保护] {item['label']}目标目录已有 {existing_count} 个文件，将先写入临时目录，成功后再替换。")

    total_files = sum(0 if item["reuse_existing"] else len(item["ordered_files"]) for item in prepared_inputs)
    processed_all = 0
    if total_files > 0:
        set_progress(stage="准备导入", current=0, total=total_files, label="准备中")
    else:
        set_progress(stage="复用现有文件，正在校验", current=0, total=0, label="复用")

    try:
        for item in prepared_inputs:
            key = str(item["key"])
            label = key.replace("_dir", "")
            if item["reuse_existing"]:
                log(f"[复用] {item['label']}源目录已是当前工作区目录，跳过复制。")
                continue
            stage_dir = Path(item["stage_dir"])
            count = 0
            ordered_files = list(item["ordered_files"])
            total_item = len(ordered_files)
            log(f"[导入] 开始处理{item['label']}，共 {total_item} 个文件。")
            for idx, (timestamp, src_path_obj) in enumerate(ordered_files, start=1):
                src_path = str(src_path_obj)
                fname = Path(src_path).name
                dst_path = stage_dir / fname
                with rasterio.open(src_path) as src:
                    if matches_dem_grid(src):
                        shutil.copy2(src_path, str(dst_path))
                        action = "直接复制"
                    else:
                        needs_align = True
                        out_meta = src.meta.copy()
                        out_meta.update(
                            height=dem_meta["height"], width=dem_meta["width"],
                            transform=dem_meta["transform"], crs=dem_meta["crs"],
                            compress="lzw",
                        )
                        with rasterio.open(dst_path, "w", **out_meta) as dst:
                            for band in range(1, src.count + 1):
                                reproject(
                                    source=rasterio.band(src, band),
                                    destination=rasterio.band(dst, band),
                                    src_transform=src.transform, src_crs=src.crs,
                                    dst_transform=dem_meta["transform"], dst_crs=dem_meta["crs"],
                                    resampling=Resampling.bilinear,
                                )
                        action = "裁剪对齐"
                count += 1
                processed_all += 1
                if _should_report_file_progress(idx, total_item):
                    ts_label = format_timestamp_for_display(timestamp, config.get("时间步长_小时", 24.0))
                    log(f"[进度] {item['label']} {idx}/{total_item} | 总计 {processed_all}/{total_files} | {ts_label} | {action}")
                set_progress(
                    stage=f"正在导入{item['label']}",
                    current=processed_all,
                    total=total_files,
                    label=item["label"],
                    item_current=idx,
                    item_total=total_item,
                    timestamp=format_timestamp_for_display(timestamp, config.get("时间步长_小时", 24.0)),
                )
            counts[label] = count
            log(f"[完成] {item['label']}临时导入完成，共 {count} 个文件。")

        for item in prepared_inputs:
            if item["reuse_existing"]:
                continue
            target_dir = Path(item["target_dir"])
            stage_dir = Path(item["stage_dir"])
            replace_directory_from_stage(target_dir, stage_dir)
            log(f"[替换] {item['label']}已安全更新到当前工作区。")
    finally:
        for stage_dir in staged_dirs:
            if stage_dir.exists():
                shutil.rmtree(stage_dir, ignore_errors=True)

    log("[校验] 开始检查导入后气象驱动的时间覆盖与连续性。")
    forcing = validate_forcing_bundle(config, profile, precip_source=precip_source)
    summary = {
        "prec_count": counts.get("prec", 0),
        "temp_count": counts.get("temp", 0),
        "evap_count": counts.get("evap", 0),
        "preparation_mode": "import_local_tif",
        "preparation_mode_label": "本地栅格导入",
        "prec_source": precip_source,
        "runtime_prec_source": precip_source,
        "configured_precip_source": configured_precip_source(config),
        "aligned": not needs_align,
        "message": "导入完成。" + ("" if not needs_align else " 栅格已自动裁剪对齐到 DEM 网格。"),
        "validation_ok": forcing["ok"],
        "validation_errors": forcing["errors"][:5],
        "validation_warnings": forcing["warnings"][:5],
        "expected_steps": forcing["expected_steps"],
        "valid_steps": forcing["total_valid_steps"],
        "time_basis": forcing.get("time_basis"),
        "time_basis_label": forcing.get("time_basis_label"),
        "import_order": "timestamp_asc",
        "source_dirs": {str(item["key"]).replace("_dir", ""): str(Path(item["src_dir"]).resolve()) for item in prepared_inputs},
        "target_dirs": {str(item["key"]).replace("_dir", ""): str(Path(item["target_dir"]).resolve()) for item in prepared_inputs},
    }
    state_payload = {
        "version": 1,
        "profile": profile,
        "preparation_mode": "import_local_tif",
        "preparation_mode_label": "本地栅格导入",
        "configured_precip_source": configured_precip_source(config),
        "runtime_prec_source": precip_source,
        "source_dirs": {str(item["key"]).replace("_dir", ""): str(Path(item["src_dir"]).resolve()) for item in prepared_inputs},
        "target_dirs": {str(item["key"]).replace("_dir", ""): str(Path(item["target_dir"]).resolve()) for item in prepared_inputs},
        "counts": {
            "prec": int(summary["prec_count"]),
            "temp": int(summary["temp_count"]),
            "evap": int(summary["evap_count"]),
        },
        "required_alignment": bool(needs_align),
        "validation_ok": bool(forcing["ok"]),
        "validation_errors": list(forcing["errors"][:5]),
        "validation_warnings": list(forcing["warnings"][:5]),
        "out_of_range_ignored": {str(item["key"]).replace("_dir", ""): int(item.get("out_of_range_count", 0)) for item in prepared_inputs},
        "expected_steps": forcing["expected_steps"],
        "valid_steps": forcing["total_valid_steps"],
        "time_basis": forcing.get("time_basis"),
        "time_basis_label": forcing.get("time_basis_label"),
        "import_order": "timestamp_asc",
        "completed_at": time.strftime("%Y-%m-%d %H:%M:%S"),
    }
    state_path = write_meteo_state(config, state_payload, profile)
    summary["state_file"] = str(state_path)
    if forcing["ok"]:
        log(f"[完成] 导入完成：降水 {summary['prec_count']}、气温 {summary['temp_count']}、蒸散发 {summary['evap_count']}。气象驱动检查通过。")
    else:
        issue_preview = "；".join((forcing["errors"] + forcing["warnings"])[:3]) or "仍需进一步检查。"
        log(f"[完成] 文件已导入，但气象驱动检查未完全通过：{issue_preview}")
    set_progress(stage="导入完成", current=total_files, total=total_files, label="完成")
    return summary


def import_meteo_files(payload: dict[str, Any]) -> dict[str, Any]:
    """Backward-compatible synchronous meteo import."""
    return perform_meteo_import(payload, task_id=None)


def meteo_import_worker(task_id: str, payload: dict[str, Any]) -> None:
    try:
        result = perform_meteo_import(payload, task_id=task_id)
        _mark_task_finished(task_id, ok=True, return_code=0, result=result)
    except Exception as exc:
        add_task_output(task_id, f"[失败] {exc}")
        _mark_task_finished(task_id, ok=False, return_code=-1)


def start_meteo_import(payload: dict[str, Any]) -> TaskRecord:
    config_path = resolve_any_path(str(payload.get("config_path", "")), must_exist=True)
    config = read_runtime_config(config_path)
    runtime_prec_source = profile_runner.resolve_runtime_precip_source(config, payload.get("prec_source", None))
    task_id = uuid.uuid4().hex[:10]
    record = TaskRecord(
        id=task_id,
        task_type="meteo_import",
        label=f"气象栅格导入 | {config_path.stem}",
        command=["meteo_import"],
        cwd=str(PROJECT_ROOT),
        metadata={
            "config_path": str(config_path.resolve()),
            "profile": current_profile(config),
            "runtime_prec_source": runtime_prec_source,
        },
    )
    with TASK_LOCK:
        TASKS[task_id] = record
    threading.Thread(target=meteo_import_worker, args=(task_id, dict(payload)), daemon=True).start()
    return record


def _resolve_config_related_path(config: dict[str, Any], raw_value: Any) -> Path | None:
    text = str(raw_value or "").strip()
    if not text:
        return None
    candidate = Path(text).expanduser()
    if candidate.is_absolute():
        return candidate.resolve(strict=False)
    config_path_raw = str(config.get("_config_path", "")).strip()
    base_dir = Path(config_path_raw).resolve().parent if config_path_raw else GUI_ROOT
    return (base_dir / candidate).resolve(strict=False)


def _path_state(path: Path | None) -> dict[str, Any]:
    if path is None:
        return {"exists": False, "path": ""}
    resolved = path.resolve(strict=False)
    try:
        stat = resolved.stat()
    except Exception:
        return {"exists": False, "path": str(resolved)}
    return {
        "exists": True,
        "path": str(resolved),
        "mtime_ns": int(getattr(stat, "st_mtime_ns", int(stat.st_mtime * 1e9))),
        "size": int(stat.st_size),
        "is_dir": resolved.is_dir(),
    }


def _forward_runtime_signature(
    config: dict[str, Any],
    config_path: Path,
    profile: str,
    prec_source: str,
    glacier_mode: str,
    prec_dir: str = "",
    objective_mode: str = "auto",
) -> tuple[dict[str, Any], str]:
    paths = build_profile_paths(config, profile)
    boundary = dict(config.get("边界条件", {}))
    time_cfg = dict(config.get("时间", {}) or {})
    init_state = dict(config.get("初始状态", {}) or {})
    _, effective_prec_dir, configured_source = effective_precip_paths(config, profile, precip_source=prec_source)
    prec_dir = Path(prec_dir) if str(prec_dir).strip() else effective_prec_dir
    signature = {
        "config_path": str(config_path.resolve(strict=False)),
        "profile": profile,
        "project_object_type": str(detect_object_type(config) or ""),
        "objective_mode": objective_mode,
        "prec_source": prec_source,
        "configured_precip_source": configured_source,
        "glacier_mode": glacier_mode,
        "prec_dir": _path_state(prec_dir),
        "temp_dir": _path_state(paths["aligned_temp_dir"]),
        "evap_dir": _path_state(paths["aligned_evap_dir"]),
        "glacier_melt_dir": _path_state(paths["glacier_melt_dir"]),
        "flow_acc": _path_state(Path(paths["gis_dir"]) / "flow_accumulation_masked.tif"),
        "glacier_mask": _path_state(Path(paths["gis_dir"]) / "glacier_mask.tif"),
        "glacier_fraction": _path_state(Path(paths["gis_dir"]) / "glacier_fraction.tif"),
        "obs_file": _path_state(_resolve_config_related_path(config, config.get(OBSERVED_FLOW_KEY))),
        "boundary_inflow": _path_state(_resolve_config_related_path(config, boundary.get("上游边界入流_csv"))),
        "boundary_config": {
            "date_field": str(boundary.get("时间字段", "") or ""),
            "flow_field": str(boundary.get("流量字段", "") or ""),
            "gap_fill": str(boundary.get("缺失填补", "") or ""),
        },
        "gis_config": {
            "cfmax_zone_threshold_m": str(config.get("CFMAX分区阈值_m", "") or ""),
            "fao56_mean_elevation_m": str(config.get("FAO56平均海拔_m", "") or ""),
        },
        "runtime_config": {
            "obs_mode": str(config.get("观测口径模式", config.get("观测径流口径模式", "full_year")) or ""),
            "initial_state": {
                key: str(init_state.get(key, profile_runner.DEFAULT_INIT_STATE[key]))
                for key in profile_runner.DEFAULT_INIT_STATE.keys()
            },
        },
        "time_config": {
            "step_hours": normalize_time_step_hours(config.get("时间步长_小时", 24.0)),
            "warmup_start": str(time_cfg.get("预热开始", "") or ""),
            "warmup_end": str(time_cfg.get("预热结束", "") or ""),
            "calib_start": str(time_cfg.get("率定开始", "") or ""),
            "calib_end": str(time_cfg.get("率定结束", "") or ""),
            "valid_start": str(time_cfg.get("验证开始", "") or ""),
            "valid_end": str(time_cfg.get("验证结束", "") or ""),
        },
    }
    token = hashlib.sha1(json.dumps(signature, ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest()
    return signature, token


def _build_forward_runtime_cli_args(
    config_path: Path,
    profile: str,
    *,
    prec_source: str,
    glacier_mode: str,
    prec_dir: str = "",
    objective_mode: str = "auto",
) -> argparse.Namespace:
    cli_args = argparse.Namespace(
        maxiter=1,
        popsize=2,
        seed=42,
        workers=1,
        method="mc_only",
        mc_samples=1,
        init_params_file=None,
        init_bound_shrink=0.0,
        quick_test=False,
        quick_days=30,
    )
    setattr(cli_args, "配置", str(config_path.resolve()))
    setattr(cli_args, "率定模式", profile)
    setattr(cli_args, "目标函数", objective_mode)
    setattr(cli_args, "降水源", prec_source)
    setattr(cli_args, "prec_dir", prec_dir)
    setattr(cli_args, "冰川模式", glacier_mode)
    return cli_args


def _build_forward_legacy_argv(prec_source: str, glacier_mode: str, prec_dir: str = "") -> list[str]:
    argv = [
        "forward_simulation",
        "--maxiter", "1",
        "--popsize", "2",
        "--seed", "42",
        "--workers", "1",
        "--method", "mc_only",
        "--mc-samples", "1",
        "--prec-source", prec_source,
        "--glacier-mode", glacier_mode,
    ]
    if prec_dir:
        argv.extend(["--prec-dir", prec_dir])
    return argv


def _build_forward_result(module: Any, sim: dict[str, Any], metrics: dict[str, Any], *, cache_hit: bool) -> dict[str, Any]:
    series_len = min(len(sim["q_total"]), len(module.Q_OBS_FULL))
    glacier_checks: dict[str, Any] = {}
    if hasattr(module, "compute_glacier_physical_checks"):
        try:
            glacier_checks = module.compute_glacier_physical_checks(sim.get("q_ice_reference"), sim.get("q_ice"))
        except Exception:
            glacier_checks = {}
    reliability_flag = str(getattr(module, "RELIABILITY_FLAG", "ok") or "ok")
    reliability_notes: list[str] = []
    if reliability_flag == "degraded_missing_glacier_elev":
        reliability_notes.append("glacier_elev 缺失，0.1° 冰川子格温度递减未启用；冰川链条物理一致性降级。")
    elif not bool(sim.get("glacier_enabled", False)):
        reliability_notes.append("当前未启用冰川模块。")

    signature_info: dict[str, Any] = {}
    glacier_fraction_info: dict[str, Any] = {}
    if hasattr(module, "compute_swr_penalty"):
        try:
            _, swr_result = module.compute_swr_penalty(
                sim.get("obs_monthly"), sim.get("sim_monthly"),
                weight=float(getattr(module, "SIGNATURE_SWR_WEIGHT", 0.20)),
                tol_ratio=float(getattr(module, "SIGNATURE_SWR_TOL_RATIO", 0.20)),
            )
            signature_info["swr"] = swr_result
        except Exception:
            pass
    if hasattr(module, "compute_peak_month_penalty"):
        try:
            _, peak_result = module.compute_peak_month_penalty(
                sim.get("obs_monthly"), sim.get("sim_monthly"),
                weight=float(getattr(module, "SIGNATURE_PEAK_WEIGHT", 0.10)),
                tol_months=int(getattr(module, "SIGNATURE_PEAK_TOL_MONTHS", 1)),
            )
            signature_info["peak_month"] = peak_result
        except Exception:
            pass
    if hasattr(module, "compute_glacier_fraction_penalty"):
        try:
            frac_q_ice = sim.get("q_ice")
            if hasattr(module, "glacier_fraction_eval_series"):
                frac_q_ice, frac_q_total = module.glacier_fraction_eval_series(sim)
            else:
                frac_q_total = sim.get("q_total")
            _, frac_result = module.compute_glacier_fraction_penalty(
                frac_q_ice, frac_q_total,
                getattr(module, "GLACIER_FRAC_WINDOW", None),
                weight=float(getattr(module, "GLACIER_FRAC_WEIGHT", 0.25)),
            )
            glacier_fraction_info = {
                "window": (
                    list(getattr(module, "GLACIER_FRAC_WINDOW", None))
                    if getattr(module, "GLACIER_FRAC_WINDOW", None) is not None
                    else None
                ),
                "basin_glacier_area_fraction": (
                    float(getattr(module, "BASIN_GLACIER_AREA_FRACTION", float("nan")))
                    if module.np.isfinite(getattr(module, "BASIN_GLACIER_AREA_FRACTION", float("nan")))
                    else None
                ),
                "evaluation_basis": (
                    "local_runoff_calibration_period"
                    if bool(sim.get("boundary_enabled"))
                    else "calibration_period"
                ),
                "result": frac_result,
            }
        except Exception:
            pass

    def to_series(values: Any) -> list[float | None]:
        if values is None:
            return [None] * series_len
        arr = values[:series_len]
        return [float(item) if module.np.isfinite(item) else None for item in arr]

    if hasattr(module, "format_time_value"):
        dates = [module.format_time_value(item) for item in module.SIM_DATES[:series_len]]
    else:
        dates = [str(item) for item in module.SIM_DATES[:series_len]]

    return {
        "dates": dates,
        "q_sim": to_series(sim["q_total"]),
        "q_obs": to_series(module.Q_OBS_FULL),
        "q_rain": to_series(sim.get("q_rain")),
        "q_snow": to_series(sim.get("q_snow")),
        "q_ice": to_series(sim.get("q_ice")),
        "q_boundary_inflow": to_series(sim.get("q_boundary")),
        "q_ice_reference": to_series(sim.get("q_ice_reference")) if sim.get("q_ice_reference") is not None else [None] * series_len,
        "metrics": {
            "nse_cal": round(float(metrics.get("nse_cal", float("nan"))), 4) if module.np.isfinite(metrics.get("nse_cal", float("nan"))) else None,
            "nse_val": round(float(metrics.get("nse_val", float("nan"))), 4) if module.np.isfinite(metrics.get("nse_val", float("nan"))) else None,
            "kge_cal": round(float(metrics.get("kge_cal", float("nan"))), 4) if module.np.isfinite(metrics.get("kge_cal", float("nan"))) else None,
            "kge_val": round(float(metrics.get("kge_val", float("nan"))), 4) if module.np.isfinite(metrics.get("kge_val", float("nan"))) else None,
            "log_nse_cal": round(float(metrics.get("log_nse_cal", float("nan"))), 4) if module.np.isfinite(metrics.get("log_nse_cal", float("nan"))) else None,
            "log_nse_val": round(float(metrics.get("log_nse_val", float("nan"))), 4) if module.np.isfinite(metrics.get("log_nse_val", float("nan"))) else None,
            "pbias_cal": round(float(metrics.get("pbias_cal", float("nan"))), 2) if module.np.isfinite(metrics.get("pbias_cal", float("nan"))) else None,
            "pbias_val": round(float(metrics.get("pbias_val", float("nan"))), 2) if module.np.isfinite(metrics.get("pbias_val", float("nan"))) else None,
            "rmse_cal": round(float(metrics.get("rmse_cal", float("nan"))), 4) if module.np.isfinite(metrics.get("rmse_cal", float("nan"))) else None,
            "rmse_val": round(float(metrics.get("rmse_val", float("nan"))), 4) if module.np.isfinite(metrics.get("rmse_val", float("nan"))) else None,
        },
        "runtime": {
            "cache_hit": bool(cache_hit),
            "glacier_enabled": bool(sim.get("glacier_enabled")),
            "boundary_enabled": bool(sim.get("boundary_enabled")),
            "reliability_flag": reliability_flag,
            "reliability_notes": reliability_notes,
            "glacier_physical_checks": glacier_checks,
            "process_signature_report": dict(signature_info or {}),
            "glacier_fraction_report": dict(glacier_fraction_info or {}),
        },
    }


def _trim_forward_runtime_cache_locked() -> None:
    while len(FORWARD_RUNTIME_CACHE) > MAX_FORWARD_RUNTIME_CACHE:
        oldest_key = min(
            FORWARD_RUNTIME_CACHE.items(),
            key=lambda item: (item[1].last_used, item[1].created_at),
        )[0]
        FORWARD_RUNTIME_CACHE.pop(oldest_key, None)


def _build_forward_payload_context(payload: dict[str, Any]) -> dict[str, Any]:
    run_path = resolve_any_path(str(payload.get("run_path", "")), must_exist=True)
    metadata_path = run_path / "metadata.json"
    if not metadata_path.exists():
        raise FileNotFoundError("结果目录缺少 metadata.json。")
    metadata, resolved_config = normalize_run_metadata(read_json_file(metadata_path), run_path=run_path)
    source_obs_series = _load_run_series_map(run_path, "q_obs")
    source_boundary_series = _load_run_series_map(run_path, "q_boundary_inflow")
    source_boundary_enabled = bool(
        metadata.get("optional_modules", {}).get("boundary_inflow", {}).get("enabled")
        or metadata.get("boundary_condition", {}).get("enabled")
    )

    params = payload.get("params", {})
    if not params:
        raise ValueError("缺少参数。")

    config_path_raw = str(metadata.get("workspace_config", "") or "")
    hint_project_root, hint_gui_root = _workspace_roots_hint_from_metadata(metadata)
    config_path = resolved_config or resolve_workspace_config_reference(
        config_path_raw,
        run_path=run_path,
        project_root=hint_project_root,
        gui_root=hint_gui_root,
    )
    if config_path is None or not config_path.exists():
        raise ValueError("找不到原始工作区配置文件，无法重算结果。")
    config = _apply_run_replay_config_overrides(read_runtime_config(config_path), metadata)
    raw_prec_source = str(
        metadata.get("data_sources", {}).get("runtime_prec_source")
        or metadata.get("data_sources", {}).get("prec_source")
        or metadata.get("data_sources", {}).get("configured_precip_source")
        or profile_runner.configured_precip_source(config)
        or "era5"
    ).strip().lower()
    prec_source = profile_runner.resolve_runtime_precip_source(config, raw_prec_source)
    validation = validate_workspace_fields(str(config_path), stage="forward", precip_source=prec_source, config_override=config)
    forward_missing = list(validation.get("missing", []) or [])
    if source_obs_series:
        forward_missing = [item for item in forward_missing if not str(item).startswith("观测径流")]
    boundary_replay_fallback = False
    if source_boundary_enabled and source_boundary_series:
        boundary_missing = [item for item in forward_missing if "上游边界入流" in str(item)]
        if boundary_missing:
            boundary_replay_fallback = True
            forward_missing = [item for item in forward_missing if "上游边界入流" not in str(item)]
    if forward_missing:
        first_issue = next(iter(forward_missing), "请先完成输入检查。")
        raise ValueError(f"当前工作区还未满足前向重算条件：{first_issue}")
    profile = resolve_profile(config, metadata.get("calibration_profile", metadata.get("rate_mode", "daily")))
    requested_objective_mode = str(
        metadata.get("requested_objective_mode")
        or metadata.get("optimization", {}).get("requested_objective_mode")
        or metadata.get("optimization", {}).get("objective_mode")
        or metadata.get("objective_profile", {}).get("type")
        or metadata.get("objective", {}).get("type")
        or metadata.get("目标函数模式")
        or "auto"
    ).strip().lower() or "auto"
    objective_mode = profile_runner.resolve_objective_mode(
        config,
        requested_objective_mode,
        profile,
    )
    prec_dir = str(metadata.get("data_sources", {}).get("prec_dir", "") or "")
    if prec_source == "custom_tif" and not prec_dir:
        paths = build_profile_paths(config, profile)
        prec_dir = str(Path(paths["aligned_prec_custom_dir"]).resolve(strict=False))
    glacier_mode = str(metadata.get("data_sources", {}).get("glacier_mode", "inline")).strip().lower() or "inline"
    return {
        "run_path": str(run_path.resolve()),
        "run_dir": run_path,
        "config_path": config_path,
        "config": config,
        "profile": profile,
        "requested_objective_mode": requested_objective_mode,
        "objective_mode": objective_mode,
        "prec_source": prec_source,
        "prec_dir": prec_dir,
        "glacier_mode": glacier_mode,
        "params": params,
        "source_metadata": metadata,
        "source_obs_series": source_obs_series,
        "source_boundary_series": source_boundary_series if source_boundary_enabled else {},
        "source_boundary_enabled": source_boundary_enabled,
        "boundary_replay_fallback": boundary_replay_fallback,
    }


def _build_workspace_forward_context(payload: dict[str, Any]) -> dict[str, Any]:
    config_path = resolve_any_path(str(payload.get("config_path", "")), must_exist=True)
    validation = validate_workspace_fields(str(config_path), stage="forward", precip_source=payload.get("prec_source", None))
    if not validation.get("valid"):
        first_issue = next(iter(validation.get("missing", []) or []), "请先完成输入检查。")
        raise ValueError(f"当前工作区还未满足前向重算条件：{first_issue}")
    config = read_runtime_config(config_path)
    profile = resolve_profile(config, str(payload.get("calibration_mode", "")).strip().lower() or None)
    requested_objective_mode = str(payload.get("objective_mode", "") or "").strip().lower() or "auto"
    objective_mode = profile_runner.resolve_objective_mode(config, requested_objective_mode, profile)
    prec_source = profile_runner.resolve_runtime_precip_source(config, payload.get("prec_source", None))
    prec_dir = str(payload.get("prec_dir", "") or "").strip()
    if prec_source == "custom_tif":
        paths = build_profile_paths(config, profile)
        prec_dir = str(paths["aligned_prec_custom_dir"])
    glacier_mode = str(payload.get("glacier_mode", "inline")).strip().lower() or "inline"
    return {
        "config_path": config_path,
        "config": config,
        "profile": profile,
        "requested_objective_mode": requested_objective_mode,
        "objective_mode": objective_mode,
        "prec_source": prec_source,
        "prec_dir": prec_dir,
        "glacier_mode": glacier_mode,
        "source_boundary_enabled": False,
        "boundary_replay_fallback": False,
    }


def _prepare_forward_runtime_config(context: dict[str, Any]) -> dict[str, Any]:
    runtime_config = copy.deepcopy(context["config"])
    if bool(context.get("boundary_replay_fallback")):
        boundary_cfg = dict(runtime_config.get("边界条件", {}) or {})
        if boundary_cfg.get("上游边界入流_csv"):
            # Falling back to the saved source-run series means runtime loading
            # must not touch a stale boundary CSV path first.
            boundary_cfg["上游边界入流_csv"] = ""
            runtime_config["边界条件"] = boundary_cfg
    return runtime_config


def _get_or_create_forward_runtime(
    context: dict[str, Any],
    *,
    stage_callback: Callable[[str, str | None], None] | None = None,
    output_callback: Callable[[str], None] | None = None,
) -> tuple[ForwardRuntimeCacheEntry, bool]:
    config_path = Path(context["config_path"])
    config = _prepare_forward_runtime_config(context)
    profile = str(context["profile"]).strip().lower()
    objective_mode = str(context.get("objective_mode", "auto") or "auto").strip().lower() or "auto"
    prec_source = profile_runner.resolve_runtime_precip_source(config, context["prec_source"])
    legacy_prec_source = profile_runner.resolve_legacy_precip_source(prec_source)
    prec_dir = str(context.get("prec_dir", "") or "").strip()
    glacier_mode = str(context["glacier_mode"]).strip().lower() or "inline"
    _, data_token = _forward_runtime_signature(config, config_path, profile, prec_source, glacier_mode, prec_dir, objective_mode)
    cache_key = f"{config_path.resolve()}|{profile}|{objective_mode}|{prec_source}|{prec_dir}|{glacier_mode}|{data_token}"

    with FORWARD_RUNTIME_CACHE_LOCK:
        cached = FORWARD_RUNTIME_CACHE.get(cache_key)
        if cached is not None:
            cached.last_used = time.time()
            if stage_callback is not None:
                stage_callback("命中缓存", "[阶段] 命中缓存：复用已加载的气象与地理数据。")
            return cached, True

        if stage_callback is not None:
            stage_callback("加载 HBV 核心", "[阶段] 加载 HBV 核心")
        module = call_with_output_capture(
            output_callback,
            profile_runner.load_legacy_module,
            profile_runner.old_script_path(config, "model", "calibrate_hbv_cryo.py"),
        )
        cli_args = _build_forward_runtime_cli_args(
            config_path,
            profile,
            prec_source=prec_source,
            glacier_mode=glacier_mode,
            prec_dir=prec_dir,
            objective_mode=objective_mode,
        )
        profile_runner.patch_runtime_environment(module, config, profile, cli_args)
        profile_runner.patch_profile_behavior(module, config, profile, objective_mode)
        base_parse_args = module.parse_args

        def parse_args_with_runtime_source() -> argparse.Namespace:
            parsed = base_parse_args()
            parsed.prec_source = prec_source
            return parsed

        module.parse_args = parse_args_with_runtime_source
        with profile_runner.temporary_argv(_build_forward_legacy_argv(legacy_prec_source, glacier_mode, prec_dir)):
            module.args = module.parse_args()
        module.configure_time_step()
        if stage_callback is not None:
            stage_callback(
                "加载气象与地理数据",
                "[阶段] 加载气象与地理数据；首次运行会写出 prec/temp/evap 缓存，请耐心等待。",
            )
        call_with_output_capture(output_callback, module.load_all_data)

        entry = ForwardRuntimeCacheEntry(
            key=cache_key,
            config_path=str(config_path.resolve()),
            profile=profile,
            prec_source=prec_source,
            glacier_mode=glacier_mode,
            data_token=data_token,
            module=module,
            observation_state=_capture_forward_observation_state(module),
        )
        FORWARD_RUNTIME_CACHE[cache_key] = entry
        _trim_forward_runtime_cache_locked()
        return entry, False


def _run_forward_simulation(
    payload: dict[str, Any],
    *,
    stage_callback: Callable[[str, str | None], None] | None = None,
    output_callback: Callable[[str], None] | None = None,
) -> dict[str, Any]:
    if stage_callback is not None:
        stage_callback("读取工作区配置", "[阶段] 读取工作区配置")
    context = _build_forward_payload_context(payload)
    entry, cache_hit = _get_or_create_forward_runtime(
        context,
        stage_callback=stage_callback,
        output_callback=output_callback,
    )

    with entry.lock:
        entry.last_used = time.time()
        module = entry.module
        _restore_forward_observation_state(module, entry.observation_state)
        params = dict(context["params"])
        base_params = dict(context.get("source_metadata", {}).get("optimized_params", {}) or {})
        started_at = time.time()
        if stage_callback is not None:
            stage_callback("执行前向模拟", "[阶段] 执行前向模拟")
        param_vector, clean_params, adjusted = build_runtime_param_vector(module, params, base_params=base_params)
        obs_restored = _restore_forward_observed_series(module, context.get("source_obs_series", {}))
        sim = call_with_output_capture(output_callback, module.run_simulation, param_vector)
        boundary_restored = False
        if bool(context.get("boundary_replay_fallback")):
            boundary_restored = _restore_forward_boundary_series(module, sim, context.get("source_boundary_series", {}))
        if stage_callback is not None:
            stage_callback("计算指标", "[阶段] 计算指标")
        metrics = call_with_output_capture(output_callback, module.compute_metrics, sim["q_total"])
        result = _build_forward_result(module, sim, metrics, cache_hit=cache_hit)
        runtime_config = dict(context["config"])
        profile = str(context["profile"]).strip().lower()
        prec_source = profile_runner.resolve_runtime_precip_source(runtime_config, context.get("prec_source", None))
        prec_dir = str(context.get("prec_dir", "") or "").strip()
        glacier_mode = str(context.get("glacier_mode", "inline") or "inline").strip().lower() or "inline"
        requested_objective_mode = str(context.get("requested_objective_mode", "auto") or "auto").strip().lower() or "auto"
        objective_mode = str(context.get("objective_mode", "auto") or "auto").strip().lower() or "auto"
        configured_source = configured_precip_source(runtime_config)
        _, effective_prec_dir, _ = effective_precip_paths(runtime_config, profile, precip_source=prec_source)
        runtime_prec_dir = str(Path(prec_dir).resolve(strict=False)) if prec_dir else str(Path(effective_prec_dir).resolve(strict=False))
        result["runtime_prec_source"] = prec_source
        result["configured_precip_source"] = configured_source
        result["prec_dir"] = runtime_prec_dir
        result["glacier_mode"] = glacier_mode
        result["objective_mode"] = objective_mode
        result["requested_objective_mode"] = requested_objective_mode
        result["profile"] = profile
        result["runtime"].update(
            {
                "prec_source": prec_source,
                "configured_precip_source": configured_source,
                "prec_dir": runtime_prec_dir,
                "glacier_mode": glacier_mode,
                "objective_mode": objective_mode,
                "requested_objective_mode": requested_objective_mode,
                "profile": profile,
            }
        )
        result["runtime"]["obs_restored_from_run"] = bool(obs_restored)
        result["runtime"]["boundary_restored_from_run"] = bool(boundary_restored)
        result["runtime"]["params_adjusted"] = bool(adjusted)
        result["params"] = clean_params
        if bool(payload.get("save_run", False)):
            run_path, saved_metadata = call_with_output_capture(
                output_callback,
                _persist_forward_run,
                module,
                context,
                param_vector,
                clean_params,
                sim,
                cache_hit=cache_hit,
                obs_replayed_from_source_run=bool(obs_restored),
                boundary_replayed_from_source_run=bool(boundary_restored),
                started_at=started_at,
                stage_callback=stage_callback,
            )
            result["run_path"] = str(run_path.resolve())
            result["run_name"] = run_path.name
            result["workspace_config"] = str(Path(context["config_path"]).resolve())
            result["saved_metrics"] = saved_metadata.get("metrics", {})
        if stage_callback is not None:
            stage_callback("完成", "[阶段] 完成")
        return result


def forward_simulate(payload: dict[str, Any]) -> dict[str, Any]:
    """Run a forward simulation with user-provided parameters and return time series."""
    return _run_forward_simulation(payload)


def replay_saved_run(run_path_raw: str, *, save_run: bool = True) -> dict[str, Any]:
    run_path = resolve_any_path(run_path_raw, must_exist=True)
    metadata_path = run_path / "metadata.json"
    if not metadata_path.exists():
        raise FileNotFoundError("结果目录缺少 metadata.json。")
    metadata = read_json_file(metadata_path)
    params = dict(metadata.get("optimized_params", {}) or {})
    if not params:
        parameters_file = run_path / "parameters.txt"
        if parameters_file.exists():
            parsed: dict[str, float] = {}
            for raw_line in parameters_file.read_text(encoding="utf-8-sig").splitlines():
                line = str(raw_line or "").strip()
                if (not line) or ("=" not in line):
                    continue
                name, raw_value = line.split("=", 1)
                name = str(name or "").strip()
                value = safe_float(raw_value)
                if name and value is not None:
                    parsed[name] = float(value)
            params = parsed
    if not params:
        raise ValueError("历史结果缺少 optimized_params，且 parameters.txt 未解析出有效参数。")
    return forward_simulate(
        {
            "run_path": str(run_path.resolve(strict=False)),
            "params": params,
            "save_run": bool(save_run),
        }
    )


def _run_csv_preview(run_path: Path, *, limit: int = 3) -> dict[str, Any]:
    csv_path = run_path / "simulation.csv"
    if not csv_path.exists():
        return {"columns": [], "rows": []}
    with csv_path.open("r", encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        rows: list[dict[str, Any]] = []
        for idx, row in enumerate(reader):
            if idx >= max(int(limit), 0):
                break
            rows.append(dict(row))
        return {"columns": list(reader.fieldnames or []), "rows": rows}


def _run_csv_date_bounds(run_path: Path) -> dict[str, Any]:
    csv_path = run_path / "simulation.csv"
    if not csv_path.exists():
        return {"first_date": None, "last_date": None, "row_count": 0}
    first_date = None
    last_date = None
    row_count = 0
    with csv_path.open("r", encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            row_count += 1
            current = str(row.get("date", "") or "").strip() or None
            if first_date is None:
                first_date = current
            last_date = current
    return {"first_date": first_date, "last_date": last_date, "row_count": row_count}


def _read_run_metrics_snapshot(run_path: Path) -> dict[str, Any]:
    metadata = read_json_file(run_path / "metadata.json")
    metrics = dict(metadata.get("metrics", {}) or {})
    calibration = dict(metrics.get("calibration", {}) or {})
    validation = dict(metrics.get("validation", {}) or {})
    return {
        "nse_cal": safe_float(calibration.get("nse")),
        "nse_val": safe_float(validation.get("nse")),
        "kge_val": safe_float(validation.get("kge")),
        "pbias_val": safe_float(validation.get("pbias")),
    }


def _prepare_saved_run_runtime(module: Any, tag: str, *, started_at: float | None = None) -> None:
    run_id = f"{time.strftime('%Y%m%d_%H%M%S')}_{tag}_{uuid.uuid4().hex[:6]}"
    os.makedirs(module.LOG_DIR, exist_ok=True)
    os.makedirs(module.RUNS_DIR, exist_ok=True)
    os.makedirs(module.CACHE_DIR, exist_ok=True)
    module.RUN_ID = run_id
    module.LOG_FILE = os.path.join(module.LOG_DIR, f"hbv_cryo_{run_id}.log")
    module.PROGRESS_FILE = os.path.join(module.LOG_DIR, f"progress_{run_id}.csv")
    module.PROGRESS_FILE_MAIN = module.PROGRESS_FILE
    module.PROGRESS_FILE_REFINE = None
    module.start_time = float(started_at) if started_at is not None else time.time()
    module.gen_count = 0
    module.eval_count = 0
    module.best_score = float("-inf")
    if hasattr(module, "best_objective"):
        module.best_objective = float("inf")
    module.best_params = None


def _prepare_manual_start_runtime(module: Any) -> None:
    _prepare_saved_run_runtime(module, "manual")


def _resolve_manual_start_params(module: Any, payload: dict[str, Any]) -> tuple[list[float], dict[str, float], str]:
    raw_params = dict(payload.get("params", {}) or {})
    clean_input = sanitize_param_values(raw_params) if raw_params else {}
    source = "user_params" if clean_input else "default_test_vector"
    vector, params, adjusted = build_runtime_param_vector(module, clean_input)
    if adjusted:
        source = f"{source}_adjusted"
    return vector, params, source


def _finalize_manual_start_metadata(
    run_path: Path,
    *,
    module: Any,
    context: dict[str, Any],
    params: dict[str, float],
    starter_source: str,
    cache_hit: bool,
) -> dict[str, Any]:
    metadata_path = run_path / "metadata.json"
    if not metadata_path.exists():
        raise FileNotFoundError("手调起点结果未生成 metadata.json。")
    metadata = read_json_file(metadata_path)
    workspace_root_hint, workspace_gui_root_hint = _placeholder_roots_for_config_path(context["config_path"])
    optimization = dict(metadata.get("optimization", {}))
    optimization.update(
        {
            "method": "manual_start",
            "method_label": "手调起点",
            "mc_samples": 0,
            "maxiter": 0,
            "popsize": 0,
            "tol": 0.0,
            "workers": 0,
            "debug_days": 0,
            "init_params_file": "",
            "init_bound_shrink": 0.0,
            "starter_param_source": starter_source,
        }
    )
    requested_objective_mode = str(context.get("requested_objective_mode", "") or "").strip().lower()
    objective_mode = str(context.get("objective_mode", "") or "").strip().lower()
    if requested_objective_mode:
        optimization["objective_mode"] = requested_objective_mode
        optimization["requested_objective_mode"] = requested_objective_mode
    if objective_mode:
        optimization["effective_objective_mode"] = objective_mode
    metadata["optimization"] = optimization
    if requested_objective_mode:
        metadata["requested_objective_mode"] = requested_objective_mode
    if objective_mode:
        metadata["effective_objective_mode"] = objective_mode
    metadata["workspace_config"] = to_portable_path(str(Path(context["config_path"]).resolve(strict=False)))
    metadata["workspace_root_hint"] = str(workspace_root_hint.resolve(strict=False))
    metadata["workspace_gui_root_hint"] = str(workspace_gui_root_hint.resolve(strict=False))
    metadata["calibration_profile"] = str(context["profile"])
    metadata["rate_mode"] = str(context["profile"])
    metadata["project_object_type"] = str(detect_object_type(context["config"]) or metadata.get("project_object_type", ""))
    if getattr(module, "PARAMETER_PROFILE", None):
        metadata["parameter_profile"] = module.PARAMETER_PROFILE
    if getattr(module, "OBJECTIVE_PROFILE", None):
        metadata["objective_profile"] = module.OBJECTIVE_PROFILE
    data_sources = dict(metadata.get("data_sources", {}))
    runtime_prec_source = str(getattr(module.args, "prec_source", "") or "").strip().lower() or configured_precip_source(context["config"])
    runtime_prec_dir = str(context.get("prec_dir", "") or data_sources.get("prec_dir", "") or "").strip()
    glacier_mode = str(context.get("glacier_mode", "") or data_sources.get("glacier_mode", "") or "inline").strip().lower() or "inline"
    data_sources["prec_source"] = runtime_prec_source
    data_sources["configured_precip_source"] = configured_precip_source(context["config"])
    data_sources["runtime_prec_source"] = runtime_prec_source
    if runtime_prec_dir:
        data_sources["prec_dir"] = runtime_prec_dir
    data_sources["glacier_mode"] = glacier_mode
    metadata["data_sources"] = data_sources
    replay_context = dict(metadata.get("replay_context", {}))
    if context.get("source_obs_series"):
        replay_context["obs_replayed_from_source_run"] = True
    if bool(context.get("source_boundary_enabled")):
        boundary_condition = dict(metadata.get("boundary_condition", {}))
        boundary_condition["replayed_from_source_run"] = True
        metadata["boundary_condition"] = boundary_condition
        optional_modules = dict(metadata.get("optional_modules", {}))
        boundary_module = dict(optional_modules.get("boundary_inflow", {}))
        boundary_module["replayed_from_source_run"] = True
        optional_modules["boundary_inflow"] = boundary_module
        metadata["optional_modules"] = optional_modules
        replay_context["boundary_replayed_from_source_run"] = True
    if replay_context:
        replay_context["source_run_path"] = str(Path(context["run_dir"]).resolve())
        replay_context["source_workspace_root"] = str(workspace_root_hint.resolve(strict=False))
        metadata["replay_context"] = replay_context
    metadata["optimized_params"] = params
    metadata["starter_result"] = {
        "enabled": True,
        "label": "手调起点",
        "param_source": starter_source,
        "cache_hit": bool(cache_hit),
    }
    metadata["result_title"] = "手调起点"
    metadata = portableize_value_paths(metadata)
    metadata_path.write_text(json_dumps_safe(metadata, indent=2), encoding="utf-8")
    return metadata


def _finalize_saved_forward_metadata(
    run_path: Path,
    *,
    module: Any,
    context: dict[str, Any],
    params: dict[str, float],
    cache_hit: bool,
    obs_replayed_from_source_run: bool,
    boundary_replayed_from_source_run: bool,
) -> dict[str, Any]:
    metadata_path = run_path / "metadata.json"
    if not metadata_path.exists():
        raise FileNotFoundError("手调结果未生成 metadata.json。")
    metadata = read_json_file(metadata_path)
    workspace_root_hint, workspace_gui_root_hint = _placeholder_roots_for_config_path(context["config_path"])
    optimization = dict(metadata.get("optimization", {}))
    optimization.update(
        {
            "method": "manual_adjustment",
            "method_label": "手调后重算",
            "mc_samples": 0,
            "maxiter": 0,
            "popsize": 0,
            "tol": 0.0,
            "workers": 0,
            "debug_days": 0,
            "init_params_file": "",
            "init_bound_shrink": 0.0,
            "source_run_path": str(Path(context["run_dir"]).resolve()),
            "source_run_name": Path(context["run_dir"]).name,
        }
    )
    requested_objective_mode = str(context.get("requested_objective_mode", "") or "").strip().lower()
    objective_mode = str(context.get("objective_mode", "") or "").strip().lower()
    if requested_objective_mode:
        optimization["objective_mode"] = requested_objective_mode
        optimization["requested_objective_mode"] = requested_objective_mode
    if objective_mode:
        optimization["effective_objective_mode"] = objective_mode
    metadata["optimization"] = optimization
    if requested_objective_mode:
        metadata["requested_objective_mode"] = requested_objective_mode
    if objective_mode:
        metadata["effective_objective_mode"] = objective_mode
    metadata["workspace_config"] = to_portable_path(str(Path(context["config_path"]).resolve(strict=False)))
    metadata["workspace_root_hint"] = str(workspace_root_hint.resolve(strict=False))
    metadata["workspace_gui_root_hint"] = str(workspace_gui_root_hint.resolve(strict=False))
    metadata["calibration_profile"] = str(context["profile"])
    metadata["rate_mode"] = str(context["profile"])
    metadata["project_object_type"] = str(detect_object_type(context["config"]) or metadata.get("project_object_type", ""))
    if getattr(module, "PARAMETER_PROFILE", None):
        metadata["parameter_profile"] = module.PARAMETER_PROFILE
    if getattr(module, "OBJECTIVE_PROFILE", None):
        metadata["objective_profile"] = module.OBJECTIVE_PROFILE
    data_sources = dict(metadata.get("data_sources", {}))
    runtime_prec_source = str(getattr(module.args, "prec_source", "") or "").strip().lower() or configured_precip_source(context["config"])
    runtime_prec_dir = str(context.get("prec_dir", "") or data_sources.get("prec_dir", "") or "").strip()
    glacier_mode = str(context.get("glacier_mode", "") or data_sources.get("glacier_mode", "") or "inline").strip().lower() or "inline"
    data_sources["prec_source"] = runtime_prec_source
    data_sources["configured_precip_source"] = configured_precip_source(context["config"])
    data_sources["runtime_prec_source"] = runtime_prec_source
    if runtime_prec_dir:
        data_sources["prec_dir"] = runtime_prec_dir
    data_sources["glacier_mode"] = glacier_mode
    metadata["data_sources"] = data_sources
    metadata["optimized_params"] = params
    replay_context = dict(metadata.get("replay_context", {}))
    replay_context["source_run_path"] = str(Path(context["run_dir"]).resolve())
    replay_context["source_workspace_root"] = str(workspace_root_hint.resolve(strict=False))
    if obs_replayed_from_source_run:
        replay_context["obs_replayed_from_source_run"] = True
    if boundary_replayed_from_source_run:
        boundary_condition = dict(metadata.get("boundary_condition", {}))
        boundary_condition["replayed_from_source_run"] = True
        metadata["boundary_condition"] = boundary_condition
        optional_modules = dict(metadata.get("optional_modules", {}))
        boundary_module = dict(optional_modules.get("boundary_inflow", {}))
        boundary_module["replayed_from_source_run"] = True
        optional_modules["boundary_inflow"] = boundary_module
        metadata["optional_modules"] = optional_modules
        replay_context["boundary_replayed_from_source_run"] = True
    if replay_context:
        metadata["replay_context"] = replay_context
    metadata["manual_result"] = {
        "enabled": True,
        "label": "手调结果",
        "source_run_path": str(Path(context["run_dir"]).resolve()),
        "source_run_name": Path(context["run_dir"]).name,
        "cache_hit": bool(cache_hit),
    }
    metadata["result_title"] = "手调结果"
    metadata = portableize_value_paths(metadata)
    metadata_path.write_text(json_dumps_safe(metadata, indent=2), encoding="utf-8")
    return metadata


def _persist_forward_run(
    module: Any,
    context: dict[str, Any],
    param_vector: list[float],
    params: dict[str, float],
    sim: dict[str, Any],
    *,
    cache_hit: bool,
    obs_replayed_from_source_run: bool,
    boundary_replayed_from_source_run: bool,
    started_at: float | None = None,
    stage_callback: Callable[[str, str | None], None] | None = None,
) -> tuple[Path, dict[str, Any]]:
    if stage_callback is not None:
        stage_callback("写出手调结果", "[阶段] 写出新的手调结果目录")
    _prepare_saved_run_runtime(module, "manual", started_at=started_at)
    original_run_simulation = module.run_simulation
    original_method = getattr(module.args, "method", None)

    def cached_run_simulation(x: Any, *args: Any, **kwargs: Any) -> Any:
        try:
            vector = [float(v) for v in x]
            if len(vector) == len(param_vector) and all(abs(a - b) <= 1e-10 for a, b in zip(vector, param_vector)):
                return sim
        except Exception:
            pass
        return original_run_simulation(x, *args, **kwargs)

    module.run_simulation = cached_run_simulation
    setattr(module.args, "method", "manual_adjustment")
    try:
        module.save_results(argparse.Namespace(x=param_vector, nfev=1))
    finally:
        module.run_simulation = original_run_simulation
        setattr(module.args, "method", original_method)

    run_path = Path(module.RUNS_DIR) / f"hbv_cryo_{module.args.prec_source}_{module.args.glacier_mode}_{module.RUN_ID}"
    if stage_callback is not None:
        stage_callback("整理结果元数据", "[阶段] 补充手调结果元数据")
    metadata = _finalize_saved_forward_metadata(
        run_path,
        module=module,
        context=context,
        params=params,
        cache_hit=cache_hit,
        obs_replayed_from_source_run=obs_replayed_from_source_run,
        boundary_replayed_from_source_run=boundary_replayed_from_source_run,
    )
    return run_path, metadata


def _create_manual_start_result(
    payload: dict[str, Any],
    *,
    stage_callback: Callable[[str, str | None], None] | None = None,
    output_callback: Callable[[str], None] | None = None,
) -> dict[str, Any]:
    if stage_callback is not None:
        stage_callback("读取工作区配置", "[阶段] 读取工作区配置")
    context = _build_workspace_forward_context(payload)
    entry, cache_hit = _get_or_create_forward_runtime(
        context,
        stage_callback=stage_callback,
        output_callback=output_callback,
    )

    with entry.lock:
        entry.last_used = time.time()
        module = entry.module
        _restore_forward_observation_state(module, entry.observation_state)
        if stage_callback is not None:
            stage_callback("整理起调参数", "[阶段] 生成手调起点参数")
        param_vector, params, starter_source = _resolve_manual_start_params(module, payload)
        _prepare_manual_start_runtime(module)
        if stage_callback is not None:
            stage_callback("写出手调起点结果", "[阶段] 执行一次完整模拟并写出可手调结果")
        call_with_output_capture(output_callback, module.save_results, argparse.Namespace(x=param_vector, nfev=1))
        run_path = Path(module.RUNS_DIR) / f"hbv_cryo_{module.args.prec_source}_{module.args.glacier_mode}_{module.RUN_ID}"
        if stage_callback is not None:
            stage_callback("整理结果元数据", "[阶段] 补充手调起点元数据")
        metadata = _finalize_manual_start_metadata(
            run_path,
            module=module,
            context=context,
            params=params,
            starter_source=starter_source,
            cache_hit=cache_hit,
        )
        metrics = metadata.get("metrics", {})
        calibration = metrics.get("calibration", {})
        validation = metrics.get("validation", {})
        if stage_callback is not None:
            stage_callback("完成", "[阶段] 完成")
        return {
            "run_path": str(run_path.resolve()),
            "run_name": run_path.name,
            "workspace_config": str(Path(context["config_path"]).resolve()),
            "metrics": {
                "nse_cal": calibration.get("nse"),
                "nse_val": validation.get("nse"),
                "kge_cal": calibration.get("kge"),
                "kge_val": validation.get("kge"),
                "pbias_cal": calibration.get("pbias"),
                "pbias_val": validation.get("pbias"),
            },
            "param_source": starter_source,
            "cache_hit": bool(cache_hit),
        }


def forward_sim_worker(task_id: str, payload: dict[str, Any]) -> None:
    last_stage = ""

    def report(stage: str, message: str | None = None) -> None:
        nonlocal last_stage
        last_stage = stage
        set_task_metadata(task_id, ui_progress={"stage": stage, "label": "保存并重算"})
        if message:
            add_task_output(task_id, message)

    try:
        report("准备启动", "[阶段] 准备启动")
        result = _run_forward_simulation(
            payload,
            stage_callback=report,
            output_callback=lambda line: add_task_output(task_id, line),
        )
        if result.get("run_path"):
            set_task_metadata(task_id, run_path=result["run_path"])
            with TASK_LOCK:
                task = TASKS.get(task_id)
                if task is not None:
                    task.detected_runs = [str(result["run_path"])]
        _mark_task_finished(task_id, ok=True, return_code=0, result=result)
    except Exception as exc:
        if last_stage:
            set_task_metadata(task_id, ui_progress={"stage": last_stage, "label": "保存并重算"})
        add_task_output(task_id, f"[失败] {exc}")
        _mark_task_finished(task_id, ok=False, return_code=-1)


def manual_start_worker(task_id: str, payload: dict[str, Any]) -> None:
    last_stage = ""

    def report(stage: str, message: str | None = None) -> None:
        nonlocal last_stage
        last_stage = stage
        set_task_metadata(task_id, ui_progress={"stage": stage, "label": "手调起点"})
        if message:
            add_task_output(task_id, message)

    try:
        report("准备启动", "[阶段] 准备生成手调起点")
        result = _create_manual_start_result(
            payload,
            stage_callback=report,
            output_callback=lambda line: add_task_output(task_id, line),
        )
        set_task_metadata(task_id, run_path=result["run_path"])
        with TASK_LOCK:
            task = TASKS.get(task_id)
            if task is not None:
                task.detected_runs = [result["run_path"]]
        _mark_task_finished(task_id, ok=True, return_code=0, result=result)
    except Exception as exc:
        if last_stage:
            set_task_metadata(task_id, ui_progress={"stage": last_stage, "label": "手调起点"})
        add_task_output(task_id, f"[失败] {exc}")
        _mark_task_finished(task_id, ok=False, return_code=-1)


def _forecast_restart_args(payload: dict[str, Any]) -> argparse.Namespace:
    config_path = str(payload.get("config_path", payload.get("config", "")) or "").strip()
    source_run = str(payload.get("source_run", payload.get("run_path", "")) or "").strip()
    if not config_path:
        run_path = resolve_any_path(source_run, must_exist=True)
        metadata = read_json_file(run_path / "metadata.json")
        config_path = str(metadata.get("workspace_config", "") or "").strip()
    if not config_path:
        raise ValueError("缺少工作区配置路径。")
    if not source_run:
        raise ValueError("缺少源结果目录。")
    forecast_end = str(payload.get("forecast_end", "") or "").strip()
    if not forecast_end:
        raise ValueError("缺少预报结束时间 forecast_end。")
    return argparse.Namespace(
        config=config_path,
        source_run=source_run,
        forecast_start=str(payload.get("forecast_start", "") or "").strip(),
        forecast_end=forecast_end,
        forecast_prec_dir=str(payload.get("forecast_prec_dir", payload.get("prec_dir", "")) or "").strip(),
        forecast_temp_dir=str(payload.get("forecast_temp_dir", payload.get("temp_dir", "")) or "").strip(),
        forecast_evap_dir=str(payload.get("forecast_evap_dir", payload.get("evap_dir", "")) or "").strip(),
        profile=str(payload.get("profile", payload.get("calibration_mode", "")) or "").strip(),
        objective_mode=str(payload.get("objective_mode", "") or "").strip(),
        prec_source=str(payload.get("prec_source", "custom_tif") or "custom_tif").strip(),
        glacier_mode=str(payload.get("glacier_mode", "inline") or "inline").strip(),
        output_dir=str(payload.get("output_dir", "") or "").strip(),
        output_json="",
    )


def forecast_restart(payload: dict[str, Any]) -> dict[str, Any]:
    ensure_forecast_input_ready(payload)
    import forecast_run

    return forecast_run.run_forecast(_forecast_restart_args(payload))


def forecast_restart_with_progress(payload: dict[str, Any], stage_callback: Callable[[str, str | None], None]) -> dict[str, Any]:
    import forecast_run

    return forecast_run.run_forecast(_forecast_restart_args(payload), stage_callback=stage_callback)


def _forecast_source_state_time(source_run: Path, metadata: dict[str, Any]) -> str:
    initial_state = dict(metadata.get("initial_state", {}) or {})
    time_config = dict(metadata.get("time_config", {}) or {})
    state_time = str(
        initial_state.get("state_snapshot_time")
        or time_config.get("forecast_end")
        or time_config.get("valid_end")
        or time_config.get("calib_end")
        or ""
    ).strip()
    if state_time:
        return state_time
    csv_path = source_run / "simulation.csv"
    if csv_path.exists():
        try:
            frame = pd.read_csv(csv_path, usecols=["date"])
            if not frame.empty:
                return str(frame["date"].iloc[-1])
        except Exception:
            pass
    return ""


def _forecast_expected_index(start_raw: str, end_raw: str, step_hours: float) -> pd.DatetimeIndex:
    step = normalize_time_step_hours(step_hours)
    start_ts = pd.to_datetime(start_raw)
    end_ts = pd.to_datetime(end_raw)
    if step < 24.0 and is_date_only_string(end_raw):
        end_ts = end_ts + pd.Timedelta(days=1) - pd.Timedelta(hours=step)
    if end_ts < start_ts:
        return pd.DatetimeIndex([])
    return pd.date_range(start_ts, end_ts, freq=pd.Timedelta(hours=step))


def _forecast_input_dir_summary(
    *,
    key: str,
    label: str,
    raw_path: str,
    step_hours: float,
    expected_index: pd.DatetimeIndex | None,
) -> dict[str, Any]:
    raw_text = str(raw_path or "").strip()
    if not raw_text:
        return {
            "key": key,
            "label": label,
            "path": "",
            "status": "fail",
            "summary": f"请选择预报{label}栅格目录。",
            "errors": [f"请选择预报{label}栅格目录。"],
            "warnings": [],
            "total_files": 0,
            "valid_time_steps": 0,
            "expected_steps": int(len(expected_index)) if expected_index is not None else 0,
            "covered_steps": 0,
            "missing_steps": 0,
            "out_of_window_steps": 0,
        }
    directory = resolve_any_path(raw_text, must_exist=False)
    check = validate_tif_time_series(label, directory, step_hours, expected_index, "预报窗口")
    expected_steps = int(len(expected_index)) if expected_index is not None else 0
    missing_count = int(len(check.get("missing_steps", []) or []))
    out_count = int(len(check.get("out_of_range_steps", []) or []))
    valid_steps = int(check.get("valid_time_steps", 0) or 0)
    covered_steps = max(0, expected_steps - missing_count) if expected_steps else valid_steps
    errors = [str(item) for item in list(check.get("errors", []) or [])]
    warnings = [str(item) for item in list(check.get("warnings", []) or [])]
    if errors:
        status = "fail"
    elif warnings or expected_steps <= 0:
        status = "warn"
    else:
        status = "ok"
    if expected_steps > 0:
        summary = f"{covered_steps}/{expected_steps} 个预报时步可用"
        if out_count:
            summary += f"，另有 {out_count} 个窗口外文件将不参与本次预报"
    else:
        summary = f"识别到 {valid_steps} 个有效时间步，填写预报时段后可核对覆盖"
    timestamps = list(check.get("timestamps", []) or [])
    return {
        "key": key,
        "label": label,
        "path": str(directory.resolve(strict=False)),
        "status": status,
        "summary": summary,
        "errors": errors,
        "warnings": warnings,
        "total_files": int(check.get("total_files", 0) or 0),
        "valid_time_steps": valid_steps,
        "expected_steps": expected_steps,
        "covered_steps": covered_steps,
        "missing_steps": missing_count,
        "out_of_window_steps": out_count,
        "first_time": _format_time_for_check(timestamps[0], step_hours) if timestamps else "",
        "last_time": _format_time_for_check(timestamps[-1], step_hours) if timestamps else "",
    }


def _forecast_output_preview(payload: dict[str, Any], source_run: Path) -> dict[str, Any]:
    source_name = source_run.name or "source_result"
    name_pattern = f"hbv_forecast_{source_name}_运行时间_编号"
    output_dir_raw = str(payload.get("output_dir", "") or "").strip()
    if output_dir_raw:
        output_dir = resolve_any_path(output_dir_raw, must_exist=False)
        archive_root = output_dir / "forecast_inputs"
        manifest_path = archive_root / "input_manifest.json"
        return {
            "explicit": True,
            "result_parent": str(output_dir.parent.resolve(strict=False)),
            "result_dir": str(output_dir.resolve(strict=False)),
            "result_name_pattern": output_dir.name,
            "result_label": "指定结果目录",
            "result_detail": str(output_dir.resolve(strict=False)),
            "archive_label": "指定目录下的 forecast_inputs",
            "archive_root": str(archive_root.resolve(strict=False)),
            "manifest_path": str(manifest_path.resolve(strict=False)),
            "archive_detail": str(manifest_path.resolve(strict=False)),
        }

    result_parent = source_run.parent
    config_path_raw = str(payload.get("config_path", "") or "").strip()
    if config_path_raw:
        try:
            cfg_path = resolve_any_path(config_path_raw, must_exist=True)
            config = read_runtime_config(cfg_path)
            result_parent = Path(build_workspace_paths(config)["results_root"]).resolve(strict=False)
        except Exception:
            result_parent = source_run.parent
    result_detail = str((result_parent / name_pattern).resolve(strict=False))
    return {
        "explicit": False,
        "result_parent": str(result_parent.resolve(strict=False)),
        "result_dir": "",
        "result_name_pattern": name_pattern,
        "result_label": "运行时新建预报结果目录",
        "result_detail": result_detail,
        "archive_label": "结果目录下的 forecast_inputs",
        "archive_root": "",
        "manifest_path": "结果目录/forecast_inputs/input_manifest.json",
        "archive_detail": f"{result_detail}\\forecast_inputs\\input_manifest.json",
    }


def forecast_input_check(payload: dict[str, Any]) -> dict[str, Any]:
    source_run_raw = str(payload.get("source_run", payload.get("run_path", "")) or "").strip()
    if not source_run_raw:
        return {
            "status": "fail",
            "headline": "请先选择预报源结果。",
            "errors": ["请先选择预报源结果。"],
            "warnings": [],
            "items": [],
            "variables": [],
        }
    source_run = resolve_any_path(source_run_raw, must_exist=True)
    metadata = read_json_file(source_run / "metadata.json")
    initial_state = dict(metadata.get("initial_state", {}) or {})
    time_config = dict(metadata.get("time_config", {}) or {})
    params = dict(metadata.get("optimized_params", {}) or {})
    step_hours = normalize_time_step_hours(time_config.get("time_step_hours", payload.get("time_step_hours", 24.0)))
    source_state_time = _forecast_source_state_time(source_run, metadata)
    errors: list[str] = []
    warnings: list[str] = []
    if not params:
        errors.append("源结果缺少率定参数，不能作为连续状态预报起点。")
    snapshot_file = str(initial_state.get("state_snapshot_file", "") or "").strip() or "state_snapshot.npz"
    snapshot_path = source_run / snapshot_file
    state_available = bool(snapshot_path.exists() or initial_state.get("state_snapshot_available"))
    if not state_available:
        errors.append("源结果缺少可用于起报的保存状态。")
    expected_start = ""
    if source_state_time:
        expected_start = _format_time_for_check(pd.to_datetime(source_state_time) + pd.Timedelta(hours=step_hours), step_hours)
    else:
        errors.append("源结果未记录状态时刻，不能推断预报起报时间。")
    requested_start_raw = str(payload.get("forecast_start", "") or "").strip()
    forecast_start = requested_start_raw or expected_start
    forecast_end = str(payload.get("forecast_end", "") or "").strip()
    expected_index: pd.DatetimeIndex | None = None
    if not forecast_end:
        warnings.append("尚未填写预报结束时间。")
    if forecast_start and forecast_end:
        try:
            expected_index = _forecast_expected_index(forecast_start, forecast_end, step_hours)
            if expected_index.empty:
                errors.append("预报结束时间不能早于起报时间。")
            elif requested_start_raw and expected_start and pd.Timestamp(pd.to_datetime(forecast_start)) != pd.Timestamp(pd.to_datetime(expected_start)):
                errors.append(f"起报时间必须紧接源结果保存状态，当前应从 {expected_start} 起报。")
        except Exception as exc:
            errors.append(f"预报时段无法解析：{exc}")
    variables = [
        _forecast_input_dir_summary(key="prec", label="降水", raw_path=str(payload.get("forecast_prec_dir", payload.get("prec_dir", "")) or ""), step_hours=step_hours, expected_index=expected_index),
        _forecast_input_dir_summary(key="temp", label="气温", raw_path=str(payload.get("forecast_temp_dir", payload.get("temp_dir", "")) or ""), step_hours=step_hours, expected_index=expected_index),
        _forecast_input_dir_summary(key="evap", label="潜在蒸散发", raw_path=str(payload.get("forecast_evap_dir", payload.get("evap_dir", "")) or ""), step_hours=step_hours, expected_index=expected_index),
    ]
    for item in variables:
        errors.extend(str(msg) for msg in list(item.get("errors", []) or []))
        warnings.extend(str(msg) for msg in list(item.get("warnings", []) or []))
    expected_steps = int(len(expected_index)) if expected_index is not None else 0
    status = "fail" if errors else "warn" if warnings or expected_steps <= 0 else "ok"
    headline = (
        f"预报气象覆盖完整：{forecast_start} 至 {forecast_end}，共 {expected_steps} 个时间步。"
        if status == "ok"
        else "预报气象输入仍需核对。"
    )
    output_preview = _forecast_output_preview(payload, source_run)
    output_status = "ok" if expected_steps > 0 else "warn"
    return {
        "status": status,
        "headline": headline,
        "errors": sorted(set(errors)),
        "warnings": sorted(set(warnings)),
        "source": {
            "source_run": str(source_run.resolve(strict=False)),
            "source_run_name": source_run.name,
            "parameter_count": int(len(params)),
            "state_available": state_available,
            "source_state_time": _format_time_for_check(source_state_time, step_hours),
            "expected_forecast_start": expected_start,
        },
        "window": {
            "forecast_start": forecast_start,
            "forecast_end": forecast_end,
            "time_step_hours": float(step_hours),
            "expected_steps": expected_steps,
        },
        "output": output_preview,
        "variables": variables,
        "items": [
            {"label": "源结果", "value": source_run.name, "status": "ok"},
            {"label": "起报状态", "value": _format_time_for_check(source_state_time, step_hours) or "未记录", "status": "ok" if source_state_time and state_available else "fail"},
            {"label": "建议起报", "value": expected_start or "未形成", "status": "ok" if expected_start else "fail"},
            {"label": "预报时段", "value": f"{forecast_start} 至 {forecast_end}" if forecast_start and forecast_end else "未完整填写", "status": "ok" if expected_steps > 0 else "warn"},
            {"label": "参数来源", "value": f"源结果参数（{len(params)} 项）" if params else "缺少参数", "status": "ok" if params else "fail"},
            {"label": "归档方式", "value": "运行时仅归档预报窗口内 P/T/PET 栅格", "status": "ok" if expected_steps > 0 else "warn"},
            {"label": "结果输出", "value": output_preview["result_label"], "detail": output_preview["result_detail"], "status": output_status},
            {"label": "输入清单", "value": output_preview["archive_label"], "detail": output_preview["archive_detail"], "status": output_status},
        ],
    }


def ensure_forecast_input_ready(payload: dict[str, Any]) -> dict[str, Any]:
    check = forecast_input_check(payload)
    if str(check.get("status", "")).lower() == "fail":
        issues = [str(item) for item in list(check.get("errors", []) or []) if str(item).strip()]
        message = "；".join(issues[:3]) if issues else "预报气象输入检查未通过。"
        raise ValueError(f"连续状态预报输入检查未通过：{message}")
    return check


def forecast_restart_worker(task_id: str, payload: dict[str, Any]) -> None:
    last_stage = ""

    def report(stage: str, message: str | None = None) -> None:
        nonlocal last_stage
        last_stage = stage
        set_task_metadata(task_id, ui_progress={"stage": stage, "label": "连续状态预报"})
        if message:
            add_task_output(task_id, message)

    try:
        report("准备启动", "[阶段] 准备连续状态预报")
        result = forecast_restart_with_progress(payload, report)
        if result.get("run_path"):
            set_task_metadata(task_id, run_path=result["run_path"])
            with TASK_LOCK:
                task = TASKS.get(task_id)
                if task is not None:
                    task.detected_runs = [str(result["run_path"])]
        _mark_task_finished(task_id, ok=True, return_code=0, result=result)
    except Exception as exc:
        if last_stage:
            set_task_metadata(task_id, ui_progress={"stage": last_stage, "label": "连续状态预报"})
        add_task_output(task_id, f"[失败] {exc}")
        _mark_task_finished(task_id, ok=False, return_code=-1)


def start_forward_simulation(payload: dict[str, Any]) -> TaskRecord:
    context = _build_forward_payload_context(payload)
    run_path = Path(context["run_dir"])
    task_id = uuid.uuid4().hex[:10]
    record = TaskRecord(
        id=task_id,
        task_type="forward_sim",
        label=f"保存并重算 | {run_path.name}",
        command=["forward_sim"],
        cwd=str(PROJECT_ROOT),
        metadata={
            "config_path": str(Path(context["config_path"]).resolve()),
            "run_path": str(run_path.resolve()),
            "profile": context["profile"],
            "runtime_prec_source": context["prec_source"],
            "objective_mode": context["objective_mode"],
            "glacier_mode": context["glacier_mode"],
        },
    )
    with TASK_LOCK:
        TASKS[task_id] = record
    threading.Thread(target=forward_sim_worker, args=(task_id, dict(payload)), daemon=True).start()
    return record


def start_forecast_restart(payload: dict[str, Any]) -> TaskRecord:
    args = _forecast_restart_args(payload)
    source_run = resolve_any_path(args.source_run, must_exist=True)
    input_check = ensure_forecast_input_ready(payload)
    task_id = uuid.uuid4().hex[:10]
    record = TaskRecord(
        id=task_id,
        task_type="forecast_restart",
        label=f"连续状态预报 | {source_run.name}",
        command=["forecast_restart"],
        cwd=str(PROJECT_ROOT),
        metadata={
            "config_path": str(resolve_any_path(args.config, must_exist=True).resolve(strict=False)),
            "run_path": str(source_run.resolve(strict=False)),
            "forecast_start": args.forecast_start,
            "forecast_end": args.forecast_end,
            "runtime_prec_source": args.prec_source,
            "glacier_mode": args.glacier_mode,
            "forecast_input_check": input_check,
            "ui_progress": {"stage": "准备启动", "label": "连续状态预报"},
        },
    )
    with TASK_LOCK:
        TASKS[task_id] = record
    threading.Thread(target=forecast_restart_worker, args=(task_id, dict(payload)), daemon=True).start()
    return record


def start_manual_start(payload: dict[str, Any]) -> TaskRecord:
    config_path = resolve_any_path(str(payload.get("config_path", "")), must_exist=True)
    current = find_running_task("manual_start", str(config_path))
    if current is not None:
        return current
    context = _build_workspace_forward_context({**payload, "config_path": str(config_path)})
    config = context["config"]
    task_id = uuid.uuid4().hex[:10]
    record = TaskRecord(
        id=task_id,
        task_type="manual_start",
        label=f"手调起点 | {str(config.get('流域名称', config_path.stem)).strip() or config_path.stem}",
        command=["manual_start"],
        cwd=str(PROJECT_ROOT),
        metadata={
            "config_path": str(config_path.resolve()),
            "profile": context["profile"],
            "runtime_prec_source": context["prec_source"],
            "objective_mode": context["objective_mode"],
            "glacier_mode": context["glacier_mode"],
            "ui_progress": {"stage": "准备启动", "label": "手调起点"},
        },
    )
    with TASK_LOCK:
        TASKS[task_id] = record
    threading.Thread(target=manual_start_worker, args=(task_id, dict(payload)), daemon=True).start()
    return record


class StudioHandler(BaseHTTPRequestHandler):
    server_version = "HBVStudio/3.0"
    CONNECTION_GONE_ERRORS = (BrokenPipeError, ConnectionAbortedError, ConnectionResetError)

    def log_message(self, fmt: str, *args: Any) -> None:
        return

    def send_json(self, payload: dict[str, Any], status: int = 200) -> bool:
        body = json_dumps_safe(payload).encode("utf-8")
        try:
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return True
        except self.CONNECTION_GONE_ERRORS:
            self.close_connection = True
            return False

    def send_error_json(self, message: str, status: int = 400) -> bool:
        return self.send_json({"ok": False, "error": message}, status=status)

    def read_json_body(self) -> dict[str, Any]:
        length = int(self.headers.get("Content-Length", "0"))
        body = self.rfile.read(length) if length > 0 else b"{}"
        return json.loads(body.decode("utf-8")) if body else {}

    def do_GET(self) -> None:
        mark_server_activity()
        parsed = urlparse(self.path)
        if parsed.path.startswith("/api/"):
            self.handle_api_get(parsed)
        else:
            self.serve_static(parsed.path)

    def do_POST(self) -> None:
        mark_server_activity()
        parsed = urlparse(self.path)
        if not parsed.path.startswith("/api/"):
            self.send_error_json("不支持的路径。", status=404)
            return
        self.handle_api_post(parsed)

    def handle_api_get(self, parsed: Any) -> None:
        query = parse_qs(parsed.query)
        try:
            if parsed.path == "/api/health":
                self.send_json({
                    "ok": True,
                    "time": time.time(),
                    "server_time": time.strftime("%Y-%m-%d %H:%M:%S"),
                    "server_started_at": SERVER_STARTED_AT,
                    "server_started_at_text": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(SERVER_STARTED_AT)),
                    "version": APP_VERSION,
                })
            elif parsed.path == "/api/dashboard":
                self.send_json({"ok": True, "data": dashboard_payload()})
            elif parsed.path == "/api/templates":
                self.send_json({"ok": True, "data": list_templates()})
            elif parsed.path in {"/api/workspaces", "/api/configs"}:
                self.send_json({"ok": True, "data": list_workspaces()})
            elif parsed.path in {"/api/workspace", "/api/config"}:
                path, data = load_workspace_config(unquote(query.get("path", [""])[0]))
                self.send_json({"ok": True, "path": str(path.resolve()), "display_path": to_display_path(path), "data": data})
            elif parsed.path == "/api/runs":
                self.send_json({"ok": True, "data": list_runs()})
            elif parsed.path == "/api/run":
                self.send_json({"ok": True, "data": load_run_detail(unquote(query.get("path", [""])[0]))})
            elif parsed.path == "/api/tasks":
                self.send_json({"ok": True, "data": list_tasks()})
            elif parsed.path == "/api/cdsapi/status":
                self.send_json({"ok": True, "data": cdsapi_status()})
            elif parsed.path == "/api/fs/list":
                raw_path = unquote(query.get("path", [""])[0])
                exts = [item for item in query.get("extensions", [""])[0].split(",") if item]
                kind = query.get("kind", ["file"])[0] or "file"
                self.send_json({"ok": True, "data": list_filesystem(raw_path, exts, kind=kind)})
            elif parsed.path == "/api/obs-info":
                csv_path = unquote(query.get("path", [""])[0])
                date_field = query.get("date_field", [""])[0] or None
                target_step_hours_raw = query.get("target_step_hours", [""])[0]
                target_step_hours = float(target_step_hours_raw) if target_step_hours_raw else None
                self.send_json(
                    {
                        "ok": True,
                        "data": inspect_observed_csv(
                            csv_path,
                            date_field=date_field,
                            target_step_hours=target_step_hours,
                        ),
                    }
                )
            elif parsed.path == "/api/suggest/bbox":
                self.send_json({"ok": True, "data": fill_bbox_from_shp(unquote(query.get("shp_path", [""])[0]))})
            elif parsed.path == "/api/suggest/cfmax-threshold":
                shp = unquote(query.get("shp_path", [""])[0])
                dem = unquote(query.get("dem_path", [""])[0]) or str(BUILTIN_DEM.resolve())
                self.send_json({"ok": True, "data": suggest_cfmax_threshold(shp, dem)})
            elif parsed.path == "/api/data-prep/steps":
                raw_config = unquote(query.get("config_path", [""])[0])
                profile = PROFILE_DAILY
                config = None
                if raw_config:
                    _, config = load_workspace_config(raw_config)
                    profile = current_profile(config)
                self.send_json(
                    {
                        "ok": True,
                        "data": [
                            {
                                "id": step["id"],
                                "title": step["title"],
                                "description": step["description"],
                                "depends_on": step.get("depends_on", []),
                                "optional": bool(step.get("optional", False)),
                                "manual": bool(step.get("manual", False)),
                                "needs_prec_source": bool(step.get("needs_prec_source", False)),
                                "supports_overwrite": bool(step.get("supports_overwrite", False)),
                            }
                            for step in (resolve_data_prep_step(item, config) for item in data_prep_steps(profile))
                        ],
                    }
                )
            elif parsed.path == "/api/data-prep/status":
                self.send_json({
                    "ok": True,
                    "data": get_data_prep_status(
                        unquote(query.get("config_path", [""])[0]),
                        precip_source=unquote(query.get("prec_source", [""])[0]),
                    ),
                })
            elif parsed.path == "/api/config/validate":
                stage = query.get("stage", ["calibration"])[0] or "calibration"
                self.send_json({
                    "ok": True,
                    "data": validate_workspace_fields(
                        unquote(query.get("config_path", [""])[0]),
                        stage=stage,
                        precip_source=unquote(query.get("prec_source", [""])[0]),
                    ),
                })
            elif parsed.path == "/api/wizard/validate-step":
                config_path = unquote(query.get("config_path", [""])[0])
                step = int(query.get("step", ["1"])[0])
                self.send_json({
                    "ok": True,
                    "data": wizard_validate_step(
                        config_path,
                        step,
                        precip_source=unquote(query.get("prec_source", [""])[0]),
                    ),
                })
            elif parsed.path == "/api/boundary-preview":
                csv_path = unquote(query.get("path", [""])[0])
                date_field = query.get("date_field", ["date"])[0] or "date"
                flow_field = query.get("flow_field", ["inflow_m3s"])[0] or "inflow_m3s"
                config_path = unquote(query.get("config_path", [""])[0])
                expected_start = query.get("expected_start", [""])[0] or ""
                expected_end = query.get("expected_end", [""])[0] or ""
                expected_step_hours_raw = query.get("expected_step_hours", [""])[0]
                expected_step_hours = float(expected_step_hours_raw) if expected_step_hours_raw else None
                self.send_json(
                    {
                        "ok": True,
                        "data": boundary_preview(
                            csv_path,
                            date_field,
                            flow_field,
                            config_path_raw=config_path,
                            expected_start=expected_start,
                            expected_end=expected_end,
                            expected_step_hours=expected_step_hours,
                        ),
                    }
                )
            elif parsed.path == "/api/workspace/completeness":
                quick = query.get("quick", ["0"])[0] in {"1", "true", "yes"}
                self.send_json({
                    "ok": True,
                    "data": workspace_completeness(
                        unquote(query.get("config_path", [""])[0]),
                        quick=quick,
                        precip_source=unquote(query.get("prec_source", [""])[0]),
                    ),
                })
            elif parsed.path == "/api/workspace/detailed-check":
                self.send_json({
                    "ok": True,
                    "data": workspace_detailed_check(
                        unquote(query.get("config_path", [""])[0]),
                        precip_source=unquote(query.get("prec_source", [""])[0]),
                    ),
                })
            elif parsed.path == "/api/workspace/layout":
                raw_path = unquote(query.get("config_path", [""])[0] or query.get("path", [""])[0])
                self.send_json({"ok": True, "data": workspace_layout_summary(raw_path)})
            elif parsed.path == "/api/workspace/advice":
                self.send_json({
                    "ok": True,
                    "data": workspace_advice(
                        unquote(query.get("config_path", [""])[0]),
                        precip_source=unquote(query.get("prec_source", [""])[0]),
                    ),
                })
            elif parsed.path == "/api/manual-presets":
                self.send_json(
                    {
                        "ok": True,
                        "data": list_manual_presets(
                            unquote(query.get("config_path", [""])[0]),
                            unquote(query.get("calibration_profile", [""])[0]),
                            scope=unquote(query.get("scope", ["workspace"])[0]),
                        ),
                    }
                )
            else:
                self.send_error_json("未知接口。", status=404)
        except FileNotFoundError as exc:
            self.send_error_json(str(exc), status=404)
        except ValueError as exc:
            self.send_error_json(str(exc), status=400)
        except Exception as exc:
            self.send_error_json(str(exc), status=500)
            traceback.print_exc()

    def handle_api_post(self, parsed: Any) -> None:
        try:
            payload = self.read_json_body()
            if parsed.path in {"/api/workspace/save", "/api/config/save"}:
                raw_path = str(payload.get("path", "")).strip()
                if not raw_path:
                    raise ValueError("缺少工作区配置保存路径。")
                path = resolve_any_path(raw_path, must_exist=False)
                normalized = normalize_config_before_save(payload.get("data", {}), path)
                write_json_file(path, normalized)
                self.send_json({"ok": True, "path": str(path.resolve()), "display_path": to_display_path(path), "data": read_json_file(path)})
            elif parsed.path == "/api/template/instantiate":
                self.send_json({"ok": True, "data": instantiate_template(payload)}, status=201)
            elif parsed.path in {"/api/import-workspace", "/api/auto-config"}:
                self.send_json({"ok": True, "data": create_workspace_from_import(payload)}, status=201)
            elif parsed.path == "/api/bootstrap/start":
                self.send_json({"ok": True, "task": start_bootstrap(payload).as_dict()}, status=201)
            elif parsed.path == "/api/data-prep/start":
                self.send_json({"ok": True, "task": start_data_prep(payload).as_dict()}, status=201)
            elif parsed.path == "/api/calibration/start":
                self.send_json({"ok": True, "task": start_calibration(payload).as_dict()}, status=201)
            elif parsed.path == "/api/self-check/start":
                self.send_json({"ok": True, "task": start_self_check().as_dict()}, status=201)
            elif parsed.path == "/api/template/sync-tuotuohe":
                self.send_json({"ok": True, "task": start_tuotuohe_sync(payload).as_dict()}, status=201)
            elif parsed.path == "/api/wizard/save-step":
                self.send_json({"ok": True, "data": wizard_save_step(payload)})
            elif parsed.path == "/api/gis/import":
                self.send_json({"ok": True, "data": import_gis_files(payload)})
            elif parsed.path == "/api/meteo/import/start":
                self.send_json({"ok": True, "task": start_meteo_import(payload).as_dict()}, status=201)
            elif parsed.path == "/api/meteo/import":
                self.send_json({"ok": True, "data": import_meteo_files(payload)})
            elif parsed.path == "/api/simulate/forward/start":
                self.send_json({"ok": True, "task": start_forward_simulation(payload).as_dict()}, status=201)
            elif parsed.path == "/api/simulate/forward":
                self.send_json({"ok": True, "data": forward_simulate(payload)})
            elif parsed.path == "/api/forecast/restart/start":
                self.send_json({"ok": True, "task": start_forecast_restart(payload).as_dict()}, status=201)
            elif parsed.path == "/api/forecast/restart":
                self.send_json({"ok": True, "data": forecast_restart(payload)})
            elif parsed.path == "/api/forecast/input-check":
                self.send_json({"ok": True, "data": forecast_input_check(payload)})
            elif parsed.path == "/api/manual-start/start":
                self.send_json({"ok": True, "task": start_manual_start(payload).as_dict()}, status=201)
            elif parsed.path == "/api/manual-preset/save":
                self.send_json({"ok": True, "data": save_manual_preset(payload)})
            elif parsed.path == "/api/manual-preset/delete":
                self.send_json({"ok": True, "data": delete_manual_preset(payload)})
            elif parsed.path == "/api/run/export-excel":
                self.send_json({"ok": True, "data": export_run_excel(payload)})
            elif parsed.path == "/api/run/rename":
                self.send_json({"ok": True, "data": rename_run(payload)})
            elif parsed.path == "/api/run/delete":
                self.send_json({"ok": True, "data": delete_run(str(payload.get("path", "")).strip())})
            elif parsed.path == "/api/workspace/delete":
                raw_path = str(payload.get("path", "")).strip()
                if not raw_path:
                    raise ValueError("缺少工作区路径。")
                self.send_json({"ok": True, "data": delete_workspace(raw_path)})
            elif parsed.path == "/api/fs/open-path":
                self.send_json({"ok": True, "data": open_path_in_explorer(payload)})
            elif parsed.path == "/api/app/window-unload":
                mark_server_activity(unload=True)
                self.send_json({"ok": True, "data": {"accepted": True}})
            elif parsed.path == "/api/app/quit":
                if has_running_tasks():
                    self.send_error_json("当前仍有运行中的任务，请等待结束后再退出程序。", status=409)
                    return
                self.send_json({"ok": True, "data": {"accepted": True}})
                request_server_shutdown(self.server, "[HBV-Studio] 收到退出请求，正在关闭本地服务。", delay_sec=0.2)
            else:
                self.send_error_json("未知接口。", status=404)
        except FileNotFoundError as exc:
            self.send_error_json(str(exc), status=404)
        except ValueError as exc:
            self.send_error_json(str(exc), status=400)
        except json.JSONDecodeError as exc:
            self.send_error_json(f"JSON 请求体无效：{exc}", status=400)
        except Exception as exc:
            self.send_error_json(str(exc), status=500)
            traceback.print_exc()

    def serve_static(self, raw_path: str) -> None:
        request_path = raw_path or "/"
        if request_path == "/":
            request_path = "/index.html"
        local_path = ensure_within(WEB_ROOT, WEB_ROOT / request_path.lstrip("/"))
        if local_path.is_dir():
            local_path = local_path / "index.html"
        if not local_path.exists() and request_path == "/plotly.min.js":
            bundled_plotly = bundled_plotly_js_path()
            if bundled_plotly is not None:
                local_path = bundled_plotly
        if not local_path.exists():
            self.send_error(HTTPStatus.NOT_FOUND, "Not Found")
            return
        content = local_path.read_bytes()
        content_type = mimetypes.guess_type(str(local_path))[0] or "application/octet-stream"
        try:
            self.send_response(200)
            self.send_header("Content-Type", f"{content_type}; charset=utf-8")
            self.send_header("Content-Length", str(len(content)))
            self.send_header("Cache-Control", "no-cache, must-revalidate")
            self.end_headers()
            self.wfile.write(content)
        except self.CONNECTION_GONE_ERRORS:
            self.close_connection = True


class ExclusiveThreadingHTTPServer(ThreadingHTTPServer):
    allow_reuse_address = False
    daemon_threads = True

    def server_bind(self) -> None:
        # Windows allows multiple listeners on the same port when SO_REUSEADDR is set.
        # Force exclusive binding so a stale HBV-Studio instance cannot silently coexist.
        if os.name == "nt":
            try:
                self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
            except (AttributeError, OSError):
                pass
        super().server_bind()


def run_server(host: str = "127.0.0.1", port: int = 8765) -> None:
    WORKSPACE_DIR.mkdir(parents=True, exist_ok=True)
    TEMPLATE_DIR.mkdir(parents=True, exist_ok=True)
    mark_server_activity()
    print(f"HBV-Studio server v{APP_VERSION} on {host}:{port}")
    server = ExclusiveThreadingHTTPServer((host, port), StudioHandler)
    threading.Thread(target=monitor_server_lifecycle, args=(server,), daemon=True).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
