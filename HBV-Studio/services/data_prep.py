#!/usr/bin/env python
# -*- coding: utf-8 -*-
from __future__ import annotations

import subprocess
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable


@dataclass(frozen=True)
class DataPrepContext:
    load_workspace_config: Callable[[str], tuple[Path, dict[str, Any]]]
    current_profile: Callable[[dict[str, Any]], str]
    data_prep_steps: Callable[[str], list[dict[str, Any]]]
    resolve_data_prep_step: Callable[[dict[str, Any], dict[str, Any] | None], dict[str, Any]]
    resolve_precip_source: Callable[[dict[str, Any], Any], str]
    find_running_task: Callable[[str, str], Any]
    profile_daily: str


@dataclass(frozen=True)
class DataPrepStepCatalogContext:
    data_prep_dir: Path
    gui_root: Path
    profile_daily: str
    check_clip_dem: Callable[..., tuple[bool, str, int]]
    check_flow_acc: Callable[..., tuple[bool, str, int]]
    check_masked_flow: Callable[..., tuple[bool, str, int]]
    check_elevation_zone: Callable[..., tuple[bool, str, int]]
    check_daily_era5_download: Callable[..., tuple[bool, str, int]]
    check_daily_era5_processed: Callable[..., tuple[bool, str, int]]
    check_daily_prec: Callable[..., tuple[bool, str, int]]
    check_station_precip_strategy: Callable[..., tuple[bool, str, int]]
    check_daily_aligned: Callable[..., tuple[bool, str, int]]
    check_precip_strategy_outputs: Callable[..., tuple[bool, str, int]]
    check_glacier_mask: Callable[..., tuple[bool, str, int]]
    check_glacier_elev: Callable[..., tuple[bool, str, int]]
    check_glacier_reference: Callable[..., tuple[bool, str, int]]
    check_daily_inputs_ready: Callable[..., tuple[bool, str, int]]
    check_hourly_era5_download: Callable[..., tuple[bool, str, int]]
    check_hourly_temp_evap: Callable[..., tuple[bool, str, int]]
    check_hourly_prec: Callable[..., tuple[bool, str, int]]
    check_hourly_aligned: Callable[..., tuple[bool, str, int]]
    check_hourly_inputs_ready: Callable[..., tuple[bool, str, int]]


@dataclass(frozen=True)
class DataPrepTaskOutputContext:
    resolve_path: Callable[..., Path]
    read_runtime_config: Callable[[Path], dict[str, Any]]
    task_step_map: Callable[[str, dict[str, Any]], dict[str, dict[str, Any]]]
    current_profile: Callable[[dict[str, Any]], str]
    resolve_runtime_precip_source: Callable[[dict[str, Any], Any], str]


@dataclass(frozen=True)
class DataPrepStartContext:
    resolve_path: Callable[..., Path]
    read_runtime_config: Callable[[Path], dict[str, Any]]
    task_step_map: Callable[[str, dict[str, Any]], dict[str, dict[str, Any]]]
    current_profile: Callable[[dict[str, Any]], str]
    resolve_runtime_precip_source: Callable[[dict[str, Any], Any], str]
    resolve_legacy_precip_source: Callable[[str], str]
    data_prep_status: Callable[[str, Any], list[dict[str, Any]]]
    build_python_script_command: Callable[..., list[str]]
    clear_meteo_state: Callable[..., None]
    forcing_pipeline_step_ids: frozenset[str]


