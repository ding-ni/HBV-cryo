from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any


def json_safe_value(value: Any) -> Any:
    if isinstance(value, dict):
        return {key: json_safe_value(item) for key, item in value.items()}
    if isinstance(value, list):
        return [json_safe_value(item) for item in value]
    if isinstance(value, tuple):
        return [json_safe_value(item) for item in value]
    if isinstance(value, float):
        return value if math.isfinite(value) else None
    return value


def json_dumps_safe(payload: Any, *, indent: int | None = None) -> str:
    return json.dumps(json_safe_value(payload), ensure_ascii=False, indent=indent, allow_nan=False)


def read_json_file(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def write_json_file(path: Path, data: dict[str, Any]) -> None:
    payload = dict(data)
    payload.pop("_config_path", None)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json_dumps_safe(payload, indent=2), encoding="utf-8")
