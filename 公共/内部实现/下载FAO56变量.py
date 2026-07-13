# -*- coding: utf-8 -*-
"""
下载 FAO-56 Penman-Monteith 所需的 ERA5 变量

需要的变量:
1. 2m_temperature (已下载)
2. surface_solar_radiation_downwards (太阳辐射)
3. 10m_u_component_of_wind (10m U风速)
4. 10m_v_component_of_wind (10m V风速)
5. 2m_dewpoint_temperature (露点温度)
"""

import calendar
import os
import shutil
import sys
import tempfile
import zipfile
from pathlib import Path

# ============================================================
# 配置
# ============================================================
def _prefer_existing_path(*paths):
    for path in paths:
        if os.path.exists(path):
            return path
    return paths[0]


PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "运行目录", "默认流域"))
TUOTUOHE_BBOX = [35.5, 90.5, 33.0, 93.5]
START_YEAR = 2006
END_YEAR = 2020

RAW_DIR = ""
SOLAR_DIR = ""
WIND_DIR = ""
DEWPOINT_DIR = ""


def refresh_workspace_paths():
    global RAW_DIR, SOLAR_DIR, WIND_DIR, DEWPOINT_DIR
    RAW_DIR = _prefer_existing_path(os.path.join(PROJECT_ROOT, "数据", "原始气象"), os.path.join(PROJECT_ROOT, "data", "raw"))
    SOLAR_DIR = _prefer_existing_path(os.path.join(RAW_DIR, "太阳辐射"), os.path.join(RAW_DIR, "solar_radiation"))
    WIND_DIR = _prefer_existing_path(os.path.join(RAW_DIR, "风速"), os.path.join(RAW_DIR, "wind"))
    DEWPOINT_DIR = _prefer_existing_path(os.path.join(RAW_DIR, "露点温度"), os.path.join(RAW_DIR, "dewpoint"))


refresh_workspace_paths()


def check_cdsapi_config():
    home = os.path.expanduser("~")
    config_file = os.path.join(home, ".cdsapirc")
    if os.path.exists(config_file):
        print(f"[OK] CDS API 配置文件存在: {config_file}")
        return True
    print(f"[ERROR] CDS API 配置文件不存在: {config_file}")
    print("请先在当前电脑注册 CDS 账号，并按提示创建 .cdsapirc。")
    print("内容示例：")
    print("  url: https://cds.climate.copernicus.eu/api/v2")
    print("  key: <your-uid>:<your-api-key>")
    return False


def extract_if_zip(file_path):
    """如果是ZIP文件则解压"""
    with open(file_path, 'rb') as f:
        header = f.read(2)

    if header == b'PK':
        print(f"      解压中...")
        zip_path = file_path + '.zip'
        os.rename(file_path, zip_path)

        with zipfile.ZipFile(zip_path, 'r') as zf:
            names = zf.namelist()
            zf.extractall(os.path.dirname(file_path))

        os.remove(zip_path)

        for name in names:
            if name.endswith('.nc'):
                extracted = os.path.join(os.path.dirname(file_path), name)
                if os.path.exists(extracted):
                    shutil.move(extracted, file_path)
                    break


EXPECTED_SHORT_NAMES = {
    "surface_solar_radiation_downwards": "ssrd",
    "10m_u_component_of_wind": "u10",
    "10m_v_component_of_wind": "v10",
    "2m_dewpoint_temperature": "d2m",
}


def validate_download(file_path, variable, year):
    """Read the complete payload before it can become an accepted forcing file."""
    import numpy as np
    import xarray as xr

    source = Path(file_path)
    if (not source.is_file()) or source.stat().st_size <= 1000:
        return False, "文件不存在或过小"

    expected_variable = EXPECTED_SHORT_NAMES[variable]
    expected_count = (366 if calendar.isleap(int(year)) else 365) * 4
    with tempfile.TemporaryDirectory(prefix="hbv_era5_qc_") as temp_dir:
        ascii_copy = Path(temp_dir) / f"{expected_variable}_{year}.nc"
        shutil.copy2(source, ascii_copy)
        try:
            with xr.open_dataset(ascii_copy, engine="netcdf4") as dataset:
                if expected_variable not in dataset.data_vars:
                    return False, f"缺少变量 {expected_variable}"
                time_name = next(
                    (name for name in ("valid_time", "time") if name in dataset.coords),
                    None,
                )
                if time_name is None:
                    return False, "缺少时间坐标"
                time_values = dataset[time_name].values
                if len(time_values) != expected_count:
                    return False, f"时间步数 {len(time_values)}，预期 {expected_count}"
                first = np.datetime64(time_values[0], "h")
                last = np.datetime64(time_values[-1], "h")
                expected_first = np.datetime64(f"{year}-01-01T00", "h")
                expected_last = np.datetime64(f"{year}-12-31T18", "h")
                if first != expected_first or last != expected_last:
                    return False, f"时间覆盖 {first} 至 {last}"
                values = np.asarray(dataset[expected_variable].values)
                if values.size == 0 or not np.isfinite(values).any():
                    return False, "变量为空或全部无效"
        except Exception as exc:
            return False, f"NetCDF 无法完整读取: {exc}"
    return True, "变量、年份、时间步和数据可读性通过"


