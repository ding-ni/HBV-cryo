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
from services.boundary import BoundaryInflowInspectContext, inspect_boundary_inflow_csv


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
OBJECTIVE_MODE_HOURLY = "hourly_alpine_qtp_v1"
OBJECTIVE_MODE_FLOOD_EVENT = "flood_event_calibration_v1"
TIME_BASIS_EVENT_WINDOWS = "event_windows"
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
EVENT_PURPOSE_ALIASES = {
    "calibration": "calibration",
    "calib": "calibration",
    "train": "calibration",
    "training": "calibration",
    "率定": "calibration",
    "训练": "calibration",
    "validation": "validation",
    "valid": "validation",
    "test": "validation",
    "验证": "validation",
    "检验": "validation",
    "diagnostic": "diagnostic",
    "diag": "diagnostic",
    "诊断": "diagnostic",
}
EVENT_PATH_FIELDS = ("事件表路径", "events_file", "event_file")
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


def _runtime_truthy(value: Any, default: bool = False) -> bool:
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
    if end and abs(float(step_hours) - 24.0) < 1e-9 and ts.hour == 0 and ts.minute == 0 and ts.second == 0:
        return ts
    return ts


def _format_event_timestamp(value: Any, step_hours: float) -> str:
    return format_runtime_time_value(pd.Timestamp(value), step_hours)


def _read_event_table_file(path: Path) -> list[dict[str, Any]]:
    suffix = path.suffix.lower()
    if suffix == ".json":
        raw = json.loads(path.read_text(encoding="utf-8"))
        events = raw.get("事件表", raw.get("events", [])) if isinstance(raw, dict) else raw
        return [dict(item) for item in events if isinstance(item, dict)] if isinstance(events, list) else []
    if suffix in {".xlsx", ".xls"}:
        frame = pd.read_excel(path)
    else:
        last_error: Exception | None = None
        for encoding in ("utf-8-sig", "utf-8", "gbk"):
            try:
                frame = pd.read_csv(path, encoding=encoding)
                break
            except Exception as exc:
                last_error = exc
        else:
            raise ValueError(f"事件表 CSV 读取失败：{last_error}")
    return frame.where(pd.notna(frame), None).to_dict(orient="records")


def _runtime_flood_event_config(config: dict[str, Any]) -> dict[str, Any]:
    raw = config.get("洪水事件率定", {})
    if isinstance(raw, list):
        cfg: dict[str, Any] = {"启用": True, "事件表": list(raw)}
    elif isinstance(raw, dict):
        cfg = dict(raw)
    else:
        cfg = {}
    event_mode = config.get("事件资料模式", {})
    if isinstance(event_mode, dict):
        for key, value in event_mode.items():
            cfg.setdefault(key, value)
    for key in EVENT_PATH_FIELDS:
        if not cfg.get(key) and config.get(key):
            cfg[key] = config.get(key)
    return cfg


def _resolve_event_file(config: dict[str, Any], cfg: dict[str, Any]) -> Path | None:
    raw = ""
    for key in EVENT_PATH_FIELDS:
        raw = str(cfg.get(key, "") or "").strip()
        if raw:
            break
    if not raw:
        return None
    target = resolve_path(raw, base=config_base_dir(config))
    return target.resolve(strict=False) if target is not None else Path(raw).expanduser().resolve(strict=False)


def runtime_time_basis(config: dict[str, Any]) -> str:
    raw = str(
        config.get("任务时段模式")
        or config.get("time_basis")
        or config.get("资料时段模式")
        or ""
    ).strip().lower()
    if raw in {"event", "events", "event_window", "event_windows", "flood_event", "洪水事件", "事件窗口", "事件资料"}:
        return TIME_BASIS_EVENT_WINDOWS
    event_mode = config.get("事件资料模式", {})
    flood_cfg = config.get("洪水事件率定", {})
    if isinstance(event_mode, dict) and _runtime_truthy(event_mode.get("启用", event_mode.get("enabled")), default=False):
        return TIME_BASIS_EVENT_WINDOWS
    if isinstance(flood_cfg, dict) and _runtime_truthy(
        flood_cfg.get("事件窗口资料", flood_cfg.get("event_windows_enabled")),
        default=False,
    ):
        return TIME_BASIS_EVENT_WINDOWS
    return "continuous"


