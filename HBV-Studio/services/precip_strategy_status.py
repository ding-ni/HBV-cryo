#!/usr/bin/env python
# -*- coding: utf-8 -*-
from __future__ import annotations

import hashlib
from collections import OrderedDict
from dataclasses import dataclass
from pathlib import Path
from threading import RLock
from typing import Any, Callable

from services.time_utils import time_step_count_text


@dataclass(frozen=True)
class PrecipStrategyStatusContext:
    meteo_key: str
    meteo_precip_mode_key: str
    current_profile: Callable[[dict[str, Any]], str]
    effective_precip_paths: Callable[..., tuple[Path, Path, str]]
    count_matching: Callable[[Any], int]
    read_json_file: Callable[[Path], dict[str, Any]]


def _fmt_float(value: Any, digits: int = 1, suffix: str = "") -> str:
    try:
        number = float(value)
    except Exception:
        return "未形成"
    if not (number == number):
        return "未形成"
    return f"{number:.{digits}f}{suffix}"


_IDENTITY_CACHE_LOCK = RLock()
_FILE_IDENTITY_CACHE: OrderedDict[tuple[Any, ...], dict[str, Any]] = OrderedDict()
_SERIES_IDENTITY_CACHE: OrderedDict[str, dict[str, Any]] = OrderedDict()


def _file_stat_signature(path: Path) -> tuple[Any, ...]:
    stat = path.stat()
    return (str(path).casefold(), stat.st_size, stat.st_mtime_ns, stat.st_ctime_ns)


def _cached_file_identity(path: Path) -> dict[str, Any]:
    """Read unchanged inputs once, while checking filesystem metadata on every poll."""
    path = Path(path).resolve(strict=False)
    if not path.is_file():
        return {"path": str(path), "available": False}
    signature = _file_stat_signature(path)
    with _IDENTITY_CACHE_LOCK:
        cached = _FILE_IDENTITY_CACHE.get(signature)
        if cached is not None:
            _FILE_IDENTITY_CACHE.move_to_end(signature)
            return dict(cached)
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    if _file_stat_signature(path) != signature:
        raise ValueError("降水输入检查期间文件发生变化，请待文件写入完成后重新检查。")
    result = {"path": str(path), "available": True, "size_bytes": signature[1], "sha256": digest.hexdigest()}
    with _IDENTITY_CACHE_LOCK:
        _FILE_IDENTITY_CACHE[signature] = result
        _FILE_IDENTITY_CACHE.move_to_end(signature)
        while len(_FILE_IDENTITY_CACHE) > 8192:
            _FILE_IDENTITY_CACHE.popitem(last=False)
    return dict(result)


def _cached_series_identity(records: list[tuple[Any, Path]]) -> dict[str, Any]:
    metadata = hashlib.sha256()
    for timestamp, raw_path in records:
        path = Path(raw_path).resolve(strict=False)
        signature = _file_stat_signature(path) if path.is_file() else (str(path).casefold(), "missing")
        metadata.update(repr((timestamp.isoformat(), signature)).encode("utf-8"))
    key = metadata.hexdigest()
    with _IDENTITY_CACHE_LOCK:
        cached = _SERIES_IDENTITY_CACHE.get(key)
        if cached is not None:
            _SERIES_IDENTITY_CACHE.move_to_end(key)
            return dict(cached)
    aggregate = hashlib.sha256()
    count = total_bytes = 0
    missing: list[str] = []
    for timestamp, raw_path in records:
        path = Path(raw_path)
        identity = _cached_file_identity(path)
        if not identity["available"]:
            missing.append(str(path.resolve(strict=False)))
            continue
        count += 1
        total_bytes += identity["size_bytes"]
        aggregate.update(
            f"{timestamp.isoformat()}\0{path.name}\0{identity['size_bytes']}\0{identity['sha256']}\n".encode("utf-8")
        )
    result = {
        "algorithm": "sha256(file_content)+sha256(ordered_series)",
        "file_count": count, "total_bytes": total_bytes, "series_sha256": aggregate.hexdigest(),
        "missing_file_count": len(missing), "missing_file_samples": missing[:5],
    }
    with _IDENTITY_CACHE_LOCK:
        _SERIES_IDENTITY_CACHE[key] = result
        _SERIES_IDENTITY_CACHE.move_to_end(key)
        while len(_SERIES_IDENTITY_CACHE) > 16:
            _SERIES_IDENTITY_CACHE.popitem(last=False)
    return dict(result)