@dataclass(frozen=True)
class DataPrepWorkflowWorkerContext:
    read_runtime_config: Callable[[Path], dict[str, Any]]
    resolve_runtime_precip_source: Callable[[dict[str, Any], Any], str]
    task_step_map: Callable[[str, dict[str, Any]], dict[str, dict[str, Any]]]
    current_profile: Callable[[dict[str, Any]], str]
    data_prep_status: Callable[..., list[dict[str, Any]]]
    step_command: Callable[[dict[str, Any], Path, dict[str, Any]], list[str]]
    verify_step_output: Callable[[dict[str, Any], dict[str, Any], Any], tuple[bool, str]]
    clear_meteo_state: Callable[..., None]
    add_task_output: Callable[[str, str], None]
    set_task_metadata: Callable[..., None]
    mark_task_finished: Callable[..., None]
    popen: Callable[..., Any]
    subprocess_env: Callable[[], dict[str, str]]
    decode_subprocess_output_line: Callable[[Any], str]
    project_root: Path
    forcing_pipeline_step_ids: frozenset[str]
    max_workers: int = 4


@dataclass(frozen=True)
class DataPrepBootstrapContext:
    resolve_path: Callable[..., Path]
    read_runtime_config: Callable[[Path], dict[str, Any]]
    task_step_map: Callable[[str, dict[str, Any]], dict[str, dict[str, Any]]]
    current_profile: Callable[[dict[str, Any]], str]
    glacier_elev_required: Callable[[dict[str, Any]], bool]


@dataclass(frozen=True)
class DataPrepStartPlan:
    label: str
    command: list[str]
    metadata: dict[str, Any]


@dataclass(frozen=True)
class DataPrepBootstrapPlan:
    label: str
    command: list[str]
    metadata: dict[str, Any]
    config_path: Path
    step_ids: list[str]


@dataclass(frozen=True)
class DataPrepWorkflowDecision:
    ready: list[str]
    skipped_done: list[str]
    skipped_manual: list[str]
    blocked: list[str]
    completed_ids: set[str]
    remaining: list[str]


def data_prep_steps_payload(config_path_raw: str, context: DataPrepContext) -> list[dict[str, Any]]:
    profile = context.profile_daily
    config = None
    if config_path_raw:
        _, config = context.load_workspace_config(config_path_raw)
        profile = context.current_profile(config)
    return [
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
        for step in (
            context.resolve_data_prep_step(item, config)
            for item in context.data_prep_steps(profile)
        )
    ]


