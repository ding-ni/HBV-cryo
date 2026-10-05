# -*- coding: utf-8 -*-
"""统一 ERA5/ERA5-Land 输入质量审计。

该模块位于所有聚合、累计差分、重投影之前。ERA5 的填充值、NaN、Inf、
重复时间和时间序列内部缺口不能静默变成 GeoTIFF 的 ``-9999``；审计会
先写出机器可读报告，再抛出 ``Era5QualityError`` 阻断当前处理。
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Iterable, Mapping

import numpy as np
import pandas as pd
import xarray as xr


ERA5_QUALITY_SCHEMA = "hbv_era5_quality_report_v1"
ERA5_QUALITY_VERSION = "2026.10.05.1"


class Era5QualityError(ValueError):
    """ERA5 输入未通过质量审计。"""

    def __init__(self, message: str, report: Mapping[str, Any] | None = None):
        super().__init__(message)
        self.report = dict(report or {})


def _time_name(arr: xr.DataArray) -> str:
    for name in ("valid_time", "time"):
        if name in arr.dims or name in arr.coords:
            return name
    raise Era5QualityError("ERA5 变量缺少 time/valid_time 时间坐标。")


def _coordinate_name(arr: xr.DataArray, names: tuple[str, ...], dims: tuple[str, ...]) -> str | None:
    for name in names:
        if name in arr.coords and (name in arr.dims or name in dims):
            return name
    return None


def _markers(arr: xr.DataArray) -> list[float]:
    values: list[float] = []
    for container in (arr.attrs, arr.encoding):
        for key in ("_FillValue", "missing_value"):
            marker = container.get(key)
            if marker is None:
                continue
            try:
                values.extend(float(item) for item in np.asarray(marker).reshape(-1))
            except (TypeError, ValueError):
                continue
    return values


def _missing_mask(values: np.ndarray, arr: xr.DataArray) -> np.ndarray:
    mask = ~np.isfinite(values)
    for marker in _markers(arr):
        if np.isfinite(marker):
            mask |= np.isclose(values, marker, rtol=0.0, atol=max(abs(marker) * 1e-12, 1e-12))
    return mask


def _sha256(path: Path) -> str | None:
    if not path.is_file():
        return None
    digest = hashlib.sha256()
    try:
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
    except OSError:
        return None
    return digest.hexdigest()


def source_file_records(source_paths: Iterable[Path | str] | None) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for raw in source_paths or ():
        path = Path(raw)
        item: dict[str, Any] = {"path": str(path)}
        if path.is_file():
            item["size_bytes"] = path.stat().st_size
            item["sha256"] = _sha256(path)
        else:
            item["exists"] = False
        records.append(item)
    return records


def _json_safe(value: Any) -> Any:
    if isinstance(value, (np.integer,)):
        return int(value)
    if isinstance(value, (np.floating,)):
        return float(value)
    if isinstance(value, (pd.Timestamp, np.datetime64)):
        return str(pd.Timestamp(value))
    if isinstance(value, Path):
        return str(value)
    return value


def _write_report(report_path: Path | str | None, report: Mapping[str, Any]) -> None:
    if report_path is None:
        return
    path = Path(report_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2, default=_json_safe),
        encoding="utf-8",
    )


def write_quality_failure_report(
    report_path: Path | str | None,
    *,
    variable: str,
    errors: Iterable[str],
    source_paths: Iterable[Path | str] | None = None,
    required_times: Iterable[Any] | None = None,
    context: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """写出无法构造 DataArray 时使用的统一失败报告。

    边界文件缺失、文件存在但不包含要求时刻时，处理流程还没有可供
    ``audit_era5_dataarray`` 审计的完整数组；仍然必须先落盘同一质量
    契约，避免异常只出现在终端而无法追溯。
    """
    normalized_errors = [str(item) for item in errors if str(item).strip()]
    normalized_required = [pd.Timestamp(item).isoformat() for item in (required_times or ())]
    report: dict[str, Any] = {
        "schema": ERA5_QUALITY_SCHEMA,
        "quality_version": ERA5_QUALITY_VERSION,
        "variable": str(variable),
        "status": "failed",
        "source_files": source_file_records(source_paths),
        "array": {},
        "time": {},
        "coordinates": {},
        "missing": {"count": None, "samples": [], "markers": []},
        "required_time_missing": normalized_required,
        "errors": normalized_errors,
    }
    if context:
        report["context"] = dict(context)
    _write_report(report_path, report)
    return report


def _time_report(arr: xr.DataArray, time_name: str) -> tuple[pd.DatetimeIndex, dict[str, Any], list[str]]:
    errors: list[str] = []
    try:
        index = pd.DatetimeIndex(pd.to_datetime(arr[time_name].values))
    except Exception as exc:
        return pd.DatetimeIndex([]), {"parse_error": str(exc)}, [f"时间坐标无法解析：{exc}"]
    if len(index) == 0:
        errors.append("时间坐标为空。")
    duplicates = index[index.duplicated()].unique()
    if len(duplicates):
        errors.append(f"时间坐标有 {len(duplicates)} 个重复时刻。")
    gaps: list[dict[str, Any]] = []
    if len(index) >= 3 and not index.has_duplicates:
        ordered = index.sort_values()
        diffs = ordered.to_series().diff().dropna()
        positive = diffs[diffs > pd.Timedelta(0)]
        if not positive.empty:
            # 以最小正间隔作为名义步长，避免单个缺口把中位数抬高而漏报。
            # ERA5 文件应为规则时间轴；若存在多个异常间隔，逐个报告。
            step = positive.min()
            for position, delta in enumerate(diffs, start=1):
                if delta > step * 1.5:
                    gaps.append({
                        "before": ordered[position - 1],
                        "after": ordered[position],
                        "missing_intervals_estimate": max(int(round(delta / step)) - 1, 1),
                    })
            if gaps:
                errors.append(f"时间序列有 {len(gaps)} 个内部缺口（基准步长 {step}）。")
    return index, {
        "count": int(len(index)),
        "first": index[0] if len(index) else None,
        "last": index[-1] if len(index) else None,
        "duplicates": [item for item in duplicates[:20]],
        "gaps": gaps[:20],
    }, errors


def audit_era5_dataarray(
    arr: xr.DataArray,
    *,
    variable: str,
    source_paths: Iterable[Path | str] | None = None,
    report_path: Path | str | None = None,
    required_times: Iterable[Any] | None = None,
    check_time_gaps: bool = True,
) -> dict[str, Any]:
    """审计一个 ERA5 DataArray，失败时写报告并抛出 ``Era5QualityError``。"""
    errors: list[str] = []
    time_name: str | None = None
    time_info: dict[str, Any] = {}
    time_index = pd.DatetimeIndex([])
    try:
        time_name = _time_name(arr)
        time_index, time_info, time_errors = _time_report(arr, time_name)
        if not check_time_gaps:
            time_info["gaps"] = []
        errors.extend(time_errors if check_time_gaps else [item for item in time_errors if "时间序列有" not in item])
    except Era5QualityError as exc:
        errors.append(str(exc))

    dims = list(arr.dims)
    coords: dict[str, Any] = {}
    for name, candidates in {
        "longitude": ("longitude", "lon"),
        "latitude": ("latitude", "lat"),
    }.items():
        coord_name = _coordinate_name(arr, candidates, tuple(arr.dims))
        if coord_name is None:
            errors.append(f"ERA5 变量缺少{name}坐标。")
            coords[name] = {"present": False}
            continue
        values = np.asarray(arr[coord_name].values, dtype=float)
        invalid = ~np.isfinite(values)
        coords[name] = {
            "name": coord_name,
            "count": int(values.size),
            "min": float(np.nanmin(values)) if values.size and (~invalid).any() else None,
            "max": float(np.nanmax(values)) if values.size and (~invalid).any() else None,
            "invalid_count": int(invalid.sum()),
        }
        if values.size == 0 or invalid.any():
            errors.append(f"{name}坐标为空或包含非有限值。")
        if coord_name not in arr.dims:
            errors.append(f"{name}坐标必须是一维网格坐标。")

    values = np.asarray(arr.values)
    missing = _missing_mask(values, arr)
    missing_positions = np.argwhere(missing)
    missing_samples: list[dict[str, Any]] = []
    for position in missing_positions[:20]:
        item: dict[str, Any] = {"indices": [int(index) for index in position]}
        if time_name and time_name in arr.dims:
            time_position = arr.dims.index(time_name)
            item["time"] = time_index[int(position[time_position])] if len(time_index) > int(position[time_position]) else None
        missing_samples.append(item)
    if missing_positions.size:
        errors.append(f"变量 {variable} 有 {len(missing_positions)} 个缺测/填充值/非有限值。")

    required_missing: list[str] = []
    if required_times is not None and len(time_index):
        available = set(time_index)
        for raw in required_times:
            stamp = pd.Timestamp(raw)
            if stamp not in available:
                required_missing.append(stamp.isoformat())
        if required_missing:
            errors.append(f"缺少 {len(required_missing)} 个要求的时间样本。")

    report: dict[str, Any] = {
        "schema": ERA5_QUALITY_SCHEMA,
        "quality_version": ERA5_QUALITY_VERSION,
        "variable": str(variable),
        "status": "passed" if not errors else "failed",
        "source_files": source_file_records(source_paths),
        "array": {"dims": dims, "shape": [int(size) for size in arr.shape], "dtype": str(arr.dtype)},
        "time": time_info,
        "coordinates": coords,
        "missing": {
            "count": int(len(missing_positions)),
            "samples": missing_samples,
            "markers": _markers(arr),
        },
        "required_time_missing": required_missing[:50],
        "errors": errors,
    }
    _write_report(report_path, report)
    if errors:
        summary = "；".join(errors[:3])
        raise Era5QualityError(f"ERA5 {variable} 质量审计失败：{summary}", report)
    return report


def audit_era5_dataset(
    dataset: xr.Dataset,
    *,
    variables: Iterable[str] | Mapping[str, str],
    source_paths: Iterable[Path | str] | None = None,
    report_dir: Path | str | None = None,
    check_time_gaps: bool = True,
) -> dict[str, Any]:
    """审计数据集中的多个变量，并为每个变量保留独立报告。"""
    mapping = dict(variables) if isinstance(variables, Mapping) else {name: name for name in variables}
    reports: dict[str, Any] = {}
    failures: list[str] = []
    for data_name, label in mapping.items():
        if data_name not in dataset.data_vars:
            failures.append(f"缺少变量 {data_name}")
            continue
        path = None
        if report_dir is not None:
            path = Path(report_dir) / f"era5_{label}_quality.json"
        try:
            reports[label] = audit_era5_dataarray(
                dataset[data_name],
                variable=label,
                source_paths=source_paths,
                report_path=path,
                check_time_gaps=check_time_gaps,
            )
        except Era5QualityError as exc:
            reports[label] = exc.report
            failures.append(str(exc))
    if failures:
        raise Era5QualityError("；".join(failures[:3]), {"schema": ERA5_QUALITY_SCHEMA, "variables": reports, "errors": failures})
    return reports