def _same_file_identity(expected: dict[str, Any], current: dict[str, Any]) -> bool:
    from profile_runner import replace_placeholders

    def actual_path(value: Any) -> str:
        text = str(value or "")
        if not text:
            return ""
        expanded = replace_placeholders(text)
        return str(Path(expanded).expanduser().resolve(strict=False)).casefold()

    return (
        actual_path(expected.get("path")) == actual_path(current.get("path"))
        and expected.get("available") == current.get("available")
        and expected.get("size_bytes") == current.get("size_bytes")
        and expected.get("sha256") == current.get("sha256")
    )


def _same_series_identity(expected: dict[str, Any], current: dict[str, Any]) -> bool:
    return all(expected.get(key) == current.get(key) for key in (
        "algorithm", "file_count", "total_bytes", "series_sha256", "missing_file_count",
    ))


def _current_precip_input_error(
    summary: dict[str, Any], algorithm: str, config: dict[str, Any], base_dir: Path,
) -> str:
    # Keep the service import light until an actual versioned product is checked.
    import precipitation_strategy_runner as runner

    meteo = dict(config.get("气象策略", {}) or {})
    provenance = dict(summary.get("provenance", {}) or {})
    if not provenance:
        return "降水结果缺少输入资料身份，不能确认与当前配置一致，请重新执行降水方案。"
    for config_key, identity_key, label in (
        ("站点降水_csv", "station_precipitation_input", "站点降水资料"),
        ("站点信息_csv", "station_metadata_input", "站点信息"),
    ):
        raw = str(meteo.get(config_key, "") or "").strip()
        if not raw:
            return f"当前未设置{label}，请补齐后重新执行降水方案。"
        current = _cached_file_identity(runner.resolve_config_entry_path(config, raw))
        expected = dict(provenance.get(identity_key, {}) or {})
        if not current["available"] or not _same_file_identity(expected, current):
            return f"{label}与生成降水时的输入不一致，请重新训练并执行降水方案。"
    base_dir = Path(base_dir).resolve(strict=False)
    all_records = runner.list_rasters(base_dir)
    expected_index = runner.build_expected_forcing_index(config, context="calibration")
    records, missing, _ = runner.filter_records_to_expected(all_records, expected_index)
    if missing or not records or not _same_series_identity(
        dict(provenance.get("base_precipitation_series", {}) or {}), _cached_series_identity(records),
    ):
        return "当前运行时段或基础降水与生成结果时不一致，请补齐资料并重新执行降水方案。"
    current_manifest = _cached_file_identity(base_dir.parent / "daily_forcing_manifest.json")
    if not _same_file_identity(dict(provenance.get("source_daily_forcing_manifest", {}) or {}), current_manifest):
        return "基础气象的来源记录已变化，请重新执行降水方案。"
    step_hours = runner.normalize_time_step_hours(config.get("时间步长_小时", 24.0))
    if float(summary.get("time_step_hours", 0) or 0) != step_hours:
        return "降水结果的时间尺度与当前项目不一致，请重新执行降水方案。"
    if algorithm != "monthly_transfer_v3":
        return ""
    rules = dict(summary.get("transfer_rules", {}) or {})
    identity = dict(rules.get("identity", {}) or {})
    training_start = meteo.get("station_rule_training_start", meteo.get("station_bias_training_start"))
    training_end = meteo.get("station_rule_training_end", meteo.get("station_bias_training_end"))
    if (
        identity.get("requested_training_start") != str(training_start or "")
        or identity.get("requested_training_end") != str(training_end or "")
    ):
        return "降水规则训练时段已变化，请重新训练并执行降水方案。"
    training_records = runner._filter_rule_training_records(
        all_records, training_start=training_start, training_end=training_end, step_hours=step_hours,
    )
    if not training_records or not _same_series_identity(
        dict(identity.get("base_series", {}) or {}), _cached_series_identity(training_records),
    ):
        return "训练时段的基础降水已变化，请重新训练并执行降水方案。"
    input_files = dict(identity.get("input_files", {}) or {})
    for key in ("station_precipitation_input", "station_metadata_input", "source_daily_forcing_manifest"):
        if not _same_file_identity(dict(input_files.get(key, {}) or {}), dict(provenance.get(key, {}) or {})):
            return "冻结规则与降水结果使用了不同的输入资料，请重新训练并应用。"
    rule_algorithm = dict(identity.get("algorithm", {}) or {})
    if rule_algorithm.get("algorithm") != algorithm or float(rule_algorithm.get("step_hours", 0) or 0) != step_hours:
        return "冻结规则的算法或时间尺度与当前配置不一致，请重新训练并应用。"
    current_implementation = _cached_file_identity(Path(runner.__file__))
    if rule_algorithm.get("implementation_sha256") != current_implementation.get("sha256", "bundled"):
        return "降水算法已更新，请重新训练并执行降水方案。"
    return ""


