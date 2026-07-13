# -*- coding: utf-8 -*-
import contextlib
import hashlib
import importlib.util
import json
import os
import shutil
import sys
import tempfile
from pathlib import Path

import geopandas as gpd
import rasterio
from rasterio.mask import mask



def _runtime_project_root() -> Path:
    raw = str(os.environ.get("HBV_STUDIO_APP_ROOT", "")).strip()
    if raw:
        return Path(raw).expanduser().resolve(strict=False)
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parents[1]


工程根目录 = _runtime_project_root()
界面根目录 = 工程根目录 / "HBV-Studio"
内部实现根目录 = 工程根目录 / "公共" / "内部实现"
模型核心路径 = 工程根目录 / "HBV-Cryo" / "率定核心.py"
基础数据目录 = 工程根目录 / "基础数据"
内置DEM目录 = 基础数据目录 / "DEM源"
内置冰川目录 = 基础数据目录 / "冰川源"

模块路径映射 = {
    ("scripts", "00b_clip_dem.py"): 内部实现根目录 / "裁剪DEM.py",
    ("scripts", "01_generate_flow_direction.py"): 内部实现根目录 / "生成流向流量累积.py",
    ("scripts", "02_download_meteorological_data.py"): 内部实现根目录 / "下载ERA5.py",
    ("scripts", "02f_download_fao56_variables.py"): 内部实现根目录 / "下载FAO56变量.py",
    ("scripts", "02b_process_era5_netcdf.py"): 内部实现根目录 / "处理ERA5.py",
    ("scripts", "02g_calculate_fao56_et.py"): 内部实现根目录 / "计算FAO56蒸散发.py",
    ("scripts", "02c_process_mswep.py"): 内部实现根目录 / "处理MSWEP.py",
    ("scripts", "02i_process_cmfd.py"): 内部实现根目录 / "处理CMFD.py",
    ("scripts", "03_数据对齐与流域掩膜.py"): 内部实现根目录 / "对齐并裁剪气象.py",
    ("glacier", "06_make_glacier_mask_from_shp.py"): 内部实现根目录 / "生成冰川掩膜.py",
    ("glacier", "06_generate_glacier_melt_from_era5.py"): 内部实现根目录 / "生成冰川融水.py",
    ("最终模型", "glacier", "06_make_glacier_mask_from_shp.py"): 内部实现根目录 / "生成冰川掩膜.py",
    ("最终模型", "glacier", "06_generate_glacier_melt_from_era5.py"): 内部实现根目录 / "生成冰川融水.py",
    ("model", "calibrate_hbv_cryo.py"): 模型核心路径,
    ("关键代码", "model", "calibrate_v6_zoned.py"): 模型核心路径,
}


_PLACEHOLDERS = {
    "__PROJECT_ROOT__": str(工程根目录),
    "__GUI_ROOT__": str(界面根目录),
}

内置DEM资产 = {
    "1km": 内置DEM目录 / "青藏高原_1km_DEM.tif",
    "0p1deg": 内置DEM目录 / "青藏高原_0p1deg_DEM.tif",
}

内置冰川资产 = 内置冰川目录 / "Second_Glacier_Inventory_China" / "Second_Glacier_Inventory_China.shp"

工作区DEM命名 = {
    "1km": "dem_1km.tif",
    "0p1deg": "dem_0p1deg.tif",
}

DEM分档候选 = ("0p1deg", "1km")


def _placeholder_roots_for_config_path(config_path):
    try:
        path = Path(config_path).resolve(strict=False)
    except Exception:
        return 工程根目录, 界面根目录
    for candidate in [path] + list(path.parents):
        if candidate.name.lower() == "hbv-studio":
            gui_root = candidate
            return gui_root.parent.resolve(strict=False), gui_root.resolve(strict=False)
    return 工程根目录, 界面根目录


def _expand_placeholders_with_roots(value, project_root, gui_root):
    placeholders = {
        "__PROJECT_ROOT__": str(project_root),
        "__GUI_ROOT__": str(gui_root),
    }
    if isinstance(value, dict):
        return {k: _expand_placeholders_with_roots(v, project_root, gui_root) for k, v in value.items()}
    if isinstance(value, list):
        return [_expand_placeholders_with_roots(v, project_root, gui_root) for v in value]
    if isinstance(value, str):
        for old, new in placeholders.items():
            value = value.replace(old, new)
    return value


