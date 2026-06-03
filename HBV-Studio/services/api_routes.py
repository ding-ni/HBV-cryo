#!/usr/bin/env python
# -*- coding: utf-8 -*-
from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

HttpMethod = Literal["GET", "POST"]


@dataclass(frozen=True)
class ApiRouteSpec:
    method: HttpMethod
    path: str
    handler: str
    group: str


API_ROUTE_SPECS: tuple[ApiRouteSpec, ...] = (
    ApiRouteSpec("GET", "/api/health", "_api_get_health", "system"),
    ApiRouteSpec("GET", "/api/dashboard", "_api_get_dashboard", "dashboard"),
    ApiRouteSpec("GET", "/api/templates", "_api_get_templates", "workspace"),
    ApiRouteSpec("GET", "/api/workspaces", "_api_get_workspaces", "workspace"),
    ApiRouteSpec("GET", "/api/configs", "_api_get_workspaces", "workspace"),
    ApiRouteSpec("GET", "/api/workspace", "_api_get_workspace", "workspace"),
    ApiRouteSpec("GET", "/api/config", "_api_get_workspace", "workspace"),
    ApiRouteSpec("GET", "/api/runs", "_api_get_runs", "runs"),
    ApiRouteSpec("GET", "/api/run", "_api_get_run", "runs"),
    ApiRouteSpec("GET", "/api/tasks", "_api_get_tasks", "tasks"),
    ApiRouteSpec("GET", "/api/cdsapi/status", "_api_get_cdsapi_status", "meteo"),
    ApiRouteSpec("GET", "/api/fs/list", "_api_get_fs_list", "filesystem"),
    ApiRouteSpec("GET", "/api/obs-info", "_api_get_obs_info", "observed"),
    ApiRouteSpec("GET", "/api/suggest/bbox", "_api_get_suggest_bbox", "geo"),
    ApiRouteSpec("GET", "/api/suggest/cfmax-threshold", "_api_get_suggest_cfmax_threshold", "geo"),
    ApiRouteSpec("GET", "/api/geo/dem", "_api_get_geo_dem", "geo"),
    ApiRouteSpec("GET", "/api/geo/overview", "_api_get_geo_overview", "geo"),
    ApiRouteSpec("GET", "/api/geo/basin", "_api_get_geo_basin", "geo"),
    ApiRouteSpec("GET", "/api/geo/elevation-zones", "_api_get_geo_elevation_zones", "geo"),
    ApiRouteSpec("GET", "/api/geo/elevation-zones.png", "_api_get_geo_elevation_zones_png", "geo"),
    ApiRouteSpec("GET", "/api/geo/glacier", "_api_get_geo_glacier", "geo"),
    ApiRouteSpec("GET", "/api/geo/glacier.png", "_api_get_geo_glacier_png", "geo"),
    ApiRouteSpec("GET", "/api/geo/stations", "_api_get_geo_stations", "geo"),
    ApiRouteSpec("GET", "/api/data-prep/steps", "_api_get_data_prep_steps", "data_prep"),
    ApiRouteSpec("GET", "/api/data-prep/status", "_api_get_data_prep_status", "data_prep"),
    ApiRouteSpec("GET", "/api/config/validate", "_api_get_config_validate", "workspace_validation"),
    ApiRouteSpec("GET", "/api/wizard/validate-step", "_api_get_wizard_validate_step", "wizard"),
    ApiRouteSpec("GET", "/api/boundary-preview", "_api_get_boundary_preview", "boundary"),
    ApiRouteSpec("GET", "/api/workspace/completeness", "_api_get_workspace_completeness", "workspace_validation"),
    ApiRouteSpec("GET", "/api/workspace/detailed-check", "_api_get_workspace_detailed_check", "workspace_validation"),
    ApiRouteSpec("GET", "/api/workspace/layout", "_api_get_workspace_layout", "workspace"),
    ApiRouteSpec("GET", "/api/workspace/advice", "_api_get_workspace_advice", "workspace_validation"),
    ApiRouteSpec("GET", "/api/manual-presets", "_api_get_manual_presets", "manual_presets"),
    ApiRouteSpec("POST", "/api/workspace/save", "_api_post_workspace_save", "workspace"),
    ApiRouteSpec("POST", "/api/config/save", "_api_post_workspace_save", "workspace"),
    ApiRouteSpec("POST", "/api/template/instantiate", "_api_post_template_instantiate", "workspace"),
    ApiRouteSpec("POST", "/api/import-workspace", "_api_post_import_workspace", "workspace"),
    ApiRouteSpec("POST", "/api/auto-config", "_api_post_import_workspace", "workspace"),
    ApiRouteSpec("POST", "/api/bootstrap/start", "_api_post_bootstrap_start", "tasks"),
    ApiRouteSpec("POST", "/api/data-prep/start", "_api_post_data_prep_start", "data_prep"),
    ApiRouteSpec("POST", "/api/calibration/start", "_api_post_calibration_start", "calibration"),
    ApiRouteSpec("POST", "/api/self-check/start", "_api_post_self_check_start", "system"),
    ApiRouteSpec("POST", "/api/template/sync-tuotuohe", "_api_post_template_sync_tuotuohe", "workspace"),
    ApiRouteSpec("POST", "/api/wizard/save-step", "_api_post_wizard_save_step", "wizard"),
    ApiRouteSpec("POST", "/api/gis/import", "_api_post_gis_import", "geo"),
    ApiRouteSpec("POST", "/api/meteo/import/start", "_api_post_meteo_import_start", "meteo"),
    ApiRouteSpec("POST", "/api/meteo/import", "_api_post_meteo_import", "meteo"),
    ApiRouteSpec("POST", "/api/simulate/forward/start", "_api_post_simulate_forward_start", "simulation"),
    ApiRouteSpec("POST", "/api/simulate/forward", "_api_post_simulate_forward", "simulation"),
    ApiRouteSpec("POST", "/api/forecast/restart/start", "_api_post_forecast_restart_start", "forecast"),
    ApiRouteSpec("POST", "/api/forecast/restart", "_api_post_forecast_restart", "forecast"),
    ApiRouteSpec("POST", "/api/forecast/input-check", "_api_post_forecast_input_check", "forecast"),
    ApiRouteSpec("POST", "/api/manual-start/start", "_api_post_manual_start_start", "manual_calibration"),
    ApiRouteSpec("POST", "/api/manual-preset/save", "_api_post_manual_preset_save", "manual_presets"),
    ApiRouteSpec("POST", "/api/manual-preset/delete", "_api_post_manual_preset_delete", "manual_presets"),
    ApiRouteSpec("POST", "/api/run/export-excel", "_api_post_run_export_excel", "runs"),
    ApiRouteSpec("POST", "/api/run/rename", "_api_post_run_rename", "runs"),
    ApiRouteSpec("POST", "/api/run/delete", "_api_post_run_delete", "runs"),
    ApiRouteSpec("POST", "/api/workspace/delete", "_api_post_workspace_delete", "workspace"),
    ApiRouteSpec("POST", "/api/fs/open-path", "_api_post_fs_open_path", "filesystem"),
    ApiRouteSpec("POST", "/api/app/window-unload", "_api_post_app_window_unload", "system"),
    ApiRouteSpec("POST", "/api/app/quit", "_api_post_app_quit", "system"),
)


def route_handlers(method: HttpMethod) -> dict[str, str]:
    return {spec.path: spec.handler for spec in API_ROUTE_SPECS if spec.method == method}


def route_specs_by_group() -> dict[str, tuple[ApiRouteSpec, ...]]:
    groups: dict[str, list[ApiRouteSpec]] = {}
    for spec in API_ROUTE_SPECS:
        groups.setdefault(spec.group, []).append(spec)
    return {group: tuple(specs) for group, specs in sorted(groups.items())}


GET_ROUTE_HANDLERS = route_handlers("GET")
POST_ROUTE_HANDLERS = route_handlers("POST")
ROUTE_SPECS_BY_GROUP = route_specs_by_group()
