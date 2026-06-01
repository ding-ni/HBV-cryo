#!/usr/bin/env python
# -*- coding: utf-8 -*-
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable


@dataclass(frozen=True)
class AppLifecycleContext:
    mark_activity: Callable[..., None]
    has_running_tasks: Callable[[], bool]


@dataclass(frozen=True)
class AppLifecycleResult:
    data: dict[str, object]
    status: int = 200
    error: str = ""
    shutdown_message: str = ""
    shutdown_delay_sec: float = 0.0

    @property
    def ok(self) -> bool:
        return not self.error


def app_window_unload(context: AppLifecycleContext) -> AppLifecycleResult:
    context.mark_activity(unload=True)
    return AppLifecycleResult(data={"accepted": True})


def app_quit(context: AppLifecycleContext) -> AppLifecycleResult:
    if context.has_running_tasks():
        return AppLifecycleResult(
            data={"accepted": False},
            status=409,
            error="当前仍有运行中的任务，请等待结束后再退出程序。",
        )
    return AppLifecycleResult(
        data={"accepted": True},
        shutdown_message="[HBV-Studio] 收到退出请求，正在关闭本地服务。",
        shutdown_delay_sec=0.2,
    )
