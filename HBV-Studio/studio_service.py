#!/usr/bin/env python
# -*- coding: utf-8 -*-
from __future__ import annotations

import argparse
import copy
import csv
import hashlib
import io
import json
import math
import mimetypes
import os
import re
import shutil
import socket
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
from services.app_lifecycle import AppLifecycleContext
from services.app_lifecycle import app_quit as build_app_quit
from services.app_lifecycle import app_window_unload as build_app_window_unload
from services.api_routes import GET_ROUTE_HANDLERS as GET_API_ROUTE_HANDLERS
from services.api_routes import POST_ROUTE_HANDLERS as POST_API_ROUTE_HANDLERS
from services.data_prep import (
    DataPrepBootstrapContext,
    DataPrepContext,
    DataPrepStartContext,
    DataPrepTaskOutputContext,
    DataPrepWorkflowWorkerContext,
    data_prep_bootstrap_plan as build_data_prep_bootstrap_plan,
    data_prep_start_plan as build_data_prep_start_plan,
    data_prep_step_command as build_data_prep_step_command,
    data_prep_workflow_worker_run as build_data_prep_workflow_worker_run,
    data_prep_status as build_data_prep_status,
    data_prep_steps_payload as build_data_prep_steps_payload,
    verify_data_prep_step_output as build_verify_data_prep_step_output,
    verify_data_prep_task_output as build_verify_data_prep_task_output,
)
from services.boundary import BoundaryPreviewContext, boundary_preview as build_boundary_preview
from services.calibration import CalibrationStartContext
from services.calibration import calibration_start_plan as build_calibration_start_plan
from services.dashboard import DashboardContext, dashboard_payload as build_dashboard_payload
from services.filesystem import (
    FilesystemContext,
    list_drives as build_list_drives,
    list_filesystem as build_list_filesystem,
    open_path_in_explorer as build_open_path_in_explorer,
    safe_iterdir as build_safe_iterdir,
)
from services.forecast_input import ForecastInputCheckContext
from services.forecast_input import ensure_forecast_input_ready as build_ensure_forecast_input_ready
from services.forecast_input import forecast_input_check as build_forecast_input_check
from services.forecast_restart import ForecastRestartStartContext
from services.forecast_restart import ForecastRestartRunContext
from services.forecast_restart import forecast_restart_args as build_forecast_restart_args
from services.forecast_restart import forecast_restart_run as build_forecast_restart_run
from services.forecast_restart import forecast_restart_run_with_progress as build_forecast_restart_run_with_progress
from services.forecast_restart import ForecastRestartWorkerContext
from services.forecast_restart import forecast_restart_worker_run as build_forecast_restart_worker_run
from services.forecast_restart import forecast_restart_start_plan as build_forecast_restart_start_plan
from services.forward_simulation import ForwardSimulationStartContext
from services.forward_simulation import ForwardSimulationWorkerContext
from services.forward_simulation import forward_simulation_start_plan as build_forward_simulation_start_plan
from services.forward_simulation import forward_simulation_worker_run as build_forward_simulation_worker_run
from services.geo_suggestions import GeoSuggestionContext
from services.geo_suggestions import fill_bbox_from_shp as build_bbox_from_shp
from services.geo_suggestions import suggest_cfmax_threshold as build_suggest_cfmax_threshold
from services.geo_overview import GeoOverviewContext
from services.geo_overview import workspace_basin_geojson as build_workspace_basin_geojson
from services.geo_overview import workspace_dem_png as build_workspace_dem_png
from services.geo_overview import workspace_elevation_zones_geojson as build_workspace_elevation_zones_geojson
from services.geo_overview import workspace_glacier_geojson as build_workspace_glacier_geojson
from services.geo_overview import workspace_geo_overview as build_workspace_geo_overview
from services.geo_overview import workspace_station_geojson as build_workspace_station_geojson
from services.manual_start import ManualStartStartContext
from services.manual_start import ManualStartWorkerContext
from services.manual_start import manual_start_start_plan as build_manual_start_start_plan
from services.manual_start import manual_start_worker_run as build_manual_start_worker_run
from services.manual_presets import ManualPresetContext
from services.manual_presets import _source_run_metadata_for_preset as build_source_run_metadata_for_preset
from services.manual_presets import delete_manual_preset as build_delete_manual_preset
from services.manual_presets import find_manual_preset as build_find_manual_preset
from services.manual_presets import list_manual_presets as build_list_manual_presets
from services.manual_presets import load_manual_preset_store as build_load_manual_preset_store
from services.manual_presets import manual_preset_store_path as build_manual_preset_store_path
from services.manual_presets import save_manual_preset as build_save_manual_preset
from services.manual_presets import write_manual_preset_store as build_write_manual_preset_store
from services.meteo_import import MeteoImportStartContext
from services.meteo_import import MeteoImportWorkerContext
from services.meteo_import import meteo_import_start_plan as build_meteo_import_start_plan
from services.meteo_import import meteo_import_worker_run as build_meteo_import_worker_run
from services.meteo_status import cdsapi_status as build_cdsapi_status
from services.observed import ObservedInfoContext, observed_info as build_observed_info
from services.runs import RunCalibrationTaskContext, RunDetailContext, RunDiscoveryContext, RunExportContext, RunListContext, RunMetadataCompatibilityContext, RunMutationContext
from services.runs import RunMetadataObjectTypeContext
from services.runs import RunReplayConfigContext, RunSourceReferenceContext, RunSummaryContext, RunWorkspaceNameContext
from services.runs import apply_run_replay_config_overrides as build_apply_run_replay_config_overrides
from services.runs import build_calibration_task_result as build_run_calibration_task_result
from services.runs import capture_forward_observation_state as build_capture_forward_observation_state
from services.runs import delete_run as build_delete_run
from services.runs import discover_run_entries as build_discover_run_entries
from services.runs import discover_runtime_roots as build_discover_runtime_roots
from services.runs import export_run_excel as build_export_run_excel
from services.runs import finalize_run_metadata_sections as build_finalize_run_metadata_sections
from services.runs import build_run_summary as build_run_summary_payload
from services.runs import first_existing_path as build_first_existing_path
from services.runs import has_custom_result_title as build_has_custom_result_title
from services.runs import infer_selected_result_stage as build_infer_selected_result_stage
from services.runs import is_studio_editable_metadata as build_is_studio_editable_metadata
from services.runs import iter_run_dirs as build_iter_run_dirs
from services.runs import iter_run_parent_dirs as build_iter_run_parent_dirs
from services.runs import list_runs as build_list_runs
from services.runs import load_run_detail as build_load_run_detail
from services.runs import load_run_series_map as build_load_run_series_map
from services.runs import metadata_boundary_enabled as build_metadata_boundary_enabled
from services.runs import normalize_result_title as build_normalize_result_title
from services.runs import normalize_metadata_object_type as build_normalize_metadata_object_type
from services.runs import normalized_method_label as build_normalized_method_label
from services.runs import normalized_selected_result_label as build_normalized_selected_result_label
from services.runs import optimization_stage_has_execution as build_optimization_stage_has_execution
from services.runs import optimization_stage_payload as build_optimization_stage_payload
from services.runs import pick_latest_run_path as build_pick_latest_run_path
from services.runs import prepare_run_metadata_sections as build_prepare_run_metadata_sections
from services.runs import read_run_metrics_snapshot as build_read_run_metrics_snapshot
from services.runs import rename_run as build_rename_run
from services.runs import restore_forward_boundary_series as build_restore_forward_boundary_series
from services.runs import restore_forward_observation_state as build_restore_forward_observation_state
from services.runs import restore_forward_observed_series as build_restore_forward_observed_series
from services.runs import resolve_run_objective_metadata as build_resolve_run_objective_metadata
from services.runs import resolve_run_workspace_config as build_resolve_run_workspace_config
from services.runs import resolve_source_run_reference as build_resolve_source_run_reference
from services.runs import resolve_metadata_object_type as build_resolve_metadata_object_type
from services.runs import run_csv_date_bounds as build_run_csv_date_bounds
from services.runs import run_csv_preview as build_run_csv_preview
from services.runs import rebase_run_data_cache_paths as build_rebase_run_data_cache_paths
from services.runs import run_precip_dir_candidates as build_run_precip_dir_candidates
from services.runs import run_parameter_context as build_run_parameter_context
from services.runs import default_run_export_fields as build_default_run_export_fields
from services.runs import run_kind_from_metadata as build_run_kind_from_metadata
from services.runs import run_kind_label as build_run_kind_label
from services.runs import sync_run_boundary_condition_path as build_sync_run_boundary_condition_path
from services.runs import sync_run_config_profile_metadata as build_sync_run_config_profile_metadata
from services.runs import sync_run_data_source_paths as build_sync_run_data_source_paths
from services.runs import workspace_name_for_summary as build_workspace_name_for_summary
from services.runs import run_time_label as build_run_time_label
from services.runs import run_update_timestamps as build_run_update_timestamps
from services.runs import snapshot_run_paths as build_snapshot_run_paths
from services.run_hydrology import RunHydrologyContext
from services.run_hydrology import build_hydrology_summary as build_run_hydrology_summary
from services.run_hydrology import ensure_hydrology_diagnostic_report as build_ensure_hydrology_diagnostic_report
from services.run_hydrology import objective_label_zh as build_hydrology_objective_label_zh
from services.system_status import (
    HealthContext,
    health_payload as build_health_payload,
    source_files_latest_mtime as build_source_files_latest_mtime,
)
from services.template_sync import TuotuoheSyncStartContext
from services.template_sync import tuotuohe_sync_start_plan as build_tuotuohe_sync_start_plan
from services.tasks import (
    ProcessTaskStartContext,
    PythonScriptCommandContext,
    TaskCreateContext,
    TaskMutationContext,
    ProcessMonitorContext,
    TaskQueryContext,
    TaskRecord,
    append_task_exception_output as build_append_task_exception_output,
    append_task_output as build_append_task_output,
    build_python_script_command as build_task_python_script_command,
    call_with_output_capture,
    create_registered_task as build_create_registered_task,
    decode_subprocess_output_line as build_decode_subprocess_output_line,
    find_running_task as build_find_running_task,
    finalize_process_task as build_finalize_process_task,
    has_running_tasks as build_has_running_tasks,
    invalidate_deleted_run_refs as build_invalidate_deleted_run_refs,
    list_tasks as build_list_tasks,
    mark_process_task_exception as build_mark_process_task_exception,
    mark_task_finished as build_mark_task_finished,
    monitor_process_task as build_monitor_process_task,
    set_task_detected_runs as build_set_task_detected_runs,
    snapshot_task_records as build_snapshot_task_records,
    start_process_task as build_start_process_task,
    subprocess_task_env as build_subprocess_task_env,
    task_monitor_context as build_task_monitor_context,
    task_progress_snapshot as build_task_progress_snapshot,
    update_task_metadata as build_update_task_metadata,
)
from services.workspace_advice import WorkspaceAdviceContext, workspace_advice as build_workspace_advice
from services.workspace_catalog import (
    WorkspaceCatalogContext,
    create_workspace_from_import as build_create_workspace_from_import,
    delete_workspace as build_delete_workspace,
    find_template as build_find_template,
    instantiate_template as build_instantiate_template,
    list_templates as build_list_templates,
    list_workspaces as build_list_workspaces,
    load_workspace_config as build_load_workspace_config,
    template_files as build_template_files,
)
from services.workspace_completeness import (
    WorkspaceCompletenessContext,
    quick_workspace_completeness as build_quick_workspace_completeness,
    workspace_completeness as build_workspace_completeness,
    workspace_workflow_summary as build_workspace_workflow_summary,
)
from services.workspace_detailed_check import (
    WorkspaceDetailedCheckContext,
    workspace_detailed_check as build_workspace_detailed_check,
)
from services.workspace_layout import WorkspaceLayoutContext, workspace_layout_summary as build_workspace_layout_summary
from services.workspace_validation import WorkspaceValidationContext, validate_workspace_fields as build_validate_workspace_fields
from services.wizard_validation import WizardValidationContext, wizard_validate_step as build_wizard_validate_step
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
        "note": "每场洪水独立确定初始状态，事件之间不传递状态。",
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
        "note": "每场洪水使用外部连续模拟状态作为初值。",
        "warning": "",
    },
    "continuous_state": {
        "label": "连续状态",
        "state_continuity_between_events": True,
        "note": "事件间按连续过程传递状态，要求事件之间强迫资料连续。",
        "warning": "连续状态策略不适合事件之间存在资料缺口的事件窗口集合。",
    },
}
def default_run_export_fields(metadata: dict[str, Any] | None) -> list[str]:
    return build_default_run_export_fields(metadata)


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


def source_files_latest_mtime() -> tuple[float, str]:
    return build_source_files_latest_mtime(_health_context())


def _health_context() -> HealthContext:
    return HealthContext(
        gui_root=GUI_ROOT,
        app_version=APP_VERSION,
        server_started_at=SERVER_STARTED_AT,
    )


def health_payload() -> dict[str, Any]:
    return build_health_payload(_health_context())


def _app_lifecycle_context() -> AppLifecycleContext:
    return AppLifecycleContext(
        mark_activity=mark_server_activity,
        has_running_tasks=has_running_tasks,
    )


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


def _task_query_context() -> TaskQueryContext:
    return TaskQueryContext(
        tasks=TASKS,
        task_lock=TASK_LOCK,
        snapshot_tasks=_snapshot_tasks,
        resolve_any_path=resolve_any_path,
        task_progress_snapshot=task_progress_snapshot,
    )


def _task_create_context() -> TaskCreateContext:
    return TaskCreateContext(
        tasks=TASKS,
        task_lock=TASK_LOCK,
        generate_task_id=lambda: uuid.uuid4().hex[:10],
        create_task_record=TaskRecord,
    )


def _task_mutation_context() -> TaskMutationContext:
    return TaskMutationContext(
        tasks=TASKS,
        task_lock=TASK_LOCK,
        now=time.time,
    )


