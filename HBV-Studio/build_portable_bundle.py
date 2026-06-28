#!/usr/bin/env python
# -*- coding: utf-8 -*-
from __future__ import annotations

import importlib.util
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any


def env_path(name: str) -> Path | None:
    raw = str(os.environ.get(name, "")).strip()
    if not raw:
        return None
    return Path(raw).expanduser().resolve(strict=False)


PROJECT_ROOT = Path(__file__).resolve().parents[1]
GUI_ROOT = PROJECT_ROOT / "HBV-Studio"
RELEASE_DOCS_SOURCE = PROJECT_ROOT.parent / "docs" / "release"
BRANDING_ICON = GUI_ROOT / "installer_assets" / "HBVStudio.ico"
DEFAULT_F_DRIVE_ROOT = PROJECT_ROOT.parent / "_build_temp" / "portable_bundle"
DIST_PARENT = env_path("HBV_STUDIO_PORTABLE_DIST_PARENT") or (DEFAULT_F_DRIVE_ROOT / "dist")
DEFAULT_BUILD_ROOT = env_path("HBV_STUDIO_PORTABLE_BUILD_ROOT") or (DEFAULT_F_DRIVE_ROOT / "work")
FALLBACK_BUILD_ROOT = env_path("HBV_STUDIO_PORTABLE_FALLBACK_BUILD_ROOT") or (DEFAULT_F_DRIVE_ROOT / "fallback")
BUNDLE_NAME = "HBVStudio_Demo"
LEGACY_BUNDLE_NAMES = (
    "HBVStudio_正式测试便携版",
    "HBVStudio_便携版",
)
BUNDLE_DIR = DIST_PARENT / BUNDLE_NAME
WORKSPACE_NAME = "正式测试"
FALLBACK_TEMPLATE_NAME = "沱沱河"
BUILTIN_DEM_NAMES = (
    "青藏高原_1km_DEM.tif",
    "青藏高原_0p1deg_DEM.tif",
)

COLLECT_ALL_PACKAGES = [
    "affine",
    "cdsapi",
    "fiona",
    "pyogrio",
    "pyproj",
    "rasterio",
    "shapely",
    "netCDF4",
    "cftime",
    "whitebox",
    "openpyxl",
    "xlrd",
    "xlsxwriter",
]

HIDDEN_IMPORTS = [
    "geopandas",
    "numba",
    "numpy",
    "pandas",
    "requests",
    "scipy",
    "scipy.optimize",
    "xarray",
    "whitebox",
    "whitebox.whitebox_tools",
]

EXCLUDED_MODULES = [
    "torch",
    "tensorflow",
    "cv2",
    "onnxruntime",
    "sklearn",
    "skimage",
    "statsmodels",
    "IPython",
]

STUDIO_FILES = [
    "app_bootstrap.py",
    "launch.py",
    "server.py",
    "studio_service.py",
    "create_hourly_workspace.py",
    "forecast_run.py",
    "profile_runner.py",
    "forward_run.py",
    "precipitation_strategy_runner.py",
    "sync_tuotuohe_data.py",
]

STUDIO_DIRS = [
    "services",
]

PUBLIC_DOC_FILES = [
    "HBV-Studio_正式用户说明.md",
    "data_request_checklist.md",
    "precipitation_strategy.md",
]

IGNORE_NAMES = {
    "__pycache__",
    ".pytest_cache",
    ".mypy_cache",
    "server_stdout.log",
    "server_stderr.log",
}


def resolve_build_root() -> Path:
    for candidate in (DEFAULT_BUILD_ROOT, FALLBACK_BUILD_ROOT):
        try:
            candidate.parent.mkdir(parents=True, exist_ok=True)
            if candidate.exists():
                shutil.rmtree(candidate, ignore_errors=True)
            candidate.mkdir(parents=True, exist_ok=True)
            return candidate
        except PermissionError:
            continue
    raise PermissionError(
        f"无法创建 PyInstaller 工作目录：{DEFAULT_BUILD_ROOT} 或 {FALLBACK_BUILD_ROOT}"
    )


def copy_tree(src: Path, dst: Path) -> None:
    if not src.exists():
        return

    def ignore(_: str, names: list[str]) -> set[str]:
        return {name for name in names if name in IGNORE_NAMES}

    shutil.copytree(src, dst, dirs_exist_ok=True, ignore=ignore)


