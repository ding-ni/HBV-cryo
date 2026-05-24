#!/usr/bin/env python
# -*- coding: utf-8 -*-
from __future__ import annotations

import json
import os
import runpy
import shutil
import sys
import traceback
from importlib.machinery import SourcelessFileLoader
from importlib.util import spec_from_file_location
from pathlib import Path
from typing import Any


RUN_PY_FILE_ROLE = "__run_py_file__"
RUNTIME_DIR_NAME = "运行目录"
INSTALLED_USER_DATA_DIR_NAME = "用户数据"


class _SourcelessPycFinder:
    """Allow ``import foo`` to find ``foo.pyc`` when ``foo.py`` is absent."""

    _installed = False

    @staticmethod
    def find_spec(fullname, path, target=None):
        tail = fullname.rsplit(".", 1)[-1]
        for entry in (path or sys.path):
            try:
                candidate = Path(entry) / f"{tail}.pyc"
            except (TypeError, ValueError):
                continue
            if candidate.is_file():
                return spec_from_file_location(
                    fullname,
                    str(candidate),
                    loader=SourcelessFileLoader(fullname, str(candidate)),
                )
        return None

    @classmethod
    def install(cls):
        if not cls._installed:
            sys.meta_path.append(cls)
            cls._installed = True


def app_root() -> Path:
    raw = str(os.environ.get("HBV_STUDIO_APP_ROOT", "")).strip()
    if raw:
        return Path(raw).expanduser().resolve(strict=False)
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parents[1]


APP_ROOT = app_root()
GUI_ROOT = APP_ROOT / "HBV-Studio"
PACKAGE_RUNTIME_ROOT = APP_ROOT / RUNTIME_DIR_NAME
INSTALLED_EXECUTABLE_NAMES = {"hbvstudio.exe"}
PORTABLE_EXECUTABLE_NAMES = {"hbvstudio_demo.exe"}


def env_flag(name: str, default: bool = False) -> bool:
    raw = str(os.environ.get(name, "")).strip().lower()
    if not raw:
        return default
    return raw in {"1", "true", "yes", "on"}


def auto_detect_installed_mode() -> bool:
    if not getattr(sys, "frozen", False):
        return False
    try:
        exe_name = Path(sys.executable).name.lower()
    except Exception:
        return False
    if exe_name in PORTABLE_EXECUTABLE_NAMES:
        return False
    return exe_name in INSTALLED_EXECUTABLE_NAMES


def consume_mode_flags() -> None:
    filtered = [sys.argv[0]]
    mode_override: str | None = None
    for arg in sys.argv[1:]:
        if arg == "--installed-mode":
            mode_override = "1"
            continue
        if arg == "--portable-mode":
            mode_override = "0"
            continue
        filtered.append(arg)
    sys.argv[:] = filtered
    if mode_override is not None:
        os.environ["HBV_STUDIO_INSTALLED_MODE"] = mode_override
    elif not str(os.environ.get("HBV_STUDIO_INSTALLED_MODE", "")).strip():
        os.environ["HBV_STUDIO_INSTALLED_MODE"] = "1" if auto_detect_installed_mode() else "0"


def installed_mode() -> bool:
    return env_flag("HBV_STUDIO_INSTALLED_MODE", default=False)


def legacy_default_user_data_root() -> Path:
    local_app_data = str(os.environ.get("LOCALAPPDATA", "")).strip()
    root_name = "HBVStudio" if installed_mode() else "HBVStudioPortable"
    if local_app_data:
        return Path(local_app_data).expanduser().resolve(strict=False) / root_name
    return Path.home().expanduser().resolve(strict=False) / "AppData" / "Local" / root_name


def preferred_installed_user_data_root() -> Path:
    return (APP_ROOT / INSTALLED_USER_DATA_DIR_NAME).resolve(strict=False)


def default_user_data_root() -> Path:
    if installed_mode():
        preferred = preferred_installed_user_data_root()
        if dir_is_writable(preferred):
            return preferred
    return legacy_default_user_data_root()


def dir_is_writable(path: Path) -> bool:
    probe = None
    try:
        candidate = path if path.exists() else path.parent
        if not str(candidate).strip():
            candidate = path
        candidate.mkdir(parents=True, exist_ok=True)
        probe = candidate / f".hbv_write_test_{os.getpid()}"
        with open(probe, "x", encoding="utf-8"):
            pass
        probe.unlink()
        return True
    except OSError:
        if probe is not None:
            try:
                probe.unlink()
            except OSError:
                pass
        return False


def should_use_user_data_root() -> bool:
    if str(os.environ.get("HBV_STUDIO_USER_ROOT", "")).strip():
        return True
    if installed_mode() or env_flag("HBV_STUDIO_FORCE_USER_ROOT", default=False):
        return True
    return not (dir_is_writable(APP_ROOT) and dir_is_writable(GUI_ROOT))


def user_data_root() -> Path:
    raw = str(os.environ.get("HBV_STUDIO_USER_ROOT", "")).strip()
    if raw:
        return Path(raw).expanduser().resolve(strict=False)
    if should_use_user_data_root():
        return default_user_data_root()
    return APP_ROOT


