#!/usr/bin/env python
# -*- coding: utf-8 -*-
from __future__ import annotations

import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable


@dataclass(frozen=True)
class TaskQueryContext:
    tasks: dict[str, Any]
    task_lock: threading.Lock
    snapshot_tasks: Callable[[], list[Any]]
    resolve_any_path: Callable[..., Path]


def has_running_tasks(context: TaskQueryContext) -> bool:
    with context.task_lock:
        return any(task.status == "running" for task in context.tasks.values())


def list_tasks(context: TaskQueryContext) -> list[dict[str, Any]]:
    items = [task.as_dict() for task in context.snapshot_tasks()]
    return sorted(items, key=lambda item: item["updated_at"], reverse=True)


def find_running_task(task_type: str, config_path_raw: str, context: TaskQueryContext) -> Any | None:
    try:
        cfg_path = context.resolve_any_path(config_path_raw, must_exist=False).resolve(strict=False)
    except Exception:
        return None
    with context.task_lock:
        for task in context.tasks.values():
            if task.task_type != task_type or task.status != "running":
                continue
            task_cfg = str(task.metadata.get("config_path", "")).strip()
            if not task_cfg:
                continue
            try:
                if Path(task_cfg).resolve(strict=False) == cfg_path:
                    return task
            except Exception:
                continue
    return None
