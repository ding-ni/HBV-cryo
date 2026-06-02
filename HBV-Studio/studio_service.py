#!/usr/bin/env python
# -*- coding: utf-8 -*-
from __future__ import annotations

import argparse
import copy
import csv
import hashlib
import io
import json
import mimetypes
import os
import shutil
import socket
import subprocess
import sys
import threading
import time
import traceback
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
    DataPrepStepCatalogContext,
    DataPrepTaskOutputContext,
    DataPrepWorkflowWorkerContext,
    data_prep_bootstrap_plan as build_data_prep_bootstrap_plan,
    data_prep_start_plan as build_data_prep_start_plan,
    data_prep_step_command as build_data_prep_step_command,
    data_prep_workflow_worker_run as build_data_prep_workflow_worker_run,
    data_prep_status as build_data_prep_status,
    data_prep_steps as build_data_prep_steps,
    data_prep_steps_payload as build_data_prep_steps_payload,
    resolve_data_prep_step as build_resolve_data_prep_step,
    verify_data_prep_step_output as build_verify_data_prep_step_output,
    verify_data_prep_task_output as build_verify_data_prep_task_output,
)
from services.boundary import BoundaryInflowInspectContext, BoundaryPreviewContext
from services.boundary import boundary_info_messages as build_boundary_info_messages
from services.boundary import boundary_preview as build_boundary_preview
from services.boundary import inspect_boundary_inflow_csv as build_inspect_boundary_inflow_csv
from services.calibration import CalibrationStartContext
from services.calibration import calibration_start_plan as build_calibration_start_plan
from services.dashboard import DashboardContext, dashboard_payload as build_dashboard_payload
from services.event_config import (
    TIME_BASIS_CONTINUOUS,
    TIME_BASIS_EVENT_WINDOWS,
    TIME_BASIS_FORECAST_WINDOW,
    TIME_BASIS_LABELS,
    event_date_range as build_event_date_range,
    event_initial_state_policy_summary as build_event_initial_state_policy_summary,
    event_window_index as build_event_window_index,
    flood_event_raw_config as build_flood_event_raw_config,
    normalize_event_initial_state_policy as build_normalize_event_initial_state_policy,
    task_time_basis as build_task_time_basis,
    truthy_config as build_truthy_config,
)
from services.event_windows import EventWindowContext
from services.event_windows import build_expected_forcing_index as build_event_expected_forcing_index
from services.event_windows import build_expected_observation_index as build_event_expected_observation_index
from services.event_windows import build_expected_time_index as build_event_expected_time_index
from services.event_windows import event_forcing_coverage_summary as build_event_forcing_coverage_summary
from services.event_windows import event_observation_coverage_messages as build_event_observation_coverage_messages
from services.event_windows import event_observation_coverage_summary as build_event_observation_coverage_summary
from services.event_windows import event_windows_ui_summary as build_event_windows_ui_summary
from services.event_windows import input_time_basis_ui_summary as build_input_time_basis_ui_summary
from services.event_windows import normalized_flood_events as build_normalized_flood_events
from services.filesystem import (
    FilesystemContext,
    FilesystemPathContext,
    FilesystemPlaceholderContext,
    ensure_within as build_ensure_within,
    is_within_any_root as build_is_within_any_root,
    is_within_root as build_is_within_root,
    list_drives as build_list_drives,
    list_filesystem as build_list_filesystem,
    normalize_legacy_project_paths as build_normalize_legacy_project_paths,
    open_path_in_explorer as build_open_path_in_explorer,
    placeholder_roots_for_config_path as build_placeholder_roots_for_config_path,
    remap_legacy_project_path as build_remap_legacy_project_path,
    replace_placeholders as build_replace_placeholders,
    resolve_any_path as build_resolve_any_path,
    safe_iterdir as build_safe_iterdir,
    to_display_path as build_to_display_path,
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
from services.forcing_validation import ForcingAlignedStatusContext
from services.forcing_validation import ForcingDownloadStatusContext
from services.forcing_validation import ForcingInputsReadyContext
from services.forcing_validation import ForcingPreprocessStatusContext
from services.forcing_validation import ForcingValidationContext
from services.forcing_validation import HourlyForcingReadyContext
from services.forcing_validation import check_aligned_forcing_status as build_check_aligned_forcing_status
from services.forcing_validation import check_daily_era5_download_status as build_check_daily_era5_download_status
from services.forcing_validation import check_daily_era5_processed_status as build_check_daily_era5_processed_status
from services.forcing_validation import check_daily_prec_status as build_check_daily_prec_status
from services.forcing_validation import check_daily_temp_evap_status as build_check_daily_temp_evap_status
from services.forcing_validation import check_forcing_inputs_ready as build_check_forcing_inputs_ready
from services.forcing_validation import check_hourly_era5_download_status as build_check_hourly_era5_download_status
from services.forcing_validation import check_hourly_prec_status as build_check_hourly_prec_status
from services.forcing_validation import check_hourly_temp_evap_status as build_check_hourly_temp_evap_status
from services.forcing_validation import configured_daily_meteo_sources as build_configured_daily_meteo_sources
from services.forcing_validation import hourly_forcing_ready_status as build_hourly_forcing_ready_status
from services.forcing_validation import prefer_raw_or_aligned_group_status as build_prefer_raw_or_aligned_group_status
from services.forcing_validation import validate_forcing_bundle as build_validate_forcing_bundle
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
from services.geo_status import GeoStatusContext
from services.geo_status import check_clip_dem as build_check_clip_dem
from services.geo_status import check_elevation_zone as build_check_elevation_zone
from services.geo_status import check_flow_acc as build_check_flow_acc
from services.geo_status import check_masked_flow as build_check_masked_flow
from services.glacier_status import GlacierStatusContext
from services.glacier_status import check_glacier_elev as build_check_glacier_elev
from services.glacier_status import check_glacier_mask as build_check_glacier_mask
from services.glacier_status import check_glacier_reference as build_check_glacier_reference
from services.glacier_status import glacier_elev_required as build_glacier_elev_required
from services.glacier_status import glacier_formal_requirements as build_glacier_formal_requirements
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
from services.json_utils import json_dumps_safe as build_json_dumps_safe
from services.json_utils import json_safe_value as build_json_safe_value
from services.json_utils import read_json_file as build_read_json_file
from services.json_utils import write_json_file as build_write_json_file
from services.meteo_import import MeteoImportStartContext
from services.meteo_import import MeteoImportWorkerContext
from services.meteo_import import meteo_import_start_plan as build_meteo_import_start_plan
from services.meteo_import import meteo_import_worker_run as build_meteo_import_worker_run
from services.meteo_config import (
    METEO_CUSTOM_PET_DIR_KEY,
    METEO_CUSTOM_PREC_DIR_KEY,
    METEO_CUSTOM_TEMP_DIR_KEY,
    METEO_HOURLY_PREC_DIR_KEY,
    METEO_KEY,
    METEO_PET_SOURCE_KEY,
    METEO_PRECIP_MODE_KEY,
    METEO_PRECIP_SOURCE_KEY,
    METEO_PRECIP_SOURCE_LEGACY_KEY,
    METEO_STATION_META_KEY,
    METEO_STATION_PREC_KEY,
    METEO_TEMP_SOURCE_KEY,
    configured_precip_source as build_configured_precip_source,
    display_precip_source_label as build_display_precip_source_label,
    display_runtime_precip_label as build_display_runtime_precip_label,
    effective_precip_source as build_effective_precip_source,
    resolve_precip_source as build_resolve_precip_source,
)
from services.meteo_status import cdsapi_status as build_cdsapi_status
from services.observed import ObservedInfoContext, ObservedWindowContext
from services.observed import observed_info as build_observed_info
from services.observed import observed_window_messages as build_observed_window_messages
from services.raster_time_series import scan_tif_time_series as build_scan_tif_time_series
from services.raster_time_series import validate_tif_grid_alignment as build_validate_tif_grid_alignment
from services.raster_time_series import validate_tif_time_series as build_validate_tif_time_series
from services.precip_strategy_status import PrecipStrategyStatusContext
from services.precip_strategy_status import check_precip_strategy_outputs as build_check_precip_strategy_outputs
from services.station_precip import StationPrecipAnalysisContext
from services.station_precip import StationPrecipStrategyStatusContext
from services.station_precip import analyze_station_precip_inputs as build_analyze_station_precip_inputs
from services.station_precip import check_station_precip_strategy_status as build_check_station_precip_strategy_status
from services.station_precip import station_precip_mode_label as build_station_precip_mode_label
from services.runs import RunCalibrationTaskContext, RunConfigBoundaryContext, RunConfigDataSourceContext, RunConfigIdentityContext, RunConfigSyncContext, RunDetailContext, RunDiscoveryContext, RunExportContext, RunListContext, RunMetadataCompatibilityContext, RunMutationContext
from services.runs import RunMetadataNormalizationContext, RunMetadataObjectTypeContext
from services.runs import RunPortablePathContext, RunWorkspaceConfigReferenceContext
from services.runs import RunReplayConfigContext, RunSourceReferenceContext, RunSummaryContext, RunWorkspaceNameContext
from services.runs import apply_run_replay_config_overrides as build_apply_run_replay_config_overrides
from services.runs import build_calibration_task_result as build_run_calibration_task_result
from services.runs import capture_forward_observation_state as build_capture_forward_observation_state
from services.runs import delete_run as build_delete_run
from services.runs import discover_run_entries as build_discover_run_entries
from services.runs import discover_runtime_roots as build_discover_runtime_roots
from services.runs import export_run_excel as build_export_run_excel
from services.runs import build_run_summary as build_run_summary_payload
from services.runs import first_existing_path as build_first_existing_path
from services.runs import has_custom_result_title as build_has_custom_result_title
from services.runs import infer_project_roots_from_run_path as build_infer_project_roots_from_run_path
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
from services.runs import normalize_run_metadata_payload as build_normalize_run_metadata_payload
from services.runs import normalized_method_label as build_normalized_method_label
from services.runs import normalized_selected_result_label as build_normalized_selected_result_label
from services.runs import optimization_stage_has_execution as build_optimization_stage_has_execution
from services.runs import optimization_stage_payload as build_optimization_stage_payload
from services.runs import pick_latest_run_path as build_pick_latest_run_path
from services.runs import portableize_value_paths as build_portableize_value_paths
from services.runs import read_run_metrics_snapshot as build_read_run_metrics_snapshot
from services.runs import rename_run as build_rename_run
from services.runs import restore_forward_boundary_series as build_restore_forward_boundary_series
from services.runs import restore_forward_observation_state as build_restore_forward_observation_state
from services.runs import restore_forward_observed_series as build_restore_forward_observed_series
from services.runs import resolve_source_run_reference as build_resolve_source_run_reference
from services.runs import resolve_metadata_object_type as build_resolve_metadata_object_type
from services.runs import resolve_workspace_config_reference as build_resolve_workspace_config_reference
from services.runs import run_csv_date_bounds as build_run_csv_date_bounds
from services.runs import run_csv_preview as build_run_csv_preview
from services.runs import run_parameter_context as build_run_parameter_context
from services.runs import default_run_export_fields as build_default_run_export_fields
from services.runs import run_kind_from_metadata as build_run_kind_from_metadata
from services.runs import run_kind_label as build_run_kind_label
from services.runs import workspace_name_for_summary as build_workspace_name_for_summary
from services.runs import run_time_label as build_run_time_label
from services.runs import run_update_timestamps as build_run_update_timestamps
from services.runs import snapshot_run_paths as build_snapshot_run_paths
from services.runs import to_portable_path as build_to_portable_path
from services.runs import workspace_config_candidates as build_workspace_config_candidates
from services.runs import workspace_roots_hint_from_metadata as build_workspace_roots_hint_from_metadata
from services.run_hydrology import RunHydrologyContext
from services.run_hydrology import build_hydrology_summary as build_run_hydrology_summary
from services.run_hydrology import ensure_hydrology_diagnostic_report as build_ensure_hydrology_diagnostic_report
from services.run_hydrology import objective_label_zh as build_hydrology_objective_label_zh
from services.system_status import (
    HealthContext,
    health_payload as build_health_payload,
    source_files_latest_mtime as build_source_files_latest_mtime,
)
from services.time_utils import format_timestamp_for_display as build_format_timestamp_for_display
from services.time_utils import detect_series_step_hours as build_detect_series_step_hours
from services.time_utils import expected_warmup_end as build_expected_warmup_end
from services.time_utils import is_date_only_string as build_is_date_only_string
from services.time_utils import normalize_time_step_hours as build_normalize_time_step_hours
from services.time_utils import parse_time_from_name as build_parse_time_from_name
from services.time_utils import time_sequence_messages as build_time_sequence_messages
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
    build_empty_workspace as build_empty_workspace_config,
    create_workspace_from_import as build_create_workspace_from_import,
    delete_workspace as build_delete_workspace,
    detect_object_type as build_detect_object_type,
    detect_profile_from_payload as build_detect_profile_from_payload,
    find_template as build_find_template,
    instantiate_template as build_instantiate_template,
    list_templates as build_list_templates,
    list_workspaces as build_list_workspaces,
    load_workspace_config as build_load_workspace_config,
    normalize_config_before_save as build_normalize_config_before_save,
    runtime_root_for_workspace as build_runtime_root_for_workspace,
    slugify_workspace_name as build_slugify_workspace_name,
    suggest_time_windows as build_suggest_time_windows,
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
    build_reasonableness_checks as build_workspace_reasonableness_checks,
    workspace_detailed_check as build_workspace_detailed_check,
)
from services.workspace_layout import (
    WorkspaceLayoutContext,
    count_path_entries as build_workspace_layout_count_path_entries,
    workspace_layout_summary as build_workspace_layout_summary,
)
from services.workspace_validation import WorkspaceValidationContext
from services.workspace_validation import build_engineering_focus_checks as build_workspace_engineering_focus_checks
from services.workspace_validation import validate_workspace_fields as build_validate_workspace_fields
from services.wizard_validation import WizardValidationContext
from services.wizard_validation import wizard_step4_meteo_validation as build_wizard_step4_meteo_validation
from services.wizard_validation import wizard_validate_step as build_wizard_validate_step
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

