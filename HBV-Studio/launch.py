#!/usr/bin/env python
# -*- coding: utf-8 -*-
import argparse
import json
import os
import socket
import sys
import urllib.request
import webbrowser
from datetime import datetime
from pathlib import Path
from typing import Optional, TextIO


def env_flag(name: str, default: bool = False) -> bool:
    raw = str(os.environ.get(name, "")).strip().lower()
    if not raw:
        return default
    return raw in {"1", "true", "yes", "on"}


def installed_mode() -> bool:
    return env_flag("HBV_STUDIO_INSTALLED_MODE", default=False)


class TeeStream:
    def __init__(self, *streams: Optional[TextIO]) -> None:
        self._streams = [stream for stream in streams if stream is not None]
        self.encoding = next(
            (getattr(stream, "encoding", None) for stream in self._streams if getattr(stream, "encoding", None)),
            "utf-8",
        )

    def write(self, text: str) -> int:
        written = 0
        for stream in self._streams:
            try:
                stream.write(text)
                written = max(written, len(text))
            except Exception:
                continue
        return written

    def flush(self) -> None:
        for stream in self._streams:
            try:
                stream.flush()
            except Exception:
                continue

    def isatty(self) -> bool:
        for stream in self._streams:
            try:
                if stream.isatty():
                    return True
            except Exception:
                continue
        return False