def copy_public_docs(src: Path, dst: Path) -> None:
    if not src.exists():
        return
    if dst.exists():
        shutil.rmtree(dst)
    dst.mkdir(parents=True, exist_ok=True)
    for name in PUBLIC_DOC_FILES:
        item = src / name
        if item.exists() and item.is_file():
            shutil.copy2(item, dst / name)


def copy_release_docs(bundle_root: Path) -> None:
    if not RELEASE_DOCS_SOURCE.exists():
        return
    dst = bundle_root / "docs" / "release"
    if dst.exists():
        shutil.rmtree(dst)
    dst.mkdir(parents=True, exist_ok=True)
    for item in RELEASE_DOCS_SOURCE.iterdir():
        if item.is_file():
            shutil.copy2(item, dst / item.name)


def candidate_paths(root: Path, *variants: tuple[str, ...]) -> list[Path]:
    base = Path(root)
    results: list[Path] = []
    seen: set[str] = set()
    for parts in variants:
        path = base.joinpath(*parts)
        key = str(path).lower()
        if key in seen:
            continue
        seen.add(key)
        results.append(path)
    return results


def pick_path(root: Path, *variants: tuple[str, ...]) -> Path:
    candidates = candidate_paths(root, *variants)
    for path in candidates:
        if path.exists():
            return path
    return candidates[0]


def runtime_workspace_root(base: Path, workspace_name: str) -> Path:
    return base / "运行目录" / workspace_name


def runtime_data_root(base: Path, workspace_name: str) -> Path:
    return pick_path(runtime_workspace_root(base, workspace_name), ("数据",), ("data",))


def runtime_results_root(base: Path, workspace_name: str) -> Path:
    return pick_path(runtime_workspace_root(base, workspace_name), ("结果",), ("results",))


def installed_package(name: str) -> bool:
    return importlib.util.find_spec(name) is not None


def run_pyinstaller() -> None:
    build_root = resolve_build_root()
    cmd = [
        sys.executable,
        "-m",
        "PyInstaller",
        "--noconfirm",
        "--clean",
        "--onedir",
        "--console",
        "--name",
        BUNDLE_NAME,
        "--distpath",
        str(DIST_PARENT),
        "--workpath",
        str(build_root / "work"),
        "--specpath",
        str(build_root / "spec"),
        str(GUI_ROOT / "app_bootstrap.py"),
    ]
    if BRANDING_ICON.exists():
        cmd.extend(["--icon", str(BRANDING_ICON.resolve())])
    for package in COLLECT_ALL_PACKAGES:
        if installed_package(package):
            cmd.extend(["--collect-all", package])
    for module in HIDDEN_IMPORTS:
        if installed_package(module.split(".", 1)[0]):
            cmd.extend(["--hidden-import", module])
    for module in EXCLUDED_MODULES:
        cmd.extend(["--exclude-module", module])
    subprocess.run(cmd, cwd=str(PROJECT_ROOT), check=True)


def copy_plotly_js(bundle_gui_root: Path) -> None:
    try:
        import plotly  # type: ignore
    except Exception:
        return
    src = Path(plotly.__file__).resolve().parent / "package_data" / "plotly.min.js"
    if src.exists():
        shutil.copy2(src, bundle_gui_root / "web" / "plotly.min.js")


