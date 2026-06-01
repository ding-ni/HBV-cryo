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
    try:
        candidate.resolve(strict=False).relative_to(root.resolve(strict=False))
        return True
    except ValueError:
        return False


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
