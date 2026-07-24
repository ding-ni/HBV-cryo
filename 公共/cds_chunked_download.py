# -*- coding: utf-8 -*-
"""CDS / ERA5-Land 按月分片下载与年文件合并。

小时整年请求会触发 CDS ``cost limits exceeded / request is too large``。
日尺度 6 小时时次在较大空间范围下也可能踩限额。统一按月（可配置）拆请求，
下载后合并为下游仍认的按年 NetCDF。
"""
from __future__ import annotations

import os
import re
import shutil
import tempfile
import zipfile
from pathlib import Path
from typing import Any, Callable, Iterable, Sequence


DEFAULT_CHUNK_MONTHS = 1
HOURLY_TIMES = [f"{hour:02d}:00" for hour in range(24)]
SIX_HOURLY_TIMES = ["00:00", "06:00", "12:00", "18:00"]

_SIZE_ERROR_MARKERS = (
    "too large",
    "cost limits",
    "cost limit",
    "payload limit",
    "request size",
)


def month_chunks(chunk_months: int = DEFAULT_CHUNK_MONTHS) -> list[list[int]]:
    size = max(1, min(int(chunk_months), 12))
    months = list(range(1, 13))
    return [months[index : index + size] for index in range(0, 12, size)]


def is_cds_size_error(exc: BaseException | str) -> bool:
    text = str(exc).lower()
    return any(marker in text for marker in _SIZE_ERROR_MARKERS)


def format_cds_size_error(exc: BaseException | str, *, hint: str | None = None) -> str:
    base = str(exc).strip()
    if not is_cds_size_error(exc):
        return base
    advice = hint or (
        "CDS 单次请求过大（cost limits / too large）。"
        "本流程已按月分片；若仍失败请缩小空间范围或保持 1 个月分片。"
    )
    return f"{base}\n[提示] {advice}"


def extract_if_zip(file_path: str | Path) -> Path:
    """若 CDS 返回 ZIP，解出其中的 .nc 到原路径。"""
    path = Path(file_path)
    if not path.exists():
        return path
    with open(path, "rb") as handle:
        header = handle.read(2)
    if header != b"PK":
        return path

    print(f"      检测到 ZIP，正在解压 {path.name} ...")
    zip_path = path.with_suffix(path.suffix + ".zip")
    if zip_path.exists():
        zip_path.unlink()
    path.replace(zip_path)
    extracted_nc: Path | None = None
    try:
        with zipfile.ZipFile(zip_path, "r") as archive:
            names = [name for name in archive.namelist() if name.lower().endswith(".nc")]
            if not names:
                raise RuntimeError(f"ZIP 中未找到 NetCDF：{zip_path}")
            archive.extract(names[0], path=path.parent)
            extracted_nc = path.parent / names[0]
        if extracted_nc.resolve() != path.resolve():
            if path.exists():
                path.unlink()
            shutil.move(str(extracted_nc), str(path))
    finally:
        if zip_path.exists():
            zip_path.unlink()
        if (
            extracted_nc is not None
            and extracted_nc.exists()
            and extracted_nc.resolve() != path.resolve()
        ):
            extracted_nc.unlink(missing_ok=True)
    return path


def time_coord_name(dataset: Any) -> str:
    for name in ("valid_time", "time"):
        if name in dataset.coords or name in dataset.dims:
            return name
    raise RuntimeError("NetCDF 中未找到 time / valid_time 坐标")


def is_usable_netcdf(path: str | Path, *, min_size: int = 1000) -> bool:
    candidate = Path(path)
    if not candidate.is_file() or candidate.stat().st_size <= min_size:
        return False
    try:
        import xarray as xr

        with xr.open_dataset(candidate, engine="netcdf4") as dataset:
            _ = time_coord_name(dataset)
            if not dataset.data_vars:
                return False
        return True
    except Exception:
        # 中文路径等情况下复制到 ASCII 临时目录再试
        try:
            import xarray as xr

            with tempfile.TemporaryDirectory(prefix="hbv_nc_probe_") as temp_dir:
                ascii_copy = Path(temp_dir) / "probe.nc"
                shutil.copy2(candidate, ascii_copy)
                with xr.open_dataset(ascii_copy, engine="netcdf4") as dataset:
                    _ = time_coord_name(dataset)
                    if not dataset.data_vars:
                        return False
            return True
        except Exception:
            return False


def unique_sorted_time_indices(values: Any) -> Any:
    import numpy as np

    arr = np.asarray(values)
    _, first_index = np.unique(arr, return_index=True)
    return np.sort(first_index)