def workspace_dir_for_mode() -> Path:
    return (user_data_root() / "workspaces") if should_use_user_data_root() else (GUI_ROOT / "workspaces")


def log_dir_for_mode() -> Path:
    return (user_data_root() / "logs") if should_use_user_data_root() else (GUI_ROOT / "logs")


def runtime_root_for_mode() -> Path:
    if installed_mode() or should_use_user_data_root():
        return user_data_root() / RUNTIME_DIR_NAME
    return PACKAGE_RUNTIME_ROOT


def replace_placeholders(value: Any) -> Any:
    if isinstance(value, dict):
        return {key: replace_placeholders(item) for key, item in value.items()}
    if isinstance(value, list):
        return [replace_placeholders(item) for item in value]
    if isinstance(value, str):
        updated = value.replace("__GUI_ROOT__", str(GUI_ROOT))
        updated = updated.replace("__PROJECT_ROOT__", str(APP_ROOT))
        return updated
    return value


def remap_prefix(value: Any, old_root: Path, new_root: Path) -> Any:
    if isinstance(value, dict):
        return {key: remap_prefix(item, old_root, new_root) for key, item in value.items()}
    if isinstance(value, list):
        return [remap_prefix(item, old_root, new_root) for item in value]
    if not isinstance(value, str):
        return value

    text = str(value).strip()
    if not text:
        return value
    try:
        path = Path(text.replace("/", "\\")).expanduser().resolve(strict=False)
        old_resolved = old_root.resolve(strict=False)
        rel = path.relative_to(old_resolved)
        return str((new_root / rel).resolve(strict=False))
    except Exception:
        return value


def workspace_runtime_name(config: dict[str, Any], src: Path) -> str:
    raw_runtime = replace_placeholders(config.get("运行目录", ""))
    if isinstance(raw_runtime, str):
        try:
            name = Path(raw_runtime.replace("/", "\\")).name.strip()
            if name:
                return name
        except Exception:
            pass
    return src.stem


def rewrite_workspace_for_user_root(config: dict[str, Any], src: Path, target_root: Path) -> dict[str, Any]:
    if not installed_mode():
        return config
    target_runtime_base = target_root / RUNTIME_DIR_NAME
    target_runtime_root = target_runtime_base / workspace_runtime_name(config, src)
    rewritten = remap_prefix(replace_placeholders(config), PACKAGE_RUNTIME_ROOT, target_runtime_base)
    if isinstance(rewritten, dict):
        rewritten["运行目录"] = str(target_runtime_root)
    return rewritten


def migrate_existing_user_data(target_root: Path) -> None:
    if not installed_mode():
        return
    legacy_root = legacy_default_user_data_root()
    if samefile_or_equal(target_root, legacy_root):
        return
    if not legacy_root.exists():
        return

    legacy_workspaces = legacy_root / "workspaces"
    target_workspaces = target_root / "workspaces"
    if legacy_workspaces.exists() and not any(target_workspaces.glob("*.json")):
        for src in legacy_workspaces.glob("*.json"):
            dst = target_workspaces / src.name
            if not dst.exists():
                shutil.copy2(src, dst)

    legacy_runtime = legacy_root / RUNTIME_DIR_NAME
    target_runtime = target_root / RUNTIME_DIR_NAME
    if legacy_runtime.exists() and (not target_runtime.exists() or not any(target_runtime.iterdir())):
        shutil.copytree(legacy_runtime, target_runtime, dirs_exist_ok=True)

    legacy_logs = legacy_root / "logs"
    target_logs = target_root / "logs"
    if legacy_logs.exists() and (not target_logs.exists() or not any(target_logs.iterdir())):
        shutil.copytree(legacy_logs, target_logs, dirs_exist_ok=True)


def samefile_or_equal(left: Path, right: Path) -> bool:
    try:
        return left.resolve(strict=False) == right.resolve(strict=False)
    except Exception:
        return False


def seed_user_data() -> None:
    if not should_use_user_data_root():
        return

    target_root = user_data_root()
    target_root.mkdir(parents=True, exist_ok=True)

    target_workspaces = target_root / "workspaces"
    target_workspaces.mkdir(parents=True, exist_ok=True)
    migrate_existing_user_data(target_root)
    source_workspaces = GUI_ROOT / "workspaces"
    if source_workspaces.exists():
        for src in source_workspaces.glob("*.json"):
            dst = target_workspaces / src.name
            try:
                payload = json.loads(src.read_text(encoding="utf-8-sig"))
            except Exception:
                if not dst.exists():
                    shutil.copy2(src, dst)
                continue
            rewritten = rewrite_workspace_for_user_root(payload, src, target_root)
            dst.write_text(json.dumps(rewritten, ensure_ascii=False, indent=2), encoding="utf-8")

    if installed_mode():
        source_runtime = PACKAGE_RUNTIME_ROOT
        target_runtime = target_root / RUNTIME_DIR_NAME
        if source_runtime.exists() and (not target_runtime.exists() or not any(target_runtime.iterdir())):
            shutil.copytree(source_runtime, target_runtime, dirs_exist_ok=True)

    (target_root / "logs").mkdir(parents=True, exist_ok=True)