def data_prep_steps(profile: str, context: DataPrepStepCatalogContext) -> list[dict[str, Any]]:
    common = [
        {
            "id": "clip_dem",
            "title": "1. 裁剪 DEM",
            "description": "根据流域边界 shp 把内置或外部 DEM 裁剪到当前运行目录。",
            "script": context.data_prep_dir / "01_裁剪DEM.py",
            "depends_on": [],
            "check": context.check_clip_dem,
        },
        {
            "id": "flow_acc",
            "title": "2. 生成流向与流量累积",
            "description": "为当前 DEM 生成流向与流量累积栅格。",
            "script": context.data_prep_dir / "02_生成流向流量累积.py",
            "depends_on": ["clip_dem"],
            "check": context.check_flow_acc,
        },
        {
            "id": "masked_flow",
            "title": "3. 生成汇流与流域掩膜",
            "description": "生成流域范围内的流量累积栅格与汇流掩膜。",
            "script": context.data_prep_dir / "12_生成汇流与流域掩膜.py",
            "depends_on": ["flow_acc"],
            "check": context.check_masked_flow,
        },
        {
            "id": "elevation_zone",
            "title": "4. 生成高程分区",
            "description": "基于 DEM 和阈值生成低/高高程区栅格。",
            "script": context.data_prep_dir / "03_生成高程分区.py",
            "depends_on": ["clip_dem"],
            "check": context.check_elevation_zone,
        },
    ]
    if profile == context.profile_daily:
        common.extend(
            [
                {
                    "id": "download_era5",
                    "title": "5. 下载 ERA5 变量",
                    "description": "按当前配置下载 ERA5 降水、气温或 FAO56 所需变量；MSWEP/CMFD 不在此步自动下载。",
                    "script": context.data_prep_dir / "05_下载ERA5和FAO56变量.py",
                    "depends_on": [],
                    "check": context.check_daily_era5_download,
                },
                {
                    "id": "process_era5",
                    "title": "6. 生成日尺度结果",
                    "description": "按当前配置生成日尺度气温或潜在蒸散发。",
                    "script": context.data_prep_dir / "06_处理ERA5温度和蒸散发.py",
                    "depends_on": ["download_era5"],
                    "check": context.check_daily_era5_processed,
                    "supports_overwrite": True,
                },
                {
                    "id": "process_prec",
                    "title": "7. 处理日尺度降水",
                    "description": "处理 ERA5 自动下载降水，或处理已放入原始目录的 MSWEP/CMFD 降水数据。",
                    "script": context.data_prep_dir / "07_处理降水数据.py",
                    "depends_on": [],
                    "check": context.check_daily_prec,
                    "needs_prec_source": True,
                    "supports_overwrite": True,
                },
                {
                    "id": "station_precip_strategy",
                    "title": "8. 站点降水资料分析（按方案）",
                    "description": "当降水方案不是“格点直接使用”时，检查站点匹配、时间覆盖、缺测和异常值。",
                    "depends_on": ["process_prec"],
                    "check": context.check_station_precip_strategy,
                    "manual": True,
                },
                {
                    "id": "align_inputs",
                    "title": "9. 对齐并裁剪日尺度气象",
                    "description": "将降水、温度、蒸散统一到 DEM 网格并裁剪到流域内。",
                    "script": context.data_prep_dir / "08_对齐并裁剪气象数据.py",
                    "depends_on": ["clip_dem", "process_era5", "process_prec", "station_precip_strategy"],
                    "check": context.check_daily_aligned,
                    "needs_prec_source": True,
                    "supports_overwrite": True,
                },
                {
                    "id": "apply_precip_strategy",
                    "title": "10. 执行降水方案（格点 / 订正 / 泰森）",
                    "description": "根据气象策略生成最终用于率定的降水栅格目录。",
                    "script": context.gui_root / "precipitation_strategy_runner.py",
                    "depends_on": ["align_inputs", "station_precip_strategy"],
                    "check": context.check_precip_strategy_outputs,
                    "needs_prec_source": True,
                },
                {
                    "id": "glacier_mask",
                    "title": "11. 生成冰川掩膜（可选）",
                    "description": "如配置了冰川边界 shp，则按 DEM 分辨率生成冰川表达结果：1km 生成二值掩膜，0.1° 生成分数栅格并附带兼容掩膜。",
                    "script": context.data_prep_dir / "09_生成冰川掩膜.py",
                    "depends_on": ["clip_dem"],
                    "check": context.check_glacier_mask,
                    "optional": True,
                },
                {
                    "id": "glacier_elev",
                    "title": "11.5 生成冰川高程栅格（0.1° 专用，可选）",
                    "description": "从高分辨率 1km DEM 提取每个 0.1° 像元内冰川区的面积加权平均高程，用于率定时的冰川子格温度递减修正。1km 方案无需此步；0.1° 方案未做此步将在率定结果标记 reliability_flag=degraded。",
                    "script": context.data_prep_dir / "11_生成冰川高程栅格.py",
                    "depends_on": ["glacier_mask"],
                    "check": context.check_glacier_elev,
                    "optional": True,
                },
                {
                    "id": "glacier_melt",
                    "title": "12. 生成冰川工程先验序列（可选）",
                    "description": "生成冰川参考栅格序列，用于与模拟冰融水过程进行对照复核。",
                    "script": context.data_prep_dir / "10_生成冰川融水.py",
                    "depends_on": ["glacier_mask"],
                    "check": context.check_glacier_reference,
                    "optional": True,
                },
                {
                    "id": "check_inputs",
                    "title": "13. 输入完整性检查",
                    "description": "检查当前日尺度输入是否齐全，可用于率定前复核。",
                    "script": context.data_prep_dir / "13_输入完整性检查.py",
                    "depends_on": ["apply_precip_strategy"],
                    "check": context.check_daily_inputs_ready,
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
                "check": context.check_hourly_era5_download,
                "script": context.data_prep_dir / "05b_下载ERA5小时变量.py",
            },
            {
                "id": "process_hourly_era5",
                "title": "6. 处理小时温度与蒸散",
                "description": "生成小时温度栅格，并把 ERA5 驱动的日 ET0 分配到小时尺度。",
                "depends_on": ["download_hourly_era5"],
                "check": context.check_hourly_temp_evap,
                "script": context.data_prep_dir / "06b_处理ERA5小时温度和蒸散发.py",
                "supports_overwrite": True,
            },
            {
                "id": "process_hourly_prec",
                "title": "7. 处理小时降水",
                "description": "处理 ERA5 小时降水，或把本地小时降水栅格标准化到工程原始降水目录。",
                "depends_on": [],
                "check": context.check_hourly_prec,
                "needs_prec_source": True,
                "script": context.data_prep_dir / "07b_处理小时降水数据.py",
                "supports_overwrite": True,
            },
            {
                "id": "station_precip_strategy",
                "title": "8. 小时尺度站点降水资料分析（按方案）",
                "description": "当降水方案不是“格点直接使用”时，检查小时项目的站点匹配、时间覆盖、缺测和异常值。",
                "depends_on": ["process_hourly_prec"],
                "check": context.check_station_precip_strategy,
                "manual": True,
            },
            {
                "id": "align_hourly_inputs",
                "title": "9. 对齐并裁剪小时气象",
                "description": "将小时降水、温度、蒸散对齐到 DEM 网格并裁剪到流域内。",
                "depends_on": ["clip_dem", "process_hourly_era5", "process_hourly_prec"],
                "check": context.check_hourly_aligned,
                "needs_prec_source": True,
                "script": context.data_prep_dir / "08b_对齐并裁剪小时气象数据.py",
                "supports_overwrite": True,
            },
            {
                "id": "apply_precip_strategy",
                "title": "10. 执行小时降水方案（格点 / 订正 / 泰森）",
                "description": "根据气象策略生成最终用于小时率定的降水栅格目录。",
                "depends_on": ["align_hourly_inputs", "station_precip_strategy"],
                "check": context.check_precip_strategy_outputs,
                "needs_prec_source": True,
                "script": context.gui_root / "precipitation_strategy_runner.py",
            },
            {
                "id": "glacier_mask",
                "title": "11. 生成冰川掩膜（可选）",
                "description": "如配置了冰川边界 shp，则按 DEM 分辨率生成冰川表达结果：1km 生成二值掩膜，0.1° 生成分数栅格并附带兼容掩膜。",
                "script": context.data_prep_dir / "09_生成冰川掩膜.py",
                "depends_on": ["clip_dem"],
                "check": context.check_glacier_mask,
                "optional": True,
            },
            {
                "id": "glacier_elev",
                "title": "11.5 生成冰川高程栅格（0.1° 专用，可选）",
                "description": "从高分辨率 1km DEM 提取每个 0.1° 像元内冰川区的面积加权平均高程，用于率定时的冰川子格温度递减修正。1km 方案无需此步；0.1° 方案未做此步将在率定结果标记 reliability_flag=degraded。",
                "script": context.data_prep_dir / "11_生成冰川高程栅格.py",
                "depends_on": ["glacier_mask"],
                "check": context.check_glacier_elev,
                "optional": True,
            },
            {
                "id": "stage_hourly_glacier_reference",
                "title": "12. 导入小时尺度冰川工程先验（可选）",
                "description": "将小时尺度冰川参考栅格放入工程目录，用于与模拟冰融水过程进行对照复核。",
                "depends_on": ["glacier_mask"],
                "check": context.check_glacier_reference,
                "optional": True,
                "manual": True,
            },
            {
                "id": "check_inputs",
                "title": "13. 小时输入完整性检查",
                "description": "检查小时尺度气象驱动与基础 GIS 是否齐全。",
                "depends_on": ["apply_precip_strategy"],
                "check": context.check_hourly_inputs_ready,
                "script": context.data_prep_dir / "13b_小时输入完整性检查.py",
                "needs_prec_source": True,
            },
        ]
    )
    return common


