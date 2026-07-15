#!/usr/bin/env python
# -*- coding: utf-8 -*-
from __future__ import annotations

import argparse
import hashlib
import json
import os
import py_compile
import re
import shutil
import subprocess
import sys
import zipfile
from datetime import datetime
from pathlib import Path

import build_portable_bundle as portable


def env_path(name: str) -> Path | None:
    raw = str(os.environ.get(name, "")).strip()
    if not raw:
        return None
    return Path(raw).expanduser().resolve(strict=False)


CN_PUBLIC = "\u516c\u5171"
CN_DATA_PREP = "\u6570\u636e\u51c6\u5907"
CN_CONFIG = "\u914d\u7f6e"
CN_BASE_DATA = "\u57fa\u7840\u6570\u636e"
CN_DEM_DIR = "DEM\u6e90"
CN_SELF_CHECK = "\u7cfb\u7edf\u81ea\u68c0.py"

PROJECT_ROOT = portable.PROJECT_ROOT
GUI_ROOT = portable.GUI_ROOT
APP_NAME = "HBVStudio"
APP_EXE_NAME = f"{APP_NAME}.exe"
PAYLOAD_NAME = "HBVStudio_payload.zip"
DEFAULT_F_PACKAGING_ROOT = (PROJECT_ROOT.parent / "_build_temp" / "installer_packaging").resolve()
PACKAGING_ROOT = env_path("HBV_STUDIO_PACKAGING_ROOT") or DEFAULT_F_PACKAGING_ROOT

COMMON_SOURCE = portable.pick_path(PROJECT_ROOT, (CN_PUBLIC,), ("common",))
PREP_SOURCE = portable.pick_path(PROJECT_ROOT, (CN_DATA_PREP,), ("data_prep",))
CONFIG_SOURCE = portable.pick_path(PROJECT_ROOT, (CN_CONFIG,), ("config",))
BASE_DATA_SOURCE = portable.pick_path(PROJECT_ROOT, (CN_BASE_DATA,), ("base_data",))
DEM_SOURCE_DIR = portable.pick_path(BASE_DATA_SOURCE, (CN_DEM_DIR,), ("dem",))
GLACIER_SOURCE_ROOT = portable.pick_path(BASE_DATA_SOURCE, ("冰川源",), ("glacier",))
GLACIER_SOURCE_DIR = GLACIER_SOURCE_ROOT / "Second_Glacier_Inventory_China"
DEFAULT_DEM_NAME = "\u9752\u85cf\u9ad8\u539f_1km_DEM.tif"
SECONDARY_DEM_NAME = "\u9752\u85cf\u9ad8\u539f_0p1deg_DEM.tif"
GLACIER_REQUIRED_SUFFIXES = {".shp", ".dbf", ".shx", ".prj"}

STAGE_PARENT = PACKAGING_ROOT / "installer_stage"
WINDOWED_BUILD_ROOT = PACKAGING_ROOT / "installer_pyinstaller"
LEGACY_ONEFILE_BUILD_ROOT = PACKAGING_ROOT / "installer_onefile"
INNO_BUILD_ROOT = PACKAGING_ROOT / "installer_inno"
OUTPUT_DIR = PACKAGING_ROOT / "output"
BRANDING_ICON = GUI_ROOT / "installer_assets" / "HBVStudio.ico"
SHORTCUT_ICON_RELATIVE = Path("HBV-Studio") / "installer_assets" / "HBVStudio.ico"

