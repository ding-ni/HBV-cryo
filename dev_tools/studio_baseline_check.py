#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Baseline checks for HBV-Studio architecture and release work.

This script is intentionally lightweight: it avoids importing the application
for static checks, then optionally starts the real local service for /api/health.
It is meant to be run before committing frontend/backend restructuring changes.
"""

from __future__ import annotations

import argparse
import ast
import importlib.util
import json
import os
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[1]
GUI_ROOT = REPO_ROOT / "HBV-Studio"
SERVICE_FILE = GUI_ROOT / "studio_service.py"
SNAPSHOT_PATH = Path(__file__).resolve().parent / "baseline" / "studio_api_routes.json"

PYTHON_GLOBS = (
    "HBV-Studio/*.py",
    "HBV-Studio/services/*.py",
    "HBV-Cryo/*.py",
    "dev_tools/*.py",
    "HBV-Studio/tests/*.py",
)
JAVASCRIPT_FILES = (
    GUI_ROOT / "web" / "app.js",
    GUI_ROOT / "web" / "js" / "eventMode.js",
    GUI_ROOT / "web" / "js" / "forecastView.js",
    GUI_ROOT / "web" / "js" / "geoPreview.js",
    GUI_ROOT / "web" / "js" / "parameterLibrary.js",
    GUI_ROOT / "web" / "js" / "stationPrecip.js",
    GUI_ROOT / "web" / "js" / "taskView.js",
    GUI_ROOT / "web" / "js" / "workspaceLayout.js",
)


class CheckError(RuntimeError):
    pass


def rel(path: Path) -> str:
    return path.resolve(strict=False).relative_to(REPO_ROOT).as_posix()


def ok(message: str) -> None:
    print(f"[OK] {message}")


def warn(message: str) -> None:
    print(f"[WARN] {message}")


def fail(message: str) -> None:
    print(f"[FAIL] {message}")


def parse_python(path: Path) -> None:
    try:
        ast.parse(path.read_text(encoding="utf-8-sig"), filename=str(path))
    except SyntaxError as exc:
        raise CheckError(f"Python syntax failed: {rel(path)}:{exc.lineno}: {exc.msg}") from exc


def check_python_syntax() -> dict[str, Any]:
    files: list[Path] = []
    for pattern in PYTHON_GLOBS:
        files.extend(sorted(REPO_ROOT.glob(pattern)))
    unique = sorted({path.resolve() for path in files if path.is_file()})
    for path in unique:
        parse_python(path)
    ok(f"Python syntax parsed: {len(unique)} files")
    return {"python_files": len(unique)}


def check_javascript_syntax() -> dict[str, Any]:
    node = shutil_which("node")
    if not node:
        raise CheckError("node is required for JavaScript syntax checks")
    checked = 0
    for path in JAVASCRIPT_FILES:
        if not path.exists():
            raise CheckError(f"JavaScript file missing: {rel(path)}")
        proc = subprocess.run(
            [node, "--check", str(path)],
            cwd=str(REPO_ROOT),
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
        )
        if proc.returncode != 0:
            raise CheckError(f"JavaScript syntax failed: {rel(path)}\n{proc.stdout.strip()}")
        checked += 1
    ok(f"JavaScript syntax checked with node --check: {checked} files")
    return {"javascript_files": checked}


def shutil_which(command: str) -> str | None:
    paths = os.environ.get("PATH", "").split(os.pathsep)
    suffixes = [""]
    if os.name == "nt":
        suffixes.extend([".exe", ".cmd", ".bat"])
    for directory in paths:
        if not directory:
            continue
        for suffix in suffixes:
            candidate = Path(directory) / f"{command}{suffix}"
            if candidate.is_file():
                return str(candidate)
    return None


class ApiRouteCollector(ast.NodeVisitor):
    def __init__(self) -> None:
        self.routes: set[str] = set()

    def visit_Constant(self, node: ast.Constant) -> Any:
        if isinstance(node.value, str) and node.value.startswith("/api/"):
            self.routes.add(node.value)


def collect_routes_from_function(tree: ast.AST, function_name: str) -> list[str]:
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == function_name:
            collector = ApiRouteCollector()
            collector.visit(node)
            return sorted(collector.routes)
    raise CheckError(f"Function not found in studio_service.py: {function_name}")


def current_api_snapshot() -> dict[str, Any]:
    tree = ast.parse(SERVICE_FILE.read_text(encoding="utf-8-sig"), filename=str(SERVICE_FILE))
    get_routes = collect_routes_from_function(tree, "handle_api_get")
    post_routes = collect_routes_from_function(tree, "handle_api_post")
    return {
        "source": rel(SERVICE_FILE),
        "get": get_routes,
        "post": post_routes,
        "total": len(set(get_routes) | set(post_routes)),
    }


def check_or_update_api_snapshot(update: bool) -> dict[str, Any]:
    snapshot = current_api_snapshot()
    SNAPSHOT_PATH.parent.mkdir(parents=True, exist_ok=True)
    if update or not SNAPSHOT_PATH.exists():
        SNAPSHOT_PATH.write_text(json.dumps(snapshot, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        ok(f"API route snapshot written: {SNAPSHOT_PATH.relative_to(REPO_ROOT).as_posix()}")
        return {"api_routes": snapshot["total"], "snapshot_updated": True}
    expected = json.loads(SNAPSHOT_PATH.read_text(encoding="utf-8"))
    if expected != snapshot:
        raise CheckError(
            "API route snapshot changed. Review route compatibility, then rerun with "
            "--update-api-snapshot if the change is intentional."
        )
    ok(f"API route snapshot matched: {snapshot['total']} routes")
    return {"api_routes": snapshot["total"], "snapshot_updated": False}


def find_free_port(host: str = "127.0.0.1") -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind((host, 0))
        return int(sock.getsockname()[1])


def request_json(url: str, *, timeout: float = 1.0, method: str = "GET") -> dict[str, Any]:
    data = b"{}" if method == "POST" else None
    request = urllib.request.Request(
        url,
        data=data,
        method=method,
        headers={"Content-Type": "application/json"} if data is not None else {},
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8", errors="replace"))


def check_health(timeout_sec: float) -> dict[str, Any]:
    port = find_free_port()
    url = f"http://127.0.0.1:{port}"
    env = os.environ.copy()
    env.setdefault("PYTHONUTF8", "1")
    env.setdefault("HBV_STUDIO_DISABLE_CONSOLE_MIRROR", "1")
    command = [
        sys.executable,
        str(GUI_ROOT / "launch.py"),
        "--host",
        "127.0.0.1",
        "--port",
        str(port),
        "--no-browser",
    ]
    proc = subprocess.Popen(
        command,
        cwd=str(REPO_ROOT),
        env=env,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )
    deadline = time.time() + timeout_sec
    try:
        while time.time() < deadline:
            if proc.poll() is not None:
                break
            try:
                payload = request_json(f"{url}/api/health", timeout=1.0)
                if payload.get("ok"):
                    ok(f"Health check passed: {url}/api/health")
                    try:
                        request_json(f"{url}/api/app/quit", timeout=2.0, method="POST")
                    except Exception:
                        pass
                    return {
                        "health_url": f"{url}/api/health",
                        "version": payload.get("version"),
                        "source_stale": payload.get("source_stale"),
                    }
            except (urllib.error.URLError, TimeoutError, json.JSONDecodeError):
                pass
            time.sleep(0.3)
        try:
            remaining, _ = proc.communicate(timeout=2)
        except subprocess.TimeoutExpired:
            remaining = ""
        output = remaining.splitlines() if remaining else []
        raise CheckError("Health check failed to reach /api/health.\n" + "\n".join(output[-40:]))
    finally:
        if proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                proc.kill()


def check_packaging_surfaces() -> dict[str, Any]:
    required = [
        GUI_ROOT / "build_portable_bundle.py",
        GUI_ROOT / "build_windows_installer.py",
        GUI_ROOT / "web" / "index.html",
        GUI_ROOT / "web" / "app.js",
        GUI_ROOT / "web" / "styles.css",
        GUI_ROOT / "services" / "dashboard.py",
        GUI_ROOT / "services" / "data_prep.py",
        GUI_ROOT / "services" / "filesystem.py",
        GUI_ROOT / "services" / "geo_overview.py",
        GUI_ROOT / "services" / "geo_suggestions.py",
        GUI_ROOT / "services" / "meteo_status.py",
        GUI_ROOT / "services" / "tasks.py",
        GUI_ROOT / "services" / "workspace_advice.py",
        GUI_ROOT / "services" / "workspace_catalog.py",
        GUI_ROOT / "services" / "workspace_completeness.py",
        GUI_ROOT / "services" / "workspace_layout.py",
    ]
    for path in required:
        if not path.exists():
            raise CheckError(f"Required packaging/source surface missing: {rel(path)}")
    spec = importlib.util.spec_from_file_location("hbvstudio_portable_build_check", GUI_ROOT / "build_portable_bundle.py")
    if spec is None or spec.loader is None:
        raise CheckError("Unable to inspect build_portable_bundle.py")
    portable = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(portable)
    if "services" not in getattr(portable, "STUDIO_DIRS", []):
        raise CheckError("Portable build script does not include HBV-Studio/services")
    installer_text = (GUI_ROOT / "build_windows_installer.py").read_text(encoding="utf-8-sig")
    if "portable.STUDIO_DIRS" not in installer_text:
        raise CheckError("Installer build script does not include portable.STUDIO_DIRS")
    project_parent = REPO_ROOT.parent
    demo_exe = project_parent / "HBVStudio_Demo" / "HBVStudio_Demo.exe"
    installer_output = project_parent / "hbvstudio_packaging" / "output"
    if demo_exe.exists():
        ok(f"Demo artifact present: {demo_exe}")
    else:
        warn(f"Demo artifact not found: {demo_exe}")
    installer_count = 0
    latest_installer = None
    if installer_output.exists():
        installers = sorted(installer_output.glob("*.exe"), key=lambda item: item.stat().st_mtime)
        installer_count = len(installers)
        latest_installer = str(installers[-1]) if installers else None
        if latest_installer:
            ok(f"Installer artifacts present: {installer_count}; latest: {latest_installer}")
        else:
            warn(f"Installer output has no exe files: {installer_output}")
    else:
        warn(f"Installer output directory not found: {installer_output}")
    return {
        "demo_exe_exists": demo_exe.exists(),
        "installer_count": installer_count,
        "latest_installer": latest_installer,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Run HBV-Studio baseline checks.")
    parser.add_argument("--update-api-snapshot", action="store_true", help="Write the current API route snapshot.")
    parser.add_argument("--skip-health", action="store_true", help="Skip launching the local service for /api/health.")
    parser.add_argument("--health-timeout", type=float, default=35.0)
    args = parser.parse_args()

    summary: dict[str, Any] = {}
    try:
        summary.update(check_python_syntax())
        summary.update(check_javascript_syntax())
        summary.update(check_or_update_api_snapshot(args.update_api_snapshot))
        summary.update(check_packaging_surfaces())
        if args.skip_health:
            warn("Health check skipped by --skip-health")
        else:
            summary.update(check_health(args.health_timeout))
    except CheckError as exc:
        fail(str(exc))
        return 1

    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