def normalize_runtime_flood_events(config: dict[str, Any], step_hours: float) -> dict[str, Any]:
    cfg = _runtime_flood_event_config(config)
    warnings: list[str] = []
    errors: list[str] = []
    raw_events = cfg.get("事件表", cfg.get("events", []))
    if isinstance(raw_events, dict):
        raw_events = raw_events.get("events", raw_events.get("事件表", []))
    if not isinstance(raw_events, list):
        raw_events = []

    event_file = _resolve_event_file(config, cfg)
    if event_file is not None:
        if not event_file.exists():
            errors.append(f"洪水事件表文件不存在：{event_file}")
            raw_events = []
        else:
            raw_events = _read_event_table_file(event_file)

    events: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    for index, raw_event in enumerate(raw_events, start=1):
        if not isinstance(raw_event, dict):
            continue
        event = dict(raw_event)
        token = json.dumps(event, ensure_ascii=False, sort_keys=True, default=str).encode("utf-8")
        event_id = str(_event_field(event, "event_id", "id", "编号", "洪水编号", "事件编号") or "").strip()
        name = str(_event_field(event, "name", "名称", "事件名称", "洪水名称") or "").strip()
        if not event_id:
            event_id = name or f"event_{hashlib.sha1(token).hexdigest()[:8]}"
        if event_id in seen_ids:
            errors.append(f"洪水事件编号重复：{event_id}")
        seen_ids.add(event_id)

        purpose_raw = str(_event_field(event, "purpose", "用途", "类型", "type") or "calibration").strip()
        purpose = EVENT_PURPOSE_ALIASES.get(purpose_raw.lower(), purpose_raw.lower() or "calibration")
        if purpose not in {"calibration", "validation", "diagnostic"}:
            warnings.append(f"事件 {event_id} 的用途 {purpose_raw} 未识别，按 diagnostic 处理。")
            purpose = "diagnostic"

        score_start_raw = _event_field(event, "score_start", "评分开始", "事件开始", "洪水开始", "开始时间", "起始时间", "start")
        score_end_raw = _event_field(event, "score_end", "评分结束", "事件结束", "洪水结束", "结束时间", "终止时间", "end")
        run_start_raw = _event_field(event, "run_start", "运行开始", "预热开始", "warmup_start") or score_start_raw
        run_end_raw = _event_field(event, "run_end", "运行结束", "退水结束") or score_end_raw
        event_errors: list[str] = []
        try:
            run_start = _parse_event_timestamp(run_start_raw, end=False, step_hours=step_hours)
            score_start = _parse_event_timestamp(score_start_raw, end=False, step_hours=step_hours)
            score_end = _parse_event_timestamp(score_end_raw, end=True, step_hours=step_hours)
            run_end = _parse_event_timestamp(run_end_raw, end=True, step_hours=step_hours)
        except Exception as exc:
            run_start = score_start = score_end = run_end = None
            event_errors.append(f"事件时间无法解析：{exc}")
        if None in (run_start, score_start, score_end, run_end):
            event_errors.append("事件缺少开始时间或结束时间。")
        elif not (run_start <= score_start <= score_end <= run_end):
            event_errors.append("事件时间顺序不正确：运行开始应不晚于开始时间，结束时间应不晚于运行结束。")
        if event_errors:
            errors.extend(f"{event_id}: {item}" for item in event_errors)
            continue

        events.append(
            {
                "event_id": event_id,
                "id": event_id,
                "name": name or event_id,
                "purpose": purpose,
                "type": purpose,
                "类型": purpose,
                "run_start": _format_event_timestamp(run_start, step_hours),
                "score_start": _format_event_timestamp(score_start, step_hours),
                "score_end": _format_event_timestamp(score_end, step_hours),
                "run_end": _format_event_timestamp(run_end, step_hours),
                "运行开始": _format_event_timestamp(run_start, step_hours),
                "评分开始": _format_event_timestamp(score_start, step_hours),
                "评分结束": _format_event_timestamp(score_end, step_hours),
                "运行结束": _format_event_timestamp(run_end, step_hours),
                "raw": event,
                "source_row": index,
            }
        )

    events.sort(key=lambda item: (pd.Timestamp(item["run_start"]), str(item["event_id"])))
    for left, right in zip(events, events[1:]):
        if pd.Timestamp(left["run_end"]) >= pd.Timestamp(right["run_start"]):
            warnings.append(f"事件时段可能重叠：{left['event_id']} 与 {right['event_id']}。")
    return {
        "config": cfg,
        "events": events,
        "event_count": len(events),
        "source_file": str(event_file) if event_file is not None else "",
        "warnings": warnings,
        "errors": errors,
    }