def resolve_data_prep_step(
    step: dict[str, Any],
    config: dict[str, Any] | None = None,
    *,
    glacier_elev_required: Callable[[dict[str, Any]], bool] | None = None,
) -> dict[str, Any]:
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
    elif resolved.get("id") == "glacier_elev" and glacier_elev_required is not None and glacier_elev_required(config):
        resolved["title"] = str(resolved.get("title", "")).replace("（0.1° 专用，可选）", "（0.1° 专用）")
        resolved["description"] = (
            "从高分辨率 1km DEM 提取每个 0.1° 像元内冰川区的面积加权平均高程，"
            "用于率定时的冰川子格温度递减修正。当前工作区为 0.1° 且已启用冰川，此步为必做；"
            "未做此步将在率定结果标记 reliability_flag=degraded。"
        )
        resolved["optional"] = False
    return resolved


def data_prep_status(
    config_path_raw: str,
    context: DataPrepContext,
    precip_source: Any = None,
) -> list[dict[str, Any]]:
    cfg_path, config = context.load_workspace_config(config_path_raw)
    runtime_prec_source = context.resolve_precip_source(config, precip_source)
    steps = [
        context.resolve_data_prep_step(step, config)
        for step in context.data_prep_steps(context.current_profile(config))
    ]
    active_task = context.find_running_task("data_prep", str(cfg_path))
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