OBSERVED_FLOW_KEY = "\u89c2\u6d4b\u5f84\u6d41_csv"
OBSERVED_FLOW_SUFFIXES = {".csv", ".xlsx", ".xls", ".xlsm"}
VECTOR_BUNDLE_SUFFIXES = tuple(
    getattr(
        profile_runner,
        "VECTOR_BUNDLE_SUFFIXES",
        (".shp", ".dbf", ".shx", ".prj", ".cpg", ".sbn", ".sbx", ".xml"),
    )
)


def configured_precip_source(config: dict[str, Any]) -> str:
    return build_configured_precip_source(config)


def resolve_precip_source(config: dict[str, Any], source: Any = None) -> str:
    return build_resolve_precip_source(config, source)


def effective_precip_source(source: str) -> str:
    return build_effective_precip_source(source)


def display_precip_source_label(source: str) -> str:
    return build_display_precip_source_label(source)


def display_runtime_precip_label(config: dict[str, Any]) -> str:
    return build_display_runtime_precip_label(config)


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


def _filesystem_path_context() -> FilesystemPathContext:
    return FilesystemPathContext(
        gui_root=GUI_ROOT,
        project_root=PROJECT_ROOT,
        replace_placeholders=replace_placeholders,
        remap_legacy_project_path=remap_legacy_project_path,
    )