def prepare_runtime_flood_event_config(
    config: dict[str, Any],
    step_hours: float,
    *,
    objective_mode: str,
) -> dict[str, Any]:
    event_info = normalize_runtime_flood_events(config, step_hours)
    strict_events = runtime_time_basis(config) == TIME_BASIS_EVENT_WINDOWS or objective_mode == OBJECTIVE_MODE_FLOOD_EVENT
    if strict_events and event_info["errors"]:
        raise ValueError("洪水事件表配置不合法：" + "；".join(event_info["errors"][:5]))
    if strict_events and not event_info["events"]:
        raise ValueError("已选择洪水事件率定或事件窗口资料模式，但事件表为空。")
    cfg = dict(event_info["config"])
    if event_info["source_file"]:
        cfg["事件表路径"] = event_info["source_file"]
        cfg["events_file"] = event_info["source_file"]
    if event_info["events"]:
        cfg["事件表"] = event_info["events"]
        cfg["events"] = event_info["events"]
        cfg.setdefault("启用", True)
    if runtime_time_basis(config) == TIME_BASIS_EVENT_WINDOWS:
        cfg["事件窗口资料"] = True
        cfg["event_windows_enabled"] = True
        cfg["允许事件间断"] = True
        cfg["event_runtime_mode"] = "independent_event_windows"
        cfg["初始条件策略"] = str(cfg.get("初始条件策略") or "event_warmup")
    if objective_mode == OBJECTIVE_MODE_FLOOD_EVENT:
        cfg["作为目标函数"] = True
        cfg["objective_enabled"] = True
        cfg["模式"] = "objective"
    if event_info["warnings"]:
        cfg["warnings"] = list(event_info["warnings"])
    if event_info["errors"]:
        cfg["errors"] = list(event_info["errors"])
    return cfg


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
PARAM_BOUNDS_PROFILE_HOURLY = "hourly_qtp_alpine_default"
PARAM_BOUNDS_PROFILE_HOURLY_LEGACY = "hourly_step"
DEFAULT_DAILY_PARAM_BOUNDS_PROFILE = PARAM_BOUNDS_PROFILE_QTP

PARAM_BOUNDS_PROFILE_LABELS = {
    PARAM_BOUNDS_PROFILE_QTP: "青藏高原高寒区默认范围",
    PARAM_BOUNDS_PROFILE_GENERIC: "通用宽范围",
    PARAM_BOUNDS_PROFILE_HOURLY: "小时尺度青藏高寒区默认范围",
    PARAM_BOUNDS_PROFILE_HOURLY_LEGACY: "小时尺度稳定范围",
}

PARAM_BOUNDS_PROFILE_NOTES = {
    PARAM_BOUNDS_PROFILE_QTP: "默认用于青藏高原高寒区率定，收窄土壤、雪冰和退水自由度，降低异参同效。",
    PARAM_BOUNDS_PROFILE_GENERIC: "保留原通用硬边界，适合资料较充分、先验不确定或需要放宽搜索的流域。",
    PARAM_BOUNDS_PROFILE_HOURLY: "用于 1 小时步长的高寒区率定，重点限制汇流和退水参数的离散稳定性。",
    PARAM_BOUNDS_PROFILE_HOURLY_LEGACY: "旧版小时尺度边界别名，自动映射到小时尺度青藏高寒区默认范围。",
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
        OBJECTIVE_MODE_FLOOD_EVENT,
        "flood_event",
        "event_objective",
        "flood_event_objective",
        "event_calibration",
        "洪水事件率定",
        "事件率定",
    }:
        return OBJECTIVE_MODE_FLOOD_EVENT
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
    if raw in {
        OBJECTIVE_MODE_HOURLY,
        "hourly",
        "hourly_qtp",
        "hourly_alpine",
        "hourly_unified",
    }:
        return OBJECTIVE_MODE_HOURLY
    raise ValueError(f"未知目标函数模式：{value}")