def _expand_placeholders(value):
    """Recursively expand __PROJECT_ROOT__ and __GUI_ROOT__ placeholders."""
    return _expand_placeholders_with_roots(value, 工程根目录, 界面根目录)


def _remap_legacy_project_path(value, preserve_project_root=None, preserve_gui_root=None):
    if not isinstance(value, str):
        return value
    text = str(value or "").strip()
    if (not text) or ("__PROJECT_ROOT__" in text) or ("__GUI_ROOT__" in text):
        return value
    candidate = Path(text.replace("/", "\\")).expanduser()
    if not candidate.is_absolute():
        return value
    try:
        if candidate.exists():
            return value
    except Exception:
        return value
    for root in (preserve_gui_root, preserve_project_root):
        if root is None:
            continue
        try:
            candidate.resolve(strict=False).relative_to(Path(root).resolve(strict=False))
            return value
        except Exception:
            pass

    normalized = str(candidate).replace("/", "\\")
    lowered = normalized.lower()
    markers = (
        (f"\\{界面根目录.name.lower()}\\", 界面根目录),
        (f"\\{工程根目录.name.lower()}\\", 工程根目录),
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
        remapped = (root / suffix).resolve(strict=False) if suffix else root.resolve(strict=False)
        return str(remapped)
    return value


def _normalize_legacy_project_paths(
    value,
    parent_key="",
    preserve_project_root=None,
    preserve_gui_root=None,
):
    if isinstance(value, dict):
        return {
            key: _normalize_legacy_project_paths(
                item,
                str(key),
                preserve_project_root=preserve_project_root,
                preserve_gui_root=preserve_gui_root,
            )
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [
            _normalize_legacy_project_paths(
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
            return _remap_legacy_project_path(
                value,
                preserve_project_root=preserve_project_root,
                preserve_gui_root=preserve_gui_root,
            )
    return value


def 默认配置路径():
    return 工程根目录 / "配置" / "流域配置模板.json"


def example_config_path():
    return 默认配置路径()


def template_config_path():
    return 默认配置路径()


def resolve_path(value, base=None):
    if value is None or value == "":
        return None
    path = Path(value)
    if path.is_absolute():
        return path
    anchor = Path(base) if base else 工程根目录
    return Path(os.path.abspath(str(anchor / path)))


def read_config(config_path):
    path = resolve_path(config_path)
    with path.open("r", encoding="utf-8-sig") as f:
        config = json.load(f)
    project_root, gui_root = _placeholder_roots_for_config_path(path)
    config = _expand_placeholders_with_roots(config, project_root, gui_root)
    config = _normalize_legacy_project_paths(
        config,
        preserve_project_root=project_root,
        preserve_gui_root=gui_root,
    )
    config["_config_path"] = str(path)
    return config


def config_base_dir(config):
    return Path(config["_config_path"]).parent


def workspace_root(config):
    return resolve_path(config["运行目录"], base=config_base_dir(config))


def _normalize_path_variant(parts):
    if isinstance(parts, str):
        return (parts,)
    return tuple(str(part) for part in parts if str(part))


def workspace_path_candidates(root, *variants):
    base = Path(root)
    candidates = []
    seen = set()
    for parts in variants:
        normalized = _normalize_path_variant(parts)
        if not normalized:
            continue
        path = base.joinpath(*normalized)
        key = str(path).lower()
        if key in seen:
            continue
        seen.add(key)
        candidates.append(path)
    return candidates


def select_workspace_path(root, *variants):
    candidates = workspace_path_candidates(root, *variants)
    for candidate in candidates:
        if candidate.exists():
            return candidate
    return candidates[0] if candidates else Path(root)


def normalize_dem_kind(value, default="1km"):
    text = str(value or "").strip().lower()
    if not text:
        return default
    if text in {"0p1", "0p1deg", "0.1", "0.1deg", "0p1_degree", "0.1_degree"}:
        return "0p1deg"
    if text in {"1km", "1_km", "1-km"}:
        return "1km"
    return default


def builtin_dem_path(kind="1km"):
    return 内置DEM资产[normalize_dem_kind(kind)]


def default_builtin_dem_path():
    return builtin_dem_path("1km")


def default_builtin_glacier_path():
    return 内置冰川资产


def workspace_dem_filename(kind="1km"):
    return 工作区DEM命名[normalize_dem_kind(kind)]


def _is_close_resolution(value, target, tolerance):
    try:
        return abs(float(value) - float(target)) <= float(tolerance)
    except Exception:
        return False


def infer_dem_kind_from_raster(dem_path):
    path = Path(dem_path)
    lowered = path.name.lower()
    if "0p1" in lowered or "0.1" in lowered:
        return "0p1deg"
    if "1km" in lowered:
        return "1km"
    try:
        with rasterio.open(path) as src:
            res_x = abs(float(src.transform.a)) if src.transform.a else abs(float(src.res[0]))
            res_y = abs(float(src.transform.e)) if src.transform.e else abs(float(src.res[1]))
            crs_text = str(src.crs or "").upper()
    except Exception:
        return "1km"
    if "EPSG:4326" in crs_text or "EPSG:4490" in crs_text:
        if _is_close_resolution(res_x, 0.1, 0.002) and _is_close_resolution(res_y, 0.1, 0.002):
            return "0p1deg"
        if _is_close_resolution(res_x, 1.0 / 120.0, 0.002) and _is_close_resolution(res_y, 1.0 / 120.0, 0.002):
            return "1km"
    return "1km"


def workspace_dem_candidates(gis_dir, prefer=None):
    gis_path = Path(gis_dir)
    preferred_kind = normalize_dem_kind(prefer, default="")
    ordered_kinds = list(DEM分档候选)
    if preferred_kind in ordered_kinds:
        ordered_kinds.remove(preferred_kind)
        ordered_kinds.insert(0, preferred_kind)
    return [gis_path / workspace_dem_filename(kind) for kind in ordered_kinds]


def resolve_workspace_dem_path(gis_dir, prefer=None):
    candidates = workspace_dem_candidates(gis_dir, prefer=prefer)
    for candidate in candidates:
        if candidate.exists():
            return candidate
    return candidates[0]


def remove_other_workspace_dem_variants(gis_dir, keep_path):
    keep = Path(keep_path).resolve(strict=False)
    for candidate in workspace_dem_candidates(gis_dir):
        resolved = candidate.resolve(strict=False)
        if resolved == keep:
            continue
        if candidate.exists():
            candidate.unlink()


def build_workspace_paths(config):
    root = workspace_root(config)
    data_root = select_workspace_path(root, ("数据",), ("data",))
    raw_root = select_workspace_path(root, ("数据", "原始气象"), ("data", "raw"))
    raw_prec_root = select_workspace_path(root, ("数据", "原始气象", "降水"), ("data", "raw", "precipitation"))
    aligned_root = select_workspace_path(root, ("数据", "模型输入"), ("data", "aligned_masked"))
    results_root = select_workspace_path(root, ("结果",), ("results",))
    return {
        "workspace_root": root,
        "data_root": data_root,
        "gis_dir": select_workspace_path(root, ("数据", "地理数据"), ("data", "gis")),
        "observed_dir": select_workspace_path(root, ("数据", "观测数据"), ("data", "observed")),
        "raw_root": raw_root,
        "raw_prec_root": raw_prec_root,
        "raw_prec_era5_dir": select_workspace_path(raw_prec_root, ("ERA5",), ("era5",)),
        "raw_prec_era5_daily_dir": select_workspace_path(raw_prec_root, ("ERA5_日尺度",), ("era5_daily",)),
        "raw_prec_era5_hourly_dir": select_workspace_path(raw_prec_root, ("ERA5_小时尺度",), ("era5_hourly",)),
        "raw_prec_mswep_dir": select_workspace_path(raw_prec_root, ("MSWEP",), ("mswep",)),
        "raw_prec_daily_dir": select_workspace_path(raw_prec_root, ("MSWEP_日尺度",), ("daily",)),
        "raw_prec_hourly_dir": select_workspace_path(raw_prec_root, ("MSWEP_小时尺度",), ("hourly",)),
        "raw_prec_cmfd_dir": select_workspace_path(raw_prec_root, ("CMFD",), ("CMFD",)),
        "raw_prec_cmfd_daily_dir": select_workspace_path(raw_prec_root, ("CMFD_日尺度",), ("cmfd_daily",)),
        "raw_prec_cmfd_hourly_dir": select_workspace_path(raw_prec_root, ("CMFD_小时尺度",), ("cmfd_hourly",)),
        "raw_temp_dir": select_workspace_path(raw_root, ("气温",), ("temperature",)),
        "raw_temp_daily_dir": select_workspace_path(raw_root, ("气温", "日尺度"), ("temperature", "daily")),
        "raw_temp_hourly_dir": select_workspace_path(raw_root, ("气温", "小时尺度"), ("temperature", "hourly")),
        "raw_evap_dir": select_workspace_path(raw_root, ("蒸散发",), ("evaporation",)),
        "raw_evap_daily_dir": select_workspace_path(raw_root, ("蒸散发", "日尺度"), ("evaporation", "daily")),
        "raw_evap_hourly_dir": select_workspace_path(raw_root, ("蒸散发", "小时尺度"), ("evaporation", "hourly")),
        "raw_solar_dir": select_workspace_path(raw_root, ("太阳辐射",), ("solar_radiation",)),
        "raw_wind_dir": select_workspace_path(raw_root, ("风速",), ("wind",)),
        "raw_dewpoint_dir": select_workspace_path(raw_root, ("露点温度",), ("dewpoint",)),
        "aligned_dir": aligned_root,
        "aligned_prec_era5_dir": select_workspace_path(aligned_root, ("降水",), ("precipitation",)),
        "aligned_prec_dir": select_workspace_path(aligned_root, ("降水_MSWEP",), ("prec",)),
        "aligned_prec_cmfd_dir": select_workspace_path(aligned_root, ("降水_CMFD",), ("prec_cmfd",)),
        "aligned_temp_dir": select_workspace_path(aligned_root, ("气温",), ("temp",)),
        "aligned_evap_dir": select_workspace_path(aligned_root, ("蒸散发",), ("evap",)),
        "glacier_melt_dir": select_workspace_path(aligned_root, ("冰川融水",), ("glacier_melt",)),
        "results_root": results_root,
        "runs_dir": select_workspace_path(results_root, ("运行记录",), ("runs",)),
        "figures_dir": select_workspace_path(results_root, ("图件",), ("figures",)),
        "logs_dir": select_workspace_path(results_root, ("日志",), ("logs",)),
        "cache_dir": select_workspace_path(results_root, ("缓存",), ("cache",)),
    }


默认工作区目录键 = (
    "workspace_root",
    "data_root",
    "gis_dir",
    "observed_dir",
    "raw_root",
    "aligned_dir",
    "results_root",
)


def ensure_workspace_dirs(paths, required_keys=None):
    keys = tuple(required_keys or 默认工作区目录键)
    created = set()
    for key in keys:
        path = paths.get(key)
        if not isinstance(path, Path):
            continue
        resolved = path.resolve(strict=False)
        if resolved in created:
            continue
        path.mkdir(parents=True, exist_ok=True)
        created.add(resolved)


def add_hapi_src(config):
    return None


def old_script_path(config, *parts):
    key = tuple(parts)
    if key not in 模块路径映射:
        raise KeyError(f"未定义的模块路径映射: {key}")
    return 模块路径映射[key]


def load_legacy_module(script_path):
    script_path = Path(script_path)
    if not script_path.exists() and script_path.suffix.lower() == ".py":
        pyc_path = script_path.with_suffix(".pyc")
        if pyc_path.exists():
            script_path = pyc_path
    module_hash = hashlib.sha1(str(script_path.resolve()).encode("utf-8")).hexdigest()[:12]
    module_name = f"local_{script_path.stem}_{module_hash}"
    sys.modules.pop(module_name, None)
    spec = importlib.util.spec_from_file_location(module_name, script_path)
    if spec is None or spec.loader is None:
        raise ImportError(f"无法加载脚本: {script_path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


def patch_module(module, mapping):
    for key, value in mapping.items():
        setattr(module, key, value)
    refresh = getattr(module, "refresh_workspace_paths", None)
    if callable(refresh):
        refresh()


def _is_ascii_path(value):
    try:
        str(value).encode("ascii")
        return True
    except UnicodeEncodeError:
        return False


def _windows_short_path(path):
    if os.name != "nt":
        return None
    try:
        import ctypes

        source = str(Path(path).resolve(strict=False))
        buffer = ctypes.create_unicode_buffer(32768)
        result = ctypes.windll.kernel32.GetShortPathNameW(source, buffer, len(buffer))
        if result <= 0:
            return None
        short_path = buffer.value
        return short_path or None
    except Exception:
        return None


def _ascii_temp_roots(source_path):
    source = Path(source_path)
    candidates = []
    if source.drive:
        candidates.append(Path(f"{source.drive}\\HBVStudio_ascii_nc_cache"))
    public_root = os.environ.get("PUBLIC", "").strip()
    if public_root:
        candidates.append(Path(public_root) / "HBVStudio_ascii_nc_cache")
    candidates.append(Path(tempfile.gettempdir()) / "HBVStudio_ascii_nc_cache")

    seen = set()
    for candidate in candidates:
        text = str(candidate)
        if (not text) or (not _is_ascii_path(text)):
            continue
        key = text.lower()
        if key in seen:
            continue
        seen.add(key)
        yield candidate


def _copy_file_to_ascii_temp(source_path):
    source = Path(source_path).resolve(strict=False)
    safe_stem = "".join(
        ch if ch.isascii() and (ch.isalnum() or ch in "._-") else "_"
        for ch in source.stem
    ).strip("._") or "dataset"
    try:
        stat = source.stat()
        fingerprint = f"{source}|{stat.st_size}|{stat.st_mtime_ns}"
    except Exception:
        fingerprint = str(source)
    digest = hashlib.sha1(fingerprint.encode("utf-8", errors="ignore")).hexdigest()[:12]

    last_error = None
    for root in _ascii_temp_roots(source):
        temp_dir = None
        try:
            root.mkdir(parents=True, exist_ok=True)
            temp_dir = Path(tempfile.mkdtemp(prefix="nc_", dir=str(root)))
            suffix = source.suffix or ".nc"
            target = temp_dir / f"{safe_stem}_{digest}{suffix}"
            shutil.copy2(source, target)
            if _is_ascii_path(target):
                return target, temp_dir
        except Exception as exc:
            last_error = exc
            if temp_dir is not None:
                shutil.rmtree(temp_dir, ignore_errors=True)
    raise RuntimeError(f"无法为 NetCDF 文件创建 ASCII 临时副本：{source}") from last_error


@contextlib.contextmanager
def open_netcdf_dataset_safe(dataset_path, *, engine="netcdf4", **kwargs):
    import xarray as xr

    source = Path(dataset_path).expanduser().resolve(strict=False)
    attempts = []

    def _open(candidate):
        return xr.open_dataset(candidate, engine=engine, **kwargs)

    candidates = [source]
    short_path = _windows_short_path(source)
    if short_path:
        short_candidate = Path(short_path)
        if str(short_candidate).lower() != str(source).lower():
            candidates.append(short_candidate)

    for candidate in candidates:
        try:
            dataset = _open(candidate)
            try:
                yield dataset
            finally:
                dataset.close()
            return
        except Exception as exc:
            attempts.append((str(candidate), exc))

    temp_dir = None
    temp_copy = None
    try:
        temp_copy, temp_dir = _copy_file_to_ascii_temp(source)
        dataset = _open(temp_copy)
        try:
            yield dataset
        finally:
            dataset.close()
        return
    except Exception as exc:
        attempts.append((str(temp_copy or source), exc))
        details = " ; ".join(
            f"{path}: {type(err).__name__}: {err}"
            for path, err in attempts[-3:]
        )
        raise RuntimeError(
            f"无法打开 NetCDF 文件：{source}。已尝试原路径、短路径和 ASCII 临时副本。{details}"
        ) from exc
    finally:
        if temp_dir is not None:
            shutil.rmtree(temp_dir, ignore_errors=True)


@contextlib.contextmanager
def temporary_argv(argv):
    old_argv = sys.argv[:]
    sys.argv = argv[:]
    try:
        yield
    finally:
        sys.argv = old_argv


def time_settings(config):
    return config["时间"]


def year_range(config):
    settings = time_settings(config)
    return range(int(settings["开始年份"]), int(settings["结束年份"]) + 1)


def bbox_list(config):
    bbox = config["范围_bbox"]
    return [bbox["北"], bbox["西"], bbox["南"], bbox["东"]]


def expand_era5_bbox(bbox, padding_degrees=0.2):
    north, west, south, east = [float(value) for value in bbox]
    pad = max(float(padding_degrees), 0.0)
    return [
        min(90.0, north + pad),
        max(-180.0, west - pad),
        max(-90.0, south - pad),
        min(180.0, east + pad),
    ]


def era5_download_bbox_list(config, padding_degrees=0.2):
    return expand_era5_bbox(bbox_list(config), padding_degrees=padding_degrees)


def bbox_dict(config):
    bbox = config["范围_bbox"]
    return {
        "lon_min": bbox["西"],
        "lon_max": bbox["东"],
        "lat_min": bbox["南"],
        "lat_max": bbox["北"],
    }


def expected_days(config):
    import pandas as pd

    settings = time_settings(config)
    start_date = f"{int(settings['开始年份'])}-01-01"
    end_date = f"{int(settings['结束年份'])}-12-31"
    return len(pd.date_range(start_date, end_date, freq="D"))


def basin_paths(config):
    base = config_base_dir(config)
    return {
        "basin_shp": resolve_path(config["流域边界_shp"], base=base),
        "raw_dem": resolve_path(config.get("DEM_tif", config.get("原始DEM_tif")), base=base),
        "obs_csv": resolve_path(config["观测径流_csv"], base=base),
        "glacier_shp": resolve_path(config.get("冰川边界_shp", ""), base=base),
    }


def 边界条件配置(config):
    section = config.get("边界条件", {})
    base = config_base_dir(config)
    return {
        "上游边界入流_csv": resolve_path(section.get("上游边界入流_csv", ""), base=base),
        "时间字段": section.get("时间字段", "date"),
        "流量字段": section.get("流量字段", "inflow_m3s"),
        "缺失填补": section.get("缺失填补", "zero"),
    }




def cfmax_zone_threshold(config):
    threshold_cfg = config.get("CFMAX分区阈值_m", 5000.0)
    if isinstance(threshold_cfg, dict):
        if "分界高程" in threshold_cfg:
            threshold = float(threshold_cfg["分界高程"])
        elif "阈值" in threshold_cfg:
            threshold = float(threshold_cfg["阈值"])
        elif "高海拔下限" in threshold_cfg:
            threshold = float(threshold_cfg["高海拔下限"])
        else:
            threshold = 5000.0
    else:
        threshold = float(threshold_cfg)
    return threshold


def cfmax_zone_thresholds(config):
    threshold = cfmax_zone_threshold(config)
    return threshold, threshold


def time_step_hours(config):
    return float(config.get("时间步长_小时", 24.0))


def mask_raster_to_basin(input_file, output_file, basin_shp):
    basin = gpd.read_file(str(basin_shp))
    with rasterio.open(input_file) as src:
        basin_reproj = basin.to_crs(src.crs)
        nodata = src.nodata if src.nodata is not None else -9999
        out_image, _ = mask(src, basin_reproj.geometry, crop=False, nodata=nodata)
        meta = src.meta.copy()
        meta.update(nodata=nodata, compress="lzw")
        output_file = Path(output_file)
        output_file.parent.mkdir(parents=True, exist_ok=True)
        with rasterio.open(output_file, "w", **meta) as dst:
            dst.write(out_image)


def print_config_summary(config, paths):
    zone_threshold = cfmax_zone_threshold(config)
    step_hours = time_step_hours(config)
    流域名称 = config.get("流域名称", config.get("流域名称_中文", "未命名流域"))
    流域编号 = config.get("流域编号", config.get("流域名称_英文", "unknown"))
    print("=" * 72)
    print("当前配置")
    print("=" * 72)
    print(f"流域名称: {流域名称}")
    print(f"流域编号: {流域编号}")
    print(f"运行目录: {paths['workspace_root']}")
    print(f"默认降水源: {config.get('默认降水源', 'era5')}")
    print(f"时间步长: {step_hours:.3f} h")
    print(f"CFMAX 分区阈值: {zone_threshold:.1f} m")
    print("=" * 72)