def _filesystem_placeholder_context() -> FilesystemPlaceholderContext:
    return FilesystemPlaceholderContext(project_root=PROJECT_ROOT, gui_root=GUI_ROOT)


def resolve_any_path(raw_path: str, *, must_exist: bool = False) -> Path:
    return build_resolve_any_path(raw_path, _filesystem_path_context(), must_exist=must_exist)


def ensure_within(root: Path, candidate: Path) -> Path:
    return build_ensure_within(root, candidate)


def is_within_root(root: Path, candidate: Path) -> bool:
    return build_is_within_root(root, candidate)


def is_within_current_project(candidate: Path) -> bool:
    return build_is_within_any_root(candidate, (WORKSPACE_DIR, GUI_ROOT, PROJECT_ROOT))


def to_display_path(path: Path) -> str:
    return build_to_display_path(path, (GUI_ROOT, PROJECT_ROOT))


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
    return build_placeholder_roots_for_config_path(config_path, _filesystem_placeholder_context())


def replace_placeholders(value: Any, *, project_root: Path | None = None, gui_root: Path | None = None) -> Any:
    return build_replace_placeholders(
        value,
        _filesystem_placeholder_context(),
        project_root=project_root,
        gui_root=gui_root,
    )


def remap_legacy_project_path(
    raw_value: Any,
    *,
    preserve_project_root: Path | None = None,
    preserve_gui_root: Path | None = None,
) -> Any:
    return build_remap_legacy_project_path(
        raw_value,
        _filesystem_placeholder_context(),
        preserve_project_root=preserve_project_root,
        preserve_gui_root=preserve_gui_root,
    )


def normalize_legacy_project_paths(
    value: Any,
    parent_key: str = "",
    *,
    preserve_project_root: Path | None = None,
    preserve_gui_root: Path | None = None,
) -> Any:
    return build_normalize_legacy_project_paths(
        value,
        _filesystem_placeholder_context(),
        parent_key,
        preserve_project_root=preserve_project_root,
        preserve_gui_root=preserve_gui_root,
    )


