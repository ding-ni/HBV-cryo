#!/usr/bin/env python
# -*- coding: utf-8 -*-
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable


@dataclass(frozen=True)
class ObservedInfoContext:
    inspect_observed_csv: Callable[..., dict[str, Any]]


def observed_info(
    csv_path: str,
    context: ObservedInfoContext,
    *,
    date_field: str | None = None,
    target_step_hours: float | None = None,
) -> dict[str, Any]:
    return context.inspect_observed_csv(
        csv_path,
        date_field=date_field,
        target_step_hours=target_step_hours,
    )
