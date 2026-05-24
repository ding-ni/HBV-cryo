#!/usr/bin/env python
# -*- coding: utf-8 -*-
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import pandas as pd
import shutil
import sys
import threading
import time
from pathlib import Path
from typing import Any


def _app_root() -> Path:
    raw = str(os.environ.get("HBV_STUDIO_APP_ROOT", "")).strip()
    if raw:
        return Path(raw).expanduser().resolve(strict=False)
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parents[1]


APP_ROOT = _app_root()
sys.path.insert(0, str(APP_ROOT / "公共"))

from 公共函数 import (  # type: ignore
    basin_paths,
    build_workspace_paths,
    cfmax_zone_threshold,
    config_base_dir,
    ensure_workspace_dirs,
    load_legacy_module,
    old_script_path,
    patch_module,
    read_config,
    resolve_path,
    select_workspace_path,
    temporary_argv,
    time_step_hours,
    workspace_path_candidates,
    边界条件配置,
)


GUI_ROOT = APP_ROOT / "HBV-Studio"
PROJECT_ROOT = APP_ROOT
TEMPLATE_ASSET_ROOT = GUI_ROOT / "templates" / "assets"
VECTOR_BUNDLE_SUFFIXES = (".shp", ".dbf", ".shx", ".prj", ".cpg", ".sbn", ".sbx", ".xml")
RUNTIME_MIRROR_ROOT = Path.home() / ".codex" / "memories" / "hbvstudio_runtime_mirror"

PROFILE_DAILY = "daily"
PROFILE_HOURLY = "hourly"
OBJECT_REGRESSION = "regression_validation"
OBJECT_REGRESSION_LEGACY = "regression_test"
OBJECT_INTERBASIN = "interbasin_with_boundary"
OBJECT_FULL_UPSTREAM = "full_upstream_basin"
OBJECTIVE_MODE_AUTO = "auto"
OBJECTIVE_MODE_SINGLE = "single_objective_nse"
OBJECTIVE_MODE_MULTI = "daily_unified_professional_v1"
CALIBRATION_WORKFLOW_SINGLE = "single_pass"
CALIBRATION_WORKFLOW_STAGED = "staged_calibration_v1"
PROFILE_LABELS = {
    PROFILE_DAILY: "日尺度率定",
    PROFILE_HOURLY: "小时尺度率定",
}
INIT_STATE_KEYS = ("SP", "SM", "UZ", "LZ", "WC")
DEFAULT_INIT_STATE = {
    "SP": 0.0,
    "SM": 5.0,
    "UZ": 0.0,
    "LZ": 0.0,
    "WC": 0.0,
}
CALIBRATION_PARAM_NAMES = [
    "TT", "FC", "BETA", "LP",
    "RFCF", "SFCF",
    "CFR", "CWH",
    "CFMAX_low", "CFMAX_high",
    "K", "K1", "K2", "UZL", "PERC",
    "ICE_FACTOR", "K_MUSK", "X_MUSK",
]


def format_runtime_time_value(value: Any, step_hours: float) -> str:
    ts = pd.to_datetime(value)
    if abs(float(step_hours) - 24.0) < 1e-9 and ts.hour == 0 and ts.minute == 0 and ts.second == 0:
        return ts.strftime("%Y-%m-%d")
    return ts.strftime("%Y-%m-%d %H:%M")


def resolve_runtime_time_config(config: dict[str, Any]) -> tuple[dict[str, Any], float]:
    time_cfg = dict(config.get("时间", {}) or {})
    step_hours = float(time_step_hours(config))
    warmup_start_raw = str(time_cfg.get("预热开始", "") or "").strip()
    calib_start_raw = str(time_cfg.get("率定开始", "") or "").strip()
    if not warmup_start_raw:
        raise ValueError("时间.预热开始 未设置。")
    if not calib_start_raw:
        raise ValueError("时间.率定开始 未设置。")

    warmup_start_ts = pd.to_datetime(warmup_start_raw)
    calib_start_ts = pd.to_datetime(calib_start_raw)
    expected_warmup_end = calib_start_ts - pd.Timedelta(hours=step_hours)
    if expected_warmup_end < warmup_start_ts:
        raise ValueError("预热期至少需要覆盖率定开始前 1 个时间步。")

    warmup_end_raw = str(time_cfg.get("预热结束", "") or "").strip()
    if warmup_end_raw:
        warmup_end_ts = pd.to_datetime(warmup_end_raw)
        if warmup_end_ts != expected_warmup_end:
            expected_label = format_runtime_time_value(expected_warmup_end, step_hours)
            raise ValueError(f"时间.预热结束 必须紧邻率定开始，当前应为 {expected_label}。")

    time_cfg["预热结束"] = format_runtime_time_value(expected_warmup_end, step_hours)
    return time_cfg, step_hours


def resolve_runtime_init_state(config: dict[str, Any]) -> list[float]:
    raw_init_state = dict(config.get("初始状态", {}) or {})
    init_state_vector: list[float] = []
    for key in INIT_STATE_KEYS:
        raw_value = raw_init_state.get(key, DEFAULT_INIT_STATE[key])
        try:
            value = float(raw_value)
        except Exception as exc:
            raise ValueError(f"初始状态.{key} 不是有效数字：{raw_value}") from exc
        init_state_vector.append(max(value, 0.0))
    return init_state_vector


def to_portable_path(value: str) -> str:
    if not value:
        return value
    try:
        resolved = Path(value).resolve(strict=False)
    except (OSError, ValueError):
        resolved = Path(value)
    gui_resolved = GUI_ROOT.resolve(strict=False)
    app_resolved = APP_ROOT.resolve(strict=False)
    try:
        rel = resolved.relative_to(gui_resolved)
        return "__GUI_ROOT__/" + str(rel).replace("\\", "/")
    except ValueError:
        pass
    try:
        rel = resolved.relative_to(app_resolved)
        return "__PROJECT_ROOT__/" + str(rel).replace("\\", "/")
    except ValueError:
        return value


def portableize_value_paths(value: Any) -> Any:
    if isinstance(value, dict):
        return {key: portableize_value_paths(item) for key, item in value.items()}
    if isinstance(value, list):
        return [portableize_value_paths(item) for item in value]
    if isinstance(value, str):
        return to_portable_path(value)
    return value


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
        (f"\\{APP_ROOT.name.lower()}\\", APP_ROOT),
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
        ("\\运行目录\\", APP_ROOT / "运行目录"),
        ("\\runtime\\", APP_ROOT / "运行目录"),
        ("\\hbv-cryo\\", APP_ROOT / "HBV-Cryo"),
        ("\\数据准备\\", APP_ROOT / "数据准备"),
        ("\\基础数据\\", APP_ROOT / "基础数据"),
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

PARAM_BOUNDS_PROFILE_QTP = "qtp_alpine_default"
PARAM_BOUNDS_PROFILE_GENERIC = "generic_wide"
PARAM_BOUNDS_PROFILE_HOURLY = "hourly_step"
DEFAULT_DAILY_PARAM_BOUNDS_PROFILE = PARAM_BOUNDS_PROFILE_QTP

PARAM_BOUNDS_PROFILE_LABELS = {
    PARAM_BOUNDS_PROFILE_QTP: "青藏高原高寒区默认范围",
    PARAM_BOUNDS_PROFILE_GENERIC: "通用宽范围",
    PARAM_BOUNDS_PROFILE_HOURLY: "小时尺度稳定范围",
}