def verify_data_prep_task_output(
    metadata: dict[str, Any],
    context: DataPrepTaskOutputContext,
) -> tuple[bool, str]:
    config_path_raw = str(metadata.get("config_path", "")).strip()
    step_id = str(metadata.get("step_id", "")).strip()
    if not config_path_raw or not step_id:
        return True, "缺少步骤产物检查上下文。"
    try:
        config_path = context.resolve_path(config_path_raw, must_exist=True)
        config = context.read_runtime_config(config_path)
        steps = context.task_step_map(context.current_profile(config), config)
        step = steps.get(step_id)
        if step is None:
            return True, f"未知步骤 {step_id}，跳过产物复核。"
        runtime_prec_source = context.resolve_runtime_precip_source(
            config,
            metadata.get("runtime_prec_source", None),
        )
        return verify_data_prep_step_output(step, config, runtime_prec_source)
    except Exception as exc:
        return False, f"产物检查准备失败：{exc}"


def data_prep_step_command(
    step: dict[str, Any],
    config_path: Path,
    payload: dict[str, Any],
    context: DataPrepStartContext,
) -> list[str]:
    command = context.build_python_script_command(step["script"], "--配置", str(config_path))
    if step.get("needs_prec_source"):
        config = context.read_runtime_config(config_path)
        runtime_prec_source = context.resolve_runtime_precip_source(config, payload.get("prec_source", None))
        command.extend(
            [
                "--降水源",
                runtime_prec_source
                if runtime_prec_source in {"era5", "custom_tif"}
                else context.resolve_legacy_precip_source(runtime_prec_source),
            ]
        )
    if step.get("supports_overwrite") and bool(payload.get("overwrite", False)):
        command.append("--覆盖")
    return command