def write_portable_workspace(bundle_gui_root: Path) -> None:
    workspaces_dir = bundle_gui_root / "workspaces"
    workspaces_dir.mkdir(parents=True, exist_ok=True)
    prefix_pairs = [
        (str(GUI_ROOT.resolve(strict=False)), "__GUI_ROOT__"),
        (str(PROJECT_ROOT.resolve(strict=False)), "__PROJECT_ROOT__"),
    ]

    for src in sorted((GUI_ROOT / "workspaces").glob("*.json")):
        with src.open("r", encoding="utf-8-sig") as f:
            config = json.load(f)
        config = _rewrite_json_value(config, prefix_pairs)

        if src.stem == WORKSPACE_NAME:
            runtime_root = "__PROJECT_ROOT__/运行目录/正式测试"
            config["运行目录"] = runtime_root
            config["流域边界_shp"] = f"{runtime_root}/数据/地理数据/tuotuohe_basin.shp"
            config["DEM_tif"] = f"{runtime_root}/数据/地理数据/dem_1km.tif"
            config["观测径流_csv"] = f"{runtime_root}/数据/观测数据/discharge_tuotuohe.csv"
            config["冰川边界_shp"] = f"{runtime_root}/数据/地理数据/glacier_shp/glacier.shp"

            meteo = dict(config.get("气象策略", {}))
            source_value = str(meteo.get("降水来源", "")).strip().lower()
            legacy_source = str(meteo.get("降水源", "")).strip().lower()
            top_level_source = str(config.get("默认降水源", "")).strip().lower()
            if not source_value:
                if top_level_source in {"era5", "cmfd", "custom_tif"} and legacy_source in {"", "mswep"}:
                    source_value = top_level_source
                else:
                    source_value = legacy_source or top_level_source or "era5"
            meteo["降水来源"] = source_value
            meteo["降水源"] = source_value
            config["默认降水源"] = source_value
            meteo["自带降水tif目录"] = (
                f"{runtime_root}/数据/模型输入/降水_本地导入"
                if source_value == "custom_tif"
                else f"{runtime_root}/数据/模型输入/降水"
            )
            meteo["自带温度tif目录"] = f"{runtime_root}/数据/模型输入/气温"
            meteo["自带蒸散发tif目录"] = f"{runtime_root}/数据/模型输入/蒸散发"
            config["气象策略"] = meteo

        with (workspaces_dir / src.name).open("w", encoding="utf-8") as f:
            json.dump(config, f, ensure_ascii=False, indent=2)


def _copy_bundle_runtime_data(bundle_root: Path) -> None:
    src_data_root = runtime_data_root(PROJECT_ROOT, WORKSPACE_NAME)
    fallback_data_root = runtime_data_root(PROJECT_ROOT, FALLBACK_TEMPLATE_NAME)

    dst_runtime_root = runtime_workspace_root(bundle_root, WORKSPACE_NAME)
    dst_data_root = dst_runtime_root / "数据"

    copy_tree(pick_path(src_data_root, ("模型输入",), ("aligned_masked",)), dst_data_root / "模型输入")
    copy_tree(pick_path(src_data_root, ("地理数据",), ("gis",)), dst_data_root / "地理数据")
    copy_tree(pick_path(src_data_root, ("原始气象",), ("raw",)), dst_data_root / "原始气象")
    (dst_data_root / "观测数据").mkdir(parents=True, exist_ok=True)

    src_gis_root = pick_path(src_data_root, ("地理数据",), ("gis",))
    fallback_gis_root = pick_path(fallback_data_root, ("地理数据",), ("gis",))
    basin_shp_files = list(src_gis_root.glob("tuotuohe_basin.*")) or list(fallback_gis_root.glob("tuotuohe_basin.*"))
    for shp_file in basin_shp_files:
        shutil.copy2(shp_file, dst_data_root / "地理数据" / shp_file.name)

    glacier_shp_src = src_gis_root / "glacier_shp"
    if not glacier_shp_src.exists():
        glacier_shp_src = fallback_gis_root / "glacier_shp"
    if glacier_shp_src.exists():
        copy_tree(glacier_shp_src, dst_data_root / "地理数据" / "glacier_shp")

    src_obs_root = pick_path(src_data_root, ("观测数据",), ("observed",))
    fallback_obs_root = pick_path(fallback_data_root, ("观测数据",), ("observed",))
    for obs_src in (
        src_obs_root / "discharge_tuotuohe.csv",
        fallback_obs_root / "discharge_tuotuohe.csv",
    ):
        if obs_src.exists():
            shutil.copy2(obs_src, dst_data_root / "观测数据" / obs_src.name)
            break


