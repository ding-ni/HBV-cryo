# -*- coding: utf-8 -*-
"""
阶段2：下载气象数据

包含：
1. ERA5-Land 温度下载（用于后续温度栅格与 FAO56 PET 计算）
2. ERA5-Land 降水下载（当工程降水源选择 ERA5 时启用）
3. MSWEP/CMFD 降水本地原始文件说明

注意：
- ERA5下载需要先注册 CDS 账号并配置 ~/.cdsapirc
- MSWEP/CMFD 当前不在本模块自动下载，需要用户自行准备本地原始文件
- 当前默认流程不再下载 ERA5 实际蒸散发 total_evaporation；
  潜在蒸散发统一走 ERA5 气象变量 + FAO56 Penman-Monteith
"""

import os
import shutil
import sys
import tempfile
from datetime import datetime
from pathlib import Path

_COMMON_DIR = Path(__file__).resolve().parents[1]
if str(_COMMON_DIR) not in sys.path:
    sys.path.insert(0, str(_COMMON_DIR))

from cds_chunked_download import (  # type: ignore
    DEFAULT_CHUNK_MONTHS,
    SIX_HOURLY_TIMES,
    download_era5_land_year_chunked,
    format_cds_size_error,
    is_usable_netcdf,
)

# ============================================================
# 路径配置
# ============================================================
def _prefer_existing_path(*paths):
    for path in paths:
        if os.path.exists(path):
            return path
    return paths[0]


PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "运行目录", "默认流域"))
RAW_ROOT = ""
RAW_TEMP_DIR = ""
RAW_EVAP_DIR = ""
RAW_PREC_DIR = ""
RAW_PREC_ERA5_DIR = ""

# 当前流域大致范围 [North, West, South, East]
# 可根据实际流域边界调整
TUOTUOHE_BBOX = [35.5, 90.5, 33.0, 93.5]

# 时间范围
START_YEAR = 2006
END_YEAR = 2020


def refresh_workspace_paths():
    global RAW_ROOT, RAW_TEMP_DIR, RAW_EVAP_DIR, RAW_PREC_DIR, RAW_PREC_ERA5_DIR
    RAW_ROOT = _prefer_existing_path(os.path.join(PROJECT_ROOT, "数据", "原始气象"), os.path.join(PROJECT_ROOT, "data", "raw"))
    RAW_TEMP_DIR = _prefer_existing_path(os.path.join(RAW_ROOT, "气温"), os.path.join(RAW_ROOT, "temperature"))
    RAW_EVAP_DIR = _prefer_existing_path(os.path.join(RAW_ROOT, "蒸散发"), os.path.join(RAW_ROOT, "evaporation"))
    RAW_PREC_DIR = _prefer_existing_path(os.path.join(RAW_ROOT, "降水"), os.path.join(RAW_ROOT, "precipitation"))
    RAW_PREC_ERA5_DIR = _prefer_existing_path(os.path.join(RAW_PREC_DIR, "ERA5"), os.path.join(RAW_PREC_DIR, "era5"))


refresh_workspace_paths()


# ============================================================
# ERA5-Land 下载配置
# ============================================================
def check_cdsapi_config():
    """检查 CDS API 配置"""
    import os

    # Windows: C:\Users\<username>\.cdsapirc
    # Linux/Mac: ~/.cdsapirc
    home = os.path.expanduser("~")
    config_file = os.path.join(home, ".cdsapirc")

    if os.path.exists(config_file):
        print(f"[OK] CDS API 配置文件存在: {config_file}")
        return True
    else:
        print(f"[ERROR] CDS API 配置文件不存在: {config_file}")
        print("\n请按以下步骤配置：")
        print("1. 访问 https://cds.climate.copernicus.eu/ 注册账号")
        print("2. 登录后访问 https://cds.climate.copernicus.eu/api-how-to")
        print("3. 复制 API key")
        print(f"4. 创建文件 {config_file}，内容如下：")
        print("   url: https://cds.climate.copernicus.eu/api/v2")
        print("   key: <your-uid>:<your-api-key>")
        return False


def extract_if_zip(file_path):
    """如果是ZIP文件则解压"""
    import zipfile
    import shutil

    with open(file_path, 'rb') as f:
        header = f.read(2)

    if header == b'PK':  # ZIP 文件标识
        print(f"      检测到ZIP格式，正在解压...")
        zip_path = file_path + '.zip'
        os.rename(file_path, zip_path)

        with zipfile.ZipFile(zip_path, 'r') as zf:
            names = zf.namelist()
            zf.extractall(os.path.dirname(file_path))

        os.remove(zip_path)

        # 重命名解压出的文件
        for name in names:
            if name.endswith('.nc'):
                extracted = os.path.join(os.path.dirname(file_path), name)
                if os.path.exists(extracted):
                    shutil.move(extracted, file_path)
                    break

        print(f"      解压完成")


BOUNDARY_VARIABLE_NAMES = {
    "total_precipitation": "tp",
    "total_evaporation": "e",
}