def data_prep_start_plan(payload: dict[str, Any], context: DataPrepStartContext) -> DataPrepStartPlan:
    config_path = context.resolve_path(str(payload.get("config_path", "")), must_exist=True)
    config = context.read_runtime_config(config_path)
    runtime_prec_source = context.resolve_runtime_precip_source(config, payload.get("prec_source", None))
    profile = context.current_profile(config)
    steps = context.task_step_map(profile, config)
    step_id = str(payload.get("step_id", "")).strip()
    if step_id not in steps:
        raise ValueError(f"未知的数据准备步骤：{step_id}")
    step = steps[step_id]
    if step.get("manual"):
        raise ValueError("这个步骤是手动导入步骤，不支持直接启动脚本。")

    status_map = {item["id"]: item for item in context.data_prep_status(str(config_path), runtime_prec_source)}
    blocked_by = list(status_map.get(step_id, {}).get("blocked_by", []) or [])
    if blocked_by:
        titles = [steps[item]["title"] for item in blocked_by if item in steps]
        raise ValueError(f"步骤前置依赖未完成：{', '.join(titles)}")
    if step_id in context.forcing_pipeline_step_ids:
        context.clear_meteo_state(config)

    metadata = {
        "config_path": str(config_path.resolve()),
        "profile": profile,
        "runtime_prec_source": runtime_prec_source,
        "step_id": step_id,
        "step_title": step["title"],
        "step_titles": [step["title"]],
        "ui_progress": {"stage": "执行脚本", "current": 0, "total": 1, "label": step["title"]},
    }
    return DataPrepStartPlan(
        label=f"数据准备 | {step['title']} | {config_path.stem}",
        command=data_prep_step_command(step, config_path, payload, context),
        metadata=metadata,
    )


def data_prep_bootstrap_plan(payload: dict[str, Any], context: DataPrepBootstrapContext) -> DataPrepBootstrapPlan:
    config_path = context.resolve_path(str(payload.get("config_path", "")), must_exist=True)
    config = context.read_runtime_config(config_path)
    profile = context.current_profile(config)
    step_ids = ["clip_dem", "flow_acc", "masked_flow", "elevation_zone"]
    if str(config.get("冰川边界_shp", "")).strip():
        step_ids.append("glacier_mask")
    if context.glacier_elev_required(config):
        step_ids.append("glacier_elev")
    steps = context.task_step_map(profile, config)
    metadata = {
        "config_path": str(config_path.resolve()),
        "profile": profile,
        "step_titles": [steps[item]["title"] for item in step_ids if item in steps],
        "ui_progress": {"stage": "准备执行", "current": 0, "total": len(step_ids), "label": "等待前置条件"},
    }
    return DataPrepBootstrapPlan(
        label=f"基础地理数据生成 | {config_path.stem}",
        command=["bootstrap"],
        metadata=metadata,
        config_path=config_path,
        step_ids=step_ids,
    )


def data_prep_workflow_decision(
    remaining: list[str],
    completed_ids: set[str],
    steps: dict[str, dict[str, Any]],
    status_map: dict[str, dict[str, Any]],
    *,
    overwrite: bool = False,
) -> DataPrepWorkflowDecision:
    completed = set(completed_ids)
    ready: list[str] = []
    skipped_done: list[str] = []
    skipped_manual: list[str] = []
    blocked: list[str] = []

    for sid in remaining:
        step = steps[sid]
        if status_map.get(sid, {}).get("done") and not overwrite:
            skipped_done.append(sid)
            completed.add(sid)
            continue
        deps = step.get("depends_on", [])
        unmet = [dep for dep in deps if dep not in completed]
        if unmet:
            blocked.append(sid)
        elif step.get("manual"):
            skipped_manual.append(sid)
            completed.add(sid)
        else:
            ready.append(sid)

    return DataPrepWorkflowDecision(
        ready=ready,
        skipped_done=skipped_done,
        skipped_manual=skipped_manual,
        blocked=blocked,
        completed_ids=completed,
        remaining=[sid for sid in remaining if sid not in completed],
    )