def merge_netcdf_files(month_files: Sequence[str | Path], output_file: str | Path) -> Path:
    import xarray as xr

    sources = [Path(item) for item in month_files]
    if not sources:
        raise RuntimeError("没有可合并的分片 NetCDF")

    output = Path(output_file)
    datasets: list[Any] = []
    temp_dir: Path | None = None
    partial_file = output.with_suffix(output.suffix + ".merge_part")
    try:
        for source in sources:
            try:
                datasets.append(xr.open_dataset(source, engine="netcdf4"))
            except Exception:
                if temp_dir is None:
                    temp_dir = Path(tempfile.mkdtemp(prefix="hbv_era5_merge_"))
                ascii_copy = temp_dir / source.name
                shutil.copy2(source, ascii_copy)
                datasets.append(xr.open_dataset(ascii_copy, engine="netcdf4"))

        time_name = time_coord_name(datasets[0])
        for dataset in datasets[1:]:
            other = time_coord_name(dataset)
            if other != time_name:
                raise RuntimeError(f"时间坐标不一致：{time_name} vs {other}")

        merged = xr.concat(datasets, dim=time_name)
        merged = merged.isel({time_name: unique_sorted_time_indices(merged[time_name].values)})
        merged = merged.sortby(time_name)

        if partial_file.exists():
            partial_file.unlink()
        # 关闭源再写，降低 Windows 文件锁冲突
        for dataset in datasets:
            dataset.close()
        datasets.clear()
        merged.to_netcdf(partial_file)
        merged.close()
        if not is_usable_netcdf(partial_file):
            raise RuntimeError(f"合并结果不可读：{partial_file}")
        os.replace(partial_file, output)
        return output
    finally:
        for dataset in datasets:
            try:
                dataset.close()
            except Exception:
                pass
        if partial_file.exists():
            try:
                partial_file.unlink()
            except Exception:
                pass
        if temp_dir is not None:
            shutil.rmtree(temp_dir, ignore_errors=True)


def _chunk_label(year: int, months: Sequence[int]) -> str:
    if len(months) == 1:
        return f"{year}-{months[0]:02d}"
    return f"{year}-{months[0]:02d}..{months[-1]:02d}"


def _chunk_filename(stem: str, months: Sequence[int]) -> str:
    if len(months) == 1:
        return f"{stem}_{months[0]:02d}.nc"
    return f"{stem}_{months[0]:02d}-{months[-1]:02d}.nc"


def download_era5_land_year_chunked(
    client: Any,
    *,
    variable: str,
    year: int,
    area: Sequence[float],
    output_file: str | Path,
    times: Sequence[str],
    chunk_months: int = DEFAULT_CHUNK_MONTHS,
    dataset: str = "reanalysis-era5-land",
    skip_if_exists: bool = True,
    exists_checker: Callable[[Path], bool] | None = None,
    on_chunk_error: Callable[[BaseException], str] | None = None,
) -> Path:
    """按月（或 N 月）分片下载 ERA5-Land 单变量单年，合并为 output_file。"""
    output = Path(output_file)
    checker = exists_checker or is_usable_netcdf
    if skip_if_exists and checker(output):
        print(f"[跳过] 已存在 {output.name}")
        return output

    output.parent.mkdir(parents=True, exist_ok=True)
    chunk_months = max(1, min(int(chunk_months), 12))
    print(f"[下载] {output.name}（按 {chunk_months} 个月分片）")

    chunk_root = output.parent / f".{output.stem}_chunks"
    chunk_root.mkdir(parents=True, exist_ok=True)
    month_files: list[Path] = []

    try:
        for months in month_chunks(chunk_months):
            chunk_file = chunk_root / _chunk_filename(output.stem, months)
            if checker(chunk_file):
                print(f"      [跳过] 分片已存在 {chunk_file.name}")
                month_files.append(chunk_file)
                continue

            partial_file = chunk_file.with_suffix(chunk_file.suffix + ".part")
            if partial_file.exists():
                partial_file.unlink()

            request = {
                "variable": variable,
                "year": str(year),
                "month": [f"{month:02d}" for month in months],
                "day": [f"{day:02d}" for day in range(1, 32)],
                "time": list(times),
                "area": list(area),
                "format": "netcdf",
            }
            label = _chunk_label(year, months)
            print(f"      [下载分片] {variable} {label} -> {chunk_file.name}")
            try:
                client.retrieve(dataset, request, str(partial_file))
                extract_if_zip(partial_file)
                if not checker(partial_file):
                    raise RuntimeError(f"分片下载结果不可读：{partial_file}")
                os.replace(partial_file, chunk_file)
            except Exception as exc:
                if partial_file.exists():
                    partial_file.unlink()
                message = on_chunk_error(exc) if on_chunk_error else format_cds_size_error(exc)
                raise RuntimeError(message) from exc
            month_files.append(chunk_file)

        print(f"      [合并] {len(month_files)} 个分片 -> {output.name}")
        merge_netcdf_files(month_files, output)
        if not checker(output):
            raise RuntimeError(f"年文件合并后校验失败：{output}")
        print(f"      [完成] {output.name}")
        shutil.rmtree(chunk_root, ignore_errors=True)
        return output
    except Exception:
        print(f"      [保留分片] 失败后可重试，目录：{chunk_root}")
        raise


def ensure_cdsapi_configured() -> Path:
    try:
        import cdsapi  # noqa: F401
    except ImportError as exc:
        raise RuntimeError("缺少 cdsapi，请先安装：pip install cdsapi") from exc
    config_file = Path.home() / ".cdsapirc"
    if not config_file.exists():
        raise RuntimeError(f"未找到 CDS API 配置文件：{config_file}")
    return config_file


def summarize_request_cost_hint(times: Sequence[str], chunk_months: int) -> str:
    return (
        f"时次={len(list(times))}/日, 分片={max(1, min(int(chunk_months), 12))} 个月/请求"
    )