def versioned_precip_summary_error(
    summary: dict[str, Any], algorithm: str, count: int,
    *, config: dict[str, Any] | None = None, base_dir: Path | None = None,
) -> str:
    """A versioned forcing product needs evidence, not just existing files."""
    if algorithm not in {"monthly_transfer_v3", "occurrence_amount_v2"}:
        return ""
    stats = dict(summary.get("processing_stats", {}) or {})
    if str(stats.get("algorithm", "") or "") != algorithm:
        return "降水结果使用的算法与当前配置不一致，请重新执行降水方案。"
    if bool(stats.get("qc_blocked", False)):
        return "降水质量检查未通过，请处理订正问题后重新生成。"
    if algorithm == "occurrence_amount_v2":
        monthly = dict(stats.get("monthly_conservation", {}) or {})
        if not isinstance(monthly.get("qc_blocked"), bool) or not isinstance(monthly.get("months"), list):
            return "降水结果缺少月量质量检查，复用文件不能视为检查通过，请重新执行降水方案。"
        if bool(monthly["qc_blocked"]) or any(int(monthly.get(key, 0) or 0) > 0 for key in ("high_factor_cell_count", "high_removed_fraction_cell_count", "unresolved_cell_count")):
            return "降水月量质量检查未通过，请重新生成。"
        if config is not None and base_dir is not None:
            return _current_precip_input_error(summary, algorithm, config, base_dir)
        return ""
    quality = dict(stats.get("quality_checks", {}) or {})
    if str(quality.get("status", "") or "") != "passed" or quality.get("qc_blocked") is not False:
        return "统计订正缺少已通过的质量检查，请重新执行降水方案。"
    selected = int(summary.get("selected_steps", 0) or 0)
    if selected <= 0 or count != selected or int(quality.get("checked_steps", 0) or 0) != selected:
        return "统计订正输出数量与已检查的目标时段不一致，请重新生成。"
    if int(summary.get("missing_expected_steps", 0) or 0) > 0:
        return "统计订正缺少目标时段的基础降水，请补齐连续气象输入。"
    rules = dict(summary.get("transfer_rules", {}) or {})
    if str(rules.get("schema", "") or "") != "station_bias_monthly_transfer_rules_v3" or not rules.get("available"):
        return "统计订正缺少冻结月规则，请重新训练并应用。"
    rule_quality = dict(rules.get("quality_checks", {}) or {})
    if rule_quality.get("status") != "passed" or rule_quality.get("qc_blocked") is not False:
        return "冻结月规则尚未通过质量检查，请检查训练样本。"
    if not rules.get("identity_sha256") or stats.get("rules_identity_sha256") != rules.get("identity_sha256"):
        return "统计订正结果与冻结规则的身份不一致，请重新生成。"
    if config is not None and base_dir is not None:
        return _current_precip_input_error(summary, algorithm, config, base_dir)
    return ""