def data_prep_workflow_worker_run(
    task_id: str,
    config_path: Path,
    step_ids: list[str],
    payload: dict[str, Any],
    context: DataPrepWorkflowWorkerContext,
) -> None:
    config = context.read_runtime_config(config_path)
    runtime_prec_source = context.resolve_runtime_precip_source(config, payload.get("prec_source", None))
    steps = context.task_step_map(context.current_profile(config), config)
    completed_ids: set[str] = set()
    total_steps = len(step_ids)

    def update_ui_progress(stage: str, label: str = "", current: int | None = None) -> None:
        context.set_task_metadata(
            task_id,
            ui_progress={
                "stage": stage,
                "current": int(len(completed_ids) if current is None else current),
                "total": int(total_steps),
                "label": label,
            },
        )

    def run_step(step_id: str) -> tuple[str, bool]:
        step = steps[step_id]
        update_ui_progress("正在执行", step["title"])
        context.add_task_output(task_id, f"[运行] {step['title']}")
        if step_id in context.forcing_pipeline_step_ids:
            context.clear_meteo_state(config, context.current_profile(config))
        proc = context.popen(
            context.step_command(step, config_path, payload),
            cwd=str(context.project_root),
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            bufsize=0,
            env=context.subprocess_env(),
        )
        if proc.stdout:
            for raw_line in proc.stdout:
                context.add_task_output(task_id, context.decode_subprocess_output_line(raw_line))
        rc = proc.wait()
        if rc != 0:
            context.add_task_output(task_id, f"[失败] {step['title']} 返回码 {rc}")
            update_ui_progress("执行失败", step["title"])
            return step_id, False
        output_ok, output_message = context.verify_step_output(step, config, runtime_prec_source)
        if not output_ok:
            context.add_task_output(task_id, f"[失败] {step['title']} 产物检查未通过：{output_message}")
            update_ui_progress("产物检查失败", step["title"])
            return step_id, False
        context.add_task_output(task_id, f"[完成] {step['title']}")
        return step_id, True

    try:
        update_ui_progress("准备执行", "等待前置条件")
        remaining = list(step_ids)
        while remaining:
            status_map = {
                item["id"]: item
                for item in context.data_prep_status(str(config_path), precip_source=runtime_prec_source)
            }
            decision = data_prep_workflow_decision(
                remaining,
                completed_ids,
                steps,
                status_map,
                overwrite=bool(payload.get("overwrite", False)),
            )
            for sid in decision.skipped_done:
                context.add_task_output(task_id, f"[跳过] {steps[sid]['title']} 已完成")
                update_ui_progress("跳过已完成", steps[sid]["title"])
            for sid in decision.skipped_manual:
                context.add_task_output(task_id, f"[跳过] {steps[sid]['title']} (手动步骤)")
                update_ui_progress("跳过手动步骤", steps[sid]["title"])
            completed_ids = set(decision.completed_ids)
            remaining = list(decision.remaining)
            ready = list(decision.ready)
            blocked = list(decision.blocked)
            if not ready:
                if blocked:
                    titles = [steps[s]["title"] for s in blocked]
                    context.add_task_output(task_id, f"[阻塞] 以下步骤依赖未完成：{', '.join(titles)}")
                    update_ui_progress("依赖未满足", "、".join(titles))
                break

            if len(ready) > 1:
                context.add_task_output(task_id, f"[并行] 同时执行 {len(ready)} 个步骤")
                update_ui_progress("并行执行", f"{len(ready)} 个步骤")
            with ThreadPoolExecutor(max_workers=min(len(ready), context.max_workers)) as pool:
                futures = {pool.submit(run_step, sid): sid for sid in ready}
                for future in as_completed(futures):
                    sid, ok = future.result()
                    if ok:
                        completed_ids.add(sid)
                        update_ui_progress("已完成阶段", steps[sid]["title"])
                    else:
                        context.mark_task_finished(task_id, ok=False, return_code=1)
                        return
            remaining = [sid for sid in remaining if sid not in completed_ids]

        context.mark_task_finished(task_id, ok=True, return_code=0)
        update_ui_progress("全部完成", "所有步骤已完成", total_steps)
    except Exception as exc:
        context.add_task_output(task_id, f"[HBV-Studio] {exc}")
        context.mark_task_finished(task_id, ok=False, return_code=-1)
        update_ui_progress("执行异常", str(exc))