def normalize_time_step_hours(value: Any) -> float:
    return build_normalize_time_step_hours(value)


def read_json_file(path: Path) -> dict[str, Any]:
    return build_read_json_file(path)


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
    return build_json_safe_value(value)


def json_dumps_safe(payload: Any, *, indent: int | None = None) -> str:
    return build_json_dumps_safe(payload, indent=indent)


def write_json_file(path: Path, data: dict[str, Any]) -> None:
    build_write_json_file(path, data)


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
    return build_detect_series_step_hours(timestamps)


def parse_time_from_name(name: str) -> pd.Timestamp | None:
    return build_parse_time_from_name(name)


def is_date_only_string(value: Any) -> bool:
    return build_is_date_only_string(value)


def format_timestamp_for_display(timestamp: pd.Timestamp, step_hours: float) -> str:
    return build_format_timestamp_for_display(timestamp, step_hours)


def expected_warmup_end(time_values: dict[str, pd.Timestamp], step_hours: float) -> pd.Timestamp | None:
    return build_expected_warmup_end(time_values, step_hours)


def time_sequence_messages(time_values: dict[str, pd.Timestamp], step_hours: float) -> list[str]:
    return build_time_sequence_messages(time_values, step_hours)


def _truthy_config(value: Any, default: bool = False) -> bool:
    return build_truthy_config(value, default)


def _flood_event_raw_config(config: dict[str, Any]) -> dict[str, Any]:
    return build_flood_event_raw_config(config)


def normalize_event_initial_state_policy(value: Any) -> str:
    return build_normalize_event_initial_state_policy(value)


def event_initial_state_policy_summary(value: Any) -> dict[str, Any]:
    return build_event_initial_state_policy_summary(value)


def _event_date_range(start: pd.Timestamp, end: pd.Timestamp, step_hours: float) -> pd.DatetimeIndex:
    return build_event_date_range(start, end, step_hours)


def task_time_basis(config: dict[str, Any], *, context: str = "calibration") -> str:
    return build_task_time_basis(config, context=context)


def _event_window_context() -> EventWindowContext:
    return EventWindowContext(resolve_config_related_path=_resolve_config_related_path)


def normalized_flood_events(config: dict[str, Any], *, step_hours: float | None = None) -> dict[str, Any]:
    return build_normalized_flood_events(config, _event_window_context(), step_hours=step_hours)


def _event_window_index(events: list[dict[str, Any]], start_key: str, end_key: str, step_hours: float) -> pd.DatetimeIndex:
    return build_event_window_index(events, start_key, end_key, step_hours)


def build_expected_time_index(config: dict[str, Any]) -> pd.DatetimeIndex | None:
    return build_event_expected_time_index(config)


def build_expected_forcing_index(config: dict[str, Any], *, context: str = "calibration") -> pd.DatetimeIndex | None:
    return build_event_expected_forcing_index(config, _event_window_context(), runtime_context=context)


def build_expected_observation_index(config: dict[str, Any], *, context: str = "calibration") -> pd.DatetimeIndex | None:
    return build_event_expected_observation_index(config, _event_window_context(), runtime_context=context)


def scan_tif_time_series(directory: Path) -> dict[str, Any]:
    return build_scan_tif_time_series(directory)


def validate_tif_grid_alignment(label: str, directory: Path, dem_path: Path) -> dict[str, Any]:
    return build_validate_tif_grid_alignment(label, directory, dem_path)


def validate_tif_time_series(
    label: str,
    directory: Path,
    step_hours: float,
    expected_index: pd.DatetimeIndex | None = None,
    time_basis_label: str = "当前配置时间范围",
) -> dict[str, Any]:
    return build_validate_tif_time_series(label, directory, step_hours, expected_index, time_basis_label)


def event_forcing_coverage_summary(
    event_info: dict[str, Any] | None,
    directories: dict[str, dict[str, Any]],
    step_hours: float,
) -> dict[str, Any] | None:
    return build_event_forcing_coverage_summary(event_info, directories, step_hours)


def event_observation_coverage_summary(
    event_info: dict[str, Any] | None,
    observed_series: Any,
    step_hours: float,
) -> dict[str, Any] | None:
    return build_event_observation_coverage_summary(event_info, observed_series, step_hours)


def event_observation_coverage_messages(coverage: dict[str, Any] | None) -> tuple[list[str], list[str]]:
    return build_event_observation_coverage_messages(coverage)


def _forcing_validation_context() -> ForcingValidationContext:
    return ForcingValidationContext(
        current_profile=current_profile,
        build_profile_paths=build_profile_paths,
        normalize_time_step_hours=normalize_time_step_hours,
        task_time_basis=task_time_basis,
        time_basis_labels=TIME_BASIS_LABELS,
        time_basis_event_windows=TIME_BASIS_EVENT_WINDOWS,
        build_expected_forcing_index=build_expected_forcing_index,
        normalized_flood_events=normalized_flood_events,
        effective_precip_paths=effective_precip_paths,
        validate_tif_time_series=validate_tif_time_series,
        workspace_dem_path=_workspace_dem_path,
        configured_dem_kind=_configured_dem_kind,
        validate_tif_grid_alignment=validate_tif_grid_alignment,
        event_windows_ui_summary=event_windows_ui_summary,
        event_forcing_coverage_summary=event_forcing_coverage_summary,
    )


def _forcing_aligned_status_context() -> ForcingAlignedStatusContext:
    return ForcingAlignedStatusContext(
        build_profile_paths=build_profile_paths,
        effective_precip_paths=effective_precip_paths,
        normalize_time_step_hours=normalize_time_step_hours,
        validate_tif_time_series=validate_tif_time_series,
    )