def _hydro_diagnostic_message(summary: dict[str, Any]) -> list[str]:
    hydro = dict(summary.get("hydrological_diagnostics", {}) or {})
    parts: list[str] = []
    stats = dict(summary.get("processing_stats", {}) or {})
    step_hours = float(summary.get("time_step_hours", 24.0) or 24.0)
    if stats:
        algorithm = str(stats.get("algorithm", "") or "").strip()
        if algorithm:
            parts.append(f"站点订正算法：{algorithm}")
        station_steps = int(stats.get("direct_station_corrected_steps", 0) or 0)
        rule_steps = int(stats.get("transfer_rule_applied_steps", 0) or 0)
        pass_steps = int(stats.get("pass_through_steps", 0) or 0)
        skipped_steps = int(stats.get("skipped_existing_steps", 0) or 0)
        if algorithm == "monthly_transfer_v3":
            parts.append(
                "统一月规则应用："
                f"{time_step_count_text(rule_steps, step_hours)}；"
                f"无样本月份保留原场 {time_step_count_text(pass_steps, step_hours)}（未经该季节实测验证）"
            )
            parts.append("发生频率：本方案仅订正量级，保留格点降水发生序列")
        elif station_steps or rule_steps or pass_steps or skipped_steps:
            parts.append(
                "订正执行："
                f"实测站点参与 {time_step_count_text(station_steps, step_hours)}；"
                f"规则外推 {time_step_count_text(rule_steps, step_hours)}；"
                f"原样保留 {time_step_count_text(pass_steps, step_hours)}；"
                f"已有输出复用 {time_step_count_text(skipped_steps, step_hours)}"
            )
    elevation_support = dict(summary.get("station_elevation_support", {}) or {})
    elevation_status = str(elevation_support.get("status", "") or "")
    if elevation_status in {"high_zone_unsupported", "high_zone_sparsely_supported", "supported"}:
        parts.append(
            "站点高程覆盖："
            f"阈值 {_fmt_float(elevation_support.get('threshold_m'), 0, ' m')}；"
            f"高区站 {int(elevation_support.get('high_zone_station_count', 0) or 0)}/"
            f"{int(elevation_support.get('valid_elevation_count', 0) or 0)}；"
            f"状态 {elevation_status}"
        )
    rules = dict(summary.get("transfer_rules", {}) or {})
    if rules:
        if bool(rules.get("available", False)):
            month_count = sum(
                1
                for item in dict(rules.get("monthly", {}) or {}).values()
                if int(dict(item).get("training_days", 0) or 0) > 0
            )
            parts.append(
                "站点订正规则："
                f"订正样本日 {int(rules.get('training_days', 0) or 0)}；"
                f"有效站点样本 {int(rules.get('valid_station_samples', 0) or 0)}；"
                f"独立月规则 {month_count}/12；"
                f"平均倍率 {_fmt_float(rules.get('global_ratio_mean'), 2)}"
            )
            unsupported = list(rules.get("unverified_months", []) or [])
            if unsupported:
                parts.append("无训练支持月份：" + "、".join(str(month) for month in unsupported))
        elif str(rules.get("status", "") or "") not in {"", "not_requested"}:
            parts.append(f"站点订正规则：未形成（{rules.get('status')}）")
    if not hydro:
        return parts
    available = hydro.get("station_day_samples_available")
    total = hydro.get("station_day_samples_total")
    missing_rate = hydro.get("station_day_missing_rate_percent")
    if total:
        parts.append(f"站点日样本：{available}/{total}，缺测率 {_fmt_float(missing_rate, 1, '%')}")
    before = dict(hydro.get("station_point_before", {}) or {})
    after = dict(hydro.get("station_point_after", {}) or {})
    if before.get("sample_count") and after.get("sample_count"):
        parts.append(
            "站点处MAE："
            f"{_fmt_float(before.get('mae_mm'), 2, ' mm')}→{_fmt_float(after.get('mae_mm'), 2, ' mm')}；"
            "PBIAS："
            f"{_fmt_float(before.get('pbias_percent'), 1, '%')}→{_fmt_float(after.get('pbias_percent'), 1, '%')}"
        )
    basin_before = hydro.get("basin_precip_total_before_mm")
    basin_after = hydro.get("basin_precip_total_after_mm")
    basin_change = hydro.get("basin_precip_total_change_percent")
    if basin_before is not None and basin_after is not None:
        parts.append(
            "流域面降水总量："
            f"{_fmt_float(basin_before, 1, ' mm')}→{_fmt_float(basin_after, 1, ' mm')}"
            f"（{_fmt_float(basin_change, 1, '%')}）"
        )
    factor = hydro.get("correction_factor_mean")
    if factor is not None:
        parts.append(f"平均订正倍率：{_fmt_float(factor, 2)}")
    clipped = int(hydro.get("ratio_clip_step_count", 0) or 0)
    repaired = int(hydro.get("grid_missed_precip_repair_step_count", 0) or 0)
    if clipped or repaired:
        parts.append(f"倍率裁剪日：{clipped}；格点漏报修复日：{repaired}")
    note = str(hydro.get("hydrological_time_basis_note", "") or "").strip()
    if note:
        parts.append(f"时间口径：{note}")
    return parts