def configured_precip_source(config: dict[str, Any]) -> str:
    meteo = dict(config.get("气象策略", {}))
    source = str(meteo.get("降水来源", "")).strip().lower()
    legacy_source = str(meteo.get("降水源", "")).strip().lower()
    top_level_source = str(config.get("默认降水源", "")).strip().lower()
    if source:
        return source
    if top_level_source in {"era5", "cmfd", "custom_tif"} and legacy_source in {"", "mswep"}:
        return top_level_source
    return legacy_source or top_level_source or "era5"


def resolve_runtime_precip_source(config: dict[str, Any], cli_source: Any) -> str:
    raw = str(cli_source or "").strip().lower()
    if raw in {"era5", "mswep", "cmfd", "custom_tif"}:
        return raw
    configured = configured_precip_source(config)
    if configured in {"era5", "mswep", "cmfd", "custom_tif"}:
        return configured
    return "era5"


def resolve_legacy_precip_source(runtime_source: str) -> str:
    source = str(runtime_source).strip().lower()
    if source in {"era5", "cmfd"}:
        return source
    return "mswep"


def _workspace_mirror_name(workspace_root: Path) -> str:
    digest = hashlib.sha1(str(workspace_root.resolve(strict=False)).encode("utf-8")).hexdigest()[:10]
    return f"{workspace_root.name}_{digest}"


def _dir_is_writable(path: Path) -> bool:
    probe = path / f".__codex_write_probe__{os.getpid()}_{threading.get_ident()}_{time.time_ns()}"
    try:
        path.mkdir(parents=True, exist_ok=True)
        probe.write_text("ok", encoding="utf-8")
        try:
            probe.unlink()
        except FileNotFoundError:
            pass
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
        "aligned_prec_era5_base_dir",
        "aligned_prec_base_dir",
        "aligned_prec_cmfd_base_dir",
        "aligned_prec_custom_base_dir",
        "aligned_prec_era5_corrected_dir",
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
    parser.add_argument("--降水源", "--prec-source", dest="降水源", choices=["era5", "mswep", "cmfd", "custom_tif"], default=None)
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
        choices=[PARAM_BOUNDS_PROFILE_QTP, PARAM_BOUNDS_PROFILE_GENERIC, PARAM_BOUNDS_PROFILE_HOURLY, PARAM_BOUNDS_PROFILE_HOURLY_LEGACY],
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


def precipitation_product_metadata_error(config: dict[str, Any]) -> str:
    metadata = dict(config.get("降水产品元数据", config.get("precipitation_product_metadata", {})) or {})
    if not metadata:
        return ""
    allowed = _runtime_truthy(metadata.get("formal_run_allowed"), default=True)
    if allowed:
        return ""
    run_purpose = str(config.get("运行用途", config.get("run_purpose", "")) or "").strip().lower()
    empirical_diagnostic_allowed = _runtime_truthy(
        metadata.get("empirical_diagnostic_allowed"),
        default=False,
    )
    if empirical_diagnostic_allowed and run_purpose in {"qc_only", "diagnostic_only", "internal_diagnostic"}:
        return ""
    status = str(metadata.get("metadata_status", "pending_confirmation") or "pending_confirmation")
    return f"降水产品元数据尚未确认（{status}），当前工作区仅允许质检，禁止正式率定。"


def precipitation_strategy_qc_error(summary: dict[str, Any]) -> str:
    processing = dict(summary.get("processing_stats", {}) or {})
    if not bool(processing.get("qc_blocked", False)):
        return ""
    monthly = dict(processing.get("monthly_conservation", {}) or {})
    return (
        "站点订正降水月量守恒 QC 未通过："
        f"高倍率像元-月份 {int(monthly.get('high_factor_cell_count', 0) or 0)}，"
        f"移除比例超过 30% 的像元-月份 {int(monthly.get('high_removed_fraction_cell_count', 0) or 0)}，"
        f"未分配像元-月份 {int(monthly.get('unresolved_cell_count', 0) or 0)}；禁止正式率定。"
    )