def has_running_tasks() -> bool:
    return build_has_running_tasks(_task_query_context())


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


TASKS: dict[str, TaskRecord] = {}
TASK_LOCK = threading.Lock()
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
    return build_snapshot_task_records(TASKS, TASK_LOCK)


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


def task_progress_snapshot(task: TaskRecord) -> dict[str, Any] | None:
    return build_task_progress_snapshot(task)


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


def _manual_preset_context() -> ManualPresetContext:
    return ManualPresetContext(
        global_parameter_library_path=GLOBAL_PARAMETER_LIBRARY_PATH,
        meteo_key=METEO_KEY,
        meteo_precip_mode_key=METEO_PRECIP_MODE_KEY,
        profile_labels=PROFILE_LABELS,
        resolve_path=resolve_any_path,
        read_runtime_config=read_runtime_config,
        read_json_file=read_json_file,
        write_json_file=write_json_file,
        replace_placeholders=replace_placeholders,
        remap_legacy_project_path=remap_legacy_project_path,
        to_portable_path=to_portable_path,
        resolve_source_run_reference=_resolve_source_run_reference,
        normalize_run_metadata=normalize_run_metadata,
        sanitize_param_values=sanitize_param_values,
        build_forward_runtime_cli_args=_build_forward_runtime_cli_args,
        build_runtime_param_vector=build_runtime_param_vector,
        is_studio_editable_metadata=is_studio_editable_metadata,
        run_kind_from_metadata=_run_kind_from_metadata,
        run_kind_label=_run_kind_label,
        workspace_name_for_summary=_workspace_name_for_summary,
        task_time_basis=task_time_basis,
        normalize_time_step_hours=normalize_time_step_hours,
        resolve_profile=resolve_profile,
        source_run_metadata_for_preset=_source_run_metadata_for_preset,
    )


def _source_run_metadata_for_preset(source_run_raw: Any) -> tuple[dict[str, Any], Path | None, Path | None]:
    return build_source_run_metadata_for_preset(source_run_raw, _manual_preset_context())


def manual_preset_store_path(config_path_raw: str, scope: str = "workspace") -> Path:
    return build_manual_preset_store_path(config_path_raw, _manual_preset_context(), scope)


def load_manual_preset_store(config_path_raw: str, scope: str = "workspace") -> dict[str, Any]:
    return build_load_manual_preset_store(config_path_raw, _manual_preset_context(), scope)


def write_manual_preset_store(config_path_raw: str, data: dict[str, Any], scope: str = "workspace") -> Path:
    return build_write_manual_preset_store(config_path_raw, data, _manual_preset_context(), scope)


def list_manual_presets(config_path_raw: str, calibration_profile: str | None = None, scope: str = "workspace") -> dict[str, Any]:
    return build_list_manual_presets(config_path_raw, _manual_preset_context(), calibration_profile, scope=scope)


def save_manual_preset(payload: dict[str, Any]) -> dict[str, Any]:
    return build_save_manual_preset(payload, _manual_preset_context())


def find_manual_preset(config_path_raw: str, preset_id: str) -> dict[str, Any]:
    return build_find_manual_preset(config_path_raw, preset_id, _manual_preset_context())


def delete_manual_preset(payload: dict[str, Any]) -> dict[str, Any]:
    return build_delete_manual_preset(payload, _manual_preset_context())


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
        event_id_raw = str(_event_field(event, "event_id", "id", "编号", "洪水编号", "事件编号") or "").strip()
        event_id = event_id_raw
        name = str(_event_field(event, "name", "名称", "事件名称", "洪水名称") or "").strip()
        if not event_id:
            event_id = name or f"event_{hashlib.sha1(token).hexdigest()[:8]}"
            warnings.append(f"第 {index} 条事件未填写 event_id，已临时使用 {event_id}；正式工程建议填写唯一事件编号。")
        purpose_raw = str(_event_field(event, "purpose", "用途", "类型", "type") or "calibration").strip()
        purpose = EVENT_PURPOSE_ALIASES.get(purpose_raw.lower(), purpose_raw.lower() or "calibration")
        if purpose not in {"calibration", "validation", "diagnostic"}:
            warnings.append(f"事件 {event_id} 的用途 {purpose_raw} 未识别，按 diagnostic 处理。")
            purpose = "diagnostic"
        if event_id in seen_ids:
            errors.append(f"洪水事件编号重复：{event_id}")
        seen_ids.add(event_id)
        score_start_raw = _event_field(event, "score_start", "评分开始", "事件开始", "洪水开始", "开始时间", "起始时间", "start")
        score_end_raw = _event_field(event, "score_end", "评分结束", "事件结束", "洪水结束", "结束时间", "终止时间", "end")
        run_start_raw = _event_field(event, "run_start", "运行开始", "预热开始", "warmup_start") or score_start_raw
        run_end_value = _event_field(event, "run_end", "运行结束", "退水结束")
        if run_end_value in (None, ""):
            run_end_raw = score_end_raw
        else:
            run_end_raw = run_end_value
        event_errors: list[str] = []
        time_steps_run = 0
        time_steps_score = 0
        try:
            run_start = _parse_event_timestamp(run_start_raw, end=False, step_hours=step)
            score_start = _parse_event_timestamp(score_start_raw, end=False, step_hours=step)
            score_end = _parse_event_timestamp(score_end_raw, end=True, step_hours=step)
            run_end = _parse_event_timestamp(run_end_raw, end=True, step_hours=step)
        except Exception as exc:
            run_start = score_start = score_end = run_end = None
            event_errors.append(f"事件时间无法解析：{exc}")
        if run_start is None or score_start is None or score_end is None or run_end is None:
            event_errors.append("事件缺少开始时间或结束时间。")
        elif not (run_start <= score_start <= score_end <= run_end):
            event_errors.append("事件时间顺序不正确：运行开始应不晚于开始时间，结束时间应不晚于运行结束。")
        else:
            time_steps_run = int(len(_event_date_range(run_start, run_end, step)))
            time_steps_score = int(len(_event_date_range(score_start, score_end, step)))
            min_score_steps = 3 if step >= 24.0 else 6
            if time_steps_score < min_score_steps:
                unit = "天" if step >= 24.0 else "小时"
                event_errors.append(f"事件时段过短：当前 {time_steps_score} 步，至少需要 {min_score_steps} 步（{unit}尺度）。")
        if event_errors:
            errors.extend(f"{event_id}: {item}" for item in event_errors)
        events.append(
            {
                "event_id": event_id,
                "name": name or event_id,
                "purpose": purpose,
                "run_start": run_start,
                "score_start": score_start,
                "score_end": score_end,
                "run_end": run_end,
                "raw": event,
                "valid": not event_errors,
                "time_steps_run": time_steps_run,
                "time_steps_score": time_steps_score,
            }
        )

    valid_events = sorted(
        [event for event in events if event.get("valid")],
        key=lambda item: (pd.Timestamp(item["run_start"]), str(item.get("event_id", ""))),
    )
    for left, right in zip(valid_events, valid_events[1:]):
        if left["run_end"] >= right["run_start"]:
            warnings.append(f"事件时段可能重叠：{left['event_id']} 与 {right['event_id']}。")
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
    try:
        resolved = directory.resolve(strict=False)
    except (OSError, ValueError):
        return str(directory), 0, 0
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

    scan_error = ""
    try:
        exists = directory.exists()
    except (OSError, ValueError) as exc:
        exists = False
        scan_error = str(exc)
    try:
        tif_files = sorted(directory.glob("*.tif")) if exists else []
    except (OSError, ValueError) as exc:
        tif_files = []
        scan_error = str(exc)
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
        "exists": exists,
        "path": str(directory),
        "total_files": len(tif_files),
        "parseable_files": parseable_files,
        "valid_time_steps": len(timestamps),
        "invalid_files": invalid_files,
        "duplicate_timestamps": {ts: duplicate_timestamps[ts] for ts in sorted(duplicate_timestamps)},
        "timestamps": timestamps,
        "scan_error": scan_error,
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

    if result.get("scan_error"):
        errors.append(f"{label}目录无法读取：{directory}（{result['scan_error']}）")
    elif not result["exists"]:
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


def event_forcing_coverage_summary(
    event_info: dict[str, Any] | None,
    directories: dict[str, dict[str, Any]],
    step_hours: float,
) -> dict[str, Any] | None:
    if not isinstance(event_info, dict):
        return None
    valid_events = [item for item in list(event_info.get("valid_events", []) or []) if isinstance(item, dict)]
    if not valid_events:
        return {
            "enabled": True,
            "status": "fail",
            "event_count": 0,
            "complete_event_count": 0,
            "events": [],
        }
    label_map = {"prec": "降水", "temp": "气温", "evap": "潜在蒸散发"}
    timestamp_sets: dict[str, set[pd.Timestamp]] = {}
    for key, item in directories.items():
        timestamp_sets[key] = set(pd.Timestamp(ts) for ts in list(item.get("timestamps", []) or []))

    rows: list[dict[str, Any]] = []
    complete_count = 0
    for event in valid_events:
        run_start = pd.Timestamp(event.get("run_start"))
        run_end = pd.Timestamp(event.get("run_end"))
        run_index = _event_date_range(run_start, run_end, step_hours)
        expected_steps = int(len(run_index))
        variables: dict[str, Any] = {}
        event_missing = 0
        for key, label in label_map.items():
            actual = timestamp_sets.get(key, set())
            missing_steps = [ts for ts in run_index if pd.Timestamp(ts) not in actual]
            missing_count = int(len(missing_steps))
            event_missing += missing_count
            variables[key] = {
                "label": label,
                "expected_steps": expected_steps,
                "covered_steps": max(0, expected_steps - missing_count),
                "missing_steps": missing_count,
                "status": "ok" if missing_count == 0 and expected_steps > 0 else "fail",
                "missing_preview": [
                    _format_time_for_check(ts, step_hours)
                    for ts in missing_steps[:3]
                ],
            }
        status = "ok" if event_missing == 0 and expected_steps > 0 else "fail"
        if status == "ok":
            complete_count += 1
        rows.append(
            {
                "event_id": str(event.get("event_id", "") or ""),
                "name": str(event.get("name", "") or event.get("event_id", "") or ""),
                "purpose": str(event.get("purpose", "") or ""),
                "run_start": _format_time_for_check(run_start, step_hours),
                "run_end": _format_time_for_check(run_end, step_hours),
                "expected_steps": expected_steps,
                "status": status,
                "variables": variables,
            }
        )

    return {
        "enabled": True,
        "status": "ok" if complete_count == len(valid_events) else "fail",
        "event_count": len(valid_events),
        "complete_event_count": complete_count,
        "events": rows,
    }


def event_observation_coverage_summary(
    event_info: dict[str, Any] | None,
    observed_series: Any,
    step_hours: float,
) -> dict[str, Any] | None:
    if not isinstance(event_info, dict):
        return None
    valid_events = [item for item in list(event_info.get("valid_events", []) or []) if isinstance(item, dict)]
    if not valid_events:
        return {
            "enabled": True,
            "status": "fail",
            "event_count": 0,
            "complete_event_count": 0,
            "required_event_count": 0,
            "events": [],
        }
    if observed_series is None:
        actual_index = pd.DatetimeIndex([])
    else:
        try:
            actual_index = pd.DatetimeIndex(observed_series.dropna().index)
        except Exception:
            actual_index = pd.DatetimeIndex([])
    actual_set = set(pd.Timestamp(ts) for ts in actual_index.tolist())

    rows: list[dict[str, Any]] = []
    complete_count = 0
    required_count = 0
    required_complete_count = 0
    diagnostic_warn_count = 0
    for event in valid_events:
        score_start = pd.Timestamp(event.get("score_start"))
        score_end = pd.Timestamp(event.get("score_end"))
        score_index = _event_date_range(score_start, score_end, step_hours)
        expected_steps = int(len(score_index))
        missing_steps = [ts for ts in score_index if pd.Timestamp(ts) not in actual_set]
        missing_count = int(len(missing_steps))
        covered_steps = max(0, expected_steps - missing_count)
        coverage_ratio = (covered_steps / expected_steps) if expected_steps > 0 else None
        purpose = str(event.get("purpose", "") or "").strip().lower()
        is_required = purpose in {"calibration", "validation", ""}
        if is_required:
            required_count += 1
        if missing_count == 0 and expected_steps > 0:
            status = "ok"
            complete_count += 1
            if is_required:
                required_complete_count += 1
        elif is_required:
            status = "fail"
        else:
            status = "warn"
            diagnostic_warn_count += 1
        rows.append(
            {
                "event_id": str(event.get("event_id", "") or ""),
                "name": str(event.get("name", "") or event.get("event_id", "") or ""),
                "purpose": purpose,
                "score_start": _format_time_for_check(score_start, step_hours),
                "score_end": _format_time_for_check(score_end, step_hours),
                "expected_steps": expected_steps,
                "covered_steps": covered_steps,
                "missing_steps": missing_count,
                "coverage_ratio": coverage_ratio,
                "status": status,
                "missing_preview": [
                    _format_time_for_check(ts, step_hours)
                    for ts in missing_steps[:5]
                ],
            }
        )

    if required_complete_count < required_count:
        status = "fail"
    elif diagnostic_warn_count > 0:
        status = "warn"
    else:
        status = "ok"
    return {
        "enabled": True,
        "status": status,
        "event_count": len(valid_events),
        "complete_event_count": complete_count,
        "required_event_count": required_count,
        "required_complete_event_count": required_complete_count,
        "events": rows,
    }