ALLOWED_TIF_RELATIVE_PATHS = {
    Path(CN_BASE_DATA) / CN_DEM_DIR / DEFAULT_DEM_NAME,
    Path(CN_BASE_DATA) / CN_DEM_DIR / SECONDARY_DEM_NAME,
}
EXCLUDED_PAYLOAD_PREFIXES = {
    Path("_internal") / "whitebox" / "testdata",
}
INSTALLER_EXCLUDED_TEMPLATE_FILES = {
    "tuotuohe_daily_builtin.template.json",
}
INSTALLER_EXCLUDED_TEMPLATE_ASSET_DIRS = {
    "tuotuohe",
}
INSTALLER_EXCLUDED_CONFIG_FILES = {
    "\u6cb1\u6cb1\u6cb3_\u9a8c\u8bc1.json",
}
INSTALLER_PRUNE_PATHS = {
    Path("_internal") / "whitebox" / "testdata",
    Path("docs"),
    Path("HBV-Studio") / "docs",
    Path("README.md"),
    Path("requirements.txt"),
}
INSTALLER_PRUNE_SUFFIXES = {".md", ".pdf", ".docx", ".pptx"}

INNO_APP_ID = "{{9B8D0C43-8A7F-4B7D-9E54-79A67A8A1BB1}}"

BUILD_CONTRACTS = {
    "daily_forcing_manifest": "hbv_cryo_daily_forcing_manifest_v1",
    "precipitation_correction": "occurrence_amount_v2",
    "state_snapshot": "per_cell_branch_states_v2",
    "model_water_balance": "hbv_cryo_model_water_balance_v1",
    "hourly_forcing_manifest": "hbv_cryo_hourly_forcing_generator_v2",
    "era5_accumulation_boundary": "hbv_cryo_era5_accumulation_following_midnight_v1",
    "path_memory": "hbvstudio.pathBrowser.lastDirectory.v1",
}


def prepare_clean_dir(path: Path) -> Path:
    if path.exists():
        shutil.rmtree(path, ignore_errors=True)
    path.mkdir(parents=True, exist_ok=True)
    return path


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest().upper()