def daily_forcing_manifest_error(config: dict[str, Any], profile: str) -> str:
    if profile != PROFILE_DAILY:
        return ""
    meteo = dict(config.get("气象策略", {}) or {})
    algorithm = str(meteo.get("station_correction_algorithm", "") or "").strip().lower()
    if algorithm != "occurrence_amount_v2":
        return ""
    paths = build_profile_paths(config, profile)
    manifest_path = Path(paths["aligned_dir"]) / "daily_forcing_manifest.json"
    if not manifest_path.exists():
        return f"缺少日强迫契约清单：{manifest_path}。请重新执行本地日 TIF 导入并确认单位与日界。"
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except Exception as exc:
        return f"日强迫契约清单无法读取：{exc}"
    precipitation = dict(manifest.get("precipitation", {}) or {})
    if str(manifest.get("schema", "")) != "hbv_cryo_daily_forcing_manifest_v1":
        return "日强迫契约清单版本不受支持，请重新导入。"
    if not bool(precipitation.get("unit_confirmed")) or precipitation.get("output_unit") != "mm/day":
        return "日降水单位尚未确认为 mm/day，请重新导入。"
    if not bool(precipitation.get("day_basis_confirmed")) or not str(precipitation.get("day_basis", "")).strip():
        return "日降水日界尚未确认，请重新导入。"
    return ""


def required_boundary_index(config: dict[str, Any]) -> tuple[pd.DatetimeIndex, float]:
    time_cfg, step_hours = resolve_runtime_time_config(config)
    warmup_end = pd.to_datetime(time_cfg["预热结束"])
    evaluation_end_raw = time_cfg.get("验证结束") or time_cfg.get("率定结束")
    if not evaluation_end_raw:
        raise ValueError("时间.验证结束或时间.率定结束未设置。")
    evaluation_end = pd.to_datetime(evaluation_end_raw)
    required_steps = max(1, int(round(14.0 * 24.0 / step_hours)))
    required_start = warmup_end - pd.Timedelta(hours=step_hours * (required_steps - 1))
    frequency = pd.Timedelta(hours=step_hours)
    return pd.date_range(required_start, evaluation_end, freq=frequency), step_hours


def required_boundary_coverage_error(config: dict[str, Any], profile: str) -> str:
    if detect_object_type(config) != OBJECT_INTERBASIN:
        return ""
    boundary = 边界条件配置(config)
    boundary_path = Path(boundary.get("上游边界入流_csv", ""))
    if not boundary_path.exists():
        return f"上游边界入流文件不存在：{boundary_path}"
    expected_index, step_hours = required_boundary_index(config)

    def resolve_boundary_path(raw: str, *, must_exist: bool = False) -> Path:
        path = Path(raw).expanduser().resolve(strict=False)
        if must_exist and not path.exists():
            raise FileNotFoundError(path)
        return path

    info = inspect_boundary_inflow_csv(
        str(boundary_path),
        BoundaryInflowInspectContext(
            resolve_path=resolve_boundary_path,
            profile_daily=PROFILE_DAILY,
            profile_hourly=PROFILE_HOURLY,
        ),
        date_field=str(boundary.get("时间字段", "date")),
        flow_field=str(boundary.get("流量字段", "flow")),
        expected_index=expected_index,
        expected_step_hours=step_hours,
    )
    missing = list(info.get("missing_steps", []))
    if not missing:
        return ""
    samples = "、".join(format_runtime_time_value(pd.Timestamp(ts), step_hours) for ts in missing[:3])
    return (
        "上游边界入流在预热末 14 日及正式评价期缺少 "
        f"{len(missing)} 个时间步，例如：{samples}；该时段禁止零填补或插值后正式率定。"
    )


def validate_profile_input_contracts(config: dict[str, Any], profile: str) -> None:
    errors: list[str] = []
    metadata_error = precipitation_product_metadata_error(config)
    if metadata_error:
        errors.append(metadata_error)
    manifest_error = daily_forcing_manifest_error(config, profile)
    if manifest_error:
        errors.append(manifest_error)
    meteo = dict(config.get("气象策略", {}) or {})
    if str(meteo.get("降水方案", "grid_only") or "grid_only").strip() != "grid_only":
        paths = build_profile_paths(config, profile)
        summary_path = Path(paths["aligned_prec_effective_dir"]) / "precipitation_strategy_summary.json"
        if summary_path.exists():
            try:
                summary_error = precipitation_strategy_qc_error(json.loads(summary_path.read_text(encoding="utf-8")))
            except Exception as exc:
                summary_error = f"站点订正降水 QC 摘要无法读取：{exc}"
            if summary_error:
                errors.append(summary_error)
    boundary_error = required_boundary_coverage_error(config, profile)
    if boundary_error:
        errors.append(boundary_error)
    if errors:
        raise ValueError("正式运行输入契约未通过：\n- " + "\n- ".join(errors))