def event_observation_coverage_messages(coverage: dict[str, Any] | None) -> tuple[list[str], list[str]]:
    issues: list[str] = []
    warnings: list[str] = []
    if not isinstance(coverage, dict) or not coverage.get("enabled"):
        return issues, warnings
    for event in list(coverage.get("events", []) or []):
        if not isinstance(event, dict):
            continue
        status = str(event.get("status", "") or "").lower()
        if status == "ok":
            continue
        name = str(event.get("name") or event.get("event_id") or "未命名事件")
        missing_steps = int(event.get("missing_steps", 0) or 0)
        expected_steps = int(event.get("expected_steps", 0) or 0)
        preview = "、".join(str(item) for item in list(event.get("missing_preview", []) or [])[:3])
        suffix = f"；例如 {preview}" if preview else ""
        message = f"事件 {name} 观测径流缺测 {missing_steps}/{expected_steps} 步{suffix}。"
        if status == "fail":
            issues.append(message)
        else:
            warnings.append(message)
    return issues, warnings


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
        "event_forcing_coverage": event_forcing_coverage_summary(event_info, directories, step_hours) if event_info is not None else None,
    }


def inspect_observed_csv(
    csv_path: str,
    date_field: str | None = None,
    expected_index: pd.DatetimeIndex | None = None,
    target_step_hours: float | None = None,
    return_series: bool = False,
) -> dict[str, Any]:
    path = resolve_any_path(csv_path, must_exist=True)
    return inspect_observed_discharge(
        path,
        date_field=date_field,
        expected_index=expected_index,
        target_step_hours=target_step_hours,
        allow_hourly_to_daily=True,
        min_daily_hours=DEFAULT_MIN_DAILY_HOURS,
        return_series=return_series,
    )