def seed_environment() -> None:
    _SourcelessPycFinder.install()
    use_user_root = should_use_user_data_root()
    seed_user_data()

    os.environ["HBV_STUDIO_EFFECTIVE_USER_ROOT"] = str(user_data_root())
    os.environ.setdefault("HBV_STUDIO_APP_ROOT", str(APP_ROOT))
    os.environ.setdefault("HBV_STUDIO_WEB_ROOT", str(GUI_ROOT / "web"))
    os.environ.setdefault("HBV_STUDIO_TEMPLATE_DIR", str(GUI_ROOT / "templates"))
    os.environ.setdefault("HBV_STUDIO_DOCS_DIR", str(GUI_ROOT / "docs"))

    if use_user_root:
        os.environ.setdefault("HBV_STUDIO_WORKSPACE_DIR", str(workspace_dir_for_mode()))
        os.environ.setdefault("HBV_STUDIO_LOG_DIR", str(log_dir_for_mode()))
    else:
        os.environ.setdefault("HBV_STUDIO_WORKSPACE_DIR", str(GUI_ROOT / "workspaces"))
        os.environ.setdefault("HBV_STUDIO_LOG_DIR", str(GUI_ROOT / "logs"))

    os.environ.setdefault("HBV_STUDIO_RUNTIME_ROOT", str(runtime_root_for_mode()))


def repair_runtime_jsons() -> None:
    runtime_default = runtime_root_for_mode()
    runtime_root = Path(str(os.environ.get("HBV_STUDIO_RUNTIME_ROOT", runtime_default) or runtime_default)).expanduser().resolve(strict=False)
    if not runtime_root.exists():
        return
    for candidate in (str(GUI_ROOT), str(APP_ROOT)):
        if candidate not in sys.path:
            sys.path.insert(0, candidate)
    try:
        from profile_runner import portableize_value_paths, remap_legacy_project_path
    except Exception:
        return

    def repair_value(value):
        if isinstance(value, dict):
            return {key: repair_value(item) for key, item in value.items()}
        if isinstance(value, list):
            return [repair_value(item) for item in value]
        if isinstance(value, str):
            try:
                return remap_legacy_project_path(value)
            except Exception:
                return value
        return value

    repaired = 0
    for json_path in runtime_root.rglob("*.json"):
        try:
            payload = json.loads(json_path.read_text(encoding="utf-8-sig"))
        except Exception:
            continue
        rewritten = portableize_value_paths(repair_value(payload))
        if rewritten == payload:
            continue
        try:
            json_path.write_text(json.dumps(rewritten, ensure_ascii=False, indent=2), encoding="utf-8")
        except Exception:
            continue
        repaired += 1
    if repaired:
        print(f"[startup repair] updated {repaired} runtime json files.")


def resolve_script(raw: str) -> Path:
    direct = Path(raw)
    candidates = []
    if direct.is_absolute():
        candidates.append(direct)
    else:
        candidates.extend([Path.cwd() / direct, APP_ROOT / direct, GUI_ROOT / direct])
    for candidate in candidates:
        if candidate.exists():
            return candidate.resolve()
    if direct.suffix.lower() == ".py":
        for candidate in candidates:
            pyc = candidate.with_suffix(".pyc")
            if pyc.exists():
                return pyc.resolve()
    raise FileNotFoundError(f"script not found: {raw}")


def run_script(script_path: Path, args: list[str]) -> None:
    old_argv = sys.argv[:]
    old_sys_path = sys.path[:]
    script_dir = str(script_path.parent.resolve())
    app_root = str(APP_ROOT)
    gui_root = str(GUI_ROOT)
    seeded: list[str] = []
    for candidate in (script_dir, gui_root, app_root):
        if candidate not in seeded:
            seeded.append(candidate)
    sys.argv = [str(script_path), *args]
    sys.path[:] = seeded + [item for item in sys.path if item not in seeded]
    try:
        runpy.run_path(str(script_path), run_name="__main__")
    finally:
        sys.argv = old_argv
        sys.path[:] = old_sys_path


def main() -> None:
    consume_mode_flags()
    seed_environment()
    repair_runtime_jsons()
    os.chdir(APP_ROOT)
    argv = sys.argv[1:]
    if argv and argv[0] == RUN_PY_FILE_ROLE:
        if len(argv) < 2:
            raise SystemExit(f"{RUN_PY_FILE_ROLE} requires a script path.")
        run_script(resolve_script(argv[1]), argv[2:])
        return
    if argv and Path(argv[0]).suffix.lower() in {".py", ".pyc"}:
        run_script(resolve_script(argv[0]), argv[1:])
        return
    run_script(resolve_script("HBV-Studio/launch.py"), argv)


if __name__ == "__main__":
    try:
        main()
    except SystemExit:
        raise
    except Exception:
        traceback.print_exc()
        raise SystemExit(1)
