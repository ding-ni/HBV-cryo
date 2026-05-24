# -*- coding: utf-8 -*-
import json
import os
import shutil
import sys
import tempfile
import time
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd
import rasterio
from rasterio.transform import from_origin
from shapely.geometry import box


工程根目录 = Path(__file__).resolve().parent
sys.path.insert(0, str(工程根目录 / "HBV-Studio"))

from studio_service import _create_manual_start_result, validate_workspace_fields, workspace_detailed_check
from studio_service import forward_simulate


def 解析便携路径(path_value):
    text = str(path_value or "").strip()
    if not text:
        return Path("")
    text = text.replace("__PROJECT_ROOT__", str(工程根目录))
    text = text.replace("__GUI_ROOT__", str(工程根目录 / "HBV-Studio"))
    return Path(text)


def 写栅格(path, data, transform, crs="EPSG:4326", nodata=-9999.0):
    path.parent.mkdir(parents=True, exist_ok=True)
    profile = {
        "driver": "GTiff",
        "height": data.shape[0],
        "width": data.shape[1],
        "count": 1,
        "dtype": str(data.dtype),
        "crs": crs,
        "transform": transform,
        "nodata": nodata,
        "compress": "lzw",
    }
    with rasterio.open(path, "w", **profile) as dst:
        dst.write(data, 1)


def 构建自检输入(运行目录):
    data_root = 运行目录 / "数据"
    gis_dir = data_root / "地理数据"
    obs_dir = data_root / "观测数据"
    prec_dir = data_root / "模型输入" / "降水_MSWEP"
    temp_dir = data_root / "模型输入" / "气温"
    evap_dir = data_root / "模型输入" / "蒸散发"

    transform = from_origin(90.0, 35.0, 0.1, 0.1)
    dem = np.array([
        [4300.0, 4600.0, 5200.0],
        [4350.0, 4700.0, 5250.0],
        [4400.0, 4800.0, 5300.0],
    ], dtype=np.float32)
    flow_acc = np.array([
        [1.0, 2.0, 3.0],
        [2.0, 4.0, 6.0],
        [3.0, 6.0, 9.0],
    ], dtype=np.float32)
    glacier = np.array([
        [0, 0, 1],
        [0, 0, 1],
        [0, 0, 1],
    ], dtype=np.uint8)
    zone_low = (dem < 5000.0).astype(np.uint8)
    zone_high = (dem >= 5000.0).astype(np.uint8)

    dem_path = gis_dir / "dem_1km.tif"
    写栅格(dem_path, dem, transform, nodata=-9999.0)
    写栅格(gis_dir / "flow_accumulation_masked.tif", flow_acc, transform, nodata=-9999.0)
    写栅格(gis_dir / "flow_direction.tif", flow_acc.astype(np.float32), transform, nodata=-9999.0)
    写栅格(gis_dir / "flow_accumulation.tif", flow_acc, transform, nodata=-9999.0)
    写栅格(gis_dir / "glacier_mask.tif", glacier, transform, nodata=255)
    写栅格(gis_dir / "elevation_zone_low.tif", zone_low, transform, nodata=255)
    写栅格(gis_dir / "elevation_zone_high.tif", zone_high, transform, nodata=255)

    basin = gpd.GeoDataFrame({"id": [1]}, geometry=[box(90.0, 34.7, 90.3, 35.0)], crs="EPSG:4326")
    basin_path = 运行目录 / "basin.shp"
    basin.to_file(basin_path, encoding="utf-8")

    dates_all = pd.date_range("2000-01-01", "2000-01-10", freq="D")
    for i, date in enumerate(dates_all):
        prec = np.full((3, 3), 5.0 + (i % 3), dtype=np.float32)
        temp = np.full((3, 3), -2.0 + 0.8 * i, dtype=np.float32)
        evap = np.full((3, 3), 1.0, dtype=np.float32)
        写栅格(prec_dir / f"{i:03d}_PREC_{date.strftime('%Y.%m.%d')}.tif", prec, transform)
        写栅格(temp_dir / f"{i:03d}_TEMP_{date.strftime('%Y.%m.%d')}.tif", temp, transform)
        写栅格(evap_dir / f"{i:03d}_EVAP_{date.strftime('%Y.%m.%d')}.tif", evap, transform)

    sim_dates = pd.date_range("2000-01-03", "2000-01-10", freq="D")
    obs = pd.DataFrame({
        "date": sim_dates,
        "discharge (m3/s)": np.linspace(8.0, 12.0, len(sim_dates)),
    })
    obs_path = obs_dir / "discharge.csv"
    obs_dir.mkdir(parents=True, exist_ok=True)
    obs.to_csv(obs_path, index=False)

    inflow = pd.DataFrame({
        "date": dates_all,
        "inflow_m3s": np.full(len(dates_all), 1.5),
    })
    inflow_path = 运行目录 / "上游边界入流.csv"
    inflow.to_csv(inflow_path, index=False)

    return basin_path, dem_path, obs_path, inflow_path