def _forcing_inputs_ready_context() -> ForcingInputsReadyContext:
    return ForcingInputsReadyContext(
        build_profile_paths=build_profile_paths,
        workspace_dem_path=_workspace_dem_path,
        configured_dem_kind=_configured_dem_kind,
        resolve_config_related_path=_resolve_config_related_path,
        validate_forcing_bundle=validate_forcing_bundle,
        observed_flow_key=OBSERVED_FLOW_KEY,
    )


def _forcing_preprocess_status_context() -> ForcingPreprocessStatusContext:
    return ForcingPreprocessStatusContext(
        build_workspace_paths=build_workspace_paths,
        build_profile_paths=build_profile_paths,
        resolve_precip_source=resolve_precip_source,
        effective_precip_source=effective_precip_source,
        count_matching=count_matching,
        validate_tif_time_series=validate_tif_time_series,
    )


def _forcing_download_status_context() -> ForcingDownloadStatusContext:
    return ForcingDownloadStatusContext(
        build_workspace_paths=build_workspace_paths,
        configured_precip_source=configured_precip_source,
    )


def _hourly_forcing_ready_context() -> HourlyForcingReadyContext:
    return HourlyForcingReadyContext(
        build_workspace_paths=build_workspace_paths,
        validate_forcing_bundle=validate_forcing_bundle,
    )


def validate_forcing_bundle(
    config: dict[str, Any],
    profile: str | None = None,
    precip_source: Any = None,
) -> dict[str, Any]:
    return build_validate_forcing_bundle(
        config,
        _forcing_validation_context(),
        profile=profile,
        precip_source=precip_source,
    )


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


def _observed_window_context() -> ObservedWindowContext:
    return ObservedWindowContext(
        current_profile=current_profile,
        normalize_time_step_hours=normalize_time_step_hours,
        task_time_basis=task_time_basis,
        format_timestamp_for_display=format_timestamp_for_display,
        profile_labels=PROFILE_LABELS,
        profile_daily=PROFILE_DAILY,
        profile_hourly=PROFILE_HOURLY,
        time_basis_event_windows=TIME_BASIS_EVENT_WINDOWS,
    )


def observed_window_messages(config: dict[str, Any], obs_info: dict[str, Any]) -> tuple[list[str], list[str]]:
    return build_observed_window_messages(config, obs_info, _observed_window_context())


def _boundary_inflow_inspect_context() -> BoundaryInflowInspectContext:
    return BoundaryInflowInspectContext(
        resolve_path=resolve_any_path,
        profile_daily=PROFILE_DAILY,
        profile_hourly=PROFILE_HOURLY,
    )


def inspect_boundary_inflow_csv(
    csv_path_raw: str,
    date_field: str = "date",
    flow_field: str = "inflow_m3s",
    *,
    expected_index: pd.DatetimeIndex | None = None,
    expected_step_hours: float | None = None,
) -> dict[str, Any]:
    return build_inspect_boundary_inflow_csv(
        csv_path_raw,
        _boundary_inflow_inspect_context(),
        date_field=date_field,
        flow_field=flow_field,
        expected_index=expected_index,
        expected_step_hours=expected_step_hours,
    )


def boundary_info_messages(
    boundary_info: dict[str, Any],
    step_hours: float,
    gap_fill: str = "zero",
) -> tuple[list[str], list[str]]:
    return build_boundary_info_messages(boundary_info, step_hours, gap_fill)


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