def check_precip_strategy_outputs(
    config: dict[str, Any],
    context: PrecipStrategyStatusContext,
    precip_source: Any = None,
) -> tuple[bool, str, int]:
    meteo = dict(config.get(context.meteo_key, {}))
    mode = str(meteo.get(context.meteo_precip_mode_key, "grid_only")).strip()
    profile = context.current_profile(config)
    base_dir, corrected_dir, selected_source = context.effective_precip_paths(
        config,
        profile,
        precip_source=precip_source,
    )
    if mode == "grid_only":
        count = context.count_matching(base_dir)
        label = (
            "当前为本地栅格基线方案，不需要额外订正。"
            if selected_source == "custom_tif"
            else "当前为格点基线方案，不需要额外订正。"
        )
        return count > 0, label, count

    count = context.count_matching(corrected_dir)
    algorithm = str(meteo.get("station_correction_algorithm", "") or "").strip().lower()
    label = "站点订正降水" if mode == "grid_plus_station_bias" else "泰森插值降水"
    summary_path = Path(corrected_dir) / "precipitation_strategy_summary.json"
    if summary_path.exists():
        try:
            summary = context.read_json_file(summary_path)
            time_basis_label = str(summary.get("time_basis_label", "") or "").strip()
            selected_steps = int(summary.get("selected_steps", 0) or 0)
            written_files = int(summary.get("written_files", 0) or 0)
            step_hours = float(summary.get("time_step_hours", 24.0) or 24.0)
            actual_period = str(summary.get("actual_period", "") or "").strip()
            zero_steps = int(summary.get("zero_available_station_steps", 0) or 0)
            skipped_steps = int(summary.get("skipped_out_of_scope_steps", 0) or 0)
            parts = [
                f"{label}：{actual_period}"
                if actual_period
                else f"{label}旧结果仅记录 {time_step_count_text(count, step_hours)}，未记录起止时间"
            ]
            processing_stats = dict(summary.get("processing_stats", {}) or {})
            evidence_error = versioned_precip_summary_error(
                summary, algorithm, count, config=config, base_dir=base_dir,
            ) if mode == "grid_plus_station_bias" else ""
            qc_blocked = bool(processing_stats.get("qc_blocked", False)) or bool(evidence_error)
            if time_basis_label:
                parts.append(f"资料口径：{time_basis_label}")
            if selected_steps or written_files:
                parts.append(
                    f"参与订正 {time_step_count_text(written_files or selected_steps, step_hours)}"
                    f"（目标 {time_step_count_text(selected_steps or count, step_hours)}）"
                )
            if zero_steps:
                if algorithm == "monthly_transfer_v3":
                    parts.append(f"缺同期站点观测：{time_step_count_text(zero_steps, step_hours)}；按冻结月规则处理")
                else:
                    parts.append(f"无可用站点并保留原场：{time_step_count_text(zero_steps, step_hours)}")
            if skipped_steps:
                parts.append(f"已忽略资料口径外：{time_step_count_text(skipped_steps, step_hours)}")
            parts.extend(_hydro_diagnostic_message(summary))
            if qc_blocked:
                if evidence_error:
                    parts.append(evidence_error)
                monthly = dict(processing_stats.get("monthly_conservation", {}) or {})
                integrity = dict(processing_stats.get("station_series_integrity", {}) or {})
                monthly_failure_count = sum(
                    int(monthly.get(key, 0) or 0)
                    for key in (
                        "high_factor_cell_count",
                        "high_removed_fraction_cell_count",
                        "unresolved_cell_count",
                    )
                )
                if bool(monthly.get("qc_blocked", False)) or monthly_failure_count > 0:
                    parts.append(
                        "月量守恒质量检查未通过："
                        f"高倍率像元 {int(monthly.get('high_factor_cell_count', 0) or 0)}；"
                        f"移除比例超限像元 {int(monthly.get('high_removed_fraction_cell_count', 0) or 0)}；"
                        f"未分配像元 {int(monthly.get('unresolved_cell_count', 0) or 0)}"
                    )
                if bool(integrity.get("qc_blocked", False)):
                    samples = [
                        f"{item.get('station_a')}/{item.get('station_b')}"
                        for item in list(integrity.get("duplicate_pairs", []) or [])[:3]
                    ]
                    parts.append(
                        f"站点序列独立性检查未通过：异站同序列 {int(integrity.get('duplicate_pair_count', 0) or 0)} 对"
                        + (f"（{'、'.join(samples)}）" if samples else "")
                    )
            return count > 0 and not qc_blocked, "；".join(parts), count
        except Exception as exc:
            if mode == "grid_plus_station_bias" and algorithm in {"monthly_transfer_v3", "occurrence_amount_v2"}:
                return False, f"站点订正质量摘要无法读取：{exc}；请重新执行降水方案。", count
    if mode == "grid_plus_station_bias" and algorithm in {"monthly_transfer_v3", "occurrence_amount_v2"}:
        return False, "站点订正缺少质量摘要，已有栅格不能视为完成，请重新执行降水方案。", count
    return count > 0, f"{label}旧结果仅记录 {count} 个栅格，未记录起止时间，请重新生成摘要", count