def 写自检配置(配置路径, 运行目录, basin_path, dem_path, obs_path, inflow_path):
    cfg = {
        "运行目录": str(运行目录),
        "项目对象": "interbasin_with_boundary",
        "流域名称": "自检流域",
        "流域编号": "self_check",
        "流域边界_shp": str(basin_path),
        "DEM_tif": str(dem_path),
        "观测径流_csv": str(obs_path),
        "观测口径模式": "full_year",
        "边界条件": {
            "上游边界入流_csv": str(inflow_path),
            "时间字段": "date",
            "流量字段": "inflow_m3s",
        },
        "冰川边界_shp": "",
        "范围_bbox": {"北": 35.0, "西": 90.0, "南": 34.7, "东": 90.3},
        "时间": {
            "开始年份": 2000,
            "结束年份": 2000,
            "预热开始": "2000-01-01",
            "预热结束": "2000-01-02",
            "率定开始": "2000-01-03",
            "率定结束": "2000-01-06",
            "验证开始": "2000-01-07",
            "验证结束": "2000-01-10",
        },
        "FAO56平均海拔_m": 4600.0,
        "默认降水源": "mswep",
        "时间步长_小时": 24.0,
        "CFMAX分区阈值_m": 5000.0,
    }
    配置路径.write_text(json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf-8")


def 写边界缺失回放配置(源配置路径, 输出配置路径, 缺失边界路径):
    cfg = json.loads(Path(源配置路径).read_text(encoding="utf-8"))
    cfg["边界条件"]["上游边界入流_csv"] = str(Path(缺失边界路径).resolve())
    输出配置路径.write_text(json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf-8")


def 验证边界回放缺口修复(临时目录, 配置路径, 结果目录, metadata, simulation):
    参数 = dict(metadata.get("optimized_params", {}) or {})
    if not 参数:
        raise RuntimeError("自检失败：metadata.json 缺少 optimized_params，无法验证边界回放 fallback。")

    回放配置路径 = 临时目录 / "自检配置_边界缺失回放.json"
    缺失边界路径 = 临时目录 / "missing_boundary.csv"
    写边界缺失回放配置(配置路径, 回放配置路径, 缺失边界路径)

    回放结果目录 = 临时目录 / "回放源结果"
    回放结果目录.mkdir(parents=True, exist_ok=True)
    shutil.copy2(结果目录 / "metadata.json", 回放结果目录 / "metadata.json")
    shutil.copy2(结果目录 / "simulation.csv", 回放结果目录 / "simulation.csv")

    回放元数据路径 = 回放结果目录 / "metadata.json"
    回放元数据 = json.loads(回放元数据路径.read_text(encoding="utf-8"))
    缺失边界绝对路径 = str(缺失边界路径.resolve())
    回放元数据["workspace_config"] = str(回放配置路径.resolve())

    边界条件 = dict(回放元数据.get("boundary_condition", {}) or {})
    边界条件["boundary_inflow_file"] = 缺失边界绝对路径
    边界条件["file"] = 缺失边界绝对路径
    回放元数据["boundary_condition"] = 边界条件

    可选模块 = dict(回放元数据.get("optional_modules", {}) or {})
    边界模块 = dict(可选模块.get("boundary_inflow", {}) or {})
    if 边界模块:
        边界模块["file"] = 缺失边界绝对路径
        可选模块["boundary_inflow"] = 边界模块
        回放元数据["optional_modules"] = 可选模块

    回放元数据路径.write_text(json.dumps(回放元数据, ensure_ascii=False, indent=2), encoding="utf-8")

    回放结果 = forward_simulate({
        "run_path": str(回放结果目录.resolve()),
        "params": 参数,
    })
    回放运行时 = dict(回放结果.get("runtime", {}) or {})
    if not 回放运行时.get("boundary_restored_from_run", False):
        raise RuntimeError("自检失败：边界文件缺失时，forward replay 未从源结果恢复 q_boundary_inflow。")
    if not 回放运行时.get("boundary_enabled", False):
        raise RuntimeError("自检失败：边界回放完成后 boundary_enabled 未恢复为 True。")

    源边界序列 = simulation["q_boundary_inflow"].to_numpy(dtype=float)
    回放边界序列 = np.asarray(回放结果.get("q_boundary_inflow", []), dtype=float)
    if 回放边界序列.shape != 源边界序列.shape:
        raise RuntimeError(
            f"自检失败：边界回放长度不一致，源结果 {源边界序列.shape}，回放结果 {回放边界序列.shape}。"
        )
    if not np.allclose(回放边界序列, 源边界序列, rtol=1e-9, atol=1e-9):
        raise RuntimeError("自检失败：边界文件缺失时，回放得到的 q_boundary_inflow 与源结果不一致。")


def main():
    临时目录 = Path(tempfile.mkdtemp(prefix="hbv_cryo_selfcheck_"))
    保留目录 = False
    try:
        started_at = time.perf_counter()
        运行目录 = 临时目录 / "运行目录" / "自检流域"
        运行目录.mkdir(parents=True, exist_ok=True)
        basin_path, dem_path, obs_path, inflow_path = 构建自检输入(运行目录)
        配置路径 = 临时目录 / "自检配置.json"
        写自检配置(配置路径, 运行目录, basin_path, dem_path, obs_path, inflow_path)
        validation = validate_workspace_fields(str(配置路径), stage="calibration")
        if not validation.get("valid"):
            raise RuntimeError(f"自检前工作区校验失败：{validation.get('missing', [])}")
        detail = workspace_detailed_check(str(配置路径))
        failed_rows = [row for row in detail.get("summary", []) if row.get("ok") is False]
        if failed_rows:
            raise RuntimeError(f"自检前输入摘要存在缺项：{failed_rows[:5]}")

        结果 = _create_manual_start_result({"config_path": str(配置路径.resolve())})
        最新结果 = Path(str(结果.get("run_path", "")).strip())
        if not 最新结果.exists():
            raise RuntimeError("自检未生成运行结果目录。")
        simulation = pd.read_csv(最新结果 / "simulation.csv")
        metadata = json.loads((最新结果 / "metadata.json").read_text(encoding="utf-8"))

        if "q_boundary_inflow" not in simulation.columns:
            raise RuntimeError("自检失败：simulation.csv 缺少 q_boundary_inflow 列。")
        if not metadata.get("boundary_condition", {}).get("enabled", False):
            raise RuntimeError("自检失败：metadata.json 未记录上游边界入流。")
        data_cache = dict(metadata.get("data_cache", {}))
        for key in ("prec", "temp", "evap"):
            item = dict(data_cache.get(key, {}))
            cache_path = 解析便携路径(item.get("cache_path", ""))
            if not cache_path.exists():
                raise RuntimeError(f"自检失败：metadata.json 未记录有效的 {key} 缓存文件。")
        验证边界回放缺口修复(临时目录, 配置路径, 最新结果, metadata, simulation)

        print("系统自检通过")
        print(f"结果目录: {最新结果}")
        print(f"NSE(率定期): {metadata['metrics']['calibration']['nse']}")
        print(f"耗时: {time.perf_counter() - started_at:.2f} s")
    except Exception:
        保留目录 = True
        if 保留目录:
            print(f"自检临时目录保留: {临时目录}")
        raise
    finally:
        if not 保留目录:
            shutil.rmtree(临时目录, ignore_errors=True)


if __name__ == "__main__":
    main()