def _geo_status_context() -> GeoStatusContext:
    return GeoStatusContext(
        current_profile=current_profile,
        build_profile_paths=build_profile_paths,
        workspace_dem_path=_workspace_dem_path,
        configured_dem_kind=_configured_dem_kind,
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
    return build_slugify_workspace_name(name)


def runtime_root_for_workspace(name: str) -> Path:
    return build_runtime_root_for_workspace(name, PROJECT_RUNTIME_DIR)


def detect_profile_from_payload(data: dict[str, Any]) -> str:
    return build_detect_profile_from_payload(
        data,
        profile_daily=PROFILE_DAILY,
        profile_hourly=PROFILE_HOURLY,
    )


def detect_object_type(data: dict[str, Any]) -> str:
    return build_detect_object_type(
        data,
        object_regression=OBJECT_REGRESSION,
        object_interbasin=OBJECT_INTERBASIN,
        object_full_upstream=OBJECT_FULL_UPSTREAM,
    )


def _run_portable_path_context() -> RunPortablePathContext:
    return RunPortablePathContext(project_root=PROJECT_ROOT, gui_root=GUI_ROOT)


def to_portable_path(value: str) -> str:
    return build_to_portable_path(value, _run_portable_path_context())


def portableize_value_paths(value: Any) -> Any:
    return build_portableize_value_paths(value, _run_portable_path_context())


def _infer_project_roots_from_run_path(run_path: Path | None) -> tuple[Path | None, Path | None]:
    return build_infer_project_roots_from_run_path(run_path)


def _workspace_roots_hint_from_metadata(metadata: dict[str, Any] | None) -> tuple[Path | None, Path | None]:
    return build_workspace_roots_hint_from_metadata(metadata)


def _workspace_config_reference_context() -> RunWorkspaceConfigReferenceContext:
    return RunWorkspaceConfigReferenceContext(
        project_root=PROJECT_ROOT,
        gui_root=GUI_ROOT,
        workspace_dir=WORKSPACE_DIR,
        replace_placeholders=replace_placeholders,
        remap_legacy_project_path=remap_legacy_project_path,
        resolve_any_path=resolve_any_path,
        is_within_current_project=is_within_current_project,
    )


def workspace_config_candidates(raw_path: str, *, project_root: Path | None = None, gui_root: Path | None = None) -> list[Path]:
    return build_workspace_config_candidates(
        raw_path,
        _workspace_config_reference_context(),
        project_root=project_root,
        gui_root=gui_root,
    )


def resolve_workspace_config_reference(raw_path: str, *, run_path: Path | None = None, project_root: Path | None = None, gui_root: Path | None = None) -> Path | None:
    return build_resolve_workspace_config_reference(
        raw_path,
        _workspace_config_reference_context(),
        run_path=run_path,
        project_root=project_root,
        gui_root=gui_root,
    )


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


def _run_config_data_source_context() -> RunConfigDataSourceContext:
    return RunConfigDataSourceContext(
        configured_precip_source=configured_precip_source,
        resolve_precip_source=resolve_precip_source,
        effective_precip_paths=effective_precip_paths,
        resolve_any_path=resolve_any_path,
        first_existing_path=_first_existing_path,
        resolve_config_related_path=_resolve_config_related_path,
        observed_flow_key=OBSERVED_FLOW_KEY,
    )


def _run_config_boundary_context() -> RunConfigBoundaryContext:
    return RunConfigBoundaryContext(
        resolve_config_related_path=_resolve_config_related_path,
        resolve_any_path=resolve_any_path,
        first_existing_path=_first_existing_path,
        boundary_inflow_key="上游边界入流_csv",
    )


def _run_config_identity_context() -> RunConfigIdentityContext:
    return RunConfigIdentityContext(resolve_metadata_object_type=_resolve_metadata_object_type)


def _run_config_sync_context() -> RunConfigSyncContext:
    return RunConfigSyncContext(
        read_runtime_config=read_runtime_config,
        resolve_profile=resolve_profile,
        build_profile_paths=build_profile_paths,
        data_source_context=_run_config_data_source_context(),
        identity_context=_run_config_identity_context(),
        boundary_context=_run_config_boundary_context(),
    )


def _run_metadata_normalization_context() -> RunMetadataNormalizationContext:
    return RunMetadataNormalizationContext(
        metadata_compatibility_context=_run_metadata_compatibility_context(),
        resolve_metadata_object_type=_resolve_metadata_object_type,
        config_sync_context=_run_config_sync_context(),
        resolve_source_run_reference=_resolve_source_run_reference,
    )


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
    return build_normalize_run_metadata_payload(
        metadata,
        run_path=run_path,
        context=_run_metadata_normalization_context(),
    )


def normalize_config_before_save(data: dict[str, Any], save_path: Path) -> dict[str, Any]:
    return build_normalize_config_before_save(data, save_path, _workspace_catalog_context())


def build_empty_workspace(name: str = "新流域工作区", profile: str = PROFILE_DAILY) -> dict[str, Any]:
    return build_empty_workspace_config(name, profile, _workspace_catalog_context())


def suggest_time_windows(start_date: pd.Timestamp, end_date: pd.Timestamp, profile: str) -> dict[str, str]:
    return build_suggest_time_windows(
        start_date,
        end_date,
        profile,
        profile_daily=PROFILE_DAILY,
        profile_hourly=PROFILE_HOURLY,
    )


def _workspace_catalog_context() -> WorkspaceCatalogContext:
    return WorkspaceCatalogContext(
        template_dir=TEMPLATE_DIR,
        workspace_dir=WORKSPACE_DIR,
        project_runtime_dir=PROJECT_RUNTIME_DIR,
        default_workspace_path=DEFAULT_WORKSPACE_PATH,
        builtin_glacier_shp=BUILTIN_GLACIER_SHP,
        builtin_dem=BUILTIN_DEM,
        profile_daily=PROFILE_DAILY,
        profile_hourly=PROFILE_HOURLY,
        time_basis_continuous=TIME_BASIS_CONTINUOUS,
        time_basis_event_windows=TIME_BASIS_EVENT_WINDOWS,
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
        normalize_objective_mode=profile_runner.normalize_objective_mode,
        default_initial_state=profile_runner.DEFAULT_INIT_STATE,
        write_json_file=write_json_file,
        to_display_path=to_display_path,
        to_portable_path=to_portable_path,
        workspace_workflow_summary=workspace_workflow_summary,
        normalize_time_step_hours=normalize_time_step_hours,
        ensure_within=ensure_within,
        inspect_observed_csv=inspect_observed_csv,
        fill_bbox_from_shp=fill_bbox_from_shp,
        suggest_cfmax_threshold=suggest_cfmax_threshold,
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


def workspace_layout_summary(config_path_raw: str) -> dict[str, Any]:
    return build_workspace_layout_summary(
        config_path_raw,
        WorkspaceLayoutContext(
            load_workspace_config=load_workspace_config,
            current_profile=current_profile,
            build_profile_paths=build_profile_paths,
            effective_precip_paths=effective_precip_paths,
            display_runtime_precip_label=display_runtime_precip_label,
            count_path_entries=build_workspace_layout_count_path_entries,
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


def _prefer_raw_or_aligned_group_status(
    raw_entries: list[tuple[str, Path]],
    aligned_entries: list[tuple[str, Path]],
    step_hours: float,
) -> tuple[bool, str, int]:
    return build_prefer_raw_or_aligned_group_status(
        raw_entries,
        aligned_entries,
        step_hours,
        _forcing_preprocess_status_context(),
    )


def _configured_daily_meteo_sources(config: dict[str, Any]) -> tuple[str, str]:
    return build_configured_daily_meteo_sources(config)


def hourly_forcing_ready(config: dict[str, Any], precip_source: Any = None) -> tuple[bool, str, int]:
    return build_hourly_forcing_ready_status(
        config,
        _hourly_forcing_ready_context(),
        profile=PROFILE_HOURLY,
        precip_source=precip_source,
    )


StepCheck = Callable  # type alias: (config: dict) -> (bool, str, int)


def check_clip_dem(config: dict[str, Any]) -> tuple[bool, str, int]:
    return build_check_clip_dem(config, _geo_status_context())


def check_flow_acc(config: dict[str, Any]) -> tuple[bool, str, int]:
    return build_check_flow_acc(config, _geo_status_context())


def check_masked_flow(config: dict[str, Any]) -> tuple[bool, str, int]:
    return build_check_masked_flow(config, _geo_status_context())


def check_elevation_zone(config: dict[str, Any]) -> tuple[bool, str, int]:
    return build_check_elevation_zone(config, _geo_status_context())


def check_daily_temp_evap(config: dict[str, Any]) -> tuple[bool, str, int]:
    return build_check_daily_temp_evap_status(
        config,
        _forcing_preprocess_status_context(),
        profile=PROFILE_DAILY,
    )


def check_daily_era5_download(config: dict[str, Any]) -> tuple[bool, str, int]:
    return build_check_daily_era5_download_status(config, _forcing_download_status_context())


def check_daily_era5_processed(config: dict[str, Any]) -> tuple[bool, str, int]:
    return build_check_daily_era5_processed_status(
        config,
        _forcing_preprocess_status_context(),
        profile=PROFILE_DAILY,
    )


def check_daily_prec(config: dict[str, Any], precip_source: Any = None) -> tuple[bool, str, int]:
    return build_check_daily_prec_status(
        config,
        _forcing_preprocess_status_context(),
        profile=PROFILE_DAILY,
        precip_source=precip_source,
    )


def check_daily_aligned(config: dict[str, Any], precip_source: Any = None) -> tuple[bool, str, int]:
    return build_check_aligned_forcing_status(
        config,
        _forcing_aligned_status_context(),
        profile=PROFILE_DAILY,
        label="日尺度",
        precip_source=precip_source,
    )


def _precip_strategy_status_context() -> PrecipStrategyStatusContext:
    return PrecipStrategyStatusContext(
        meteo_key=METEO_KEY,
        meteo_precip_mode_key=METEO_PRECIP_MODE_KEY,
        current_profile=current_profile,
        effective_precip_paths=effective_precip_paths,
        count_matching=count_matching,
        read_json_file=read_json_file,
    )


def check_precip_strategy_outputs(config: dict[str, Any], precip_source: Any = None) -> tuple[bool, str, int]:
    return build_check_precip_strategy_outputs(
        config,
        _precip_strategy_status_context(),
        precip_source=precip_source,
    )


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
    return build_event_windows_ui_summary(event_info, step_hours)


def input_time_basis_ui_summary(
    config: dict[str, Any],
    *,
    time_basis: str,
    step_hours: float,
    event_info: dict[str, Any] | None = None,
    context: str = "calibration",
) -> dict[str, Any]:
    return build_input_time_basis_ui_summary(
        config,
        _event_window_context(),
        time_basis=time_basis,
        step_hours=step_hours,
        event_info=event_info,
        runtime_context=context,
    )


def analyze_station_precip_inputs(
    config: dict[str, Any],
    *,
    step_hours: float | None = None,
    context: str = "calibration",
) -> dict[str, Any]:
    analysis_context = StationPrecipAnalysisContext(
        resolve_config_related_path=_resolve_config_related_path,
        normalize_time_step_hours=normalize_time_step_hours,
        task_time_basis=task_time_basis,
        normalized_flood_events=normalized_flood_events,
        build_expected_forcing_index=build_expected_forcing_index,
    )
    return build_analyze_station_precip_inputs(
        config,
        analysis_context,
        step_hours=step_hours,
        context=context,
    )


def _station_precip_strategy_status_context() -> StationPrecipStrategyStatusContext:
    return StationPrecipStrategyStatusContext(
        normalize_time_step_hours=normalize_time_step_hours,
        analyze_station_precip_inputs=analyze_station_precip_inputs,
    )


def check_station_precip_strategy(config: dict[str, Any]) -> tuple[bool, str, int]:
    return build_check_station_precip_strategy_status(
        config,
        _station_precip_strategy_status_context(),
    )


def _glacier_status_context() -> GlacierStatusContext:
    return GlacierStatusContext(
        current_profile=current_profile,
        build_profile_paths=build_profile_paths,
        read_json_file=read_json_file,
        count_matching=count_matching,
        workspace_dem_path=_workspace_dem_path,
        configured_dem_kind=_configured_dem_kind,
        infer_dem_kind_from_raster=infer_dem_kind_from_raster,
        resolve_objective_mode=profile_runner.resolve_objective_mode,
        objective_mode_multi=profile_runner.OBJECTIVE_MODE_MULTI,
        objective_mode_flood_event=getattr(profile_runner, "OBJECTIVE_MODE_FLOOD_EVENT", ""),
    )


def check_glacier_mask(config: dict[str, Any]) -> tuple[bool, str, int]:
    return build_check_glacier_mask(config, _glacier_status_context())


def check_glacier_reference(config: dict[str, Any]) -> tuple[bool, str, int]:
    return build_check_glacier_reference(config, _glacier_status_context())


def check_glacier_elev(config: dict[str, Any]) -> tuple[bool, str, int]:
    return build_check_glacier_elev(config, _glacier_status_context())


def glacier_elev_required(config: dict[str, Any]) -> bool:
    return build_glacier_elev_required(config, _glacier_status_context())


def glacier_formal_requirements(config: dict[str, Any], profile: str | None = None) -> dict[str, Any]:
    return build_glacier_formal_requirements(config, _glacier_status_context(), profile)


def check_daily_inputs_ready(config: dict[str, Any], precip_source: Any = None) -> tuple[bool, str, int]:
    return build_check_forcing_inputs_ready(
        config,
        _forcing_inputs_ready_context(),
        profile=PROFILE_DAILY,
        precip_source=precip_source,
    )


def check_hourly_temp_evap(config: dict[str, Any]) -> tuple[bool, str, int]:
    return build_check_hourly_temp_evap_status(
        config,
        _forcing_preprocess_status_context(),
        profile=PROFILE_HOURLY,
    )


def check_hourly_era5_download(config: dict[str, Any]) -> tuple[bool, str, int]:
    return build_check_hourly_era5_download_status(config, _forcing_download_status_context())


def check_hourly_prec(config: dict[str, Any], precip_source: Any = None) -> tuple[bool, str, int]:
    return build_check_hourly_prec_status(
        config,
        _forcing_preprocess_status_context(),
        profile=PROFILE_HOURLY,
        precip_source=precip_source,
    )


def check_hourly_aligned(config: dict[str, Any], precip_source: Any = None) -> tuple[bool, str, int]:
    return build_check_aligned_forcing_status(
        config,
        _forcing_aligned_status_context(),
        profile=PROFILE_HOURLY,
        label="小时尺度",
        precip_source=precip_source,
    )


def check_hourly_inputs_ready(config: dict[str, Any], precip_source: Any = None) -> tuple[bool, str, int]:
    return build_check_forcing_inputs_ready(
        config,
        _forcing_inputs_ready_context(),
        profile=PROFILE_HOURLY,
        forcing_label="小时",
        precip_source=precip_source,
    )


def _data_prep_step_catalog_context() -> DataPrepStepCatalogContext:
    return DataPrepStepCatalogContext(
        data_prep_dir=DATA_PREP_DIR,
        gui_root=GUI_ROOT,
        profile_daily=PROFILE_DAILY,
        check_clip_dem=check_clip_dem,
        check_flow_acc=check_flow_acc,
        check_masked_flow=check_masked_flow,
        check_elevation_zone=check_elevation_zone,
        check_daily_era5_download=check_daily_era5_download,
        check_daily_era5_processed=check_daily_era5_processed,
        check_daily_prec=check_daily_prec,
        check_station_precip_strategy=check_station_precip_strategy,
        check_daily_aligned=check_daily_aligned,
        check_precip_strategy_outputs=check_precip_strategy_outputs,
        check_glacier_mask=check_glacier_mask,
        check_glacier_elev=check_glacier_elev,
        check_glacier_reference=check_glacier_reference,
        check_daily_inputs_ready=check_daily_inputs_ready,
        check_hourly_era5_download=check_hourly_era5_download,
        check_hourly_temp_evap=check_hourly_temp_evap,
        check_hourly_prec=check_hourly_prec,
        check_hourly_aligned=check_hourly_aligned,
        check_hourly_inputs_ready=check_hourly_inputs_ready,
    )


def data_prep_steps(profile: str) -> list[dict[str, Any]]:
    return build_data_prep_steps(profile, _data_prep_step_catalog_context())


def resolve_data_prep_step(step: dict[str, Any], config: dict[str, Any] | None = None) -> dict[str, Any]:
    return build_resolve_data_prep_step(
        step,
        config,
        glacier_elev_required=glacier_elev_required,
    )


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
    return build_workspace_engineering_focus_checks(
        config,
        _workspace_validation_context(),
        profile=profile,
        object_type=object_type,
        step_hours=step_hours,
        obs_info=obs_info,
        boundary_info=boundary_info,
        forcing=forcing,
        station_precip_info=station_precip_info,
        boundary_csv=boundary_csv,
    )


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
        input_time_basis_ui_summary=input_time_basis_ui_summary,
        event_windows_ui_summary=event_windows_ui_summary,
        default_init_state=profile_runner.DEFAULT_INIT_STATE,
        observed_flow_key=OBSERVED_FLOW_KEY,
        profile_daily=PROFILE_DAILY,
        profile_hourly=PROFILE_HOURLY,
        profile_labels=PROFILE_LABELS,
        default_min_daily_hours=DEFAULT_MIN_DAILY_HOURS,
        object_interbasin=OBJECT_INTERBASIN,
        object_full_upstream=OBJECT_FULL_UPSTREAM,
        object_labels=OBJECT_LABELS,
        time_basis_event_windows=TIME_BASIS_EVENT_WINDOWS,
        time_basis_labels=TIME_BASIS_LABELS,
        meteo_key=METEO_KEY,
        meteo_precip_mode_key=METEO_PRECIP_MODE_KEY,
        meteo_pet_source_key=METEO_PET_SOURCE_KEY,
    )


def wizard_step4_meteo_validation(config: dict[str, Any]) -> tuple[list[str], list[str]]:
    return build_wizard_step4_meteo_validation(config, _wizard_validation_context())


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
        configured_precip_source=configured_precip_source,
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
        meteo_key=METEO_KEY,
        meteo_precip_mode_key=METEO_PRECIP_MODE_KEY,
        meteo_temp_source_key=METEO_TEMP_SOURCE_KEY,
        meteo_pet_source_key=METEO_PET_SOURCE_KEY,
        meteo_station_prec_key=METEO_STATION_PREC_KEY,
        meteo_station_meta_key=METEO_STATION_META_KEY,
        meteo_custom_prec_dir_key=METEO_CUSTOM_PREC_DIR_KEY,
        meteo_custom_temp_dir_key=METEO_CUSTOM_TEMP_DIR_KEY,
        meteo_custom_pet_dir_key=METEO_CUSTOM_PET_DIR_KEY,
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


def build_reasonableness_checks(
    config: dict[str, Any],
    forcing: dict[str, Any],
    *,
    dem_stats: dict[str, Any] | None = None,
    glacier_mask_summary: dict[str, Any] | None = None,
    glacier_mask_exists: bool = False,
    gis_dir: Path | str | None = None,
) -> list[dict[str, Any]]:
    return build_workspace_reasonableness_checks(
        config,
        forcing,
        _workspace_detailed_check_context(),
        dem_stats=dem_stats,
        glacier_mask_summary=glacier_mask_summary,
        glacier_mask_exists=glacier_mask_exists,
        gis_dir=gis_dir,
    )

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
        format_timestamp_for_display=format_timestamp_for_display,
        resolve_objective_mode=profile_runner.resolve_objective_mode,
        count_matching=count_matching,
        profile_daily=PROFILE_DAILY,
        profile_labels=PROFILE_LABELS,
        object_labels=OBJECT_LABELS,
        object_interbasin=OBJECT_INTERBASIN,
        objective_mode_multi=profile_runner.OBJECTIVE_MODE_MULTI,
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
        station_precip_mode_label=build_station_precip_mode_label,
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