def _copy_bundle_runtime_results(bundle_root: Path) -> None:
    src_results_root = runtime_results_root(PROJECT_ROOT, WORKSPACE_NAME)
    dst_results_root = runtime_workspace_root(bundle_root, WORKSPACE_NAME) / "结果"
    copy_tree(src_results_root, dst_results_root)

    # Copied caches and logs are runtime artifacts from the source machine.
    # Cache tokens embed absolute paths, and old logs only add stale diagnostics noise.
    for transient_dir in (
        list(dst_results_root.rglob("缓存"))
        + list(dst_results_root.rglob("cache"))
        + list(dst_results_root.rglob("日志"))
        + list(dst_results_root.rglob("logs"))
    ):
        if not transient_dir.is_dir():
            continue
        shutil.rmtree(transient_dir, ignore_errors=True)
        transient_dir.mkdir(parents=True, exist_ok=True)

    for subdir in [
        dst_results_root,
        dst_results_root / "日尺度" / "运行记录",
        dst_results_root / "日尺度" / "日志",
        dst_results_root / "日尺度" / "缓存",
        dst_results_root / "小时尺度" / "运行记录",
        dst_results_root / "小时尺度" / "日志",
        dst_results_root / "小时尺度" / "缓存",
    ]:
        subdir.mkdir(parents=True, exist_ok=True)


def copy_runtime_template_data(bundle_root: Path) -> None:
    _copy_bundle_runtime_data(bundle_root)
    _copy_bundle_runtime_results(bundle_root)


def _rewrite_json_value(value: Any, prefix_pairs: list[tuple[str, str]]) -> Any:
    if isinstance(value, dict):
        return {key: _rewrite_json_value(item, prefix_pairs) for key, item in value.items()}
    if isinstance(value, list):
        return [_rewrite_json_value(item, prefix_pairs) for item in value]
    if not isinstance(value, str):
        return value

    normalized = value.replace("/", "\\")
    normalized_lower = normalized.lower()
    for source_prefix, target_prefix in prefix_pairs:
        source_norm = source_prefix.replace("/", "\\").rstrip("\\")
        target_norm = target_prefix.rstrip("/")
        source_lower = source_norm.lower()
        if normalized_lower != source_lower and not normalized_lower.startswith(source_lower + "\\"):
            continue
        suffix = normalized[len(source_norm):].lstrip("\\/")
        if not suffix:
            return target_norm
        return target_norm + "/" + suffix.replace("\\", "/")
    legacy_markers = (
        ("\\hbv-studio\\", "__GUI_ROOT__"),
        ("\\workspaces\\", "__GUI_ROOT__/workspaces"),
        ("\\运行目录\\", "__PROJECT_ROOT__/运行目录"),
        ("\\runtime\\", "__PROJECT_ROOT__/运行目录"),
        ("\\hbv-cryo\\", "__PROJECT_ROOT__/HBV-Cryo"),
        ("\\数据准备\\", "__PROJECT_ROOT__/数据准备"),
        ("\\基础数据\\", "__PROJECT_ROOT__/基础数据"),
    )
    for marker, target_prefix in legacy_markers:
        marker_lower = marker.lower()
        idx = normalized_lower.find(marker_lower)
        if idx < 0:
            suffix_marker = marker_lower.rstrip("\\")
            if not normalized_lower.endswith(suffix_marker):
                continue
            suffix = ""
        else:
            suffix = normalized[idx + len(marker):].lstrip("\\/")
        if not suffix:
            return target_prefix
        return target_prefix + "/" + suffix.replace("\\", "/")
    return value


def _invalidate_removed_runtime_cache(value: Any) -> Any:
    if not isinstance(value, dict):
        return value
    cache = value.get("data_cache")
    if not isinstance(cache, dict):
        return value
    updated_cache: dict[str, Any] = {}
    changed = False
    for key, item in cache.items():
        if not isinstance(item, dict):
            updated_cache[key] = item
            continue
        current = dict(item)
        if current.get("cache_hit"):
            current["cache_hit"] = False
            changed = True
        if current.get("cache_path"):
            current["cache_path"] = ""
            changed = True
        if current.get("source_dir"):
            current["source_dir"] = ""
            changed = True
        if current.get("directory"):
            current["directory"] = ""
            changed = True
        updated_cache[key] = current
    if not changed:
        return value
    updated = dict(value)
    updated["data_cache"] = updated_cache
    return updated