def observed_info(csv_path: str, *, date_field: str | None = None, target_step_hours: float | None = None) -> dict[str, Any]:
    return build_observed_info(
        csv_path,
        ObservedInfoContext(inspect_observed_csv=inspect_observed_csv),
        date_field=date_field,
        target_step_hours=target_step_hours,
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

    if task_time_basis(config, context="calibration") == TIME_BASIS_EVENT_WINDOWS:
        return issues, warnings

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
    return build_bbox_from_shp(
        shp_path,
        GeoSuggestionContext(resolve_path=lambda raw: resolve_any_path(raw, must_exist=True)),
    )


def suggest_cfmax_threshold(shp_path: str, dem_path: str) -> dict[str, Any]:
    return build_suggest_cfmax_threshold(
        shp_path,
        dem_path,
        GeoSuggestionContext(resolve_path=lambda raw: resolve_any_path(raw, must_exist=True)),
    )


def _geo_overview_context() -> GeoOverviewContext:
    return GeoOverviewContext(
        load_workspace_config=load_workspace_config,
        read_json_file=read_json_file,
        current_profile=current_profile,
        build_profile_paths=build_profile_paths,
        resolve_config_related_path=_resolve_config_related_path,
        workspace_dem_path=_workspace_dem_path,
        configured_dem_kind=_configured_dem_kind,
        to_display_path=to_display_path,
        profile_labels=PROFILE_LABELS,
    )


def workspace_geo_overview(config_path_raw: str) -> dict[str, Any]:
    return build_workspace_geo_overview(config_path_raw, _geo_overview_context())


def workspace_basin_geojson(config_path_raw: str) -> dict[str, Any]:
    return build_workspace_basin_geojson(config_path_raw, _geo_overview_context())


def workspace_dem_png(config_path_raw: str, style: str = "hillshade") -> dict[str, Any]:
    return build_workspace_dem_png(config_path_raw, _geo_overview_context(), style=style)


def workspace_glacier_geojson(config_path_raw: str) -> dict[str, Any]:
    return build_workspace_glacier_geojson(config_path_raw, _geo_overview_context())


def workspace_elevation_zones_geojson(config_path_raw: str) -> dict[str, Any]:
    return build_workspace_elevation_zones_geojson(config_path_raw, _geo_overview_context())


def workspace_station_geojson(config_path_raw: str) -> dict[str, Any]:
    return build_workspace_station_geojson(config_path_raw, _geo_overview_context())


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
    return build_first_existing_path(candidates)


def _run_metadata_compatibility_context() -> RunMetadataCompatibilityContext:
    return RunMetadataCompatibilityContext(
        workspace_roots_hint_from_metadata=_workspace_roots_hint_from_metadata,
        resolve_workspace_config_reference=resolve_workspace_config_reference,
    )


def is_studio_editable_metadata(metadata: dict[str, Any], resolved_config: Path | None = None) -> bool:
    return build_is_studio_editable_metadata(metadata, resolved_config, _run_metadata_compatibility_context())


def _run_source_reference_context() -> RunSourceReferenceContext:
    return RunSourceReferenceContext(
        resolve_any_path=resolve_any_path,
        replace_placeholders=replace_placeholders,
        discover_runtime_roots=discover_runtime_roots,
        iter_run_parent_dirs=iter_run_parent_dirs,
    )


def _resolve_source_run_reference(source_run_path_raw: Any, source_run_name_raw: Any) -> str:
    return build_resolve_source_run_reference(source_run_path_raw, source_run_name_raw, _run_source_reference_context())


def _normalize_metadata_object_type(value: Any) -> str:
    return build_normalize_metadata_object_type(value)


def _metadata_boundary_enabled(metadata: dict[str, Any]) -> bool | None:
    return build_metadata_boundary_enabled(metadata)


def _run_metadata_object_type_context() -> RunMetadataObjectTypeContext:
    return RunMetadataObjectTypeContext(detect_object_type=detect_object_type)


def _resolve_metadata_object_type(metadata: dict[str, Any], config: dict[str, Any] | None = None) -> str:
    return build_resolve_metadata_object_type(metadata, config, _run_metadata_object_type_context())


def _optimization_stage_payload(value: Any) -> dict[str, Any]:
    return build_optimization_stage_payload(value)


def _optimization_stage_has_execution(stage: dict[str, Any]) -> bool:
    return build_optimization_stage_has_execution(stage)


def _infer_selected_result_stage(optimization: dict[str, Any], stage_stats: dict[str, dict[str, Any]]) -> str:
    return build_infer_selected_result_stage(optimization, stage_stats)


def _normalized_selected_result_label(optimization: dict[str, Any]) -> str:
    return build_normalized_selected_result_label(optimization)


def _normalized_method_label(optimization: dict[str, Any]) -> str:
    return build_normalized_method_label(optimization)


def normalize_run_metadata(metadata: dict[str, Any], *, run_path: Path | None = None) -> tuple[dict[str, Any], Path | None]:
    normalized = copy.deepcopy(metadata or {})
    resolved_config = build_resolve_run_workspace_config(
        normalized,
        run_path=run_path,
        context=_run_metadata_compatibility_context(),
    )
    resolved_object_type = _resolve_metadata_object_type(normalized)

    sections = build_prepare_run_metadata_sections(normalized)
    data_sources = sections.data_sources
    boundary_condition = sections.boundary_condition
    optimization = sections.optimization
    manual_result = sections.manual_result
    replay_context = sections.replay_context
    cache = sections.cache
    effective_objective_mode = sections.effective_objective_mode

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
            prec_candidates = build_run_precip_dir_candidates(
                paths,
                source_key,
                data_sources.get("prec_dir", ""),
                effective_prec_dir,
                resolve_any_path,
            )
            resolved_prec_dir = _first_existing_path(prec_candidates)
            obs_path = _resolve_config_related_path(config, config.get(OBSERVED_FLOW_KEY))
            build_sync_run_data_source_paths(
                data_sources,
                paths,
                source_key,
                configured_source,
                resolved_prec_dir,
                obs_path,
            )
            if not resolved_object_type:
                resolved_object_type = _resolve_metadata_object_type(normalized, config)
            config_objective_mode = build_sync_run_config_profile_metadata(
                normalized,
                optimization,
                profile=profile,
                objective_mode=objective_mode,
                workspace_label=str(config.get("流域名称", resolved_config.stem)).strip() or resolved_config.stem,
                resolved_object_type=resolved_object_type,
            )
            if config_objective_mode:
                effective_objective_mode = config_objective_mode

            boundary_cfg = dict(config.get("边界条件", {}) or {})
            boundary_path = _resolve_config_related_path(config, boundary_cfg.get("上游边界入流_csv"))
            optional_modules = dict(normalized.get("optional_modules", {}) or {})
            build_sync_run_boundary_condition_path(
                boundary_condition,
                optional_modules,
                boundary_path,
                resolve_any_path,
                _first_existing_path,
            )
            build_rebase_run_data_cache_paths(cache, paths, data_sources)
        except Exception:
            pass

    effective_objective_mode = build_resolve_run_objective_metadata(
        normalized,
        optimization,
        effective_objective_mode=effective_objective_mode,
        resolved_object_type=resolved_object_type,
    )

    build_finalize_run_metadata_sections(
        normalized,
        data_sources=data_sources,
        boundary_condition=boundary_condition,
        replay_context=replay_context,
        manual_result=manual_result,
        optimization=optimization,
        cache=cache,
        effective_objective_mode=effective_objective_mode,
        resolve_source_run_reference=_resolve_source_run_reference,
    )
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


def _workspace_catalog_context() -> WorkspaceCatalogContext:
    return WorkspaceCatalogContext(
        template_dir=TEMPLATE_DIR,
        workspace_dir=WORKSPACE_DIR,
        default_workspace_path=DEFAULT_WORKSPACE_PATH,
        builtin_glacier_shp=BUILTIN_GLACIER_SHP,
        builtin_dem=BUILTIN_DEM,
        profile_daily=PROFILE_DAILY,
        profile_hourly=PROFILE_HOURLY,
        object_regression=OBJECT_REGRESSION,
        object_interbasin=OBJECT_INTERBASIN,
        object_full_upstream=OBJECT_FULL_UPSTREAM,
        observed_flow_key=OBSERVED_FLOW_KEY,
        meteo_key=METEO_KEY,
        meteo_precip_source_key=METEO_PRECIP_SOURCE_KEY,
        meteo_precip_source_legacy_key=METEO_PRECIP_SOURCE_LEGACY_KEY,
        read_json_file=read_json_file,
        read_runtime_config=read_runtime_config,
        replace_placeholders=replace_placeholders,
        resolve_any_path=resolve_any_path,
        resolve_profile=resolve_profile,
        normalize_config_before_save=normalize_config_before_save,
        detect_object_type=detect_object_type,
        slugify_workspace_name=slugify_workspace_name,
        runtime_root_for_workspace=runtime_root_for_workspace,
        write_json_file=write_json_file,
        to_display_path=to_display_path,
        workspace_workflow_summary=workspace_workflow_summary,
        normalize_time_step_hours=normalize_time_step_hours,
        ensure_within=ensure_within,
        inspect_observed_csv=inspect_observed_csv,
        fill_bbox_from_shp=fill_bbox_from_shp,
        suggest_time_windows=suggest_time_windows,
        suggest_cfmax_threshold=suggest_cfmax_threshold,
        build_empty_workspace=build_empty_workspace,
        stage_vector_shapefile=stage_vector_shapefile,
        stage_observed_runoff_file=stage_observed_runoff_file,
    )


def template_files() -> list[Path]:
    return build_template_files(_workspace_catalog_context())


def list_templates() -> list[dict[str, Any]]:
    return build_list_templates(_workspace_catalog_context())


def find_template(template_id: str) -> Path:
    return build_find_template(template_id, _workspace_catalog_context())


def instantiate_template(payload: dict[str, Any]) -> dict[str, Any]:
    return build_instantiate_template(payload, _workspace_catalog_context())


def list_workspaces() -> list[dict[str, Any]]:
    return build_list_workspaces(_workspace_catalog_context())


def load_workspace_config(path_value: str) -> tuple[Path, dict[str, Any]]:
    return build_load_workspace_config(path_value, _workspace_catalog_context())


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


def workspace_layout_summary(config_path_raw: str) -> dict[str, Any]:
    return build_workspace_layout_summary(
        config_path_raw,
        WorkspaceLayoutContext(
            load_workspace_config=load_workspace_config,
            current_profile=current_profile,
            build_profile_paths=build_profile_paths,
            effective_precip_paths=effective_precip_paths,
            display_runtime_precip_label=display_runtime_precip_label,
            count_path_entries=_count_path_entries,
            to_display_path=to_display_path,
            detect_object_type=detect_object_type,
            profile_labels=PROFILE_LABELS,
        ),
    )


def delete_workspace(path_value: str) -> dict[str, Any]:
    return build_delete_workspace(path_value, _workspace_catalog_context())


def delete_run(run_path_raw: str) -> dict[str, Any]:
    return build_delete_run(run_path_raw, _run_mutation_context())


def rename_run(payload: dict[str, Any]) -> dict[str, Any]:
    return build_rename_run(payload, _run_mutation_context())


def _run_mutation_context() -> RunMutationContext:
    return RunMutationContext(
        resolve_path=resolve_any_path,
        list_runs=list_runs,
        summarize_run=summarize_run,
        read_json_file=read_json_file,
        write_json_file=write_json_file,
        normalize_result_title=_normalized_result_title,
        invalidate_deleted_run_refs=invalidate_deleted_run_refs,
    )


def create_workspace_from_import(payload: dict[str, Any]) -> dict[str, Any]:
    return build_create_workspace_from_import(payload, _workspace_catalog_context())


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
    summary_path = Path(corrected_dir) / "precipitation_strategy_summary.json"
    if summary_path.exists():
        try:
            summary = read_json_file(summary_path)
            time_basis_label = str(summary.get("time_basis_label", "") or "").strip()
            selected_steps = int(summary.get("selected_steps", 0) or 0)
            written_files = int(summary.get("written_files", 0) or 0)
            zero_steps = int(summary.get("zero_available_station_steps", 0) or 0)
            skipped_steps = int(summary.get("skipped_out_of_scope_steps", 0) or 0)
            parts = [f"{label}文件数：{count}"]
            if time_basis_label:
                parts.append(f"资料口径：{time_basis_label}")
            if selected_steps or written_files:
                parts.append(f"参与时段：{written_files or selected_steps}/{selected_steps or count}")
            if zero_steps:
                parts.append(f"无可用站点时段：{zero_steps}")
            if skipped_steps:
                parts.append(f"已忽略口径外时段：{skipped_steps}")
            return count > 0, "；".join(parts), count
        except Exception:
            pass
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
            "valid": bool(event.get("valid")),
            "score_start": _format_time_for_check(event.get("score_start"), step_hours),
            "score_end": _format_time_for_check(event.get("score_end"), step_hours),
            "run_start": _format_time_for_check(event.get("run_start"), step_hours),
            "run_end": _format_time_for_check(event.get("run_end"), step_hours),
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
        status = "fail" if valid_event_count <= 0 else "warn" if info.get("errors") or info.get("warnings") else "ok"
        initial_label = str(info.get("initial_state_policy_label", "事件预热") or "事件预热")
        initial_note = str(info.get("initial_state_note", "") or "")
        headline = (
            f"当前按 {valid_event_count} 场洪水事件检查，事件之间允许资料间断。"
            if valid_event_count > 0
            else "当前选择洪水事件，但尚未识别到合法事件。"
        )
        return {
            "time_basis": time_basis,
            "time_basis_label": label,
            "headline": headline,
            "detail": "只检查每场洪水内部的气象与流量资料。"
            + (f" {initial_note}" if initial_note else ""),
            "start": start,
            "end": end,
            "expected_steps": expected_steps,
            "event_count": event_count,
            "valid_event_count": valid_event_count,
            "status": status,
            "items": [
                {"label": "资料口径", "value": label},
                {"label": "有效事件", "value": f"{valid_event_count}/{event_count} 场"},
                {"label": "事件时段", "value": f"{start} 至 {end}" if start and end else "未形成有效时段"},
                {"label": "初始条件", "value": initial_label},
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


def _station_precip_mode_label(mode: str) -> str:
    return {
        "grid_plus_station_bias": "格点 + 站点偏差订正",
        "thiessen_station_only": "纯站点泰森分配",
    }.get(str(mode or "").strip(), "站点降水方案")


def _index_display_range(index: pd.DatetimeIndex | None, step_hours: float) -> tuple[str, str, int]:
    if index is None or len(index) <= 0:
        return "", "", 0
    return (
        _format_time_for_check(index[0], step_hours),
        _format_time_for_check(index[-1], step_hours),
        int(len(index)),
    )


def _max_consecutive_true(values: Any) -> int:
    longest = 0
    current = 0
    for value in list(values):
        if bool(value):
            current += 1
            longest = max(longest, current)
        else:
            current = 0
    return int(longest)


def _station_count_text(min_count: int | None, mean_count: float | None) -> str:
    if min_count is None:
        return "未形成"
    if mean_count is None:
        return str(int(min_count))
    return f"最少 {int(min_count)}，平均 {mean_count:.1f}"


def _station_precip_task_context_summary(
    *,
    mode: str,
    context: str,
    time_basis: str,
    time_basis_label: str,
    step_hours: float,
    expected_index: pd.DatetimeIndex | None,
    expected_count: int,
    covered_count: int,
    coverage_ratio: float | None,
    zero_available_steps: int,
    max_consecutive_zero_steps: int = 0,
    min_available_station_count: int | None = None,
    mean_available_station_count: float | None = None,
    station_start: Any = None,
    station_end: Any = None,
    event_info: dict[str, Any] | None = None,
    event_coverage: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    start, end, expected_steps = _index_display_range(expected_index, step_hours)
    station_start_text = _format_time_for_check(station_start, step_hours)
    station_end_text = _format_time_for_check(station_end, step_hours)
    coverage_text = (
        f"{covered_count}/{expected_count} 步（{coverage_ratio * 100:.1f}%）"
        if coverage_ratio is not None and expected_count > 0
        else "未形成可核对时段"
    )
    events = list(event_coverage or [])
    event_ok_count = sum(1 for item in events if str(item.get("status", "") or "") == "ok")
    event_count = int(len(events))
    event_valid_count = int((event_info or {}).get("valid_event_count", event_count) or 0)
    if time_basis == TIME_BASIS_EVENT_WINDOWS and event_valid_count <= 0:
        status = "fail"
    elif expected_count <= 0:
        status = "warn"
    elif coverage_ratio is None or covered_count <= 0:
        status = "fail"
    elif coverage_ratio >= 0.99 and zero_available_steps == 0 and all(str(item.get("status", "")) == "ok" for item in events):
        status = "ok"
    elif mode == "thiessen_station_only" and zero_available_steps > 0:
        status = "fail"
    else:
        status = "warn"

    if time_basis == TIME_BASIS_EVENT_WINDOWS:
        headline = (
            f"当前按 {event_valid_count} 场洪水事件运行窗口核对站点降水，事件之间允许资料间断。"
            if event_valid_count > 0
            else "当前选择洪水事件窗口，但尚未形成可核对的有效事件。"
        )
        detail = (
            "站点降水完整性只在事件运行窗口内评价；事件内部若出现无可用站点时间步，"
            "纯站点泰森分配不能直接运行，格点订正也应作为风险处理。"
        )
        scope_value = f"{start} 至 {end}" if start and end else "未形成事件运行窗口"
        items = [
            {"label": "检查口径", "value": time_basis_label, "status": "ok" if event_valid_count > 0 else "fail"},
            {"label": "事件覆盖", "value": f"{event_ok_count}/{event_count} 场完整" if event_count else "未形成", "status": "ok" if event_count and event_ok_count == event_count else "fail" if event_valid_count <= 0 else "warn"},
            {"label": "运行窗口并集", "value": scope_value, "status": "ok" if expected_steps else "warn"},
            {"label": "覆盖步数", "value": coverage_text, "status": "ok" if coverage_ratio is not None and coverage_ratio >= 0.99 else "warn" if covered_count > 0 else "fail"},
            {"label": "可用站点", "value": _station_count_text(min_available_station_count, mean_available_station_count), "status": "ok" if min_available_station_count and min_available_station_count > 0 else "fail" if mode == "thiessen_station_only" else "warn"},
            {"label": "无站点时间步", "value": str(zero_available_steps), "status": "ok" if zero_available_steps == 0 else "fail" if mode == "thiessen_station_only" else "warn"},
            {"label": "最大连续无站点", "value": f"{max_consecutive_zero_steps} 步", "status": "ok" if max_consecutive_zero_steps == 0 else "fail" if mode == "thiessen_station_only" else "warn"},
        ]
    elif time_basis == TIME_BASIS_FORECAST_WINDOW or context == "forecast":
        headline = (
            f"当前按连续状态预报窗口核对站点降水：{start} 至 {end}。"
            if start and end
            else "当前按连续状态预报窗口核对站点降水，但预报起止时间尚未完整配置。"
        )
        detail = (
            "预报运行主线读取已经制备好的降水栅格；如果未来降水来自站点资料，应先在气象准备流程中完成订正或泰森制图，"
            "再将生成的预报窗口栅格交给连续状态预报。"
        )
        items = [
            {"label": "检查口径", "value": time_basis_label, "status": "ok" if expected_steps else "warn"},
            {"label": "预报窗口", "value": f"{start} 至 {end}" if start and end else "未完整配置", "status": "ok" if expected_steps else "warn"},
            {"label": "覆盖步数", "value": coverage_text, "status": "ok" if coverage_ratio is not None and coverage_ratio >= 0.99 else "warn" if covered_count > 0 else "fail"},
            {"label": "可用站点", "value": _station_count_text(min_available_station_count, mean_available_station_count), "status": "ok" if min_available_station_count and min_available_station_count > 0 else "warn"},
            {"label": "最大连续无站点", "value": f"{max_consecutive_zero_steps} 步", "status": "ok" if max_consecutive_zero_steps == 0 else "warn"},
            {"label": "降水处理", "value": "预报页使用目标栅格，站点雨量先在气象准备中制图", "status": "ok"},
        ]
    else:
        headline = (
            f"当前按连续时段核对站点降水：{start} 至 {end}。"
            if start and end
            else "当前按连续时段核对站点降水，但预热、率定或验证时间尚未完整配置。"
        )
        detail = (
            "连续模拟要求目标时间轴内站点降水连续参与；中间缺口会影响土壤含水量、积雪、水库状态和汇流记忆。"
        )
        items = [
            {"label": "检查口径", "value": time_basis_label, "status": "ok" if expected_steps else "warn"},
            {"label": "连续时段", "value": f"{start} 至 {end}" if start and end else "未完整配置", "status": "ok" if expected_steps else "warn"},
            {"label": "覆盖步数", "value": coverage_text, "status": "ok" if coverage_ratio is not None and coverage_ratio >= 0.99 else "warn" if covered_count > 0 else "fail"},
            {"label": "可用站点", "value": _station_count_text(min_available_station_count, mean_available_station_count), "status": "ok" if min_available_station_count and min_available_station_count > 0 else "fail" if mode == "thiessen_station_only" else "warn"},
            {"label": "无站点时间步", "value": str(zero_available_steps), "status": "ok" if zero_available_steps == 0 else "fail" if mode == "thiessen_station_only" else "warn"},
            {"label": "最大连续无站点", "value": f"{max_consecutive_zero_steps} 步", "status": "ok" if max_consecutive_zero_steps == 0 else "fail" if mode == "thiessen_station_only" else "warn"},
        ]

    return {
        "schema": "station_precip_task_context_v1",
        "context": context,
        "mode": mode,
        "mode_label": _station_precip_mode_label(mode),
        "time_basis": time_basis,
        "time_basis_label": time_basis_label,
        "headline": headline,
        "detail": detail,
        "status": status,
        "start": start,
        "end": end,
        "expected_steps": int(expected_steps),
        "covered_steps": int(covered_count),
        "coverage_ratio": coverage_ratio,
        "zero_available_steps": int(zero_available_steps),
        "max_consecutive_zero_steps": int(max_consecutive_zero_steps),
        "min_available_station_count": min_available_station_count,
        "mean_available_station_count": mean_available_station_count,
        "station_time_range": {
            "start": station_start_text,
            "end": station_end_text,
        },
        "event_count": event_count,
        "event_ok_count": int(event_ok_count),
        "items": items,
    }


def analyze_station_precip_inputs(
    config: dict[str, Any],
    *,
    step_hours: float | None = None,
    context: str = "calibration",
) -> dict[str, Any]:
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
    runtime_context = str(context or "calibration").strip().lower() or "calibration"
    time_basis = task_time_basis(config, context=runtime_context)
    time_basis_label = TIME_BASIS_LABELS.get(time_basis, "当前任务时段")
    event_info = normalized_flood_events(config, step_hours=step) if time_basis == TIME_BASIS_EVENT_WINDOWS else None
    expected_index = build_expected_forcing_index(config, context=runtime_context)
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
            "time_basis": time_basis,
            "time_basis_label": time_basis_label,
            "task_context": _station_precip_task_context_summary(
                mode=mode,
                context=runtime_context,
                time_basis=time_basis,
                time_basis_label=time_basis_label,
                step_hours=step,
                expected_index=expected_index,
                expected_count=int(len(expected_index)) if expected_index is not None else 0,
                covered_count=0,
                coverage_ratio=None,
                zero_available_steps=0,
                event_info=event_info,
                event_coverage=[],
            ),
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
            "time_basis": time_basis,
            "time_basis_label": time_basis_label,
            "task_context": _station_precip_task_context_summary(
                mode=mode,
                context=runtime_context,
                time_basis=time_basis,
                time_basis_label=time_basis_label,
                step_hours=step,
                expected_index=expected_index,
                expected_count=int(len(expected_index)) if expected_index is not None else 0,
                covered_count=0,
                coverage_ratio=None,
                zero_available_steps=0,
                event_info=event_info,
                event_coverage=[],
            ),
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
    expected_count = 0
    covered_count = 0
    coverage_ratio: float | None = None
    event_coverage: list[dict[str, Any]] = []
    zero_available_steps = 0
    max_consecutive_zero_steps = 0
    min_available_station_count: int | None = None
    mean_available_station_count: float | None = None
    quality_series = matched_series
    if expected_index is not None and len(expected_index) > 0:
        expected_count = int(len(expected_index))
        if expected_count > 0 and not matched_series.empty:
            present = matched_series.reindex(expected_index)
            quality_series = present
            available_counts = present.notna().sum(axis=1)
            covered_count = int((available_counts > 0).sum())
            coverage_ratio = covered_count / expected_count
            zero_flags = available_counts == 0
            zero_available_steps = int(zero_flags.sum())
            max_consecutive_zero_steps = _max_consecutive_true(zero_flags.tolist())
            min_available_station_count = int(available_counts.min()) if not available_counts.empty else None
            mean_available_station_count = float(available_counts.mean()) if not available_counts.empty else None
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
                event_available_min = None if len(event_index) <= 0 else 0
                event_available_mean = None if len(event_index) <= 0 else 0.0
                event_max_zero = int(len(event_index))
            else:
                event_present = matched_series.reindex(event_index)
                event_available_counts = event_present.notna().sum(axis=1)
                event_zero_flags = event_available_counts == 0
                covered_event = int((event_available_counts > 0).sum())
                zero_event = int(event_zero_flags.sum())
                event_available_min = int(event_available_counts.min()) if not event_available_counts.empty else None
                event_available_mean = float(event_available_counts.mean()) if not event_available_counts.empty else None
                event_max_zero = _max_consecutive_true(event_zero_flags.tolist())
            event_steps = int(len(event_index))
            event_ratio = covered_event / event_steps if event_steps else None
            if event_ratio is not None and event_ratio >= 0.99 and zero_event == 0:
                event_status = "ok"
            elif mode == "thiessen_station_only" and zero_event > 0:
                event_status = "fail"
            elif covered_event == 0:
                event_status = "fail"
            else:
                event_status = "warn"
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
                    "missing_ratio": (1.0 - event_ratio) if event_ratio is not None else None,
                    "zero_available_steps": zero_event,
                    "max_consecutive_zero_steps": event_max_zero,
                    "available_station_min": event_available_min,
                    "available_station_mean": event_available_mean,
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

    numeric_values = quality_series.to_numpy(dtype="float64") if not quality_series.empty else np.empty((0, 0), dtype="float64")
    negative_count = int(np.sum(numeric_values < 0)) if numeric_values.size else 0
    extreme_threshold = 80.0 if abs(step - 1.0) < 1e-9 else 300.0
    extreme_count = int(np.sum(numeric_values > extreme_threshold)) if numeric_values.size else 0
    all_zero_count = 0
    max_missing_rate = 0.0
    station_missing_rates: list[dict[str, Any]] = []
    if matched_ids:
        for col in matched_ids:
            values = quality_series[col].dropna().to_numpy(dtype="float64") if col in quality_series.columns else np.array([], dtype="float64")
            if values.size and bool(np.nanmax(np.abs(values)) <= 1e-9):
                all_zero_count += 1
        missing_rates = quality_series[matched_ids].isna().mean(axis=0) if not quality_series.empty else pd.Series(dtype="float64")
        max_missing_rate = float(missing_rates.max()) if not missing_rates.empty else 0.0
        station_missing_rates = [
            {"station_id": str(station_id), "missing_rate": float(rate)}
            for station_id, rate in missing_rates.sort_values(ascending=False).head(20).items()
        ]
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
    task_context = _station_precip_task_context_summary(
        mode=mode,
        context=runtime_context,
        time_basis=time_basis,
        time_basis_label=time_basis_label,
        step_hours=step,
        expected_index=expected_index,
        expected_count=expected_count,
        covered_count=covered_count,
        coverage_ratio=coverage_ratio,
        zero_available_steps=zero_available_steps,
        max_consecutive_zero_steps=max_consecutive_zero_steps,
        min_available_station_count=min_available_station_count,
        mean_available_station_count=mean_available_station_count,
        station_start=station_start,
        station_end=station_end,
        event_info=event_info,
        event_coverage=event_coverage,
    )
    items.extend(
        [
            {"label": "降水方案", "value": "格点+站点偏差订正" if mode == "grid_plus_station_bias" else "站点泰森分配", "status": "ok"},
            {"label": "检查口径", "value": task_context["headline"], "status": str(task_context.get("status", "warn"))},
            {"label": "资料口径", "value": time_basis_label, "status": "ok"},
            {"label": "站号匹配", "value": f"{len(matched_ids)}/{len(meta_id_set)}", "status": "ok" if matched_ids and not missing_in_precip else "warn" if matched_ids else "fail"},
            {"label": "降水表额外站号", "value": str(len(missing_in_meta)), "status": "ok" if not missing_in_meta else "warn"},
            {"label": "资料格式", "value": station_format, "status": "ok"},
            {"label": "时间范围", "value": f"{_format_time_for_check(station_start, step)} 至 {_format_time_for_check(station_end, step)}", "status": "ok" if coverage_ratio is None or coverage_ratio >= 0.99 else "warn" if covered_count > 0 else "fail"},
            {"label": f"{time_basis_label}覆盖", "value": f"{coverage_ratio * 100:.1f}%" if coverage_ratio is not None else "未配置完整时段", "status": "ok" if coverage_ratio is None or coverage_ratio >= 0.99 else "warn" if covered_count > 0 else "fail"},
            {"label": "无可用站点时间步", "value": str(zero_available_steps), "status": "ok" if zero_available_steps == 0 else "fail" if mode == "thiessen_station_only" else "warn"},
            {"label": "最大连续无站点", "value": f"{max_consecutive_zero_steps} 步", "status": "ok" if max_consecutive_zero_steps == 0 else "fail" if mode == "thiessen_station_only" else "warn"},
            {"label": "可用站点数", "value": _station_count_text(min_available_station_count, mean_available_station_count), "status": "ok" if min_available_station_count and min_available_station_count > 0 else "fail" if mode == "thiessen_station_only" else "warn"},
            {"label": "单站最大缺测率", "value": f"{max_missing_rate * 100:.1f}%", "status": "warn" if max_missing_rate > 0.20 else "ok"},
            {"label": "负降水记录", "value": str(negative_count), "status": "ok" if negative_count == 0 else "warn"},
            {"label": "异常大值记录", "value": str(extreme_count), "status": "ok" if extreme_count == 0 else "warn"},
        ]
    )
    for event_item in event_coverage[:5]:
        ratio = event_item.get("coverage_ratio")
        station_text = _station_count_text(
            event_item.get("available_station_min"),
            event_item.get("available_station_mean"),
        )
        value = f"{float(ratio) * 100:.1f}% / {station_text} / 连续无站点 {int(event_item.get('max_consecutive_zero_steps', 0) or 0)} 步" if ratio is not None else "未覆盖"
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
        "max_consecutive_zero_steps": max_consecutive_zero_steps,
        "min_available_station_count": min_available_station_count,
        "mean_available_station_count": mean_available_station_count,
        "station_missing_rates": station_missing_rates,
        "time_basis": time_basis,
        "time_basis_label": time_basis_label,
        "task_context": task_context,
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
                "task_context": dict(station_precip_info.get("task_context", {}) or {}),
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
    return build_validate_workspace_fields(
        config_path_raw,
        _workspace_validation_context(),
        stage=stage,
        precip_source=precip_source,
        config_override=config_override,
    )


def _workspace_validation_context() -> WorkspaceValidationContext:
    return WorkspaceValidationContext(
        resolve_path=resolve_any_path,
        read_config=read_runtime_config,
        find_running_task=find_running_task,
        current_profile=current_profile,
        detect_object_type=detect_object_type,
        build_profile_paths=build_profile_paths,
        normalize_time_step_hours=normalize_time_step_hours,
        task_time_basis=task_time_basis,
        normalized_flood_events=normalized_flood_events,
        workspace_dem_path=_workspace_dem_path,
        configured_dem_kind=_configured_dem_kind,
        resolve_config_related_path=_resolve_config_related_path,
        time_sequence_messages=time_sequence_messages,
        inspect_observed_csv=inspect_observed_csv,
        build_expected_observation_index=build_expected_observation_index,
        observed_window_messages=observed_window_messages,
        event_observation_coverage_summary=event_observation_coverage_summary,
        event_observation_coverage_messages=event_observation_coverage_messages,
        format_timestamp_for_display=format_timestamp_for_display,
        inspect_boundary_csv=inspect_boundary_inflow_csv,
        build_expected_forcing_index=build_expected_forcing_index,
        boundary_info_messages=boundary_info_messages,
        resolve_precip_source=resolve_precip_source,
        analyze_station_precip_inputs=analyze_station_precip_inputs,
        validate_forcing_bundle=validate_forcing_bundle,
        glacier_formal_requirements=glacier_formal_requirements,
        build_engineering_focus_checks=build_engineering_focus_checks,
        input_time_basis_ui_summary=input_time_basis_ui_summary,
        event_windows_ui_summary=event_windows_ui_summary,
        default_init_state=profile_runner.DEFAULT_INIT_STATE,
        observed_flow_key=OBSERVED_FLOW_KEY,
        profile_daily=PROFILE_DAILY,
        profile_hourly=PROFILE_HOURLY,
        object_interbasin=OBJECT_INTERBASIN,
        object_full_upstream=OBJECT_FULL_UPSTREAM,
        time_basis_event_windows=TIME_BASIS_EVENT_WINDOWS,
        time_basis_labels=TIME_BASIS_LABELS,
        meteo_key=METEO_KEY,
        meteo_precip_mode_key=METEO_PRECIP_MODE_KEY,
        meteo_pet_source_key=METEO_PET_SOURCE_KEY,
    )


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


def _data_prep_context() -> DataPrepContext:
    return DataPrepContext(
        load_workspace_config=load_workspace_config,
        current_profile=current_profile,
        data_prep_steps=data_prep_steps,
        resolve_data_prep_step=resolve_data_prep_step,
        resolve_precip_source=resolve_precip_source,
        find_running_task=find_running_task,
        profile_daily=PROFILE_DAILY,
    )


def get_data_prep_steps_payload(config_path_raw: str = "") -> list[dict[str, Any]]:
    return build_data_prep_steps_payload(config_path_raw, _data_prep_context())


def get_data_prep_status(config_path_raw: str, precip_source: Any = None) -> list[dict[str, Any]]:
    return build_data_prep_status(
        config_path_raw,
        _data_prep_context(),
        precip_source=precip_source,
    )


def task_step_map(profile: str, config: dict[str, Any] | None = None) -> dict[str, dict[str, Any]]:
    return {step["id"]: resolve_data_prep_step(step, config) for step in data_prep_steps(profile)}


def add_task_output(task_id: str, line: str) -> None:
    build_append_task_output(task_id, line, _task_mutation_context())


def add_task_exception_output(task_id: str, exc: BaseException, *, prefix: str = "[失败]") -> None:
    build_append_task_exception_output(task_id, exc, _task_mutation_context(), prefix=prefix)


def set_task_metadata(task_id: str, **items: Any) -> None:
    build_update_task_metadata(task_id, _task_mutation_context(), **items)


def invalidate_deleted_run_refs(run_path: Path) -> None:
    build_invalidate_deleted_run_refs(run_path, _task_mutation_context(), same_path)


def list_tasks() -> list[dict[str, Any]]:
    return build_list_tasks(_task_query_context())


def find_running_task(task_type: str, config_path_raw: str) -> TaskRecord | None:
    return build_find_running_task(task_type, config_path_raw, _task_query_context())


def _run_discovery_context() -> RunDiscoveryContext:
    return RunDiscoveryContext(
        project_runtime_dir=PROJECT_RUNTIME_DIR,
        list_workspaces=list_workspaces,
        workspace_path_candidates=profile_runner.workspace_path_candidates,
        safe_iterdir=_safe_iterdir,
    )


def discover_runtime_roots() -> list[Path]:
    return build_discover_runtime_roots(_run_discovery_context())


def iter_run_parent_dirs(root_dir: Path) -> list[Path]:
    return build_iter_run_parent_dirs(root_dir, _run_discovery_context())


def _discover_run_entries() -> list[tuple[tuple[Any, ...], Path]]:
    return build_discover_run_entries(_run_discovery_context())


def iter_run_dirs() -> list[Path]:
    return build_iter_run_dirs(_run_discovery_context())


def _run_update_timestamps(run_dir: Path) -> tuple[float, int]:
    return build_run_update_timestamps(run_dir)


def _run_workspace_name_context() -> RunWorkspaceNameContext:
    return RunWorkspaceNameContext(
        workspace_roots_hint_from_metadata=_workspace_roots_hint_from_metadata,
        resolve_workspace_config_reference=resolve_workspace_config_reference,
        read_runtime_config=read_runtime_config,
    )


def _workspace_name_for_summary(metadata: dict[str, Any], resolved_config: Path | None = None) -> str:
    return build_workspace_name_for_summary(metadata, resolved_config, _run_workspace_name_context())


def _run_kind_from_metadata(metadata: dict[str, Any] | None, studio_compatible: bool = False) -> str:
    return build_run_kind_from_metadata(metadata, studio_compatible)


def _run_kind_label(kind: str) -> str:
    return build_run_kind_label(kind)


def _normalized_result_title(value: Any) -> str:
    return build_normalize_result_title(value)


def _has_custom_result_title(run_dir: Path, title: str) -> bool:
    return build_has_custom_result_title(run_dir, title)


def _run_time_label(raw_value: Any, updated_at: float | None = None) -> str:
    return build_run_time_label(raw_value, updated_at)


def _run_hydrology_context() -> RunHydrologyContext:
    return RunHydrologyContext(to_display_path=to_display_path)


def _objective_label_zh(metadata: dict[str, Any]) -> str:
    return build_hydrology_objective_label_zh(metadata)


def _build_hydrology_summary(metadata: dict[str, Any], run_dir: Path) -> dict[str, Any]:
    return build_run_hydrology_summary(metadata, run_dir, _run_hydrology_context())


def _ensure_hydrology_diagnostic_report(run_dir: Path, metadata: dict[str, Any], summary: dict[str, Any]) -> dict[str, Any]:
    return build_ensure_hydrology_diagnostic_report(run_dir, metadata, summary, _run_hydrology_context())


def _run_parameter_context(
    run_dir: Path,
    metadata: dict[str, Any],
    resolved_config: Path | None,
) -> dict[str, Any]:
    return build_run_parameter_context(
        run_dir,
        metadata,
        resolved_config,
        _workspace_name_for_summary(metadata, resolved_config),
        getattr(profile_runner, "PARAM_BOUNDS_PROFILE_LABELS", {}),
    )


def _run_summary_context() -> RunSummaryContext:
    return RunSummaryContext(
        to_display_path=to_display_path,
        is_studio_editable_metadata=is_studio_editable_metadata,
        build_hydrology_summary=_build_hydrology_summary,
        workspace_name_for_summary=_workspace_name_for_summary,
        param_bounds_profile_labels=getattr(profile_runner, "PARAM_BOUNDS_PROFILE_LABELS", {}),
        replace_placeholders=replace_placeholders,
    )


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
    return build_run_summary_payload(
        run_dir,
        metadata,
        resolved_config,
        updated_at=updated_at,
        updated_at_ns=updated_at_ns,
        context=_run_summary_context(),
    )


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
    return build_list_runs(RunListContext(discover_run_entries=_discover_run_entries, summarize_run=summarize_run))


def export_run_excel(payload: dict[str, Any]) -> dict[str, Any]:
    return build_export_run_excel(payload, _run_export_context())


def _run_export_context() -> RunExportContext:
    return RunExportContext(
        resolve_path=resolve_any_path,
        read_json_file=read_json_file,
        normalize_time_step_hours=normalize_time_step_hours,
        is_date_only_string=is_date_only_string,
        format_timestamp_for_display=format_timestamp_for_display,
        slugify_workspace_name=slugify_workspace_name,
        to_display_path=to_display_path,
    )


def load_run_detail(run_path: str) -> dict[str, Any]:
    return build_load_run_detail(run_path, _run_detail_context())


def _run_detail_context() -> RunDetailContext:
    return RunDetailContext(
        resolve_path=resolve_any_path,
        read_json_file=read_json_file,
        normalize_run_metadata=normalize_run_metadata,
        run_update_timestamps=_run_update_timestamps,
        safe_float=safe_float,
        build_hydrology_summary=_build_hydrology_summary,
        ensure_hydrology_diagnostic_report=_ensure_hydrology_diagnostic_report,
        build_run_summary=_build_run_summary,
        is_studio_editable_metadata=is_studio_editable_metadata,
    )


def _run_replay_config_context() -> RunReplayConfigContext:
    return RunReplayConfigContext(
        default_initial_state=dict(profile_runner.DEFAULT_INIT_STATE),
        resolve_metadata_object_type=_resolve_metadata_object_type,
        metadata_boundary_enabled=_metadata_boundary_enabled,
    )


def _apply_run_replay_config_overrides(config: dict[str, Any], metadata: dict[str, Any]) -> dict[str, Any]:
    return build_apply_run_replay_config_overrides(config, metadata, _run_replay_config_context())


def snapshot_run_paths() -> set[str]:
    return build_snapshot_run_paths(list_runs)


def _calibration_task_context() -> RunCalibrationTaskContext:
    return RunCalibrationTaskContext(
        resolve_path=resolve_any_path,
        read_json_file=read_json_file,
        normalize_run_metadata=normalize_run_metadata,
        run_update_timestamps=_run_update_timestamps,
        build_run_summary=_build_run_summary,
        is_studio_editable_metadata=is_studio_editable_metadata,
    )


def _build_calibration_task_result(run_path: str) -> dict[str, Any] | None:
    return build_run_calibration_task_result(run_path, _calibration_task_context())


def verify_data_prep_step_output(
    step: dict[str, Any],
    config: dict[str, Any],
    runtime_prec_source: Any = None,
) -> tuple[bool, str]:
    return build_verify_data_prep_step_output(step, config, runtime_prec_source)


def _data_prep_task_output_context() -> DataPrepTaskOutputContext:
    return DataPrepTaskOutputContext(
        resolve_path=resolve_any_path,
        read_runtime_config=read_runtime_config,
        task_step_map=task_step_map,
        current_profile=current_profile,
        resolve_runtime_precip_source=profile_runner.resolve_runtime_precip_source,
    )


def verify_data_prep_task_output(metadata: dict[str, Any]) -> tuple[bool, str]:
    return build_verify_data_prep_task_output(metadata, _data_prep_task_output_context())


def monitor_task(task_id: str, process: subprocess.Popen[Any], previous_runs: set[str]) -> None:
    build_monitor_process_task(
        task_id,
        process,
        previous_runs,
        ProcessMonitorContext(
            decode_output_line=build_decode_subprocess_output_line,
            add_task_output=add_task_output,
            get_task_context=lambda current_task_id: build_task_monitor_context(
                current_task_id,
                _task_mutation_context(),
            ),
            verify_data_prep_task_output=verify_data_prep_task_output,
            snapshot_run_paths=snapshot_run_paths,
            pick_latest_run_path=build_pick_latest_run_path,
            build_calibration_task_result=_build_calibration_task_result,
            finalize_task=lambda current_task_id, return_code, detected_runs, result: build_finalize_process_task(
                current_task_id,
                return_code,
                detected_runs,
                result,
                _task_mutation_context(),
            ),
            mark_task_exception=lambda current_task_id, exc: build_mark_process_task_exception(
                current_task_id,
                exc,
                _task_mutation_context(),
            ),
        ),
    )


def build_python_script_command(script: Path | str, *args: Any) -> list[str]:
    return build_task_python_script_command(
        script,
        *args,
        context=PythonScriptCommandContext(
            python_exe=PYTHON_EXE,
            run_py_file_role=RUN_PY_FILE_ROLE,
            frozen=bool(getattr(sys, "frozen", False)),
        ),
    )


def create_registered_task(
    task_type: str,
    label: str,
    command: list[str],
    cwd: Path,
    *,
    metadata: dict[str, Any] | None = None,
) -> TaskRecord:
    return build_create_registered_task(
        task_type,
        label,
        command,
        cwd,
        _task_create_context(),
        metadata=metadata,
    )


def start_process(task_type: str, label: str, command: list[str], cwd: Path, metadata: dict[str, Any] | None = None) -> TaskRecord:
    return build_start_process_task(
        task_type,
        label,
        command,
        cwd,
        ProcessTaskStartContext(
            popen=subprocess.Popen,
            subprocess_env=build_subprocess_task_env,
            create_registered_task=create_registered_task,
            snapshot_run_paths=snapshot_run_paths,
            start_monitor_thread=lambda task_id, process, previous_runs: threading.Thread(
                target=monitor_task,
                args=(task_id, process, previous_runs),
                daemon=True,
            ).start(),
            stdout_pipe=subprocess.PIPE,
            stderr_stdout=subprocess.STDOUT,
        ),
        metadata=metadata,
    )


def start_self_check() -> TaskRecord:
    return start_process(
        "self_check",
        "系统自检",
        build_python_script_command(SELF_CHECK),
        PROJECT_ROOT,
        metadata={"ui_progress": {"stage": "检查环境与脚本", "label": "系统自检"}},
    )


def step_command(step: dict[str, Any], config_path: Path, payload: dict[str, Any]) -> list[str]:
    return build_data_prep_step_command(step, config_path, payload, _data_prep_start_context())


def _data_prep_start_context() -> DataPrepStartContext:
    return DataPrepStartContext(
        resolve_path=resolve_any_path,
        read_runtime_config=read_runtime_config,
        task_step_map=task_step_map,
        current_profile=current_profile,
        resolve_runtime_precip_source=profile_runner.resolve_runtime_precip_source,
        resolve_legacy_precip_source=profile_runner.resolve_legacy_precip_source,
        data_prep_status=get_data_prep_status,
        build_python_script_command=build_python_script_command,
        clear_meteo_state=clear_meteo_state,
        forcing_pipeline_step_ids=FORCING_PIPELINE_STEP_IDS,
    )


def _data_prep_bootstrap_context() -> DataPrepBootstrapContext:
    return DataPrepBootstrapContext(
        resolve_path=resolve_any_path,
        read_runtime_config=read_runtime_config,
        task_step_map=task_step_map,
        current_profile=current_profile,
        glacier_elev_required=glacier_elev_required,
    )


def start_data_prep(payload: dict[str, Any]) -> TaskRecord:
    plan = build_data_prep_start_plan(payload, _data_prep_start_context())
    return start_process(
        "data_prep",
        plan.label,
        plan.command,
        PROJECT_ROOT,
        metadata=plan.metadata,
    )


def workflow_worker(task_id: str, config_path: Path, step_ids: list[str], payload: dict[str, Any]) -> None:
    build_data_prep_workflow_worker_run(
        task_id,
        config_path,
        step_ids,
        payload,
        DataPrepWorkflowWorkerContext(
            read_runtime_config=read_runtime_config,
            resolve_runtime_precip_source=profile_runner.resolve_runtime_precip_source,
            task_step_map=task_step_map,
            current_profile=current_profile,
            data_prep_status=get_data_prep_status,
            step_command=step_command,
            verify_step_output=verify_data_prep_step_output,
            clear_meteo_state=clear_meteo_state,
            add_task_output=add_task_output,
            set_task_metadata=set_task_metadata,
            mark_task_finished=_mark_task_finished,
            popen=subprocess.Popen,
            subprocess_env=build_subprocess_task_env,
            decode_subprocess_output_line=build_decode_subprocess_output_line,
            project_root=PROJECT_ROOT,
            forcing_pipeline_step_ids=FORCING_PIPELINE_STEP_IDS,
        ),
    )


def start_bootstrap(payload: dict[str, Any]) -> TaskRecord:
    plan = build_data_prep_bootstrap_plan(payload, _data_prep_bootstrap_context())
    record = create_registered_task("bootstrap", plan.label, plan.command, PROJECT_ROOT, metadata=plan.metadata)
    threading.Thread(target=workflow_worker, args=(record.id, plan.config_path, plan.step_ids, payload), daemon=True).start()
    return record


def _calibration_start_context() -> CalibrationStartContext:
    return CalibrationStartContext(
        resolve_path=resolve_any_path,
        read_runtime_config=read_runtime_config,
        current_profile=current_profile,
        resolve_runtime_precip_source=profile_runner.resolve_runtime_precip_source,
        validate_workspace_fields=validate_workspace_fields,
        config_text_value=_config_text_value,
        resolve_config_related_path=_resolve_config_related_path,
        build_profile_paths=build_profile_paths,
        resolve_legacy_precip_source=profile_runner.resolve_legacy_precip_source,
        glacier_formal_requirements=glacier_formal_requirements,
        resolve_objective_mode=profile_runner.resolve_objective_mode,
        resolve_param_bounds_profile=profile_runner.resolve_param_bounds_profile,
        resolve_calibration_workflow=profile_runner.resolve_calibration_workflow,
        calibration_workflow_status=profile_runner.calibration_workflow_status,
        find_manual_preset=find_manual_preset,
        build_forward_runtime_cli_args=_build_forward_runtime_cli_args,
        load_legacy_module=profile_runner.load_legacy_module,
        old_script_path=profile_runner.old_script_path,
        patch_runtime_environment=profile_runner.patch_runtime_environment,
        patch_profile_behavior=profile_runner.patch_profile_behavior,
        build_runtime_param_vector=build_runtime_param_vector,
        build_python_script_command=build_python_script_command,
        model_runner=MODEL_RUNNER,
        observed_flow_key=OBSERVED_FLOW_KEY,
        calibration_methods=CALIBRATION_METHODS,
        profile_daily=PROFILE_DAILY,
        profile_labels=PROFILE_LABELS,
        param_bounds_profile_labels=profile_runner.PARAM_BOUNDS_PROFILE_LABELS,
    )


def start_calibration(payload: dict[str, Any]) -> TaskRecord:
    plan = build_calibration_start_plan(payload, _calibration_start_context())
    return start_process("calibration", plan.label, plan.command, PROJECT_ROOT, metadata=plan.metadata)


def _tuotuohe_sync_start_context() -> TuotuoheSyncStartContext:
    return TuotuoheSyncStartContext(
        list_drives=list_drives,
        env_get=lambda key, default="": str(os.environ.get(key, default)),
        build_python_script_command=build_python_script_command,
        tuotuohe_sync_script=TUOTUOHE_SYNC_SCRIPT,
        project_runtime_dir=PROJECT_RUNTIME_DIR,
        gui_root=GUI_ROOT,
    )


def start_tuotuohe_sync(payload: dict[str, Any]) -> TaskRecord:
    plan = build_tuotuohe_sync_start_plan(payload, _tuotuohe_sync_start_context())
    return start_process("sync", plan.label, plan.command, plan.cwd)


def list_drives() -> list[str]:
    return build_list_drives()


def _safe_iterdir(directory: Path) -> list[Path]:
    return build_safe_iterdir(directory)


def _filesystem_context() -> FilesystemContext:
    return FilesystemContext(
        resolve_any_path=resolve_any_path,
        workspace_dir=WORKSPACE_DIR,
        project_runtime_dir=PROJECT_RUNTIME_DIR,
        project_root=PROJECT_ROOT,
        dir_browser_file_preview_items=DIR_BROWSER_FILE_PREVIEW_ITEMS,
        max_browser_file_items=MAX_BROWSER_FILE_ITEMS,
    )


def list_filesystem(path_value, extensions=None, kind: str = "file"):
    return build_list_filesystem(path_value, _filesystem_context(), extensions=extensions, kind=kind)


def open_path_in_explorer(payload: dict[str, Any]) -> dict[str, Any]:
    return build_open_path_in_explorer(payload, _filesystem_context())


def dashboard_payload() -> dict[str, Any]:
    return build_dashboard_payload(
        DashboardContext(
            list_templates=list_templates,
            list_workspaces=list_workspaces,
            list_runs=list_runs,
            list_tasks=list_tasks,
            project_root=PROJECT_ROOT,
            gui_root=GUI_ROOT,
            builtin_dem=BUILTIN_DEM,
            builtin_dem_1km=BUILTIN_DEM_1KM,
            builtin_dem_0p1=BUILTIN_DEM_0P1,
            project_runtime_dir=PROJECT_RUNTIME_DIR,
        )
    )


def cdsapi_status() -> dict[str, Any]:
    return build_cdsapi_status()


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


def _wizard_validation_context() -> WizardValidationContext:
    return WizardValidationContext(
        resolve_path=resolve_any_path,
        read_config=read_runtime_config,
        resolve_precip_source=resolve_precip_source,
        detect_object_type=detect_object_type,
        resolve_config_related_path=_resolve_config_related_path,
        normalize_time_step_hours=normalize_time_step_hours,
        task_time_basis=task_time_basis,
        normalized_flood_events=normalized_flood_events,
        event_windows_ui_summary=event_windows_ui_summary,
        time_sequence_messages=time_sequence_messages,
        inspect_observed_csv=inspect_observed_csv,
        build_expected_observation_index=build_expected_observation_index,
        observed_window_messages=observed_window_messages,
        event_observation_coverage_summary=event_observation_coverage_summary,
        event_observation_coverage_messages=event_observation_coverage_messages,
        inspect_boundary_csv=inspect_boundary_inflow_csv,
        build_expected_forcing_index=build_expected_forcing_index,
        boundary_info_messages=boundary_info_messages,
        meteo_validation=wizard_step4_meteo_validation,
        check_clip_dem=check_clip_dem,
        check_flow_acc=check_flow_acc,
        check_masked_flow=check_masked_flow,
        check_elevation_zone=check_elevation_zone,
        find_running_task=find_running_task,
        validate_forcing_bundle=validate_forcing_bundle,
        current_profile=current_profile,
        read_meteo_state=read_meteo_state,
        validate_workspace_fields=validate_workspace_fields,
        observed_flow_key=OBSERVED_FLOW_KEY,
        object_interbasin=OBJECT_INTERBASIN,
        time_basis_event_windows=TIME_BASIS_EVENT_WINDOWS,
    )


def wizard_validate_step(config_path_raw: str, step: int, precip_source: Any = None) -> dict[str, Any]:
    return build_wizard_validate_step(
        config_path_raw,
        step,
        _wizard_validation_context(),
        precip_source=precip_source,
    )


def _boundary_preview_context() -> BoundaryPreviewContext:
    return BoundaryPreviewContext(
        resolve_path=resolve_any_path,
        read_config=read_runtime_config,
        build_expected_time_index=build_expected_time_index,
        normalize_time_step_hours=normalize_time_step_hours,
        inspect_boundary_csv=inspect_boundary_inflow_csv,
        is_date_only_string=is_date_only_string,
    )


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
    return build_boundary_preview(
        csv_path_raw,
        date_field,
        flow_field,
        _boundary_preview_context(),
        config_path_raw=config_path_raw,
        expected_start=expected_start,
        expected_end=expected_end,
        expected_step_hours=expected_step_hours,
    )


def _workspace_completeness_context() -> WorkspaceCompletenessContext:
    return WorkspaceCompletenessContext(
        resolve_any_path=resolve_any_path,
        read_runtime_config=read_runtime_config,
        resolve_precip_source=resolve_precip_source,
        detect_object_type=detect_object_type,
        wizard_validate_step=wizard_validate_step,
        current_profile=current_profile,
        build_profile_paths=build_profile_paths,
        workspace_dem_path=_workspace_dem_path,
        configured_dem_kind=_configured_dem_kind,
        effective_precip_paths=effective_precip_paths,
        has_matching=has_matching,
        validate_workspace_fields=validate_workspace_fields,
        object_interbasin=OBJECT_INTERBASIN,
    )


def quick_workspace_completeness(config_path_raw: str, precip_source: Any = None) -> dict[str, Any]:
    return build_quick_workspace_completeness(
        config_path_raw,
        _workspace_completeness_context(),
        precip_source=precip_source,
    )


def workspace_completeness(config_path_raw: str, *, quick: bool = False, precip_source: Any = None) -> dict[str, Any]:
    return build_workspace_completeness(
        config_path_raw,
        _workspace_completeness_context(),
        quick=quick,
        precip_source=precip_source,
    )


def workspace_workflow_summary(config_path_raw: str, *, quick: bool = False, precip_source: Any = None) -> dict[str, Any]:
    return build_workspace_workflow_summary(
        config_path_raw,
        _workspace_completeness_context(),
        quick=quick,
        precip_source=precip_source,
    )


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
    return build_workspace_detailed_check(
        config_path_raw,
        _workspace_detailed_check_context(),
        precip_source=precip_source,
    )


def _workspace_detailed_check_context() -> WorkspaceDetailedCheckContext:
    return WorkspaceDetailedCheckContext(
        resolve_path=resolve_any_path,
        read_config=read_runtime_config,
        current_profile=current_profile,
        build_profile_paths=build_profile_paths,
        configured_precip_source=configured_precip_source,
        resolve_precip_source=resolve_precip_source,
        detect_object_type=detect_object_type,
        read_meteo_state=read_meteo_state,
        workspace_dem_path=_workspace_dem_path,
        configured_dem_kind=_configured_dem_kind,
        read_json_file=read_json_file,
        validate_forcing_bundle=validate_forcing_bundle,
        normalize_time_step_hours=normalize_time_step_hours,
        resolve_config_related_path=_resolve_config_related_path,
        build_reasonableness_checks=build_reasonableness_checks,
        format_timestamp_for_display=format_timestamp_for_display,
        fmt_num=_fmt_num,
        profile_labels=PROFILE_LABELS,
        object_labels=OBJECT_LABELS,
        object_interbasin=OBJECT_INTERBASIN,
        observed_flow_key=OBSERVED_FLOW_KEY,
    )


def workspace_advice(config_path_raw: str, precip_source: Any = None) -> dict[str, Any]:
    return build_workspace_advice(
        config_path_raw,
        WorkspaceAdviceContext(
            resolve_any_path=resolve_any_path,
            read_runtime_config=read_runtime_config,
            current_profile=current_profile,
            resolve_precip_source=resolve_precip_source,
            workspace_completeness=workspace_completeness,
            validate_workspace_fields=validate_workspace_fields,
            validate_forcing_bundle=validate_forcing_bundle,
            list_manual_presets=list_manual_presets,
            detect_object_type=detect_object_type,
            profile_daily=PROFILE_DAILY,
            profile_hourly=PROFILE_HOURLY,
            object_interbasin=OBJECT_INTERBASIN,
            daily_param_bounds_profile=profile_runner.DEFAULT_DAILY_PARAM_BOUNDS_PROFILE,
            hourly_param_bounds_profile=profile_runner.PARAM_BOUNDS_PROFILE_HOURLY,
            param_bounds_profile_labels=profile_runner.PARAM_BOUNDS_PROFILE_LABELS,
        ),
        precip_source=precip_source,
    )


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
    build_mark_task_finished(task_id, _task_mutation_context(), ok=ok, return_code=return_code, result=result)


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
    build_meteo_import_worker_run(
        task_id,
        payload,
        MeteoImportWorkerContext(
            perform_meteo_import=perform_meteo_import,
            add_task_exception_output=add_task_exception_output,
            mark_task_finished=_mark_task_finished,
        ),
    )


def _meteo_import_start_context() -> MeteoImportStartContext:
    return MeteoImportStartContext(
        resolve_path=resolve_any_path,
        read_runtime_config=read_runtime_config,
        current_profile=current_profile,
        resolve_runtime_precip_source=profile_runner.resolve_runtime_precip_source,
    )


def start_meteo_import(payload: dict[str, Any]) -> TaskRecord:
    plan = build_meteo_import_start_plan(payload, _meteo_import_start_context())
    record = create_registered_task("meteo_import", plan.label, plan.command, PROJECT_ROOT, metadata=plan.metadata)
    threading.Thread(target=meteo_import_worker, args=(record.id, dict(payload)), daemon=True).start()
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
    source_obs_series = build_load_run_series_map(run_path, "q_obs")
    source_boundary_series = build_load_run_series_map(run_path, "q_boundary_inflow")
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
            observation_state=build_capture_forward_observation_state(module),
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
        build_restore_forward_observation_state(module, entry.observation_state)
        params = dict(context["params"])
        base_params = dict(context.get("source_metadata", {}).get("optimized_params", {}) or {})
        started_at = time.time()
        if stage_callback is not None:
            stage_callback("执行前向模拟", "[阶段] 执行前向模拟")
        param_vector, clean_params, adjusted = build_runtime_param_vector(module, params, base_params=base_params)
        obs_restored = build_restore_forward_observed_series(module, context.get("source_obs_series", {}))
        sim = call_with_output_capture(output_callback, module.run_simulation, param_vector)
        boundary_restored = False
        if bool(context.get("boundary_replay_fallback")):
            boundary_restored = build_restore_forward_boundary_series(module, sim, context.get("source_boundary_series", {}))
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
    return build_run_csv_preview(run_path, limit=limit)


def _run_csv_date_bounds(run_path: Path) -> dict[str, Any]:
    return build_run_csv_date_bounds(run_path)


def _read_run_metrics_snapshot(run_path: Path) -> dict[str, Any]:
    return build_read_run_metrics_snapshot(run_path, read_json_file)


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
        build_restore_forward_observation_state(module, entry.observation_state)
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


def set_task_detected_runs(task_id: str, detected_runs: list[str]) -> None:
    build_set_task_detected_runs(task_id, detected_runs, _task_mutation_context())


def forward_sim_worker(task_id: str, payload: dict[str, Any]) -> None:
    build_forward_simulation_worker_run(
        task_id,
        payload,
        ForwardSimulationWorkerContext(
            run_forward_simulation=_run_forward_simulation,
            set_task_metadata=set_task_metadata,
            add_task_output=add_task_output,
            add_task_exception_output=add_task_exception_output,
            mark_task_finished=_mark_task_finished,
            set_detected_runs=set_task_detected_runs,
        ),
    )


def manual_start_worker(task_id: str, payload: dict[str, Any]) -> None:
    build_manual_start_worker_run(
        task_id,
        payload,
        ManualStartWorkerContext(
            create_manual_start_result=_create_manual_start_result,
            set_task_metadata=set_task_metadata,
            add_task_output=add_task_output,
            add_task_exception_output=add_task_exception_output,
            mark_task_finished=_mark_task_finished,
            set_detected_runs=set_task_detected_runs,
        ),
    )


def forecast_restart(payload: dict[str, Any]) -> dict[str, Any]:
    import forecast_run

    return build_forecast_restart_run(
        payload,
        ForecastRestartRunContext(
            build_args=lambda checked_payload: build_forecast_restart_args(
                checked_payload,
                resolve_path=resolve_any_path,
                read_json_file=read_json_file,
            ),
            ensure_input_ready=ensure_forecast_input_ready,
            run_forecast=forecast_run.run_forecast,
        ),
    )


def forecast_restart_with_progress(payload: dict[str, Any], stage_callback: Callable[[str, str | None], None]) -> dict[str, Any]:
    import forecast_run

    return build_forecast_restart_run_with_progress(
        payload,
        ForecastRestartRunContext(
            build_args=lambda checked_payload: build_forecast_restart_args(
                checked_payload,
                resolve_path=resolve_any_path,
                read_json_file=read_json_file,
            ),
            ensure_input_ready=ensure_forecast_input_ready,
            run_forecast=forecast_run.run_forecast,
        ),
        stage_callback,
    )


def _forecast_input_check_context() -> ForecastInputCheckContext:
    return ForecastInputCheckContext(
        resolve_path=resolve_any_path,
        read_json_file=read_json_file,
        read_runtime_config=read_runtime_config,
        build_profile_paths=build_profile_paths,
        resolve_profile=resolve_profile,
        run_parameter_context=_run_parameter_context,
        profile_labels=PROFILE_LABELS,
        objective_label=_objective_label_zh,
        precip_source_label=display_precip_source_label,
        station_precip_mode_label=_station_precip_mode_label,
        normalize_time_step_hours=normalize_time_step_hours,
        is_date_only_string=is_date_only_string,
        validate_tif_time_series=validate_tif_time_series,
        format_time_for_check=_format_time_for_check,
        analyze_station_precip_inputs=analyze_station_precip_inputs,
        meteo_key=METEO_KEY,
        meteo_precip_mode_key=METEO_PRECIP_MODE_KEY,
        time_basis_forecast_window=TIME_BASIS_FORECAST_WINDOW,
        time_basis_labels=TIME_BASIS_LABELS,
    )


def forecast_input_check(payload: dict[str, Any]) -> dict[str, Any]:
    return build_forecast_input_check(payload, _forecast_input_check_context())


def ensure_forecast_input_ready(payload: dict[str, Any]) -> dict[str, Any]:
    return build_ensure_forecast_input_ready(payload, _forecast_input_check_context())


def forecast_restart_worker(task_id: str, payload: dict[str, Any]) -> None:
    build_forecast_restart_worker_run(
        task_id,
        payload,
        ForecastRestartWorkerContext(
            run_with_progress=forecast_restart_with_progress,
            set_task_metadata=set_task_metadata,
            add_task_output=add_task_output,
            add_task_exception_output=add_task_exception_output,
            mark_task_finished=_mark_task_finished,
            set_detected_runs=set_task_detected_runs,
        ),
    )


def _forward_simulation_start_context() -> ForwardSimulationStartContext:
    return ForwardSimulationStartContext(
        build_forward_payload_context=_build_forward_payload_context,
    )


def start_forward_simulation(payload: dict[str, Any]) -> TaskRecord:
    plan = build_forward_simulation_start_plan(payload, _forward_simulation_start_context())
    record = create_registered_task("forward_sim", plan.label, plan.command, PROJECT_ROOT, metadata=plan.metadata)
    threading.Thread(target=forward_sim_worker, args=(record.id, dict(payload)), daemon=True).start()
    return record


def _forecast_restart_start_context() -> ForecastRestartStartContext:
    return ForecastRestartStartContext(
        build_args=lambda payload: build_forecast_restart_args(
            payload,
            resolve_path=resolve_any_path,
            read_json_file=read_json_file,
        ),
        resolve_path=resolve_any_path,
        ensure_input_ready=ensure_forecast_input_ready,
    )


def start_forecast_restart(payload: dict[str, Any]) -> TaskRecord:
    plan = build_forecast_restart_start_plan(payload, _forecast_restart_start_context())
    record = create_registered_task("forecast_restart", plan.label, plan.command, PROJECT_ROOT, metadata=plan.metadata)
    threading.Thread(target=forecast_restart_worker, args=(record.id, plan.checked_payload), daemon=True).start()
    return record


def _manual_start_start_context() -> ManualStartStartContext:
    return ManualStartStartContext(
        build_workspace_forward_context=_build_workspace_forward_context,
    )


def start_manual_start(payload: dict[str, Any]) -> TaskRecord:
    config_path = resolve_any_path(str(payload.get("config_path", "")), must_exist=True)
    current = find_running_task("manual_start", str(config_path))
    if current is not None:
        return current
    plan = build_manual_start_start_plan(payload, config_path, _manual_start_start_context())
    record = create_registered_task("manual_start", plan.label, plan.command, PROJECT_ROOT, metadata=plan.metadata)
    threading.Thread(target=manual_start_worker, args=(record.id, dict(payload)), daemon=True).start()
    return record


class StudioHandler(BaseHTTPRequestHandler):
    server_version = "HBVStudio/3.0"
    CONNECTION_GONE_ERRORS = (BrokenPipeError, ConnectionAbortedError, ConnectionResetError)
    GET_ROUTE_HANDLERS = GET_API_ROUTE_HANDLERS
    POST_ROUTE_HANDLERS = POST_API_ROUTE_HANDLERS

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

    def send_bytes(
        self,
        body: bytes,
        content_type: str,
        status: int = 200,
        headers: dict[str, str] | None = None,
    ) -> bool:
        try:
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            for key, value in (headers or {}).items():
                self.send_header(key, value)
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

    def _dispatch_api_route(self, route_handlers: dict[str, str], path: str, argument: Any) -> None:
        handler_name = route_handlers.get(path)
        if handler_name is None:
            self.send_error_json("未知接口。", status=404)
            return
        try:
            getattr(self, handler_name)(argument)
        except FileNotFoundError as exc:
            self.send_error_json(str(exc), status=404)
        except ValueError as exc:
            self.send_error_json(str(exc), status=400)
        except Exception as exc:
            self.send_error_json(str(exc), status=500)
            traceback.print_exc()

    def handle_api_get(self, parsed: Any) -> None:
        self._dispatch_api_route(self.GET_ROUTE_HANDLERS, parsed.path, parse_qs(parsed.query))

    def _api_get_health(self, query: dict[str, list[str]]) -> None:
        self.send_json(health_payload())

    def _api_get_dashboard(self, query: dict[str, list[str]]) -> None:
        self.send_json({"ok": True, "data": dashboard_payload()})

    def _api_get_templates(self, query: dict[str, list[str]]) -> None:
        self.send_json({"ok": True, "data": list_templates()})

    def _api_get_workspaces(self, query: dict[str, list[str]]) -> None:
        self.send_json({"ok": True, "data": list_workspaces()})

    def _api_get_workspace(self, query: dict[str, list[str]]) -> None:
        path, data = load_workspace_config(unquote(query.get("path", [""])[0]))
        self.send_json({"ok": True, "path": str(path.resolve()), "display_path": to_display_path(path), "data": data})

    def _api_get_runs(self, query: dict[str, list[str]]) -> None:
        self.send_json({"ok": True, "data": list_runs()})

    def _api_get_run(self, query: dict[str, list[str]]) -> None:
        self.send_json({"ok": True, "data": load_run_detail(unquote(query.get("path", [""])[0]))})

    def _api_get_tasks(self, query: dict[str, list[str]]) -> None:
        self.send_json({"ok": True, "data": list_tasks()})

    def _api_get_cdsapi_status(self, query: dict[str, list[str]]) -> None:
        self.send_json({"ok": True, "data": cdsapi_status()})

    def _api_get_fs_list(self, query: dict[str, list[str]]) -> None:
        raw_path = unquote(query.get("path", [""])[0])
        exts = [item for item in query.get("extensions", [""])[0].split(",") if item]
        kind = query.get("kind", ["file"])[0] or "file"
        self.send_json({"ok": True, "data": list_filesystem(raw_path, exts, kind=kind)})

    def _api_get_obs_info(self, query: dict[str, list[str]]) -> None:
        csv_path = unquote(query.get("path", [""])[0])
        date_field = query.get("date_field", [""])[0] or None
        target_step_hours_raw = query.get("target_step_hours", [""])[0]
        target_step_hours = float(target_step_hours_raw) if target_step_hours_raw else None
        self.send_json({"ok": True, "data": observed_info(csv_path, date_field=date_field, target_step_hours=target_step_hours)})

    def _api_get_suggest_bbox(self, query: dict[str, list[str]]) -> None:
        self.send_json({"ok": True, "data": fill_bbox_from_shp(unquote(query.get("shp_path", [""])[0]))})

    def _api_get_suggest_cfmax_threshold(self, query: dict[str, list[str]]) -> None:
        shp = unquote(query.get("shp_path", [""])[0])
        dem = unquote(query.get("dem_path", [""])[0]) or str(BUILTIN_DEM.resolve())
        self.send_json({"ok": True, "data": suggest_cfmax_threshold(shp, dem)})

    def _api_get_geo_dem(self, query: dict[str, list[str]]) -> None:
        raw_path = unquote(query.get("ws", [""])[0] or query.get("config_path", [""])[0] or query.get("path", [""])[0])
        style = unquote(query.get("style", ["hillshade"])[0] or "hillshade")
        image = workspace_dem_png(raw_path, style=style)
        self.send_bytes(
            image["body"],
            str(image.get("content_type") or "image/png"),
            headers={
                "X-HBV-Geo-Bounds": json_dumps_safe(image.get("bounds") or {}),
                "X-HBV-Geo-Metrics": json_dumps_safe(image.get("metrics") or {}),
            },
        )

    def _api_get_geo_overview(self, query: dict[str, list[str]]) -> None:
        raw_path = unquote(query.get("config_path", [""])[0] or query.get("path", [""])[0])
        self.send_json({"ok": True, "data": workspace_geo_overview(raw_path)})

    def _api_get_geo_basin(self, query: dict[str, list[str]]) -> None:
        raw_path = unquote(query.get("ws", [""])[0] or query.get("config_path", [""])[0] or query.get("path", [""])[0])
        self.send_json({"ok": True, "data": workspace_basin_geojson(raw_path)})

    def _api_get_geo_elevation_zones(self, query: dict[str, list[str]]) -> None:
        raw_path = unquote(query.get("ws", [""])[0] or query.get("config_path", [""])[0] or query.get("path", [""])[0])
        self.send_json({"ok": True, "data": workspace_elevation_zones_geojson(raw_path)})

    def _api_get_geo_glacier(self, query: dict[str, list[str]]) -> None:
        raw_path = unquote(query.get("ws", [""])[0] or query.get("config_path", [""])[0] or query.get("path", [""])[0])
        self.send_json({"ok": True, "data": workspace_glacier_geojson(raw_path)})

    def _api_get_geo_stations(self, query: dict[str, list[str]]) -> None:
        raw_path = unquote(query.get("ws", [""])[0] or query.get("config_path", [""])[0] or query.get("path", [""])[0])
        self.send_json({"ok": True, "data": workspace_station_geojson(raw_path)})

    def _api_get_data_prep_steps(self, query: dict[str, list[str]]) -> None:
        raw_config = unquote(query.get("config_path", [""])[0])
        self.send_json({"ok": True, "data": get_data_prep_steps_payload(raw_config)})

    def _api_get_data_prep_status(self, query: dict[str, list[str]]) -> None:
        self.send_json({
            "ok": True,
            "data": get_data_prep_status(
                unquote(query.get("config_path", [""])[0]),
                precip_source=unquote(query.get("prec_source", [""])[0]),
            ),
        })

    def _api_get_config_validate(self, query: dict[str, list[str]]) -> None:
        stage = query.get("stage", ["calibration"])[0] or "calibration"
        self.send_json({
            "ok": True,
            "data": validate_workspace_fields(
                unquote(query.get("config_path", [""])[0]),
                stage=stage,
                precip_source=unquote(query.get("prec_source", [""])[0]),
            ),
        })

    def _api_get_wizard_validate_step(self, query: dict[str, list[str]]) -> None:
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

    def _api_get_boundary_preview(self, query: dict[str, list[str]]) -> None:
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

    def _api_get_workspace_completeness(self, query: dict[str, list[str]]) -> None:
        quick = query.get("quick", ["0"])[0] in {"1", "true", "yes"}
        self.send_json({
            "ok": True,
            "data": workspace_completeness(
                unquote(query.get("config_path", [""])[0]),
                quick=quick,
                precip_source=unquote(query.get("prec_source", [""])[0]),
            ),
        })

    def _api_get_workspace_detailed_check(self, query: dict[str, list[str]]) -> None:
        self.send_json({
            "ok": True,
            "data": workspace_detailed_check(
                unquote(query.get("config_path", [""])[0]),
                precip_source=unquote(query.get("prec_source", [""])[0]),
            ),
        })

    def _api_get_workspace_layout(self, query: dict[str, list[str]]) -> None:
        raw_path = unquote(query.get("config_path", [""])[0] or query.get("path", [""])[0])
        self.send_json({"ok": True, "data": workspace_layout_summary(raw_path)})

    def _api_get_workspace_advice(self, query: dict[str, list[str]]) -> None:
        self.send_json({
            "ok": True,
            "data": workspace_advice(
                unquote(query.get("config_path", [""])[0]),
                precip_source=unquote(query.get("prec_source", [""])[0]),
            ),
        })

    def _api_get_manual_presets(self, query: dict[str, list[str]]) -> None:
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

    def handle_api_post(self, parsed: Any) -> None:
        try:
            payload = self.read_json_body()
        except ValueError as exc:
            self.send_error_json(str(exc), status=400)
            return
        except Exception as exc:
            self.send_error_json(str(exc), status=500)
            traceback.print_exc()
            return
        self._dispatch_api_route(self.POST_ROUTE_HANDLERS, parsed.path, payload)

    def _api_post_workspace_save(self, payload: dict[str, Any]) -> None:
        raw_path = str(payload.get("path", "")).strip()
        if not raw_path:
            raise ValueError("缺少工作区配置保存路径。")
        path = resolve_any_path(raw_path, must_exist=False)
        normalized = normalize_config_before_save(payload.get("data", {}), path)
        write_json_file(path, normalized)
        self.send_json({"ok": True, "path": str(path.resolve()), "display_path": to_display_path(path), "data": read_json_file(path)})

    def _api_post_template_instantiate(self, payload: dict[str, Any]) -> None:
        self.send_json({"ok": True, "data": instantiate_template(payload)}, status=201)

    def _api_post_import_workspace(self, payload: dict[str, Any]) -> None:
        self.send_json({"ok": True, "data": create_workspace_from_import(payload)}, status=201)

    def _api_post_bootstrap_start(self, payload: dict[str, Any]) -> None:
        self.send_json({"ok": True, "task": start_bootstrap(payload).as_dict()}, status=201)

    def _api_post_data_prep_start(self, payload: dict[str, Any]) -> None:
        self.send_json({"ok": True, "task": start_data_prep(payload).as_dict()}, status=201)

    def _api_post_calibration_start(self, payload: dict[str, Any]) -> None:
        self.send_json({"ok": True, "task": start_calibration(payload).as_dict()}, status=201)

    def _api_post_self_check_start(self, payload: dict[str, Any]) -> None:
        self.send_json({"ok": True, "task": start_self_check().as_dict()}, status=201)

    def _api_post_template_sync_tuotuohe(self, payload: dict[str, Any]) -> None:
        self.send_json({"ok": True, "task": start_tuotuohe_sync(payload).as_dict()}, status=201)

    def _api_post_wizard_save_step(self, payload: dict[str, Any]) -> None:
        self.send_json({"ok": True, "data": wizard_save_step(payload)})

    def _api_post_gis_import(self, payload: dict[str, Any]) -> None:
        self.send_json({"ok": True, "data": import_gis_files(payload)})

    def _api_post_meteo_import_start(self, payload: dict[str, Any]) -> None:
        self.send_json({"ok": True, "task": start_meteo_import(payload).as_dict()}, status=201)

    def _api_post_meteo_import(self, payload: dict[str, Any]) -> None:
        self.send_json({"ok": True, "data": import_meteo_files(payload)})

    def _api_post_simulate_forward_start(self, payload: dict[str, Any]) -> None:
        self.send_json({"ok": True, "task": start_forward_simulation(payload).as_dict()}, status=201)

    def _api_post_simulate_forward(self, payload: dict[str, Any]) -> None:
        self.send_json({"ok": True, "data": forward_simulate(payload)})

    def _api_post_forecast_restart_start(self, payload: dict[str, Any]) -> None:
        self.send_json({"ok": True, "task": start_forecast_restart(payload).as_dict()}, status=201)

    def _api_post_forecast_restart(self, payload: dict[str, Any]) -> None:
        self.send_json({"ok": True, "data": forecast_restart(payload)})

    def _api_post_forecast_input_check(self, payload: dict[str, Any]) -> None:
        self.send_json({"ok": True, "data": forecast_input_check(payload)})

    def _api_post_manual_start_start(self, payload: dict[str, Any]) -> None:
        self.send_json({"ok": True, "task": start_manual_start(payload).as_dict()}, status=201)

    def _api_post_manual_preset_save(self, payload: dict[str, Any]) -> None:
        self.send_json({"ok": True, "data": save_manual_preset(payload)})

    def _api_post_manual_preset_delete(self, payload: dict[str, Any]) -> None:
        self.send_json({"ok": True, "data": delete_manual_preset(payload)})

    def _api_post_run_export_excel(self, payload: dict[str, Any]) -> None:
        self.send_json({"ok": True, "data": export_run_excel(payload)})

    def _api_post_run_rename(self, payload: dict[str, Any]) -> None:
        self.send_json({"ok": True, "data": rename_run(payload)})

    def _api_post_run_delete(self, payload: dict[str, Any]) -> None:
        self.send_json({"ok": True, "data": delete_run(str(payload.get("path", "")).strip())})

    def _api_post_workspace_delete(self, payload: dict[str, Any]) -> None:
        raw_path = str(payload.get("path", "")).strip()
        if not raw_path:
            raise ValueError("缺少工作区路径。")
        self.send_json({"ok": True, "data": delete_workspace(raw_path)})

    def _api_post_fs_open_path(self, payload: dict[str, Any]) -> None:
        self.send_json({"ok": True, "data": open_path_in_explorer(payload)})

    def _api_post_app_window_unload(self, payload: dict[str, Any]) -> None:
        result = build_app_window_unload(_app_lifecycle_context())
        self.send_json({"ok": True, "data": result.data}, status=result.status)

    def _api_post_app_quit(self, payload: dict[str, Any]) -> None:
        result = build_app_quit(_app_lifecycle_context())
        if not result.ok:
            self.send_error_json(result.error, status=result.status)
            return
        self.send_json({"ok": True, "data": result.data}, status=result.status)
        if result.shutdown_message:
            request_server_shutdown(self.server, result.shutdown_message, delay_sec=result.shutdown_delay_sec)

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