def resolve_objective_mode(config: dict[str, Any], explicit: Any, profile: str) -> str:
    selected = normalize_objective_mode(explicit)
    flood_cfg = config.get("洪水事件率定", {})
    if isinstance(flood_cfg, dict):
        flood_objective_enabled = (
            flood_cfg.get("作为目标函数")
            if "作为目标函数" in flood_cfg
            else flood_cfg.get("目标函数启用")
            if "目标函数启用" in flood_cfg
            else flood_cfg.get("objective_enabled")
            if "objective_enabled" in flood_cfg
            else flood_cfg.get("use_as_objective")
        )
        flood_mode = str(flood_cfg.get("模式", flood_cfg.get("mode", flood_cfg.get("率定模式", ""))) or "").strip().lower()
        flood_objective_bool = (
            flood_objective_enabled is True
            or str(flood_objective_enabled or "").strip().lower() in {"1", "true", "yes", "on", "启用", "是"}
        )
        if flood_objective_bool or flood_mode in {"objective", "event_objective", "calibration", "event_calibration", OBJECTIVE_MODE_FLOOD_EVENT, "目标函数", "事件率定", "洪水事件率定"}:
            return OBJECTIVE_MODE_FLOOD_EVENT
    if selected == OBJECTIVE_MODE_AUTO:
        selected = normalize_objective_mode(config.get("目标函数模式", OBJECTIVE_MODE_AUTO))
    if selected == OBJECTIVE_MODE_FLOOD_EVENT:
        return OBJECTIVE_MODE_FLOOD_EVENT
    if profile == PROFILE_DAILY:
        return OBJECTIVE_MODE_MULTI
    if selected == OBJECTIVE_MODE_AUTO:
        return OBJECTIVE_MODE_HOURLY
    if selected == OBJECTIVE_MODE_SINGLE:
        return OBJECTIVE_MODE_SINGLE
    return OBJECTIVE_MODE_HOURLY


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
    if raw in {"hourly", "hourly_qtp", "hourly_alpine", PARAM_BOUNDS_PROFILE_HOURLY, PARAM_BOUNDS_PROFILE_HOURLY_LEGACY}:
        return PARAM_BOUNDS_PROFILE_HOURLY
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

    paths["aligned_prec_era5_base_dir"] = select_workspace_path(aligned_root, ("降水",), ("precipitation",))
    paths["aligned_prec_base_dir"] = select_workspace_path(aligned_root, ("降水_MSWEP",), ("prec",))
    paths["aligned_prec_cmfd_base_dir"] = select_workspace_path(aligned_root, ("降水_CMFD",), ("prec_cmfd",))
    paths["aligned_prec_custom_base_dir"] = select_workspace_path(aligned_root, ("降水_本地导入",), ("prec_custom",))
    paths["aligned_prec_era5_corrected_dir"] = select_workspace_path(aligned_root, ("降水_ERA5_站点订正",), ("precipitation_corrected",))
    paths["aligned_prec_corrected_dir"] = select_workspace_path(aligned_root, ("降水_MSWEP_站点订正",), ("prec_corrected",))
    paths["aligned_prec_cmfd_corrected_dir"] = select_workspace_path(aligned_root, ("降水_CMFD_站点订正",), ("prec_cmfd_corrected",))
    paths["aligned_prec_custom_corrected_dir"] = select_workspace_path(aligned_root, ("降水_本地导入_站点订正",), ("prec_custom_corrected",))
    precip_mode = str(dict(config.get("气象策略", {})).get("降水方案", "grid_only")).strip()
    use_corrected = precip_mode != "grid_only"
    paths["aligned_prec_era5_dir"] = paths["aligned_prec_era5_corrected_dir"] if use_corrected else paths["aligned_prec_era5_base_dir"]
    paths["aligned_prec_dir"] = paths["aligned_prec_corrected_dir"] if use_corrected else paths["aligned_prec_base_dir"]
    paths["aligned_prec_cmfd_dir"] = paths["aligned_prec_cmfd_corrected_dir"] if use_corrected else paths["aligned_prec_cmfd_base_dir"]
    paths["aligned_prec_custom_dir"] = paths["aligned_prec_custom_corrected_dir"] if use_corrected else paths["aligned_prec_custom_base_dir"]
    configured_source = configured_precip_source(config)
    if configured_source == "era5":
        paths["aligned_prec_effective_base_dir"] = paths["aligned_prec_era5_base_dir"]
        paths["aligned_prec_effective_dir"] = paths["aligned_prec_era5_dir"]
    elif configured_source == "custom_tif":
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
    step_hours = float(time_step_hours(config))
    runtime_objective_mode = resolve_objective_mode(config, getattr(cli_args, "目标函数", None), profile)
    flood_event_config = prepare_runtime_flood_event_config(
        config,
        step_hours,
        objective_mode=runtime_objective_mode,
    )
    if runtime_time_basis(config) == TIME_BASIS_EVENT_WINDOWS:
        events = list(flood_event_config.get("事件表", flood_event_config.get("events", [])) or [])
        if not events:
            raise ValueError("已选择洪水事件窗口资料模式，但没有可用事件。请检查事件表。")
        objective_events = [item for item in events if str(item.get("purpose", item.get("type", ""))).lower() == "calibration"] or events
        validation_events = [item for item in events if str(item.get("purpose", item.get("type", ""))).lower() == "validation"]
        run_start = min(pd.Timestamp(item["run_start"]) for item in events)
        run_end = max(pd.Timestamp(item["run_end"]) for item in events)
        calib_start = min(pd.Timestamp(item["score_start"]) for item in objective_events)
        calib_end = max(pd.Timestamp(item["score_end"]) for item in objective_events)
        if validation_events:
            valid_start = min(pd.Timestamp(item["score_start"]) for item in validation_events)
            valid_end = max(pd.Timestamp(item["score_end"]) for item in validation_events)
        else:
            valid_start = calib_end
            valid_end = calib_end
        warmup_end = calib_start - pd.Timedelta(hours=step_hours)
        if warmup_end < run_start:
            warmup_end = run_start
        time_cfg = dict(config.get("时间", {}) or {})
        time_cfg.update(
            {
                "预热开始": format_runtime_time_value(run_start, step_hours),
                "预热结束": format_runtime_time_value(warmup_end, step_hours),
                "率定开始": format_runtime_time_value(calib_start, step_hours),
                "率定结束": format_runtime_time_value(calib_end, step_hours),
                "验证开始": format_runtime_time_value(valid_start, step_hours),
                "验证结束": format_runtime_time_value(valid_end, step_hours),
                "模拟结束": format_runtime_time_value(run_end, step_hours),
            }
        )
    else:
        time_cfg, step_hours = resolve_runtime_time_config(config)
    prec_source = resolve_runtime_precip_source(config, cli_args.降水源)
    prec_dir_override = str(getattr(cli_args, "prec_dir", "") or "").strip()
    if not prec_dir_override and prec_source == "custom_tif":
        prec_dir_override = str(paths["aligned_prec_custom_dir"])
    zone_threshold = cfmax_zone_threshold(config)
    obs_mode = config.get("观测口径模式", config.get("观测径流口径模式", "full_year"))
    init_state_vector = resolve_runtime_init_state(config)
    interval_evaluation = dict(config.get("区间评价", config.get("interval_evaluation", {})) or {})
    interval_guard_enabled = _runtime_truthy(
        interval_evaluation.get("目标约束启用", interval_evaluation.get("objective_guard_enabled")),
        default=False,
    )
    try:
        interval_guard_weight = float(
            interval_evaluation.get("目标约束权重", interval_evaluation.get("objective_guard_weight", 0.15))
        )
    except (TypeError, ValueError):
        interval_guard_weight = 0.15
    interval_guard_weight = min(max(interval_guard_weight, 0.0), 1.0)
    patch_module(
        module,
        {
            "PROJECT_ROOT": str(paths["workspace_root"]),
            "PREC_DIR_ERA5": str(paths["aligned_prec_era5_dir"]),
            "PREC_DIR_MSWEP": str(paths["aligned_prec_dir"]),
            "PREC_DIR_CMFD": str(paths["aligned_prec_cmfd_dir"]),
            "PREC_DIR": str(
                prec_dir_override
                or (
                    paths["aligned_prec_era5_dir"]
                    if prec_source == "era5"
                    else paths["aligned_prec_dir"]
                    if prec_source == "mswep"
                    else paths["aligned_prec_custom_dir"]
                    if prec_source == "custom_tif"
                    else paths["aligned_prec_cmfd_dir"]
                )
            ),
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
            "INTERVAL_OBJECTIVE_GUARD_ENABLED": interval_guard_enabled,
            "INTERVAL_OBJECTIVE_GUARD_WEIGHT": interval_guard_weight,
            "FLOOD_EVENT_CONFIG": flood_event_config,
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
            "interbasin_residual": True,
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


def build_hourly_alpine_objective_meta(profile: str) -> dict[str, Any]:
    return {
        "type": OBJECTIVE_MODE_HOURLY,
        "profile": profile,
        "label": "小时尺度高寒区率定目标",
        "summary": "小时流量过程为主，叠加 08:00 水文日聚合约束和 6 小时洪峰时序容差。",
        "formula": "weighted(hourly NSE/logNSE/PBIAS, hydro-day NSE/PBIAS, peak timing penalty)",
        "weights": {
            "hourly_nse_cal": 1.00,
            "hourly_log_nse_cal": 0.25,
            "hourly_pbias_cal": 0.12,
            "hydroday_nse_cal": 0.35,
            "hydroday_pbias_cal": 0.12,
            "peak_timing_cal": 0.08,
        },
        "diagnostic_only_constraints": {
            "validation_metrics": True,
            "source_partition": True,
        },
        "notes": [
            "率定目标只使用率定期有效观测；验证期指标保留为诊断输出。",
            "日约束按 08:00-次日 08:00 水文日把小时流量聚合为日均流量。",
            "该目标函数服务于小时尺度高寒区方案，不改变日尺度统一目标函数。",
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
        if selected_objective == OBJECTIVE_MODE_SINGLE:
            module.OBJECTIVE_PROFILE = build_single_objective_meta(profile)
        else:
            module.OBJECTIVE_PROFILE = build_hourly_alpine_objective_meta(profile)

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
                "小时尺度当前启用小时高寒区综合目标，可显式切回单目标 NSE。"
                if selected_objective == OBJECTIVE_MODE_HOURLY
                else "小时尺度当前显式使用单目标 NSE，默认推荐小时高寒区综合目标。"
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
        actual_objective_profile = (
            dict(metadata.get("objective_profile", {}) or {})
            if effective_objective == OBJECTIVE_MODE_FLOOD_EVENT
            else module.OBJECTIVE_PROFILE
        )
        metadata["objective_profile"] = actual_objective_profile
        objective_meta = dict(metadata.get("objective", {}))
        if isinstance(actual_objective_profile, dict):
            for key in ("type", "profile", "label", "summary", "formula", "weights", "diagnostic_only_constraints", "notes"):
                if key in actual_objective_profile:
                    objective_meta[key] = actual_objective_profile[key]
        metadata["objective"] = objective_meta
        metadata["workspace_config"] = to_portable_path(str(config.get("_config_path", "") or ""))
        metadata["rate_mode"] = profile
        data_sources = dict(metadata.get("data_sources", {}))
        runtime_prec_source = str(getattr(module.args, "prec_source", "") or "").strip().lower() or configured_precip_source(config)
        data_sources["prec_source"] = runtime_prec_source
        data_sources["runtime_prec_source"] = runtime_prec_source
        data_sources["configured_precip_source"] = configured_precip_source(config)
        data_sources["station_precip_mode"] = str(dict(config.get("气象策略", {}) or {}).get("降水方案", "grid_only") or "grid_only").strip()
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
    validate_profile_input_contracts(config, profile)
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
    if param_bounds_profile in {
        PARAM_BOUNDS_PROFILE_QTP,
        PARAM_BOUNDS_PROFILE_GENERIC,
        PARAM_BOUNDS_PROFILE_HOURLY,
        PARAM_BOUNDS_PROFILE_HOURLY_LEGACY,
    }:
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
