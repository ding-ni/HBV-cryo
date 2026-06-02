#!/usr/bin/env python
# -*- coding: utf-8 -*-
from __future__ import annotations

import os
import string
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable


WINDOWS_HIDDEN_DIRS = frozenset({
    "system volume information",
    "$recycle.bin",
    "$winrepackage",
    "recovery",
    "config.msi",
    "msocache",
    "$sysreset",
})


@dataclass(frozen=True)
class FilesystemContext:
    resolve_any_path: Callable[..., Path]
    workspace_dir: Path
    project_runtime_dir: Path
    project_root: Path
    dir_browser_file_preview_items: int
    max_browser_file_items: int


@dataclass(frozen=True)
class FilesystemPlaceholderContext:
    project_root: Path
    gui_root: Path


@dataclass(frozen=True)
class FilesystemPathContext:
    gui_root: Path
    project_root: Path
    replace_placeholders: Callable[..., Any]
    remap_legacy_project_path: Callable[..., Any]


def list_drives() -> list[str]:
    if os.name != "nt":
        return ["/"]
    drives = []
    for letter in string.ascii_uppercase:
        drive = f"{letter}:\\"
        if Path(drive).exists():
            drives.append(drive)
    return drives


def safe_iterdir(directory: Path) -> list[Path]:
    """Iterate a directory, skipping entries that raise PermissionError individually."""
    results: list[Path] = []
    try:
        scanner = os.scandir(str(directory))
    except (PermissionError, OSError):
        return results
    try:
        while True:
            try:
                entry = next(scanner)
            except StopIteration:
                break
            except (PermissionError, OSError):
                continue
            results.append(Path(entry.path))
    finally:
        scanner.close()
    return results


def placeholder_roots_for_config_path(
    config_path: Path | str | None,
    context: FilesystemPlaceholderContext,
) -> tuple[Path, Path]:
    try:
        path = Path(config_path).resolve(strict=False) if config_path else None
    except Exception:
        path = None
    if path is not None:
        for candidate in [path] + list(path.parents):
            if candidate.name.lower() == "hbv-studio":
                gui_root = candidate.resolve(strict=False)
                return gui_root.parent.resolve(strict=False), gui_root
    return context.project_root, context.gui_root