def validate_boundary_download(file_path, variable, boundary_year):
    import numpy as np
    import xarray as xr

    source = Path(file_path)
    if (not source.is_file()) or source.stat().st_size <= 1000:
        return False, "边界文件不存在或过小"
    expected_variable = EXPECTED_SHORT_NAMES[variable]
    expected_time = np.datetime64(f"{boundary_year}-01-01T00", "h")
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
    return True, "边界变量与次年 01-01 00:00 时次通过"


def download_variable(c, variable, output_dir, prefix, year):
    """下载单个变量单年数据"""
    os.makedirs(output_dir, exist_ok=True)
    output_file = os.path.join(output_dir, f"{prefix}_{year}.nc")
    partial_file = output_file + ".part"

    if os.path.exists(output_file):
        valid, reason = validate_download(output_file, variable, year)
        if valid:
            print(f"   {year}: 已存在且校验通过，跳过")
            return True
        print(f"   {year}: 现有文件未通过校验，将重新下载（{reason}）")

    if os.path.exists(partial_file):
        os.remove(partial_file)

    print(f"   {year}: 下载中...")

    try:
        c.retrieve(
            'reanalysis-era5-land',
            {
                'variable': variable,
                'year': str(year),
                'month': [f'{m:02d}' for m in range(1, 13)],
                'day': [f'{d:02d}' for d in range(1, 32)],
                'time': ['00:00', '06:00', '12:00', '18:00'],
                'area': TUOTUOHE_BBOX,
                'format': 'netcdf',
            },
            partial_file
        )
        extract_if_zip(partial_file)
        valid, reason = validate_download(partial_file, variable, year)
        if not valid:
            raise RuntimeError(f"下载结果校验失败：{reason}")
        os.replace(partial_file, output_file)
        print(f"   {year}: [OK]")
        return True
    except Exception as e:
        if os.path.exists(partial_file):
            os.remove(partial_file)
        print(f"   {year}: [ERROR] {e}")
        return False


def download_boundary_variable(c, variable, output_dir, prefix, boundary_year):
    os.makedirs(output_dir, exist_ok=True)
    output_file = os.path.join(output_dir, f"{prefix}_boundary_{boundary_year}.nc")
    partial_file = output_file + ".part"
    if os.path.exists(output_file):
        valid, reason = validate_boundary_download(output_file, variable, boundary_year)
        if valid:
            print(f"   {boundary_year}-01-01 00:00: 边界文件已存在且校验通过")
            return True
        print(f"   边界文件未通过校验，将重新下载（{reason}）")
    if os.path.exists(partial_file):
        os.remove(partial_file)
    print(f"   {boundary_year}-01-01 00:00: 下载累计量收尾样本...")
    try:
        c.retrieve(
            'reanalysis-era5-land',
            {
                'variable': variable,
                'year': str(boundary_year),
                'month': '01',
                'day': '01',
                'time': '00:00',
                'area': TUOTUOHE_BBOX,
                'format': 'netcdf',
            },
            partial_file,
        )
        extract_if_zip(partial_file)
        valid, reason = validate_boundary_download(partial_file, variable, boundary_year)
        if not valid:
            raise RuntimeError(f"边界下载结果校验失败：{reason}")
        os.replace(partial_file, output_file)
        print(f"   {boundary_year}-01-01 00:00: [OK]")
        return True
    except Exception as exc:
        if os.path.exists(partial_file):
            os.remove(partial_file)
        print(f"   {boundary_year}-01-01 00:00: [ERROR] {exc}")
        return False


def main():
    print("=" * 60)
    print("FAO-56 Penman-Monteith 所需变量下载")
    print("=" * 60)
    print(f"工作区运行目录: {PROJECT_ROOT}")
    print(f"太阳辐射目录: {SOLAR_DIR}")
    print(f"风速目录: {WIND_DIR}")
    print(f"露点温度目录: {DEWPOINT_DIR}")

    for directory in [SOLAR_DIR, WIND_DIR, DEWPOINT_DIR]:
        os.makedirs(directory, exist_ok=True)

    try:
        import cdsapi
    except ImportError:
        print("[ERROR] cdsapi 未安装，请先运行: pip install cdsapi")
        return
    if not check_cdsapi_config():
        return

    c = cdsapi.Client()

    # 1. 太阳辐射
    print("\n[1/3] 下载太阳辐射...")
    for year in range(START_YEAR, END_YEAR + 1):
        download_variable(c, 'surface_solar_radiation_downwards',
                         SOLAR_DIR, 'era5_ssrd', year)
    download_boundary_variable(
        c,
        'surface_solar_radiation_downwards',
        SOLAR_DIR,
        'era5_ssrd',
        END_YEAR + 1,
    )

    # 2. 风速 (U 和 V 分量)
    print("\n[2/3] 下载风速...")
    for year in range(START_YEAR, END_YEAR + 1):
        # U 分量
        download_variable(c, '10m_u_component_of_wind',
                         WIND_DIR, 'era5_u10', year)
        # V 分量
        download_variable(c, '10m_v_component_of_wind',
                         WIND_DIR, 'era5_v10', year)

    # 3. 露点温度
    print("\n[3/3] 下载露点温度...")
    for year in range(START_YEAR, END_YEAR + 1):
        download_variable(c, '2m_dewpoint_temperature',
                         DEWPOINT_DIR, 'era5_d2m', year)

    print("\n" + "=" * 60)
    print("[OK] FAO-56 变量下载完成!")
    print("=" * 60)


if __name__ == "__main__":
    main()