def port_is_open(host: str, port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.settimeout(0.5)
        return sock.connect_ex((host, port)) == 0


def find_available_port(host: str, preferred_port: int) -> int:
    for port in range(int(preferred_port) + 1, int(preferred_port) + 40):
        if not port_is_open(host, port):
            return port
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind((host, 0))
        return int(sock.getsockname()[1])


def apply_path_override(env_name: str, value: Optional[str]) -> None:
    if value:
        os.environ[env_name] = value


def apply_temp_root(value: Optional[str]) -> None:
    if not value:
        return
    temp_root = Path(value).expanduser().resolve(strict=False)
    temp_root.mkdir(parents=True, exist_ok=True)
    os.environ["HBV_STUDIO_TEMP_ROOT"] = str(temp_root)
    os.environ["TEMP"] = str(temp_root)
    os.environ["TMP"] = str(temp_root)
    os.environ["TMPDIR"] = str(temp_root)


def browser_host(host: str) -> str:
    value = str(host or "").strip()
    return "127.0.0.1" if value in {"0.0.0.0", "::"} else value


def existing_hbv_service(url: str) -> dict:
    health_url = f"{url.rstrip('/')}/api/health"
    try:
        with urllib.request.urlopen(health_url, timeout=1.5) as response:
            if int(getattr(response, "status", 0) or 0) != 200:
                return {}
            data = json.loads(response.read().decode("utf-8", errors="replace"))
            return data if isinstance(data, dict) and data.get("ok") else {}
    except Exception:
        return {}


def latest_source_mtime() -> tuple[float, str]:
    root = Path(__file__).resolve().parent
    candidates = [
        root / "launch.py",
        root / "studio_service.py",
        root / "forecast_run.py",
        root / "profile_runner.py",
        root / "precipitation_strategy_runner.py",
        root / "web" / "app.js",
        root / "web" / "index.html",
        root / "web" / "styles.css",
        root / "web" / "js" / "forecastView.js",
        root / "web" / "js" / "eventMode.js",
        root / "web" / "js" / "parameterLibrary.js",
        root / "web" / "js" / "stationPrecip.js",
        root / "web" / "js" / "appDataFlow.js",
    ]
    latest = 0.0
    latest_file = ""
    for path in candidates:
        try:
            stamp = path.stat().st_mtime
        except OSError:
            continue
        if stamp > latest:
            latest = stamp
            latest_file = str(path)
    return latest, latest_file


def service_is_stale(health: dict, latest_mtime: float, *, tolerance_sec: float = 1.0) -> bool:
    try:
        started_at = float(health.get("server_started_at", 0) or 0)
    except (TypeError, ValueError):
        started_at = 0.0
    return bool(started_at and latest_mtime and latest_mtime > started_at + tolerance_sec)


def _interactive_console_stream(stream: Optional[TextIO]) -> Optional[TextIO]:
    if stream is None:
        return None
    if env_flag("HBV_STUDIO_DISABLE_CONSOLE_MIRROR", default=False):
        return None
    if installed_mode() and not env_flag("HBV_STUDIO_FORCE_CONSOLE_LOG", default=False):
        return None
    try:
        if stream.isatty():
            return stream
    except Exception:
        pass
    return stream if env_flag("HBV_STUDIO_FORCE_CONSOLE_LOG", default=False) else None


def configure_runtime_logging() -> Optional[Path]:
    log_dir_raw = str(os.environ.get("HBV_STUDIO_LOG_DIR", "")).strip()
    if not log_dir_raw:
        return None

    log_dir = Path(log_dir_raw).expanduser().resolve(strict=False)
    log_dir.mkdir(parents=True, exist_ok=True)
    log_file = log_dir / f"launch_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log"
    log_handle = open(log_file, "a", encoding="utf-8", buffering=1)

    console_stdout = _interactive_console_stream(getattr(sys, "__stdout__", None))
    console_stderr = _interactive_console_stream(getattr(sys, "__stderr__", console_stdout))
    sys.stdout = TeeStream(log_handle, console_stdout)
    sys.stderr = TeeStream(log_handle, console_stderr)

    print(f"[HBV-Studio] 日志写入：{log_file}", flush=True)
    return log_file


def _path_text(value: str) -> str:
    return str(Path(value).expanduser().resolve(strict=False)) if value else ""


def print_runtime_paths() -> None:
    path_items = {
        "user root": os.environ.get("HBV_STUDIO_EFFECTIVE_USER_ROOT", "") or os.environ.get("HBV_STUDIO_USER_ROOT", ""),
        "workspace dir": os.environ.get("HBV_STUDIO_WORKSPACE_DIR", ""),
        "runtime root": os.environ.get("HBV_STUDIO_RUNTIME_ROOT", ""),
        "log dir": os.environ.get("HBV_STUDIO_LOG_DIR", ""),
        "web root": os.environ.get("HBV_STUDIO_WEB_ROOT", ""),
        "temp root": os.environ.get("HBV_STUDIO_TEMP_ROOT", ""),
    }
    for label, raw in path_items.items():
        if raw:
            print(f"[HBV-Studio] {label}: {_path_text(raw)}", flush=True)


def print_result_roots() -> None:
    try:
        import studio_service

        runtime_roots = [str(path.resolve(strict=False)) for path in studio_service.discover_runtime_roots()]
        run_parents = []
        for root in studio_service.discover_runtime_roots():
            run_parents.extend(str(path.resolve(strict=False)) for path in studio_service.iter_run_parent_dirs(root))
    except Exception as exc:
        print(f"[HBV-Studio] result root discovery failed: {exc}", flush=True)
        return
    print(f"[HBV-Studio] discovered runtime roots: {runtime_roots or ['<none>']}", flush=True)
    print(f"[HBV-Studio] discovered run metadata roots: {run_parents or ['<none>']}", flush=True)


def main() -> None:
    parser = argparse.ArgumentParser(description="Launch the HBV-Studio GUI.")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--no-browser", action="store_true")
    parser.add_argument("--user-root", default="", help="Writable root for Studio user data, workspaces and logs.")
    parser.add_argument("--temp-root", default="", help="Writable temp directory used for TMP/TEMP/TMPDIR.")
    parser.add_argument("--workspace-dir", default="")
    parser.add_argument("--runtime-root", default="")
    parser.add_argument("--template-dir", default="")
    parser.add_argument("--web-root", default="")
    args = parser.parse_args()

    apply_path_override("HBV_STUDIO_USER_ROOT", args.user_root)
    apply_path_override("HBV_STUDIO_WORKSPACE_DIR", args.workspace_dir)
    apply_path_override("HBV_STUDIO_RUNTIME_ROOT", args.runtime_root)
    apply_path_override("HBV_STUDIO_TEMPLATE_DIR", args.template_dir)
    apply_path_override("HBV_STUDIO_WEB_ROOT", args.web_root)
    apply_temp_root(args.temp_root)

    from app_bootstrap import repair_runtime_jsons, seed_environment

    seed_environment()
    log_file = configure_runtime_logging()
    print_runtime_paths()
    print(f"[HBV-Studio] 启动模式：{'installed' if installed_mode() else 'portable'}", flush=True)
    if args.workspace_dir:
        print(f"[HBV-Studio] 工作区目录：{Path(args.workspace_dir).resolve(strict=False)}", flush=True)
    if args.runtime_root:
        print(f"[HBV-Studio] 运行目录根：{Path(args.runtime_root).resolve(strict=False)}", flush=True)

    repair_runtime_jsons()

    from server import run_server
    print_result_roots()

    url = f"http://{browser_host(args.host)}:{args.port}/"
    if port_is_open(args.host, args.port):
        health = existing_hbv_service(url)
        latest_mtime, latest_file = latest_source_mtime()
        if health and service_is_stale(health, latest_mtime):
            old_port = args.port
            args.port = find_available_port(args.host, old_port)
            url = f"http://{browser_host(args.host)}:{args.port}/"
            print(
                "[HBV-Studio] 检测到端口上的旧实例早于当前源码，"
                f"为避免继续使用旧代码，已改用端口 {args.port} 启动新实例。",
                flush=True,
            )
            if latest_file:
                print(f"[HBV-Studio] 最新源码文件：{latest_file}", flush=True)
    print(f"[HBV-Studio] 准备连接至 {url}", flush=True)
    if port_is_open(args.host, args.port):
        print(f"[HBV-Studio] 端口 {args.port} 已被占用，疑似已有旧实例。", flush=True)
        if existing_hbv_service(url):
            print("[HBV-Studio] 检测到已有可用实例，本次不再重复启动。", flush=True)
            if not args.no_browser:
                try:
                    webbrowser.open(url)
                    print(f"[HBV-Studio] 已转到现有实例：{url}", flush=True)
                except Exception as exc:
                    print(f"[HBV-Studio] 现有实例可用，但浏览器打开失败：{exc}", flush=True)
            return
        print(f"[HBV-Studio] 请先关闭旧实例，或改用其他端口重新启动：{url}", flush=True)
        if log_file is not None:
            print(f"[HBV-Studio] 详细日志：{log_file}", flush=True)
        raise SystemExit(1)

    if not args.no_browser:
        try:
            webbrowser.open(url)
            print(f"[HBV-Studio] 已发出浏览器打开请求：{url}", flush=True)
        except Exception as exc:
            print(f"[HBV-Studio] 浏览器打开失败，将继续保留服务：{exc}", flush=True)
    else:
        print("[HBV-Studio] 已按参数跳过自动打开浏览器。", flush=True)

    print(f"[HBV-Studio] 正在监听 {browser_host(args.host)}:{args.port}", flush=True)
    try:
        run_server(host=args.host, port=args.port)
    except OSError as exc:
        print(f"HBV-Studio 启动失败：{exc}", file=sys.stderr, flush=True)
        raise SystemExit(1) from exc


if __name__ == "__main__":
    main()