def replace_placeholders(
    value: Any,
    context: FilesystemPlaceholderContext,
    *,
    project_root: Path | None = None,
    gui_root: Path | None = None,
) -> Any:
    project_root = project_root or context.project_root
    gui_root = gui_root or context.gui_root
    placeholders = {
        "__PROJECT_ROOT__": str(project_root),
        "__GUI_ROOT__": str(gui_root),
    }
    if isinstance(value, dict):
        return {
            key: replace_placeholders(item, context, project_root=project_root, gui_root=gui_root)
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [
            replace_placeholders(item, context, project_root=project_root, gui_root=gui_root)
            for item in value
        ]
    if isinstance(value, str):
        updated = value
        for old, new in placeholders.items():
            updated = updated.replace(old, new)
        return updated
    return value


def remap_legacy_project_path(
    raw_value: Any,
    context: FilesystemPlaceholderContext,
    *,
    preserve_project_root: Path | None = None,
    preserve_gui_root: Path | None = None,
) -> Any:
    if not isinstance(raw_value, str):
        return raw_value
    text = str(raw_value or "").strip()
    if (not text) or ("__PROJECT_ROOT__" in text) or ("__GUI_ROOT__" in text):
        return raw_value
    candidate = Path(text.replace("/", "\\")).expanduser()
    if not candidate.is_absolute():
        return raw_value
    try:
        if candidate.exists():
            return raw_value
    except Exception:
        return raw_value
    for root in (preserve_gui_root, preserve_project_root):
        if root is None:
            continue
        try:
            candidate.resolve(strict=False).relative_to(Path(root).resolve(strict=False))
            return raw_value
        except Exception:
            pass

    normalized = str(candidate).replace("/", "\\")
    lowered = normalized.lower()
    markers = (
        (f"\\{context.gui_root.name.lower()}\\", context.gui_root),
        (f"\\{context.project_root.name.lower()}\\", context.project_root),
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
        remapped = (root / suffix) if suffix else root
        try:
            return str(remapped.resolve(strict=False))
        except Exception:
            return str(remapped)
    legacy_markers = (
        ("\\hbv-studio\\", context.gui_root),
        ("\\workspaces\\", context.gui_root / "workspaces"),
        ("\\运行目录\\", context.project_root / "运行目录"),
        ("\\runtime\\", context.project_root / "运行目录"),
        ("\\hbv-cryo\\", context.project_root / "HBV-Cryo"),
        ("\\数据准备\\", context.project_root / "数据准备"),
        ("\\基础数据\\", context.project_root / "基础数据"),
    )
    for marker, root in legacy_markers:
        idx = lowered.find(marker)
        if idx < 0:
            suffix_marker = marker.rstrip("\\")
            if not lowered.endswith(suffix_marker):
                continue
            suffix = ""
        else:
            suffix = normalized[idx + len(marker):].lstrip("\\/")
        remapped = (root / suffix) if suffix else root
        try:
            return str(remapped.resolve(strict=False))
        except Exception:
            return str(remapped)
    return raw_value


def normalize_legacy_project_paths(
    value: Any,
    context: FilesystemPlaceholderContext,
    parent_key: str = "",
    *,
    preserve_project_root: Path | None = None,
    preserve_gui_root: Path | None = None,
) -> Any:
    if isinstance(value, dict):
        return {
            key: normalize_legacy_project_paths(
                item,
                context,
                str(key),
                preserve_project_root=preserve_project_root,
                preserve_gui_root=preserve_gui_root,
            )
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [
            normalize_legacy_project_paths(
                item,
                context,
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
            return remap_legacy_project_path(
                value,
                context,
                preserve_project_root=preserve_project_root,
                preserve_gui_root=preserve_gui_root,
            )
    return value


def resolve_any_path(raw_path: str, context: FilesystemPathContext, *, must_exist: bool = False) -> Path:
    text = str(raw_path or "").strip()
    if not text:
        raise ValueError("缺少路径参数。")
    expanded = context.replace_placeholders(text)
    expanded = context.remap_legacy_project_path(expanded)
    path = Path(str(expanded)).expanduser()
    if not path.is_absolute():
        path = (context.gui_root / path).resolve()
    else:
        path = path.resolve(strict=False)
    if must_exist and not path.exists():
        raise FileNotFoundError(str(path))
    return path


def ensure_within(root: Path, candidate: Path) -> Path:
    resolved_root = root.resolve()
    resolved = candidate.resolve(strict=False)
    try:
        resolved.relative_to(resolved_root)
    except ValueError as exc:
        raise ValueError(f"路径超出允许范围：{resolved}") from exc
    return resolved


def is_within_root(root: Path, candidate: Path) -> bool:
    try:
        candidate.resolve(strict=False).relative_to(root.resolve(strict=False))
        return True
    except ValueError:
        return False
    except Exception:
        return False


def is_within_any_root(candidate: Path, roots: list[Path] | tuple[Path, ...]) -> bool:
    return any(is_within_root(root, candidate) for root in roots)


def to_display_path(path: Path, bases: list[Path] | tuple[Path, ...]) -> str:
    for base in bases:
        try:
            return str(path.resolve().relative_to(base.resolve())).replace("\\", "/")
        except ValueError:
            continue
    return str(path.resolve())


def list_filesystem(
    path_value: str,
    context: FilesystemContext,
    extensions: list[str] | None = None,
    kind: str = "file",
) -> dict[str, Any]:
    normalized_exts = {item.lower() for item in (extensions or []) if item}
    browse_kind = str(kind or "file").strip().lower() or "file"
    preview_only = browse_kind == "dir"
    file_limit = context.dir_browser_file_preview_items if preview_only else context.max_browser_file_items
    if not path_value:
        return {
            "current_path": "",
            "parent_path": None,
            "roots": list_drives(),
            "directories": [],
            "files": [],
            "kind": browse_kind,
            "file_count": 0,
            "shown_file_count": 0,
            "files_truncated": False,
        }
    current = context.resolve_any_path(path_value, must_exist=False)
    try:
        if current.is_file():
            current = current.parent
    except (PermissionError, OSError):
        current = current.parent
    try:
        exists = current.exists()
    except (PermissionError, OSError):
        exists = False
    if not exists:
        current = current.parent
    try:
        exists = current.exists()
    except (PermissionError, OSError):
        exists = False
    if not exists:
        raise FileNotFoundError(str(current))
    directories = []
    files = []
    raw_children = safe_iterdir(current)

    def _is_system_entry(item: Path) -> bool:
        try:
            name = item.name.lower()
            return name in WINDOWS_HIDDEN_DIRS or name.startswith("$") or name.startswith(".")
        except Exception:
            return True

    raw_children = [child for child in raw_children if not _is_system_entry(child)]

    def _sort_key(item: Path) -> tuple[bool, str]:
        try:
            return (not item.is_dir(), item.name.lower())
        except (PermissionError, OSError):
            return (True, item.name.lower())

    file_count = 0
    for child in sorted(raw_children, key=_sort_key):
        try:
            if child.is_dir():
                directories.append({"name": child.name, "path": str(child)})
            else:
                if normalized_exts and child.suffix.lower() not in normalized_exts:
                    continue
                file_count += 1
                if len(files) >= file_limit:
                    continue
                files.append({"name": child.name, "path": str(child), "suffix": child.suffix.lower()})
        except (PermissionError, OSError):
            continue
    return {
        "current_path": str(current),
        "parent_path": str(current.parent) if current.parent != current else None,
        "roots": list_drives(),
        "directories": directories,
        "files": files,
        "kind": browse_kind,
        "file_count": file_count,
        "shown_file_count": len(files),
        "files_truncated": file_count > len(files),
    }


def _is_within_root(candidate: Path, root: Path) -> bool:
    return is_within_root(root, candidate)


def open_path_in_explorer(payload: dict[str, Any], context: FilesystemContext) -> dict[str, Any]:
    raw_path = str(payload.get("path", "")).strip()
    if not raw_path:
        raise ValueError("缺少路径。")
    target = context.resolve_any_path(raw_path, must_exist=True)
    allowed_roots = [context.workspace_dir, context.project_runtime_dir, context.project_root, context.project_root.parent]
    if not any(_is_within_root(target, root) for root in allowed_roots):
        raise ValueError(f"该路径不在允许打开的工程目录范围内：{target}")
    if os.name == "nt":
        if target.is_file():
            subprocess.Popen(["explorer.exe", f"/select,{str(target)}"])
        else:
            subprocess.Popen(["explorer.exe", str(target)])
    elif sys.platform == "darwin":
        subprocess.Popen(["open", str(target)])
    else:
        subprocess.Popen(["xdg-open", str(target)])
    return {"opened": True, "path": str(target.resolve(strict=False))}
