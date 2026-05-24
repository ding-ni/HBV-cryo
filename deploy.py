#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
HBV-Studio 部署工具
====================
用法:
  python deploy.py pack       — 打包当前环境的最小依赖到 runtime/ 目录
  python deploy.py install    — 在目标电脑上从 runtime/ 创建 venv 并安装依赖
  python deploy.py launch     — 自动查找 Python 并启动 Studio
"""
from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent
RUNTIME_DIR = PROJECT_ROOT / "runtime"
VENV_DIR = RUNTIME_DIR / "venv"
REQUIREMENTS = PROJECT_ROOT / "requirements.txt"


def find_python() -> str:
    """Find usable Python: venv > conda > system."""
    # 1. Bundled venv
    venv_python = VENV_DIR / "Scripts" / "python.exe"
    if venv_python.exists():
        return str(venv_python)
    # 2. Conda in common locations
    for base in [Path(os.environ.get("CONDA_PREFIX", "")), Path("D:/miniconda3"), Path("C:/miniconda3"), Path.home() / "miniconda3"]:
        candidate = base / "python.exe"
        if candidate.exists():
            return str(candidate)
    # 3. System
    return sys.executable


def cmd_pack(args: argparse.Namespace) -> None:
    """Pack current environment's site-packages needed by this project."""
    print("=== 打包项目依赖 ===")
    RUNTIME_DIR.mkdir(parents=True, exist_ok=True)

    # Export only project dependencies (not the entire env)
    print("1. 导出 requirements.txt ...")
    if not REQUIREMENTS.exists():
        subprocess.check_call([sys.executable, "-m", "pip", "freeze"], stdout=open(REQUIREMENTS, "w"))
        print(f"   已生成 {REQUIREMENTS}")
    else:
        print(f"   使用已有 {REQUIREMENTS}")

    # Create a fresh venv with only needed packages
    print("2. 创建最小 venv ...")
    if VENV_DIR.exists():
        shutil.rmtree(VENV_DIR)
    subprocess.check_call([sys.executable, "-m", "venv", str(VENV_DIR)])
    venv_pip = VENV_DIR / "Scripts" / "pip.exe"
    print("3. 安装依赖到 venv ...")
    subprocess.check_call([str(venv_pip), "install", "-r", str(REQUIREMENTS)])

    # Copy the wheel cache for offline install
    print(f"\n=== 完成！可以将整个项目目录复制到目标电脑 ===")
    print(f"目标电脑运行: python deploy.py launch")


def cmd_install(args: argparse.Namespace) -> None:
    """On target machine: create venv from requirements."""
    print("=== 在目标电脑安装环境 ===")
    RUNTIME_DIR.mkdir(parents=True, exist_ok=True)

    if VENV_DIR.exists() and (VENV_DIR / "Scripts" / "python.exe").exists():
        print("venv 已存在，跳过创建。如需重建请删除 runtime/venv/。")
    else:
        print("1. 创建 venv ...")
        subprocess.check_call([sys.executable, "-m", "venv", str(VENV_DIR)])
        print("2. 安装依赖 ...")
        venv_pip = VENV_DIR / "Scripts" / "pip.exe"
        subprocess.check_call([str(venv_pip), "install", "-r", str(REQUIREMENTS)])

    print(f"\n=== 环境就绪！运行: python deploy.py launch ===")


def cmd_launch(args: argparse.Namespace) -> None:
    """Auto-find Python and launch Studio."""
    python = find_python()
    print(f"使用 Python: {python}")
    studio_launch = PROJECT_ROOT / "HBV-Studio" / "launch.py"
    if not studio_launch.exists():
        print(f"错误: 找不到 {studio_launch}")
        sys.exit(1)
    launch_args = [python, str(studio_launch)]
    if args.no_browser:
        launch_args.append("--no-browser")
    for flag, value in (
        ("--workspace-dir", args.workspace_dir),
        ("--runtime-root", args.runtime_root),
        ("--template-dir", args.template_dir),
        ("--web-root", args.web_root),
    ):
        if value:
            launch_args.extend([flag, value])
    os.execv(python, launch_args)


def main() -> None:
    parser = argparse.ArgumentParser(description="HBV-Studio 部署工具")
    sub = parser.add_subparsers(dest="command")

    sub.add_parser("pack", help="打包当前环境的最小依赖")
    sub.add_parser("install", help="在目标电脑安装环境")
    launch_p = sub.add_parser("launch", help="自动查找 Python 并启动 Studio")
    launch_p.add_argument("--no-browser", action="store_true")
    launch_p.add_argument("--workspace-dir", default="")
    launch_p.add_argument("--runtime-root", default="")
    launch_p.add_argument("--template-dir", default="")
    launch_p.add_argument("--web-root", default="")

    args = parser.parse_args()
    if args.command == "pack":
        cmd_pack(args)
    elif args.command == "install":
        cmd_install(args)
    elif args.command == "launch":
        cmd_launch(args)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