def git_text(*arguments: str) -> str:
    result = subprocess.run(
        ["git", "-C", str(PROJECT_ROOT), *arguments],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    return result.stdout.strip() if result.returncode == 0 else ""


def source_version() -> str:
    text = (GUI_ROOT / "studio_service.py").read_text(encoding="utf-8")
    match = re.search(r'^APP_VERSION\s*=\s*["\']([^"\']+)["\']', text, flags=re.MULTILINE)
    return match.group(1) if match else ""


def parse_ahead_behind_counts(value: str) -> tuple[int | None, int | None]:
    """Parse ``git rev-list --left-right --count HEAD...upstream`` output."""
    parts = str(value or "").split()
    if len(parts) != 2:
        return None, None
    try:
        # Left is reachable only from HEAD (ahead); right only from upstream (behind).
        return int(parts[0]), int(parts[1])
    except ValueError:
        return None, None


def build_source_records() -> list[dict[str, object]]:
    candidates = [GUI_ROOT / name for name in portable.STUDIO_FILES]
    candidates.extend((GUI_ROOT / "services").glob("*.py"))
    candidates.extend((GUI_ROOT / "web").rglob("*.js"))
    candidates.extend((GUI_ROOT / "web").rglob("*.html"))
    candidates.extend((GUI_ROOT / "web").rglob("*.css"))
    candidates.extend((PROJECT_ROOT / "HBV-Cryo").glob("*.py"))
    candidates.extend((PROJECT_ROOT / CN_PUBLIC).rglob("*.py"))
    candidates.extend((PROJECT_ROOT / CN_DATA_PREP).rglob("*.py"))
    records = []
    for path in sorted({item.resolve() for item in candidates if item.is_file()}):
        records.append(
            {
                "path": str(path.relative_to(PROJECT_ROOT.resolve())).replace("\\", "/"),
                "length": path.stat().st_size,
                "sha256": sha256_file(path),
            }
        )
    return records


def write_build_manifest(version: str, package_paths: list[Path]) -> Path:
    upstream = git_text("rev-parse", "--abbrev-ref", "@{upstream}")
    counts = git_text("rev-list", "--left-right", "--count", f"HEAD...{upstream}") if upstream else ""
    ahead, behind = parse_ahead_behind_counts(counts)
    status_lines = [line for line in git_text("status", "--porcelain").splitlines() if line.strip()]
    manifest = {
        "schema": "hbv_studio_build_manifest_v2",
        "version": version,
        "app_version": source_version(),
        "created_at": datetime.now().astimezone().isoformat(),
        "source_control": {
            "branch": git_text("branch", "--show-current"),
            "head": git_text("rev-parse", "HEAD"),
            "upstream": upstream,
            "behind": behind,
            "ahead": ahead,
            "worktree_dirty": bool(status_lines),
            "worktree_change_count": len(status_lines),
            "note": "A dirty worktree is identified explicitly; HEAD alone is not a source/package alignment claim.",
        },
        "contracts": dict(BUILD_CONTRACTS),
        "source_files": build_source_records(),
        "packages": [
            {
                "path": str(path.resolve()),
                "length": path.stat().st_size,
                "sha256": sha256_file(path),
            }
            for path in package_paths
            if path.exists()
        ],
    }
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    output = OUTPUT_DIR / f"BUILD_MANIFEST_{version}.json"
    # UTF-8 BOM keeps Chinese paths readable in Windows PowerShell 5.1,
    # whose Get-Content default otherwise treats BOM-less UTF-8 as ANSI.
    output.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8-sig")
    return output


def run_windowed_pyinstaller(stage_parent: Path, build_root: Path) -> Path:
    bundle_dir = stage_parent / APP_NAME
    if bundle_dir.exists():
        shutil.rmtree(bundle_dir)
    cmd = [
        sys.executable,
        "-m",
        "PyInstaller",
        "--noconfirm",
        "--clean",
        "--onedir",
        "--windowed",
        "--name",
        APP_NAME,
        "--distpath",
        str(stage_parent),
        "--workpath",
        str(build_root / "work"),
        "--specpath",
        str(build_root / "spec"),
        str(GUI_ROOT / "app_bootstrap.py"),
    ]
    if BRANDING_ICON.exists():
        cmd.extend(["--icon", str(BRANDING_ICON.resolve())])
    for package in portable.COLLECT_ALL_PACKAGES:
        if portable.installed_package(package):
            cmd.extend(["--collect-all", package])
    for module in portable.HIDDEN_IMPORTS:
        if portable.installed_package(module.split(".", 1)[0]):
            cmd.extend(["--hidden-import", module])
    for module in portable.EXCLUDED_MODULES:
        cmd.extend(["--exclude-module", module])
    subprocess.run(cmd, cwd=str(PROJECT_ROOT), check=True)
    return bundle_dir


def find_required_dem() -> Path:
    exact = DEM_SOURCE_DIR / DEFAULT_DEM_NAME
    if exact.exists():
        return exact
    tif_files = sorted(DEM_SOURCE_DIR.glob("*.tif"))
    if tif_files:
        return tif_files[0]
    raise FileNotFoundError(f"Missing base DEM: {DEM_SOURCE_DIR}")


def installer_dem_files() -> list[Path]:
    dem_files: list[Path] = []
    for name in (DEFAULT_DEM_NAME, SECONDARY_DEM_NAME):
        candidate = DEM_SOURCE_DIR / name
        if candidate.exists():
            dem_files.append(candidate)
    if dem_files:
        return dem_files
    return [find_required_dem()]


def copy_installer_glacier_assets(bundle_dir: Path) -> None:
    if not GLACIER_SOURCE_DIR.exists():
        return
    glacier_dst_root = bundle_dir / CN_BASE_DATA / "冰川源" / GLACIER_SOURCE_DIR.name
    glacier_dst_root.mkdir(parents=True, exist_ok=True)
    for item in GLACIER_SOURCE_DIR.iterdir():
        if item.is_file() and item.suffix.lower() in GLACIER_REQUIRED_SUFFIXES:
            shutil.copy2(item, glacier_dst_root / item.name)


def copy_tree(src: Path, dst: Path) -> None:
    portable.copy_tree(src, dst)


def copy_plotly_js(bundle_gui_root: Path) -> None:
    portable.copy_plotly_js(bundle_gui_root)


def copy_docs_without_scripts(src: Path, dst: Path) -> None:
    if not src.exists():
        return
    dst.mkdir(parents=True, exist_ok=True)
    for item in src.iterdir():
        if item.is_dir():
            copy_tree(item, dst / item.name)
        elif item.suffix.lower() != ".py":
            shutil.copy2(item, dst / item.name)


def copy_installer_templates(src: Path, dst: Path) -> None:
    if not src.exists():
        return
    dst.mkdir(parents=True, exist_ok=True)
    for item in src.iterdir():
        if item.is_file():
            if item.name in INSTALLER_EXCLUDED_TEMPLATE_FILES:
                continue
            shutil.copy2(item, dst / item.name)
            continue

        if item.name != "assets":
            copy_tree(item, dst / item.name)
            continue

        assets_dst = dst / item.name
        assets_dst.mkdir(parents=True, exist_ok=True)
        for asset_item in item.iterdir():
            if asset_item.name in INSTALLER_EXCLUDED_TEMPLATE_ASSET_DIRS:
                continue
            if asset_item.is_dir():
                copy_tree(asset_item, assets_dst / asset_item.name)
            else:
                shutil.copy2(asset_item, assets_dst / asset_item.name)


def copy_installer_config(src: Path, dst: Path) -> None:
    if not src.exists():
        return
    dst.mkdir(parents=True, exist_ok=True)
    for item in src.iterdir():
        if item.is_file():
            if item.name in INSTALLER_EXCLUDED_CONFIG_FILES:
                continue
            shutil.copy2(item, dst / item.name)
            continue
        copy_tree(item, dst / item.name)


def prune_installer_bundle(bundle_dir: Path) -> None:
    for relative_path in INSTALLER_PRUNE_PATHS:
        target = bundle_dir / relative_path
        if target.is_dir():
            shutil.rmtree(target, ignore_errors=True)
        elif target.exists():
            target.unlink()
    for target in bundle_dir.rglob("*"):
        if not target.is_file():
            continue
        if "_internal" in target.relative_to(bundle_dir).parts:
            continue
        if target.suffix.lower() in INSTALLER_PRUNE_SUFFIXES:
            target.unlink()


def copy_installer_files(bundle_dir: Path) -> None:
    bundle_gui_root = bundle_dir / "HBV-Studio"
    bundle_gui_root.mkdir(parents=True, exist_ok=True)

    for name in portable.STUDIO_FILES:
        shutil.copy2(GUI_ROOT / name, bundle_gui_root / name)

    for name in portable.STUDIO_DIRS:
        copy_tree(GUI_ROOT / name, bundle_gui_root / name)

    copy_tree(GUI_ROOT / "web", bundle_gui_root / "web")
    copy_installer_templates(GUI_ROOT / "templates", bundle_gui_root / "templates")
    copy_tree(GUI_ROOT / "installer_assets", bundle_gui_root / "installer_assets")
    copy_plotly_js(bundle_gui_root)
    (bundle_gui_root / "workspaces").mkdir(parents=True, exist_ok=True)

    copy_tree(COMMON_SOURCE, bundle_dir / CN_PUBLIC)
    copy_tree(PROJECT_ROOT / "HBV-Cryo", bundle_dir / "HBV-Cryo")
    copy_tree(PREP_SOURCE, bundle_dir / CN_DATA_PREP)
    copy_installer_config(CONFIG_SOURCE, bundle_dir / CN_CONFIG)

    for filename in (CN_SELF_CHECK,):
        src = PROJECT_ROOT / filename
        if src.exists():
            shutil.copy2(src, bundle_dir / filename)

    dem_dst_root = bundle_dir / CN_BASE_DATA / CN_DEM_DIR
    dem_dst_root.mkdir(parents=True, exist_ok=True)
    for dem_src in installer_dem_files():
        shutil.copy2(dem_src, dem_dst_root / dem_src.name)
    copy_installer_glacier_assets(bundle_dir)
    prune_installer_bundle(bundle_dir)


def should_include_in_payload(relative_path: Path) -> bool:
    for prefix in EXCLUDED_PAYLOAD_PREFIXES:
        if relative_path.parts[: len(prefix.parts)] == prefix.parts:
            return False
    if relative_path.suffix.lower() in {".tif", ".tiff"}:
        return relative_path in ALLOWED_TIF_RELATIVE_PATHS
    return True


def compile_and_strip_source(bundle_dir: Path) -> int:
    targets: list[Path] = []
    for name in ("HBV-Studio", "HBV-Cryo", CN_PUBLIC, CN_DATA_PREP):
        src_dir = bundle_dir / name
        if src_dir.exists():
            targets.extend(sorted(src_dir.rglob("*.py")))
    root_script = bundle_dir / CN_SELF_CHECK
    if root_script.exists():
        targets.append(root_script)

    for py_file in targets:
        py_compile.compile(str(py_file), cfile=str(py_file.with_suffix(".pyc")), doraise=True)
        py_file.unlink()

    print(f"Compiled and removed {len(targets)} source files from the staged app.")
    return len(targets)


def create_payload_zip(bundle_dir: Path, stage_dir: Path) -> Path:
    payload_zip = stage_dir / PAYLOAD_NAME
    if payload_zip.exists():
        payload_zip.unlink()
    with zipfile.ZipFile(payload_zip, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for file_path in bundle_dir.rglob("*"):
            if file_path.is_dir():
                continue
            relative_path = file_path.relative_to(bundle_dir)
            if not should_include_in_payload(relative_path):
                continue
            zf.write(file_path, Path("app") / relative_path)
    return payload_zip


def iss_quote(value: Path | str) -> str:
    return str(value).replace("'", "''")


def iss_quote_double(value: Path | str) -> str:
    return str(value).replace('"', '""')


def find_iscc_executable() -> str | None:
    local_app_data = str(os.environ.get("LOCALAPPDATA", "")).strip()
    candidates = (
        shutil.which("ISCC"),
        shutil.which("iscc"),
        str(Path(local_app_data) / "Programs" / "Inno Setup 6" / "ISCC.exe") if local_app_data else None,
        r"C:\Program Files (x86)\Inno Setup 6\ISCC.exe",
        r"C:\Program Files\Inno Setup 6\ISCC.exe",
    )
    for candidate in candidates:
        if candidate and Path(candidate).exists():
            return str(Path(candidate).resolve(strict=False))
    return None


def resolve_inno_language(spec_dir: Path) -> tuple[str, str]:
    local_chinese = GUI_ROOT / "installer_assets" / "ChineseSimplified.isl"
    if local_chinese.exists():
        local_copy = spec_dir / local_chinese.name
        shutil.copy2(local_chinese, local_copy)
        return "chinesesimp", iss_quote_double(local_copy.resolve())
    return "english", "compiler:Default.isl"


def write_inno_setup_script(bundle_dir: Path, version: str) -> Path:
    spec_dir = prepare_clean_dir(INNO_BUILD_ROOT / "spec")
    output_dir = OUTPUT_DIR.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    installer_name = f"HBVStudio_Setup_{version}"
    script_path = spec_dir / f"{installer_name}.iss"
    language_name, messages_file = resolve_inno_language(spec_dir)
    setup_icon_line = f'SetupIconFile={iss_quote_double(BRANDING_ICON.resolve())}\n' if BRANDING_ICON.exists() else ""
    shortcut_icon_path = bundle_dir / SHORTCUT_ICON_RELATIVE
    shortcut_icon_rel_text = SHORTCUT_ICON_RELATIVE.as_posix().replace("/", "\\")
    if shortcut_icon_path.exists():
        shortcut_icon_value = f"{{app}}\\{shortcut_icon_rel_text}"
    else:
        shortcut_icon_value = r"{app}\{#MyAppExeName}"
    script_text = f"""#define MyAppName '{iss_quote(APP_NAME)}'
#define MyAppVersion '{iss_quote(version)}'
#define MyAppExeName '{iss_quote(APP_EXE_NAME)}'
#define MyOutputDir '{iss_quote(output_dir)}'
#define MyOutputBase '{iss_quote(installer_name)}'
#define MySourceDir '{iss_quote(bundle_dir.resolve())}'

[Setup]
AppId={INNO_APP_ID}
AppName={{#MyAppName}}
AppVersion={{#MyAppVersion}}
AppPublisher=HBV-Studio
DefaultDirName={{localappdata}}\\Programs\\HBVStudio
DefaultGroupName=HBVStudio
DisableDirPage=no
DisableProgramGroupPage=no
OutputDir={{#MyOutputDir}}
OutputBaseFilename={{#MyOutputBase}}
Compression=lzma2/ultra64
SolidCompression=yes
WizardStyle=modern
{setup_icon_line}PrivilegesRequired=lowest
ArchitecturesInstallIn64BitMode=x64compatible
CloseApplications=yes
CloseApplicationsFilter=HBVStudio.exe
RestartApplications=no
UninstallDisplayIcon={shortcut_icon_value}
ChangesAssociations=no
UsePreviousAppDir=yes
SetupLogging=yes

[Languages]
Name: "{language_name}"; MessagesFile: "{messages_file}"

[Tasks]
Name: "desktopicon"; Description: "创建桌面快捷方式"; GroupDescription: "附加任务:"; Flags: unchecked

[Files]
Source: "{{#MySourceDir}}\\*"; DestDir: "{{app}}"; Flags: ignoreversion recursesubdirs createallsubdirs

[InstallDelete]
Type: files; Name: "{{group}}\\HBVStudio.lnk"
Type: files; Name: "{{autodesktop}}\\HBVStudio.lnk"
Type: files; Name: "{{app}}\\HBV-Studio\\workspaces\\*.json"

[Icons]
Name: "{{group}}\\HBVStudio"; Filename: "{{app}}\\{{#MyAppExeName}}"; Parameters: "--installed-mode"; WorkingDir: "{{app}}"; IconFilename: "{shortcut_icon_value}"
Name: "{{autodesktop}}\\HBVStudio"; Filename: "{{app}}\\{{#MyAppExeName}}"; Parameters: "--installed-mode"; WorkingDir: "{{app}}"; Tasks: desktopicon; IconFilename: "{shortcut_icon_value}"

[Run]
Filename: "{{app}}\\{{#MyAppExeName}}"; Parameters: "--installed-mode"; Description: "安装完成后启动 HBVStudio"; Flags: nowait postinstall skipifsilent
"""
    script_path.write_text(script_text, encoding="utf-8-sig")
    return script_path


def build_inno_setup_installer(script_path: Path) -> Path | None:
    iscc = find_iscc_executable()
    if not iscc:
        print("ISCC.exe was not found. Generated the Inno Setup script but skipped compilation.")
        print(f"Installer script: {script_path}")
        return None

    subprocess.run([iscc, str(script_path)], cwd=str(script_path.parent), check=True)
    output_exe = OUTPUT_DIR / f"{script_path.stem}.exe"
    if not output_exe.exists():
        raise FileNotFoundError(f"Expected installer was not produced: {output_exe}")
    return output_exe


def build_legacy_onefile_installer(stage_dir: Path, payload_zip: Path, version: str) -> Path:
    output_dir = OUTPUT_DIR.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    build_root = prepare_clean_dir(LEGACY_ONEFILE_BUILD_ROOT)
    launcher_path = stage_dir / "installer_launcher.py"
    launcher_path.write_text(
        (
            "from pathlib import Path\n"
            "import os, shutil, subprocess, sys, tempfile, traceback, zipfile\n"
            "APP_EXE_NAME = 'HBVStudio.exe'\n"
            "PAYLOAD_NAME = 'HBVStudio_payload.zip'\n"
            "INSTALL_ROOT_NAME = 'HBVStudio'\n"
            "def bundled_path(name):\n"
            "    base = Path(getattr(sys, '_MEIPASS', Path(__file__).resolve().parent))\n"
            "    return base / name\n"
            "def install():\n"
            "    payload = bundled_path(PAYLOAD_NAME)\n"
            "    install_root = Path(os.environ.get('LOCALAPPDATA', Path.home() / 'AppData' / 'Local')) / INSTALL_ROOT_NAME\n"
            "    if install_root.exists():\n"
            "        shutil.rmtree(install_root, ignore_errors=True)\n"
            "    with zipfile.ZipFile(payload, 'r') as zf:\n"
            "        zf.extractall(install_root)\n"
            "    return install_root / 'app' / APP_EXE_NAME\n"
            "def main():\n"
            "    try:\n"
            "        exe_path = install()\n"
            "        subprocess.Popen([str(exe_path), '--installed-mode'], cwd=str(exe_path.parent))\n"
            "    except Exception:\n"
            "        log_path = Path(tempfile.gettempdir()) / 'HBVStudio_setup_error.log'\n"
            "        log_path.write_text(traceback.format_exc(), encoding='utf-8')\n"
            "        raise\n"
            "if __name__ == '__main__':\n"
            "    main()\n"
        ),
        encoding="utf-8",
    )

    installer_name = f"HBVStudio_LegacySetup_{version}"
    cmd = [
        sys.executable,
        "-m",
        "PyInstaller",
        "--noconfirm",
        "--clean",
        "--onefile",
        "--windowed",
        "--name",
        installer_name,
        "--distpath",
        str(output_dir),
        "--workpath",
        str(build_root / "work"),
        "--specpath",
        str(build_root / "spec"),
        "--add-data",
        f"{payload_zip}{os.pathsep}.",
        str(launcher_path),
    ]
    subprocess.run(cmd, cwd=str(stage_dir), check=True)
    output_exe = output_dir / f"{installer_name}.exe"
    if not output_exe.exists():
        raise FileNotFoundError(f"Legacy installer was not produced: {output_exe}")
    return output_exe


def main() -> None:
    parser = argparse.ArgumentParser(description="Build the HBVStudio Windows installer.")
    parser.add_argument("--version", default=datetime.now().strftime("%Y.%m.%d"))
    parser.add_argument(
        "--legacy-self-extractor",
        action="store_true",
        help="Also produce the historical one-click self-extracting installer.",
    )
    args = parser.parse_args()
    if source_version() != args.version:
        raise ValueError(
            f"Installer version {args.version} does not match Studio APP_VERSION {source_version()}."
        )

    stage_parent = prepare_clean_dir(STAGE_PARENT)
    build_root = prepare_clean_dir(WINDOWED_BUILD_ROOT)
    bundle_dir = run_windowed_pyinstaller(stage_parent, build_root)
    copy_installer_files(bundle_dir)
    compile_and_strip_source(bundle_dir)

    script_path = write_inno_setup_script(bundle_dir, args.version)
    output_exe = build_inno_setup_installer(script_path)
    package_outputs: list[Path] = []
    if output_exe is not None:
        package_outputs.append(output_exe)
        print(f"Professional installer created: {output_exe}")
    else:
        print("Professional installer script is ready. Install Inno Setup and rerun to compile it.")

    if args.legacy_self_extractor:
        payload_zip = create_payload_zip(bundle_dir, stage_parent)
        legacy_exe = build_legacy_onefile_installer(stage_parent, payload_zip, args.version)
        package_outputs.append(legacy_exe)
        print(f"Legacy self-extracting installer created: {legacy_exe}")

    manifest_path = write_build_manifest(args.version, package_outputs)
    print(f"Build manifest created: {manifest_path}")


if __name__ == "__main__":
    main()