def rewrite_runtime_json_paths(bundle_root: Path) -> None:
    runtime_root = runtime_workspace_root(bundle_root, WORKSPACE_NAME)
    if not runtime_root.exists():
        return

    bundle_gui_root = bundle_root / "HBV-Studio"
    prefix_pairs = [
        (str(GUI_ROOT.resolve(strict=False)), "__GUI_ROOT__"),
        (str(PROJECT_ROOT.resolve(strict=False)), "__PROJECT_ROOT__"),
        (str(bundle_gui_root.resolve(strict=False)), "__GUI_ROOT__"),
        (str(bundle_root.resolve(strict=False)), "__PROJECT_ROOT__"),
    ]

    for json_path in runtime_root.rglob("*.json"):
        try:
            with json_path.open("r", encoding="utf-8-sig") as f:
                payload = json.load(f)
        except Exception:
            continue
        rewritten = _rewrite_json_value(payload, prefix_pairs)
        if json_path.name.lower() == "metadata.json":
            rewritten = _invalidate_removed_runtime_cache(rewritten)
        if rewritten == payload:
            continue
        with json_path.open("w", encoding="utf-8") as f:
            json.dump(rewritten, f, ensure_ascii=False, indent=2)


def copy_project_files(bundle_root: Path) -> None:
    bundle_gui_root = bundle_root / "HBV-Studio"
    bundle_gui_root.mkdir(parents=True, exist_ok=True)

    for name in STUDIO_FILES:
        shutil.copy2(GUI_ROOT / name, bundle_gui_root / name)

    for name in STUDIO_DIRS:
        copy_tree(GUI_ROOT / name, bundle_gui_root / name)

    copy_tree(GUI_ROOT / "web", bundle_gui_root / "web")
    copy_tree(GUI_ROOT / "templates", bundle_gui_root / "templates")
    copy_public_docs(GUI_ROOT / "docs", bundle_gui_root / "docs")
    copy_release_docs(bundle_root)
    copy_tree(GUI_ROOT / "installer_assets", bundle_gui_root / "installer_assets")
    copy_plotly_js(bundle_gui_root)
    write_portable_workspace(bundle_gui_root)

    copy_tree(PROJECT_ROOT / "公共", bundle_root / "公共")
    copy_tree(PROJECT_ROOT / "HBV-Cryo", bundle_root / "HBV-Cryo")
    copy_tree(PROJECT_ROOT / "数据准备", bundle_root / "数据准备")
    shutil.copy2(PROJECT_ROOT / "系统自检.py", bundle_root / "系统自检.py")

    dem_dst_root = bundle_root / "基础数据" / "DEM源"
    dem_dst_root.mkdir(parents=True, exist_ok=True)
    for dem_name in BUILTIN_DEM_NAMES:
        dem_src = PROJECT_ROOT / "基础数据" / "DEM源" / dem_name
        if not dem_src.exists():
            continue
        shutil.copy2(dem_src, dem_dst_root / dem_src.name)

    copy_runtime_template_data(bundle_root)
    rewrite_runtime_json_paths(bundle_root)


def write_readme(bundle_root: Path) -> None:
    text = "\n".join(
        [
            "HBV-Studio Demo（沱沱河演示包）",
            "",
            "启动方式：",
            f"1. 双击 {BUNDLE_NAME}.exe",
            "2. 首次启动会直接打开本地浏览器界面",
            "",
            "内置内容：",
            "- 预置工作区：正式测试（沱沱河流域完整数据）",
            "- 内置 DEM、流域边界、冰川边界、气温/降水/蒸散发栅格、观测径流",
            "- 可直接运行率定、正向模拟、结果分析，无需额外数据准备",
            "",
            "用途：",
            "- 移植到其他电脑上快速验证 HBV-Studio 功能完整性",
            "- 结果写在本目录下 运行目录/正式测试/结果 中",
        ]
    )
    (bundle_root / "README.txt").write_text(text, encoding="utf-8")


def main() -> None:
    for legacy_name in LEGACY_BUNDLE_NAMES:
        legacy_dir = DIST_PARENT / legacy_name
        if legacy_dir == BUNDLE_DIR:
            continue
        if legacy_dir.exists():
            shutil.rmtree(legacy_dir, ignore_errors=True)
    if BUNDLE_DIR.exists():
        shutil.rmtree(BUNDLE_DIR, ignore_errors=True)
    run_pyinstaller()
    copy_project_files(BUNDLE_DIR)
    write_readme(BUNDLE_DIR)
    print(f"打包完成：{BUNDLE_DIR}")
    print(f"主程序：{BUNDLE_DIR / (BUNDLE_NAME + '.exe')}")


if __name__ == "__main__":
    main()