def validate_accumulation_boundary(file_path, variable, boundary_year):
    """校验累计变量最后一年所需的次年 01-01 00:00 收尾样本。"""
    import numpy as np
    import xarray as xr

    source = Path(file_path)
    if not source.is_file() or source.stat().st_size <= 1000:
        return False, "边界文件不存在或过小"

    expected_variable = BOUNDARY_VARIABLE_NAMES[variable]
    expected_time = np.datetime64(f"{int(boundary_year):04d}-01-01T00", "h")
    with tempfile.TemporaryDirectory(prefix="hbv_era5_boundary_qc_") as temp_dir:
        ascii_copy = Path(temp_dir) / f"{expected_variable}_boundary.nc"
        shutil.copy2(source, ascii_copy)
        try:
            with xr.open_dataset(ascii_copy, engine="netcdf4") as dataset:
                if expected_variable not in dataset.data_vars:
                    return False, f"缺少变量 {expected_variable}"
                time_name = next(
                    (name for name in ("valid_time", "time") if name in dataset.coords),
                    None,
                )
                if time_name is None or len(dataset[time_name]) != 1:
                    return False, "边界文件必须且只能包含一个时次"
                actual_time = np.datetime64(dataset[time_name].values[0], "h")
                if actual_time != expected_time:
                    return False, f"边界时次 {actual_time}，预期 {expected_time}"
                values = np.asarray(dataset[expected_variable].values)
                if values.size == 0 or not np.isfinite(values).any():
                    return False, "边界变量为空或全部无效"
        except Exception as exc:
            return False, f"边界 NetCDF 无法完整读取: {exc}"
    return True, "变量、时次和数据可读性通过"


def download_accumulation_boundary(variable, output_dir, prefix, boundary_year):
    """下载最后一年累计量所需的次年 01-01 00:00 单时次文件。"""
    import cdsapi

    os.makedirs(output_dir, exist_ok=True)
    output_file = os.path.join(output_dir, f"{prefix}_boundary_{boundary_year}.nc")
    partial_file = output_file + ".part"

    if os.path.exists(output_file):
        valid, reason = validate_accumulation_boundary(output_file, variable, boundary_year)
        if valid:
            print(f"   {boundary_year}-01-01 00:00: 边界文件已存在且校验通过")
            return output_file
        print(f"   边界文件未通过校验，将重新下载（{reason}）")

    if os.path.exists(partial_file):
        os.remove(partial_file)

    print(f"   {boundary_year}-01-01 00:00: 下载累计量收尾样本...")
    try:
        cdsapi.Client().retrieve(
            "reanalysis-era5-land",
            {
                "variable": variable,
                "year": str(boundary_year),
                "month": "01",
                "day": "01",
                "time": "00:00",
                "area": TUOTUOHE_BBOX,
                "format": "netcdf",
            },
            partial_file,
        )
        extract_if_zip(partial_file)
        valid, reason = validate_accumulation_boundary(partial_file, variable, boundary_year)
        if not valid:
            raise RuntimeError(f"边界下载结果校验失败：{reason}")
        os.replace(partial_file, output_file)
    except Exception:
        if os.path.exists(partial_file):
            os.remove(partial_file)
        raise

    print(f"   {boundary_year}-01-01 00:00: [OK]")
    return output_file


def _download_daily_era5_variable(variable, output_file, year, *, label):
    """日尺度 ERA5-Land：6 小时时次，按月分片后合并为年文件。"""
    import cdsapi

    output_path = Path(output_file)
    if is_usable_netcdf(output_path):
        print(f"   {year}: 文件已存在，跳过")
        return

    print(f"   {year}: 下载中（{label}，按月分片）...")
    try:
        download_era5_land_year_chunked(
            cdsapi.Client(),
            variable=variable,
            year=int(year),
            area=TUOTUOHE_BBOX,
            output_file=output_path,
            times=SIX_HOURLY_TIMES,
            chunk_months=DEFAULT_CHUNK_MONTHS,
            on_chunk_error=lambda exc: format_cds_size_error(
                exc,
                hint="日尺度 ERA5 已按月分片；若仍 too large，请缩小下载范围或保持 1 个月/请求。",
            ),
        )
        print(f"   {year}: [OK]")
    except Exception as exc:
        print(f"   {year}: [ERROR] {format_cds_size_error(exc)}")
        raise


def download_era5_temperature(year):
    """下载 ERA5-Land 2m温度数据"""
    output_file = os.path.join(RAW_TEMP_DIR, f"era5_t2m_{year}.nc")
    _download_daily_era5_variable("2m_temperature", output_file, year, label="t2m")


def download_era5_evaporation(year):
    """下载 ERA5-Land 蒸散发数据"""
    output_file = os.path.join(RAW_EVAP_DIR, f"era5_evap_{year}.nc")
    _download_daily_era5_variable("total_evaporation", output_file, year, label="evap")