PARAM_BOUNDS_PROFILE_NOTES = {
    PARAM_BOUNDS_PROFILE_QTP: "默认用于青藏高原高寒区率定，收窄土壤、雪冰和退水自由度，降低异参同效。",
    PARAM_BOUNDS_PROFILE_GENERIC: "保留原通用硬边界，适合资料较充分、先验不确定或需要放宽搜索的流域。",
    PARAM_BOUNDS_PROFILE_HOURLY: "小时尺度边界按 1 小时步长的离散稳定性单独管理。",
}

DAILY_GENERIC_PARAM_BOUNDS = [
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

DAILY_QTP_ALPINE_PARAM_BOUNDS = [
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

DAILY_PARAM_BOUNDS_BY_PROFILE = {
    PARAM_BOUNDS_PROFILE_QTP: DAILY_QTP_ALPINE_PARAM_BOUNDS,
    PARAM_BOUNDS_PROFILE_GENERIC: DAILY_GENERIC_PARAM_BOUNDS,
}
DAILY_PARAM_BOUNDS = DAILY_QTP_ALPINE_PARAM_BOUNDS

HOURLY_PARAM_BOUNDS = [
    (-2.0, 2.0),
    (100.0, 1500.0),
    (0.5, 4.0),
    (0.2, 1.0),
    (0.8, 1.2),
    (0.5, 1.5),
    (0.0, 0.1),
    (0.01, 0.1),
    (2.0, 5.0),
    (3.0, 8.0),
    (0.02, 0.5),
    (0.01, 0.2),
    (0.0005, 0.02),
    (1.0, 120.0),
    (0.01, 5.0),
    (1.0, 4.0),
    (0.03, 1.2),
    (0.0, 0.05),
]


def normalize_objective_mode(value: Any) -> str:
    raw = str(value or "").strip().lower()
    if raw in {"", OBJECTIVE_MODE_AUTO, "default"}:
        return OBJECTIVE_MODE_AUTO
    if raw in {OBJECTIVE_MODE_SINGLE, "single", "single_nse", "nse"}:
        return OBJECTIVE_MODE_SINGLE
    if raw in {
        OBJECTIVE_MODE_MULTI,
        "weighted_multi_criteria",
        "multi",
        "multi_objective",
        "composite",
        "weighted_daily_universal",
        "daily_unified_professional_v1",
    }:
        return OBJECTIVE_MODE_MULTI
    raise ValueError(f"未知目标函数模式：{value}")


def configured_precip_source(config: dict[str, Any]) -> str:
    meteo = dict(config.get("气象策略", {}))
    source = str(meteo.get("降水来源", "")).strip().lower()
    legacy_source = str(meteo.get("降水源", "")).strip().lower()
    top_level_source = str(config.get("默认降水源", "")).strip().lower()
    if source:
        return source
    if top_level_source in {"cmfd", "custom_tif"} and legacy_source in {"", "mswep"}:
        return top_level_source
    return legacy_source or top_level_source or "mswep"


def resolve_runtime_precip_source(config: dict[str, Any], cli_source: Any) -> str:
    raw = str(cli_source or "").strip().lower()
    if raw in {"mswep", "cmfd", "custom_tif"}:
        return raw
    configured = configured_precip_source(config)
    if configured in {"mswep", "cmfd", "custom_tif"}:
        return configured
    return "mswep"


def resolve_legacy_precip_source(runtime_source: str) -> str:
    return "cmfd" if str(runtime_source).strip().lower() == "cmfd" else "mswep"


def _workspace_mirror_name(workspace_root: Path) -> str:
    digest = hashlib.sha1(str(workspace_root.resolve(strict=False)).encode("utf-8")).hexdigest()[:10]
    return f"{workspace_root.name}_{digest}"


def _dir_is_writable(path: Path) -> bool:
    try:
        path.mkdir(parents=True, exist_ok=True)
        probe = path / ".__codex_write_probe__"
        probe.write_text("ok", encoding="utf-8")
        probe.unlink()
        return True
    except Exception:
        return False


def _effective_results_root(workspace_root: Path, requested_results_root: Path) -> Path:
    if _dir_is_writable(requested_results_root):
        return requested_results_root
    mirror_root = RUNTIME_MIRROR_ROOT / _workspace_mirror_name(workspace_root) / requested_results_root.name
    mirror_root.mkdir(parents=True, exist_ok=True)
    return mirror_root


def _effective_workspace_root(requested_workspace_root: Path) -> Path:
    requested_workspace_root = Path(requested_workspace_root).resolve(strict=False)
    if _dir_is_writable(requested_workspace_root):
        return requested_workspace_root
    mirror_root = RUNTIME_MIRROR_ROOT / _workspace_mirror_name(requested_workspace_root) / "workspace_runtime"
    mirror_root.mkdir(parents=True, exist_ok=True)
    return mirror_root


def _dir_has_entries(path: Path) -> bool:
    try:
        return path.exists() and any(path.iterdir())
    except Exception:
        return False


def _copy_tree_if_needed(source: Path, target: Path) -> bool:
    if not source.exists():
        return False
    copied = False
    target.mkdir(parents=True, exist_ok=True)
    for item in source.rglob("*"):
        relative = item.relative_to(source)
        target_item = target / relative
        if item.is_dir():
            target_item.mkdir(parents=True, exist_ok=True)
            continue
        if target_item.exists():
            continue
        target_item.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(item, target_item)
        copied = True
    return copied


def _workspace_seed_root_candidates(requested_workspace_root: Path) -> list[Path]:
    requested_workspace_root = Path(requested_workspace_root).resolve(strict=False)
    candidates: list[Path] = []
    seen: set[str] = set()

    def _append(path: Path | None) -> None:
        if path is None:
            return
        resolved = Path(path).resolve(strict=False)
        key = str(resolved).lower()
        if key in seen:
            return
        seen.add(key)
        candidates.append(resolved)

    _append(requested_workspace_root)
    _append(APP_ROOT / "运行目录" / requested_workspace_root.name)
    parent = requested_workspace_root.parent
    try:
        if parent.exists():
            for sibling in parent.iterdir():
                if sibling.is_dir():
                    _append(sibling)
    except Exception:
        pass
    return candidates


def _seed_workspace_runtime_inputs(
    requested_paths: dict[str, Path],
    effective_paths: dict[str, Path],
    profile: str,
) -> dict[str, str]:
    copied: dict[str, str] = {}
    requested_root = Path(requested_paths["workspace_root"]).resolve(strict=False)
    effective_root = Path(effective_paths["workspace_root"]).resolve(strict=False)
    if requested_root == effective_root:
        return copied

    source_roots = _workspace_seed_root_candidates(requested_root)
    path_keys = (
        "gis_dir",
        "aligned_prec_base_dir",
        "aligned_prec_cmfd_base_dir",
        "aligned_prec_custom_base_dir",
        "aligned_prec_corrected_dir",
        "aligned_prec_cmfd_corrected_dir",
        "aligned_prec_custom_corrected_dir",
        "aligned_temp_dir",
        "aligned_evap_dir",
        "glacier_melt_dir",
    )
    for key in path_keys:
        target = Path(effective_paths[key]).resolve(strict=False)
        try:
            relative = target.relative_to(effective_root)
        except Exception:
            continue
        for source_root in source_roots:
            source_root = Path(source_root).resolve(strict=False)
            source = (source_root / relative).resolve(strict=False)
            if not source.exists():
                continue
            if source.is_dir() and (not any(source.iterdir())):
                continue
            if _copy_tree_if_needed(source, target):
                copied[key] = str(source)
            elif _dir_has_entries(target):
                copied.setdefault(key, str(source))
            break
    return copied


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="HBV-Studio calibration runner with mode profiles.")
    parser.add_argument("--配置", "--config", dest="配置", required=True)
    parser.add_argument("--率定模式", "--calibration-mode", dest="率定模式", choices=[PROFILE_DAILY, PROFILE_HOURLY], default=None)
    parser.add_argument("--目标函数", "--objective-mode", dest="目标函数", default=None)
    parser.add_argument("--降水源", "--prec-source", dest="降水源", choices=["mswep", "cmfd", "custom_tif"], default=None)
    parser.add_argument("--prec-dir", type=str, default="")
    parser.add_argument("--冰川模式", "--glacier-mode", dest="冰川模式", choices=["inline", "off"], default="inline")
    parser.add_argument("--maxiter", type=int, default=24)
    parser.add_argument("--popsize", type=int, default=6)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--method", choices=["de", "mc_screen_de", "mc_only"], default="mc_screen_de")
    parser.add_argument("--mc-samples", type=int, default=300)
    parser.add_argument("--refine-maxiter", dest="refine_maxiter", type=int, default=-1)
    parser.add_argument("--init-params-file", type=str, default=None)
    parser.add_argument("--init-bound-shrink", type=float, default=0.0)
    parser.add_argument(
        "--param-bounds-profile",
        "--参数边界档案",
        dest="param_bounds_profile",
        choices=[PARAM_BOUNDS_PROFILE_QTP, PARAM_BOUNDS_PROFILE_GENERIC],
        default=None,
        help="日尺度参数边界档案，默认使用青藏高原高寒区推荐范围。",
    )
    parser.add_argument("--debug-days", type=int, default=0)
    parser.add_argument("--quick-test", action="store_true")
    parser.add_argument("--quick-days", type=int, default=30)
    parser.add_argument("--calibration-workflow", default="")
    return parser.parse_args()


def resolve_profile(config: dict[str, Any], explicit: str | None) -> str:
    if explicit:
        return explicit
    profile = str(config.get("率定模式", "")).strip().lower()
    if profile in {PROFILE_DAILY, PROFILE_HOURLY}:
        return profile
    return PROFILE_HOURLY if float(time_step_hours(config)) <= 1.5 else PROFILE_DAILY


def detect_object_type(config: dict[str, Any]) -> str:
    explicit = str(config.get("项目对象", "") or "").strip().lower()
    if explicit == OBJECT_REGRESSION_LEGACY:
        return OBJECT_REGRESSION
    if explicit in {OBJECT_REGRESSION, OBJECT_INTERBASIN, OBJECT_FULL_UPSTREAM}:
        return explicit
    boundary = dict(config.get("边界条件", {}) or {})
    if str(boundary.get("上游边界入流_csv", "") or "").strip():
        return OBJECT_INTERBASIN
    return OBJECT_FULL_UPSTREAM


def resolve_objective_mode(config: dict[str, Any], explicit: Any, profile: str) -> str:
    selected = normalize_objective_mode(explicit)
    if selected == OBJECTIVE_MODE_AUTO:
        selected = normalize_objective_mode(config.get("目标函数模式", OBJECTIVE_MODE_AUTO))
    if profile == PROFILE_DAILY:
        return OBJECTIVE_MODE_MULTI
    if selected == OBJECTIVE_MODE_AUTO:
        return OBJECTIVE_MODE_SINGLE
    return OBJECTIVE_MODE_SINGLE if selected == OBJECTIVE_MODE_SINGLE else OBJECTIVE_MODE_SINGLE


def normalize_calibration_workflow(value: Any) -> str:
    raw = str(value or "").strip().lower()
    if raw in {"", "auto", "default"}:
        return ""
    if raw in {CALIBRATION_WORKFLOW_STAGED, "staged", "three_phase", "three_stage", "staged_v1"}:
        return CALIBRATION_WORKFLOW_STAGED
    if raw in {CALIBRATION_WORKFLOW_SINGLE, "single", "single_pass_calibration", "legacy_single_pass"}:
        return CALIBRATION_WORKFLOW_SINGLE
    raise ValueError(f"未知率定流程：{value}")


def normalize_param_bounds_profile(value: Any) -> str:
    raw = str(value or "").strip().lower()
    if raw in {"", "auto", "default", "qtp", "tibetan_plateau", "qinghai_tibet", "alpine", PARAM_BOUNDS_PROFILE_QTP}:
        return PARAM_BOUNDS_PROFILE_QTP
    if raw in {"generic", "wide", "universal", "legacy", PARAM_BOUNDS_PROFILE_GENERIC}:
        return PARAM_BOUNDS_PROFILE_GENERIC
    raise ValueError(f"未知参数边界档案：{value}")


def resolve_param_bounds_profile(config: dict[str, Any], explicit: Any, profile: str) -> str:
    if profile != PROFILE_DAILY:
        return PARAM_BOUNDS_PROFILE_HOURLY
    raw = explicit
    if raw in (None, ""):
        raw = (
            config.get("参数边界档案")
            or config.get("param_bounds_profile")
            or config.get("参数范围档案")
            or DEFAULT_DAILY_PARAM_BOUNDS_PROFILE
        )
    return normalize_param_bounds_profile(raw)


def parameter_bounds_for_profile(profile: str, bounds_profile: str | None = None) -> list[tuple[float, float]]:
    if profile == PROFILE_HOURLY:
        return [tuple(bound) for bound in HOURLY_PARAM_BOUNDS]
    selected = normalize_param_bounds_profile(bounds_profile or DEFAULT_DAILY_PARAM_BOUNDS_PROFILE)
    return [tuple(bound) for bound in DAILY_PARAM_BOUNDS_BY_PROFILE[selected]]


def build_parameter_profile_meta(profile: str, bounds_profile: str | None = None) -> dict[str, Any]:
    selected_profile = resolve_param_bounds_profile({}, bounds_profile, profile)
    bounds = parameter_bounds_for_profile(profile, selected_profile)
    label = PROFILE_LABELS[PROFILE_HOURLY] if profile == PROFILE_HOURLY else PROFILE_LABELS[PROFILE_DAILY]
    bounds_label = PARAM_BOUNDS_PROFILE_LABELS.get(selected_profile, selected_profile)
    return {
        "name": profile,
        "label": f"{label} · {bounds_label}" if profile == PROFILE_DAILY else label,
        "bounds_profile": selected_profile,
        "bounds_profile_label": bounds_label,
        "notes": [
            PARAM_BOUNDS_PROFILE_NOTES.get(selected_profile, "参数边界取自当前运行配置。"),
            "日尺度参数范围与小时尺度分开管理。" if profile == PROFILE_DAILY else "Results are stored separately from daily mode.",
        ],
        "bounds": {name: list(bound) for name, bound in zip(CALIBRATION_PARAM_NAMES, bounds)},
    }


def calibration_workflow_status(workflow: Any) -> str:
    normalized = normalize_calibration_workflow(workflow)
    if normalized == CALIBRATION_WORKFLOW_STAGED:
        return "experimental"
    return "default_production"


def resolve_calibration_workflow(config: dict[str, Any], explicit: Any, profile: str) -> str:
    selected = normalize_calibration_workflow(explicit)
    if not selected:
        selected = normalize_calibration_workflow(
            config.get("率定流程", config.get("calibration_workflow", ""))
        )
    if selected:
        return selected if profile == PROFILE_DAILY else CALIBRATION_WORKFLOW_SINGLE
    return CALIBRATION_WORKFLOW_SINGLE


def build_profile_paths(config: dict[str, Any], profile: str) -> dict[str, Path]:
    requested_base = build_workspace_paths(config)
    requested_workspace_root = Path(requested_base["workspace_root"]).resolve(strict=False)
    effective_workspace_root = _effective_workspace_root(requested_workspace_root)
    effective_config = dict(config)
    effective_config["运行目录"] = str(effective_workspace_root)
    base = build_workspace_paths(effective_config)
    paths = {key: Path(value) if isinstance(value, Path) else value for key, value in base.items()}
    workspace_root = Path(paths["workspace_root"])
    profile_label = "小时尺度" if profile == PROFILE_HOURLY else "日尺度"
    results_root = select_workspace_path(
        workspace_root,
        ("结果", profile_label),
        ("results", profile),
    )
    requested_results_root = Path(results_root)
    results_root = _effective_results_root(workspace_root, requested_results_root)
    if profile == PROFILE_HOURLY:
        aligned_root = select_workspace_path(
            workspace_root,
            ("数据", "模型输入", "小时尺度"),
            ("data", "aligned_masked", "hourly"),
        )
        paths["aligned_dir"] = aligned_root
        paths["aligned_temp_dir"] = select_workspace_path(aligned_root, ("气温",), ("temp",))
        paths["aligned_evap_dir"] = select_workspace_path(aligned_root, ("蒸散发",), ("evap",))
        paths["glacier_melt_dir"] = select_workspace_path(aligned_root, ("冰川融水",), ("glacier_melt",))
    else:
        aligned_root = Path(paths["aligned_dir"])

    paths["aligned_prec_base_dir"] = select_workspace_path(aligned_root, ("降水_MSWEP",), ("prec",))
    paths["aligned_prec_cmfd_base_dir"] = select_workspace_path(aligned_root, ("降水_CMFD",), ("prec_cmfd",))
    paths["aligned_prec_custom_base_dir"] = select_workspace_path(aligned_root, ("降水_本地导入",), ("prec_custom",))
    paths["aligned_prec_corrected_dir"] = select_workspace_path(aligned_root, ("降水_MSWEP_站点订正",), ("prec_corrected",))
    paths["aligned_prec_cmfd_corrected_dir"] = select_workspace_path(aligned_root, ("降水_CMFD_站点订正",), ("prec_cmfd_corrected",))
    paths["aligned_prec_custom_corrected_dir"] = select_workspace_path(aligned_root, ("降水_本地导入_站点订正",), ("prec_custom_corrected",))
    precip_mode = str(dict(config.get("气象策略", {})).get("降水方案", "grid_only")).strip()
    use_corrected = precip_mode != "grid_only"
    paths["aligned_prec_dir"] = paths["aligned_prec_corrected_dir"] if use_corrected else paths["aligned_prec_base_dir"]
    paths["aligned_prec_cmfd_dir"] = paths["aligned_prec_cmfd_corrected_dir"] if use_corrected else paths["aligned_prec_cmfd_base_dir"]
    paths["aligned_prec_custom_dir"] = paths["aligned_prec_custom_corrected_dir"] if use_corrected else paths["aligned_prec_custom_base_dir"]
    configured_source = configured_precip_source(config)
    if configured_source == "custom_tif":
        paths["aligned_prec_effective_base_dir"] = paths["aligned_prec_custom_base_dir"]
        paths["aligned_prec_effective_dir"] = paths["aligned_prec_custom_dir"]
    elif configured_source == "cmfd":
        paths["aligned_prec_effective_base_dir"] = paths["aligned_prec_cmfd_base_dir"]
        paths["aligned_prec_effective_dir"] = paths["aligned_prec_cmfd_dir"]
    else:
        paths["aligned_prec_effective_base_dir"] = paths["aligned_prec_base_dir"]
        paths["aligned_prec_effective_dir"] = paths["aligned_prec_dir"]
    paths["results_root"] = results_root
    paths["runs_dir"] = select_workspace_path(results_root, ("运行记录",), ("runs",))
    paths["logs_dir"] = select_workspace_path(results_root, ("日志",), ("logs",))
    paths["cache_dir"] = select_workspace_path(results_root, ("缓存",), ("cache",))
    paths["requested_results_root"] = requested_results_root
    paths["requested_workspace_root"] = requested_workspace_root
    return paths


def _append_unique_candidate(candidates: list[Path], seen: set[str], value: Path | None) -> None:
    if value is None:
        return
    try:
        resolved = Path(value).resolve(strict=False)
    except Exception:
        return
    key = str(resolved).lower()
    if key in seen:
        return
    seen.add(key)
    candidates.append(resolved)


def _path_within(root: Path, candidate: Path) -> bool:
    try:
        candidate.resolve(strict=False).relative_to(root.resolve(strict=False))
        return True
    except Exception:
        return False


def _first_existing_file(candidates: list[Path]) -> Path | None:
    for candidate in candidates:
        try:
            if candidate.exists() and candidate.is_file():
                return candidate.resolve(strict=False)
        except Exception:
            continue
    return None


def _copy_vector_bundle(source: Path, target: Path) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    copied = False
    for suffix in VECTOR_BUNDLE_SUFFIXES:
        src = source.with_suffix(suffix)
        if not src.exists():
            continue
        shutil.copy2(src, target.with_suffix(suffix))
        copied = True
    if (not copied) and source.exists():
        shutil.copy2(source, target)


def _workspace_missing_input_candidates(config: dict[str, Any], target: Path) -> list[Path]:
    basename = str(target.name or "").strip()
    if not basename:
        return []
    workspace_root = Path(build_workspace_paths(config)["workspace_root"]).resolve(strict=False)
    candidates: list[Path] = []
    seen: set[str] = set()

    _append_unique_candidate(candidates, seen, target.parent / basename)

    if TEMPLATE_ASSET_ROOT.exists():
        for found in TEMPLATE_ASSET_ROOT.rglob(basename):
            _append_unique_candidate(candidates, seen, found)

    parent = workspace_root.parent
    if parent.exists():
        for sibling in parent.iterdir():
            try:
                if (not sibling.is_dir()) or sibling.resolve(strict=False) == workspace_root:
                    continue
            except Exception:
                continue
            for found in sibling.rglob(basename):
                _append_unique_candidate(candidates, seen, found)

    return candidates


def _observed_csv_recovery_candidates(config: dict[str, Any], target: Path) -> list[Path]:
    basename = str(target.name or "").strip()
    if not basename:
        return []
    paths = build_workspace_paths(config)
    workspace_root = Path(paths["workspace_root"]).resolve(strict=False)
    observed_dir = Path(paths["observed_dir"]).resolve(strict=False)
    candidates: list[Path] = []
    seen: set[str] = set()

    _append_unique_candidate(candidates, seen, observed_dir / basename)

    if TEMPLATE_ASSET_ROOT.exists():
        for found in TEMPLATE_ASSET_ROOT.rglob(basename):
            _append_unique_candidate(candidates, seen, found)

    parent = workspace_root.parent
    if parent.exists():
        for sibling in parent.iterdir():
            try:
                if (not sibling.is_dir()) or sibling.resolve(strict=False) == workspace_root:
                    continue
            except Exception:
                continue
            for candidate_dir in workspace_path_candidates(sibling, ("数据", "观测数据"), ("data", "observed")):
                _append_unique_candidate(candidates, seen, Path(candidate_dir) / basename)

    return candidates


def resolve_observed_csv_path(config: dict[str, Any], *, copy_missing: bool = False) -> tuple[Path | None, Path | None]:
    text = str(config.get("观测径流_csv", "") or "").strip()
    if not text:
        return None, None
    target = resolve_path(text, base=config_base_dir(config))
    if target is None:
        return None, None
    target = target.resolve(strict=False)
    if target.exists():
        return target, None

    workspace_root = Path(build_workspace_paths(config)["workspace_root"]).resolve(strict=False)
    if not _path_within(workspace_root, target):
        return target, None

    candidate = _first_existing_file(_observed_csv_recovery_candidates(config, target))
    if candidate is None:
        return target, None

    if copy_missing and candidate != target:
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(candidate, target)
    return target, candidate


def resolve_vector_input_path(
    config: dict[str, Any],
    key: str,
    *,
    copy_missing: bool = False,
) -> tuple[Path | None, Path | None]:
    text = str(config.get(key, "") or "").strip()
    if not text:
        return None, None
    target = resolve_path(text, base=config_base_dir(config))
    if target is None:
        return None, None
    target = target.resolve(strict=False)
    if target.exists():
        return target, None

    workspace_root = Path(build_workspace_paths(config)["workspace_root"]).resolve(strict=False)
    if not _path_within(workspace_root, target):
        return target, None

    candidate = _first_existing_file(_workspace_missing_input_candidates(config, target))
    if candidate is None:
        return target, None

    if copy_missing and candidate != target:
        if target.suffix.lower() == ".shp":
            _copy_vector_bundle(candidate, target)
        else:
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(candidate, target)
    return target, candidate


def patch_runtime_environment(module: Any, config: dict[str, Any], profile: str, cli_args: argparse.Namespace) -> dict[str, Path]:
    paths = build_profile_paths(config, profile)
    requested_paths = build_workspace_paths(config)
    basin = basin_paths(config)
    boundary = 边界条件配置(config)
    obs_path, _ = resolve_observed_csv_path(config, copy_missing=True)
    object_type = detect_object_type(config)
    use_boundary_inflow = object_type == OBJECT_INTERBASIN
    ensure_workspace_dirs(
        paths,
        required_keys=(
            "workspace_root",
            "data_root",
            "gis_dir",
            "observed_dir",
            "raw_root",
            "aligned_dir",
            "aligned_temp_dir",
            "aligned_evap_dir",
            "glacier_melt_dir",
            "aligned_prec_effective_base_dir",
            "aligned_prec_effective_dir",
            "results_root",
            "runs_dir",
            "logs_dir",
            "cache_dir",
        ),
    )
    seeded_inputs = _seed_workspace_runtime_inputs(requested_paths, paths, profile)
    time_cfg, step_hours = resolve_runtime_time_config(config)
    prec_source = resolve_runtime_precip_source(config, cli_args.降水源)
    prec_dir_override = str(getattr(cli_args, "prec_dir", "") or "").strip()
    if not prec_dir_override and prec_source == "custom_tif":
        prec_dir_override = str(paths["aligned_prec_custom_dir"])
    zone_threshold = cfmax_zone_threshold(config)
    obs_mode = config.get("观测口径模式", config.get("观测径流口径模式", "full_year"))
    init_state_vector = resolve_runtime_init_state(config)

    patch_module(
        module,
        {
            "PROJECT_ROOT": str(paths["workspace_root"]),
            "PREC_DIR_MSWEP": str(paths["aligned_prec_dir"]),
            "PREC_DIR_CMFD": str(paths["aligned_prec_cmfd_dir"]),
            "PREC_DIR": str(prec_dir_override or (paths["aligned_prec_dir"] if prec_source == "mswep" else paths["aligned_prec_cmfd_dir"])),
            "TEMP_DIR": str(paths["aligned_temp_dir"]),
            "EVAP_DIR": str(paths["aligned_evap_dir"]),
            "OBS_FILE": str(obs_path or basin["obs_csv"] or ""),
            "FLOW_ACC_PATH": str(paths["gis_dir"] / "flow_accumulation_masked.tif"),
            "GLACIER_MELT_DIR": str(paths["glacier_melt_dir"]),
            "GLACIER_MASK_PATH": str(paths["gis_dir"] / "glacier_mask.tif"),
            "GLACIER_FRACTION_PATH": str(paths["gis_dir"] / "glacier_fraction.tif"),
            "GLACIER_ELEV_PATH": str(paths["gis_dir"] / "glacier_elev.tif"),
            "LOG_DIR": str(paths["logs_dir"]),
            "RUNS_DIR": str(paths["runs_dir"]),
            "CACHE_DIR": str(paths["cache_dir"]),
            "WARMUP_START": time_cfg["预热开始"],
            "WARMUP_END": time_cfg["预热结束"],
            "CALIB_START": time_cfg["率定开始"],
            "CALIB_END": time_cfg["率定结束"],
            "VALID_START": time_cfg["验证开始"],
            "VALID_END": time_cfg["验证结束"],
            "SIM_START": time_cfg["预热开始"],
            "SIM_END": time_cfg["验证结束"],
            "OBS_MODE_OVERRIDE": obs_mode,
            "TIME_STEP_HOURS": step_hours,
            "CFMAX_ZONE_ELEV": zone_threshold,
            "INIT_ST": init_state_vector,
            "BOUNDARY_INFLOW_FILE": (
                str(boundary["上游边界入流_csv"])
                if use_boundary_inflow and boundary["上游边界入流_csv"]
                else ""
            ),
            "BOUNDARY_INFLOW_DATE_FIELD": str(boundary["时间字段"]) if use_boundary_inflow else "date",
            "BOUNDARY_INFLOW_FLOW_FIELD": str(boundary["流量字段"]) if use_boundary_inflow else "inflow_m3s",
            "BOUNDARY_INFLOW_GAP_FILL": str(boundary.get("缺失填补", "zero")) if use_boundary_inflow else "zero",
            "PROJECT_OBJECT_TYPE": object_type,
        },
    )
    setattr(module, "REQUESTED_WORKSPACE_ROOT", str(Path(requested_paths["workspace_root"]).resolve(strict=False)))
    setattr(module, "WORKSPACE_INPUT_SEED_SOURCES", dict(seeded_inputs))
    return paths


def build_weighted_multi_objective_meta(profile: str) -> dict[str, Any]:
    profile_label = PROFILE_LABELS.get(profile, profile)
    return {
        "type": OBJECTIVE_MODE_MULTI,
        "profile": profile,
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


def build_weighted_multi_objective(module: Any, profile: str) -> tuple[Any, Any, Any, dict[str, Any]]:
    multi_meta = build_weighted_multi_objective_meta(profile)
    state_lock = getattr(module, "_studio_objective_state_lock", None)

    def glacier_constraint_active() -> bool:
        if (
            getattr(module, "GLACIER_MELT_REF_RAW", None) is None
            and getattr(module, "GLACIER_FRAC_WINDOW", None) is None
        ):
            return False
        checker = getattr(module, "glacier_feature_enabled", None)
        if callable(checker):
            try:
                return bool(checker())
            except Exception:
                pass
        args = getattr(module, "args", None)
        return str(getattr(args, "glacier_mode", "inline") or "inline").strip().lower() == "inline"

    def compute_terms(sim: dict[str, Any]) -> tuple[float, dict[str, float] | None]:
        metrics = module.compute_metrics(sim["q_total"])
        core_compute_terms = getattr(module, "compute_objective_terms", None)
        if callable(core_compute_terms):
            try:
                return core_compute_terms(metrics, sim)
            except Exception:
                pass
        nse_cal = float(metrics.get("nse_cal", float("nan")))
        nse_val = float(metrics.get("nse_val", float("nan")))
        log_nse_cal = float(metrics.get("log_nse_cal", float("nan")))
        log_nse_val = float(metrics.get("log_nse_val", float("nan")))
        pbias_cal = float(metrics.get("pbias_cal", float("nan")))
        pbias_val = float(metrics.get("pbias_val", float("nan")))
        if not module.np.isfinite(nse_cal):
            return module.BAD_OBJ, None
        if not module.np.isfinite(log_nse_cal):
            log_nse_cal = nse_cal
        obj = (1.0 - nse_cal)
        obj += 0.35 * (1.0 - log_nse_cal)
        if module.np.isfinite(nse_val):
            obj += 0.35 * (1.0 - nse_val)
        if module.np.isfinite(log_nse_val):
            obj += 0.1225 * (1.0 - log_nse_val)
        if module.np.isfinite(pbias_cal):
            obj += 0.10 * (abs(pbias_cal) / 100.0)
        if module.np.isfinite(pbias_val):
            obj += 0.10 * (abs(pbias_val) / 100.0)

        swr_info = None
        peak_info = None
        fraction_info = None
        if sim is not None:
            obs_monthly = sim.get("obs_monthly")
            sim_monthly = sim.get("sim_monthly")
            if hasattr(module, "compute_swr_penalty") and obs_monthly is not None and sim_monthly is not None:
                pen, swr_info = module.compute_swr_penalty(
                    obs_monthly,
                    sim_monthly,
                    weight=float(getattr(module, "SIGNATURE_SWR_WEIGHT", 0.20)),
                    tol_ratio=float(getattr(module, "SIGNATURE_SWR_TOL_RATIO", 0.20)),
                )
                obj += pen
            if hasattr(module, "compute_peak_month_penalty") and obs_monthly is not None and sim_monthly is not None:
                pen, peak_info = module.compute_peak_month_penalty(
                    obs_monthly,
                    sim_monthly,
                    weight=float(getattr(module, "SIGNATURE_PEAK_WEIGHT", 0.10)),
                    tol_months=int(getattr(module, "SIGNATURE_PEAK_TOL_MONTHS", 1)),
                )
                obj += pen
            if hasattr(module, "compute_glacier_fraction_penalty"):
                frac_q_ice = sim.get("q_ice")
                frac_q_total = sim.get("q_total")
                if hasattr(module, "glacier_fraction_eval_series"):
                    frac_q_ice, frac_q_total = module.glacier_fraction_eval_series(sim)
                pen, fraction_info = module.compute_glacier_fraction_penalty(
                    frac_q_ice,
                    frac_q_total,
                    getattr(module, "GLACIER_FRAC_WINDOW", None),
                    weight=float(getattr(module, "GLACIER_FRAC_WEIGHT", 0.25)),
                )
                obj += pen

        return float(obj), {
            "nse_cal": nse_cal,
            "nse_val": nse_val,
            "log_nse_cal": log_nse_cal,
            "log_nse_val": log_nse_val,
            "pbias_cal": pbias_cal,
            "pbias_val": pbias_val,
            "swr_info": swr_info,
            "peak_info": peak_info,
            "fraction_info": fraction_info,
        }

    def objective_mode() -> str:
        core_objective_mode = getattr(module, "objective_simulation_mode", None)
        if callable(core_objective_mode):
            try:
                resolved = str(core_objective_mode() or "").strip()
                if resolved:
                    return resolved
            except Exception:
                pass
        return "objective_ice" if glacier_constraint_active() else "objective_total"

    def objective(x: Any) -> float:
        if state_lock is not None:
            with state_lock:
                module.eval_count += 1
        else:
            module.eval_count += 1
        try:
            k0 = float(x[10])
            k1 = float(x[11])
            k2 = float(x[12])
            k_musk = float(x[16])
            x_musk = float(x[17])
            if not (k0 > k1 > k2 > 0.0):
                return module.BAD_OBJ
            if not module.muskingum_is_valid(k_musk, x_musk):
                return module.BAD_OBJ
            sim = module.run_simulation(x, mode=objective_mode())
            obj, terms = compute_terms(sim)
            if not module.np.isfinite(obj):
                return module.BAD_OBJ
            if terms and obj < float(getattr(module, "best_objective", module.np.inf)):
                if state_lock is not None:
                    with state_lock:
                        if obj < float(getattr(module, "best_objective", module.np.inf)):
                            module.best_objective = float(obj)
                            module.best_score = terms["nse_cal"]
                            module.best_params = module.np.array(x).copy()
                else:
                    module.best_objective = float(obj)
                    module.best_score = terms["nse_cal"]
                    module.best_params = module.np.array(x).copy()
            return obj
        except Exception:
            return module.BAD_OBJ

    def objective_with_logging(x: Any) -> float:
        obj = objective(x)
        if state_lock is not None:
            with state_lock:
                current_eval = int(module.eval_count)
                current_best_obj = float(getattr(module, "best_objective", module.np.inf))
                current_best_score = float(getattr(module, "best_score", float("-inf")))
        else:
            current_eval = int(module.eval_count)
            current_best_obj = float(getattr(module, "best_objective", module.np.inf))
            current_best_score = float(getattr(module, "best_score", float("-inf")))
        if module.np.isfinite(obj) and (current_eval % module.args.log_every == 0):
            try:
                sim = module.run_simulation(x, mode=objective_mode())
                _, terms = compute_terms(sim)
                elapsed = time.time() - module.start_time
                rate = current_eval / elapsed if elapsed > 0 else 0.0
                if terms:
                    module.log_msg(
                        f"[{current_eval}] NSE_cal={terms['nse_cal']:.4f} "
                        f"NSE_val={terms['nse_val']:.4f} logNSE_cal={terms['log_nse_cal']:.4f} "
                        f"PBIAS_cal={terms['pbias_cal']:+.2f}% OBJ={obj:.4f} "
                        f"BestOBJ={current_best_obj:.4f} "
                        f"BestNSE={current_best_score:.4f} Rate={rate:.1f}/s"
                    )
            except Exception:
                pass
        return obj

    def de_callback(xk: Any, convergence: float) -> bool:
        if state_lock is not None:
            with state_lock:
                module.gen_count += 1
                current_gen = int(module.gen_count)
        else:
            module.gen_count += 1
            current_gen = int(module.gen_count)
        try:
            sim = module.run_simulation(xk, mode=objective_mode())
            obj, terms = compute_terms(sim)
            if terms and obj < float(getattr(module, "best_objective", module.np.inf)):
                if state_lock is not None:
                    with state_lock:
                        if obj < float(getattr(module, "best_objective", module.np.inf)):
                            module.best_objective = float(obj)
                            module.best_score = terms["nse_cal"]
                            module.best_params = module.np.array(xk).copy()
                else:
                    module.best_objective = float(obj)
                    module.best_score = terms["nse_cal"]
                    module.best_params = module.np.array(xk).copy()
            if terms:
                module.append_progress(
                    current_gen,
                    float(terms["nse_cal"]),
                    float(terms["nse_val"]),
                    float(obj),
                    float(convergence),
                )
                stage = "REFINE" if (module.PROGRESS_FILE_REFINE and module.PROGRESS_FILE == module.PROGRESS_FILE_REFINE) else "GLOBAL"
                module.log_msg(
                    f"[{stage} Gen {current_gen}] "
                    f"NSE_cal={terms['nse_cal']:.4f} NSE_val={terms['nse_val']:.4f} "
                    f"logNSE_cal={terms['log_nse_cal']:.4f} OBJ={obj:.4f} conv={convergence:.3e}"
                )
        except Exception as exc:
            module.log_msg(f"[Gen {current_gen}] Callback error: {exc}")
        return False

    return objective, objective_with_logging, de_callback, multi_meta


def build_single_objective_meta(profile: str) -> dict[str, Any]:
    profile_label = PROFILE_LABELS.get(profile, profile)
    return {
        "type": OBJECTIVE_MODE_SINGLE,
        "profile": profile,
        "label": profile_label,
        "summary": "单目标：1 - 率定期 NSE",
        "formula": "1 - NSE(calibration_period)",
        "notes": [
            "日尺度率定直接优化 1 - NSE(calibration_period)。"
            if profile == PROFILE_DAILY
            else "小时尺度率定直接优化 1 - NSE(calibration_period)。"
        ],
    }


def patch_profile_behavior(
    module: Any,
    config: dict[str, Any],
    profile: str,
    objective_mode: Any = None,
    param_bounds_profile: Any = None,
) -> None:
    selected_objective = resolve_objective_mode(config, objective_mode, profile)
    selected_bounds_profile = resolve_param_bounds_profile(config, param_bounds_profile, profile)
    if not hasattr(module, "_studio_objective_state_lock"):
        module._studio_objective_state_lock = threading.Lock()
    if not hasattr(module, "_studio_base_objective"):
        module._studio_base_objective = getattr(module, "objective", None)
        module._studio_base_objective_with_logging = getattr(module, "objective_with_logging", None)
        module._studio_base_de_callback = getattr(module, "de_callback", None)
    module.CALIBRATION_PROFILE = profile
    module.CALIBRATION_PROFILE_LABEL = PROFILE_LABELS[profile]
    module.OBJECTIVE_MODE_SELECTED = selected_objective
    module.best_objective = float("inf")
    if profile == PROFILE_DAILY:
        module.best_objective = float("inf")
        if getattr(module, "_studio_base_objective", None) is not None:
            module.objective = module._studio_base_objective
        if getattr(module, "_studio_base_objective_with_logging", None) is not None:
            module.objective_with_logging = module._studio_base_objective_with_logging
        if getattr(module, "_studio_base_de_callback", None) is not None:
            module.de_callback = module._studio_base_de_callback
        module.OBJECTIVE_PROFILE = build_weighted_multi_objective_meta(profile)
    else:
        if getattr(module, "_studio_base_objective", None) is not None:
            module.objective = module._studio_base_objective
        if getattr(module, "_studio_base_objective_with_logging", None) is not None:
            module.objective_with_logging = module._studio_base_objective_with_logging
        if getattr(module, "_studio_base_de_callback", None) is not None:
            module.de_callback = module._studio_base_de_callback
        module.OBJECTIVE_PROFILE = build_single_objective_meta(profile)

    if profile == PROFILE_DAILY:
        selected_bounds = parameter_bounds_for_profile(PROFILE_DAILY, selected_bounds_profile)
    else:
        selected_bounds = parameter_bounds_for_profile(PROFILE_HOURLY, selected_bounds_profile)
    module.PARAM_BOUNDS = selected_bounds
    if hasattr(module, "PARAM_BOUNDS_PROFILE_SELECTED"):
        module.PARAM_BOUNDS_PROFILE_SELECTED = selected_bounds_profile
    module.PARAMETER_PROFILE = build_parameter_profile_meta(profile, selected_bounds_profile)
    if profile == PROFILE_DAILY:
        module.PARAMETER_PROFILE["notes"] = [
            "日尺度率定固定使用统一日尺度 objective，不再提供多 objective 产品分支。",
            PARAM_BOUNDS_PROFILE_NOTES.get(selected_bounds_profile, "参数边界取自当前运行配置。"),
            "Parameter bounds remain managed separately from hourly mode.",
        ]
    else:
        module.PARAMETER_PROFILE["notes"] = [
            (
                "小时尺度当前启用多指标综合目标，可切回单目标 NSE。"
                if selected_objective == OBJECTIVE_MODE_MULTI
                else "小时尺度默认使用单目标 NSE，也可切换为多指标综合目标。"
            ),
            "Muskingum 路由参数范围已按 1 小时步长的离散稳定性收紧，避免大面积无效搜索。",
            "Results are stored separately from daily mode.",
        ]

    base_save_results = module.save_results

    def save_results_with_profile(result: Any) -> None:
        base_save_results(result)
        run_dir = Path(module.RUNS_DIR) / f"hbv_cryo_{module.args.prec_source}_{module.args.glacier_mode}_{module.RUN_ID}"
        metadata_file = run_dir / "metadata.json"
        if not metadata_file.exists():
            return
        metadata = json.loads(metadata_file.read_text(encoding="utf-8"))
        optimization = dict(metadata.get("optimization", {}))
        requested_objective = str(getattr(module, "REQUESTED_OBJECTIVE_MODE", OBJECTIVE_MODE_AUTO) or OBJECTIVE_MODE_AUTO).strip().lower() or OBJECTIVE_MODE_AUTO
        objective_mode_fn = getattr(module, "current_objective_mode", None)
        if callable(objective_mode_fn):
            effective_objective = str(objective_mode_fn() or requested_objective).strip().lower() or requested_objective
        else:
            effective_objective = str(getattr(module, "OBJECTIVE_MODE_SELECTED", requested_objective) or requested_objective).strip().lower() or requested_objective
        init_params_file = str(getattr(module.args, "init_params_file", "") or "")
        preset_id = ""
        if init_params_file:
            stem = Path(init_params_file).stem
            if stem.startswith("init_params_"):
                preset_id = stem[len("init_params_") :]
        method_key = str(optimization.get("method", "")).strip().lower()
        stage_stats = dict(optimization.get("stage_stats", {}) or {})
        refine_stage = dict(stage_stats.get("refine", {}) or {})
        refine_requested = bool(optimization.get("refine_requested") or optimization.get("refine_enabled") or refine_stage.get("requested"))
        refine_executed = bool(optimization.get("refine_executed") or refine_stage.get("executed"))
        refine_skipped = bool(str(refine_stage.get("skipped_reason", "") or "").strip())
        polish_enabled = bool(optimization.get("polish"))
        if method_key == "de":
            if refine_executed:
                method_label = "精细搜索 + 局部精修"
            elif refine_requested and refine_skipped:
                method_label = "精细搜索（局部精修已跳过）"
            elif refine_requested:
                method_label = "精细搜索（局部精修未产出有效结果）"
            elif polish_enabled:
                method_label = "精细搜索（含末端精修）"
            else:
                method_label = "精细搜索（差分进化）"
        elif method_key == "mc_screen_de":
            if refine_executed:
                method_label = "快速筛选 + 精细搜索 + 局部精修"
            elif refine_requested and refine_skipped:
                method_label = "快速筛选 + 精细搜索（局部精修已跳过）"
            elif refine_requested:
                method_label = "快速筛选 + 精细搜索（局部精修未产出有效结果）"
            elif polish_enabled:
                method_label = "快速筛选 + 精细搜索（含末端精修）"
            else:
                method_label = "快速筛选 + 精细搜索"
        elif method_key == "mc_only":
            method_label = "仅快速筛选"
        else:
            method_label = str(optimization.get("method_label", "")).strip() or str(optimization.get("method", "")).strip()
        optimization["method_label"] = method_label
        selected_stage = str(optimization.get("selected_result_stage", "")).strip().lower()
        optimization["selected_result_stage"] = selected_stage
        if selected_stage == "global":
            optimization["selected_result_label"] = "精细搜索结果（含末端精修）" if polish_enabled else "精细搜索结果"
        elif selected_stage == "refine":
            optimization["selected_result_label"] = "局部精修结果"
        elif selected_stage == "mc":
            optimization["selected_result_label"] = "快速筛选结果"
        optimization["init_preset_id"] = preset_id
        optimization["init_params_file"] = init_params_file or str(optimization.get("init_params_file", "") or "")
        optimization["objective_mode"] = effective_objective
        optimization["requested_objective_mode"] = requested_objective
        optimization["effective_objective_mode"] = effective_objective
        optimization["param_bounds_profile"] = selected_bounds_profile
        optimization["param_bounds_profile_label"] = PARAM_BOUNDS_PROFILE_LABELS.get(
            selected_bounds_profile,
            selected_bounds_profile,
        )
        metadata["optimization"] = optimization
        metadata["requested_objective_mode"] = requested_objective
        metadata["effective_objective_mode"] = effective_objective
        metadata["calibration_profile"] = profile
        metadata["param_bounds_profile"] = selected_bounds_profile
        metadata["param_bounds_profile_label"] = PARAM_BOUNDS_PROFILE_LABELS.get(
            selected_bounds_profile,
            selected_bounds_profile,
        )
        metadata["calibration_workflow_status"] = calibration_workflow_status(
            metadata.get("calibration_workflow", CALIBRATION_WORKFLOW_SINGLE)
        )
        metadata["project_object_type"] = detect_object_type(config)
        metadata["parameter_profile"] = module.PARAMETER_PROFILE
        metadata["objective_profile"] = module.OBJECTIVE_PROFILE
        objective_meta = dict(metadata.get("objective", {}))
        if isinstance(module.OBJECTIVE_PROFILE, dict):
            for key in ("type", "profile", "label", "summary", "formula", "weights", "diagnostic_only_constraints", "notes"):
                if key in module.OBJECTIVE_PROFILE:
                    objective_meta[key] = module.OBJECTIVE_PROFILE[key]
        metadata["objective"] = objective_meta
        metadata["workspace_config"] = to_portable_path(str(config.get("_config_path", "") or ""))
        metadata["rate_mode"] = profile
        data_sources = dict(metadata.get("data_sources", {}))
        runtime_prec_source = str(getattr(module.args, "prec_source", "") or "").strip().lower() or configured_precip_source(config)
        data_sources["prec_source"] = runtime_prec_source
        data_sources["runtime_prec_source"] = runtime_prec_source
        data_sources["configured_precip_source"] = configured_precip_source(config)
        data_sources["prec_dir"] = str(getattr(module, "PREC_DIR", "") or data_sources.get("prec_dir", ""))
        data_sources["glacier_mode"] = str(getattr(module.args, "glacier_mode", "") or data_sources.get("glacier_mode", "inline"))
        metadata["data_sources"] = data_sources
        metadata = portableize_value_paths(metadata)
        metadata_file.write_text(json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8")

    module.save_results = save_results_with_profile

def main() -> None:
    import io

    def _prefer_utf8_when_redirected(stream):
        if stream is None or (not hasattr(stream, "buffer")):
            return stream
        try:
            if stream.isatty():
                # Interactive console should keep its native encoding,
                # otherwise Windows terminals may display Chinese as mojibake.
                return stream
        except Exception:
            pass
        return io.TextIOWrapper(
            stream.buffer,
            encoding="utf-8",
            errors="replace",
            line_buffering=True,
            write_through=True,
        )

    sys.stdout = _prefer_utf8_when_redirected(sys.stdout)
    sys.stderr = _prefer_utf8_when_redirected(sys.stderr)

    args = parse_args()
    if bool(getattr(args, "quick_test", False)):
        args.debug_days = 0
    config = read_config(args.配置)
    project_root, gui_root = _placeholder_roots_for_config_path(args.配置)
    config = replace_placeholders(config, project_root=project_root, gui_root=gui_root)
    config = normalize_legacy_project_paths(
        config,
        preserve_project_root=project_root,
        preserve_gui_root=gui_root,
    )
    profile = resolve_profile(config, args.率定模式)
    requested_objective_mode = normalize_objective_mode(getattr(args, "目标函数", None))
    objective_mode = resolve_objective_mode(config, getattr(args, "目标函数", None), profile)
    calibration_workflow = resolve_calibration_workflow(config, getattr(args, "calibration_workflow", ""), profile)
    param_bounds_profile = resolve_param_bounds_profile(config, getattr(args, "param_bounds_profile", None), profile)
    runtime_precip_source = resolve_runtime_precip_source(config, args.降水源)
    legacy_precip_source = resolve_legacy_precip_source(runtime_precip_source)

    module = load_legacy_module(old_script_path(config, "model", "calibrate_hbv_cryo.py"))
    paths = patch_runtime_environment(module, config, profile, args)
    patch_profile_behavior(module, config, profile, objective_mode, param_bounds_profile)
    module.REQUESTED_OBJECTIVE_MODE = requested_objective_mode
    base_parse_args = module.parse_args

    def parse_args_with_runtime_source() -> argparse.Namespace:
        parsed = base_parse_args()
        parsed.prec_source = runtime_precip_source
        return parsed

    module.parse_args = parse_args_with_runtime_source

    argv = [
        "profile_runner.py",
        "--maxiter", str(args.maxiter),
        "--popsize", str(args.popsize),
        "--seed", str(args.seed),
        "--workers", str(args.workers),
        "--method", str(args.method),
        "--mc-samples", str(args.mc_samples),
        "--prec-source", legacy_precip_source,
        "--glacier-mode", args.冰川模式,
        "--objective-mode", requested_objective_mode,
        "--calibration-workflow", calibration_workflow,
    ]
    if profile == PROFILE_DAILY and param_bounds_profile in {PARAM_BOUNDS_PROFILE_QTP, PARAM_BOUNDS_PROFILE_GENERIC}:
        argv.extend(["--param-bounds-profile", param_bounds_profile])
    if args.prec_dir:
        argv.extend(["--prec-dir", str(args.prec_dir)])
    elif runtime_precip_source == "custom_tif":
        argv.extend(["--prec-dir", str(paths["aligned_prec_custom_dir"])])
    if args.init_params_file:
        argv.extend(["--init-params-file", str(args.init_params_file), "--init-bound-shrink", str(args.init_bound_shrink)])
    if int(getattr(args, "refine_maxiter", -1)) != -1:
        argv.extend(["--refine-maxiter", str(args.refine_maxiter)])
    if args.debug_days > 0:
        argv.extend(["--debug-days", str(args.debug_days)])
    if args.quick_test:
        argv.extend(["--quick-test", "--quick-days", str(args.quick_days)])

    with temporary_argv(argv):
        module.main()


if __name__ == "__main__":
    main()