def download_era5_precipitation(year):
    """下载 ERA5-Land 总降水数据"""
    output_file = os.path.join(RAW_PREC_ERA5_DIR, f"era5_tp_{year}.nc")
    _download_daily_era5_variable("total_precipitation", output_file, year, label="tp")


def download_era5_all(download_actual_evaporation=False, download_precipitation=False, download_temperature=True):
    """下载所有年份的 ERA5 数据。

    默认仅下载 2m 温度。
    只有在兼容旧流程时，才额外下载 ERA5 actual evaporation。
    """
    print("=" * 60)
    print("下载 ERA5-Land 数据")
    print("=" * 60)
    print(f"工作区运行目录: {PROJECT_ROOT}")
    if download_precipitation:
        print(f"ERA5 降水目录: {RAW_PREC_ERA5_DIR}")
    if download_temperature:
        print(f"ERA5 温度目录: {RAW_TEMP_DIR}")
    if download_actual_evaporation:
        print(f"ERA5 实际蒸散发目录: {RAW_EVAP_DIR}")
    else:
        print("说明: 当前只下载 PET 所需的 ERA5 温度，不下载 ERA5 实际蒸散发。")

    # 确保目录存在
    if download_precipitation:
        os.makedirs(RAW_PREC_ERA5_DIR, exist_ok=True)
    if download_temperature:
        os.makedirs(RAW_TEMP_DIR, exist_ok=True)
    if download_actual_evaporation:
        os.makedirs(RAW_EVAP_DIR, exist_ok=True)

    # 检查配置
    if not check_cdsapi_config():
        return

    try:
        import cdsapi
    except ImportError:
        print("\n[ERROR] cdsapi 未安装")
        print("   pip install cdsapi")
        return

    if download_precipitation:
        print("\n[降水] 下载 ERA5 total_precipitation")
        for year in range(START_YEAR, END_YEAR + 1):
            try:
                download_era5_precipitation(year)
            except Exception as e:
                print(f"   [ERROR] {year}: {e}")
        try:
            download_accumulation_boundary(
                "total_precipitation",
                RAW_PREC_ERA5_DIR,
                "era5_tp",
                END_YEAR + 1,
            )
        except Exception as e:
            raise RuntimeError(f"ERA5 降水跨年收尾样本下载失败: {e}") from e

    # 下载温度
    if download_temperature:
        print("\n[温度] 下载 ERA5 2m 温度")
        for year in range(START_YEAR, END_YEAR + 1):
            try:
                download_era5_temperature(year)
            except Exception as e:
                print(f"   [ERROR] {year}: {e}")

    if download_actual_evaporation:
        print("\n[附加] 下载 ERA5 实际蒸散发数据")
        for year in range(START_YEAR, END_YEAR + 1):
            try:
                download_era5_evaporation(year)
            except Exception as e:
                print(f"   [ERROR] {year}: {e}")
        try:
            download_accumulation_boundary(
                "total_evaporation",
                RAW_EVAP_DIR,
                "era5_evap",
                END_YEAR + 1,
            )
        except Exception as e:
            raise RuntimeError(f"ERA5 实际蒸散发跨年收尾样本下载失败: {e}") from e
    else:
        print("\n[说明] 当前默认不下载 ERA5 actual evaporation（total_evaporation）。")
        print("      潜在蒸散发将在后续阶段使用 ERA5 温度/辐射/风速/露点按 FAO56 计算。")

    print("\n[OK] ERA5 下载完成！")


# ============================================================
# MSWEP 下载说明
# ============================================================
def print_mswep_instructions():
    """打印 MSWEP 下载说明"""
    print("=" * 60)
    print("MSWEP v2.8 降水数据下载说明")
    print("=" * 60)
    print("""
MSWEP 需要手动下载：

1. 访问 http://www.gloh2o.org/mswep/
2. 注册账号并登录
3. 选择 MSWEP V2.8 产品
4. 下载参数：
   - 时间范围: 2006-01-01 ~ 2020-12-31
   - 时间分辨率: Daily
   - 空间范围: 33°N-35.5°N, 90.5°E-93.5°E (当前流域)
   - 格式: NetCDF

5. 下载后将文件放入:
   {prec_dir}

文件命名格式:
   - MSWEP_2006.nc
   - 或 mswep_daily_2006.nc
""".format(prec_dir=RAW_PREC_DIR))


# ============================================================
# 主函数
# ============================================================
if __name__ == "__main__":
    print("气象数据下载工具")
    print("=" * 60)

    # 显示配置
    print(f"\n流域范围 (N, W, S, E): {TUOTUOHE_BBOX}")
    print(f"时间范围: {START_YEAR} - {END_YEAR}")

    # 打印 MSWEP 说明
    print_mswep_instructions()

    # 询问是否下载 ERA5
    print("\n" + "=" * 60)
    response = input("是否开始下载 ERA5-Land 数据? (y/n): ").strip().lower()

    if response == 'y':
        download_era5_all()
    else:
        print("\n跳过 ERA5 下载")
        print("如需下载，请确保已配置 cdsapi 后重新运行")

